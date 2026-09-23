"""Read-only scheduling diagnostics. Never approve, cancel, or recolor work."""
from datetime import datetime, timezone
import json
from pathlib import Path

from contracts import digest
import run_storage


def record_rejection(root, req, actor, reason):
    """Keep the latest rejected action visible outside the accepted event journal."""
    root = Path(root).resolve()
    if not root.is_dir():
        return
    try:
        from ledger import atomic, read_events
        with run_storage.file_lock(root / '.ledger.lock'):
            state, events = read_events(root)
            if state:
                run_storage.for_state(root, state)
            mid = req.get('module_id')
            scope = ((state or {}).get('modules', {}).get(mid) or
                     (state or {}).get('module_groups', {}).get(mid)) if mid else state
            revision = (scope or {}).get('revision')
            fingerprint = digest([mid, req.get('operation'), reason, revision])
            path = run_storage.checked_path(root / 'reports/rejected-operation.json')
            scoped = run_storage.checked_path(root / 'reports/rejections' / (fingerprint + '.json'))
            try:
                previous = json.loads((scoped if scoped.exists() else path).read_text()) if scoped.exists() or path.exists() else {}
            except (OSError, ValueError):
                previous = {}
            if not isinstance(previous, dict):
                previous = {}
            record = {'module_id': mid, 'operation': req.get('operation'), 'reason': reason,
                          'request_id': req.get('request_id'), 'actor_role': actor.get('role'),
                          'revision': revision, 'sequence': len(events), 'fingerprint': fingerprint,
                          'attempts': previous.get('attempts', 0) + 1 if previous.get('fingerprint') == fingerprint else 1,
                          'recorded_at': datetime.now(timezone.utc).isoformat(),
                          'next_action': 'read-current-status; resolve gate or record evidenced suspension; do not retry unchanged request'}
            atomic(scoped, record)
            atomic(path, record)  # Compatibility/latest navigation, not the counter store.
    except (OSError, ValueError, KeyError, TypeError):
        pass  # The original failure is returned even if diagnostic persistence fails.


