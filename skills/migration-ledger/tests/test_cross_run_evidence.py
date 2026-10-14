"""Imported lessons keep committed reports without demanding historical live tools."""
import json
from pathlib import Path
import unittest

import test_project_context
import ledger
import project_context
import context_readiness
from contracts import Rejected, file_ref
from verify_openspec import AcceptanceEvidence


class CrossRunEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        payload = self.f.init_payload(self.f.prepare())
        self.tool = self.f.base / 'controller.py'
        self.tool.write_text('old controller')
        self.report = self.f.run / 'staging/host/report.json'
        self.report.parent.mkdir(parents=True)
        self.report.write_text(json.dumps({'tool_ref': file_ref(self.tool), 'finding': 'old observed behavior'}))
        self.report_ref = file_ref(self.report)
        payload['global_spec'] = self.report_ref
        self.ack = self.f.start(payload)
        self.tool.write_text('new controller')
        self.current = self.f.base / '.sdd-runs/r2'
        self.current.mkdir()
        self.wrapper = self.current / 'lesson.json'
        self.wrapper.write_text(json.dumps({'evidence_refs': [self.report_ref]}))

    def test_new_init_and_acceptance_reader_use_committed_report_boundary(self):
        prepared = project_context.prepare(self.f.root, self.current, self.f.run_request('r2'), self.f.actor)
        payload = self.f.init_payload(prepared)
        # The actual experience index is a JSON reference in prepared inputs.
        payload['global_spec'] = file_ref(self.wrapper)
        ack = ledger.apply(self.current, {
            'schema_version': 1, 'request_id': 'init-r2', 'run_id': 'r2',
            'module_id': None, 'expected_revision': 0, 'operation': 'init', 'payload': payload}, self.f.actor)
        self.assertTrue(ack['committed'])
        events = ledger.read_events(self.current)[1]
        rows = events[-1]['artifact_snapshots']
        imported = next(row for row in rows if row['source_path'] == str(self.report))
        self.assertEqual(imported['status'], 'accepted-prior-run-artifact')
        self.assertEqual(imported['accepted_run_id'], 'r1')
        self.assertEqual(imported['accepted_event']['event_id'], self.ack['event_id'])
        self.assertNotIn(str(self.tool), [row['source_path'] for row in rows])
        reader = AcceptanceEvidence(self.current, events, self.f.target)
        reader.visit(payload)
        self.assertEqual(json.loads(reader.check(self.report_ref).read_text())['finding'], 'old observed behavior')
        self.assertEqual(self.tool.read_text(), 'new controller')
        state = ledger.read_events(self.current)[0]
        context_readiness.verify_inputs(state, None, 'global-discovery', deep=True,
                                        refs=[file_ref(self.wrapper)], run_root=self.current)
        with self.assertRaises(Rejected):
            context_readiness.verify_inputs(state, None, 'global-discovery', deep=True,
                                            refs=[file_ref(self.wrapper)])
        with self.assertRaisesRegex(Rejected, 'archive context run mismatch'):
            context_readiness.verify_inputs({**state, 'run_id': 'wrong'}, None, 'global-discovery', deep=True,
                                            refs=[file_ref(self.wrapper)], run_root=self.current)

    def test_corrupt_or_missing_promised_archive_rejects(self):
        archive = self.f.run / 'artifacts' / self.report_ref['sha256']
        archive.write_text('corrupt')
        with self.assertRaises(Rejected):
            ledger.preserve_refs(self.current, file_ref(self.wrapper))
        archive.unlink()
        with self.assertRaises(Rejected):
            ledger.preserve_refs(self.current, file_ref(self.wrapper))

    def test_direct_inputs_and_uncommitted_reports_remain_strict(self):
        self.report.write_text('{}')
        with self.assertRaises(Rejected):
            ledger.preserve_refs(self.current, self.report_ref)
        uncommitted = self.report.with_name('uncommitted.json')
        uncommitted.write_text(json.dumps({'tool_ref': {'path': str(self.tool), 'sha256': 'a' * 64}}))
        self.wrapper.write_text(json.dumps({'evidence_refs': [file_ref(uncommitted)]}))
        with self.assertRaises(Rejected):
            ledger.preserve_refs(self.current, file_ref(self.wrapper))


if __name__ == '__main__':
    unittest.main()
