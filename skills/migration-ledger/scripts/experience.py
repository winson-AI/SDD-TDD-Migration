"""Cross-run experience: harvest one run's lessons into the project store, and read the store back.

The store `<workspace_root>/.sdd-migration/experience/` is advisory planning input, not state:
  lessons.json      one block per run_id (re-harvest replaces that run's block, never another run's)
  retrospect.jsonl  append-only harvest receipts

Lessons are rebuilt from the run's integrity-checked Ledger journal, not from the rebuildable
`ledger/lessons.json` projection. `project_context.py prepare` freezes the current lessons.json into the
next run's snapshot (`source_refs.experience_ref`), so planners read it under the same hash discipline as
knowledge files. Experience never relaxes a gate, approves a plan, or turns a result Green.

  experience.py harvest --root <workspace>/.sdd-migration --run-root <run_root>
  experience.py list    --root <workspace>/.sdd-migration [--kind fix-pattern]
  experience.py show    --root <workspace>/.sdd-migration --run-id <run_id>
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import run_storage
from contracts import read_json, require
from project_context import atomic, encoded

KINDS = ('slicing-gap', 'boundary-conflict', 'planning-gap', 'fix-pattern')


def store(root):
    return run_storage.checked_path(Path(root).resolve() / 'experience', Path(root).resolve())


def load(root):
    path = store(root) / 'lessons.json'
    if not path.exists():
        return {'schema_version': 1, 'runs': {}}
    data = read_json(path)
    require(data.get('schema_version') == 1 and isinstance(data.get('runs'), dict), 'invalid experience store')
    return data


def registered_run(root, run_root):
    """Only runs prepared by this project may contribute experience."""
    import ledger
    state, events = ledger.read_events(run_root)
    require(state and events, 'run has no committed Ledger events')
    index = Path(root).resolve() / 'runs' / (state['run_id'] + '.json')
    require(index.is_file() and read_json(index).get('run_root') == str(Path(run_root).resolve()),
            'run is not registered in this project context')
    return state, len(events)


def harvest(root, run_root):
    from openspec_projection import build_lessons
    state, sequence = registered_run(root, run_root)
    lessons = build_lessons(state, sequence)
    rid = state['run_id']
    with run_storage.file_lock(Path(root).resolve() / '.context.lock'):  # prepare reads the store under this lock
        data = load(root)
        previous = data['runs'].get(rid)
        require(not previous or previous['sequence'] <= sequence, 'stored experience is newer than this journal')
        if previous and previous['sequence'] == sequence:
            return {'run_id': rid, 'sequence': sequence, 'entries': len(previous['entries']), 'duplicate': True}
        stamp = datetime.now(timezone.utc).isoformat()
        data['runs'][rid] = {'sequence': sequence, 'run_quality': state.get('quality'), 'harvested_at': stamp,
                             'entries': lessons['entries']}
        directory = store(root)
        directory.mkdir(exist_ok=True)
        atomic(directory / 'lessons.json', encoded(data))
        counts = dict(Counter(e['kind'] for e in lessons['entries']))
        receipt = {'run_id': rid, 'sequence': sequence, 'run_quality': state.get('quality'),
                   'harvested_at': stamp, 'counts': counts}
        with (directory / 'retrospect.jsonl').open('a') as f:
            f.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + '\n')
    return {**receipt, 'entries': len(lessons['entries']), 'duplicate': False}


def entries(root, kind=None):
    rows = []
    for rid, block in sorted(load(root)['runs'].items()):
        for entry in block['entries']:
            if kind is None or entry['kind'] == kind:
                rows.append({'run_id': rid, **entry})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('harvest', 'list', 'show'))
    parser.add_argument('--root', required=True, help='<workspace_root>/.sdd-migration')
    parser.add_argument('--run-root'); parser.add_argument('--run-id'); parser.add_argument('--kind', choices=KINDS)
    args = parser.parse_args(argv)
    try:
        if args.command == 'harvest':
            require(args.run_root, '--run-root required')
            out = harvest(args.root, args.run_root)
        elif args.command == 'list':
            out = {'entries': entries(args.root, args.kind)}
        else:
            require(args.run_id, '--run-id required')
            block = load(args.root)['runs'].get(args.run_id)
            require(block, 'no experience harvested for run ' + str(args.run_id))
            out = {'run_id': args.run_id, **block}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False)); return 2
    print(json.dumps(out, ensure_ascii=False, indent=2)); return 0


if __name__ == '__main__':
    sys.exit(main())
