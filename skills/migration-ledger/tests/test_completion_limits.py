"""Skipped/expected-failure reports cannot become Green during host normalization."""
import copy
from pathlib import Path
import sys
import unittest

import test_ledger
from contracts import Rejected, check_ref, read_json, validate_result
from execute_test import execute

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
import harmony_stage


class CompletionLimitsTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.prepare(); self.f.implementation()

    def report(self, flags, quality='green-passed'):
        f = self.f
        assignment = f.assign('test-runner', 'TEST-LIMIT')
        script_root = str(Path(__file__).resolve().parents[1] / 'scripts')
        adapter = f.base / 'adapter-limits.py'
        adapter.write_text(f'''
import sys,json
from pathlib import Path
sys.path.insert(0, {script_root!r})
from contracts import digest,file_ref
q=json.loads(Path(sys.argv[sys.argv.index('--query-file')+1]).read_text())
out=Path(sys.argv[sys.argv.index('--result-file')+1])
obs=out.parent/'observations.json'; obs.write_text('[]')
quality={quality!r}
passed=quality == 'green-passed'
report={{'producer':'harmony-adapter', 'query_sha256':digest(q),
    **{{k:q[k] for k in ('run_id','module_id','path_id','freeze_id','code_baseline')}},
    'quality':quality, 'flaky':False, 'observations_ref':file_ref(obs), **{flags!r},
    'assertions':[{{'assertion_id':'A1','expected':2,'actual':2 if passed else 1,'passed':passed}}]}}
if not passed:
    report['root_cause']={{'category':'code','summary':'observed fixture failure',
        'confidence':'observed','owner':'M001','next_action':'diagnose'}}
out.write_text(json.dumps(report))
sys.exit(0 if passed else 1)
''', encoding='utf-8')
        ref = execute(f.root, 'M001', assignment['assignment_id'], 'P1',
                      [sys.executable, '-B', str(adapter)], str(f.target), f.base / 'limited-execution')
        native = read_json(check_ref(read_json(check_ref(ref))['result_ref']))
        stage = harmony_stage.build(f.root, 'M001', assignment['assignment_id'], [ref])
        return assignment, native, stage

    def accept(self, assignment, stage):
        self.f.submit(stage, assignment)
        self.f.call('accept', {'assignment_id': assignment['assignment_id']})
        return self.f.state()['modules']['M001']['results']['P1']

    def assert_limited(self, flag):
        assignment, native, stage = self.report({flag: True})
        row = stage['paths'][0]
        self.assertEqual(native['quality'], 'green-passed')
        self.assertEqual(row['quality'], 'yellow-blocked')
        self.assertIs(row[flag], True)
        self.assertEqual(row['assertions'], native['assertions'])
        self.assertEqual(row['root_cause']['reason_code'], 'incomplete-test-execution')
        forged = copy.deepcopy(stage)
        forged['paths'][0].update(quality='green-passed')
        forged['paths'][0].pop(flag)
        with self.assertRaisesRegex(Rejected, 'host completion interpretation changed'):
            validate_result(forged, self.f.state()['modules']['M001'], assignment, run_root=self.f.root)
        self.assertEqual(self.accept(assignment, stage)['quality'], 'yellow-blocked')

    def test_skipped_report_is_persisted_as_yellow_with_real_assertions(self):
        self.assert_limited('skipped')

    def test_expected_failure_cannot_pass_through_normalization(self):
        self.assert_limited('xfail')

    def test_false_flags_allow_clean_pass(self):
        assignment, _, stage = self.report({'skipped': False, 'xfail': False})
        self.assertEqual(self.accept(assignment, stage)['quality'], 'green-passed')

    def test_observed_red_is_not_downgraded_by_skip(self):
        assignment, native, stage = self.report({'skipped': True}, 'red-bug')
        self.assertEqual(stage['paths'][0]['root_cause'], native['root_cause'])
        self.assertEqual(self.accept(assignment, stage)['quality'], 'red-bug')

    def test_raw_report_cannot_bypass_limits_by_omitting_completion_version(self):
        assignment, native, stage = self.report({'xfail': True})
        raw = copy.deepcopy(stage)
        record = raw['paths'][0]
        record.pop('host_completion_version')
        record.update(quality='green-passed', assertions=native['assertions'])
        with self.assertRaisesRegex(Rejected, 'not a clean pass'):
            validate_result(raw, self.f.state()['modules']['M001'], assignment, run_root=self.f.root)


if __name__ == '__main__':
    unittest.main()
