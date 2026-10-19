"""An Android target is installed, hashed on the device against the accepted APK and captured as an android-candidate
record; the comparison pipeline reads a candidate of either platform against the legacy reference."""
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, read_json
import lean_visual_worker as worker
import test_lean_visual_worker as base
import visual_evidence
from lean_tools import validate_manifest

APP = 'com.example.app'
XML = ('<hierarchy rotation="0"><node index="0" class="android.widget.FrameLayout" package="' + APP + '" resource-id="" text="" content-desc="" bounds="[0,0][1080,1920]" scrollable="false">'
       '<node index="0" class="android.widget.TextView" package="' + APP + '" resource-id="' + APP + ':id/title" text="{text}" content-desc="" bounds="[0,0][1080,200]" scrollable="false"/></node></hierarchy>')


class AndroidTargetTests(unittest.TestCase):
    def setUp(self):
        self.t = t = base.VisualExecutionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        env = t.write('runs/harmony/sandbox/environment/visual-adb.json', {
            'visual_capture': {'backend': 'adb', 'tool': 'adb', 'device_id': 'device-1'},
            'visual_model': {'mode': 'external', 'enabled': False, 'name': 'vision-test', 'base_url': 'https://model.example/v1', 'api_key_env': 'SDD_TEST_VISION_KEY'}})
        self.apk = t.write('runs/build/build-1/app.apk', b'apk-bytes')
        self.sha = hashlib.sha256(b'apk-bytes').hexdigest()
        t.path['visual_execution'].update(environment_ref=file_ref(env), ability='.MainActivity')
        t.module['build_artifacts'] = [file_ref(self.apk)]; t.args['artifact_ref'] = file_ref(self.apk)
        self.commands, self.focus, self.text, self.installed_sha = [], APP + '/' + APP + '.MainActivity', 'Home', self.sha
        sleep = patch.object(worker.time, 'sleep', lambda s: None); sleep.start(); self.addCleanup(sleep.stop)

    def fake(self, argv, **kwargs):
        self.commands.append(argv); self.assertEqual(argv[1:3], ['-s', 'device-1'])
        command, stdout = argv[3:], ''
        if command == ['version']: stdout = 'Android Debug Bridge version 1.0.41\nVersion 35.0.0'
        elif command[:2] == ['install', '-r']: stdout = 'Success'
        elif command[:3] == ['shell', 'pm', 'path']: stdout = 'package:/data/app/' + APP + '-1/base.apk'
        elif command[:2] == ['shell', 'sha256sum']: stdout = self.installed_sha + '  ' + command[2]
        elif command[:3] == ['shell', 'dumpsys', 'window']: stdout = '  mCurrentFocus=Window{1a u0 ' + self.focus + '}\n'
        elif command[:3] == ['shell', 'uiautomator', 'dump']: stdout = 'UI hierchary dumped to: ' + command[3]
        elif command[:1] == ['pull']:
            dest = Path(command[2]); dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.suffix == '.xml': dest.write_text(XML.format(text=self.text))
            else: dest.write_bytes(self.t.image('PNG'))
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    def run_tool(self, operation, **extra):
        t = self.t; out = t.sandbox / 'test-1' / f'adb-{len(list(t.sandbox.glob("test-1/*")))}'; out.mkdir(parents=True)
        with patch.object(worker.subprocess, 'run', side_effect=self.fake):
            result = worker.run(operation, {**t.args, **extra}, root=t.root, out=out, module=t.module, task=t.task, actor=t.actor, config={})
        return result, worker.save(out / 'result.json', result)

    def test_an_apk_is_installed_hashed_on_the_device_and_captured_as_an_android_candidate(self):
        install, install_ref = self.run_tool('visual-install')
        self.assertEqual((install['status'], install['artifact_identity']['sha256']), ('INSTALLED', self.sha))
        result, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1, reference_manifest_ref=file_ref(self.t.manifest))
        self.assertEqual(result['status'], 'CAPTURED')
        record = read_json(result['manifest_ref']['path'])['targets'][-1]
        self.assertEqual((record['phase'], record['platform'], record['round'], record['snapshot']['device_backend']['name']),
                         ('android-candidate', 'android', 1, 'adb'))
        self.assertTrue(visual_evidence.is_candidate(record))
        self.assertFalse(visual_evidence.is_candidate({'phase': 'harmony-candidate', 'platform': 'android'}))
        validate_manifest.validate_snapshot(record['snapshot'], 'viewport', 'candidate')
        self.assertTrue(read_json(result['capture_execution_ref']['path'])['observations'])
        self.assertTrue(any(c[3:8] == ['shell', 'am', 'start', '-n', APP + '/.MainActivity'] for c in self.commands))
        self.assertTrue(any(c[3:5] == ['shell', 'rm'] for c in self.commands))
        self.text = 'Elsewhere'
        again, _ = self.run_tool('visual-capture', install_ref=install_ref, round=2, reference_manifest_ref=file_ref(self.t.manifest))
        self.assertEqual((again['status'], again['root_cause']['reason']), ('BLOCKED', 'frozen target selectors not observed'))

    def test_the_target_emulator_is_booted_before_the_install_when_it_does_not_answer(self):
        import json
        env = self.t.write('runs/harmony/sandbox/environment/visual-adb-boot.json', {
            'visual_capture': {'backend': 'adb', 'tool': 'adb', 'device_id': 'device-1', 'avd': 'pixel_7', 'boot': {'argv': [sys.executable, '-c', 'pass'], 'timeout_seconds': 30}},
            'visual_model': {'mode': 'external', 'enabled': False, 'name': 'vision-test', 'base_url': 'https://model.example/v1', 'api_key_env': 'SDD_TEST_VISION_KEY'}})
        self.t.path['visual_execution']['environment_ref'] = file_ref(env)
        self.booted, launches = False, []
        def fake(argv, **kwargs):
            command = argv[3:]
            if command == ['get-state']: return SimpleNamespace(returncode=0 if self.booted else 1, stdout='device' if self.booted else '', stderr='')
            if command[:3] == ['shell', 'getprop', 'sys.boot_completed']: return SimpleNamespace(returncode=0, stdout='1' if self.booted else '', stderr='')
            return self.fake(argv, **kwargs)
        def launch(argv, **kwargs):
            launches.append(argv); self.booted = True
            return SimpleNamespace(pid=7, returncode=None, poll=lambda: None)
        out = self.t.sandbox / 'test-1' / 'adb-boot'; out.mkdir(parents=True)
        with patch.object(worker.subprocess, 'run', side_effect=fake), patch.object(worker.subprocess, 'Popen', side_effect=launch), patch.object(worker.time, 'sleep', lambda s: None):
            install = worker.run('visual-install', dict(self.t.args), root=self.t.root, out=out, module=self.t.module, task=self.t.task, actor=self.t.actor, config={})
        self.assertEqual((install['status'], launches, Path(install['boot_ref']['path']).name), ('INSTALLED', [[sys.executable, '-c', 'pass']], 'boot.json'))

    def test_the_installed_bytes_must_be_the_accepted_apk_and_a_hap_is_refused_on_adb(self):
        self.installed_sha = 'f' * 64
        install, _ = self.run_tool('visual-install')
        self.assertEqual((install['status'], install['root_cause']['kind']), ('BLOCKED', 'artifact-identity-unverified'))
        self.t.args['artifact_ref'] = file_ref(self.t.artifact); self.t.module['build_artifacts'].append(file_ref(self.t.artifact))
        with self.assertRaisesRegex(Rejected, 'accepted APK artifact'):
            self.run_tool('visual-install')


if __name__ == '__main__':
    unittest.main()
