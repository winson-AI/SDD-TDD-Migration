"""Explicit independent Test-Runner tasks beneath the one host-task Auditor assignment."""
import copy
from pathlib import Path
from contracts import Drifted, Rejected, check_ref, check_retest_chain, digest, file_ref, nonempty, read_json, require, validate_result

OPS = {'audit-test-assign', 'audit-test-submit', 'audit-test-revoke'}
INPUT_VERSION = 2
GLOBAL_VISUAL_INPUT_VERSION = 3


def submitted(s):
    audit = s.get('audit_assignment') or {}
    return [task for task in [*s.get('audit_test_history', []), s.get('audit_test_assignment') or {}]
            if task.get('audit_assignment_id') == audit.get('assignment_id') and task.get('closed') and task.get('result_ref')]


def latest_batches(batches):
    seen, latest = set(), []
    for task in reversed(batches):
        paths = [pid for pid in task['path_ids'] if pid not in seen]
        seen.update(paths)
        if paths:
            latest.append({**task, 'path_ids': paths})
    return list(reversed(latest))


def completed(s, scope, *, verify=True, archives=None):
    batches = latest_batches(submitted(s))
    done = {pid for task in batches for pid in task['path_ids']}
    auditor = (s.get('audit_assignment') or {}).get('instance_id')
    if verify:
        batches = verified_batches(s, scope, batches, {} if archives is None else archives)
    return carried(s, scope, auditor, exclude=done) + batches


def waiting_paths(s, scope, *, verify=True):
    audit = s.get('audit_assignment') or {}
    if audit.get('closed', True):
        batches = carried(s, scope, s.get('audit_code_review', {}).get('auditor_instance_id'))
    else:
        batches = completed(s, scope, verify=verify)
    done = {pid for task in batches for pid in task['path_ids']}
    return [path for path in scope['plan']['paths'] if path['path_id'] not in done]


def mechanical_paths(s, paths):
    from context_readiness import adapter_stated
    return [path['path_id'] for path in paths if path.get('command')
            or (path.get('kind') or 'automation') == 'automation' and adapter_stated(s, path)]


def batch_inputs(scope, path):
    """Group PATHs that depend on the same command, environment and frozen execution references."""
    from context_readiness import verify_refs_in
    from project_context import path_device
    from test_validation import visual_environment

    pid = path['path_id']
    command = path.get('command')
    if command and path.get('kind') in ('unit', 'automation') and path.get('unit_report'):
        # Approval evidence is checked on each original PATH before grouping and again before execution.
        command = {key: value for key, value in command.items() if key != 'selection_ref'}
        command['cwd'] = str(Path(command['cwd']).resolve())
        path = {**path, 'command': command}
    refs = sorted((ref['path'], ref['sha256']) for ref in verify_refs_in(path))
    return (path.get('kind') or 'automation', path_device(path), command, path.get('build_binding'),
            visual_environment(path, scope.get('visual_environment_rebindings')), refs,
            scope.get('path_test_sources', {}).get(pid), scope.get('path_build_artifacts', {}).get(pid, []))


def ready_paths(s, scope):
    """Dispatch runnable commands first, then give the remaining ready paths to an independent worker."""
    reported = environment_blocks(s)
    waiting = waiting_paths(s, scope, verify=False)
    ready, blocked = partition_paths(s, scope, waiting, reported=reported)
    if not ready and submitted(s):
        waiting = waiting_paths(s, scope)
        ready, blocked = partition_paths(s, scope, waiting, reported=reported)
    available = [path for path in waiting if path['path_id'] in ready]
    mechanical = mechanical_paths(s, available)
    if mechanical:
        available = [path for path in available if path['path_id'] in mechanical]
    if not available:
        return [], blocked
    inputs = batch_inputs(scope, available[0])
    return [path['path_id'] for path in available if batch_inputs(scope, path) == inputs], blocked


def check_path_inputs(s, scope, path):
    from integration import check_path_inputs as check_frozen
    from test_validation import bound_native_visual, check_managed_visual_artifacts

    check_frozen(s, path)
    if bound_native_visual(path):
        # Classify by the frozen PATH even when its rebound configuration can no longer be read.
        builds = scope['path_build_artifacts'].get(path['path_id'], [])
        check_managed_visual_artifacts(s, path, builds, allow_boot=True)


