"""Post-module audit: finding routes, dependency-ordered repairs/tests, human handoff."""
import copy
import re

from contracts import require, check_ref, read_json, digest, keyed, baseline, verify_plan
import workflow
import decomposition
import test_validation as tv
import audit_code_review

OPS = {'audit-collect', 'audit-plan', 'audit-route-batch', 'audit-work', 'audit-retest', 'audit-verdict', 'audit-release', 'audit-block'}
GLOBAL_OPS = OPS - {'audit-work', 'audit-retest', 'audit-block'}
TERMINAL = {'completed', 'waiting-auditor', 'waiting-dependency', 'waiting-human', 'automation-deferred'}


def active(s):
    return s.get('audit_batch', {}).get('status') not in (None, 'verified', 'released', 'completed-with-unverified-tests')


def collection_blockers(s):
    # Local import avoids a module initialization cycle. The cursor and mutation use
    # the same guard, so callers cannot bypass the all-modules barrier via raw JSON.
    from ledger import next_step
    blockers = [] if s['modules'] else [{'module_id': None, 'reason': 'no-modules'}]
    released = s.get('audit_batch', {})
    if released.get('status') == 'released':
        for mid, snapshot in released.get('recovery_contexts', {}).items():
            m = s['modules'][mid]
            if {'context': context(m), 'blocked': m.get('blocked')} == snapshot:
                blockers.append({'module_id': mid, 'reason': 'human-recovery-not-applied'})
    for mid, m in s['modules'].items():
        if m.get('effective_quality') == 'yellow-blocked':
            blockers.append({'module_id': mid, 'reason': 'module-evidence-stale'})
        elif any(not a.get('closed') for a in m['assignments'].values()):
            blockers.append({'module_id': mid, 'reason': 'worker-running'})
        elif m['phase'] not in TERMINAL:
            blockers.append({'module_id': mid, 'reason': 'module-round-unfinished', 'phase': m['phase']})
        elif m['phase'] != 'completed' and not m.get('blocked'):
            blockers.append({'module_id': mid, 'reason': 'suspension-record-missing'})
        else:
            step = next_step(s, m)
            if step.get('ready'):
                blockers.append({'module_id': mid, 'reason': 'module-work-ready', 'operation': step['operation']})
    for mid, group in s.get('module_groups', {}).items():
        if not decomposition.summary_current(s, group):
            step = decomposition.group_step(s, group)
            blockers.append({'module_id': mid, 'reason': 'parent-summary-required', 'operation': step['operation']})
    return blockers


def module_rounds(s, steps):
    """Separate per-module progress from aggregate quality; never mutate peers."""
    blockers = collection_blockers(s)
    unfinished = {item['module_id'] for item in blockers}
    return {
        'all_settled': not blockers,
        'registered_modules': sorted(set(s['modules']) | set(s.get('module_groups', {}))),
        'leaf_modules': sorted(s['modules']),
        'parent_modules': sorted(s.get('module_groups', {})),
        'settled_modules': sorted((set(s['modules']) | set(s.get('module_groups', {}))) - unfinished),
        'unfinished_modules': sorted(mid for mid in unfinished if mid is not None),
        'active_modules': sorted(mid for mid, m in s['modules'].items()
                                 if any(not a.get('closed') for a in m['assignments'].values())),
        'ready_modules': sorted(step['module_id'] for step in steps if step['ready']),
        'blockers': blockers,
    }


def leftovers(s):
    found = {}
    for mid, m in s['modules'].items():
        if tv.deferred(m):
            continue  # Recorded in final Auditor coverage, never routed as a code defect.
        bad = {pid: r for pid, r in {**m['results'], **m.get('repair_findings', {})}.items() if r['quality'] != 'green-passed'}
        if bad or mid in s.get('audit_queue', {}) or m.get('blocked'):
            found[mid] = {'results': copy.deepcopy(bad), 'blocker': copy.deepcopy(m.get('blocked')),
                          'queue': copy.deepcopy(s.get('audit_queue', {}).get(mid)),
                          **context(m)}
    return found


def context(m):
    return {'freeze_id': m.get('freeze_id'), 'code_baseline': m.get('code_baseline'),
            'spec_ref': m.get('plan_ref'), 'test_paths': copy.deepcopy((m.get('plan') or {}).get('paths', []))}


