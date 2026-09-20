"""Reuse rejection routes to coding; only reviewed inability gets a human signal."""
import copy
import json
from pathlib import Path
import unittest

import test_ledger
import test_reuse
import ledger
from contracts import Rejected, digest


class ImplementationGapTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.prepare()

    def payload(self, change=None):
        f=self.f; s=f.state()
        proof=f.ref('gap-evidence.md', 'Fixture source and target reviewed; required hardware capability unavailable under current architecture, including alternative implementations.')
        report={'schema_version':1, 'module_id':'M001', 'module_revision':s['modules']['M001']['revision'],
                'goal':'Reproduce required device behavior', 'requirement_ids':['R1'], 'case_ids':['C1'], 'task_ids':['T1'],
                **{k:s[k] for k in ('legacy_root','target_root','global_spec','new_architecture')},
                'context_review_ref':proof, 'reuse_unavailable_ref':proof,
                'alternatives':{k:{'conclusion':'not-feasible','reason':'Required hardware interface absent', 'evidence_refs':[proof]}
                                for k in ('adapt','reference','new')},
                'verification':{'method':'constraint-analysis','summary':'Source and target platform capability constraints checked', 'evidence_refs':[proof]},
                'conclusion':'not-implementable-under-current-constraints'}
        if change: change(report)
        return {'kind':'human','reason_code':'not-implemented','reason':'Required function cannot currently be implemented',
                'root_cause':{'category':'capability','summary':'Hardware interface unavailable','evidence_refs':[proof]},
                'owner':'module-orchestrator','next_action':'Human review target capability or approved architecture alternatives',
                'implementation_gap_ref':f.ref('gap-review.json',report)}

    def test_new_implementation_without_reusable_library_can_reach_testing(self):
        f=test_reuse.ReuseTests(); f.setUp(); self.addCleanup(f.doCleanups)
        plan=f.attach_reuse(f.plan()); f.freeze(plan)
        f.implementation()
        s=f.state()
        self.assertEqual(s['modules']['M001']['phase'],'testing')
        self.assertFalse(any(x['reason']=='not-implemented' for x in s['workflow_progress']['signals']))

    def test_verified_gap_surfaces_in_status_and_go_report_then_clears_on_recovery(self):
        f=self.f; payload=self.payload(); f.call('suspend',payload)
        s=f.state()
        signal=next(x for x in s['workflow_progress']['signals'] if x['reason']=='not-implemented')
        self.assertEqual(signal['label'],'未实现'); self.assertTrue(s['workflow_progress']['notify_user'])
        report=json.loads(Path(s['migration_report']['json']).read_text())
        self.assertEqual(report['unimplemented'][0]['review']['case_ids'],['C1'])
        self.assertEqual(next(p for p in report['paths'] if p['module_id']=='M001')['implementation_status'],'not-implemented')
        self.assertIn('## 未实现',Path(s['migration_report']['markdown']).read_text())
        self.assertEqual(s['modules']['M001']['quality'],'yellow-blocked')
        self.assertTrue((f.root/'artifacts'/payload['implementation_gap_ref']['sha256']).exists())
        with self.assertRaises(Rejected): f.assign('implementer','BAD')
        f.approve(digest(s['modules']['M001']['blocked']),'UNBLOCK')
        f.call('resume',{'decision_id':'UNBLOCK'})
        self.assertFalse(any(x['reason']=='not-implemented' for x in f.state()['workflow_progress']['signals']))
        self.assertIn('not-implemented',(f.root/'ledger/events.jsonl').read_text())

    def test_no_review_or_viable_fallback_cannot_claim_unimplemented(self):
        for change in (lambda r:r['alternatives']['new'].update(conclusion='feasible'),
                       lambda r:r['alternatives'].pop('adapt'),
                       lambda r:r.update(case_ids=['UNRELATED']),
                       lambda r:r.update(module_revision=-1),
                       lambda r:r['verification'].update(evidence_refs=[])):
            with self.subTest(change=change):
                before=ledger.read_events(self.f.root)
                with self.assertRaises(Rejected): self.f.call('suspend',self.payload(change))
                self.assertEqual(before,ledger.read_events(self.f.root))
        payload=self.payload(); payload.pop('implementation_gap_ref')
        with self.assertRaises(Rejected): self.f.call('suspend',payload)

    def test_unrelated_module_remains_dispatchable(self):
        f=self.f
        f.call('register',{'module_id':'M002','case_ids':['C1'],'dependencies':[],
                          'write_paths':[str(f.target/'m2')]},role='global-orchestrator',module=None)
        f.global_plan()
        f.call('suspend',self.payload())
        # A peer can still plan, freeze and acquire its own implementation worker.
        plan=copy.deepcopy(f.plan()); plan['module_id']='M002'
        plan['paths'][0]['path_id']='P2'; plan['tasks'][0]['path_ids']=['P2']
        f.call('plan',{'plan_ref':f.ref('peer-plan.json',plan)},role='spec-designer',module='M002')
        f.call('decision',{'decision_id':'PEER','module_id':'M002','decision':'approved',
                          'subject_sha256':digest(plan),'human_source_ref':f.ref('peer-approval.md','approved')},role='host',module=None)
        f.call('freeze',{'decision_id':'PEER'},module='M002')
        f.call('assign',{'assignment_id':'PEER-I','role':'implementer','instance_id':'peer'},module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'],'implementing')
