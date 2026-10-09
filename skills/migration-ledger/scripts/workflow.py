"""Global coverage, bounded local repair, and whole-task audit contracts."""
import copy
import re
import test_validation as tv
import dimensions

from contracts import check_ref, digest, intact, keyed, nonempty, read_json, require, baseline, validate_result, verify_plan

EXTERNAL = {'dependency', 'environment', 'tooling', 'external', 'peripheral', 'human'}
OPERATIONS = {'global-plan', 'audit-defer', 'audit-recover'}
GLOBAL_OPERATIONS = {'global-plan', 'audit-recover'}


def global_paths_check(paths, case_ids):
    require(isinstance(paths, list), 'global paths must be an array')
    if paths:
        paths = keyed(paths, 'path_id')
        require({v.get('case_id') for v in paths.values()} <= set(case_ids), 'global path case is not registered')
        for path in paths.values():
            if path.get('test_design_ref'):
                import prepared_tests
                prepared_tests.binding({'path_test_sources': {path['path_id']: {
                    'module_id': 'GLOBAL', 'freeze_id': digest(path),
                    'test_design_ref': path['test_design_ref'], 'contract_version': 1}}}, path)
            assertions = keyed(path.get('expected_assertions'), 'assertion_id')
            require(all('expected' in a for a in assertions.values()), 'global assertion expected value required')
            device_interaction = path.get('kind') in ('automation', 'visual') and path.get('interaction_id')
            if device_interaction:
                from ui_evidence import interaction_contract
                interaction = interaction_contract(path.get('frozen_interaction'))
                require(interaction['id'] == path['interaction_id'], 'GLOBAL frozen interaction ID mismatch')
            if path.get('kind') == 'visual' or device_interaction:
                binding = path.get('build_binding') or {}
                require(isinstance(binding.get('module_id'), str) and re.fullmatch(r'M[0-9]{3,}', binding['module_id'])
                        and isinstance(binding.get('path_id'), str) and binding['path_id'],
                        'GLOBAL device path requires frozen integration build_binding module_id/path_id')


def registry(s):
    return {mid: {k: m.get(k) for k in ('case_ids', 'dependencies', 'write_paths')}
            for mid, m in s['modules'].items()}


def awaits_resplit(s, module):
    """A leaf waits for its parent's re-split only when the revision reaches what it holds."""
    parent = s.get('module_groups', {}).get(module.get('parent_module_id'))
    return bool(parent and parent.get('replanning_required')
                and module['module_id'] in parent.get('replanning_children', parent['children']))


def runtime_allocations(s, module_id, planning=False):
    """Only this leaf, its actual dependency closure, and their parent allocations. While it plans, a leaf is not held
    by a provider that waits for a re-split: it needs the provider's code only when it is dispatched."""
    pending, visited = [module_id], set()
    while pending:
        mid = pending.pop()
        if mid in visited:
            continue
        visited.add(mid)
        module = s['modules'].get(mid) or s.get('module_groups', {}).get(mid)
        require(module, 'allocated module/dependency missing')
        require(mid not in s['modules'] or not awaits_resplit(s, module) or (planning and mid != module_id),
                'root allocation requires redecomposition')
        require(mid not in s['modules'] or (not module.get('decomposition_required') and not module.get('decomposition_submission')),
                'complete MO decomposition for this leaf and its dependencies before execution')
        require(not module.get('realloc_request'), 'resolve upstream allocation request before execution')
        dimensions.allocation(s, module)
        if s.get('behavior_contract_required'):
            import behavior_contract  # judged when the allocation was registered; here only drift of what it cites
            intact(lambda: behavior_contract.review(module, module.get('behavior_review')))
        parent = module.get('parent_module_id')
        if parent:
            pending.append(parent)
        if mid in s['modules']:
            pending.extend(module['dependencies'])
        else:
            check_ref(module['decomposition_ref']); check_ref(module['decomposition_review_ref'])
    return visited


