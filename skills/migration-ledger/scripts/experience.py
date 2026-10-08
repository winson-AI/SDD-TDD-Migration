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
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import run_storage
from contracts import read_json, require
from project_context import atomic, encoded

KINDS = ('slicing-gap', 'boundary-conflict', 'planning-gap', 'fix-pattern', 'failed-strategy', 'escalation', 'gate-rejection')
ABSTRACT_FIELDS = ('summary', 'applicability', 'root_cause', 'strategy', 'result', 'next_check', 'evidence_refs')


def planning_view(data, archive_lesson=None):
    """Project observations remain available for retrospective; new tasks read abstract lessons only."""
    from contracts import digest
    runs, omitted = {}, 0
    for rid, block in data['runs'].items():
        selected = [entry for entry in block['entries'] if all(entry.get(key) for key in ABSTRACT_FIELDS)]
        omitted += len(block['entries']) - len(selected)
        if selected:
            if archive_lesson:
                selected = [{**{key: entry[key] for key in ('kind', 'summary', 'applicability', 'root_cause')},
                            'lesson_ref': archive_lesson(entry)} for entry in selected]
            runs[rid] = {key: value for key, value in block.items() if key != 'entries'}
            runs[rid]['entries'] = selected
    return {'schema_version': 1, 'source_store_sha256': digest(data), 'observations_omitted': omitted,
            'view': 'index' if archive_lesson else 'abstract-lessons', 'runs': runs}


def global_scope(state):
    """Use the current host goal and feature names; no historical lesson body is opened."""
    from contracts import check_ref
    terms = [check_ref(state['global_spec']).read_text()]
    inventory = (state.get('global_plan') or {}).get('content', {}).get('feature_inventory_ref')
    if inventory:
        terms += [row['name'] for row in read_json(check_ref(inventory))['features']]
    for module in [*state.get('modules', {}).values(), *state.get('module_groups', {}).values()]:
        terms += (module.get('scope') or {}).get('in', [])
    return {'scope': {'in': terms}}


def candidates(index, module, task_ids=()):
    """Scope, dimension and cause suggestions; bodies stay unopened and applicability still needs review."""
    terms = set((module.get('scope') or {}).get('in', []))
    for task in (module.get('plan') or {}).get('tasks', []):
        if not task_ids or task['task_id'] in task_ids:
            terms.update((task.get('scope') or {}).get('in', []))
            terms.update(row['dimension'] for row in task.get('dimension_analysis', {}).get('dimensions', []) if row.get('status') == 'applicable')
    for result in [*module.get('results', {}).values(), *module.get('repair_findings', {}).values()]:
        cause = result.get('root_cause') or {}
        if isinstance(cause, dict): terms.update(str(cause.get(key, '')) for key in ('category', 'summary'))
    ref = (module.get('plan') or {}).get('dimension_analysis_ref') or module.get('dimension_analysis_ref')
    if ref:
        from contracts import check_ref
        analysis = read_json(check_ref(ref))
        selected = {r['item_id'] for r in (module.get('plan') or {}).get('dimension_trace', []) if set(task_ids) & set(r['task_ids'])}
        for dimension in analysis['dimensions']:
            if dimension['status'] != 'applicable': continue
            items = [i for i in dimension.get('items', []) if not task_ids or i['item_id'] in selected]
            if items:
                terms.add(dimension['dimension'])
                terms.update(str(i.get('resource_kind', '')) for i in items)
    terms = {term.casefold() for term in terms if isinstance(term, str) and len(term.strip()) > 1}
    def tokens(text):
        words = set(re.findall(r'[a-z][a-z0-9_-]{2,}', text)) - {'the', 'and', 'with', 'from', 'this', 'that', 'task', 'module', 'implement', 'migration', 'behavior'}
        for phrase in re.findall(r'[\u4e00-\u9fff]+', text):
            words.update(phrase[i:i+2] for i in range(len(phrase)-1))
        return words
    keywords = tokens(' '.join(terms))
    rows = []
    for block in index.get('runs', {}).values():
        for entry in block.get('entries', []):
            text = ' '.join(str(entry.get(key, '')) for key in ('applicability', 'root_cause', 'summary')).casefold()
            score = 4 * sum(term in text for term in terms) + len(keywords & tokens(text))
            if score and entry.get('lesson_ref'):
                rows.append((score, {key: entry[key] for key in ('kind', 'summary', 'applicability', 'lesson_ref')}))
    return [row for _, row in sorted(rows, key=lambda pair: (-pair[0], pair[1]['kind'] != 'failed-strategy', pair[1]['summary']))[:5]]


def shared(root):
    """The directory a project names so that several workspaces keep one store (`experience_root`), or None."""
    path = Path(root).resolve() / 'project-context.json'
    record = read_json(path) if path.is_file() else {}
    return record.get('config', {}).get('experience_root'), record.get('project_id')


