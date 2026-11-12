"""Same-task root/context revisions retain evidence, identities and independent gates."""
import copy
import unittest
from pathlib import Path

import test_decomposition
import test_source_changes
import ledger
import decomposition
import context_readiness as cr
import run_changes
import project_context
from contracts import Rejected, digest, check_ref, read_json, file_ref, baseline
import workflow


class RootRevisionTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(); f.global_plan()

    def report(self, updates):
        f = self.f
        return {'schema_version': 1, 'run_id': 'demo', 'reason': 'Root boundary review', 'context_patch': {},
            'boundary_review': {'semantic_change': True, 'authorization_change': False, 'unresolved_questions': [],
                'reason': 'Reviewed root allocation impact', 'evidence_refs': [f.ref('root-boundary-review.md', 'Precise root allocation reviewed')]},
            'root_updates': updates, 'modules': [{'module_id': mid, 'action': 'replan', 'reason': 'Affected boundary',
                'evidence_refs': [f.ref('impact.md', 'Reviewed source boundaries')], 'resume_blocker_sha256': None}
                for mid in f.state()['modules']]}

    def update(self, mid):
        root = run_changes.roots(self.f.state())[mid]
        return {k: copy.deepcopy(root[k]) for k in run_changes.ROOT_KEYS if k in root}

    def apply(self, report):
        f = self.f
        f.call('run-review', {'report_ref': f.ref('run-review.json', report)}, role='global-orchestrator', module=None)
        subject = f.state()['run_change_review']['subject_sha256']
        f.call('decision', {'decision_id': 'REV', 'module_id': None, 'decision': 'approved', 'subject_sha256': subject,
            'human_source_ref': f.ref('run-decision.md', 'Approve this task revision')}, role='host', module=None)
        f.call('revise-run', {'decision_id': 'REV', 'subject_sha256': subject}, role='host', module=None)

    def test_root_revision_restarts_parent_then_leaf_planning_in_same_run(self):
        f = self.f; f.prepare_leaf('M001')
        old = f.state()['modules']['M001']['plan_ref']
        f.call('realloc-request', {'reason': 'Parent scope needs correction', 'evidence_refs': [f.ref('root-problem.md', 'Wrong root assumption')]}, module='M010')
        self.assertEqual(f.state()['global_next_step']['operation'], 'run-review')
        request = f.state()['module_groups']['M010']['realloc_request']
        update = self.update('M010'); update['scope']['in'] = ['Corrected search scope']
        self.apply(self.report([update]))
        s = f.state()
        self.assertEqual(s['run_id'], 'demo')
        resolution, = s['run_change_history'][-1]['allocation_resolutions']
        self.assertEqual((resolution['module_id'], resolution['request_sha256'], resolution['outcome']),
                         ('M010', digest(request), 'adjusted'))
        self.assertEqual(s['modules']['M001']['planning_history'][-1]['plan_ref'], old)
        self.assertIsNone(s['modules']['M001']['freeze_id'])
        step = next(x for x in s['next_steps'] if x['module_id'] == 'M010')
        self.assertEqual(step['operation'], 'redecompose')
        with self.assertRaisesRegex(Rejected, 'redecomposition'):
            f.global_plan()
        f.call('redecompose', {'plan_ref': f.ref('corrected-split.json', f.proposal())}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('corrected-review.md', 'Reviewed corrected children')}, role='global-orchestrator', module='M010')
        f.global_plan()
        self.assertFalse(f.state()['module_groups']['M010'].get('replanning_required'))
        with self.assertRaises(Rejected):
            f.call('assign', {'role': 'implementer', 'assignment_id': 'EARLY', 'instance_id': 'coder'})
        view = ledger.status(f.root, view='step', module_id='M001')
        self.assertTrue(view['history_refs']['lessons'])
        self.assertTrue(read_json(check_ref(view['history_refs']['lessons']))['entries'])
        _, events = ledger.read_events(f.root)
        ref = view['history_refs']['lessons']
        self.assertIn((ref['path'], ref['sha256']), ledger.artifact_index(events))

    def test_two_parents_can_transfer_write_boundaries_without_new_run(self):
        f = self.f
        second = self.update('M010'); second['module_id'] = 'M020'; second['name'] = 'Filters'
        second['decomposition_required'] = True
        second['scope']['in'] = ['Filters']
        f.call('register', second, role='global-orchestrator', module=None)
        f.split(f.proposal('M020', ('M003', 'M004')), parent='M020')
        first = self.update('M010'); second = self.update('M020')
        first['write_paths'] = [str(f.target / 'm1')]
        second['write_paths'] = [str(f.target / 'm2')]
        self.apply(self.report([first, second]))
        s = f.state()
        self.assertTrue(all(g['replanning_required'] for g in s['module_groups'].values()))
        self.assertEqual(s['module_groups']['M010']['write_paths'], first['write_paths'])
        self.assertEqual(s['module_groups']['M020']['write_paths'], second['write_paths'])
        self.assertEqual(len(s['run_change_history']), 1)

    def test_retired_provider_updates_consumer_parent_and_its_children(self):
        f = self.f
        consumer = self.update('M010')
        consumer.update(module_id='M020', name='Consumer', decomposition_required=True, dependencies=['M001', 'M002'], acceptance_case_ids=[])
        f.call('register', consumer, role='global-orchestrator', module=None)
        from test_behavior_contract import review
        plan = f.proposal('M020', ('M003', 'M004'), dependencies={'M003': ['M001'], 'M004': ['M002']})
        for child in plan['children']: child['behavior_review'] = review(f, child)
        f.split(plan, parent='M020')
        replacement = f.proposal(ids=('M005', 'M002'))
        consumer_child = copy.deepcopy(f.state()['modules']['M003']); consumer_child['dependencies'] = ['M005']
        replacement['consumer_dependencies'] = {'M003': ['M005']}
        replacement['consumer_verifications'] = {'M003': review(f, consumer_child)['verification']}
        f.call('redecompose', {'plan_ref': f.ref('replacement-split.json', replacement)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('replacement-review.md', 'Provider replaced; consumers reviewed')},
               role='global-orchestrator', module='M010')
        s = f.state()
        self.assertEqual(s['module_groups']['M020']['dependencies'], ['M002', 'M005'])
        self.assertEqual(s['modules']['M003']['dependencies'], ['M005'])
        self.assertEqual(s['modules']['M004']['dependencies'], ['M002'])
        plan = f.proposal('M020', ('M003', 'M004'), dependencies={'M003': ['M005'], 'M004': ['M002']})
        for child in plan['children']: child['behavior_review'] = review(f, child)
        f.call('redecompose', {'plan_ref': f.ref('consumer-split.json', plan)}, module='M020')

    def test_atomic_root_can_request_go_review_and_decision_is_mandatory(self):
        f = self.f
        root = self.update('M010'); root.update(module_id='M020', leaf_review_ref=f.ref('leaf.md', 'Atomic root'))
        f.call('register', root, role='global-orchestrator', module=None)
        f.call('realloc-request', {'reason': 'Root slice conflict', 'evidence_refs': [f.ref('conflict.md', 'Cross-root overlap')]}, module='M020')
        self.assertEqual(f.state()['global_next_step']['operation'], 'run-review')
        update = self.update('M020'); update['scope']['in'] = ['Corrected atomic scope']
        f.call('run-review', {'report_ref': f.ref('revision.json', self.report([update]))}, role='global-orchestrator', module=None)
        subject = f.state()['run_change_review']['subject_sha256']
        before = ledger.read_events(f.root)
        with self.assertRaisesRegex(Rejected, 'decision'):
            f.call('revise-run', {'decision_id': 'MISSING', 'subject_sha256': subject}, role='host', module=None)
        self.assertEqual(ledger.read_events(f.root), before)

    def test_review_can_explicitly_keep_the_requested_root_allocation(self):
        f = self.f
        f.call('realloc-request', {'reason': 'Check the existing boundary', 'evidence_refs': [f.ref('request.md', 'Scope evidence')]}, module='M010')
        report = self.report([self.update('M010')])
        for row in report['modules']:
            row['action'] = 'unchanged'
        self.apply(report)
        state = f.state()
        self.assertNotIn('realloc_request', state['module_groups']['M010'])
        self.assertEqual(state['run_change_history'][-1]['allocation_resolutions'][0]['outcome'], 'maintained')

    def test_atomic_dependency_revision_recommends_global_coverage_review(self):
        f = self.f
        root = self.update('M010'); root.update(module_id='M020', leaf_review_ref=f.ref('atomic.md', 'Atomic root'))
        f.call('register', root, role='global-orchestrator', module=None); f.global_plan()
        update = self.update('M020'); update['dependencies'] = ['M001']
        self.apply(self.report([update]))
        self.assertIsNone(f.state()['global_plan'])
        self.assertEqual(f.state()['global_next_step']['operation'], 'global-plan')
        f.global_plan()
        workflow.planning_guard(f.state(), 'M020')

    def test_missing_requirements_and_cases_extend_contract_inside_same_run(self):
        f = self.f; f.prepare_leaf('M001')
        old = f.state()
        update = self.update('M010')
        update['scope']['requirement_ids'].append('R2'); update['case_ids'].append('C2')
        report = self.report([update])
        report.update(global_spec_ref=f.ref('complete-business.md', 'R1/R2 business boundaries; C1/C2 acceptance inputs'),
                      contract_patch={'requirement_ids': ['R1', 'R2'], 'case_ids': ['C1', 'C2']})
        self.apply(report)
        state = f.state()
        self.assertEqual(state['run_id'], old['run_id'])
        self.assertEqual(state['case_ids'], ['C1', 'C2'])
        self.assertEqual(state['run_change_history'][-1]['previous_contract']['case_ids'], ['C1'])
        self.assertEqual(state['max_fix_rounds'], old['max_fix_rounds'])
        proposal = f.proposal()
        for child in proposal['children']:
            child['scope']['requirement_ids'] = ['R1', 'R2']; child['case_ids'] = ['C1', 'C2']
        f.call('redecompose', {'plan_ref': f.ref('extended-split.json', proposal)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('extended-split-review.md', 'Reviewed both requirements and cases')},
               role='global-orchestrator', module='M010')
        f.global_plan(requirement_owners={'R1': ['M001', 'M002'], 'R2': ['M001', 'M002']},
                      case_owners={'C1': ['M001', 'M002'], 'C2': ['M001', 'M002']})
        self.assertTrue(all(m['freeze_id'] is None for m in f.state()['modules'].values()))

    def test_contract_cannot_delete_old_acceptance_or_omit_new_coverage(self):
        f = self.f
        report = self.report([]); report['global_spec_ref'] = f.ref('changed-business.md', 'Corrected contract')
        report['contract_patch'] = {'case_ids': ['C2']}
        with self.assertRaisesRegex(Rejected, 'cannot be removed'):
            run_changes.validate(f.state(), f.ref('delete-case.json', report))
        report['contract_patch'] = {'case_ids': ['C1', 'C2']}
        with self.assertRaisesRegex(Rejected, 'coverage'):
            run_changes.validate(f.state(), f.ref('missing-owner.json', report))

    def test_parent_redecomposition_keeps_unaffected_active_sibling(self):
        f = self.f; f.prepare_leaf('M001'); f.prepare_leaf('M002')
        f.call('assign', {'role': 'test-runner', 'assignment_id': 'BUSY-SIBLING', 'instance_id': 'tester'}, module='M002')
        before = f.state(); m = before['modules']['M002']
        proposal = f.proposal(); proposal['children'][0]['scope']['in'] = ['Corrected M001 boundary']
        f.call('redecompose', {'plan_ref': f.ref('local-parent-revision.json', proposal)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('local-parent-review.md', 'Only M001 changes; M002 execution inputs unchanged')},
               role='global-orchestrator', module='M010')
        state = f.state()
        self.assertEqual(state['modules']['M002']['revision'], m['revision'])
        self.assertEqual(state['modules']['M002']['freeze_id'], m['freeze_id'])
        self.assertFalse(state['modules']['M002']['assignments']['BUSY-SIBLING']['closed'])
        self.assertEqual(cr.subject(state, 'M002', 'testing'), cr.subject(before, 'M002', 'testing'))
        self.assertEqual(cr.inputs(state, 'M002', 'testing'), cr.inputs(before, 'M002', 'testing'))
        self.assertIsNone(state['modules']['M001']['freeze_id'])

    def test_parent_redecomposition_cannot_reset_affected_active_worker(self):
        f = self.f; f.prepare_leaf('M001')
        f.call('assign', {'role': 'test-runner', 'assignment_id': 'BUSY-AFFECTED', 'instance_id': 'tester'})
        proposal = f.proposal(); proposal['children'][0]['scope']['in'] = ['Corrected M001 boundary']
        f.call('redecompose', {'plan_ref': f.ref('busy-parent-revision.json', proposal)}, module='M010')
        step = next(row for row in f.state()['next_steps'] if row['module_id'] == 'M010')
        self.assertFalse(step['ready'])
        self.assertEqual(step['reason'], 'wait-for-affected-workers')
        before = ledger.read_events(f.root)
        with self.assertRaisesRegex(Rejected, 'worker|assignment'):
            f.call('redecompose-accept', {'review_ref': f.ref('busy-parent-review.md', 'Wait for affected worker')},
                   role='global-orchestrator', module='M010')
        self.assertEqual(ledger.read_events(f.root), before)


