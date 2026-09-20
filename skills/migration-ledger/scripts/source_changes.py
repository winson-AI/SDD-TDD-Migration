"""GO impact review and Host append-only context revisions within an existing run."""
import copy
from pathlib import Path

from contracts import check_ref, digest, keyed, nonempty, read_json, require, verify_plan
import project_context
import reuse
import workflow

OPS = {'source-review', 'reconfigure-sources'}


def subject(s, report_ref):
    # Decisions/receipts do not change the subject; progress, allocations and findings do.
    return digest({'run_id': s['run_id'], 'context': s.get('project_context_ref'),
                   'sources': s.get('reuse_sources', []), 'modules': s['modules'],
                   'parents': s.get('module_groups', {}), 'global_plan': s.get('global_plan'),
                   'audit': {k: v for k, v in s.items() if k.startswith('audit')},
                   'report_ref': report_ref})


def validate(s, report_ref):
    require(s.get('project_context_ref'), 'source append requires a prepared run context')
    project_context.verify_snapshot(s['project_context_ref'])
    workflow.planning_guard(s)
    report = read_json(check_ref(report_ref))
    require(set(report) == {'schema_version', 'run_id', 'reuse_sources', 'catalog_ref', 'modules', 'parent_reviews'},
            'source impact report fields invalid')
    require(report['schema_version'] == 1 and report['run_id'] == s['run_id'], 'source impact run mismatch')
    sources = reuse.normalize_sources(report['reuse_sources'], s['target_root'], existing=True)
    require(sources == report['reuse_sources'], 'normalize reuse sources before review')
    old = {r['source_id']: r for r in s.get('reuse_sources', [])}
    new = {r['source_id']: r for r in sources}
    require(set(old) < set(new) and all(new[k] == v for k, v in old.items()),
            'only new source IDs may be appended; old sources are immutable')
    data, caps = reuse.catalog(report['catalog_ref'], reuse.sources({**s, 'reuse_sources': sources}))
    require(data['schema_version'] == 2, 'source review requires explicit provider ownership')
    reuse.validate_owners(caps, s['modules'])
    rows = keyed(report['modules'], 'module_id')
    require(set(rows) == set(s['modules']), 'source impact must review every leaf including new implementation routes')
    affected = set()
    for mid, row in rows.items():
        require(set(row) == {'module_id', 'action', 'reason', 'evidence_refs', 'resume_blocker_sha256'}, 'invalid source impact row')
        require(row['action'] in ('replan', 'unchanged') and row['reason'], 'source impact action/reason required')
        for ref in nonempty(row['evidence_refs'], 'source impact evidence'): check_ref(ref)
        m = s['modules'][mid]
        if row['action'] == 'replan':
            affected.add(mid)
        else:
            require(m.get('freeze_id') and m.get('plan'), 'unfrozen modules must plan against new sources')
            verify_plan(m['plan'])
            require(not row['resume_blocker_sha256'], 'unchanged module cannot release a blocker')
        if row['resume_blocker_sha256']:
            require(m.get('blocked') and row['resume_blocker_sha256'] == digest(m['blocked']), 'source blocker decision stale')
    for mid, m in s['modules'].items():
        require(not affected.intersection(m['dependencies']) or mid in affected, 'source impact must include dependent closure')
    parents = report['parent_reviews']
    require(isinstance(parents, dict) and set(parents) == set(s.get('module_groups', {})), 'all parent allocations must be reviewed')
    for ref in parents.values(): check_ref(ref)
    return report, affected


