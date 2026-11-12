"""Execution-local scratch/cache and Harmony CLI storage (including standalone runs)."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sys
import tempfile

from contracts import Rejected, check_ref, digest, file_ref, require
from run_storage import checked_path, layout


def gradle_command(argv):
    return any(Path(arg).name in ('gradle', 'gradlew', 'gradle.bat', 'gradlew.bat') for arg in argv[:2])


def gradle_seed_sources():
    seed = os.environ.get('SDD_GRADLE_CACHE_SEED', str(Path.home() / '.gradle'))
    return {relative: (Path(seed) / relative).resolve() for relative in ('wrapper/dists', 'caches/modules-2')
            if seed and (Path(seed) / relative).is_dir()}


def build_command(argv, directory, unit_report=False):
    """Extend argv only with deterministic storage and frozen unit-report policy."""
    if not gradle_command(argv): return list(argv)
    require(not any(a.startswith(('--project-cache-dir', '--gradle-user-home', '-g'))
                    for a in argv), 'freeze Gradle task arguments without storage flags; host binds runner directories')
    directory = Path(directory).resolve()
    command = [*argv, '--project-cache-dir', str(directory / 'cache/project-gradle'),
               '--gradle-user-home', str(directory / 'cache/gradle')]
    # Includes KMP/native test tasks, which need not subclass Gradle's JVM Test.
    if unit_report:
        command += ['--rerun-tasks', '--no-build-cache']
    return command


def revalidation_snapshot(s, root):
    """Scan shared target and host inputs once for one receipt comparison."""
    from write_scope import managed_roots

    target = Path(s['target_root']).resolve()
    context = s.get('project_context_ref')
    if not context:
        return None
    try:
        check_ref(context)
        excluded = set(managed_roots(root))
        files = {}
        pending = [target]
        while pending:
            for path in pending.pop().iterdir():
                if path.name == '.git' or path in excluded:
                    continue
                if path.is_symlink():
                    return None
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    files[str(path.relative_to(target))] = file_ref(path)['sha256']
                else:
                    return None
        return {'context': context, 'package_sha': s.get('package_sha'), 'host': list(os.uname()),
                'environment': dict(os.environ), 'target': files}
    except (OSError, Rejected, TypeError, ValueError):
        return None


def revalidation_inputs(s, root, cwd, argv, *, snapshot=None):
    """Fingerprint host inputs for possible reuse of an accepted build or unit command."""
    target = Path(s['target_root']).resolve()
    if not s.get('project_context_ref') or not Path(cwd).resolve().is_relative_to(target):
        return None
    if gradle_command(argv) and gradle_seed_sources():
        return None  # Mutable cache files outside the target manifest are not frozen inputs.
    try:
        shared = snapshot() if snapshot else revalidation_snapshot(s, root)
        if shared is None:
            return None
        executable = Path(argv[0])
        if not executable.is_absolute():
            executable = Path(cwd) / executable if '/' in argv[0] else shutil.which(argv[0])
        tools = [file_ref(executable)]
        tools.extend(file_ref(Path(cwd) / arg) for arg in argv[1:] if (Path(cwd) / arg).is_file())
        return digest({**shared, 'tools': tools})
    except (OSError, Rejected, TypeError, ValueError):
        return None


def harmony_output(root, output, area=None):
    path = Path(output).absolute()
    roots = [p for p in path.parents if p.parent.name == '.sdd-runs']
    require(len(roots) == 1, 'output requires <workspace>/.sdd-runs/<run_id>/runs/harmony/')
    output_root = roots[0]
    raw_root = Path(root).absolute() if root else output_root
    require(raw_root.parent.name == '.sdd-runs', 'Harmony root must be .sdd-runs/<run_id>')
    storage = layout(raw_root.parent.parent, raw_root.name)
    root = Path(storage['run_root'])
    other = layout(output_root.parent.parent, output_root.name)
    require(other['run_root'] == str(root), 'output outside selected run')
    path = root / path.relative_to(output_root)
    snapshot = root / 'context/snapshot.json'
    if snapshot.exists():
        import project_context
        from contracts import file_ref
        value = project_context.verify_snapshot(file_ref(snapshot))
        require(value['run_root'] == str(root), 'context belongs to a different run root')
    base = root / 'runs/harmony'
    if area:
        require(area in ('automation', 'sandbox'), 'unknown Harmony output area')
        base /= area
    return checked_path(path, base)


def environment(directory):
    """For subprocesses: never mutate the parent host environment."""
    directory = checked_path(directory)
    temp = checked_path(directory / 'temp'); temp.mkdir(parents=True, exist_ok=True)
    cache = checked_path(directory / 'cache'); cache.mkdir(parents=True, exist_ok=True)
    # SDD_GRADLE_CACHE_SEED names a Gradle user home whose read-mostly subtrees - wrapper distributions and the dependency
    # cache - a runner-local cold cache shares, so a build survives repositories it cannot reach. By default the host user's
    # ~/.gradle seeds it; an empty value turns the seed off. Frozen argv, receipts and integrity guards are untouched.
    for relative, source in gradle_seed_sources().items():
        destination = cache / 'gradle' / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(source)
    env = dict(os.environ)
    env.update({k: str(temp) for k in ('TMPDIR', 'TMP', 'TEMP')})
    env.update(PYTHONDONTWRITEBYTECODE='1', XDG_CACHE_HOME=str(cache),
               UV_CACHE_DIR=str(cache / 'uv'), PIP_CACHE_DIR=str(cache / 'pip'),
               GRADLE_USER_HOME=str(cache / 'gradle'),
               HYPIUM_MCP_OUTPUT_DIR=str(directory / 'sdk'),
               HYPIUM_MCP_WORKING_DIR=str(directory), SDD_RUNNER_DIR=str(directory))
    return env


def cleanup(directory):
    """Only delete this execution's scratch; retain failures inside its run."""
    temp = Path(directory) / 'temp'
    try:
        checked_path(temp, directory)
        if temp.exists(): shutil.rmtree(temp)
        return {'path': str(temp), 'status': 'removed'}
    except (OSError, ValueError) as exc:
        return {'path': str(temp), 'status': 'retained-in-run', 'reason': type(exc).__name__}


@contextmanager
def scope(directory):
    """For a dedicated runner process, before importing device/LLM SDKs."""
    directory = checked_path(directory)
    old_env, old_temp, old_cwd = dict(os.environ), tempfile.tempdir, Path.cwd()
    old_bytecode = sys.dont_write_bytecode
    try:
        os.environ.update(environment(directory))
        tempfile.tempdir = os.environ['TMPDIR']
        sys.dont_write_bytecode = True
        os.chdir(directory)
        yield
    finally:
        os.chdir(old_cwd)
        # Cleanup failure is retained in-run; never silently moves to system /tmp.
        from run_storage import atomic_bytes
        import json
        try:
            atomic_bytes(directory / 'cleanup.json', (json.dumps(cleanup(directory)) + '\n').encode())
        finally:
            os.environ.clear(); os.environ.update(old_env)
            tempfile.tempdir, sys.dont_write_bytecode = old_temp, old_bytecode
