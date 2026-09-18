"""Audit barriers, finding routing, dependency scheduling and approved recovery."""
import copy
import unittest

import test_audit_closure
import audit_closure as ac
from contracts import Rejected, digest


class AuditSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.f = test_audit_closure.ClosureTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_normal_dependency_release_blocks_collection(self):
        f=self.f
        f.call('register', {'module_id':'M002','case_ids':['C1'],'dependencies':['M001'],
                           'write_paths':[str(f.target/'m2')]}, role='global-orchestrator', module=None)
        f.prepare(); f.implement('M001','I1'); f.verify_module('M001','T1'); f.complete('M001')
        s=f.state(); self.assertFalse(s['global_next_step']['ready'])
        self.assertEqual(next(x for x in s['next_steps'] if x['module_id']=='M002')['operation'],'dependency-ready')
        with self.assertRaises(Rejected):
            f.call('audit-collect',{'batch_id':'B1','auditor_instance_id':'auditor'},role='global-orchestrator',module=None)
        f.call('dependency-ready',role='global-orchestrator',module='M002')
        self.assertFalse(f.state()['global_next_step']['ready'])
        f.call('resume',module='M002')
        self.assertFalse(f.state()['global_next_step']['ready'])

    def test_unfinished_unrelated_module_blocks_auditor(self):
        f=self.f; f.cross_module_failure()
        f.call('register',{'module_id':'M003','case_ids':['C1'],'dependencies':[],
                           'write_paths':[str(f.target/'m3')]},role='global-orchestrator',module=None)
        f.global_plan()
        self.assertFalse(f.state()['global_next_step']['ready'])
        with self.assertRaises(Rejected):
            f.call('audit-collect',{'batch_id':'B1','auditor_instance_id':'auditor'},role='global-orchestrator',module=None)
        # Explicitly suspended module rounds count; dependency-unrunnable is not a pass.
        f.call('suspend',{'kind':'human','reason':'missing external configuration','root_cause':'configuration unavailable','owner':'human'},module='M003')
        self.assertTrue(f.state()['global_next_step']['ready'])

    def scenario(self, dependencies, failed):
        """Pure scheduler fixture based on valid frozen/code artifacts from the real harness."""
        f=self.f; f.cross_module_failure(); original=f.state()
        s=copy.deepcopy(original); s['modules']={}; s['audit_queue']={}
        for mid,deps in dependencies.items():
            m=copy.deepcopy(original['modules']['M001']);m.update(module_id=mid,dependencies=deps,phase='completed',blocked=None,stale=False)
            m['results']={};m['assignments']={};m['fix_memory']=[]
            if mid in failed:
                record=copy.deepcopy(original['modules']['M002']['results']['P2'])
                record['path_id']='PATH-'+mid
                m['results'][record['path_id']]=record
                m.update(phase='waiting-auditor',blocked={'kind':'auditor','resume_phase':'testing'})
            s['modules'][mid]=m
        sources=ac.leftovers(s)
        s['audit_batch']={'schema_version':2,'batch_id':'B1','auditor_instance_id':'auditor','status':'collected',
                          'sources':sources,'findings':ac.findings(sources),'contexts':{mid:ac.context(m) for mid,m in s['modules'].items()},
                          'routes':{},'started_owners':[],'owner_tests':{},'source_tests':{},'human_issues':{},'blocked_modules':[]}
        return s

    def route(self,s,owners_by_source,human=()):
        b=s['audit_batch'];routes=[]
        for fid,finding in b['findings'].items():
            source=finding['source_module_id'];owners=owners_by_source.get(source,[])
            action='human' if source in human else 'fix' if owners else 'verify'
            routes.append({'finding_id':fid,'source_module_id':source,'action':action,'owner_module_ids':owners,
                           'source_context':b['contexts'][source],'owner_contexts':{o:b['contexts'][o] for o in owners},
                           'analysis_ref':self.f.ref('analysis.md','SPEC/PATH root causes reviewed'),
                           'root_cause':{'category':'code','summary':'identified cause','confidence':'confirmed','owner':source,'next_action':'fix'}})
        ac.handle(s,{'operation':'audit-plan','payload':{'plan_ref':self.f.ref('routing.json',{'routes':routes})}},
                  {'role':'auditor','instance_id':'auditor'})
        ac.handle(s,{'operation':'audit-route-batch','payload':{'review_ref':self.f.ref('review.md','routes reviewed')}},
                  {'role':'global-orchestrator','instance_id':'global'})
        return b

    def verified(self,s,mid):
        b=s['audit_batch'];m=s['modules'][mid]
        m.update(phase='completed',stale=False,blocked=None)
        p={'freeze_id':m['freeze_id'],'code_baseline':m['code_baseline'],
           'result_ref':self.f.ref('verified-'+mid+'.json',{'fixture':'scheduler proof'}),
           'paths':[{'quality':'green-passed'}]}
        if mid in ac.owners(b):
            b['started_owners'].append(mid);b['owner_tests'][mid]=p
        else:b['source_tests'][mid]=p

    def test_interleave_source_verification_before_downstream_owner(self):
        s=self.scenario({'A':[],'B':['A'],'C':['B'],'D':['C']},['B','D'])
        b=self.route(s,{'B':['A'],'D':['C']})
        self.assertFalse(ac.module_step(s,s['modules']['C'])['ready'])
        self.verified(s,'A')
        self.assertTrue(ac.module_step(s,s['modules']['B'])['ready'])
        self.assertFalse(ac.module_step(s,s['modules']['C'])['ready'])
        self.verified(s,'B')
        self.assertEqual(ac.module_step(s,s['modules']['C'])['operation'],'audit-work')
        self.assertTrue(ac.module_step(s,s['modules']['C'])['ready'])
        self.verified(s,'C')
        self.assertTrue(ac.module_step(s,s['modules']['D'])['ready'])

    def test_green_intermediate_is_reverified_after_upstream_fix(self):
        s=self.scenario({'A':[],'B':['A'],'C':['B']},['C'])
        b=self.route(s,{'C':['A']});self.assertIn('B',b['work_modules'])
        self.verified(s,'A')
        self.assertEqual(ac.module_step(s,s['modules']['B'])['operation'],'audit-retest')
        self.assertFalse(ac.module_step(s,s['modules']['C'])['ready'])
        self.verified(s,'B');self.assertTrue(ac.module_step(s,s['modules']['C'])['ready'])

    def test_same_source_multiple_findings_have_distinct_owners(self):
        s=self.scenario({'A':[],'B':[],'C':[]},['C']);b=s['audit_batch']
        second=copy.deepcopy(next(iter(b['findings'].values())));second.update(finding_id='SECOND',path_id='PATH-SECOND')
        b['findings']['SECOND']=second
        routes=[]
        for fid,owner in zip(b['findings'],['A','B']):
            routes.append({'finding_id':fid,'source_module_id':'C','owner_module_ids':[owner],'action':'fix',
                           'source_context':b['contexts']['C'],'owner_contexts':{owner:b['contexts'][owner]},
                           'analysis_ref':self.f.ref('analysis.md','cause'),
                           'root_cause':{'category':'code','summary':'cause','confidence':'confirmed','owner':owner,'next_action':'fix'}})
        ac.handle(s,{'operation':'audit-plan','payload':{'plan_ref':self.f.ref('multi.json',{'routes':routes})}},
                  {'role':'auditor','instance_id':'auditor'})
        self.assertEqual(ac.owners(b),{'A','B'});self.assertEqual(len(b['routes']),2)
        self.assertEqual(b['dependencies']['C'],['A','B'])

    def test_one_finding_can_require_multiple_owners(self):
        s=self.scenario({'A':[],'B':[],'C':[]},['C']);b=self.route(s,{'C':['A','B']})
        self.assertEqual(ac.owners(b),{'A','B'})
        self.verified(s,'A');self.assertFalse(ac.module_step(s,s['modules']['C'])['ready'])
        self.verified(s,'B');self.assertTrue(ac.module_step(s,s['modules']['C'])['ready'])

    def test_human_branch_does_not_stop_independent_repair(self):
        s=self.scenario({'A':[],'B':[],'C':['A']},['B','C'])
        b=self.route(s,{'C':['A']},human=['B'])
        self.assertEqual(b['status'],'repairing')
        self.assertTrue(ac.module_step(s,s['modules']['A'])['ready'])
        self.assertFalse(ac.module_step(s,s['modules']['B'])['ready'])
        self.verified(s,'A');self.verified(s,'C')
        self.assertEqual(ac.global_step(s)['operation'],'audit-verdict')
        ac.handle(s,{'operation':'audit-verdict','payload':{'review_ref':self.f.ref('verdict.md','partial verified')}},
                  {'role':'auditor','instance_id':'auditor'})
        self.assertEqual(b['status'],'awaiting-human');self.assertEqual(len(b['resolved_findings']),1)
        self.assertTrue(b['human_report']['source_tests']['C'])

    def test_routing_dependency_cycle_is_rejected(self):
        s=self.scenario({'A':[],'B':['A']},['A'])
        with self.assertRaises(Rejected):self.route(s,{'A':['B']})

    def failed_batch(self):
        f=self.f;f.cross_module_failure();f.route();f.implement('M001','F1',shared=1,fixer=True)
        f.verify_module('M001','T3');f.complete('M001');f.call('audit-retest',module='M002')
        f.verify_module('M002','T4',consume=True)
        return f.state()

    def release(self,s):
        f=self.f
        f.call('decision',{'decision_id':'RELEASE','decision':'approved','module_id':None,
                           'subject_sha256':digest(s['audit_batch']['human_report']),
                           'human_source_ref':f.ref('release.md','human approved release for reviewed recovery')},role='host',module=None)
        self.assertEqual(f.state()['global_next_step']['operation'],'audit-release')
        f.call('audit-release',{'decision_id':'RELEASE'},role='global-orchestrator',module=None)

    def test_human_release_unlocks_replanning_without_changing_results(self):
        s=self.failed_batch();f=self.f
        with self.assertRaises(Rejected):f.call('audit-release',{'decision_id':'missing'},role='global-orchestrator',module=None)
        before=copy.deepcopy(s['modules']['M002']['results']);self.release(s)
        self.assertEqual(f.state()['modules']['M002']['results'],before)
        self.assertFalse(f.state()['global_next_step']['ready'])
        self.assertTrue(any(x['reason']=='human-recovery-not-applied' for x in f.state()['global_next_step']['module_barrier']))
        self.assertEqual(f.state()['audit_batch_history'][0]['status'],'released')
        f.call('invalidate',{'reason':'human requested revised SPEC/context'},module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'],'specifying')
        self.assertIsNone(f.state()['modules']['M002']['freeze_id'])

    def test_budget_recovery_after_release_retains_total_usage(self):
        s=self.failed_batch();f=self.f;self.release(s)
        m=f.state()['modules']['M001'];used=m['total_fix_rounds']
        subject=digest({'module_id':'M001','revision':m['revision'],'recovery_cycle':m['recovery_cycle'],'additional_rounds':1})
        f.call('decision',{'decision_id':'BUDGET','decision':'approved','module_id':'M001','subject_sha256':subject,
                          'human_source_ref':f.ref('budget.md','approve one additional repair')},role='host',module=None)
        f.call('recover',{'decision_id':'BUDGET','additional_rounds':1},module='M001')
        m=f.state()['modules']['M001'];self.assertEqual(m['fix_budget'],2);self.assertEqual(m['total_fix_rounds'],used)

    def test_real_independent_fix_completes_while_other_module_waits_human(self):
        f=self.f;f.cross_module_failure()
        f.call('register',{'module_id':'M003','case_ids':['C1'],'dependencies':[],
                          'write_paths':[str(f.target/'m3')]},role='global-orchestrator',module=None)
        f.global_plan()
        f.call('suspend',{'kind':'human','reason':'missing SPEC decision','root_cause':'scope unclear','owner':'human'},module='M003')
        f.call('audit-collect',{'batch_id':'B1','auditor_instance_id':'auditor'},role='global-orchestrator',module=None)
        b=f.state()['audit_batch'];routes=[]
        for fid, finding in b['findings'].items():
            source=finding['source_module_id']
            routes.append({'finding_id':fid,'source_module_id':source,'action':'fix' if source=='M002' else 'human',
                           'owner_module_ids':['M001'] if source=='M002' else [],
                           'source_context':b['contexts'][source],'owner_contexts':{'M001':b['contexts']['M001']} if source=='M002' else {},
                           'analysis_ref':f.ref('analysis-'+source+'.md','root cause from SPEC and paths'),
                           'root_cause':{'category':'dependency','summary':'identified cause','confidence':'confirmed','owner':source,'next_action':'review'}})
        f.call('audit-plan',{'plan_ref':f.ref('multi-plan.json',{'routes':routes})},role='auditor',module=None)
        f.call('audit-route-batch',{'review_ref':f.ref('multi-review.md','approved routes')},role='global-orchestrator',module=None)
        f.call('audit-work',module='M001');f.implement('M001','F1',shared=2,fixer=True)
        f.verify_module('M001','T3');f.complete('M001')
        f.call('audit-retest',module='M002');f.verify_module('M002','T4',consume=True);f.complete('M002')
        f.call('audit-verdict',{'review_ref':f.ref('partial.md','independent branch passed')},role='auditor',module=None)
        s=f.state();self.assertEqual(s['modules']['M002']['quality'],'green-passed')
        self.assertEqual(s['audit_batch']['status'],'awaiting-human')
        self.assertEqual(len(s['audit_batch']['resolved_findings']),1)
        self.assertEqual(s['modules']['M003']['phase'],'waiting-human')
