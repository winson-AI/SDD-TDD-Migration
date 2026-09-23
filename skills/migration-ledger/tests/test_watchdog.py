"""Observer isolation, real process identity, host exports and recovery cursors."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import ledger
import project_context as pc
import run_storage
import test_ledger
import test_project_context
import test_source_changes
import watchdog
from contracts import Rejected


class SignalFixTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_parallel_rejections_keep_independent_counts_and_history(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.prepare(); before = (f.root / 'ledger/events.jsonl').read_bytes()
        for _ in range(3):
            for mid in ('M001', 'M002'):
                with self.assertRaises(Rejected): f.call('complete', {'checks_passed': True}, module=mid)
        signals = [x for x in f.state()['workflow_progress']['signals'] if x['reason'] == 'operation-rejected']
        self.assertEqual({x['module_id']: x['evidence']['rejection']['attempts'] for x in signals}, {'M001': 3, 'M002': 3})
        self.assertTrue(all(x['severity'] == 'human' for x in signals))
        self.assertEqual((f.root / 'ledger/events.jsonl').read_bytes(), before)
        files = list((f.root / 'reports/rejections').glob('*.json')); self.assertEqual(len(files), 2)
        f.implementation()
        signals = [x for x in f.state()['workflow_progress']['signals'] if x['reason'] == 'operation-rejected']
        self.assertEqual([x['module_id'] for x in signals], ['M002'])
        self.assertTrue(all(p.exists() for p in files))

    def test_stale_audit_requires_host_revoke_before_invalidate(self):
        f = self.f; f.prepare(); f.implementation()
        a, r = f.make_test_result(); f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('complete', {'dod_ref': f.ref('dod.md', 'Reviewed'), 'checks_passed': True}); test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'AUD', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        (f.target / 'm1/code.py').write_text('value=99\n')
        s = f.state(); step = s['global_next_step']
        self.assertEqual((step['operation'], step['ready']), ('audit-revoke', True))
        self.assertFalse(s['next_steps'][0]['ready']); self.assertTrue(s['workflow_progress']['notify_user'])
        with self.assertRaises(Rejected): f.call('invalidate', {'reason': 'drift'})
        with self.assertRaises(Rejected): f.call('audit-revoke', {'assignment_id': 'AUD'}, role='host', module=None)
        f.call('audit-revoke', {'assignment_id': 'AUD', 'stopped_worker_ref': f.ref('stop.md', 'Host confirmed stopped')}, role='host', module=None)
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'invalidate')
        f.call('invalidate', {'reason': 'drift'}); self.assertEqual(f.state()['modules']['M001']['phase'], 'specifying')


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_project_context.ProjectContextTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.start(f.init_payload(f.prepare())); ledger.status(f.run)
        self.root, self.config = watchdog.bound_root(f.run)

    def host_state(self, host, workers=None):
        path = self.root / 'runs/watchdog/host-state.json'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'run_id': self.root.name, 'host': host, 'workers': workers or []}))
        return path

    def export(self, **changes):
        return {'source': 'host-api', 'provider': 'fixture-host', 'execution_id': 'host-execution-1',
                'instance_id': 'host-1', 'status': 'running', 'observed_at': watchdog.now(),
                'heartbeat_at': watchdog.now(), **changes}

    def inventory(self):
        return {str(p.relative_to(self.f.base)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.f.base.rglob('*') if p.is_file() and
                '/runs/watchdog/' not in str(p) and '/reports/watchdog/' not in str(p)}

    def acknowledge(self, result):
        watchdog.acknowledge(self.root, [n['notice_id'] for n in result['pending_notices']])

    def test_check_is_read_only_for_all_business_assets_and_unknown_without_interface(self):
        before = self.inventory()
        result = watchdog.check(self.root, self.config)
        self.assertEqual(result['host']['status'], 'unknown')
        self.assertEqual(result['mode'], 'observe-only'); self.assertTrue(result['notify_user'])
        self.assertEqual(self.inventory(), before)
        replay = watchdog.check(self.root, self.config)
        self.assertEqual(replay['pending_notices'], result['pending_notices'])
        self.acknowledge(replay)
        second = watchdog.check(self.root, self.config)
        self.assertFalse(second['notify_user'])
        self.assertEqual(self.inventory(), before)

    def test_real_local_process_probe_and_pid_identity(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            start = subprocess.check_output(['/bin/ps', '-p', str(process.pid), '-o', 'lstart='], text=True).strip()
            entry = {'source': 'local-process', 'pid': process.pid, 'process_start': start, 'observed_at': watchdog.now()}
            self.assertEqual(watchdog.liveness(entry, watchdog.now(), 180)['status'], 'running')
            self.assertEqual(watchdog.liveness({**entry, 'process_start': 'different generation'}, watchdog.now(), 180)['status'], 'unknown')
            process.terminate(); process.wait(timeout=5)
            self.assertEqual(watchdog.liveness(entry, watchdog.now(), 180)['status'], 'exited')
        finally:
            if process.poll() is None: process.kill(); process.wait()

    def test_host_api_freshness_pause_and_notifications(self):
        watchdog.check(self.root, self.config)
        self.host_state(self.export())
        result = watchdog.check(self.root, self.config)
        self.assertEqual(result['host']['status'], 'running')
        self.assertTrue(any(x['kind'] == 'closed' and x['finding']['code'] == 'host-unknown' for x in result['notifications']))
        self.host_state(self.export(), workers=[self.export(execution_id='GO1', expected_active=True,
            last_progress_at=(datetime.now(timezone.utc) - timedelta(seconds=901)).isoformat())])
        result = watchdog.check(self.root, self.config)
        self.assertNotIn('no-runnable-action-and-no-worker', [x['code'] for x in result['findings']])
        self.assertTrue(any(x['code'] == 'worker-progress-overdue' and x['scope'] == 'GLOBAL/GO1' for x in result['findings']))
        old = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
        self.host_state(self.export(observed_at=old))
        self.assertEqual(watchdog.check(self.root, self.config)['host']['status'], 'unknown')
        self.host_state(self.export(control='paused'))
        paused = watchdog.check(self.root, self.config)
        self.assertEqual(paused['state'], 'paused'); self.assertFalse(paused['findings'])

    def test_watchdog_does_not_wait_for_ledger_lock(self):
        script = Path(watchdog.__file__)
        with run_storage.file_lock(self.root / '.ledger.lock'):
            result = subprocess.run([sys.executable, '-B', str(script), 'check', '--root', str(self.root)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['mode'], 'observe-only')

    def test_observer_singleton_does_not_lock_workflow(self):
        folder = self.root / 'runs/watchdog'; folder.mkdir(parents=True)
        with run_storage.file_lock(folder / '.watchdog.lock'):
            result = subprocess.run([sys.executable, '-B', watchdog.__file__, 'check', '--root', str(self.root)], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('lock acquisition timed out', result.stderr)
            self.assertEqual(ledger.status(self.root)['run_id'], 'r1')

    def test_timeout_and_corrupt_journal_only_affect_observer(self):
        first = watchdog.check(self.root, self.config)
        before = self.inventory()
        with patch.object(watchdog.subprocess, 'run', side_effect=subprocess.TimeoutExpired('observer', 10)):
            result = watchdog.check(self.root, self.config)
        self.assertEqual(result['state'], 'observation-unavailable')
        self.assertFalse(any(x['kind'] == 'closed' for x in result['notifications']))
        self.assertEqual(self.inventory(), before)
        journal = self.root / 'ledger/events.jsonl'; journal.write_bytes(journal.read_bytes() + b'{')
        damaged = self.inventory(); result = watchdog.check(self.root, self.config)
        self.assertEqual(result['state'], 'observation-unavailable'); self.assertEqual(self.inventory(), damaged)

    def test_configuration_is_frozen_and_cannot_enable_actions(self):
        f = self.f
        pc.update(f.root, f.request('monitor', 1, {'watchdog': {'interval_seconds': 30}}), f.actor)
        second = pc.prepare(f.root, None, f.run_request('r2'), f.actor)
        self.assertEqual(watchdog.bound_root(second['run_root'])[1]['interval_seconds'], 30)
        self.assertEqual(watchdog.bound_root(self.root)[1]['interval_seconds'], 60)
        with self.assertRaises(Rejected): watchdog.policy({'mode': 'auto-recover'})
        with self.assertRaises(Rejected): watchdog.policy({'check_timeout_seconds': 0})

    def test_output_symlink_cannot_write_outside_run(self):
        external = self.f.base / 'external'; external.mkdir()
        (self.root / 'reports/watchdog').symlink_to(external, target_is_directory=True)
        with self.assertRaises(Rejected): watchdog.check(self.root, self.config)
        self.assertFalse(list(external.iterdir()))

    def test_disabled_and_direct_api_invalid_root_create_no_monitor_assets(self):
        f = self.f
        with self.assertRaises(Rejected): watchdog.check(f.base / 'external-run', self.config)
        self.assertFalse((f.base / 'external-run').exists())
        pc.update(f.root, f.request('disable-monitor', 1, {'watchdog': {'enabled': False}}), f.actor)
        second = pc.prepare(f.root, None, f.run_request('r2'), f.actor)
        root, config = watchdog.bound_root(second['run_root'])
        self.assertEqual(watchdog.check(root, config)['state'], 'disabled')
        self.assertFalse((root / 'runs/watchdog').exists())

    def test_persistent_ready_action_only_generates_deduplicated_notification(self):
        observation = watchdog.inspect(self.root)
        observation.update(workers=[], ready_actions=[{'module_id': 'M001', 'operation': 'plan', 'role': 'spec-designer'}])
        start = datetime.now(timezone.utc)
        before = self.inventory()
        def tick(seconds):
            observation['observed_at'] = (start + timedelta(seconds=seconds)).isoformat()
            completed = subprocess.CompletedProcess([], 0, json.dumps(observation), '')
            with patch.object(watchdog.subprocess, 'run', return_value=completed):
                return watchdog.check(self.root, self.config)
        self.acknowledge(tick(0)); later = tick(181)
        self.assertIn('ready-actions-await-host-review', [f['code'] for f in later['findings']])
        self.acknowledge(later)
        self.assertFalse(tick(182)['notify_user'])
        self.assertEqual(self.inventory(), before)

    def test_watch_ends_on_explicit_host_stop_without_touching_workflow(self):
        self.host_state(self.export(control='stopped'))
        before = self.inventory()
        result = subprocess.run([sys.executable, '-B', watchdog.__file__, 'watch', '--root', str(self.root)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.inventory(), before)

    def test_completed_run_keeps_projection_notice_until_host_rebuilds(self):
        import openspec_projection
        from simulate_storage import simulate
        summary = simulate(self.f.base / 'completed-fixture')
        root = Path(summary['workspace']) / '.sdd-runs/demo'
        root, config = watchdog.bound_root(root)
        journal = (root / 'ledger/events.jsonl').read_bytes()
        original = openspec_projection.write
        def fail_report(path, content):
            if path.name == 'migration-report.md': raise OSError('report unavailable')
            return original(path, content)
        with patch.object(openspec_projection, 'write', side_effect=fail_report):
            state = ledger.status(root)
        self.assertEqual(state['quality'], 'green-passed')
        before = self.inventory()
        result = watchdog.check(root, config)
        self.assertEqual(result['state'], 'completed-with-pending-diagnostics')
        self.assertEqual([f['code'] for f in result['findings']], ['projection-pending'])
        self.assertTrue(result['notify_user'])
        self.assertEqual(self.inventory(), before)
        watchdog.acknowledge(root, [n['notice_id'] for n in result['pending_notices']])
        pending = watchdog.check(root, config)
        self.assertEqual(pending['state'], 'completed-with-pending-diagnostics')
        self.assertFalse(pending['notify_user'])  # Delivery is not repair.
        ledger.status(root)  # Only the normal Host path rebuilds business views.
        before = self.inventory()
        recovered = watchdog.check(root, config)
        self.assertEqual(recovered['state'], 'completed')
        self.assertEqual([n['kind'] for n in recovered['notifications']], ['closed'])
        self.assertEqual(self.inventory(), before)
        self.assertEqual((root / 'ledger/events.jsonl').read_bytes(), journal)

    def test_unverified_terminal_projection_failure_and_explicit_stop(self):
        # Observer input fixture: Yellow completion is terminal but diagnostics are not.
        path = self.root / 'ledger/progress.json'
        progress = json.loads(path.read_text())
        progress.update(state='completed-with-unverified-tests', runnable_actions=[], signals=[
            {'reason': 'projection-pending', 'severity': 'human', 'module_id': None,
             'evidence': {'errors': [{'stage': 'workflow-attention', 'reason': 'fixture failure'}]}}])
        path.write_text(json.dumps(progress))
        before = self.inventory()
        observed = watchdog.inspect(self.root)
        self.assertEqual(observed['state'], 'completed-with-pending-diagnostics')
        self.assertEqual([f['code'] for f in observed['findings']], ['projection-pending'])
        self.assertEqual(self.inventory(), before)
        self.host_state(self.export(control='stopped'))
        stopped = watchdog.inspect(self.root)
        self.assertEqual(stopped['state'], 'stopped')
        self.assertFalse(stopped['findings'])

    def test_watch_continues_after_delivery_until_diagnostics_resolved(self):
        results = [{'state': 'completed-with-pending-diagnostics', 'notify_user': False},
                   {'state': 'completed', 'notify_user': True, 'notifications': [{'kind': 'closed'}]}]
        before = self.inventory()
        with patch.object(sys, 'argv', ['watchdog.py', 'watch', '--root', str(self.root)]), \
                patch.object(watchdog, 'check', side_effect=results) as check, \
                patch.object(watchdog.time, 'sleep') as sleep, patch('builtins.print'):
            self.assertEqual(watchdog.main(), 0)
        self.assertEqual(check.call_count, 2)
        sleep.assert_called_once_with(self.config['interval_seconds'])
        self.assertEqual(self.inventory(), before)

    def test_assignment_requires_matching_host_identity_and_no_control_actions(self):
        fixture = test_source_changes.SourceChangeTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.freeze('M001'); f = fixture.f; f.assign('implementer', 'I1')
        root, config = watchdog.bound_root(f.root)
        entry = {'source': 'host-api', 'provider': 'fixture', 'execution_id': 'E1', 'instance_id': 'implementer',
                 'module_id': 'M001', 'assignment_id': 'I1', 'status': 'exited', 'observed_at': watchdog.now()}
        path = root / 'runs/watchdog/host-state.json'; path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'run_id': root.name, 'host': self.export(), 'workers': [entry]}))
        journal = (root / 'ledger/events.jsonl').read_bytes()
        result = watchdog.check(root, config)
        self.assertIn('worker-exited', [x['code'] for x in result['findings']])
        self.assertEqual((root / 'ledger/events.jsonl').read_bytes(), journal)
        self.assertFalse(ledger.read_events(root)[0]['modules']['M001']['assignments']['I1']['closed'])
        entry['instance_id'] = 'other-worker'
        path.write_text(json.dumps({'run_id': root.name, 'host': self.export(), 'workers': [entry]}))
        self.assertEqual(watchdog.check(root, config)['workers'][0]['status'], 'unknown')

    def test_notice_replays_after_latest_write_failure(self):
        original = run_storage.atomic_bytes
        def write(path, content):
            if path.name == 'latest.json': raise OSError('injected latest failure')
            return original(path, content)
        before = self.inventory()
        with patch.object(run_storage, 'atomic_bytes', side_effect=write), self.assertRaises(OSError):
            watchdog.check(self.root, self.config)
        result = watchdog.check(self.root, self.config)
        self.assertTrue(result['notify_user'])
        self.assertEqual(len(result['pending_notices']), 1)
        self.assertEqual(len(list((self.root / 'reports/watchdog').glob('notice-*.json'))), 1)
        self.acknowledge(result)
        self.assertFalse(watchdog.check(self.root, self.config)['notify_user'])
        self.assertEqual(self.inventory(), before)

    def test_notice_recovers_state_write_failure_without_duplicate_transition(self):
        original = run_storage.atomic_bytes
        def write(path, content):
            if path.name == 'state.json': raise OSError('injected state failure')
            return original(path, content)
        with patch.object(run_storage, 'atomic_bytes', side_effect=write), self.assertRaises(OSError):
            watchdog.check(self.root, self.config)
        result = watchdog.check(self.root, self.config)
        self.assertEqual(len(result['pending_notices']), 1)
        self.assertEqual(len(list((self.root / 'reports/watchdog').glob('notice-*.json'))), 1)

    def test_stdout_failure_does_not_acknowledge_and_restart_replays(self):
        def broken_stdout(*args, **kwargs):
            if kwargs.get('file') is not sys.stderr: raise BrokenPipeError('Host disconnected')
        before = self.inventory()
        with patch.object(sys, 'argv', ['watchdog.py', 'check', '--root', str(self.root)]), \
                patch('builtins.print', side_effect=broken_stdout):
            self.assertEqual(watchdog.main(), 1)
        result = watchdog.check(self.root, self.config)
        self.assertTrue(result['notify_user'])
        self.assertEqual(len(result['pending_notices']), 1)
        self.acknowledge(result)
        self.assertFalse(watchdog.check(self.root, self.config)['notify_user'])
        self.assertEqual(self.inventory(), before)

    def test_legacy_notice_is_replayed_and_acknowledged_without_new_transition(self):
        first = watchdog.check(self.root, self.config)
        path = self.root / 'reports/watchdog' / (first['pending_notices'][0]['notice_id'] + '.json')
        event = json.loads(path.read_text())
        path.write_text(json.dumps({k: event[k] for k in ('observed_at', 'notifications')}))
        result = watchdog.check(self.root, self.config)
        self.assertEqual(len(result['pending_notices']), 1)
        self.acknowledge(result)
        self.assertFalse(watchdog.check(self.root, self.config)['notify_user'])

    def test_ack_cli_works_while_watch_and_business_locks_are_held(self):
        result = watchdog.check(self.root, self.config); before = self.inventory()
        notice_id = result['pending_notices'][0]['notice_id']
        with run_storage.file_lock(self.root / 'runs/watchdog/.watchdog.lock'), run_storage.file_lock(self.root / '.ledger.lock'):
            for _ in range(2):
                ack = subprocess.run([sys.executable, '-B', watchdog.__file__, 'ack', '--root', str(self.root),
                    '--notice-id', notice_id], capture_output=True, text=True, timeout=5)
                self.assertEqual(ack.returncode, 0, ack.stderr)
                self.assertEqual(json.loads(ack.stdout)['workflow_action'], 'none')
        self.assertFalse(watchdog.check(self.root, self.config)['notify_user'])
        self.assertEqual(self.inventory(), before)

    def test_close_and_reopen_get_distinct_notices_and_keep_unacknowledged_history(self):
        opened = watchdog.check(self.root, self.config); self.acknowledge(opened)
        self.host_state(self.export(control='paused'))
        closed = watchdog.check(self.root, self.config)
        self.assertTrue(all(n['kind'] == 'closed' for n in closed['notifications']))
        (self.root / 'runs/watchdog/host-state.json').unlink()
        reopened = watchdog.check(self.root, self.config)
        self.assertEqual(len(reopened['pending_notices']), 2)
        ids = [n['notice_id'] for n in reopened['pending_notices']]
        self.assertNotEqual(ids[0], ids[1])
        self.assertNotIn(opened['pending_notices'][0]['notice_id'], ids)
        self.acknowledge(reopened)
        self.assertFalse(watchdog.check(self.root, self.config)['notify_user'])

    def test_ack_rejects_unknown_notice_and_redirected_destination(self):
        result = watchdog.check(self.root, self.config)
        with self.assertRaises(Rejected): watchdog.acknowledge(self.root, ['../foreign'])
        external = self.f.base / 'external'; external.mkdir()
        (self.root / 'runs/watchdog/acknowledged').symlink_to(external, target_is_directory=True)
        with self.assertRaises(Rejected): self.acknowledge(result)
        self.assertFalse(list(external.iterdir()))
