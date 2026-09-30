"""Budget renewal preserves independent blocker ownership and resume gates."""
import copy
import unittest

import test_audit_closure
import test_module_isolation
import ledger
from contracts import Rejected, digest


class BudgetRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = test_module_isolation.ModuleIsolationTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups); fixture.prepare_peers()
        self.f = f = fixture.f
        a, result = f.make_test_result(quality='red-bug')
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', 'implementation defect'),
                           'owner': 'M001', 'root_cause': 'code'}, role='diagnostician')
        f.call('diagnosis-accept')
        f.implementation(role='fixer', aid='FIX1')

    def budget_subject(self, m):
        return digest({'module_id': 'M001', 'revision': m['revision'],
                       'recovery_cycle': m['recovery_cycle'], 'additional_rounds': 1})

    def assert_external_blocker(self, kind):
        f = self.f
        f.call('suspend', {'kind': kind, 'reason': 'independent prerequisite unresolved',
                           'root_cause': 'product choice' if kind == 'human' else 'tool unavailable',
                           'owner': 'human' if kind == 'human' else 'host'})
        before = f.state(); m = before['modules']['M001']; blocker = copy.deepcopy(m['blocked'])
        f.approve(self.budget_subject(m), 'BUDGET')
        with self.assertRaisesRegex(Rejected, 'resume needs current blocker decision'):
            f.call('resume', {'decision_id': 'BUDGET'})
        f.call('recover', {'decision_id': 'BUDGET', 'additional_rounds': 1})
        after = f.state(); recovered = after['modules']['M001']
        self.assertEqual(recovered['blocked'], blocker)
        self.assertEqual(recovered['phase'], 'waiting-human')
        self.assertEqual(recovered['fix_budget'], 2)
        self.assertEqual(recovered['fix_rounds_used'], 1)
        self.assertEqual(recovered['total_fix_rounds'], 1)
        self.assertEqual(recovered['recovery_cycle'], 1)
        self.assertEqual(recovered['results'], m['results'])
        self.assertEqual(after['modules']['M002'], before['modules']['M002'])
        self.assertIn('M002', after['ready_modules'])
        step = next(s for s in after['next_steps'] if s['module_id'] == 'M001')
        self.assertEqual(step['reason'], 'human-decision-required')
        self.assertFalse(step['ready'])
        with self.assertRaisesRegex(Rejected, 'resume needs current blocker decision'):
            f.call('resume', {'decision_id': 'BUDGET'})
        f.approve(digest(blocker), 'RESUME')
        f.call('resume', {'decision_id': 'RESUME'})
        resumed = f.state()['modules']['M001']
        self.assertIsNone(resumed['blocked'])
        self.assertEqual(resumed['phase'], blocker['resume_phase'])
        self.assertEqual(resumed['fix_budget'], 2)
        self.assertEqual(resumed['results'], m['results'])

    def test_human_blocker_requires_its_own_resume_decision(self):
        self.assert_external_blocker('human')

    def test_tooling_blocker_requires_its_own_resume_decision(self):
        self.assert_external_blocker('tooling')

    def test_dependency_blocker_and_release_gate_survive_budget_recovery(self):
        # Isolate the transition with an unavailable provider; use real frozen evidence.
        s = ledger.read_events(self.f.root)[0]; m = s['modules']['M001']
        m['dependencies'] = ['M002']
        s['context_readiness_required'] = True
        actor = {'role': 'module-orchestrator', 'instance_id': 'mo'}
        ledger.mutate(s, {'operation': 'suspend', 'module_id': 'M001', 'payload': {
            'kind': 'dependency', 'reason': 'provider unavailable', 'root_cause': 'missing upstream',
            'owner': 'global-orchestrator'}}, actor, [])
        blocker = copy.deepcopy(m['blocked']); peer = copy.deepcopy(s['modules']['M002'])
        s['decisions']['BUDGET'] = {'module_id': 'M001', 'subject_sha256': self.budget_subject(m), 'consumed': False}
        ledger.mutate(s, {'operation': 'recover', 'module_id': 'M001', 'payload': {
            'decision_id': 'BUDGET', 'additional_rounds': 1}}, actor, [])
        self.assertEqual(m['blocked'], blocker)
        self.assertEqual(m['phase'], 'waiting-dependency')
        self.assertEqual(m['fix_budget'], 2)
        self.assertEqual(s['modules']['M002'], peer)
        self.assertNotIn('dependency_release', m)
        with self.assertRaisesRegex(Rejected, 'dependencies not complete'):
            ledger.resume_guard(s, m, {'decision_id': 'BUDGET'})
        with self.assertRaisesRegex(Rejected, 'dependencies not complete'):
            ledger.mutate(s, {'operation': 'dependency-ready', 'module_id': 'M001'},
                          {'role': 'global-orchestrator', 'instance_id': 'go'}, [])
        # Real provider verification alone does not replace GO's explicit release.
        test_audit_closure.ClosureTests.verify_module(self.f, 'M002', 'PEER_TEST')
        test_audit_closure.ClosureTests.complete(self.f, 'M002')
        s['modules']['M002'] = ledger.read_events(self.f.root)[0]['modules']['M002']
        with self.assertRaisesRegex(Rejected, 'Global dependency release missing/stale'):
            ledger.resume_guard(s, m, {'decision_id': 'BUDGET'})
        ledger.mutate(s, {'operation': 'dependency-ready', 'module_id': 'M001'},
                      {'role': 'global-orchestrator', 'instance_id': 'go'}, [])
        ledger.mutate(s, {'operation': 'resume', 'module_id': 'M001'}, actor, [])
        self.assertIsNone(m['blocked'])
        self.assertEqual(m['phase'], blocker['resume_phase'])
        self.assertEqual(m['fix_budget'], 2)

    def test_unblocked_recovery_keeps_existing_phase_and_budget_semantics(self):
        for diagnosis in (None, {'root_cause': 'accepted diagnosis'}):
            with self.subTest(diagnosis=bool(diagnosis)):
                s = ledger.read_events(self.f.root)[0]; m = s['modules']['M001']
                m['diagnosis'] = diagnosis; m['no_progress_rounds'] = s['max_no_progress_rounds']
                peer = copy.deepcopy(s['modules']['M002']); results = copy.deepcopy(m['results'])
                s['decisions']['BUDGET'] = {'module_id': 'M001', 'subject_sha256': self.budget_subject(m), 'consumed': False}
                ledger.mutate(s, {'operation': 'recover', 'module_id': 'M001', 'payload': {
                    'decision_id': 'BUDGET', 'additional_rounds': 1}},
                    {'role': 'module-orchestrator', 'instance_id': 'mo'}, [])
                self.assertIsNone(m['blocked'])
                self.assertEqual(m['phase'], 'diagnosing' if diagnosis else 'testing')
                self.assertEqual((m['fix_budget'], m['fix_rounds_used'], m['total_fix_rounds']), (2, 1, 1))
                self.assertEqual((m['recovery_cycle'], m['no_progress_rounds']), (1, 0))
                self.assertTrue(s['decisions']['BUDGET']['consumed'])
                self.assertEqual(m['results'], results)
                self.assertEqual(s['modules']['M002'], peer)
