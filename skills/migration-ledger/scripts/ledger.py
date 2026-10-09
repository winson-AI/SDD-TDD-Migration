#!/usr/bin/env python3
"""Local transactional Ledger. Host must authenticate principals and enforce write isolation."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True

import workflow
import audit_closure
import audit_code_review
import decomposition
import dimensions
import model_routing
import reading
import status_view
import git_checkpoint
import prepared_tests
import context_handoff
import workflow_cost
import write_scope
import reuse
import knowledge_gate
import ui_fidelity
import project_context
import context_readiness
import design_stage
import test_validation as tv
import progress_signals
import source_changes
import run_changes
import control_policy
import task_revalidation
import user_paths
import audit_execution
import run_storage
from openspec_projection import materialize, attempt as project_attempt

from contracts import (Rejected, baseline, check_ref, digest, file_ref, keyed, nonempty,
                       intact, read_json, require, validate_plan, validate_result, verify_plan)

HISTORICAL_TOOL_ROOTS = (Path(__file__).resolve().parent,
                         Path(__file__).resolve().parents[2] / 'migration-protocol')


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, value):
    run_storage.atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def overlaps(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a.is_relative_to(b) or b.is_relative_to(a)


def refresh(s):
    for m in s['modules'].values():
        qualities = [p['quality'] for p in m['results'].values()] + [p['quality'] for p in m.get('repair_findings', {}).values()]
        m['quality'] = ('red-bug' if 'red-bug' in qualities else 'green-passed' if m['phase'] == 'completed'
                        and not m['stale'] and not user_paths.gaps(m.get('plan')) else 'yellow-blocked')
    decomposition.refresh_groups(s)
    mods = list(s['modules'].values())
    s['quality'] = ('red-bug' if any(m['quality'] == 'red-bug' for m in mods) or s.get('audit', {}).get('quality') == 'red-bug' else
                    'green-passed' if mods and all(m['quality'] == 'green-passed' for m in mods)
                    and all(decomposition.summary_current(s, group) for group in s.get('module_groups', {}).values())
                    and s.get('audit', {}).get('quality') == 'green-passed' else 'yellow-blocked')


PATCH_DEPTH = 4  # top-level key -> module id -> module field -> entry; an entry is recorded whole


def journal_diff(before, after, depth=PATCH_DEPTH):
    """What one event changed: nested values to set plus key paths to delete.

    The journal then grows with the change, not with the whole state of every module."""
    changed, removed = {}, []
    for key, value in after.items():
        if key not in before:
            changed[key] = value
        elif before[key] != value:
            if depth > 1 and isinstance(before[key], dict) and isinstance(value, dict):
                changed[key], gone = journal_diff(before[key], value, depth - 1)
                removed += [[key] + path for path in gone]
            else:
                changed[key] = value
    removed += [[key] for key in before if key not in after]
    return changed, removed


def _merge(target, change, depth):
    for key, value in change.items():
        if depth > 1 and isinstance(value, dict) and isinstance(target.get(key), dict):
            child = dict(target[key])  # copy on write: the old object may belong to an earlier event
            _merge(child, value, depth - 1)
            target[key] = child
        else:
            target[key] = value


def _remove(target, path):
    if len(path) == 1:
        target.pop(path[0], None)
    elif isinstance(target.get(path[0]), dict):
        child = dict(target[path[0]])
        _remove(child, path[1:])
        target[path[0]] = child


def apply_change(state, event):
    """Advance a replayed state by one event; returns the top-level keys it changed.

    Events written before patches existed carry the changed top-level keys whole in `effect`."""
    if 'patch' in event:
        patch = event['patch']
        _merge(state, patch['set'], PATCH_DEPTH)
        for path in patch['del']:
            _remove(state, path)
        return {*patch['set'], *(path[0] for path in patch['del'])}
    state.update(event['effect'])
    return set(event['effect'])


def replay(events):
    """Yield (event, state after it, changed top-level keys) for readers of history.

    The state dict is reused between events; nested objects it yielded earlier are never mutated."""
    state = {}
    for event in events:
        changed = apply_change(state, event)
        yield event, state, changed


def read_events(root):
    root = Path(root).resolve()
    path = run_storage.checked_path(root / 'ledger/events.jsonl', root)
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
            state = {}  # Replaying later events must not rewrite the first historical event.
        apply_change(state, e)
        events.append(e)
        prev = e['sha256']
    return state, events


def model_usage(s):
    """Actual host-reported model per dispatch, for after-the-fact task tracing."""
    rows = []
    scopes = {**{mid: m for mid, m in s['modules'].items()}, **s.get('module_groups', {})}
    for mid, m in scopes.items():
        for name, sess in m.get('sessions', {}).items():
            if sess.get('model'):
                rows.append({'scope': mid, 'kind': 'session', 'role': name, 'session_id': sess.get('session_id'),
                             'model': sess['model'], 'model_tier': sess.get('model_tier')})
        for aid, a in m.get('assignments', {}).items():
            if a.get('model'):
                rows.append({'scope': mid, 'kind': 'assignment', 'role': a.get('role'), 'assignment_id': aid,
                             'model': a['model'], 'model_tier': a.get('model_tier'), 'closed': a.get('closed', False)})
    audit = s.get('audit_assignment', {})
    if audit.get('model'):
        rows.append({'scope': 'GLOBAL', 'kind': 'audit', 'role': 'auditor', 'assignment_id': audit.get('assignment_id'),
                     'model': audit['model'], 'model_tier': audit.get('model_tier'), 'closed': audit.get('closed', False)})
    audit_test = s.get('audit_test_assignment', {})
    if audit_test.get('model'):
        rows.append({'scope': 'GLOBAL', 'kind': 'audit-test', 'role': 'test-runner', 'assignment_id': audit_test['assignment_id'],
            'model': audit_test['model'], 'model_tier': audit_test.get('model_tier'), 'closed': audit_test.get('closed', False)})
    return rows


def project(root, s, sequence):
    errors = []
    project_attempt(errors, 'global-state', lambda: atomic(root / 'ledger/global.json', {**s, 'last_sequence': sequence, 'parent_mo_names': decomposition.parent_mo_names(s)}))
    project_attempt(errors, 'model-usage', lambda: atomic(root / 'ledger/model-usage.json', {'sequence': sequence, 'usage': model_usage(s),
                                                                                          'hint_adoption': hint_adoption(s)}))
    for mid, m in s['modules'].items():
        project_attempt(errors, 'module-state', lambda: atomic(root / f'ledger/modules/{mid}.json', {**m, 'last_sequence': sequence}), mid)
    for mid, group in s.get('module_groups', {}).items():
        project_attempt(errors, 'parent-state', lambda: atomic(root / f'ledger/modules/{mid}.json', {**group, 'last_sequence': sequence}), mid)
    errors.extend(project_attempt(errors, 'openspec', lambda: materialize(root,
        {**s, 'projection_steps': {mid: next_step(s, m) for mid, m in s['modules'].items()}}, sequence)) or [])
    return {'sequence': sequence, 'status': 'pending' if errors else 'current', 'errors': errors}


def project_outcome(root, s, sequence):
    errors = []
    return project_attempt(errors, 'projection', lambda: project(root, s, sequence)) or {
        'sequence': sequence, 'status': 'pending', 'errors': errors}


def role(principal, *roles):
    require(principal.get('role') in roles and principal.get('instance_id'), 'principal role denied')


def current(m, observe_worker=False):
    verify_plan(m['plan'], m if m.get('freeze_id') else None)
    worker = next((a for a in m['assignments'].values() if not a.get('closed')), None)
    writing = bool(observe_worker and worker and not m.get('blocked') and
                   worker['role'] in ('implementer', 'fixer') and
                   m['phase'] == ('implementing' if worker['role'] == 'implementer' else 'fixing') and
                   worker['freeze_id'] == m['freeze_id'])
    mutable = (worker.get('execution_contract', {}).get('write_paths') or m['write_paths']) if writing else []
    if not m.get('execution_partition_pending'):
        dimensions.current(m, mutable)
    if m.get('code_files'):
        if writing:
            # Old accepted bytes remain in artifacts. Only the assigned working
            # copy may change; submit/accept must validate the new full manifest.
            for ref in m['code_files']:
                path = run_storage.checked_path(ref['path'])
                if not any(path.is_relative_to(Path(p).resolve()) for p in mutable):
                    check_ref(ref)
        else:
            require(baseline(m['code_files']) == m['code_baseline'], 'code evidence stale; invalidate before continuing')
    retained_write = writing and set(worker.get('execution_contract', {}).get('task_ids', [])) & set(m.get('task_revalidation', {}).get('retained_task_ids', []))
    if not retained_write:
        task_revalidation.current(m)


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


def checklist_rubric(root):
    """The package's freeze/DoD rubric as this run's content-addressed copy; a plan is bound to it, its author does not write it."""
    data = (reading.PACKAGE / 'template' / 'checklist.md').read_bytes()
    blob = run_storage.checked_path(root / 'artifacts' / hashlib.sha256(data).hexdigest(), root / 'artifacts')
    if not blob.exists():
        run_storage.atomic_bytes(blob, data)
    return file_ref(blob)


def reset_plan(m, reason='invalidated', evidence_ref=None):
    """Preserve failures/budgets and old evidence while returning to explicit planning."""
    history = {k: copy.deepcopy(m.get(k)) for k in
        ('revision', 'plan', 'plan_ref', 'plan_hash', 'freeze_id', 'code_files', 'code_baseline',
         'results', 'repair_findings', 'blocked', 'dimension_evidence', 'provider_owners', 'change_request', 'accepted_test_design', 'design_input_ref', 'execution_context_ref')}
    history.update(kind='planning-history', executable=False, reason=reason, evidence_ref=evidence_ref)
    m.setdefault('planning_history', []).append(history)
    m['design_generation'] = m.get('design_generation', 0) + 1
    m.pop('accepted_test_design', None)
    m.pop('design_input_ref', None)
    m.update(stale=True, phase='specifying', blocked=None, freeze_id=None, diagnosis_submission=None,
             plan=None, plan_ref=None, plan_hash=None, build_baseline=None, accepted_task_ids=[],
             code_files=[], code_baseline=None, provider_owners=[])
    for key in ('dimension_evidence', 'effective_quality', 'context_acceptances', 'automation_retry_ready',
                'dependency_release', 'source_context_continuation', 'allocation_continuation', 'change_request', 'scenario_index', 'plan_binding',
                'checklist_ref', 'execution_context_ref', 'plan_review_ref', 'task_files', 'execution_partition_pending', 'planning_continuation', 'task_revalidation'):
        m.pop(key, None)


def open_change(s, m, request):
    """Reopen a frozen leaf's contract and keep what was built on it: the plan is revised and frozen again, and the code
    already written is updated under the next freeze. A request that is already open keeps the plan it started from."""
    current_request = m.get('change_request') or {}
    m['design_generation'] = m.get('design_generation', 0) + 1
    previous_plan = current_request.get('previous_plan') or {
        key: copy.deepcopy(m.get(key)) for key in ('plan_ref', 'plan_hash', 'plan', 'accepted_test_design')}
    previous_revalidation = current_request.get('previous_revalidation') if current_request else m.pop('task_revalidation', None)
    # Existing coded work is updated under the next freeze. Design assistance is opt-in again.
    m.setdefault('approved_test_paths', copy.deepcopy(control_policy.acceptance(m['plan']['paths'])))
    m.pop('accepted_test_design', None)
    m.pop('test_design_required', None)
    m.update(phase='change-review', stale=True, change_request={**request, 'from_freeze_id': m['freeze_id'],
        'previous_plan': previous_plan, 'previous_revalidation': previous_revalidation}, diagnosis_submission=None)
    invalidate_dependents(s, m['module_id'])


def replan_module(m, reason, evidence_ref, release_blocker=False):
    """Keep failure/budget history and unrelated blockers when replacing an execution baseline."""
    blocker, phase = copy.deepcopy(m.get('blocked')), m['phase']
    reset_plan(m, reason, evidence_ref)
    m.pop('approved_envelope', None)
    m.pop('approved_acceptance', None)
    m.pop('allocation_continuation', None)
    if blocker and not release_blocker:
        m['blocked'] = {**blocker, 'resume_phase': 'specifying'}
        m['phase'] = phase


def dependencies_ready(s, m):
    providers = ((m.get('behavior_review') or {}).get('verification') or {}).get('provider_inputs', [])
    stages = {row['module_id']: row['required_stage'] for row in providers}
    require(all((bool(s['modules'][d].get('code_baseline')) and set(s['modules'][d].get('accepted_task_ids', [])) ==
                {t['task_id'] for t in (s['modules'][d].get('plan') or {}).get('tasks', [])})
                if stages.get(d) == 'implemented' and m.get('phase') not in ('testing', 'dod', 'completed')
                else tv.available(s['modules'][d]) for d in m['dependencies']), 'dependencies not complete')
    for d in m['dependencies']:
        current(s['modules'][d])


def failure_fingerprint(results):
    """Structured facts only: a reworded summary must not make a repeated failure look like progress."""
    rows = []
    for pid, r in results.items():
        if r['quality'] == 'green-passed':
            continue
        cause = r.get('root_cause') or {}
        failed = sorted([a.get('assertion_id'), json.dumps(a.get('actual'), sort_keys=True)]
                        for a in r.get('assertions', []) if a.get('passed') is False)
        rows.append([pid, r['quality'], cause.get('category'), cause.get('reason_code'), failed])
    return digest(sorted(rows))


def worker_phase(m, assignment):
    expected = {'implementer': 'implementing', 'fixer': 'fixing', 'test-runner': 'testing'}
    require(not m.get('blocked') and m['phase'] == expected[assignment['role']], 'worker result is not valid in current phase')


def approval(s, m, subject):
    return next((d for d in s['decisions'].values() if d.get('module_id') == m['module_id']
                 and d.get('subject_sha256') == subject and not d.get('consumed')), None)


def self_diagnosis(s, m):
    """A lightweight leaf's local round is diagnosed by the repairing session; audit rounds stay independent."""
    return (bool(m.get('lean_leaf')) or bool(s.get('fixer_self_diagnosis'))) and not audit_closure.active(s) \
        and not m.get('audit_fix_grant')


