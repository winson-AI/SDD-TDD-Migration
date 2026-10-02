"""Real command/report execution, stale/empty/skipped evidence and acceptance tampering."""
import copy
import json
import os
from pathlib import Path
import unittest

import test_unit_gate
from contracts import Rejected, file_ref, read_json, validate_result
from execute_test import execute
from harmony_stage import build as stage_result
import unit_reports

PASS = '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="SearchTest" name="query"/></testsuite>'


class UnitReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_unit_gate.UnitGateTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.f = f = self.fixture.f
        self.xml, self.code = PASS, 0
        self.old_timestamp = False
        self.omit_report = False
        old_plan = f.plan
        def argv():
            program = ('import os; from pathlib import Path; '
                       'p=Path(os.environ["SDD_RUNNER_DIR"])/"reports/TEST-query.xml"; '
                       'p.parent.mkdir(parents=True,exist_ok=True); ')
            if not self.omit_report:
                program += 'p.write_text(' + repr(self.xml) + '); '
                if self.old_timestamp: program += 'os.utime(p,(1,1)); '
            return [__import__('sys').executable, '-c', program + f'raise SystemExit({self.code})']
        self.fixture.unit_argv = argv
        def plan():
            p = old_plan()
            unit = next(row for row in p['paths'] if row.get('kind') == 'unit')
            unit['expected_assertions'][0]['expected'] = True
            unit['unit_report'] = {'format': 'junit', 'patterns': ['reports/TEST-*.xml'],
                                   'required_test_ids': ['SearchTest#query']}
            return p
        f.plan = plan

    def run_unit(self, accept=True):
        self.fixture.split.prepare(); self.fixture.split.compile()
        f = self.f; m = f.state()['modules']['M001']; a = m['assignments']['BUILD1']
        receipt = execute(f.root, 'M001', 'BUILD1', 'U1', self.fixture.unit_argv(), f.target, f.base / 'unit-attempt')
        result = stage_result(f.root, 'M001', 'BUILD1', [receipt] + self.fixture.split.receipts)  # unit row first, then build
        if accept:
            f.submit(result, a); f.call('accept', {'assignment_id': 'BUILD1'})
        return receipt, result, a

    def test_current_tests_pass_and_summary_is_retained(self):
        receipt, result, _ = self.run_unit()
        row = result['paths'][0]; r = read_json(receipt['path'])
        self.assertEqual(row['quality'], 'green-passed')
        summary = row['unit_execution']
        self.assertEqual(summary['counts'], {'passed': 1, 'failed': 0, 'skipped': 0, 'total': 1, 'executed': 1})
        self.assertEqual(summary['test_run_id'], r['test_run_id'])
        self.assertTrue(all(Path(ref['path']).is_relative_to((self.f.base / 'unit-attempt').resolve()) for ref in summary['reports']))
        self.fixture.split.defer()
        module = self.f.state()['modules']['M001']
        self.assertEqual((module['phase'], module['results']['U1']['quality']), ('automation-deferred', 'green-passed'))

    def test_gradle_report_policy_forces_execution_and_receipt_validates_it(self):
        wrapper = self.f.target / 'gradlew'
        wrapper.write_text('case "$*" in *--rerun-tasks*--no-build-cache*) ;; *) exit 9 ;; esac\n'
                           'mkdir -p "$SDD_RUNNER_DIR/reports"\n'
                           'cat > "$SDD_RUNNER_DIR/reports/TEST-query.xml" <<\'XML\'\n' + PASS + '\nXML\n')
        self.fixture.unit_argv = lambda: ['/bin/sh', str(wrapper), 'test']
        receipt_ref, result, _ = self.run_unit()
        receipt = read_json(receipt_ref['path'])
        self.assertEqual(result['paths'][0]['quality'], 'green-passed')
        self.assertEqual(receipt['argv'][-2:], ['--rerun-tasks', '--no-build-cache'])
        self.assertNotIn('--rerun-tasks', receipt['requested_argv'])

    def test_zero_tests_cannot_pass_even_with_exit_zero(self):
        self.xml = '<testsuite tests="0"/>'
        _, result, _ = self.run_unit()
        row = result['paths'][0]
        self.assertEqual(row['quality'], 'yellow-blocked')
        self.assertIn('zero executed', row['root_cause']['summary'])
        self.assertIsNone(row['assertions'][0]['actual'])
        self.assertEqual(self.f.state()['next_steps'][0]['operation'], 'diagnose')

    def test_all_skipped_is_yellow(self):
        self.xml = '<testsuite tests="1" skipped="1"><testcase classname="SearchTest" name="query"><skipped/></testcase></testsuite>'
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        self.assertEqual(result['paths'][0]['unit_execution']['missing_test_ids'], ['SearchTest#query'])

    def test_failed_assertion_is_red_even_if_command_exit_zero(self):
        self.xml = '<testsuite tests="1" failures="1"><testcase classname="SearchTest" name="query"><failure>wrong value</failure></testcase></testsuite>'
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'red-bug')
        self.assertEqual(result['paths'][0]['root_cause']['category'], 'code')

    def test_command_failure_is_red_and_missing_report_does_not_mask_it(self):
        self.omit_report, self.code = True, 1
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'red-bug')

    def test_missing_report_is_yellow(self):
        self.omit_report = True
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        self.assertIn('no JUnit', result['paths'][0]['root_cause']['summary'])

    def test_wrong_test_selection_is_yellow(self):
        self.xml = PASS.replace('name="query"', 'name="unrelated"')
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')

    def test_old_report_timestamp_cannot_pass(self):
        self.old_timestamp = True
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        self.assertIn('predates', result['paths'][0]['root_cause']['summary'])

    def test_truncated_or_inconsistent_report_is_yellow(self):
        self.xml = PASS.replace('tests="1"', 'tests="2"')
        _, result, _ = self.run_unit()
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        self.assertIn('counter mismatch', result['paths'][0]['root_cause']['summary'])

    def test_receipt_and_summary_cannot_be_rebound_or_overridden(self):
        receipt_ref, result, a = self.run_unit(accept=False)
        f = self.f; module = f.state()['modules']['M001']
        receipt = read_json(receipt_ref['path'])
        self.assertEqual(validate_result(result, module, a), 'tests')
        changed = copy.deepcopy(result)
        changed['paths'][0]['unit_execution']['counts']['executed'] = 9
        with self.assertRaisesRegex(Rejected, 'interpretation changed|summary changed'):
            validate_result(changed, module, a)
        # Rebinding only the receipt/query to another run ID cannot reuse the old report.
        changed = copy.deepcopy(receipt)
        changed['test_run_id'] = 'another-attempt'
        from test_completion import interpret
        planned = next(p for p in module['plan']['paths'] if p.get('kind') == 'unit')
        with self.assertRaisesRegex(Rejected, 'context mismatch'):
            interpret(changed, planned)
        report_path = Path(result['paths'][0]['unit_execution']['reports'][0]['path'])
        report_path.write_text(PASS.replace('query', 'changed'))
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            validate_result(result, module, a)

    def test_stream_capture_identity_and_files_are_checked_on_acceptance(self):
        receipt_ref, result, a = self.run_unit(accept=False)
        receipt = read_json(receipt_ref['path']); module = self.f.state()['modules']['M001']
        state_path = Path(receipt['capture']['state_ref']['path'])
        state = read_json(state_path); state['module_id'] = 'M999'
        state_path.write_text(json.dumps(state)); receipt['capture']['state_ref'] = file_ref(state_path)
        Path(receipt_ref['path']).write_text(json.dumps(receipt))
        result['paths'][0]['execution_receipt'] = file_ref(receipt_ref['path'])
        with self.assertRaisesRegex(Rejected, 'capture identity mismatch'):
            validate_result(result, module, a)
        state.update(module_id='M001', output_complete=False)
        state_path.write_text(json.dumps(state)); receipt['capture']['state_ref'] = file_ref(state_path)
        Path(receipt_ref['path']).write_text(json.dumps(receipt))
        result['paths'][0]['execution_receipt'] = file_ref(receipt_ref['path'])
        with self.assertRaisesRegex(Rejected, 'complete output capture'):
            validate_result(result, module, a)

    def test_report_patterns_cannot_read_target_or_old_attempt(self):
        path = next(p for p in self.f.plan()['paths'] if p.get('kind') == 'unit')
        for patterns in (['../old/*.xml'], ['/tmp/TEST-*.xml'], ['..\\old\\TEST.xml']):
            path['unit_report']['patterns'] = patterns
            with self.subTest(patterns=patterns), self.assertRaisesRegex(Rejected, 'this runner attempt'):
                unit_reports.plan_check(path)

    def test_duplicate_report_test_ids_and_symlink_are_not_green(self):
        from datetime import datetime, timezone
        f = self.f; output = f.base / 'direct'; output.mkdir()
        (output / 'execution.log').write_text('unit run')
        query = {**next(p for p in f.plan()['paths'] if p.get('kind') == 'unit'),
                 **{key: 'current' for key in unit_reports.BINDINGS}}
        started = datetime.now(timezone.utc).isoformat()
        (output / 'reports').mkdir()
        one = output / 'reports/TEST-one.xml'; one.write_text(PASS)
        self.assertEqual(unit_reports.collect(query, output, started, -9)['quality'], 'yellow-blocked')
        two = output / 'reports/TEST-two.xml'; two.write_text(PASS)
        result = unit_reports.collect(query, output, started, 0)
        self.assertEqual(result['quality'], 'yellow-blocked')
        self.assertIn('duplicate JUnit', result['root_cause']['summary'])
        two.unlink(); one.unlink()
        external = f.base / 'old.xml'; external.write_text(PASS)
        one.symlink_to(external)
        result = unit_reports.collect(query, output, started, 0)
        self.assertEqual(result['quality'], 'yellow-blocked')
        self.assertEqual(result['unit_execution']['reports'], [])


if __name__ == '__main__':
    unittest.main()
