"""A root's split is drafted from its feature inventory: the orchestrator edits a draft instead of cutting from nothing."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import split_draft
import test_tree_binding as tb
from contracts import keyed


class SplitDraftTests(unittest.TestCase):
    def test_the_leaves_are_the_nodes_below_the_shared_root_with_small_ones_joined(self):
        features = keyed(tb.tree(), 'feature_id')
        drafted = split_draft.groups(features, set(tb.CASES), decomposition.LEAF_MIN_CASES, decomposition.LEAF_MAX_CASES)
        self.assertEqual(sorted(len(paths) for paths, _ in drafted), [1, 2])  # the two-case intro joins one of the four-case leaves
        self.assertTrue(any('Login/Intro' in paths and len(paths) == 2 for paths, _ in drafted))
        t = tb.TreeBindingTests(methodName='runTest'); t.setUp(); self.addCleanup(t.tearDown)
        children = [tb.leaf(f'M00{n}', sorted({c for fid in fids for c in features[fid]['case_ids']}), *paths)
                    for n, (paths, fids) in enumerate(drafted, 2)]
        t.judge(children, t.inventory())  # the draft is a split the Ledger accepts: nodes, cases and coverage agree

    def test_nodes_sharing_a_case_are_one_leaf_and_a_wide_node_splits_one_level_down(self):
        f = lambda fid, path, cases: tb.feature(fid, path, cases)
        features = keyed([f('A1', 'App/A/x', [f'A{i}' for i in range(1, 20)]), f('A2', 'App/A/y', [f'B{i}' for i in range(1, 20)]),
                          f('C', 'App/C', ['C1', 'C2', 'C3', 'B1']), f('D', 'App/D', ['D1', 'D2', 'D3', 'D4'])], 'feature_id')
        cases = {c for row in features.values() for c in row['case_ids']}
        drafted = split_draft.groups(features, cases, 3, 30)
        self.assertEqual(sorted(sorted(paths) for paths, _ in drafted), [['App/A/x'], ['App/A/y', 'App/C'], ['App/D']])

    def test_a_small_root_gets_no_draft_and_a_marked_split_is_refused(self):
        import test_decomposition
        from contracts import Rejected
        d = test_decomposition.DecompositionTests(methodName='runTest'); d.setUp(); self.addCleanup(d.doCleanups)
        d.root_scope()
        out = split_draft.write(d.root, 'M010', d.base / 'staging/module-orchestrator/draft')
        self.assertIsNone(out['draft'])  # one case: the root is confirmed as one leaf
        self.assertEqual(d.state()['next_steps'][0]['planning_outcomes'], ['atomic-leaf'])
        plan = d.proposal(); plan['children'][0]['name'] = split_draft.todo('叶子名称')
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton field left in'):
            d.call('decompose', {'plan_ref': d.ref('marked-split.json', plan)}, module='M010')


if __name__ == '__main__':
    unittest.main()
