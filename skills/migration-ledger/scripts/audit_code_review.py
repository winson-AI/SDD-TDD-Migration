"""Independent whole-change review before defect collection; never writes target code."""
import copy

from contracts import Rejected, baseline, check_ref, digest, keyed, nonempty, read_json, require
import workflow

CHECKS = ('changes', 'refactoring', 'redundancy', 'library-reuse', 'shared-capabilities', 'fidelity')


def snapshot(s):
    # Historical snapshots are digest values, not live code refs. Otherwise the
    # evidence walker would reject the old review precisely when Fixer changes code.
    return {**({'host_contract_sha256': digest([s.get('host_task_contract'), s['global_spec'], s['requirement_ids'], s['case_ids'], s['global_paths']])} if s.get('control_policy_version', 1) >= 2 else {}),
            **({'retirements_sha256': digest([h for h in s['run_change_history'] if h.get('retirements')])}
               if any(h.get('retirements') for h in s.get('run_change_history', [])) else {}),
            'project_context_sha256': digest(s.get('project_context_ref')),
            'global_plan_sha256': digest(s.get('global_plan')),
            'modules': {mid: {'spec_sha256': digest(m.get('plan_ref')), 'freeze_id': m.get('freeze_id'),
                'code_baseline': m.get('code_baseline'), 'manifest_sha256': digest(m.get('code_files')),
                'allocation_sha256': digest([m.get('dependencies'), m.get('write_paths')]),
                'authors': copy.deepcopy(m.get('authors'))} for mid, m in s['modules'].items()}}


def current(s, ref_check=check_ref):
    review = s.get('audit_code_review')
    if not review or not review.get('change_inventory_ref') or review['snapshot'] != snapshot(s):
        return False
    batch = s.get('audit_batch', {})
    if batch.get('code_review_ref') == review['report_ref'] and batch.get('status') in ('verified', 'completed-with-unverified-tests'):
        return False  # Even an unchanged patch needs independent governance re-review.
    try:
        ref_check(review['report_ref'])
        for ref in review['evidence_refs']:
            ref_check(ref)
        for m in s['modules'].values():
            if m.get('code_files'):
                require(baseline(m['code_files']) == m['code_baseline'], 'review code changed')
    except (Rejected, OSError):
        return False
    return True


def pending(s):
    review = s.get('audit_code_review', {})
    resolved = set()
    for batch in [*s.get('audit_batch_history', []), s.get('audit_batch', {})]:
        if batch.get('code_review_ref') == review.get('report_ref'):
            resolved.update(batch.get('resolved_findings', []))
            if batch.get('status') == 'completed-with-unverified-tests':
                # Preserve Yellow separately; unavailable automation must not trigger
                # another automatic Fixer round or block independent final review.
                resolved.update(batch.get('unverified_findings', []))
    return {f['finding_id']: copy.deepcopy(f) for f in review.get('findings', [])
            if f['finding_id'] not in resolved}


def deferred(s):
    return [{'batch_id': b['batch_id'], 'report_ref': b['code_review_ref'],
             'finding_ids': b['unverified_findings']} for b in
            [*s.get('audit_batch_history', []), s.get('audit_batch', {})]
            if b.get('code_review_ref') and b.get('unverified_findings')]


def require_current(s, auditor=None):
    require(current(s), 'independent audit-code-review required for current SPEC/code/context')
    if auditor:
        require(s['audit_code_review']['auditor_instance_id'] == auditor, 'code review Auditor identity mismatch')


