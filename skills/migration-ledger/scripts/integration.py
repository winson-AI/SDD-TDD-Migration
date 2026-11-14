"""Wave integration verifies GLOBAL PATHs as soon as their execution inputs are ready."""
import copy

from contracts import Rejected, check_ref, digest, read_json, require, validate_result

OPS = {'integration-assign', 'integration-submit', 'integration-revoke'}


def owners(s, path):
    """The leaves that hold a global path's case: the global plan's case owners, else the leaves registered on it."""
    held = (s.get('global_plan') or {}).get('content', {}).get('case_owners', {}).get(path.get('case_id'))
    if held is None:
        held = [mid for mid, m in s['modules'].items() if path.get('case_id') in m.get('case_ids', [])]
    return sorted(mid for mid in held if mid in s['modules'])


def owner_baselines(s, path):
    return {mid: s['modules'][mid].get('code_baseline') for mid in owners(s, path)}


def scoped(s, path):
    from test_validation import managed_visual_environment
    return bool(path.get('build_binding') and managed_visual_environment(s, path))


def build_artifacts(s, path):
    binding = path.get('build_binding') or {}
    owner = s['modules'].get(binding.get('module_id'), {})
    build = owner.get('results', {}).get(binding.get('path_id'), {})
    if (any(p.get('path_id') == binding.get('path_id') and p.get('kind') == 'build'
            for p in (owner.get('plan') or {}).get('paths', []))
            and build.get('quality') == 'green-passed' and not build.get('stale')
            and build.get('code_baseline') == owner.get('code_baseline') and not owner.get('stale')):
        return [r for r in build.get('build_artifacts', []) if r in owner.get('build_artifacts', [])]
    return []


def module_ids(s, path):
    from ledger import dependency_closure
    return dependency_closure(s, [*owners(s, path), path['build_binding']['module_id']])


def device_inputs(s, path):
    """The device portion of the inputs used by the built-in GLOBAL automation runner."""
    from execute_test import builtin_platform
    from project_context import device_inputs as configured_devices

    if path.get('kind', 'automation') != 'automation' or not (platform := builtin_platform(s, path)):
        return None
    device = s['test_adapter']['device']
    return {key: config for key, config in configured_devices(device).items()
            if key == platform or platform == 'harmony' and key.startswith('harmony-')}


def affected_by_device(s, path, devices):
    if not devices:
        return False
    if scoped(s, path):
        from project_context import path_device
        return path_device(path) in devices
    bound = device_inputs(s, path)
    return bound is None or bool(devices.intersection(bound))


def inputs(s, path, code_baseline=None, *, legacy=False):
    """A managed visual path consumes its named build. Opaque commands may inspect the whole project."""
    if scoped(s, path):
        from context_readiness import verify_refs
        from ledger import current as check_module
        from test_validation import managed_visual_artifacts
        verify_refs(path)
        mids = module_ids(s, path)
        refs = managed_visual_artifacts(s, path, build_artifacts(s, path))
        require(refs, 'managed integration build or visual environment unavailable')
        for mid in mids:
            m = s['modules'][mid]
            require(m['phase'] == 'completed' and not m.get('stale'), 'integration input module unsettled')
            check_module(m)
        return digest({'path': path, 'build': refs,
                       'modules': {mid: {k: s['modules'][mid].get(k) for k in ('code_baseline', 'freeze_id')} for mid in mids}})
    common = {'path': path, 'baseline': code_baseline,
              'modules': {mid: {k: m.get(k) for k in ('freeze_id', 'build_artifacts')} for mid, m in s['modules'].items()}}
    if not legacy and (device := device_inputs(s, path)) is not None:
        platform = path['platform']
        adapter = s['test_adapter']
        web_config = (s.get('target_preview') or {}).get('web_main_config')
        if platform == 'web' and web_config:
            check_ref(web_config)
        runtime = ({'web_config': web_config} if platform == 'web'
                   else {'environment_revision': s.get('harmony_environment_revision')})
        return digest({**common, 'device': device, 'adapter': {k: v for k, v in adapter.items() if k != 'device'},
                       'runtime': runtime, 'package_sha': s.get('package_sha')})
    return digest({**common, 'test_adapter': s.get('test_adapter'), 'environment_revision': s.get('harmony_environment_revision')})


