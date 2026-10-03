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
            if op == 'assign' and 'context_ref' not in p:
                # Dispatch first: the worker reports inside its assignment, which authorizes the work.
                ack = self.raw(op, p, role=role, module=module, instance=instance, request=request)
                self.record(self.report(stage, module, producer))
                return ack
            report = self.report(stage, module, producer, p.get('report_ref') if op == 'audit-code-review' else p.get('plan_ref'))
            # An actor's own preflight rides its operation; a report another role accepts is submitted first.
            p['context_ref'] = (self.ref(f'context-report-{self.n}.json', report) if op in cr.SELF_REPORTED
                                else self.record(report))
        return self.raw(op, p, role=role, module=module, instance=instance, request=request)

    def completed(self):
        self.prepare(); self.implementation()
        a, result = self.make_test_result()
        self.submit(result, a); self.call('accept', {'assignment_id': a['assignment_id']})
        self.call('complete', {'dod_ref': self.ref('dod.md', 'all paths complete')})

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

    def test_own_preflight_rides_the_operation_and_a_workers_report_stays_its_own(self):
        self.global_plan()
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['ready']), ('plan', True))
        self.assertTrue(step['context_gate']['with_operation'])
        plan = self.plan(); plan_ref = self.ref('own-plan.json', plan)
        report = self.report('planning', draft=plan_ref)
        events = len(ledger.read_events(self.root)[1])
        stranger = self.ref('stranger.json', {**report, 'producer': {'role': 'spec-designer', 'instance_id': 'someone-else'}})
        with self.assertRaisesRegex(Rejected, 'identity mismatch'):
            self.raw('plan', {'plan_ref': plan_ref, 'context_ref': stranger}, role='spec-designer')
        self.raw('plan', {'plan_ref': plan_ref, 'context_ref': self.ref('own-report.json', report)}, role='spec-designer')
        self.assertEqual(len(ledger.read_events(self.root)[1]), events + 1)  # report and plan in one event
        self.assertIn('planning:spec-designer', self.state()['modules']['M001']['context_receipts'])
        self.approve(digest(plan), 'D-own'); self.raw('freeze', {'decision_id': 'D-own'})
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['ready'], step['reason']), ('assign', True, None))  # dispatch does not wait for a report
        self.assertEqual((step['context_gate']['stage'], step['context_gate']['ready_receipts']), ('coding', []))
        coding = self.ref('coding-report.json', self.report('coding'))
        with self.assertRaisesRegex(Rejected, 'not submitted'):  # the MO cannot register the worker's report for it
            self.raw('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer', 'context_ref': coding})

    def test_a_worker_preflights_inside_its_dispatch_and_the_ready_report_authorizes_the_work(self):
        self.prepare()
        self.raw('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'})
        a = self.state()['modules']['M001']['assignments']['I1']
        self.assertNotIn('context_ref', a)
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['role'], step['context_gate']['stage']), ('await-result', 'implementer', 'coding'))
        view = ledger.status(self.root, 'step', 'M001')  # the worker finds what its report must contain
        self.assertEqual(view['request']['operation'], 'context-submit')
        self.assertEqual(view['context']['subject_sha256'], cr.subject(self.state(), 'M001', 'coding'))
        self.assertTrue(view['context']['required_input_refs'])
        source = self.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True); source.write_text('value = 2\n')
        from contracts import baseline, file_ref
        refs = [file_ref(source)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': 'I1',
                  'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(source)]}],
                  'production_binding_evidence': self.ref('binding.txt', 'real binding reviewed'),
                  'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': self.ref('diag.log', '0 errors')}}
        with self.assertRaisesRegex(Rejected, 'preflight required'):
            self.submit(result, a)
        self.record(self.report('coding', instance='someone-else'))  # another instance's report is not this worker's
        self.assertNotIn('context_ref', self.state()['modules']['M001']['assignments']['I1'])
        ref = self.record(self.report('coding'))
        self.assertEqual(self.state()['modules']['M001']['assignments']['I1']['context_ref'], ref)
        self.assertNotIn('context_gate', self.state()['next_steps'][0])  # nothing is owed any more
        self.assertEqual(ledger.status(self.root, 'step', 'M001')['request']['operation'], 'submit')
        self.submit(result, a); self.raw('accept', {'assignment_id': 'I1'})
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')

    def test_a_blocked_report_hands_the_dispatch_back_and_holds_the_next_one(self):
        self.prepare()
        self.raw('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'})
        blocked = self.record(self.report('coding', blocked='permissions-tools'))
        m = self.state()['modules']['M001']
        self.assertEqual((m['assignments']['I1']['closed'], m['assignments']['I1']['declined_ref'], m['phase']), (True, blocked, 'frozen'))
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['ready'], step['reason']), ('assign', False, 'context-blocked'))
        self.assertEqual(step['context_gate']['blocked_receipts'], [blocked])
        self.assertNotIn('mechanical', step)
        with self.assertRaisesRegex(Rejected, 'context blocked'):  # the same gap would only come back
            self.raw('assign', {'assignment_id': 'I2', 'role': 'implementer', 'instance_id': 'implementer'})
        ready = self.record(self.report('coding'))  # the gap is closed: the worker says so before or after the dispatch
        self.assertEqual(self.state()['next_steps'][0]['payload'], {'role': 'implementer', 'instance_id': 'implementer', 'context_ref': ready})
        self.raw('assign', {'assignment_id': 'I2', 'role': 'implementer', 'instance_id': 'implementer'})
        self.assertEqual(self.state()['modules']['M001']['assignments']['I2']['context_ref'], ready)

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
        for payload in ({'context_ref': ref}, {}):  # neither citing the blocked report nor leaving it out gets past it
            with self.assertRaisesRegex(Rejected, 'context blocked'):
                self.raw('assign', {'assignment_id': 'I1', 'instance_id': 'implementer', 'role': 'implementer', **payload})
        after = self.state()['modules']['M001']
        self.assertEqual(before['assignments'], after['assignments'])
        self.assertEqual(before['fix_rounds_used'], after['fix_rounds_used'])
        self.assertEqual(self.state()['next_steps'][0]['reason'], 'context-blocked')
        self.record(self.report('coding'))  # the gap is closed and the worker says so
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
        self.raw('assign', {'assignment_id': 'TEST', 'role': 'test-runner', 'instance_id': 'test-runner'})
        out = self.base / 'must-not-execute'
        with self.assertRaisesRegex(Rejected, 'test context missing'):  # dispatched, but not yet preflighted
            execute(self.root, 'M001', 'TEST', 'P1', self.report('testing')['execution']['argv'], str(self.target), out)
        self.record(self.report('testing'))
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
        self.raw('assign', {'assignment_id': 'F0', 'role': 'fixer', 'instance_id': 'fixer'})
        m = self.state()['modules']['M001']  # dispatched, but a round is only spent once the Fixer can start
        self.assertEqual((m['phase'], m['local_fix_used'], m['fix_rounds_used'], m.get('fix_memory', [])), ('fixing', 0, 0, []))
        self.record(self.report('fixing', blocked='failure-diagnosis'))
        m = self.state()['modules']['M001']
        self.assertEqual((m['phase'], m['local_fix_used'], m['fix_rounds_used'], m['assignments']['F0']['closed']), ('diagnosing', 0, 0, True))
        self.record(self.report('fixing'))  # the Fixer can work now
        self.implementation('fixer', 'F1')
        m = self.state()['modules']['M001']
        self.assertEqual((m['local_fix_used'], m['fix_rounds_used'], len(m['fix_memory'])), (1, 1, 1))
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
        self.raw('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'})
        with self.assertRaisesRegex(Rejected, 'evidence hash mismatch'):  # no ready report can stand on drifted evidence
            self.record(self.report('coding'))
        self.assertNotIn('context_ref', self.state()['modules']['M001']['assignments']['I1'])  # so the work is never authorized


if __name__ == '__main__':
    unittest.main()