def partition_paths(s, scope, paths, *, reported=None):
    ready, blocked = [], {}
    for path in paths:
        pid = path['path_id']
        if reported and pid in reported:
            blocked[pid] = reported[pid]['summary']
            continue
        try:
            check_path_inputs(s, scope, path)
        except (Rejected, OSError, KeyError) as exc:
            blocked[pid] = str(exc)
        else:
            ready.append(pid)
    return ready, blocked


def task_scope(scope, task):
    return {**scope, 'plan': {**scope['plan'], 'paths': [p for p in scope['plan']['paths'] if p['path_id'] in task['path_ids']]}}


def return_unstarted(task, receipt):
    """Hand back a dispatch whose environment preflight never authorized any command."""
    report = read_json(check_ref(receipt['report_ref']))
    checks = report['checks']
    if {name for name, check in checks.items() if check['status'] == 'blocked'} != {'test-environment'}:
        return
    issue = checks['test-environment']
    assigned = task['path_ids']
    paths = issue.get('path_ids', assigned if len(assigned) == 1 else [])
    require(isinstance(paths, list) and paths and all(pid in assigned for pid in paths) and len(set(paths)) == len(paths),
            'blocked audit preflight must name distinct PATHs within its assignment')
    task.update(closed=True, environment_blocks={pid: {'summary': issue['summary'], 'report_ref': receipt['report_ref']}
                                               for pid in paths})


def environment_blocks(s):
    from test_validation import final_deferred_current

    audit = s.get('audit_assignment') or {}
    previous = s['audit'].get('deferred_preflight_blocks', {}) if final_deferred_current(s) else {}
    if audit.get('closed', True):
        return previous
    reported = dict(previous)
    for task in [*s.get('audit_test_history', []), s.get('audit_test_assignment') or {}]:
        if task.get('audit_assignment_id') == audit['assignment_id']:
            reported.update(task.get('environment_blocks', {}))
    return reported


def input_fingerprint(s, scope, path, root, argv=None, cwd=None, *, version=INPUT_VERSION):
    """Bind an observation to its frozen PATH, actual command and current platform inputs."""
    from context_readiness import verify_refs
    from execute_test import adapter_for, builtin_platform
    from integration import check_path_inputs as check_frozen
    from integration import device_inputs, inputs, managed_inputs
    from prepared_tests import binding, global_source
    from reference_media import assertion_refs
    from test_validation import bound_native_visual, check_visual_command, managed_visual_artifacts, managed_visual_environment, visual_environment

    pid = path['path_id']
    try:
        if argv is None:
            command = adapter_for(s, path, Path(root).resolve())
            argv, cwd = command['argv'], command['cwd']
        executable = Path(argv[0])
        if not executable.is_absolute():
            return None
        cwd = Path(cwd).resolve(strict=True)
        settings = {'runtime': s.get('runtime'), 'package': s.get('package_sha')}
        refs = {'media': assertion_refs(s, path)}
        if version == GLOBAL_VISUAL_INPUT_VERSION:
            require(bound_native_visual(path), 'scoped audit binding requires a managed GLOBAL visual PATH')
            check_visual_command(argv)
            check_frozen(s, path)
            execution = managed_inputs(s, path)
            refs['test_assets'] = binding({'path_test_sources': {pid: global_source(path)}}, path)
        else:
            code = scope['code_baseline']
            builds = scope['path_build_artifacts'].get(pid, [])
            if version == INPUT_VERSION and (path.get('kind') or 'automation') == 'automation' and builtin_platform(s, path) == 'web':
                check_frozen(s, path)
                execution = {'path': path, 'baseline': code, 'device': device_inputs(s, path),
                             'web_config': (s.get('target_preview') or {}).get('web_main_config')}
                if not path.get('build_binding'):
                    builds = []
            elif version == INPUT_VERSION and path.get('build_binding') and managed_visual_environment(s, path):
                check_visual_command(argv)
                visual = managed_visual_artifacts(s, path, builds)
                require(visual, 'managed audit visual build is unavailable')
                execution = {'path': path, 'baseline': code, 'environment_ref': visual['environment_ref']}
                builds = visual['artifacts']
            else:
                execution = inputs(s, path, code)
            settings.update(freeze=scope['freeze_id'], build=s.get('build'))
            refs.update(test_assets=binding(scope, path), builds=builds,
                        visual_environment=visual_environment(path, scope.get('visual_environment_rebindings')))
        verify_refs(refs)
        tools = [file_ref(executable), *(file_ref(cwd / arg) for arg in argv[1:] if (cwd / arg).is_file())]
        return digest({'inputs': execution, **settings,
                       'argv': argv, 'cwd': str(cwd), 'tools': tools, 'refs': refs})
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None  # An ordinary execution can proceed without proof suitable for a future assignment.