class PreparedRunRevisionTests(unittest.TestCase):
    def setUp(self):
        self.source = test_source_changes.SourceChangeTests(); self.source.setUp(); self.addCleanup(self.source.doCleanups)
        self.f = self.source.f

    def test_historical_context_uses_current_budget_without_rewriting_history(self):
        f = self.f; state = f.state()
        snapshot = copy.deepcopy(project_context.verify_snapshot(state['project_context_ref']))
        snapshot['control_policy_version'] = 1
        snapshot['effective_config'].setdefault('defaults', {}).setdefault('budgets', {}).update(local_fix_rounds=1, max_fix_rounds=3)
        historical = project_context.encoded(snapshot)
        ref = project_context.archive(f.root / 'context/files', historical, '.snapshot')
        state['project_context_ref'] = ref
        current = project_context.prepared_input(ref)
        self.assertNotIn('control_policy_version', current)
        self.assertNotIn('local_fix_rounds', current)
        self.assertEqual(current['max_fix_rounds'], 3)
        report = self.report({'runtime': {'fixture': 'current'}})
        report_ref = f.ref('historical-context-review.json', report)
        run_changes.validate(state, report_ref)
        updated = run_changes.revise_context(f.root, state, report['context_patch'], {'report_ref': report_ref}, {})
        projected = project_context.verify_snapshot(updated)
        self.assertNotIn('local_fix_rounds', projected['effective_config']['defaults']['budgets'])
        self.assertEqual(projected['run_id'], state['run_id'])
        self.assertEqual(check_ref(ref).read_bytes(), historical)

    def report(self, patch, affected=('M001', 'M002')):
        f = self.f
        return {'schema_version': 1, 'run_id': 'demo', 'reason': 'Reviewed execution configuration correction',
            'context_patch': patch, 'root_updates': [],
            'boundary_review': {'semantic_change': False, 'authorization_change': False, 'unresolved_questions': [], 'reason': 'Reviewed correction preserves user goal and acceptance', 'evidence_refs': [f.ref('revision-boundary.md', 'Original requirements and acceptance preserved')]}, 'modules': [{'module_id': mid,
                'action': 'replan' if mid in affected else 'unchanged', 'reason': 'Compared frozen execution requirements',
                'evidence_refs': [f.ref('configuration-impact.md', 'Compared both module configurations')], 'resume_blocker_sha256': None}
                for mid in f.state()['modules']]}

    def test_clear_technical_correction_does_not_require_human_or_new_run(self):
        f = self.f
        report = self.report({'build': {'timeout_seconds': 20}})
        report['global_spec_ref'] = f.ref('goal-format-correction.md', check_ref(f.state()['global_spec']).read_text() + '\n')
        ref = f.ref('technical-revision.json', report)
        receipt = f.ref('technical-context.json', f.report('global-planning', module=None, draft=ref))
        f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        step = f.state()['global_next_step']
        self.assertEqual(step['operation'], 'revise-run'); self.assertTrue(step['ready'])
        self.assertNotIn('decision_id', step['payload'])
        f.call('revise-run', step['payload'], role='host', module=None)
        self.assertEqual(f.state()['run_id'], 'demo')
        self.assertEqual(f.state()['decisions'], {})

    def test_semantic_revision_still_requires_precise_human_decision(self):
        f = self.f; report = self.report({'build': {'timeout_seconds': 20}})
        report['boundary_review']['semantic_change'] = True
        ref = f.ref('semantic-revision.json', report)
        receipt = f.ref('semantic-context.json', f.report('global-planning', module=None, draft=ref))
        f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        step = f.state()['global_next_step']; self.assertFalse(step['ready'])
        with self.assertRaisesRegex(Rejected, 'exact human decision'):
            f.call('revise-run', step['payload'], role='host', module=None)

    def review(self, report):
        f = self.f; ref = f.ref('prepared-revision.json', report)
        receipt = f.ref('run-review-context.json', f.report('global-planning', module=None, draft=ref))
        f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        subject = f.state()['run_change_review']['subject_sha256']
        f.call('decision', {'decision_id': 'CONFIG', 'decision': 'approved', 'module_id': None,
            'subject_sha256': subject, 'human_source_ref': f.ref('config-decision.md', 'Approve exact config impacts')}, role='host', module=None)
        return {'decision_id': 'CONFIG', 'subject_sha256': subject}

    def test_approved_execution_review_survives_green_worker_settlement(self):
        from test_run_rehearsal import MO, RunWalk

        f = self.f; src = self.source
        src.freeze('M001')
        f.call('assign', {'role': 'implementer', 'assignment_id': 'I1', 'instance_id': 'coder'})
        walk = RunWalk(); walk.f = f; walk.t = src
        walk.model_turn(next(step for step in f.state()['next_steps'] if step['module_id'] == 'M001'))
        f.call('accept', {'assignment_id': 'I1'})
        ledger.advance(f.root, MO, 'M001', defer_commands=True)
        payload = self.review(self.report({'build': {'timeout_seconds': 20}}, affected=('M001',)))
        self.assertEqual(run_changes.next_action(f.state())['reason'], 'wait-for-affected-workers')
        ledger.advance(f.root, MO, 'M001')
        state = f.state()
        self.assertEqual(run_changes.next_action(state)['reason'], 'run-context-switch-ready')
        for key, value in [('code_baseline', 'moved code'), ('freeze_id', 'new freeze'), ('blocked', {'kind': 'human'})]:
            changed = copy.deepcopy(state)
            changed['modules']['M001'][key] = value
            self.assertEqual(run_changes.next_action(changed)['reason'], 'run-review-stale')
        state['modules']['M001']['results']['M001-U']['quality'] = 'red-bug'
        self.assertEqual(run_changes.next_action(state)['reason'], 'run-review-stale')
        f.raw('revise-run', payload, role='host', module=None)
        self.assertTrue(f.state()['decisions']['CONFIG']['consumed'])

    def test_root_revision_keeps_an_independent_frozen_leaf_dispatchable(self):
        from test_run_rehearsal import MO, RunWalk

        f = self.f; src = self.source
        src.freeze('M002')
        before = f.state()
        parent = before['module_groups']['M010']
        update = {key: copy.deepcopy(parent[key]) for key in run_changes.ROOT_KEYS if key in parent}
        update['scope']['in'].append('Clarify only M001 scope')
        analysis = read_json(check_ref(update['dimension_analysis_ref']))
        analysis['scope'] = update['scope']
        update['dimension_analysis_ref'] = f.ref('revised-parent-dimensions.json', analysis)
        update['behavior_review']['scope_sha256'] = digest(update['scope'])
        report = self.report({}, affected=('M001',))
        report['root_updates'] = [update]
        report['boundary_review']['semantic_change'] = True
        f.raw('revise-run', self.review(report), role='host', module=None)
        state, _ = ledger.read_events(f.root)
        self.assertIsNone(state['global_plan'])
        self.assertEqual(state['module_groups']['M010']['replanning_children'], ['M001'])
        self.assertEqual(state['modules']['M002']['freeze_id'], before['modules']['M002']['freeze_id'])
        with self.assertRaisesRegex(Rejected, 'global coverage'):
            workflow.planning_guard(state)
        with self.assertRaisesRegex(Rejected, 'global coverage'):
            workflow.planning_guard(state, 'M001')
        for field, value in [('dependencies', ['M001']), ('freeze_id', 'different freeze')]:
            changed = copy.deepcopy(state)
            changed['modules']['M002'][field] = value
            with self.assertRaisesRegex(Rejected, 'global coverage'):
                workflow.planning_guard(changed, 'M002')
        changed = copy.deepcopy(state)
        changed['modules']['M001']['write_paths'] = state['modules']['M002']['write_paths']
        with self.assertRaisesRegex(Rejected, 'global coverage'):
            workflow.planning_guard(changed, 'M002')

        ledger.advance(f.root, MO, 'M002', defer_commands=True)
        step = next(row for row in f.state()['next_steps'] if row['module_id'] == 'M002')
        self.assertEqual((step['operation'], step['role']), ('await-result', 'implementer'))
        walk = RunWalk(); walk.f = f; walk.t = src
        walk.model_turn(step)
        f.call('accept', {'assignment_id': step['assignment_id']}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'], 'testing')
        self.assertIsNone(f.state()['global_plan'])

    def test_context_revision_keeps_original_snapshot_and_unaffected_green(self):
        f = self.f; src = self.source
        src.freeze('M001'); src.freeze('M002'); src.implement_and_test('M002')
        old = f.state(); old_bytes = check_ref(src.original_ref).read_bytes()
        payload = self.review(self.report({'build': {'argv': ['fixture-build-v2']}}, affected=('M001',)))
        f.raw('revise-run', payload, role='host', module=None)
        s = f.state()
        self.assertNotEqual(s['project_context_ref'], src.original_ref)
        self.assertEqual(check_ref(src.original_ref).read_bytes(), old_bytes)
        self.assertEqual(project_context.verify_snapshot(s['project_context_ref'])['previous_context_ref'], src.original_ref)
        self.assertEqual(s['modules']['M002']['phase'], 'completed')
        self.assertEqual(s['modules']['M002']['results'], old['modules']['M002']['results'])
        self.assertFalse(s['observed_invalidations'])
        self.assertEqual(s['build']['argv'], ['fixture-build-v2'])
        self.assertIsNone(s['modules']['M001']['freeze_id'])

    def test_device_only_revision_keeps_current_build_unit_and_static_receipts(self):
        from test_run_rehearsal import RunWalk
        from execute_test import adapter_for

        src = test_source_changes.SourceChangeTests(); self.addCleanup(src.doCleanups)
        device = {'platforms': ['android', 'web'], 'android': {'serial': 'old-device'}, 'web': {'url': 'https://example.test'}}
        f = src.register_root(config={'test_adapter': {'device': device}})
        self.f = f
        f.split(src.d.proposal(ids=('M001', 'M002')))
        f.global_plan(); src.freeze('M001'); src.freeze('M002'); src.implement_and_test('M002')
        state = f.state(); old = state['modules']['M002']
        old_env = state['target_preview']['environments']['android']
        report = self.report({'test_adapter': {'device': {'android': {'serial': 'new-device'}}}}, affected=('M002',))
        next(row for row in report['modules'] if row['module_id'] == 'M002')['action'] = 'reverify'
        f.raw('revise-run', self.review(report), role='host', module=None)
        state = f.state(); current = state['modules']['M002']
        self.assertEqual((current['freeze_id'], current['code_baseline'], current['build_baseline']),
                         (old['freeze_id'], old['code_baseline'], old['build_baseline']))
        for suffix in ('B', 'U', 'S'):
            pid = 'M002-' + suffix
            self.assertEqual(current['results'][pid], old['results'][pid])
        self.assertTrue(current['results']['M002-P']['stale'])
        step = next(step for step in state['next_steps'] if step['module_id'] == 'M002')
        self.assertEqual((step['test_scope'], step['payload']['path_ids']), ('automation', ['M002-P']))
        self.assertIn('new-device', adapter_for(state, {'platform': 'android'}, f.root)['argv'])
        self.assertEqual(read_json(check_ref(old_env))['visual_capture']['device_id'], 'old-device')
        from lean_visual_worker import configuration
        contract, settings = configuration(f.root, {'visual_execution': {'environment_ref': old_env}},
                                            state['target_preview']['visual_environment_rebindings'])
        self.assertEqual(contract['environment_ref'], old_env)
        self.assertEqual(settings['visual_capture']['device_id'], 'new-device')

        walk = RunWalk(); walk.f = f; walk.t = src
        f.raw('assign', {**step['payload'], 'assignment_id': 'DEVICE-RETEST', 'instance_id': 'test-runner'}, module='M002')
        walk.model_turn(next(step for step in f.state()['next_steps'] if step['module_id'] == 'M002'))
        f.call('accept', {'assignment_id': 'DEVICE-RETEST'}, module='M002')
        result = f.state()['modules']['M002']['results']['M002-P']
        self.assertEqual((result['quality'], result['retest_of']), ('green-passed', old['results']['M002-P']['test_run_id']))
        self.assertEqual(f.state()['modules']['M002']['phase'], 'dod')

    def test_device_review_survives_an_independent_freeze_and_only_holds_affected_paths(self):
        from unittest.mock import patch
        import test_validation as tv

        f = self.f
        state = f.state()
        state['test_adapter'] = {'device': {'platforms': ['harmony'], 'harmony': {
            'profiles': {'physical-a': {'serial': 'one', 'model': 'A'}, 'physical-b': {'serial': 'two', 'model': 'B'}}}}}
        def path(pid, profile):
            return {'path_id': pid, 'kind': 'visual', 'platform': 'harmony', 'harmony_device_profile': profile}
        first, second = path('V1', 'physical-a'), path('V2', 'physical-b')
        mid = 'M001'
        module = state['modules'][mid]
        module.update(plan={'paths': [first, second]}, phase='testing', code_baseline='C')
        report = self.report({'test_adapter': {'device': {'harmony': {'profiles': {'physical-b': {'serial': 'new'}}}}}},
                             affected=(mid,))
        next(row for row in report['modules'] if row['module_id'] == mid)['action'] = 'reverify'
        ref = f.ref('device-path-review.json', report)
        review = {'report_ref': ref, 'status': 'reviewed', 'execution_review': True, 'device_path_review': True}
        state['run_change_review'] = review
        review['subject_sha256'] = run_changes.review_subject(state, review)
        peer = state['modules']['M002']
        peer.update(plan={'paths': [path('V3', 'physical-a')]}, freeze_id='peer-freeze', plan_hash='peer-plan')
        self.assertEqual(review['subject_sha256'], run_changes.review_subject(state, review))
        self.assertEqual(run_changes.pending_device_paths(state, mid), {'V2'})
        self.assertFalse(run_changes.execution_switch_pending(state, mid, ['V1']))
        self.assertTrue(run_changes.execution_switch_pending(state, mid, ['V2']))
        devices = run_changes.changed_devices(state, report)
        with patch.object(ledger, 'worker_dependencies_ready'), patch.object(tv, 'artifact_only_visual', return_value=True), \
                patch.object(run_changes, 'retain_verification', return_value=set()):
            assignment = {'role': 'test-runner', 'test_scope': 'visual', 'artifact_only': True,
                          'execution_contract': {'path_ids': ['V1']}}
            self.assertFalse(run_changes.blocks_switch(state, module, assignment, devices))
            assignment['execution_contract']['path_ids'] = ['V2']
            self.assertTrue(run_changes.blocks_switch(state, module, assignment, devices))
        peer['plan']['paths'].append(path('V4', 'physical-b'))
        self.assertNotEqual(review['subject_sha256'], run_changes.review_subject(state, review))

    def test_corrupt_hap_only_expires_its_build_and_consumers(self):
        from unittest.mock import patch
        import task_revalidation

        f = self.f
        good = f.ref('good.hap', 'good')
        bad = f.ref('bad.hap', 'before')
        build = {pid: {'path_id': pid, 'kind': 'build'} for pid in ('B1', 'B2')}
        visual = {pid: {'path_id': pid, 'kind': 'visual', 'platform': 'harmony'} for pid in ('V1', 'V2')}
        module = {'module_id': 'M001', 'code_baseline': 'C', 'freeze_id': 'F', 'phase': 'testing',
                  'build_artifacts': [good, bad], 'plan': {'paths': [*build.values(), *visual.values()]}, 'results': {}}
        proof = f.ref('test-input.json', {})
        for bid, vid, artifact in [('B1', 'V1', good), ('B2', 'V2', bad)]:
            for pid, fields in [(bid, {'build_artifacts': [artifact]}), (vid, {'visual_alignment': {'hap_ref': artifact}})]:
                receipt = f.ref(pid + '-device-reverify.json', {'producer': 'host-executor', 'run_id': 'demo',
                    'module_id': 'M001', 'path_id': pid, 'freeze_id': 'F', 'code_baseline': 'C', 'test_run_id': pid,
                    'query_ref': proof, 'result_ref': proof, 'log_ref': proof})
                module['results'][pid] = {'quality': 'green-passed', 'code_baseline': 'C', 'test_run_id': pid,
                                          'executed': True, 'execution_receipt': receipt, **fields}
        Path(bad['path']).write_text('drifted')
        with patch.object(ledger, 'current'), patch.object(ledger, 'dependencies_ready'), \
                patch.object(task_revalidation, 'current_build_paths', side_effect=lambda _s, _m, _root, ids: ids):
            run_changes.reverify({'run_id': 'demo'}, module, {'harmony-physical-a'}, proof, root=f.root)
        self.assertEqual(module['retained_build_paths'], ['B1'])
        self.assertFalse(module['results']['V1'].get('stale', False))
        self.assertTrue(module['results']['V2']['stale'])

    def test_device_change_scopes_global_results_and_active_integration(self):
        src = test_source_changes.SourceChangeTests(); self.addCleanup(src.doCleanups)
        device = {'platforms': ['android', 'web'], 'android': {'serial': 'before'}, 'web': {'url': 'https://example.test'}}
        paths = [{'path_id': 'G-' + platform, 'platform': platform, 'kind': 'automation', 'case_id': 'C1',
                  'name': platform + ' integration', 'expected_assertions': [{'assertion_id': 'A1', 'expected': True}]}
                 for platform in ('android', 'web')]
        f = src.register_root(global_paths=paths, config={'test_adapter': {'device': device}})
        self.f = f
        f.split(src.d.proposal(ids=('M001', 'M002'))); f.global_plan()
        state, _ = ledger.read_events(f.root)
        state['audit_results'] = {p['path_id']: {'quality': 'green-passed', 'test_run_id': p['path_id']} for p in paths}
        report = self.report({'test_adapter': {'device': {'android': {'serial': 'after'}}}}, affected=())
        go = {'role': 'global-orchestrator', 'instance_id': 'go'}
        host = {'role': 'host', 'instance_id': 'host'}
        run_changes.handle(f.root, state, {'operation': 'run-review', 'payload': {'report_ref': f.ref('device-impact.json', report)}}, go)
        request = {'operation': 'revise-run', 'payload': {'subject_sha256': state['run_change_review']['subject_sha256']}}
        state['integration_assignment'] = {'closed': False, 'path_ids': ['G-android'], 'assignment_id': 'INT1'}
        self.assertFalse(run_changes.next_action(state)['ready'])
        from unittest.mock import patch
        with patch('integration.stale', return_value=False):
            cursor = ledger.routing(state)['global_next_step']
        self.assertEqual((cursor['operation'], cursor['assignment_id'], cursor['ready']), ('integration-submit', 'INT1', True))
        with self.assertRaisesRegex(Rejected, 'affected integration'):
            run_changes.handle(f.root, state, request, host)
        state['integration_assignment']['path_ids'] = ['G-web']
        self.assertTrue(run_changes.next_action(state)['ready'])
        run_changes.handle(f.root, state, request, host)
        self.assertTrue(state['audit_results']['G-android']['stale'])
        self.assertEqual(state['audit_results']['G-web'], {'quality': 'green-passed', 'test_run_id': 'G-web'})

    def test_unrelated_run_revision_keeps_an_audit_scope_request_open(self):
        import audit_closure

        f = self.f; state = ledger.read_events(f.root)[0]
        mid = 'M002'; finding = 'TRACE-B1-F1'
        go = {'role': 'global-orchestrator', 'instance_id': 'go'}
        mo = {'role': 'module-orchestrator', 'instance_id': 'mo'}
        batch = {'batch_id': 'B1', 'status': 'repairing',
                 'routes': {'F1': {'action': 'trace', 'owner_module_ids': [mid], 'source_module_id': mid,
                                   'analysis_ref': f.ref('scope-trace.md', 'The leaf is missing an allocated route'),
                                   'root_cause': {'category': 'scope-insufficient', 'confidence': 'confirmed'}}}}
        state['audit_batch'] = batch
        audit_closure.trace_back(state, batch, go)
        step = ledger.traced_revision(state, state['modules'][mid], [finding])
        decomposition.handle(state, {'module_id': mid, 'operation': step['operation'], 'payload': step['payload']}, mo, f.root)
        request = copy.deepcopy(state['modules'][mid]['realloc_request'])
        report = f.ref('unrelated-timeout.json', self.report({'build': {'timeout_seconds': 20}}, affected=('M001',)))
        run_changes.handle(f.root, state, {'operation': 'run-review', 'payload': {'report_ref': report}}, go)
        run_changes.handle(f.root, state, {'operation': 'revise-run', 'payload': {
            'subject_sha256': state['run_change_review']['subject_sha256']}}, {'role': 'host', 'instance_id': 'host'})
        self.assertEqual(state['build']['timeout_seconds'], 20)
        self.assertEqual(state['modules'][mid]['realloc_request'], request)
        self.assertEqual(state['modules'][mid]['phase'], 'waiting-upstream')
        self.assertNotIn(mid, state['issues'][finding]['resolved'])

    def test_context_revision_rejects_identity_and_quality_gate_changes(self):
        for patch in ({'target_root': str(self.f.target)}, {'defaults': {'quality_gates': {'unit_tests_required': False}}}):
            with self.subTest(patch=patch), self.assertRaisesRegex(Rejected, 'identity'):
                run_changes.validate(self.f.state(), self.f.ref('forbidden-revision.json', self.report(patch)))

    def test_global_business_spec_revision_requires_new_global_plan(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        old = f.state()['global_spec']
        report = self.report({})
        report['global_spec_ref'] = f.ref('revised-global-spec.md', 'Correct R1 business boundary; C1 must cover corrected behavior')
        payload = self.review(report)
        f.raw('revise-run', payload, role='host', module=None)
        s = f.state()
        self.assertEqual(s['global_spec'], report['global_spec_ref'])
        self.assertIsNone(s['global_plan'])
        self.assertEqual(s['run_change_history'][-1]['previous_global_spec'], old)
        self.assertEqual(s['global_next_step']['operation'], 'global-plan')
        self.assertTrue(all(m['freeze_id'] is None for m in s['modules'].values()))

    def test_worker_progress_makes_revision_approval_stale(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        payload = self.review(self.report({'runtime': {'fixture': 'v2'}}))
        f.call('assign', {'role': 'implementer', 'assignment_id': 'BUSY', 'instance_id': 'coder'}, module='M002')
        with self.assertRaisesRegex(Rejected, 'stale'):
            f.raw('revise-run', payload, role='host', module=None)
        self.assertEqual(f.state()['project_context_ref'], src.original_ref)

    def test_unaffected_worker_progress_keeps_approval_and_accepted_execution_context(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        report = self.report({'build': {'argv': ['fixture-build-v2']}}, affected=('M001',))
        report['global_spec_ref'] = f.ref('active-business-revision.md', 'M001 correction; M002 frozen requirements unchanged')
        payload = self.review(report)
        f.call('assign', {'role': 'implementer', 'assignment_id': 'CONTINUE', 'instance_id': 'coder'}, module='M002')
        before = f.state(); module = before['modules']['M002']; assignment = module['assignments']['CONTINUE']
        coding_subject = cr.subject(before, 'M002', 'coding')
        coding_inputs = cr.inputs(before, 'M002', 'coding')
        self.assertTrue(before['run_change_next_step']['ready'])
        f.raw('revise-run', payload, role='host', module=None)
        state = f.state()
        self.assertEqual(state['modules']['M002']['revision'], module['revision'])
        self.assertEqual(cr.subject(state, 'M002', 'coding'), coding_subject)
        self.assertEqual(cr.inputs(state, 'M002', 'coding'), coding_inputs)
        cr.validate(state, 'M002', 'coding', assignment['context_ref'], 'coder')
        f.global_plan()
        cr.validate(f.state(), 'M002', 'coding', assignment['context_ref'], 'coder')
        view = ledger.status(f.root, view='step', module_id='M002')
        self.assertTrue(view['module']['execution_context_ref'])
        code = Path(module['write_paths'][0]) / 'code.py'; code.parent.mkdir(exist_ok=True); code.write_text('value = 2\n')
        proof = f.ref('continued-binding.md', 'Same frozen production behavior')
        refs = [file_ref(code)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M002',
            'assignment_id': 'CONTINUE', 'actor_instance_id': 'coder', 'freeze_id': module['freeze_id'],
            'code_files': refs, 'code_baseline': baseline(refs), 'task_trace': [{'task_id': 'T1', 'files': [str(code)]}],
            'production_binding_evidence': proof, 'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture', 'log_ref': proof},
            'dimension_evidence': [{'item_id': 'M002-Logic', 'task_ids': ['T1'], 'summary': 'Scoped implementation', 'evidence_refs': [proof]}]}
        f.call('submit', {'assignment_id': 'CONTINUE', 'fencing_token': assignment['fencing_token'],
                         'result_ref': f.ref('continued-result.json', result)}, role='implementer', instance='coder', module='M002')
        f.call('accept', {'assignment_id': 'CONTINUE'}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'], 'testing')
        self.assertEqual(f.state()['modules']['M002']['freeze_id'], module['freeze_id'])

    def test_global_spec_revision_retains_unaffected_green_with_reviewed_scope(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002'); src.implement_and_test('M002')
        old = f.state()['modules']['M002']
        report = self.report({}, affected=('M001',))
        report['global_spec_ref'] = f.ref('local-business-correction.md', 'Correct M001 allocation; M002 contract remains identical')
        payload = self.review(report); f.raw('revise-run', payload, role='host', module=None)
        state = f.state()
        self.assertEqual(state['modules']['M002']['results'], old['results'])
        self.assertEqual(state['modules']['M002']['freeze_id'], old['freeze_id'])
        self.assertIsNone(state['global_plan'])
        self.assertIsNone(state['modules']['M001']['freeze_id'])
        f.global_plan()
        decomposition.check_module_plan(f.state(), f.state()['modules']['M002'], old['plan'])

    def test_a_consumer_of_a_leaf_that_plans_again_keeps_its_plan(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        state = f.state(); state['modules']['M002']['dependencies'] = ['M001']
        report = self.report({}, affected=('M001',))
        report['global_spec_ref'] = f.ref('provider-business.md', 'Correct shared provider behavior')
        _, affected, _ = run_changes.validate(state, f.ref('provider-only-impact.json', report))
        self.assertEqual(affected, {'M001'})  # the consumer is not sent back with its provider
        self.assertEqual(decomposition.built_on(state, {'M001'}), set())  # and holds no code that would have to wait
        state['modules']['M002']['code_baseline'] = {'files': 'built on the provider'}
        self.assertEqual(decomposition.built_on(state, {'M001'}), {'M002'})
        waiting = state['modules']['M002']; revision = waiting['revision']
        ledger.await_provider(waiting)
        self.assertEqual((waiting['phase'], waiting['stale'], waiting['blocked']['reason'], waiting['blocked']['resume_phase'], waiting['revision']),
                         ('waiting-dependency', True, 'dependency-version-changed', 'frozen', revision + 1))
        self.assertTrue(waiting['freeze_id'] and waiting['plan'])  # its plan and freeze stand

    def test_revision_only_releases_the_exact_reviewed_blocker(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        f.call('suspend', {'kind': 'human', 'reason': 'Resolve the upstream assumption',
                          'root_cause': 'Incorrect plan', 'owner': 'human'}, module='M001')
        blocker = f.state()['modules']['M001']['blocked']
        report = self.report({'runtime': {'fixture': 'v2'}})
        report['modules'][0]['resume_blocker_sha256'] = digest(blocker)
        payload = self.review(report)
        f.raw('revise-run', payload, role='host', module=None)
        module = f.state()['modules']['M001']
        self.assertIsNone(module['blocked'])
        self.assertEqual(module['phase'], 'specifying')
        self.assertIsNone(module['freeze_id'])

    def test_runtime_revision_isolates_environment_and_keeps_old_bundle(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
        from harmony_environment import prepare_environment
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        old_config, old_env = prepare_environment(f.root)
        before = (old_config.read_bytes(), old_env.read_bytes())
        payload = self.review(self.report({'runtime': {'fixture': 'v2'}}, affected=('M001',)))
        f.raw('revise-run', payload, role='host', module=None)
        new_config, new_env = prepare_environment(f.root)
        self.assertNotEqual(old_config.parent, new_config.parent)
        self.assertEqual(new_config.parent.name, 'environment-' + f.state()['project_context_ref']['sha256'])
        self.assertEqual((old_config.read_bytes(), old_env.read_bytes()), before)
        self.assertEqual(new_config.parent, prepare_environment(f.root)[0].parent)
        self.assertEqual(old_config.parent, prepare_environment(f.root, module_id='M002')[0].parent)
        self.assertEqual(new_config.parent, prepare_environment(f.root, module_id='M001')[0].parent)