def same_inputs(s, path, previous, code_baseline, expected=None):
    if not previous or previous.get('stale'):
        return False
    if 'integration_inputs' in previous:
        try:
            expected = expected or inputs(s, path, code_baseline)
            return (expected in (previous['integration_inputs'], previous.get('device_continuation_inputs'))
                    or device_inputs(s, path) is not None
                    and previous['integration_inputs'] == inputs(s, path, code_baseline, legacy=True))
        except (Rejected, OSError, KeyError):
            return False
    # Older receipts carry the whole baseline. An owner match alone cannot prove what a command read.
    return previous.get('code_baseline') == code_baseline


def current(s, path, previous, code_baseline):
    return bool(previous and previous.get('quality') == 'green-passed'
                and same_inputs(s, path, previous, code_baseline))


def work_remaining(s):
    """Some leaf is still at work: the boundary of a wave, not the end of the run (the audit takes it from there)."""
    import audit_closure
    return any(m['phase'] not in audit_closure.TERMINAL for m in s['modules'].values())


def task(s):
    item = s.get('integration_assignment') or {}
    return item if item and not item.get('closed', True) else None


def due(s):
    """Prefer a ready managed wave, even when unrelated code is dirty or still being written."""
    import audit_closure
    from ledger import global_baseline
    if audit_closure.active(s) or not (s.get('audit_assignment') or {}).get('closed', True) or task(s):
        return []
    device_reviews = [change['report_ref'] for change in s.get('run_change_history', []) if change.get('device_only')]
    leaves_working = work_remaining(s)
    for managed in (True, False):
        selected = []
        baseline = None
        for path in s.get('global_paths', []):
            if scoped(s, path) != managed:
                continue
            held = owners(s, path)
            if not held or not all(s['modules'][mid]['phase'] == 'completed' and not s['modules'][mid].get('stale')
                                   and not any(not a.get('closed') for a in s['modules'][mid]['assignments'].values())
                                   for mid in held):
                continue
            previous = s.get('audit_results', {}).get(path['path_id'])
            device_retest = bool(previous and previous.get('stale') and previous.get('invalidated_by') in device_reviews
                                 and device_inputs(s, path) is not None)
            if not device_retest and (not leaves_working or
                    (not managed and previous and previous.get('owner_baselines') == owner_baselines(s, path))):
                continue  # Leave ordinary whole-snapshot retests to the final audit.
            try:
                if not managed and baseline is None:
                    baseline = global_baseline(s)
                expected = inputs(s, path, baseline)
            except (Rejected, OSError, KeyError):
                if not managed:
                    return []
                continue
            if not same_inputs(s, path, previous, baseline, expected):
                selected.append(path)
        if selected:
            return selected
    return []


def scope(s, selected=None):
    from ledger import scope_of
    item = task(s)
    if selected is None:
        selected = due(s) if not item else [p for p in s['global_paths'] if p['path_id'] in item['path_ids']]
    managed = bool(selected and all(scoped(s, p) for p in selected) and (not item or item.get('artifact_only')))
    mids = sorted({mid for path in selected for mid in module_ids(s, path)}) if managed else None
    value = scope_of(s, selected, leftovers=False, module_ids=mids)
    if item:
        require(item['path_ids'] == [p['path_id'] for p in selected]
                and (item['freeze_id'], item['code_baseline']) == (value['freeze_id'], value['code_baseline']),
                'integration selection or code changed; stop or isolate the worker and revoke the assignment')
        if 'inputs' in item:
            require(all(same_inputs(s, p, {'integration_inputs': item['inputs'].get(p['path_id'])}, value['code_baseline'])
                        for p in selected),
                    'integration execution inputs changed; stop or isolate the worker and revoke the assignment')
    return value


