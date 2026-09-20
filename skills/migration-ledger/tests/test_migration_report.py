"""Observable parent names and complete, evidence-backed GO reports."""
import json
from pathlib import Path
import unittest

import test_ledger
import test_decomposition
import test_split_testing
import test_audit_scope
import test_audit_closure
from contracts import Rejected, check_ref
import migration_report


class MigrationReportTests(unittest.TestCase):
    def fixture(self, cls=test_ledger.FlowTests):
        f = cls(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def report(self, f):
        state = f.state()
        artifact = state['migration_report']
        result = json.loads(Path(artifact['json']).read_text())
        self.assertEqual(result['sequence'], state['last_sequence'])
        self.assertEqual(artifact['sequence'], state['last_sequence'])
        self.assertTrue(Path(artifact['markdown']).is_file())
        self.assertEqual({r['case_id'] for r in result['cases']}, set(state['case_ids']))
        return result

    def test_parent_name_before_after_split_and_session_recovery(self):
        f = self.fixture(test_decomposition.DecompositionTests); f.root_scope()
        self.assertEqual(f.state()['parent_mo_names'], {'M010': 'parent-mo-M010'})
        self.assertEqual(f.state()['next_steps'][0]['agent_name'], 'parent-mo-M010')
        with self.assertRaisesRegex(Rejected, 'parent MO name'):
            f.call('session', {'role': 'module-orchestrator', 'session_id': 'parent', 'agent_name': 'other'}, module='M010')
        f.call('session', {'role': 'module-orchestrator', 'session_id': 'parent'}, module='M010')
        f.split()
        state = f.state()
        self.assertEqual(state['parent_mo_names'], {'M010': 'parent-mo-M010'})
        self.assertEqual(state['module_groups']['M010']['sessions']['module-orchestrator']['agent_name'], 'parent-mo-M010')
        step = next(r for r in state['next_steps'] if r['module_id'] == 'M010')
        self.assertEqual(step['agent_name'], 'parent-mo-M010')
        f.call('session', {'role': 'module-orchestrator', 'session_id': 'replacement',
                          'reason': 'session-unavailable', 'checkpoint_ref': f.ref('checkpoint.md', 'resume parent')}, module='M010')
        self.assertEqual(f.state()['parent_mo_names']['M010'], 'parent-mo-M010')
        report = self.report(f)
        self.assertTrue(all(r['parent_mo_name'] == 'parent-mo-M010' for r in report['paths'] if r['module_id'] != 'GLOBAL'))

    def test_all_green_after_independent_audit_is_complete(self):
        f = self.fixture(); f.test_green_flow_and_independent_global_audit()
        report = self.report(f)
        self.assertEqual(report['report_stage'], 'completed')
        self.assertEqual(report['case_counts'], {'green-passed': 1, 'red-bug': 0, 'yellow-blocked': 0})
        self.assertEqual(report['non_green'], [])
        self.assertEqual(len(report['paths']), 2)

    def test_red_case_includes_cause_assertions_and_real_evidence(self):
        f = self.fixture(); f.prepare(); f.implementation()
        a, result = f.make_test_result(quality='red-bug'); f.submit(result, a)
        f.call('accept', {'assignment_id': a['assignment_id']})
        report = self.report(f)
        self.assertEqual(report['cases'][0]['quality'], 'red-bug')
        row = next(r for r in report['non_green'] if r['path_id'] == 'P1')
        self.assertEqual(row['root_causes'][0]['summary'], 'observed issue')
        self.assertFalse(row['assertions'][0]['passed'])
        self.assertTrue(row['evidence_refs'])
        for ref in row['evidence_refs']: check_ref(ref)
        self.assertEqual(row['ledger_evidence']['sequence'], report['sequence'])
        markdown = Path(f.state()['migration_report']['markdown']).read_text()
        self.assertIn(row['evidence_refs'][0]['path'], markdown)

    def test_unplanned_and_unrun_cases_are_not_omitted(self):
        f = self.fixture(); report = self.report(f)
        self.assertEqual(report['cases'][0]['quality'], 'yellow-blocked')
        self.assertEqual(report['report_stage'], 'in-progress')
        self.assertTrue(any(r['root_causes'][0]['category'] == 'path-not-defined' for r in report['non_green']))
        self.assertTrue(all(r['ledger_evidence'] for r in report['non_green']))

    def test_changed_code_downgrades_prior_green_and_preserves_history(self):
        f = self.fixture(); f.test_green_flow_and_independent_global_audit()
        (f.target / 'm1/code.py').write_text('changed after audit')
        report = self.report(f)
        self.assertEqual(report['report_stage'], 'in-progress')
        self.assertEqual(report['cases'][0]['quality'], 'yellow-blocked')
        row = next(r for r in report['paths'] if r['path_id'] == 'P1')
        self.assertEqual(row['recorded_quality'], 'green-passed')
        self.assertTrue(row['stale'])
        self.assertEqual(row['root_causes'][0]['category'], 'evidence-stale')

    def test_automation_unavailable_is_yellow_despite_green_build(self):
        fixture = self.fixture(test_split_testing.SplitTestingTests); f = fixture.f
        fixture.prepare(); fixture.compile(); fixture.defer()
        context_ref = f.record(f.report('audit-testing', module=None, instance='auditor', blocked='test-environment'))
        f.raw('audit-unavailable', {'context_ref': context_ref}, role='auditor', module=None)
        report = self.report(f)
        self.assertEqual(report['report_stage'], 'completed-with-unverified-tests')
        rows = {r['path_id']: r for r in report['paths']}
        self.assertEqual(rows['B1']['quality'], 'green-passed')
        self.assertEqual(rows['P1']['quality'], 'yellow-blocked')
        self.assertFalse(rows['P1']['executed'])
        self.assertEqual(rows['P1']['root_causes'][0]['category'], 'automation-environment')
        self.assertIn(context_ref, rows['P1']['evidence_refs'])
        self.assertEqual(report['cases'][0]['quality'], 'yellow-blocked')

    def test_empty_audit_review_keeps_original_case_evidence(self):
        fixture = self.fixture(test_audit_scope.AuditScopeTests)
        f = fixture.fixture(); f.completed()
        result = fixture.review(f)
        f.raw('audit', {'report_ref': f.ref('empty-audit.json', result)}, role='auditor', module=None)
        report = self.report(f)
        self.assertEqual(report['report_stage'], 'completed')
        self.assertEqual(report['cases'][0]['quality'], 'green-passed')
        self.assertTrue(report['paths'][0]['test_run_id'])
        self.assertEqual(report['audit']['execution_status'], 'no-retest-needed')

    def test_current_auditor_red_overrides_older_module_green(self):
        f = self.fixture(); f.test_green_flow_and_independent_global_audit()
        s = f.state()
        s['audit']['paths'].append({**s['modules']['M001']['results']['P1'], 'quality': 'red-bug',
                                   'root_cause': {'category': 'integration', 'summary': 'auditor finding', 'owner': 'M001', 'next_action': 'fix'}})
        report = migration_report.build(f.root, s, s['last_sequence'])
        self.assertEqual(report['cases'][0]['quality'], 'red-bug')
        self.assertEqual(next(r for r in report['paths'] if r['path_id'] == 'P1')['root_causes'][0]['summary'], 'auditor finding')

    def test_shared_case_preserves_green_module_and_reports_failed_consumer(self):
        f = self.fixture(test_audit_closure.ClosureTests); f.cross_module_failure()
        report = self.report(f)
        rows = {r['path_id']: r for r in report['paths']}
        self.assertEqual(report['cases'][0]['quality'], 'red-bug')
        self.assertEqual(rows['P1']['quality'], 'green-passed')
        self.assertEqual(rows['P2']['quality'], 'red-bug')
        self.assertEqual(rows['P2']['root_causes'][0]['owner'], 'M001')
        self.assertNotIn('P1', [r['path_id'] for r in report['non_green']])

    def test_failed_auditor_repair_links_human_evidence(self):
        f = self.fixture(test_audit_closure.ClosureTests)
        f.test_failed_consumer_verification_stops_for_human()
        report = self.report(f)
        self.assertEqual(report['report_stage'], 'awaiting-human')
        self.assertEqual(report['cases'][0]['quality'], 'red-bug')
        self.assertTrue(Path(report['human_report_path']).is_file())
        self.assertIn(report['human_report_path'], Path(f.state()['migration_report']['markdown']).read_text())
