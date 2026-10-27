#!/usr/bin/env python3
"""The host's loop, as one command: submit every mechanical step of every module and of the run (`ledger.py advance`),
then hand back only what needs a model or a person, one line each, and, with --wait, follow the Ledger journal's end until
someone submits something.

    drive.py --root <run> --host-context '<MO principal JSON>' [--worker ROLE=INSTANCE] [--wait SECONDS]

Each output line is JSON: `dispatch` (start this role on this step with this card), `running` (a dispatched worker has not
submitted yet), `person` (a decision only a person gives), then one `tick` line with the journal sequence. The host reads
these lines, not the status views.
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


def journal_size(root):
    path = Path(root) / 'ledger/events.jsonl'
    return path.stat().st_size if path.is_file() else 0


def row(step, card=None):
    out = {k: step[k] for k in ('module_id', 'role', 'operation', 'assignment_id', 'reason', 'review_asked', 'approval_subject_sha256')
           if step.get(k) is not None}
    if step.get('worker_role'):
        out.update(role=step['worker_role'], dispatched_by=step['role'])
    return {**out, **({'card': card} if card else {})}


def tick(root, principal, workers=None):
    """Advance everything mechanical; the steps left, as lines."""
    cards = {}
    for _ in range(50):  # a module's step may unblock another's: repeat until nothing moves
        moved = False
        for step in ledger.status(root)['next_steps']:
            out = ledger.advance(root, principal, step['module_id'], workers)
            moved |= bool(out['applied'])
            if out.get('card'):
                cards[step['module_id']] = out['card']
        if not moved:
            break
    st = ledger.status(root, 'full')  # read by this script, not by a model
    lines = []
    for step in st['next_steps'] + [st['global_next_step']]:
        operation = step.get('operation')
        if not operation or step.get('mechanical') and step.get('ready'):
            continue
        if step.get('human_required') or step.get('reason') == 'human-decision-required':
            lines.append({'kind': 'person', **row(step)})
        elif operation == 'await-result' or step.get('reason') == 'audit-running':
            lines.append({'kind': 'running', **row(step)})
        elif step.get('ready'):
            card = cards.get(step.get('module_id'))
            if not card and step.get('must_read'):
                card = reading.render(step['must_read'], Path(root) / 'reports/reading', step.get('templates', ()),
                                      on_demand=step.get('read_when_writing', ()))['path']
            lines.append({'kind': 'dispatch', **row(step, card)})
    return lines, st['last_sequence']


def drive(root, principal, workers=None, wait=None):
    lines, sequence = tick(root, principal, workers)
    if wait and not any(line['kind'] == 'dispatch' for line in lines):
        size, deadline = journal_size(root), time.monotonic() + wait
        while journal_size(root) == size and time.monotonic() < deadline:  # tail the journal: its end moves when anyone submits
            time.sleep(POLL_SECONDS)
        if journal_size(root) != size:
            lines, sequence = tick(root, principal, workers)
    return lines + [{'kind': 'tick', 'last_sequence': sequence}]


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
