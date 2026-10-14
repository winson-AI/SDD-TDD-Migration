"""A scaffold names the tasks that make its shell; its features are released on them, and the rest of it lands beside them."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import ledger
from contracts import Rejected


def plan(tasks, skeleton=None, kinds=None):
    return {'tasks': [{'task_id': t, 'path_ids': ['P' + t[1:]]} for t in tasks],
            'paths': [{'path_id': 'P' + t[1:], 'kind': (kinds or {}).get(t, 'unit')} for t in tasks],
            **({'skeleton_task_ids': skeleton} if skeleton is not None else {})}


class ThinScaffoldTests(unittest.TestCase):
    def test_a_scaffold_names_its_skeleton_and_a_feature_does_not(self):
        scaffold = {'kind': 'scaffold'}
        decomposition.check_skeleton(scaffold, plan(['T1', 'T2', 'T3']))  # a small scaffold is its own shell
        with self.assertRaisesRegex(Rejected, 'declares skeleton_task_ids'):
            decomposition.check_skeleton(scaffold, plan(['T1', 'T2', 'T3', 'T4']))
        decomposition.check_skeleton(scaffold, plan(['T1', 'T2', 'T3', 'T4'], ['T1', 'T2']))
        for bad, message in ((plan(['T1', 'T2', 'T3', 'T4'], ['T1', 'T2', 'T3', 'T4']), 'at most 3 tasks'),
                             (plan(['T1', 'T2', 'T3', 'T4'], ['T9']), 'at most 3 tasks'),
                             (plan(['T1', 'T2', 'T3', 'T4'], ['T1'], {'T1': 'automation'}), 'build, unit and static paths only: T1')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                decomposition.check_skeleton(scaffold, bad)
        with self.assertRaisesRegex(Rejected, 'only a scaffold'):
            decomposition.check_skeleton({'kind': 'feature'}, plan(['T1'], ['T1']))
        decomposition.check_skeleton({}, plan(['T1']))  # a leaf of no declared kind, declaring nothing

    def test_a_scaffold_is_there_for_its_features_once_its_skeleton_is_built(self):
        tasks = [{'task_id': t} for t in ('T1', 'T2', 'T3', 'T4')]
        paths = [{'path_id': 'B', 'kind': 'build'}, {'path_id': 'U', 'kind': 'unit'}]
        base = {'kind': 'scaffold', 'plan': {'tasks': tasks, 'paths': paths, 'skeleton_task_ids': ['T1', 'T2']}, 'code_baseline': 'c1'}
        green = {'B': {'quality': 'green-passed', 'stale': False}, 'U': {'quality': 'green-passed', 'stale': False}}
        self.assertFalse(ledger.provider_written({**base, 'accepted_task_ids': ['T1']}))
        self.assertFalse(ledger.provider_written({**base, 'accepted_task_ids': ['T1', 'T2']}))  # accepted, not yet built
        self.assertTrue(ledger.provider_written({**base, 'accepted_task_ids': ['T1', 'T2'], 'build_baseline': 'c1', 'results': green}))
        self.assertFalse(ledger.provider_written({**base, 'accepted_task_ids': ['T1', 'T2'], 'build_baseline': 'c0', 'results': green}))  # built on older code
        self.assertTrue(ledger.provider_written({**base, 'accepted_task_ids': ['T1', 'T2', 'T3', 'T4']}))  # everything written: as before
        plain = {'plan': {'tasks': tasks, 'paths': paths}, 'code_baseline': 'c1'}
        self.assertFalse(ledger.provider_written({**plain, 'accepted_task_ids': ['T1', 'T2']}))
        self.assertTrue(ledger.provider_written({**plain, 'accepted_task_ids': ['T1', 'T2', 'T3', 'T4']}))
        self.assertFalse(ledger.provider_written({**plain, 'accepted_task_ids': ['T1', 'T2', 'T3', 'T4'], 'code_baseline': None}))
        self.assertEqual(decomposition.skeleton(base), {'T1', 'T2'}); self.assertEqual(decomposition.skeleton(plain), set())


if __name__ == '__main__':
    unittest.main()