def build(root, state, events, steps, global_step, at=None):
    at = at or datetime.now(timezone.utc)
    signals, watches = [], []
    timeout = state.get('worker_stall_timeout_seconds', 900)
    for mid, module in state['modules'].items():
        blocker = module.get('blocked') or {}
        if blocker.get('reason_code') == 'not-implemented' and blocker.get('implementation_gap') and blocker.get('implementation_gap_ref'):
            signals.append({'module_id': mid, 'reason': 'not-implemented', 'label': '未实现',
                            'owner': blocker['owner'], 'next_action': blocker['next_action'], 'severity': 'human',
                            'evidence': {'sequence': len(events), 'review_ref': blocker['implementation_gap_ref'],
                                         'review': blocker['implementation_gap']}})
    if global_step.get('reason') == 'audit-snapshot-stale':
        signals.append({'module_id': None, 'reason': 'audit-snapshot-stale', 'owner': 'host',
                        'next_action': 'confirm auditor stopped; audit-revoke before module invalidation', 'severity': 'human',
                        'evidence': {'sequence': len(events), 'step': global_step}})
    for step in steps + [{'module_id': None, **global_step}]:
        mid, reason = step.get('module_id'), step.get('reason')
        if step.get('ready'):
            continue
        if reason in ('module-complete', 'parent-summary-current', 'automation-not-run; other work may continue',
                      'await-delivery-authorization', 'completed-with-unverified-tests', 'worker-running',
                      'audit-running', 'await-child-modules', 'await-audit-closure', 'await-fixer-and-testing',
                      'await-auditor', 'dependency-incomplete', 'dependency-verification-pending'):
            continue
        # A barrier itself is not a failure; report concrete child causes below.
        if mid is None and reason in ('await-all-module-rounds', 'await-parent-summaries', 'module-work-remaining', 'module-decomposition-required'):
            continue
        human = reason in ('human-decision-required', 'human-review-required', 'finding-awaits-human',
                           'approval-or-impact-review-required', 'budget-exhausted', 'audit-budget-exhausted',
                           'allocation-review-required')
        action = step.get('recovery_action') or step.get('context_next_action') or step.get('operation') or 'inspect gate; repair inputs or escalate with evidence'
        signals.append({'module_id': mid, 'reason': reason or 'gate-not-ready',
                        'owner': step.get('context_gate', {}).get('producer_role') or step.get('role') or 'global-orchestrator',
                        'next_action': action, 'severity': 'human' if human else 'action',
                        'evidence': {'sequence': len(events), 'step': step}})
    assignments = [(mid, a) for mid, m in state['modules'].items() for a in m['assignments'].values() if not a.get('closed')]
    audit = state.get('audit_assignment', {})
    if audit and not audit.get('closed'):
        assignments.append((None, audit))
    for mid, assignment in assignments:
        matching = [e for e in events if e.get('module_id') == mid]
        stamp = (matching[-1] if matching else events[-1])['timestamp'] if events else at.isoformat()
        elapsed = max(0, int((at - datetime.fromisoformat(stamp)).total_seconds()))
        watch = {'module_id': mid, 'assignment_id': assignment['assignment_id'], 'owner': 'host',
                 'idle_seconds': elapsed, 'timeout_seconds': timeout,
                 'next_action': 'check actual worker liveness; on exit/failure record stop evidence and revoke; then recover or suspend'}
        watches.append(watch)
        if elapsed >= timeout:
            signals.append({**watch, 'reason': 'worker-progress-overdue', 'severity': 'human',
                            'evidence': {'sequence': len(events), 'last_event_at': stamp}})
    latest = Path(root) / 'reports/rejected-operation.json'
    try:
        directory = run_storage.checked_path(Path(root) / 'reports/rejections')
        rejection_paths = sorted(directory.glob('*.json')) if directory.is_dir() else []
    except (OSError, ValueError) as exc:
        rejection_paths = []
        signals.append({'module_id': None, 'reason': 'diagnostic-unreadable', 'owner': 'host',
                        'next_action': 'repair diagnostic path; continue independently valid actions', 'severity': 'action',
                        'evidence': {'error': str(exc)}})
    if latest.exists(): rejection_paths.append(latest)
    seen = set()
    for rejection in rejection_paths:
        try:
            run_storage.checked_path(rejection)
            rejected = json.loads(rejection.read_text())
            if not isinstance(rejected, dict):
                raise ValueError('invalid rejection diagnostic')
            mid = rejected.get('module_id')
            scope = (state['modules'].get(mid) or state.get('module_groups', {}).get(mid)) if mid else state
            fingerprint = rejected.get('fingerprint') or str(rejection)
            if scope and scope.get('revision') == rejected.get('revision') and fingerprint not in seen:
                seen.add(fingerprint)
                signals.append({'module_id': mid, 'reason': 'operation-rejected', 'owner': rejected['actor_role'],
                                'next_action': rejected['next_action'], 'severity': 'human' if rejected['attempts'] >= 3 else 'action',
                                'evidence': {'path': str(rejection.resolve()), 'rejection': rejected}})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            signals.append({'module_id': None, 'reason': 'diagnostic-unreadable', 'owner': 'host',
                            'next_action': 'repair diagnostic file; continue independently valid actions', 'severity': 'action',
                            'evidence': {'path': str(rejection.resolve()), 'error': str(exc)}})
    import source_changes
    source_step = source_changes.next_action(state)
    if source_step:
        signals.append({'module_id': None, 'reason': source_step['reason'], 'owner': source_step['role'],
                        'next_action': source_step['operation'], 'severity': 'human' if source_step['reason'] == 'source-approval-required' else 'action',
                        'evidence': source_step})
    ready = [{'module_id': x.get('module_id'), 'operation': x['operation'], 'role': x.get('role')}
             for x in steps + [{'module_id': None, **global_step}] if x.get('ready')]
    if source_step and source_step['ready']:
        ready.append({'module_id': None, 'operation': source_step['operation'], 'role': source_step['role']})
    terminal = global_step.get('reason') in ('await-delivery-authorization', 'completed-with-unverified-tests')
    stalled = not terminal and not ready and not assignments
    if stalled:
        signals.append({'module_id': None, 'reason': 'no-runnable-action-and-no-worker', 'owner': 'global-orchestrator',
                        'next_action': 'resolve listed gates; record per-module suspension when genuinely blocked; surface unresolved decisions to user',
                        'severity': 'human', 'evidence': {'sequence': len(events), 'global_step': global_step,
                                                       'module_steps': steps}})
    return {'sequence': len(events), 'state': global_step['reason'] if terminal else 'stalled' if stalled else 'running',
            'notify_user': any(x['severity'] == 'human' for x in signals), 'signals': signals,
            'runnable_actions': ready, 'worker_watches': watches,
            'host_contract': 'continue independent runnable actions; check workers; surface human signals; never exit silently on ready=false',
            'report_path': str((Path(root) / 'reports/workflow-attention.md').resolve())}


def projection_attention(progress, errors):
    if errors:
        progress['signals'] = [s for s in progress['signals'] if s['reason'] != 'projection-pending']
        progress['signals'].append({'module_id': None, 'reason': 'projection-pending', 'owner': 'host',
            'severity': 'human', 'next_action': 'repair reported projection; refresh status; preserve committed events and continue independent actions',
            'evidence': {'errors': list(errors)}})
        progress['notify_user'] = True


def render(progress):
    lines = ['# Workflow attention', '', 'Sequence: ' + str(progress['sequence']),
             'State: ' + progress['state'], '', progress['host_contract'], '']
    for item in progress['signals']:
        lines += ['## ' + (item['module_id'] or 'GLOBAL') + ': ' + item['reason'], '',
                  'Owner: ' + str(item['owner']), 'Action: ' + str(item['next_action']),
                  'Severity: ' + item['severity'], '', '```json', json.dumps(item['evidence'], ensure_ascii=False, indent=2), '```', '']
    lines += ['## Runnable actions / worker watches', '', '```json',
              json.dumps({k: progress[k] for k in ('runnable_actions', 'worker_watches')}, ensure_ascii=False, indent=2), '```', '']
    return '\n'.join(lines)
