"""A leaf is a sub-business flow: not a screen, not a branch, and not a whole module either."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
from contracts import Rejected


def child(mid, cases, kind=None, deps=(), anchor=None):
    return {'module_id': mid, 'case_ids': ['C%d' % n for n in range(cases)], 'dependencies': list(deps),
            **({'kind': kind} if kind else {}), **({'anchor_ui': anchor} if anchor is not None else {})}


class FlowSliceTests(unittest.TestCase):
    def setUp(self):
        self.s = {'modules': {}, 'module_groups': {}, 'dimension_slicing_required': False}
        self.parent = {'module_id': 'M010', 'case_ids': ['C%d' % n for n in range(40)]}

    def judge(self, *children, parent=None):
        decomposition.standard(self.s, parent or self.parent, list(children), {})

    def test_a_leaf_holds_a_flows_worth_of_cases(self):
        self.judge(child('M001', 3), child('M002', 20), child('M003', 30))
        with self.assertRaisesRegex(Rejected, 'at least 3 cases: merge it into the flow'):
            self.judge(child('M001', 2))
        with self.assertRaisesRegex(Rejected, 'at most 30 cases: split it by sub-flow'):
            self.judge(child('M001', 31))
        self.judge(child('M001', 1), parent={'module_id': 'M010', 'case_ids': ['C0', 'C1']})  # a parent of two cases cannot give three
        self.judge(child('M001', 1, kind='scaffold'), child('M002', 5, deps=['M001']))  # a scaffold holds what it serves

    def test_a_re_split_is_judged_again_in_full(self):
        # one version doctrine: what the Ledger holds unchanged is not judged again; a child restated with anything of its
        # allocation moved (here the provider stage inside behavior_review) answers to every current rule
        held = {'M007': child('M007', 3, deps=['M003']), 'M008': child('M008', 3),
                'M009': {**child('M009', 3, deps=['M007', 'M008']), 'behavior_review': {'verification': {'provider_inputs': {'M007': 'verified'}}}}}
        self.s['modules'] = {mid: dict(m) for mid, m in held.items()}
        self.judge(*held.values())  # restated verbatim: nothing to judge
        moved = {**held['M009'], 'behavior_review': {'verification': {'provider_inputs': {'M007': 'implemented'}}}}
        with self.assertRaisesRegex(Rejected, 'a leaf depends only on scaffold leaves'):
            self.judge(held['M007'], held['M008'], moved)

    def test_a_wide_leaf_and_a_parent_of_many_features_are_facts_not_refusals(self):
        self.judge(child('M001', 25))
        fact = self.s['issues']['SLICE-M001-wide']
        self.assertEqual((fact['kind'], fact['applies_to'], fact['resolved']['M010']['recorded']), ('fact', ['M010'], True))
        self.judge(*[child('M%03d' % n, 5) for n in range(1, 8)])
        self.assertIn('splits into 7 feature leaves (over 6)', self.s['issues']['SLICE-M010-features']['summary'])
        s = {'modules': {}, 'module_groups': {}, 'dimension_slicing_required': False}
        decomposition.standard(s, self.parent, [child('M001', 25)], {}, record=False)  # a re-judgement under current rules records nothing
        self.assertNotIn('issues', s)

    def test_the_cursor_flags_a_wide_leaf_and_a_parent_of_many_features(self):
        s = {'modules': {'M%03d' % n: {'module_id': 'M%03d' % n, 'dependencies': [], 'case_ids': ['C%d' % c for c in range(25 if n == 1 else 4)]} for n in range(1, 9)},
             'module_groups': {'M010': {'children': ['M%03d' % n for n in range(1, 9)]}}}
        signals = decomposition.slicing_signals(s)
        self.assertIn('wide-leaf', signals['M001']['flags']); self.assertNotIn('wide-leaf', signals['M002']['flags'])
        self.assertEqual(signals['M010'], {'feature_leaves': 8, 'flags': ['many-features']})


if __name__ == '__main__':
    unittest.main()
