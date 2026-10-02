"""Queries read committed archives and never refresh projections or acquire workflow locks."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_unit_reports
import test_ledger
import ledger
# Explicit module file avoids Python's unrelated standard-library trace module cache.
import importlib.util
spec = importlib.util.spec_from_file_location('migration_trace', Path(__file__).resolve().parents[1] / 'scripts/trace.py')
trace = importlib.util.module_from_spec(spec); spec.loader.exec_module(trace)
from contracts import Rejected, digest, read_json


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_unit_reports.UnitReportTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f
        self.f.root = self.f.root.resolve()
        old = self.f.plan
        def plan():
            p = old()
            p['scenario_trace'] = [{'scenario_id': 'SCN-query', 'task_ids': ['T1'],
                                    'assertions': [{'path_id': 'U1', 'assertion_id': 'UNIT-EXIT'}]}]
            return p
        self.f.plan = plan

    def inventory(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.f.root.rglob('*') if p.is_file()}

    def test_scenario_path_assertion_and_test_selection_uses_current_committed_evidence(self):
        receipt_ref, _, _ = self.fixture.run_unit()
        before = self.inventory()
        with patch('run_storage.file_lock', side_effect=AssertionError('query must not take workflow lock')):
            answer = trace.query(self.f.root, 'M001', scenario_id='SCN-query', assertion_id='UNIT-EXIT', test_id='SearchTest#query')
        self.assertEqual(self.inventory(), before)
        self.assertEqual(answer['total'], 1); row = answer['rows'][0]
        self.assertEqual(row['quality'], 'green-passed'); self.assertNotIn('log_excerpt', row)
        self.assertEqual(row['evidence_refs']['receipt'], receipt_ref)
        self.assertEqual(row['unit']['selected_test'], [{'test_id': 'SearchTest#query', 'status': 'passed'}])
        self.assertEqual(row['acceptance_event']['operation'], 'accept')
        self.assertEqual(trace.query(self.f.root, 'M001', scenario_id='wrong')['total'], 0)
        self.assertEqual(trace.query(self.f.root, 'M001', test_id='Wrong#test')['total'], 0)

    def test_failed_log_excerpt_and_explicit_pages_read_archive_even_if_live_file_changed(self):
        self.fixture.code = 1
        receipt_ref, _, _ = self.fixture.run_unit()
        receipt = read_json(receipt_ref['path'])
        log = receipt['log_ref']; Path(log['path']).write_text('tampered live log')
        before = self.inventory()
        answer = trace.query(self.f.root, 'M001', path_id='U1', excerpt_bytes=32)
        row = answer['rows'][0]
        self.assertEqual(row['quality'], 'red-bug'); self.assertEqual(row['evidence_issues'], [])
        self.assertNotIn('tampered', row['log_excerpt']['text'])
        page = trace.evidence_page(self.f.root, receipt['query_ref']['sha256'], size=13)
        self.assertEqual(page['excerpt']['bytes'], 13); self.assertEqual(page['excerpt']['next_offset'], 13)
        page2 = trace.evidence_page(self.f.root, receipt['query_ref']['sha256'], offset=13, size=11)
        self.assertEqual(page2['excerpt']['offset'], 13)
        self.assertEqual(self.inventory(), before)
        archive = self.f.root / 'artifacts' / log['sha256']; archive.write_text('corrupt archive')
        self.assertTrue(trace.query(self.f.root, 'M001', path_id='U1')['rows'][0]['evidence_issues'])
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): trace.evidence_page(self.f.root, log['sha256'])

    def test_pagination_limits_and_no_auto_loading_of_unexecuted_or_uncommitted_paths(self):
        self.fixture.run_unit(accept=False)
        answer = trace.query(self.f.root, 'M001', limit=1)
        self.assertEqual(answer['total'], 3); self.assertEqual(len(answer['rows']), 1)
        self.assertEqual(answer['next_offset'], 1)
        unit = trace.query(self.f.root, 'M001', path_id='U1')['rows'][0]
        self.assertEqual(unit['quality'], 'not-executed'); self.assertEqual(unit['evidence_refs'], {})
        self.assertLess(len(json.dumps(answer).encode()), 60000)
        for kwargs in ({'limit': 0}, {'offset': -1}, {'excerpt_bytes': 5000}):
            with self.assertRaises(Rejected): trace.query(self.f.root, 'M001', **kwargs)
        with self.assertRaises(Rejected): trace.query(self.f.root, 'M999')
        with self.assertRaises(Rejected): trace.evidence_page(self.f.root, 'not-a-committed-hash')

    def test_read_events_does_not_rewrite_first_event_during_replay(self):
        self.fixture.run_unit()
        _, events = ledger.read_events(self.f.root)
        for event in events:
            self.assertEqual(event['sha256'], digest({k: v for k, v in event.items() if k != 'sha256'}))

    def test_global_audit_has_its_own_committed_trace(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root = f.root.resolve()
        f.test_green_flow_and_independent_global_audit()
        result = trace.query(f.root, 'GLOBAL', path_id='GP1')
        row = result['rows'][0]
        self.assertEqual(row['quality'], 'green-passed')
        self.assertEqual(row['acceptance_event']['operation'], 'audit')
        self.assertEqual(trace.query(f.root, 'M001', path_id='GP1')['total'], 0)
        self.assertFalse(result['current_code_revalidated'])

    def test_live_is_explicitly_unaccepted_and_confined_to_selected_run(self):
        from execution_capture import Capture
        out = self.f.root / 'runs/build/live'; out.mkdir(parents=True)
        capture = Capture(out, {'run_id': 'demo', 'module_id': 'M001', 'test_run_id': 'live1'})
        capture.files['stderr.log'].write(b'partial failure'); capture.close()
        before = self.inventory()
        result = trace.live(self.f.root, 'M001', out, stream='stderr', size=7)
        self.assertIs(result['accepted'], False); self.assertEqual(result['excerpt']['text'], 'partial')
        self.assertEqual(self.inventory(), before)
        with self.assertRaisesRegex(Rejected, 'identity'):
            trace.live(self.f.root, 'M002', out)

    def test_historical_result_survives_invalidation_and_is_not_current_green(self):
        self.fixture.run_unit()
        if not self.f.state()['modules']['M001']['assignments']['BUILD1']['closed']:
            self.f.call('revoke', {'assignment_id': 'BUILD1', 'stopped_worker_ref': self.f.ref('stop.md', 'worker ended')}, role='host')
        self.f.call('invalidate', {'reason': 'new plan needed'})
        self.assertEqual(trace.query(self.f.root, 'M001')['rows'], [])
        rows = trace.query(self.f.root, 'M001', history=True, path_id='U1')['rows']
        self.assertEqual(len(rows), 1); self.assertTrue(rows[0]['history'])
        self.assertEqual(rows[0]['quality'], 'green-passed'); self.assertEqual(rows[0]['phase'], 'specifying')
