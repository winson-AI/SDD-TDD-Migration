#!/usr/bin/env python3
"""Optional write-scope evidence for code workers, gathered by the host from the target Git worktree.

A worker's result lists the files it claims to have written; this records what actually changed.
`baseline` snapshots the dirty paths when an Implementer/Fixer is dispatched, `delta` records the
paths that changed since, each with its git blob id. The Ledger then requires every change inside
the module's write scope to be declared and every change outside it to belong to another module's
authorised work. Read-only: never stages, commits or reverts anything.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

from contracts import Rejected, check_ref, file_ref, read_json, require
from git_checkpoint import blob_id


def managed_roots(run_root):
    """Workflow assets are not target code even when the workspace lives inside the target repository."""
    run_root = Path(run_root).resolve()
    roots = [run_root]
    if run_root.parent.name == '.sdd-runs':
        workspace = run_root.parent.parent
        roots += [workspace / '.sdd-runs', workspace / '.sdd-migration', workspace / 'openspec']
    return roots


def _dirty(target_root, exclude=()):
    """Tracked modifications, deletions, renames and untracked files as {absolute path: blob id or None}."""
    proc = subprocess.run(['git', '-C', str(target_root), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if proc.returncode:
        raise Rejected('write scope check needs a Git worktree: ' + proc.stderr.strip())
    top = Path(proc.stdout.strip()).resolve()
    out = subprocess.run(['git', '-C', str(top), 'status', '--porcelain', '-z', '--untracked-files=all'],
                         capture_output=True, text=True)
    if out.returncode:
        raise Rejected('git status failed: ' + out.stderr.strip())
    tokens, paths, i = out.stdout.split('\0'), {}, 0
    while i < len(tokens):
        entry = tokens[i]; i += 1
        if not entry:
            continue
        names = [entry[3:]]
        if entry[0] in 'RC':  # the original path follows as its own token
            names.append(tokens[i]); i += 1
        for name in names:
            path = top / name
            if any(path.resolve().is_relative_to(root) for root in exclude):
                continue
            paths[str(path)] = blob_id(path) if path.is_file() else None
    return paths


def _assignment(root, module_id, assignment_id):
    from ledger import status
    s = status(root)
    require(s.get('write_scope_check'), 'write scope check not enabled for this run')
    a = s['modules'][module_id]['assignments'].get(assignment_id) or {}
    require(not a.get('closed', True) and a.get('role') in ('implementer', 'fixer'), 'active code assignment required')
    return s


def _write(output, receipt):
    out = Path(output)
    require(not out.exists(), 'write scope receipt must be new')
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return receipt


def baseline(root, module_id, assignment_id, output):
    s = _assignment(root, module_id, assignment_id)
    return _write(output, {'schema_version': 1, 'producer': 'write-scope', 'kind': 'baseline', 'run_id': s['run_id'],
                           'module_id': module_id, 'assignment_id': assignment_id,
                           'dirty': _dirty(s['target_root'], managed_roots(root))})


def delta(root, module_id, assignment_id, baseline_ref, output):
    s = _assignment(root, module_id, assignment_id)
    base = read_json(baseline_ref if isinstance(baseline_ref, (str, Path)) else check_ref(baseline_ref))
    require(base.get('producer') == 'write-scope' and base.get('kind') == 'baseline'
            and base.get('assignment_id') == assignment_id and base.get('module_id') == module_id,
            'baseline belongs to another assignment')
    before, now = base['dirty'], _dirty(s['target_root'], managed_roots(root))
    changed = [{'path': path, 'blob': blob} for path, blob in sorted(now.items()) if before.get(path, '') != blob]
    return _write(output, {'schema_version': 1, 'producer': 'write-scope', 'kind': 'delta', 'run_id': s['run_id'],
                           'module_id': module_id, 'assignment_id': assignment_id, 'changed': changed})


def verify(s, m, assignment, result, receipt):
    """Ledger-side: declared inside the module's scope, authorised outside it, and still current."""
    require(receipt.get('producer') == 'write-scope' and receipt.get('kind') == 'delta' and receipt.get('run_id') == s['run_id']
            and receipt.get('module_id') == m['module_id'] and receipt.get('assignment_id') == assignment['assignment_id'],
            'write scope receipt context mismatch')
    declared = {str(Path(r['path']).resolve()) for r in result.get('code_files', [])}

    def inside(path, module):
        return any(Path(path).resolve().is_relative_to(Path(root).resolve()) for root in module['write_paths'])

    for item in receipt.get('changed') or []:
        path, blob = item.get('path'), item.get('blob')
        require(isinstance(path, str) and (blob_id(path) if Path(path).is_file() else None) == blob,
                'write scope receipt is stale: ' + str(path))
        resolved = str(Path(path).resolve())
        if inside(path, m):
            require(blob is None or resolved in declared, 'undeclared change inside module scope: ' + path)
            continue
        authorised = False
        for other_id, other in s['modules'].items():
            if other_id == m['module_id'] or not inside(path, other):
                continue
            working = any(not a.get('closed') and a.get('role') in ('implementer', 'fixer') for a in other['assignments'].values())
            accepted = blob is not None and any(str(Path(r['path']).resolve()) == resolved and r['sha256'] == file_ref(path)['sha256']
                                                for r in other.get('code_files', []))
            authorised = authorised or working or accepted
        require(authorised, 'write outside module scope: ' + path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('baseline', 'delta'))
    for key in ('root', 'module', 'assignment', 'output'): p.add_argument('--' + key, required=True)
    p.add_argument('--baseline')
    args = p.parse_args()
    try:
        if args.command == 'baseline':
            baseline(args.root, args.module, args.assignment, args.output)
        else:
            require(args.baseline, '--baseline receipt required for delta')
            delta(args.root, args.module, args.assignment, args.baseline, args.output)
        print(json.dumps({'receipt': args.output}))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
