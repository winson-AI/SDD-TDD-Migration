#!/usr/bin/env python3
"""The host's loop, as one command: submit every mechanical step of every module and of the run (`ledger.py advance`),
then hand back only what needs a model or a person, one line each, and, with --wait, follow the Ledger journal's end until
someone submits something.

    drive.py --root <run> --host-context '<MO principal JSON>' [--worker ROLE=INSTANCE] [--wait SECONDS]

Each output line is JSON: `dispatch` (start this role on this step with this card), `running` (a worker the Ledger
dispatched: start it with its card unless already started, then wait), `host` (an operation the host submits itself with
the payload given), `person` (a decision only a person gives, with what is asked), `signal` (a stall, an overdue plan, a
refused request, a run ready for its retrospective: act on next_action; printed once, while it stands the tick line counts it
in signals_held), then one `tick` line with the journal sequence. A line names the instance and, when one holds this role's
context, the session to resume; its card then holds only the sections that session has not read. The host reads these
lines, not the status views.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.dont_write_bytecode = True

import ledger
import reading

POLL_SECONDS = 1
PERSON = ('human-decision-required', 'run-approval-required', 'source-approval-required')


def journal_size(root):
    path = Path(root) / 'ledger/events.jsonl'
    return path.stat().st_size if path.is_file() else 0


def row(step, card=None):
    out = {k: step[k] for k in ('module_id', 'role', 'operation', 'assignment_id', 'reason', 'review_asked', 'approval_subject_sha256',
                                'approval_kind', 'detail', 'root_ids', 'session_id', 'session_affinity') if step.get(k) is not None}
    if step.get('report_ref'):
        out['report'] = step['report_ref']['path']
    if step.get('worker_role'):
        out.update(role=step['worker_role'], dispatched_by=step['role'])
    return {**out, **(card or {})}


def card(root, step, instance=None):
    """The card a line hands its role: only what the session to resume has not read, else the whole card."""
    if not step.get('must_read'):
        return {}
    resumed = bool(step.get('session_id')) and 'must_read_new' in step
    rows = step['must_read_new'] if resumed else step['must_read']
    out = reading.render(rows, Path(root) / 'reports/reading', step.get('templates', ()), on_demand=step.get('read_when_writing', ()))
    return {'card': out['path'], 'card_bytes': out['bytes'], **({'instance_id': instance} if instance else {}),
            **({'resumed_from_bytes': sum(r['bytes'] for r in step['must_read'])} if resumed else {})}


def tick(root, principal, workers=None):
    """Advance everything mechanical; the steps left, as lines."""
    for _ in range(50):  # a module's step may unblock another's: repeat until nothing moves
        moved = False
        for step in ledger.status(root)['next_steps']:
            moved |= bool(ledger.advance(root, principal, step['module_id'], workers)['applied'])
        moved |= bool(ledger.advance_run(root, principal, workers))  # the run's own fixed flows
        if not moved:
            break
    st = ledger.status(root, 'full')  # read by this script, not by a model
    lines = []
    changes = [x for x in (st.get('run_change_next_step'), st.get('source_change_next_step')) if x]  # same-run revisions, new sources
    for step in st['next_steps'] + [st['global_next_step']] + changes:
        operation = step.get('operation')
        if not operation or step.get('mechanical') and step.get('ready'):
            continue
        if step.get('human_required') or step.get('reason') in PERSON:
            lines.append({'kind': 'person', **row(step)})
        elif step.get('role') == 'host' and step.get('ready'):
            lines.append({'kind': 'host', **row(step), 'payload': step.get('payload') or {}})
        elif operation == 'await-result' or step.get('reason') == 'audit-running':
            a = (st['modules'].get(step.get('module_id')) or {}).get('assignments', {}).get(step.get('assignment_id')) or {}
            lines.append({'kind': 'running', **row(step, card(root, step, a.get('instance_id')))})
        elif step.get('ready'):
            lines.append({'kind': 'dispatch', **row(step, card(root, step))})
    progress = st.get('workflow_progress') or {}
    seen = {x.get('reason') for x in changes}
    for signal in progress.get('signals', []):
        if signal.get('reason') not in seen:  # a source change already has its own line
            lines.append({'kind': 'signal', **{k: signal[k] for k in ('module_id', 'reason', 'owner', 'next_action', 'severity')
                                               if signal.get(k) is not None}})
    if st['global_next_step'].get('retrospective_due'):
        lines.append({'kind': 'signal', 'reason': 'retrospective-due', 'owner': 'global-orchestrator', 'severity': 'action',
                      'next_action': 'run /sdd-retrospect before the run is closed'})
    if any(line['kind'] == 'signal' for line in lines):
        lines.append({'kind': 'signal', 'reason': 'attention-report', 'next_action': 'read only on a human signal', 'report': progress.get('report_path')})
    return lines, st['last_sequence']


def unseen(root, lines):
    """The lines with every signal a previous tick already printed left out, and how many were: a standing signal reaches
    the host once, not every tick. What was printed is kept under reports/; the attention report lists them all."""
    path = Path(root) / 'reports/drive-signals.json'
    try:
        printed = set(json.loads(path.read_text()))
    except (OSError, ValueError):
        printed = set()
    key = lambda line: json.dumps(line, sort_keys=True, ensure_ascii=False)
    signals = [line for line in lines if line['kind'] == 'signal' and line.get('reason') != 'attention-report']
    new = [line for line in signals if key(line) not in printed]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(key(line) for line in signals), ensure_ascii=False))
    kept = [line for line in lines if line['kind'] != 'signal' or line in new or line.get('reason') == 'attention-report' and new]
    return kept, len(signals) - len(new)


def drive(root, principal, workers=None, wait=None):
    lines, sequence = tick(root, principal, workers)
    if wait and not any(line['kind'] == 'dispatch' for line in lines):
        size, deadline = journal_size(root), time.monotonic() + wait
        while journal_size(root) == size and time.monotonic() < deadline:  # tail the journal: its end moves when anyone submits
            time.sleep(POLL_SECONDS)
        if journal_size(root) != size:
            lines, sequence = tick(root, principal, workers)
    lines, held = unseen(root, lines)
    return lines + [{'kind': 'tick', 'last_sequence': sequence, **({'signals_held': held} if held else {})}]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', required=True)
    parser.add_argument('--host-context', required=True, help='the module orchestrator principal JSON the host submits as')
    parser.add_argument('--worker', action='append', default=[], metavar='ROLE=INSTANCE')
    parser.add_argument('--wait', type=float, help='seconds to follow the journal when nothing is to dispatch')
    args = parser.parse_args()
    workers = dict(item.split('=', 1) for item in args.worker)
    try:
        for line in drive(args.root, json.loads(args.host_context), workers, args.wait):
            print(json.dumps(line, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'kind': 'refused', 'reason': str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
