"""Bounded visual execution; fake subprocess/API, real evidence and native manifest validation."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, read_json
import lean_visual_worker as worker
import lean_semantic_process
from lean_tools import select_runtime_ui, validate_manifest


class VisualExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / '.sdd-runs/run-1'
        self.sandbox = self.root / 'runs/harmony/sandbox'
        self.env = self.write('runs/harmony/sandbox/environment/visual.json', {
            'visual_capture': {'backend': 'hdc', 'tool': 'hdc', 'device_id': 'device-1'},
            'visual_model': {'mode': 'external', 'enabled': True, 'name': 'vision-test',
                             'base_url': 'https://model.example/v1', 'api_key_env': 'SDD_TEST_VISION_KEY'}})
        self.shot = self.write('context/reference.png', self.image('PNG'))
        self.view = self.write('context/reference.xml', '<node text="Home" />')
        self.meta = self.write('context/meta.json', {'screenshot': self.shot.name})
        self.artifact = self.write('runs/build/build-1/app.hap', self.hap())
        self.path = {'path_id': 'V1', 'kind': 'visual', 'coverage': 'home:base:viewport',
                     'baseline_ref': file_ref(self.shot), 'visual_execution': {
                         'environment_ref': file_ref(self.env), 'app_id': 'com.example.app',
                         'target_match': [{'text': 'Home'}], 'actions': []}}
        self.module = {'module_id': 'M001', 'code_baseline': 'code-1',
                       'plan': {'paths': [self.path]}, 'build_artifacts': [file_ref(self.artifact)]}
        self.task = {'role': 'test-runner', 'assignment_id': 'T1', 'fencing_token': 'fence-1', 'test_scope': 'visual'}
        self.actor = {'role': 'test-runner', 'instance_id': 'test-1', 'device_lock': {
            'held': True, 'device_id': 'device-1', 'assignment_id': 'T1', 'fencing_token': 'fence-1'}}
        self.args = {'path_id': 'V1', 'artifact_ref': file_ref(self.artifact)}
        self.commands = []
        self.scrollable = False
        self.dynamic = False
        self.index = 0
        self.swipes = 0
        self.endpoint_after = None
        self.after_layout_change = False
        self.foreground = 'com.example.app'
        self.app_running = True
        self.dump_timeouts = 0
        self.corrupt_image = False
        self.capture_manifest('viewport')

    def hap(self, bundle='com.example.app', version=1, build_id=None):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('module.json', json.dumps({'app': {'bundleName': bundle, 'versionCode': version}}))
            if build_id:
                archive.writestr('resources/rawfile/sdd-build-id.txt', build_id)
        return data.getvalue()

    def image(self, fmt='JPEG', color=0):
        out = io.BytesIO()
        Image.new('RGB', (20, 20), (color * 20 % 255, 30, 50)).save(out, format=fmt)
        return out.getvalue()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes): path.write_bytes(value)
        else: path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
        return path

    def capture_manifest(self, coverage):
        observed = {'requested': coverage, 'achieved': 'viewport' if coverage == 'viewport' else 'scroll-complete',
                    'capture_count': 1, 'termination': 'viewport' if coverage == 'viewport' else 'not-scrollable'}
        snapshot = {'screenshot': str(self.shot), 'view_tree': str(self.view), 'meta': str(self.meta),
                    'view_signature': 'reference', 'device_backend': {'name': 'adb', 'version': 'cli', 'device': 'source'},
                    'coverage': observed, 'captures': [{'index': 0, 'screenshot': str(self.shot),
                        'view_tree': str(self.view), 'view_signature': 'reference'}]}
        self.manifest = self.write('context/manifest.json', {'schema_version': 2, 'capture_id': 'source', 'targets': [{
            'mode': 'targeted', 'phase': 'android-reference', 'platform': 'android', 'page_id': 'home', 'state_id': 'base',
            'observed_variant': 'base', 'round': None, 'status': 'COMPLETE', 'coverage': observed, 'snapshot': snapshot}]})
        self.bind_visual_evidence()

    def bind_visual_evidence(self, baselines=None):
        evidence = {'visual_mode': 'runtime', 'coverage': self.path['coverage'],
                    'capture_manifest_ref': file_ref(self.manifest), 'baseline_refs': baselines or [file_ref(self.shot)]}
        analysis = self.write('context/dimensions.json', {'dimensions': [{'dimension': 'UI', 'status': 'applicable',
            'items': [{'semantic_model': {'ui_evidence': evidence}}]}]})
        self.module['plan']['dimension_analysis_ref'] = file_ref(analysis)

    def add_frozen_reference_viewport(self):
        second = self.write('context/reference-second.png', self.image('PNG', 3))
        manifest = read_json(self.manifest)
        record = manifest['targets'][0]
        record['snapshot']['captures'].append({'index': 1, 'screenshot': str(second),
            'view_tree': str(self.view), 'view_signature': 'second'})
        record['coverage']['capture_count'] = record['snapshot']['coverage']['capture_count'] = 2
        self.write('context/manifest.json', manifest)
        self.bind_visual_evidence([file_ref(self.shot), file_ref(second)])
        return second

    def fake_subprocess(self, argv, **kwargs):
        self.commands.append(argv)
        self.assertFalse(kwargs.get('shell', False))
        self.assertEqual(kwargs['cwd'], self.current_out)
        self.assertTrue(Path(kwargs['env']['TMPDIR']).is_relative_to(self.current_out))
        command = argv[3:]
        stdout = ''
        if command == ['-v']:
            stdout = 'Ver: 3.1.0 test-device-tool'
        elif command == ['shell', 'param', 'get', 'const.product.model']:
            stdout = 'TestPhone'
        elif command == ['shell', 'param', 'get', 'const.product.software.version']:
            stdout = 'TestOS.21'
        elif command[:3] == ['shell', 'bm', 'dump']:
            stdout = '{"bundleName":"com.example.app","versionCode":1}'
        elif command[:3] == ['shell', 'aa', 'dump']:
            if self.dump_timeouts:
                self.dump_timeouts -= 1
                raise subprocess.TimeoutExpired(argv, 30)
            rows = [f'app name [{self.foreground}] foreground'] if self.foreground else []
            if self.app_running and self.foreground != 'com.example.app':
                rows.insert(0, 'app name [com.example.app] background')
            stdout = '\n'.join(rows)
        elif command == ['shell', "hidumper -s WindowManagerService -a '-a'"]:
            stdout = 'App 0 42 7 1 1 0 10 0 [ 0 0 20 20 ] [ 0 0 ] [ 1 1 0.5 0.5 ]\nFocus window: 7'
        elif command[:3] == ['shell', 'uitest', 'dumpLayout']:
            stdout = 'saved to: /data/local/tmp/layout.json'
        elif command[:2] == ['file', 'recv']:
            dest = Path(command[-1]); dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.suffix == '.json':
                children = []
                if probe := getattr(self, 'probe', None):
                    children.append({'attributes': {'type': 'Text', 'key': 'sdd-probe', 'text': json.dumps(probe),
                                                    'bounds': '[0,0][20,20]'}})
                if self.endpoint_after is not None and self.swipes >= self.endpoint_after:
                    children.append({'attributes': {'type': 'Text', 'text': 'End', 'bounds': '[0,180][100,200]'}})
                text = 'Login' if self.after_layout_change and '-after' in dest.name else 'Home'
                dest.write_text(json.dumps({'attributes': {'type': 'Column', 'text': text, 'key': 'list',
                    'bundleName': 'com.example.app', 'bounds': getattr(self, 'window_bounds', '[0,0][100,200]'), 'scrollable': self.scrollable},
                    'children': children}))
            else:
                self.index += 1
                dest.write_bytes(b'\xff\xd8\xffbroken' if self.corrupt_image else
                                 self.image(fmt='PNG' if dest.suffix == '.png' else 'JPEG', color=self.index if self.dynamic else 0))
        elif command[:4] == ['shell', 'uitest', 'uiInput', 'swipe']:
            self.swipes += 1
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    def run_tool(self, operation, **extra):
        self.current_out = self.sandbox / 'test-1' / f'attempt-{len(list(self.sandbox.glob("test-1/*")))}'
        self.current_out.mkdir(parents=True)
        with patch.object(worker.subprocess, 'run', side_effect=self.fake_subprocess):
            result = worker.run(operation, {**self.args, **extra}, root=self.root, out=self.current_out,
                                module=self.module, task=self.task, actor=self.actor, config={})
        ref = worker.save(self.current_out / 'result.json', result)
        return result, ref

    def installed(self):
        return self.run_tool('visual-install')[1]

    def capture(self, **extra):
        return self.run_tool('visual-capture', install_ref=self.installed(), round=1,
                             reference_manifest_ref=file_ref(self.manifest), **extra)

    def test_install_and_capture_real_contract_with_fixed_commands(self):
        result, _ = self.capture()
        self.assertEqual(result['status'], 'CAPTURED')
        data = read_json(result['manifest_ref']['path'])
        target = data['targets'][-1]
        validate_manifest.validate_snapshot(target['snapshot'], 'viewport', 'candidate')
        self.assertEqual(target['observed_variant'], 'base')
        self.assertEqual(target['snapshot']['device_backend']['device'], 'device-1')
        self.assertTrue(select_runtime_ui.select(Path(result['manifest_ref']['path']), ['home:base:viewport']))
        self.assertTrue(any(command[3:6] == ['install', '-r', str(self.artifact)] for command in self.commands))
        self.assertTrue(any(command[3:5] == ['shell', 'rm'] for command in self.commands))
        self.assertNotIn('quality', result)

    def test_harmony_png_and_raw_layout_bracket_the_selected_resource(self):
        import lean_visual_adapter
        import test_validation
        import visual_evidence

        self.path.pop('baseline_ref')
        self.path.update(platform='harmony', image_check_ids=['title'], node_ids=['node:title'],
                         device_configuration={'night': True, 'vp_scale': 2.0}, expected_assertions=[{'assertion_id': 'V', 'expected': True}],
                         harmony_resource_probe={'node_id': 'sdd-probe', 'selections': {
                             'title': {'resource_id': 'title', 'target_qualifier': 'dark'}}})
        check = {'id': 'title', 'kind': 'text', 'source_resource': '@string/title', 'qualifier': 'night',
                 'node_id': 'node:title', 'target': {'selector': {'resource-id': 'list'}}, 'expect': {'text': 'Home'}}
        analysis = self.write('context/qualified.json', {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [{'semantic_model': {'ui_evidence': {'coverage': self.path['coverage']},
                                                             'image_checks': [check]}}]}]})
        self.module['plan']['dimension_analysis_ref'] = file_ref(analysis)
        self.probe = {'schema_version': 1, 'configuration': {'night': True, 'vp_scale': 2.0, 'window_width_vp': 412,
                                                            'locale': 'zh_Hans_CN'}, 'resources': {'title': 'Home'}}
        installed = self.installed()
        for label, value, quality in [('match', 'Home', 'green-passed'), ('wrong selection', 'Fallback', 'red-bug')]:
            with self.subTest(label=label):
                self.probe['resources']['title'] = value
                capture, _ = self.run_tool('visual-capture', install_ref=installed, round=1)
                self.assertEqual(capture['status'], 'CAPTURED')
                self.assertEqual(capture['device_configuration']['locale'], 'b+zh+Hans+CN')
                out = self.current_out
                measured = worker.parity({'path_id': 'V1', 'manifest_ref': capture['manifest_ref'], 'round': 1},
                                         out, self.module, self.task, 'run-1')
                query = {**self.path, 'run_id': 'run-1', 'module_id': 'M001', 'freeze_id': 'F1', 'code_baseline': 'code-1',
                         'frozen_image_checks': [check], 'run_root': str(self.root), 'execution_assignment': self.task}
                accepted = lean_visual_adapter.report(query, None, self.base, [], measured['report_ref'])
                self.assertEqual(accepted['quality'], quality)
                if quality == 'green-passed':
                    test_validation.visual_result(self.module, self.path, accepted, accepted,
                                                  run_root=str(self.root), assignment=self.task)
                proof = accepted['visual_alignment']['image_parity']
                self.assertEqual(proof['checks'][0]['resource_selection']['observed'], value)
                pair = proof['capture_evidence']['harmony_probe'][0]
                Path(pair['after_ref']['path']).write_text('{}')
                with self.assertRaises(Rejected):
                    visual_evidence.validate_image_parity(measured['report_ref'], checks=[check], path=self.path,
                        code_baseline='code-1', run_root=str(self.root), assignment=self.task)
        self.probe['configuration']['night'] = False
        result, _ = self.run_tool('visual-capture', install_ref=installed, round=1)
        self.assertEqual(result['root_cause']['kind'], 'device-configuration-mismatch')

    def test_physical_capture_binds_packaged_build_device_window_and_actual_qualifier(self):
        import lean_visual_adapter
        import test_validation
        import visual_evidence

        marker = 'a' * 64
        self.artifact.write_bytes(self.hap(build_id=marker))
        self.module['build_artifacts'] = [file_ref(self.artifact)]
        self.args['artifact_ref'] = file_ref(self.artifact)
        self.path.pop('baseline_ref')
        self.path.update(platform='harmony', harmony_device_profile='physical-phone-a', image_check_ids=['title'],
                         node_ids=['node:title'], device_configuration={'night': True, 'harmony_api_level': 21},
                         expected_assertions=[{'assertion_id': 'V', 'expected': True}],
                         harmony_resource_probe={'node_id': 'sdd-probe', 'configuration_scope': 'system', 'selections': {
                             'title': {'resource_id': 'title', 'target_qualifier': 'dark', 'target_branch': 'xml-dark-title'}}})
        config = read_json(self.env)
        config['visual_capture'].update(harmony_device_profile='physical-phone-a', model='TestPhone')
        self.write('runs/harmony/sandbox/environment/visual.json', config)
        self.path['visual_execution']['environment_ref'] = file_ref(self.env)
        check = {'id': 'title', 'kind': 'text', 'source_resource': '@string/title', 'qualifier': 'night',
                 'node_id': 'node:title', 'target': {'selector': {'resource-id': 'list'}}, 'expect': {'text': 'Home'}}
        self.module['plan']['dimension_analysis_ref'] = file_ref(self.write('context/qualified.json', {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [{'semantic_model': {
                'ui_evidence': {'coverage': self.path['coverage']}, 'image_checks': [check]}}]}]}))
        self.window_bounds = '[0,2][20,20]'
        self.probe = {'schema_version': 3, 'build_id': marker, 'configuration': {
            'night': True, 'vp_scale': 1, 'window_width_vp': 20, 'harmony_api_level': 21},
            'system_configuration': {'night': True},
            'viewport': {'display_id': 0, 'window_id': 7, 'window_bounds_px': [0, 0, 20, 20], 'orientation': 'portrait'},
            'resources': {'title': {'value': 'Home', 'resolved_qualifier': 'dark', 'identity': 'xml-dark-title'}}}
        test_validation.validate_visual_profile(self.path)
        install_ref = self.installed()
        query = {**self.path, 'run_id': 'run-1', 'module_id': 'M001', 'freeze_id': 'F1', 'code_baseline': 'code-1',
                 'frozen_image_checks': [check], 'run_root': str(self.root), 'execution_assignment': self.task}
        for qualifier, identity, quality in [('dark', 'xml-dark-title', 'green-passed'),
                                             ('base', 'xml-dark-title', 'red-bug'),
                                             ('dark', 'xml-light-title', 'red-bug'),
                                             ('dark', None, 'yellow-blocked')]:
            self.probe['resources']['title'].update(resolved_qualifier=qualifier, identity=identity)
            capture, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1)
            self.assertEqual(capture['status'], 'CAPTURED', capture)
            parity = worker.parity({'path_id': 'V1', 'manifest_ref': capture['manifest_ref'], 'round': 1},
                                   self.current_out, self.module, self.task, 'run-1')
            report = lean_visual_adapter.report(query, None, self.base, [], parity['report_ref'])
            self.assertEqual(report['quality'], quality)
            test_validation.visual_result(self.module, self.path, report, report, run_root=str(self.root), assignment=self.task)
            evidence = report['visual_alignment']['image_parity']['capture_evidence']
            self.assertEqual(evidence['physical_device'], {'model': 'TestPhone', 'os_build': 'TestOS.21'})
            self.assertEqual(evidence['viewport']['window_id'], 7)
            self.assertEqual(evidence['viewport']['content_bounds_px'], [0, 2, 20, 20])
            self.assertEqual(evidence['build_id'], marker)
            self.assertEqual(evidence['configuration_scope'], 'system')
            self.assertEqual(evidence['system_configuration'], {'night': True})
            self.assertTrue(any(cmd[3:] == ['shell', 'uitest', 'dumpLayout', '-d', '0', '-w', '7'] for cmd in self.commands))
            import harmony_resource_probe as probe
            log = read_json(evidence['command_log_ref']['path'])
            screen = next(i for i, row in enumerate(log) if row['argv'][3:6] == ['shell', 'uitest', 'screenCap'])
            log.insert(0, log.pop(screen))
            with self.assertRaisesRegex(Rejected, 'must bracket'):
                probe.capture_proof(evidence['harmony_probe'], evidence['observations'], log, 'device-1',
                    'com.example.app', 'sdd-probe', str(self.root), physical_build=marker)
            other = self.write('runs/harmony/sandbox/environment/other.json', {
                'visual_capture': {**config['visual_capture'], 'device_id': 'another-device'}})
            with self.assertRaisesRegex(Rejected, 'effective managed environment'):
                visual_evidence.validate_image_parity(parity['report_ref'], checks=[check], path=self.path,
                    code_baseline='code-1', run_root=str(self.root), assignment=self.task, environment=file_ref(other))
        self.probe['system_configuration']['night'] = False
        capture, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1)
        self.assertEqual(capture['root_cause']['kind'], 'device-configuration-mismatch')
        self.probe['system_configuration']['night'] = True
        self.probe['viewport']['window_id'] = 8
        capture, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1)
        self.assertIn('WindowManager', str(capture['root_cause']))
        self.probe['viewport']['window_id'] = 7
        self.probe['build_id'] = 'b' * 64  # same bundle/version, different running build
        capture, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1)
        self.assertEqual(capture['root_cause']['kind'], 'capture-environment')
        self.assertIn('build marker', str(capture['root_cause']))

        import harmony_resource_probe as probe
        emulator_readback = [{'argv': ['hdc', '-t', 'device-1', *cmd], 'exit_code': 0, 'stdout': value}
                             for cmd, value in [(probe.MODEL, 'emulator'), (probe.OS_BUILD, 'emulator 6.0')]]
        with self.assertRaisesRegex(Rejected, 'HDC reports an emulator'):
            probe.device_identity(emulator_readback, 'device-1')

    def test_packaged_image_binding_requires_both_selected_member_and_bytes(self):
        import hashlib
        import harmony_resource_probe as probe

        entry = 'resources/dark-xldpi/media/picture.png'
        pixels = self.image('PNG')
        expected = hashlib.sha256(pixels).hexdigest()
        with zipfile.ZipFile(self.artifact, 'a') as archive:
            archive.writestr(entry, pixels)
            archive.writestr('resources/base/media/picture.png', pixels)
        mapping = {'resource_id': 'picture', 'target_qualifier': 'dark-xldpi', 'target_entry': entry, 'target_sha256': expected}
        check = {'id': 'picture'}
        for identity, status in [(entry, 'match'), ('resources/base/media/picture.png', 'mismatch'), (None, 'missing')]:
            row = {'status': 'MATCH'}
            probe.with_selection(row, check, {'selections': {'picture': mapping}},
                {'picture': {'value': expected, 'resolved_qualifier': 'dark-xldpi', 'identity': identity}}, artifact=self.artifact)
            self.assertEqual(row['resource_selection']['status'], status)
            self.assertEqual(row['resource_selection']['packaged_sha256'], expected)

    def test_a_path_with_image_checks_only_captures_the_target_alone(self):
        self.path.pop('baseline_ref')
        self.path['image_check_ids'] = ['back-arrow']
        result, _ = self.run_tool('visual-capture', install_ref=self.installed(), round=1)  # no legacy manifest is named
        self.assertEqual(result['status'], 'CAPTURED')
        manifest = read_json(result['manifest_ref']['path'])
        self.assertEqual([(r['phase'], r['platform'], r['round']) for r in manifest['targets']], [('harmony-candidate', 'harmony', 1)])
        validate_manifest.validate_snapshot(manifest['targets'][0]['snapshot'], 'viewport', 'candidate')
        self.assertTrue(read_json(result['capture_execution_ref']['path'])['observations'])
        self.path.pop('image_check_ids')
        with self.assertRaisesRegex(Rejected, 'must carry image checks'):
            self.run_tool('visual-capture', install_ref=self.installed(), round=1)

    def test_semantic_inspection_compares_a_baseline_so_an_image_check_path_has_none_to_inspect(self):
        self.path.pop('baseline_ref')
        self.path['image_check_ids'] = ['back-arrow']
        with self.assertRaisesRegex(Rejected, 'carries image checks only'):
            self.run_tool('semantic-inspect', reference_ref=file_ref(self.shot), candidate_ref=file_ref(self.shot),
                          score_ref=file_ref(self.shot))

    def test_install_allows_automation_path_without_visual_actions(self):
        self.path['kind'] = self.task['test_scope'] = 'automation'
        result, _ = self.run_tool('visual-install')
        self.assertEqual(result['status'], 'INSTALLED')
        with self.assertRaisesRegex(Rejected, 'visual PATH'):
            self.run_tool('visual-capture')

    def test_no_tool_or_timeout_returns_local_yellow_candidate(self):
        for error in (FileNotFoundError('no hdc'), subprocess.TimeoutExpired('hdc', 30)):
            out = self.sandbox / 'test-1' / type(error).__name__; out.mkdir(parents=True)
            with patch.object(worker.subprocess, 'run', side_effect=error):
                result = worker.run('visual-install', self.args, root=self.root, out=out,
                                    module=self.module, task=self.task, actor=self.actor, config={})
            self.assertEqual(result['quality_candidate'], 'yellow-blocked')
            self.assertEqual(result['root_cause']['kind'], 'environment-unavailable')
            self.assertFalse(result['executed'])

    def test_current_device_lock_and_build_owner_required_before_side_effect(self):
        self.actor['device_lock']['held'] = False
        with self.assertRaisesRegex(Rejected, 'exclusive device lock'):
            self.run_tool('visual-install')
        self.actor['device_lock']['held'] = True
        self.module['path_build_artifacts'] = {'V1': []}
        with self.assertRaisesRegex(Rejected, 'current accepted build'):
            self.run_tool('visual-install')
        self.assertEqual(self.commands, [])

    def test_audit_path_selection_applies_even_with_matching_hap(self):
        self.task.update(role='auditor', path_ids=['other'])
        self.actor['role'] = 'auditor'
        with self.assertRaisesRegex(Rejected, 'audit assignment selection'):
            self.run_tool('visual-install')
        self.assertEqual(self.commands, [])

    def test_missing_config_returns_yellow_changed_or_external_config_rejected(self):
        old = self.path.pop('visual_execution')
        result, _ = self.run_tool('visual-install')
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')
        self.path['visual_execution'] = old
        self.env.write_text('{}')
        with self.assertRaisesRegex(Rejected, 'hash'):
            self.run_tool('visual-install')
        other = self.write('staging/unsafe-config.json', {})
        old['environment_ref'] = file_ref(other)
        with self.assertRaises(Rejected):
            self.run_tool('visual-install')

    def test_unmatched_target_is_not_complete(self):
        self.path['visual_execution']['target_match'] = [{'text': 'Not Home'}]
        result, _ = self.capture()
        self.assertEqual(result['root_cause']['kind'], 'target-precondition')
        self.assertNotIn('manifest_ref', result)

    def test_frozen_navigation_has_no_shell_escape_or_request_override(self):
        self.path['visual_execution']['actions'] = [{'action': 'shell', 'command': 'touch /tmp/escaped'}]
        with self.assertRaisesRegex(Rejected, 'unsupported navigation'):
            self.capture()
        self.assertFalse(any('touch' in part for command in self.commands for part in command))

    def test_capture_rejects_stale_install_assignment(self):
        install = self.installed()
        self.task['assignment_id'] = self.actor['device_lock']['assignment_id'] = 'T2'
        with self.assertRaisesRegex(Rejected, 'installation receipt'):
            self.run_tool('visual-capture', install_ref=install, round=1,
                          reference_manifest_ref=file_ref(self.manifest))

    def test_wrong_or_unreadable_hap_identity_never_installs_existing_old_app(self):
        for payload in (self.hap(bundle='com.other.app'), b'not-a-hap-archive'):
            self.artifact.write_bytes(payload)
            self.args['artifact_ref'] = file_ref(self.artifact)
            self.module['build_artifacts'] = [self.args['artifact_ref']]
            self.commands.clear()
            result, _ = self.run_tool('visual-install')
            self.assertEqual(result['root_cause']['kind'], 'artifact-identity-unverified')
            self.assertFalse(any(command[3] == 'install' for command in self.commands))

    def test_installed_version_must_match_hap_identity(self):
        self.artifact.write_bytes(self.hap(version=2))
        self.args['artifact_ref'] = file_ref(self.artifact)
        self.module['build_artifacts'] = [self.args['artifact_ref']]
        result, _ = self.run_tool('visual-install')
        self.assertEqual(result['root_cause']['kind'], 'artifact-identity-unverified')

    def test_corrupt_jpeg_is_retained_but_not_complete(self):
        self.corrupt_image = True
        result, _ = self.capture()
        self.assertEqual(result['root_cause']['kind'], 'capture-incomplete')
        self.assertTrue((self.current_out / 'screenshot-candidate-0.jpeg').exists())

    def test_the_harmony_candidate_is_observed_like_every_other_screen(self):
        result, _ = self.capture()
        row = read_json(result['manifest_ref']['path'])['targets'][-1]
        meta = read_json(row['snapshot']['meta'])
        self.assertEqual((row['phase'], row['platform'], row['snapshot']['device_backend']['name'], meta['platform'], meta['image_mime'], meta['foreground']),
                         ('harmony-candidate', 'harmony', 'hdc', 'harmony', 'image/jpeg', 'com.example.app/' + meta['page_name']))
        self.assertTrue((self.current_out / 'view-candidate-0.xml').exists() and Path(row['snapshot']['screenshot']).name == 'screenshot-candidate-0.jpeg')
        self.assertEqual(sorted(k for k in meta if k in ('install_ref', 'artifact_ref', 'code_baseline', 'assignment_id', 'fencing_token')),
                         ['artifact_ref', 'assignment_id', 'code_baseline', 'fencing_token', 'install_ref'])

    def test_same_bundle_different_page_during_screenshot_is_incomplete(self):
        self.after_layout_change = True
        result, _ = self.capture()
        self.assertEqual(result['root_cause']['kind'], 'capture-incomplete')
        self.assertTrue(Path(result['before_view_ref']['path']).exists())
        self.assertTrue(Path(result['after_view_ref']['path']).exists())

    def test_wrong_foreground_app_is_not_complete(self):
        self.foreground = 'com.other.app'
        result, _ = self.capture()
        self.assertEqual(result['root_cause']['kind'], 'target-precondition')
        self.assertFalse(any('snapshot_display' in command for command in self.commands))

    def test_app_that_exited_after_launch_is_a_code_defect_not_an_environment_gap(self):
        self.foreground, self.app_running = 'com.ohos.launcher', False
        result, _ = self.capture()
        self.assertEqual((result['status'], result['quality_candidate'], result['root_cause']['kind']),
                         ('FAILED', 'red-bug', 'app-runtime-failure'))
        self.assertTrue(result['executed'])

    def test_read_only_device_query_retries_one_transient_timeout(self):
        self.dump_timeouts = 1
        result, _ = self.capture()
        self.assertEqual(result['status'], 'CAPTURED')
        install = self.installed()
        self.dump_timeouts = 2
        result, _ = self.run_tool('visual-capture', install_ref=install, round=2, reference_manifest_ref=file_ref(self.manifest))
        self.assertEqual(result['root_cause']['kind'], 'environment-unavailable')

    def test_scroll_repeat_or_limit_never_claims_full_coverage(self):
        self.path['coverage'] = 'home:base:scroll'
        self.path['visual_execution']['max_scrolls'] = 1
        self.path['visual_execution'].update(scroll_region={'resource-id': 'list'}, scroll_end_match=[{'text': 'End'}])
        self.capture_manifest('scroll')
        self.scrollable = True
        result, _ = self.capture()
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')
        row = read_json(result['manifest_ref']['path'])['targets'][-1]
        self.assertEqual(row['coverage']['termination'], 'observed-repeat-not-proof-of-end')
        self.dynamic = True
        result, _ = self.capture()
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')
        row = read_json(result['manifest_ref']['path'])['targets'][-1]
        self.assertEqual(row['status'], 'BLOCKED')
        self.assertEqual(row['coverage']['achieved'], 'scroll-partial')

    def test_scroll_source_backed_region_and_observed_endpoint_complete_with_ordered_viewports(self):
        self.path['coverage'] = 'home:base:scroll'
        self.path['visual_execution'].update(max_scrolls=3, scroll_region={'resource-id': 'list'},
                                             scroll_end_match=[{'text': 'End'}])
        self.capture_manifest('scroll')
        self.scrollable = self.dynamic = True
        self.endpoint_after = 2
        result, _ = self.capture()
        self.assertEqual(result['status'], 'CAPTURED')
        row = read_json(result['manifest_ref']['path'])['targets'][-1]
        self.assertEqual(row['coverage']['termination'], 'frozen-scroll-end-observed')
        self.assertEqual(row['coverage']['achieved'], 'scroll-complete')
        self.assertEqual([c['index'] for c in row['snapshot']['captures']], [0, 1, 2])
        validate_manifest.validate_snapshot(row['snapshot'], 'scroll', 'candidate')

    def test_missing_scroll_contract_does_not_assume_no_scroll_is_complete(self):
        self.path['coverage'] = 'home:base:scroll'
        self.capture_manifest('scroll')
        result, _ = self.capture()
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')
        row = read_json(result['manifest_ref']['path'])['targets'][-1]
        self.assertEqual(row['coverage']['achieved'], 'scroll-partial')

    def semantic_args(self):
        candidate = self.write('runs/harmony/sandbox/compare/candidate.jpeg', self.image())
        score = self.write('runs/harmony/sandbox/compare/score.json', {
            'reference': str(self.shot), 'candidate': str(candidate), 'status': 'COMPLETE', 'metrics': {}})
        return {'reference_ref': file_ref(self.shot), 'candidate_ref': file_ref(candidate), 'score_ref': file_ref(score)}

    def test_semantic_executes_api_and_binds_original_images_and_score(self):
        args = self.semantic_args()
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                patch.object(lean_semantic_process, 'call', return_value={
                    'status': 'COMPLETE', 'overall': 90, 'comparability': 1, 'issues': []}) as call:
            result, _ = self.run_tool('semantic-inspect', **args)
        call.assert_called_once()
        self.assertEqual(result['status'], 'INSPECTED')
        output = read_json(result['semantic_ref']['path'])
        self.assertEqual(output['score_sha256'], args['score_ref']['sha256'])
        self.assertNotIn('secret-fixture', json.dumps(output))
        self.assertNotIn('quality', result)

    def test_semantic_missing_env_and_invalid_model_result_never_green(self):
        args = self.semantic_args()
        with patch.dict(os.environ, {}, clear=True):
            result, _ = self.run_tool('semantic-inspect', **args)
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                patch.object(lean_semantic_process, 'call', return_value={'status': 'SKIPPED'}):
            result, _ = self.run_tool('semantic-inspect', **args)
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')

    def test_semantic_api_failure_does_not_leak_secret_or_response_body(self):
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                patch.object(lean_semantic_process, 'call', side_effect=RuntimeError('secret-fixture')):
            result, _ = self.run_tool('semantic-inspect', **self.semantic_args())
        self.assertNotIn('secret-fixture', json.dumps(result))
        self.assertEqual(result['root_cause']['kind'], 'semantic-unavailable')

    def test_semantic_rejects_unrelated_score_before_api(self):
        args = self.semantic_args()
        fake = self.write('runs/harmony/sandbox/compare/wrong.json', {'reference': str(self.shot), 'candidate': str(self.shot)})
        args['score_ref'] = file_ref(fake)
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                patch.object(lean_semantic_process, 'call') as call, \
                self.assertRaisesRegex(Rejected, 'actual comparison images'):
            self.run_tool('semantic-inspect', **args)
        call.assert_not_called()

    def test_semantic_allows_second_original_viewport_of_same_frozen_target(self):
        self.path['coverage'] = 'home:base:scroll'
        self.capture_manifest('scroll')
        second = self.add_frozen_reference_viewport()
        args = self.semantic_args()
        args['reference_ref'] = file_ref(second)
        score = self.write('runs/harmony/sandbox/compare/score-second.json', {
            'reference': str(second), 'candidate': args['candidate_ref']['path'], 'status': 'COMPLETE'})
        args['score_ref'] = file_ref(score)
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                patch.object(lean_semantic_process, 'call', return_value={
                    'status': 'COMPLETE', 'overall': 90, 'comparability': 1, 'issues': []}):
            result, _ = self.run_tool('semantic-inspect', **args)
        self.assertEqual(result['status'], 'INSPECTED')
        self.assertEqual(read_json(result['semantic_ref']['path'])['reference_ref'], file_ref(second))

    def test_capture_rejects_manifest_with_additional_unfrozen_source_screenshot(self):
        foreign = self.write('context/foreign.png', self.image('PNG', 5))
        manifest = read_json(self.manifest)
        reference = manifest['targets'][0]
        reference['snapshot']['captures'].append({'index': 1, 'screenshot': str(foreign),
                                                  'view_tree': str(self.view), 'view_signature': 'foreign'})
        reference['coverage']['capture_count'] = reference['snapshot']['coverage']['capture_count'] = 2
        replacement = self.write('context/replacement-manifest.json', manifest)
        with self.assertRaisesRegex(Rejected, 'original frozen Android record'):
            self.run_tool('visual-capture', install_ref=self.installed(), round=1,
                          reference_manifest_ref=file_ref(replacement))

    def test_second_capture_preserves_original_android_and_prior_harmony_round(self):
        result, _ = self.capture()
        second, _ = self.run_tool('visual-capture', install_ref=self.installed(), round=2,
                                 reference_manifest_ref=result['manifest_ref'])
        self.assertEqual(second['status'], 'CAPTURED')
        records = read_json(second['manifest_ref']['path'])['targets']
        self.assertEqual([row['round'] for row in records], [None, 1, 2])

    def test_changed_secondary_baseline_and_original_manifest_hash_are_rejected(self):
        second = self.add_frozen_reference_viewport()
        second.write_bytes(self.image('PNG', 9))
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.run_tool('semantic-inspect', **self.semantic_args())
        self.capture_manifest('viewport')
        self.manifest.write_text('{}')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.run_tool('visual-capture', install_ref=self.installed(), round=1,
                          reference_manifest_ref=file_ref(self.manifest))

    def test_global_explicit_baseline_fallback_does_not_infer_manifest_or_extra_screens(self):
        self.module['plan'].pop('dimension_analysis_ref')
        result, _ = self.capture()
        self.assertEqual(result['root_cause']['kind'], 'source-evidence-unavailable')
        foreign = self.write('context/foreign.png', self.image('PNG', 5))
        args = self.semantic_args()
        args['reference_ref'] = file_ref(foreign)
        with patch.dict(os.environ, {'SDD_TEST_VISION_KEY': 'secret-fixture'}), \
                self.assertRaisesRegex(Rejected, 'frozen baseline set'):
            self.run_tool('semantic-inspect', **args)


if __name__ == '__main__':
    unittest.main()
