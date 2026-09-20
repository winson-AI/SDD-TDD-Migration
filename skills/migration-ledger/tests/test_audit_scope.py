"""Empty init paths remain recoverable; audit execution excludes valid Green paths."""
import copy
import unittest

import test_context_readiness
import test_audit_closure
import ledger
from contracts import Rejected, validate_result


class AuditScopeTests(unittest.TestCase):
    def fixture(self, kind=test_context_readiness.ContextReadinessTests):
        f = kind()
        call = f.call
        def empty_global(op, payload=None, **kwargs):
            if op == 'init':
                payload = {**payload, 'global_paths': []}
            return call(op, payload, **kwargs)
        f.call = empty_global
        f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def review(self, f):
        f.call('audit-assign', {'assignment_id': 'REVIEW', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        s = f.state(); scope = ledger.audit_scope(s)
        return {'schema_version': 1, 'kind': 'audit-review', 'run_id': 'demo', 'module_id': 'GLOBAL',
                'assignment_id': 'REVIEW', 'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'],
                'code_baseline': scope['code_baseline'], 'snapshot': s['audit_assignment']['snapshot'],
                'paths': [], 'execution_status': 'no-retest-needed',
                'review_ref': f.ref('review.md', 'Read all module evidence: no unresolved cases; no tests rerun.')}

    def test_empty_init_recovers_to_independent_review_without_automation_environment(self):
        f = self.fixture(); f.completed()
        s = f.state(); original = copy.deepcopy(s['modules']['M001']['results'])
        self.assertEqual(s['global_paths'], [])
        self.assertEqual(s['global_next_step']['operation'], 'audit-assign')
        self.assertEqual(s['global_next_step']['context_gate']['stage'], 'audit-verdict')
        self.assertEqual(s['global_next_step']['path_ids'], [])
        report = self.review(f)
        missing = copy.deepcopy(report); missing.pop('review_ref')
        with self.assertRaises(Rejected):
            f.raw('audit', {'report_ref': f.ref('missing-review.json', missing)}, role='auditor', module=None)
        f.raw('audit', {'report_ref': f.ref('review.json', report)}, role='auditor', module=None)
        s = f.state()
        self.assertEqual(s['quality'], 'green-passed')
        self.assertEqual(s['audit']['execution_status'], 'no-retest-needed')
        self.assertEqual(s['modules']['M001']['results'], original)
        self.assertEqual(s['global_next_step']['reason'], 'await-delivery-authorization')

    def test_empty_global_does_not_block_cross_module_repair_and_retest(self):
        f = self.fixture(test_audit_closure.ClosureTests)
        f.test_cross_module_fix_then_owner_and_source_verification()
        s = f.state()
        self.assertEqual(s['global_paths'], [])
        self.assertTrue(s['global_next_step']['ready'])
        self.assertEqual(ledger.audit_scope(s)['plan']['paths'], [])
        report = self.review(f)
        f.call('audit', {'report_ref': f.ref('review.json', report)}, role='auditor', module=None)
        self.assertEqual(f.state()['quality'], 'green-passed')

    def test_selector_keeps_red_yellow_and_excludes_green_and_review_cannot_hide_them(self):
        f = self.fixture(); f.completed(); s = f.state()
        m = s['modules']['M001']; original = m['plan']['paths'][0]
        for pid, quality in [('RED', 'red-bug'), ('YELLOW', 'yellow-blocked')]:
            m['plan']['paths'].append({**original, 'path_id': pid})
            m['results'][pid] = {'path_id': pid, 'quality': quality, 'test_run_id': pid}
        scope = ledger.audit_scope(s)
        self.assertEqual([p['path_id'] for p in scope['plan']['paths']], ['RED', 'YELLOW'])
        report = self.review(f)
        assignment = f.state()['audit_assignment']
        with self.assertRaisesRegex(Rejected, 'review cannot skip'):
            validate_result(report, scope, assignment)

    def test_empty_global_failed_repair_still_requires_human(self):
        f = self.fixture(test_audit_closure.ClosureTests)
        f.test_failed_consumer_verification_stops_for_human()
        self.assertEqual(f.state()['global_paths'], [])

    def test_optional_global_green_is_reused_until_its_baseline_changes(self):
        f = self.fixture(); f.completed(); s = f.state()
        base = ledger.audit_scope(s)['code_baseline']
        s['global_paths'] = [{**s['modules']['M001']['plan']['paths'][0], 'path_id': 'GP1'}]
        s['audit_results'] = {'GP1': {'quality': 'green-passed', 'test_run_id': 'prior-global', 'code_baseline': base}}
        self.assertEqual(ledger.audit_scope(s)['plan']['paths'], [])
        s['audit_results']['GP1']['code_baseline'] = 'previous-code'
        scope = ledger.audit_scope(s)
        self.assertEqual([p['path_id'] for p in scope['plan']['paths']], ['GP1'])
        self.assertTrue(scope['stale'])  # Expired Green must also link retest_of.
