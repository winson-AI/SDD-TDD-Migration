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
    from project_context import device_inputs as configured_devices, path_device

    if path.get('kind', 'automation') != 'automation' or not (platform := builtin_platform(s, path)):
        return None
    device = s['test_adapter']['device']
    return {key: config for key, config in configured_devices(device).items()
            if key == path_device(path) or platform == 'harmony' and key.startswith('harmony-')}


def frozen_unit(path):
    return bool(path.get('command') and (path.get('kind') == 'unit' or
                path.get('kind') == 'automation' and path.get('unit_report')))


def host_junit(path):
    return bool(path.get('unit_report') and frozen_unit(path))


def independent_of_adapter_override(s, path):
    """The PATH has its own unit command or currently resolves to the platform's built-in runner."""
    return frozen_unit(path) or device_inputs(s, path) is not None


def affected_by_device(s, path, devices):
    if not devices or host_junit(path):
        return False
    if scoped(s, path):
        from project_context import path_device
        return path_device(path) in devices
    bound = device_inputs(s, path)
    return bound is None or bool(devices.intersection(bound))


def check_path_inputs(s, path):
    """Validate frozen adapter and PATH references independently of the shared code baseline."""
    from context_readiness import verify_refs
    from execute_test import builtin_platform

    verify_refs(path)
    if builtin_platform(s, path) == 'ios' and path.get('ios_device_profile'):
        selected = next(iter(device_inputs(s, path).values()), None)
        require(selected and selected.get('wda_url'), 'iOS ' + path['ios_device_profile'] + ' PATH needs its WDA device binding')
        if path['ios_device_profile'] == 'physical':
            require(selected.get('deployment_ref'), 'iOS physical PATH needs its deployment receipt')
        if selected.get('deployment_ref'):
            check_ref(selected['deployment_ref'])
    if builtin_platform(s, path) == 'web':
        config = (s.get('target_preview') or {}).get('web_main_config')
        if config:
            check_ref(config)


def managed_inputs(s, path):
    """The accepted build, environment and owner/provider closure consumed by this visual PATH."""
    from ledger import current as check_module
    from test_validation import check_managed_visual_artifacts

    mids = module_ids(s, path)
    refs = check_managed_visual_artifacts(s, path, build_artifacts(s, path))
    for mid in mids:
        m = s['modules'][mid]
        require(m['phase'] == 'completed' and not m.get('stale'), 'integration input module unsettled')
        check_module(m)
    return {'path': path, 'build': refs,
            'modules': {mid: {k: s['modules'][mid].get(k) for k in ('code_baseline', 'freeze_id')} for mid in mids}}


def inputs(s, path, code_baseline=None, *, legacy=False, full_adapter=False, unit_with_device=False):
    """A managed visual path consumes its named build. Opaque commands may inspect the whole project."""
    if not legacy:
        check_path_inputs(s, path)
    if scoped(s, path):
        return digest(managed_inputs(s, path))
    common = {'path': path, 'baseline': code_baseline,
              'modules': {mid: {k: m.get(k) for k in ('freeze_id', 'build_artifacts')} for mid, m in s['modules'].items()}}
    if not legacy:
        from test_validation import bound_native_visual, check_managed_visual_artifacts
        if bound_native_visual(path):
            common['visual_inputs'] = check_managed_visual_artifacts(s, path, build_artifacts(s, path), allow_boot=True)
    adapter = s.get('test_adapter')
    if not legacy and not full_adapter and not unit_with_device and host_junit(path) and adapter:
        adapter = {k: v for k, v in adapter.items() if k != 'device'}
    device = None if legacy else device_inputs(s, path)
    if not legacy and not full_adapter and adapter and (device is not None or frozen_unit(path)):
        adapter = {k: v for k, v in adapter.items() if k != 'adapters'}
    if device is not None:
        platform = path['platform']
        web_config = (s.get('target_preview') or {}).get('web_main_config')
        runtime = ({'web_config': web_config} if platform == 'web'
                   else {'environment_revision': s.get('harmony_environment_revision')})
        return digest({**common, 'device': device, 'adapter': {k: v for k, v in adapter.items() if k != 'device'},
                       'runtime': runtime, 'package_sha': s.get('package_sha')})
    return digest({**common, 'test_adapter': adapter, 'environment_revision': s.get('harmony_environment_revision')})


