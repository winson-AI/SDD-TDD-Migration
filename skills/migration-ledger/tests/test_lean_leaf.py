"""Lightweight leaves: atomic roots skip parent decomposition, local fixes self-diagnose,
and one human envelope approval can cover a parent's children."""
import copy
import json
import unittest

import test_ledger
import test_workflow
import test_decomposition
from contracts import Rejected, digest, file_ref


class LeanLeafRootTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def leaf(self, mid='M002', **over):
        f = self.f
        payload = {'module_id': mid, 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm2')], 'lean_leaf': True,
                   'scope': {'in': ['Search box'], 'out': [], 'requirement_ids': ['R1']},
                   'context_refs': [f.ref('leaf-context.md', 'Search entry and reuse owner')],
                   'leaf_review_ref': f.ref('leaf-review.md', 'One screen, one requirement, one writer; no subfunction split')}
        payload.update(over)
        return payload

    def test_atomic_root_registers_as_governed_leaf(self):
        f = self.f
        for bad in ({'leaf_review_ref': None}, {'decomposition_required': True}, {'scope': None}):
            with self.subTest(bad=bad), self.assertRaises(Rejected):
                f.call('register', self.leaf(**bad), role='global-orchestrator', module=None)
        f.call('register', self.leaf(), role='global-orchestrator', module=None)
        m = f.state()['modules']['M002']
        self.assertTrue(m['lean_leaf'])
        self.assertFalse(m.get('decomposition_required'))


class LeanLeafDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.w = w = test_workflow.WorkflowTests(); w.setUp(); self.addCleanup(w.doCleanups)

    def lean(self):
        w = self.w; original = w.state()
        w.root = w.base / 'lean-run'
        w.call('init', {**{k: original[k] for k in ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required',
                 'target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec', 'new_architecture', 'global_paths')},
                 'max_fix_rounds': 1}, role='host')
        w.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(w.target / 'm1')], 'lean_leaf': True,
                            'scope': {'in': ['feature'], 'out': [], 'requirement_ids': ['R1']},
                            'context_refs': [w.ref('ctx.md', 'entry')], 'leaf_review_ref': w.ref('leaf.md', 'atomic')},
               role='global-orchestrator', module=None)

    def diagnose_as(self, role):
        w = self.w
        w.call('diagnose', {'diagnosis_ref': w.ref(f'diag-{w.n}.md', 'compared failing value with source'), 'owner': 'M001',
                            'root_cause': {'category': 'code', 'summary': 'wrong value', 'confidence': 'confirmed',
                                           'owner': 'M001', 'next_action': 'fix'}}, role=role)

    def test_local_round_is_diagnosed_by_the_fixer_session(self):
        w = self.w; self.lean(); w.failed_module()
        w.call('session', {'role': 'implementer', 'session_id': 'S-IMPL'})
        step = w.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['role'], step['session_id']), ('diagnose', 'fixer', 'S-IMPL'))
        self.diagnose_as('fixer')
        w.call('diagnosis-accept')
        self.assertEqual(w.state()['next_steps'][0]['worker_role'], 'fixer')

    def test_regular_leaf_keeps_independent_diagnostician(self):
        w = self.w; w.failed_module()
        self.assertEqual(w.state()['next_steps'][0]['role'], 'diagnostician')
        with self.assertRaisesRegex(Rejected, 'principal role denied'):
            self.diagnose_as('fixer')


