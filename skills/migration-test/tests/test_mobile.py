"""Mobile test-mode integration with simulated device and model I/O."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from harmony_adapter import ENGINE, execution_config, run_engine, device_lock
from harmony_contract import ObservationSink, validate_query, task_text
from runner_storage import scope
from test_harmony import query


class MobileContractTests(unittest.TestCase):
    def test_platform_bound_device_selection_and_no_silent_provider_fallback(self):
        raw = {'devices': {'android': 'A', 'ios': 'http://localhost:8100', 'harmony': 'H'},
               'models': {'execute_provider': 'general'}}
        for platform, serial in [('android', 'A'), ('ios', 'http://localhost:8100'), ('harmony', 'H')]:
            result = execution_config(raw, {'platform': platform})
            self.assertEqual((result['device'], result['platform'], result['task_type']), (serial, platform, 'test'))
        self.assertEqual(execution_config(raw, platform='android', device='override')['device'], 'override')
        with self.assertRaisesRegex(ValueError, 'frozen PATH'):
            execution_config(raw, {'platform': 'android'}, platform='harmony')
        for bad in ('web', 'snapshot'):
            with self.assertRaises(ValueError): execution_config(raw, platform=bad)
        with self.assertRaisesRegex(ValueError, 'WebDriverAgent HTTP'):
            execution_config(raw, platform='ios', device='bare-udid')
        for mode in ('snapshot', 'recording'):  # media tasks: accepted, and never with a test's assertions
            self.assertEqual(execution_config(raw, {'task_type': mode})['task_type'], mode)
            with self.assertRaisesRegex(ValueError, 'carry no assertions'): validate_query({**query(), 'task_type': mode})
        with self.assertRaises(ValueError): execution_config(raw, {'task_type': 'preview'})
        with self.assertRaisesRegex(ValueError, 'no provider fallback'):
            execution_config({**raw, 'models': {'execute_provider': 'hypium_mcp_agent'}}, platform='android')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'serial required'):
            execution_config({'device': 'harmony-only', 'models': raw['models']}, platform='android')

    def test_android_device_lock_ignores_harmony_connector_parameters(self):
        with device_lock('mobile-fixture', '127.0.0.1', 8710, 'android'):
            with self.assertRaises(ValueError):
                with device_lock('mobile-fixture', 'different-host', 7777, 'android'): pass

    def test_ios_device_lock_catches_aliases_and_second_forward_to_same_udid(self):
        with device_lock('http://localhost:8182', None, None, 'ios', udid='DESIGNATED-UDID'):
            for endpoint, udid in [('http://127.0.0.1:8182/', None), ('http://localhost:8183', 'designated-udid')]:
                with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, 'device busy'):
                    with device_lock(endpoint, None, None, 'ios', udid=udid): pass

    def test_assigned_runner_waits_for_same_device_and_others_can_run(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        started = Event()

        def second():
            started.set()
            with device_lock('shared-test-device', None, None, 'android', wait=True):
                return 'executed'

        with ThreadPoolExecutor(1) as pool:
            with device_lock('shared-test-device', None, None, 'android'):
                result = pool.submit(second)
                self.assertTrue(started.wait(1))
                with device_lock('independent-test-device', None, None, 'android'):
                    self.assertFalse(result.done())
            self.assertEqual(result.result(timeout=2), 'executed')

    def test_recordings_for_the_same_steps_are_separated_by_platform(self):
        self.assertNotEqual(task_text({**query(), 'platform': 'android'}), task_text({**query(), 'platform': 'harmony'}))

    def test_generated_android_adapter_uses_test_mode_and_preserves_unavailable_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / '.sdd-runs/mobile'
            adapter = root / 'runs/harmony/sandbox/adapter.json'
            source = Path(temp) / 'config.json'
            source.write_text(json.dumps({'models': {'execute_provider': 'general'}}))
            subprocess.run([sys.executable, str(ENGINE / 'sandbox.py'), 'adapter', '--root', str(root),
                            '--config', str(source), '--platform', 'android', '--output', str(adapter)],
                           check=True, capture_output=True)
            argv = json.loads(adapter.read_text())['argv']
            self.assertIn('test', argv); self.assertIn('android', argv)
            q = Path(temp) / 'query.json'; q.write_text(json.dumps({**query(), 'platform': 'android'}))
            result = root / 'runs/harmony/automation/missing-device/result.json'
            with patch.dict(os.environ, {}, clear=True):
                p = subprocess.run([*argv, '--query-file', str(q), '--result-file', str(result)], capture_output=True)
            self.assertEqual(p.returncode, 2, p.stderr)
            report = json.loads(result.read_text())
            self.assertEqual(report['quality'], 'yellow-blocked')
            self.assertIsNone(report['assertions'][0]['actual'])
            self.assertIn('serial required', report['root_cause']['summary'])
            self.assertEqual(report['root_cause']['reason_code'], 'mobile-test-environment')


@unittest.skipUnless(importlib.util.find_spec('uiautomator2') and importlib.util.find_spec('agents'), 'mobile dependencies required')
class MobileNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name).resolve() / '.sdd-runs/mobile/runs/harmony/automation/attempt'
        self.out.mkdir(parents=True)
        sys.path.insert(0, str(ENGINE))

    def test_android_driver_real_planner_verifier_report_wiring(self):
        from PIL import Image
        from AutoTest.layered_agent_cli.agent_registry import agent_registry
        from AutoTest.layered_agent_cli import mcp_tools
        from AutoTest.verify_agent.agent import VerifyAgent
        from AutoTest.devices.adb import apps
        driver = Mock(serial='android-fixture')
        driver.window_size.return_value = (100, 200)
        driver.screenshot.return_value = Image.new('RGB', (100, 200), 'green')
        driver.dump_hierarchy.return_value = '<hierarchy><node text="已登录"/></hierarchy>'
        driver.app_current.return_value = {'package': 'example.target'}
        q = {**query(), 'platform': 'android', 'task_type': 'test'}
        sink = ObservationSink(q, self.out)
        devices = []
        def planner(config, device, reporter):
            devices.append(device)
            agent_registry.set_executor_agent(SimpleNamespace(device=device))
            return SimpleNamespace(name='fixture')
        async def runner(*args, **kwargs):
            self.assertIn('显示完整结果', args[1])
            from test_step_execution import drive_fixture_steps
            def action(number):
                if number == 1: self.assertIn('successfully', mcp_tools._start_app('Fixture'))
                else: devices[0].type_text('测试输入')
            await drive_fixture_steps(sink, action)
            shot = devices[0].get_screenshot()
            with patch.object(VerifyAgent, '_verify', return_value=(True, 'observed', 'one_image_assert', [shot.screenshot_path])):
                self.assertTrue(agent_registry.get_verify_agent().verify('[ASSERT:A1]')[0])
            return SimpleNamespace(final_output='任务结果: 通过')
        config = {'platform': 'android', 'device': 'android-fixture',
                  'devices': {'android': 'configured-device-before-cli-override'},
                  'apps': {'android': {'name': 'Fixture', 'package': 'example.target'}},
                  'models': {'decision_models': [{'name': 'fixture', 'base_url': 'https://example.invalid', 'api_key': 'unused'}],
                             'execute_model_name': 'fixture', 'execute_provider': 'general',
                             'verify_model_name': 'fixture', 'verify_video_enable': False}}
        with scope(self.out), patch.dict(apps.APP_PACKAGES), patch('uiautomator2.connect', return_value=driver) as connect, \
             patch('AutoTest.layered_agent_cli.decision.create_planner_agent', side_effect=planner), \
             patch('AutoTest.layered_agent_cli.decision.Runner.run', side_effect=runner), \
             patch.object(mcp_tools.time, 'sleep'):
            result = asyncio.run(run_engine(q, config, self.out, sink))
        connect.assert_called_once_with('android-fixture')
        driver.app_start.assert_called_once_with('example.target', use_monkey=True)
        driver.send_keys.assert_called_once_with('测试输入')
        driver.press.assert_not_called()  # No implicit fixture reset.
        self.assertIn('通过', result)
        self.assertEqual(sink.report()['quality'], 'green-passed')
        self.assertTrue(list((self.out / 'reports').glob('*.html')))
        self.assertTrue(list((self.out / 'memory').glob('*.json')))
        self.assertTrue(sink.observations[0]['evidence_refs'])

    def test_native_factory_dispatch_and_test_only(self):
        spec = importlib.util.spec_from_file_location('mobile_native_test', ENGINE / 'main.py')
        native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
        args = SimpleNamespace(platform='harmony', task_type='test', device='H', ip='localhost', port=8710)
        with patch.object(native, 'HDCDevice') as hdc:
            native.create_device(args, None, SimpleNamespace(execute_provider='general'))
            hdc.assert_called_once_with('H', 'localhost', 8710, report_generator=None, config=unittest.mock.ANY)
        for platform, mode in [('web', 'test'), ('android', 'preview')]:
            args.platform, args.task_type = platform, mode
            with self.assertRaises(ValueError): native.create_device(args, None, SimpleNamespace(execute_provider='general'))
        args.platform, args.task_type = 'android', 'snapshot'
        with patch('AutoTest.devices.adb_device.AdbDevice') as adb:
            native.create_device(args, None, SimpleNamespace(execute_provider='general'))  # a media task on Android
            adb.assert_called_once()

    def test_android_screenshot_failure_cannot_create_fake_observation(self):
        from AutoTest.devices.adb import screenshot
        driver = Mock(); driver.screenshot.side_effect = OSError('disconnected')
        with self.assertRaisesRegex(RuntimeError, 'screenshot unavailable'): screenshot.get_screenshot(driver)

    def test_harmony_screenshot_failure_cannot_create_fake_observation(self):
        from AutoTest.devices.hdc import screenshot
        driver = Mock(); driver.UiTree.dump_page_info.side_effect = OSError('disconnected')
        with scope(self.out), self.assertRaisesRegex(RuntimeError, 'screenshot unavailable'):
            screenshot.get_screenshot(driver)

    @unittest.skipUnless(importlib.util.find_spec('wda'), 'optional iOS dependencies required')
    def test_physical_ios_receipt_checks_wda_device_and_current_installed_build(self):
        from AutoTest.devices.ios_device import IosDevice
        from contracts import file_ref
        from ios_evidence import check_device

        endpoint, baseline = 'http://127.0.0.1:8100', 'accepted-code'
        artifact = self.out / 'signed.ipa'
        artifact.write_bytes(b'fixture')
        receipt = self.out / 'deployment.json'
        receipt.write_text(json.dumps({'schema_version': 1, 'wda_url': endpoint, 'wda_uuid': 'observed-uuid', 'udid': 'PHONE',
                                       'bundle_id': 'com.example.app', 'build_version': '42',
                                       'code_baseline': baseline, 'artifact_ref': file_ref(artifact)}))
        binding = {'profile': 'physical', 'wda_url': endpoint, 'udid': 'PHONE', 'app_id': 'com.example.app',
                   'deployment_ref': file_ref(receipt)}
        client = Mock()
        client.http.get.return_value.value = {'uuid': 'observed-uuid', 'isSimulator': False, 'name': 'iPhone'}
        observed = self.out / 'device.json'
        with scope(self.out), patch('wda.Client', return_value=client), \
             patch('AutoTest.devices.ios.screenshot.physical_device', return_value={'identifier': 'CORE'}) as lookup, \
             patch('AutoTest.devices.ios.screenshot.physical_installation') as installation:
            installation.return_value = {'udid': 'PHONE', 'bundle_id': 'com.example.app', 'build_version': '41', 'core_device_id': 'CORE'}
            with self.assertRaisesRegex(ValueError, 'differs from deployment'):
                IosDevice(endpoint, udid='PHONE', observation=observed, execution=(binding, baseline))
            installation.return_value['build_version'] = '42'
            IosDevice(endpoint, udid='PHONE', observation=observed, execution=(binding, baseline))
            lookup.assert_called_with('PHONE')
            check_device(binding, baseline, json.loads(observed.read_text()))
            client.http.get.return_value.value['isSimulator'] = True
            with self.assertRaisesRegex(ValueError, 'frozen profile'):
                IosDevice(endpoint, udid='PHONE', execution=(binding, baseline))

    def test_ios_video_evidence_covers_the_assertion_on_the_same_device(self):
        from contracts import file_ref, Rejected
        from ios_evidence import check_video

        trace = {'steps': [{'before_device': {'captured_at': 15}, 'after_device': {'captured_at': 17}}]}
        assertion = {'after_step': 1}
        device = {'configured_udid': 'PHONE', 'wda_uuid': 'WDA', 'is_simulator': False, 'installed': {'core_device_id': 'CORE'}}
        video = self.out / 'segment.mp4'
        video.write_bytes(b'media fixture')
        capture = self.out / 'segment.ios-capture.json'
        facts = {'video_ref': file_ref(video), 'decoded_duration': 5, 'started_at': 14, 'ended_at': 19,
                 'udid': 'PHONE', 'wda_uuid': 'WDA', 'backend': 'avfoundation', 'core_device_id': 'CORE'}
        capture.write_text(json.dumps(facts))
        check_video([file_ref(capture)], trace, assertion, device, self.out)
        for change, reason in [({'ended_at': 16}, 'assertion interval'), ({'core_device_id': 'OTHER'}, 'source differs')]:
            capture.write_text(json.dumps({**facts, **change}))
            with self.assertRaisesRegex(Rejected, reason):
                check_video([file_ref(capture)], trace, assertion, device, self.out)

    @unittest.skipUnless(importlib.util.find_spec('wda'), 'optional iOS dependencies required')
    def test_ios_launch_capture_and_assertion_use_wda_points_and_managed_evidence(self):
        from io import BytesIO
        import base64
        from PIL import Image
        from AutoTest.layered_agent_cli.agent_registry import agent_registry
        from AutoTest.layered_agent_cli import mcp_tools
        from AutoTest.verify_agent.agent import VerifyAgent
        from AutoTest.devices.ios import apps
        from test_step_execution import drive_fixture_steps

        endpoint = 'http://192.0.2.40:8184'
        client = Mock()
        client.http.get.return_value.value = {'uuid': 'wda-fixture', 'model': 'iPhone', 'isSimulator': True}
        client._unsafe_window_size.return_value = (100, 200)
        client.screenshot.return_value = Image.new('RGB', (300, 600), 'green')
        client.source.return_value = '<XCUIElementTypeApplication name="Fixture"/>'
        client.app_current.return_value = {'bundleId': 'com.example.fixture'}
        q = {**query(), 'platform': 'ios', 'ios_device_profile': 'simulator',
             'ios_execution': {'profile': 'simulator', 'wda_url': endpoint, 'app_id': 'com.example.fixture'}}
        sink = ObservationSink(q, self.out)

        def planner(config, device, reporter):
            agent_registry.set_executor_agent(SimpleNamespace(device=device))
            return SimpleNamespace(name='fixture')

        async def runner(*args, **kwargs):
            device = agent_registry.get_executor_agent().device
            def action(number):
                if number == 1:
                    self.assertIn('successfully', mcp_tools._start_app('Fixture'))
                else:
                    device.tap(50, 100)
            await drive_fixture_steps(sink, action)
            shot = device.get_screenshot()
            self.assertEqual((shot.width, shot.height), (100, 200))
            with Image.open(BytesIO(base64.b64decode(shot.base64_data))) as image:
                self.assertEqual(image.size, (300, 600))
            with patch.object(VerifyAgent, '_verify', return_value=(True, 'observed', 'one_image_assert', [shot.screenshot_path])):
                self.assertTrue(agent_registry.get_verify_agent().verify('[ASSERT:A1]')[0])
            client.screenshot.side_effect = OSError('unavailable')
            with self.assertRaisesRegex(RuntimeError, 'screenshot or UI tree unavailable'):
                device.get_screenshot()
            return SimpleNamespace(final_output='test passed')

        config = {'platform': 'ios', 'device': endpoint, 'ios_bundle_id': 'com.example.fixture', 'ios_udid': 'SIM-UDID',
                  'apps': {'ios': {'name': 'Fixture', 'package': 'com.example.fixture'}},
                  'models': {'decision_models': [{'name': 'fixture', 'base_url': 'https://example.invalid', 'api_key': 'unused'}],
                             'execute_model_name': 'fixture', 'execute_provider': 'general', 'verify_model_name': 'fixture',
                             'verify_video_enable': True}}
        with scope(self.out), patch.dict(apps.APP_PACKAGES), patch('wda.Client', return_value=client), \
             patch('AutoTest.layered_agent_cli.decision.create_planner_agent', side_effect=planner), \
             patch('AutoTest.layered_agent_cli.decision.Runner.run', side_effect=runner), patch.object(mcp_tools.time, 'sleep'):
            asyncio.run(run_engine(q, config, self.out, sink))
        from ios_evidence import check_checkpoints
        check_checkpoints(q['ios_execution'], q, sink.step_trace, self.out)
        client.app_launch.assert_called_once_with('com.example.fixture')
        client.tap.assert_called_once_with(50, 100)
        client.home.assert_not_called()
        self.assertEqual(sink.report()['quality'], 'green-passed')
        proof = json.loads((self.out / 'ios-device.json').read_text())
        self.assertEqual((proof['endpoint'], proof['wda_uuid']), (endpoint, 'wda-fixture'))

    def test_android_recording_storage_checked_before_device_io(self):
        from AutoTest.devices.adb import screenshot
        driver = Mock(serial='fixture')
        with scope(self.out), self.assertRaises(ValueError):
            screenshot._stop_native_record(driver, {}, str(Path(self.temp.name) / 'outside.mp4'))
        driver.shell.assert_not_called()
        proc = Mock(); proc.poll.return_value = None
        with scope(self.out), patch.object(screenshot.subprocess, 'Popen', return_value=proc) as popen, \
             patch.object(screenshot.time, 'sleep'):
            state = screenshot._start_scrcpy_record(driver)
        self.assertTrue(Path(state['tmp_path']).is_relative_to(self.out / 'temp'))
        self.assertIn('--record=' + state['tmp_path'], popen.call_args.args[0])
        driver.shell.return_value = SimpleNamespace(output='/system/bin/screenrecord\n')
        self.assertTrue(screenshot._screenrecord_available(driver))

    def test_android_cached_actions_and_xpath_use_android_driver(self):
        from AutoTest.memory.tool_player import ToolPlayer
        device = Mock(platform='android'); device.get_display_size.return_value = (100, 200)
        player = ToolPlayer(device=device)
        self.assertTrue(player._call_mcp_tool('click', {'pos': [500, 250]}))
        device.tap.assert_called_once_with(50, 50)
        player._call_mcp_tool('input_text', {'text': 'fixture'})
        device.type_text.assert_called_once_with('fixture')
        device.driver.xpath.return_value.all.return_value = [SimpleNamespace(center=lambda: (1, 2)), SimpleNamespace(center=lambda: (40, 50))]
        component = player._find_best_component_by_xpath(device.driver, '//node', bounds='[30,40][50,60]')
        self.assertEqual(component.getBoundsCenter().X, 40)

    def test_video_skills_scale_android_coordinates(self):
        from AutoTest.devices.device_protocol import skill_driver
        device = Mock(platform='android'); device.get_display_size.return_value = (100, 200)
        driver = skill_driver(SimpleNamespace(device=device))
        driver.click((0.5, 0.25)); driver.slide((0.1, 0.2), (0.8, 0.9), slide_time=0.5)
        device.tap.assert_called_once_with(50, 50)
        device.swipe.assert_called_once_with(10, 40, 80, 180, duration_s=0.5)

    def test_android_generated_fixture_upload_preserves_existing_media(self):
        from mcp_tools import media_generator
        driver = Mock()
        with scope(self.out), patch.object(media_generator, 'get_driver', return_value=driver), \
             patch.object(media_generator, 'get_device', return_value=SimpleNamespace(platform='android')):
            self.assertIn('successfully', media_generator._generate_random_gradient_image_to_device())
        target = driver.adb_device.sync.push.call_args.args[1]
        self.assertTrue(target.startswith('/sdcard/Pictures/SDD/'))
        commands = [c.args[0] for c in driver.shell.call_args_list]
        self.assertEqual(commands[0], ['mkdir', '-p', '/sdcard/Pictures/SDD'])
        self.assertEqual(commands[1][-1], 'file://' + target)
        self.assertEqual(len(commands), 2)


if __name__ == '__main__': unittest.main()
