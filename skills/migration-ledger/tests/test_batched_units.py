"""Unit PATHs that froze the same command run once; each keeps its own receipt and JUnit attribution."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_unit_reports
from contracts import Rejected, read_json
from execute_test import execute
from harmony_stage import build as stage_result

BOTH = ('<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase classname="SearchTest" name="query"/>'
        '<testcase classname="SearchTest" name="other"/></testsuite>')


class BatchedUnitTests(unittest.TestCase):
    def setUp(self):
        self.inner = test_unit_reports.UnitReportTests(); self.inner.setUp(); self.addCleanup(self.inner.doCleanups)
        self.inner.xml = BOTH
        self.second = 'SearchTest#other'
        f = self.f = self.inner.f
        old_plan, old_report = f.plan, f.report
        def plan():
            p = old_plan()
            unit = next(row for row in p['paths'] if row.get('kind') == 'unit')
            p['paths'].append({**copy.deepcopy(unit), 'path_id': 'U2', 'name': 'other logic',
                               'unit_report': {**unit['unit_report'], 'required_test_ids': [self.second]}})
            p['tasks'][0]['path_ids'].append('U2')
            return p
        def report(stage, *args, **kwargs):
            r = old_report(stage, *args, **kwargs)
            if stage == 'building':
                r['execution']['commands']['U2'] = r['execution']['commands']['U1']
            return r
        f.plan, f.report = plan, report

    def compiled(self):
        self.inner.fixture.split.prepare(); self.inner.fixture.split.compile()
        return self.f.state()['modules']['M001']['assignments']['BUILD1']

    def run_batch(self, pids=('U1', 'U2')):
        f = self.f
        return execute(f.root, 'M001', 'BUILD1', list(pids), self.inner.fixture.unit_argv(), f.target, f.base / 'batch')

    def test_one_run_gives_every_path_its_own_receipt_and_attribution(self):
        a = self.compiled(); f = self.f
        receipts = self.run_batch()
        r1, r2 = (read_json(r['path']) for r in receipts)
        self.assertEqual((r1['path_id'], r2['path_id']), ('U1', 'U2'))
        self.assertNotEqual(r1['test_run_id'], r2['test_run_id'])
        self.assertEqual((r1['log_ref'], r1['batch']), (r2['log_ref'], {'path_ids': ['U1', 'U2'], 'test_run_id': r2['batch']['test_run_id']}))
        self.assertEqual(len(list((f.base / 'batch').glob('execution.log'))), 1)
        result = stage_result(f.root, 'M001', 'BUILD1', receipts + self.inner.fixture.split.receipts)
        rows = {row['path_id']: row for row in result['paths']}
        self.assertEqual({pid: rows[pid]['quality'] for pid in ('U1', 'U2')}, {'U1': 'green-passed', 'U2': 'green-passed'})
        self.assertEqual(rows['U2']['unit_execution']['counts']['total'], 2)
        f.submit(result, a); f.call('accept', {'assignment_id': 'BUILD1'})
        m = f.state()['modules']['M001']
        self.assertEqual({m['results'][pid]['quality'] for pid in ('U1', 'U2')}, {'green-passed'})

    def test_a_missing_required_test_is_that_paths_finding_alone(self):
        self.second = 'SearchTest#missing'
        self.compiled(); f = self.f
        receipts = self.run_batch()
        result = stage_result(f.root, 'M001', 'BUILD1', receipts + self.inner.fixture.split.receipts)
        rows = {row['path_id']: row for row in result['paths']}
        self.assertEqual((rows['U1']['quality'], rows['U2']['quality']), ('green-passed', 'yellow-blocked'))
        self.assertIn('SearchTest#missing', rows['U2']['root_cause']['summary'])

    def test_a_batch_is_unit_paths_of_one_frozen_command(self):
        self.compiled()
        with self.assertRaisesRegex(Rejected, 'unit PATHs with JUnit reports'):
            self.run_batch(('U1', 'B1'))
        with self.assertRaisesRegex(Rejected, 'each once'):
            self.run_batch(('U1', 'U1'))


if __name__ == '__main__':
    unittest.main()