def store(root):
    """Where a project's lessons are kept: its own directory, or the store it shares."""
    directory, _ = shared(root)
    return Path(directory).resolve() if directory else run_storage.checked_path(Path(root).resolve() / 'experience', Path(root).resolve())


def key(root, run_id):
    """A run's block in the store. Projects that share a store may reuse a run id, so there the project names it too."""
    directory, project_id = shared(root)
    return f'{project_id}/{run_id}' if directory else run_id


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


def validate_lessons(ref):
    from contracts import check_ref, nonempty
    data = read_json(check_ref(ref))
    require(data.get('schema_version') == 1, 'invalid retrospective schema')
    for entry in nonempty(data.get('entries'), 'retrospective entries'):
        require(entry.get('kind') in KINDS, 'invalid lesson kind')
        require(all(entry.get(k) for k in ABSTRACT_FIELDS), 'abstract lesson needs condition, cause, strategy, result and next check')
        for evidence in nonempty(entry.get('evidence_refs'), 'retrospective evidence'): check_ref(evidence)
    return data['entries']


def bind_history(root, state, sequence):
    """Immutable Ledger-authored history inputs; only changed lessons acquire a new reference."""
    from contracts import check_ref
    from openspec_projection import build_lessons
    from project_context import archive
    lessons = build_lessons(state, sequence, root)
    generated = []
    def bind(obj, key, entries):
        previous = obj.get(key)
        if not entries and not previous:
            return
        if previous and read_json(check_ref(previous)).get('entries') == entries:
            return
        obj[key] = archive(Path(root) / 'artifacts/lessons', encoded({
            'run_id': state['run_id'], 'sequence': sequence, 'entries': entries}), '.json')
        generated.append(obj[key])
    bind(state, 'lessons_ref', lessons['entries'])
    for mid, m in {**state.get('module_groups', {}), **state['modules']}.items():
        entries = [e for e in lessons['entries'] if not any(e.get(k) for k in ('module_id', 'parent_module_id', 'affected_modules', 'root_ids', 'scope'))
                   or e.get('module_id') == mid or (e.get('parent_module_id') and e['parent_module_id'] in (mid, m.get('parent_module_id')))
                   or mid in e.get('affected_modules', []) or mid in e.get('root_ids', [])]
        bind(m, 'planning_lessons_ref', entries)
    return generated


def auto_harvest(run_root, force=False):
    import ledger
    import audit_closure
    state, events = ledger.read_events(Path(run_root))
    ref = state.get('project_context_ref')
    if not ref:
        return None
    import project_context
    snapshot = project_context.verify_snapshot(ref)
    if not force and not audit_closure.module_rounds(state, ledger.routing(state)['next_steps'])['all_settled']:
        return None
    project_root = Path(snapshot['storage_layout']['workspace_root']) / '.sdd-migration'
    return harvest(project_root, run_root)


def harvest(root, run_root):
    from openspec_projection import build_lessons
    state, sequence = registered_run(root, run_root)
    lessons = build_lessons(state, sequence, run_root)
    rid = key(root, state['run_id'])
    directory = store(root)
    directory.mkdir(parents=True, exist_ok=True)
    # prepare reads the store under the project lock; a shared store is also written by other projects
    with run_storage.file_lock(Path(root).resolve() / '.context.lock'), run_storage.file_lock(directory / '.experience.lock'):
        data = load(root)
        previous = data['runs'].get(rid)
        require(not previous or previous['sequence'] <= sequence, 'stored experience is newer than this journal')
        if previous and previous['sequence'] == sequence:
            return {'run_id': rid, 'sequence': sequence, 'entries': len(previous['entries']), 'duplicate': True}
        stamp = datetime.now(timezone.utc).isoformat()
        data['runs'][rid] = {'sequence': sequence, 'run_quality': state.get('quality'), 'harvested_at': stamp,
                             'entries': lessons['entries']}
        atomic(directory / 'lessons.json', encoded(data))
        counts = dict(Counter(e['kind'] for e in lessons['entries']))
        missing = planning_view({'runs': {rid: data['runs'][rid]}})['observations_omitted']
        receipt = {'run_id': rid, 'sequence': sequence, 'run_quality': state.get('quality'),
                   'harvested_at': stamp, 'counts': counts, 'observations_needing_retrospective': missing,
                   **({'next_action': 'sdd-retrospect: extract conditions, causes, strategies and next checks from committed observations'} if missing else {})}
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
            runs = load(args.root)['runs']
            block = runs.get(args.run_id) or runs.get(key(args.root, args.run_id))
            require(block, 'no experience harvested for run ' + str(args.run_id))
            out = {'run_id': args.run_id, **block}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False)); return 2
    print(json.dumps(out, ensure_ascii=False, indent=2)); return 0


if __name__ == '__main__':
    sys.exit(main())