def batch_approval(s, m):
    """An unrevoked parent batch-envelope decision whose entry for this child equals its plan envelope."""
    for did, d in s['decisions'].items():
        if d.get('kind') == 'batch-envelope' and d.get('module_id') == m.get('parent_module_id') and m.get('plan'):
            if read_json(check_ref(d['envelope_ref']))['children'].get(m['module_id']) == m['plan']['decision_envelope']:
                return did
    return None


def within_envelope(m, impact_ref):
    require(m.get('approved_envelope') == digest(m['plan']['decision_envelope']), 'decision envelope changed')
    require(m.get('approved_acceptance') == control_policy.acceptance_hash(m), 'acceptance/path set changed')
    require(impact_ref, 'independent impact review required')
    change = m.get('change_request') or {}
    require(change.get('impact_ref') == impact_ref and change.get('from_freeze_id') == m.get('freeze_id'),
            'impact review must belong to the current change and prior freeze')
    impact = read_json(check_ref(impact_ref))
    require(isinstance(impact, dict), 'impact review must be a structured object')
    require(impact.get('from_freeze_id') == m.get('freeze_id') and impact.get('to_plan_hash') == m['plan_hash'],
            'impact review must bind from_freeze_id and to_plan_hash')


def allocation_frozen(m):
    """A leaf frozen before on the analysis it still holds: what concerns that allocation alone was judged then."""
    ref = m.get('dimension_analysis_ref')
    return bool(ref) and any(row.get('freeze_id') and (row.get('plan') or {}).get('dimension_analysis_ref') == ref
                             for row in [m, *m.get('planning_history', [])])


def freeze_guard(s, m, p):
    """Pure shared guard: routing and mutation must recommend/accept the same freeze.

    The plan was judged when it was submitted; here it must be intact and stand on the current allocation and
    context, and the freeze gates judge what only a freeze can."""
    idle(m)
    require(m.get('plan'), 'SPEC not prepared')
    design_stage.plan_check(s, m, m['plan'], judge=False)
    if m.get('scope'):
        decomposition.check_module_plan(s, m, m['plan'])
    require(m['phase'] == 'clarifying' and not m.get('blocked'), 'freeze requires unblocked clarifying')
    verify_plan(m['plan'], m)
    intact(lambda: validate_plan(m['plan'], m))
    require(digest(m['plan']) == m['plan_hash'], 'plan changed')
    if m.get('change_request') and task_revalidation.prepare(m, p.get('review_ref'))['mode'] == 'partial':
        require(p['review_ref'] == m.get('plan_review_ref'), 'TASK independence requires accepted MO plan review')
    first = not allocation_frozen(m)
    import resource_fidelity
    resource_fidelity.freeze_gate(s, m, first)
    import api_contract
    api_contract.freeze(s, m, p)
    ui_fidelity.freeze_gate(s, m, first)
    knowledge_gate.freeze_gate(s, m)
    if not p.get('decision_id') and p.get('review_ref'):
        control_policy.technical_review(m, p['review_ref'])
        task_revalidation.prepare(m, p['review_ref'])
    elif p.get('change_class') == 'within-envelope':
        within_envelope(m, p.get('impact_ref'))
    else:
        decision = s['decisions'].get(p.get('decision_id'), {})
        if decision.get('kind') == 'batch-envelope':
            require(decision.get('module_id') == m.get('parent_module_id') and
                    read_json(check_ref(decision['envelope_ref']))['children'].get(m['module_id']) == m['plan']['decision_envelope'],
                    'child plan envelope differs from the approved batch envelope')
            return
        require(decision.get('subject_sha256') == m['plan_hash'] and decision.get('module_id') == m['module_id'] and
                not decision.get('consumed'), 'approval missing/stale/wrong module')


def unresolved(m):
    if m['stale']:
        return {}
    results = dict(m['results'])
    results.update(m.get('repair_findings', {}))
    return {k: v for k, v in results.items() if v['quality'] != 'green-passed'}


def diagnosis_focus(m, p):
    """A visual-only round names one or two actionable issues; more only dilutes a bounded repair."""
    bad = unresolved(m)
    kinds = {path['path_id']: path.get('kind') for path in (m.get('plan') or {}).get('paths', [])}
    if not bad or any(kinds.get(pid) != 'visual' for pid in bad):
        return
    issues = p.get('visual_issues')
    require(isinstance(issues, list) and 1 <= len(issues) <= 2, 'visual diagnosis needs one or two visual_issues')
    for item in issues:
        require(isinstance(item, dict) and all(item.get(k) for k in ('area', 'problem', 'evidence_ref'))
                and item.get('severity') in ('low', 'medium', 'high', 'critical'),
                'each visual issue needs area, problem, severity and evidence_ref')


