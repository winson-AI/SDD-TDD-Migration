"""A run's artifacts have no size gate: an issue summary, a task's scope lines, a device gap's reason and the authored
documents are as long as their author needs; the task's completion is the criterion. The size ratchets bind the package."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import control_policy
import user_paths
from contracts import validate_plan
import test_dimensions
import test_issues
import test_user_paths


class NoSizeGateTests(unittest.TestCase):
    def test_an_issue_summary_is_as_long_as_it_needs_and_a_step_shows_its_head(self):
        t = test_issues.IssueTests(); t.setUp(); self.addCleanup(t.doCleanups)
        t.raise_issue(summary='y' * 1200)
        shown = t.step()['open_issues'][0]['summary']
        self.assertEqual((len(shown), shown[-1]), (200, '…'))  # the Ledger's own view stays small
        self.assertEqual(len(t.f.state()['issues']['I1']['summary']), 1200)  # the state keeps the line

    def test_a_task_states_its_scope_in_as_many_lines_as_it_needs(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f; d.root(); f.split(d.proposal()); f.global_plan()
        p = d.leaf_plan(); m = f.state()['modules']['M001']
        p['tasks'][0]['scope'].update({'in': ['x' * 900, 'b', 'c', 'd', 'e'], 'out': ['Orders', 'a', 'b', 'c', 'd']})
        validate_plan(p, m)

    def test_a_device_gap_states_its_reason_at_length(self):
        u = test_user_paths.PlanGateTests(); u.setUp(); self.addCleanup(u.doCleanups)
        paths = [u.path('C1', platform='android'), u.path('C2'), u.path('C3')]
        user_paths.plan_gate(u.module(), u.plan(*paths, device_gaps=[u.gap('C2', reason='r' * 2000)]))

    def test_no_document_size_check_remains(self):
        self.assertFalse(hasattr(control_policy, 'document_sizes'))
        self.assertFalse(hasattr(control_policy, 'REVIEW_BYTES'))


if __name__ == '__main__':
    unittest.main()