class SelfDiagnosisOptionTests(unittest.TestCase):
    def test_run_option_lets_any_module_self_diagnose_its_local_round(self):
        w = test_workflow.WorkflowTests(); w.setUp(); self.addCleanup(w.doCleanups)
        original = w.state(); w.root = w.base / 'self-diagnosis-run'
        w.call('init', {**{k: original[k] for k in ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required',
                 'target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec', 'new_architecture', 'global_paths')},
                 'max_fix_rounds': 1, 'fixer_self_diagnosis': True}, role='host')
        w.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(w.target / 'm1')]},
               role='global-orchestrator', module=None)
        w.failed_module()
        self.assertEqual(w.state()['next_steps'][0]['role'], 'fixer')
        w.root = w.base / 'bad-option-run'
        with self.assertRaisesRegex(Rejected, 'fixer_self_diagnosis must be boolean'):
            w.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec',
                     'new_architecture', 'global_paths')}, 'fixer_self_diagnosis': 'yes'}, role='host')


class BatchEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_decomposition.DecompositionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        d.root_scope(); d.split(); d.global_plan()

    def child_plan(self, mid):
        d = self.d
        plan = d.plan(); pid = 'P1' if mid == 'M001' else 'P2'
        plan['module_id'] = mid
        plan['paths'][0]['path_id'] = pid; plan['tasks'][0]['path_ids'] = [pid]
        d.attach_reuse(plan)
        d.call('plan', {'plan_ref': d.ref('plan-'+mid+'.json', plan)}, role='spec-designer', module=mid)
        return plan

    def approve_batch(self, envelopes):
        d = self.d
        doc = {'schema_version': 1, 'parent_module_id': 'M010', 'children': envelopes}
        ref = d.ref('batch-envelope.json', doc)
        d.call('decision', {'decision_id': 'BATCH', 'decision': 'approved', 'module_id': 'M010', 'kind': 'batch-envelope',
                            'envelope_ref': ref, 'subject_sha256': ref['sha256'],
                            'human_source_ref': d.ref('batch-approval.md', 'approved both children envelopes')},
               role='host', module=None)

    def test_one_parent_envelope_approval_freezes_matching_children(self):
        d = self.d
        plans = {mid: self.child_plan(mid) for mid in ('M001', 'M002')}
        self.approve_batch({mid: p['decision_envelope'] for mid, p in plans.items()})
        step = next(s for s in d.state()['next_steps'] if s['module_id'] == 'M001')
        self.assertEqual((step['operation'], step['payload']['decision_id']), ('freeze', 'BATCH'))
        with self.assertRaisesRegex(Rejected, 'review_ref'):
            d.call('freeze', {'decision_id': 'BATCH'}, module='M001')
        for mid in ('M001', 'M002'):
            d.call('freeze', {'decision_id': 'BATCH', 'review_ref': d.ref('mo-review-'+mid+'.md', 'tasks/paths reviewed inside envelope')},
                   module=mid)
            self.assertEqual(d.state()['modules'][mid]['phase'], 'frozen')
        self.assertEqual(set(d.state()['decisions']['BATCH']['used_by']), {'M001', 'M002'})

    def test_child_envelope_outside_batch_needs_its_own_approval(self):
        d = self.d
        plan = self.child_plan('M001')
        wider = copy.deepcopy(plan['decision_envelope']); wider['scope'] = ['feature', 'export']
        self.approve_batch({'M001': wider})
        with self.assertRaisesRegex(Rejected, 'batch envelope'):
            d.call('freeze', {'decision_id': 'BATCH', 'review_ref': d.ref('mo-review.md', 'reviewed')}, module='M001')

    def test_batch_decision_must_belong_to_the_parent_and_hash_its_document(self):
        d = self.d
        plan = self.child_plan('M001')
        ref = d.ref('batch-envelope.json', {'schema_version': 1, 'parent_module_id': 'M010', 'children': {'M001': plan['decision_envelope']}})
        with self.assertRaisesRegex(Rejected, 'batch envelope'):
            d.call('decision', {'decision_id': 'BAD', 'decision': 'approved', 'module_id': 'M010', 'kind': 'batch-envelope',
                                'envelope_ref': ref, 'subject_sha256': 'not-the-file-hash',
                                'human_source_ref': d.ref('h.md', 'approved')}, role='host', module=None)


if __name__ == '__main__':
    unittest.main()
