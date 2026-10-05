"""Host audit waits for the complete registry while unrelated modules keep moving."""
import unittest

import test_ledger
import test_module_isolation
import test_workflow
from contracts import Rejected, digest


class EarlyAuditTests(unittest.TestCase):
    def setUp(self):
        self.iso = test_module_isolation.ModuleIsolationTests()
        self.iso.setUp(); self.addCleanup(self.iso.doCleanups)
        self.f = self.iso.f

    def defer_m001(self):
        f = self.f
        a, result = f.make_test_result(quality='red-bug')
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        test_workflow.WorkflowTests.diagnose(f)
        f.implementation(role='fixer', aid='F1')
        a, retry = f.make_test_result(aid='RETRY', quality='red-bug', previous=result['paths'][0]['test_run_id'])
        f.submit(retry, a); f.call('accept', {'assignment_id': 'RETRY'})
        test_workflow.WorkflowTests.defer(f)

    def test_independent_peer_continues_while_host_audit_waits(self):
        f = self.f; self.iso.prepare_peers()
        f.call('assign', {'assignment_id': 'T2', 'role': 'test-runner', 'instance_id': 'peer-tester'}, module='M002')
        self.defer_m001()
        self.iso.assert_auditor_waits()
        self.assertFalse(f.state().get('audit_assignment'))
        self.iso.finish_peer_test()
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')

    def test_old_policy_metadata_cannot_enable_early_audit(self):
        import ledger
        f = self.f; self.iso.prepare_peers(); self.defer_m001()
        state = f.state()
        for marker in (None, 1, 2, 99):
            state['control_policy_version'] = marker
            self.assertNotEqual(ledger.routing(state)['global_next_step']['operation'], 'problem-assign')
            with self.assertRaises(Rejected):
                f.call('problem-assign', {'assignment_id': 'PA', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
