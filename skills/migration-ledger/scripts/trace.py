#!/usr/bin/env python3
"""Read-only, bounded evidence navigation. No status refresh, locks or workflow actions."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

import ledger
from contracts import digest, read_json, require
from run_storage import checked_path
from verify_openspec import AcceptanceEvidence


def excerpt(path, offset=0, size=1024, tail=False):
    require(type(offset) is int and offset >= 0 and type(size) is int and 0 <= size <= 4096,
            'excerpt offset must be nonnegative and size must be 0..4096')
    with Path(path).open('rb') as stream:
        length = stream.seek(0, 2)
        start = max(0, length - size) if tail else min(offset, length)
        stream.seek(start); data = stream.read(size)
    return {'text': data.decode('utf-8', errors='replace'), 'offset': start, 'bytes': len(data),
            'total_bytes': length, 'next_offset': start + len(data) if start + len(data) < length else None,
            'truncated': start > 0 or start + len(data) < length}


def bounded(value, depth=0):
    """Bound display fields; full values remain in the hash-referenced evidence."""
    if isinstance(value, str): return value if len(value) <= 600 else value[:600] + '…[truncated]'
    if depth >= 5 and isinstance(value, (dict, list)): return '[omitted; read evidence]'
    if isinstance(value, list):
        return [bounded(v, depth + 1) for v in value[:8]] + ([{'omitted': len(value) - 8}] if len(value) > 8 else [])
    if isinstance(value, dict):
        items = list(value.items())
        return {k: bounded(v, depth + 1) for k, v in (items if depth == 0 else items[:20])}
    return value


def load(root):
    root = Path(root).absolute(); checked_path(root)
    state, events = ledger.read_events(root)
    require(state, 'run not initialized')
    return root, state, events


def node(state, module_id):
    if module_id == 'GLOBAL':
        return {'plan': {'paths': state.get('global_paths', [])}, 'results': state.get('audit_results', {}),
                'phase': 'audited' if state.get('audit') else 'await-audit', 'freeze_id': None, 'code_baseline': None}
    require(module_id in state['modules'], 'trace needs an executable leaf module_id or GLOBAL')
    return state['modules'][module_id]


def records(state, events, module_id, history):
    latest = node(state, module_id)
    seen, rows = set(), []
    for event, snapshot, changed in ledger.replay(events):
        if module_id == 'GLOBAL':
            module = node({**state, **{k: snapshot[k] for k in changed if k in snapshot}}, module_id) if 'audit_results' in changed else None
        else:
            module = snapshot['modules'].get(module_id) if 'modules' in changed else None
        if not module: continue
        for pid, result in module.get('results', {}).items():
            if module_id == 'GLOBAL' and pid not in {p['path_id'] for p in latest['plan']['paths']}:
                continue
            key = (pid, result.get('test_run_id'), digest(result))
            if key in seen: continue
            seen.add(key)
            rows.append((event, module, pid, result))
    if history:
        return sorted(rows, key=lambda r: r[0]['sequence'], reverse=True)
    current = []
    for path in (latest.get('plan') or {}).get('paths', []):
        pid = path['path_id']; result = latest.get('results', {}).get(pid)
        matching = [r for r in rows if r[2] == pid and r[3] == result]
        current.append(matching[-1] if matching else (None, latest, pid, result))
    return current


def query(root, module_id, scenario_id=None, task_id=None, path_id=None, assertion_id=None,
          test_id=None, history=False, offset=0, limit=5, excerpt_bytes=1024):
    require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 20,
            'offset must be nonnegative and limit must be 1..20')
    require(type(excerpt_bytes) is int and 0 <= excerpt_bytes <= 4096, 'excerpt_bytes must be 0..4096')
    root, state, events = load(root)
    evidence = AcceptanceEvidence(root, events, state['target_root'])
    matches = []
    for event, module, pid, result in records(state, events, module_id, history):
        plan = module.get('plan') or {}
        path = next((p for p in plan.get('paths', []) if p['path_id'] == pid), {})
        assertions = [a['assertion_id'] for a in path.get('expected_assertions', [])]
        scenarios = [t for t in plan.get('scenario_trace', []) if any(
            a['path_id'] == pid and (not assertion_id or a['assertion_id'] == assertion_id)
            for a in t['assertions']) or path.get('kind') == 'static']
        tasks = [t['task_id'] for t in plan.get('tasks', []) if pid in t.get('path_ids', [])]
        required_tests = path.get('unit_report', {}).get('required_test_ids', [])
        actual_tests = (result or {}).get('unit_execution', {}).get('tests', [])
        if (path_id and path_id != pid or scenario_id and scenario_id not in [t['scenario_id'] for t in scenarios]
                or task_id and task_id not in tasks or assertion_id and assertion_id not in assertions
                or test_id and test_id not in required_tests and not any(t['test_id'] == test_id for t in actual_tests)):
            continue
        matches.append((event, module, path, result, scenarios, tasks))
    rows = []
    for event, module, path, result, scenarios, tasks in matches[offset:offset + limit]:
        plan = module.get('plan') or {}; result = result or {}
        row = {'module_id': module_id, 'path_id': path.get('path_id'), 'case_id': path.get('case_id'),
               'kind': path.get('kind'), 'scenario_ids': [t['scenario_id'] for t in scenarios], 'task_ids': tasks,
               'phase': node(state, module_id)['phase'], 'stale': node(state, module_id).get('stale', False),
               'quality': result.get('quality', 'not-executed'), 'test_run_id': result.get('test_run_id'),
               'retest_of': result.get('retest_of'), 'assertions': result.get('assertions', []),
               'root_cause': result.get('root_cause'), 'freeze_id': module.get('freeze_id'),
               'code_baseline': result.get('code_baseline', module.get('code_baseline')),
               'evidence_refs': {}, 'evidence_issues': [], 'history': history}
        if event:
            row['acceptance_event'] = {k: event.get(k) for k in ('event_id', 'sequence', 'operation', 'sha256')}
        row['spec_refs'] = [d for d in plan.get('definitions', []) if d['kind'] == 'spec']
        audit = state.get('audit_results', {}).get(path.get('path_id'))
        if module_id != 'GLOBAL' and audit:
            row['auditor_result'] = {k: audit.get(k) for k in ('quality', 'test_run_id', 'root_cause', 'execution_receipt')}
            row['auditor_result']['snapshot_matches_current_code'] = (
                state.get('audit', {}).get('snapshot', {}).get(module_id) == node(state, module_id).get('code_baseline'))
        unit = result.get('unit_execution', {})
        if unit:
            row['unit'] = {'counts': unit['counts'], 'missing_test_ids': unit['missing_test_ids'],
                           'issues': unit['issues'], 'reports': unit['reports']}
            if test_id: row['unit']['selected_test'] = [t for t in unit['tests'] if t['test_id'] == test_id]
        receipt_ref = result.get('execution_receipt')
        if receipt_ref:
            row['evidence_refs']['receipt'] = receipt_ref
            try:
                receipt = read_json(evidence.check(receipt_ref))
                row['execution'] = {k: receipt.get(k) for k in ('started_at', 'finished_at', 'exit_code', 'termination')}
                refs = {key: receipt[key] for key in ('log_ref', 'query_ref', 'result_ref') if receipt.get(key)}
                refs.update(receipt.get('capture') or {})
                row['evidence_refs'].update(refs)
                # Hash refs are navigable on demand; verify the receipt and selected excerpt now.
                if excerpt_bytes and result.get('quality') != 'green-passed':
                    row['log_excerpt'] = excerpt(evidence.check(receipt['log_ref']), size=excerpt_bytes, tail=True)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                row['evidence_issues'].append(str(exc))
        preview = row.pop('log_excerpt', None)
        row = bounded(row)
        if preview is not None: row['log_excerpt'] = preview
        if len(json.dumps(row, ensure_ascii=False).encode()) > 16000:
            row = {k: row.get(k) for k in ('module_id', 'path_id', 'quality', 'test_run_id', 'acceptance_event', 'evidence_refs')}
            row['truncated'] = 'details exceed 16KB; use evidence refs'
        rows.append(row)
    while len(json.dumps(rows, ensure_ascii=False).encode()) > 48000:
        rows.pop()
    return {'schema_version': 1, 'run_id': state['run_id'], 'sequence': len(events), 'module_id': module_id,
            'source': 'committed-ledger', 'workflow_action': 'none', 'current_code_revalidated': False, 'rows': rows,
            'total': len(matches), 'offset': offset,
            'next_offset': offset + len(rows) if offset + len(rows) < len(matches) else None,
            'retrieval': {'rows_returned': len(rows), 'rows_bytes': len(json.dumps(rows, ensure_ascii=False).encode()),
                          'excerpt_bytes_returned': sum(r.get('log_excerpt', {}).get('bytes', 0) for r in rows)},
            'display_limits': {'rows': limit, 'list_items': 8, 'string_chars': 600,
                               'excerpt_bytes': excerpt_bytes, 'rows_bytes': 48000},
            'note': '摘要供恢复/排查；历史 Green 不表示当前有效。仅所读 receipt/片段已核验，其余引用按需读取。'}


def evidence_page(root, sha256, offset=0, size=1024):
    """Explicit artifact hash, never an arbitrary filename; no media is auto-loaded."""
    root, state, events = load(root)
    evidence = AcceptanceEvidence(root, events, state['target_root'])
    ref = next(({'path': path, 'sha256': sha} for path, sha in evidence.index if sha == sha256), None)
    require(ref, 'hash is not indexed by a committed event')
    path = evidence.check(ref)
    # Text excerpts only; screenshots/video are left as verified references.
    text_suffixes = {'.log', '.json', '.jsonl', '.xml', '.md', '.txt', '.py', '.kt', '.kts', '.gradle'}
    require(Path(ref['path']).suffix.lower() in text_suffixes, 'binary/media evidence must be opened explicitly')
    return {'source': 'committed-artifact', 'ref': ref, 'archive_path': str(path),
            'accepted_event': ledger.artifact_index(events)[(ref['path'], ref['sha256'])][1],
            'historical_only': True, 'workflow_action': 'none',
            'excerpt': excerpt(path, offset, size)}


def live(root, module_id, attempt, stream='execution', offset=0, size=1024):
    from execution_capture import observe
    root, state, _ = load(root)
    require(stream in ('execution', 'stdout', 'stderr'), 'unknown stream')
    directory = checked_path(Path(attempt).absolute(), root / 'runs')
    observation = observe(root, directory / 'execution-state.json', {'run_id': state['run_id'], 'module_id': module_id})
    return {'source': 'host-live-observation', 'workflow_action': 'none', 'accepted': False,
            'observation': observation, 'excerpt': excerpt(checked_path(directory / (stream + '.log'), directory), offset, size)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('query', 'evidence', 'live'))
    parser.add_argument('--root', required=True); parser.add_argument('--module')
    for key in ('scenario-id', 'task-id', 'path-id', 'assertion-id', 'test-id', 'sha256', 'attempt'):
        parser.add_argument('--' + key)
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--offset', type=int, default=0); parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--bytes', type=int, default=1024); parser.add_argument('--stream', default='execution')
    args = parser.parse_args()
    try:
        root = Path(args.root).absolute()
        require(root.parent.name == '.sdd-runs', 'trace CLI requires .sdd-runs/<run_id>')
        if args.command == 'query':
            result = query(root, args.module, args.scenario_id, args.task_id, args.path_id, args.assertion_id,
                           args.test_id, args.history, args.offset, args.limit, args.bytes)
        elif args.command == 'evidence': result = evidence_page(root, args.sha256, args.offset, args.bytes)
        else:
            require(args.attempt and args.module, 'live requires --attempt and --module')
            result = live(root, args.module, args.attempt, args.stream, args.offset, args.bytes)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc), 'workflow_action': 'none'}, ensure_ascii=False), file=sys.stderr); return 2


if __name__ == '__main__':
    sys.exit(main())
