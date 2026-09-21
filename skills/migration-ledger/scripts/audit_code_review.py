"""Independent whole-change review before defect collection; never writes target code."""
import copy

from contracts import Rejected, baseline, check_ref, digest, keyed, nonempty, read_json, require
import workflow

CHECKS = ('changes', 'refactoring', 'redundancy', 'library-reuse', 'shared-capabilities', 'fidelity')


def snapshot(s):
    # Historical snapshots are digest values, not live code refs. Otherwise the
    # evidence walker would reject the old review precisely when Fixer changes code.
    return {'project_context_sha256': digest(s.get('project_context_ref')),
            'global_plan_sha256': digest(s.get('global_plan')),
            'modules': {mid: {'spec_sha256': digest(m.get('plan_ref')), 'freeze_id': m.get('freeze_id'),
                'code_baseline': m.get('code_baseline'), 'manifest_sha256': digest(m.get('code_files')),
                'allocation_sha256': digest([m.get('dependencies'), m.get('write_paths')]),
                'authors': copy.deepcopy(m.get('authors'))} for mid, m in s['modules'].items()}}


def current(s):
    review = s.get('audit_code_review')
    if not review or not review.get('change_inventory_ref') or review['snapshot'] != snapshot(s):
        return False
    batch = s.get('audit_batch', {})
    if batch.get('code_review_ref') == review['report_ref'] and batch.get('status') in ('verified', 'completed-with-unverified-tests'):
        return False  # Even an unchanged patch needs independent governance re-review.
    try:
        check_ref(review['report_ref'])
        for ref in review['evidence_refs']:
            check_ref(ref)
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
        require(finding.get('category') in CHECKS, 'unknown code review category')
        workflow.root_cause(finding.get('root_cause'))
        refs.append(finding.get('analysis_ref'))
        affected = nonempty(finding.get('affected_module_ids'), 'affected consumers required')
        require(set(affected) <= set(s['modules']) and finding['source_module_id'] in affected, 'invalid affected modules')
        require(finding.get('path_id') is None and not finding.get('result'), 'code findings cannot fabricate test failures')
        finding['requires_human'] = any(b.get('code_review_ref') and fid in b.get('routes', {}) and
            set(b['routes'][fid]['owner_module_ids']).intersection(b.get('started_owners', []))
            for b in [*s.get('audit_batch_history', []), s.get('audit_batch', {})])
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


def collection(s):
    """Governance precedes residual defects, without overwriting CASE qualities."""
    import audit_closure
    items = pending(s)
    if not items:
        return audit_closure.leftovers(s), None
    sources = {f['source_module_id']: {'results': {}, 'blocker': None, 'queue': None,
                **audit_closure.context(s['modules'][f['source_module_id']])} for f in items.values()}
    return sources, items