def accept(s, p, actor):
    import audit_closure
    workflow.role(actor, 'auditor'); workflow.planning_guard(s)
    require(not workflow.audit_active(s) and not audit_closure.active(s), 'close active audit before code review')
    require(not audit_closure.collection_blockers(s), 'all module rounds must settle before code review')
    import prepared_tests
    require(actor['instance_id'] not in prepared_tests.global_authors(s), 'Auditor must be independent of GLOBAL script author')
    require(all(actor['instance_id'] not in m['authors'] for m in s['modules'].values()), 'Auditor must be independent')
    report = read_json(check_ref(p.get('report_ref')))
    require(report.get('schema_version') == 1 and report.get('run_id') == s['run_id'], 'code review run/schema mismatch')
    require(report.get('auditor_instance_id') == actor['instance_id'], 'code review author mismatch')
    require(report.get('snapshot') == snapshot(s), 'code review snapshot stale')
    require(report.get('modules'), 'review every execution module, including Green')
    reviews = keyed(report['modules'], 'module_id')
    require(set(reviews) == set(s['modules']), 'review every execution module, including Green')
    inventory_ref = report.get('change_inventory_ref')
    require(inventory_ref, 'audit change inventory reference required')
    check_ref(inventory_ref)
    refs = [inventory_ref]
    if s.get('control_policy_version', 1) >= 2:
        refs += goal_review(s, report)
    for mid, review in reviews.items():
        refs += nonempty(review.get('diff_refs'), 'before/after change evidence required')
        checks = review.get('checks', {})
        require(set(checks) == set(CHECKS), 'code review checks incomplete')
        for item in checks.values():
            require(item.get('conclusion') in ('satisfied', 'finding', 'not-applicable') and
                    isinstance(item.get('reason'), str) and item['reason'].strip(), 'code review conclusion/reason required')
            refs += nonempty(item.get('evidence_refs'), 'code review evidence required')
    require(isinstance(report.get('findings'), list), 'code findings list required')
    items = keyed(report['findings'], 'finding_id') if report['findings'] else {}
    for fid, finding in items.items():
        require(fid.startswith('CR-') and finding.get('source_module_id') in s['modules'], 'invalid code finding identity/source')
        require(finding.get('category') in CHECKS or (s.get('control_policy_version', 1) >= 2 and
                finding.get('category') == 'host-goal'), 'unknown code review category')
        workflow.root_cause(finding.get('root_cause'))
        refs.append(finding.get('analysis_ref'))
        affected = nonempty(finding.get('affected_module_ids'), 'affected consumers required')
        require(set(affected) <= set(s['modules']) and finding['source_module_id'] in affected, 'invalid affected modules')
        require(finding.get('path_id') is None and not finding.get('result'), 'code findings cannot fabricate test failures')
        attempts = [b for b in [*s.get('audit_batch_history', []), s.get('audit_batch', {})]
                    if b.get('code_review_ref') and fid in b.get('routes', {}) and
                    set(b['routes'][fid]['owner_module_ids']).intersection(b.get('started_owners', []))]
        finding['requires_human'] = bool(attempts) if s.get('control_policy_version', 1) < 2 else (
            len(attempts) >= s['max_no_progress_rounds'] or any(
                s['modules'][mid]['fix_rounds_used'] >= s['modules'][mid].get('fix_budget', s['max_fix_rounds'])
                for b in attempts for mid in b['routes'][fid]['owner_module_ids']))
    for mid, review in reviews.items():
        for category, item in review['checks'].items():
            require((item['conclusion'] == 'finding') == any(f['source_module_id'] == mid and f['category'] == category for f in items.values()),
                    'code review finding/check mismatch')
    removed = set(pending(s)) - set(items)
    resolutions = report.get('recovery_resolutions', [])
    require(isinstance(resolutions, list), 'recovery resolutions must be a list')
    resolutions = keyed(resolutions, 'finding_id') if resolutions else {}
    require(set(resolutions) == removed, 'cannot erase unresolved code findings; close or explicitly recover them')
    for fid, resolution in resolutions.items():
        batch = s.get('audit_batch', {})
        decision = s['decisions'].get(resolution.get('decision_id'), {})
        require(batch.get('status') == 'released' and fid in batch.get('human_issues', {}) and
                resolution.get('decision_id') == batch.get('release_decision_id') and decision.get('consumed') and
                decision.get('subject_sha256') == digest(batch['human_report']), 'recovery resolution needs released human decision')
        require(snapshot(s) != s['audit_code_review']['snapshot'], 'recovery needs a new reviewed SPEC/code baseline')
        require(isinstance(resolution.get('reason'), str) and resolution['reason'].strip(), 'recovery resolution reason required')
        refs += nonempty(resolution.get('evidence_refs'), 'recovery resolution evidence required')
    for ref in refs:
        check_ref(ref)
    for m in s['modules'].values():
        if m.get('code_files'):
            require(baseline(m['code_files']) == m['code_baseline'], 'review code evidence stale')
    if s.get('audit_code_review'):
        s.setdefault('audit_code_review_history', []).append(copy.deepcopy(s['audit_code_review']))
    s['audit_code_review'] = {'report_ref': p['report_ref'], 'snapshot': snapshot(s),
        'change_inventory_ref': inventory_ref,
        'auditor_instance_id': actor['instance_id'], 'findings': list(items.values()), 'evidence_refs': refs,
        'recovery_resolutions': list(resolutions.values())}


