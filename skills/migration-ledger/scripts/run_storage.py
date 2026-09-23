"""Project-owned storage layout. Existing snapshots without this layout stay put."""
import json
import hashlib
import os
from pathlib import Path
import re
import tempfile
import fcntl
import math
import time
from contextlib import contextmanager

from contracts import require


class LockTimeout(TimeoutError):
    def __init__(self, path, timeout):
        self.diagnostic = {'status': 'lock-timeout', 'lock_path': str(path),
            'timeout_seconds': timeout, 'owner': 'host',
            'next_action': 'inspect lock holder liveness; retry after release; do not steal lock or cancel unrelated workers'}
        super().__init__('lock acquisition timed out: ' + str(path))


@contextmanager
def file_lock(path, timeout=None):
    """Bound acquisition only; a live transaction keeps its lock until it exits."""
    timeout = float(os.environ.get('SDD_LOCK_TIMEOUT_SECONDS', '10')) if timeout is None else float(timeout)
    require(math.isfinite(timeout) and timeout > 0, 'lock timeout must be finite and positive')
    path = checked_path(path)
    deadline = time.monotonic() + timeout
    with path.open('a+') as stream:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockTimeout(path, timeout)
                time.sleep(min(0.05, remaining))
        try:
            yield stream
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def checked_path(path, boundary=None):
    """Reject redirects before reading, writing or deleting a managed path."""
    path = Path(path).absolute()
    require(path.resolve() == path and not path.is_symlink(), 'managed path cannot redirect through a symlink')
    if boundary is not None:
        base = Path(boundary).absolute()
        require(path != base and path.is_relative_to(base), 'managed path escapes its storage boundary')
    return path


def atomic_bytes(path, content):
    """One guarded writer for managed configuration, context and projections."""
    path = checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.sdd-write-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        checked_path(path)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def layout(workspace, run_id):
    require(isinstance(run_id, str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', run_id), 'invalid run id')
    base = Path(workspace).resolve()
    values = {'workspace_root': base, 'project_root': base / '.sdd-migration',
              'runs_root': base / '.sdd-runs', 'run_root': base / '.sdd-runs' / run_id,
              'openspec_root': base / 'openspec', 'hub_root': base / 'openspec/runs' / run_id}
    for path in values.values():
        require(path.resolve() == path, 'managed storage path cannot redirect through a symlink')
    return {'schema_version': 1, 'run_id': run_id, **{k: str(v) for k, v in values.items()}}


def validate(value, root, run_id):
    require(value == layout(value['workspace_root'], run_id), 'storage layout mismatch')
    require(value['run_root'] == str(Path(root).resolve()), 'storage belongs to a different run root')


def for_state(root, state):
    # Imported lazily: project_context also uses this module during prepare.
    import project_context
    if state.get('project_context_ref'):
        snapshot = project_context.verify_snapshot(state['project_context_ref'])
        require(snapshot['run_root'] == str(Path(root).resolve()), 'context belongs to a different run root')
        require(snapshot['run_id'] == state['run_id'], 'context belongs to a different run id')
        if snapshot.get('storage_layout'):
            value = snapshot['storage_layout']
            validate(value, root, state['run_id'])
            return value
    return None


def change_root(root, state, module_id, claim=False):
    value = for_state(root, state)
    base = Path(value['openspec_root']) if value else Path(root) / 'openspec'
    path = base / 'changes' / f"{state['run_id']}-{module_id.lower()}"
    checked_path(path)
    expected = {'schema_version': 1, 'run_root': str(root), 'module_id': module_id, 'change_root': str(path)}
    owner = checked_path(Path(value['hub_root']) / 'projection-owners' / (module_id + '.json')) if value else None
    owned = owner is not None and owner.is_file()
    if owned:
        require(json.loads(owner.read_text()) == expected, 'OpenSpec projection belongs to another owner')
    if value and path.exists():
        manifest = checked_path(path / 'manifest.json')
        require(manifest.is_file() or owned, 'existing OpenSpec change has no managed manifest or ownership claim')
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text())
            except (ValueError, UnicodeError):
                require(claim and owned, 'damaged OpenSpec manifest requires verified ownership before rebuilding')
                content = manifest.read_bytes()
                saved = checked_path(Path(root) / 'reports/projection-recovery' / module_id /
                                     (hashlib.sha256(content).hexdigest() + '.manifest'), root)
                atomic_bytes(saved, content)
                # Keep the damaged original inside this run. Never trust its file
                # list for deletion; regenerate current views from accepted facts.
                data = {**expected, 'files': [], 'recovered_manifest': str(saved)}
                atomic_bytes(manifest, json.dumps(data, ensure_ascii=False, indent=2).encode())
            require(isinstance(data, dict), 'invalid OpenSpec manifest object')
            require(data.get('run_root') == str(root) and data.get('module_id') == module_id,
                    'OpenSpec change belongs to another owner')
    if claim and owner is not None and not owned:
        # Durable ownership precedes the first generated file. A missing manifest
        # after interruption can then be rebuilt from committed Ledger facts.
        from project_context import atomic, encoded
        atomic(owner, encoded(expected))
    return path


def test_output(root, state, output):
    value = for_state(root, state)
    path = Path(output).resolve()
    if value:
        base = Path(root) / 'runs'
        require(base.resolve() == base and path != base and path.is_relative_to(base),
                'execution output must be inside this run runs/ directory')
    return path


def managed_output(root, output, area='staging'):
    """Workflow outputs, also available after prepare and before init."""
    import project_context
    from contracts import file_ref
    root = checked_path(root)
    snapshot = root / 'context/snapshot.json'
    if snapshot.is_file():
        value = project_context.verify_snapshot(file_ref(snapshot))
        require(value['run_root'] == str(root), 'context belongs to a different run root')
    else:
        require((root / 'ledger/events.jsonl').is_file(), 'prepared or initialized run required')
    require(area in ('staging', 'runs'), 'invalid output area')
    return checked_path(output, checked_path(root / area))


def staging_output(root, output):
    return managed_output(root, output)
