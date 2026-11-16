"""Explicit independent Test-Runner tasks beneath the one host-task Auditor assignment."""
import copy
from pathlib import Path
from contracts import Rejected, check_ref, digest, file_ref, nonempty, read_json, require, validate_result

OPS = {'audit-test-assign', 'audit-test-submit'}
INPUT_VERSION = 2


def submitted(s):
    audit = s.get('audit_assignment') or {}
    return [task for task in [*s.get('audit_test_history', []), s.get('audit_test_assignment') or {}]
            if task.get('audit_assignment_id') == audit.get('assignment_id') and task.get('closed') and task.get('result_ref')]


def completed(s, scope):
    batches = submitted(s)
    done = {pid for task in batches for pid in task['path_ids']}
    auditor = (s.get('audit_assignment') or {}).get('instance_id')
    return carried(s, scope, auditor, exclude=done) + batches


def waiting_paths(s, scope):
    audit = s.get('audit_assignment') or {}
    if audit.get('closed', True):
        batches = carried(s, scope, s.get('audit_code_review', {}).get('auditor_instance_id'))
    else:
        batches = completed(s, scope)
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
    refs = sorted((ref['path'], ref['sha256']) for ref in verify_refs_in(path))
    return (path.get('kind') or 'automation', path_device(path), path.get('command'), path.get('build_binding'),
            visual_environment(path, scope.get('visual_environment_rebindings')), refs,
            scope.get('path_test_sources', {}).get(pid), scope.get('path_build_artifacts', {}).get(pid, []))


def ready_paths(s, scope):
    """Dispatch runnable commands first, then give the remaining ready paths to an independent worker."""
    waiting = waiting_paths(s, scope)
    ready, blocked = partition_paths(s, waiting, reported=environment_blocks(s))
    available = [path for path in waiting if path['path_id'] in ready]
    mechanical = mechanical_paths(s, available)
    if mechanical:
        available = [path for path in available if path['path_id'] in mechanical]
    if not available:
        return [], blocked
    inputs = batch_inputs(scope, available[0])
    return [path['path_id'] for path in available if batch_inputs(scope, path) == inputs], blocked


def partition_paths(s, paths, *, reported=None):
    from integration import check_path_inputs
    ready, blocked = [], {}
    for path in paths:
        pid = path['path_id']
        if reported and pid in reported:
            blocked[pid] = reported[pid]['summary']
            continue
        try:
            check_path_inputs(s, path)
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
    from integration import check_path_inputs, device_inputs, inputs
    from prepared_tests import binding
    from reference_media import assertion_refs
    from test_validation import check_visual_command, managed_visual_artifacts, managed_visual_environment, visual_environment

    pid = path['path_id']
    try:
        if argv is None:
            command = adapter_for(s, path, Path(root).resolve())
            argv, cwd = command['argv'], command['cwd']
        executable = Path(argv[0])
        if not executable.is_absolute():
            return None
        cwd = Path(cwd).resolve(strict=True)
        code = scope['code_baseline']
        builds = scope['path_build_artifacts'].get(pid, [])
        if version == INPUT_VERSION and (path.get('kind') or 'automation') == 'automation' and builtin_platform(s, path) == 'web':
            check_path_inputs(s, path)
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
        refs = {'test_assets': binding(scope, path), 'media': assertion_refs(s, path),
                'builds': builds,
                'visual_environment': visual_environment(path, scope.get('visual_environment_rebindings'))}
        verify_refs(refs)
        tools = [file_ref(executable), *(file_ref(cwd / arg) for arg in argv[1:] if (cwd / arg).is_file())]
        return digest({'inputs': execution, 'freeze': scope['freeze_id'],
                       'runtime': s.get('runtime'), 'build': s.get('build'), 'package': s.get('package_sha'),
                       'argv': argv, 'cwd': str(cwd), 'tools': tools, 'refs': refs})
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None  # An ordinary execution can proceed without proof suitable for a future assignment.


def receipt_fingerprint(s, scope, path, task, receipt):
    from context_readiness import check_execution, enabled
    from test_validation import check_visual_command, managed_visual_environment

    version = receipt.get('audit_inputs_version', 1)
    if version not in (1, INPUT_VERSION):
        return None
    argv = cwd = None
    if path.get('build_binding') and managed_visual_environment(s, path) and enabled(s) and task.get('context_ref'):
        argv, cwd = receipt['requested_argv'], receipt['cwd']
        check_visual_command(argv)
        check_execution(s, task, argv, cwd, path['path_id'])
    return input_fingerprint(s, scope, path, task['run_root'], argv, cwd, version=version)


def carried(s, scope, auditor, exclude=()):
    """Keep original result authorship; admit only the still current observations of each batch."""
    if not s.get('audit_carry'):
        return []
    paths = {path['path_id']: path for path in scope['plan']['paths']}
    seen, batches = set(exclude), []
    for task in reversed(s.get('audit_carry', [])):
        if (not task.get('run_root') or task['instance_id'] == auditor or task['freeze_id'] != scope['freeze_id']
                or task['code_baseline'] != scope['code_baseline']):
            continue
        try:
            report = read_json(check_ref(task['result_ref']))
        except (OSError, ValueError, TypeError):
            continue
        keep = []
        for row in report['paths']:
            pid = row['path_id']
            if (pid not in paths or pid not in task['path_ids'] or pid in seen or not row.get('executed')
                    or row['quality'] not in ('green-passed', 'red-bug')):
                continue
            seen.add(pid)  # A stale newer observation never reinstates an older one.
            try:
                receipt = read_json(check_ref(row['execution_receipt']))
                recorded = receipt.get('audit_inputs_sha256')
                if not recorded or recorded != receipt_fingerprint(s, scope, paths[pid], task, receipt):
                    continue
                validate_result({**report, 'paths': [row]}, task_scope(scope, {'path_ids': [pid]}), task,
                                run_root=task['run_root'])
            except (OSError, ValueError, TypeError, KeyError):
                continue
            keep.append(pid)
        if keep:
            batches.append({**task, 'path_ids': keep})
    return list(reversed(batches))


def hold(s):
    """Retain accepted observations when the whole-task audit releases its execution lock."""
    accepted = submitted(s)
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
    from ledger import role
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


def evidence(s, scope=None, report=None):
    """Gather exact accepted batch observations in their submission order."""
    from ledger import audit_scope
    tasks = completed(s, scope if scope is not None else audit_scope(s))
    refs, rows = [], []
    for task in tasks:
        result = read_json(check_ref(task['result_ref']))
        rows_in_scope = [row for row in result['paths'] if row['path_id'] in task['path_ids']]
        if scope is not None:
            validate_result({**result, 'paths': rows_in_scope}, task_scope(scope, task), task,
                            run_root=task.get('run_root'))
        refs.append(task['result_ref'])
        rows.extend(rows_in_scope)
    if report is not None:
        ids = [row['path_id'] for row in rows]
        expected = s['audit_assignment']['path_ids']
        require(len(ids) == len(expected) and set(ids) == set(expected),
                'Auditor must consume accepted independent Test-Runner evidence for every required PATH')
        require(report.get('test_result_refs', [report.get('test_result_ref')]) == refs, 'audit evidence reference mismatch')
        require(report.get('paths') == rows, 'Auditor cannot rewrite Test-Runner observations')
    return refs, rows
