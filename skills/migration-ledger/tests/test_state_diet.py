"""The module state carries frozen contracts by reference and digest, not as copies of their text."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import control_policy
import ledger
from contracts import Rejected
import test_control_policy


class StateDietTests(unittest.TestCase):
    def setUp(self):
        self.t = test_control_policy.ControlPolicyTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def revise(self, edit):
        t = self.t; f = self.f; t.freeze(); f.implementation()
        old = f.state()['modules']['M001']
        f.call('change', {'request_ref': f.ref('cr.md', 'Revision'), 'impact_ref': f.ref('impact.md', 'Review')})
        self.assertEqual(f.state()['modules']['M001']['change_request']['previous_plan']['plan'], old['plan'])  # read by the revalidation
        p = copy.deepcopy(old['plan']); edit(p)
        f.call('plan', {'plan_ref': f.ref('revised-plan.json', p)}, role='spec-designer')
        return old

    def test_the_history_names_the_previous_plan_by_reference_and_hash(self):
        t = self.t; f = self.f
        old = self.revise(lambda p: p['paths'][0]['expected_assertions'].append({'assertion_id': 'MORE', 'expected': 'extra coverage'}))
        f.call('plan-review', {'review_ref': t.review()})
        f.call('freeze', f.state()['next_steps'][0]['payload'])
        history = f.state()['modules']['M001']['change_request_history'][-1]
        self.assertEqual((history['previous_plan']['plan_ref'], history['previous_plan']['plan_hash']), (old['plan_ref'], old['plan_hash']))
        self.assertNotIn('plan', history['previous_plan'])
        self.assertLess(len(json.dumps(history['previous_plan'])), 1_000)

    def test_the_frozen_acceptance_is_kept_as_digests_and_still_guards_every_expectation(self):
        t = self.t; f = self.f; t.freeze()
        m = f.state()['modules']['M001']
        self.assertNotIn('approved_test_paths', m)
        self.assertEqual(set(m['approved_acceptance_digests']), {p['path_id'] for p in m['plan']['paths']})
        for frozen in m['approved_acceptance_digests'].values():
            self.assertEqual(len(frozen['shape']), 64); self.assertTrue(all(len(d) == 64 for d in frozen['assertions'].values()))
        self.assertNotIn('expected', json.dumps(m['approved_acceptance_digests']))  # digests, not the assertions' text
        self.assertEqual(control_policy.acceptance_digests(m['plan']['paths']), m['approved_acceptance_digests'])

    def test_a_weakened_assertion_is_still_refused_and_an_added_one_passes(self):
        t = self.t; f = self.f
        self.revise(lambda p: p['paths'][0]['expected_assertions'].__setitem__(0, {**p['paths'][0]['expected_assertions'][0], 'expected': 'weakened'}))
        with self.assertRaisesRegex(Rejected, 'acceptance changed'):
            f.call('plan-review', {'review_ref': t.review()})
        p = copy.deepcopy(f.state()['modules']['M001']['change_request']['previous_plan']['plan'])
        p['paths'][0]['expected_assertions'].append({'assertion_id': 'MORE', 'expected': 'extra coverage'})
        f.call('plan', {'plan_ref': f.ref('added-plan.json', p)}, role='spec-designer')
        f.call('plan-review', {'review_ref': t.review()})
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'freeze')

    def test_the_global_projection_names_plans_by_reference(self):
        t = self.t; f = self.f; t.freeze()
        projected = json.loads((f.root / 'ledger/global.json').read_text())
        module = json.loads((f.root / 'ledger/modules/M001.json').read_text())
        self.assertNotIn('plan', projected['modules']['M001']); self.assertEqual(projected['modules']['M001']['plan_ref'], module['plan_ref'])
        self.assertEqual(module['plan'], f.state()['modules']['M001']['plan'])
        self.assertEqual(ledger.global_projection(f.state(), projected['last_sequence'])['modules'], projected['modules'])


if __name__ == '__main__':
    unittest.main()