def planning_guard(s, module_id=None):
    plan = s.get('global_plan')
    require(plan and plan['registry_hash'] == digest(registry(s)), 'global coverage review required')
    require(module_id or not any(m.get('decomposition_required') or m.get('decomposition_submission') for m in s['modules'].values()),
            'complete MO decomposition before implementation/audit')
    for ref in (s['global_spec'], s['new_architecture'], plan['plan_ref'], plan['review_ref']):
        check_ref(ref)
    if plan.get('source_review_ref'):
        check_ref(plan['source_review_ref'])
    if module_id:
        runtime_allocations(s, module_id)
    # Global semantic/source coverage is accepted once by global-plan. Runtime
    # dispatch must not recursively revalidate unrelated modules' source evidence.
    if plan['content'].get('feature_inventory_ref'):
        check_ref(plan['content']['feature_inventory_ref'])
    if plan.get('boundary_decision_id'):
        check_ref(s['decisions'][plan['boundary_decision_id']]['human_source_ref'])


def feature_inventory(s, plan):
    """Enforce explicit enumeration/traceability; semantic completeness is reviewed by GO."""
    ref = plan.get('feature_inventory_ref')
    if not s.get('context_readiness_required') and not ref:
        return  # The minimal low-level API can omit the feature-inventory capability.
    inventory = read_json(check_ref(ref))
    require(inventory.get('schema_version') == 1 and inventory.get('legacy_root') == s['legacy_root']
            and inventory.get('entry_mode') == s['entry_mode'], 'feature inventory scope mismatch')
    if s['entry_mode'] == 'single-module':
        require(inventory.get('single_module_id') == s['single_module_id'], 'feature inventory selected root mismatch')
    summary = inventory.get('test_summary_ref')
    require(inventory.get('source_mode') == ('test-case-summary' if summary else 'legacy-source'),
            'feature inventory must default to supplied test summary or fall back to legacy source')
    if summary:
        check_ref(summary)
    if s.get('project_context_ref'):
        supplied = read_json(check_ref(s['project_context_ref'])).get('source_refs', {}).get('test_cases_path')
        require(not supplied or summary == supplied, 'feature inventory must use supplied test case summary')
    coverage = inventory.get('coverage', {})
    require(coverage.get('status') == 'complete' and coverage.get('unclassified') == []
            and coverage.get('unresolved_questions') == [], 'feature enumeration incomplete; human clarification required')
    features = keyed(inventory.get('features'), 'feature_id')
    require(features, 'complete feature list required')
    reqs, cases = set(), set()
    for item in features.values():
        require(all(item.get(k) for k in ('name', 'functional_path', 'trigger', 'observable_result')), 'feature behavior details required')
        rids = set(nonempty(item.get('requirement_ids'), 'feature requirements'))
        cids = set(nonempty(item.get('case_ids'), 'feature cases; derive cases from source when absent'))
        require(rids <= set(s['requirement_ids']) and cids <= set(s['case_ids']), 'feature references unknown requirement/case')
        reqs.update(rids); cases.update(cids)
    require(reqs == set(s['requirement_ids']) and cases == set(s['case_ids']), 'feature inventory misses requirements/cases')
    units = keyed(inventory.get('source_units'), 'unit_id')
    require(units and any(u.get('kind') == 'legacy-entry' for u in units.values()), 'legacy entrypoint completeness review required')
    if summary:
        require(any(u.get('kind') == 'test-case-group' for u in units.values()), 'test case summary extraction required')
    mapped = set()
    for item in units.values():
        require(item.get('kind') in ('legacy-entry', 'test-case-group', 'non-functional') and item.get('locator'), 'source unit kind/location required')
        ids = item.get('feature_ids')
        require(isinstance(ids, list) and set(ids) <= set(features), 'source unit contains unknown feature')
        require(ids or (item['kind'] == 'non-functional' and item.get('reason')), 'unclassified source unit; human clarification required')
        mapped.update(ids)
    require(mapped == set(features), 'feature lacks extraction evidence mapping')
    for item in list(features.values()) + list(units.values()):
        for evidence in nonempty(item.get('evidence_refs'), 'feature/source evidence'):
            check_ref(evidence)
    owners = plan.get('feature_owners', {})
    require(set(owners) == set(features), 'every feature requires module ownership')
    for fid, mids in owners.items():
        require(mids and len(set(mids)) == len(mids) and set(mids) <= set(s['modules']), 'feature owners must be execution modules')
        for rid in features[fid]['requirement_ids']:
            require(set(mids) <= set(plan['requirement_owners'][rid]), 'feature/requirement owner mismatch')
        for cid in features[fid]['case_ids']:
            require(set(mids) <= set(plan['case_owners'][cid]), 'feature/case owner mismatch')
    require({mid for mids in owners.values() for mid in mids} == set(s['modules']), 'module missing functional list')
    questions = inventory.get('questions')
    require(isinstance(questions, list), 'explicit feature questions list required')
    issues = {item['question_id']: item for item in plan.get('boundary_review', {}).get('issues', [])}
    for question in questions:
        require(question.get('question_id') in issues and question.get('question') and
                issues[question['question_id']].get('question') == question['question'],
                'feature doubt requires human boundary review; do not omit questions')


