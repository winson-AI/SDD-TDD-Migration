"""Functional scope selection, independent child MOs and parent join gates."""
import copy
import unittest

import test_ledger
import test_audit_closure
import ledger
import decomposition as dc
from contracts import Rejected, digest


class DecompositionTests(unittest.TestCase):
    setUp = test_ledger.FlowTests.setUp
    ref = test_ledger.FlowTests.ref
    state = test_ledger.FlowTests.state
    attach_reuse = test_ledger.FlowTests.attach_reuse

    def plan(self):
        return self.attach_reuse(test_ledger.FlowTests.plan(self))
    global_plan = test_ledger.FlowTests.global_plan

    def call(self, op, payload=None, role='module-orchestrator', module='M001', instance=None):
        self.n += 1
        s = ledger.read_events(self.root)[0]
        if op == 'init':
            module = None
        scope = (s['modules'].get(module) or s.get('module_groups', {}).get(module)) if module and s else s
        return ledger.apply(self.root, {'schema_version': 1, 'request_id': str(self.n), 'run_id': 'demo',
            'module_id': module, 'expected_revision': scope['revision'] if scope else 0,
            'operation': op, 'payload': payload or {}}, {'role': role, 'instance_id': instance or role})

    def root_scope(self, mode='single-module'):
        original = self.state()
        self.root = self.base / 'hierarchical-run'
        self.call('init', {**{k: original[k] for k in ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required', 'target_root', 'legacy_root', 'case_ids',
                    'requirement_ids', 'global_spec', 'new_architecture', 'global_paths')},
                    'entry_mode': mode, 'single_module_id': 'M010' if mode == 'single-module' else None}, role='host')
        self.call('register', {'module_id': 'M010', 'name': 'Search', 'case_ids': ['C1'],
                    'write_paths': [str(self.target)], 'dependencies': [], 'decomposition_required': True,
                    'scope': {'in': ['Search'], 'out': ['Orders'], 'requirement_ids': ['R1']},
                    'context_refs': [self.ref('search-context.md', 'Search entry, reuse contracts, architecture and testing list')]},
                    role='global-orchestrator', module=None)

    def proposal(self, parent='M010', ids=('M001', 'M002'), dependencies=None):
        return {'parent_module_id': parent, 'rationale': 'independent functional behaviors and coverage',
                'planning_context': self.state()['planning_context'],
                'assigned_module': self.state()['module_inputs'][parent], 'children': [
                    {'module_id': mid, 'name': 'subfunction-' + mid, 'case_ids': ['C1'],
                     'write_paths': [str(self.target / ('m1' if mid == 'M001' else 'm2' if mid == 'M002' else 'm1/nested'))],
                     'dependencies': (dependencies or {}).get(mid, []),
                     'scope': {'in': ['subfunction-' + mid], 'out': ['Orders'], 'requirement_ids': ['R1']},
                     'context_refs': [self.ref('context-'+mid+'.md', 'Subfunction '+mid+' entry and reuse ownership')]} for mid in ids]}

    def split(self, plan=None, parent='M010'):
        self.call('decompose', {'plan_ref': self.ref('split-'+parent+'.json', plan or self.proposal(parent))}, module=parent)
        self.call('decompose-accept', {'review_ref': self.ref('review-'+parent+'.md', 'scope and ownership reviewed')},
                  role='global-orchestrator', module=parent)

    def prepare_leaf(self, mid):
        plan = self.plan()
        pid = 'P1' if mid == 'M001' else 'P2'
        plan.update(module_id=mid, planning_context=self.state()['planning_context'],
                    assigned_module=self.state()['module_inputs'][mid])
        plan['paths'][0]['path_id'] = pid
        plan['tasks'][0]['path_ids'] = [pid]
        self.attach_reuse(plan)
        self.call('plan', {'plan_ref': self.ref('plan-'+mid+'.json', plan)}, role='spec-designer', module=mid)
        self.call('decision', {'decision_id': mid, 'decision': 'approved', 'module_id': mid,
                  'subject_sha256': digest(plan), 'human_source_ref': self.ref('decision-'+mid+'.md', 'approved')}, role='host', module=None)
        self.call('freeze', {'decision_id': mid}, module=mid)
        test_audit_closure.ClosureTests.implement(self, mid, 'I-'+mid)

    def complete_leaf(self, mid):
        test_audit_closure.ClosureTests.verify_module(self, mid, 'T-'+mid)
        self.call('complete', {'dod_ref': self.ref('dod-'+mid+'.md', 'all paths verified'), 'checks_passed': True}, module=mid)

    def summarize(self, mid='M010'):
        group = self.state()['module_groups'][mid]
        self.call('module-summary', {'summary_ref': self.ref('summary-'+mid+'.md', 'child evidence reviewed'),
                  'subject_sha256': dc.summary_subject(self.state(), group)}, module=mid)

    def test_single_function_has_multiple_children_and_internal_dependencies(self):
        self.root_scope()
        self.assertEqual(self.state()['next_steps'][0]['operation'], 'decompose')
        self.split(self.proposal(dependencies={'M002': ['M001']}))
        s = self.state()
        self.assertEqual(set(s['modules']), {'M001', 'M002'})
        self.assertEqual(s['modules']['M002']['dependencies'], ['M001'])
        self.assertEqual(s['module_groups']['M010']['children'], ['M001', 'M002'])
        self.assertEqual(s['single_module_id'], 'M010')
        with self.assertRaises(Rejected):
            self.call('register', {'module_id': 'M003', 'case_ids': ['C1'], 'write_paths': [str(self.target)]},
                      role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'parent MO only'):
            self.call('assign', {'role': 'implementer', 'assignment_id': 'BAD', 'instance_id': 'coder'}, module='M010')

    def test_parent_and_child_plans_require_shared_global_context(self):
        self.root_scope()
        plan = self.proposal()
        del plan['planning_context']
        with self.assertRaisesRegex(Rejected, 'current global'):
            self.call('decompose', {'plan_ref': self.ref('bad.json', plan)}, module='M010')
        self.split(); self.global_plan()
        plan = self.plan()
        with self.assertRaisesRegex(Rejected, 'current global'):
            self.call('plan', {'plan_ref': self.ref('missing-context.json', plan)}, role='spec-designer')
        plan['planning_context'] = self.state()['planning_context']
        plan['assigned_module'] = self.state()['module_inputs']['M001']
        self.call('plan', {'plan_ref': self.ref('with-context.json', plan)}, role='spec-designer')
        self.assertEqual(plan['planning_context']['legacy_root'], str(self.legacy.resolve()))
        self.assertIn('M002', plan['planning_context']['modules'])
        self.assertIn('new_architecture', plan['planning_context'])

    def test_scope_coverage_cycles_and_role_boundaries(self):
        self.root_scope()
        for change, error in (
            (lambda p: p['children'][0].update(write_paths=[str(self.base / 'outside')]), 'outside parent'),
            (lambda p: p['children'][0].update(case_ids=['OTHER']), 'outside selected function'),
            (lambda p: p['children'][0].update(dependencies=['M999']), 'outside approved parent'),
            (lambda p: p['children'][0].update(dependencies=['M001']), 'cycle'),
        ):
            plan = self.proposal(); change(plan)
            with self.subTest(error=error), self.assertRaisesRegex(Rejected, error):
                self.call('decompose', {'plan_ref': self.ref('bad-'+str(self.n)+'.json', plan)}, module='M010')
        with self.assertRaisesRegex(Rejected, 'principal role denied'):
            self.call('decompose', {'plan_ref': self.ref('roles.json', self.proposal())}, role='implementer', module='M010')
        self.call('decompose', {'plan_ref': self.ref('valid.json', self.proposal())}, module='M010')
        with self.assertRaisesRegex(Rejected, 'principal role denied'):
            self.call('decompose-accept', {'review_ref': self.ref('review.md', 'reviewed')}, module='M010')
        with self.assertRaisesRegex(Rejected, 'complete MO decomposition'):
            self.global_plan()

    def test_all_children_green_still_require_parent_summary_then_final_auditor(self):
        self.root_scope(); self.split(); self.global_plan()
        for mid in ('M001', 'M002'):
            self.prepare_leaf(mid); self.complete_leaf(mid)
        self.assertEqual(self.state()['global_next_step']['reason'], 'await-parent-summaries')
        with self.assertRaises(Rejected):
            self.call('audit-assign', {'assignment_id': 'A1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.summarize()
        self.assertEqual(self.state()['module_groups']['M010']['quality'], 'green-passed')
        self.assertTrue(self.state()['module_rounds']['all_settled'])
        self.assertNotEqual(self.state()['quality'], 'green-passed')
        self.call('audit-assign', {'assignment_id': 'A1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.assertEqual(set(self.state()['audit_assignment']['snapshot']), {'M001', 'M002'})

    def test_blocked_child_does_not_stop_sibling_or_allow_early_summary(self):
        self.root_scope(); self.split(); self.global_plan()
        sibling = copy.deepcopy(self.state()['modules']['M002'])
        self.call('suspend', {'kind': 'human', 'reason': 'M001 business question', 'root_cause': 'ambiguous behavior', 'owner': 'human'})
        self.assertEqual(self.state()['modules']['M002'], sibling)
        with self.assertRaisesRegex(Rejected, 'all descendants settled'):
            self.summarize()
        self.prepare_leaf('M002'); self.complete_leaf('M002')
        with self.assertRaises(Rejected):
            self.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.summarize()
        self.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.assertEqual(set(self.state()['audit_batch']['sources']), {'M001'})
        self.assertEqual(self.state()['modules']['M002']['quality'], 'green-passed')

    def test_project_contains_separate_parents_and_global_context_changes_require_review(self):
        self.root_scope('project')
        old = self.proposal()
        self.call('register', {'module_id': 'M020', 'name': 'Orders', 'case_ids': ['C1'],
                  'write_paths': [str(self.target / 'orders')], 'dependencies': ['M010']}, role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'current global'):
            self.call('decompose', {'plan_ref': self.ref('stale-context.json', old)}, module='M010')
        self.split()
        self.assertEqual(self.state()['modules']['M020']['dependencies'], ['M001', 'M002'])
        self.assertIn('M020', self.state()['planning_context']['modules'])
        self.assertFalse(self.state()['module_rounds']['all_settled'])

    def test_child_mo_decomposes_tasks_not_more_mos(self):
        self.root_scope(); self.split()
        with self.assertRaisesRegex(Rejected, 'child MO decomposes tasks'):
            self.split(self.proposal('M001', ('M003',)), parent='M001')
        self.assertEqual(set(self.state()['modules']), {'M001', 'M002'})
        self.global_plan(); self.prepare_leaf('M001')
        self.assertEqual(self.state()['modules']['M001']['plan']['tasks'][0]['task_id'], 'T1')

    def test_parent_must_acknowledge_allocation_and_preserve_business_scope(self):
        self.root_scope()
        for change, error in (
            (lambda p: p.pop('assigned_module'), 'acknowledge current assigned'),
            (lambda p: p['children'][0]['scope'].update(requirement_ids=['OTHER']), 'outside parent scope'),
            (lambda p: p['children'][0]['scope'].update(out=[]), 'retain parent exclusions'),
            (lambda p: p['children'][0].update(context_refs=[]), 'focused module context'),
            (lambda p: p['children'][0].update(decomposition_required=True), 'child MO decomposes tasks'),
        ):
            plan = self.proposal(); change(plan)
            with self.subTest(error=error), self.assertRaisesRegex(Rejected, error):
                self.call('decompose', {'plan_ref': self.ref('scope-'+str(self.n)+'.json', plan)}, module='M010')
        self.split()
        packet = self.state()['module_inputs']['M001']
        self.assertEqual(packet['parent_context']['module_id'], 'M010')
        self.assertEqual(packet['scope']['in'], ['subfunction-M001'])
        self.assertEqual(packet['parent_context']['scope']['in'], ['Search'])

    def test_child_tasks_and_tests_cannot_expand_assigned_scope(self):
        self.root_scope(); self.split(); self.global_plan()
        for change, error in (
            (lambda p: p.pop('assigned_module'), 'acknowledge current assigned'),
            (lambda p: p['assigned_module']['scope'].update(requirement_ids=['OTHER']), 'acknowledge current assigned'),
            (lambda p: p['tasks'][0].update(global_requirement_ids=['OTHER']), 'outside assigned submodule'),
            (lambda p: p['paths'][0].update(case_id='OTHER'), 'test cases outside assigned'),
        ):
            plan = self.plan()
            plan.update(planning_context=self.state()['planning_context'],
                        assigned_module=self.state()['module_inputs']['M001'])
            change(plan)
            with self.subTest(error=error), self.assertRaisesRegex(Rejected, error):
                self.call('plan', {'plan_ref': self.ref('task-'+str(self.n)+'.json', plan)}, role='spec-designer')

    def test_changed_focused_context_blocks_dispatch(self):
        self.root_scope(); self.split(); self.global_plan(); self.prepare_leaf('M001')
        ref = self.state()['module_inputs']['M001']['context_refs'][0]
        from pathlib import Path
        Path(ref['path']).write_text('changed contract')
        with self.assertRaisesRegex(Rejected, 'evidence hash mismatch'):
            self.call('assign', {'assignment_id': 'T1', 'role': 'test-runner', 'instance_id': 'tester'})

    def test_go_registration_requires_scope_context_and_root_identity(self):
        self.root_scope('project')
        root = {'module_id': 'M020', 'name': 'Other', 'case_ids': ['C1'],
                'write_paths': [str(self.target / 'other')], 'decomposition_required': True,
                'scope': {'in': ['Other'], 'out': [], 'requirement_ids': ['R1']},
                'context_refs': [self.ref('other-context.md', 'Other module context')]}
        for field, value, error in (
            ('scope', None, 'scope object required'),
            ('context_refs', [], 'focused module context'),
            ('scope', {'in': ['Other'], 'out': [], 'requirement_ids': ['UNKNOWN']}, 'unknown global requirement'),
            ('parent_module_id', 'M010', 'register GO root'),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, error):
                self.call('register', {**root, field: value}, role='global-orchestrator', module=None)
        self.call('register', root, role='global-orchestrator', module=None)
        self.assertEqual(self.state()['module_inputs']['M020']['scope'], root['scope'])

    def test_decomposition_and_tasks_must_cover_all_allocated_requirements(self):
        self.root_scope()
        s = self.state()
        parent = s['modules']['M010']
        parent['scope']['requirement_ids'].append('R2')
        plan = self.proposal()
        plan.update(planning_context=dc.planning_context(s), assigned_module=dc.assigned_module(s, parent))
        with self.assertRaisesRegex(Rejected, 'cover every parent requirement'):
            dc.validate(s, parent, plan)
        self.split()
        s = self.state()
        child = s['modules']['M001']
        child['scope']['requirement_ids'].append('R2')
        plan = self.plan()
        plan.update(planning_context=dc.planning_context(s), assigned_module=dc.assigned_module(s, child))
        with self.assertRaisesRegex(Rejected, 'cover assigned submodule requirements'):
            dc.check_module_plan(s, child, plan)

    def test_parent_summary_is_bound_to_current_children(self):
        self.root_scope(); self.split(); self.global_plan()
        for mid in ('M001', 'M002'):
            self.call('suspend', {'kind': 'human', 'reason': mid+' question', 'root_cause': 'unresolved', 'owner': 'human'}, module=mid)
        old = dc.summary_subject(self.state(), self.state()['module_groups']['M010'])
        self.call('session', {'role': 'test-runner', 'session_id': 'new-session'}, module='M002')
        with self.assertRaisesRegex(Rejected, 'snapshot stale'):
            self.call('module-summary', {'summary_ref': self.ref('old-summary.md', 'old review'), 'subject_sha256': old}, module='M010')
        self.summarize()
        self.call('invalidate', {'reason': 'new child scope evidence'}, module='M002')
        self.assertFalse(self.state()['module_rounds']['all_settled'])
        self.assertEqual(self.state()['module_groups']['M010']['phase'], 'coordinating')

    def test_hierarchical_audit_repair_requires_fresh_parent_summary(self):
        self.root_scope(); self.split(self.proposal(dependencies={'M002': ['M001']})); self.global_plan()
        self.prepare_leaf('M001'); self.complete_leaf('M001')
        self.call('dependency-ready', role='global-orchestrator', module='M002')
        self.call('resume', module='M002')
        self.prepare_leaf('M002')
        result = test_audit_closure.ClosureTests.verify_module(self, 'M002', 'FAIL', consume=True)
        self.call('audit-defer', {'root_cause': result['paths'][0]['root_cause'],
                  'evidence_ref': self.ref('handoff.md', 'producer defect confirmed')}, module='M002')
        self.summarize()
        test_audit_closure.ClosureTests.route(self)
        test_audit_closure.ClosureTests.implement(self, 'M001', 'FIX', shared=2, fixer=True)
        test_audit_closure.ClosureTests.verify_module(self, 'M001', 'OWNER')
        self.call('complete', {'dod_ref': self.ref('owner-dod.md', 'reviewed'), 'checks_passed': True})
        self.call('audit-retest', module='M002')
        test_audit_closure.ClosureTests.verify_module(self, 'M002', 'SOURCE', consume=True)
        self.call('complete', {'dod_ref': self.ref('source-dod.md', 'reviewed'), 'checks_passed': True}, module='M002')
        self.call('audit-verdict', {'review_ref': self.ref('verdict.md', 'verified')}, role='auditor', module=None)
        self.assertEqual(self.state()['global_next_step']['reason'], 'await-parent-summaries')
        self.summarize()
        self.assertEqual(self.state()['global_next_step']['operation'], 'audit-assign')

    def test_frozen_leaf_cannot_be_decomposed_to_escape_its_contract(self):
        self.root_scope(); self.split(); self.global_plan(); self.prepare_leaf('M001')
        with self.assertRaisesRegex(Rejected, 'child MO decomposes tasks'):
            self.split(self.proposal('M001', ('M003',)), parent='M001')
