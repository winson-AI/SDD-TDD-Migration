"""Build and automation are separate Test-Runner duties, with separate evidence."""
import copy
from pathlib import Path

from contracts import require, check_ref, verify_plan, baseline

OPS = {'automation-unavailable', 'automation-resume', 'audit-unavailable'}


def split(m):
    return any(p.get('kind') == 'build' for p in (m.get('plan') or {}).get('paths', []))


def paths(m, scope):
    return [p for p in m['plan']['paths'] if (p.get('kind') == 'build') == (scope == 'build')]


def build_ready(m):
    return bool(split(m) and m.get('build_baseline') == m.get('code_baseline') and m.get('code_baseline')
                and all(m.get('results', {}).get(p['path_id'], {}).get('quality') == 'green-passed'
                        for p in paths(m, 'build')))


def deferred(m):
    return m['phase'] == 'automation-deferred' and not m['stale'] and build_ready(m)


def available(m):
    return (m['phase'] == 'completed' and not m['stale']) or deferred(m)


def observed_failure(record):
    # Yellow may include a real failed assertion followed by an environment error.
    # Missing observations have actual=None and are not observed business failures.
    return record.get('quality') == 'red-bug' or any(
        a.get('passed') is False and a.get('actual') is not None
        for a in record.get('assertions', []))


def can_defer(m):
    return not any(observed_failure(r) and r.get('code_baseline', m['code_baseline']) == m['code_baseline']
                   for r in m['results'].values())


def plan_check(plan, target):
    builds = [p for p in plan['paths'] if p.get('kind') == 'build']
    require(builds and len(builds) < len(plan['paths']), 'split testing requires build and automation paths')
    require(all(p.get('kind') in ('build', 'automation') for p in plan['paths']), 'test path kind required')
    require({p.get('case_id') for p in plan['paths']} ==
            {p.get('case_id') for p in plan['paths'] if p['kind'] == 'automation'},
            'every module case needs an automation path; build cannot cover a business case')
    for path in builds:
        command = path.get('command', {})
        require(isinstance(command.get('argv'), list) and command['argv'] and
                all(isinstance(a, str) and a for a in command['argv']) and Path(command['argv'][0]).is_absolute(),
                'absolute build command argv required')
        cwd = command.get('cwd', '')
        require(Path(cwd).is_absolute() and Path(cwd).resolve().is_relative_to(Path(target).resolve()), 'build cwd outside target')
        require(type(command.get('timeout_seconds')) is int and command['timeout_seconds'] > 0, 'build timeout required')
        require(len(path['expected_assertions']) == 1 and path['expected_assertions'][0]['expected'] == 0,
                'build assertion must expect exit code zero')
        check_ref(command.get('selection_ref'))


def blocked_report(s, mid, ref, stage, instance=None):
    import context_readiness as cr
    require(cr.enabled(s), 'environment deferral requires context evidence')
    report = cr.validate(s, mid, stage, ref, instance=instance, allow_blocked=True)
    blocked = {k for k, v in report['checks'].items() if v['status'] == 'blocked'}
    require(blocked == {'test-environment'}, 'only automation environment may be deferred; resolve other blockers')
    return report


def untested(path, report_ref, report, token, previous=None):
    issue = report['checks']['test-environment']
    return {'path_id': path['path_id'], 'test_run_id': token + ':' + path['path_id'],
            'quality': 'yellow-blocked', 'executed': False, 'reason_code': 'automation-not-run',
            'assertions': [], 'retest_of': previous.get('test_run_id') if previous else None,
            'root_cause': {'category': 'automation-environment', 'summary': issue['summary'],
                           'confidence': 'confirmed', 'owner': issue['owner'], 'next_action': issue['next_action'],
                           'missing': issue['missing'], 'evidence_refs': [report_ref]}}