def boundary_review(s, plan, decision_id):
    """Validate declared business-boundary questions; semantics remain agent-reviewed."""
    review = plan.get('boundary_review')
    require(isinstance(review, dict) and isinstance(review.get('issues'), list), 'boundary review required')
    issues = review['issues']
    require(all(isinstance(issue, dict) for issue in issues), 'invalid boundary issue')
    if issues:
        keyed(issues, 'question_id')
    for issue in issues:
        require(issue.get('kind') in ('cross-module', 'uncertain'), 'invalid boundary kind')
        mids = nonempty(issue.get('module_ids'), 'boundary modules')
        require(len(set(mids)) == len(mids) and set(mids) <= set(s['modules']), 'unknown/duplicate boundary module')
        require(issue.get('question') and issue.get('proposed_resolution'), 'boundary question/resolution required')
    if not issues:
        require(not decision_id, 'boundary approval without issues')
        return
    decision = s['decisions'].get(decision_id, {})
    subject = digest({'plan': plan, 'registry': registry(s)})
    require(decision.get('decision') == 'approved' and decision.get('module_id') is None
            and decision.get('subject_sha256') == subject and not decision.get('consumed', True),
            'human approval required for current business boundaries and registry')
    check_ref(decision['human_source_ref'])
    decision['consumed'] = True


def audit_active(s):
    return bool(s.get('audit_assignment') and not s['audit_assignment'].get('closed'))


def audit_locks(s, mid):
    """The host-task audit locks its run until closed or revoked."""
    if not audit_active(s):
        return False
    return True


def audit_budget(s, mid='GLOBAL'):
    return s.get('audit_budgets', {}).get(mid, s['max_audit_rounds'])


def audit_recovery_subject(s, mids, additional_rounds):
    return digest({'run_id': s['run_id'], 'module_ids': mids, 'additional_rounds': additional_rounds,
        'attempts': {mid: s.get('audit_attempts', 0) for mid in mids},
        'budgets': {mid: audit_budget(s, mid) for mid in mids}})


def audit_recovery_step(s):
    mids = []
    if s.get('audit_attempts', 0) >= audit_budget(s) and s.get('audit', {}).get('quality') != 'green-passed' \
            and s['modules'] and all(tv.available(m) for m in s['modules'].values()):
        mids.append('GLOBAL')
    if not mids:
        return None
    subject = audit_recovery_subject(s, mids, 1)
    decision = next((d for d in s['decisions'].values() if d.get('module_id') is None and not d.get('consumed')
                     and d.get('subject_sha256') == subject), None)
    return {'operation': 'audit-recover', 'role': 'global-orchestrator', 'ready': bool(decision),
            'reason': 'audit-budget-exhausted', 'approval_subject_sha256': subject,
            'payload': {'module_ids': mids, 'additional_rounds': 1, **({'decision_id': decision['decision_id']} if decision else {})}}


