"""A leaf plans against its provider's current plan. One that still cites a plan the provider gave up owes the citation
of the current one; the plan is accepted and the gap recorded until a plan no longer cites it."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_audit_closure
import test_decomposition
from contracts import digest


class SupersededCitationTests(unittest.TestCase):
    def test_a_leaf_that_cites_a_plan_its_provider_gave_up_owes_the_current_one(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(f.proposal(dependencies={'M002': ['M001']})); f.global_plan()
        plan = f.plan(); plan['module_id'] = 'M001'; f.attach_reuse(plan)
        first = f.ref('provider/v1/plan.json', plan)
        f.call('plan', {'plan_ref': first}, role='spec-designer', module='M001')
        f.call('decision', {'decision_id': 'M001', 'decision': 'approved', 'module_id': 'M001', 'subject_sha256': digest(plan),
                            'human_source_ref': f.ref('decision-M001.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'M001'}, module='M001')
        test_audit_closure.ClosureTests.implement(f, 'M001', 'I-M001')
        self.assertEqual(ledger.superseded_plans(f.state(), f.state()['modules']['M002']), {})  # one plan: nothing given up
        f.call('change', {'request_ref': f.ref('cr.md', 'the contract gains a field'), 'impact_ref': f.ref('impact.md', 'no task moves')}, module='M001')
        second = copy.deepcopy(plan); second['source_closure']['observable_result'] += ' (renewed)'
        f.call('plan', {'plan_ref': f.ref('provider/v2/plan.json', second)}, role='spec-designer', module='M001')
        gone = str(Path(first['path']).parent)
        self.assertEqual(ledger.superseded_plans(f.state(), f.state()['modules']['M002']), {'M001': [gone]})
        consumer = f.plan(); consumer['module_id'] = 'M002'; consumer['paths'][0]['path_id'] = 'P2'; consumer['tasks'][0]['path_ids'] = ['P2']
        f.attach_reuse(consumer)
        design = next(d for d in consumer['definitions'] if d['kind'] == 'design')
        design.update(f.ref('defs/design-M002.md', 'the entries are those of the provider plan at ' + gone + '/design.md'))
        f.call('plan', {'plan_ref': f.ref('consumer-plan.json', consumer)}, role='spec-designer', module='M002')  # accepted, owing
        gaps = ledger.status(f.root, 'step', 'M002')['open_issues']
        self.assertEqual([(g['kind'], g['summary']) for g in gaps], [('gap', 'cites a superseded plan of provider M001: ' + gone)])
        design.update(f.ref('defs/design-M002-current.md', 'the entries are those of the provider plan'))
        f.call('plan', {'plan_ref': f.ref('consumer-plan-2.json', consumer)}, role='spec-designer', module='M002')
        self.assertEqual(ledger.status(f.root, 'step', 'M002')['open_issues'], [])  # the plan that no longer cites it settles the gap


if __name__ == '__main__':
    unittest.main()