def receipt_inputs(s, scope, path, task, root, argv, cwd):
    from context_readiness import enabled
    from test_validation import bound_native_visual

    if bound_native_visual(path) and path in s['global_paths'] and enabled(s) and task.get('context_ref'):
        stamp = input_fingerprint(s, scope, path, root, argv, cwd, version=GLOBAL_VISUAL_INPUT_VERSION)
        if stamp:
            return {'audit_inputs_version': GLOBAL_VISUAL_INPUT_VERSION, 'audit_inputs_sha256': stamp}
    stamp = input_fingerprint(s, scope, path, root, argv, cwd)
    return {'audit_inputs_version': INPUT_VERSION, 'audit_inputs_sha256': stamp} if stamp else {}


def receipt_fingerprint(s, scope, path, task, receipt, *, same_assignment=False):
    from context_readiness import check_execution, enabled
    from test_validation import check_visual_command, managed_visual_environment

    version = receipt.get('audit_inputs_version', 1)
    if version not in (1, INPUT_VERSION, GLOBAL_VISUAL_INPUT_VERSION):
        return None
    argv = cwd = None
    if version == GLOBAL_VISUAL_INPUT_VERSION:
        if not enabled(s) or not task.get('context_ref'):
            return None
        argv, cwd = receipt['requested_argv'], receipt['cwd']
        check_execution(s, task, argv, cwd, path['path_id'])
    elif same_assignment:
        argv, cwd = receipt['requested_argv'], receipt['cwd']
    elif path.get('build_binding') and managed_visual_environment(s, path) and enabled(s) and task.get('context_ref'):
        argv, cwd = receipt['requested_argv'], receipt['cwd']
        check_visual_command(argv)
        check_execution(s, task, argv, cwd, path['path_id'])
    return input_fingerprint(s, scope, path, task['run_root'], argv, cwd, version=version)


def archived_evidence(task, archives):
    from ledger import read_events
    from verify_openspec import AcceptanceEvidence

    root = Path(task['run_root'])
    if root not in archives:
        state, events = read_events(root)
        archives[root] = AcceptanceEvidence(root, events, state['target_root'], prefer_live=True)
    return archives[root]


def proof_document(task, ref, archives):
    try:
        return read_json(check_ref(ref))
    except (Drifted, OSError):
        return read_json(archived_evidence(task, archives).check(ref))


def capture_matches(s, path, row, task, archives):
    from test_validation import visual_environment

    try:
        ref = visual_environment(path, (s.get('target_preview') or {}).get('visual_environment_rebindings'))
        device = read_json(check_ref(ref))['visual_capture']['device_id']
        proof = row['visual_alignment']
        captures = proof.get('capture_evidence', [])[-1:]
        if image := proof.get('image_parity'):
            captures = [*captures, image['capture_evidence']]
        expected = device, path['visual_execution']['app_id'], proof['hap_ref']
        return bool(captures) and all((record['device_id'], record['app_id'], record['artifact_ref']) == expected
            for record in (proof_document(task, capture['capture_execution_ref'], archives) for capture in captures))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def global_visual_current(s, path, previous):
    """Recheck only the execution already accepted for this PATH, against its current named inputs."""
    task = previous['global_visual_binding']
    try:
        receipt = proof_document(task, previous['execution_receipt'], {})
        stamp = receipt.get('audit_inputs_sha256')
        return (bool(stamp) and receipt.get('audit_inputs_version') == GLOBAL_VISUAL_INPUT_VERSION
                and (receipt['run_id'], receipt['module_id'], receipt['path_id'], receipt['test_run_id'])
                    == (s['run_id'], 'GLOBAL', path['path_id'], previous['test_run_id'])
                and stamp == receipt_fingerprint(s, None, path, task, receipt))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def verify_archived_observation(task, row, archives):
    archive = archived_evidence(task, archives)
    archive.check(task['result_ref'])
    archive.walked.clear()
    archive.visit(row)


