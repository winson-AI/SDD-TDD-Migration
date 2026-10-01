#!/usr/bin/env python3
"""Optional per-module Git checkpoint, run by the host when a module reaches DoD.

Committing each validated slice gives every later step a reviewable rollback boundary. Each MO
commits independently in the shared target worktree: only the module's accepted
code_files, with explicit paths, on the run branch sdd/<run_id> that the host created with the
user's authorization. Parallel modules serialize through one run-level lock; pre-existing dirty
paths are never staged. The receipt records each file's git blob id so the Ledger can re-verify
it against current files without running git. Never pushes, tags, resets or changes Git config.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

from contracts import Rejected, baseline, require
import run_storage


def blob_id(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def branch(run_id):
    return 'sdd/' + run_id


def _git(cwd, *args, check=True):
    proc = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise Rejected('git ' + args[0] + ' failed: ' + (proc.stderr or proc.stdout).strip())
    return proc


def commit(root, module_id, output):
    from ledger import status
    s = status(root)
    m = s['modules'][module_id]
    require(s.get('git_checkpoint'), 'git checkpoint not enabled for this run')
    require(m['phase'] == 'dod' and not m['stale'], 'checkpoint only at module DoD')
    require(m['code_files'] and baseline(m['code_files']) == m['code_baseline'], 'code changed after acceptance')
    out = Path(output)
    require(not out.exists(), 'checkpoint receipt must be new')
    top = Path(_git(s['target_root'], 'rev-parse', '--show-toplevel').stdout.strip()).resolve()
    current = _git(top, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    require(current == branch(s['run_id']), 'checkpoint requires the run branch ' + branch(s['run_id']) +
            '; host creates it from the pre-migration baseline with user authorization')
    paths = sorted(str(Path(r['path']).resolve().relative_to(top)) for r in m['code_files'])
    with run_storage.file_lock(Path(root).resolve() / 'ledger/git-checkpoint.lock'):
        _git(top, 'add', '--', *paths)
        if _git(top, 'diff', '--cached', '--quiet', 'HEAD', '--', *paths, check=False).returncode:
            message = f"sdd({s['run_id']}): {module_id} freeze {m['freeze_id'][:12]}"
            _git(top, 'commit', '-q', '--only', '-m', message, '--', *paths)
        head = _git(top, 'rev-parse', 'HEAD').stdout.strip()
        files = []
        for rel in paths:
            committed = _git(top, 'rev-parse', f'{head}:{rel}').stdout.strip()
            require(committed == blob_id(top / rel), 'committed blob differs from accepted file: ' + rel)
            files.append({'path': str(top / rel), 'blob': committed})
    receipt = {'schema_version': 1, 'producer': 'git-checkpoint', 'run_id': s['run_id'], 'module_id': module_id,
               'branch': current, 'commit': head, 'code_baseline': m['code_baseline'], 'freeze_id': m['freeze_id'],
               'files': files}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return receipt


def verify(s, m, receipt):
    """Ledger-side check: the receipt describes exactly the module's current accepted files."""
    require(s.get('git_checkpoint'), 'git checkpoint not enabled for this run')
    require(receipt.get('producer') == 'git-checkpoint' and receipt.get('run_id') == s['run_id']
            and receipt.get('module_id') == m['module_id'] and receipt.get('branch') == branch(s['run_id']),
            'checkpoint receipt context mismatch')
    commit_id = receipt.get('commit')
    require(isinstance(commit_id, str) and len(commit_id) == 40 and all(c in '0123456789abcdef' for c in commit_id),
            'checkpoint commit id required')
    require(receipt.get('code_baseline') == m['code_baseline'] == baseline(m['code_files']),
            'checkpoint does not match the accepted code baseline')
    files = receipt.get('files') or []
    require(sorted(f.get('path') for f in files) == sorted(str(Path(r['path']).resolve()) for r in m['code_files']),
            'checkpoint must cover exactly the module code files')
    for item in files:
        require(item.get('blob') == blob_id(item['path']), 'checkpoint blob differs from current file: ' + item['path'])
    return {k: receipt[k] for k in ('commit', 'branch', 'code_baseline', 'freeze_id')}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'module', 'output'): p.add_argument('--' + key, required=True)
    args = p.parse_args()
    try:
        receipt = commit(args.root, args.module, args.output)
        print(json.dumps({'commit': receipt['commit'], 'receipt': args.output}))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
