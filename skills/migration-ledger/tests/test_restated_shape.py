"""A re-split that restates a registered leaf's shape is a rebind, not a new cut: the slicing standard judges new and
re-cut children, and does not retroactively re-judge dependency edges and case sets the Ledger already accepted."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
from contracts import Rejected

VERIFIED = {'verification': {'provider_inputs': {'M007': 'verified', 'M008': 'implemented'}}}
IMPLEMENTED = {'verification': {'provider_inputs': {'M007': 'implemented', 'M008': 'implemented'}}}


def held(mid, deps, cases, review=None):
    return {'module_id': mid, 'dependencies': list(deps), 'case_ids': list(cases),
            **({'behavior_review': review} if review is not None else {})}


def state():
    """The live-run shape: an in-flight allocation accepted before the scaffold rule, feature -> feature edges and all."""
    return {'dimension_slicing_required': False, 'modules': {
        'M007': held('M007', ['M003'], ['C7']),
        'M008': held('M008', [], ['C8']),
        'M009': held('M009', ['M007', 'M008'], ['C9a', 'C9b'], VERIFIED)}}


PARENT = {'module_id': 'M001', 'dimension_analysis_ref': None}


def restated(mid, deps=None, cases=None, review=None):
    m = state()['modules'][mid]
    return held(mid, deps if deps is not None else m['dependencies'],
                cases if cases is not None else m['case_ids'],
                review if review is not None else m.get('behavior_review'))


class RestatedShapeTests(unittest.TestCase):
    def test_an_inflight_leaf_restated_with_its_shape_is_not_rejudged(self):
        # the repro: M009's provider stage moved inside behavior_review (an ALLOCATION_KEY, so registered() is False);
        # its dependency edges and case set did not move, so the shape rules have nothing new to judge
        moved = restated('M009', review=IMPLEMENTED)
        self.assertFalse(decomposition.registered(state(), moved))
        self.assertTrue(decomposition.restated_shape(state(), moved))
        decomposition.standard(state(), PARENT, [restated('M007'), restated('M008'), moved], {})  # no rejection

    def test_a_new_leaf_still_may_not_depend_on_features(self):
        fresh = held('M010', ['M007', 'M008'], ['C10'])
        with self.assertRaisesRegex(Rejected, 'a leaf depends only on scaffold leaves'):
            decomposition.standard(state(), PARENT, [restated('M007'), restated('M008'), fresh], {})

    def test_a_recut_leaf_is_judged_again(self):
        with self.subTest('moved edge'):
            recut = restated('M009', deps=['M007', 'M008', 'M003'])
            self.assertFalse(decomposition.restated_shape(state(), recut))
            with self.assertRaisesRegex(Rejected, 'a leaf depends only on scaffold leaves'):
                decomposition.standard(state(), PARENT, [restated('M007'), restated('M008'), recut], {})
        with self.subTest('moved cases'):
            recut = restated('M009', cases=['C9a'])
            self.assertFalse(decomposition.restated_shape(state(), recut))
            with self.assertRaisesRegex(Rejected, 'a leaf depends only on scaffold leaves'):
                decomposition.standard(state(), PARENT, [restated('M007'), restated('M008'), recut], {})

    def test_the_standard_still_binds_a_fresh_split(self):
        s = {'dimension_slicing_required': False, 'modules': {}}
        scaffold = {'module_id': 'M002', 'dependencies': [], 'case_ids': ['C2'], 'kind': 'scaffold'}
        feature = {'module_id': 'M011', 'dependencies': ['M002'], 'case_ids': ['C11'], 'kind': 'feature'}
        decomposition.standard(s, PARENT, [scaffold, feature], {})  # feature on scaffold only: fine
        big = {'module_id': 'M012', 'dependencies': ['M002'], 'case_ids': ['C%d' % i for i in range(21)], 'kind': 'feature'}
        with self.assertRaisesRegex(Rejected, 'at most 20 cases'):
            decomposition.standard(s, PARENT, [scaffold, big], {})


if __name__ == '__main__':
    unittest.main()