def diagnosis_subject(m):
    return digest({'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'issues': unresolved(m)})


def idle(m):
    require(not any(not a.get('closed') for a in m['assignments'].values()), 'worker still active')


def complete_guard(s, m):
    require(m['phase'] == 'dod' and not m['stale'] and m['results'] and
            all(r['quality'] == 'green-passed' for r in m['results'].values()) and
            set(m['results']) == {p['path_id'] for p in m['plan']['paths']}, 'DoD requires all paths Green')
    current(m); dependencies_ready(s, m)
    require((set(m.get('accepted_task_ids', [])) == {t['task_id'] for t in m['plan']['tasks']}), 'DoD requires cumulative TASK completion')
    if s.get('git_checkpoint'):
        require((m.get('git_checkpoint') or {}).get('code_baseline') == m['code_baseline'],
                'git checkpoint of the current code baseline required before completion')


def pending_repairs(s):
    return {pid: item for pid, item in s.get('audit_repairs', {}).items()
            if not item.get('module_ids') or set(item['module_ids']) != set(item.get('accepted_by', []))}


def dispatch_guard(s, m, worker):
    require(m.get('plan') and m.get('freeze_id'), 'SPEC not frozen/prepared')
    workflow.planning_guard(s, m['module_id'])
    if m.get('scope'):
        decomposition.check_module_plan(s, m, m['plan'])
    if audit_closure.active(s):
        b = s['audit_batch']
        require(b['status'] == 'repairing' and m.get('audit_batch_id') == b['batch_id'], 'audit closure owns dispatch; human review may be required')
        require(worker in ('fixer', 'test-runner'), 'audit closure only fixes and verifies')
        require(m['module_id'] in audit_closure.pending_modules(b) and audit_closure.dependencies_done(s, b, m['module_id']),
                'audit finding blocked or upstream verification incomplete')
    require(not workflow.audit_locks(s, m['module_id']), 'audit snapshot locked; close audit before dispatch')
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
        require(not (unresolved(m) and workflow.defer_reason(m, m.get('fix_budget', s['max_fix_rounds']))) or m.get('automation_retry_ready'), 'unresolved failure awaits Auditor')
        require(m['code_baseline'], 'code must be accepted before testing')
        require((set(m.get('accepted_task_ids', [])) == {t['task_id'] for t in m['plan']['tasks']}), 'all TASKs must be implemented before target tests')
    if worker == 'fixer':
        require(control_policy.repair_route(m.get('diagnosis') or {}) == 'fixer', 'SPEC/scope repair must route through CR/upstream before Fixer')
        require(not workflow.defer_reason(m, m.get('fix_budget', s['max_fix_rounds'])), 'local repair deferred to Auditor')
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
    if workflow.audit_locks(s, m['module_id']):
        return {'module_id': m['module_id'], 'phase': m['phase'], 'expected_revision': m['revision'],
                'operation': None, 'role': 'host', 'ready': False, 'reason': 'await-auditor',
                'assignment_id': None, 'session_id': None}
    batch_step = audit_closure.module_step(s, m)
    if batch_step is not None:
        return batch_step
    active = next((a for a in m['assignments'].values() if not a.get('closed')), None)
    step = {'module_id': m['module_id'], 'phase': m['phase'], 'expected_revision': m['revision'],
            'operation': None, 'role': None, 'ready': False, 'reason': None,
            'session_id': None, 'assignment_id': active['assignment_id'] if active else None}
    if m.get('effective_quality') == 'yellow-blocked':
        step.update(operation='revoke' if active else 'invalidate', role='host' if active else 'module-orchestrator', ready=True, reason='evidence-stale',
                    payload={'reason': 'evidence-stale'} if not active else {})
    elif m['phase'] == 'automation-deferred':
        step.update(role='module-orchestrator', reason='automation-not-run; other work may continue')
        for receipt in (m.get('context_receipts', {}).values() if tv.resume_budget_left(s, m) else ()):
            try:
                context_readiness.validate(s, m['module_id'], 'testing', receipt['report_ref'])
                step.update(operation='automation-resume', ready=True, payload={'context_ref': receipt['report_ref']})
                break
            except (Rejected, OSError, ValueError):
                pass
    elif m['phase'] == 'waiting-auditor':
        step.update(operation=None, role='module-orchestrator', ready=False, reason='await-host-audit')
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
                        reason=None if decision else 'human-decision-required', approval_subject_sha256=digest(m['blocked']))
    elif active:
        submitted = active['assignment_id'] in m['submissions']
        step.update(operation='accept' if submitted else 'await-result',
                    role='module-orchestrator' if submitted else active['role'], ready=submitted,
                    reason=None if submitted else 'worker-running')
        if submitted and m['submissions'][active['assignment_id']].get('green'):
            # Nothing to judge: accept re-validates the result, so the host may submit it without a model turn.
            step['mechanical'] = True
        if design_stage.is_design(active):
            step.update(mode='design', test_scope='design')
            if not design_stage.valid(s, m, active):
                step.update(operation='revoke', role='host', ready=True, reason='design-input-stale',
                            recovery_action='stop-design-worker-and-revoke-before-redesign')
    elif m.get('decomposition_submission'):
        step.update(operation='decompose-accept', role='global-orchestrator', ready=True)
    elif m.get('decomposition_required') and m['phase'] in ('context', 'specifying', 'clarifying'):
        step.update(operation='decompose', role='module-orchestrator', ready=True,
                    planning_outcomes=['split', 'atomic-leaf'])
    elif m['phase'] in ('completed', 'testing') and any(m['module_id'] in r.get('module_ids', []) and m['module_id'] not in r.get('accepted_by', [])
             for r in pending_repairs(s).values()):
        step.update(operation='repair-accept', role='module-orchestrator', ready=True,
                    path_ids=[pid for pid, r in pending_repairs(s).items() if m['module_id'] in r.get('module_ids', [])
                              and m['module_id'] not in r.get('accepted_by', [])])
    elif m['phase'] == 'waiting-upstream':
        step.update(operation=None, role='module-orchestrator', ready=False,
                    reason='await-upstream-reallocation',
                    detail='Submodule requested reallocation from parent MO',
                    recovery_action='realloc-request-or-redecompose-parent')
    elif m['phase'] in ('context', 'specifying', 'change-review'):
        step.update(operation='plan', role='spec-designer', ready=True,
                    input_subject_sha256=design_stage.subject(s, m),
                    upstream_case_refs=design_stage.upstream_refs(s), upstream_case_ids=m['case_ids'])
        if design_stage.required(s, m) and not design_stage.ready(s, m):
            step.update(operation='assign', role='module-orchestrator', worker_role='test-runner',
                        mode='design', test_scope='design', reason='independent-test-design-required',
                        payload={'role': 'test-runner', 'mode': 'design'},
                        # What the design input cites instead of copying the context and the allocation.
                        input_subject_sha256=design_stage.subject(s, m))
            if s.get('behavior_contract_required'):
                step['design_input_needs'] = ('spec_refs: the leaf SPEC draft the Spec-Designer staged, with Requirement-ID and '
                                              'Scenario-ID lines; have it staged before assigning the design')
        try:
            workflow.runtime_allocations(s, m['module_id'])
        except (Rejected, OSError) as exc:
            step.update(operation=None, role='global-orchestrator', ready=False,
                        reason='allocation-review-required', detail=str(exc),
                        recovery_action='realloc-request-or-redecompose-parent')
    elif m['phase'] == 'clarifying':
        decision = approval(s, m, m['plan_hash'])
        if not decision and batch_approval(s, m):
            decision = {'decision_id': batch_approval(s, m)}
        impact = m.get('change_request', {}).get('impact_ref')
        eligible = False
        if not decision:
            try:
                within_envelope(m, impact)
                eligible = True
            except (ValueError, OSError, TypeError):
                pass
        step.update(operation='freeze', role='module-orchestrator', ready=bool(decision) or eligible or bool(m.get('plan_review_ref')),
                    payload={'decision_id': decision['decision_id']} if decision else
                            {'change_class': 'within-envelope', 'impact_ref': impact} if eligible else
                            {'review_ref': m['plan_review_ref']} if m.get('plan_review_ref') else {},
                    reason=None if decision or eligible else 'MO-plan-review-required',
                    # What a human approval or an impact review binds: the hash of the plan as the Ledger completed it.
                    approval_subject_sha256=m['plan_hash'])
        if not decision and not eligible and not m.get('plan_review_ref'):
            step.update(operation='plan-review', ready=True, reason='MO-technical-review', payload={})
        if design_stage.required(s, m) and not design_stage.ready(s, m):
            step.update(operation='invalidate', ready=True, reason='independent-test-design-stale',
                        payload={'reason': 'independent-test-design-stale'})
    elif m['phase'] in ('frozen', 'testing', 'diagnosing'):
        bad = unresolved(m)
        if m['phase'] == 'testing' and bad and not m.get('automation_retry_ready'):
            draft = m.get('diagnosis_submission')
            categories = {r.get('root_cause', {}).get('category') for r in bad.values()}
            conflict = workflow.variant_conflict(m)
            if conflict:
                step.update(operation='suspend', role='module-orchestrator', ready=True, reason=conflict['reason_code'],
                            payload={'kind': 'human', 'reason': conflict['summary'], 'reason_code': conflict['reason_code'],
                                     'root_cause': conflict, 'owner': 'human'})
            elif draft and draft['subject'] == diagnosis_subject(m):
                routed = control_policy.repair_step(draft['report'])
                step.update(routed or dict(operation='diagnosis-accept', role='module-orchestrator', ready=True,
                            # Optional: once the Fixer preflighted this diagnosis, accept and dispatch in one step.
                            then_assign={'role': 'fixer', 'session_id': suggested_session(s, m, 'fixer')[0]}))
            elif workflow.defer_reason(m, m.get('fix_budget', s['max_fix_rounds'])):
                step.update(operation='audit-defer', role='module-orchestrator', ready=True,
                            root_cause=workflow.defer_reason(m, m.get('fix_budget', s['max_fix_rounds'])), reason='auditor-handoff')
            else:
                step.update(operation='diagnose', role='fixer' if self_diagnosis(s, m) else 'diagnostician', ready=True)
        else:
            routed = control_policy.repair_step(m['diagnosis']) if m['phase'] == 'diagnosing' else None
            if routed:
                step.update(routed)
                return step
            worker = {'frozen': 'implementer', 'testing': 'test-runner', 'diagnosing': 'fixer'}[m['phase']]
            if worker == 'fixer' and workflow.defer_reason(m, m.get('fix_budget', s['max_fix_rounds'])):
                step.update(operation='audit-defer', role='module-orchestrator', ready=True,
                            root_cause=workflow.defer_reason(m, m.get('fix_budget', s['max_fix_rounds'])), reason='auditor-handoff')
                return step
            exhausted = m['no_progress_rounds'] >= s['max_no_progress_rounds'] or (worker == 'fixer' and
                         m['fix_rounds_used'] >= m.get('fix_budget', s['max_fix_rounds']))
            step.update(operation='recover' if exhausted else 'assign', role='module-orchestrator',
                        worker_role=worker, ready=not exhausted, reason='budget-exhausted' if exhausted else None)
            if worker == 'test-runner' and tv.split(m):
                step['test_scope'] = tv.next_scope(m)
                step['payload'] = {'test_scope': step['test_scope']}
            if step['ready']:
                try:
                    dispatch_guard(s, m, worker)
                except (Rejected, OSError) as exc:
                    step.update(ready=False, reason=str(exc))
    elif m['phase'] == 'dod' and s.get('git_checkpoint') and \
            (m.get('git_checkpoint') or {}).get('code_baseline') != m['code_baseline']:
        step.update(operation='checkpoint', role='host', ready=True, reason='commit-module-paths-on-run-branch',
                    branch=git_checkpoint.branch(s['run_id']))
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
                freeze_guard(s, m, step.get('payload', {}))
            elif step['operation'] == 'repair-accept':
                idle(m); current(m); dependencies_ready(s, m)
        except (ValueError, OSError) as exc:
            step.update(ready=False, reason=str(exc))
            if step['operation'] == 'freeze':
                step['recovery_action'] = 'Spec-Designer revise the current plan/evidence, then MO review and freeze again'
    session_id, affinity = suggested_session(s, m, step.get('worker_role') or step['role'])
    step['session_id'] = session_id
    if affinity:
        step['session_affinity'] = affinity
    return step


def all_green_tests(result):
    return (result.get('kind') == 'tests' and bool(result.get('paths'))
            and all(row.get('quality') == 'green-passed' for row in result['paths']))


def suggested_session(s, m, role):
    """Resume the role's own session; a local repair without one resumes the code author's context."""
    own = m['sessions'].get(role, {}).get('session_id')
    if (role == 'fixer' and not own and not audit_closure.active(s)
            and not m.get('audit_fix_grant') and m['sessions'].get('implementer', {}).get('session_id')):
        return m['sessions']['implementer']['session_id'], 'implementer'
    return own, None


def deliver(m, rows, session_id):
    """Remember what a session now holds and what handing it this card cost; advisory, never a gate."""
    held = m.setdefault('delivered_cards', {}).setdefault(session_id, {})
    load = m.setdefault('card_load', {'dispatches': 0, 'full': 0, 'delivered': 0})
    load['dispatches'] += 1
    load['full'] += sum(row['bytes'] for row in rows)
    new = sum(row['bytes'] for row in reading.fresh(rows, held))
    load['delivered'] += new
    sessions = m.setdefault('session_load', {})
    sessions[session_id] = sessions.get(session_id, 0) + new
    for section, digest in reading.delivered(rows).items():
        seen = held.get(section) or []
        seen = [seen] if isinstance(seen, str) else seen
        held[section] = seen if digest in seen else [*seen, digest]


READ_BY_ITS_ACTOR = ('plan', 'plan-review', 'freeze', 'change', 'planning-reopen', 'decompose', 'redecompose', 'realloc-request',
                     'diagnosis-accept', 'complete', 'suspend', 'resume', 'recover', 'invalidate')


def record_actor(s, m, principal, op):
    """Without a host report the acting instance is the evidence: it performed the step, so it holds the step's card.
    Steps a host may submit without a model turn are left out, since nobody read a card for them. Advisory."""
    if op in READ_BY_ITS_ACTOR:
        rows = reading.card(s, m, {'role': principal['role'], 'operation': op})
        if rows:
            deliver(m, rows, principal['instance_id'])
            m.setdefault('actors', {})[principal['role']] = principal['instance_id']


def record_hint(s, m, hint):
    """A request may report the session and card the host acted on; counted when it matches the cursor step."""
    try:
        step = next_step(s, m)
    except (Rejected, OSError, ValueError, KeyError):
        return
    if step.get('operation') and step.get('card_sha256') == hint['card_sha256']:
        deliver(m, step['must_read'], hint['session_id'])


def worker_step(p):
    """The cursor step a host acts on when it dispatches a worker: the assign the module orchestrator performs."""
    return {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': p['role'],
            'mode': p.get('mode'), 'test_scope': 'design' if design_stage.is_design(p) else p.get('test_scope'),
            'assignment_id': p.get('assignment_id'), 'payload': {key: p[key] for key in ('task_ids', 'path_ids') if key in p}}


def record_inputs(s, hint):
    """Host-reported deliveries, measured from hash-bound files; this grants no read permission."""
    rows = hint.get('context_inputs', [])
    require(isinstance(rows, list) and len(rows) <= 128, 'context_inputs must be a bounded list')
    validated = []
    for row in rows:
        require(row.get('kind') in ('spec', 'source', 'log', 'history', 'tool', 'fixture'), 'unknown context input kind')
        path = check_ref(row.get('ref'))
        validated.append((row['ref']['sha256'], {**row, 'bytes': path.stat().st_size}))
    if validated:
        held = s.setdefault('context_load', {}).setdefault(hint['session_id'], {})
        held.update(dict(validated))
        delivery = s.setdefault('context_deliveries', {}).setdefault(hint['session_id'], {'bytes': 0, 'count': 0})
        delivery['bytes'] += sum(row['bytes'] for _, row in validated)
        delivery['count'] += len(validated)


def context_load(s, session):
    protocol = sum(obj.get('session_load', {}).get(session, 0)
                   for obj in [s, *s['modules'].values(), *s.get('module_groups', {}).values()])
    inputs = s.get('context_load', {}).get(session, {})
    size = sum(r['bytes'] for r in inputs.values())
    delivery = s.get('context_deliveries', {}).get(session, {})
    return {'protocol_bytes': protocol, 'input_bytes': size, 'input_count': len(inputs), 'reported_bytes': protocol + size,
            'input_delivered_bytes': delivery.get('bytes', 0), 'input_delivery_count': delivery.get('count', 0)}


def hint_record(s, m, p):
    """Advisory hints stay advisory; the host's report of what it actually used is kept for audit."""
    suggested, _ = suggested_session(s, m, p['role'])
    card = reading.digest_card(reading.card(s, m, worker_step(p)))
    used, delivered = p.get('session_id'), p.get('card_sha256')
    return {'session_suggested': suggested, 'session_used': used,
            'session_followed': None if used is None or suggested is None else used == suggested,
            'card_expected': card, 'card_delivered': delivered,
            'card_followed': None if delivered is None else delivered == card}


def hint_adoption(s):
    rows = [{'scope': mid, 'assignment_id': aid, 'role': a.get('role'), **a['hints']}
            for mid, m in s['modules'].items() for aid, a in m.get('assignments', {}).items() if a.get('hints')]
    def tally(key):
        values = [r[key] for r in rows]
        return {'followed': values.count(True), 'not_followed': values.count(False), 'unreported': values.count(None)}
    return {'session': tally('session_followed'), 'card': tally('card_followed'), 'rows': rows}


def reasoning_escalated(m):
    """Ambiguous/unconfirmed failures need strong reasoning even on otherwise weak steps."""
    if m.get('no_progress_rounds', 0) > 0 or m.get('repair_findings'):
        return True
    results = {**m.get('results', {}), **m.get('repair_findings', {})}
    return any(r.get('quality') != 'green-passed' and r.get('root_cause', {}).get('confidence') != 'confirmed'
               for r in results.values())


# Where slicing is decided or revised: the steps at which an orchestrator loads the project's slicing skill.
SLICING_STEPS = {('global-orchestrator', op) for op in ('register', 'global-plan', 'decompose-accept', 'redecompose-accept',
                                                         'run-review', 'source-review')} | {
                 ('module-orchestrator', op) for op in ('decompose', 'redecompose', 'realloc-request')}


def with_card(s, m, step):
    """A step that asks for an operation names the protocol sections and the templates it needs."""
    # A step the host submits without a model turn is read by nobody; a dispatch still carries its worker's card.
    waiting = not step.get('ready') and step.get('reason') == 'dependency-incomplete'  # nothing to do until the provider is done
    step['must_read'] = [] if waiting or step.get('mechanical') and not step.get('worker_role') else reading.card(s, m, step)
    step['card_sha256'] = reading.digest_card(step['must_read'])
    step['templates'] = reading.templates(s, m, step)
    enhancement = reading.reasoning_sections(m)
    if enhancement: step['reasoning_activation'] = [{'ref': ref, 'section': heading} for ref, heading in enhancement]
    if s.get('project_context_ref') and (m or (step.get('role') == 'global-orchestrator' and step.get('operation') in
            ('register', 'global-plan', 'source-review', 'run-review', 'revise-run'))):
        import experience
        snapshot = project_context.verify_snapshot(s['project_context_ref'])
        if (step.get('role'), step.get('operation')) == ('spec-designer', 'plan') and m and m.get('dimension_analysis_ref') and not m.get('plan'):
            step['spec_skeleton'] = 'spec_skeleton.py --root <run_root> --module ' + m['module_id'] + ' --out <staging directory>'
        skill = snapshot.get('source_refs', {}).get('slicing_skill_ref')
        if skill and (step.get('role'), step.get('operation')) in SLICING_STEPS:
            step['slicing_skill'] = {'name': experience.SKILL, 'ref': copy.deepcopy(skill)}
        ref = snapshot.get('source_refs', {}).get('experience_ref')
        if ref:
            candidates = experience.candidates(read_json(check_ref(ref)), m if m is not None else experience.global_scope(s), (step.get('payload') or {}).get('task_ids', []))
            if candidates: step['lesson_candidates'] = candidates
    session = step.get('session_id') or (s.get('context_sessions', {}).get(step['role']) if m is None else None)
    if session:
        step['session_id'] = session
        load = context_load(s, session)
        step['context_load'] = load
        if load['reported_bytes'] >= reading.ROTATE_BUDGET:
            step['session_rotate'] = {'reason': 'context-load' if load['input_bytes'] else 'reading-load',
                'delivered_bytes': load['reported_bytes'], 'threshold': reading.ROTATE_BUDGET,
                'run_id': s['run_id'], 'next_action': 'resume-independent-session-from-checkpoint',
                'checkpoint': context_handoff.checkpoint(s, m, step.get('worker_role', step['role']), session),
                'resume_refs': context_handoff.checkpoint(s, m, step.get('worker_role', step['role']), session)['resume_refs'],
                'host_receipt_required': s.get('host_handoff_required', False),
                'read_hint': {'ref': reading.P + 'host-integration.md', 'section': '会话交接'}}
    return step


def next_step(s, m):
    step = context_readiness.annotate(s, m['module_id'], _next_step(s, m))
    if m.get('decomposition_required') and step['role'] == 'module-orchestrator':
        step['agent_name'] = 'parent-mo-' + m['module_id']
    if step.get('operation') == 'assign' and step.get('mode') != 'design' and step['ready']:
        # Who works next and on which stage are facts the Ledger holds; assign re-checks every guard and the worker
        # reports its own readiness, so the host may submit it as the module orchestrator without a model turn.
        step['mechanical'] = True
        step['payload'] = {**step.get('payload', {}), 'role': step['worker_role']}
        selected = [t for t in m['plan']['tasks'] if step['worker_role'] != 'implementer' or t['task_id'] not in m.get('accepted_task_ids', [])]
        if step['worker_role'] == 'fixer' and m.get('task_revalidation', {}).get('mode') == 'partial' and not m.get('repair_findings'):
            affected_paths = set(unresolved(m))
            selected = [t for t in selected if affected_paths.intersection(t['path_ids'])]
        scope = step.get('test_scope')
        paths = [p for p in m['plan']['paths'] if not scope or (p.get('kind') in tv.PRE if scope == 'build' else p.get('kind', 'automation') == scope)]
        if step['worker_role'] == 'implementer' or step['worker_role'] == 'fixer' and m.get('task_revalidation', {}).get('mode') == 'partial':
            wanted = {pid for t in selected for pid in t['path_ids']}
            paths = [p for p in paths if p['path_id'] in wanted]
        elif step['worker_role'] == 'test-runner' and scope != 'build' and m.get('task_revalidation', {}).get('mode') == 'partial':
            paths = [p for p in paths if not tv.path_green(m, p['path_id'])]
        step['payload'].update(task_ids=[t['task_id'] for t in selected], path_ids=[p['path_id'] for p in paths])
        if step['worker_role'] == 'fixer':
            step['payload']['finding_ids'] = list(unresolved(m)) + [r['finding_id'] for r in (m.get('diagnosis') or {}).get('findings', [])]
        receipts = (step.get('context_gate') or {}).get('ready_receipts')
        if receipts:
            producer = next(r['producer'] for r in m['context_receipts'].values() if r['report_ref'] == receipts[0])
            step['payload'].update(instance_id=producer['instance_id'], context_ref=receipts[0])
    if step.get('role'):
        step['model_tier'] = model_routing.advise(step['role'], step.get('operation'),
                                                   step.get('worker_role'), escalate=reasoning_escalated(m))
    step['human_required'] = control_policy.human_required(step)  # said on every step, so a host asks nobody otherwise
    if step.get('operation'):
        with_card(s, m, step)
        # Without a session the host reported, the instance that last acted in this role is who may still hold cards.
        session = step.get('session_id') or (m.get('actors') or {}).get(step.get('worker_role') or step.get('role')) or ''
        held = m.get('delivered_cards', {}).get(session)
        if held:
            step['must_read_new'] = reading.fresh(step['must_read'], held)
            if not step.get('session_id'):
                step['card_new_for'] = session
    return step


def new_module(p):
    require(re.fullmatch(r'M[0-9]{3,}', p.get('module_id', '')), 'invalid module id')
    nonempty(p.get('case_ids'), 'module cases')
    nonempty(p.get('write_paths'), 'write paths')
    require(all(Path(x).is_absolute() for x in p['write_paths']), 'absolute write paths required')
    return {**p, 'revision': 0, 'phase': 'context', 'quality': 'yellow-blocked', 'stale': True,
            'plan': None, 'freeze_id': None, 'code_files': [], 'code_baseline': None, 'build_artifacts': [],
            'results': {}, 'submissions': {}, 'assignments': {}, 'sessions': {},
            'fix_rounds_used': 0, 'total_fix_rounds': 0, 'recovery_cycle': 0,
            'no_progress_rounds': 0, 'blocked': None, 'authors': [], 'local_fix_used': 0, 'fix_memory': [],
            'dependencies': p.get('dependencies', [])}


def audit_scope(s):
    """Select unresolved paths, never expand an audit into a full project replay.

    Optional GLOBAL-only cases not yet executed (or invalidated by code changes)
    are unverified, rather than implicitly Green. Module Green evidence is reused.
    """
    path_test_sources = {}
    refs = [ref for m in s['modules'].values() for ref in m['code_files']]
    code_baseline = baseline(refs)
    results = dict(s.get('audit_results', {}))
    selected, frozen_interactions, path_build_artifacts, path_dimension_analysis_refs = [], {}, {}, {}
    for path in s.get('global_paths', []):
        previous = results.get(path['path_id'])
        if not previous or previous.get('stale') or previous['quality'] != 'green-passed' or previous.get('code_baseline') != code_baseline:
            selected.append(path)
            if path.get('test_design_ref'):
                path_test_sources[path['path_id']] = {'module_id': 'GLOBAL', 'freeze_id': digest(path),
                    'test_design_ref': path['test_design_ref'], 'contract_version': 1}
            # A GLOBAL visual path explicitly names its frozen integration build owner/path.
            binding = path.get('build_binding') or {}
            owner = s['modules'].get(binding.get('module_id'), {})
            build = owner.get('results', {}).get(binding.get('path_id'), {})
            if (any(p.get('path_id') == binding.get('path_id') and p.get('kind') == 'build'
                    for p in (owner.get('plan') or {}).get('paths', []))
                    and build.get('quality') == 'green-passed' and build.get('code_baseline') == owner.get('code_baseline')
                    and not owner.get('stale')):
                path_build_artifacts[path['path_id']] = [r for r in build.get('build_artifacts', []) if r in owner.get('build_artifacts', [])]
            if path.get('kind') in ('automation', 'visual') and path.get('interaction_id'):
                from ui_evidence import interaction_contract
                item = interaction_contract(path.get('frozen_interaction'))
                require(item['id'] == path['interaction_id'], 'GLOBAL frozen interaction ID mismatch')
                frozen_interactions[path['path_id']] = item
    for m in s['modules'].values():
        for path in m['plan']['paths']:
            previous = m['results'].get(path['path_id'])
            if previous and (previous.get('stale') or previous['quality'] != 'green-passed'):
                selected.append(path)
                if prepared_tests.source(m): path_test_sources[path['path_id']] = prepared_tests.source(m)
                path_build_artifacts[path['path_id']] = list(m.get('build_artifacts', []))
                if m['plan'].get('dimension_analysis_ref'):
                    path_dimension_analysis_refs[path['path_id']] = m['plan']['dimension_analysis_ref']
                results[path['path_id']] = previous
                interaction = ui_fidelity.frozen_interaction(m, path)
                if interaction is not None:
                    frozen_interactions[path['path_id']] = interaction
    return {'path_test_sources': path_test_sources, 'frozen_interactions': frozen_interactions, 'path_build_artifacts': path_build_artifacts,
            'path_dimension_analysis_refs': path_dimension_analysis_refs,
            'freeze_id': digest({k:v['freeze_id'] for k,v in s['modules'].items()}),
            'code_files': refs, 'code_baseline': code_baseline,
            'build_artifacts': [ref for module in s['modules'].values() for ref in module.get('build_artifacts', [])],
            'plan': {'definitions': [], 'paths': selected},
            'results': results,
            'stale': any(results.get(p['path_id'], {}).get('quality') == 'green-passed' for p in selected)}


def dispatch_record(s, m, p):
    """What every worker dispatch records, whatever its mode: the hints the host followed and what it delivered."""
    hints = hint_record(s, m, p)
    if hints['card_followed'] is not False:  # reported and matching, or not reported: the dispatched instance holds its card
        holder = p.get('session_id') or p['instance_id']
        deliver(m, reading.card(s, m, worker_step(p)), holder)
        m.setdefault('actors', {})[p['role']] = holder
    return {'hints': hints}


def assign_worker(s, m, mid, p, events, root):
    """Shared by assign and the merged diagnosis-accept: every dispatch guard applies either way."""
    require(p.get('role') in ('implementer', 'fixer', 'test-runner'), 'unsupported worker role')
    require(p.get('role') not in ('implementer', 'fixer') or p.get('instance_id') not in m.get('design_authors', []),
            'design author cannot implement or fix this module')
    require(p.get('instance_id') and p.get('assignment_id') not in m['assignments'], 'invalid/duplicate assignment')
    usage = model_routing.record(p, role=p['role'])
    if audit_closure.active(s):
        require(p.get('instance_id') != s['audit_batch']['auditor_instance_id'], 'Auditor cannot implement or author verification')
    dispatch_guard(s, m, p['role'])
    execution_contract = control_policy.execution_contract(m, p)
    if p['role'] == 'test-runner' and tv.split(m):
        require(p.get('test_scope') == tv.next_scope(m), 'test stages run build -> unit -> static -> automation -> visual; the build assignment carries the first three')
    if p['instance_id'] not in m['authors']:
        m['authors'].append(p['instance_id'])
    preflight = context_readiness.enabled(s)
    context_ref = p.get('context_ref') or (context_readiness.reported(s, mid, p) if preflight else None)
    if p['role'] in ('implementer', 'fixer'):
        m['phase'] = 'implementing' if p['role'] == 'implementer' else 'fixing'
    a = m['assignments'][p['assignment_id']] = {**p, 'run_id': s['run_id'], 'module_id': mid,
        'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'closed': False,
        'fencing_token': len(events) + 1, **dispatch_record(s, m, p), **(usage or {})}
    if execution_contract:
        a['execution_contract'] = execution_contract
    if s.get('write_scope_check') and p['role'] == 'implementer':
        a['authoring_snapshot'] = write_scope.authoring_snapshot(s['target_root'], m['write_paths'],
            root)
    if preflight and not context_ref:
        context_ref = context_readiness.mechanical(root, s, mid, a)  # coding: nothing a model has to attest
        if context_ref:
            a['preflight'] = 'mechanical'
    if context_ref:
        a['context_ref'] = copy.deepcopy(context_ref)
    if context_ref or not preflight:
        start_work(m, a)


def start_work(m, a):
    """The work of a dispatch is authorized: a repair round is spent from here, not while its context is missing."""
    if a['role'] != 'fixer':
        return
    m.setdefault('fix_memory', []).append({'assignment_id': a['assignment_id'], 'audit_batch_id': m.get('audit_batch_id'), 'freeze_id': m['freeze_id'],
        'before_baseline': m['code_baseline'], 'diagnosis': m.get('diagnosis'), 'issues': copy.deepcopy(unresolved(m)),
        'status': 'pending', 'reusable': False})
    if not m.pop('audit_fix_grant', None):
        m['local_fix_used'] = m.get('local_fix_used', 0) + 1
    else:
        m['auditor_fix_used'] = True
    m['fix_rounds_used'] += 1
    m['total_fix_rounds'] += 1


def settle_preflight(m, actor, receipt):
    """A worker's report inside its own dispatch: ready authorizes the work, blocked hands the dispatch back."""
    # A dispatch the Ledger preflighted by itself still takes its worker's own report: a blocked one hands it back.
    a = next((x for x in m['assignments'].values() if not x.get('closed') and not design_stage.is_design(x)
              and (not x.get('context_ref') or x.get('preflight') == 'mechanical')
              and (x['role'], x['instance_id']) == (actor['role'], actor['instance_id'])), None)
    if not a or context_readiness.requirement('assign', a) != receipt['stage'] or a.get('context_ref') == receipt['report_ref']:
        return
    if receipt['verdict'] == 'ready':
        started = bool(a.get('context_ref'))
        a['context_ref'] = copy.deepcopy(receipt['report_ref'])
        a.pop('preflight', None)
        if not started:
            start_work(m, a)
    else:
        # Nothing was authorized, so there is no worker to stop: the module is back where a blocked preflight
        # before any dispatch leaves it, and the gap is handled the same way.
        a.update(closed=True, declined_ref=copy.deepcopy(receipt['report_ref']))
        m['phase'] = 'diagnosing' if a['role'] == 'fixer' else 'frozen' if a['role'] == 'implementer' else 'testing'


def mutate(s, req, principal, events, root=None):
    op, p = req['operation'], req.get('payload', {})
    audit_before = copy.deepcopy(s['modules']) if audit_closure.active(s) or op in audit_closure.OPS else {}
    mid = req.get('module_id')
    global_ops = {'register', 'decision', 'audit-code-review', 'audit-assign', 'audit', 'audit-revoke', 'audit-route', 'audit-unavailable'} | workflow.GLOBAL_OPERATIONS | audit_closure.GLOBAL_OPS | source_changes.OPS | run_changes.OPS | audit_execution.OPS | {'retrospect'}
    if op in ('context-submit', 'session') and mid is None:
        global_ops.add(op)
    require((mid is None) == (op in global_ops), 'operation has incorrect global/module scope')
    m = s['modules'].get(mid) or s.get('module_groups', {}).get(mid)
    if mid:
        require(m is not None, 'module not registered')
        if mid in s.get('module_groups', {}):
            require(op in ('module-summary', 'session', 'redecompose', 'redecompose-accept', 'realloc-request'), 'parent MO only coordinates/summarizes; execute code and tests in child modules')
    audit_preflight = op == 'context-submit' and read_json(check_ref(p.get('report_ref'))).get('stage') == 'audit-execution'
    if workflow.audit_locks(s, mid) and not audit_preflight and op not in ('audit', 'audit-revoke', 'decision', 'audit-test-assign', 'audit-test-submit'):
        raise Rejected('audit snapshot locked; close or revoke audit before mutation')
    if audit_closure.active(s) and op not in audit_closure.OPS | {'decision', 'assign', 'submit', 'accept', 'complete', 'checkpoint', 'revoke', 'session', 'module-summary', 'context-submit', 'automation-unavailable'}:
        raise Rejected('audit closure active; complete verification or obtain human review')
    context_readiness.gate(s, req, principal)
    hint = req.get('hint')
    if hint is not None:
        require(isinstance(hint, dict) and isinstance(hint.get('session_id'), str) and hint['session_id']
                and isinstance(hint.get('card_sha256'), str), 'hint needs session_id and card_sha256')
        record_inputs(s, hint)
        if mid is None:
            step = routing(s)['global_next_step']
            if step.get('card_sha256') == hint['card_sha256']:
                deliver(s, step['must_read'], hint['session_id'])
            previous_session = s.get('context_sessions', {}).get(principal['role'])
            require(not s.get('host_handoff_required') or previous_session in (None, hint['session_id']),
                    'global hint cannot replace session; submit host session handoff first')
            s.setdefault('context_sessions', {})[principal['role']] = hint['session_id']
        if op == 'assign':  # one way to report for every operation; explicit payload fields still win
            p = {'session_id': hint['session_id'], 'card_sha256': hint['card_sha256'], **p}
        elif mid and mid not in s.get('module_groups', {}):
            record_hint(s, m, hint)
    elif mid in s['modules']:
        record_actor(s, m, principal, op)
    if op == 'context-submit':
        receipt = context_readiness.submit(s, req, principal)
        if mid in s['modules']:
            settle_preflight(m, principal, receipt)
    elif op == 'audit-code-review':
        audit_code_review.accept(s, p, principal)
    elif op in run_changes.OPS:
        run_changes.handle(root, s, req, principal)
    elif op == 'retrospect':
        role(principal, 'host')
        import experience
        experience.validate_lessons(p.get('lessons_ref'))
        s.setdefault('retrospectives', []).append({'lessons_ref': p['lessons_ref'], 'actor': principal})
    elif op in source_changes.OPS:
        source_changes.handle(root, s, req, principal)
    elif op in tv.OPS:
        tv.handle(s, req, principal)
    elif op in decomposition.OPERATIONS:
        decomposition.handle(s, req, principal, root)
    elif op in audit_closure.OPS:
        audit_closure.handle(s, req, principal)
    elif op in workflow.OPERATIONS:
        workflow.handle(s, req, principal, run_root=root)
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
        require(p.get('lean_leaf') in (None, True), 'lean_leaf must be true when present')
        if p.get('lean_leaf'):
            require(not p.get('decomposition_required'), 'a lightweight leaf is an atomic root; it cannot also require decomposition')
            decomposition.check_scope(p)
            require(set(p['scope']['requirement_ids']) <= set(s['requirement_ids']), 'unknown global requirement in leaf scope')
            require(p.get('leaf_review_ref'), 'lean leaf requires the GO atomic-root review')
            check_ref(p['leaf_review_ref'])
        if p.get('decomposition_required'):
            decomposition.check_scope(p)
            require(set(p['scope']['requirement_ids']) <= set(s['requirement_ids']), 'unknown global requirement in root scope')
        dimensions.allocation(s, p)
        if s.get('behavior_contract_required'):
            import behavior_contract
            decomposition.check_scope(p)
            behavior_contract.review(p, p.get('behavior_review'))
            behavior_contract.verification({**p, 'dependencies': p.get('dependencies', [])})
            accepted = behavior_contract.accepts(p)
            require(isinstance(accepted, list) and len(set(accepted)) == len(accepted) and set(accepted) <= set(p['case_ids']),
                    'acceptance cases outside allocation')
            shared = sorted({cid for other in run_changes.roots(s).values() for cid in behavior_contract.accepts(other)}.intersection(accepted))
            require(not shared, 'cases already accepted by another root: ' + ', '.join(shared[:8])
                    + '; one root accepts a case and the others hold it as a contribution (acceptance_case_ids)')
        s['modules'][mid] = new_module(p)
        s['global_plan'] = None
    elif op == 'decision':
        role(principal, 'host')
        require(p.get('decision') == 'approved' and p.get('human_source_ref') and p.get('subject_sha256'), 'actual human approval required')
        check_ref(p['human_source_ref'])
        require(p.get('decision_id') not in s['decisions'], 'decision already exists')
        if p.get('kind') == 'batch-envelope':
            parent = s.get('module_groups', {}).get(p.get('module_id'), {})
            doc = read_json(check_ref(p.get('envelope_ref')))
            children = doc.get('children')
            require(parent and p['subject_sha256'] == p['envelope_ref']['sha256'] and doc.get('parent_module_id') == p['module_id']
                    and isinstance(children, dict) and children and set(children) <= set(parent.get('children', [])),
                    'batch envelope decision must hash its document and cover only this parent\'s children')
        s['decisions'][p['decision_id']] = {**p, 'consumed': False}
    elif op == 'plan':
        role(principal, 'spec-designer')
        idle(m)
        require(not m.get('blocked'), 'resolve module blocker before planning')
        require(not m.get('decomposition_required') and not m.get('decomposition_submission'), 'finish MO decomposition before leaf SPEC planning')
        require(m['phase'] in ('context', 'specifying', 'clarifying', 'change-review'), 'plan not editable in this phase')
        held = m.get('plan_ref') == p['plan_ref']
        plan = design_stage.materialize(s, m, read_json(check_ref(p['plan_ref'])), judge=not held)
        import minimal_plan
        plan = minimal_plan.complete(s, m, plan)  # what follows from the leaf's accepted four-dimension specification
        if s.get('planning_coverage_required'):
            plan = user_paths.settle_gaps(s, m, plan)  # and from the run's statement that no device is available
        require('checklist' not in {d.get('kind') for d in plan.get('definitions') or []},
                'the checklist is the package rubric the Ledger binds; omit it from definitions')
        if s.get('behavior_contract_required'):
            plan.setdefault('behavior_contract_required', True)  # the run requires it; the author need not declare it
            import behavior_contract
            behavior_contract.complete(plan)  # the designed assertions say which scenarios they verify
        # The plan the Ledger already holds, submitted again to stand on the current context: it was judged when it
        # was first submitted, so only its bytes and what it relates to are checked now.
        resubmitted = held and digest(plan) == m.get('plan_hash')
        design_stage.plan_check(s, m, plan, principal['instance_id'], judge=not resubmitted)
        if s.get('behavior_contract_required'):
            require(plan.get('behavior_contract_required') is True, 'plan cannot opt out of the behavior contract')
        if m.get('scope'):
            decomposition.check_scopes(s, m)
            decomposition.check_tasks(m, plan)
        if resubmitted:
            verify_plan(plan, m)
            plan_hash = m['plan_hash']
        else:
            plan_hash = validate_plan(plan, m)
            m['plan_submissions'] = m.get('plan_submissions', 0) + 1  # distinct plans accepted for this freeze
            if s.get('split_testing_required') or any(path.get('kind') == 'build' for path in plan['paths']):
                tv.plan_check(plan, s['target_root'], static_required=s.get('spec_closure_required', False),
                              unit_required=s.get('unit_tests_required', False))
            if m.get('parent_module_id') or s.get('reuse_required') or plan.get('reuse_plan_ref'):
                reuse.validate_plan(plan, m, reuse.sources(s), s['modules'], s['legacy_root'])
            if s.get('planning_coverage_required'):
                user_paths.plan_gate(m, plan)
        occupied = {path['path_id'] for path in s['global_paths']}
        occupied.update(path['path_id'] for other in s['modules'].values() if other['module_id'] != mid
                        and other.get('plan') for path in other['plan']['paths'])
        require(not occupied.intersection(path['path_id'] for path in plan['paths']), 'PATH IDs must be globally unique')
        import behavior_contract
        scenarios = behavior_contract.index(plan)
        other_scenarios = {row['scenario_id'] for other in s['modules'].values() if other['module_id'] != mid
                           for row in other.get('scenario_index', [])}
        require(not other_scenarios.intersection(row['scenario_id'] for row in scenarios), 'Scenario IDs must be globally unique')
        owners = reuse.selected_owners(plan)
        if s.get('behavior_contract_required'):
            behavior_contract.check_owners(s, owners)
        # The boundary belongs to the allocation and was judged when that was registered; a plan is held to the one it has.
        boundary = (m.get('behavior_review') or {}).get('verification')
        if boundary and not resubmitted:
            require(plan['source_closure'].get('verification') == boundary, 'leaf plan verification differs from allocation')
            for path in plan['paths']:
                if path.get('kind', 'automation') in behavior_contract.BEHAVIOR_KINDS:
                    require(path.get('fixture_contract_ref') == boundary['fixture_contract_ref'], 'behavior PATH must bind allocated verification fixture')
        # Plan is content; the artifact remains immutable and is checked at freeze/dispatch.
        # The plan stands on the context and allocation current now; its author does not copy them into it.
        m.pop('plan_review_ref', None)
        m.update(plan=plan, plan_ref=p['plan_ref'], plan_hash=plan_hash, phase='clarifying', provider_owners=owners,
                 scenario_index=scenarios, plan_binding=decomposition.context_binding(s, m), checklist_ref=checklist_rubric(root))
        if principal['instance_id'] not in m.setdefault('spec_authors', []):
            m['spec_authors'].append(principal['instance_id'])
        if plan.get('test_design_ref') and not design_stage.required(s, m) and principal['instance_id'] not in m['authors']:
            m['authors'].append(principal['instance_id'])
    elif op == 'plan-review':
        role(principal, 'module-orchestrator')
        require(m['phase'] == 'clarifying', 'plan review requires clarifying')
        idle(m)
        control_policy.technical_review(m, p.get('review_ref'), principal)
        m['plan_review_ref'] = p['review_ref']
    elif op == 'planning-reopen':
        role(principal, 'module-orchestrator')
        require(m['phase'] in ('clarifying', 'frozen') and not m.get('blocked'), 'planning reopen requires unblocked planning')
        idle(m)
        require(not control_policy.execution_started(m), 'execution started; use CR/upstream revision')
        for a in m['assignments'].values():
            if a.get('no_code_change_ref'):
                require(a['authoring_snapshot'] == write_scope.authoring_snapshot(s['target_root'],
                    a['authoring_snapshot']['scopes'], root), 'code changed after stop; use CR/upstream revision')
        check_ref(p.get('reason_ref'))
        reset_plan(m, 'pre-implementation replanning', p['reason_ref'])
    elif op == 'freeze':
        role(principal, 'module-orchestrator')
        freeze_guard(s, m, p)
        m.setdefault('plan_rounds', []).append(m.pop('plan_submissions', 0))  # how many distinct plans this freeze took
        if not p.get('decision_id') and p.get('review_ref'):
            control_policy.technical_review(m, p['review_ref'], principal)
            m['plan_review_ref'] = p['review_ref']
        decision = s['decisions'].get(p.get('decision_id'), {})
        if decision.get('kind') == 'batch-envelope':
            require(p.get('review_ref'), 'batch envelope freeze requires the MO plan review_ref')
            check_ref(p['review_ref'])
            decision.setdefault('used_by', {})[mid] = m['plan_hash']
        if p.get('change_class') != 'within-envelope':
            if decision and decision.get('kind') != 'batch-envelope':
                decision['consumed'] = True
            m['approved_envelope'] = digest(m['plan']['decision_envelope'])
            m['approved_acceptance_kind'] = 'business'
            m['approved_acceptance'] = control_policy.acceptance_hash(m)
        m['approved_test_paths'] = copy.deepcopy(control_policy.acceptance(m['plan']['paths']))
        if m.get('change_request'):
            revalidation = task_revalidation.prepare(m, p.get('review_ref'))
            prior_execution = {key: copy.deepcopy(m.get(key)) for key in
                ('code_files', 'code_baseline', 'accepted_task_ids', 'task_files', 'results', 'dimension_evidence', 'build_artifacts')}
            m.setdefault('change_request_history', []).append({**m.pop('change_request'), 'to_freeze_id': m['plan_hash'],
                'kind': 'planning-history', 'executable': False, 'prior_execution': prior_execution})
            retained = set(revalidation['retained_task_ids'])
            # No TASK changed: the code already accepted implements the revised contract, so the leaf goes on to rebuild it.
            rebuilt = bool(retained) and retained == {t['task_id'] for t in m['plan']['tasks']} and bool(m.get('code_baseline'))
            m.update(accepted_task_ids=sorted(retained), task_files={tid: files for tid, files in m.get('task_files', {}).items() if tid in retained},
                     execution_partition_pending=not rebuilt, build_baseline=None, build_artifacts=[], task_revalidation=revalidation)
            if not rebuilt:
                m.pop('dimension_evidence', None)
            m['results'] = {pid: {**result, 'stale': True} for pid, result in m['results'].items() if pid in {p['path_id'] for p in m['plan']['paths']}}
            task_revalidation.carry(m, prior_execution['results'])
            m.update(freeze_id=m['plan_hash'], phase='testing' if rebuilt else 'frozen', stale=True)
        else:
            m.update(freeze_id=m['plan_hash'], phase='frozen', stale=True)
    elif op == 'change':
        role(principal, 'module-orchestrator')
        require(m.get('freeze_id') and p.get('request_ref') and p.get('impact_ref'), 'CR and impact required')
        check_ref(p['request_ref']); check_ref(p['impact_ref'])
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'close active assignments before CR')
        require(not m.get('blocked'), 'resolve blocker or invalidate before CR')
        if unresolved(m):
            # Reworking a failed module through a contract change is a repair attempt, not a free retry.
            require(m['fix_rounds_used'] < m.get('fix_budget', s['max_fix_rounds']), 'repair budget exhausted; recover requires decision')
            m['fix_rounds_used'] += 1
            m['total_fix_rounds'] += 1
        open_change(s, m, p)
    elif op == 'assign':
        role(principal, 'module-orchestrator')
        require(p.get('mode') in (None, 'execute', 'design'), 'unknown assignment mode')
        if design_stage.is_design(p):
            record = {**dispatch_record(s, m, p), **(model_routing.record(p, role=p['role']) or {})}
            design_stage.dispatch(s, m, p, principal, len(events) + 1)
            m['assignments'][p['assignment_id']].update(record)
        else:
            assign_worker(s, m, mid, p, events, root)
    elif op == 'submit':
        assignment = m['assignments'].get(p.get('assignment_id'), {})
        require(not assignment.get('closed', True), 'assignment inactive')
        require(principal == {'role': assignment['role'], 'instance_id': assignment['instance_id']}, 'worker identity mismatch')
        require(p.get('fencing_token') == assignment['fencing_token'], 'stale fencing token')
        if design_stage.is_design(assignment):
            design_stage.submission(s, m, assignment, p, principal)
        else:
            require(assignment.get('execution_contract'), 'assignment execution contract missing; revoke and reassign')
            require(assignment['freeze_id'] == m['freeze_id'], 'assignment freeze stale')
            require(assignment.get('context_ref') or not context_readiness.enabled(s),
                    'preflight required: context-submit a ready report for this assignment before its result')
            worker_phase(m, assignment)
            dependencies_ready(s, m)
            result = read_json(check_ref(p['result_ref']))
            validate_result(result, m, assignment, run_root=root)
            if s.get('write_scope_check') and result.get('kind') == 'implementation':
                require(p.get('write_scope_ref'), 'write_scope_ref required: host write-scope delta receipt')
                write_scope.verify(s, m, assignment, result, read_json(check_ref(p['write_scope_ref'])))
            # The submission is the hash-bound reference plus what the cursor and the report need from it.
            m['submissions'][p['assignment_id']] = {
                'ref': p['result_ref'], 'kind': result.get('kind'), 'green': all_green_tests(result),
                'test_run_ids': [row.get('test_run_id') for row in result.get('paths', [])] if result.get('kind') == 'tests' else []}
    elif op == 'accept':
        require(not s.get('audit_batch', {}).get('retry_stops', {}).get(mid), 'stop affected old worker before accepting stale audit output')
        role(principal, 'module-orchestrator')
        aid = p['assignment_id']
        assignment = m['assignments'].get(aid, {})
        require(not assignment.get('closed', True) and aid in m['submissions'], 'no active submission')
        if design_stage.is_design(assignment):
            design_stage.accept(s, m, assignment, p, principal)
            m['revision'] += 1
            refresh(s)
            return
        require(assignment.get('execution_contract'), 'assignment execution contract missing; revoke and reassign')
        worker_phase(m, assignment)
        dependencies_ready(s, m)
        sub = m['submissions'][aid]
        result = read_json(check_ref(sub['ref']))
        kind = validate_result(result, m, assignment, run_root=root)
        assignment['closed'] = True
        if kind == 'implementation':
            prior_results = copy.deepcopy(m['results'])
            m['results'] = {pid: {**row, 'stale': True} for pid, row in m['results'].items()}
            m['build_artifacts'] = []
            m['accepted_task_ids'] = sorted(set(m.get('accepted_task_ids', [])) | {t['task_id'] for t in result['task_trace']})
            m.setdefault('task_files', {}).update({t['task_id']: t['files'] for t in result['task_trace']})
            if result.get('dimension_evidence'):
                m['dimension_evidence'] = copy.deepcopy(result['dimension_evidence'])
            if assignment['role'] == 'fixer':
                memory = next(x for x in m['fix_memory'] if x['assignment_id'] == aid)
                memory.update(after_baseline=result['code_baseline'], implementation_ref=sub['ref'],
                              fix_note_ref=result['fix_note_ref'], status='awaiting-regression')
            m['execution_partition_pending'] = set(m['accepted_task_ids']) != {t['task_id'] for t in m['plan']['tasks']}
            complete_tasks = set(m['accepted_task_ids']) == {t['task_id'] for t in m['plan']['tasks']}
            m.update(code_files=result['code_files'], code_baseline=result['code_baseline'], phase='testing' if complete_tasks else 'frozen', stale=True, build_baseline=None)
            if {t['task_id'] for t in result['task_trace']} & set(m.get('task_revalidation', {}).get('retained_task_ids', [])):
                m['task_revalidation'] = {'mode': 'full', 'reason': 'retained-task-updated', 'retained_task_ids': [], 'retained_path_ids': []}
            task_revalidation.carry(m, prior_results)
            m.pop('automation_retry_ready', None)
            invalidate_dependents(s, mid)
        else:
            previous_fingerprint = failure_fingerprint(m['results'])
            if tv.split(m):
                m['results'].update({x['path_id']: {**x, 'code_baseline': m['code_baseline'], 'stale': False} for x in result['paths']})
                kinds = {x['path_id']: x.get('kind') for x in m['plan']['paths']}
                builds = [row for row in result['paths'] if kinds.get(row['path_id']) == 'build']
                if builds:
                    m['build_artifacts'] = [ref for row in builds if row['quality'] == 'green-passed' for ref in row.get('build_artifacts', [])]
                    m['build_baseline'] = m['code_baseline'] if all(x['quality'] == 'green-passed' for x in builds) else None
                if assignment.get('test_scope') != 'build' or any(x['quality'] != 'green-passed' for x in result['paths']):
                    m.pop('automation_retry_ready', None)
            else:
                if assignment.get('execution_contract'):
                    m['results'].update({x['path_id']: {**x, 'code_baseline': m['code_baseline'], 'stale': False} for x in result['paths']})
                else:
                    m['results'] = {x['path_id']: x for x in result['paths']}
            # Build, unit tests and static review are pre-functional gates: judge only their own paths.
            build_only = tv.split(m) and assignment.get('test_scope') == 'build'
            bad = sorted(x['path_id'] for x in result['paths'] if x['quality'] != 'green-passed') if build_only else sorted(k for k,v in m['results'].items() if v['quality'] != 'green-passed')
            if build_only and not bad:
                m['automation_retry_ready'] = True
            m['no_progress_rounds'] = m['no_progress_rounds'] + 1 if bad and failure_fingerprint(m['results']) == previous_fingerprint else 0
            for memory in m.get('fix_memory', []):
                if not build_only and memory['status'] == 'awaiting-regression' and memory.get('after_baseline') == m['code_baseline']:
                    memory.update(status='verified' if not bad else 'failed', reusable=not bad,
                                  regression_ref=sub['ref'], regression_paths=copy.deepcopy(result['paths']))
            m.update(stale=False, phase='dod' if tv.all_green(m) else 'testing', diagnosis_submission=None, diagnosis=None, repair_findings={})
            audit_closure.test_accepted(s, m, result, sub['ref'], build_only=build_only,
                                        stage=assignment.get('test_scope') or 'build')
    elif op == 'diagnose':
        role(principal, 'diagnostician', 'fixer')
        require(principal['role'] == 'diagnostician' or self_diagnosis(s, m), 'principal role denied')
        require(m['phase'] == 'testing' and not m.get('blocked') and unresolved(m), 'no unresolved test failure')
        idle(m); current(m)
        check_ref(p['diagnosis_ref'])
        require(p.get('owner') and p.get('root_cause'), 'root cause and owner required')
        control_policy.repair_route(p)
        diagnosis_focus(m, p)
        m['diagnosis_submission'] = {'report': p, 'subject': diagnosis_subject(m)}
    elif op == 'diagnosis-accept':
        role(principal, 'module-orchestrator')
        idle(m); current(m)
        draft = m.get('diagnosis_submission')
        require(m['phase'] == 'testing' and not m.get('blocked') and unresolved(m) and draft
                and draft['subject'] == diagnosis_subject(m), 'diagnosis missing/stale')
        check_ref(draft['report']['diagnosis_ref'])
        m.update(diagnosis=draft['report'], diagnosis_submission=None, phase='diagnosing')
        if p.get('assign') is not None:
            # Merged dispatch: all assign guards still apply; a Fixer that already preflighted this diagnosis is bound at once.
            a = p['assign']
            require(isinstance(a, dict) and a.get('role') == 'fixer', 'merged dispatch only assigns the Fixer')
            if context_readiness.enabled(s) and a.get('context_ref'):
                context_readiness.validate(s, mid, 'fixing', a.get('context_ref'), a.get('instance_id'))
                m.setdefault('context_acceptances', {})['assign'] = {'report_ref': copy.deepcopy(a['context_ref']),
                                                                     'accepted_by': copy.deepcopy(principal)}
            assign_worker(s, m, mid, a, events, root)
    elif op == 'suspend':
        role(principal, 'module-orchestrator')
        require(not m.get('blocked') and m['phase'] != 'completed', 'cannot stack blockers or suspend completed module')
        require(p.get('reason') and p.get('root_cause') and p.get('owner'), 'structured blocker required')
        require(p.get('kind') in ('dependency', 'human', 'tooling'), 'invalid blocker')
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'stop/revoke workers before suspension')
        gap = None
        require('implementation_gap' not in p, 'implementation gap is derived from reviewed evidence')
        if p.get('reason_code') == 'not-implemented' or p.get('implementation_gap_ref'):
            require(p.get('reason_code') == 'not-implemented', 'implementation gap needs not-implemented reason code')
            gap = reuse.implementation_gap(s, m, p)
        blocked_on = []
        if p['kind'] == 'dependency':
            for dep in m['dependencies']:
                try:
                    dependencies_ready(s, {'dependencies': [dep]})
                except (Rejected, OSError):
                    blocked_on.append(dep)
            require(blocked_on, 'dependency suspension requires an unavailable registered dependency; peer failure is not a blocker')
        m['blocked'] = {**p, 'resume_phase': m['phase']}
        if gap:
            m['blocked']['implementation_gap'] = gap
            m['stale'] = True
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
        resolved = {key: copy.deepcopy(m['blocked'][key]) for key in ('kind', 'reason', 'reason_code', 'root_cause', 'owner', 'evidence_refs')
                    if m['blocked'].get(key)}
        if m['blocked']['kind'] == 'dependency':
            m.pop('dependency_release', None)
        else:
            s['decisions'][p['decision_id']]['consumed'] = True
            resolved['resolution_ref'] = copy.deepcopy(s['decisions'][p['decision_id']]['human_source_ref'])
        m.setdefault('blocker_history', []).append(resolved)  # what stopped the module and what released it
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
        # Budget approval does not resolve an independent human/tooling/dependency blocker.
        if not m.get('blocked'):
            m['phase'] = 'diagnosing' if m.get('diagnosis') else 'testing'
    elif op == 'session':
        role(principal, 'module-orchestrator' if mid else 'host')
        name = p['role']
        require(p.get('session_id'), 'session id required')
        usage = model_routing.record(p, role=name)
        parent_name = decomposition.parent_mo_names(s).get(mid)
        if name == 'module-orchestrator' and parent_name:
            require(p.get('agent_name', parent_name) == parent_name, 'parent MO name must be ' + parent_name)
            p = {**p, 'agent_name': parent_name}
        previous = m['sessions'].get(name) if m is not None else ({'role': name, 'session_id': s['context_sessions'][name]} if name in s.get('context_sessions', {}) else None)
        context_handoff.replace(s, m, p, previous)
        if m is not None:
            m['sessions'][name] = {**p, **(usage or {})}
        else:
            s.setdefault('context_sessions', {})[name] = p['session_id']
            s.setdefault('sessions', {})[name] = {**p, **(usage or {})}
    elif op == 'revoke':
        role(principal, 'host')
        a = m['assignments'].get(p.get('assignment_id'), {})
        require(a and not a.get('closed') and p.get('stopped_worker_ref'), 'active worker and host stop/isolation evidence required')
        check_ref(p['stopped_worker_ref'])
        stops = s.get('audit_batch', {}).get('retry_stops', {}).get(mid, [])
        retry_stop = a['assignment_id'] in stops
        if retry_stop: stops.remove(a['assignment_id'])
        if p.get('allow_planning_reopen'):
            require((a.get('role') == 'implementer') and (not m.get('code_baseline')) and (a.get('authoring_snapshot')) and (a['assignment_id'] not in m['submissions']),
                    'planning rollback needs host authoring baseline and no code submission')
            require(a['authoring_snapshot'] == write_scope.authoring_snapshot(s['target_root'],
                a['authoring_snapshot']['scopes'], root), 'code changed; use CR/upstream revision')
            a['no_code_change_ref'] = copy.deepcopy(p['stopped_worker_ref'])
        a['closed'] = True
        if design_stage.is_design(a):
            a['revoked'] = True
            m['submissions'].pop(a['assignment_id'], None)
        if not retry_stop and audit_closure.active(s) and m.get('audit_batch_id') == s['audit_batch']['batch_id']:
            audit_closure.stop(s, 'worker-interrupted', mid, p['stopped_worker_ref'])
        m['stale'] = True
        for memory in m.get('fix_memory', []):
            if memory['assignment_id'] == p['assignment_id'] and memory['status'] == 'pending':
                memory['status'] = 'interrupted'
        if not m.get('blocked'):
            m['phase'] = a['resume_phase'] if design_stage.is_design(a) else 'diagnosing' if a['role'] == 'fixer' else 'frozen' if a['role'] == 'implementer' else 'testing'
    elif op == 'invalidate':
        role(principal, 'module-orchestrator', 'host')
        require(p.get('reason'), 'invalidation reason required')
        require(not any(not a.get('closed') for a in m['assignments'].values()), 'revoke worker before invalidation')
        if m.get('blocked'):
            m.pop('approved_envelope', None)
            m.pop('approved_acceptance', None)
        reset_plan(m, p['reason'])
        invalidate_dependents(s, mid)
    elif op == 'checkpoint':
        role(principal, 'host')
        require(s.get('git_checkpoint'), 'git checkpoint not enabled for this run')
        require(m['phase'] == 'dod' and not m['stale'], 'checkpoint only at module DoD')
        m['git_checkpoint'] = git_checkpoint.verify(s, m, read_json(check_ref(p.get('receipt_ref'))))
    elif op == 'complete':
        role(principal, 'module-orchestrator')
        complete_guard(s, m)
        ui_fidelity.completion_gate(s, m)
        check_ref(p['dod_ref'])
        require(p.get('checks_passed', True) is True, 'DoD review required')
        m['phase'] = 'completed'
    elif op in audit_execution.OPS:
        audit_execution.handle(s, req, principal, audit_scope(s))
    elif op == 'audit-assign':
        role(principal, 'global-orchestrator')
        workflow.planning_guard(s)
        audit_code_review.require_current(s, p.get('instance_id'))
        governance = read_json(check_ref(s['audit_code_review']['report_ref']))
        require(all(row['conclusion'] == 'satisfied' for row in governance['goal_review']['requirements']), 'host goal issues require upstream/finding convergence before final verdict')
        require(not audit_code_review.pending(s), 'code governance findings require closure before final audit')
        require(not audit_closure.collection_blockers(s), 'all module rounds must settle before Auditor')
        require(not audit_closure.active(s), 'audit closure incomplete')
        require(not s.get('audit_queue'), 'problem audit queue unresolved')
        require(not pending_repairs(s), 'audit repairs require routing and MO acceptance')
        require(s['modules'] and all(tv.available(x) for x in s['modules'].values()), 'modules incomplete')
        require(not s.get('audit_assignment') or s['audit_assignment'].get('closed'), 'audit already active')
        require(p.get('instance_id') and p.get('assignment_id'), 'audit identity required')
        require(p['assignment_id'] not in s.get('audit_assignment_ids', []), 'audit assignment id already used')
        require(p['instance_id'] not in prepared_tests.global_authors(s), 'Auditor must be independent of GLOBAL script author')
        for mod in s['modules'].values():
            require(p['instance_id'] not in mod['authors'], 'Auditor must be independent')
            current(mod)
        require(s.get('audit_attempts', 0) < workflow.audit_budget(s), 'audit budget exhausted; audit-recover requires decision in this run')
        s['audit_attempts'] = s.get('audit_attempts', 0) + 1
        s.setdefault('audit_assignment_ids', []).append(p['assignment_id'])
        audit_usage = model_routing.record(p, role='auditor')
        s['audit_assignment'] = {**p, 'role': 'auditor', 'run_id': s['run_id'], 'module_id': 'GLOBAL',
                                 'closed': False, 'attempt': s['audit_attempts'],
                                 'scope_policy': 'non-green-only',
                                 'path_ids': [p['path_id'] for p in audit_scope(s)['plan']['paths']],
                                 'snapshot': {k:v['code_baseline'] for k,v in s['modules'].items()}, **(audit_usage or {})}
    elif op == 'audit':
        role(principal, 'auditor')
        assignment = s.get('audit_assignment', {})
        require(assignment.get('mode') != 'problem', 'obsolete problem audit; revoke and use whole-task audit')
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
        if scope['plan']['paths']:
            audit_execution.evidence(s, scope, report)
            require(report.get('schema_version') == 1 and report.get('kind') == 'tests', 'audit report schema/kind mismatch')
            for field, value in (('run_id', s['run_id']), ('module_id', 'GLOBAL'), ('assignment_id', assignment['assignment_id']),
                ('actor_instance_id', principal['instance_id']), ('freeze_id', scope['freeze_id']), ('code_baseline', scope['code_baseline'])):
                require(report.get(field) == value, 'audit verdict ' + field + ' mismatch')
            check_ref(report.get('review_ref'))
        else:
            validate_result(report, scope, assignment, run_root=root)
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
        task = s.get('audit_test_assignment', {})
        if not task.get('closed', True) and task.get('audit_assignment_id') == assignment['assignment_id']:
            check_ref(p.get('test_worker_stopped_ref'))
            task['closed'] = True
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


