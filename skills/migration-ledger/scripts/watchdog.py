#!/usr/bin/env python3
"""Observe only. No dispatch, Ledger mutation, recovery execution or business locks."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
import time

from contracts import digest, read_json, require
import run_storage

DEFAULTS = {'enabled': True, 'mode': 'observe-only', 'interval_seconds': 60,
            'host_stale_seconds': 180, 'worker_stall_seconds': 900, 'check_timeout_seconds': 10}


def policy(value=None):
    value = {} if value is None else value
    require(isinstance(value, dict) and set(value) <= set(DEFAULTS), 'invalid watchdog configuration')
    result = {**DEFAULTS, **value}
    require(type(result['enabled']) is bool and result['mode'] == 'observe-only', 'watchdog must be observe-only')
    require(all(type(result[k]) is int and result[k] > 0 for k in DEFAULTS if k.endswith('_seconds')), 'invalid watchdog timeout')
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def age(stamp, at):
    try:
        value = datetime.fromisoformat(stamp)
        require(value.tzinfo is not None, 'timezone required')
        seconds = (datetime.fromisoformat(at) - value).total_seconds()
        return seconds if seconds >= 0 else None
    except (TypeError, ValueError):
        return None


def bound_root(value):
    root = run_storage.checked_path(Path(value).absolute())
    require(root.parent.name == '.sdd-runs', 'watchdog requires .sdd-runs/<run_id>')
    snapshot = read_json(run_storage.checked_path(root / 'context/snapshot.json', root))
    require(snapshot['run_id'] == root.name and snapshot['run_root'] == str(root), 'watchdog run identity mismatch')
    run_storage.validate(snapshot['storage_layout'], root, root.name)
    return root, policy(snapshot.get('effective_config', {}).get('watchdog'))


def liveness(entry, at, stale):
    """Actual local process query or fresh trusted host API export; never guess."""
    result = {'status': 'unknown', 'reason': 'no-host-interface'}
    if not isinstance(entry, dict): return result
    elapsed = age(entry.get('observed_at'), at)
    if elapsed is None or elapsed > stale:
        return {'status': 'unknown', 'reason': 'host-observation-stale-or-missing'}
    if entry.get('source') == 'local-process':
        pid = entry.get('pid')
        if type(pid) is not int or pid <= 0 or not entry.get('process_start'):
            return {'status': 'unknown', 'reason': 'process-identity-missing'}
        try:
            probe = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='], capture_output=True, text=True, timeout=2)
            if probe.returncode == 1 and not probe.stdout.strip():
                return {'status': 'exited', 'reason': 'process-not-found', 'pid': pid}
            if probe.returncode != 0:
                return {'status': 'unknown', 'reason': 'process-query-unavailable'}
            if probe.stdout.strip() != entry['process_start']:
                return {'status': 'unknown', 'reason': 'process-identity-changed'}
            return {'status': 'running', 'reason': 'local-process-observed', 'pid': pid}
        except (OSError, subprocess.TimeoutExpired):
            return {'status': 'unknown', 'reason': 'process-query-unavailable'}
    if entry.get('source') == 'host-api' and entry.get('execution_id') and entry.get('provider'):
        status = entry.get('status')
        if status in ('running', 'exited', 'unknown'):
            return {'status': status, 'reason': 'host-api-observed', 'execution_id': entry['execution_id']}
    return result


def inspect(root):
    """Executed in a disposable, bounded read-only observer subprocess."""
    root, config = bound_root(root)
    import ledger
    import project_context
    from contracts import file_ref
    project_context.verify_snapshot(file_ref(root / 'context/snapshot.json'))
    state, events = ledger.read_events(root)  # No status/apply or .ledger.lock.
    require(state and state['run_id'] == root.name, 'Ledger not initialized or wrong run')
    at = now(); findings = []
    def add(code, scope='GLOBAL', detail=None):
        findings.append({'code': code, 'scope': scope, 'detail': detail,
                         'next_action': 'Host review only; watchdog never executes recovery'})
    host_path = run_storage.checked_path(root / 'runs/watchdog/host-state.json', root)
    host_input = {}
    if host_path.exists():
        try:
            host_input = read_json(host_path)
            require(host_input.get('run_id') == root.name and isinstance(host_input.get('workers', []), list), 'host state identity/format mismatch')
        except (ValueError, OSError, AttributeError):
            host_input = {}; add('host-state-invalid')
    host_entry = host_input.get('host', {})
    host = liveness(host_entry, at, config['host_stale_seconds'])
    fresh = age(host_entry.get('observed_at'), at) if isinstance(host_entry, dict) else None
    control = host_entry.get('control', 'running') if fresh is not None and fresh <= config['host_stale_seconds'] else 'unknown'
    paused = control in ('paused', 'stopped')
    if not paused:
        if host['status'] != 'running': add('host-' + host['status'], detail=host)
        heartbeat = age(host_entry.get('heartbeat_at'), at) if isinstance(host_entry, dict) else None
        if host['status'] == 'running' and (heartbeat is None or heartbeat > config['host_stale_seconds']):
            add('host-heartbeat-stale-or-missing')
    expected = [(mid, a) for mid, m in state['modules'].items() for a in m['assignments'].values() if not a.get('closed')]
    audit = state.get('audit_assignment', {})
    if audit and not audit.get('closed'): expected.append((None, audit))
    entries = host_input.get('workers', []); workers = []; used = set()
    for mid, assignment in expected:
        matches = [(i, e) for i, e in enumerate(entries) if isinstance(e, dict) and
                   e.get('assignment_id') == assignment['assignment_id'] and e.get('module_id') == mid and
                   e.get('instance_id') == assignment['instance_id']]
        entry = matches[0][1] if len(matches) == 1 else {}
        if len(matches) == 1: used.add(matches[0][0])
        observed = liveness(entry, at, config['host_stale_seconds'])
        scope = (mid or 'GLOBAL') + '/' + assignment['assignment_id']
        elapsed = age(entry.get('last_progress_at'), at)
        workers.append({'scope': scope, **observed, 'progress': 'unknown' if elapsed is None else 'observed',
                        'idle_seconds': elapsed})
        if not paused and observed['status'] != 'running': add('worker-' + observed['status'], scope, observed)
        if not paused and observed['status'] == 'running' and elapsed is not None and elapsed >= config['worker_stall_seconds']:
            add('worker-progress-overdue', scope, {'idle_seconds': elapsed})
    # GO, parent MO, Spec and preflight executions may have no Ledger assignment.
    for i, entry in enumerate(entries):
        if i in used or not isinstance(entry, dict) or entry.get('assignment_id') or not entry.get('execution_id'): continue
        observed = liveness(entry, at, config['host_stale_seconds'])
        scope = str(entry.get('module_id') or 'GLOBAL') + '/' + entry['execution_id']
        elapsed = age(entry.get('last_progress_at'), at)
        workers.append({'scope': scope, **observed, 'progress': 'unknown' if elapsed is None else 'observed',
                        'idle_seconds': elapsed})
        if not paused and observed['status'] == 'unknown': add('worker-unknown', scope, observed)
        if not paused and observed['status'] == 'exited' and entry.get('expected_active') is True:
            add('orchestrator-exited-await-host-review', scope, observed)
        if not paused and observed['status'] == 'running' and entry.get('expected_active') is True and elapsed is not None and elapsed >= config['worker_stall_seconds']:
            add('worker-progress-overdue', scope, {'idle_seconds': elapsed})
    progress_path = run_storage.checked_path(root / 'ledger/progress.json', root)
    progress = read_json(progress_path) if progress_path.exists() else {}
    current = progress.get('sequence') == len(events)
    terminal = current and not expected and progress.get('state') in ('await-delivery-authorization', 'completed-with-unverified-tests')
    if terminal: findings = []  # Suppress worker/Host execution reminders after completion.
    if not paused:
        if not current: add('routing-observation-stale', detail={'ledger_sequence': len(events), 'progress_sequence': progress.get('sequence')})
        else:
            for signal in progress.get('signals', []):
                if terminal and signal.get('reason') != 'projection-pending':
                    continue
                if signal.get('reason') == 'no-runnable-action-and-no-worker' and any(w['status'] == 'running' for w in workers):
                    continue  # Host may be running GO/parent/preflight outside assignment records.
                if signal.get('severity') == 'human': add(signal['reason'], signal.get('module_id') or 'GLOBAL', signal)
    if paused: findings = []
    return {'run_id': root.name, 'observed_at': at, 'sequence': len(events), 'host': host, 'workers': workers,
            'state': control if paused else ('completed-with-pending-diagnostics' if findings else 'completed') if terminal else 'observing',
            'ready_actions': progress.get('runnable_actions', []) if current else [],
            'findings': findings, 'mode': 'observe-only'}


def notices(root):
    directory = run_storage.checked_path(root / 'reports/watchdog', root)
    result = []
    for path in sorted(directory.glob('notice-*.json')):
        run_storage.checked_path(path, directory)
        require(re.fullmatch(r'notice-[0-9]+', path.stem), 'invalid watchdog notice id')
        event = read_json(path)
        require(event.get('run_id', root.name) == root.name and isinstance(event.get('notifications'), list),
                'invalid watchdog notice')
        result.append((path.stem, event))
    return result


def acknowledge(root, notice_ids):
    """Host delivery receipt only; never an acknowledgement of business recovery."""
    root, _ = bound_root(root)
    require(bool(notice_ids), 'notice id required')
    known = dict(notices(root))
    for notice_id in notice_ids:
        require(notice_id in known, 'unknown watchdog notice id')
    for notice_id in notice_ids:
        path = run_storage.checked_path(root / 'runs/watchdog/acknowledged' / (notice_id + '.json'), root)
        if path.exists():
            ack = read_json(path)
            require(ack.get('run_id') == root.name and ack.get('notice_sha256') == digest(known[notice_id]),
                    'watchdog acknowledgement mismatch')
            continue
        run_storage.atomic_bytes(path, (json.dumps({'run_id': root.name, 'notice_id': notice_id,
            'notice_sha256': digest(known[notice_id]), 'acknowledged_at': now()}) + '\n').encode())
    return {'run_id': root.name, 'acknowledged_notice_ids': notice_ids, 'workflow_action': 'none'}


def pending_notices(root, recorded):
    pending = []
    for notice_id, event in recorded:
        path = run_storage.checked_path(root / 'runs/watchdog/acknowledged' / (notice_id + '.json'), root)
        ack = read_json(path) if path.exists() else {}
        require(not ack or (ack.get('run_id') == root.name and ack.get('notice_sha256') == digest(event)),
                'watchdog acknowledgement mismatch')
        if not ack:
            pending.append({'notice_id': notice_id, 'observed_at': event['observed_at'],
                            'notifications': event['notifications']})
    return pending


def check(root, config):
    root, frozen = bound_root(root)
    require(policy(config) == frozen, 'watchdog policy differs from frozen run configuration')
    if not frozen['enabled']:
        return {'run_id': root.name, 'state': 'disabled', 'mode': 'observe-only', 'notify_user': False, 'notifications': []}
    folder = run_storage.checked_path(root / 'runs/watchdog', root)
    reports = run_storage.checked_path(root / 'reports/watchdog', root)
    try:
        process = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '_inspect', '--root', str(root)],
                                 capture_output=True, text=True, timeout=config['check_timeout_seconds'])
        require(process.returncode == 0, process.stderr.strip()[:500] or 'observer failed')
        result = json.loads(process.stdout)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        result = {'run_id': root.name, 'observed_at': now(), 'mode': 'observe-only', 'state': 'observation-unavailable',
                  'host': {'status': 'unknown'}, 'workers': [], 'findings': [
                      {'code': 'observation-unavailable', 'scope': 'GLOBAL', 'detail': str(exc)[:500],
                       'next_action': 'Host inspect read failure; no workflow action taken'}]}
    state_path = run_storage.checked_path(folder / 'state.json', folder)
    try: previous = read_json(state_path) if state_path.exists() else {}
    except (OSError, ValueError): previous = {}
    if not isinstance(previous, dict): previous = {}
    recorded = notices(root)
    ready = result.get('ready_actions', [])
    ready_key = digest([result.get('sequence'), ready]) if ready else None
    ready_since = previous.get('ready_since') if ready_key and previous.get('ready_key') == ready_key else result['observed_at']
    elapsed = age(ready_since, result['observed_at'])
    if ready and result['state'] == 'observing' and elapsed is not None and elapsed >= config['host_stale_seconds'] and not any(w['status'] == 'running' for w in result['workers']):
        result['findings'].append({'code': 'ready-actions-await-host-review', 'scope': 'GLOBAL', 'detail': ready,
                                  'next_action': 'Host check whether these actions are already claimed; observer does not dispatch'})
    # Stable identities deduplicate ticks; changing durations do not create spam.
    active = {digest([root.name, f['scope'], f['code']]): f for f in result['findings']}
    old = previous.get('active', {})
    # The durable notice is authoritative if a crash preceded the state write.
    # Legacy notices have no active checkpoint; keep their existing state.
    for _, event in reversed(recorded):
        if 'active' in event:
            old = event['active']
            break
    if not isinstance(old, dict): old = {}
    if result['state'] == 'observation-unavailable':
        active = {**old, **active}  # An unreadable run is not evidence of recovery.
    opened, closed = sorted(set(active) - set(old)), sorted(set(old) - set(active))
    notifications = [{'kind': 'opened', 'id': key, 'finding': active[key]} for key in opened]
    notifications += [{'kind': 'closed', 'id': key, 'finding': old[key]} for key in closed]
    if notifications:
        notice_id = 'notice-' + str(max(time.time_ns(), 1 + max(
            (int(key.split('-')[1]) for key, _ in recorded), default=0)))
        event = {'run_id': root.name, 'observed_at': result['observed_at'],
                 'notifications': notifications, 'active': active}
        run_storage.atomic_bytes(reports / (notice_id + '.json'), (json.dumps(event, ensure_ascii=False, indent=2) + '\n').encode())
        recorded.append((notice_id, event))
    pending = pending_notices(root, recorded)
    result.update(notify_user=bool(pending), pending_notices=pending,
                  notifications=[{**item, 'notice_id': batch['notice_id']}
                                 for batch in pending for item in batch['notifications']])
    run_storage.atomic_bytes(state_path, (json.dumps({'active': active, 'last_check': result['observed_at'],
        'ready_key': ready_key, 'ready_since': ready_since}) + '\n').encode())
    run_storage.atomic_bytes(reports / 'latest.json', (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('check', 'watch', 'ack', '_inspect'))
    p.add_argument('--root', required=True)
    p.add_argument('--notice-id', action='append', default=[])
    args = p.parse_args()
    try:
        root, config = bound_root(args.root)
        require(bool(args.notice_id) == (args.command == 'ack'), '--notice-id is required only for ack')
        if args.command == '_inspect': print(json.dumps(inspect(root), ensure_ascii=False)); return 0
        if not config['enabled'] and args.command != 'ack': print(json.dumps({'state': 'disabled', 'mode': 'observe-only'})); return 0
        folder = run_storage.checked_path(root / 'runs/watchdog', root); folder.mkdir(parents=True, exist_ok=True)
        if args.command == 'ack':
            # Separate lock: delivery acknowledgement must work during watch.
            with run_storage.file_lock(folder / '.ack.lock', timeout=0.1):
                print(json.dumps(acknowledge(root, args.notice_id), ensure_ascii=False)); return 0
        with run_storage.file_lock(folder / '.watchdog.lock', timeout=0.1):
            while True:
                result = check(root, config)
                if args.command == 'check' or result['notify_user']:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                if args.command == 'check' or result['state'] in ('completed', 'stopped'): break
                time.sleep(config['interval_seconds'])
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'state': 'observer-error', 'reason': str(exc), 'workflow_action': 'none'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
