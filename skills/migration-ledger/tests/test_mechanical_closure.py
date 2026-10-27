"""Steps whose every fact the Ledger already checks take no model turn: a freeze on a recorded review or decision, a
completion the DoD guard admits and a parent summary whose children settled are submitted by advance."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import check_ref, digest
import ledger
import test_decomposition
import test_ledger

MO = {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}


class MechanicalClosureTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def step(self):
        return self.f.state()['next_steps'][0]

    def test_a_leaf_freezes_on_its_decision_and_completes_on_its_guard_without_a_model_turn(self):
        f = self.f
        f.global_plan()
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1')
        step = self.step()
        self.assertEqual((step['operation'], step['mechanical'], step['must_read']), ('freeze', True, []))
        out = ledger.advance(f.root, MO, 'M001')
        self.assertEqual([a['operation'] for a in out['applied']][:2], ['freeze', 'assign'])
        self.assertEqual(f.state()['modules']['M001']['freeze_id'] is not None, True)
        assignment = out['applied'][1]['assignment_id']
        a = f.state()['modules']['M001']['assignments'][assignment]
        source = f.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True); source.write_text('value = 2\n')
        from contracts import file_ref
        import test_ledger as tl
        refs = [file_ref(source)]
        f.call('submit', {'assignment_id': assignment, 'fencing_token': a['fencing_token'], 'result_ref': f.ref('impl.json', {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': assignment,
                  'actor_instance_id': a['instance_id'], 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': tl.baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(source)]}], 'production_binding_evidence': f.ref('binding.txt', 'real binding reviewed'),
                  'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')}})}, role='implementer', instance=a['instance_id'])
        self.assertTrue(self.step().get('mechanical'))  # code its author compiled: accept re-runs every check, nothing to judge
        f.call('accept', {'assignment_id': assignment})
        a, result = f.make_test_result()
        f.submit(result, a)
        self.assertEqual(self.step()['operation'], 'accept')
        out = ledger.advance(f.root, MO, 'M001')
        self.assertEqual([x['operation'] for x in out['applied']], ['accept', 'complete'])
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['quality']), ('completed', 'green-passed'))
        record = json.loads(next((Path(f.root) / 'reports/dod').glob('M001-*.json')).read_text())
        self.assertEqual((record['written_by'], record['paths']['P1']['quality'], record['tasks']), ('ledger', 'green-passed', ['T1']))

    def test_a_review_freeze_waits_for_a_person_when_one_must_decide(self):
        f = self.f
        f.global_plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', f.plan())}, role='spec-designer')
        step = self.step()
        self.assertFalse(step.get('mechanical'))  # nothing recorded yet: a review or a decision comes first
        self.assertEqual(ledger.advance(f.root, MO, 'M001')['applied'], [])


class MechanicalSummaryTests(unittest.TestCase):
    def test_a_parent_whose_children_settled_is_summarized_by_the_ledger(self):
        t = test_decomposition.DecompositionTests(methodName='runTest'); t.setUp(); self.addCleanup(t.doCleanups)
        t.root_scope(); t.split(); t.global_plan()
        for mid in ('M001', 'M002'):
            t.prepare_leaf(mid); t.complete_leaf(mid)
        step = next(x for x in t.state()['next_steps'] if x.get('module_id') == 'M010')
        self.assertEqual((step['operation'], step['mechanical'], step['must_read']), ('module-summary', True, []))
        out = ledger.advance(t.root, MO, 'M010')
        self.assertEqual([x['operation'] for x in out['applied']], ['module-summary'])
        group = t.state()['module_groups']['M010']
        record = json.loads(check_ref(group['summary_ref']).read_text())
        self.assertEqual((record['written_by'], sorted(record['leaves'])), ('ledger', ['M001', 'M002']))


if __name__ == '__main__':
    unittest.main()
