#!/usr/bin/env python3
"""Host-owned project configuration and immutable per-run context snapshots."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True

import reuse
import context_links
import run_storage

from contracts import require, digest, file_ref, check_ref, read_json

FIELDS = {'package_root', 'legacy_root', 'target_root', 'architecture_path', 'requirements_path',
          'test_cases_path', 'project_rules_path', 'test_adapter', 'runtime', 'human_owner',
          'escalation_timeout_hours', 'module_slicing', 'defaults', 'knowledge_paths', 'reuse_sources', 'build', 'workspace_root', 'watchdog'}
DOCUMENTS = ('architecture_path', 'requirements_path', 'test_cases_path', 'project_rules_path')
BUDGETS = {'max_parallel_modules': 3, 'max_fix_rounds': 3, 'max_audit_rounds': 3, 'max_no_progress_rounds': 2}


def host(actor):
    require(actor.get('role') == 'host' and actor.get('instance_id'), 'host principal required')


def atomic(path, content):
    run_storage.atomic_bytes(path, content)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def archive(directory, data, suffix=''):
    path = run_storage.checked_path(directory / (hashlib.sha256(data).hexdigest() + suffix), directory)
    if path.exists():
        require(path.read_bytes() == data, 'context archive corrupt')
    else:
        atomic(path, data)
    return file_ref(path)


def copy_ref(directory, ref):
    path = check_ref(ref)
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == ref['sha256'], 'source changed during snapshot')
    if path.suffix.lower() in context_links.MARKDOWN:
        return context_links.freeze(directory, ref, archive)
    # Source JSON is opaque evidence, not a Ledger envelope whose inner paths
    # should be followed later against a mutable project directory.
    suffix = '.json.source' if path.suffix == '.json' else path.suffix
    return archive(directory, data, suffix)


def freeze_refs(directory, value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            return copy_ref(directory, value)
        return {key: freeze_refs(directory, item) for key, item in value.items()}
    if isinstance(value, list):
        return [freeze_refs(directory, item) for item in value]
    return value


def merge(config, patch):
    require(isinstance(patch, dict), 'configuration patch must be an object')
    result = copy.deepcopy(config)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            result[key] = merge(result.get(key, {}) if isinstance(result.get(key), dict) else {}, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate(config):
    require(isinstance(config, dict) and set(config) <= FIELDS, 'unknown project configuration field')
    if 'watchdog' in config:
        from watchdog import policy
        config['watchdog'] = policy(config['watchdog'])
    knowledge = config.get('knowledge_paths', [])
    require(isinstance(knowledge, list) and all(isinstance(p, str) and Path(p).is_absolute() for p in knowledge),
            'knowledge_paths must be absolute file paths')
    if 'knowledge_paths' in config:
        config['knowledge_paths'] = list(dict.fromkeys(str(Path(p).resolve()) for p in knowledge))
    for key in ('package_root', 'legacy_root', 'target_root', 'workspace_root') + DOCUMENTS:
        if key in config:
            require(isinstance(config[key], str) and Path(config[key]).is_absolute(), key + ' must be absolute')
            config[key] = str(Path(config[key]).resolve())
    if config.get('legacy_root') and config.get('target_root'):
        a, b = Path(config['legacy_root']), Path(config['target_root'])
        require(not (a.is_relative_to(b) or b.is_relative_to(a)), 'legacy/target overlap')
    if 'reuse_sources' in config:
        config['reuse_sources'] = reuse.normalize_sources(config['reuse_sources'], config.get('target_root'))
    defaults = config.get('defaults', {})
    require(isinstance(defaults, dict) and set(defaults) <= {'entry_mode', 'budgets', 'quality_gates', 'repair_policy'}, 'invalid defaults')
    require(defaults.get('entry_mode', 'project') == 'project', 'persistent default must remain project')
    budgets = defaults.get('budgets', {})
    require(isinstance(budgets, dict) and set(budgets) <= set(BUDGETS) | {'max_yellow_retries'}, 'invalid budgets')
    require(all(type(v) is int and v > 0 for v in budgets.values()), 'budgets must be positive integers')
    for key in ('quality_gates', 'repair_policy'):
        require(isinstance(defaults.get(key, {}), dict), 'invalid ' + key)
    if 'repair_policy' in defaults:
        require(defaults['repair_policy'].get('local_automatic_rounds', 1) == 1, 'local automatic repair must remain one round')
    for key in ('test_adapter', 'runtime', 'module_slicing', 'build'):
        if key in config: require(isinstance(config[key], dict), key + ' must be an object')
    routing = (config.get('runtime') or {}).get('model_routing')
    if routing is not None:
        import model_routing
        model_routing.validate_config(routing)
    build = config.get('build', {})
    require(set(build) <= {'argv', 'cwd', 'timeout_seconds', 'environment_ref'}, 'unknown build configuration')
    if build.get('argv') is not None:
        require(isinstance(build['argv'], list) and build['argv'] and all(isinstance(x, str) and x for x in build['argv']), 'build argv must be a nonempty string array')
    for key in ('cwd', 'environment_ref'):
        if build.get(key) is not None:
            require(isinstance(build[key], str) and Path(build[key]).is_absolute(), 'absolute build ' + key + ' required')
    if 'timeout_seconds' in build:
        require(type(build['timeout_seconds']) is int and build['timeout_seconds'] > 0, 'invalid build timeout')
    adapter = config.get('test_adapter', {})
    for key in ('executable', 'cwd', 'environment_ref'):
        if adapter.get(key) is not None:
            require(isinstance(adapter[key], str) and Path(adapter[key]).is_absolute(), 'absolute adapter ' + key + ' required')
    if 'args' in adapter:
        require(isinstance(adapter['args'], list) and all(isinstance(a, str) for a in adapter['args']), 'adapter args must be a string array')
    if 'timeout_seconds' in adapter:
        require(type(adapter['timeout_seconds']) is int and adapter['timeout_seconds'] > 0, 'invalid adapter timeout')
    require('{{' not in json.dumps(config), 'unfilled project placeholders')
    return config


def current(root):
    root = Path(root).resolve()
    path = root / 'project-context.json'
    require(path.exists(), 'project context not initialized')
    data = path.read_bytes()
    record = json.loads(data)
    history = root / 'history' / (hashlib.sha256(data).hexdigest() + '.json')
    require(history.is_file() and history.read_bytes() == data, 'project context edited outside update protocol')
    return record


def history(root):
    item = current(root); rows = []
    while item:
        rows.append(item)
        ref = item.get('previous_ref')
        if not ref: break
        previous = read_json(check_ref(ref))
        require(previous['project_id'] == item['project_id'] and previous['revision'] == item['revision'] - 1, 'broken context history')
        item = previous
    return rows


def update(root, request, actor, initialize=False):
    host(actor)
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    require(request.get('schema_version') == 1 and request.get('request_id'), 'version/request id required')
    require(isinstance(request.get('project_id'), str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', request['project_id']), 'invalid project id')
    fingerprint = digest({'request': request, 'actor': actor, 'initialize': initialize})
    with run_storage.file_lock(root / '.context.lock'):
        exists = (root / 'project-context.json').exists()
        rows = history(root) if exists else []
        for row in rows:
            if row['request_id'] == request['request_id']:
                require(row['request_hash'] == fingerprint, 'request id reused with different content/actor')
                return {'revision': row['revision'], 'duplicate': True, 'project_id': row['project_id']}
        require(initialize != exists, 'project already exists' if initialize else 'project context not initialized')
        old = rows[0] if rows else None
        require(type(request.get('expected_revision')) is int and request['expected_revision'] == (old['revision'] if old else 0), 'stale project revision')
        require(not old or old['project_id'] == request['project_id'], 'project identity cannot change')
        patch = request.get('patch')
        require(isinstance(patch, dict) and set(patch) <= FIELDS, 'unknown project patch field')
        config = validate(merge(old['config'] if old else {}, patch))
        config.setdefault('workspace_root', str(root.parent))
        require(root == Path(config['workspace_root']) / '.sdd-migration', 'project store must be <workspace_root>/.sdd-migration')
        source = copy_ref(root / 'sources', request.get('source_ref'))
        previous = file_ref(root / 'history' / (file_ref(root / 'project-context.json')['sha256'] + '.json')) if old else None
        record = {'schema_version': 1, 'project_id': request['project_id'], 'revision': request['expected_revision'] + 1,
                  'updated_at': datetime.now(timezone.utc).isoformat(), 'request_id': request['request_id'],
                  'request_hash': fingerprint, 'actor': actor, 'source_ref': source, 'previous_ref': previous,
                  'patch': patch, 'config': config}
        data = encoded(record)
        archive(root / 'history', data, '.json')
        atomic(root / 'project-context.json', data)
        return {'project_id': record['project_id'], 'revision': record['revision'], 'duplicate': False,
                'context_path': str(root / 'project-context.json')}


def verify_snapshot(ref):
    path = check_ref(ref)
    snapshot = read_json(path)
    require(snapshot.get('schema_version') == 1, 'invalid context snapshot')
    sealed = Path(snapshot['run_root']) / 'context/files' / (ref['sha256'] + '.snapshot')
    require(sealed.is_file() and sealed.read_bytes() == path.read_bytes(), 'run context edited outside prepare protocol')
    if snapshot.get('storage_layout'):
        run_storage.validate(snapshot['storage_layout'], snapshot['run_root'], snapshot['run_id'])
    def verify(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                check_ref(value)
                if value.get('link_manifest_ref'): context_links.verify(value['link_manifest_ref'])
            else:
                for item in value.values(): verify(item)
        elif isinstance(value, list):
            for item in value: verify(item)
    verify(snapshot)
    return snapshot


def prepared_input(ref):
    snapshot = verify_snapshot(ref); config = snapshot['effective_config']; sources = snapshot['source_refs']
    defaults = config.get('defaults', {})
    return {**{k: copy.deepcopy(config[k]) for k in ('workspace_root', 'package_root', 'legacy_root', 'target_root', 'test_adapter',
                'runtime', 'human_owner', 'escalation_timeout_hours', 'module_slicing', 'reuse_sources') if k in config},
            'dimension_slicing_required': True, 'context_readiness_required': True, 'split_testing_required': True, 'build': config.get('build', {}), 'reuse_required': True, 'schema_version': 1, 'run_id': snapshot['run_id'], 'entry_mode': snapshot['entry_mode'],
            'module_name': snapshot['module_name'], 'project_context_ref': ref, 'project_sources': sources,
            'run_root': snapshot['run_root'], 'storage_layout': snapshot.get('storage_layout'),
            'new_architecture': sources['architecture_path'], 'document_link_warnings': context_links.mapping(snapshot)[1],
            'global_spec': None, 'global_test_cases': [],
            'requirement_ids': [], 'global_test_paths': [],
            'budgets': {**BUDGETS, **defaults.get('budgets', {})}, 'quality_gates': defaults.get('quality_gates', {}),
            'repair_policy': defaults.get('repair_policy', {'local_automatic_rounds': 1}),
            'custom_rules_path': sources.get('project_rules_path', {}).get('path')}


def prepare(root, run_root, request, actor):
    """One project/run_id maps to one immutable location, including on restart."""
    host(actor)
    rid = request.get('run_id')
    require(isinstance(rid, str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', rid), 'invalid run id')
    root = Path(root).resolve()
    require(root.is_dir(), 'project context not initialized')
    with run_storage.file_lock(root / '.context.lock'):
        record = current(root)
        require(request.get('project_id') == record['project_id'], 'wrong project context')
        require('workspace_root' not in request.get('overrides', {}), 'workspace_root is project-owned, not a run override')
        storage = run_storage.layout(record['config'].get('workspace_root', root.parent), rid)
        index = root / 'runs' / (rid + '.json')
        registered = read_json(index) if index.exists() else None
        chosen = Path(run_root).resolve() if run_root else Path(registered['run_root'] if registered else storage['run_root'])
        if registered:
            snap = verify_snapshot(registered['project_context_ref'])
            require(registered['project_id'] == record['project_id'] and snap['project_id'] == record['project_id']
                    and snap['run_id'] == rid and snap['run_root'] == str(chosen)
                    and registered['run_root'] == str(chosen), 'run already registered at a different root')
        elif not (chosen / 'context/snapshot.json').exists():
            require(str(chosen) == storage['run_root'], 'new run root must be <workspace_root>/.sdd-runs/<run_id>')
        pending = run_storage.checked_path(root / 'preparations' / (rid + '.json'))
        receipt = read_json(pending) if pending.exists() else None
        if receipt:
            require(receipt['run_root'] == str(chosen) and receipt['project_id'] == record['project_id'],
                    'preparation belongs to a different project or run root')
        if not (chosen / 'context/snapshot.json').exists():
            preflight(record, request)
            check_owner(root, chosen, request, storage, record)
            receipt = {'schema_version': 1, 'project_id': record['project_id'], 'run_id': rid,
                       'run_root': str(chosen), 'phase': 'preparing',
                       'request_hash': digest({'request': request, 'actor': actor, 'project_root': str(root)}),
                       'failures': receipt.get('failures', []) if receipt else [],
                       'next_action': 'retry-prepare'}
            atomic(pending, encoded(receipt))
        try:
            result = _prepare(root, chosen, request, actor, storage)
            if not registered:
                atomic(index, encoded({'schema_version': 1, 'project_id': record['project_id'], 'run_id': rid,
                    'run_root': str(chosen), 'project_context_ref': result['project_context_ref']}))
            if receipt and receipt['phase'] != 'prepared':
                receipt.update(phase='prepared', next_action='initialize-or-resume-ledger')
                atomic(pending, encoded(receipt))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            if receipt and receipt['phase'] != 'prepared':
                receipt.update(phase='failed', next_action='correct-input-or-storage-and-retry-prepare')
                receipt['failures'].append({'reason': str(exc), 'request_hash': receipt['request_hash']})
                atomic(pending, encoded(receipt))
            raise
        result['run_root'] = str(chosen)
        return result


def preflight(record, request):
    """Validate available inputs before creating a run or an OpenSpec namespace."""
    require(request.get('schema_version') == 1 and request.get('request_id'), 'version/request id required')
    mode, name = request.get('entry_mode', 'project'), request.get('module_name')
    require(mode in ('project', 'single-module'), 'invalid entry mode')
    require((mode == 'single-module' and isinstance(name, str) and bool(name.strip())) or
            (mode == 'project' and name is None), 'single-module requires a name; project has no module name')
    if 'expected_revision' in request:
        require(request['expected_revision'] == record['revision'], 'stale project revision')
    overrides = request.get('overrides', {})
    require(isinstance(overrides, dict) and set(overrides) <= FIELDS, 'unknown override field')
    effective = validate(merge(record['config'], overrides))
    for key in ('legacy_root', 'target_root'):
        require(key in effective and Path(effective[key]).is_dir(), 'missing directory: ' + key)
    require(effective.get('architecture_path'), 'architecture_path required before prepare')
    reuse.normalize_sources(effective.get('reuse_sources', []), effective['target_root'], existing=True)
    for path in [effective[k] for k in DOCUMENTS if effective.get(k)] + effective.get('knowledge_paths', []):
        file_ref(path)
    for key in ('build', 'test_adapter'):
        if effective.get(key, {}).get('environment_ref'): file_ref(effective[key]['environment_ref'])
    def verify(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                check_ref(value)
            else:
                for item in value.values(): verify(item)
        elif isinstance(value, list):
            for item in value: verify(item)
    verify(effective); verify(record['config'])
    check_ref(request.get('source_ref')); check_ref(record['source_ref'])


def check_owner(root, run_root, request, storage, record):
    owner = run_storage.checked_path(Path(storage['hub_root']) / 'owner.json')
    ownership = {'schema_version': 1, 'project_id': record['project_id'], 'run_id': request['run_id'],
                 'project_root': str(root), 'run_root': str(run_root)}
    if owner.exists():
        require(read_json(owner) == ownership, 'OpenSpec run namespace already owned')
    else:
        changes = run_storage.checked_path(Path(storage['openspec_root']) / 'changes')
        require(not any(re.fullmatch(re.escape(request['run_id']) + r'-m[0-9]{3,}', p.name)
                        for p in changes.glob('*')), 'existing OpenSpec changes require an owned run namespace')
    return owner, ownership


def _prepare(root, run_root, request, actor, storage):
    host(actor)
    require(request.get('schema_version') == 1 and request.get('request_id'), 'version/request id required')
    require(isinstance(request.get('run_id'), str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', request['run_id']), 'invalid run id')
    mode = request.get('entry_mode', 'project'); name = request.get('module_name')
    require(mode in ('project', 'single-module'), 'invalid entry mode')
    require((mode == 'single-module' and isinstance(name, str) and bool(name.strip())) or
            (mode == 'project' and name is None), 'single-module requires a name; project has no module name')
    root = Path(root).resolve(); run_root = Path(run_root).resolve()
    require(root != run_root and not root.is_relative_to(run_root) and not run_root.is_relative_to(root), 'project store and run root must be separate')
    run_root.mkdir(parents=True, exist_ok=True)
    # Same lock as Ledger prevents preparation racing with init.
    with run_storage.file_lock(run_root / '.ledger.lock'):
        path = run_root / 'context/snapshot.json'
        fingerprint = digest({'request': request, 'actor': actor, 'project_root': str(root)})
        if path.exists():
            ref = file_ref(path); snap = verify_snapshot(ref)
            require(snap['project_id'] == request['project_id'], 'context belongs to a different project')
            require(snap['run_id'] == request['run_id'], 'context belongs to a different run id')
            require(snap['run_root'] == str(run_root), 'context belongs to a different run root')
            require(snap['request_hash'] == fingerprint, 'run context already frozen; use a new run')
            return {'project_context_ref': ref, 'input': prepared_input(ref), 'duplicate': True}
        require(not (run_root / 'ledger/events.jsonl').exists(), 'cannot attach context after run initialization')
        record = current(root)
        require(request.get('project_id') == record['project_id'], 'wrong project context')
        if 'expected_revision' in request:
            require(request['expected_revision'] == record['revision'], 'stale project revision')
        overrides = request.get('overrides', {})
        require(isinstance(overrides, dict) and set(overrides) <= FIELDS, 'unknown override field')
        effective = validate(merge(record['config'], overrides))
        for key in ('legacy_root', 'target_root'):
            require(key in effective and Path(effective[key]).is_dir(), 'missing directory: ' + key)
        require(effective.get('architecture_path'), 'architecture_path required before prepare')
        reuse.normalize_sources(effective.get('reuse_sources', []), effective['target_root'], existing=True)
        owner, ownership = check_owner(root, run_root, request, storage, record)
        if not owner.exists():
            atomic(owner, encoded(ownership))
        files = run_root / 'context/files'
        sources = {key: copy_ref(files, file_ref(effective[key])) for key in DOCUMENTS if effective.get(key)}
        if 'knowledge_paths' in effective:
            sources['knowledge_paths'] = [copy_ref(files, file_ref(path)) for path in effective['knowledge_paths']]
        source_paths = {key: copy.deepcopy(effective[key]) for key in DOCUMENTS + ('knowledge_paths',) if effective.get(key)}
        effective = freeze_refs(files, effective)
        for key, source in sources.items():
            effective[key] = [ref['path'] for ref in source] if isinstance(source, list) else source['path']
        adapter = effective.get('test_adapter', {})
        if adapter.get('environment_ref'):
            sources['test_environment'] = copy_ref(files, file_ref(adapter['environment_ref']))
            adapter['environment_ref'] = sources['test_environment']['path']
        build = effective.get('build', {})
        if build.get('environment_ref'):
            sources['build_environment'] = copy_ref(files, file_ref(build['environment_ref']))
            build['environment_ref'] = sources['build_environment']['path']
        snapshot = {'schema_version': 1, 'project_id': record['project_id'], 'project_revision': record['revision'],
                    'project_revision_hash': digest(record), 'project_config': freeze_refs(files, record['config']), 'effective_config': effective,
                    'run_id': request['run_id'], 'run_root': str(run_root), 'entry_mode': mode, 'module_name': name,
                    'request_hash': fingerprint, 'source_refs': sources, 'source_paths': source_paths,
                    'request_source_ref': copy_ref(files, request.get('source_ref')),
                    'config_source_ref': copy_ref(files, record['source_ref']),
                    'created_at': datetime.now(timezone.utc).isoformat()}
        snapshot.update(storage_layout=storage, storage_owner_ref=file_ref(owner))
        data = encoded(snapshot)
        archive(files, data, '.snapshot')
        atomic(path, data)
        ref = file_ref(path)
        return {'project_context_ref': ref, 'input': prepared_input(ref), 'duplicate': False}


def bind_run(ref, run_root, run_id, payload):
    snapshot = verify_snapshot(ref)
    require(snapshot['run_id'] == run_id and snapshot['run_root'] == str(Path(run_root).resolve()), 'context belongs to a different run')
    config = snapshot['effective_config']
    for key in ('legacy_root', 'target_root'):
        require(str(Path(payload[key]).resolve()) == config[key], 'run/config mismatch: ' + key)
    require(payload.get('entry_mode', 'project') == snapshot['entry_mode'] and
            payload.get('module_name') == snapshot['module_name'], 'run/config scope mismatch')
    require(payload.get('new_architecture') == snapshot['source_refs']['architecture_path'], 'run must use frozen architecture')
    if 'reuse_sources' in payload:
        require(payload['reuse_sources'] == config.get('reuse_sources', []), 'run/config reuse sources mismatch')
    budgets = config.get('defaults', {}).get('budgets', {})
    for key, fallback in BUDGETS.items():
        require(payload.get(key, fallback) == budgets.get(key, fallback), 'run/config budget mismatch: ' + key)
    require(payload.get('split_testing_required', True) is True, 'prepared run requires split testing')
    if 'build' in payload:
        require(payload['build'] == config.get('build', {}), 'run/config build mismatch')
    require(payload.get('dimension_slicing_required', True) is True, 'prepared run requires dimension slicing')
    require(payload.get('context_readiness_required', True) is True, 'prepared run requires context readiness')
    return {'dimension_slicing_required': True, 'context_readiness_required': True, 'split_testing_required': True, 'build': copy.deepcopy(config.get('build', {})), 'reuse_sources': copy.deepcopy(config.get('reuse_sources', [])), 'reuse_required': True,
            'project_context_ref': ref, 'project_id': snapshot['project_id'],
            'project_revision': snapshot['project_revision'], 'module_name': snapshot['module_name']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'update', 'show', 'history', 'prepare'))
    parser.add_argument('--root', default=str(Path.cwd() / '.sdd-migration'))
    parser.add_argument('--request'); parser.add_argument('--host-context'); parser.add_argument('--run-root')
    args = parser.parse_args()
    try:
        if args.command in ('show', 'history'):
            result = current(args.root) if args.command == 'show' else history(args.root)
        else:
            require(args.request and args.host_context, 'request and host context required')
            req, actor = read_json(args.request), read_json(args.host_context)
            if args.command == 'prepare':
                result = prepare(args.root, args.run_root, req, actor)
            else:
                result = update(args.root, req, actor, initialize=args.command == 'init')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except run_storage.LockTimeout as exc:
        print(json.dumps(exc.diagnostic, ensure_ascii=False), file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
