"""MO may accept a diagnosis and dispatch the Fixer in one transaction; the Fixer's report on that diagnosis authorizes the fix."""
import unittest

import test_context_readiness
from contracts import Rejected


class MergedDiagnosisDispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        a, r = f.make_test_result(quality='red-bug')
        f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        self.diagnosis = f.ref('diag.md', 'compared failing value with source')
        f.raw('diagnose', {'diagnosis_ref': self.diagnosis, 'owner': 'M001',
                           'root_cause': {'category': 'code', 'summary': 'wrong value', 'confidence': 'confirmed',
                                          'owner': 'M001', 'next_action': 'fix'}}, role='diagnostician')

    def fixer_preflight(self, acknowledge=True):
        f = self.f
        report = f.report('fixing', instance='fixer')
        if not acknowledge:
            report['read_refs'] = [r for r in report['read_refs'] if r != self.diagnosis]
        return report

    def test_accept_and_dispatch_in_one_step_after_fixer_read_the_draft(self):
        f = self.f
        ref = f.record(self.fixer_preflight())  # Fixer reads the submitted diagnosis before MO accepts it
        f.raw('diagnosis-accept', {'assign': {'assignment_id': 'F1', 'role': 'fixer', 'instance_id': 'fixer', 'context_ref': ref}})
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['assignments']['F1']['role'], m['fix_rounds_used']), ('fixing', 'fixer', 1))
        self.assertEqual(m['diagnosis']['diagnosis_ref'], self.diagnosis)

    def test_accept_and_dispatch_before_the_fixer_reports(self):
        f = self.f
        f.raw('diagnosis-accept', {'assign': {'assignment_id': 'F1', 'role': 'fixer', 'instance_id': 'fixer'}})
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['fix_rounds_used']), ('fixing', 0))  # no round is spent before the Fixer can start
        f.record(self.fixer_preflight())
        m = f.state()['modules']['M001']
        self.assertEqual((m['fix_rounds_used'], m['fix_memory'][0]['assignment_id']), (1, 'F1'))

    def test_fixer_must_acknowledge_the_diagnosis(self):
        f = self.f
        with self.assertRaisesRegex(Rejected, 'mandatory input'):
            f.record(self.fixer_preflight(acknowledge=False))

    def test_failed_dispatch_leaves_nothing_accepted(self):
        f = self.f
        report = self.fixer_preflight()
        report['checks']['repair-history'] = {'status': 'blocked', 'summary': 'earlier attempts are not readable',
                                              'missing': ['fix memory'], 'owner': 'M001', 'next_action': 'restore the memory'}
        report['verdict'] = 'blocked'
        f.record(report)
        with self.assertRaisesRegex(Rejected, 'context blocked'):
            f.raw('diagnosis-accept', {'assign': {'assignment_id': 'F1', 'role': 'fixer', 'instance_id': 'fixer'}})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'testing')
        f.raw('diagnosis-accept')  # the two-step path still works
        self.assertEqual(f.state()['modules']['M001']['phase'], 'diagnosing')


if __name__ == '__main__':
    unittest.main()