def artifact_index(events):
    """Index archives declared by the caller's verified committed event chain."""
    index = {}
    for event in events:
        for item in event.get('artifact_snapshots', []):
            if item.get('source_path') and item.get('sha256'):
                key = (item['source_path'], item['sha256'])
                index.setdefault(key, (item, {k: event[k] for k in ('event_id', 'sha256')}))
    return index


def new_snapshots(root, payload, target_root, index):
    """Archive every ref of a payload; list what this event adds to the cumulative index.

    An artifact some earlier event already archived is found through that event, so it is not listed
    again. Drift and historical-snapshot records describe this event and are always kept."""
    return [item for item in preserve_refs(root, payload, target_root=target_root, accepted=index)
            if item.get('status') or (item.get('source_path'), item.get('sha256')) not in index]


def preserve_refs(root, value, seen=None, nested=False, target_root=None, accepted=None):
    """Archive evidence bytes before commit; keep live refs for stale-code detection.

    Nested historical controller/protocol refs may read an exact archive from a prior committed event;
    top-level inputs and business gates still require current live bytes.
    Refs discovered inside archived JSON evidence are preserved best-effort for
    live target code only: target files legitimately drift after accepted
    implementations (code_baseline/reuse.verify remain the business gates), so
    nested drift under target_root is recorded in the event trail instead of
    rejecting the commit. Top-level payload refs and nested immutable evidence
    (legacy sources, staging/context artifacts) remain strictly validated.
    """
    seen = set() if seen is None else seen
    saved = []
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            key = (value['path'], value['sha256'])
            if key in seen:
                return []
            seen.add(key)
            historical = None
            try:
                path = check_ref(value)
            except ValueError:
                tool_history = nested and any(Path(value['path']).resolve().is_relative_to(p)
                                              for p in HISTORICAL_TOOL_ROOTS)
                historical = (accepted or {}).get(key) if tool_history else None
                if historical:
                    entry, source_event = historical
                    path = run_storage.checked_path(root / 'artifacts' / value['sha256'], root / 'artifacts')
                    require(entry['path'] == str(path), 'event artifact location differs from managed archive')
                    check_ref({'path': str(path), 'sha256': value['sha256']})
                else:
                    live_target = nested and target_root and isinstance(value.get('path'), str) and \
                        Path(value['path']).resolve().is_relative_to(Path(target_root).resolve())
                    if not live_target:
                        raise
                    return [{'source_path': value.get('path'), 'expected_sha256': value.get('sha256'),
                             'status': 'drifted-or-missing-live-target-code'}]
            blob = run_storage.checked_path(root / 'artifacts' / value['sha256'], root / 'artifacts')
            blob.parent.mkdir(exist_ok=True)
            if not blob.exists():
                with blob.open('xb') as f:
                    with path.open('rb') as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            f.write(chunk)
                    f.flush(); os.fsync(f.fileno())
            require(file_ref(blob)['sha256'] == value['sha256'], 'archived artifact corrupt')
            saved.append({'source_path': value['path'], **file_ref(blob),
                          **({'status': 'historical-snapshot', 'accepted_event': source_event} if historical else {})})
            if Path(value['path']).suffix == '.json':
                try:
                    nested_value = read_json(path)
                except Rejected:
                    raise  # a document that cites an id its refs table lacks is wrong, not merely not JSON
                except ValueError:
                    nested_value = None
                saved.extend(preserve_refs(root, nested_value, seen, nested=True, target_root=target_root, accepted=accepted))
        else:
            for item in value.values():
                saved.extend(preserve_refs(root, item, seen, nested, target_root, accepted))
    elif isinstance(value, list):
        for item in value:
            saved.extend(preserve_refs(root, item, seen, nested, target_root, accepted))
    return saved


