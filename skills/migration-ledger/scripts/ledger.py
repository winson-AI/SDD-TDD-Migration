#!/usr/bin/env python3
"""Local transactional Ledger. Host must authenticate principals and enforce write isolation."""
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys

import workflow
import audit_closure
import decomposition
import reuse
import project_context
import context_readiness
import test_validation as tv
from openspec_projection import materialize

from contracts import (Rejected, baseline, check_ref, digest, file_ref, keyed, nonempty,
                       read_json, require, validate_plan, validate_result, verify_plan)


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def overlaps(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a.is_relative_to(b) or b.is_relative_to(a)


def refresh(s):
    for m in s['modules'].values():
        qualities = [p['quality'] for p in m['results'].values()] + [p['quality'] for p in m.get('repair_findings', {}).values()]
        m['quality'] = ('red-bug' if 'red-bug' in qualities else
                        'green-passed' if m['phase'] == 'completed' and not m['stale'] else 'yellow-blocked')
    decomposition.refresh_groups(s)
    mods = list(s['modules'].values())
    s['quality'] = ('red-bug' if any(m['quality'] == 'red-bug' for m in mods) or s.get('audit', {}).get('quality') == 'red-bug' else
                    'green-passed' if mods and all(m['quality'] == 'green-passed' for m in mods)
                    and all(decomposition.summary_current(s, group) for group in s.get('module_groups', {}).values())
                    and s.get('audit', {}).get('quality') == 'green-passed' else 'yellow-blocked')


def read_events(root):
    path = root / 'ledger/events.jsonl'
    state, events, prev = None, [], None
    if not path.exists():
        return state, events
    for line in path.read_bytes().splitlines(keepends=True):
        require(line.endswith(b'\n'), 'incomplete journal tail; stop and recover from verified backup')
        e = json.loads(line)
        body = {k: v for k, v in e.items() if k != 'sha256'}
        require(digest(body) == e['sha256'] and e['previous_hash'] == prev, 'journal integrity failure')
        require(e['sequence'] == len(events) + 1, 'journal sequence failure')
        if state is None:
            state = e['effect']
        else:
            state.update(e['effect'])
        events.append(e)
        prev = e['sha256']
    return state, events


def project(root, s, sequence):
    atomic(root / 'ledger/global.json', {**s, 'last_sequence': sequence, 'parent_mo_names': decomposition.parent_mo_names(s)})
    for mid, m in s['modules'].items():
        atomic(root / f'ledger/modules/{mid}.json', {**m, 'last_sequence': sequence})
    for mid, group in s.get('module_groups', {}).items():
        atomic(root / f'ledger/modules/{mid}.json', {**group, 'last_sequence': sequence})
    materialize(root, {**s, 'projection_steps': {mid: next_step(s, m) for mid, m in s['modules'].items()}}, sequence)


def role(principal, *roles):
    require(principal.get('role') in roles and principal.get('instance_id'), 'principal role denied')


def current(m):
    verify_plan(m['plan'])
    if m.get('code_files'):
        require(baseline(m['code_files']) == m['code_baseline'], 'code evidence stale; invalidate before continuing')


def invalidate_dependents(s, mid):
    pending = [mid]
    visited = set()
    while pending:
        parent = pending.pop()
        if parent in visited:
            continue
        visited.add(parent)
        for m in s['modules'].values():
            if parent in m['dependencies']:
                m['stale'] = True
                resume_phase = 'frozen' if m.get('freeze_id') else (m.get('blocked') or {}).get('resume_phase', m['phase'])
                if m['module_id'] not in s.get('audit_queue', {}):
                    m['phase'] = 'waiting-dependency'
                    m['blocked'] = {'kind': 'dependency', 'reason': 'dependency-version-changed', 'resume_phase': resume_phase}
                else:
                    s.get('audit_resolutions', {}).pop(m['module_id'], None)
                m['revision'] += 1
                pending.append(m['module_id'])
    s['audit'] = {}


def dependencies_ready(s, m):
    require(all(tv.available(s['modules'][d])
                for d in m['dependencies']), 'dependencies not complete')
    for d in m['dependencies']:
        current(s['modules'][d])


def failure_fingerprint(results):
    return digest(sorted((pid, r['quality'], r.get('root_cause', {}).get('category'),
                          r.get('root_cause', {}).get('summary'), r.get('root_cause', {}).get('owner'))
                         for pid, r in results.items() if r['quality'] != 'green-passed'))


def worker_phase(m, assignment):
    expected = {'implementer': 'implementing', 'fixer': 'fixing', 'test-runner': 'testing'}
    require(not m.get('blocked') and m['phase'] == expected[assignment['role']], 'worker result is not valid in current phase')


def approval(s, m, subject):
    return next((d for d in s['decisions'].values() if d.get('module_id') == m['module_id']
                 and d.get('subject_sha256') == subject and not d.get('consumed')), None)


def within_envelope(m, impact_ref):
    require(m.get('approved_envelope') == digest(m['plan']['decision_envelope']), 'decision envelope changed')
    require(m.get('approved_acceptance') == digest(m['plan']['paths']), 'acceptance/path set changed')
    require(impact_ref, 'independent impact review required')
    check_ref(impact_ref)


def unresolved(m):
    if m['stale']:
        return {}
    results = dict(m['results'])
    results.update(m.get('repair_findings', {}))
    return {k: v for k, v in results.items() if v['quality'] != 'green-passed'}


def diagnosis_subject(m):
    return digest({'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'issues': unresolved(m)})


def idle(m):
    require(not any(not a.get('closed') for a in m['assignments'].values()), 'worker still active')


def complete_guard(s, m):
    require(m['phase'] == 'dod' and not m['stale'] and m['results'] and
            all(r['quality'] == 'green-passed' for r in m['results'].values()) and
            set(m['results']) == {p['path_id'] for p in m['plan']['paths']}, 'DoD requires all paths Green')
    current(m); dependencies_ready(s, m)


def pending_repairs(s):
    return {pid: item for pid, item in s.get('audit_repairs', {}).items()
            if not item.get('module_ids') or set(item['module_ids']) != set(item.get('accepted_by', []))}


def dispatch_guard(s, m, worker):
    workflow.planning_guard(s)
    if m.get('parent_module_id'):
        decomposition.check_module_plan(s, m, m['plan'])
    if audit_closure.active(s):
        b = s['audit_batch']
        require(b['status'] == 'repairing' and m.get('audit_batch_id') == b['batch_id'], 'audit closure owns dispatch; human review may be required')
        require(worker in ('fixer', 'test-runner'), 'audit closure only fixes and verifies')
        require(m['module_id'] in audit_closure.pending_modules(b) and audit_closure.dependencies_done(s, b, m['module_id']),
                'audit finding blocked or upstream verification incomplete')
    require(not workflow.audit_active(s), 'audit snapshot locked; close audit before dispatch')
    require(not m.get('blocked'), 'module blocked')
    idle(m); current(m); dependencies_ready(s, m)
    required = {rid for rid, owners in s['global_plan']['content']['requirement_owners'].items() if m['module_id'] in owners}
    require(required <= {rid for task in m['plan']['tasks'] for rid in task.get('global_requirement_ids', task.get('requirement_ids', []))}, 'module plan misses global requirements')
    active = sum(not a.get('closed') for mod in s['modules'].values() for a in mod['assignments'].values())
    require(active < s['max_parallel_modules'], 'parallel budget exhausted')
    require(m['no_progress_rounds'] < s['max_no_progress_rounds'], 'no-progress budget exhausted')
    for other in s['modules'].values():
        if any(not a.get('closed') for a in other['assignments'].values()):
            require(not any(overlaps(x, y) for x in m['write_paths'] for y in other['write_paths']), 'resource lock conflict')
    require(m['phase'] == {'implementer': 'frozen', 'fixer': 'diagnosing', 'test-runner': 'testing'}[worker], 'worker phase gate rejected')
    if worker == 'test-runner':
        require(not (unresolved(m) and workflow.defer_reason(m)) or m.get('automation_retry_ready'), 'unresolved failure awaits Auditor')
        require(m['code_baseline'], 'code must be accepted before testing')
    if worker == 'fixer':
        require(not workflow.defer_reason(m), 'local repair deferred to Auditor')
        require(m['fix_rounds_used'] < m.get('fix_budget', s['max_fix_rounds']), 'fix budget exhausted; recover requires decision')


def resume_guard(s, m, p):
    require(m['blocked'] and m['phase'] in ('waiting-dependency', 'waiting-human'), 'module is not suspended')
    require(m['blocked']['resume_phase'] not in ('waiting-dependency', 'waiting-human', 'completed'), 'invalid resume phase')
    if m['blocked']['kind'] == 'dependency':
        dependencies_ready(s, m)
        require(m.get('dependency_release') == {d: s['modules'][d]['code_baseline'] for d in m['dependencies']}, 'Global dependency release missing/stale')
    else:
        decision = approval(s, m, digest(m['blocked']))
        selected = s['decisions'].get(p.get('decision_id'))
        require(decision and selected and selected.get('subject_sha256') == digest(m['blocked'])
                and selected.get('module_id') == m['module_id'] and not selected.get('consumed'), 'resume needs current blocker decision')
    if m.get('plan'):
        current(m)


def _next_step(s, m):
    """Derived dispatch guidance only; every mutation must still pass its own guards."""
    batch_step = audit_closure.module_step(s, m)
    if batch_step is not None:
        return batch_step
    active = next((a for a in m['assignments'].values() if not a.get('closed')), None)
    step = {'module_id': m['module_id'], 'phase': m['phase'], 'expected_revision': m['revision'],
            'operation': None, 'role': None, 'ready': False, 'reason': None,
            'session_id': None, 'assignment_id': active['assignment_id'] if active else None}
    if m.get('effective_quality') == 'yellow-blocked':
        step.update(operation='revoke' if active else 'invalidate', role='host' if active else 'module-orchestrator', reason='evidence-stale')
    elif m['phase'] == 'automation-deferred':
        step.update(role='module-orchestrator', reason='automation-not-run; other work may continue')
        for receipt in m.get('context_receipts', {}).values():
            try:
                context_readiness.validate(s, m['module_id'], 'testing', receipt['report_ref'])
                step.update(operation='automation-resume', ready=True, payload={'context_ref': receipt['report_ref']})
                break
            except (Rejected, OSError, ValueError):
                pass
    elif m['phase'] == 'waiting-auditor':
        resolution = s.get('audit_resolutions', {}).get(m['module_id'])
        step.update(operation='audit-resume' if resolution else None, role='module-orchestrator',
                    ready=bool(resolution and resolution['action'] not in ('wait', 'human')),
                    reason='await-auditor' if not resolution else resolution['action'])
        if resolution and resolution['action'] == 'human':
            decision = approval(s, m, digest(resolution))
            step.update(ready=bool(decision), payload={'decision_id': decision['decision_id']} if decision else {})
    elif m.get('blocked'):
        if active:
            step.update(operation='revoke', role='host', reason='stop-invalidated-worker')
        elif m['blocked']['kind'] == 'dependency':
            deps = {d: s['modules'][d]['code_baseline'] for d in m['dependencies']}
            available = all(tv.available(s['modules'][d])
                            and s['modules'][d].get('effective_quality') != 'yellow-blocked' for d in m['dependencies'])
            released = m.get('dependency_release') == deps
            step.update(operation='resume' if released else 'dependency-ready',
                        role='module-orchestrator' if released else 'global-orchestrator',
                        ready=available, reason=None if available else 'dependency-incomplete')
        else:
            decision = approval(s, m, digest(m['blocked']))
            step.update(operation='resume', role='module-orchestrator', ready=bool(decision),
                        decision_id=decision.get('decision_id') if decision else None,
                        reason=None if decision else 'human-decision-required')
    elif active:
        submitted = active['assignment_id'] in m['submissions']
        step.update(operation='accept' if submitted else 'await-result',
                    role='module-orchestrator' if submitted else active['role'], ready=submitted,
                    reason=None if submitted else 'worker-running')
    elif m.get('decomposition_submission'):
        step.update(operation='decompose-accept', role='global-orchestrator', ready=True)
    elif m.get('decomposition_required') and m['phase'] in ('context', 'specifying', 'clarifying'):
        step.update(operation='decompose', role='module-orchestrator', ready=True)
    elif m['phase'] in ('completed', 'testing') and any(m['module_id'] in r.get('module_ids', []) and m['module_id'] not in r.get('accepted_by', [])
             for r in pending_repairs(s).values()):
        step.update(operation='repair-accept', role='module-orchestrator', ready=True,
                    path_ids=[pid for pid, r in pending_repairs(s).items() if m['module_id'] in r.get('module_ids', [])
                              and m['module_id'] not in r.get('accepted_by', [])])
    elif m['phase'] in ('context', 'specifying', 'change-review'):
        step.update(operation='plan', role='spec-designer', ready=True)
    elif m['phase'] == 'clarifying':
        decision = approval(s, m, m['plan_hash'])
        impact = m.get('change_request', {}).get('impact_ref')
        eligible = False
        if not decision:
            try:
                within_envelope(m, impact)
                eligible = True
            except (Rejected, OSError, TypeError):
                pass
        step.update(operation='freeze', role='module-orchestrator', ready=bool(decision) or eligible,
                    payload={'decision_id': decision['decision_id']} if decision else
                            {'change_class': 'within-envelope', 'impact_ref': impact} if eligible else {},
                    reason=None if decision or eligible else 'approval-or-impact-review-required')
    elif m['phase'] in ('frozen', 'testing', 'diagnosing'):
        bad = unresolved(m)
        if m['phase'] == 'testing' and bad and not m.get('automation_retry_ready'):
            draft = m.get('diagnosis_submission')
            categories = {r.get('root_cause', {}).get('category') for r in bad.values()}
            if draft and draft['subject'] == diagnosis_subject(m):
                step.update(operation='diagnosis-accept', role='module-orchestrator', ready=True)
            elif workflow.defer_reason(m):
                step.update(operation='audit-defer', role='module-orchestrator', ready=True,
                            root_cause=workflow.defer_reason(m), reason='auditor-handoff')
            else:
                step.update(operation='diagnose', role='diagnostician', ready=True)
        else:
            worker = {'frozen': 'implementer', 'testing': 'test-runner', 'diagnosing': 'fixer'}[m['phase']]
            if worker == 'fixer' and workflow.defer_reason(m):
                step.update(operation='audit-defer', role='module-orchestrator', ready=True,
                            root_cause=workflow.defer_reason(m), reason='auditor-handoff')
                return step
            exhausted = m['no_progress_rounds'] >= s['max_no_progress_rounds'] or (worker == 'fixer' and
                         m['fix_rounds_used'] >= m.get('fix_budget', s['max_fix_rounds']))
            step.update(operation='recover' if exhausted else 'assign', role='module-orchestrator',
                        worker_role=worker, ready=not exhausted, reason='budget-exhausted' if exhausted else None)
            if worker == 'test-runner' and tv.split(m):
                step['test_scope'] = 'automation' if tv.build_ready(m) else 'build'
                step['payload'] = {'test_scope': step['test_scope']}
            if step['ready']:
                try:
                    dispatch_guard(s, m, worker)
                except (Rejected, OSError) as exc:
                    step.update(ready=False, reason=str(exc))
    elif m['phase'] == 'dod':
        step.update(operation='complete', role='module-orchestrator', ready=True)
        try:
            complete_guard(s, m)
        except (Rejected, OSError):
            step.update(ready=False, reason='DoD-or-baseline-incomplete')
    elif m['phase'] == 'completed':
        step.update(reason='module-complete')
    else:
        step.update(reason='unrecognized-phase')
    if step['ready']:
        try:
            if step['operation'] == 'resume':
                resume_guard(s, m, {'decision_id': step.get('decision_id')})
            elif step['operation'] == 'freeze':
                require(not m.get('blocked') and validate_plan(m['plan'], m) == m['plan_hash'], 'plan changed/blocked')
            elif step['operation'] == 'repair-accept':
                idle(m); current(m); dependencies_ready(s, m)
        except (Rejected, OSError) as exc:
            step.update(ready=False, reason=str(exc))
    session_role = step.get('worker_role') or step['role']
    step['session_id'] = m['sessions'].get(session_role, {}).get('session_id')
    return step


def next_step(s, m):
    step = context_readiness.annotate(s, m['module_id'], _next_step(s, m))
    if m.get('decomposition_required') and step['role'] == 'module-orchestrator':
        step['agent_name'] = 'parent-mo-' + m['module_id']
    return step


def new_module(p):
    require(re.fullmatch(r'M[0-9]{3,}', p.get('module_id', '')), 'invalid module id')
    nonempty(p.get('case_ids'), 'module cases')
    nonempty(p.get('write_paths'), 'write paths')
    require(all(Path(x).is_absolute() for x in p['write_paths']), 'absolute write paths required')
    return {**p, 'revision': 0, 'phase': 'context', 'quality': 'yellow-blocked', 'stale': True,
            'plan': None, 'freeze_id': None, 'code_files': [], 'code_baseline': None,
            'results': {}, 'submissions': {}, 'assignments': {}, 'sessions': {},
            'fix_rounds_used': 0, 'total_fix_rounds': 0, 'recovery_cycle': 0,
            'no_progress_rounds': 0, 'blocked': None, 'authors': [], 'local_fix_used': 0, 'fix_memory': [],
            'dependencies': p.get('dependencies', [])}


def audit_scope(s):
    """Select unresolved paths, never expand an audit into a full project replay.

    Optional GLOBAL-only cases not yet executed (or invalidated by code changes)
    are unverified, rather than implicitly Green. Module Green evidence is reused.
    """
    refs = [ref for m in s['modules'].values() for ref in m['code_files']]
    code_baseline = baseline(refs)
    results = dict(s.get('audit_results', {}))
    selected = []
    for path in s.get('global_paths', []):
        previous = results.get(path['path_id'])
        if not previous or previous['quality'] != 'green-passed' or previous.get('code_baseline') != code_baseline:
            selected.append(path)
    for m in s['modules'].values():
        for path in m['plan']['paths']:
            previous = m['results'].get(path['path_id'])
            if previous and previous['quality'] != 'green-passed':
                selected.append(path)
                results[path['path_id']] = previous
    return {'freeze_id': digest({k:v['freeze_id'] for k,v in s['modules'].items()}),
            'code_files': refs, 'code_baseline': code_baseline,
            'plan': {'definitions': [], 'paths': selected},
            'results': results,
            'stale': any(results.get(p['path_id'], {}).get('quality') == 'green-passed' for p in selected)}


def mutate(s, req, principal, events):
    op, p = req['operation'], req.get('payload', {})
    audit_before = copy.deepcopy(s['modules']) if audit_closure.active(s) or op in audit_closure.OPS else {}
    mid = req.get('module_id')
    global_ops = {'register', 'decision', 'audit-assign', 'audit', 'audit-revoke', 'audit-route', 'audit-unavailable'} | workflow.GLOBAL_OPERATIONS | audit_closure.GLOBAL_OPS
    if op == 'context-submit' and mid is None:
        global_ops.add(op)
    require((mid is None) == (op in global_ops), 'operation has incorrect global/module scope')
    m = s['modules'].get(mid) or s.get('module_groups', {}).get(mid)
    if mid:
        require(m is not None, 'module not registered')
        if mid in s.get('module_groups', {}):
            require(op in ('module-summary', 'session'), 'parent MO only coordinates/summarizes; execute code and tests in child modules')
    if workflow.audit_active(s) and op not in ('audit', 'problem-audit', 'audit-revoke', 'decision'):
        raise Rejected('audit snapshot locked; close or revoke audit before mutation')
    if audit_closure.active(s) and op not in audit_closure.OPS | {'decision', 'assign', 'submit', 'accept', 'complete', 'revoke', 'session', 'module-summary', 'context-submit', 'automation-unavailable'}:
        raise Rejected('audit closure active; complete verification or obtain human review')
    context_readiness.gate(s, req, principal)
    if op == 'context-submit':
        context_readiness.submit(s, req, principal)
    elif op in tv.OPS:
        tv.handle(s, req, principal)
    elif op in decomposition.OPERATIONS:
        decomposition.handle(s, req, principal)
    elif op in audit_closure.OPS:
        audit_closure.handle(s, req, principal)
    elif op in workflow.OPERATIONS:
        workflow.handle(s, req, principal)
        if op == 'audit-resume' and m['phase'] != 'waiting-auditor':
            invalidate_dependents(s, mid)
    elif op == 'register':
        role(principal, 'global-orchestrator')
        mid = p['module_id']
        if s.get('entry_mode', 'project') == 'single-module':
            # Direct registration selects the root; accepted MO decomposition
            # registers its children (and their internal DAG) atomically.
            require(mid == s['single_module_id'] and not s['modules'], 'single-module run only permits the selected module as a root; register children via decompose-accept')
            require(not p.get('dependencies'), 'single-module input must be independent of other roots; internal child dependencies are allowed')
            require(set(p.get('case_ids', [])) == set(s['case_ids']), 'single-module case coverage mismatch')
        require(mid not in s['modules'] and mid not in s.get('module_groups', {}), 'module already registered')
        require(set(p.get('dependencies', [])) <= set(s['modules']), 'register dependencies first; cycles/missing modules forbidden')
        require(set(p['case_ids']) <= set(s['case_ids']), 'unknown global case')
        require(all(Path(x).resolve().is_relative_to(Path(s['target_root'])) for x in p['write_paths']), 'write scope outside target')
        require(not p.get('parent_module_id'), 'register GO root modules; children require decompose-accept')
        if p.get('decomposition_required'):
            decomposition.check_scope(p)
            require(set(p['scope']['requirement_ids']) <= set(s['requirement_ids']), 'unknown global requirement in root scope')
        s['modules'][mid] = new_module(p)
        s['global_plan'] = None
    elif op == 'decision':
        role(principal, 'host')
        require(p.get('decision') == 'approved' and p.get('human_source_ref') and p.get('subject_sha256'), 'actual human approval required')
        check_ref(p['human_source_ref'])
        require(p.get('decision_id') not in s['decisions'], 'decision already exists')
        s['decisions'][p['decision_id']] = {**p, 'consumed': False}
    elif op == 'plan':
        role(principal, 'spec-designer')
        require(not m.get('decomposition_required') and not m.get('decomposition_submission'), 'finish MO decomposition before leaf SPEC planning')
        require(m['phase'] in ('context', 'specifying', 'clarifying', 'change-review'), 'plan not editable in this phase')
        plan = read_json(check_ref(p['plan_ref']))
        if m.get('parent_module_id'):
            decomposition.check_module_plan(s, m, plan)
        plan_hash = validate_plan(plan, m)
        if s.get('split_testing_required') or any(path.get('kind') == 'build' for path in plan['paths']):
            tv.plan_check(plan, s['target_root'])
        if m.get('parent_module_id') or s.get('reuse_required') or plan.get('reuse_plan_ref'):
            reuse.validate_plan(plan, m, reuse.sources(s), s['modules'], s['legacy_root'])
        occupied = {path['path_id'] for path in s['global_paths']}
        occupied.update(path['path_id'] for other in s['modules'].values() if other['module_id'] != mid
                        and other.get('plan') for path in other['plan']['paths'])
        require(not occupied.intersection(path['path_id'] for path in plan['paths']), 'PATH IDs must be globally unique')
        # Plan is content; the artifact remains immutable and is checked at freeze/dispatch.
        m.update(plan=plan, plan_ref=p['plan_ref'], plan_hash=plan_hash, phase='clarifying')
    elif op == 'freeze':
        role(principal, 'module-orchestrator')
        if m.get('parent_module_id'):
            decomposition.check_module_plan(s, m, m['plan'])
        require(m['phase'] == 'clarifying' and not m.get('blocked'), 'freeze requires unblocked clarifying')
        verify_plan(m['plan'])
        require(validate_plan(m['plan'], m) == m['plan_hash'], 'plan changed')
        decision = s['decisions'].get(p.get('decision_id'), {})
        if p.get('change_class') == 'within-envelope':
            within_envelope(m, p.get('impact_ref'))
        else:
            require(decision.get('subject_sha256') == m['plan_hash'] and decision.get('module_id') == mid and
                    not decision.get('consumed'), 'approval missing/stale/wrong module')
            decision['consumed'] = True
            m['approved_envelope'] = digest(m['plan']['decision_envelope'])
            m['approved_acceptance'] = digest(m['plan']['paths'])
        m.update(freeze_id=m['plan_hash'], phase='frozen', stale=True)
    elif op == 'change':
        role(principal, 'module-orchestrator')
        require(m.get('freeze_id') and p.get('request_ref') and p.get('impact_ref'), 'CR and impact required')
        check_ref(p['request_ref']); check_ref(p['impact_ref'])
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'close active assignments before CR')
        require(not m.get('blocked'), 'resolve blocker or invalidate before CR')
        m.update(phase='change-review', stale=True, change_request=p, diagnosis_submission=None)
        invalidate_dependents(s, mid)
    elif op == 'assign':
        role(principal, 'module-orchestrator')
        require(p.get('role') in ('implementer', 'fixer', 'test-runner'), 'unsupported worker role')
        require(p.get('instance_id') and p.get('assignment_id') not in m['assignments'], 'invalid/duplicate assignment')
        if audit_closure.active(s):
            require(p.get('instance_id') != s['audit_batch']['auditor_instance_id'], 'Auditor cannot implement or author verification')
        dispatch_guard(s, m, p['role'])
        if p['role'] == 'test-runner' and tv.split(m):
            require(p.get('test_scope') == ('automation' if tv.build_ready(m) else 'build'), 'build must precede automation')
        if p['instance_id'] not in m['authors']:
            m['authors'].append(p['instance_id'])
        if p['role'] in ('implementer', 'fixer'):
            if p['role'] == 'fixer':
                m.setdefault('fix_memory', []).append({'assignment_id': p['assignment_id'], 'audit_batch_id': m.get('audit_batch_id'), 'freeze_id': m['freeze_id'],
                    'before_baseline': m['code_baseline'], 'diagnosis': m.get('diagnosis'), 'issues': copy.deepcopy(unresolved(m)),
                    'status': 'pending', 'reusable': False})
                if not m.pop('audit_fix_grant', None):
                    m['local_fix_used'] = m.get('local_fix_used', 0) + 1
                else:
                    m['auditor_fix_used'] = True
                m['fix_rounds_used'] += 1
                m['total_fix_rounds'] += 1
            m['phase'] = 'implementing' if p['role'] == 'implementer' else 'fixing'
        m['assignments'][p['assignment_id']] = {**p, 'run_id': s['run_id'], 'module_id': mid,
            'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'closed': False,
            'fencing_token': len(events) + 1}
    elif op == 'submit':
        assignment = m['assignments'].get(p.get('assignment_id'), {})
        require(not assignment.get('closed', True), 'assignment inactive')
        require(principal == {'role': assignment['role'], 'instance_id': assignment['instance_id']}, 'worker identity mismatch')
        require(p.get('fencing_token') == assignment['fencing_token'], 'stale fencing token')
        require(assignment['freeze_id'] == m['freeze_id'], 'assignment freeze stale')
        worker_phase(m, assignment)
        dependencies_ready(s, m)
        result = read_json(check_ref(p['result_ref']))
        validate_result(result, m, assignment)
        m['submissions'][p['assignment_id']] = {'ref': p['result_ref'], 'result': result}
    elif op == 'accept':
        role(principal, 'module-orchestrator')
        aid = p['assignment_id']
        assignment = m['assignments'].get(aid, {})
        require(not assignment.get('closed', True) and aid in m['submissions'], 'no active submission')
        worker_phase(m, assignment)
        dependencies_ready(s, m)
        sub = m['submissions'][aid]
        check_ref(sub['ref'])
        result = sub['result']
        kind = validate_result(result, m, assignment)
        assignment['closed'] = True
        if kind == 'implementation':
            m['accepted_task_ids'] = [t['task_id'] for t in result['task_trace']]
            if assignment['role'] == 'fixer':
                memory = next(x for x in m['fix_memory'] if x['assignment_id'] == aid)
                memory.update(after_baseline=result['code_baseline'], implementation_ref=sub['ref'],
                              fix_note_ref=result['fix_note_ref'], status='awaiting-regression')
            m.update(code_files=result['code_files'], code_baseline=result['code_baseline'], phase='testing', stale=True, build_baseline=None)
            m.pop('automation_retry_ready', None)
            invalidate_dependents(s, mid)
        else:
            previous_fingerprint = failure_fingerprint(m['results'])
            if tv.split(m):
                m['results'].update({x['path_id']: {**x, 'code_baseline': m['code_baseline']} for x in result['paths']})
                if assignment.get('test_scope') == 'build':
                    m['build_baseline'] = m['code_baseline'] if all(x['quality'] == 'green-passed' for x in result['paths']) else None
                else:
                    m.pop('automation_retry_ready', None)
            else:
                m['results'] = {x['path_id']: x for x in result['paths']}
            build_only = tv.split(m) and assignment.get('test_scope') == 'build'
            bad = sorted(x['path_id'] for x in result['paths'] if x['quality'] != 'green-passed') if build_only else sorted(k for k,v in m['results'].items() if v['quality'] != 'green-passed')
            if build_only and not bad:
                m['automation_retry_ready'] = True
            m['no_progress_rounds'] = m['no_progress_rounds'] + 1 if bad and failure_fingerprint(m['results']) == previous_fingerprint else 0
            for memory in m.get('fix_memory', []):
                if not build_only and memory['status'] == 'awaiting-regression' and memory.get('after_baseline') == m['code_baseline']:
                    memory.update(status='verified' if not bad else 'failed', reusable=not bad,
                                  regression_ref=sub['ref'], regression_paths=copy.deepcopy(result['paths']))
            m.update(stale=False, phase='dod' if not bad and not build_only else 'testing', diagnosis_submission=None, diagnosis=None, repair_findings={})
            if not build_only:
                audit_closure.test_accepted(s, m, result, sub['ref'])
    elif op == 'diagnose':
        role(principal, 'diagnostician')
        require(m['phase'] == 'testing' and not m.get('blocked') and unresolved(m), 'no unresolved test failure')
        idle(m); current(m)
        check_ref(p['diagnosis_ref'])
        require(p.get('owner') and p.get('root_cause'), 'root cause and owner required')
        m['diagnosis_submission'] = {'report': p, 'subject': diagnosis_subject(m)}
    elif op == 'diagnosis-accept':
        role(principal, 'module-orchestrator')
        idle(m); current(m)
        draft = m.get('diagnosis_submission')
        require(m['phase'] == 'testing' and not m.get('blocked') and unresolved(m) and draft
                and draft['subject'] == diagnosis_subject(m), 'diagnosis missing/stale')
        check_ref(draft['report']['diagnosis_ref'])
        m.update(diagnosis=draft['report'], diagnosis_submission=None, phase='diagnosing')
    elif op == 'suspend':
        role(principal, 'module-orchestrator')
        require(not m.get('blocked') and m['phase'] != 'completed', 'cannot stack blockers or suspend completed module')
        require(p.get('reason') and p.get('root_cause') and p.get('owner'), 'structured blocker required')
        require(p.get('kind') in ('dependency', 'human', 'tooling'), 'invalid blocker')
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'stop/revoke workers before suspension')
        blocked_on = []
        if p['kind'] == 'dependency':
            for dep in m['dependencies']:
                try:
                    dependencies_ready(s, {'dependencies': [dep]})
                except (Rejected, OSError):
                    blocked_on.append(dep)
            require(blocked_on, 'dependency suspension requires an unavailable registered dependency; peer failure is not a blocker')
        m['blocked'] = {**p, 'resume_phase': m['phase']}
        if blocked_on:
            m['blocked']['dependency_module_ids'] = blocked_on
        m['phase'] = 'waiting-dependency' if p['kind'] == 'dependency' else 'waiting-human'
    elif op == 'dependency-ready':
        role(principal, 'global-orchestrator')
        dependencies_ready(s, m)
        require(m['phase'] == 'waiting-dependency', 'consumer not waiting')
        m['dependency_release'] = {d: s['modules'][d]['code_baseline'] for d in m['dependencies']}
    elif op == 'resume':
        role(principal, 'module-orchestrator')
        resume_guard(s, m, p)
        if m['blocked']['kind'] == 'dependency':
            m.pop('dependency_release', None)
        else:
            s['decisions'][p['decision_id']]['consumed'] = True
        m['phase'] = 'testing' if m['blocked']['resume_phase'] == 'dod' else m['blocked']['resume_phase']
        m['blocked'] = None
        m['stale'] = True
    elif op == 'recover':
        role(principal, 'module-orchestrator')
        require(m['fix_rounds_used'] >= m.get('fix_budget', s['max_fix_rounds']) or
                m['no_progress_rounds'] >= s['max_no_progress_rounds'], 'recover only after budget exhaustion')
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'worker still active')
        decision = s['decisions'].get(p.get('decision_id'), {})
        subject = digest({'module_id': mid, 'revision': m['revision'], 'recovery_cycle': m['recovery_cycle'], 'additional_rounds': p.get('additional_rounds')})
        require(decision.get('subject_sha256') == subject and decision.get('module_id') == mid and
                not decision.get('consumed'), 'new explicit recovery decision required')
        require(type(p.get('additional_rounds')) is int and 0 < p['additional_rounds'] <= 100, 'invalid additional budget')
        decision['consumed'] = True
        m['recovery_cycle'] += 1
        m['fix_budget'] = m['fix_rounds_used'] + p['additional_rounds']
        m['no_progress_rounds'] = 0
        m['blocked'] = None
        m['phase'] = 'diagnosing' if m.get('diagnosis') else 'testing'
    elif op == 'session':
        role(principal, 'module-orchestrator')
        name = p['role']
        require(p.get('session_id'), 'session id required')
        parent_name = decomposition.parent_mo_names(s).get(mid)
        if name == 'module-orchestrator' and parent_name:
            require(p.get('agent_name', parent_name) == parent_name, 'parent MO name must be ' + parent_name)
            p = {**p, 'agent_name': parent_name}
        previous = m['sessions'].get(name)
        if previous and previous['session_id'] != p['session_id']:
            require(p.get('reason') == 'session-unavailable' and p.get('checkpoint_ref'), 'replacement requires cold recovery record')
            check_ref(p['checkpoint_ref'])
            require(not any(not a.get('closed') for a in m['assignments'].values()), 'revoke old worker before cold recovery')
        m['sessions'][name] = p
    elif op == 'revoke':
        role(principal, 'host')
        a = m['assignments'].get(p.get('assignment_id'), {})
        require(a and not a.get('closed') and p.get('stopped_worker_ref'), 'active worker and host stop/isolation evidence required')
        check_ref(p['stopped_worker_ref'])
        a['closed'] = True
        if audit_closure.active(s) and m.get('audit_batch_id') == s['audit_batch']['batch_id']:
            audit_closure.stop(s, 'worker-interrupted', mid, p['stopped_worker_ref'])
        m['stale'] = True
        for memory in m.get('fix_memory', []):
            if memory['assignment_id'] == p['assignment_id'] and memory['status'] == 'pending':
                memory['status'] = 'interrupted'
        if not m.get('blocked'):
            m['phase'] = 'diagnosing' if a['role'] == 'fixer' else 'frozen' if a['role'] == 'implementer' else 'testing'
    elif op == 'invalidate':
        role(principal, 'module-orchestrator', 'host')
        require(p.get('reason'), 'invalidation reason required')
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'revoke worker before invalidation')
        if m.get('blocked'):
            m.pop('approved_envelope', None)
            m.pop('approved_acceptance', None)
        m.update(stale=True, phase='specifying', blocked=None, freeze_id=None, diagnosis_submission=None)
        m.pop('dependency_release', None)
        m['code_files'] = []
        m['code_baseline'] = None
        invalidate_dependents(s, mid)
    elif op == 'complete':
        role(principal, 'module-orchestrator')
        complete_guard(s, m)
        check_ref(p['dod_ref'])
        require(p.get('checks_passed') is True, 'DoD review required')
        m['phase'] = 'completed'
    elif op == 'audit-assign':
        role(principal, 'global-orchestrator')
        workflow.planning_guard(s)
        require(not audit_closure.collection_blockers(s), 'all module rounds must settle before Auditor')
        require(not audit_closure.active(s), 'audit closure incomplete')
        require(not s.get('audit_queue'), 'problem audit queue unresolved')
        require(not pending_repairs(s), 'audit repairs require routing and MO acceptance')
        require(s['modules'] and all(tv.available(x) for x in s['modules'].values()), 'modules incomplete')
        require(not s.get('audit_assignment') or s['audit_assignment'].get('closed'), 'audit already active')
        require(p.get('instance_id') and p.get('assignment_id'), 'audit identity required')
        require(p['assignment_id'] not in s.get('audit_assignment_ids', []), 'audit assignment id already used')
        for mod in s['modules'].values():
            require(p['instance_id'] not in mod['authors'], 'Auditor must be independent')
            current(mod)
        require(s.get('audit_attempts', 0) < s['max_audit_rounds'], 'audit budget exhausted; explicit new run required')
        s['audit_attempts'] = s.get('audit_attempts', 0) + 1
        s.setdefault('audit_assignment_ids', []).append(p['assignment_id'])
        s['audit_assignment'] = {**p, 'role': 'auditor', 'run_id': s['run_id'], 'module_id': 'GLOBAL',
                                 'closed': False, 'attempt': s['audit_attempts'],
                                 'scope_policy': 'non-green-only',
                                 'path_ids': [p['path_id'] for p in audit_scope(s)['plan']['paths']],
                                 'snapshot': {k:v['code_baseline'] for k,v in s['modules'].items()}}
    elif op == 'audit':
        role(principal, 'auditor')
        assignment = s.get('audit_assignment', {})
        require(assignment.get('mode') != 'problem', 'use problem-audit for problem assignment')
        require(not assignment.get('closed', True) and assignment.get('instance_id') == principal['instance_id'], 'audit assignment inactive/mismatch')
        require(s['modules'] and all(tv.available(x) for x in s['modules'].values()), 'modules incomplete')
        for mod in s['modules'].values():
            current(mod)
        report = read_json(check_ref(p['report_ref']))
        snapshot = {k:v['code_baseline'] for k,v in s['modules'].items()}
        require(report.get('snapshot') == snapshot == assignment['snapshot'], 'audit snapshot stale')
        scope = audit_scope(s)
        require(assignment.get('scope_policy') == 'non-green-only', 'legacy full audit assignment; revoke and reassign')
        require(assignment['path_ids'] == [p['path_id'] for p in scope['plan']['paths']], 'audit selection changed')
        validate_result(report, scope, assignment)
        qualities = [p['quality'] for p in report['paths']]
        quality = 'red-bug' if 'red-bug' in qualities else 'yellow-blocked' if 'yellow-blocked' in qualities else 'green-passed'
        s['audit'] = {'quality': quality, 'report_ref': p['report_ref'], 'paths': report['paths'],
                      'scope_policy': 'non-green-only', 'snapshot': snapshot,
                      'execution_status': 'no-retest-needed' if not report['paths'] else 'reviewed'}
        s.setdefault('audit_results', {}).update({r['path_id']: {**r, 'code_baseline': scope['code_baseline']} for r in report['paths']})
        owners = {path['path_id']: mid for mid, mod in s['modules'].items() for path in mod['plan']['paths']}
        s['audit_repairs'] = {r['path_id']: {'finding': r, 'report_ref': p['report_ref'],
                                'module_ids': [owners[r['path_id']]] if r['path_id'] in owners else [],
                                'accepted_by': []}
                              for r in report['paths'] if r['quality'] != 'green-passed'}
        for mod in s['modules'].values():
            if tv.deferred(mod):
                module_rows = [r for r in report['paths'] if r['path_id'] in {x['path_id'] for x in mod['plan']['paths']}]
                mod['results'].update({r['path_id']: {**r, 'code_baseline': mod['code_baseline'],
                                  'module_retest_of': mod['results'].get(r['path_id'], {}).get('test_run_id')} for r in module_rows})
                passed = bool(module_rows) and all(r['quality'] == 'green-passed' for r in mod['results'].values())
                mod.update(phase='dod' if passed else 'testing', blocked=None, stale=False, audit_acceptance_ref=p['report_ref'])
                if not all(mod['results'][x['path_id']]['quality'] == 'green-passed' for x in tv.paths(mod, 'build')):
                    mod['build_baseline'] = None
        assignment['closed'] = True
    elif op == 'audit-route':
        role(principal, 'global-orchestrator')
        item = s.get('audit_repairs', {}).get(p.get('path_id'))
        require(item and not item['module_ids'], 'only unassigned global findings can be routed')
        mids = nonempty(p.get('module_ids'), 'repair modules')
        require(len(set(mids)) == len(mids) and set(mids) <= set(s['modules']), 'unknown/duplicate repair module')
        check_ref(p.get('reason_ref'))
        item.update(module_ids=mids, reason_ref=p['reason_ref'])
        for mid in mids:
            s['modules'][mid]['revision'] += 1
    elif op == 'repair-accept':
        role(principal, 'module-orchestrator')
        idle(m); current(m); dependencies_ready(s, m)
        require(not m.get('blocked') and m['phase'] in ('completed', 'testing'), 'resolve existing module work before repair')
        ids = nonempty(p.get('path_ids'), 'repair paths')
        require(len(set(ids)) == len(ids), 'duplicate repair path')
        for pid in ids:
            item = s.get('audit_repairs', {}).get(pid)
            require(item and mid in item['module_ids'] and mid not in item['accepted_by'], 'repair not pending for module')
            check_ref(item['report_ref'])
            item['accepted_by'].append(mid)
            m.setdefault('repair_findings', {})[pid] = item['finding']
        m.update(phase='testing', stale=False, diagnosis_submission=None, audit_fix_grant='final-audit-repair')
        invalidate_dependents(s, mid)
    elif op == 'audit-revoke':
        role(principal, 'host')
        assignment = s.get('audit_assignment', {})
        require(assignment.get('assignment_id') == p.get('assignment_id') and not assignment.get('closed', True), 'audit not active')
        check_ref(p.get('stopped_worker_ref'))
        assignment['closed'] = True
    else:
        raise Rejected(f'unsupported operation: {op}')
    for changed_mid, before in audit_before.items():
        changed = s['modules'][changed_mid]
        if changed_mid != mid and changed != before and changed['revision'] == before['revision']:
            changed['revision'] += 1
    if m:
        m['revision'] += 1
    else:
        s['revision'] += 1
    refresh(s)


