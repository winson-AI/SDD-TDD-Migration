"""Every step says whether it waits for a person; the report says what each human decision was used for and what
planning each leaf cost."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import control_policy
import migration_report
import workflow_cost
import test_ledger


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def step(self):
        return self.f.state()['next_steps'][0]

    def test_a_step_waits_for_a_person_only_for_a_reason_that_needs_one(self):
        for step, expected in (({'ready': False, 'reason': 'human-decision-required'}, True),
                               ({'ready': True, 'reason': 'human-decision-required'}, False),  # the decision is there
                               ({'ready': False, 'reason': 'run-approval-required'}, True),
                               ({'ready': False, 'reason': 'await-delivery-authorization'}, True),
                               ({'ready': False, 'reason': 'worker-running'}, False),
                               ({'ready': False, 'reason': 'MO-plan-review-required'}, False),  # the roles' own review
                               ({'ready': True, 'reason': None}, False)):
            self.assertIs(control_policy.human_required(step), expected, step)

    def test_planning_and_the_mo_reviewed_freeze_ask_nobody(self):
        f = self.f; f.global_plan()
        self.assertEqual((self.step()['operation'], self.step()['human_required']), ('plan', False))
        f.call('plan', {'plan_ref': f.ref('plan.json', f.plan())}, role='spec-designer')
        step = self.step()
        self.assertIn(step['operation'], ('plan-review', 'freeze'))
        self.assertIn('approval_subject_sha256', step)  # what an approval would bind is named, and none is asked for
        self.assertFalse(step['human_required'])

    def test_a_blocker_only_a_person_releases_says_so_until_the_decision_exists(self):
        f = self.f
        f.call('suspend', {'kind': 'human', 'reason': 'need decision', 'root_cause': 'ambiguous input', 'owner': 'human'})
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['human_required']), ('resume', False, True))
        f.approve(step['approval_subject_sha256'], 'RESUME')
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['human_required']), ('resume', True, False))

    def test_delivery_waits_for_a_person(self):
        f = self.f; f.test_green_flow_and_independent_global_audit()
        step = f.state()['global_next_step']
        self.assertEqual((step['reason'], step['human_required']), ('await-delivery-authorization', True))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def test_each_human_decision_is_listed_with_what_it_was_used_for(self):
        f = self.f; f.prepare()  # D1 approves the freeze
        f.call('suspend', {'kind': 'human', 'reason': 'need decision', 'root_cause': 'ambiguous input', 'owner': 'human'})
        f.approve(f.state()['next_steps'][0]['approval_subject_sha256'], 'RESUME')
        f.call('resume', {'decision_id': 'RESUME'})
        f.approve('0' * 64, 'SPARE')  # recorded and never used
        state = f.state()
        self.assertEqual({did: d.get('used_for') for did, d in state['decisions'].items()},
                         {'D1': 'freeze', 'RESUME': 'resume', 'SPARE': None})
        cost = workflow_cost.build(state, workflow_cost.journal(f.root))
        self.assertEqual(cost['human_by_purpose'], {'freeze': 1, 'resume': 1, 'unused': 1})
        rows = {row['decision_id']: row for row in cost['human_touches']}
        self.assertEqual((rows['RESUME']['module_id'], rows['RESUME']['reason']), ('M001', 'need decision'))
        self.assertIsNone(rows['D1']['reason'])
        markdown = migration_report.render(migration_report.build(f.root, state, state['last_sequence']))
        self.assertIn('| RESUME | M001 | resume | need decision |', markdown)
        self.assertIn('人工介入（按用途）', markdown)

    def test_the_planning_a_leaf_cost_is_shown_next_to_its_size(self):
        f = self.f; f.prepare()
        state = f.state()
        row = workflow_cost.build(state, workflow_cost.journal(f.root))['modules']['M001']
        plan = state['modules']['M001']['plan']
        self.assertEqual((row['cases'], row['tasks']), (len(state['modules']['M001']['case_ids']), len(plan['tasks'])))
        documents, size = workflow_cost.plan_volume(plan)
        self.assertEqual((row['plan_documents'], row['plan_bytes']), (documents, size))
        self.assertGreaterEqual(documents, len(plan['definitions']))  # at least the six-piece itself, each file once
        self.assertGreater(size, 0)
        markdown = migration_report.render(migration_report.build(f.root, state, state['last_sequence']))
        self.assertIn(f"| M001 | {row['cases']} | {row['tasks']} | {documents} | {size} |", markdown)
        self.assertEqual(workflow_cost.plan_volume(None), (0, 0))


if __name__ == '__main__':
    unittest.main()