def apply(root, req, principal):
    try:
        ack = _apply(root, req, principal)
        if req['operation'] in ('audit', 'audit-verdict', 'module-summary', 'retrospect'):
            # Project lock comes after the Ledger transaction releases its lock (prepare takes the reverse order).
            import experience
            try:
                ack['experience'] = experience.auto_harvest(root, force=req['operation'] == 'retrospect')
            except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
                ack['experience'] = {'status': 'pending', 'reason': str(exc), 'recovery_action': 'retry same request or sdd-retrospect'}
        return ack
    except run_storage.LockTimeout:
        # Reacquiring the same lock for a rejection diagnostic would wait again.
        raise
    except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
        # Diagnostic only; rejected requests never mutate business events/quality.
        progress_signals.record_rejection(root, req, principal, str(exc))
        raise


def _apply(root, req, principal):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with run_storage.file_lock(root / '.ledger.lock'):
        s, events = read_events(root)
        if s and s.get('project_context_ref'):
            run_storage.for_state(root, s)
        require(req.get('schema_version') == 1 and req.get('request_id'), 'version/request id required')
        request_hash = digest({'request': req, 'principal': principal})
        for e in events:
            if e['request_id'] == req['request_id']:
                require(e['request_hash'] == request_hash, 'request id reused with different content/actor')
                projection = project_outcome(root, s, len(events))
                return {'event_id': e['event_id'], 'sequence': e['sequence'], 'duplicate': True,
                        'committed': True, 'projection': projection}
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
            require(type(p.get('dimension_slicing_required', True)) is bool, 'dimension_slicing_required must be boolean')
            require(type(p.get('reuse_required', False)) is bool, 'reuse_required must be boolean')
            require(type(p.get('split_testing_required', True)) is bool, 'split_testing_required must be boolean')
            require(type(p.get('context_readiness_required', True)) is bool, 'context_readiness_required must be boolean')
            require(type(p.get('ui_fidelity_required', False)) is bool, 'ui_fidelity_required must be boolean')
            require(type(p.get('spec_closure_required', False)) is bool, 'spec_closure_required must be boolean')
            require(type(p.get('unit_tests_required', False)) is bool, 'unit_tests_required must be boolean')
            require(type(p.get('host_handoff_required', False)) is bool, 'host_handoff_required must be boolean')
            require(type(p.get('planning_coverage_required', False)) is bool, 'planning_coverage_required must be boolean')
            require(type(p.get('test_design_required', False)) is bool, 'test_design_required must be boolean')
            require('control_policy_version' not in p, 'workflow policy selectors are not supported')
            require(type(p.get('behavior_contract_required', False)) is bool, 'behavior_contract_required must be boolean')
            require(type(p.get('git_checkpoint', False)) is bool, 'git_checkpoint must be boolean')
            require(type(p.get('fixer_self_diagnosis', False)) is bool, 'fixer_self_diagnosis must be boolean')
            require(type(p.get('write_scope_check', False)) is bool, 'write_scope_check must be boolean')
            require(type(p.get('dependency_resolution_required', False)) is bool, 'dependency_resolution_required must be boolean')
            require(isinstance(p.get('build', {}), dict), 'build configuration must be an object')
            resources = project_context.target_resources(p.get('target_resources', {}), p['target_root'])
            require(type(p.get('worker_stall_timeout_seconds', 900)) is int and p.get('worker_stall_timeout_seconds', 900) > 0, 'invalid worker stall timeout')
            s = {'worker_stall_timeout_seconds': p.get('worker_stall_timeout_seconds', 900), 'dimension_slicing_required': p.get('dimension_slicing_required', True), 'build': copy.deepcopy(p.get('build', {})), 'split_testing_required': p.get('split_testing_required', True), 'context_readiness_required': p.get('context_readiness_required', True), 'ui_fidelity_required': p.get('ui_fidelity_required', False), 'spec_closure_required': p.get('spec_closure_required', False), 'unit_tests_required': p.get('unit_tests_required', False), 'git_checkpoint': p.get('git_checkpoint', False), 'fixer_self_diagnosis': p.get('fixer_self_diagnosis', False), 'write_scope_check': p.get('write_scope_check', False), 'dependency_resolution_required': p.get('dependency_resolution_required', False),
                 'target_resources': resources,
                 'behavior_contract_required': p.get('behavior_contract_required', False),
                 'test_design_required': p.get('test_design_required', False),
                 'planning_coverage_required': p.get('planning_coverage_required', False),
                 'host_handoff_required': p.get('host_handoff_required', False),
                 'reuse_sources': reuse_sources, 'reuse_required': bool(reuse_sources) or p.get('reuse_required', False),
                 'entry_mode': entry_mode, 'single_module_id': selected_module,
                 'host_task_contract': {'global_spec': copy.deepcopy(p['global_spec']), 'requirement_ids': copy.deepcopy(p['requirement_ids']), 'case_ids': copy.deepcopy(p['case_ids'])},
                 'global_spec': p['global_spec'], 'new_architecture': p['new_architecture'], 'requirement_ids': p['requirement_ids'],
                 'global_plan': None, 'audit_queue': {}, 'run_id': req['run_id'], 'revision': 1, 'target_root': str(Path(p['target_root']).resolve()),
                 'legacy_root': str(Path(p['legacy_root']).resolve()), 'case_ids': p['case_ids'],
                 'modules': {}, 'decisions': {}, 'audit': {}, 'global_paths': p.get('global_paths', []), 'quality': 'yellow-blocked',
                 'max_parallel_modules': p.get('max_parallel_modules', 3), 'max_audit_rounds': p.get('max_audit_rounds', 3),
                 'max_fix_rounds': p.get('max_fix_rounds', 3), 'max_no_progress_rounds': p.get('max_no_progress_rounds', 2),
                 'max_yellow_retries': p.get('max_yellow_retries', 2)}
            workflow.global_paths_check(s['global_paths'], s['case_ids'])
            require(all(type(s[k]) is int and s[k] > 0 for k in ('max_fix_rounds', 'max_no_progress_rounds', 'max_parallel_modules', 'max_audit_rounds', 'max_yellow_retries')), 'invalid budgets')
            require('local_fix_rounds' not in p, 'use the shared max_fix_rounds budget')
            if p.get('project_context_ref'):
                s.update(project_context.bind_run(p['project_context_ref'], root, req['run_id'], p))
            else:
                require(not (root / 'context/snapshot.json').exists(), 'prepared run requires project_context_ref')
        else:
            require(s and req.get('run_id') == s['run_id'], 'run mismatch')
            scope = (s['modules'].get(req.get('module_id')) or s.get('module_groups', {}).get(req.get('module_id'))) if req.get('module_id') else s
            require(scope is not None and req.get('expected_revision') == scope['revision'], 'stale revision')
            mutate(s, req, principal, events, root)
        import experience
        history_refs = experience.bind_history(root, s, len(events) + 1)
        history_refs += [m['execution_context_ref'] for m in s['modules'].values() if m.get('execution_context_ref')]
        # Store immutable event facts, not a second mutable state authority: the first event carries the
        # initial state, every later one only what it changed.
        if before is None:
            change = {'effect': s}
        else:
            after = json.loads(json.dumps(s, ensure_ascii=False))  # compare what a replay will actually read
            changed, removed = journal_diff(before, after)
            change = {'patch': {'set': changed, 'del': removed}}
            apply_change(before, change)
            require(before == after, 'journal patch does not reproduce the committed state')
        e = {'schema_version': 1, 'event_id': f'E{len(events)+1:08d}', 'sequence': len(events)+1,
             'timestamp': now(), 'request_id': req['request_id'], 'request_hash': request_hash,
             'actor': principal, 'operation': req['operation'], 'module_id': req.get('module_id'),
             'previous_hash': events[-1]['sha256'] if events else None, **change,
             'artifact_snapshots': new_snapshots(root, {'payload': req.get('payload', {}), 'history_refs': history_refs},
                                               s.get('target_root'), artifact_index(events))}
        e['sha256'] = digest(e)
        journal = run_storage.checked_path(root / 'ledger/events.jsonl', root)
        journal.parent.mkdir(exist_ok=True)
        with journal.open('a') as f:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + '\n')
            f.flush(); os.fsync(f.fileno())
        projection = project_outcome(root, s, e['sequence'])
        return {'event_id': e['event_id'], 'sequence': e['sequence'], 'duplicate': False,
                'committed': True, 'projection': projection}


