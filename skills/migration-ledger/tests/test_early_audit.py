"""A deferred module is audited as soon as its dependency/consumer closure is settled; the rest keeps moving."""
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

    def test_independent_peer_keeps_working_during_the_early_audit(self):
        f = self.f
        self.iso.prepare_peers()                     # M002 frozen with code, still testing: not settled
        f.call('assign', {'assignment_id': 'T2', 'role': 'test-runner', 'instance_id': 'peer-tester'}, module='M002')
        self.defer_m001()
        f.call('problem-assign', {'assignment_id': 'PA1', 'instance_id': 'auditor', 'module_ids': ['M001']},
               role='global-orchestrator', module=None)
        s = f.state()
        self.assertEqual(s['audit_assignment']['closure'], ['M001'])
        steps = {step['module_id']: step for step in s['next_steps']}
        self.assertEqual(steps['M001']['reason'], 'await-auditor')
        self.assertNotEqual(steps['M002'].get('reason'), 'await-auditor')
        self.iso.finish_peer_test()                  # M002 submits, is accepted and completes meanwhile
        self.assertEqual(f.state()['modules']['M002']['phase'], 'completed')
        with self.assertRaisesRegex(Rejected, 'audit'):
            f.call('invalidate', {'reason': 'audit locked'})  # M001 itself stays locked
        with self.assertRaisesRegex(Rejected, 'audit'):
            f.call('audit-assign', {'assignment_id': 'FINAL', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)

    def test_consumer_with_a_busy_dependency_blocks_the_early_audit(self):
        f = self.f
        # M003 consumes M001 and M002; M002 is still testing, so M003 cannot be re-verified yet.
        original = self.iso.f.call
        def call(op, payload=None, **kwargs):
            result = original(op, payload, **kwargs)
            if op == 'register' and (payload or {}).get('module_id') == 'M002':
                original('register', {'module_id': 'M003', 'case_ids': ['C1'], 'dependencies': ['M001', 'M002'],
                                      'write_paths': [str(f.target / 'm3')]}, role='global-orchestrator', module=None)
            return result
        f.call = call
        self.iso.prepare_peers()
        f.call = original
        f.call('assign', {'assignment_id': 'T2', 'role': 'test-runner', 'instance_id': 'peer-tester'}, module='M002')
        self.defer_m001()
        self.assertNotEqual(f.state()['global_next_step']['operation'], 'problem-assign')
        with self.assertRaisesRegex(Rejected, 'audit closure'):
            f.call('problem-assign', {'assignment_id': 'PA1', 'instance_id': 'auditor', 'module_ids': ['M001']},
                   role='global-orchestrator', module=None)
        self.iso.finish_peer_test()  # once M002 settles, M001's closure is ready
        f.call('problem-assign', {'assignment_id': 'PA1', 'instance_id': 'auditor', 'module_ids': ['M001']},
               role='global-orchestrator', module=None)
        self.assertEqual(f.state()['audit_assignment']['closure'], ['M001', 'M002', 'M003'])


if __name__ == '__main__':
    unittest.main()