def handle(s, req, actor):
    import workflow
    import audit_closure as ac
    import context_readiness as cr
    op, p, mid = req['operation'], req['payload'], req.get('module_id')
    if op == 'audit-unavailable':
        import audit_code_review
        audit_code_review.require_current(s, actor['instance_id'])
        require(not audit_code_review.pending(s), 'code governance findings require closure before final audit')
        workflow.role(actor, 'auditor')
        workflow.planning_guard(s)
        require(not ac.active(s) and not workflow.audit_active(s) and not ac.collection_blockers(s), 'audit barrier not settled')
        from ledger import pending_repairs, audit_scope
        require(not pending_repairs(s), 'resolve pending audit repairs first')
        require(not ac.leftovers(s) and not s.get('audit_queue'), 'resolve non-environment findings first')
        require(all(available(m) for m in s['modules'].values()) and s['modules'], 'modules not operationally ready')
        require(all(actor['instance_id'] not in m['authors'] for m in s['modules'].values()), 'Auditor must be independent')
        report = blocked_report(s, None, p.get('context_ref'), 'audit-testing', actor['instance_id'])
        scope = audit_scope(s)
        require(scope['plan']['paths'], 'no unresolved paths; submit independent audit-review')
        require(not any(observed_failure(r) for r in scope['results'].values()),
                'cannot conceal observed failure as missing environment')
        rows = [untested(x, p['context_ref'], report, req['request_id'], scope['results'].get(x['path_id'])) for x in scope['plan']['paths']]
        s.setdefault('audit_results', {}).update({r['path_id']: r for r in rows})
        s['audit'] = {'quality': 'yellow-blocked', 'environment_deferred': True,
                      'report_ref': p['context_ref'], 'paths': rows,
                      'snapshot': {k: v['code_baseline'] for k, v in s['modules'].items()},
                      'reason': 'automation-not-run', 'execution_status': 'completed-with-unverified-tests'}
        return
    m = s['modules'][mid]
    workflow.role(actor, 'module-orchestrator'); workflow.idle(m)
    verify_plan(m['plan']); require(baseline(m['code_files']) == m['code_baseline'], 'code evidence stale')
    require(build_ready(m), 'current build must pass before automation deferral/resume')
    if op == 'automation-resume':
        require(deferred(m) and not ac.active(s), 'automation is not deferred or audit still active')
        cr.validate(s, mid, 'testing', p.get('context_ref'))
        m.update(phase='testing', blocked=None, stale=False)
        # Keep history in the journal and preserve retest_of chains in results.
        m['automation_retry_ready'] = True
        s['audit'] = {}
        return
    require(m['phase'] == 'testing' and not m.get('blocked'), 'automation deferral requires testing phase')
    report = blocked_report(s, mid, p.get('context_ref'), 'testing')
    require(can_defer(m), 'cannot conceal observed failure as missing environment')
    for path in paths(m, 'automation'):
        previous = m['results'].get(path['path_id'], {})
        if previous.get('quality') == 'green-passed' and previous.get('code_baseline') == m['code_baseline']:
            continue
        m['results'][path['path_id']] = untested(path, p['context_ref'], report, req['request_id'], m['results'].get(path['path_id']))
    m.update(phase='automation-deferred', stale=False,
             blocked={'kind': 'automation', 'reason': 'automation-not-run', 'context_ref': p['context_ref']})
    m.pop('automation_retry_ready', None)
    if ac.active(s):
        b = s['audit_batch']
        b.setdefault('automation_deferred', {})[mid] = copy.deepcopy(m['blocked'])
        # This is a verification omission, not a failed repair or a human branch lock.
        for memory in m.get('fix_memory', []):
            if memory.get('audit_batch_id') == b['batch_id']: memory.update(status='unverified', reusable=False)


def final_deferred_current(s):
    audit = s.get('audit', {})
    return audit.get('environment_deferred') and audit.get('snapshot') == {k: v['code_baseline'] for k, v in s['modules'].items()}
