"""Green code can need governance; review never fabricates a failed test."""
import copy
import json
from pathlib import Path
import unittest

import test_ledger
import audit_code_review as review
import test_audit_closure
import test_context_readiness
import test_split_testing
from contracts import Rejected, digest


class CodeReviewTests(unittest.TestCase):
    def fixture(self):
        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implement('M001', 'I1'); f.verify_module('M001', 'T1'); f.complete('M001')
        return f

    def finding(self, f):
        return {'finding_id': 'CR-M001-REUSE', 'source_module_id': 'M001', 'category': 'library-reuse',
                'affected_module_ids': ['M001'], 'path_id': None,
                'root_cause': {'category': 'code', 'summary': 'duplicate producer bypasses approved shared capability',
                               'confidence': 'confirmed', 'owner': 'M001', 'next_action': 'refactor-and-regress'},
                'analysis_ref': f.ref('reuse-review.md', 'Compared frozen T1, old source and target shared contract; same owner and acceptance.')}

    def test_green_still_requires_review_and_cannot_skip_governance(self):
        f = self.fixture(); before = copy.deepcopy(f.state()['modules']['M001']['results'])
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')
        with self.assertRaisesRegex(Rejected, 'audit-code-review required'):
            f.call('audit-assign', {'assignment_id': 'A1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        test_ledger.code_review(f, [self.finding(f)])
        self.assertEqual(f.state()['modules']['M001']['results'], before)
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-collect')
        with self.assertRaisesRegex(Rejected, 'governance findings'):
            f.call('audit-assign', {'assignment_id': 'A1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'erase unresolved'):
            test_ledger.code_review(f, [])

    def governance_round(self):
        f = self.fixture(); test_ledger.code_review(f, [self.finding(f)])
        f.call('audit-collect', {'batch_id': 'G1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = f.state()['audit_batch']; finding = b['findings']['CR-M001-REUSE']
        route = {**{k: finding[k] for k in ('finding_id', 'source_module_id', 'root_cause', 'analysis_ref')},
                 'action': 'fix', 'owner_module_ids': ['M001'], 'source_context': b['contexts']['M001'],
                 'owner_contexts': {'M001': b['contexts']['M001']}}
        f.call('audit-plan', {'plan_ref': f.ref('governance-plan.json', {'routes': [route]})}, role='auditor', module=None)
        f.call('audit-route-batch', {'review_ref': f.ref('route.md', 'same frozen task and owner')}, role='global-orchestrator', module=None)
        f.call('audit-work')
        with self.assertRaisesRegex(Rejected, 'Auditor cannot'):
            f.call('assign', {'assignment_id': 'BAD', 'role': 'fixer', 'instance_id': 'auditor'})
        f.implement('M001', 'F1', shared=2, fixer=True)
        with self.assertRaisesRegex(Rejected, 'verification incomplete'):
            f.call('audit-verdict', {'review_ref': f.ref('early.md', 'too early')}, role='auditor', module=None)
        f.verify_module('M001', 'T2'); f.complete('M001')
        f.call('audit-verdict', {'review_ref': f.ref('verdict.md', 'new execution reviewed')}, role='auditor', module=None)
        self.assertFalse(review.pending(f.state()))
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')
        test_ledger.code_review(f, [])
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-assign')
        self.assertEqual(len(f.state()['audit_code_review_history']), 1)
        return f

    def test_governance_fixer_testing_and_refreshed_review(self):
        self.governance_round()

    def test_governance_collects_before_existing_red_and_keeps_failure(self):
        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.cross_module_failure(); old = copy.deepcopy(f.state()['modules']['M002']['results'])
        item = self.finding(f); item['affected_module_ids'].append('M002')
        test_ledger.code_review(f, [item])
        f.call('audit-collect', {'batch_id': 'G1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = f.state()['audit_batch']
        self.assertEqual(set(b['findings']), {'CR-M001-REUSE'})
        self.assertEqual(f.state()['modules']['M002']['results'], old)
        route = {**{k: item[k] for k in ('finding_id', 'source_module_id', 'root_cause', 'analysis_ref')},
                 'action': 'fix', 'owner_module_ids': ['M001'], 'source_context': b['contexts']['M001'],
                 'owner_contexts': {'M001': b['contexts']['M001']}}
        f.call('audit-plan', {'plan_ref': f.ref('governance-plan.json', {'routes': [route]})}, role='auditor', module=None)
        self.assertEqual(f.state()['audit_batch']['work_modules'], ['M001', 'M002'])
        f.call('audit-route-batch', {'review_ref': f.ref('route.md', 'provider and consumer regression')}, role='global-orchestrator', module=None)
        with self.assertRaises(Rejected):
            f.call('audit-retest', module='M002')
        f.call('audit-work'); f.implement('M001', 'F1', shared=1, fixer=True)
        f.verify_module('M001', 'T3'); f.complete('M001')
        f.call('audit-retest', module='M002'); f.verify_module('M002', 'T4', consume=True)
        self.assertEqual(f.state()['audit_batch']['status'], 'awaiting-human')
        self.assertIn(item['finding_id'], f.state()['audit_batch']['human_issues'])

    def test_review_checks_identity_coverage_and_artifact_hash(self):
        f = self.fixture(); test_ledger.code_review(f)
        s = f.state(); report = json.loads(Path(s['audit_code_review']['report_ref']['path']).read_text())
        missing = copy.deepcopy(report); missing['modules'] = []
        with self.assertRaisesRegex(Rejected, 'every execution module'):
            f.call('audit-code-review', {'report_ref': f.ref('missing.json', missing)}, role='auditor', module=None)
        with self.assertRaisesRegex(Rejected, 'independent'):
            f.call('audit-code-review', {'report_ref': f.ref('author.json', report)}, role='auditor', instance='implementer', module=None)
        Path(report['modules'][0]['diff_refs'][0]['path']).write_text('changed evidence')
        self.assertFalse(review.current(f.state()))
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')

    def test_receipt_bound_to_review_and_no_automation_needed(self):
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.completed(); test_ledger.code_review(f)
        self.assertIn('audit-code-review', f.state()['context_acceptances'])
        self.assertTrue(review.current(f.state()))

    def test_change_inventory_required_projected_and_hash_bound(self):
        f = self.fixture(); test_ledger.code_review(f)
        s = f.state(); report = json.loads(Path(s['audit_code_review']['report_ref']['path']).read_text())
        missing = copy.deepcopy(report); missing.pop('change_inventory_ref')
        with self.assertRaisesRegex(Rejected, 'inventory reference required'):
            f.call('audit-code-review', {'report_ref': f.ref('no-inventory.json', missing)}, role='auditor', module=None)
        projected = json.loads((f.root / 'reports/migration-report.json').read_text())
        self.assertEqual(projected['code_governance']['change_inventory_ref'], report['change_inventory_ref'])
        self.assertIn(report['change_inventory_ref']['path'], (f.root / 'reports/migration-report.md').read_text())
        legacy = copy.deepcopy(s); legacy['audit_code_review'].pop('change_inventory_ref')
        self.assertFalse(review.current(legacy))
        Path(report['change_inventory_ref']['path']).write_text('changed inventory')
        self.assertFalse(review.current(f.state()))
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')

    def test_cannot_review_while_module_work_is_running(self):
        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        with self.assertRaisesRegex(Rejected, 'all module rounds'):
            test_ledger.code_review(f)

    def test_governance_automation_unavailable_never_repeats_fixer(self):
        fixture = test_split_testing.SplitTestingTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        f = fixture.f; fixture.prepare(); fixture.compile(); fixture.defer()
        item = self.finding(f); test_ledger.code_review(f, [item])
        f.call('audit-collect', {'batch_id': 'G1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = f.state()['audit_batch']
        route = {**{k: item[k] for k in ('finding_id', 'source_module_id', 'root_cause', 'analysis_ref')},
                 'action': 'fix', 'owner_module_ids': ['M001'], 'source_context': b['contexts']['M001'],
                 'owner_contexts': {'M001': b['contexts']['M001']}}
        f.call('audit-plan', {'plan_ref': f.ref('governance.json', {'routes': [route]})}, role='auditor', module=None)
        f.call('audit-route-batch', {'review_ref': f.ref('route.md', 'approved frozen correction')}, role='global-orchestrator', module=None)
        f.call('audit-work'); f.implement('M001', 'F1', shared=2, fixer=True)
        fixture.compile('BUILD2'); fixture.defer()
        f.call('audit-verdict', {'review_ref': f.ref('verdict.md', 'build passed, business not verified')}, role='auditor', module=None)
        self.assertEqual(f.state()['audit_batch']['unverified_findings'], [item['finding_id']])
        self.assertFalse(review.pending(f.state()))
        test_ledger.code_review(f, [])
        blocked = f.record(f.report('audit-testing', module=None, instance='auditor', blocked='test-environment'))
        f.raw('audit-unavailable', {'context_ref': blocked}, role='auditor', module=None)
        s = f.state()
        self.assertEqual(s['global_next_step']['reason'], 'completed-with-unverified-tests')
        self.assertEqual(s['modules']['M001']['total_fix_rounds'], 1)
        self.assertEqual(s['modules']['M001']['results']['P1']['quality'], 'yellow-blocked')
        self.assertTrue(review.deferred(s))

    def test_affected_consumer_deferral_is_not_resolved(self):
        import audit_closure
        b = {'routes': {'CR-1': {'source_module_id': 'M001', 'owner_module_ids': ['M001']}},
             'findings': {'CR-1': {'affected_module_ids': ['M001', 'M002']}},
             'dependencies': {'M001': [], 'M002': [], 'M003': ['M002'], 'M004': []}}
        self.assertEqual(audit_closure.finding_impact(b, 'CR-1'), {'M001', 'M002', 'M003'})
        b['routes']['CR-1'].update(finding_id='CR-1', action='fix')
        b['sources'] = {'M001': {}}
        s = {'modules': {mid: {'dependencies': deps} for mid, deps in b['dependencies'].items()}}
        audit_closure.build_graph(s, b)
        self.assertEqual(b['dependencies']['M002'], ['M001'])
        self.assertEqual(b['work_modules'], ['M001', 'M002', 'M003'])

    def test_persistent_governance_finding_requires_human_in_next_batch(self):
        f = self.governance_round()
        item = self.finding(f); test_ledger.code_review(f, [item])
        self.assertTrue(review.pending(f.state())[item['finding_id']]['requires_human'])
        f.call('audit-collect', {'batch_id': 'G2', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = f.state()['audit_batch']
        route = {**{k: item[k] for k in ('finding_id', 'source_module_id', 'root_cause', 'analysis_ref')},
                 'action': 'fix', 'owner_module_ids': ['M001'], 'source_context': b['contexts']['M001'],
                 'owner_contexts': {'M001': b['contexts']['M001']}}
        with self.assertRaisesRegex(Rejected, 'no second automatic fix'):
            f.call('audit-plan', {'plan_ref': f.ref('retry.json', {'routes': [route]})}, role='auditor', module=None)
        route.update(action='human', owner_module_ids=[], owner_contexts={})
        f.call('audit-plan', {'plan_ref': f.ref('human.json', {'routes': [route]})}, role='auditor', module=None)
        f.call('audit-route-batch', {'review_ref': f.ref('human-review.md', 'needs task/contract decision')}, role='global-orchestrator', module=None)
        self.assertEqual(f.state()['audit_batch']['status'], 'awaiting-human')
        b = f.state()['audit_batch']
        f.call('decision', {'decision_id': 'RELEASE', 'decision': 'approved', 'module_id': None,
                           'subject_sha256': digest(b['human_report']), 'human_source_ref': f.ref('human.md', 'approved replan')},
               role='host', module=None)
        f.call('audit-release', {'decision_id': 'RELEASE'}, role='global-orchestrator', module=None)
        f.call('invalidate', {'reason': 'human-approved revised implementation'})
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('recovered-plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'REFREEZE'); f.call('freeze', {'decision_id': 'REFREEZE'})
        f.implement('M001', 'I2', shared=3); f.verify_module('M001', 'T3'); f.complete('M001')
        with self.assertRaisesRegex(Rejected, 'erase unresolved'):
            test_ledger.code_review(f, [])
        resolution = {'finding_id': item['finding_id'], 'decision_id': 'RELEASE', 'reason': 'replanned and reverified',
                      'evidence_refs': [f.ref('recovered.md', 'independent review of revised scope and new binding')]}
        test_ledger.code_review(f, [], [resolution])
        self.assertFalse(review.pending(f.state()))
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-assign')
