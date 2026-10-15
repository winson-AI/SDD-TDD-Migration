"""A global path runs at the wave boundary: as soon as every leaf holding its case has completed; its green stands for
the audit while its owners' code is unchanged, and its red is routed to the owning leaves."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import integration
import ledger
import test_audit_closure
import test_ledger
from contracts import Rejected, digest
from execute_test import execute


class WaveIntegrationTests(unittest.TestCase):
    def setUp(self):
        f = self.f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state(); f.root = f.base / 'wave'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'global_spec', 'new_architecture')},
                        'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False,
                        'case_ids': ['C1', 'C2'], 'requirement_ids': ['R1'], 'max_fix_rounds': 1,
                        'global_paths': [{'path_id': 'GP1', 'case_id': 'C1', 'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}]}]}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]}, role='global-orchestrator', module=None)
        f.call('register', {'module_id': 'M002', 'case_ids': ['C2'], 'dependencies': ['M001'], 'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.global_plan(case_owners={'C1': ['M001', 'GLOBAL'], 'C2': ['M002']}, requirement_owners={'R1': ['M001', 'M002']})
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer'); f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})

    def first_wave(self):
        f = self.f
        f.implement('M001', 'I1'); f.verify_module('M001', 'T1'); f.complete('M001')
        return f.state()['global_next_step']

    def run_gp1(self, aid, passing=True):
        f = self.f; scope = integration.scope(f.state())
        adapter = f.base / f'wave-{aid}.py'
        adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n"
                           "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':%d,'passed':%s}]},open(a.result_file,'w'))\n" % ((2, 'True') if passing else (1, 'False')))
        rr = execute(f.root, 'GLOBAL', aid, 'GP1', [sys.executable, str(adapter)], str(f.target), f.base / ('exec-' + aid))
        receipt = json.loads(Path(rr['path']).read_text()); assertions = json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']
        row = {'path_id': 'GP1', 'quality': 'green-passed' if passing else 'red-bug', 'executed': True, 'test_run_id': receipt['test_run_id'],
               'execution_receipt': rr, 'assertions': assertions}
        if not passing:
            row['root_cause'] = {'category': 'code', 'summary': 'integration result wrong', 'confidence': 'confirmed', 'owner': 'M001', 'next_action': 'fix'}
        return {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL', 'assignment_id': aid, 'actor_instance_id': 'wave-runner',
                'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'], 'paths': [row]}

    def second_wave(self):
        f = self.f
        p = f.plan(); p['module_id'] = 'M002'; p['paths'][0].update(path_id='P2', case_id='C2'); p['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('p2.json', p)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002', 'subject_sha256': digest(p),
                            'human_source_ref': f.ref('d2.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        f.implement('M002', 'I2'); f.verify_module('M002', 'T2'); f.complete('M002')

    def test_a_global_path_runs_when_its_owners_complete_and_its_green_stands_for_the_audit(self):
        f = self.f
        with self.assertRaisesRegex(Rejected, 'no global path is due'):
            f.call('integration-assign', {'assignment_id': 'INT0', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        step = self.first_wave()
        self.assertEqual((step['operation'], step['reason'], step['path_ids']), ('integration-assign', 'wave-complete', ['GP1']))
        with self.assertRaisesRegex(Rejected, 'independent of code'):
            f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'implementer', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        self.assertEqual(f.state()['global_next_step']['operation'], 'integration-submit')
        f.call('integration-submit', {'result_ref': f.ref('int1.json', self.run_gp1('INT1'))}, role='test-runner', instance='wave-runner', module=None)
        s = f.state()
        self.assertEqual((s['audit_results']['GP1']['quality'], s['audit_results']['GP1']['owner_baselines']),
                         ('green-passed', {'M001': s['modules']['M001']['code_baseline']}))
        self.assertTrue(s['integration_assignment']['closed']); self.assertNotEqual(s['global_next_step']['operation'], 'integration-assign')
        self.second_wave()
        s = f.state()
        self.assertNotEqual(ledger.global_baseline(s), s['audit_results']['GP1']['code_baseline'])  # the whole code moved, the owner's did not
        self.assertEqual([p['path_id'] for p in ledger.audit_scope(s)['plan']['paths']], [])
        test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'AUD', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        s = f.state(); self.assertEqual(s['audit_assignment']['path_ids'], [])
        report = {'schema_version': 1, 'kind': 'audit-review', 'run_id': 'demo', 'module_id': 'GLOBAL', 'assignment_id': 'AUD', 'actor_instance_id': 'auditor',
                  'freeze_id': ledger.audit_scope(s)['freeze_id'], 'code_baseline': ledger.audit_scope(s)['code_baseline'],
                  'snapshot': s['audit_assignment']['snapshot'], 'paths': [], 'execution_status': 'no-retest-needed', 'review_ref': f.ref('review.md', 'reviewed')}
        f.call('audit', {'report_ref': f.ref('audit.json', report)}, role='auditor', module=None)
        self.assertEqual(f.state()['quality'], 'green-passed')
        rows = {r['path_id']: r for r in __import__('migration_report').build(f.root, f.state(), f.state()['last_sequence'])['paths']}
        self.assertEqual((rows['GP1']['quality'], rows['GP1']['stale']), ('green-passed', False))

    def test_a_red_integration_result_is_routed_to_the_owning_leaf(self):
        f = self.f; self.first_wave()
        f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        f.call('integration-submit', {'result_ref': f.ref('int1.json', self.run_gp1('INT1', passing=False))}, role='test-runner', instance='wave-runner', module=None)
        s = f.state()
        self.assertEqual((ledger.pending_repairs(s)['GP1']['module_ids'], s['audit_results']['GP1']['quality']), (['M001'], 'red-bug'))
        self.assertNotEqual(s['global_next_step']['operation'], 'integration-assign')  # red is routed, not re-run
        f.call('repair-accept', {'path_ids': ['GP1']}, module='M001')
        m = f.state()['modules']['M001']
        self.assertIn('GP1', m['repair_findings']); self.assertEqual(ledger.pending_repairs(f.state()), {})
        self.assertEqual([p['path_id'] for p in ledger.audit_scope(f.state())['plan']['paths']], ['GP1'])  # the audit still sees it until it is green again


if __name__ == '__main__':
    unittest.main()
