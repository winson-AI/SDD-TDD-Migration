"""Structured fields state a thing in a few lines; the detail is in the documents and evidence they cite."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import project_context
import user_paths
from contracts import Rejected, validate_plan
import test_dimensions
import test_issues
import test_user_paths


class FieldCapTests(unittest.TestCase):
    def test_an_issue_summary_is_one_line_and_a_step_shows_its_head(self):
        t = test_issues.IssueTests(); t.setUp(); self.addCleanup(t.doCleanups)
        with self.assertRaisesRegex(Rejected, 'at most 400 characters'):
            t.raise_issue(summary='x' * 401)
        t.raise_issue(summary='y' * 400)
        shown = t.step()['open_issues'][0]['summary']
        self.assertEqual((len(shown), shown[-1]), (200, '…'))
        self.assertEqual(len(t.f.state()['issues']['I1']['summary']), 400)  # the state keeps the line

    def test_a_task_states_its_own_scope_in_a_few_lines(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f; d.root(); f.split(d.proposal()); f.global_plan()
        p = d.leaf_plan(); m = f.state()['modules']['M001']
        validate_plan(p, m)
        p['tasks'][0]['scope']['out'] = ['Orders', 'no history', 'no export', 'no sync']  # the module's exclusion does not count
        validate_plan(p, m)
        for change, message in (
            (lambda p: p['tasks'][0]['scope'].update(out=['Orders', 'a', 'b', 'c', 'd']), 'task scope out: at most 3 own lines'),
            (lambda p: p['tasks'][0]['scope'].update({'in': ['a', 'b', 'c', 'd']}), 'task scope in: at most 3 own lines'),
            (lambda p: p['tasks'][0]['scope'].update({'in': ['x' * 301]}), 'task scope in: at most 3 own lines of at most 300 characters'),
        ):
            bad = copy.deepcopy(p); change(bad)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                validate_plan(bad, m)

    def test_a_device_gap_states_its_reason_in_a_paragraph(self):
        u = test_user_paths.PlanGateTests(); u.setUp(); self.addCleanup(u.doCleanups)
        paths = [u.path('C1', platform='android'), u.path('C2'), u.path('C3')]
        user_paths.plan_gate(u.module(), u.plan(*paths, device_gaps=[u.gap('C2', reason='r' * 400)]))
        with self.assertRaisesRegex(Rejected, 'at most 400 characters'):
            user_paths.plan_gate(u.module(), u.plan(*paths, device_gaps=[u.gap('C2', reason='r' * 401)]))


if __name__ == '__main__':
    unittest.main()