def current(m, expected):
    require(context(m) == expected, 'audit task SPEC/code context changed')
    require(m.get('freeze_id') and m.get('code_files'), 'frozen SPEC and generated code required')
    verify_plan(m['plan'])
    require(baseline(m['code_files']) == m['code_baseline'], 'audit code evidence stale')


def findings(sources):
    result = {}
    for mid, source in sources.items():
        for pid, record in source['results'].items():
            fid = 'F-' + mid + '-' + digest(['path', pid])[:12]
            result[fid] = {'finding_id': fid, 'source_module_id': mid, 'path_id': pid, 'result': record}
        if not source['results']:
            fid = 'F-' + mid + '-' + digest(['blocker'])[:12]
            result[fid] = {'finding_id': fid, 'source_module_id': mid, 'path_id': None,
                           'blocker': source['blocker'], 'queue': source['queue']}
    return result


def owners(b):
    return {mid for r in b['routes'].values() if r['action'] == 'fix' for mid in r['owner_module_ids']}


def proof(b, mid):
    return b['owner_tests'].get(mid) or b['source_tests'].get(mid)


def completed(s, b, mid):
    m = s['modules'][mid]
    if tv.deferred(m):
        return mid not in b.get('work_modules', []) or mid in b.get('automation_deferred', {})
    if m['phase'] != 'completed' or m['stale']:
        return False
    if mid in b.get('work_modules', []):
        p = proof(b, mid)
        return bool(p and p['freeze_id'] == m['freeze_id'] and p['code_baseline'] == m['code_baseline'])
    return True


def dependencies_done(s, b, mid):
    return all(completed(s, b, dep) for dep in b['dependencies'][mid])


def pending_modules(b):
    # The work set includes finding sources, owners and affected Green descendants.
    return set(b.get('work_modules', [])) - set(b.get('blocked_modules', []))


def finding_impact(b, fid):
    route = b['routes'][fid]
    affected = {route['source_module_id'], *route['owner_module_ids'],
                *b['findings'][fid].get('affected_module_ids', [])}
    while True:
        more = {mid for mid, deps in b['dependencies'].items() if affected.intersection(deps)} - affected
        if not more:
            return affected
        affected.update(more)


def human_report(s, reason, mid=None, evidence=None):
    b = s['audit_batch']
    causes = [item['root_cause'] for item in b.get('human_issues', {}).values()]
    b['human_report'] = {'batch_id': b['batch_id'], 'reason': reason, 'module_id': mid,
                         'evidence': evidence, 'sources': copy.deepcopy(b['sources']),
                         'findings': copy.deepcopy(b['findings']), 'routes': copy.deepcopy(b['routes']),
                         'human_issues': copy.deepcopy(b.get('human_issues', {})),
                         'owner_tests': copy.deepcopy(b['owner_tests']), 'source_tests': copy.deepcopy(b['source_tests']),
                         'root_causes': causes, 'next_action': 'human-review'}


def stop(s, reason, module_id=None, evidence=None, finding_id=None):
    """Suspend the affected dependency branch; independent findings can still run."""
    b = s['audit_batch']
    affected = {module_id} if module_id else set(b.get('work_modules', []))
    if finding_id:
        affected.add(b['findings'][finding_id]['source_module_id'])
    changed = True
    while changed:
        before = set(affected)
        for mid, deps in b.get('dependencies', {}).items():
            if affected.intersection(deps): affected.add(mid)
        for fid, r in b['routes'].items():
            if r['source_module_id'] in affected or affected.intersection(r['owner_module_ids']) or (
                    b.get('code_review_ref') and affected.intersection(finding_impact(b, fid))):
                affected.add(r['source_module_id'])
                causes = evidence.get('root_causes') if isinstance(evidence, dict) else None
                cause = causes[0] if causes else r['root_cause'] if finding_id == fid else {
                    'category': 'verification-blocked', 'summary': reason, 'confidence': 'confirmed',
                    'owner': module_id or 'global-orchestrator', 'next_action': 'human-review'}
                b.setdefault('human_issues', {}).setdefault(fid, {'root_cause': cause, 'reason': reason, 'evidence': evidence})
        changed = affected != before
    b['blocked_modules'] = sorted(set(b.get('blocked_modules', [])) | affected)
    failed_owners = {owner for fid,r in b['routes'].items() if fid in b['human_issues'] for owner in r['owner_module_ids']}
    for owner in failed_owners:
        for memory in s['modules'][owner].get('fix_memory', []):
            if memory.get('audit_batch_id') == b['batch_id']: memory.update(status='failed', reusable=False)
    for mid in affected:
        if mid not in s['modules']: continue
        m = s['modules'][mid]
        if not any(not a.get('closed') for a in m['assignments'].values()):
            m.update(phase='waiting-human', blocked={'kind': 'human', 'reason': reason, 'resume_phase': 'testing'})
        for memory in m.get('fix_memory', []):
            if memory.get('audit_batch_id') == b['batch_id']: memory.update(status='failed', reusable=False)
    human_report(s, reason, module_id, evidence)
    if all(completed(s,b,mid) for mid in pending_modules(b)) and all(not any(not a.get('closed') for a in m['assignments'].values()) for m in s['modules'].values()):
        b['status'] = 'awaiting-human'


