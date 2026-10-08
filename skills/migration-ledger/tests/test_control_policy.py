"""Unified workflow exercises actual Ledger transitions, task batches and independent audit execution."""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_ledger
import test_decomposition
from test_behavior_contract import review as behavior_review
import ledger
import control_policy
import behavior_contract
import decomposition
import audit_code_review
import run_changes
import test_validation as tv
import test_write_scope
from contracts import Rejected, baseline, check_ref, digest, file_ref, read_json, validate_result
from execute_test import execute


class ControlPolicyTests(unittest.TestCase):
    def setUp(self):
        f = self.f = test_ledger.FlowTests()
        original = f.call
        def call(op, payload=None, **kwargs):
            payload = copy.deepcopy(payload or {})
            if op == 'register':
                payload['scope'] = {'in': ['query'], 'out': ['history'], 'requirement_ids': ['R1']}
                payload['context_refs'] = [f.ref('allocation-context.md', 'Reviewed query source entry, target owner and excluded history behavior')]
                payload['behavior_review'] = behavior_review(f, payload)
            return original(op, payload, **kwargs)
        f.call = call
        f.setUp(); self.addCleanup(f.doCleanups)
        original_plan = f.plan
        def plan():
            p = original_plan()
            p['source_closure']['verification'] = f.state()['modules']['M001']['behavior_review']['verification']
            p['paths'][0]['fixture_contract_ref'] = p['source_closure']['verification']['fixture_contract_ref']
            return p
        f.plan = plan

    def review(self, **change):
        f = self.f
        value = {'schema_version': 1, 'plan_hash': f.state()['modules']['M001']['plan_hash'],
            'reviewer_instance_id': 'module-orchestrator', 'semantic_change': False, 'authorization_change': False,
            'unresolved_questions': [], 'reason': 'Original host behavior and acceptance preserved; independent design reviewed',
            'evidence_refs': [f.ref('technical-review.md', 'Scope, code boundary and fixed tests checked')]}
        return f.ref('plan-review.json', {**value, **change})

    def freeze(self, plan=None):
        f = self.f; f.global_plan()
        f.call('plan', {'plan_ref': f.ref('policy-plan.json', plan or f.plan())}, role='spec-designer')
        f.call('plan-review', {'review_ref': self.review()})
        step = f.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'freeze'); self.assertTrue(step['ready'])
        f.call('freeze', step['payload'])

    def test_clear_initial_plan_freezes_without_human_decision(self):
        self.freeze()
        s = self.f.state()
        self.assertEqual(s['decisions'], {})
        self.assertEqual(s['modules']['M001']['phase'], 'frozen')

    def test_uncertainty_semantics_authority_and_stale_review_do_not_freeze(self):
        f = self.f; f.global_plan()
        f.call('plan', {'plan_ref': f.ref('policy-plan.json', f.plan())}, role='spec-designer')
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'plan-review')
        for change, reason in [({'semantic_change': True}, 'human decision'), ({'authorization_change': True}, 'human decision'),
            ({'unresolved_questions': ['Q1']}, 'human check'), ({'plan_hash': '0'*64}, 'stale'),
            ({'reviewer_instance_id': 'spec-designer'}, 'independent')]:
            with self.subTest(change=change), self.assertRaisesRegex(Rejected, reason):
                f.call('plan-review', {'review_ref': self.review(**change)})
        self.assertIsNone(f.state()['modules']['M001']['freeze_id'])

    def test_preimplementation_history_is_nonexecutable_and_is_not_CR(self):
        self.freeze(); f = self.f
        old = f.state()['modules']['M001']['plan_ref']
        f.call('planning-reopen', {'reason_ref': f.ref('replan.md', 'Better task boundary before coding')})
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'specifying'); self.assertIsNone(m['freeze_id'])
        self.assertEqual(m['planning_history'][-1]['plan_ref'], old)
        self.assertFalse(m['planning_history'][-1]['executable'])
        self.assertEqual(m['planning_history'][-1]['kind'], 'planning-history')
        with self.assertRaises(Rejected):
            f.assign('implementer', 'STALE')
        self.assertEqual(f.state()['run_id'], 'demo')

    def test_reopen_cannot_disguise_started_implementation(self):
        self.freeze(); f = self.f
        f.assign('implementer', 'I1')
        with self.assertRaises(Rejected):
            f.call('planning-reopen', {'reason_ref': f.ref('replan.md', 'Change')})
        m = f.state()['modules']['M001']; m['assignments']['I1']['closed'] = True
        self.assertTrue(control_policy.execution_started(m))

    def git_policy(self):
        f = self.f; old = f.state(); f.root = f.base / 'policy-git-run'
        f.call('init', {**{k: old[k] for k in ('legacy_root', 'target_root', 'global_spec', 'new_architecture',
            'case_ids', 'requirement_ids', 'global_paths', 'context_readiness_required', 'dimension_slicing_required',
            'split_testing_required')}, 'write_scope_check': True}, role='host', module=None)
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm1')],
            'dependencies': []}, role='global-orchestrator', module=None)
        for args in (('init', '-q'), ('config', 'user.email', 'fixture@example.invalid'),
                     ('config', 'user.name', 'fixture')): test_write_scope.git(f.target, *args)
        (f.target / 'README.md').write_text('baseline')
        test_write_scope.git(f.target, 'add', '.'); test_write_scope.git(f.target, 'commit', '-qm', 'fixture')
        self.freeze()
        f.assign('implementer', 'I1')

    def test_authorized_worker_without_code_delta_can_return_to_planning_after_host_stop(self):
        self.git_policy(); f = self.f
        f.call('revoke', {'assignment_id': 'I1', 'allow_planning_reopen': True,
            'stopped_worker_ref': f.ref('stopped.md', 'Host confirms process stopped')}, role='host')
        f.call('planning-reopen', {'reason_ref': f.ref('replan.md', 'Improve boundary before any source change')})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'specifying')
        self.assertEqual(f.state()['run_id'], 'demo')

    def test_code_delta_cannot_be_hidden_by_worker_stop_or_after_stop(self):
        self.git_policy(); f = self.f
        (f.target / '.gitignore').write_text('*.py\n')  # ignored production code must still be observed
        code = f.target / 'm1/new.py'; code.parent.mkdir(); code.write_text('changed = True')
        stop = {'assignment_id': 'I1', 'allow_planning_reopen': True, 'stopped_worker_ref': f.ref('stop.md', 'Stopped')}
        with self.assertRaisesRegex(Rejected, 'code changed'): f.call('revoke', stop, role='host')
        code.unlink(); f.call('revoke', stop, role='host')
        code.write_text('changed after stop')
        with self.assertRaisesRegex(Rejected, 'code changed after stop'):
            f.call('planning-reopen', {'reason_ref': f.ref('replan.md', 'Cannot hide source change')})

    def two_tasks(self):
        p = self.f.plan()
        p['tasks'].append({**copy.deepcopy(p['tasks'][0]), 'task_id': 'T2'})
        for i, ref in enumerate(p['definitions']):
            if ref['kind'] == 'tasks': p['definitions'][i] = {**self.f.ref('two-tasks.md', '- [ ] T1 implement R1\n- [ ] T2 second part\n'), 'kind': 'tasks'}
        return p

    def implement_task(self, tid, aid):
        f = self.f
        f.call('assign', {'assignment_id': aid, 'role': 'implementer', 'instance_id': 'implementer',
            'task_ids': [tid], 'path_ids': ['P1']})
        a = f.state()['modules']['M001']['assignments'][aid]
        code = f.target / ('m1/code.py' if tid == 'T1' else 'm1/extra.py')
        code.parent.mkdir(exist_ok=True); code.write_text('value = 2\n')
        refs = f.state()['modules']['M001']['code_files'] + [file_ref(code)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
            'assignment_id': aid, 'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'],
            'code_files': refs, 'code_baseline': baseline(refs), 'task_trace': [{'task_id': tid, 'files': [str(code)]}],
            'production_binding_evidence': f.ref('binding-'+aid+'.md', 'Real query route binding'),
            'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref(aid+'.log', '0 errors')}}
        return a, result

    def test_task_batches_accumulate_and_no_target_tests_run_before_all_tasks(self):
        self.freeze(self.two_tasks()); f = self.f
        a, result = self.implement_task('T1', 'I1')
        f.submit(result, a); f.call('accept', {'assignment_id': 'I1'})
        m = f.state()['modules']['M001']; self.assertEqual(m['phase'], 'frozen')
        self.assertEqual(m['accepted_task_ids'], ['T1'])
        with self.assertRaises(Rejected): f.assign('test-runner', 'EARLY')
        a, result = self.implement_task('T2', 'I2')
        self.assertEqual(a['execution_contract']['accepted_task_ids'], ['T1'])
        self.assertEqual(len(a['execution_contract']['accepted_code_files']), 1)
        missing = copy.deepcopy(result); missing['code_files'] = missing['code_files'][1:]; missing['code_baseline'] = baseline(missing['code_files'])
        with self.assertRaisesRegex(Rejected, 'unassigned TASK code'):
            validate_result(missing, f.state()['modules']['M001'], a)
        wrong = copy.deepcopy(result); wrong['task_trace'][0]['task_id'] = 'T1'
        with self.assertRaisesRegex(Rejected, 'unassigned task trace'):
            validate_result(wrong, f.state()['modules']['M001'], a)
        f.submit(result, a); f.call('accept', {'assignment_id': 'I2'})
        m = f.state()['modules']['M001']
        self.assertEqual(m['accepted_task_ids'], ['T1', 'T2']); self.assertEqual(m['phase'], 'testing')
        self.assertEqual(len(m['code_files']), 2)

    def test_host_advance_dispatches_explicit_task_contract(self):
        self.freeze(); f = self.f
        out = ledger.advance(f.root, {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}, 'M001')
        self.assertEqual(out['applied'][0]['operation'], 'assign')
        a = next(iter(f.state()['modules']['M001']['assignments'].values()))
        self.assertEqual(a['execution_contract']['task_ids'], ['T1'])
        self.assertEqual(a['execution_contract']['permissions'], 'code')

    def test_missing_explicit_task_selection_is_rejected_on_actual_bus(self):
        self.freeze(); f = self.f; s = f.state()
        with self.assertRaisesRegex(Rejected, 'task_ids'):
            ledger.apply(f.root, {'schema_version': 1, 'request_id': 'missing-task', 'run_id': 'demo', 'module_id': 'M001',
                'expected_revision': s['modules']['M001']['revision'], 'operation': 'assign',
                'payload': {'role': 'implementer', 'assignment_id': 'I1', 'instance_id': 'implementer'}},
                {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'})

    def test_children_select_real_provider_instead_of_inheriting_parent_union(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); state = f.state()
        parent = state['modules']['M010']; parent['dependencies'] = ['M020']
        provider = copy.deepcopy(parent); provider.update(module_id='M020', dependencies=[], decomposition_required=False, acceptance_case_ids=[])
        state['modules']['M020'] = provider
        proposal = f.proposal(dependencies={'M001': ['M020']})
        for child in proposal['children']: child['behavior_review'] = behavior_review(f, child)
        _, graph = decomposition.validate(state, parent, proposal)
        self.assertEqual(graph['M001'], ['M020']); self.assertEqual(graph['M002'], [])

    def test_consumer_of_parent_must_select_actual_provider_children(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); state = f.state()
        parent = state['modules']['M010']
        consumer = copy.deepcopy(parent); consumer.update(module_id='M030', dependencies=['M010'], decomposition_required=False, acceptance_case_ids=[])
        consumer['behavior_review'] = behavior_review(f, consumer); state['modules']['M030'] = consumer
        proposal = f.proposal()
        for child in proposal['children']: child['behavior_review'] = behavior_review(f, child)
        with self.assertRaisesRegex(Rejected, 'consumer_dependencies'):
            decomposition.validate(state, parent, proposal)
        proposal['consumer_dependencies'] = {'M030': ['M001']}
        selected = copy.deepcopy(consumer); selected['dependencies'] = ['M001']
        proposal['consumer_verifications'] = {'M030': behavior_review(f, selected)['verification']}
        _, graph = decomposition.validate(state, parent, proposal)
        self.assertEqual(graph['M030'], ['M001'])

    def test_parent_replanning_marker_does_not_force_unchanged_children_to_replan(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(); state = f.state()
        parent = state['module_groups']['M010']; parent['replanning_required'] = True
        children = [copy.deepcopy(state['modules'][mid]) for mid in parent['children']]
        graph = {mid: m['dependencies'] for mid, m in state['modules'].items()}
        self.assertEqual(decomposition.redecomposition_impact(state, parent, children, graph), set())

    def test_identical_slice_observation_is_rejected_even_with_unique_ids(self):
        m = copy.deepcopy(self.f.state()['modules']['M001']); peer = copy.deepcopy(m)
        peer['module_id'] = 'M002'; peer['behavior_review']['verification']['acceptance_owner'] = 'M002'
        with self.assertRaisesRegex(Rejected, 'duplicate verification boundary'):
            behavior_contract.distinct([m, peer])
        peer['behavior_review']['verification']['independent_observation'] = 'Separate observable history result'
        behavior_contract.distinct([m, peer])

    def test_whole_goal_audit_cannot_omit_an_original_requirement(self):
        self.f.finish_module(); f = self.f
        test_ledger.code_review(f); s = f.state()
        report = read_json(check_ref(s['audit_code_review']['report_ref']))
        report['goal_review']['requirements'] = []
        with self.assertRaises(Rejected):
            f.call('audit-code-review', {'report_ref': f.ref('omitted-goal.json', report)}, role='auditor', module=None)

    def test_independent_test_task_then_auditor_consumes_exact_observations(self):
        f = self.f; f.finish_module(); test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'AUD', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-test-assign')
        with self.assertRaisesRegex(Rejected, 'independent'):
            f.call('audit-test-assign', {'assignment_id': 'AT', 'instance_id': 'auditor', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        f.call('audit-test-assign', {'assignment_id': 'AT', 'instance_id': 'independent-test', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        s = f.state(); scope = ledger.audit_scope(s)
        script = f.base/'audit-adapter.py'
        script.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\njson.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))\n")
        rr = execute(f.root, 'GLOBAL', 'AT', 'GP1', [sys.executable, str(script)], str(f.target), f.base/'audit-result')
        receipt = read_json(check_ref(rr))
        result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL', 'assignment_id': 'AT',
            'actor_instance_id': 'independent-test', 'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'],
            'paths': [{'path_id': 'GP1', 'quality': 'green-passed', 'executed': True, 'test_run_id': receipt['test_run_id'],
                'execution_receipt': rr, 'assertions': read_json(check_ref(receipt['result_ref']))['assertions']}]}
        result_ref = f.ref('independent-audit-test.json', result)
        f.call('audit-test-submit', {'result_ref': result_ref}, role='test-runner', instance='independent-test', module=None)
        report = {**result, 'assignment_id': 'AUD', 'actor_instance_id': 'auditor', 'snapshot': s['audit_assignment']['snapshot'],
            'test_result_ref': result_ref, 'review_ref': f.ref('audit-verdict.md', 'Original goal and independent evidence reviewed')}
        changed = copy.deepcopy(report); changed['paths'][0]['quality'] = 'yellow-blocked'
        with self.assertRaisesRegex(Rejected, 'cannot rewrite'):
            f.call('audit', {'report_ref': f.ref('changed-audit.json', changed)}, role='auditor', module=None)
        f.call('audit', {'report_ref': f.ref('audit-verdict.json', report)}, role='auditor', module=None)
        self.assertEqual(f.state()['quality'], 'green-passed')
        self.assertEqual(f.state()['audit_test_assignment']['role'], 'test-runner')

    def test_new_policy_never_dispatches_local_problem_auditor(self):
        self.freeze(); f = self.f
        with self.assertRaisesRegex(Rejected, 'unknown operation|incorrect global/module scope'):
            f.call('problem-assign', {'assignment_id': 'LOCAL', 'instance_id': 'auditor', 'module_ids': ['M001']}, role='global-orchestrator', module=None)

    def test_audit_snapshot_always_binds_the_host_goal(self):
        state = self.f.state()
        expected = audit_code_review.snapshot(state)
        self.assertIn('host_contract_sha256', expected)
        for marker in (1, 2, 99):
            state['control_policy_version'] = marker  # inert historical metadata
            self.assertEqual(audit_code_review.snapshot(state), expected)

    def test_execution_command_hash_change_does_not_weaken_acceptance(self):
        path = {'path_id': 'B1', 'case_id': 'C1', 'requirement_id': 'R1', 'name': 'Build',
            'kind': 'build', 'expected_assertions': [{'assertion_id': 'EXIT', 'expected': 0}], 'command': {'argv': ['old-build']}}
        updated = {**path, 'name': 'Updated build label', 'command': {'argv': ['new-build']}}
        self.assertEqual(control_policy.acceptance([path]), control_policy.acceptance([updated]))
        updated['expected_assertions'] = [{'assertion_id': 'EXIT', 'expected': 1}]
        self.assertNotEqual(control_policy.acceptance([path]), control_policy.acceptance([updated]))

    def test_new_CR_freeze_requires_fresh_task_acceptance_and_preserves_old_execution(self):
        self.freeze(); f = self.f; f.implementation()
        a, result = f.make_test_result(); f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        old = f.state()['modules']['M001']; plan = copy.deepcopy(old['plan'])
        plan['paths'][0]['name'] = 'Updated verification label'
        impact = f.ref('cr-impact.json', {'from_freeze_id': old['freeze_id'], 'to_plan_hash': digest(plan)})
        f.call('change', {'request_ref': f.ref('cr.md', 'Technical revision with unchanged acceptance'), 'impact_ref': impact})
        f.call('plan', {'plan_ref': f.ref('cr-plan.json', plan)}, role='spec-designer')
        f.call('freeze', {'change_class': 'within-envelope', 'impact_ref': impact})
        current = f.state()['modules']['M001']
        self.assertEqual(current['accepted_task_ids'], [])
        self.assertEqual(current['change_request_history'][-1]['prior_execution']['accepted_task_ids'], ['T1'])
        self.assertEqual(f.state()['next_steps'][0]['payload']['task_ids'], ['T1'])
        f.implementation(aid='I2')
        current = f.state()['modules']['M001']
        self.assertEqual(current['accepted_task_ids'], ['T1'])
        self.assertEqual(current['code_baseline'], old['code_baseline'])
        self.assertTrue(current['results']['P1']['stale'])
        self.assertFalse(tv.all_green(current))
        a, result = f.make_test_result(aid='TEST2')
        with self.assertRaisesRegex(Rejected, 'retest chain'):
            validate_result(result, current, a, run_root=f.root)
        result['paths'][0]['retest_of'] = old['results']['P1']['test_run_id']
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        current = f.state()['modules']['M001']
        self.assertFalse(current['results']['P1']['stale'])
        self.assertEqual(current['phase'], 'dod')

    def test_stale_prerequisites_and_automation_require_actual_stage_retests(self):
        m = {'code_baseline': 'same', 'build_baseline': 'same', 'plan': {'paths': [
            {'path_id': kind, 'kind': kind} for kind in ('build', 'unit', 'static', 'automation')]},
            'results': {kind: {'quality': 'green-passed', 'code_baseline': 'same', 'stale': True}
                        for kind in ('build', 'unit', 'static', 'automation')}}
        self.assertFalse(tv.build_ready(m)); self.assertFalse(tv.all_green(m))
        tests = {kind: {'quality': 'green-passed'} for kind in ('build', 'unit', 'static')}
        self.assertEqual([p['path_id'] for p in tv.stage_paths(m, tests)], ['build', 'unit', 'static'])
        for kind in tests: m['results'][kind]['stale'] = False
        self.assertEqual(tv.next_scope(m), 'automation')
        self.assertFalse(tv.functional_ready(m)); self.assertFalse(tv.all_green(m))
        m['results']['automation']['stale'] = False
        self.assertTrue(tv.all_green(m))

    def test_policy_upgrade_is_not_an_executable_operation(self):
        f = self.f; f.prepare(); before = f.state()
        with self.assertRaisesRegex(Rejected, 'unknown operation|incorrect global/module scope'):
            f.call('upgrade-control-policy', {}, role='host', module=None)
        self.assertEqual(f.state()['last_sequence'], before['last_sequence'])
        self.assertNotIn('control_policy_version', f.state())

    def test_init_rejects_every_workflow_selector(self):
        f = self.f; current = f.state()
        payload = {k: current[k] for k in ('target_root', 'legacy_root', 'global_spec', 'new_architecture', 'case_ids', 'requirement_ids')}
        for marker in (1, 2, 99):
            f.root = f.base / ('selector-' + str(marker))
            with self.subTest(marker=marker), self.assertRaisesRegex(Rejected, 'policy selectors'):
                f.call('init', {**payload, 'control_policy_version': marker}, role='host', module=None)
            self.assertEqual(ledger.read_events(f.root), (None, []))

    def test_historical_assignment_cannot_submit_without_current_task_contract(self):
        self.freeze(); f = self.f; f.implementation()
        a, result = f.make_test_result()
        state, events = ledger.read_events(f.root)
        state['modules']['M001']['assignments'][a['assignment_id']].pop('execution_contract')
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(Rejected, 'execution contract missing'):
            ledger.mutate(state, {'operation': 'submit', 'module_id': 'M001', 'payload': {
                'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'],
                'result_ref': f.ref('historical-submission.json', result)}},
                {'role': 'test-runner', 'instance_id': a['instance_id']}, events, root=f.root)
        self.assertEqual(state, before)

    def test_historical_assignment_cannot_execute_without_current_task_contract(self):
        from unittest.mock import patch
        self.freeze(); f = self.f; f.implementation(); a = f.assign('test-runner', 'OLD')
        state = f.state(); state['modules']['M001']['assignments'][a['assignment_id']].pop('execution_contract')
        output = f.base / 'forbidden-execution'
        with patch('execute_test.status', return_value=state), self.assertRaisesRegex(Rejected, 'execution contract missing'):
            execute(f.root, 'M001', a['assignment_id'], 'P1', [sys.executable, '-c', 'pass'], f.target, output)
        self.assertFalse(output.exists())

    def test_blocked_goal_must_enter_the_unified_finding_closure(self):
        f = self.f; f.finish_module(); test_ledger.code_review(f)
        report = read_json(check_ref(f.state()['audit_code_review']['report_ref']))
        report['goal_review']['requirements'][0]['conclusion'] = 'blocked'
        with self.assertRaisesRegex(Rejected, 'unified finding closure'):
            f.call('audit-code-review', {'report_ref': f.ref('blocked-goal.json', report)}, role='auditor', module=None)


if __name__ == '__main__': unittest.main()
