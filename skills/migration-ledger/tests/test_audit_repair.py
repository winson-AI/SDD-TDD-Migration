"""What the unified audit sends back is repaired in the run with the model turns only judgment takes: a consumer that
failed on its provider's defect is routed by the cause its test confirmed, collected, routed, dispatched, retested and
given its verdict by the Ledger; the Auditor reviews the whole change once and, after the repair, only what it changed.
Like the run rehearsals the count reports, it does not gate: a change that adds turns warns with the walk."""
from pathlib import Path
import sys
import unittest
import warnings

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_audit_closure
import test_ledger
from test_rehearsal import MO

# The turns last recorded in VERIFICATION.md, from the consumer's deferral to the run's verdict.
RECORDED = {'auditor': 2, 'fixer': 1, 'test-runner': 3}


class AuditRepairTests(unittest.TestCase):
    def setUp(self):
        self.c = c = test_audit_closure.ClosureTests(methodName='run'); c.setUp(); self.addCleanup(c.doCleanups)
        c.cross_module_failure()
        self.turns = []

    def settle(self):
        """What a host's drive tick submits: every mechanical step of every module and of the run."""
        while True:
            moved = bool(ledger.advance_run(self.c.root, MO))
            for mid in self.c.state()['modules']:
                moved |= bool(ledger.advance(self.c.root, MO, mid)['applied'])
            if not moved:
                return

    def left(self):
        """The steps a model has to take now."""
        st = ledger.status(self.c.root, 'full')
        steps = [st['global_next_step'], *st['next_steps']]
        return [(x.get('worker_role') or x['role'], x['operation'], x.get('module_id')) for x in steps
                if x.get('operation') and x.get('ready') is not False and not x.get('mechanical')]

    def worker(self, mid):
        m = self.c.state()['modules'][mid]
        return next(a for a in m['assignments'].values() if not a.get('closed'))

    def global_retest(self):
        """The independent Test-Runner the Ledger dispatched runs the global paths the repair made stale."""
        import json
        from execute_test import execute
        c, s = self.c, self.c.state()
        scope, task = ledger.audit_scope(s), s['audit_test_assignment']
        adapter = c.base / 'global-adapter.py'
        adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n"
                           "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))\n")
        rows = []
        for pid in task['path_ids']:
            rr = execute(c.root, 'GLOBAL', task['assignment_id'], pid, [sys.executable, str(adapter)], str(c.target), c.base / ('global-' + pid))
            receipt = json.loads(Path(rr['path']).read_text())
            rows.append({'path_id': pid, 'quality': 'green-passed', 'executed': True, 'test_run_id': receipt['test_run_id'], 'execution_receipt': rr,
                         'assertions': json.loads(Path(receipt['result_ref']['path']).read_text())['assertions'],
                         **({'retest_of': scope['results'][pid]['test_run_id']} if pid in scope['results'] else {})})
        test_ledger.accept_audit_test(c, {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL', 'freeze_id': scope['freeze_id'],
                                          'code_baseline': scope['code_baseline'], 'paths': rows,
                                          'snapshot': {mid: m['code_baseline'] for mid, m in s['modules'].items()}})

    def test_a_finding_the_audit_sends_back_is_repaired_with_the_turns_judgment_takes(self):
        self.walk()

    def walk(self):
        c = self.c
        test_ledger.code_review(c); self.turns.append('auditor')  # the whole change, once
        self.settle()
        b = c.state()['audit_batch']
        self.assertEqual((b['status'], [(r['action'], r['owner_module_ids']) for r in b['routes'].values()]), ('repairing', [('fix', ['M001'])]))
        a = self.worker('M001'); self.assertEqual(a['role'], 'fixer')
        c.implement('M001', a['assignment_id'], shared=2, fixer=True); self.turns.append('fixer')
        self.settle()
        a = self.worker('M001'); self.assertEqual(a['role'], 'test-runner')
        c.verify_module('M001', a['assignment_id']); self.turns.append('test-runner')  # the owner first
        self.settle()
        a = self.worker('M002'); self.assertEqual(a['role'], 'test-runner')
        c.verify_module('M002', a['assignment_id'], consume=True); self.turns.append('test-runner')  # then the source
        self.settle()
        s = c.state()
        self.assertEqual(s['audit_batch_history'][-1]['status'] if s['audit_batch']['status'] != 'verified' else 'verified', 'verified')
        self.assertTrue(s['modules']['M001']['fix_memory'][0]['reusable'])
        step = s['global_next_step']
        self.assertEqual((step['operation'], step['review_modules']), ('audit-code-review', ['M001']))  # only what the repair changed
        test_ledger.code_review(c, modules=['M001']); self.turns.append('auditor')
        self.assertEqual(c.state()['audit_code_review']['carried_modules'], ['M002'])
        self.settle()
        self.assertEqual(c.state()['global_next_step']['operation'], 'audit-test-submit')  # the repair moved what a global path ran on
        self.global_retest(); self.turns.append('test-runner')
        self.settle()  # a clean review and a green retest are the verdict
        self.assertEqual(self.left(), [])
        self.assertEqual(c.state()['quality'], 'green-passed')
        counted = {role: self.turns.count(role) for role in set(self.turns)}
        if sum(counted.values()) > sum(RECORDED.values()):
            warnings.warn('the audit repair took %s model turns, %s recorded' % (counted, RECORDED))
        self.assertEqual(counted, RECORDED)

    def test_a_finding_the_findings_do_not_route_by_themselves_is_routed_by_the_auditor(self):
        import copy
        import audit_closure
        c = self.c
        test_ledger.code_review(c); self.settle()
        b = c.state()['audit_batch_history'][-1] if c.state()['audit_batch']['status'] == 'verified' else c.state()['audit_batch']
        s = c.state()
        unsure = copy.deepcopy(b); fid = next(iter(unsure['findings']))
        unsure['findings'][fid]['result']['root_cause']['confidence'] = 'likely'
        self.assertIsNone(audit_closure.drafted_routes(s, unsure))  # a cause the test did not confirm: the Auditor analyses it
        gap = copy.deepcopy(b); gap['findings'][fid]['result']['root_cause']['category'] = 'planning-gap'
        self.assertEqual(audit_closure.drafted_routes(s, gap)[0]['action'], 'trace')  # a SPEC gap goes back to its owner's SPEC
        review = {**copy.deepcopy(b), 'code_review_ref': {'path': 'review'}, 'findings': {'CR-1': {
            'finding_id': 'CR-1', 'source_module_id': 'M002', 'root_cause': {'category': 'fidelity'}, 'analysis_ref': {'path': 'review'}}}}
        self.assertIsNone(audit_closure.drafted_routes(s, review))  # a code finding without the route its review wrote
        review['findings']['CR-1']['route'] = {'action': 'fix', 'owner_module_ids': ['M001']}
        self.assertEqual([(r['action'], r['owner_module_ids']) for r in audit_closure.drafted_routes(s, review)], [('fix', ['M001'])])
        review['findings']['CR-1']['requires_human'] = True
        self.assertIsNone(audit_closure.drafted_routes(s, review))


if __name__ == '__main__':
    unittest.main()
