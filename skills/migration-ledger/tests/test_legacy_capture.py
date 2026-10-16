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


class LegacyCaptureTests(unittest.TestCase):
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
        elif command[:3] == ['shell', 'dumpsys', 'window']: stdout = '  mCurrentFocus=Window{1a2b u0 ' + self.focus + '}\n'
        elif command[:3] == ['shell', 'uiautomator', 'dump']: stdout = 'UI hierchary dumped to: ' + command[3]
        elif command[:1] == ['pull']:
            dest = Path(command[2]); dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.suffix == '.xml': dest.write_text(self.hierarchy())
            else: self.shots += 1; dest.write_bytes(self.png(self.swipes))
        elif command[:3] == ['shell', 'input', 'swipe']: self.swipes += 1
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    def capture(self, targets, stated=None, **extra):
        out = self.sandbox / 'spec-1' / f'attempt-{len(list(self.sandbox.glob("spec-1/*")))}'; out.mkdir(parents=True)
        with patch.object(worker.subprocess, 'run', side_effect=self.fake):
            return worker.legacy_capture({'targets': targets, **extra}, root=self.root, out=out,
                                         state=self.state(self.stated if stated is None else stated), task=self.task, actor=self.actor)

    def login(self, **over):
        return {'coverage': 'login:base:viewport', 'target_match': [{'resource-id': APP + ':id/title', 'text': 'Login'}], **over}

    def test_the_legacy_screens_become_android_reference_records_the_pipeline_reads(self):
        result = self.capture([self.login()])
        self.assertEqual((result['status'], result['captured'], result['blocked']), ('CAPTURED', ['login:base:viewport'], []))
        manifest = read_json(result['manifest_ref']['path'])
        self.assertEqual(validate_manifest.validate_manifest(manifest)['mode'], 'runtime')
        record = ui_evidence.capture_target(result['manifest_ref'], 'login:base:viewport')
        self.assertEqual((record['phase'], record['platform'], record['status'], record['snapshot']['device_backend']['name']),
                         ('android-reference', 'android', 'COMPLETE', 'adb'))
        self.assertTrue(select_runtime_ui.select(Path(result['manifest_ref']['path']), ['login:base:viewport']))
        self.assertTrue(any(c[3:6] == ['install', '-r', str(self.apk)] for c in self.commands))
        self.assertTrue(any(c[3:8] == ['shell', 'am', 'start', '-n', APP + '/.LoginActivity'] for c in self.commands))
        self.assertTrue(any(c[3:5] == ['shell', 'rm'] for c in self.commands))
        self.assertEqual(read_json(result['install_ref']['path'])['status'], 'INSTALLED')
        self.assertEqual(manifest['legacy_preview']['kind'], 'android-emulator')

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


if __name__ == '__main__':
    unittest.main()