def goal_review(s, report):
    """Independent evidence from the original host contract, including omissions with no Red PATH."""
    goal = report.get('goal_review')
    require(isinstance(goal, dict) and goal.get('global_spec_ref') == s['global_spec'], 'whole host goal review required')
    check_ref(goal['global_spec_ref'])
    origin = s.get('host_task_contract', {}).get('global_spec') or next(iter(s.get('run_change_history', [])), {}).get('previous_global_spec', s['global_spec'])
    require(goal.get('origin_spec_ref') == origin, 'goal review must reference original host contract')
    check_ref(origin)
    rows = keyed(goal.get('requirements'), 'requirement_id')
    require(set(rows) == set(s['requirement_ids']), 'goal review must cover every active host requirement')
    inventory_ref = (s.get('global_plan') or {}).get('content', {}).get('feature_inventory_ref')
    features = {row['feature_id'] for row in read_json(check_ref(inventory_ref))['features']} if inventory_ref else set()
    require(set(goal.get('feature_ids', [])) == features, 'goal review feature coverage incomplete')
    refs = []
    import run_changes
    retired = {(r['kind'], r['id']): r for r in run_changes.retirements(s)}
    reviews = goal.get('retirement_reviews', [])
    require(isinstance(reviews, list), 'retirement reviews must be an array')
    seen = set()
    for row in reviews:
        require(isinstance(row, dict) and isinstance(row.get('kind'), str) and isinstance(row.get('id'), str),
                'retirement review identity required')
        key = (row.get('kind'), row.get('id'))
        require(key in retired and key not in seen, 'unknown/duplicate retirement review')
        seen.add(key); item = retired[key]
        require(row.get('revision_ref') == item['revision_ref'] and row.get('decision_id') == item['decision_id'],
                'retirement review must bind approved revision')
        require(row.get('conclusion') in ('confirmed', 'finding', 'blocked') and row.get('reason'),
                'retirement review conclusion/reason required')
        if row['conclusion'] != 'confirmed':
            require(any(f.get('finding_id') == row.get('finding_id') and f.get('category') == 'host-goal'
                        for f in report.get('findings', [])), 'retirement concern must enter host-goal finding closure')
        refs += [item['revision_ref'], item['human_source_ref'], item['previous_spec_ref']]
        refs += nonempty(row.get('evidence_refs'), 'retirement review evidence')
    require(seen == set(retired), 'goal review must cover every approved retirement')
    for rid, row in rows.items():
        require(row.get('conclusion') in ('satisfied', 'finding', 'blocked') and row.get('reason'), 'goal conclusion/reason required')
        refs += nonempty(row.get('evidence_refs'), 'goal review evidence')
        tasks = row.get('tasks'); paths = row.get('path_ids')
        require(isinstance(tasks, list) and isinstance(paths, list), 'goal TASK/PATH trace required')
        allowed_paths = {p['path_id'] for p in s['global_paths'] if rid in p.get('requirement_ids', [p.get('requirement_id')])}
        for task in tasks:
            m = s['modules'].get(task.get('module_id'), {})
            t = next((t for t in (m.get('plan') or {}).get('tasks', []) if t['task_id'] == task.get('task_id')), None)
            require(t and rid in t.get('global_requirement_ids', t['requirement_ids']), 'goal trace references unrelated TASK')
            allowed_paths.update(t['path_ids'])
        require(set(paths) <= allowed_paths, 'goal trace PATH outside requirement')
        if row['conclusion'] == 'satisfied':
            require(paths and (tasks or set(paths) <= {p['path_id'] for p in s['global_paths']}), 'satisfied goal has no TASK/PATH evidence')
        if row['conclusion'] in ('finding', 'blocked'):
            require(any(f.get('finding_id') == row.get('finding_id') and f.get('category') == 'host-goal'
                for f in report.get('findings', [])), 'goal omission must enter unified finding closure')
    return refs


def collection(s):
    """Governance precedes residual defects, without overwriting CASE qualities."""
    import audit_closure
    items = pending(s)
    if not items:
        return audit_closure.leftovers(s), None
    sources = {f['source_module_id']: {'results': {}, 'blocker': None, 'queue': None,
                **audit_closure.context(s['modules'][f['source_module_id']])} for f in items.values()}
    return sources, items