def preserve_refs(root, value, seen=None):
    """Archive evidence bytes before commit; keep live refs for stale-code detection."""
    seen = set() if seen is None else seen
    saved = []
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            key = (value['path'], value['sha256'])
            if key in seen:
                return []
            seen.add(key)
            path = check_ref(value)
            blob = root / 'artifacts' / value['sha256']
            blob.parent.mkdir(exist_ok=True)
            if not blob.exists():
                with blob.open('xb') as f:
                    f.write(path.read_bytes()); f.flush(); os.fsync(f.fileno())
            require(file_ref(blob)['sha256'] == value['sha256'], 'archived artifact corrupt')
            saved.append({'source_path': str(path), **file_ref(blob)})
            if path.suffix == '.json':
                try:
                    nested = read_json(path)
                except ValueError:
                    nested = None
                saved.extend(preserve_refs(root, nested, seen))
        else:
            for item in value.values():
                saved.extend(preserve_refs(root, item, seen))
    elif isinstance(value, list):
        for item in value:
            saved.extend(preserve_refs(root, item, seen))
    return saved


def apply(root, req, principal):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.ledger.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        s, events = read_events(root)
        if s and s.get('project_context_ref'):
            project_context.verify_snapshot(s['project_context_ref'])
        require(req.get('schema_version') == 1 and req.get('request_id'), 'version/request id required')
        request_hash = digest({'request': req, 'principal': principal})
        for e in events:
            if e['request_id'] == req['request_id']:
                require(e['request_hash'] == request_hash, 'request id reused with different content/actor')
                project(root, s, len(events))
                return {'event_id': e['event_id'], 'sequence': e['sequence'], 'duplicate': True}
        before = copy.deepcopy(s)
        if req['operation'] == 'init':
            role(principal, 'host')
            require(s is None and req.get('expected_revision') == 0, 'run exists or wrong initial revision')
            p = req['payload']
            entry_mode = p.get('entry_mode', 'project')
            require(entry_mode in ('project', 'single-module'), 'invalid entry mode')
            selected_module = p.get('single_module_id')
            if entry_mode == 'single-module':
                require(isinstance(selected_module, str) and re.fullmatch(r'M[0-9]{3,}', selected_module), 'selected module id required')
            else:
                require(selected_module is None, 'selected module requires single-module mode')
            require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', req.get('run_id', '')), 'invalid run id')
            require(Path(p['target_root']).is_absolute() and Path(p['target_root']).is_dir(), 'target root missing')
            require(Path(p['legacy_root']).is_absolute() and Path(p['legacy_root']).is_dir(), 'legacy root missing')
            require(not overlaps(p['legacy_root'], p['target_root']), 'legacy/target overlap')
            nonempty(p.get('case_ids'), 'global cases')
            require(len(set(p['case_ids'])) == len(p['case_ids']), 'duplicate global case')
            for field in ('global_spec', 'new_architecture'):
                check_ref(p.get(field))
            nonempty(p.get('requirement_ids'), 'global requirements')
            require(len(set(p['requirement_ids'])) == len(p['requirement_ids']), 'duplicate global requirement')
            reuse_sources = reuse.normalize_sources(p.get('reuse_sources', []), p['target_root'], existing=True)
            require(type(p.get('reuse_required', False)) is bool, 'reuse_required must be boolean')
            require(type(p.get('split_testing_required', True)) is bool, 'split_testing_required must be boolean')
            require(type(p.get('context_readiness_required', True)) is bool, 'context_readiness_required must be boolean')
            require(isinstance(p.get('build', {}), dict), 'build configuration must be an object')
            s = {'build': copy.deepcopy(p.get('build', {})), 'split_testing_required': p.get('split_testing_required', True), 'context_readiness_required': p.get('context_readiness_required', True),
                 'reuse_sources': reuse_sources, 'reuse_required': bool(reuse_sources) or p.get('reuse_required', False),
                 'entry_mode': entry_mode, 'single_module_id': selected_module,
                 'global_spec': p['global_spec'], 'new_architecture': p['new_architecture'], 'requirement_ids': p['requirement_ids'],
                 'global_plan': None, 'audit_queue': {}, 'run_id': req['run_id'], 'revision': 1, 'target_root': str(Path(p['target_root']).resolve()),
                 'legacy_root': str(Path(p['legacy_root']).resolve()), 'case_ids': p['case_ids'],
                 'modules': {}, 'decisions': {}, 'audit': {}, 'global_paths': p.get('global_paths', []), 'quality': 'yellow-blocked',
                 'max_parallel_modules': p.get('max_parallel_modules', 3), 'max_audit_rounds': p.get('max_audit_rounds', 3),
                 'max_fix_rounds': p.get('max_fix_rounds', 3), 'max_no_progress_rounds': p.get('max_no_progress_rounds', 2)}
            if s['global_paths']:
                paths = keyed(s['global_paths'], 'path_id')
                require(set(p['case_ids']) == {v.get('case_id') for v in paths.values()}, 'global path coverage mismatch')
                for path in paths.values():
                    assertions = keyed(path.get('expected_assertions'), 'assertion_id')
                    require(all('expected' in a for a in assertions.values()), 'global assertion expected value required')
            require(all(type(s[k]) is int and s[k] > 0 for k in ('max_fix_rounds', 'max_no_progress_rounds', 'max_parallel_modules', 'max_audit_rounds')), 'invalid budgets')
            if p.get('project_context_ref'):
                s.update(project_context.bind_run(p['project_context_ref'], root, req['run_id'], p))
            else:
                require(not (root / 'context/snapshot.json').exists(), 'prepared run requires project_context_ref')
        else:
            require(s and req.get('run_id') == s['run_id'], 'run mismatch')
            scope = (s['modules'].get(req.get('module_id')) or s.get('module_groups', {}).get(req.get('module_id'))) if req.get('module_id') else s
            require(scope is not None and req.get('expected_revision') == scope['revision'], 'stale revision')
            mutate(s, req, principal, events)
        # Store immutable event facts, not a second mutable state authority.
        effect = s if before is None else {k:v for k,v in s.items() if before.get(k) != v}
        e = {'schema_version': 1, 'event_id': f'E{len(events)+1:08d}', 'sequence': len(events)+1,
             'timestamp': now(), 'request_id': req['request_id'], 'request_hash': request_hash,
             'actor': principal, 'operation': req['operation'], 'module_id': req.get('module_id'),
             'previous_hash': events[-1]['sha256'] if events else None, 'effect': effect,
             'artifact_snapshots': preserve_refs(root, req.get('payload', {}))}
        e['sha256'] = digest(e)
        journal = root / 'ledger/events.jsonl'
        journal.parent.mkdir(exist_ok=True)
        with journal.open('a') as f:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + '\n')
            f.flush(); os.fsync(f.fileno())
        project(root, s, e['sequence'])
        return {'event_id': e['event_id'], 'sequence': e['sequence'], 'duplicate': False}