def routing(s, observed_invalidations=(), ref_check=check_ref):
    """Derive the existing status routes without writing facts or projections."""
    observed = observed_invalidations
    cursor = [next_step(s, m) for m in s['modules'].values()]
    for group in s.get('module_groups', {}).values():
        step = decomposition.group_step(s, group, ref_check)
        step['human_required'] = control_policy.human_required(step)
        if step.get('operation'):
            step['model_tier'] = model_routing.advise(step['role'], step['operation'])
            with_card(s, group, step)
        cursor.append(step)
    rounds = audit_closure.module_rounds(s, cursor, ref_check)
    audit = s.get('audit_assignment', {})
    revision_step = run_changes.next_action(s)
    recovery_step = workflow.audit_recovery_step(s)
    if audit_closure.active(s):
        global_next = audit_closure.global_step(s)
    elif audit and not audit.get('closed'):
        fresh = audit.get('scope_policy') == 'non-green-only' and not observed and all(tv.available(m) for m in s['modules'].values()) and audit['snapshot'] == {k:v['code_baseline'] for k,v in s['modules'].items()}
        global_next = {'operation': 'audit' if fresh else 'audit-revoke', 'role': 'auditor' if fresh else 'host',
                       'assignment_id': audit['assignment_id'], 'ready': not fresh,
                       'reason': 'audit-running' if fresh else 'audit-snapshot-stale'}
        if fresh and audit['path_ids']:
            task = s.get('audit_test_assignment', {})
            same = task.get('audit_assignment_id') == audit['assignment_id']
            if not same or not task.get('result_ref'):
                global_next.update(operation='audit-test-submit' if same and not task.get('closed', True) else 'audit-test-assign',
                    role='test-runner' if same and not task.get('closed', True) else 'global-orchestrator',
                    ready=not same or task.get('closed', False), path_ids=audit['path_ids'],
                    assignment_id=task['assignment_id'] if same and not task.get('closed', True) else audit['assignment_id'])
            else:
                global_next.update(ready=True, test_result_ref=task['result_ref'])
    elif revision_step:
        global_next = {**revision_step, 'continue_modules': rounds['ready_modules']}
    elif recovery_step:
        global_next = recovery_step
        global_next['continue_modules'] = rounds['ready_modules']
    elif not s.get('global_plan'):
        splitting = any(g.get('replanning_required') or g.get('redecomposition_submission') for g in s.get('module_groups', {}).values())
        global_next = {'operation': None if splitting else 'global-plan', 'role': 'global-orchestrator',
                       'ready': bool(s['modules']) and not splitting,
                       'reason': 'module-decomposition-required' if splitting else 'coverage-review-required',
                       'continue_modules': rounds['ready_modules']}
    elif rounds['all_settled'] and not audit_code_review.current(s, ref_check):
        global_next = {'operation': 'audit-code-review', 'role': 'auditor', 'ready': True,
                       'reason': 'review-whole-change-before-defects', 'snapshot': audit_code_review.snapshot(s)}
    elif audit_code_review.pending(s) or audit_closure.leftovers(s):
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
    elif tv.final_deferred_current(s) and not observed and not tv.audit_resume_context(s):
        global_next = {'operation': None, 'role': 'global-orchestrator', 'ready': False,
                       'reason': 'completed-with-unverified-tests', 'quality': 'yellow-blocked'}
    elif user_paths.unverified_only(s) and not observed:
        global_next = {'operation': None, 'role': 'global-orchestrator', 'ready': False,
                       'reason': 'completed-with-unverified-tests', 'quality': 'yellow-blocked',
                       'device_gap_cases': {mid: sorted(user_paths.gaps(m.get('plan'))) for mid, m in s['modules'].items()
                                            if user_paths.gaps(m.get('plan'))}}
    elif cursor and all(tv.available(m) for m in s['modules'].values()) and not observed:
        ready = rounds['all_settled'] and s.get('audit_attempts', 0) < workflow.audit_budget(s)
        global_next = {'operation': 'audit-assign' if rounds['all_settled'] else None, 'role': 'global-orchestrator', 'ready': ready,
                       'reason': 'await-parent-summaries' if not rounds['all_settled'] else None if ready else 'audit-budget-exhausted',
                       'continue_modules': rounds['ready_modules'],
                       'scope_policy': 'non-green-only',
                       'path_ids': [p['path_id'] for p in audit_scope(s)['plan']['paths']]}
        resume_context = tv.audit_resume_context(s)
        if ready and resume_context:
            global_next.update(reason='automation-environment-restored',
                               payload={'context_ref': resume_context,
                                        'instance_id': s['audit_code_review']['auditor_instance_id']})
    else:
        global_next = {'operation': None, 'role': 'global-orchestrator', 'ready': False, 'reason': 'module-work-remaining'}
    global_next = context_readiness.annotate(s, None, global_next)
    if global_next.get('role'):
        global_next['model_tier'] = model_routing.advise(global_next['role'], global_next.get('operation'))
    if global_next.get('operation'):
        with_card(s, None, global_next)
    if global_next.get('reason') in ('await-delivery-authorization', 'completed-with-unverified-tests'):
        import experience
        due = experience.retrospective_due(s)  # a finished run that has something to learn from says so before it is closed
        if due:
            global_next['retrospective_due'] = due
    source_step = source_changes.next_action(s)
    for step in (global_next, source_step, revision_step):
        if isinstance(step, dict):
            step['human_required'] = control_policy.human_required(step)
    return {'global_next_step': global_next, 'next_steps': cursor,
            'source_change_next_step': source_step, 'run_change_next_step': revision_step, 'module_rounds': rounds}


