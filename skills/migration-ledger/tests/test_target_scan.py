"""The target project scanned read-only for what it already holds of a feature: modules, entry points and declared symbols
that mention a keyword, each with its file hash, as candidates for the orchestrator's target profile."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, check_ref, file_ref, read_json
import lean_worker
import test_project_context
from lean_tools import target_scan


class TargetScanTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        prepared = self.f.prepare(); self.f.start(self.f.init_payload(prepared))
        t = self.f.target
        self.write(t / 'app/build.gradle.kts', 'plugins { id("com.android.application") }')
        self.write(t / 'app/src/main/AndroidManifest.xml', '<manifest><application><activity android:name=".LoginActivity"/><activity android:name=".SettingsActivity"/></application></manifest>')
        self.write(t / 'app/src/main/java/demo/LoginViewModel.kt', 'package demo\n\nclass LoginViewModel {\n    fun signIn() {}\n}\n')
        self.write(t / 'app/src/main/java/demo/settings/SettingsScreen.kt', 'package demo.settings\n\n@Composable\nfun SettingsScreen() {}\n')
        self.write(t / 'app/src/test/java/demo/LoginViewModelTest.kt', 'class LoginViewModelTest {}\n')
        self.write(t / 'feature/payments/oh-package.json5', '{ "name": "payments" }')
        self.write(t / 'feature/payments/src/main/module.json5', '{ "module": { "abilities": [ { "name": "PaymentsAbility" } ] } }')
        self.write(t / 'feature/payments/src/main/ets/PaymentsPage.ets', '@Entry\n@Component\nstruct PaymentsPage {}\n')
        self.write(t / 'build/generated/Login.kt', 'class LoginGenerated {}\n')  # a build output is not the target's code
        self.count = 0

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)

    def run_tool(self, args, role='global-orchestrator'):
        self.count += 1
        result = lean_worker.run(self.f.run, {'request_id': 'scan-' + str(self.count), 'operation': 'target-scan', 'args': args}, {'role': role, 'instance_id': role + '-1'})
        return read_json(check_ref(result['result_ref']))

    def test_the_scan_names_modules_entries_and_symbols_that_match_the_feature(self):
        result = self.run_tool({'keywords': ['login', 'payments']})
        self.assertEqual([(Path(m['path']).name, sorted(m['build_files']), m['has_tests']) for m in result['modules']], [('app', ['build.gradle.kts'], True), ('payments', ['oh-package.json5'], False)])
        self.assertEqual(sorted((e['kind'], tuple(e['names'])) for e in result['entries']), [('android-manifest', ('.LoginActivity', '.SettingsActivity')), ('harmony-module', ('PaymentsAbility',))])
        symbols = {s['symbol'].split('/')[-1]: (s['keyword'], s['in_tests']) for s in result['symbols']}
        self.assertEqual(symbols, {'LoginViewModel.kt#LoginViewModel': ('login', False), 'LoginViewModel.kt#signIn': ('login', False),
                                   'LoginViewModelTest.kt#LoginViewModelTest': ('login', True), 'PaymentsPage.ets#PaymentsPage': ('payments', False)})
        self.assertTrue(all(file_ref(Path(s['symbol'].split('#')[0]))['sha256'] == s['sha256'] for s in result['symbols']))
        self.assertEqual(result['acceptance'], 'candidates-for-the-target-profile-not-a-state-verdict')

    def test_roots_narrow_the_scan_and_bad_requests_are_refused(self):
        result = self.run_tool({'keywords': ['settings'], 'roots': ['app']}, role='spec-designer')
        self.assertEqual([s['symbol'].split('/')[-1] for s in result['symbols']], ['SettingsScreen.kt#SettingsScreen'])
        self.assertEqual([Path(m['path']).name for m in result['modules']], ['app'])
        for args, message in (({'keywords': []}, '1..20 keyword'), ({'keywords': ['x'], 'roots': ['/abs']}, 'relative to target_root'),
                              ({'keywords': ['x'], 'roots': ['nowhere']}, 'not a folder of the target')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.run_tool(args)
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_tool({'keywords': ['x']}, role='implementer')
        self.assertEqual(lean_worker.ROLES['target-scan'], {'global-orchestrator', 'module-orchestrator', 'spec-designer'})


if __name__ == '__main__':
    unittest.main()