def verify_carried_visual(s, scope, path, task, report, row, receipt, archives):
    """Keep the original batch identity when the current visual execution inputs still match."""
    from prepared_tests import global_authors

    runner = task['instance_id']
    require(runner not in global_authors(s) and all(runner not in m.get('authors', []) for m in s['modules'].values()),
            'carried visual Test-Runner must still be independent')
    original = {'run_id': s['run_id'], 'module_id': 'GLOBAL', 'assignment_id': task['assignment_id'],
                'actor_instance_id': runner, 'freeze_id': task['freeze_id'], 'code_baseline': task['code_baseline']}
    require(all(report.get(field) == receipt.get(field) == value for field, value in original.items())
            and (receipt['path_id'], receipt['test_run_id']) == (row['path_id'], row['test_run_id']),
            'carried visual observation differs from its original assignment')
    check_retest_chain(scope, path['path_id'], row)
    require(capture_matches(s, path, row, task, archives), 'carried visual capture differs from the current device or build')
    verify_archived_observation(task, row, archives)


def verified_batches(s, scope, tasks, archives, *, fingerprint=False):
    """Recheck the newest selected PATH observations under the current frozen inputs."""
    from context_readiness import verify_refs
    from prepared_tests import binding
    from test_validation import bound_native_visual

    paths = {path['path_id']: path for path in scope['plan']['paths']}
    visual_paths = {path['path_id'] for path in s.get('global_paths', []) if bound_native_visual(path)} if fingerprint else set()
    batches = []
    for task in tasks:
        if not task.get('run_root'):
            continue
        same_snapshot = (task['freeze_id'], task['code_baseline']) == (scope['freeze_id'], scope['code_baseline'])
        if not same_snapshot and not visual_paths.intersection(task['path_ids']):
            continue
        try:
            report = proof_document(task, task['result_ref'], archives)
        except (OSError, ValueError, TypeError, KeyError):
            continue
        keep = []
        for row in report['paths']:
            pid = row['path_id']
            if pid not in paths or pid not in task['path_ids']:
                continue
            if fingerprint and (not row.get('executed') or row['quality'] not in ('green-passed', 'red-bug')):
                continue
            if not same_snapshot and (pid not in visual_paths or row['quality'] != 'green-passed'):
                continue
            try:
                path = paths[pid]
                check_path_inputs(s, scope, path)
                verify_refs(binding(scope, path))
                verify_refs(scope.get('path_build_artifacts', {}).get(pid, []) if path.get('build_binding') else [])
                receipt_ref = row.get('execution_receipt')
                receipt = proof_document(task, receipt_ref, archives) if receipt_ref else {}
                if not same_snapshot and receipt.get('audit_inputs_version') != GLOBAL_VISUAL_INPUT_VERSION:
                    continue
                recorded = receipt.get('audit_inputs_sha256')
                if fingerprint and not recorded:
                    continue
                if recorded and recorded != receipt_fingerprint(s, scope, path, task, receipt, same_assignment=not fingerprint):
                    continue
                if not same_snapshot:
                    verify_carried_visual(s, scope, path, task, report, row, receipt, archives)
                else:
                    try:
                        validate_result({**report, 'paths': [row]}, task_scope(scope, {'path_ids': [pid]}), task,
                                        run_root=task['run_root'])
                    except (Drifted, OSError):
                        # The original submission already validated the observation and its output paths.
                        verify_archived_observation(task, row, archives)
            except (OSError, ValueError, TypeError, KeyError):
                continue
            keep.append(pid)
        if keep:
            batches.append({**task, 'path_ids': keep})
    return batches


def carried(s, scope, auditor, exclude=()):
    """Keep original result authorship and validate the original execution fingerprint."""
    tasks = [{**task, 'path_ids': [pid for pid in task['path_ids'] if pid not in exclude]}
             for task in latest_batches(s.get('audit_carry', [])) if task['instance_id'] != auditor]
    return verified_batches(s, scope, tasks, {}, fingerprint=True)


