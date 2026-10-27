"""What a new host session needs to continue a run whose host stopped: the package it is pinned to, the last event and how
long ago, the ready actions, the open assignments, the work written under staging since the last event and the signals
waiting on a person. Read-only over the run (status refreshes its projections); written to reports/handover.md.

  ledger.py handover --root <run>
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from contracts import SKELETON_MARK, require
import run_storage


def in_progress(root, since):
    """[{dir, files, newest, unfilled}] of the staging folders written after `since`: work a stopped host left unsubmitted."""
    rows, staging = [], Path(root) / 'staging'
    for role in sorted(p for p in staging.iterdir() if p.is_dir()) if staging.is_dir() else []:
        for folder in sorted(p for p in role.iterdir() if p.is_dir()):
            files = [f for f in folder.rglob('*') if f.is_file() and '/build/' not in str(f) and '/.gradle/' not in str(f)]
            later = [f for f in files if f.stat().st_mtime > since]
            if not later:
                continue
            newest = max(later, key=lambda f: f.stat().st_mtime)
            unfilled = sum(f.read_text(errors='replace').count(SKELETON_MARK) for f in files if f.suffix in ('.md', '.json', '.kt', '.txt', '.ets'))
            rows.append({'dir': str(folder.relative_to(root)), 'files': len(files), 'unfilled': unfilled,
                         'newest': str(newest.relative_to(root)),
                         'newest_at': datetime.fromtimestamp(newest.stat().st_mtime, timezone.utc).isoformat()})
    return rows


def brief(root):
    import ledger
    import package_version
    import reading
    root = Path(root).resolve()
    state, events = ledger.read_events(root)
    require(state, 'run not initialised: no journal under ' + str(root))
    status = ledger.status(root)
    last = events[-1]
    at = datetime.now(timezone.utc)
    idle = int((at - datetime.fromisoformat(last['timestamp'])).total_seconds())
    pinned, current = state.get('package_sha'), package_version.sha(reading.PACKAGE)
    ready = [{k: step.get(k) for k in ('module_id', 'operation', 'role', 'reason', 'waiting_for') if step.get(k) is not None}
             for step in status.get('next_steps', []) + [status.get('global_next_step') or {}] if step.get('operation') and step.get('ready')]
    open_work = [{'module_id': mid, 'assignment_id': a['assignment_id'], 'role': a['role'], 'instance_id': a.get('instance_id')}
                 for mid, m in state['modules'].items() for a in m['assignments'].values() if not a.get('closed')]
    signals = [{k: s.get(k) for k in ('module_id', 'reason', 'next_action')} for s in (status.get('workflow_progress') or {}).get('signals', [])
               if s.get('severity') == 'human' or s.get('reason') == 'planning-overdue']
    staged = in_progress(root, datetime.fromisoformat(last['timestamp']).timestamp())
    out = {'run_id': state['run_id'], 'package_sha': pinned, 'checkout_matches': pinned in (None, current),
           'last_event': {'sequence': last['sequence'], 'operation': last['operation'], 'module_id': last.get('module_id'),
                          'timestamp': last['timestamp'], 'idle_minutes': idle // 60},
           'ready_actions': ready, 'open_assignments': open_work, 'unsubmitted_staging': staged, 'waiting_on_a_person': signals,
           'next_action': 'start the host from a checkout of package ' + str(pinned or 'any') + '; continue the ready actions; '
                          'an open assignment is checked and revoked or resumed before a new dispatch; a staging folder listed '
                          'is the stopped worker\'s draft: give it to the next worker of that module instead of starting over'}
    lines = [f"# Handover · {out['run_id']}", '',
             f"- package: {pinned or '—'}（当前 checkout {'一致' if out['checkout_matches'] else '不一致：从该提交的 worktree 运行'}）",
             f"- last event: #{last['sequence']} {last['operation']} {last.get('module_id') or 'GLOBAL'} at {last['timestamp']}（{idle // 60} 分钟前）", '',
             '## Ready actions', *([f"- {r.get('module_id') or 'GLOBAL'}: {r['operation']} ({r['role']})" for r in ready] or ['- none']), '',
             '## Open assignments', *([f"- {a['module_id']}/{a['assignment_id']}: {a['role']} {a['instance_id']}" for a in open_work] or ['- none']), '',
             '## Unsubmitted staging', *([f"- {r['dir']}: {r['files']} files, {r['unfilled']} [[待写 left, newest {r['newest']}" for r in staged] or ['- none']), '',
             '## Waiting on a person', *([f"- {s.get('module_id') or 'GLOBAL'}: {s['reason']} — {s['next_action']}" for s in signals] or ['- none']), '',
             out['next_action'], '']
    path = run_storage.checked_path(root / 'reports/handover.md', root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines))
    out['path'] = str(path)
    return out


if __name__ == '__main__':
    import sys
    print(json.dumps(brief(sys.argv[1]), ensure_ascii=False, indent=2))
