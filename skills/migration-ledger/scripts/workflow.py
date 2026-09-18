"""Global coverage, one-round repair policy, and independent problem audit contracts."""
import copy

from contracts import check_ref, digest, keyed, nonempty, read_json, require, baseline, validate_result, verify_plan

EXTERNAL = {'dependency', 'environment', 'tooling', 'external', 'peripheral', 'human'}
OPERATIONS = {'global-plan', 'audit-defer', 'problem-assign', 'problem-audit', 'audit-resume'}
GLOBAL_OPERATIONS = {'global-plan', 'problem-assign', 'problem-audit'}


def registry(s):
    return {mid: {k: m.get(k) for k in ('case_ids', 'dependencies', 'write_paths')}
            for mid, m in s['modules'].items()}


def planning_guard(s):
    plan = s.get('global_plan')
    require(plan and plan['registry_hash'] == digest(registry(s)), 'global coverage review required')
    require(not any(m.get('decomposition_required') or m.get('decomposition_submission') for m in s['modules'].values()),
            'complete MO decomposition before implementation/audit')
    for group in s.get('module_groups', {}).values():
        check_ref(group['decomposition_ref']); check_ref(group['decomposition_review_ref'])
    for ref in (s['global_spec'], s['new_architecture'], plan['plan_ref'], plan['review_ref']):
        check_ref(ref)
    if plan['content'].get('feature_inventory_ref'):
        inventory = read_json(check_ref(plan['content']['feature_inventory_ref']))
        for item in inventory['features'] + inventory['source_units']:
            for ref in item['evidence_refs']:
                check_ref(ref)
        if inventory.get('test_summary_ref'):
            check_ref(inventory['test_summary_ref'])
    if plan.get('boundary_decision_id'):
        check_ref(s['decisions'][plan['boundary_decision_id']]['human_source_ref'])


def feature_inventory(s, plan):
    """Enforce explicit enumeration/traceability; semantic completeness is reviewed by GO."""
    ref = plan.get('feature_inventory_ref')
    if not s.get('context_readiness_required') and not ref:
        return  # Existing runs retain their original coverage contract.
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


def defer_reason(m):
    if m.get('audit_fix_grant'):
        return None
    cause = peripheral(m)
    if cause:
        return cause
    if (m.get('local_fix_used', 0) >= 1 or m.get('auditor_fix_used')) and not m.get('audit_fix_grant'):
        return {'category': 'local-round-exhausted', 'summary': 'one local repair round used',
                'confidence': 'confirmed', 'owner': 'auditor', 'next_action': 'problem-audit'}
    return None


def problem_snapshot(s, mids):
    return digest({mid: {k: m.get(k) for k in ('revision', 'phase', 'freeze_id', 'code_baseline', 'blocked', 'results')}
                   for mid, m in s['modules'].items() if mid in mids})


def runnable(s, mid):
    m = s['modules'][mid]
    try:
        require(m.get('freeze_id') and m.get('code_files'), 'code not generated/frozen')
        verify_plan(m['plan'])
        require(baseline(m['code_files']) == m['code_baseline'], 'stale code')
        for dep in m['dependencies']:
            producer = s['modules'][dep]
            require(producer['phase'] == 'completed' and not producer['stale'], 'dependency incomplete')
            require(baseline(producer['code_files']) == producer['code_baseline'], 'dependency stale')
        return True
    except (ValueError, OSError, KeyError, TypeError):
        return False


def problem_assignment(s, mid):
    a = s.get('audit_assignment', {})
    require(a.get('mode') == 'problem' and not a.get('closed') and mid in a['module_ids'], 'problem audit assignment required')
    require(a['snapshot'] == problem_snapshot(s, a['module_ids']), 'problem audit snapshot stale')
    return {**a, 'module_id': mid}


