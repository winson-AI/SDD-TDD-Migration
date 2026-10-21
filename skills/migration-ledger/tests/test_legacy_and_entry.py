"""The legacy is a frozen input of the run, the intake asks whether the screens before sign-in run, and a device platform
stated without an adapter runs the package's own Main."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import execute_test
import ledger
import project_context as pc
import test_project_context
from contracts import Drifted, Rejected, check_ref, file_ref, legacy_as_prepared


def git(cwd, *args):
    subprocess.run(['git', '-C', str(cwd), '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', *args],
                   check=True, capture_output=True)


class LegacyAndEntryTests(unittest.TestCase):
    def test_a_legacy_file_changed_under_the_run_is_read_as_prepared(self):
        f = test_project_context.ProjectContextTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        source = f.legacy / 'app/LoginActivity.java'; source.parent.mkdir(parents=True); source.write_text('class Login { /* v1 */ }')
        git(f.legacy, 'init', '-q'); git(f.legacy, 'add', '.'); git(f.legacy, 'commit', '-qm', 'v1')
        f.start(f.init_payload(f.prepare()))
        snapshot = json.loads((f.run / 'context/snapshot.json').read_text())
        self.assertEqual(snapshot['legacy_commit'], pc.git_head(f.legacy))
        cited = file_ref(source)
        source.write_text('class Login { /* v2: a new entry point */ }'); git(f.legacy, 'commit', '-qam', 'v2')
        with self.assertRaises(Drifted):
            check_ref(cited)  # outside a judged request the reference is to the live file
        with legacy_as_prepared(f.run):
            self.assertEqual(check_ref(cited).read_text(), 'class Login { /* v1 */ }')
            with self.assertRaises(Drifted):
                check_ref({**cited, 'sha256': '0' * 64})  # bytes the run never held stay refused
        ledger.status(f.run)
        signals = json.loads((f.run / 'ledger/progress.json').read_text())['signals']
        moved = next(row for row in signals if row['reason'] == 'legacy-changed-since-prepare')
        self.assertEqual(moved['evidence']['prepared'], snapshot['legacy_commit'])

    def test_the_intake_asks_whether_the_screens_before_sign_in_run(self):
        ask = next(q for q in pc.intake({}) if q['field'] == 'legacy_preview')['ask']
        self.assertIn('登录前的界面', ask)

    def test_a_stated_device_platform_without_an_adapter_runs_the_builtin_main(self):
        s = {'test_adapter': {'device': {'platforms': ['android', 'web']}}, 'target_root': '/target'}
        android = execute_test.adapter_for(s, {'platform': 'android'}, Path('/run'))
        self.assertTrue(android['argv'][1].endswith('runtime/harmony/sandbox.py'))
        self.assertEqual(android['argv'][2:7], ['test', '--root', '/run', '--platform', 'android'])
        self.assertTrue(execute_test.adapter_for(s, {'platform': 'web'}, Path('/run'))['argv'][1].endswith('scripts/web_main.py'))
        with self.assertRaisesRegex(Rejected, 'no adapter runs platform harmony'):
            execute_test.adapter_for(s, {'platform': 'harmony'}, Path('/run'))  # not a platform the project states
        stated = {**s, 'test_adapter': {**s['test_adapter'], 'adapters': {'android': {'argv': ['/bin/own-main'], 'cwd': '/target'}}}}
        self.assertEqual(execute_test.adapter_for(stated, {'platform': 'android'}, Path('/run'))['argv'], ['/bin/own-main'])


if __name__ == '__main__':
    unittest.main()
