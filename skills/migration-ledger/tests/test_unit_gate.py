"""Unit PATHs give device-free logic evidence and ride the build dispatch: build -> unit -> static."""
import copy
import sys
import unittest

import test_split_testing
import test_validation as tv
import spec_closure
from contracts import Rejected
from execute_test import execute
from harmony_stage import build as stage_result

PASSING = "from pathlib import Path; raise SystemExit(0 if '2' in Path('m1/code.py').read_text() else 1)"
FAILING = "raise SystemExit(1)"


class UnitGateTests(unittest.TestCase):
    def setUp(self):
        self.split = test_split_testing.SplitTestingTests()
        self.split.setUp(); self.addCleanup(self.split.doCleanups)
        self.f = f = self.split.f
        self.unit_code = PASSING
        old_plan, old_report = f.plan, f.report
        def plan():
            p = old_plan()
            p['paths'].append({'path_id': 'U1', 'kind': 'unit', 'name': 'logic unit tests', 'case_id': 'C1',
                               'requirement_id': 'R1', 'required': True,
                               'expected_assertions': [{'assertion_id': 'UNIT-EXIT', 'expected': 0}],
                               'command': {'argv': self.unit_argv(), 'cwd': str(f.target), 'timeout_seconds': 20,
                                           'selection_ref': f.ref('unit-selection.md', 'Module unit test task')}})
            p['tasks'][0]['path_ids'].append('U1')
            return p
        def report(stage, *args, **kwargs):
            r = old_report(stage, *args, **kwargs)
            if stage == 'building':  # one preflight approves the build and the unit command
                build = {k: r['execution'][k] for k in ('argv', 'cwd')}
                r['execution']['commands'] = {'B1': build, 'U1': {'argv': self.unit_argv(), 'cwd': str(f.target)}}
            return r
        f.plan, f.report = plan, report

    def unit_argv(self):
        return [sys.executable, '-c', self.unit_code]

    def run_unit(self, aid='BUILD1'):
        f = self.f
        assignment = f.state()['modules']['M001']['assignments'][aid]
        self.assertEqual((assignment['test_scope'], assignment['closed']), ('build', False))
        receipt = execute(f.root, 'M001', aid, 'U1', self.unit_argv(), str(f.target), f.base / (aid + '-unit'))
        result = stage_result(f.root, 'M001', aid, [receipt] + self.split.receipts)  # unit row first, then build
        f.submit(result, assignment); f.call('accept', {'assignment_id': aid})
        return result['paths'][0]

    def test_unit_rides_the_build_dispatch_then_automation(self):
        f = self.f; self.split.prepare(); self.split.compile()
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['assignment_id']), ('await-result', 'BUILD1'))
        self.assertEqual(self.run_unit()['quality'], 'green-passed')
        m = f.state()['modules']['M001']
        self.assertTrue(m['assignments']['BUILD1']['closed'])
        self.assertEqual(f.state()['next_steps'][0]['test_scope'], 'automation')

    def test_failing_unit_tests_are_a_code_defect_before_any_device_run(self):
        f = self.f; self.unit_code = FAILING
        self.split.prepare(); self.split.compile()
        row = self.run_unit()
        self.assertEqual((row['quality'], row['root_cause']['category']), ('red-bug', 'code'))
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'diagnose')
        ref = f.record(f.report('testing'))
        with self.assertRaisesRegex(Rejected, 'build -> unit -> static -> automation -> visual'):
            f.raw('assign', {'assignment_id': 'AUTO-EARLY', 'role': 'test-runner', 'instance_id': 'test-runner',
                             'test_scope': 'automation', 'context_ref': ref})

    def test_unit_green_survives_missing_automation_environment(self):
        f = self.f; self.split.prepare(); self.split.compile(); self.run_unit()
        self.split.defer()
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['results']['U1']['quality'], m['results']['P1']['quality']),
                         ('automation-deferred', 'green-passed', 'yellow-blocked'))

    def test_every_applicable_logic_item_needs_a_unit_path_or_a_stated_reason(self):
        f = self.f
        plan = f.plan()
        analysis = f.ref('logic-analysis.json', {'dimensions': [
            {'dimension': 'Logic', 'status': 'applicable', 'items': [{'item_id': 'M001-Logic'}]},
            {'dimension': 'UI', 'status': 'not-applicable', 'items': []}]})
        plan['dimension_analysis_ref'] = analysis
        plan['dimension_trace'] = [{'item_id': 'M001-Logic', 'task_ids': ['T1'], 'path_ids': ['P1']}]
        with self.assertRaisesRegex(Rejected, 'unit PATH'):
            tv.plan_check(plan, str(f.target), unit_required=True)
        tv.plan_check(plan, str(f.target))  # not required without the gate
        covered = copy.deepcopy(plan); covered['dimension_trace'][0]['path_ids'] = ['P1', 'U1']
        tv.plan_check(covered, str(f.target), unit_required=True)
        excused = copy.deepcopy(plan); excused['dimension_trace'][0]['unit_test_na'] = 'pure pass-through with no branch'
        tv.plan_check(excused, str(f.target), unit_required=True)

    def test_static_review_cites_tests_when_the_module_has_unit_paths(self):
        f = self.f
        code = f.target / 'm1/code.py'; code.parent.mkdir(exist_ok=True); code.write_text('value = 2\n')
        entry = f.target / 'm1/entry.py'; entry.write_text('from code import value\n')
        test = f.target / 'm1/test_code.py'; test.write_text('from code import value\nassert value == 2\n')
        note = f.ref('note.md', 'reviewed')
        query = {'kind': 'static', 'scenario_requirement_ids': ['R1'], 'unit_tests_present': True,
                 'expected_assertions': [{'assertion_id': 'SPEC-CLOSURE', 'expected': True}],
                 'run_id': 'demo', 'module_id': 'M001', 'path_id': 'S1', 'freeze_id': 'fz', 'code_baseline': 'cb'}
        scenario = {'requirement_id': 'R1', 'status': 'passed', 'summary': 'value reaches entry',
                    'production_symbols': [{'path': str(code), 'symbol': 'value'}],
                    'reached_from': {'path': str(entry), 'symbol': 'value'}, 'evidence_refs': [note]}
        review = {**{k: query[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')},
                  'scenarios': [scenario],
                  'anti_patterns': {k: {'status': 'absent', 'note': 'checked', 'evidence_refs': [note]} for k in spec_closure.ANTI_PATTERNS}}
        with self.assertRaisesRegex(Rejected, 'test_refs'):
            spec_closure.report(query, f.ref('no-tests.json', review), str(f.target))
        scenario['test_refs'] = [{'path': str(test), 'symbol': 'value'}]
        self.assertEqual(spec_closure.report(query, f.ref('with-tests.json', review), str(f.target))['quality'], 'green-passed')


if __name__ == '__main__':
    unittest.main()
