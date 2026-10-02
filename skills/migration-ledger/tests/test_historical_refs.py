"""Only committed nested historical bytes may bridge live hash drift."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_ledger
import ledger
from contracts import Rejected, check_ref, digest
from verify_openspec import AcceptanceEvidence


class HistoricalRefsTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.root = self.f.root.resolve()
        tools = self.f.base / 'tools'
        self.patch = patch.object(ledger, 'HISTORICAL_TOOL_ROOTS', (tools.resolve(),)); self.patch.start()
        self.addCleanup(self.patch.stop)
        self.child = self.f.ref('tools/old-controller.py', 'old controller bytes')
        self.parent = self.f.ref('tools/old-protocol.json', {'child_ref': self.child})
        self.f.call('decision', {'decision_id': 'OLD', 'module_id': 'M001', 'subject_sha256': digest('old'),
                                     'decision': 'approved', 'human_source_ref': self.parent}, role='host', module=None)
        self.events = ledger.read_events(self.f.root)[1]
        self.index = ledger.artifact_index(self.events)
        Path(self.child['path']).write_text('new controller bytes')

    def preserve(self, value):
        return ledger.preserve_refs(self.f.root, value, accepted=self.index)

    def test_nested_archive_and_event_proof_survive_without_overwriting_history(self):
        before = [e['sha256'] for e in self.events]
        self.f.call('decision', {'decision_id': 'NEW', 'module_id': 'M001', 'subject_sha256': digest('new'),
                                     'decision': 'approved', 'human_source_ref': self.parent}, role='host', module=None)
        _, events = ledger.read_events(self.f.root)
        self.assertEqual(before, [e['sha256'] for e in events[:-1]])
        row = next(x for x in events[-1]['artifact_snapshots'] if x['source_path'] == self.child['path'])
        self.assertEqual(row['status'], 'historical-snapshot')
        self.assertEqual(row['accepted_event']['event_id'], self.events[-1]['event_id'])
        self.assertEqual(check_ref(row).read_text(), 'old controller bytes')
        self.assertEqual(Path(self.child['path']).read_text(), 'new controller bytes')
        reader = AcceptanceEvidence(self.f.root, events, self.f.target)
        reader.visit(self.parent)
        self.assertEqual(reader.check(self.child).read_text(), 'old controller bytes')

    def test_changed_nested_json_recurses_using_original_suffix(self):
        Path(self.parent['path']).write_text('{}')
        wrapper = self.f.ref('wrapper.json', {'historical_context_ref': self.parent})
        rows = self.preserve(wrapper)
        self.assertEqual({r['source_path'] for r in rows}, {wrapper['path'], self.parent['path'], self.child['path']})
        self.assertEqual(sum(r.get('status') == 'historical-snapshot' for r in rows), 2)

    def test_direct_live_inputs_and_check_ref_remain_strict(self):
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): self.preserve(self.child)
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): check_ref(self.child)
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.preserve({'direct_input': self.child})

    def test_uncommitted_or_foreign_archive_is_not_proof(self):
        wrapper = self.f.ref('wrapper.json', {'old': self.child})
        with self.assertRaises(Rejected): ledger.preserve_refs(self.f.root, wrapper, accepted={})
        unknown = self.f.ref('tools/uncommitted.txt', 'uncommitted')
        blob = self.f.root / 'artifacts' / unknown['sha256']; blob.write_text('uncommitted')
        Path(unknown['path']).write_text('changed')
        with self.assertRaises(Rejected): self.preserve(self.f.ref('unknown.json', {'old': unknown}))

    def test_nested_business_spec_source_environment_still_need_live_bytes(self):
        for name in ('legacy/entry.kt', 'spec.md', 'environment.json'):
            ref = self.f.ref(name, 'original')
            self.f.call('decision', {'decision_id': name, 'module_id': 'M001', 'subject_sha256': digest(name),
                                    'decision': 'approved', 'human_source_ref': ref}, role='host', module=None)
            self.index = ledger.artifact_index(ledger.read_events(self.f.root)[1])
            Path(ref['path']).write_text('changed')
            with self.assertRaises(Rejected): self.preserve(self.f.ref('wrapper.json', {'old': ref}))

    def test_corrupt_missing_and_redirected_archive_reject(self):
        wrapper = self.f.ref('wrapper.json', {'old': self.child})
        blob = self.f.root / 'artifacts' / self.child['sha256']
        saved = blob.read_bytes(); blob.write_text('corrupt')
        with self.assertRaises(Rejected): self.preserve(wrapper)
        blob.unlink()
        with self.assertRaises(Rejected): self.preserve(wrapper)
        foreign = self.f.base / 'foreign'; foreign.write_bytes(saved); blob.symlink_to(foreign)
        with self.assertRaises(Rejected): self.preserve(wrapper)
        blob.unlink(); blob.write_bytes(saved)
        bad = copy.deepcopy(self.index); bad[(self.child['path'], self.child['sha256'])][0]['path'] = str(foreign)
        with self.assertRaisesRegex(Rejected, 'location'):
            ledger.preserve_refs(self.f.root, wrapper, accepted=bad)

    def test_target_drift_without_archived_bytes_keeps_existing_record(self):
        ref = self.f.ref('target/new.py', 'before')
        Path(ref['path']).write_text('after')
        wrapper = self.f.ref('wrapper.json', {'old': ref})
        rows = ledger.preserve_refs(self.f.root, wrapper, target_root=self.f.target, accepted=self.index)
        self.assertEqual(rows[-1]['status'], 'drifted-or-missing-live-target-code')
