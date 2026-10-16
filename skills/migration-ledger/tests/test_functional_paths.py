"""An in-process functional PATH: a frozen command, JUnit attribution, one assertion per named test; the skeleton writes
it for cases no device shows, and a device UI script where a UI tree gives stable selectors."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import automation_report
import spec_skeleton
import test_source_changes
import test_ui_fidelity
import test_unit_reports
import test_validation as tv
from contracts import Rejected, check_ref, read_json
from execute_test import execute
from harmony_stage import build as stage_result

XML = ('<testsuite tests="3" failures="%d" errors="0" skipped="0"><testcase classname="SearchTest" name="query"/>'
       '<testcase classname="FlowTest" name="login"/><testcase classname="FlowTest" name="logout">%s</testcase></testsuite>')


class FunctionalPathTests(unittest.TestCase):
    def setUp(self):
        self.inner = test_unit_reports.UnitReportTests(); self.inner.setUp(); self.addCleanup(self.inner.doCleanups)
        f = self.f = self.inner.f
        self.flow_file = f.base / 'flow-fixture.json'  # one frozen command; what the flow tests report comes from this file
        old_plan, old_report = f.plan, f.report
        def plan():
            p = old_plan()
            flow = next(row for row in p['paths'] if row['path_id'] == 'P1')  # the case's automation path, in process
            flow.update(platform='jvm', command={'argv': self.flow_argv(), 'cwd': str(f.target), 'timeout_seconds': 20,
                                                  'selection_ref': f.ref('flow-selection.md', 'kotlin.test flow tests of the state machine')},
                        unit_report={'format': 'junit', 'patterns': ['reports/TEST-*.xml'], 'required_test_ids': ['FlowTest#login', 'FlowTest#logout']},
                        expected_assertions=[{'assertion_id': 'A1', 'expected': True, 'test_id': 'FlowTest#login'},
                                             {'assertion_id': 'A2', 'expected': True, 'test_id': 'FlowTest#logout'}])
            return p
        def report(stage, *args, **kwargs):
            r = old_report(stage, *args, **kwargs)
            if stage == 'testing':
                r['execution'] = {'argv': self.flow_argv(), 'cwd': str(f.target), 'environment_ref': f.ref('flow-env.md', 'JVM test fixture')}
            return r
        f.plan, f.report = plan, report

    def flow_argv(self):
        program = ('import json, os; from pathlib import Path; d = json.load(open(%r)); '
                   'p = Path(os.environ["SDD_RUNNER_DIR"]) / "reports/TEST-flow.xml"; p.parent.mkdir(parents=True, exist_ok=True); '
                   'p.write_text(d["xml"]); raise SystemExit(d["code"])') % str(self.flow_file)
        return [sys.executable, '-c', program]

    def run_flow(self, flow_xml=XML % (0, ''), code=0):
        f = self.f
        self.inner.run_unit()  # build + unit accepted under BUILD1
        self.flow_file.write_text(json.dumps({'xml': flow_xml, 'code': code}))
        self.inner.fixture.split.f.assign('test-runner', 'AUTO1')
        receipt = execute(f.root, 'M001', 'AUTO1', 'P1', self.flow_argv(), f.target, f.base / 'flow-attempt')
        result = stage_result(f.root, 'M001', 'AUTO1', [receipt])
        a = f.state()['modules']['M001']['assignments']['AUTO1']
        f.submit(result, a); f.call('accept', {'assignment_id': 'AUTO1'})
        return result['paths'][0], read_json(check_ref(receipt))

    def test_a_functional_path_runs_its_frozen_command_and_scores_each_named_test(self):
        row, receipt = self.run_flow()
        self.assertEqual(row['quality'], 'green-passed')
        self.assertEqual([(a['assertion_id'], a['actual'], a['passed']) for a in row['assertions']], [('A1', True, True), ('A2', True, True)])
        self.assertEqual(receipt['requested_argv'], self.flow_argv())
        m = self.f.state()['modules']['M001']
        self.assertEqual((m['results']['P1']['quality'], m['results']['P1']['scripted'], m['phase']), ('green-passed', False, 'dod'))

    def test_a_failed_named_test_is_that_assertions_red(self):
        row, _ = self.run_flow(XML % (1, '<failure message="logout stays signed in"/>'), code=1)
        self.assertEqual((row['quality'], row['root_cause']['category']), ('red-bug', 'code'))
        self.assertEqual([(a['assertion_id'], a['actual']) for a in row['assertions']], [('A1', True), ('A2', False)])

    def test_every_assertion_names_a_required_test(self):
        plan = self.f.plan(); flow = next(row for row in plan['paths'] if row['path_id'] == 'P1')
        flow['expected_assertions'][1].pop('test_id')
        with self.assertRaisesRegex(Rejected, 'each name one required test'):
            tv.plan_check(plan, str(self.f.target))
        flow['expected_assertions'][1]['test_id'] = 'FlowTest#login'
        with self.assertRaisesRegex(Rejected, 'each name one required test'):
            tv.plan_check(plan, str(self.f.target))


class FunctionalSkeletonTests(unittest.TestCase):
    def test_a_case_no_device_shows_gets_an_in_process_flow_test(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        files = spec_skeleton.write(t.f.root, 'M001', t.f.root / 'staging/spec-designer/flow')['files']
        upstream = json.loads(check_ref(files['upstream-test-plan.json']).read_text())
        flow = next(p for p in upstream['paths'] if p['kind'] == 'automation')
        asset = next(a for a in upstream['test_assets'] if a['path_ids'] == [flow['path_id']])
        self.assertEqual((flow['platform'], flow['unit_report']['required_test_ids'], flow['expected_assertions'][0]['test_id'], asset['kind']),
                         ('jvm', asset['required_test_ids'], asset['required_test_ids'][0], 'test-source'))
        self.assertIn('FlowTest', asset['required_test_ids'][0]); self.assertIn('fun flow(', check_ref(asset['ref']).read_text())

    def test_a_case_a_device_shows_gets_a_ui_script_from_the_tree(self):
        u = test_ui_fidelity.UiFidelityTests(); u.setUp(); self.addCleanup(u.doCleanups)
        f = u.f; s = copy.deepcopy(f.state()); m = s['modules']['M001']
        m['dimension_analysis_ref'] = u.analysis_ref(ui_evidence=True)
        s['test_adapter'] = {'device': {'platforms': ['android']}}
        out = f.root / 'staging/spec-designer/ui'; out.mkdir(parents=True)
        documents = {kind + '.md': f.ref(f'doc-{kind}.md', kind) for kind in ('proposal', 'spec', 'design', 'tasks')}
        rest = spec_skeleton.plans(s, m, out, documents)
        upstream = rest['upstream-test-plan.json']
        screen = next(p for p in upstream['paths'] if p['kind'] == 'automation')
        script = next(a for a in upstream['test_assets'] if a['kind'] == 'script')
        self.assertEqual((screen['platform'], screen['preparation']['asset_ids'], script['path_ids'], script['assertions']),
                         ('android', [script['asset_id']], [screen['path_id']], [{'path_id': screen['path_id'], 'assertion_id': 'ASSERT-' + screen['path_id']}]))
        self.assertIn('node:root', rest[script['ref']])


class ScriptedDeviceReportTests(unittest.TestCase):
    def test_the_report_counts_device_paths_a_frozen_script_drove(self):
        rows = [{'module_id': 'M001', 'path_id': 'P%d' % n, 'case_id': 'C1', 'kind': 'automation', 'task_ids': [], 'platform': 'android', 'parameters': {},
                 'on_device': True, 'quality': 'green-passed', 'stale': False, 'attempt_executed': True, 'executed': True, 'assertions': [],
                 'evidence_refs': [], 'code_baseline': 'b', 'test_run_id': 't%d' % n, 'scripted': n == 1, 'flaky': n == 1} for n in (1, 2)]
        summary = automation_report.summarize(rows, {'C1'})
        self.assertEqual((summary['device_paths'], summary['scripted_device_paths'], summary['scripted_flaky_paths']), (2, 1, 1))
        self.assertIn('脚本驱动', '\n'.join(automation_report.render({**summary, 'modules': {}, 'tasks': {}}, str)))


if __name__ == '__main__':
    unittest.main()
