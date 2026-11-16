"""Explicit independent Test-Runner tasks beneath the one host-task Auditor assignment."""
import copy
from contracts import Rejected, check_ref, digest, nonempty, read_json, require, validate_result

OPS = {'audit-test-assign', 'audit-test-submit'}


def completed(s):
    audit = s.get('audit_assignment') or {}
    return [task for task in [*s.get('audit_test_history', []), s.get('audit_test_assignment') or {}]
            if task.get('audit_assignment_id') == audit.get('assignment_id') and task.get('closed') and task.get('result_ref')]


def ready_paths(s, scope):
    """From the audit's complete retest list, select unexecuted paths whose own inputs are available."""
    done = {pid for task in completed(s) for pid in task['path_ids']}
    planned = {path['path_id']: path for path in scope['plan']['paths']}
    waiting = [planned[pid] for pid in s['audit_assignment']['path_ids'] if pid not in done]
    return partition_paths(s, waiting)


def partition_paths(s, paths):
    from integration import check_path_inputs
    ready, blocked = [], {}
    for path in paths:
        pid = path['path_id']
        try:
            check_path_inputs(s, path)
        except (Rejected, OSError, KeyError) as exc:
            blocked[pid] = str(exc)
        else:
            ready.append(pid)
    return ready, blocked


def task_scope(scope, task):
    return {**scope, 'plan': {**scope['plan'], 'paths': [p for p in scope['plan']['paths'] if p['path_id'] in task['path_ids']]}}


def handle(s, req, actor, scope):
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
        s['audit_test_assignment'] = {**copy.deepcopy(p), **(usage or {}), 'context_ref': context, 'role': 'test-runner', 'mode': 'audit-execute',
            'run_id': s['run_id'], 'module_id': 'GLOBAL', 'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'],
            'audit_assignment_id': audit['assignment_id'], 'scope_policy': 'non-green-only', 'snapshot': copy.deepcopy(audit['snapshot']),
            'closed': False, 'audit_snapshot_sha256': digest(audit['snapshot'])}
    else:
        role(actor, 'test-runner')
        task = s.get('audit_test_assignment', {})
        require(not task.get('closed', True) and task['instance_id'] == actor['instance_id'] and
                task['audit_assignment_id'] == audit['assignment_id'], 'audit test task inactive/mismatch')
        require(task.get('context_ref') or not s.get('context_readiness_required'),
                'preflight required: context-submit a ready report for this assignment before its result')
        result = read_json(check_ref(p.get('result_ref')))
        validate_result(result, task_scope(scope, task), task)
        require(result['kind'] == 'tests', 'audit test task needs execution evidence')
        task.update(closed=True, result_ref=p['result_ref'])


def evidence(s, scope=None, report=None):
    """Gather exact accepted batch observations in their submission order."""
    tasks = completed(s)
    refs, rows = [], []
    for task in tasks:
        result = read_json(check_ref(task['result_ref']))
        if scope is not None:
            validate_result(result, task_scope(scope, task), task)
        refs.append(task['result_ref'])
        rows.extend(result['paths'])
    if report is not None:
        ids = [row['path_id'] for row in rows]
        expected = s['audit_assignment']['path_ids']
        require(len(ids) == len(expected) and set(ids) == set(expected),
                'Auditor must consume accepted independent Test-Runner evidence for every required PATH')
        require(report.get('test_result_refs', [report.get('test_result_ref')]) == refs, 'audit evidence reference mismatch')
        require(report.get('paths') == rows, 'Auditor cannot rewrite Test-Runner observations')
    return refs, rows
