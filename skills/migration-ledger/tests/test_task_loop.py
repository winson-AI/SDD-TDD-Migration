"""A task is built and unit-tested as soon as it is written. What looks at the whole module waits for all of its tasks,
what looks for a module's callers waits until they are written, and one module at a time writes into a build unit."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import execute_test
import test_ledger
import test_feedback_repair
import test_validation as tv
from contracts import Rejected


class DueTests(unittest.TestCase):
    PATHS = [{'path_id': 'B1', 'kind': 'build'}, {'path_id': 'U1', 'kind': 'unit'}, {'path_id': 'U2', 'kind': 'unit'},
             {'path_id': 'S1', 'kind': 'static'}, {'path_id': 'P1', 'kind': 'automation'}]
    TASKS = [{'task_id': 'T1', 'path_ids': ['B1', 'U1', 'P1']}, {'task_id': 'T2', 'path_ids': ['B1', 'U2']}]

    def due(self, accepted, **state):
        module = {'module_id': 'M001', 'plan': {'paths': self.PATHS, 'tasks': self.TASKS}, 'accepted_task_ids': accepted, **state}
        return [path['path_id'] for path in tv.due(module)]

    def test_the_paths_that_can_be_judged_follow_what_is_written(self):
        self.assertEqual(self.due([]), ['B1'])
        self.assertEqual(self.due(['T1']), ['B1', 'U1'])                           # its unit tests, not the other task's
        self.assertEqual(self.due(['T1', 'T2']), ['B1', 'U1', 'U2', 'S1'])         # the closure looks at the whole module
        self.assertEqual(self.due(['T1', 'T2'], awaiting_assembly=True), ['B1', 'U1', 'U2'])
        self.assertNotIn('P1', self.due(['T1', 'T2']))                             # a device path is never a device-free gate

    def test_one_result_covers_what_is_due_and_stops_at_the_first_gate_that_fails(self):
        module = {'module_id': 'M001', 'plan': {'paths': self.PATHS, 'tasks': self.TASKS}, 'accepted_task_ids': ['T1'],
                  'code_baseline': 'c1', 'build_baseline': None, 'results': {}}
        green, red = {'quality': 'green-passed'}, {'quality': 'red-bug'}
        ids = lambda tests: [path['path_id'] for path in tv.stage_paths(module, tests)]
        self.assertEqual(ids({'B1': green, 'U1': green}), ['B1', 'U1'])
        self.assertEqual(ids({'B1': red}), ['B1'])
        module.update(build_baseline='c1', results={pid: {**green, 'code_baseline': 'c1'} for pid in ('B1', 'U1')})
        self.assertEqual(ids({}), [])                                              # what is written is tested: the next task is written
        self.assertEqual(tv.next_scope(module), 'build')                           # and the stage is not over while a path is not due

    def test_the_static_closure_waits_for_the_slices_that_will_call_the_module(self):
        provider = {'module_id': 'M001', 'dependencies': []}

        def consumer(stage, **state):
            return {'module_id': 'M002', 'dependencies': ['M001'], **state,
                    'behavior_review': {'verification': {'provider_inputs': [{'module_id': 'M001', 'required_stage': stage}]}}}
        self.assertTrue(tv.awaits_assembly(provider, [provider, consumer('implemented')]))
        self.assertTrue(tv.awaits_assembly(provider, [provider, consumer('implemented', code_baseline='c', execution_partition_pending=True)]))
        self.assertFalse(tv.awaits_assembly(provider, [provider, consumer('implemented', code_baseline='c')]))
        self.assertFalse(tv.awaits_assembly(provider, [provider, consumer('verified')]))  # that slice waits for this one's verification
        self.assertFalse(tv.awaits_assembly(provider, [provider]))

    def test_one_module_at_a_time_writes_into_a_build_unit(self):
        build = lambda *argv: {'paths': [{'path_id': 'B', 'kind': 'build', 'command': {'argv': list(argv), 'cwd': '/target'}}]}
        mine = {'module_id': 'M001', 'plan': build('gradlew', ':app:assemble'), 'assignments': {}}

        def other(plan, role='implementer', closed=False):
            return {'module_id': 'M002', 'plan': plan, 'assignments': {'A': {'role': role, 'closed': closed}}}
        for role in ('implementer', 'fixer'):
            with self.subTest(role=role), self.assertRaisesRegex(Rejected, 'build unit busy: M002 is being written'):
                tv.build_unit_free(mine, [mine, other(build('gradlew', ':app:assemble'), role)])
        tv.build_unit_free(mine, [mine, other(build('gradlew', ':lib:assemble'))])              # another build
        tv.build_unit_free(mine, [mine, other(build('gradlew', ':app:assemble'), closed=True)])  # its result is in
        tv.build_unit_free(mine, [mine, other(build('gradlew', ':app:assemble'), 'test-runner')])  # reading, not writing
        tv.build_unit_free({**mine, 'plan': {'paths': []}}, [other(build('gradlew', ':app:assemble'))])  # nothing compiled together


class TaskLoopTests(unittest.TestCase):
    setUp = test_feedback_repair.TaskIndependenceTests.setUp
    plan = test_feedback_repair.TaskIndependenceTests.plan
    implement = test_feedback_repair.TaskIndependenceTests.implement
    execute_paths = test_feedback_repair.TaskIndependenceTests.execute_paths

    def step(self):
        return self.f.state()['next_steps'][0]

    def module(self):
        return self.f.state()['modules']['M001']

    def test_a_written_task_is_built_before_the_next_one_is_written(self):
        self.t.freeze(self.plan())
        self.implement(['T1'], 'I1')
        self.assertEqual(self.module()['phase'], 'frozen')
        step = self.step()
        self.assertEqual((step['operation'], step['worker_role'], step['test_scope'], step['ready']), ('assign', 'test-runner', 'build', True))
        self.assertEqual(step['payload']['path_ids'], ['B'])
        self.execute_paths('BUILD1', 'build', ['B'])
        module = self.module()
        self.assertEqual((module['phase'], module['results']['B']['quality'], module['accepted_task_ids']), ('frozen', 'green-passed', ['T1']))
        step = self.step()
        self.assertEqual((step['worker_role'], step['payload']['task_ids']), ('implementer', ['T2']))  # tested: the next task
        self.implement(['T2'], 'I2')
        self.assertEqual(self.module()['phase'], 'testing')
        step = self.step()
        self.assertEqual((step['worker_role'], step['test_scope'], step['payload']['path_ids']), ('test-runner', 'build', ['B']))  # again, on all of it

    def test_the_next_task_may_still_be_written_without_waiting_for_the_build(self):
        self.t.freeze(self.plan())
        self.implement(['T1'], 'I1'); self.implement(['T2'], 'I2')
        self.assertEqual((self.module()['phase'], sorted(self.module()['accepted_task_ids'])), ('testing', ['T1', 'T2']))

    def test_a_failing_build_of_what_is_written_goes_to_repair_before_more_is_written(self):
        plan = self.plan()
        next(path for path in plan['paths'] if path['path_id'] == 'B')['command']['argv'] = [sys.executable, '-c', 'raise SystemExit(1)']
        self.t.freeze(plan)
        self.implement(['T1'], 'I1')
        self.execute_paths('BUILD1', 'build', ['B'], red='B')
        self.assertEqual(self.module()['phase'], 'testing')
        self.assertEqual(self.step()['operation'], 'diagnose')
        with self.assertRaisesRegex(Rejected, 'worker phase gate rejected'):
            self.f.call('assign', {'assignment_id': 'I2', 'role': 'implementer', 'instance_id': 'implementer', 'task_ids': ['T2'], 'path_ids': ['B', 'P2']})


class AwaitingAssemblyTests(unittest.TestCase):
    """A provider gets its build result at once; its static closure is neither run nor failed while its callers are unwritten."""
    def test_a_module_whose_callers_are_unwritten_is_built_and_then_waits_for_them(self):
        from unittest import mock
        import test_spec_closure
        from harmony_stage import build as stage_result
        c = test_spec_closure.SpecClosureTests(); c.setUp(); self.addCleanup(c.doCleanups)
        f = c.f
        with mock.patch.object(tv, 'awaits_assembly', return_value=True):
            c.split.prepare()
            step = f.state()['next_steps'][0]
            self.assertEqual((step['worker_role'], step['test_scope'], step['payload']['path_ids']), ('test-runner', 'build', ['B1']))
            self.assertIsNone(c.split.compile())  # the build ran; the fixture leaves its result to be submitted
            assignment = f.state()['modules']['M001']['assignments']['BUILD1']
            f.submit(stage_result(f.root, 'M001', 'BUILD1', c.split.receipts), assignment)  # the build alone: nothing else is due
            f.call('accept', {'assignment_id': 'BUILD1'})
            module = f.state()['modules']['M001']
            self.assertEqual((module['phase'], module['results']['B1']['quality'], 'S1' in module['results']), ('testing', 'green-passed', False))
            step = f.state()['next_steps'][0]
            self.assertEqual((step['operation'], step['ready'], step['reason']), (None, False, 'awaiting-assembly'))
        f.approve('0' * 64, 'LATER')  # any later event: the callers are written by now
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role'], step['test_scope'], step['payload']['path_ids']),
                         ('assign', 'test-runner', 'build', ['B1', 'S1']))
        self.assertEqual([path['path_id'] for path in tv.stage_paths(f.state()['modules']['M001'], {})], ['S1'])  # the build stays Green: only the closure runs


class RedirectionTests(unittest.TestCase):
    PROBE = ("import os, sys\nfrom pathlib import Path\n"
             "ok = (Path(os.environ['GRADLE_USER_HOME']) / 'init.d/sdd-storage.init.gradle').is_file() and bool(os.environ['SDD_RUNNER_DIR'])\n")

    def test_a_path_whose_own_script_builds_inherits_the_redirection(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        f.assign('test-runner', 'TEST1')
        adapter = f.base / 'probe.py'
        adapter.write_text(self.PROBE + "import argparse, json\np = argparse.ArgumentParser(); p.add_argument('--query-file'); p.add_argument('--result-file')\n"
                           "a = p.parse_args()\njson.dump({'assertions': [{'assertion_id': 'A1', 'expected': 2, 'actual': 2 if ok else 0, 'passed': ok}]}, open(a.result_file, 'w'))\n")
        receipt = json.loads(Path(execute_test.execute(f.root, 'M001', 'TEST1', 'P1', [sys.executable, str(adapter)], str(f.target), f.base / 'exec')['path']).read_text())
        self.assertEqual(json.loads(Path(receipt['result_ref']['path']).read_text())['assertions'][0]['passed'], True)

    def test_a_roles_own_run_uses_the_same_redirection_and_builds_outside_the_tree(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        base = Path(directory.name).resolve()
        tree = base / 'tree'; tree.mkdir()
        argv = [sys.executable, '-c', self.PROBE + "sys.exit(0 if ok and not os.path.exists('build') else 3)"]
        self.assertEqual(execute_test.selfcheck(argv, str(tree), str(base / 'check')), 0)
        self.assertTrue((base / 'check/cache/gradle/init.d/sdd-storage.init.gradle').is_file())
        self.assertEqual(os.listdir(tree), [])  # nothing of the run lands in the tree it ran in
        for output in (tree / 'out', base / 'check'):  # inside the tree; not new
            with self.subTest(output=output), self.assertRaisesRegex(Rejected, 'a new directory outside the tree it builds'):
                execute_test.selfcheck(argv, str(tree), str(output))


if __name__ == '__main__':
    unittest.main()
