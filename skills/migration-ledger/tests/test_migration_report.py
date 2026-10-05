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
    def test_partial_execution_is_not_complete_coverage(self):
        import automation_report
        row = dict(module_id='M1', task_ids=['T1'], case_id='C1', path_id='P1', kind='automation',
                   platform='android', parameters={}, code_baseline='baseline', test_run_id='attempt',
                   evidence_refs=[], stale=False, quality='yellow-blocked', assertions=[],
                   attempt_executed=True, execution_status='incomplete')
        report = automation_report.summarize([row], ['C1'])
        self.assertEqual((report['attempted_paths'], report['completed_paths'], report['partial_paths']), (1, 0, 1))
        self.assertEqual(report['attempt_coverage'], 1)
        self.assertEqual(report['completion_coverage'], 0)
        self.assertTrue(report['definition_coverage_complete'])
        self.assertFalse(report['validation_complete'])
        row.update(execution_status='completed', quality='red-bug')
        report = automation_report.summarize([row], ['C1'])
        self.assertTrue(report['validation_complete']); self.assertEqual(report['passed_paths'], 0)
        row.pop('execution_status')
        self.assertEqual(automation_report.summarize([row], ['C1'])['completion_unknown_paths'], 1)
        row.update(stale=True)
        self.assertEqual(automation_report.summarize([row], ['C1'])['unattempted_paths'], 1)
        empty = automation_report.summarize([], ['C1'])
        self.assertIsNone(empty['completion_coverage']); self.assertFalse(empty['validation_complete'])

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
        test_ledger.code_review(f)
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
        self.assertEqual(report['automation']['required_paths'], 2)  # module and GLOBAL, excluding build
        self.assertEqual(report['automation']['passed_paths'], 0)
        self.assertEqual(report['automation']['current_executed_paths'], 0)

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

    def test_task_membership_does_not_duplicate_successful_paths(self):
        f = self.fixture(); f.test_green_flow_and_independent_global_audit()
        state = f.state()
        task = state['modules']['M001']['plan']['tasks'][0]
        state['modules']['M001']['plan']['tasks'].append({**task, 'task_id': 'T-OTHER'})
        report = migration_report.build(f.root, state, state['last_sequence'])
        summary = report['automation']
        self.assertEqual(summary['required_paths'], 2)
        self.assertEqual(summary['passed_paths'], 2)
        self.assertEqual(summary['tasks']['M001/T-OTHER']['passed_paths'], 1)
        path = next(p for p in summary['successful_paths'] if p['path_id'] == 'P1')
        self.assertEqual(len(path['task_ids']), 2)
        self.assertEqual(summary['success_coverage'], 1)

    def test_historical_report_without_statistics_remains_readable(self):
        f = self.fixture(); report = self.report(f)
        report.pop('automation')
        self.assertIn('历史报告未包含 automation 统计', migration_report.render(report))

    def test_missing_paths_stale_and_observed_failure_are_explicit(self):
        f = self.fixture()
        summary = self.report(f)['automation']
        self.assertFalse(summary['coverage_complete'])
        self.assertTrue(summary['missing_case_paths'])
        f.test_green_flow_and_independent_global_audit()
        state = f.state(); m = state['modules']['M001']
        state['audit']['snapshot'] = {}
        m['results']['P1'].update(quality='yellow-blocked', assertions=[{'passed': False, 'actual': False}])
        report = migration_report.build(f.root, state, state['last_sequence'])
        self.assertIn('P1', [p['path_id'] for p in report['automation']['observed_failure_paths']])
        self.assertNotIn('P1', [p['path_id'] for p in report['automation']['successful_paths']])
        m['stale'] = True
        report = migration_report.build(f.root, state, state['last_sequence'])
        self.assertEqual(report['automation']['passed_paths'], 0)