def hold(s):
    """Retain accepted observations when the whole-task audit releases its execution lock."""
    accepted = latest_batches(submitted(s))
    done = {pid for task in accepted for pid in task['path_ids']}
    batches = [{**task, 'path_ids': [pid for pid in task['path_ids'] if pid not in done]}
               for task in s.get('audit_carry', [])] + accepted
    batches = [task for task in batches if task['path_ids']]
    if batches:
        s['audit_carry'] = copy.deepcopy(batches)
    else:
        s.pop('audit_carry', None)


def defer(s, req, actor, scope, report):
    import test_validation as tv

    audit, task = s['audit_assignment'], s.get('audit_test_assignment') or {}
    require(audit.get('mode') != 'problem' and audit['instance_id'] == actor['instance_id'], 'audit assignment inactive/mismatch')
    require(audit['snapshot'] == {mid: m['code_baseline'] for mid, m in s['modules'].items()}
            and audit['path_ids'] == [path['path_id'] for path in scope['plan']['paths']], 'audit selection changed')
    require(task.get('audit_assignment_id') != audit['assignment_id'] or task.get('closed'),
            'audit Test-Runner still active; submit or verify stop/isolation and revoke')
    ready, blocked = ready_paths(s, scope)
    require(blocked and not ready, 'only unresolved unavailable audit PATHs may be deferred')
    context = req['payload']['context_ref']
    refs, rows = evidence(s, scope)
    reported = environment_blocks(s)
    for path in scope['plan']['paths']:
        if (pid := path['path_id']) in blocked:
            previous = scope['results'].get(pid)
            if previous and tv.observed_failure(previous):
                rows.append(previous)
                continue
            row = tv.untested(path, context, report, req['request_id'], previous, scope['code_baseline'])
            if pid in reported:
                row['root_cause']['evidence_refs'].append(reported[pid]['report_ref'])
            rows.append(row)
    hold(s)
    audit.update(closed=True, deferral_ref=context)
    # An unavailable input interrupted this audit before its independent verdict.
    s['audit_attempts'] -= 1
    s['audit'] = {'quality': 'red-bug' if any(tv.observed_failure(row) for row in rows) else 'yellow-blocked',
                  'environment_deferred': True, 'deferred_path_ids': list(blocked), 'snapshot': audit['snapshot'],
                  'deferred_preflight_blocks': {pid: reported[pid] for pid in blocked if pid in reported},
                  'report_ref': context, 'test_result_refs': refs, 'paths': rows,
                  'execution_status': 'waiting-for-test-environment'}


