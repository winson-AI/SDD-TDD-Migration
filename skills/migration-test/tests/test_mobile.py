"""Android/Harmony test-mode integration with simulated device/model I/O, never live acceptance."""
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
        raw = {'devices': {'android': 'A', 'harmony': 'H'}, 'models': {'execute_provider': 'general'}}
        for platform, serial in [('android', 'A'), ('harmony', 'H')]:
            result = execution_config(raw, {'platform': platform})
            self.assertEqual((result['device'], result['platform'], result['task_type']), (serial, platform, 'test'))
        self.assertEqual(execution_config(raw, platform='android', device='override')['device'], 'override')
        with self.assertRaisesRegex(ValueError, 'frozen PATH'):
            execution_config(raw, {'platform': 'android'}, platform='harmony')
        for bad in ('ios', 'snapshot'):
            with self.assertRaises(ValueError): execution_config(raw, platform=bad)
        for mode in ('snapshot', 'recording'):
            with self.assertRaises(ValueError): execution_config(raw, {'task_type': mode})
            with self.assertRaises(ValueError): validate_query({**query(), 'task_type': mode})
        with self.assertRaisesRegex(ValueError, 'no provider fallback'):
            execution_config({**raw, 'models': {'execute_provider': 'hypium_mcp_agent'}}, platform='android')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'serial required'):
            execution_config({'device': 'harmony-only', 'models': raw['models']}, platform='android')

    def test_android_device_lock_ignores_harmony_connector_parameters(self):
        with device_lock('mobile-fixture', '127.0.0.1', 8710, 'android'):
            with self.assertRaises(ValueError):
                with device_lock('mobile-fixture', 'different-host', 7777, 'android'): pass

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
        for platform, mode in [('ios', 'test'), ('android', 'snapshot')]:
            args.platform, args.task_type = platform, mode
            with self.assertRaises(ValueError): native.create_device(args, None, SimpleNamespace(execute_provider='general'))

    def test_android_screenshot_failure_cannot_create_fake_observation(self):
        from AutoTest.devices.adb import screenshot
        driver = Mock(); driver.screenshot.side_effect = OSError('disconnected')
        with self.assertRaisesRegex(RuntimeError, 'screenshot unavailable'): screenshot.get_screenshot(driver)

    def test_harmony_screenshot_failure_cannot_create_fake_observation(self):
        from AutoTest.devices.hdc import screenshot
        driver = Mock(); driver.UiTree.dump_page_info.side_effect = OSError('disconnected')
        with scope(self.out), self.assertRaisesRegex(RuntimeError, 'screenshot unavailable'):
            screenshot.get_screenshot(driver)

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