def handle(root, s, req, actor):
    from ledger import reset_plan
    p = req['payload']
    if req['operation'] == 'source-review':
        workflow.role(actor, 'global-orchestrator')
        require(set(p) <= {'report_ref', 'context_ref'} and p.get('report_ref'), 'invalid source review payload')
        validate(s, p['report_ref'])
        s['source_change_review'] = {'report_ref': p['report_ref'], 'subject_sha256': subject(s, p['report_ref']),
                                     'reviewed_by': actor, 'status': 'reviewed'}
        return
    workflow.role(actor, 'host')
    require(set(p) == {'decision_id', 'subject_sha256'}, 'source append cannot change other run configuration')
    review = s.get('source_change_review', {})
    require(review.get('status') == 'reviewed', 'GO source review required')
    require(review['subject_sha256'] == p['subject_sha256'] == subject(s, review['report_ref']), 'source impact review stale')
    report, affected = validate(s, review['report_ref'])
    require(not any(not a.get('closed') for m in s['modules'].values() for a in m['assignments'].values()),
            'finish or stop/revoke workers before context switch; do not cancel unrelated modules')
    decision = s['decisions'].get(p['decision_id'], {})
    require(decision.get('decision') == 'approved' and decision.get('module_id') is None
            and decision.get('subject_sha256') == p['subject_sha256'] and not decision.get('consumed', True),
            'source append requires approval bound to exact impact and blockers')
    check_ref(decision['human_source_ref'])
    old_ref = s['project_context_ref']
    snapshot = copy.deepcopy(project_context.verify_snapshot(old_ref))
    require(Path(snapshot['run_root']).resolve() == root.resolve() and snapshot['run_id'] == s['run_id'], 'context belongs to another run')
    snapshot['effective_config']['reuse_sources'] = report['reuse_sources']
    snapshot.update(previous_context_ref=old_ref, source_change_ref=review['report_ref'],
                    source_decision_ref=decision['human_source_ref'], source_subject_sha256=p['subject_sha256'])
    data = project_context.encoded(snapshot)
    project_context.archive(root / 'context/files', data, '.snapshot')
    new_ref = project_context.archive(root / 'context/revisions', data, '.json')
    rows = {row['module_id']: row for row in report['modules']}
    for mid, m in s['modules'].items():
        if mid in affected:
            blocker = copy.deepcopy(m.get('blocked'))
            old_phase = m['phase']
            reset_plan(m, reason='reuse-source-added', evidence_ref=review['report_ref'])
            # Results/findings/repair budgets remain live history for mandatory retest.
            if blocker and not rows[mid]['resume_blocker_sha256']:
                m['blocked'] = {**blocker, 'resume_phase': 'specifying'}
                m['phase'] = old_phase
            m.pop('approved_envelope', None); m.pop('approved_acceptance', None)
            s.get('audit_resolutions', {}).pop(mid, None)
            m['revision'] += 1
        else:
            # Only reviewed source/context fields may differ from this frozen plan.
            m['source_context_continuation'] = {'plan_hash': m['plan_hash'], 'context_ref': new_ref,
                                                'review_ref': review['report_ref']}
            m['revision'] += 1
        m.pop('context_acceptances', None)
    for group in s.get('module_groups', {}).values():
        from decomposition import leaves
        if affected.intersection(leaves(s, group['module_id'])):
            group.pop('summary_ref', None); group.pop('summary_subject', None)
            group['revision'] += 1
    # Parent acceptance is never synthesized: changed leaf revisions require each
    # parent to submit its own fresh summary, even when child Green was retained.
    s.setdefault('source_change_history', []).append({**copy.deepcopy(review), 'previous_context_ref': old_ref,
        'project_context_ref': new_ref, 'decision_id': p['decision_id'], 'affected_modules': sorted(affected)})
    s['project_context_ref'] = new_ref
    s['reuse_sources'] = report['reuse_sources']; s['reuse_required'] = True
    # GO already reviewed the complete, unchanged allocation in this transaction.
    s['global_plan']['source_review_ref'] = review['report_ref']
    s['context_acceptances'] = {}
    if s.get('audit'):
        s.setdefault('audit_history', []).append(copy.deepcopy(s['audit']))
        s['audit'] = {}
    decision['consumed'] = True
    review.update(status='applied', project_context_ref=new_ref, affected_modules=sorted(affected))


def next_action(s):
    review = s.get('source_change_review')
    if not review or review.get('status') != 'reviewed': return None
    current = review['subject_sha256'] == subject(s, review['report_ref'])
    decisions = [d for d in s['decisions'].values() if d.get('module_id') is None and not d.get('consumed')
                 and d.get('subject_sha256') == review['subject_sha256']]
    busy = any(not a.get('closed') for m in s['modules'].values() for a in m['assignments'].values())
    import audit_closure
    auditing = workflow.audit_active(s) or audit_closure.active(s)
    return {'operation': 'reconfigure-sources' if current else 'source-review',
            'role': 'host' if current else 'global-orchestrator', 'ready': current and bool(decisions) and not busy and not auditing,
            'reason': 'source-approval-required' if current and not decisions else 'source-review-stale' if not current
                      else 'wait-for-workers' if busy else 'wait-for-audit' if auditing else 'source-context-switch-ready',
            'subject_sha256': review['subject_sha256'], 'report_ref': review['report_ref'],
            'payload': {'decision_id': decisions[0]['decision_id'], 'subject_sha256': review['subject_sha256']} if decisions else {}}