def role(actor, name):
    require(actor.get('role') == name and actor.get('instance_id'), 'principal role denied')


def idle(m):
    require(not any(not a.get('closed') for a in m['assignments'].values()), 'worker still active')


def root_cause(value):
    require(isinstance(value, dict) and all(value.get(k) for k in
            ('category', 'summary', 'confidence', 'owner', 'next_action')), 'structured root cause required')


def peripheral(m):
    diagnosis = m.get('diagnosis') or (m.get('diagnosis_submission') or {}).get('report', {})
    cause = diagnosis.get('root_cause')
    if isinstance(cause, dict) and cause.get('confidence') == 'confirmed':
        return cause if cause.get('category') in EXTERNAL else None
    issues = list(m.get('results', {}).values()) + list(m.get('repair_findings', {}).values())
    bad = [r for r in issues if r['quality'] != 'green-passed']
    if bad and all(r.get('root_cause', {}).get('category') in EXTERNAL and
                   r.get('root_cause', {}).get('confidence') == 'confirmed' for r in bad):
        return bad[0]['root_cause']
    return None


def variant_conflict(m):
    """Confirmed runtime-vs-SPEC variant conflict: suspend for the user, never a repair round."""
    issues = list(m.get('results', {}).values()) + list(m.get('repair_findings', {}).values())
    for r in issues:
        cause = r.get('root_cause') or {}
        if (r['quality'] != 'green-passed' and cause.get('reason_code') == 'runtime-spec-variant-conflict'
                and cause.get('confidence') == 'confirmed'):
            return cause
    return None


def defer_reason(m, local_rounds=3):
    """Defer only confirmed external blockers or exhausted cumulative repair budget."""
    if m.get('audit_fix_grant'):
        return None
    cause = peripheral(m)
    if cause:
        return cause
    used = m.get('local_fix_used', 0)
    if used >= local_rounds:
        return {'category': 'local-round-exhausted', 'summary': f'{used} local repair round(s) used',
                'confidence': 'confirmed', 'owner': 'auditor', 'next_action': 'host-task-audit'}
    return None


def runnable(s, mid):
    m = s['modules'][mid]
    try:
        require(m.get('freeze_id') and m.get('code_files'), 'code not generated/frozen')
        verify_plan(m['plan'])
        require(baseline(m['code_files']) == m['code_baseline'], 'stale code')
        for dep in m['dependencies']:
            producer = s['modules'][dep]
            require(tv.available(producer), 'dependency incomplete')
            require(baseline(producer['code_files']) == producer['code_baseline'], 'dependency stale')
        return True
    except (ValueError, OSError, KeyError, TypeError):
        return False


