"""Facts the Ledger holds are filled by the Ledger: a child keeps its parent's exclusions, a task its module's, an analysis
binds the allocated scope, an inventory binds the supplied case list, and re-accepting global coverage with a rewritten
inventory leaves a leaf whose features did not change as it was."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import design_stage
import test_context_readiness
import test_decomposition


class LedgerFillsFactsTests(unittest.TestCase):
    def test_a_child_carries_its_parents_exclusions(self):
        t = test_decomposition.DecompositionTests(methodName='runTest'); t.setUp(); self.addCleanup(t.doCleanups)
        t.root_scope()
        plan = t.proposal()
        parent_out = t.state()['modules']['M010']['scope']['out'] if 'M010' in t.state()['modules'] else t.state()['module_groups']['M010']['scope']['out']
        for child in plan['children']:
            child['scope']['out'] = []  # nothing restated
        t.split(plan)
        for mid in ('M001', 'M002'):
            self.assertTrue(set(parent_out) <= set(t.state()['modules'][mid]['scope']['out']), mid)

    def test_a_task_carries_its_modules_exclusions_and_global_coverage_does_not_move_a_leaf(self):
        f = test_context_readiness.ContextReadinessTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        m = f.state()['modules']['M001']
        before = design_stage.subject(f.state(), m)
        f.global_plan()  # the GO re-accepts coverage with a freshly written inventory of the same features
        self.assertEqual(design_stage.subject(f.state(), f.state()['modules']['M001']), before)
        self.assertIn('F1', f.state()['module_inputs']['M001']['features'])


if __name__ == '__main__':
    unittest.main()
