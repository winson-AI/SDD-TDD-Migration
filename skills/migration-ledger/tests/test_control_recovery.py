"""Fault interleavings: active edits, partial testing, projections and lock waits."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_ledger
import test_source_changes
import test_split_testing
import test_project_context
import ledger
import openspec_projection
import run_storage
from contracts import Rejected, baseline, file_ref


class WorkingCopyTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        a, r = f.make_test_result(quality='red-bug'); f.submit(r, a)
        f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('diagnose', {'diagnosis_ref': f.ref('diag.md', 'code issue'), 'owner': 'M001',
                           'root_cause': 'code'}, role='diagnostician')
        f.call('diagnosis-accept')
        self.assignment = f.assign('fixer', 'FIX1')
        self.code = f.target / 'm1/code.py'
        self.code.write_text('value = 3\n')

    def test_poll_during_fix_and_before_accept_keeps_worker_then_accepts_new_baseline(self):
        f, a = self.f, self.assignment
        s = f.state()
        self.assertEqual(s['observed_invalidations'], [])
        self.assertEqual(s['next_steps'][0]['operation'], 'await-result')
        refs = [file_ref(self.code)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
            'assignment_id': a['assignment_id'], 'actor_instance_id': 'fixer', 'freeze_id': a['freeze_id'],
            'code_files': refs, 'code_baseline': baseline(refs),
            'task_trace': [{'task_id': 'T1', 'files': [str(self.code)]}],
            'production_binding_evidence': f.ref('binding-fix.md', 'binding verified'),
            'fix_note_ref': f.ref('fix-note.json', {'root_cause': 'wrong value', 'strategy': 'correct value',
                'applicability': 'same task', 'risks': 'regression required'})}
        f.submit(result, a)
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'accept')
        f.call('accept', {'assignment_id': 'FIX1'})
        self.assertEqual(f.state()['modules']['M001']['code_baseline'], baseline(refs))

    def test_spec_drift_still_revokes_active_fixer(self):
        f = self.f
        spec = f.state()['modules']['M001']['plan']['definitions'][0]
        Path(spec['path']).write_text('unauthorized specification edit')
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'revoke')

    def test_code_redirect_still_revokes_active_fixer(self):
        outside = self.f.base / 'outside-code'; outside.write_text('external')
        self.code.unlink(); self.code.symlink_to(outside)
        self.assertEqual(self.f.state()['next_steps'][0]['operation'], 'revoke')

    def test_stopped_fixer_with_unaccepted_patch_requires_invalidation(self):
        f = self.f
        f.call('revoke', {'assignment_id': 'FIX1', 'stopped_worker_ref': f.ref('stop.md', 'Host stopped worker')}, role='host')
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'invalidate')


class PartialTestTests(unittest.TestCase):
    def test_yellow_with_failed_assertion_cannot_become_unexecuted(self):
        t = test_split_testing.SplitTestingTests(); t.setUp(); self.addCleanup(t.doCleanups)
        t.prepare(); t.compile(); f = t.f
        a, result = f.make_test_result(quality='red-bug')
        result['paths'][0]['quality'] = 'yellow-blocked'
        result['paths'][0]['root_cause'].update(category='tooling', summary='failed assertion then connection lost')
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        before = f.state()['modules']['M001']['results']
        with self.assertRaisesRegex(Rejected, 'cannot conceal'):
            t.defer()
        after = f.state()
        self.assertEqual(after['modules']['M001']['results'], before)
        self.assertNotEqual(after['next_steps'][0]['operation'], 'automation-unavailable')
        self.assertIs(after['modules']['M001']['results']['P1']['assertions'][0]['passed'], False)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture = test_source_changes.SourceChangeTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.freeze('M001'); fixture.freeze('M002')
        self.f = fixture.f
        self.change = (self.f.base / 'openspec/changes/demo-m001').resolve()

    def request(self):
        state, _ = ledger.read_events(self.f.root)
        return {'schema_version': 1, 'request_id': 'projection-probe', 'run_id': 'demo',
                'module_id': 'M002', 'expected_revision': state['modules']['M002']['revision'],
                'operation': 'session', 'payload': {'role': 'implementer', 'session_id': 'S2'}}

    actor = {'role': 'module-orchestrator', 'instance_id': 'mo'}

    def test_attention_write_failure_persists_signal_without_changing_routing(self):
        before = self.f.state()
        journal = (self.f.root / 'ledger/events.jsonl').read_bytes()
        original = openspec_projection.write
        def fail(path, content):
            if path.name == 'workflow-attention.md': raise OSError('attention output unavailable')
            return original(path, content)
        with patch.object(openspec_projection, 'write', side_effect=fail):
            state = self.f.state()
        saved = json.loads((self.f.root / 'ledger/progress.json').read_text())
        self.assertEqual(saved, state['workflow_progress'])
        signal = next(s for s in saved['signals'] if s['reason'] == 'projection-pending')
        self.assertEqual(signal['evidence']['errors'][0]['stage'], 'workflow-attention')
        self.assertEqual(state['next_steps'], before['next_steps'])
        self.assertEqual(state['quality'], before['quality'])
        self.assertEqual((self.f.root / 'ledger/events.jsonl').read_bytes(), journal)
        recovered = self.f.state()
        self.assertEqual(recovered['projection']['status'], 'current')
        self.assertNotIn('projection-pending', [s['reason'] for s in recovered['workflow_progress']['signals']])

    def test_progress_write_failure_retries_once_with_diagnostic(self):
        original = ledger.atomic
        writes = []
        def fail_first(path, content):
            if path.name == 'progress.json':
                writes.append(path)
                if len(writes) == 1: raise OSError('temporary progress output failure')
            return original(path, content)
        with patch.object(ledger, 'atomic', side_effect=fail_first):
            state = self.f.state()
        self.assertEqual(len(writes), 2)
        saved = json.loads((self.f.root / 'ledger/progress.json').read_text())
        self.assertEqual(saved, state['workflow_progress'])
        self.assertEqual(state['projection']['errors'][0]['stage'], 'progress-state')
        self.assertTrue(saved['notify_user'])

    def test_diagnostic_writes_both_unavailable_return_bounded_failure(self):
        self.f.state()
        journal = (self.f.root / 'ledger/events.jsonl').read_bytes()
        previous = (self.f.root / 'ledger/progress.json').read_bytes()
        original_atomic, original_write = ledger.atomic, openspec_projection.write
        writes = []
        def fail_progress(path, content):
            if path.name == 'progress.json':
                writes.append(path)
                raise OSError('progress unavailable')
            return original_atomic(path, content)
        def fail_attention(path, content):
            if path.name == 'workflow-attention.md': raise OSError('attention unavailable')
            return original_write(path, content)
        with patch.object(ledger, 'atomic', side_effect=fail_progress), \
                patch.object(openspec_projection, 'write', side_effect=fail_attention):
            state = self.f.state()
        self.assertEqual(len(writes), 2)
        self.assertEqual([e['stage'] for e in state['projection']['errors']],
                         ['workflow-attention', 'progress-state', 'progress-state-retry'])
        self.assertTrue(state['workflow_progress']['notify_user'])
        self.assertEqual((self.f.root / 'ledger/progress.json').read_bytes(), previous)
        self.assertEqual((self.f.root / 'ledger/events.jsonl').read_bytes(), journal)

    def test_owned_manifest_recovered_without_blocking_peer_or_losing_original(self):
        manifest = self.change / 'manifest.json'; manifest.write_text('{damaged')
        ack = ledger.apply(self.f.root, self.request(), self.actor)
        self.assertTrue(ack['committed'])
        self.assertEqual(ack['projection']['status'], 'current')
        self.assertEqual(json.loads(manifest.read_text())['module_id'], 'M001')
        saved = list((self.f.root / 'reports/projection-recovery/M001').glob('*.manifest'))
        self.assertEqual([p.read_text() for p in saved], ['{damaged'])
        self.assertEqual(self.f.state()['modules']['M002']['sessions']['implementer']['session_id'], 'S2')

    def test_projection_io_error_returns_committed_ack_and_retry_is_idempotent(self):
        original = openspec_projection.write
        def fail_one(path, content):
            if path == self.change / 'design.md': raise OSError('fixture projection disk error')
            return original(path, content)
        req = self.request(); before = len(ledger.read_events(self.f.root)[1])
        with patch.object(openspec_projection, 'write', side_effect=fail_one):
            ack = ledger.apply(self.f.root, req, self.actor)
            self.assertTrue(ack['committed']); self.assertEqual(ack['projection']['status'], 'pending')
            retry = ledger.apply(self.f.root, req, self.actor)
            self.assertTrue(retry['duplicate']); self.assertEqual(ack['event_id'], retry['event_id'])
            state = self.f.state()
            self.assertTrue(state['workflow_progress']['notify_user'])
            self.assertEqual(state['projection']['errors'][0]['module_id'], 'M001')
            self.assertEqual(state['modules']['M002']['sessions']['implementer']['session_id'], 'S2')
            self.assertTrue((self.f.base / 'openspec/changes/demo-m002/tasks.md').is_file())
        self.assertEqual(len(ledger.read_events(self.f.root)[1]), before + 1)
        self.assertEqual(self.f.state()['projection']['status'], 'current')

    def test_foreign_manifest_not_overwritten_but_status_and_peer_remain_available(self):
        manifest = self.change / 'manifest.json'
        foreign = {'run_root': '/other-run', 'module_id': 'M999', 'files': []}
        manifest.write_text(json.dumps(foreign))
        ack = ledger.apply(self.f.root, self.request(), self.actor)
        self.assertTrue(ack['committed']); self.assertEqual(ack['projection']['status'], 'pending')
        self.assertEqual(json.loads(manifest.read_text()), foreign)
        self.assertTrue(self.f.state()['workflow_progress']['notify_user'])
        self.assertFalse((self.f.root / 'reports/projection-recovery').exists())


class LockTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_project_context.ProjectContextTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.start(f.init_payload(f.prepare()))

    def test_ledger_cli_timeout_is_structured_and_does_not_steal_lock(self):
        f = self.f; journal = (f.run / 'ledger/events.jsonl').read_bytes()
        with run_storage.file_lock(f.run / '.ledger.lock'):
            start = time.monotonic()
            result = subprocess.run([sys.executable, '-B', ledger.__file__, 'status', '--root', str(f.run)],
                capture_output=True, text=True, timeout=3, env={**os.environ, 'SDD_LOCK_TIMEOUT_SECONDS': '0.1'})
            self.assertLess(time.monotonic() - start, 3)
            self.assertEqual(result.returncode, 1)
            diagnostic = json.loads(result.stderr)
            self.assertEqual(diagnostic['status'], 'lock-timeout')
            self.assertEqual(diagnostic['lock_path'], str(f.run / '.ledger.lock'))
            with self.assertRaises(run_storage.LockTimeout):
                with run_storage.file_lock(f.run / '.ledger.lock', timeout=0.05): pass
        self.assertEqual((f.run / 'ledger/events.jsonl').read_bytes(), journal)
        self.assertEqual(ledger.status(f.run)['run_id'], 'r1')

    def test_apply_does_not_reacquire_timed_out_lock_for_diagnostics(self):
        f = self.f
        with run_storage.file_lock(f.run / '.ledger.lock'), patch.dict(os.environ, SDD_LOCK_TIMEOUT_SECONDS='0.05'):
            with patch('progress_signals.record_rejection') as diagnostic:
                with self.assertRaises(run_storage.LockTimeout): ledger.apply(f.run, {}, f.actor)
                diagnostic.assert_not_called()

    def test_project_and_harmony_preparation_use_bounded_locks(self):
        f = self.f
        with patch.dict(os.environ, SDD_LOCK_TIMEOUT_SECONDS='0.05'):
            with run_storage.file_lock(f.root / '.context.lock'):
                with self.assertRaises(run_storage.LockTimeout): f.prepare()
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
            from harmony_environment import prepare_environment
            directory = f.run / 'runs/harmony/sandbox/environment'; directory.mkdir(parents=True)
            with run_storage.file_lock(directory / '.prepare.lock'):
                with self.assertRaises(run_storage.LockTimeout): prepare_environment(f.run)
            self.assertFalse((directory / 'config.json').exists())

    def test_invalid_timeout_is_rejected(self):
        for value in ('0', '-1', 'nan', 'inf', 'invalid'):
            with self.subTest(value=value), patch.dict(os.environ, SDD_LOCK_TIMEOUT_SECONDS=value):
                with self.assertRaises(ValueError):
                    with run_storage.file_lock(self.f.run / '.ledger.lock'): pass
