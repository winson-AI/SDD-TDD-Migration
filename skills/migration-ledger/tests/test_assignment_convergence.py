"""Same-Run convergence and scoped loading, through real Ledger events where applicable."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import api_contract
import audit_closure as ac
import design_stage
import experience
import ledger
import reading
import resource_fidelity as rf
import run_changes
import test_audit_closure
import test_audit_scheduler
import test_ledger
import test_progressive_fidelity
import test_run_changes
from contracts import Rejected


class AuditConvergenceTests(unittest.TestCase):
    def flow(self):
        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        old = f.state(); f.root = f.base / 'policy-two'
        f.call('init', {**{key: old[key] for key in ('target_root', 'legacy_root', 'global_spec', 'new_architecture', 'global_paths', 'case_ids', 'requirement_ids')},
            'max_fix_rounds': 3, 'dimension_slicing_required': False,
            'split_testing_required': False, 'context_readiness_required': False}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]}, role='global-orchestrator', module=None)
        return f

    def test_confirmed_provider_failure_retries_approved_owner_then_requires_fresh_tests(self):
        f = self.flow(); f.cross_module_failure()

        f.route()
        f.implement('M001', 'F1', shared=1, fixer=True); f.verify_module('M001', 'T3'); f.complete('M001')
        f.call('audit-retest', module='M002'); failed = f.verify_module('M002', 'T4', consume=True)
        s = f.state(); b = s['audit_batch']
        self.assertEqual(b['status'], 'repairing'); self.assertFalse(b['human_issues'])
        self.assertEqual(next(row for row in s['next_steps'] if row['module_id'] == 'M001')['operation'], 'audit-work')
        self.assertNotIn('M001', b['owner_tests']); self.assertNotIn('M002', b['source_tests'])
        self.assertEqual(b['test_history'][-1]['paths'][0]['test_run_id'], failed['paths'][0]['test_run_id'])
        f.call('audit-work', module='M001'); f.implement('M001', 'F2', shared=2, fixer=True)
        f.verify_module('M001', 'T5'); f.complete('M001')
        f.call('audit-retest', module='M002'); passed = f.verify_module('M002', 'T6', consume=True); f.complete('M002')
        self.assertEqual(passed['paths'][0]['retest_of'], failed['paths'][0]['test_run_id'])
        f.call('audit-verdict', {'review_ref': f.ref('verified-v2.md', 'Independent audit of both actual regressions')}, role='auditor', module=None)
        s = f.state(); self.assertEqual(s['run_id'], 'demo'); self.assertEqual(s['audit_batch']['status'], 'verified')
        self.assertEqual(s['modules']['M001']['fix_rounds_used'], 2)
        memories = s['modules']['M001']['fix_memory']
        self.assertEqual(memories[0]['status'], 'failed'); self.assertFalse(memories[0]['reusable'])
        self.assertEqual(memories[1]['status'], 'verified'); self.assertTrue(memories[1]['reusable'])

    def test_retry_does_not_bypass_uncertainty_budget_or_unrelated_owner(self):
        helper = test_audit_scheduler.AuditSchedulerTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        original = helper.scenario({'A': [], 'B': []}, ['A'])
        for cause, exhausted in (({'owner': 'A', 'confidence': 'suspected'}, False),
                                 ({'owner': 'B', 'confidence': 'confirmed'}, False),
                                 ({'owner': 'A', 'confidence': 'confirmed'}, True)):
            s = copy.deepcopy(original)
            b = helper.route(s, {'A': ['A']}); m = s['modules']['A']; m.update(phase='testing', blocked=None)
            if exhausted: m['fix_rounds_used'] = s['max_fix_rounds']
            bad = [{'quality': 'red-bug', 'root_cause': {'category': 'code', **cause}}]
            self.assertFalse(ac.retry_repair(s, m, bad, helper.f.ref('retry.md', 'Observed failure')))
            self.assertFalse(b.get('retry_owners'))

    def test_retry_stops_only_in_flight_workers_in_the_actual_dependency_closure(self):
        helper = test_audit_scheduler.AuditSchedulerTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        s = helper.scenario({'A': [], 'B': ['A'], 'C': []}, ['A'])
        b = helper.route(s, {'A': ['A']}); owner = s['modules']['A']; owner.update(phase='testing', blocked=None)
        for mid in ('B', 'C'):
            s['modules'][mid]['assignments']['BUSY-'+mid] = {'assignment_id': 'BUSY-'+mid, 'role': 'test-runner', 'closed': False}
        bad = [{'quality': 'red-bug', 'root_cause': {'category': 'code', 'owner': 'A', 'confidence': 'confirmed'}}]
        self.assertTrue(ac.retry_repair(s, owner, bad, helper.f.ref('queue.md', 'Confirmed failure')))
        self.assertEqual(b['retry_stops'], {'B': ['BUSY-B']})
        self.assertEqual(ac.module_step(s, s['modules']['B'])['operation'], 'revoke')
        self.assertIsNone(ac.module_step(s, s['modules']['C']))
        self.assertFalse(ac.module_step(s, owner)['ready'])
        ledger.mutate(s, {'operation': 'revoke', 'module_id': 'B', 'payload': {'assignment_id': 'BUSY-B',
            'stopped_worker_ref': helper.f.ref('stop-B.md', 'Host actually stopped this stale worker')}},
            {'role': 'host', 'instance_id': 'host'}, [], helper.f.root)
        self.assertFalse(b['human_issues']); self.assertEqual(b['status'], 'repairing')
        self.assertTrue(ac.module_step(s, owner)['ready'])


class ScopedReadingTests(unittest.TestCase):
    def setUp(self):
        helper = test_progressive_fidelity.ProgressiveReadingTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        self.helper = helper

    def module(self):
        ref = self.helper.ref({'api_inventory_ref': {'path': 'bound'}, 'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [{'item_id': 'UI', 'semantic_model': {'image_checks': ['IMG']}}]},
            {'dimension': 'Logic', 'status': 'applicable', 'items': [{'item_id': 'LOGIC', 'api_ids': ['QUERY']}]},
            {'dimension': 'Resource', 'status': 'applicable', 'items': [{'item_id': 'RESOURCE', 'source_signal': 'remote'}]}]})
        return {'plan': {'dimension_analysis_ref': ref, 'tasks': [
            {'task_id': 'API', 'path_ids': ['P1']}, {'task_id': 'SCREEN', 'path_ids': ['P2']}],
            'dimension_trace': [{'item_id': 'LOGIC', 'task_ids': ['API']}, {'item_id': 'UI', 'task_ids': ['SCREEN']},
                                {'item_id': 'RESOURCE', 'task_ids': ['SCREEN']}],
            'paths': [{'path_id': 'P1', 'kind': 'unit'}, {'path_id': 'P2', 'kind': 'visual', 'image_check_ids': ['IMG']}]}}

    def test_api_assignment_omits_sibling_ui_but_global_audit_keeps_it(self):
        m = self.module(); step = {'role': 'implementer', 'payload': {'task_ids': ['API'], 'path_ids': ['P1']}}
        facts = reading.topic_facts({}, m, step)
        self.assertTrue(facts['api']); self.assertFalse(facts['ui']); self.assertFalse(facts['pictures'])
        dispatched = ledger.worker_step({'role': 'implementer', 'assignment_id': 'DISPATCH', 'task_ids': ['API'], 'path_ids': ['P1']})
        self.assertEqual(reading.topic_facts({}, m, dispatched), facts)
        audit = reading.topic_facts({'modules': {'M001': m}}, None, {'role': 'auditor'})
        self.assertTrue(audit['ui']); self.assertTrue(audit['pictures'])
        m['assignments'] = {'A': {'execution_contract': {'task_ids': ['SCREEN'], 'path_ids': ['P2']}}}
        step['assignment_id'] = 'A'
        self.assertTrue(reading.topic_facts({}, m, step)['ui'])

    def test_reasoning_methods_activate_only_with_evidence(self):
        self.assertEqual(reading.reasoning_sections({'results': {}}), [])
        self.assertTrue(reading.reasoning_sections({'no_progress_rounds': 1}))
        self.assertTrue(reading.reasoning_sections({'results': {'P1': {'quality': 'yellow-blocked', 'root_cause': {'confidence': 'suspected'}}}}))
        self.assertEqual(reading.reasoning_sections({'results': {'P1': {'quality': 'red-bug', 'root_cause': {'confidence': 'confirmed'}}}}), [])

    def test_lesson_candidates_are_bounded_and_do_not_load_bodies(self):
        entries = [{'kind': 'planning-gap', 'summary': str(i), 'applicability': 'Search filters', 'lesson_ref': {'path': 'unopened-'+str(i)}} for i in range(9)]
        index = {'runs': {'old': {'entries': entries}}}
        self.assertEqual(len(experience.candidates(index, {'scope': {'in': ['Search']}})), 5)
        self.assertEqual(experience.candidates(index, {'scope': {'in': ['Orders']}}), [])


class ImageApiTests(unittest.TestCase):
    def test_recorded_image_field_must_bind_the_frozen_api_response_mapping(self):
        signal = {'id': 'IMAGE', 'kind': 'remote-image', 'source': {'kind': 'expression'},
                  'api': {'field': 'coverUrl', 'candidates': [{'jsonKey': 'cover_url'}]}, 'loader': {}}
        item = {'resource_kind': 'remote-image', 'resource_strategy': 'source_equivalent', 'target_source': 'photoUrl',
                'loader_mapping': {}, 'api_binding': {'api_id': 'QUERY', 'response_field': 'cover_url'}}
        contracts = {'QUERY': {'target': {'response_mapping': {'cover_url': 'photoUrl'}}}}
        rf.validate_signal_item(item, signal, set(), contracts)
        for change in ({'target_source': 'wrongField'}, {'api_binding': {'api_id': 'OTHER', 'response_field': 'cover_url'}},
                       {'api_binding': {'api_id': 'QUERY', 'response_field': 'other'}}):
            with self.subTest(change=change), self.assertRaises(Rejected): rf.validate_signal_item({**item, **change}, signal, set(), contracts)
        with self.assertRaises(Rejected): rf.validate_signal_item({**item, 'api_binding': None}, signal, set(), contracts)

    def test_local_model_origin_requires_evidence_and_still_checks_loader_behavior(self):
        helper = test_progressive_fidelity.ProgressiveReadingTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        signal = {'id': 'LOCAL', 'kind': 'remote-image', 'source': {'kind': 'expression'},
            'api': {'field': 'coverUrl', 'candidates': []}, 'loader': {'placeholder': ['@drawable/loading']}}
        item = {'resource_kind': 'remote-image', 'resource_strategy': 'source_equivalent', 'target_source': 'localModel.coverUrl',
            'loader_mapping': {'placeholder': 'LOADING'}, 'image_source_review': {'kind': 'non-api', 'reason': 'Local fixture supplies the model',
                'evidence_refs': [helper.ref({'origin': 'local-fixture'})]}}
        rf.validate_signal_item(item, signal, {'LOADING'}, {})
        with self.assertRaises(Rejected): rf.validate_signal_item({**item, 'loader_mapping': {}}, signal, {'LOADING'}, {})
        item['image_source_review']['evidence_refs'] = []
        with self.assertRaises(Rejected): rf.validate_signal_item(item, signal, {'LOADING'}, {})

    def test_applicability_review_cannot_waive_an_applicable_inventory(self):
        helper = test_progressive_fidelity.ApiContractTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        analysis = helper.analysis()
        with self.assertRaisesRegex(Rejected, 'applicability review'): api_contract.applicability(analysis, True)
        analysis['api_review'] = {'status': 'applicable', 'reason': 'Source-reviewed query call', 'evidence_refs': [helper.source['source_ref']]}
        api_contract.applicability(analysis, True)
        analysis['api_review']['status'] = 'not-applicable'
        with self.assertRaisesRegex(Rejected, 'disagree'): api_contract.applicability(analysis, True)


class PlanningRetentionTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_run_changes.PreparedRunRevisionTests(); self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.f = self.helper.f

    def test_unfrozen_plan_and_independent_design_survive_unrelated_context_revision(self):
        f = self.f; self.helper.source.freeze('M001'); self.helper.source.freeze('M002')
        f.call('planning-reopen', {'reason_ref': f.ref('reopen.md', 'Planning review before coding')}, module='M002')
        plan = self.helper.source.plan('M002')
        from test_design_stage import prepare_design
        prepare_design(f, plan, 'M002')
        f.call('plan', {'plan_ref': f.ref('unfrozen-M002.json', plan)}, role='spec-designer', module='M002')
        old = f.state(); m = old['modules']['M002']; subject = design_stage.subject(old, m)
        payload = self.helper.review(self.helper.report({'build': {'timeout_seconds': 20}}, affected=('M001',)))
        f.raw('revise-run', payload, role='host', module=None)
        s = f.state(); kept = s['modules']['M002']
        self.assertIsNone(kept['freeze_id']); self.assertEqual(kept['plan_ref'], m['plan_ref'])
        self.assertEqual(kept['accepted_test_design'], m['accepted_test_design'])
        self.assertEqual(design_stage.subject(s, kept), subject); self.assertTrue(design_stage.ready(s, kept))

    def test_environment_reverify_retains_spec_but_requires_new_execution(self):
        f = self.f; src = self.helper.source
        src.freeze('M001'); src.freeze('M002'); src.implement_and_test('M002')
        old = f.state()['modules']['M002']
        report = self.helper.report({'runtime': {'model_routing': {'strong': {'model': 'fixture-strong'}, 'low_cost': {'model': 'fixture-low'}}}}, affected=('M002',))
        next(row for row in report['modules'] if row['module_id'] == 'M002')['action'] = 'reverify'
        payload = self.helper.review(report); f.raw('revise-run', payload, role='host', module=None)
        m = f.state()['modules']['M002']; self.assertEqual(m['freeze_id'], old['freeze_id'])
        self.assertEqual(m['plan_ref'], old['plan_ref']); self.assertTrue(m['stale']); self.assertEqual(m['phase'], 'testing')
        self.assertTrue(all(row['stale'] for row in m['results'].values()))
        with self.assertRaises(Rejected): f.call('complete', {'dod_ref': f.ref('too-early.md', 'Old Green is stale')}, module='M002')
        bad = copy.deepcopy(report); bad['context_patch'] = {'build': {'timeout_seconds': 30}}
        with self.assertRaisesRegex(Rejected, 'require replan'): run_changes.validate(f.state(), f.ref('wrong-reverify.json', bad))


class SessionRotationTests(unittest.TestCase):
    def test_rotation_checkpoint_is_scope_bound_and_keeps_run_identity(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups); f.prepare()
        f.call('session', {'role': 'implementer', 'session_id': 'old'})
        m = f.state()['modules']['M001']
        checkpoint = {'run_id': 'demo', 'module_id': 'M001', 'role': 'implementer', 'previous_session_id': 'old',
            'plan_ref': m['plan_ref'], 'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'resume_refs': [m['plan_ref']]}
        bad = {**checkpoint, 'run_id': 'other'}
        with self.assertRaisesRegex(Rejected, 'wrong scope'):
            f.call('session', {'role': 'implementer', 'session_id': 'new', 'reason': 'context-rotation', 'checkpoint_ref': f.ref('bad-rotation.json', bad)})
        f.call('session', {'role': 'implementer', 'session_id': 'new', 'reason': 'context-rotation', 'checkpoint_ref': f.ref('rotation.json', checkpoint)})
        s = f.state(); self.assertEqual(s['run_id'], 'demo'); self.assertEqual(s['modules']['M001']['session_history'][-1]['session_id'], 'old')
