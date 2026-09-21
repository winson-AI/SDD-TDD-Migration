"""Real Ledger operations exercise preflight ownership, freshness and recovery."""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_ledger
import test_audit_closure
import test_decomposition
import ledger
import workflow
import context_readiness as cr
from contracts import Rejected, digest
from execute_test import execute


class ContextReadinessTests(unittest.TestCase):
    ref = test_ledger.FlowTests.ref
    state = test_ledger.FlowTests.state
    plan = test_ledger.FlowTests.plan
    global_plan = test_ledger.FlowTests.global_plan
    prepare = test_ledger.FlowTests.prepare
    approve = test_ledger.FlowTests.approve
    assign = test_ledger.FlowTests.assign
    submit = test_ledger.FlowTests.submit
    implementation = test_ledger.FlowTests.implementation
    make_test_result = test_ledger.FlowTests.make_test_result
    implement = test_audit_closure.ClosureTests.implement
    complete = test_audit_closure.ClosureTests.complete
    cross_module_failure = test_audit_closure.ClosureTests.cross_module_failure
    route = test_audit_closure.ClosureTests.route
    root_scope = test_decomposition.DecompositionTests.root_scope
    proposal = test_decomposition.DecompositionTests.proposal
    split = test_decomposition.DecompositionTests.split

    def setUp(self):
        self.auto_context = True
        test_ledger.FlowTests.setUp(self)

    def raw(self, *args, **kwargs):
        return test_ledger.FlowTests.call(self, *args, **kwargs)

    def report(self, stage, module='M001', instance=None, draft=None, blocked=None):
        s = self.state()
        actor = {'role': cr.ROLES[stage], 'instance_id': instance or cr.ROLES[stage]}
        refs = cr.input_refs(s, module, stage) + ([draft] if draft else [])
        proof = self.ref(f'context-evidence-{self.n}.md', 'Inspected fixture inputs, no external dependency; scope and fixture contract understood.')
        checks = {name: {'status': 'ready', 'summary': 'Reviewed ' + name + ' against fixture contract', 'evidence_refs': [proof]}
                  for name in cr.CHECKS[stage]}
        if blocked:
            checks[blocked] = {'status': 'blocked', 'summary': 'Required input is unavailable',
                               'missing': ['fixture credentials'], 'owner': 'host', 'next_action': 'provide fixture credentials'}
        result = {'schema_version': 1, 'run_id': s['run_id'], 'module_id': module, 'stage': stage,
                  'producer': actor, 'subject_sha256': cr.subject(s, module, stage),
                  'checks': checks, 'read_refs': refs, 'verdict': 'blocked' if blocked else 'ready'}
        if draft:
            result['draft_ref'] = draft
        if stage in ('testing', 'audit-testing'):
            result['execution'] = {'argv': getattr(self, 'test_argv', [sys.executable, str(self.base / 'adapter.py')]), 'cwd': str(self.target),
                                   'environment_ref': self.ref('environment.md', 'Fixture environment and test data available')}
        return result

    def record(self, report):
        ref = self.ref(f'context-report-{self.n}.json', report)
        self.raw('context-submit', {'report_ref': ref}, role=report['producer']['role'],
                 instance=report['producer']['instance_id'], module=report['module_id'])
        return ref

    def call(self, op, payload=None, role='module-orchestrator', module='M001', instance=None, request=None):
        p = copy.deepcopy(payload or {})
        if op == 'init':
            p.pop('context_readiness_required', None)  # Exercise the new default.
        stage = cr.requirement(op, p, self.state() if op == 'audit-assign' else None)
        if self.auto_context and stage and op not in ('freeze', 'decompose-accept'):
            producer = p.get('instance_id') if op in ('assign', 'audit-assign', 'problem-assign') else instance or role
            report = self.report(stage, module, producer, p.get('report_ref') if op == 'audit-code-review' else p.get('plan_ref'))
            p['context_ref'] = self.record(report)
        return self.raw(op, p, role=role, module=module, instance=instance, request=request)

    def completed(self):
        self.prepare(); self.implementation()
        a, result = self.make_test_result()
        self.submit(result, a); self.call('accept', {'assignment_id': a['assignment_id']})
        self.call('complete', {'dod_ref': self.ref('dod.md', 'all paths complete'), 'checks_passed': True})

    def verify_module(self, mid, aid, consume=False):
        self.test_argv = [sys.executable, str(self.base / f'adapter-{aid}.py')]
        try:
            return test_audit_closure.ClosureTests.verify_module(self, mid, aid, consume)
        finally:
            del self.test_argv

    def test_default_on_and_missing_global_plan_receipt_is_rejected(self):
        self.assertTrue(self.state()['context_readiness_required'])
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(self.target / 'm2')]},
                     role='global-orchestrator', module=None)
        self.auto_context = False
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.global_plan()
        self.assertIsNone(self.state()['global_plan'])

    def test_environment_changed_after_assignment_prevents_process_start(self):
        self.prepare(); self.implementation()
        report = self.report('testing')
        ref = self.record(report)
        self.raw('assign', {'assignment_id': 'TEST', 'role': 'test-runner', 'instance_id': 'test-runner', 'context_ref': ref})
        Path(report['execution']['environment_ref']['path']).write_text('device/build changed')
        out = self.base / 'stale-environment'
        with self.assertRaises(Rejected):
            execute(self.root, 'M001', 'TEST', 'P1', report['execution']['argv'], str(self.target), out)
        self.assertFalse(out.exists())

    def test_full_green_flow_and_independent_final_audit(self):
        test_ledger.FlowTests.test_green_flow_and_independent_global_audit(self)

    def test_blocked_context_does_not_assign_or_spend_budget_and_can_be_replaced(self):
        self.prepare()
        ref = self.record(self.report('coding', blocked='permissions-tools'))
        before = self.state()['modules']['M001']
        with self.assertRaisesRegex(Rejected, 'context blocked'):
            self.raw('assign', {'assignment_id': 'I1', 'instance_id': 'implementer', 'role': 'implementer', 'context_ref': ref})
        after = self.state()['modules']['M001']
        self.assertEqual(before['assignments'], after['assignments'])
        self.assertEqual(before['fix_rounds_used'], after['fix_rounds_used'])
        self.assertEqual(self.state()['next_steps'][0]['reason'], 'context-readiness-required')
        self.implementation()
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')

    def test_worker_identity_and_authoritative_inputs_are_required(self):
        self.prepare()
        report = self.report('coding'); report['read_refs'] = []
        with self.assertRaisesRegex(Rejected, 'mandatory input'):
            self.record(report)
        ref = self.record(self.report('coding', instance='worker-A'))
        with self.assertRaisesRegex(Rejected, 'another worker'):
            self.raw('assign', {'assignment_id': 'I1', 'instance_id': 'worker-B', 'role': 'implementer', 'context_ref': ref})
        with self.assertRaisesRegex(Rejected, 'producer identity'):
            self.raw('context-submit', {'report_ref': ref}, role='implementer', instance='worker-B')

    def test_new_blocked_receipt_supersedes_old_ready_receipt(self):
        self.prepare()
        ready = self.record(self.report('coding'))
        self.record(self.report('coding', blocked='interfaces-ownership'))
        with self.assertRaisesRegex(Rejected, 'not submitted/current'):
            self.raw('assign', {'assignment_id': 'I1', 'instance_id': 'implementer', 'role': 'implementer', 'context_ref': ready})

    def test_draft_and_evidence_changes_prevent_freeze(self):
        self.global_plan()
        plan = self.plan(); ref = self.ref('candidate.json', plan)
        report = self.report('planning', draft=ref)
        proof = report['checks']['source-closure']['evidence_refs'][0]
        context = self.record(report)
        with self.assertRaisesRegex(Rejected, 'reviewed draft'):
            self.raw('plan', {'plan_ref': self.ref('different.json', plan), 'context_ref': context}, role='spec-designer')
        self.raw('plan', {'plan_ref': ref, 'context_ref': context}, role='spec-designer')
        self.approve(digest(plan), 'D1')
        Path(proof['path']).write_text('changed after review')
        with self.assertRaises(Rejected):
            self.raw('freeze', {'decision_id': 'D1'})
        self.assertIsNone(self.state()['modules']['M001']['freeze_id'])

    def test_testing_preflight_and_command_binding(self):
        self.prepare(); self.implementation()
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('assign', {'assignment_id': 'BAD', 'role': 'test-runner', 'instance_id': 'test-runner'})
        ref = self.record(self.report('testing'))
        self.raw('assign', {'assignment_id': 'TEST', 'role': 'test-runner', 'instance_id': 'test-runner', 'context_ref': ref})
        out = self.base / 'must-not-execute'
        with self.assertRaisesRegex(Rejected, 'command differs'):
            execute(self.root, 'M001', 'TEST', 'P1', [sys.executable, '-c', 'print(1)'], str(self.target), out)
        self.assertFalse(out.exists())

    def test_early_auditor_context_review_cannot_bypass_barrier(self):
        with self.assertRaisesRegex(Rejected, 'all module rounds'):
            self.record(self.report('audit-testing', module=None, instance='auditor'))

    def test_final_audit_requires_its_own_context_and_environment(self):
        self.completed()
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('audit-assign', {'assignment_id': 'AUD', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        report = self.report('audit-testing', module=None, instance='auditor', blocked='test-environment')
        ref = self.record(report)
        with self.assertRaisesRegex(Rejected, 'context blocked'):
            self.raw('audit-assign', {'assignment_id': 'AUD', 'instance_id': 'auditor', 'context_ref': ref}, role='global-orchestrator', module=None)
        self.assertNotIn('audit_assignment', self.state())

    def test_parent_decomposition_requires_context_and_go_accepts_same_receipt(self):
        self.root_scope()
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('decompose', {'plan_ref': self.ref('missing.json', self.proposal())}, module='M010')
        self.split()
        self.assertEqual(set(self.state()['modules']), {'M001', 'M002'})

    def test_local_fixer_needs_fresh_diagnosis_context_without_extra_budget(self):
        self.prepare(); self.implementation()
        a, result = self.make_test_result(quality='red-bug')
        self.submit(result, a); self.call('accept', {'assignment_id': a['assignment_id']})
        self.call('diagnose', {'diagnosis_ref': self.ref('diag.md', 'assert mismatch'), 'owner': 'M001', 'root_cause': 'code'}, role='diagnostician')
        self.call('diagnosis-accept')
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('assign', {'assignment_id': 'F1', 'role': 'fixer', 'instance_id': 'fixer'})
        self.assertEqual(self.state()['modules']['M001']['local_fix_used'], 0)
        self.implementation('fixer', 'F1')
        self.assertEqual(self.state()['modules']['M001']['local_fix_used'], 1)
        a, result2 = self.make_test_result('T2', previous=result['paths'][0]['test_run_id'])
        self.submit(result2, a); self.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(self.state()['modules']['M001']['phase'], 'dod')

    def test_cross_module_auditor_fix_and_verification_with_context_gates(self):
        test_audit_closure.ClosureTests.test_cross_module_fix_then_owner_and_source_verification(self)

    def test_sibling_context_updates_do_not_invalidate_independent_receipt(self):
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        self.prepare()
        ref = self.record(self.report('coding'))
        self.record(self.report('planning', module='M002', blocked='target-feasibility'))
        self.raw('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer', 'context_ref': ref})
        self.assertEqual(self.state()['modules']['M001']['phase'], 'implementing')
        self.assertEqual(self.state()['modules']['M002']['phase'], 'context')

    def test_audit_analysis_and_verdict_cannot_skip_context_receipts(self):
        self.cross_module_failure()
        test_ledger.code_review(self)
        self.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('audit-plan', {'plan_ref': self.ref('unreviewed.json', {})}, role='auditor', module=None)
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            self.raw('audit-verdict', {'review_ref': self.ref('verdict.md', 'no review')}, role='auditor', module=None)

    def feature_draft(self):
        self.global_plan()
        plan = copy.deepcopy(self.state()['global_plan']['content'])
        inventory = json.loads(Path(plan['feature_inventory_ref']['path']).read_text())
        return plan, inventory

    def accept_feature_draft(self, plan, inventory, **extra):
        plan['feature_inventory_ref'] = self.ref(f'inventory-review-{self.n}.json', inventory)
        return self.call('global-plan', {'plan_ref': self.ref(f'feature-plan-{self.n}.json', plan),
                         'review_ref': self.ref(f'feature-review-{self.n}.md', 'coverage reviewed'), **extra},
                         role='global-orchestrator', module=None)

    def test_feature_source_defaults_and_per_module_function_list(self):
        plan, inventory = self.feature_draft()
        self.assertEqual(inventory['source_mode'], 'legacy-source')
        inventory['source_mode'] = 'test-case-summary'
        inventory['test_summary_ref'] = self.ref('use-cases.md', 'Feature/Result: C1 returns result')
        inventory['source_units'].append({'unit_id': 'U2', 'kind': 'test-case-group', 'locator': 'Feature/Result',
            'feature_ids': ['F1'], 'evidence_refs': [inventory['test_summary_ref']]})
        self.accept_feature_draft(plan, inventory)
        assigned = self.state()['module_inputs']['M001']
        self.assertEqual(assigned['feature_ids'], ['F1'])
        self.assertEqual(assigned['feature_inventory_ref'], plan['feature_inventory_ref'])
        inventory['source_mode'] = 'legacy-source'
        with self.assertRaisesRegex(Rejected, 'default to supplied'):
            self.accept_feature_draft(plan, inventory)

    def test_incomplete_feature_inventory_cannot_enter_accepted_global_plan(self):
        original, inventory = self.feature_draft()
        for edit in (
            lambda p, i: i['coverage'].update(unclassified=['unknown background worker']),
            lambda p, i: i['coverage'].update(unresolved_questions=['Q1']),
            lambda p, i: p.update(feature_owners={}),
            lambda p, i: i['features'][0].update(case_ids=[]),
            lambda p, i: i['source_units'][0].update(feature_ids=[]),
            lambda p, i: i.update(source_units=[]),
        ):
            plan, changed = copy.deepcopy(original), copy.deepcopy(inventory)
            edit(plan, changed)
            with self.subTest(edit=edit), self.assertRaises(Rejected):
                self.accept_feature_draft(plan, changed)

    def test_feature_question_requires_real_human_decision(self):
        plan, inventory = self.feature_draft()
        inventory['questions'] = [{'question_id': 'Q1', 'question': 'Does the background result belong to this feature?'}]
        with self.assertRaisesRegex(Rejected, 'human boundary review'):
            self.accept_feature_draft(plan, inventory)
        plan['boundary_review']['issues'] = [{'question_id': 'Q1', 'kind': 'uncertain', 'module_ids': ['M001'],
            'question': inventory['questions'][0]['question'], 'proposed_resolution': 'Include background result in F1 and C1'}]
        with self.assertRaisesRegex(Rejected, 'human approval required'):
            self.accept_feature_draft(plan, inventory)
        # Freeze this exact inventory reference before the host records approval.
        decision_subject = digest({'plan': plan, 'registry': workflow.registry(self.state())})
        self.call('decision', {'decision_id': 'FEATURE-DECISION', 'decision': 'approved', 'module_id': None,
            'subject_sha256': decision_subject, 'human_source_ref': self.ref('feature-answer.md', 'Human approved including the background result')},
            role='host', module=None)
        self.call('global-plan', {'plan_ref': self.ref('approved-feature-plan.json', plan),
            'review_ref': self.ref('approved-feature-review.md', 'complete'), 'boundary_decision_id': 'FEATURE-DECISION'},
            role='global-orchestrator', module=None)
        self.assertTrue(self.state()['decisions']['FEATURE-DECISION']['consumed'])

    def test_feature_source_evidence_drift_blocks_coding(self):
        self.prepare()
        plan = self.state()['global_plan']['content']
        inventory = json.loads(Path(plan['feature_inventory_ref']['path']).read_text())
        Path(inventory['source_units'][0]['evidence_refs'][0]['path']).write_text('entry changed after enumeration')
        with self.assertRaises(Rejected):
            self.assign('implementer', 'I1')
        self.assertFalse(self.state()['modules']['M001']['assignments'])


if __name__ == '__main__':
    unittest.main()
