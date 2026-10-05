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
        update = self.update('M010'); update['scope']['in'] = ['Corrected search scope']
        self.apply(self.report([update]))
        s = f.state()
        self.assertEqual(s['run_id'], 'demo')
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
        consumer.update(module_id='M020', name='Consumer', decomposition_required=True, dependencies=['M001', 'M002'])
        f.call('register', consumer, role='global-orchestrator', module=None)
        f.split(f.proposal('M020', ('M003', 'M004')), parent='M020')
        f.call('redecompose', {'plan_ref': f.ref('replacement-split.json', f.proposal(ids=('M005', 'M002')))}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('replacement-review.md', 'Provider replaced; consumers reviewed')},
               role='global-orchestrator', module='M010')
        s = f.state()
        self.assertEqual(s['module_groups']['M020']['dependencies'], ['M002', 'M005'])
        self.assertEqual(s['modules']['M003']['dependencies'], ['M002', 'M005'])
        f.call('redecompose', {'plan_ref': f.ref('consumer-split.json', f.proposal('M020', ('M003', 'M004')))}, module='M020')

    def test_atomic_root_can_request_go_review_and_decision_is_mandatory(self):
        f = self.f
        root = self.update('M010'); root.update(module_id='M020', lean_leaf=True, leaf_review_ref=f.ref('leaf.md', 'Atomic root'))
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

    def test_atomic_dependency_revision_recommends_global_coverage_review(self):
        f = self.f
        root = self.update('M010'); root.update(module_id='M020', lean_leaf=True, leaf_review_ref=f.ref('atomic.md', 'Atomic root'))
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

    def test_impact_must_include_consumers_even_for_partial_global_spec_change(self):
        src, f = self.source, self.f
        src.freeze('M001'); src.freeze('M002')
        state = f.state(); state['modules']['M002']['dependencies'] = ['M001']
        report = self.report({}, affected=('M001',))
        report['global_spec_ref'] = f.ref('provider-business.md', 'Correct shared provider behavior')
        with self.assertRaisesRegex(Rejected, 'dependent closure'):
            run_changes.validate(state, f.ref('incomplete-impact.json', report))

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
