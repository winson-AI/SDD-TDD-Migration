"""A task's red evidence: two self-check notes of one frozen unit PATH, failing before the code and passing after it;
recorded and counted, never a gate."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import execute_test
import migration_report
import red_evidence
import test_unit_reports
from contracts import Rejected, baseline, check_ref, file_ref, read_json

FAIL = ('<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase classname="SearchTest" name="query">'
        '<failure message="not yet"/></testcase></testsuite>')


class RedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.inner = test_unit_reports.UnitReportTests(); self.inner.setUp(); self.addCleanup(self.inner.doCleanups)
        self.f = self.inner.f
        self.f.prepare()  # frozen: the unit PATH U1 and its required test are known before any code
        self.fixture_file = self.f.base / 'fixture.json'

    def argv(self):  # one command for every self-check; what the tests do comes from a file the test rewrites
        program = ('import json, os; from pathlib import Path; d = json.load(open(%r)); '
                   'p = Path(os.environ["SDD_RUNNER_DIR"]) / "reports/TEST-query.xml"; p.parent.mkdir(parents=True, exist_ok=True); '
                   'p.write_text(d["xml"]); raise SystemExit(d["code"])') % str(self.fixture_file)
        return [sys.executable, '-c', program]

    def note(self, name, xml, code):
        self.fixture_file.write_text(json.dumps({'xml': xml, 'code': code}))
        out = self.f.base / name
        execute_test.selfcheck(self.argv(), str(self.f.target), str(out), self.f.root, 'M001', 'U1')
        return file_ref(out / 'selfcheck.json')

    def implementation(self, trace):
        f = self.f; a = f.assign('implementer', 'I1')
        source = f.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True); source.write_text('value = 2\n')
        refs = [file_ref(source)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': 'I1',
                  'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(source)], **trace}],
                  'production_binding_evidence': f.ref('binding.txt', 'real binding reviewed'),
                  'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')}}
        f.submit(result, a)
        return a

    def test_a_note_records_the_state_of_each_required_test(self):
        before = read_json(check_ref(self.note('red', FAIL, 1)))
        self.assertEqual((before['producer'], before['path_id'], before['required'], before['exit_code']),
                         ('author-selfcheck', 'U1', {'SearchTest#query': 'failed'}, 1))
        self.assertTrue(Path(before['log_ref']['path']).is_file())
        missing = read_json(check_ref(self.note('missing', '<testsuite tests="0"></testsuite>', 0)))
        self.assertEqual(missing['required'], {'SearchTest#query': 'missing'})
        with self.assertRaisesRegex(Rejected, 'frozen unit PATH'):
            execute_test.selfcheck(self.argv(), str(self.f.target), str(self.f.base / 'bad'), self.f.root, 'M001', 'B1')

    def test_failing_then_passing_notes_are_the_tasks_red_evidence(self):
        before = self.note('red', FAIL, 1); after = self.note('green', test_unit_reports.PASS, 0)
        a = self.implementation({'test_order': 'tests-first', 'red_evidence': {'before_ref': before, 'after_ref': after}})
        self.f.call('accept', {'assignment_id': a['assignment_id']})
        m = self.f.state()['modules']['M001']
        self.assertEqual(m['task_red'], {'T1': 'observed'})
        self.assertEqual(red_evidence.counts(m), {'observed': 1, 'not_observed': 0, 'not_applicable': 0})
        cost = migration_report.build(self.f.root, self.f.state(), self.f.state()['last_sequence'])['workflow_cost']['modules']['M001']
        self.assertEqual(cost['tdd']['observed'], 1); self.assertIn('planning_share', cost)
        self.assertIn('测试先行', migration_report.render(migration_report.build(self.f.root, self.f.state(), self.f.state()['last_sequence'])))

    def test_a_task_without_evidence_is_accepted_and_counted_as_not_observed(self):
        a = self.implementation({})
        self.f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(self.f.state()['modules']['M001']['task_red'], {'T1': 'not-observed'})

    def test_evidence_that_never_failed_or_never_passed_is_refused(self):
        green = self.note('green', test_unit_reports.PASS, 0); again = self.note('again', test_unit_reports.PASS, 0)
        with self.assertRaisesRegex(Rejected, 'first run must fail or miss'):
            self.implementation({'red_evidence': {'before_ref': green, 'after_ref': again}})
        red = self.note('red', FAIL, 1); red2 = self.note('red2', FAIL, 1)
        with self.assertRaisesRegex(Rejected, 'second run must pass'):
            self.f.call('submit', {'assignment_id': 'I1', 'fencing_token': self.f.state()['modules']['M001']['assignments']['I1']['fencing_token'],
                                   'result_ref': self.f.ref('r2.json', self.result_with({'red_evidence': {'before_ref': red, 'after_ref': red2}}))}, role='implementer')

    def result_with(self, trace):
        f = self.f; a = f.state()['modules']['M001']['assignments']['I1']
        source = f.target / 'm1/code.py'; refs = [file_ref(source)]
        return {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': 'I1',
                'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': baseline(refs),
                'task_trace': [{'task_id': 'T1', 'files': [str(source)], **trace}],
                'production_binding_evidence': f.ref('binding.txt', 'real binding reviewed'),
                'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')}}


if __name__ == '__main__':
    unittest.main()
