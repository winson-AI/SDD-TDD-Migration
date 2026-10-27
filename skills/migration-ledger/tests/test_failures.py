"""A command hands back its status and, on a failure, the locations grepped from its log; the log itself is not read."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import failures
import run_command
import test_split_testing

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_command.py'


class FailureLocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def log(self, text):
        path = self.tmp / 'build.log'
        path.write_text(text)
        return path

    def test_compiler_and_tool_errors_become_locations(self):
        rows = failures.extract(self.log('\n'.join([
            '> Task :app:compileKotlin',
            'e: file:///work/app/src/Login.kt:12:5 Unresolved reference: token',
            '/work/app/src/Main.java:7: error: cannot find symbol',
            'hvigor ERROR: ArkTS:ERROR File: /work/entry/src/main/ets/pages/Index.ets:10:3',
            " Cannot find name 'state'.",
            'src/app.ts(4,9): error TS2304: Cannot find name x.',
            '* What went wrong:',
            "Execution failed for task ':app:compileKotlin'.",
            'BUILD FAILED in 3s'])))
        located = [(r['kind'], r.get('path'), r.get('line')) for r in rows]
        self.assertEqual(located, [('kotlin', '/work/app/src/Login.kt', 12), ('javac', '/work/app/src/Main.java', 7),
                                   ('arkts', '/work/entry/src/main/ets/pages/Index.ets', 10), ('tsc', 'src/app.ts', 4),
                                   ('gradle', None, None)])
        self.assertEqual(rows[2]['message'], "Cannot find name 'state'.")  # the message on the line after the marker
        self.assertEqual(rows[4]['message'], "Execution failed for task ':app:compileKotlin'.")
        self.assertTrue(failures.inside(rows[:3], ['/work']))
        self.assertFalse(failures.inside(rows[:2], ['/work/app/src/Login.kt']))

    def test_a_traceback_keeps_its_innermost_frame(self):
        rows = failures.extract(self.log('Traceback (most recent call last):\n  File "/w/a.py", line 3, in <module>\n'
                                         '  File "/w/b.py", line 9, in f\nValueError: bad\n'))
        self.assertEqual([(r['path'], r['line']) for r in rows], [('/w/b.py', 9)])

    def test_run_hands_back_the_status_and_the_locations_not_the_log(self):
        code = "print('noise ' * 2000); print('e: file:///work/m1/code.kt:3:1 Type mismatch'); raise SystemExit(1)"
        out = subprocess.run([sys.executable, str(SCRIPT), 'run', '--log', str(self.tmp / 'run.log'), '--', sys.executable, '-c', code],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        result = json.loads(out.stdout)
        self.assertNotIn('noise', out.stdout)  # what the model reads is the result, not the log
        self.assertEqual((result['exit_code'], result['failure_count']), (1, 1))
        self.assertIn('/work/m1/code.kt:3', result['summary'])
        self.assertEqual(json.loads(Path(result['failures_ref']['path']).read_text())['failures'][0]['message'], 'Type mismatch')
        grepped = run_command.grep(self.tmp / 'run.log', 'Type mismatch')
        self.assertEqual([m['line'] for m in grepped['matches']], [2])

    def test_a_started_command_is_waited_for_by_its_end(self):
        log = self.tmp / 'server.log'
        self.addCleanup(setattr, run_command, 'POLL_SECONDS', run_command.POLL_SECONDS); run_command.POLL_SECONDS = 0.05
        started = run_command.start([sys.executable, '-c', 'import time; time.sleep(0.5); print("ready")'], log)
        self.assertIn('started', started)
        self.assertTrue(run_command.wait(log, timeout=0.01).get('running'))
        result = run_command.wait(log, timeout=30)
        self.assertEqual(result['exit_code'], 0)
        self.assertNotIn('summary', result)


class BuildFailureTests(unittest.TestCase):
    def setUp(self):
        self.split = test_split_testing.SplitTestingTests(); self.split.setUp(); self.addCleanup(self.split.doCleanups)
        self.f = self.split.f

    def fail_build(self, where):
        self.split.build_code = "print('e: file://%s:1:1 Unresolved reference: missing'); raise SystemExit(1)" % where
        self.split.prepare(); self.split.compile()
        return self.f.state()['modules']['M001']['results']['B1']

    def test_a_build_broken_inside_the_write_scope_is_a_confirmed_code_defect_with_its_locations(self):
        row = self.fail_build(self.f.target / 'm1/code.py')
        cause = row['root_cause']
        self.assertEqual((row['quality'], cause['category'], cause['confidence']), ('red-bug', 'code', 'confirmed'))
        self.assertIn('m1/code.py:1', cause['summary'])
        step = self.f.state()['next_steps'][0]
        self.assertEqual(step['failure_locations'], {'B1': cause['failures_ref']})

    def test_a_build_broken_outside_the_write_scope_is_left_to_diagnosis(self):
        cause = self.fail_build(self.f.base / 'elsewhere/Lib.kt')['root_cause']
        self.assertEqual((cause['category'], cause['confidence'], cause['next_action']), ('build', 'observed', 'diagnose'))


if __name__ == '__main__':
    unittest.main()