def test_accepted(s, m, result, result_ref):
    b = s.get('audit_batch', {})
    if not b or m.get('audit_batch_id') != b.get('batch_id') or b.get('status') != 'repairing': return
    mid = m['module_id']
    p = {'result_ref': result_ref, 'code_baseline': m['code_baseline'], 'freeze_id': m['freeze_id'], 'paths': copy.deepcopy(result['paths'])}
    stage = m.get('audit_test_stage')
    require(stage in ('owner', 'source'), 'audit verification stage missing')
    b[stage + '_tests'][mid] = p
    bad = [r for r in result['paths'] if r['quality'] != 'green-passed']
    for memory in m.get('fix_memory', []):
        if memory.get('audit_batch_id') == b['batch_id']: memory.update(status='failed' if bad else 'awaiting-cross-verification', reusable=False)
    if stage == 'owner' and mid in b['sources']: b['source_tests'][mid] = p
    if bad:
        stop(s, 'verification-failed', mid, {'result_ref': result_ref, 'root_causes': [r['root_cause'] for r in bad]})
    elif b.get('human_issues'):
        human_report(s, 'partial-verification-awaits-human')


def batch(s):
    require(active(s), 'no active audit closure')
    return s['audit_batch']


def build_graph(s, b):
    deps = {mid: set(m['dependencies']) for mid, m in s['modules'].items()}
    for r in b['routes'].values():
        deps[r['source_module_id']].update(set(r['owner_module_ids']) - {r['source_module_id']})
        for consumer in b['findings'][r['finding_id']].get('affected_module_ids', []):
            if consumer not in r['owner_module_ids']:
                deps[consumer].update(set(r['owner_module_ids']) - {consumer})
    visiting, visited = set(), set()
    def visit(mid):
        require(mid not in visiting, 'audit ownership creates dependency cycle; revise routing')
        if mid in visited: return
        visiting.add(mid)
        for dep in deps[mid]: visit(dep)
        visiting.remove(mid); visited.add(mid)
    for mid in deps: visit(mid)
    work = set(b['sources']) | owners(b)
    for finding in b['findings'].values():
        work.update(finding.get('affected_module_ids', []))
    changed = True
    while changed:
        before = set(work)
        for mid, required in deps.items():
            if work.intersection(required): work.add(mid)
        changed = work != before
    b['dependencies'] = {mid: sorted(d) for mid, d in deps.items()}
    b['work_modules'] = sorted(work)


