"""Local isolation, recovery cursors and explicit host attention without weakening gates."""
from datetime import datetime, timedelta
from pathlib import Path
import unittest

import test_dimensions
import test_ledger
import test_split_testing
from contracts import Rejected, digest
import ledger
import progress_signals
import workflow


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.d = test_dimensions.DimensionTests(); self.d.setUp()
        self.addCleanup(self.d.doCleanups)
        self.f = self.d.f

    def freeze(self, dependencies=False):
        d, f = self.d, self.f
        d.root(); p = d.proposal(ids=('M001', 'M002'))
        if dependencies: p['children'][0]['dependencies'] = ['M002']
        f.split(p); f.global_plan()
        plan = d.leaf_plan()
        f.call('plan', {'plan_ref': f.ref('recovery-plan.json', plan)}, role='spec-designer')
        f.call('decision', {'decision_id': 'D', 'decision': 'approved', 'module_id': 'M001',
                           'subject_sha256': digest(plan), 'human_source_ref': f.ref('approve.md', 'approve')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'D'})
        return plan

    def change_peer(self):
        path = Path(self.f.state()['modules']['M002']['dimension_analysis_ref']['path'])
        path.write_text(path.read_text() + '\n')

    def test_unrelated_bad_analysis_does_not_block_actual_dispatch(self):
        f = self.f; self.freeze(); self.change_peer()
        s = f.state()
        self.assertTrue(next(x for x in s['next_steps'] if x['module_id'] == 'M001')['ready'])
        self.assertEqual(next(x for x in s['next_steps'] if x['module_id'] == 'M002')['reason'], 'allocation-review-required')
        f.call('assign', {'assignment_id': 'I', 'role': 'implementer', 'instance_id': 'coder'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'implementing')
        # Global acceptance still checks the entire allocation.
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            f.global_plan()

    def test_actual_dependency_and_parent_evidence_remain_gated(self):
        f = self.f; self.freeze(dependencies=True)
        workflow.planning_guard(f.state(), 'M001')
        self.change_peer()
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            workflow.planning_guard(f.state(), 'M001')
        # Recreate immutable peer bytes, then invalidate only the parent allocation.
        p = Path(f.state()['modules']['M002']['dimension_analysis_ref']['path'])
        p.write_text(p.read_text()[:-1])
        parent = Path(self.d.root_ref['path']); parent.write_text(parent.read_text()+'\n')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            workflow.planning_guard(f.state(), 'M001')

    def test_invalidate_archives_old_plan_and_exposes_replanning(self):
        f = self.f; old = self.freeze()
        old_ref = f.state()['modules']['M001']['plan_ref']
        (f.base/'task-analysis-source.md').write_text('drift')
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M001')
        self.assertEqual((step['operation'], step['ready']), ('invalidate', True))
        f.call('invalidate', step['payload'])
        s=f.state(); m=s['modules']['M001']
        self.assertIsNone(m['plan']); self.assertIsNone(m['freeze_id'])
        self.assertEqual(m['planning_history'][-1]['plan'], old)
        self.assertTrue((f.root/'artifacts'/old_ref['sha256']).exists())
        step=next(x for x in s['next_steps'] if x['module_id']=='M001')
        self.assertEqual((step['operation'],step['ready']), ('plan', True))
        change=f.root/'openspec/changes/demo-m001'
        self.assertFalse((change/'tasks.md').exists())
        self.assertIn('Replanning required', (change/'status.md').read_text())
        plan=self.d.leaf_plan()
        f.call('plan', {'plan_ref':f.ref('revised.json',plan)}, role='spec-designer')
        self.assertEqual(f.state()['modules']['M001']['phase'],'clarifying')


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.f=test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_rejected_gate_is_visible_and_repeated_attempts_escalate(self):
        f=self.f; f.prepare()
        before, events_before = ledger.read_events(f.root)
        for _ in range(3):
            with self.assertRaises(Rejected):
                f.call('complete', {'checks_passed':True})
        after, events_after = ledger.read_events(f.root)
        self.assertEqual((before, events_before), (after, events_after))
        s=f.state(); signal=next(x for x in s['workflow_progress']['signals'] if x['reason']=='operation-rejected')
        self.assertEqual(signal['severity'],'human')
        self.assertTrue(s['workflow_progress']['notify_user'])
        self.assertEqual(signal['evidence']['rejection']['attempts'],3)
        self.assertTrue((f.root/'reports/workflow-attention.md').exists())
        self.assertTrue(s['workflow_progress']['runnable_actions'])
        f.implementation()
        self.assertNotIn('operation-rejected',[x['reason'] for x in f.state()['workflow_progress']['signals']])

    def test_damaged_diagnostic_does_not_block_status_or_next_assignment(self):
        f=self.f; f.prepare()
        path=f.root/'reports/rejected-operation.json'
        path.write_text('{broken')
        report=f.state()['workflow_progress']
        self.assertIn('diagnostic-unreadable', [x['reason'] for x in report['signals']])
        self.assertTrue(report['runnable_actions'])
        f.assign('implementer', 'I')
        self.assertEqual(f.state()['modules']['M001']['phase'], 'implementing')

    def test_no_runnable_action_surfaces_human_attention(self):
        f=self.f; f.global_plan()
        plan=f.plan(); f.call('plan',{'plan_ref':f.ref('pending.json',plan)},role='spec-designer')
        report=f.state()['workflow_progress']
        self.assertEqual(report['state'],'stalled'); self.assertTrue(report['notify_user'])
        self.assertIn('approval-or-impact-review-required',[x['reason'] for x in report['signals']])

    def test_overdue_worker_signal_never_cancels_worker_or_other_work(self):
        f=self.f; f.prepare(); f.assign('implementer','I')
        state,events=ledger.read_events(f.root); snapshot=f.state()
        at=datetime.fromisoformat(events[-1]['timestamp'])+timedelta(seconds=901)
        report=progress_signals.build(f.root,state,events,snapshot['next_steps'],snapshot['global_next_step'],at=at)
        self.assertTrue(report['notify_user'])
        self.assertIn('worker-progress-overdue',[x['reason'] for x in report['signals']])
        self.assertFalse(f.state()['modules']['M001']['assignments']['I']['closed'])


class AutomationProgressTests(unittest.TestCase):
    def test_missing_environment_proposes_bypass_and_allows_auditor_review(self):
        t=test_split_testing.SplitTestingTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f=t.f; t.prepare(); t.compile()
        report=f.record(f.report('testing',blocked='test-environment'))
        step=f.state()['next_steps'][0]
        self.assertEqual((step['operation'],step['ready']),('automation-unavailable',True))
        f.raw('automation-unavailable',{'context_ref':report})
        self.assertTrue(f.state()['module_rounds']['all_settled'])
        test_ledger.code_review(f)
        report=f.record(f.report('audit-testing',module=None,instance='auditor',blocked='test-environment'))
        step=f.state()['global_next_step']
        self.assertEqual((step['operation'],step['ready']),('audit-unavailable',True))
        f.raw('audit-unavailable',{'context_ref':report},role='auditor',module=None)
        s=f.state()
        self.assertEqual(s['workflow_progress']['state'],'completed-with-unverified-tests')
        self.assertFalse(s['workflow_progress']['notify_user'])
        self.assertEqual(s['modules']['M001']['results']['P1']['quality'],'yellow-blocked')
