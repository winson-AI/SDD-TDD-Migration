"""A case the user sees is verified on a device or on the rendered screen, and the statistics say where each path ran."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import automation_report
import ledger
import migration_report
import user_paths
from contracts import Rejected, file_ref
import test_decomposition
import test_ledger
import test_source_changes


class PlanGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name, value):
        path = self.base / name
        path.write_text(value if isinstance(value, str) else json.dumps(value))
        return file_ref(path)

    def module(self, **over):
        return {'module_id': 'M001', 'case_ids': ['C1', 'C2', 'C3'], **over}

    def plan(self, *paths, ui=('C1', 'C2'), **over):
        analysis = {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable' if ui else 'not-applicable', 'items': [{'item_id': 'SCREEN', 'case_ids': list(ui)}] if ui else []},
            {'dimension': 'Logic', 'status': 'applicable', 'items': [{'item_id': 'RULE', 'case_ids': ['C1', 'C2', 'C3']}]}]}
        return {'dimension_analysis_ref': self.ref('analysis.json', analysis), 'paths': list(paths), **over}

    def path(self, case, **over):
        return {'path_id': 'P-' + case + '-' + str(len(over)), 'case_id': case, 'kind': 'automation', **over}

    def gap(self, case, **over):
        return {'case_id': case, 'reason': 'the screen needs a paired second device', 'evidence_refs': [self.ref('gap.md', 'reviewed')], **over}

    def test_where_a_path_runs(self):
        self.assertTrue(user_paths.on_device({'kind': 'visual'}))
        self.assertTrue(user_paths.on_device({'kind': 'automation', 'platform': 'android'}))
        self.assertTrue(user_paths.on_device({'platform': 'harmony'}))  # a path is automation unless it says otherwise
        self.assertTrue(user_paths.on_device({'kind': 'automation', 'interaction_id': 'open-settings'}))
        for path in ({'kind': 'automation'}, {'kind': 'automation', 'platform': 'jvm'}, {'kind': 'unit', 'platform': 'android'},
                     {'kind': 'build'}, {'kind': 'static'}):
            self.assertFalse(user_paths.on_device(path), path)

    def test_a_user_visible_case_needs_a_device_or_visual_path(self):
        in_process = [self.path(case) for case in ('C1', 'C2', 'C3')]
        with self.assertRaisesRegex(Rejected, 'needs a device or visual path, or a declared device gap: C1, C2'):
            user_paths.plan_gate(self.module(), self.plan(*in_process))
        on_screen = [self.path('C1', platform='android'), self.path('C2', kind='visual')]
        user_paths.plan_gate(self.module(), self.plan(*in_process, *on_screen))
        with self.assertRaisesRegex(Rejected, 'declared device gap: C2'):
            user_paths.plan_gate(self.module(), self.plan(*in_process, on_screen[0]))

    def test_only_the_leaf_that_accepts_the_case_owes_the_path(self):
        in_process = [self.path(case) for case in ('C1', 'C2', 'C3')]
        user_paths.plan_gate(self.module(acceptance_case_ids=[]), self.plan(*in_process))      # a supporting slice
        user_paths.plan_gate(self.module(acceptance_case_ids=['C3']), self.plan(*in_process))  # accepts what no screen shows
        user_paths.plan_gate(self.module(), self.plan(*in_process, ui=()))                     # no UI in this allocation
        with self.assertRaisesRegex(Rejected, 'declared device gap: C2'):
            user_paths.plan_gate(self.module(acceptance_case_ids=['C2', 'C3']), self.plan(*in_process))

    def test_a_case_that_cannot_have_one_is_a_declared_gap_with_its_reason(self):
        paths = [self.path('C1', platform='android'), self.path('C2'), self.path('C3')]
        user_paths.plan_gate(self.module(), self.plan(*paths, device_gaps=[self.gap('C2')]))
        for gaps, message in (([self.gap('C2', reason=' ')], 'states why no device or visual path'),
                              ([self.gap('C2', evidence_refs=[])], 'device gap evidence'),
                              ([self.gap('C1')], 'already verifies'),      # it has its device path
                              ([self.gap('C2'), self.gap('C3')], 'not user-visible in this leaf'),
                              ({'C2': 'no device'}, 'device_gaps must be a list')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                user_paths.plan_gate(self.module(), self.plan(*paths, device_gaps=gaps))


class WiringTests(unittest.TestCase):
    def test_a_prepared_run_judges_a_new_plan_and_not_the_one_it_holds(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f
        with mock.patch.object(user_paths, 'plan_gate') as gate:
            plan = t.plan('M001')
            if f.state().get('test_design_required'):
                from test_design_stage import prepare_design
                prepare_design(f, plan, 'M001')
            ref = f.ref('plan-M001.json', plan)
            f.call('plan', {'plan_ref': ref}, role='spec-designer', module='M001')
            self.assertEqual(gate.call_count, 1)
            self.assertEqual(gate.call_args.args[0]['module_id'], 'M001')
            f.call('plan', {'plan_ref': ref}, role='spec-designer', module='M001')  # the plan the Ledger already holds
            self.assertEqual(gate.call_count, 1)

    def test_a_run_without_planning_coverage_is_not_asked(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        with mock.patch.object(user_paths, 'plan_gate') as gate:
            f.call('plan', {'plan_ref': f.ref('plan.json', f.plan())}, role='spec-designer')
            gate.assert_not_called()


class UnverifiedRunTests(unittest.TestCase):
    """What was built passes; the automation of the case with no device path does not, and the run says so at the end."""
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        authored = f.plan
        f.plan = lambda: {**authored(), 'device_gaps': [{'case_id': 'C1', 'reason': 'the screen needs a paired second device',
                                                         'evidence_refs': [f.ref('gap.md', 'reviewed')]}]}

    def finish(self):
        f = self.f
        f.prepare(); f.implementation()
        a, result = f.make_test_result()
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('complete', {'dod_ref': f.ref('dod.md', 'all reviewed')})

    def audit(self):
        f = self.f
        test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'AUDIT', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        scope = ledger.audit_scope(f.state())
        test_id = test_ledger.start_audit_test(f, 'AUDIT')
        rr = test_ledger.execute(f.root, 'GLOBAL', test_id, 'GP1', [sys.executable, str(f.base / 'adapter.py')], str(f.target), f.base / 'global-exec')
        receipt = json.loads(Path(rr['path']).read_text())
        report = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL', 'assignment_id': 'AUDIT',
                  'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'],
                  'snapshot': {'M001': f.state()['modules']['M001']['code_baseline']},
                  'paths': [{'path_id': 'GP1', 'quality': 'green-passed', 'executed': True, 'test_run_id': receipt['test_run_id'],
                             'execution_receipt': rr, 'assertions': json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']}]}
        f.call('audit', {'report_ref': f.ref('audit.json', test_ledger.accept_audit_test(f, report))}, role='auditor', module=None)

    def test_the_module_completes_and_is_yellow_while_everything_it_ran_is_green(self):
        f = self.f; self.finish()
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['quality']), ('completed', 'yellow-blocked'))
        self.assertTrue(all(row['quality'] == 'green-passed' for row in m['results'].values()))  # the build and what ran
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')  # the run goes on to its audit

    def test_the_run_ends_unverified_and_asks_nobody_to_authorize_a_green_delivery(self):
        f = self.f; self.finish(); self.audit()
        state = f.state()
        self.assertEqual((state['audit']['quality'], state['quality']), ('green-passed', 'yellow-blocked'))
        step = state['global_next_step']
        self.assertEqual((step['reason'], step['quality'], step['human_required']), ('completed-with-unverified-tests', 'yellow-blocked', False))
        self.assertEqual(step['device_gap_cases'], {'M001': ['C1']})

    def test_the_report_marks_the_case_and_its_automation_yellow_and_leaves_the_build_green(self):
        f = self.f; self.finish(); self.audit()
        state = f.state()
        report = migration_report.build(f.root, state, state['last_sequence'])
        self.assertEqual(report['report_stage'], 'completed-with-unverified-tests')
        case, = [c for c in report['cases'] if c['case_id'] == 'C1']
        self.assertEqual(case['quality'], 'yellow-blocked')
        gap, = [row for row in report['paths'] if row['path_id'] == 'DEVICE-GAP:C1']
        self.assertEqual((gap['kind'], gap['quality'], gap['executed'], gap['on_device']), ('automation', 'yellow-blocked', False, True))
        self.assertEqual(gap['root_causes'][0]['category'], 'device-path-gap')
        self.assertIn('the screen needs a paired second device', gap['root_causes'][0]['summary'])
        built = [row for row in report['paths'] if row['module_id'] == 'M001' and row['path_id'] != 'DEVICE-GAP:C1']
        self.assertTrue(built and all(row['quality'] == 'green-passed' for row in built))
        module = report['automation']['modules']['M001']
        self.assertEqual((module['yellow_paths'], module['yellow_reasons'], module['device_paths'], module['device_passed_paths']),
                         (1, {'not-executed': 1}, 1, 0))
        self.assertFalse(module['validation_complete'])


class GapUnderAParentTests(unittest.TestCase):
    def test_a_parent_whose_children_have_a_gap_settles_and_the_run_goes_on_to_its_audit(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        authored = f.plan
        f.plan = lambda: {**authored(), 'device_gaps': [{'case_id': 'C1', 'reason': 'the screen needs a paired second device',
                                                         'evidence_refs': [f.ref('gap.md', 'reviewed')]}]}
        f.root_scope(); f.split(); f.global_plan()
        for mid in ('M001', 'M002'):
            f.prepare_leaf(mid); f.complete_leaf(mid)
        f.summarize()
        state = f.state()
        self.assertEqual({mid: (m['phase'], m['quality']) for mid, m in state['modules'].items()},
                         {'M001': ('completed', 'yellow-blocked'), 'M002': ('completed', 'yellow-blocked')})
        group = state['module_groups']['M010']
        self.assertEqual((group['phase'], group['quality']), ('waiting-auditor', 'yellow-blocked'))  # settled, and not Green
        self.assertTrue(state['module_rounds']['all_settled'])
        self.assertEqual(state['global_next_step']['operation'], 'audit-code-review')


class StatisticsTests(unittest.TestCase):
    def row(self, path_id, **over):
        return dict(module_id='M001', task_ids=['T1'], case_id='C1', path_id=path_id, kind='automation', platform=None, parameters={},
                    code_baseline='baseline', test_run_id='run-' + path_id, evidence_refs=[], stale=False, quality='green-passed',
                    assertions=[], attempt_executed=True, execution_status='completed', on_device=False) | over

    def rows(self):
        return [self.row('IN-1'), self.row('IN-2', quality='red-bug'),
                self.row('DEV-1', platform='android', on_device=True), self.row('DEV-2', platform='android', on_device=True, quality='yellow-blocked'),
                self.row('VIS-1', kind='visual', on_device=True), self.row('VIS-2', kind='visual', on_device=True, stale=True),
                self.row('BUILD-1', kind='build')]

    def test_device_in_process_and_visual_paths_are_counted_apart(self):
        summary = automation_report.summarize(self.rows(), ['C1'])
        self.assertEqual(summary['required_paths'], 4)  # automation only, as before
        self.assertEqual((summary['device_paths'], summary['device_passed_paths']), (2, 1))
        self.assertEqual((summary['in_process_paths'], summary['in_process_passed_paths']), (2, 1))
        self.assertEqual((summary['visual_paths'], summary['visual_passed_paths']), (2, 1))
        self.assertEqual(summary['device_gap_cases'], [])

    def test_a_declared_gap_is_listed_and_the_validation_is_not_complete(self):
        rows = [self.row('IN-1'), self.row('DEV-1', platform='android', on_device=True)]
        self.assertTrue(automation_report.summarize(rows, ['C1'])['validation_complete'])
        summary = automation_report.summarize(rows, ['C1'], {'C1'})
        self.assertEqual(summary['device_gap_cases'], ['C1'])
        self.assertFalse(summary['validation_complete'])

    def test_the_report_gives_the_split_per_task_and_names_the_gap_as_a_limitation(self):
        proof = {'path': '/evidence/gap.md', 'sha256': 'a' * 64}
        plan = {'tasks': [{'task_id': 'T1', 'case_ids': ['C1'], 'path_ids': ['IN-1']}, {'task_id': 'T2', 'case_ids': ['C2'], 'path_ids': []}],
                'device_gaps': [{'case_id': 'C1', 'reason': 'the screen needs a paired second device', 'evidence_refs': [proof]}]}
        state = {'case_ids': ['C1', 'C2'], 'modules': {'M001': {'case_ids': ['C1', 'C2'], 'plan': plan}}}
        summary = automation_report.build(state, [self.row('IN-1')])
        self.assertEqual(summary['device_gap_cases'], ['C1'])
        self.assertEqual(summary['tasks']['M001/T1']['device_gap_cases'], ['C1'])
        self.assertEqual(summary['tasks']['M001/T2']['device_gap_cases'], [])
        text = '\n'.join(automation_report.render(summary, str))
        self.assertIn('| 范围 | 设备路径 | 进程内路径 | 视觉路径 | 设备缺口 CASE |', text)
        self.assertIn("| 宿主任务 | 0 / 0 | 1 / 1 | 0 / 0 | ['C1'] |", text)
        _, limitations, _ = migration_report.fidelity(state, [], lambda ref: Path(ref['path']))
        gap, = [row for row in limitations if row['kind'] == 'device-path-gap']
        self.assertEqual((gap['module_id'], gap['case_ids'], gap['evidence_refs']), ('M001', ['C1'], [proof]))
        self.assertIn('the screen needs a paired second device', gap['reason'])


if __name__ == '__main__':
    unittest.main()