def same_inputs(s, path, previous, code_baseline, expected=None):
    if not previous or previous.get('stale'):
        return False
    if previous.get('global_visual_binding'):
        from audit_execution import global_visual_current
        return global_visual_current(s, path, previous)
    if 'integration_inputs' in previous:
        try:
            expected = expected or inputs(s, path, code_baseline)
            original = previous['integration_inputs']
            return (expected in (original, previous.get('device_continuation_inputs'), previous.get('integration_continuation_inputs'))
                    or host_junit(path) and original == inputs(s, path, code_baseline, unit_with_device=True)
                    or independent_of_adapter_override(s, path) and original == inputs(s, path, code_baseline, full_adapter=True)
                    or device_inputs(s, path) is not None and original == inputs(s, path, code_baseline, legacy=True))
        except (Rejected, OSError, KeyError):
            return False
    if previous.get('code_baseline') != code_baseline:
        return False
    from test_validation import bound_native_visual, managed_visual_artifacts
    if not bound_native_visual(path):
        return True
    # Legacy native results can still describe the current final verdict. A revision clears that verdict.
    verdict = s.get('audit') or {}
    if (verdict.get('snapshot') != {mid: m.get('code_baseline') for mid, m in s['modules'].items()}
            or not any(row['path_id'] == path['path_id'] and row.get('test_run_id') == previous.get('test_run_id')
                       for row in verdict.get('paths', []))):
        return False
    if previous.get('quality') != 'green-passed':
        return True
    visual = managed_visual_artifacts(s, path, build_artifacts(s, path), allow_boot=True)
    return bool(visual and (previous.get('visual_alignment') or {}).get('hap_ref') in visual['artifacts'])


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


def runs_by_itself(s, path):
    from context_readiness import adapter_stated
    from test_validation import bound_native_visual
    return not bound_native_visual(path) and bool(path.get('command') or adapter_stated(s, path))


def due(s, *, blocked=None, revision_step=None):
    """Prefer a ready managed wave, even when unrelated code is dirty or still being written."""
    import audit_closure
    from execute_test import builtin_mobile
    from ledger import global_baseline
    from run_changes import next_action, pending_global_paths
    from test_validation import bound_native_visual, check_managed_visual_artifacts
    if audit_closure.active(s) or not (s.get('audit_assignment') or {}).get('closed', True) or task(s):
        return []
    device_reviews = [change['report_ref'] for change in s.get('run_change_history', []) if change.get('device_only')]
    wave_allowed = work_remaining(s)
    if not wave_allowed and s.get('global_plan') and (s.get('run_change_review') or {}).get('global_path_review'):
        # The final audit is waiting for approval. The existing wave can still verify other PATHs.
        revision_step = revision_step if revision_step is not None else next_action(s)
        wave_allowed = bool(revision_step and revision_step['reason'] == 'run-approval-required')
    switching = pending_global_paths(s, revision_step=revision_step)
    needs_boot = set()
    for managed in (True, False):
        selected = []
        baseline = None
        for path in s.get('global_paths', []):
            pid = path['path_id']
            if pid in switching or (bound_native_visual(path) != managed and pid not in needs_boot):
                continue
            held = owners(s, path)
            if not held or not all(s['modules'][mid]['phase'] == 'completed' and not s['modules'][mid].get('stale')
                                   and not any(not a.get('closed') for a in s['modules'][mid]['assignments'].values())
                                   for mid in held):
                continue
            previous = s.get('audit_results', {}).get(pid)
            device_retest = bool(previous and previous.get('stale') and previous.get('invalidated_by') in device_reviews
                                 and device_inputs(s, path) is not None)
            if not device_retest and (not wave_allowed or
                    (not managed and previous and previous.get('owner_baselines') == owner_baselines(s, path))):
                continue  # Leave ordinary whole-snapshot retests to the final audit.
            if not managed and baseline is None:
                try:
                    baseline = global_baseline(s)
                except (Rejected, OSError, KeyError):
                    return []  # Every unscoped PATH needs the shared baseline.
            try:
                if managed and not scoped(s, path):
                    # Missing bindings stay local. With a valid boot command, use the full baseline.
                    check_path_inputs(s, path)
                    check_managed_visual_artifacts(s, path, build_artifacts(s, path), allow_boot=True)
                    needs_boot.add(pid)
                    continue
                expected = inputs(s, path, baseline)
            except (Rejected, OSError, KeyError) as exc:
                if blocked is not None:
                    blocked[pid] = str(exc)
                continue
            if not same_inputs(s, path, previous, baseline, expected):
                selected.append(path)
        if selected:
            if managed:
                return selected
            automatic = [path for path in selected if runs_by_itself(s, path)]
            quick = [path for path in automatic if not builtin_mobile(s, path)]
            return quick or automatic[:1] or selected
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
        blocked = {}
        selected = due(s, blocked=blocked)
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
            **({'blocked_paths': blocked} if blocked else {}),
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