def status(root, view='full', module_id=None, since=None):
    root = Path(root).resolve()
    require(root.is_dir(), 'run root missing')
    with run_storage.file_lock(root / '.ledger.lock'):
        s, events = read_events(root)
        require(s, 'run not initialized')
        layout = run_storage.for_state(root, s) if s.get('project_context_ref') else None
        observed = []
        for mid, m in s['modules'].items():
            if m.get('plan'):
                try:
                    current(m, observe_worker=True)
                except (Rejected, OSError) as exc:
                    observed.append({'module_id': mid, 'reason': str(exc)})
                    m['effective_quality'] = 'yellow-blocked'
        decomposition.refresh_groups(s)
        projection = project_outcome(root, s, len(events))
        routes = routing(s, observed)
        cursor, global_next, rounds = routes['next_steps'], routes['global_next_step'], routes['module_rounds']
        progress = progress_signals.build(root, s, events, cursor, global_next)
        progress['model_usage'] = model_usage(s)
        errors = projection['errors']
        from openspec_projection import write
        from workflow_hub import materialize as hub
        hub_paths = project_attempt(errors, 'workflow-routing', lambda: hub(root, {**s, 'quality': 'yellow-blocked' if observed and s['quality'] != 'red-bug' else s['quality']},
                        len(events), routes))
        progress_signals.projection_attention(progress, errors)
        project_attempt(errors, 'workflow-attention', lambda: write(root / 'reports/workflow-attention.md', progress_signals.render(progress)))
        progress_signals.projection_attention(progress, errors)
        # Persist after human-readable outputs so observers see their failures.
        before_progress = len(errors)
        project_attempt(errors, 'progress-state', lambda: atomic(root / 'ledger/progress.json', progress))
        if len(errors) != before_progress:
            progress_signals.projection_attention(progress, errors)
            # One bounded retry records a transient write failure; permanent I/O
            # failure remains in the Host response without blocking other work.
            project_attempt(errors, 'progress-state-retry', lambda: atomic(root / 'ledger/progress.json', progress))
            progress_signals.projection_attention(progress, errors)
        projection['status'] = 'pending' if errors else 'current'
        full = {**s, 'source_change_next_step': routes['source_change_next_step'], 'run_change_next_step': routes['run_change_next_step'],
                'projection': projection,
                'run_root': str(root), 'openspec_hub': hub_paths,
                'workflow_progress': progress, 'context_requirements': context_readiness.requirements(s),
                'parent_mo_names': decomposition.parent_mo_names(s),
                'migration_report': {'json': str(root / 'reports/migration-report.json'),
                                     'markdown': str(root / 'reports/migration-report.md'), 'sequence': len(events)},
                'semantic_index': str(root / 'ledger/semantic-index.json'),
                'openspec_binding': {'bound': bool(layout),
                                     'location': 'top-level' if layout else 'in-run-fallback',
                                     'openspec_root': layout['openspec_root'] if layout else str(root / 'openspec'),
                                     'note': None if layout else 'run not bound to a prepared storage_layout; OpenSpec projects inside .sdd-runs/<run_id>/openspec, not workspace/openspec — recreate via prepare -> init(project_context_ref)'},
                'last_sequence': len(events), 'observed_invalidations': observed,
                'model_usage': model_usage(s), 'hint_adoption': hint_adoption(s), 'workflow_cost': workflow_cost.build(s, events),
                'next_steps': cursor, 'global_next_step': global_next, 'ready_modules': rounds['ready_modules'],
                'module_rounds': rounds,
                'planning_context': decomposition.planning_context(s),
                'module_inputs': {mid: decomposition.assigned_module(s, m) for mid, m in
                                  {**s.get('module_groups', {}), **s['modules']}.items()},
                'quality': 'yellow-blocked' if observed and s['quality'] != 'red-bug' else s['quality']}
        return status_view.select(full, view, module_id, since)


