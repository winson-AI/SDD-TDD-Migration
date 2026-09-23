"""Materialize one shared Harmony configuration per run; never emit credentials."""
import json
import base64
import hashlib
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-ledger/scripts'))
from runner_storage import harmony_output
from run_storage import checked_path, atomic_bytes, file_lock
from contracts import require

ENGINE = Path(__file__).resolve().parents[1] / 'runtime/harmony'
FILES = ('config.json', '.env', 'config.native.yaml')


def private_json(path, value):
    atomic_bytes(path, (json.dumps(value, sort_keys=True) + '\n').encode())
    os.chmod(path, 0o600)


def validate_bundle(files):
    require(set(files) == set(FILES) and all(files[name] is not None for name in FILES[:2]),
            'incomplete Harmony environment bundle')
    require(isinstance(json.loads(files['config.json']), dict), 'Harmony configuration must be a JSON object')


def manifest_for(root, files):
    return {'schema_version': 1, 'run_root': str(root), 'status': 'ready',
            'files': {name: hashlib.sha256(data).hexdigest() if data is not None else None
                      for name, data in files.items()}}


def prepare_environment(root, config_source=None, env_source=None):
    directory = harmony_output(root, Path(root) / 'runs/harmony/sandbox/environment', 'sandbox')
    project = directory.parents[4].parent / '.sdd-migration/harmony'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    lock = checked_path(directory / '.prepare.lock', directory)
    with file_lock(lock):
        root = directory.parents[3]
        targets = {name: checked_path(directory / name, directory) for name in FILES}
        manifest = checked_path(directory / 'manifest.json', directory)
        preparation = checked_path(directory / 'preparation.json', directory)
        if manifest.exists():
            files = {name: path.read_bytes() if path.exists() else None for name, path in targets.items()}
            validate_bundle(files)
            require(json.loads(manifest.read_text()) == manifest_for(root, files),
                    'run sandbox environment changed; restore its frozen files or use a new run')
        else:
            if preparation.exists():
                draft = json.loads(preparation.read_text())
                require(draft.get('schema_version') == 1 and draft.get('status') == 'preparing' and
                        draft.get('run_root') == str(root), 'invalid Harmony environment preparation')
                files = {name: base64.b64decode(data, validate=True) if data is not None else None
                         for name, data in draft['files'].items()}
                validate_bundle(files)
                require(draft.get('manifest') == manifest_for(root, files), 'Harmony preparation digest mismatch')
            else:
                existing = {name: path.exists() for name, path in targets.items()}
                if any(existing.values()):
                    # Legacy complete environments are adopted as they stand, never
                    # supplemented from mutable references. Partial ones need review.
                    require(all(existing[name] for name in FILES[:2]),
                            'incomplete legacy environment; Host review or a new run required')
                    files = {name: path.read_bytes() if existing[name] else None for name, path in targets.items()}
                else:
                    inputs = [('config.json', config_source, project / 'config.json', ENGINE / 'config.default.json'),
                              ('.env', env_source, project / '.env', ENGINE / '.env.example')]
                    files = {name: (Path(explicit).resolve() if explicit else preferred if preferred.is_file() else fallback).read_bytes()
                             for name, explicit, preferred, fallback in inputs}
                    native = project / 'config.native.yaml'
                    files['config.native.yaml'] = native.read_bytes() if native.is_file() else None
                validate_bundle(files)
                private_json(preparation, {'schema_version': 1, 'status': 'preparing', 'run_root': str(root),
                    'files': {name: base64.b64encode(data).decode() if data is not None else None for name, data in files.items()},
                    'manifest': manifest_for(root, files)})
            # Existing partial output must match the frozen transaction before any
            # missing member is installed. Never overwrite a foreign/tampered file.
            for name, path in targets.items():
                require(not path.exists() or path.read_bytes() == files[name], 'partial environment differs from frozen preparation')
            for name, explicit in (('config.json', config_source), ('.env', env_source)):
                if explicit:
                    require(Path(explicit).read_bytes() == files[name],
                            'run sandbox configuration already exists; use a new run for changed configuration')
            for name, path in targets.items():
                if files[name] is not None and not path.exists(): atomic_bytes(path, files[name])
            private_json(manifest, manifest_for(root, files))
        for name, explicit in (('config.json', config_source), ('.env', env_source)):
            if explicit:
                require(Path(explicit).read_bytes() == files[name],
                        'run sandbox configuration already exists; use a new run for changed configuration')
        for path in targets.values():
            if path.exists(): os.chmod(path, 0o600)
        preparation.unlink(missing_ok=True)
    return directory / 'config.json', directory / '.env'


def load_environment(path):
    from dotenv import load_dotenv
    # Explicit host environment remains supported; never search the target cwd.
    load_dotenv(Path(path).resolve(), override=False)
