"""A provider that revises its SPEC keeps the code it accepted; a dependent that needs that code goes on against it."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_waves
from test_behavior_contract import review


class ProviderRevisingTests(unittest.TestCase):
    def test_a_revising_provider_with_accepted_code_is_still_there_for_its_dependents(self):
        tasks = {'plan': {'tasks': [{'task_id': 'T1'}, {'task_id': 'T2'}]}, 'code_baseline': 'c1', 'accepted_task_ids': ['T1', 'T2']}
        needs = {'behavior_review': {'verification': {'provider_inputs': [{'module_id': 'M001', 'required_stage': 'implemented'}]}}}
        s = {'modules': {'M001': test_waves.leaf('M001', **tasks, change_request={'request_ref': {}}),
                         'M002': test_waves.leaf('M002', 'M001', **needs)}, 'module_groups': {}}
        row, = ledger.providers(s, s['modules']['M002'])
        self.assertEqual((row['ready'], row['revising']), (True, True))

    def test_the_cursor_keeps_offering_the_dependents_planning_while_its_provider_revises(self):
        t = test_waves.WaveTests()
        import test_decomposition
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope()
        proposal = f.proposal(dependencies={'M002': ['M001']})
        for child in proposal['children']:
            child['behavior_review'] = review(f, child)
        proposal['children'][1]['behavior_review']['verification']['provider_inputs'][0]['required_stage'] = 'implemented'  # its code is enough
        f.split(proposal); f.global_plan()
        import test_audit_closure
        from contracts import digest
        plan = f.plan(); plan['module_id'] = 'M001'
        boundary = f.state()['modules']['M001']['behavior_review']['verification']  # the plan repeats the allocation's boundary
        plan['source_closure']['verification'] = boundary; plan['paths'][0]['fixture_contract_ref'] = boundary['fixture_contract_ref']
        f.attach_reuse(plan)
        f.call('plan', {'plan_ref': f.ref('plan-M001.json', plan)}, role='spec-designer', module='M001')
        f.call('decision', {'decision_id': 'M001', 'decision': 'approved', 'module_id': 'M001', 'subject_sha256': digest(plan),
                            'human_source_ref': f.ref('decision-M001.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'M001'}, module='M001')
        test_audit_closure.ClosureTests.implement(f, 'M001', 'I-M001')
        self.assertTrue(t.steps(f)['M002']['ready'])  # the provider's code is there; its verification is not needed
        f.complete_leaf('M001')
        self.assertTrue(t.steps(f)['M002']['ready'])
        f.call('change', {'request_ref': f.ref('cr.md', 'Revision of the provider'), 'impact_ref': f.ref('impact.md', 'Review')}, module='M001')
        step = t.steps(f)['M002']
        self.assertEqual((step['operation'], step['ready'], step.get('waiting_for')), ('plan', True, None))
        row, = ledger.status(f.root, 'step', 'M002')['providers']
        self.assertEqual((row['required_stage'], row['ready'], row['revising'], bool(row['code_baseline'])), ('implemented', True, True, True))


if __name__ == '__main__':
    unittest.main()
