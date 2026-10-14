"""A reviewer sees, before any verdict, every freeze gate the plan still fails - the Ledger lists them on the module
after the plan and after the review - and a review is a verdict, the blocking defects, the issues it recorded and the
gates still failing, in eight kilobytes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
from contracts import Rejected, digest


class ReviewShapeTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()

    def test_the_gates_a_plan_still_fails_are_listed_on_the_module_after_the_plan_and_after_the_review(self):
        f = self.f
        f.call('issue', {'issue_id': 'STOP', 'kind': 'defect', 'summary': 'as planned the password is shown in clear text',
                         'applies_to': ['M001'], 'blocks': True}, role='module-orchestrator', module=None)
        plan = f.plan(); f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        gates = ledger.status(f.root, 'step', 'M001')['module']['review_gates']
        self.assertEqual([g['gate'] for g in gates], ['issues'])  # reported with the plan, before anyone reviews
        self.assertRegex(gates[0]['reason'], 'blocking issue open for this module: STOP')
        f.approve(digest(plan), 'D1')
        review = f.ref('review.json', {'schema_version': 1, 'plan_hash': f.state()['modules']['M001']['plan_hash'], 'reviewer_instance_id': 'module-orchestrator',
                                       'semantic_change': False, 'authorization_change': False, 'unresolved_questions': [], 'recorded_issue_ids': ['STOP'],
                                       'reason': 'the defect stands', 'evidence_refs': [f.ref('review.md', 'verdict: hold; STOP blocks')]})
        f.call('plan-review', {'review_ref': review}, role='module-orchestrator')
        self.assertEqual([g['gate'] for g in f.state()['modules']['M001']['review_gates']], ['issues'])  # and again after the review
        f.call('issue-resolve', {'issue_id': 'STOP', 'module_id': 'M001', 'evidence_ref': f.ref('fixed.md', 'masked now')}, role='spec-designer', module=None)
        f.call('freeze', {'decision_id': 'D1'})
        self.assertNotIn('review_gates', f.state()['modules']['M001'])  # frozen: nothing is failing any more

    def test_a_review_carries_as_much_evidence_as_it_needs(self):
        f = self.f  # a run's artifacts have no size gate; the task's completion is the criterion
        plan = f.plan(); f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1')
        review = f.ref('long-review.json', {'schema_version': 1, 'plan_hash': f.state()['modules']['M001']['plan_hash'], 'reviewer_instance_id': 'module-orchestrator',
                                            'semantic_change': False, 'authorization_change': False, 'unresolved_questions': [], 'recorded_issue_ids': [],
                                            'reason': 'reviewed', 'evidence_refs': [f.ref('narrative.md', 'x' * 9_000)]})
        f.call('plan-review', {'review_ref': review}, role='module-orchestrator')
        self.assertEqual(f.state()['modules']['M001']['plan_review_ref'], review)


if __name__ == '__main__':
    unittest.main()