def stale(s):
    try:
        scope(s)
    except (Rejected, OSError, KeyError):
        return True
    return False


def handle(s, req, actor, sequence, root=None):
    from ledger import role
    import prepared_tests
    p = req['payload']
    if req['operation'] == 'integration-assign':
        role(actor, 'global-orchestrator')
        require(not task(s), 'integration Test-Runner still active')
        selected = due(s)
        require(selected, 'no global path is due on the current execution inputs')
        require(p.get('instance_id') and p.get('assignment_id'), 'integration Test-Runner identity required')
        authors = {a['instance_id'] for m in s['modules'].values() for a in m['assignments'].values() if a['role'] in ('implementer', 'fixer')}
        require(p['instance_id'] not in authors | prepared_tests.global_authors(s), 'integration Test-Runner must be independent of code and script authors')
        require(p.get('path_ids') == [x['path_id'] for x in selected], 'integration assignment must cover exactly the due paths')
        require(p['assignment_id'] not in s.get('integration_assignment_ids', []), 'duplicate integration assignment')
        s.setdefault('integration_assignment_ids', []).append(p['assignment_id'])
        if s.get('integration_assignment'):
            s.setdefault('integration_history', []).append(copy.deepcopy(s['integration_assignment']))
        value = scope(s, selected)
        managed = all(scoped(s, path) for path in selected)
        mids = sorted({mid for path in selected for mid in module_ids(s, path)}) if managed else s['modules']
        s['integration_assignment'] = {**copy.deepcopy(p), 'artifact_only': managed, 'role': 'test-runner', 'mode': 'integration', 'run_id': s['run_id'],
            'module_id': 'GLOBAL', 'freeze_id': value['freeze_id'], 'code_baseline': value['code_baseline'],
            'snapshot': {mid: s['modules'][mid]['code_baseline'] for mid in mids},
            'inputs': {path['path_id']: inputs(s, path, value['code_baseline']) for path in selected},
            **({'test_scope': 'visual'} if managed else {}),
            'owner_baselines': {x['path_id']: owner_baselines(s, x) for x in selected},
            'scope_policy': 'non-green-only', 'closed': False, 'fencing_token': sequence}
    elif req['operation'] == 'integration-revoke':
        role(actor, 'host')
        item = task(s)
        require(item and p.get('assignment_id') == item['assignment_id']
                and p.get('fencing_token') == item['fencing_token'], 'integration assignment or fence mismatch')
        check_ref(p.get('stopped_worker_ref'))
        item.update(closed=True, stopped_worker_ref=p['stopped_worker_ref'])
    else:
        role(actor, 'test-runner')
        item = task(s)
        require(item and item['instance_id'] == actor['instance_id'], 'integration task inactive/mismatch')
        require(item.get('context_ref') or not s.get('context_readiness_required'),
                'preflight required: context-submit a ready report for this assignment before its result')
        value = scope(s)
        result = read_json(check_ref(p.get('result_ref')))
        validate_result(result, value, item, run_root=root)
        require(result['kind'] == 'tests', 'integration task needs execution evidence')
        paths = {x['path_id']: x for x in s.get('global_paths', [])}
        for row in result['paths']:
            s.setdefault('audit_results', {})[row['path_id']] = {**row, 'code_baseline': value['code_baseline'],
                'owner_baselines': item['owner_baselines'][row['path_id']],
                **({'integration_inputs': item['inputs'][row['path_id']]} if 'inputs' in item else {})}
            if row['quality'] != 'green-passed':
                s.setdefault('audit_repairs', {})[row['path_id']] = {'finding': row, 'report_ref': p['result_ref'],
                    'module_ids': owners(s, paths[row['path_id']]), 'accepted_by': []}
            else:
                s.get('audit_repairs', {}).pop(row['path_id'], None)
        item.update(closed=True, result_ref=p['result_ref'])
