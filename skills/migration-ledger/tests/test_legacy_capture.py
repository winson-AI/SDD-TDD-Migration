"""The legacy application's screens become android-reference records: installed from the package the run was prepared
with, walked by frozen actions on the stated device, captured stable; what could not be captured is named, never invented."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, read_json
import lean_visual_worker as worker
import lean_worker
import ui_evidence
from lean_tools import select_runtime_ui, validate_manifest

APP = 'com.example.legacy'
NODE = '<node index="{i}" class="{cls}" package="' + APP + '" resource-id="{rid}" text="{text}" content-desc="" bounds="{bounds}" scrollable="{scroll}"/>'


class CaptureFixture(unittest.TestCase):
    """The fake adb, the crafted statement and the capture call shared by the Android and browser cases."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / '.sdd-runs/run-1'; self.sandbox = self.root / 'runs/harmony/sandbox'
        self.apk = self.base / 'legacy.apk'; self.apk.write_bytes(b'apk-bytes')
        self.stated = {'kind': 'android-emulator', 'app_id': APP, 'device': {'serial': 'emulator-5554'}, 'artifact': str(self.apk),
                       'artifact_sha256': file_ref(self.apk)['sha256'], 'launch': '.LoginActivity'}
        self.task = {'role': 'spec-designer', 'assignment_id': 'A1', 'fencing_token': 'fence-1'}
        self.actor = {'role': 'spec-designer', 'instance_id': 'spec-1',
                      'device_lock': {'held': True, 'device_id': 'emulator-5554', 'assignment_id': 'A1', 'fencing_token': 'fence-1'}}
        self.commands, self.focus, self.swipes, self.shots, self.end_after = [], APP + '/' + APP + '.LoginActivity', 0, 0, None
        self.dumps, self.front_after = 0, 0  # the launcher keeps the focus for the first front_after window dumps
        sleep = patch.object(worker.time, 'sleep', lambda s: None); sleep.start(); self.addCleanup(sleep.stop)

    def state(self, stated):
        path = self.root / 'context' / f'snapshot-{len(list((self.root / "context").glob("*")) if (self.root / "context").exists() else [])}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'effective_config': {'legacy_preview': stated}, 'source_refs': {}}))
        return {'project_context_ref': file_ref(path), 'modules': {}}

    def png(self, color):
        out = io.BytesIO(); Image.new('RGB', (20, 20), (color * 20 % 255, 30, 50)).save(out, format='PNG'); return out.getvalue()

    def hierarchy(self):
        start = self.swipes * 3
        items = ''.join(NODE.format(i=i, cls='android.widget.TextView', rid='', text=f'Item {i}', bounds=f'[0,{300 + i * 100}][1080,{400 + i * 100}]', scroll='false')
                        for i in range(start, start + 3))
        if self.end_after is not None and self.swipes >= self.end_after:
            items += NODE.format(i=9, cls='android.widget.TextView', rid='', text='End', bounds='[0,1700][1080,1800]', scroll='false')
        return ('<hierarchy rotation="0"><node index="0" class="android.widget.FrameLayout" package="' + APP + '" resource-id="" text="" content-desc="" bounds="[0,0][1080,1920]" scrollable="false">'
                + NODE.format(i=0, cls='android.widget.TextView', rid=APP + ':id/title', text='Login', bounds='[0,0][1080,200]', scroll='false')
                + '<node index="1" class="androidx.recyclerview.widget.RecyclerView" package="' + APP + '" resource-id="' + APP + ':id/list" text="" content-desc="" bounds="[0,200][1080,1900]" scrollable="true">'
                + items + '</node></node></hierarchy>')

    def fake(self, argv, **kwargs):
        self.commands.append(argv)
        self.assertFalse(kwargs.get('shell', False))
        if argv[0] == sys.executable:  # the legacy build command of a build-kind statement
            Path(argv[-1]).write_bytes(b'built-apk'); return SimpleNamespace(returncode=0, stdout='built', stderr='')
        self.assertEqual(argv[1:3], ['-s', 'emulator-5554'])
        command, stdout = argv[3:], ''
        if command == ['version']: stdout = 'Android Debug Bridge version 1.0.41\nVersion 35.0.0'
        elif command == ['get-state']: stdout = 'device'
        elif command[:2] == ['install', '-r']: stdout = 'Success'
        elif command[:3] == ['shell', 'pm', 'path']: stdout = 'package:/data/app/' + APP + '/base.apk'
        elif command[:3] == ['shell', 'dumpsys', 'window']:
            self.dumps += 1
            stdout = '  mCurrentFocus=Window{1a2b u0 ' + (self.focus if self.dumps > self.front_after else 'com.android.launcher3/.Launcher') + '}\n'
        elif command[:3] == ['shell', 'uiautomator', 'dump']: stdout = 'UI hierchary dumped to: ' + command[3]
        elif command[:1] == ['pull']:
            dest = Path(command[2]); dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.suffix == '.xml': dest.write_text(self.hierarchy())
            else: self.shots += 1; dest.write_bytes(self.png(self.swipes))
        elif command[:3] == ['shell', 'input', 'swipe']: self.swipes += 1
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    def capture(self, targets, stated=None, module_id='M001', **extra):
        out = self.sandbox / 'spec-1' / f'attempt-{len(list(self.sandbox.glob("spec-1/*")))}'; out.mkdir(parents=True)
        with patch.object(worker.subprocess, 'run', side_effect=self.fake):
            return worker.legacy_capture({'targets': targets, **extra}, root=self.root, out=out, module_id=module_id,
                                         state=self.state(self.stated if stated is None else stated), task=self.task, actor=self.actor)

    def login(self, **over):
        return {'coverage': 'login:base:viewport', 'target_match': [{'resource-id': APP + ':id/title', 'text': 'Login'}], **over}

