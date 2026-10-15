"""What a leaf needs to start, and what is only observed: an Implementer is assigned tasks and their paths follow; tasks
cut by layer are a fact; a claim that the supplied cases are complete needs supplied cases."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import ledger
import project_context
from contracts import Rejected, digest
import test_ledger


class StartGateTests(unittest.TestCase):
    def test_an_implementer_is_assigned_tasks_and_their_paths_follow(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        s = f.state()
        ledger.apply(f.root, {'schema_version': 1, 'request_id': 'assign-by-task', 'run_id': 'demo', 'module_id': 'M001',
                              'expected_revision': s['modules']['M001']['revision'], 'operation': 'assign',
                              'payload': {'assignment_id': 'IMPL-1', 'role': 'implementer', 'instance_id': 'impl', 'task_ids': ['T1']}},
                     {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'})
        self.assertEqual(f.state()['modules']['M001']['assignments']['IMPL-1']['path_ids'], ['P1'])

    def test_tasks_cut_by_layer_are_a_fact_not_a_gate(self):
        def plan(tasks):
            return {'tasks': [{'task_id': tid, 'path_ids': pids} for tid, pids in tasks.items()],
                    'paths': [{'path_id': 'P%d' % n, 'kind': 'automation'} for n in range(1, 4)] + [{'path_id': 'B', 'kind': 'build'}]}
        s = {'modules': {'M001': {}}}
        decomposition.task_shape_facts(s, 'M001', plan({'T1': ['P1', 'P2', 'P3', 'B'], 'T2': ['P1', 'P2', 'P3', 'B'], 'T3': ['P2', 'B']}), sequence=5)
        fact = s['issues']['SLICE-M001-tasks-by-layer']
        self.assertEqual((fact['kind'], fact['applies_to'], fact['sequence'], fact['resolved']['M001']['recorded']), ('fact', ['M001'], 5, True))
        self.assertIn('3 of 3 behaviour paths bind at least half of its 3 tasks', fact['summary'])
        decomposition.task_shape_facts(s, 'M001', plan({'T1': ['P1', 'P2', 'P3', 'B'], 'T2': ['P1', 'P2', 'P3', 'B']}), sequence=9)
        self.assertEqual(s['issues']['SLICE-M001-tasks-by-layer']['sequence'], 5)  # recorded once
        s = {'modules': {'M001': {}}}
        decomposition.task_shape_facts(s, 'M001', plan({'T1': ['P1', 'B'], 'T2': ['P2', 'B'], 'T3': ['P3', 'B']}), sequence=5)  # by behaviour: the build path is shared by design
        decomposition.task_shape_facts(s, 'M001', plan({'T1': ['P1', 'P2', 'P3', 'B']}), sequence=6)  # one task: nothing to compare
        self.assertNotIn('issues', s)

    def test_a_completeness_claim_needs_the_supplied_cases(self):
        with self.assertRaisesRegex(Rejected, 'needs test_cases_path'):
            project_context.validate({'module_slicing': {'functional_use_cases_complete': True}})
        project_context.validate({'module_slicing': {'functional_use_cases_complete': True}, 'test_cases_path': '/cases/login.md'})
        project_context.validate({'module_slicing': {'functional_use_cases_complete': False}})


    def test_the_first_version_of_a_leaf_is_timed_and_its_refusals_counted(self):
        import tempfile
        import workflow_cost
        def event(op, mid, stamp, **sets):
            return {'operation': op, 'module_id': mid, 'timestamp': '2026-01-01T%s+00:00' % stamp, 'patch': {'set': {'modules': {'M001': sets}} if sets else {}}}
        events = [event('register', None, '00:00:00', case_ids=['C1']), event('plan', 'M001', '00:30:00'), event('freeze', 'M001', '01:00:00'),
                  event('assign', 'M001', '01:06:00', assignments={'T': {'role': 'test-runner'}}),
                  event('assign', 'M001', '01:12:00', assignments={'I': {'role': 'implementer'}}),
                  event('accept', 'M001', '03:00:00', quality='green-passed')]
        self.assertEqual(workflow_cost.timings(events, 'M001'),
                         {'minutes_to_plan': 30.0, 'minutes_to_freeze': 60.0, 'minutes_to_first_dispatch': 72.0, 'minutes_to_first_green': 180.0})
        self.assertEqual(workflow_cost.timings(events[:2], 'M001')['minutes_to_freeze'], None)
        self.assertEqual(workflow_cost.timings(events, 'M002'), {})
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'reports/rejections'; folder.mkdir(parents=True)
            for name, row in (('a', {'module_id': 'M001', 'attempts': '2'}), ('b', {'module_id': 'M001'}), ('c', {'module_id': None})):
                (folder / (name + '.json')).write_text(json.dumps(row))
            self.assertEqual(workflow_cost.rejections(tmp), {'M001': 3, 'GLOBAL': 1})
            s = {'modules': {'M001': {'case_ids': ['C1']}}, 'decisions': {}}
            row = workflow_cost.build(s, events, root=tmp)['modules']['M001']
            self.assertEqual((row['rejections'], row['minutes_to_first_dispatch']), (3, 72.0))
        self.assertNotIn('rejections', workflow_cost.build({'modules': {}, 'decisions': {}}, [])['modules'])



if __name__ == '__main__':
    unittest.main()
