"""Storage rules shared by native writers and CLI entrypoints."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'migration-ledger/scripts'))
from runner_storage import harmony_output
from run_storage import checked_path


def output_path(path=None, *, default=None, boundary=None):
    """Relative/default outputs require a runner; explicit outputs must be managed."""
    runner = os.environ.get('SDD_RUNNER_DIR')
    root = None
    if runner:
        runner = harmony_output(None, runner)
        root = next(p for p in runner.parents if p.parent.name == '.sdd-runs')
    path = path if path is not None else default
    if path is None:
        raise ValueError('managed output path required')
    path = Path(path)
    if not path.is_absolute():
        if runner is None:
            raise ValueError('relative/default output requires SDD_RUNNER_DIR; supply an absolute managed output')
        path = runner / path
    path = harmony_output(root, path)
    run = next(p for p in path.parents if p.parent.name == '.sdd-runs')
    relative = path.relative_to(run / 'runs/harmony').parts
    if len(relative) < 2 or relative[0] not in ('automation', 'sandbox'):
        raise ValueError('output must belong to a Harmony automation attempt or sandbox request')
    if boundary is not None:
        checked_path(path, output_path(boundary))
    return path


def temp_directory(anchor=None):
    """Never use the system temporary directory, even outside the CLI."""
    runner = os.environ.get('SDD_RUNNER_DIR')
    if runner:
        directory = output_path(Path(runner) / 'temp')
    elif anchor is not None:
        directory = output_path(output_path(anchor).parent / 'temp')
    else:
        raise ValueError('temporary output requires a managed runner or explicit managed output')
    directory.mkdir(parents=True, exist_ok=True)
    return directory
