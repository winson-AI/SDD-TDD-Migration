"""The completion contract reads the built-in web Main's report the way it reads the Harmony adapter's: bound to the query,
the page and every step, Green only when every assertion was observed after its step; and a project adapter's bare
assertions are still the documented minimum."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, digest, file_ref
import test_completion

STEPS = [{'action': 'goto', 'url': 'http://127.0.0.1:1/index.html'}, {'action': 'click', 'selector': '#submit'}]
PLANNED = {'path_id': 'P1', 'kind': 'automation', 'platform': 'web', 'task_type': 'test',
           'expected_assertions': [{'assertion_id': 'A1', 'expected': True, 'description': 'heading', 'matcher': 'exact', 'verification': 'dom', 'after_step': 2,
                                    'predicate': {'kind': 'text', 'selector': '#heading', 'equals': 'Items'}}]}


class WebMainReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.attempt = Path(self.tmp.name).resolve() / '.sdd-runs/r/runs/harmony/automation/attempt'
        self.out = self.attempt / 'web'; self.out.mkdir(parents=True)
        self.query = {**PLANNED, 'steps': STEPS, 'run_id': 'r', 'module_id': 'M001', 'freeze_id': 'F', 'code_baseline': 'B', 'execution_contract_version': 2}
        self.write(self.attempt / 'query.json', self.query); (self.attempt / 'log.txt').write_text('')
        self.write(self.out / 'environment.json', {'platform': 'web', 'task_type': 'test', 'browser': 'chromium'})
        shots = {}
        for n in (1, 2):
            for side in ('before', 'after'):
                p = self.out / f'step-{n}-{side}.png'; p.write_bytes(b'png' + bytes([n])); shots[n, side] = file_ref(p)
        self.trace = {'schema_version': 1, 'query_sha256': digest(self.query), 'steps': [
            {'step_number': n, 'step_sha256': digest(STEPS[n - 1]), 'status': 'executed', 'before_ref': shots[n, 'before'], 'after_ref': shots[n, 'after'],
             'started_at': 't', 'finished_at': 't', 'actions': [STEPS[n - 1]]} for n in (1, 2)]}
        self.observations = [{'sequence': 1, 'assertion_ids': ['A1'], 'description': 'heading', 'result': True, 'actual': 'Items', 'reason': 'held',
                              'tool': 'dom', 'evidence_refs': [shots[2, 'after']], 'error': None, 'after_step': 2, 'step_sha256': digest(STEPS[1])}]
        self.media = [{'kind': 'screenshot', 'ref': ref} for ref in shots.values()]

    def write(self, path, value):
        path.write_text(json.dumps(value)); return file_ref(path)

    def receipt(self, report, exit_code=0):
        return {'execution_contract_version': 2, 'run_id': 'r', 'module_id': 'M001', 'path_id': 'P1', 'freeze_id': 'F', 'code_baseline': 'B', 'exit_code': exit_code,
                'query_ref': file_ref(self.attempt / 'query.json'), 'log_ref': file_ref(self.attempt / 'log.txt'), 'result_ref': self.write(self.attempt / 'result.json', report)}

    def report(self, **over):
        return {'producer': 'web-main', 'platform': 'web', 'task_type': 'test', 'step_contract_version': 1, 'run_id': 'r', 'module_id': 'M001', 'path_id': 'P1',
                'freeze_id': 'F', 'code_baseline': 'B', 'query_sha256': digest(self.query), 'quality': 'green-passed', 'flaky': False,
                'assertions': [{'assertion_id': 'A1', 'expected': True, 'actual': True, 'passed': True}],
                'observations_ref': self.write(self.out / 'observations.json', self.observations), 'step_trace_ref': self.write(self.out / 'step-trace.json', self.trace),
                'environment_ref': file_ref(self.out / 'environment.json'), 'media_refs': self.media, 'artifacts': [], **over}

    def test_a_web_main_report_is_green_when_every_step_and_observation_is_bound(self):
        row = test_completion.interpret(self.receipt(self.report()), PLANNED)
        self.assertEqual((row['quality'], row['execution_status'], len(row['media_refs'])), ('green-passed', 'completed', 4))

    def test_what_is_not_shown_for_a_step_or_an_assertion_is_yellow(self):
        self.trace['steps'][1]['status'] = 'blocked'
        row = test_completion.interpret(self.receipt(self.report()), PLANNED)
        self.assertEqual((row['quality'], row['root_cause']['reason_code']), ('yellow-blocked', 'path-step-evidence-incomplete'))
        self.assertIn('step 2: blocked', row['root_cause']['summary'])
        self.trace['steps'][1]['status'] = 'executed'; self.observations[0]['after_step'] = 1
        row = test_completion.interpret(self.receipt(self.report()), PLANNED)
        self.assertIn('A1: not observed after its frozen step', row['root_cause']['summary'])
        self.observations[0]['after_step'] = 2
        with self.assertRaisesRegex(Rejected, 'web query mismatch'):  # a report of another query is refused, not graded
            test_completion.interpret(self.receipt(self.report(query_sha256='0' * 64)), PLANNED)

    def test_a_project_adapter_reports_its_assertions_and_the_verdict_follows_from_them(self):
        row = test_completion.interpret(self.receipt({'assertions': [{'assertion_id': 'A1', 'expected': True, 'actual': True, 'passed': True}]}), PLANNED)
        self.assertEqual((row['quality'], row['executed']), ('green-passed', True))
        row = test_completion.interpret(self.receipt({'assertions': [{'assertion_id': 'A1', 'expected': True, 'actual': False, 'passed': False}]}, exit_code=1), PLANNED)
        self.assertEqual((row['quality'], row['root_cause']['category']), ('red-bug', 'code'))
        self.assertIn('A1', row['root_cause']['summary'])
        row = test_completion.interpret(self.receipt({'assertions': []}), PLANNED)
        self.assertEqual(row['quality'], 'yellow-blocked')


if __name__ == '__main__':
    unittest.main()