def handle(s, req, actor, run_root=None):
    op, p = req['operation'], req.get('payload', {})
    mid = req.get('module_id'); m = s['modules'].get(mid)
    if op == 'audit-recover':
        role(actor, 'global-orchestrator')
        mids, extra = p.get('module_ids'), p.get('additional_rounds')
        require(mids == ['GLOBAL'], 'audit recovery scope must be the whole host task: GLOBAL')
        require(type(extra) is int and 0 < extra <= 100, 'invalid additional audit budget')
        require(all((s.get('audit_attempts', 0)) >= audit_budget(s, mid)
                    for mid in mids), 'audit recovery only after budget exhaustion')
        decision = s['decisions'].get(p.get('decision_id'), {})
        require(decision.get('module_id') is None and not decision.get('consumed', True)
                and decision.get('subject_sha256') == audit_recovery_subject(s, mids, extra), 'explicit audit budget decision required')
        check_ref(decision['human_source_ref'])
        for mid in mids:
            s.setdefault('audit_budgets', {})[mid] = audit_budget(s, mid) + extra
        s.setdefault('audit_recovery_history', []).append(copy.deepcopy(p))
        decision['consumed'] = True
    elif op == 'global-plan':
        role(actor, 'global-orchestrator')
        require(s['modules'], 'no modules')
        require(not any(g.get('replanning_required') for g in s.get('module_groups', {}).values()), 'finish root redecomposition before global coverage acceptance')
        require(not audit_active(s), 'audit active')
        plan = read_json(check_ref(p.get('plan_ref')))
        check_ref(p.get('review_ref'))
        require(plan.get('global_spec', s['global_spec']) == s['global_spec'] and
                plan.get('new_architecture', s['new_architecture']) == s['new_architecture'], 'global inputs mismatch')
        check_ref(s['global_spec']); check_ref(s['new_architecture'])
        requirements = plan.get('requirement_owners', {})
        cases = plan.get('case_owners', {})
        require(set(requirements) == set(s['requirement_ids']) and set(cases) == set(s['case_ids']), 'incomplete global requirement/case coverage')
        valid = set(s['modules']) | {'GLOBAL'}
        for mapping in (requirements, cases):
            for owners in mapping.values():
                nonempty(owners, 'owners')
                require(len(set(owners)) == len(owners) and set(owners) <= valid, 'unknown/duplicate owner')
        global_cases = {path['case_id'] for path in s['global_paths']}
        for rid, owners in requirements.items():
            if 'GLOBAL' in owners:
                require(any(path.get('requirement_id') == rid or rid in path.get('requirement_ids', [])
                            for path in s['global_paths']), 'global requirement lacks test path')
        for cid, owners in cases.items():
            require('GLOBAL' not in owners or cid in global_cases, 'global case lacks test path')
            for owner in set(owners) - {'GLOBAL'}:
                require(cid in s['modules'][owner]['case_ids'], 'case owner not registered')
        for module_id, module in s['modules'].items():
            require(all(module_id in cases[cid] for cid in module['case_ids']), 'module case missing owner mapping')
            require(any(module_id in owners for owners in requirements.values()), 'module missing requirement ownership')
            if module.get('scope'):
                require({rid for rid, owners in requirements.items() if module_id in owners} ==
                        set(module['scope']['requirement_ids']), 'global ownership must match assigned submodule requirements')
        for module in {**s.get('module_groups', {}), **s['modules']}.values():
            dimensions.allocation(s, module)
        for group in s.get('module_groups', {}).values():
            check_ref(group['decomposition_ref']); check_ref(group['decomposition_review_ref'])
        feature_inventory(s, plan)
        boundary_review(s, plan, p.get('boundary_decision_id'))
        import behavior_contract
        behavior_contract.global_review(s)
        source_review = (s.get('global_plan') or {}).get('source_review_ref')
        s['global_plan'] = {**p, 'content': plan, 'registry_hash': digest(registry(s))}
        if source_review: s['global_plan']['source_review_ref'] = source_review
    elif op == 'audit-defer':
        role(actor, 'module-orchestrator'); idle(m)
        require(not audit_locks(s, mid), 'audit active')
        require(m['phase'] not in ('completed', 'waiting-auditor'), 'cannot defer completed/already queued module')
        s.get('audit_resolutions', {}).pop(mid, None)  # a new deferral is never answered by an older disposition
        root_cause(p.get('root_cause'))
        check_ref(p.get('evidence_ref'))
        if m.get('code_baseline') and m['phase'] in ('testing', 'diagnosing'):
            require(defer_reason(m, m.get('fix_budget', s['max_fix_rounds'])) or (p['root_cause']['category'] in EXTERNAL and p['root_cause']['confidence'] == 'confirmed'),
                    'repairable failure must exhaust its local budget before handoff')
        original = (m.get('blocked') or {}).get('resume_phase', m['phase'])
        s.setdefault('audit_queue', {})[mid] = {'root_cause': p['root_cause'], 'evidence_ref': p['evidence_ref'],
                                               'resume_phase': original, 'previous_blocker': m.get('blocked'),
                                               'results': copy.deepcopy(m['results'])}
        m.update(phase='waiting-auditor', blocked={'kind': 'auditor', 'resume_phase': original,
                                                 'root_cause': p['root_cause']})