def handle(s, req, actor, scope, root):
    from ledger import current, role
    p = req['payload']; audit = s.get('audit_assignment', {})
    require((not audit.get('closed', True)) and (audit.get('mode') != 'problem'),
            'whole-task audit assignment required')
    require(audit['snapshot'] == {mid: m['code_baseline'] for mid, m in s['modules'].items()}, 'audit execution snapshot stale')
    if req['operation'] == 'audit-test-assign':
        role(actor, 'global-orchestrator')
        require(not s.get('audit_test_assignment') or s['audit_test_assignment'].get('closed'), 'audit Test-Runner still active')
        require(p.get('instance_id') and p.get('assignment_id') and p['instance_id'] != audit['instance_id'], 'independent Test-Runner identity required')
        import prepared_tests
        require(p['instance_id'] not in prepared_tests.global_authors(s), 'audit Test-Runner must be independent of GLOBAL script author')
        require(p['instance_id'] not in {i for m in s['modules'].values() for i in m.get('authors', [])}, 'audit Test-Runner must be independent of code and script authors')
        context = p.get('context_ref')
        if context and s.get('context_readiness_required'):  # else dispatched first: the Test-Runner reports inside it
            import context_readiness
            context_readiness.validate(s, None, 'audit-execution', context, p['instance_id'])
        paths = nonempty(p.get('path_ids'), 'audit test PATHs')
        ready, _ = ready_paths(s, scope)
        require(paths == ready, 'audit test assignment must cover selected ready retest scope')
        require(p['assignment_id'] not in s.get('audit_test_assignment_ids', []), 'duplicate audit test assignment')
        s.setdefault('audit_test_assignment_ids', []).append(p['assignment_id'])
        if s.get('audit_test_assignment'):
            s.setdefault('audit_test_history', []).append(copy.deepcopy(s['audit_test_assignment']))
        import model_routing
        usage = model_routing.record(p, role='test-runner')
        kind = task_scope(scope, p)['plan']['paths'][0].get('kind') or 'automation'
        s['audit_test_assignment'] = {**copy.deepcopy(p), **(usage or {}), 'context_ref': context, 'role': 'test-runner', 'mode': 'audit-execute',
            'run_id': s['run_id'], 'run_root': str(root), 'module_id': 'GLOBAL', 'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'],
            'audit_assignment_id': audit['assignment_id'], 'scope_policy': 'non-green-only', 'snapshot': copy.deepcopy(audit['snapshot']),
            'test_scope': kind, 'closed': False, 'audit_snapshot_sha256': digest(audit['snapshot'])}
    elif req['operation'] == 'audit-test-revoke':
        role(actor, 'host')
        import context_readiness
        import test_validation as tv
        task = s.get('audit_test_assignment') or {}
        require(set(p) == {'assignment_id', 'stopped_worker_ref'} and not task.get('closed', True)
                and p['assignment_id'] == task['assignment_id'] and task['audit_assignment_id'] == audit['assignment_id'],
                'audit test task inactive/mismatch')
        require(task.get('context_ref') or not context_readiness.enabled(s), 'audit test runner is not authorized')
        require(audit['path_ids'] == [path['path_id'] for path in scope['plan']['paths']]
                and task['freeze_id'] == scope['freeze_id'] and all(tv.available(m) for m in s['modules'].values()),
                'audit selection or snapshot changed; revoke the whole audit')
        for module in s['modules'].values():
            current(module)
        check_ref(p['stopped_worker_ref'])
        _, blocked = partition_paths(s, scope, task_scope(scope, task)['plan']['paths'])
        task.update(closed=True, stopped_worker_ref=p['stopped_worker_ref'], blocked_paths=blocked)
    else:
        role(actor, 'test-runner')
        task = s.get('audit_test_assignment', {})
        require(not task.get('closed', True) and task['instance_id'] == actor['instance_id'] and
                task['audit_assignment_id'] == audit['assignment_id'], 'audit test task inactive/mismatch')
        require(task.get('context_ref') or not s.get('context_readiness_required'),
                'preflight required: context-submit a ready report for this assignment before its result')
        result = read_json(check_ref(p.get('result_ref')))
        validate_result(result, task_scope(scope, task), task, run_root=root)
        require(result['kind'] == 'tests', 'audit test task needs execution evidence')
        task.update(closed=True, result_ref=p['result_ref'])


def evidence(s, scope=None, report=None, *, visual_bindings=None):
    """Gather exact accepted batch observations in their submission order."""
    from ledger import audit_scope
    from test_validation import bound_native_visual
    archives = {}
    tasks = completed(s, scope if scope is not None else audit_scope(s), archives=archives)
    global_paths = ({path['path_id']: path for path in s['global_paths'] if bound_native_visual(path)}
                    if visual_bindings is not None else {})
    refs, rows = [], []
    for task in tasks:
        result = proof_document(task, task['result_ref'], archives)
        rows_in_scope = [row for row in result['paths'] if row['path_id'] in task['path_ids']]
        refs.append(task['result_ref'])
        rows.extend(rows_in_scope)
        for row in rows_in_scope:
            path = global_paths.get(row['path_id'])
            if not path or row['quality'] != 'green-passed' or not task.get('context_ref'):
                continue
            receipt = proof_document(task, row['execution_receipt'], archives)
            if (receipt.get('audit_inputs_version') == GLOBAL_VISUAL_INPUT_VERSION and receipt.get('audit_inputs_sha256')
                    and capture_matches(s, path, row, task, archives)):
                visual_bindings[row['path_id']] = {key: task[key] for key in ('run_root', 'context_ref', 'freeze_id', 'code_baseline')}
    if report is not None:
        ids = [row['path_id'] for row in rows]
        expected = s['audit_assignment']['path_ids']
        require(len(ids) == len(expected) and set(ids) == set(expected),
                'Auditor must consume accepted independent Test-Runner evidence for every required PATH')
        require(report.get('test_result_refs', [report.get('test_result_ref')]) == refs, 'audit evidence reference mismatch')
        require(report.get('paths') == rows, 'Auditor cannot rewrite Test-Runner observations')
    return refs, rows