def handle(s, req, actor):
    op, p = req['operation'], req.get('payload', {})
    mid = req.get('module_id'); m = s['modules'].get(mid)
    if op == 'global-plan':
        role(actor, 'global-orchestrator')
        require(s['modules'], 'no modules')
        require(not any(m.get('decomposition_required') or m.get('decomposition_submission') for m in s['modules'].values()),
                'complete MO decomposition before global coverage acceptance')
        require(not audit_active(s), 'audit active')
        plan = read_json(check_ref(p.get('plan_ref')))
        check_ref(p.get('review_ref'))
        require(plan.get('global_spec') == s['global_spec'] and plan.get('new_architecture') == s['new_architecture'], 'global inputs mismatch')
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
            if module.get('parent_module_id'):
                require({rid for rid, owners in requirements.items() if module_id in owners} ==
                        set(module['scope']['requirement_ids']), 'global ownership must match assigned submodule requirements')
        feature_inventory(s, plan)
        boundary_review(s, plan, p.get('boundary_decision_id'))
        s['global_plan'] = {**p, 'content': plan, 'registry_hash': digest(registry(s))}
    elif op == 'audit-defer':
        role(actor, 'module-orchestrator'); idle(m)
        require(not audit_active(s), 'audit active')
        require(m['phase'] not in ('completed', 'waiting-auditor'), 'cannot defer completed/already queued module')
        root_cause(p.get('root_cause'))
        check_ref(p.get('evidence_ref'))
        if m.get('code_baseline') and m['phase'] in ('testing', 'diagnosing'):
            require(defer_reason(m) or (p['root_cause']['category'] in EXTERNAL and p['root_cause']['confidence'] == 'confirmed'),
                    'repairable failure must receive one local repair round before handoff')
        original = (m.get('blocked') or {}).get('resume_phase', m['phase'])
        s.setdefault('audit_queue', {})[mid] = {'root_cause': p['root_cause'], 'evidence_ref': p['evidence_ref'],
                                               'resume_phase': original, 'previous_blocker': m.get('blocked'),
                                               'results': copy.deepcopy(m['results'])}
        m.update(phase='waiting-auditor', blocked={'kind': 'auditor', 'resume_phase': original,
                                                 'root_cause': p['root_cause']})
    elif op == 'problem-assign':
        role(actor, 'global-orchestrator'); planning_guard(s)
        require(not audit_active(s), 'audit already active')
        from audit_closure import collection_blockers
        require(not collection_blockers(s), 'all module rounds must settle before Auditor')
        for mod in s['modules'].values(): idle(mod)
        mids = p.get('module_ids', list(s.get('audit_queue', {})))
        require(mids and len(set(mids)) == len(mids) and set(mids) <= set(s.get('audit_queue', {})), 'queued modules required')
        require(p.get('assignment_id') and p.get('instance_id'), 'audit identity required')
        require(p['assignment_id'] not in s.get('audit_assignment_ids', []), 'audit assignment id already used')
        require(all(p['instance_id'] not in mod['authors'] for mod in s['modules'].values()), 'Auditor must be independent')
        require(s.get('problem_attempts', 0) < s['max_audit_rounds'], 'problem audit budget exhausted')
        s['problem_attempts'] = s.get('problem_attempts', 0) + 1
        s.setdefault('audit_assignment_ids', []).append(p['assignment_id'])
        s['audit_assignment'] = {**p, 'role': 'auditor', 'mode': 'problem', 'module_ids': mids,
                                 'run_id': s['run_id'], 'closed': False, 'snapshot': problem_snapshot(s, mids)}
    elif op == 'problem-audit':
        role(actor, 'auditor')
        a = s.get('audit_assignment', {})
        require(a.get('mode') == 'problem' and not a.get('closed') and a['instance_id'] == actor['instance_id'], 'problem auditor mismatch')
        require(a['snapshot'] == problem_snapshot(s, a['module_ids']), 'problem audit snapshot stale')
        report = read_json(check_ref(p.get('report_ref')))
        require(report.get('assignment_id') == a['assignment_id'] and report.get('snapshot') == a['snapshot'], 'problem report snapshot mismatch')
        entries = keyed(report.get('modules'), 'module_id')
        require(set(entries) == set(a['module_ids']), 'problem report must account for every queued module')
        for module_id, entry in entries.items():
            module = s['modules'][module_id]
            action = entry.get('action')
            require(action in ('retry', 'fix', 'change', 'wait', 'human'), 'unknown auditor disposition')
            root_cause(entry.get('root_cause'))
            result = entry.get('result')
            if runnable(s, module_id):
                require(result, 'runnable module requires independent retest')
                scope = copy.deepcopy(module)
                scope['results'] = s.get('problem_results', {}).get(module_id, module['results'])
                validate_result(result, scope, problem_assignment(s, module_id))
                s.setdefault('problem_results', {})[module_id] = {r['path_id']: r for r in result['paths']}
                all_green = all(r['quality'] == 'green-passed' for r in result['paths'])
                require(not all_green or action == 'retry', 'independent Green requires Main confirmation')
                require(action != 'retry' or all_green, 'retry disposition requires independent Green')
            else:
                require(result is None and entry.get('quality') == 'yellow-blocked', 'unrunnable module must remain Yellow')
                require(action in ('wait', 'human', 'change'), 'cannot fix or pass code without valid baseline')
            s.setdefault('audit_resolutions', {})[module_id] = {**entry, 'report_ref': p['report_ref'],
                                                              'assignment_id': a['assignment_id']}
        s['problem_report'] = p['report_ref']
        a['closed'] = True
    elif op == 'audit-resume':
        role(actor, 'module-orchestrator'); idle(m)
        require(not audit_active(s), 'audit active')
        resolution = s.get('audit_resolutions', {}).get(mid)
        require(m['phase'] == 'waiting-auditor' and resolution, 'auditor disposition required')
        check_ref(resolution['report_ref'])
        action = resolution['action']
        require(action != 'wait', 'Auditor kept module queued; re-audit after prerequisite changes')
        if action == 'human':
            require(p.get('decision_id') in s['decisions'], 'human decision required')
            d = s['decisions'][p['decision_id']]
            require(not d['consumed'] and d.get('module_id') == mid and d['subject_sha256'] == digest(resolution), 'human disposition approval stale')
            d['consumed'] = True
        if action in ('retry', 'fix'):
            require(runnable(s, mid), 'module baseline/dependencies unavailable')
        if action == 'fix':
            m.update(phase='diagnosing', blocked=None, stale=False,
                     diagnosis={'diagnosis_ref': resolution['report_ref'], 'root_cause': resolution['root_cause'], 'owner': mid},
                     audit_fix_grant=resolution['assignment_id'])
            m['repair_findings'] = {r['path_id']: r for r in resolution['result']['paths'] if r['quality'] != 'green-passed'}
        elif action == 'retry':
            m.update(phase='testing', blocked=None, stale=True)
        else:
            # Contract changes and human resolutions re-enter planning; never approve new acceptance implicitly.
            m.update(phase='specifying', blocked=None, stale=True, freeze_id=None, code_files=[], code_baseline=None)
            m.pop('approved_envelope', None); m.pop('approved_acceptance', None)
        del s['audit_queue'][mid]
        del s['audit_resolutions'][mid]