class LegacyCaptureTests(CaptureFixture):
    def test_the_legacy_screens_become_android_reference_records_the_pipeline_reads(self):
        result = self.capture([self.login()])
        self.assertEqual((result['status'], result['captured'], result['blocked']), ('CAPTURED', ['login:base:viewport'], []))
        manifest = read_json(result['manifest_ref']['path'])
        self.assertEqual(validate_manifest.validate_manifest(manifest)['mode'], 'runtime')
        record = ui_evidence.capture_target(result['manifest_ref'], 'login:base:viewport')
        self.assertEqual((record['phase'], record['platform'], record['status'], record['snapshot']['device_backend']['name']),
                         ('android-reference', 'android', 'COMPLETE', 'adb'))
        self.assertTrue(select_runtime_ui.select(Path(result['manifest_ref']['path']), ['login:base:viewport']))
        self.assertTrue(any(c[3:7] == ['install', '-r', '-t', str(self.apk)] for c in self.commands))
        self.assertTrue(any(c[3:8] == ['shell', 'am', 'start', '-n', APP + '/.LoginActivity'] for c in self.commands))
        self.assertTrue(any(c[3:5] == ['shell', 'rm'] for c in self.commands))
        self.assertEqual(read_json(result['install_ref']['path'])['status'], 'INSTALLED')
        self.assertEqual(manifest['legacy_preview']['kind'], 'android-emulator')

    def test_an_activity_still_starting_is_read_again_before_it_is_judged_not_in_front(self):
        self.front_after = 3
        result = self.capture([self.login()])
        self.assertEqual((result['status'], result['captured']), ('CAPTURED', ['login:base:viewport']))
        self.assertEqual(sum(1 for c in self.commands if c[3:8] == ['shell', 'am', 'start', '-n', APP + '/.LoginActivity']), 1)
        self.front_after = 99
        result = self.capture([self.login()])
        self.assertEqual((result['status'], result['blocked'][0]['reason']), ('BLOCKED', 'requested app is not the observed foreground app before capture'))

    def test_a_scroll_target_is_complete_only_when_the_frozen_end_is_observed(self):
        self.end_after = 2
        scroll = {'coverage': 'list:base:scroll', 'target_match': [{'resource-id': APP + ':id/list'}], 'actions': [{'action': 'tap', 'x': 540, 'y': 1800}],
                  'scroll_region': {'resource-id': APP + ':id/list'}, 'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 5}
        result = self.capture([self.login(), scroll])
        self.assertEqual((result['status'], result['captured']), ('CAPTURED', ['login:base:viewport', 'list:base:scroll']))
        record = ui_evidence.capture_target(result['manifest_ref'], 'list:base:scroll')
        self.assertEqual((record['coverage']['achieved'], record['coverage']['capture_count'], record['coverage']['termination']),
                         ('scroll-complete', 3, 'frozen-scroll-end-observed'))
        self.assertTrue(any(c[3:6] == ['shell', 'input', 'tap'] for c in self.commands))
        self.commands.clear(); self.swipes, self.end_after = 0, None
        result = self.capture([scroll])
        self.assertEqual((result['status'], result['blocked'][0]['kind']), ('BLOCKED', 'capture-incomplete'))

    def test_what_cannot_be_captured_is_named_and_the_rest_still_is(self):
        result = self.capture([self.login(), self.login(coverage='settings:base:viewport', target_match=[{'text': 'Settings'}])])
        self.assertEqual((result['status'], result['captured'], result['blocked'][0]['reason']),
                         ('PARTIAL', ['login:base:viewport'], 'frozen target selectors not observed'))
        self.focus = 'com.android.launcher/.Launcher'
        self.assertEqual(self.capture([self.login()])['blocked'][0]['kind'], 'target-precondition')
        self.focus = APP + '/' + APP + '.LoginActivity'
        self.apk.write_bytes(b'rebuilt elsewhere')
        result = self.capture([self.login()])
        self.assertEqual((result['status'], result['root_cause']['kind']), ('BLOCKED', 'artifact-identity-unverified'))
        with self.assertRaisesRegex(Rejected, 'adb-visible provider'):
            self.capture([self.login()], stated={'kind': 'none', 'reason': 'no build'})
        self.actor['device_lock']['device_id'] = 'other'
        with self.assertRaisesRegex(Rejected, 'exclusive device lock'):
            self.capture([self.login()])

    def test_a_build_statement_builds_the_package_before_installing_it(self):
        built = self.base / 'built.apk'
        stated = {**self.stated, 'build': {'argv': [sys.executable, '-c', 'pass', str(built)], 'cwd': str(self.base), 'timeout_seconds': 30, 'output': str(built)}}
        stated.pop('artifact'); stated.pop('artifact_sha256')
        result = self.capture([self.login()], stated=stated)
        self.assertEqual(result['status'], 'CAPTURED')
        install = read_json(result['install_ref']['path'])
        self.assertEqual((install['artifact_ref']['path'], bool(install['build_log_ref'])), (str(built), True))

    def test_the_operation_is_open_to_the_planner_and_bound_to_an_assignment_without_a_plan(self):
        self.assertEqual(lean_worker.ROLES['legacy-capture'], {'spec-designer', 'test-runner'})
        state = {'modules': {'M001': {'module_id': 'M001', 'plan': None, 'assignments': {'A1': {
            'assignment_id': 'A1', 'closed': False, 'role': 'spec-designer', 'instance_id': 'spec-1', 'fencing_token': 'fence-1', 'execution_contract': {'path_ids': []}}}}}}
        request = {'module_id': 'M001', 'assignment_id': 'A1', 'fencing_token': 'fence-1'}
        module, task = lean_worker.assignment(state, request, self.actor, planned=False)
        self.assertEqual(task['assignment_id'], 'A1')


class FakePage:
    """What the worker asks of a browser page; the DOM it returns is the tree the selectors read."""
    version = 'chromium 130'

    def __init__(self, png):
        self.calls, self.title_text, self.text, self.png = [], 'Login', 'Sign in', png

    def goto(self, url): self.calls.append(('goto', url))
    def click(self, selector): self.calls.append(('click', selector))
    def back(self): self.calls.append(('back',))
    def wheel(self, x, y, dy): self.calls.append(('wheel',))
    def settle(self, network=False): self.calls.append(('settle',))
    def wait(self, ms): self.calls.append(('wait', ms))
    def title(self): return self.title_text
    def close(self): self.calls.append(('close',))
    def screenshot(self, path): Path(path).write_bytes(self.png)

    def dom(self):
        return {'tag': 'body', 'id': '', 'cls': '', 'text': '', 'aria': '', 'bounds': [0, 0, 1280, 800], 'scrollable': False, 'children': [
            {'tag': 'h1', 'id': 'title', 'cls': 'hero', 'text': self.text, 'aria': '', 'bounds': [0, 0, 1280, 80], 'scrollable': False, 'children': []},
            {'tag': 'div', 'id': 'list', 'cls': '', 'text': '', 'aria': 'items', 'bounds': [0, 80, 1280, 800], 'scrollable': True, 'children': []}]}


class BrowserCaptureTests(CaptureFixture):
    """A legacy web application: the url is the device, the DOM is the tree, the record is legacy-reference on platform web."""
    def setUp(self):
        super().setUp()
        self.page = FakePage(self.png(1))
        self.web = {'kind': 'browser', 'url': 'https://legacy.example.test/login'}
        self.actor['device_lock']['device_id'] = self.web['url']
        self.viewports = []
        self.open = patch.object(worker, 'open_browser', lambda out, viewport=None: (self.viewports.append(viewport), self.page)[1]); self.open.start(); self.addCleanup(self.open.stop)

    def test_the_statement_may_name_the_window_the_legacy_is_captured_in(self):
        import project_context as pc
        phone = {**self.web, 'viewport': {'width': 390, 'height': 844}}
        self.assertEqual(pc.legacy_preview_config(phone)['viewport'], {'width': 390, 'height': 844})
        for bad in ({'width': 390}, {'width': 390, 'height': 10}, {'width': '390', 'height': 844}):
            with self.assertRaisesRegex(Rejected, 'viewport is'):
                pc.legacy_preview_config({**self.web, 'viewport': bad})
        result = self.capture([{'coverage': 'login:base:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]}], stated=phone)
        self.assertEqual((result['status'], self.viewports), ('CAPTURED', [{'width': 390, 'height': 844}]))

    def test_a_web_screen_becomes_a_legacy_reference_record_the_pipeline_reads(self):
        from lean_tools import validate_manifest as vm
        self.assertTrue(vm.is_reference({'phase': 'legacy-reference', 'platform': 'web'}) and vm.is_reference({'phase': 'android-reference', 'platform': 'android'}))
        self.assertFalse(vm.is_reference({'phase': 'legacy-reference', 'platform': 'ios'}) or vm.is_reference({'phase': 'android-reference', 'platform': 'web'}))
        target = {'coverage': 'login:base:viewport', 'actions': [{'action': 'click', 'selector': 'a.login'}], 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]}
        result = self.capture([target], stated=self.web)
        self.assertEqual((result['status'], result['captured'], result['install_ref']), ('CAPTURED', ['login:base:viewport'], None))
        record = ui_evidence.capture_target(result['manifest_ref'], 'login:base:viewport')
        self.assertEqual((record['phase'], record['platform'], record['snapshot']['device_backend']['name'], record['snapshot']['device_backend']['device']),
                         ('legacy-reference', 'web', 'playwright', 'legacy.example.test'))
        self.assertEqual(validate_manifest.validate_manifest(read_json(result['manifest_ref']['path']))['mode'], 'runtime')
        selected = select_runtime_ui.select(Path(result['manifest_ref']['path']), ['login:base:viewport'])
        self.assertTrue(any(n['resource-id'] == 'title' and n['class'] == 'h1 hero' for n in selected['captures'][0]['viewports'][0]['nodes']))
        self.assertEqual(self.page.calls[:2], [('goto', self.web['url']), ('click', 'a.login')]); self.assertIn(('close',), self.page.calls)
        self.assertEqual(self.viewports, [None])
        self.assertEqual(read_json(result['manifest_ref']['path'])['legacy_preview']['url'], self.web['url'])

    def test_what_a_browser_cannot_show_is_named(self):
        self.page.text = 'Welcome back'
        result = self.capture([{'coverage': 'login:base:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]}], stated=self.web)
        self.assertEqual((result['status'], result['blocked'][0]['reason']), ('BLOCKED', 'frozen target selectors not observed'))
        result = self.capture([{'coverage': 'list:base:scroll', 'target_match': [{'resource-id': 'list'}], 'scroll_region': {'resource-id': 'list'}, 'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 2}], stated=self.web)
        self.assertEqual((result['blocked'][0]['kind'], ('wheel',) in self.page.calls), ('capture-incomplete', True))  # a bounded scroll that never showed the frozen end
        with self.assertRaisesRegex(Rejected, 'unsupported navigation action'):
            self.capture([{'coverage': 'login:base:viewport', 'actions': [{'action': 'tap', 'x': 1, 'y': 1}], 'target_match': [{'resource-id': 'title'}]}], stated=self.web)


class AgentNavigationTests(CaptureFixture):
    """A screen whose way in is not a deterministic action list: the stated navigator walks frozen step texts as a snapshot
    task, the worker still matches the frozen selectors; what the navigator did not reach is a capture_gap suggestion."""
    def setUp(self):
        super().setUp()
        self.navigator = {'argv': [sys.executable, str(self.base / 'navigator.py')], 'cwd': str(self.base), 'timeout_seconds': 30}
        self.stated = {**self.stated, 'navigator': self.navigator}
        self.navigation_status, self.queries = 'reached', []

    def fake(self, argv, **kwargs):
        if '--query-file' in argv:  # the navigator: an adapter walking a snapshot task
            self.assertEqual((argv[:2], kwargs.get('cwd'), kwargs.get('timeout')), (self.navigator['argv'], self.navigator['cwd'], 30))
            self.queries.append(read_json(argv[argv.index('--query-file') + 1]))
            reached = self.navigation_status == 'reached'
            Path(argv[argv.index('--result-file') + 1]).write_text(json.dumps({'producer': 'harmony-adapter', 'task_type': 'snapshot', 'status': self.navigation_status,
                                                                            'reason': None if reached else 'the path was not walked to its end'}))
            return SimpleNamespace(returncode=0 if reached else 2, stdout='', stderr='')
        return super().fake(argv, **kwargs)

    def target(self):
        return self.login(navigation={'mode': 'agent', 'steps': ['open the drawer', 'tap Settings']})

    def test_the_navigator_walks_the_frozen_steps_and_the_worker_still_captures_by_selector(self):
        result = self.capture([self.target()])
        self.assertEqual((result['status'], result['captured']), ('CAPTURED', ['login:base:viewport']))
        self.assertEqual([(q['task_type'], q['steps'], q['capture_id'], q['module_id'], q['parameters']['device_id']) for q in self.queries],
                         [('snapshot', ['open the drawer', 'tap Settings'], 'login:base:viewport', 'M001', 'emulator-5554')])
        record = ui_evidence.capture_target(result['manifest_ref'], 'login:base:viewport')
        navigation = read_json(record['snapshot']['meta'])['navigation']
        self.assertEqual((navigation['mode'], navigation['status'], Path(navigation['result_ref']['path']).name), ('agent', 'reached', 'result.json'))
        self.assertTrue(any(c[3:6] == ['shell', 'uiautomator', 'dump'] for c in self.commands))  # the selectors were still matched after the walk

    def test_what_the_navigator_did_not_reach_is_a_capture_gap_suggestion_not_a_record(self):
        self.navigation_status = 'needs-review'
        row = self.capture([self.target()])['blocked'][0]
        self.assertEqual((row['kind'], Path(row['capture_gap']['evidence_refs'][0]['path']).name), ('navigation-unverified', 'result.json'))
        self.assertIn('needs-review', row['capture_gap']['reason'])
        self.stated.pop('navigator')
        self.assertTrue(self.capture([self.target()])['blocked'][0]['reason'].startswith('legacy_preview.navigator is not configured'))
        with self.assertRaisesRegex(Rejected, 'mode agent and 1..30'):
            self.capture([self.login(navigation={'mode': 'script', 'steps': []})])
        web = {'kind': 'browser', 'url': 'https://legacy.example.test/login'}
        self.actor['device_lock']['device_id'] = web['url']
        with patch.object(worker, 'open_browser', lambda out, viewport=None: FakePage(self.png(1))):
            result = self.capture([{'coverage': 'login:base:viewport', 'target_match': [{'resource-id': 'title'}], 'navigation': {'mode': 'agent', 'steps': ['x']}}], stated=web)
        self.assertIn('adb device statement', result['blocked'][0]['reason'])


class EmulatorBootTests(CaptureFixture):
    """No real device: the stated emulator is booted by the worker, waited for, recorded, and left running."""
    def setUp(self):
        super().setUp()
        self.booted, self.launches, self.exit_code = False, [], None
        self.sleep = patch.object(worker.time, 'sleep', lambda s: None); self.sleep.start(); self.addCleanup(self.sleep.stop)
        self.popen = patch.object(worker.subprocess, 'Popen', side_effect=self.launch); self.popen.start(); self.addCleanup(self.popen.stop)

    def launch(self, argv, **kwargs):
        self.launches.append((argv, kwargs.get('cwd'), kwargs.get('start_new_session')))
        self.booted = self.exit_code is None
        return SimpleNamespace(pid=4242, returncode=self.exit_code, poll=lambda: self.exit_code)

    def fake(self, argv, **kwargs):
        command = argv[3:]
        if command == ['get-state']:
            self.commands.append(argv)
            return SimpleNamespace(returncode=0, stdout='device', stderr='') if self.booted else SimpleNamespace(returncode=1, stdout='', stderr='error: device offline')
        if command[:3] == ['shell', 'getprop', 'sys.boot_completed']:
            self.commands.append(argv)
            return SimpleNamespace(returncode=0, stdout='1' if self.booted else '', stderr='')
        return super().fake(argv, **kwargs)

    def test_the_stated_emulator_is_booted_when_the_serial_does_not_answer(self):
        boot = {'argv': [sys.executable, '-c', 'pass'], 'cwd': str(self.base), 'timeout_seconds': 60}
        result = self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554', 'boot': boot}})
        self.assertEqual((result['status'], Path(result['boot_ref']['path']).name, self.launches), ('CAPTURED', 'boot.json', [(boot['argv'], str(self.base), True)]))
        self.assertEqual(read_json(result['boot_ref']['path'])['pid'], 4242)
        self.booted = True; self.launches.clear()
        self.assertIsNone(self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554', 'boot': boot}})['boot_ref'])  # already up: nothing started
        self.assertEqual(self.launches, [])

    def test_an_avd_boots_through_the_sdk_emulator_and_nothing_is_assumed_without_one(self):
        sdk = self.base / 'sdk'; (sdk / 'emulator').mkdir(parents=True); (sdk / 'emulator/emulator').write_text('#!/bin/sh\n')
        with patch.dict(worker.os.environ, {'ANDROID_SDK_ROOT': str(sdk)}):
            result = self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554', 'avd': 'pixel_7'}})
        self.assertEqual((result['status'], self.launches[0][0]), ('CAPTURED', [str(sdk / 'emulator/emulator'), '-avd', 'pixel_7']))
        self.booted = False
        with patch.dict(worker.os.environ, {'ANDROID_SDK_ROOT': '', 'ANDROID_HOME': ''}), patch.object(worker.shutil, 'which', lambda name: None):
            result = self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554', 'avd': 'pixel_7'}})
        self.assertEqual((result['status'], result['root_cause']['kind']), ('BLOCKED', 'environment-unavailable'))
        self.assertIn('state the emulator to boot', result['root_cause']['reason'])
        result = self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554'}})
        self.assertIn('not connected', result['root_cause']['reason'])

    def test_an_emulator_that_dies_or_never_boots_is_an_environment_gap_with_its_log(self):
        boot = {'argv': [sys.executable, '-c', 'pass'], 'timeout_seconds': 9}
        self.exit_code = 3
        result = self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554', 'boot': boot}})
        self.assertIn('exited with 3', result['root_cause']['reason'])
        self.exit_code = None
        with patch.object(self, 'launch', side_effect=lambda argv, **kw: SimpleNamespace(pid=1, returncode=None, poll=lambda: None)):
            self.popen.stop(); again = patch.object(worker.subprocess, 'Popen', side_effect=self.launch); again.start(); self.addCleanup(again.stop)
            result = self.capture([self.login()], stated={**self.stated, 'device': {'serial': 'emulator-5554', 'boot': boot}})
        self.assertIn('did not boot within 9 s', result['root_cause']['reason'])


if __name__ == '__main__':
    unittest.main()
