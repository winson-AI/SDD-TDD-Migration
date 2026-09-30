"""Real Ledger coverage of audit-only recovery and omitted-attempt evidence retention."""
import copy
import unittest
from pathlib import Path

import test_ledger
import test_split_testing
from contracts import Rejected
import migration_report
import test_validation as tv


class AuditResumeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.split = test_split_testing.SplitTestingTests()
        self.split.setUp(); self.addCleanup(self.split.doCleanups)
        self.f = self.split.f

    def complete(self):
        f = self.f
        self.split.prepare(); self.split.compile()
        a, r = f.make_test_result(); f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('complete', {'dod_ref': f.ref('dod.md', 'Every module path passed'), 'checks_passed': True})

    def audit_defer(self):
        f = self.f; test_ledger.code_review(f)
        blocked = f.record(f.report('audit-testing', module=None, instance='auditor', blocked='test-environment'))
        f.raw('audit-unavailable', {'context_ref': blocked}, role='auditor', module=None)
        return blocked

    def test_global_only_deferral_resumes_from_new_ready_context(self):
        f = self.f; self.complete(); self.audit_defer()
        self.assertEqual(f.state()['global_next_step']['reason'], 'completed-with-unverified-tests')
        ready = f.record(f.report('audit-testing', module=None, instance='auditor'))
        step = f.state()['global_next_step']
        self.assertEqual(step['operation'], 'audit-assign')
        self.assertTrue(step['ready'])
        self.assertEqual(step['path_ids'], ['GP1'])
        self.assertEqual(step['payload']['context_ref'], ready)
        f.raw(step['operation'], {**step['payload'], 'assignment_id': 'RESTORED'}, role='global-orchestrator', module=None)
        self.assertEqual(f.state()['audit_assignment']['path_ids'], ['GP1'])

    def test_blocked_stale_or_already_consumed_context_cannot_trigger_resume(self):
        f = self.f; self.complete(); self.audit_defer()
        f.record(f.report('audit-testing', module=None, instance='auditor', blocked='test-environment'))
        self.assertEqual(f.state()['global_next_step']['reason'], 'completed-with-unverified-tests')
        ready = f.record(f.report('audit-testing', module=None, instance='auditor'))
        self.assertIsNotNone(tv.audit_resume_context(f.state()))
        self.audit_defer()  # New deferral consumes preflights already present.
        self.assertIsNone(tv.audit_resume_context(f.state()))
        newer = f.record(f.report('audit-testing', module=None, instance='auditor'))
        Path(newer['path']).write_text('{}')
        self.assertIsNone(tv.audit_resume_context(f.state()))

    def test_omission_preserves_executed_yellow_and_report_evidence(self):
        f = self.f; self.split.prepare(); self.split.compile()
        a, r = f.make_test_result(quality='yellow-blocked')
        f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        old = copy.deepcopy(f.state()['modules']['M001']['results']['P1'])
        self.split.defer()
        current = f.state()['modules']['M001']['results']['P1']
        self.assertFalse(current['executed']); self.assertEqual(current['assertions'], [])
        self.assertEqual(current['last_execution'], old)
        self.assertEqual(current['retest_of'], old['test_run_id'])
        # A second omission carries one execution, not a recursive history chain.
        ready = f.record(f.report('testing')); f.raw('automation-resume', {'context_ref': ready})
        self.split.defer(); self.audit_defer()
        s = f.state(); report = migration_report.build(f.root, s, 1)
        row = next(row for row in report['paths'] if row['path_id'] == 'P1')
        self.assertTrue(row['executed']); self.assertFalse(row['attempt_executed'])
        self.assertFalse(row['last_execution_stale'])
        self.assertEqual(row['last_execution']['assertions'], old['assertions'])
        self.assertNotIn('last_execution', row['last_execution'])
        self.assertIn(old['execution_receipt'], row['evidence_refs'])
        self.assertEqual(row['quality'], 'yellow-blocked')
        self.assertIn('最近真实执行', migration_report.render(report))

    def test_stale_execution_does_not_become_current_evidence(self):
        previous = {'executed': True, 'execution_receipt': {'path': 'old'}, 'code_baseline': 'old'}
        self.assertIsNone(tv.retained_execution(previous, 'new'))


class GlobalPathSubsetTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def init(self, case_id='C1'):
        f = self.f; s = f.state(); f.root = f.base / ('subset-' + case_id)
        f.call('init', {**{k: s[k] for k in ('target_root', 'legacy_root', 'requirement_ids', 'global_spec', 'new_architecture')},
            'case_ids': ['C1', 'C2'], 'dimension_slicing_required': False, 'split_testing_required': False,
            'context_readiness_required': False,
            'global_paths': [{'path_id': 'GP1', 'case_id': case_id, 'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}]}]}, role='host')

    def test_global_paths_may_cover_subset_but_global_plan_still_requires_all_cases(self):
        self.init(); f = self.f
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1', 'C2'], 'write_paths': [str(f.target / 'm1')]},
               role='global-orchestrator', module=None)
        s = f.state()
        plan = {'global_spec': s['global_spec'], 'new_architecture': s['new_architecture'],
                'boundary_review': {'issues': []}, 'requirement_owners': {'R1': ['M001']},
                'case_owners': {'C1': ['M001', 'GLOBAL']}}
        with self.assertRaisesRegex(Rejected, 'case'):
            f.call('global-plan', {'plan_ref': f.ref('incomplete-global.json', plan),
                                  'review_ref': f.ref('review.md', 'Reviewed coverage')}, role='global-orchestrator', module=None)
        plan['case_owners']['C2'] = ['M001']
        f.call('global-plan', {'plan_ref': f.ref('complete-global.json', plan),
                              'review_ref': f.ref('review.md', 'Reviewed coverage')}, role='global-orchestrator', module=None)

    def test_unregistered_global_case_rejected(self):
        with self.assertRaisesRegex(Rejected, 'not registered'):
            self.init('UNKNOWN')


if __name__ == '__main__':
    unittest.main()
