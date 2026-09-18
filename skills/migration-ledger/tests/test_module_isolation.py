"""Independent MO progress and the all-module join before any Auditor entry."""
import copy
import json
import sys
import unittest
from pathlib import Path

import test_ledger
import test_audit_closure
import test_workflow
from contracts import Rejected, digest
from execute_test import execute


class ModuleIsolationTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def prepare_peers(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [],
                           'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.prepare()
        plan = f.plan()
        plan['module_id'] = 'M002'
        plan['paths'][0]['path_id'] = 'P2'
        plan['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('plan-m2.json', plan)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002',
                           'subject_sha256': digest(plan), 'human_source_ref': f.ref('d2.md', 'approved')},
               role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        f.implementation()
        test_audit_closure.ClosureTests.implement(f, 'M002', 'I2')

    def assert_auditor_waits(self):
        f = self.f
        for op, payload in (
            ('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}),
            ('problem-assign', {'assignment_id': 'OLD', 'instance_id': 'auditor'}),
            ('audit-assign', {'assignment_id': 'FINAL', 'instance_id': 'auditor'}),
        ):
            with self.subTest(operation=op), self.assertRaises(Rejected):
                f.call(op, payload, role='global-orchestrator', module=None)
        self.assertFalse(f.state()['global_next_step']['ready'])
        self.assertFalse(f.state()['module_rounds']['all_settled'])

    def finish_peer_test(self):
        f = self.f
        m = f.state()['modules']['M002']
        a = m['assignments']['T2']
        adapter = f.base / 'peer-adapter.py'
        adapter.write_text(
            "import argparse,json,runpy\n"
            "p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n"
            f"value=runpy.run_path({str(f.target / 'm2/code.py')!r})['value']\n"
            "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':value,'passed':value==2}]},open(a.result_file,'w'))\n")
        rr = execute(f.root, 'M002', 'T2', 'P2', [sys.executable, str(adapter)], str(f.target), f.base / 'peer-exec')
        receipt = json.loads(Path(rr['path']).read_text())
        result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'M002',
                  'assignment_id': 'T2', 'actor_instance_id': 'peer-tester', 'freeze_id': m['freeze_id'],
                  'code_baseline': m['code_baseline'], 'paths': [
                      {'path_id': 'P2', 'test_run_id': receipt['test_run_id'], 'quality': 'green-passed',
                       'executed': True, 'execution_receipt': rr,
                       'assertions': json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']}]}
        f.call('submit', {'assignment_id': 'T2', 'fencing_token': a['fencing_token'],
                          'result_ref': f.ref('peer-result.json', result)}, role='test-runner',
               instance='peer-tester', module='M002')
        f.call('accept', {'assignment_id': 'T2'}, module='M002')
        f.call('complete', {'dod_ref': f.ref('peer-dod.md', 'full coverage verified'), 'checks_passed': True}, module='M002')

    def test_red_fix_and_defer_do_not_cancel_running_peer(self):
        f = self.f
        self.prepare_peers()
        f.call('assign', {'assignment_id': 'T2', 'role': 'test-runner', 'instance_id': 'peer-tester'}, module='M002')
        peer = copy.deepcopy(f.state()['modules']['M002'])
        a, result = f.make_test_result(quality='red-bug')
        f.submit(result, a)
        f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M002'], peer)
        self.assertEqual(f.state()['quality'], 'red-bug')
        self.assertEqual(f.state()['module_rounds']['active_modules'], ['M002'])
        self.assert_auditor_waits()
        test_workflow.WorkflowTests.diagnose(f)
        f.implementation(role='fixer', aid='F1')
        a, retry = f.make_test_result(aid='RETRY', quality='red-bug', previous=result['paths'][0]['test_run_id'])
        f.submit(retry, a)
        f.call('accept', {'assignment_id': 'RETRY'})
        test_workflow.WorkflowTests.defer(f)
        self.assertEqual(f.state()['modules']['M002'], peer)
        self.assertEqual(f.state()['global_next_step']['wait_for_modules'], ['M002'])
        self.assert_auditor_waits()
        self.finish_peer_test()
        s = f.state()
        self.assertEqual(s['modules']['M001']['quality'], 'red-bug')
        self.assertEqual(s['modules']['M002']['quality'], 'green-passed')
        self.assertTrue(s['module_rounds']['all_settled'])
        self.assertEqual(s['global_next_step']['operation'], 'audit-collect')
        f.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.assertEqual(set(f.state()['audit_batch']['sources']), {'M001'})

    def test_yellow_peer_does_not_suppress_ready_work(self):
        f = self.f
        self.prepare_peers()
        peer = copy.deepcopy(f.state()['modules']['M002'])
        f.call('suspend', {'kind': 'tooling', 'reason': 'M001 adapter unavailable',
                           'root_cause': 'module-specific tool missing', 'owner': 'host'})
        s = f.state()
        self.assertEqual(s['modules']['M002'], peer)
        self.assertIn('M002', s['ready_modules'])
        self.assertIn('M002', s['global_next_step']['continue_modules'])
        self.assertIsNone(s['global_next_step']['operation'])
        self.assert_auditor_waits()
        test_audit_closure.ClosureTests.verify_module(f, 'M002', 'T2')
        f.call('complete', {'dod_ref': f.ref('dod2.md', 'reviewed'), 'checks_passed': True}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['quality'], 'green-passed')
        self.assertTrue(f.state()['module_rounds']['all_settled'])

    def test_unrelated_failure_cannot_be_used_as_dependency_suspension(self):
        f = self.f
        self.prepare_peers()
        before = f.state()['modules']['M002']
        with self.assertRaisesRegex(Rejected, 'unavailable registered dependency'):
            f.call('suspend', {'kind': 'dependency', 'reason': 'M001 failed',
                               'root_cause': 'peer failure', 'owner': 'global-orchestrator'}, module='M002')
        self.assertEqual(f.state()['modules']['M002'], before)

    def test_pending_module_is_not_finished_and_completed_peer_keeps_green(self):
        f = self.f
        self.prepare_peers()
        test_audit_closure.ClosureTests.verify_module(f, 'M002', 'T2')
        f.call('complete', {'dod_ref': f.ref('dod2.md', 'reviewed'), 'checks_passed': True}, module='M002')
        peer = copy.deepcopy(f.state()['modules']['M002'])
        f.call('register', {'module_id': 'M003', 'case_ids': ['C1'], 'dependencies': [],
                           'write_paths': [str(f.target / 'm3')]}, role='global-orchestrator', module=None)
        f.global_plan()
        f.call('suspend', {'kind': 'tooling', 'reason': 'M001 tooling', 'root_cause': 'missing adapter', 'owner': 'host'})
        s = f.state()
        self.assertEqual(s['modules']['M002'], peer)
        self.assertEqual(s['module_rounds']['unfinished_modules'], ['M003'])
        self.assertIn('M003', s['global_next_step']['continue_modules'])
        self.assert_auditor_waits()

    def test_real_dependency_wait_is_scoped_to_consumer(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                           'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        parent = copy.deepcopy(f.state()['modules']['M001'])
        f.call('suspend', {'kind': 'dependency', 'reason': 'producer pending',
                           'root_cause': 'M001 unavailable', 'owner': 'global-orchestrator'}, module='M002')
        s = f.state()
        self.assertEqual(s['modules']['M001'], parent)
        self.assertEqual(s['modules']['M002']['blocked']['dependency_module_ids'], ['M001'])
        self.assertEqual(s['modules']['M002']['quality'], 'yellow-blocked')
        self.assertFalse(s['module_rounds']['all_settled'])


if __name__ == '__main__':
    unittest.main()
