"""A worker that cannot go on says so on the bus: the cursor names what is blocked and, when the cause is in the frozen plan,
the step that revises it; a blocked report written before its subject moved still hands its dispatch back."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_ledger
import test_context_readiness
from contracts import Rejected


class BlockedReportTests(unittest.TestCase):
    def setUp(self):
        self.c = c = test_context_readiness.ContextReadinessTests(); c.setUp(); self.addCleanup(c.doCleanups)
        c.prepare()
        c.raw('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'})

    def step(self):
        return self.c.state()['next_steps'][0]

    def test_a_block_in_the_frozen_plan_points_to_the_step_that_revises_it(self):
        c = self.c
        c.record(c.report('coding', blocked='task-trace'))
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['reason'], step['blocked_checks'], step['recovery_action']),
                         ('assign', False, 'context-blocked', ['task-trace'], 'change-or-realloc-request'))
        c.raw('change', {'request_ref': c.ref('cr.md', 'the task names a file the plan never traced'), 'impact_ref': c.ref('impact.md', 'one task')})
        self.assertEqual((c.state()['modules']['M001']['phase'], self.step()['operation']), ('change-review', 'plan'))

    def test_a_block_outside_the_plan_names_no_change(self):
        c = self.c
        c.record(c.report('coding', blocked='permissions-tools'))
        step = self.step()
        self.assertEqual((step['reason'], step['blocked_checks']), ('context-blocked', ['permissions-tools']))
        self.assertNotIn('recovery_action', step)  # the host provides what is missing; the plan stands

    def test_a_blocked_report_written_before_its_subject_moved_still_hands_the_dispatch_back(self):
        c = self.c
        report = c.report('coding', blocked='task-trace')
        report['subject_sha256'] = '0' * 64  # what the worker read at its dispatch is no longer what the run holds
        ref = c.record(report)
        module = c.state()['modules']['M001']
        self.assertEqual((module['assignments']['I1']['closed'], module['assignments']['I1']['declined_ref'], module['phase']), (True, ref, 'frozen'))
        step = self.step()
        self.assertEqual((step['operation'], step['ready']), ('assign', True))  # it holds nothing: the next worker reads what is current
        self.assertNotIn('blocked_checks', step)

    def test_only_a_worker_s_blocked_report_may_be_out_of_date(self):
        c = self.c
        ready = c.report('coding')
        ready['subject_sha256'] = '0' * 64
        with self.assertRaisesRegex(Rejected, 'context subject stale'):  # a ready report authorizes work: it reads what is current
            c.record(ready)
        planning = c.report('planning', blocked='assigned-scope')
        planning['subject_sha256'] = '0' * 64
        with self.assertRaisesRegex(Rejected, 'context subject stale'):  # there is no dispatch for it to hand back
            c.record(planning)
        self.assertFalse(c.state()['modules']['M001']['assignments']['I1']['closed'])


if __name__ == '__main__':
    unittest.main()