def advance(root, principal, module_id, workers=None):
    """Submit, as the module orchestrator, every step of one module the cursor marks mechanical: accepting a Green
    test result and dispatching a worker. Each goes through apply with all of its guards. It stops at the first step
    that needs a model or a person and renders that step's card for the dispatch."""
    applied = []
    while True:
        st = status(root)
        step = next((x for x in st['next_steps'] if x.get('module_id') == module_id), None)
        require(step is not None, 'unknown module for advance: ' + str(module_id))
        if not (step.get('mechanical') and step.get('ready')):
            break
        sequence = st['last_sequence'] + 1
        if step['operation'] == 'accept':
            payload = {'assignment_id': step['assignment_id']}
        else:
            role = step['worker_role']
            payload = {**step['payload'], 'assignment_id': f'{role}-{module_id}-{sequence}'}
            payload.setdefault('instance_id', (workers or {}).get(role) or f'{role}-{module_id}')
        ack = apply(root, {'schema_version': 1, 'request_id': f'advance-{module_id}-{sequence}', 'run_id': st['run_id'],
                           'module_id': module_id, 'expected_revision': step['expected_revision'],
                           'operation': step['operation'], 'payload': payload}, principal)
        applied.append({'operation': step['operation'], 'event_id': ack['event_id'],
                        **{k: payload[k] for k in ('assignment_id', 'role', 'instance_id', 'test_scope') if k in payload}})
    out = {'applied': applied, 'next_step': {k: step[k] for k in ('operation', 'role', 'ready', 'reason', 'assignment_id')
                                             if step.get(k) is not None}}
    if step.get('must_read'):
        out['card'] = reading.render(step['must_read'], Path(st['run_root']) / 'reports/reading', step.get('templates', ()))['path']
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'apply', 'status', 'resume', 'recover', 'history', 'advance'))
    parser.add_argument('--root', required=True)
    parser.add_argument('--request')
    parser.add_argument('--view', choices=status_view.VIEWS, default='cursor',
                        help='status only: cursor (default), step (one module with --module, else the global step), '
                             'module (needs --module) or full')
    parser.add_argument('--module')
    parser.add_argument('--since', type=int, help='status only: last_sequence already seen; an unchanged run answers briefly')
    parser.add_argument('--host-context', help='Host-protected principal JSON; CLI does not authenticate humans')
    parser.add_argument('--worker', action='append', default=[], metavar='ROLE=INSTANCE',
                        help='advance only: instance to dispatch for a role (default <role>-<module>)')
    args = parser.parse_args()
    try:
        if args.command == 'history':
            state, _ = read_events(Path(args.root).resolve())
            require(state, 'run not initialized')
            print(json.dumps(state, ensure_ascii=False, separators=(',', ':')))
            return 0
        root = Path(args.root).resolve()
        require(root.parent.name == '.sdd-runs', 'managed CLI requires .sdd-runs/<run_id>; use history for old read-only evidence')
        run_storage.layout(root.parent.parent, root.name)
        snapshot = project_context.verify_snapshot(file_ref(root / 'context/snapshot.json'))
        require(snapshot.get('storage_layout'), 'prepared storage layout required; use history for old read-only evidence')
        run_storage.validate(snapshot['storage_layout'], root, root.name)
        if args.command == 'status':
            result = status(args.root, args.view, args.module, args.since)
        elif args.command == 'advance':
            require(args.module and args.host_context, 'advance needs --module and --host-context (the module orchestrator)')
            workers = dict(item.split('=', 1) for item in args.worker)
            result = advance(args.root, read_json(args.host_context), args.module, workers)
        else:
            require(args.request and args.host_context, 'request and host context required')
            req = read_json(args.request)
            require(req.get('run_id') == root.name, 'request run_id differs from run directory')
            if req.get('operation') == 'init':
                require(req.get('payload', {}).get('project_context_ref'), 'init must bind prepared project context')
            if args.command != 'apply':
                require(req.get('operation') == args.command, 'command/operation mismatch')
            result = apply(args.root, req, read_json(args.host_context))
        print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))  # read by hosts and models, not formatted for them
        return 0
    except run_storage.LockTimeout as exc:
        print(json.dumps(exc.diagnostic, ensure_ascii=False), file=sys.stderr)
        return 1
    except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
        diagnostic = Path(args.root).resolve() / 'reports/rejected-operation.json'
        print(json.dumps({'status': 'rejected', 'reason': str(exc), 'read_hint': reading.read_hint(exc),
                          'next_action': 'read status.workflow_progress; resolve gate or escalate; do not stop unrelated modules',
                          'diagnostic_path': str(diagnostic) if diagnostic.is_file() else None}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
