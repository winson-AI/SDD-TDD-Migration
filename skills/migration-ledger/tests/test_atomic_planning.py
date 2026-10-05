"""Atomic scope decisions and independent planning progress on the real Ledger bus."""
import copy
import unittest

import test_decomposition
import test_design_stage
import ledger
import workflow
import design_stage
from contracts import Rejected, digest


class AtomicPlanningTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests()
        f.setUp(); self.addCleanup(f.doCleanups)

    def atomic_proposal(self):
        return {'kind': 'atomic-leaf', 'parent_module_id': 'M010',
                'rationale': 'One behavior, one writer, distinct observable test path; further scope split adds no ownership.',
                'leaf_review_ref': self.f.ref('atomic-review.md', 'Reviewed source, target reuse, dependencies and independent verification.')}

    def submit_atomic(self, proposal=None):
        f = self.f
        f.call('decompose', {'plan_ref': f.ref('atomic-proposal.json', proposal or self.atomic_proposal())}, module='M010')

    def accept_atomic(self):
        f = self.f
        f.call('decompose-accept', {'review_ref': f.ref('go-atomic-review.md', 'Same scope/CASE/owner and dependencies; terminal capability.')},
               role='global-orchestrator', module='M010')

    def pending_root(self, dependencies=None):
        f = self.f
        original = f.state(); f.root = f.base / 'parallel-run'
        f.call('init', {k: original[k] for k in ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required',
            'target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec', 'new_architecture', 'global_paths')}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm1')],
            'lean_leaf': True, 'scope': {'in': ['Atomic capability'], 'out': [], 'requirement_ids': ['R1']},
            'context_refs': [f.ref('leaf-context.md', 'Source and target entry')],
            'leaf_review_ref': f.ref('leaf-review.md', 'Independent behavior and verification, unique writer')}, role='global-orchestrator', module=None)
        f.call('register', {'module_id': 'M010', 'name': 'Pending capability', 'case_ids': ['C1'],
            'write_paths': [str(f.target / 'pending')], 'dependencies': dependencies or [], 'decomposition_required': True,
            'scope': {'in': ['pending'], 'out': [], 'requirement_ids': ['R1']},
            'context_refs': [f.ref('pending.md', 'Independent pending source boundary')]}, role='global-orchestrator', module=None)

    def split_pending(self):
        f = self.f
        proposal = f.proposal('M010', ('M002', 'M003'))
        for child in proposal['children']:
            child['write_paths'] = [str(f.target / 'pending' / child['module_id'])]
        f.split(proposal, parent='M010')

    def test_mo_confirms_atomic_root_without_dummy_child_or_early_code(self):
        f = self.f; f.root_scope()
        before = f.state()['modules']['M010']
        self.assertIn('atomic-leaf', f.state()['next_steps'][0]['planning_outcomes'])
        f.global_plan(); self.submit_atomic(); self.accept_atomic()
        s = f.state(); m = s['modules']['M010']
        self.assertEqual(set(s['modules']), {'M010'})
        self.assertFalse(s.get('module_groups'))
        self.assertEqual(m['scope'], before['scope'])
        self.assertEqual(m['case_ids'], before['case_ids'])
        self.assertTrue(m['lean_leaf']); self.assertFalse(m['decomposition_required'])
        self.assertIsNone(m['freeze_id']); self.assertIsNone(m['code_baseline'])
        self.assertTrue(all(row['kind'] == 'planning-history' and row['executable'] is False for row in m['planning_history']))
        workflow.planning_guard(s, 'M010')
        for role in ('implementer', 'fixer', 'test-runner'):
            with self.subTest(role=role), self.assertRaises(Rejected):
                f.call('assign', {'assignment_id': 'EARLY-' + role, 'role': role, 'instance_id': role}, module='M010')
        f.prepare_leaf('M010')
        self.assertTrue(f.state()['modules']['M010']['code_baseline'])

    def test_atomic_confirmation_cannot_change_scope_or_skip_review(self):
        f = self.f; f.root_scope()
        for patch in ({'children': []}, {'scope': {'in': ['expanded']}}, {'leaf_review_ref': None}, {'parent_module_id': 'M999'}):
            with self.subTest(patch=patch), self.assertRaises(Rejected):
                self.submit_atomic({**self.atomic_proposal(), **patch})
        self.submit_atomic()
        with self.assertRaisesRegex(Rejected, 'principal role denied'):
            f.call('decompose-accept', {'review_ref': f.ref('self-approval.md', 'No GO review')}, module='M010')

    def test_atomic_confirmation_requires_behavior_and_verification_boundaries(self):
        import test_behavior_contract
        f = self.f; f.root_scope()
        s = f.state(); s['behavior_contract_required'] = True
        parent = s['modules']['M010']
        parent['behavior_review'] = test_behavior_contract.review(f, parent)
        ledger.decomposition.validate(s, parent, self.atomic_proposal())
        for field in ('entry', 'verification'):
            changed = copy.deepcopy(parent); changed['behavior_review'].pop(field)
            with self.subTest(field=field), self.assertRaises(Rejected):
                ledger.decomposition.validate(s, changed, self.atomic_proposal())
        parent['behavior_review']['verification']['provider_inputs'] = [{'module_id': 'M999'}]
        with self.assertRaisesRegex(Rejected, 'providers must match'):
            ledger.decomposition.validate(s, parent, self.atomic_proposal())

    def test_atomic_root_tasks_cannot_expand_the_accepted_allocation(self):
        f = self.f; f.root_scope(); self.submit_atomic(); self.accept_atomic(); f.global_plan()
        plan = f.plan(); plan['module_id'] = 'M010'; f.attach_reuse(plan)
        plan['tasks'][0]['global_requirement_ids'] = ['OUTSIDE']
        with self.assertRaisesRegex(Rejected, 'outside assigned'):
            f.call('plan', {'plan_ref': f.ref('expanded-plan.json', plan)}, role='spec-designer', module='M010')

    def test_atomic_review_binds_current_context_and_cannot_bypass_freeze(self):
        f = self.f; f.root_scope('project'); self.submit_atomic()
        f.call('register', {'module_id': 'M020', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'other')]},
               role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'current global'):
            self.accept_atomic()
        self.submit_atomic(); self.accept_atomic(); f.global_plan(); f.prepare_leaf('M010')
        with self.assertRaisesRegex(Rejected, 'before freezing/coding'):
            self.submit_atomic()

    def test_ready_leaf_executes_while_unrelated_root_is_still_planning(self):
        f = self.f; self.pending_root()
        self.assertEqual(f.state()['global_next_step']['operation'], 'global-plan')
        f.global_plan(); f.prepare_leaf('M001'); f.complete_leaf('M001')
        s = f.state()
        self.assertEqual(s['modules']['M001']['quality'], 'green-passed')
        self.assertIsNone(s['modules']['M010']['code_baseline'])
        with self.assertRaises(Rejected):
            f.call('audit-assign', {'assignment_id': 'TOO-EARLY', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)

    def test_pending_provider_blocks_consumer_but_not_an_unrelated_leaf(self):
        f = self.f; self.pending_root()
        f.call('register', {'module_id': 'M020', 'case_ids': ['C1'], 'dependencies': ['M010'],
                           'write_paths': [str(f.target / 'consumer')]}, role='global-orchestrator', module=None)
        f.global_plan()
        workflow.planning_guard(f.state(), 'M001')
        with self.assertRaisesRegex(Rejected, 'complete MO decomposition'):
            workflow.planning_guard(f.state(), 'M020')

    def test_sibling_split_preserves_frozen_spec_and_active_execution_context(self):
        f = self.f; self.pending_root(); f.global_plan(); f.prepare_leaf('M001')
        f.call('assign', {'role': 'test-runner', 'assignment_id': 'ACTIVE', 'instance_id': 'tester'})
        before = f.state()['modules']['M001']
        self.split_pending(); f.global_plan()
        after = f.state()['modules']['M001']
        for key in ('plan_hash', 'freeze_id', 'code_baseline', 'revision', 'assignments'):
            self.assertEqual(after[key], before[key])
        self.assertIsNotNone(after.get('execution_context_ref'))
        ledger.decomposition.check_module_plan(f.state(), after, after['plan'])

    def test_sibling_split_preserves_inflight_independent_test_design(self):
        f = self.f; self.pending_root(); f.global_plan()
        plan = f.plan(); a, result = test_design_stage.start_design(f, plan)
        self.split_pending(); f.global_plan()
        m = f.state()['modules']['M001']
        self.assertTrue(design_stage.valid(f.state(), m, m['assignments'][a['assignment_id']]))
        test_design_stage.submit_design(f, a, result)
        f.call('accept', {'assignment_id': a['assignment_id'], 'review_ref': f.ref('design-review.md', 'Path coverage verified')})
        self.assertTrue(f.state()['modules']['M001']['accepted_test_design'])

    def test_replanning_is_history_and_requires_new_freeze(self):
        f = self.f; f.root_scope(); self.submit_atomic(); self.accept_atomic(); f.global_plan()
        plan = f.plan(); plan['module_id'] = 'M010'; f.attach_reuse(plan)
        f.call('plan', {'plan_ref': f.ref('first-plan.json', plan)}, role='spec-designer', module='M010')
        f.call('planning-reopen', {'reason_ref': f.ref('issue.md', 'Correct a technical assumption before implementation')}, module='M010')
        m = f.state()['modules']['M010']; old = copy.deepcopy(m['planning_history'][-1])
        self.assertEqual(old['plan'], plan); self.assertFalse(old['executable'])
        self.assertIsNone(m['plan']); self.assertIsNone(m['freeze_id'])
        with self.assertRaises(Rejected):
            f.call('assign', {'assignment_id': 'STALE', 'role': 'implementer', 'instance_id': 'coder'}, module='M010')
        corrected = copy.deepcopy(plan); corrected['tasks'][0]['title'] = 'Use the reviewed technical plan'
        f.call('plan', {'plan_ref': f.ref('corrected-plan.json', corrected)}, role='spec-designer', module='M010')
        f.call('decision', {'decision_id': 'CURRENT', 'decision': 'approved', 'module_id': 'M010',
            'subject_sha256': digest(corrected), 'human_source_ref': f.ref('current-approved.md', 'Current SPEC accepted')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'CURRENT'}, module='M010')
        m = f.state()['modules']['M010']
        self.assertEqual(m['plan'], corrected); self.assertEqual(m['planning_history'][-1], old)
        self.assertEqual(f.state()['run_id'], 'demo')
