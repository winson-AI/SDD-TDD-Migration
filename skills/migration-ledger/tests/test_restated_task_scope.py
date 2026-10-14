"""A CR rebind restates an accepted task's scope on refreshed refs; a prose limit added since is rule debt, not a gate.
Mirrors restated_shape: the SCOPE prose limit binds new and re-cut task scopes, not a verbatim restatement of the
scope the Ledger already accepted (the same doctrine the freeze binding applies via contracts.intact())."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dimensions
from contracts import Rejected

OVER = ['line one of the task business scope', 'line two', 'line three', 'line four']  # 4 > SCOPE_ITEMS(3)


def task(scope_in, tid='T1'):
    return {'task_id': tid, 'scope': {'in': list(scope_in), 'out': [], 'write_paths': ['/t/x.kt']}, 'path_ids': ['P1']}


def module(held_plan_task=None):
    m = {'scope': {'out': []}, 'write_paths': ['/t']}
    if held_plan_task is not None:
        m['plan'] = {'tasks': [held_plan_task]}
    return m


def plan(t):
    return {'tasks': [t], 'dimension_analysis_ref': None, 'paths': [{'path_id': 'P1'}]}


class RestatedTaskScopeTests(unittest.TestCase):
    def test_predicate(self):
        t = task(OVER)
        self.assertTrue(dimensions.restated_task_scope(module(task(OVER)), t))       # verbatim restatement
        self.assertFalse(dimensions.restated_task_scope(module(), t))                # no held plan (fresh leaf)
        self.assertFalse(dimensions.restated_task_scope(module(task(['short'])), t))  # re-cut scope
        self.assertFalse(dimensions.restated_task_scope(module(task(OVER, tid='T9')), t))  # different task id

    def test_a_fresh_overlong_scope_is_judged(self):
        with self.assertRaisesRegex(Rejected, 'at most 3 own lines'):
            dimensions.task_analyses(plan(task(OVER)), module(), {}, {})

    def test_a_recut_overlong_scope_is_judged(self):
        with self.assertRaisesRegex(Rejected, 'at most 3 own lines'):
            dimensions.task_analyses(plan(task(OVER)), module(task(['short'])), {}, {})

    def test_a_restated_overlong_scope_is_grandfathered(self):
        # SCOPE must NOT fire; it proceeds past the prose limit and stops later (dimension uncertainty), proving the
        # grandfather let the accepted prose through instead of re-judging it under the newer limit.
        with self.assertRaises(Rejected) as ctx:
            dimensions.task_analyses(plan(task(OVER)), module(task(OVER)), {}, {})
        self.assertNotIn('at most 3 own lines', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