def handle(s, req, actor):
    op, p, mid = req['operation'], req.get('payload', {}), req.get('module_id')
    if op == 'audit-collect':
        workflow.role(actor, 'global-orchestrator'); workflow.planning_guard(s)
        require(not workflow.audit_active(s), 'close active audit before collection')
        require(not active(s), 'release failed audit with human approval before new collection')
        blockers = collection_blockers(s)
        require(not blockers, 'all module rounds must finish or suspend before Auditor: ' + str(blockers))
        audit_code_review.require_current(s, p.get('auditor_instance_id'))
        sources, code_findings = audit_code_review.collection(s)
        require(sources, 'no leftover issues')
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', p.get('batch_id', '')) and p.get('auditor_instance_id'), 'batch and auditor identity required')
        require(p['batch_id'] not in s.get('audit_batch_ids', []), 'batch id reused')
        require(all(p['auditor_instance_id'] not in m['authors'] for m in s['modules'].values()), 'Auditor must be independent')
        s.setdefault('audit_batch_ids', []).append(p['batch_id'])
        if s.get('audit_batch') and s['audit_batch']['status'] in ('verified', 'completed-with-unverified-tests'):
            s.setdefault('audit_batch_history', []).append(copy.deepcopy(s['audit_batch']))
        s['audit_batch'] = {'schema_version': 2, 'batch_id': p['batch_id'], 'auditor_instance_id': p['auditor_instance_id'],
                            'status': 'collected', 'sources': sources, 'findings': code_findings or findings(sources),
                            'code_review_ref': s['audit_code_review']['report_ref'] if code_findings else None,
                            'round_snapshot': {k: {'phase':m['phase'], 'revision':m['revision']} for k,m in s['modules'].items()},
                            'contexts': {k: context(v) for k, v in s['modules'].items()},
                            'routes': {}, 'started_owners': [], 'owner_tests': {}, 'source_tests': {}, 'human_issues': {}, 'blocked_modules': []}
    elif op == 'audit-plan':
        workflow.role(actor, 'auditor'); b = batch(s)
        require(actor['instance_id'] == b['auditor_instance_id'] and b['status'] == 'collected', 'auditor/phase mismatch')
        plan = read_json(check_ref(p.get('plan_ref')))
        normalized = []
        for entry in plan.get('routes', []):
            r = copy.deepcopy(entry)
            if not r.get('finding_id'):
                matches = [fid for fid,f in b['findings'].items() if f['source_module_id'] == r.get('source_module_id')]
                require(len(matches) == 1, 'route by finding_id when module has multiple findings')
                r['finding_id'] = matches[0]
            f = b['findings'].get(r['finding_id']); require(f and r.get('source_module_id') == f['source_module_id'], 'unknown finding/source')
            workflow.root_cause(r.get('root_cause')); check_ref(r.get('analysis_ref'))
            require(r.get('action') in ('fix', 'verify', 'human'), 'invalid finding action')
            r['owner_module_ids'] = r.get('owner_module_ids', [r['owner_module_id']] if r.get('owner_module_id') else [])
            if b.get('code_review_ref'):
                require(r['action'] in ('fix', 'human'), 'code governance requires delegated change or human decision')
                require(not f.get('requires_human') or r['action'] == 'human', 'persistent governance finding requires human review; no second automatic fix')
            mids = r['owner_module_ids']
            require(len(set(mids)) == len(mids) and set(mids) <= set(s['modules']), 'unknown/duplicate repair owner')
            require(bool(mids) == (r['action'] == 'fix'), 'only fix routes must specify repair owners')
            if r['action'] != 'human':
                require(r.get('source_context') == b['contexts'][f['source_module_id']], 'source SPEC/test context mismatch')
                contexts = r.get('owner_contexts', {mids[0]:r.get('owner_context')} if len(mids) == 1 else {})
                require(contexts == {owner:b['contexts'][owner] for owner in mids}, 'owner SPEC/test contexts mismatch')
                r['owner_contexts'] = contexts
            normalized.append(r)
        routes = keyed(normalized, 'finding_id')
        require(set(routes) == set(b['findings']), 'route every collected finding exactly once')
        b.update(routes=routes, plan_ref=p['plan_ref'], status='planned')
        build_graph(s, b)
    elif op == 'audit-route-batch':
        workflow.role(actor, 'global-orchestrator'); b = batch(s)
        require(b['status'] == 'planned', 'Auditor routing plan required')
        check_ref(p.get('review_ref')); check_ref(b['plan_ref'])
        b.update(review_ref=p['review_ref'], status='repairing')
        for fid,r in b['routes'].items():
            if r['action'] == 'human': stop(s, 'unrepairable-or-contract-decision', r['source_module_id'], r['analysis_ref'], fid)
    elif op == 'audit-work':
        workflow.role(actor, 'module-orchestrator'); b = batch(s)
        require(b['status'] == 'repairing' and mid in pending_modules(b), 'module not runnable in audit')
        routes = [r for r in b['routes'].values() if mid in r['owner_module_ids']]
        require(routes and mid not in b['started_owners'], 'owner not routed/already attempted')
        m = s['modules'][mid]; workflow.idle(m)
        require(dependencies_done(s, b, mid), 'wait for dependency repair and full module verification')
        try:
            current(m, b['contexts'][mid])
            require((m.get('blocked') or {}).get('kind') != 'human', 'unresolved human blocker')
            require(workflow.runnable(s, mid), 'owner prerequisites unavailable')
            require(m['fix_rounds_used'] < m.get('fix_budget', s['max_fix_rounds']) and m['no_progress_rounds'] < s['max_no_progress_rounds'], 'repair budget exhausted')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            stop(s, str(exc), mid, b['plan_ref']); return
        b['started_owners'].append(mid)
        m.update(phase='diagnosing', blocked=None, stale=False, audit_batch_id=b['batch_id'], audit_test_stage='owner',
                 diagnosis={'diagnosis_ref': b['plan_ref'], 'root_cause': routes[0]['root_cause'],
                            'findings': copy.deepcopy(routes), 'owner': mid}, audit_fix_grant=b['batch_id'])
    elif op == 'audit-retest':
        workflow.role(actor, 'module-orchestrator'); b = batch(s)
        require(b['status'] == 'repairing' and mid in pending_modules(b) and not completed(s,b,mid), 'module retest not pending')
        require(mid not in owners(b) or mid in b['started_owners'], 'owner must receive repair before verification')
        require(dependencies_done(s,b,mid), 'upstream repair/verification incomplete')
        m = s['modules'][mid]; workflow.idle(m)
        try:
            require((m.get('blocked') or {}).get('kind') != 'human', 'unresolved human blocker')
            # Owners have an accepted new code baseline; other modules retain their captured context.
            if mid not in owners(b): current(m, b['contexts'][mid])
            require(workflow.runnable(s, mid), 'source prerequisites still unavailable')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            stop(s, str(exc), mid, b['plan_ref']); return
        m.update(phase='testing', blocked=None, stale=True, audit_batch_id=b['batch_id'],
                 audit_test_stage='owner' if mid in owners(b) else 'source')
    elif op == 'audit-verdict':
        workflow.role(actor, 'auditor'); b = batch(s)
        require(actor['instance_id'] == b['auditor_instance_id'] and b['status'] == 'repairing', 'auditor/phase mismatch')
        check_ref(p.get('review_ref'))
        for m in s['modules'].values(): workflow.idle(m)
        require(all(completed(s,b,mid) for mid in pending_modules(b)), 'verification incomplete')
        try:
            for mid in pending_modules(b):
                m = s['modules'][mid]
                if mid in b.get('automation_deferred', {}):
                    require(tv.deferred(m), 'deferred automation evidence changed')
                    continue
                pr = proof(b,mid); check_ref(pr['result_ref'])
                require(pr['freeze_id'] == m['freeze_id'] and pr['code_baseline'] == baseline(m['code_files']), 'verification stale')
                require(all(r['quality'] == 'green-passed' for r in pr['paths']), 'unresolved verification')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            stop(s, str(exc), evidence=p['review_ref']); return
        b['unverified_findings'] = [fid for fid in b['routes'] if
                                    finding_impact(b, fid).intersection(b.get('automation_deferred', {}))]
        b['resolved_findings'] = [fid for fid in b['findings'] if fid not in b['human_issues'] and fid not in b['unverified_findings']]
        b['verdict_ref'] = p['review_ref']
        if b['human_issues']:
            b['status'] = 'awaiting-human'; human_report(s, 'partial-audit-requires-human', evidence=p['review_ref'])
        else:
            b['status'] = 'completed-with-unverified-tests' if b['unverified_findings'] else 'verified'
            b['quality'] = 'yellow-blocked' if b['unverified_findings'] else 'green-passed'
            for owner in owners(b):
                for memory in s['modules'][owner].get('fix_memory', []):
                    if memory.get('audit_batch_id') == b['batch_id'] and not any(owner in b['routes'][fid]['owner_module_ids'] for fid in b['unverified_findings']):
                        memory.update(status='verified', reusable=True, audit_verdict_ref=p['review_ref'])
        for source in {b['findings'][fid]['source_module_id'] for fid in b['resolved_findings'] + b['unverified_findings']}:
            if not any(f['source_module_id'] == source and fid in b['human_issues'] for fid,f in b['findings'].items()):
                s.get('audit_queue', {}).pop(source, None); s.get('audit_resolutions', {}).pop(source, None)
    elif op == 'audit-block':
        workflow.role(actor, 'module-orchestrator'); b = batch(s)
        require(b['status'] == 'repairing' and mid in b['work_modules'], 'audit module required')
        workflow.idle(s['modules'][mid]); require(p.get('reason'), 'block reason required'); check_ref(p.get('evidence_ref'))
        stop(s, p['reason'], mid, p['evidence_ref'])
    elif op == 'audit-release':
        workflow.role(actor, 'global-orchestrator'); b = batch(s)
        require(b['status'] == 'awaiting-human', 'only failed/partial audit can be released')
        for m in s['modules'].values(): workflow.idle(m)
        d = s['decisions'].get(p.get('decision_id'), {})
        require(d.get('module_id') is None and not d.get('consumed', True) and d.get('subject_sha256') == digest(b['human_report']), 'approval must bind current human report')
        check_ref(d['human_source_ref']); d['consumed'] = True
        b['recovery_contexts'] = {mid: {'context': context(m), 'blocked': copy.deepcopy(m.get('blocked'))}
                                  for mid,m in s['modules'].items() if mid in b.get('blocked_modules', [])
                                  or (m.get('blocked') or {}).get('kind') == 'human'}
        b.update(status='released', release_decision_id=p['decision_id'])
        s.setdefault('audit_batch_history', []).append(copy.deepcopy(b))
        for mid,m in s['modules'].items():
            if m.get('audit_batch_id') == b['batch_id']:
                m.pop('audit_batch_id', None); m.pop('audit_test_stage', None); m.pop('audit_fix_grant', None)
        # Release only unlocks normal guarded operations. Budget/semantic changes still
        # need their own explicit decisions and no test is promoted to Green.


