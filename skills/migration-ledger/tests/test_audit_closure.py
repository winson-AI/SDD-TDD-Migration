import copy
import json
from pathlib import Path
import sys
import unittest

import test_ledger
from contracts import Rejected, digest, baseline, file_ref
from execute_test import execute


class ClosureTests(unittest.TestCase):
    setUp = test_ledger.FlowTests.setUp
    ref = test_ledger.FlowTests.ref
    state = test_ledger.FlowTests.state
    call = test_ledger.FlowTests.call
    plan = test_ledger.FlowTests.plan
    global_plan = test_ledger.FlowTests.global_plan
    prepare = test_ledger.FlowTests.prepare
    approve = test_ledger.FlowTests.approve

    def implement(self, mid, aid, shared=1, fixer=False, value=2):
        actor = 'fixer' if fixer else 'implementer'
        self.call('assign', {'assignment_id': aid, 'role': actor, 'instance_id': actor}, module=mid)
        a = self.state()['modules'][mid]['assignments'][aid]
        path = self.target / ('m1' if mid == 'M001' else 'm2') / 'code.py'
        path.parent.mkdir(exist_ok=True); path.write_text(f'value = {value}\nshared = {shared}\n')
        refs = [file_ref(path)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': mid,
                  'assignment_id': aid, 'actor_instance_id': actor, 'freeze_id': a['freeze_id'],
                  'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(path)]}],
                  'production_binding_evidence': self.ref(f'binding-{aid}.md', 'reviewed production binding')}
        if fixer:
            result['fix_note_ref'] = self.ref(f'note-{aid}.json', {'root_cause': 'shared value mismatch', 'strategy': 'correct producer value',
                                                               'applicability': 'same shared contract', 'risks': 'retest consumer'})
        self.call('submit', {'assignment_id': aid, 'fencing_token': a['fencing_token'], 'result_ref': self.ref(f'impl-{aid}.json', result)},
                  role=actor, module=mid)
        self.call('accept', {'assignment_id': aid}, module=mid)

    def verify_module(self, mid, aid, consume=False):
        self.call('assign', {'assignment_id': aid, 'role': 'test-runner', 'instance_id': 'test-runner'}, module=mid)
        m = self.state()['modules'][mid]; a = m['assignments'][aid]; pid = 'P1' if mid == 'M001' else 'P2'
        adapter = self.base / f'adapter-{aid}.py'
        target = self.target / 'm1/code.py' if consume else self.target / ('m1' if mid == 'M001' else 'm2') / 'code.py'
        field = 'shared' if consume else 'value'
        adapter.write_text("import argparse,json,runpy\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n" +
                           f"actual=runpy.run_path({str(target)!r})[{field!r}]\n" +
                           "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':actual,'passed':actual==2}]},open(a.result_file,'w'))\n")
        rr = execute(self.root, mid, aid, pid, [sys.executable, str(adapter)], str(self.target), self.base / f'exec-{aid}')
        receipt = json.loads(Path(rr['path']).read_text()); assertions = json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']
        passed = assertions[0]['passed']
        record = {'path_id': pid, 'quality': 'green-passed' if passed else 'red-bug', 'executed': True,
                  'test_run_id': receipt['test_run_id'], 'execution_receipt': rr, 'assertions': assertions,
                  'retest_of': m['results'].get(pid, {}).get('test_run_id')}
        if not passed:
            record['root_cause'] = {'category': 'dependency', 'summary': 'producer shared value wrong', 'confidence': 'confirmed',
                                    'owner': 'M001', 'next_action': 'fix-producer'}
        result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': mid, 'assignment_id': aid,
                  'actor_instance_id': 'test-runner', 'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'paths': [record]}
        self.call('submit', {'assignment_id': aid, 'fencing_token': a['fencing_token'], 'result_ref': self.ref(f'test-{aid}.json', result)},
                  role='test-runner', module=mid)
        self.call('accept', {'assignment_id': aid}, module=mid)
        return result

    def complete(self, mid):
        self.call('complete', {'dod_ref': self.ref(f'dod-{mid}-{self.n}.md', 'reviewed'), 'checks_passed': True}, module=mid)

    def cross_module_failure(self):
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                              'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        self.prepare(); self.implement('M001', 'I1'); self.verify_module('M001', 'T1'); self.complete('M001')
        self.call('dependency-ready', role='global-orchestrator', module='M002')
        self.call('resume', module='M002')
        p = self.plan(); p['module_id'] = 'M002'; p['paths'][0]['path_id'] = 'P2'; p['tasks'][0]['path_ids'] = ['P2']
        self.call('plan', {'plan_ref': self.ref('p2.json', p)}, role='spec-designer', module='M002')
        self.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002', 'subject_sha256': digest(p),
                              'human_source_ref': self.ref('d2.md', 'approved')}, role='host', module=None)
        self.call('freeze', {'decision_id': 'D2'}, module='M002')
        self.implement('M002', 'I2'); result = self.verify_module('M002', 'T2', consume=True)
        self.call('audit-defer', {'root_cause': result['paths'][0]['root_cause'], 'evidence_ref': self.ref('handoff.md', 'module round ended with confirmed dependency failure')}, module='M002')

    def route(self):
        self.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = self.state()['audit_batch']
        self.assertEqual(set(b['sources']), {'M002'})  # The module execution round explicitly handed off before collection.
        route = {'source_module_id': 'M002', 'owner_module_id': 'M001', 'action': 'fix',
                 'source_context': b['contexts']['M002'], 'owner_context': b['contexts']['M001'],
                 'root_cause': {'category': 'dependency', 'summary': 'producer defect affects consumer', 'confidence': 'confirmed',
                                'owner': 'M001', 'next_action': 'fix-producer'}, 'analysis_ref': self.ref('analysis.md', 'SPEC and PATH reviewed')}
        self.call('audit-plan', {'plan_ref': self.ref('route.json', {'routes': [route]})}, role='auditor', module=None)
        self.call('audit-route-batch', {'review_ref': self.ref('route-review.md', 'Global confirmed owner')}, role='global-orchestrator', module=None)
        self.call('audit-work', module='M001')

    def test_cross_module_fix_then_owner_and_source_verification(self):
        self.cross_module_failure(); self.route()
        self.implement('M001', 'F1', shared=2, fixer=True)
        self.verify_module('M001', 'T3'); self.complete('M001')
        self.assertFalse(self.state()['modules']['M001']['fix_memory'][0]['reusable'])
        self.call('audit-retest', module='M002')
        self.verify_module('M002', 'T4', consume=True); self.complete('M002')
        self.call('audit-verdict', {'review_ref': self.ref('verdict.md', 'all independent verification accepted')}, role='auditor', module=None)
        s = self.state()
        self.assertEqual(s['audit_batch']['status'], 'verified')
        self.assertTrue(s['modules']['M001']['fix_memory'][0]['reusable'])
        self.assertEqual(s['global_next_step']['operation'], 'audit-assign')

    def test_failed_consumer_verification_stops_for_human(self):
        self.cross_module_failure(); self.route()
        self.implement('M001', 'F1', shared=1, fixer=True)
        self.verify_module('M001', 'T3'); self.complete('M001')
        self.call('audit-retest', module='M002')
        self.verify_module('M002', 'T4', consume=True)
        s = self.state()
        self.assertEqual(s['audit_batch']['status'], 'awaiting-human')
        self.assertEqual(s['global_next_step']['reason'], 'human-review-required')
        self.assertFalse(s['modules']['M001']['fix_memory'][0]['reusable'])
        report = json.loads((self.root / 'audit-reports/B1.json').read_text())
        self.assertEqual(report['evidence']['root_causes'][0]['owner'], 'M001')
        with self.assertRaises(Rejected): self.call('audit-work', module='M001')
        with self.assertRaises(Rejected): self.call('resume', module='M002')
        with self.assertRaises(Rejected): self.call('audit-collect', {'batch_id': 'B2', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)

    def test_context_binding_and_auditor_separation(self):
        self.cross_module_failure()
        self.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = self.state()['audit_batch']
        bad = {'routes': [{'source_module_id': 'M002', 'owner_module_id': 'M001', 'action': 'fix',
                          'source_context': b['contexts']['M002'], 'owner_context': {},
                          'analysis_ref': self.ref('analysis.md', 'review'),
                          'root_cause': {'category': 'code', 'summary': 'cause', 'confidence': 'confirmed', 'owner': 'M001', 'next_action': 'fix'}}]}
        with self.assertRaises(Rejected): self.call('audit-plan', {'plan_ref': self.ref('bad-route.json', bad)}, role='auditor', module=None)
        with self.assertRaises(Rejected): self.call('audit-work', module='M001')

    def test_owner_verification_failure_prevents_source_testing(self):
        self.cross_module_failure(); self.route()
        self.implement('M001', 'F1', shared=2, fixer=True, value=3)
        self.verify_module('M001', 'T3')
        self.assertEqual(self.state()['audit_batch']['human_report']['module_id'], 'M001')
        with self.assertRaises(Rejected): self.call('audit-retest', module='M002')

    def test_changed_source_context_is_reported_for_human(self):
        self.cross_module_failure(); self.route()
        self.implement('M001', 'F1', shared=2, fixer=True)
        self.verify_module('M001', 'T3'); self.complete('M001')
        (self.target / 'm2/code.py').write_text('changed outside the frozen audit task')
        self.call('audit-retest', module='M002')
        b = self.state()['audit_batch']
        self.assertEqual(b['status'], 'awaiting-human')
        self.assertEqual(b['human_report']['root_causes'][0]['category'], 'verification-blocked')
        self.assertTrue(b['human_report']['reason'])