def status(root):
    root = Path(root).resolve()
    require(root.is_dir(), 'run root missing')
    with (root / '.ledger.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        s, events = read_events(root)
        require(s, 'run not initialized')
        if s.get('project_context_ref'):
            project_context.verify_snapshot(s['project_context_ref'])
        observed = []
        for mid, m in s['modules'].items():
            if m.get('plan'):
                try:
                    current(m)
                except (Rejected, OSError) as exc:
                    observed.append({'module_id': mid, 'reason': str(exc)})
                    m['effective_quality'] = 'yellow-blocked'
        decomposition.refresh_groups(s)
        project(root, s, len(events))
        cursor = [next_step(s, m) for m in s['modules'].values()]
        cursor += [decomposition.group_step(s, group) for group in s.get('module_groups', {}).values()]
        rounds = audit_closure.module_rounds(s, cursor)
        audit = s.get('audit_assignment', {})
        if audit_closure.active(s):
            global_next = audit_closure.global_step(s)
        elif audit and not audit.get('closed'):
            fresh = audit.get('scope_policy') == 'non-green-only' and not observed and all(tv.available(m) for m in s['modules'].values()) and audit['snapshot'] == {k:v['code_baseline'] for k,v in s['modules'].items()}
            if audit.get('mode') == 'problem':
                fresh = audit['snapshot'] == workflow.problem_snapshot(s, audit['module_ids'])
            global_next = {'operation': ('problem-audit' if audit.get('mode') == 'problem' else 'audit') if fresh else 'audit-revoke', 'role': 'auditor' if fresh else 'host',
                           'assignment_id': audit['assignment_id'], 'ready': False,
                           'reason': 'audit-running' if fresh else 'audit-snapshot-stale'}
        elif not s.get('global_plan'):
            splitting = any(m.get('decomposition_required') or m.get('decomposition_submission') for m in s['modules'].values())
            global_next = {'operation': None if splitting else 'global-plan', 'role': 'global-orchestrator',
                           'ready': bool(s['modules']) and not splitting,
                           'reason': 'module-decomposition-required' if splitting else 'coverage-review-required',
                           'continue_modules': rounds['ready_modules']}
        elif audit_closure.leftovers(s):
            blockers = rounds['blockers']
            global_next = {'operation': None if blockers else 'audit-collect', 'role': 'global-orchestrator', 'ready': not blockers,
                           'reason': 'await-all-module-rounds' if blockers else 'collect-all-leftovers',
                           'module_barrier': blockers, 'continue_modules': rounds['ready_modules'],
                           'wait_for_modules': rounds['active_modules']}
        elif pending_repairs(s):
            unassigned = [pid for pid, item in pending_repairs(s).items() if not item['module_ids']]
            global_next = {'operation': 'audit-route' if unassigned else None, 'role': 'global-orchestrator',
                           'ready': bool(unassigned), 'path_ids': unassigned,
                           'reason': 'repair-owner-required' if unassigned else 'await-module-repair-acceptance'}
        elif s['quality'] == 'green-passed' and not observed:
            global_next = {'operation': None, 'role': 'global-orchestrator', 'ready': False, 'reason': 'await-delivery-authorization'}
        elif tv.final_deferred_current(s) and not observed:
            global_next = {'operation': None, 'role': 'global-orchestrator', 'ready': False,
                           'reason': 'completed-with-unverified-tests', 'quality': 'yellow-blocked'}
        elif cursor and all(tv.available(m) for m in s['modules'].values()) and not observed:
            ready = rounds['all_settled'] and s.get('audit_attempts', 0) < s['max_audit_rounds']
            global_next = {'operation': 'audit-assign' if rounds['all_settled'] else None, 'role': 'global-orchestrator', 'ready': ready,
                           'reason': 'await-parent-summaries' if not rounds['all_settled'] else None if ready else 'audit-budget-exhausted',
                           'continue_modules': rounds['ready_modules'],
                           'scope_policy': 'non-green-only',
                           'path_ids': [p['path_id'] for p in audit_scope(s)['plan']['paths']]}
        else:
            global_next = {'operation': None, 'role': 'global-orchestrator', 'ready': False, 'reason': 'module-work-remaining'}
        global_next = context_readiness.annotate(s, None, global_next)
        return {**s, 'context_requirements': context_readiness.requirements(s),
                'parent_mo_names': decomposition.parent_mo_names(s),
                'migration_report': {'json': str(root / 'reports/migration-report.json'),
                                     'markdown': str(root / 'reports/migration-report.md'), 'sequence': len(events)},
                'last_sequence': len(events), 'observed_invalidations': observed,
                'next_steps': cursor, 'global_next_step': global_next, 'ready_modules': rounds['ready_modules'],
                'module_rounds': rounds,
                'planning_context': decomposition.planning_context(s),
                'module_inputs': {mid: decomposition.assigned_module(s, m) for mid, m in
                                  {**s.get('module_groups', {}), **s['modules']}.items()},
                'quality': 'yellow-blocked' if observed and s['quality'] != 'red-bug' else s['quality']}



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'apply', 'status', 'resume', 'recover'))
    parser.add_argument('--root', required=True)
    parser.add_argument('--request')
    parser.add_argument('--host-context', help='Host-protected principal JSON; CLI does not authenticate humans')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            result = status(args.root)
        else:
            require(args.request and args.host_context, 'request and host context required')
            req = read_json(args.request)
            if args.command != 'apply':
                require(req.get('operation') == args.command, 'command/operation mismatch')
            result = apply(args.root, req, read_json(args.host_context))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
