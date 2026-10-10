"""A person decides a plan's decision boundary - its envelope and what it accepts; the MO reviews the rest of its text. The
cursor says who decides, a review can be recorded once a person has, and rewording an approved plan asks no one again."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import control_policy
import ledger
import test_ledger
import test_control_policy
from contracts import Rejected


class DecisionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_control_policy.ControlPolicyTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = f = t.f
        t.freeze(); f.implementation()  # code exists: from here the MO's own review cannot move what was approved
        f.call('change', {'request_ref': f.ref('cr.md', 'the SPEC allows one more alternative'), 'impact_ref': f.ref('impact.md', 'one task')})

    def submit(self, name, alternatives=('fallback',), design=None):
        f = self.f
        plan = copy.deepcopy(f.state()['modules']['M001']['plan'])
        plan['decision_envelope']['allowed_alternatives'] = list(alternatives)
        if design:
            plan['definitions'] = [{**f.ref('defs/design-reworded.md', design), 'kind': 'design'} if row['kind'] == 'design' else row
                                   for row in plan['definitions']]
        f.call('plan', {'plan_ref': f.ref(name, plan)}, role='spec-designer')
        return f.state()['modules']['M001']['plan_hash']

    def step(self):
        return self.f.state()['next_steps'][0]

    def test_the_cursor_says_a_person_decides_when_the_review_alone_would_be_refused(self):
        subject = self.submit('moved-boundary.json')
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['reason'], step['approval_kind'], step['detail'], step['approval_subject_sha256']),
                         ('freeze', False, 'human-decision-required', 'plan', 'decision boundary changed', subject))
        self.assertTrue(control_policy.human_required(step))
        with self.assertRaisesRegex(Rejected, 'decision boundary changed; human decision required'):
            self.f.call('plan-review', {'review_ref': self.t.review()})

    def test_a_plan_that_keeps_what_was_approved_is_still_the_mo_s_to_review(self):
        self.submit('same-boundary.json', alternatives=(), design='the same design, reworded')
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['reason']), ('plan-review', True, 'MO-technical-review'))
        self.assertFalse(control_policy.human_required(step))

    def test_once_a_person_has_decided_the_review_is_recorded_and_the_plan_freezes(self):
        f = self.f
        subject = self.submit('moved-boundary.json')
        f.approve(subject, 'D1')
        self.assertEqual(f.state()['decisions']['D1']['boundary_sha256'], control_policy.boundary_hash(f.state()['modules']['M001']))
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['payload']), ('freeze', True, {'decision_id': 'D1'}))
        review = self.t.review()
        f.call('plan-review', {'review_ref': review})  # its verdict is on the record, not only in what the reviewer handed back
        self.assertEqual(f.state()['modules']['M001']['plan_review_ref'], review)
        f.call('freeze', self.step()['payload'])
        state = f.state()
        self.assertEqual((state['modules']['M001']['phase'], state['decisions']['D1']['consumed']), ('frozen', True))

    def test_rewording_an_approved_plan_asks_no_one_again(self):
        f = self.f
        f.approve(self.submit('moved-boundary.json'), 'D1')
        reworded = self.submit('reworded.json', design='the same design, with the reviewer\'s wording')
        self.assertNotEqual(reworded, f.state()['decisions']['D1']['subject_sha256'])
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['reason']), ('plan-review', True, 'MO-technical-review'))  # the text is the MO's
        with self.assertRaisesRegex(Rejected, 'freezes the reworded plan with the MO plan review_ref'):
            f.call('freeze', {'decision_id': 'D1'})
        review = self.t.review()
        f.call('plan-review', {'review_ref': review})
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['payload']), ('freeze', True, {'decision_id': 'D1', 'review_ref': review}))
        f.call('freeze', step['payload'])
        state = f.state()
        self.assertEqual((state['modules']['M001']['phase'], list(state['decisions']), state['decisions']['D1']['consumed']), ('frozen', ['D1'], True))

    def test_an_approval_does_not_cover_a_boundary_it_did_not_see(self):
        f = self.f
        f.approve(self.submit('moved-boundary.json'), 'D1')
        self.submit('moved-again.json', alternatives=('fallback', 'another'))
        step = self.step()
        self.assertEqual((step['ready'], step['reason'], step['detail']), (False, 'human-decision-required', 'decision boundary changed'))
        with self.assertRaisesRegex(Rejected, 'approval missing/stale/wrong module'):
            f.call('freeze', {'decision_id': 'D1', 'review_ref': self.t.review()})
        with self.assertRaisesRegex(Rejected, 'human decision required'):
            f.call('plan-review', {'review_ref': self.t.review()})

    def test_what_was_approved_is_stated_by_the_ledger(self):
        f = self.f
        self.submit('moved-boundary.json')
        f.call('decision', {'decision_id': 'FORGED', 'decision': 'approved', 'module_id': 'M001', 'subject_sha256': '0' * 64,
                            'boundary_sha256': control_policy.boundary_hash(f.state()['modules']['M001']),
                            'human_source_ref': f.ref('other.txt', 'approved something else')}, role='host', module=None)
        self.assertNotIn('boundary_sha256', f.state()['decisions']['FORGED'])
        self.assertIsNone(ledger.covering(f.state(), f.state()['modules']['M001']))
        self.assertEqual(self.step()['reason'], 'human-decision-required')


if __name__ == '__main__':
    unittest.main()
