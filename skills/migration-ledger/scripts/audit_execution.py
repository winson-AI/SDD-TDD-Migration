"""Explicit independent Test-Runner tasks beneath the one host-task Auditor assignment."""
import copy
from contracts import check_ref, digest, nonempty, read_json, require, validate_result

OPS = {'audit-test-assign', 'audit-test-submit'}


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
        if s.get('context_readiness_required'):
            require(context, 'audit execution context required')
            import context_readiness
            context_readiness.validate(s, None, 'audit-execution', context, p['instance_id'])
        paths = nonempty(p.get('path_ids'), 'audit test PATHs')
        require(paths == audit['path_ids'], 'audit test assignment must cover selected retest scope')
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
        result = read_json(check_ref(p.get('result_ref')))
        validate_result(result, scope, task)
        require(result['kind'] == 'tests', 'audit test task needs execution evidence')
        task.update(closed=True, result_ref=p['result_ref'])


def evidence(s, scope, report):
    task = s.get('audit_test_assignment', {}); audit = s['audit_assignment']
    require(task.get('closed') and task.get('result_ref') and task.get('audit_assignment_id') == audit['assignment_id'],
            'Auditor must consume accepted independent Test-Runner evidence')
    require(report.get('test_result_ref') == task['result_ref'], 'audit evidence reference mismatch')
    result = read_json(check_ref(task['result_ref']))
    validate_result(result, scope, task)
    require(report.get('paths') == result['paths'], 'Auditor cannot rewrite Test-Runner observations')