def module_step(s, m):
    if not active(s): return None
    b = s['audit_batch']; mid = m['module_id']
    step = {'module_id': mid, 'phase': m['phase'], 'expected_revision': m['revision'], 'operation': None,
            'role': 'module-orchestrator', 'ready': False, 'reason': 'await-audit-closure', 'assignment_id': None, 'session_id': None}
    if any(not a.get('closed') for a in m['assignments'].values()):
        if mid in b.get('blocked_modules', []):
            step.update(operation='revoke', role='host', ready=True, reason='stop-blocked-audit-worker'); return step
        return None
    if b['status'] == 'awaiting-human': step['reason'] = 'human-review-required'; return step
    if b['status'] != 'repairing': return step
    if mid in b['blocked_modules']: step['reason'] = 'finding-awaits-human'; return step
    if mid not in pending_modules(b): return step
    if m.get('effective_quality') == 'yellow-blocked':
        step.update(operation='audit-block', ready=True, reason='audit-evidence-stale'); return step
    if not dependencies_done(s,b,mid): step['reason'] = 'dependency-verification-pending'; return step
    if mid in owners(b) and mid not in b['started_owners']:
        step.update(operation='audit-work', ready=True, reason=None); return step
    if m.get('audit_batch_id') == b['batch_id'] and m['phase'] in ('diagnosing', 'fixing', 'testing', 'dod'): return None
    if not completed(s,b,mid): step.update(operation='audit-retest', ready=True, reason=None)
    return step


def global_step(s):
    if not active(s): return None
    b = s['audit_batch']; status = b['status']
    op = {'collected': 'audit-plan', 'planned': 'audit-route-batch'}.get(status)
    decision = None
    if status == 'awaiting-human':
        decision = next((d for d in s['decisions'].values() if d.get('module_id') is None and not d.get('consumed')
                         and d.get('subject_sha256') == digest(b['human_report'])), None)
        if decision: op = 'audit-release'
    if status == 'repairing' and all(completed(s,b,mid) for mid in pending_modules(b)) and all(
            not any(not a.get('closed') for a in m['assignments'].values()) for m in s['modules'].values()): op = 'audit-verdict'
    return {'operation': op, 'role': 'global-orchestrator' if op in ('audit-route-batch', 'audit-release') else 'auditor',
            'ready': bool(op), 'batch_id': b['batch_id'], 'payload': {'decision_id':decision['decision_id']} if decision else {}, 'human_finding_ids': list(b.get('human_issues', {})),
            'reason': None if op else 'human-review-required' if status == 'awaiting-human' else 'await-fixer-and-testing'}
