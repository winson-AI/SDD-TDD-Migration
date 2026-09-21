"""Version-bound, role-specific context receipts; no new business state machine."""
import copy
from pathlib import Path

from contracts import Rejected, check_ref, digest, nonempty, read_json, require
import decomposition


CHECKS = {
    'global-discovery': ('global-inputs', 'feature-inventory', 'source-target', 'architecture-knowledge', 'reuse-sources', 'host-capabilities'),
    'global-planning': ('global-inputs', 'feature-inventory', 'allocation-coverage', 'interfaces-ownership', 'reuse-sources'),
    'decomposition': ('global-inputs', 'feature-inventory', 'assigned-scope', 'source-target', 'interfaces-ownership', 'reuse-sources'),
    'planning': ('global-inputs', 'feature-inventory', 'assigned-scope', 'source-closure', 'target-feasibility', 'interfaces-ownership', 'test-design', 'reuse-mapping'),
    'coding': ('frozen-spec', 'task-trace', 'source-closure', 'target-feasibility', 'interfaces-ownership', 'reuse-mapping', 'permissions-tools'),
    'building': ('frozen-spec', 'accepted-code', 'build-command', 'build-environment', 'permissions-tools'),
    'testing': ('frozen-spec', 'test-paths', 'accepted-code', 'provider-binding', 'test-environment', 'permissions-tools'),
    'fixing': ('frozen-spec', 'task-trace', 'interfaces-ownership', 'reuse-mapping', 'failure-diagnosis', 'repair-history', 'permissions-tools'),
    'audit-analysis': ('module-summaries', 'findings', 'spec-paths', 'dependency-owners', 'reuse-mapping', 'independence'),
    'audit-code-review': ('module-summaries', 'whole-change-diff', 'spec-paths', 'dependency-owners', 'reuse-mapping', 'shared-capabilities', 'fidelity', 'independence'),
    'audit-testing': ('module-summaries', 'spec-paths', 'accepted-code', 'provider-binding', 'test-environment', 'independence'),
    'audit-verdict': ('module-summaries', 'findings', 'spec-paths', 'verification-results', 'independence'),
}
ROLES = {stage: ('auditor' if stage.startswith('audit-') else
                 'global-orchestrator' if stage.startswith('global-') else
                 {'decomposition': 'module-orchestrator', 'planning': 'spec-designer',
                  'coding': 'implementer', 'building': 'test-runner', 'testing': 'test-runner', 'fixing': 'fixer'}[stage])
         for stage in CHECKS}
GLOBAL = {stage for stage in CHECKS if stage.startswith(('global-', 'audit-'))}
WORKERS = {'implementer': 'coding', 'test-runner': 'testing', 'fixer': 'fixing'}


def enabled(s):
    return s.get('context_readiness_required', False)


def scope(s, mid):
    return s if mid is None else s['modules'].get(mid) or s.get('module_groups', {})[mid]


def subject(s, mid, stage):
    """Do not bind sibling progress or receipt revisions into a leaf receipt."""
    require(stage in CHECKS and ((mid is None) == (stage in GLOBAL)), 'context stage/scope mismatch')
    shared = decomposition.planning_context(s)
    if stage == 'global-discovery':
        shared = {k: v for k, v in shared.items() if k not in ('modules', 'parents', 'dimension_allocations')}
    value = {'run_id': s['run_id'], 'module_id': mid, 'stage': stage, 'planning_context': shared}
    if mid:
        m = scope(s, mid)
        value['assigned_module'] = decomposition.assigned_module(s, m)
        if stage in set(WORKERS.values()) | {'building'}:
            value['execution'] = {k: m.get(k) for k in (
                'plan_ref', 'freeze_id', 'code_baseline', 'recovery_cycle', 'diagnosis',
                'results', 'repair_findings', 'fix_memory', 'local_fix_used', 'audit_fix_grant')}
            value['dependencies'] = {d: {k: s['modules'][d].get(k) for k in ('freeze_id', 'code_baseline', 'stale', 'phase')}
                                     for d in m['dependencies']}
    elif stage.startswith('audit-'):
        value['modules'] = {mid: {k: m.get(k) for k in (
            'plan_ref', 'freeze_id', 'code_baseline', 'results', 'blocked', 'phase', 'stale', 'authors')}
                           for mid, m in s['modules'].items()}
        value['summaries'] = {mid: {k: g.get(k) for k in ('summary_ref', 'summary_subject')}
                              for mid, g in s.get('module_groups', {}).items()}
        value['audit_batch'] = s.get('audit_batch')
        value['audit_queue'] = s.get('audit_queue')
        value['global_paths'] = s['global_paths']
        value['audit_assignment'] = s.get('audit_assignment')
        value['audit_code_review'] = s.get('audit_code_review')
    return digest(value)


def verify_refs(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            check_ref(value)
        for item in value.values():
            verify_refs(item)
    elif isinstance(value, list):
        for item in value:
            verify_refs(item)


def input_refs(s, mid, stage):
    refs = [s['global_spec'], s['new_architecture']]
    if (s.get('global_plan') or {}).get('source_review_ref'):
        change_ref = s['global_plan']['source_review_ref']
        refs += [change_ref, read_json(check_ref(change_ref))['catalog_ref']]
    inventory = (s.get('global_plan') or {}).get('content', {}).get('feature_inventory_ref')
    if inventory:
        refs.append(inventory)
    if s.get('project_context_ref'):
        refs.append(s['project_context_ref'])
        for source in read_json(check_ref(s['project_context_ref'])).get('source_refs', {}).values():
            refs.extend(source if isinstance(source, list) else [source])
    if mid:
        m = scope(s, mid)
        refs += m.get('context_refs', [])
        if m.get('dimension_analysis_ref'):
            refs.append(m['dimension_analysis_ref'])
        parent = decomposition.assigned_module(s, m).get('parent_context')
        if parent:
            refs += parent['context_refs']
            if parent.get('dimension_analysis_ref'):
                refs.append(parent['dimension_analysis_ref'])
        if stage in set(WORKERS.values()) | {'building'} and m.get('plan_ref'):
            refs.append(m['plan_ref'])
            if m['plan'].get('reuse_plan_ref'):
                refs.append(m['plan']['reuse_plan_ref'])
    elif stage.startswith('audit-'):
        refs += [m['dimension_analysis_ref'] for m in s['modules'].values() if m.get('dimension_analysis_ref')]
        refs += [m['plan_ref'] for m in s['modules'].values() if m.get('plan_ref')]
        refs += [g['summary_ref'] for g in s.get('module_groups', {}).values() if g.get('summary_ref')]
        refs += [m['plan']['reuse_plan_ref'] for m in s['modules'].values() if (m.get('plan') or {}).get('reuse_plan_ref')]
        if stage != 'audit-code-review' and s.get('audit_code_review'):
            refs.append(s['audit_code_review']['report_ref'])
    if stage == 'global-planning':
        refs += list(decomposition.planning_context(s).get('dimension_allocations', {}).values())
    return list({(ref['path'], ref['sha256']): ref for ref in refs}.values())


def submit(s, req, actor):
    p, mid = req['payload'], req.get('module_id')
    report = read_json(check_ref(p.get('report_ref')))
    stage = report.get('stage')
    require(stage in CHECKS and actor.get('role') == ROLES[stage] and actor.get('instance_id'), 'context producer role denied')
    require(report.get('schema_version') == 1 and report.get('run_id') == s['run_id'] and report.get('module_id') == mid,
            'context report run/module mismatch')
    require(report.get('producer') == actor, 'context producer identity mismatch')
    require(report.get('subject_sha256') == subject(s, mid, stage), 'context subject stale')
    if stage.startswith('audit-'):
        import audit_closure
        if not audit_closure.active(s):
            require(not audit_closure.collection_blockers(s), 'all module rounds must settle before Auditor context review')
        require(all(actor['instance_id'] not in m['authors'] for m in s['modules'].values()), 'Auditor must be independent')
        if s.get('audit_batch', {}).get('status') not in (None, 'released', 'verified', 'completed-with-unverified-tests'):
            require(actor['instance_id'] == s['audit_batch']['auditor_instance_id'], 'context auditor mismatch')
    checks = report.get('checks')
    require(isinstance(checks, dict) and set(checks) == set(CHECKS[stage]), 'context checklist incomplete/unknown')
    for name, item in checks.items():
        require(isinstance(item, dict) and item.get('status') in ('ready', 'blocked'), 'invalid context check: ' + name)
        require(isinstance(item.get('summary'), str) and item['summary'].strip(), 'context understanding summary required: ' + name)
        if item['status'] == 'ready':
            for ref in nonempty(item.get('evidence_refs'), 'context evidence: ' + name):
                check_ref(ref)
        else:
            require(item.get('missing') and item.get('next_action') and item.get('owner'), 'context blocker needs missing/owner/next_action')
    require(report.get('verdict') == ('blocked' if any(c['status'] == 'blocked' for c in checks.values()) else 'ready'),
            'context verdict disagrees with checks')
    if report['verdict'] == 'ready':
        reads = report.get('read_refs', [])
        require(all(ref in reads for ref in input_refs(s, mid, stage)), 'context mandatory input not acknowledged')
        if report.get('draft_ref'):
            require(report['draft_ref'] in reads, 'context draft not acknowledged')
        if stage in ('building', 'testing', 'audit-testing'):
            execution = report.get('execution', {})
            argv = execution.get('argv')
            require(isinstance(argv, list) and argv and all(isinstance(arg, str) for arg in argv)
                    and Path(argv[0]).is_absolute(), 'context approved test argv required')
            require(Path(execution.get('cwd', '')).is_absolute() and Path(execution['cwd']).is_dir(), 'context test cwd missing')
            check_ref(execution.get('environment_ref'))
    verify_refs(report)
    # Most recent receipt for this role instance wins; an old ready report cannot
    # bypass a newer missing-context report from the same instance.
    key = stage + ':' + actor['instance_id']
    scope(s, mid).setdefault('context_receipts', {})[key] = {
        'report_ref': copy.deepcopy(p['report_ref']), 'report': report}


def requirement(op, p, s=None):
    if op == 'audit-assign' and s is not None:
        from ledger import audit_scope
        return 'audit-testing' if audit_scope(s)['plan']['paths'] else 'audit-verdict'
    if op == 'assign':
        return 'building' if p.get('role') == 'test-runner' and p.get('test_scope') == 'build' else WORKERS.get(p.get('role'))
    return {'register': 'global-discovery', 'global-plan': 'global-planning', 'source-review': 'global-planning',
            'decompose': 'decomposition', 'decompose-accept': 'decomposition',
            'plan': 'planning', 'freeze': 'planning', 'audit-plan': 'audit-analysis', 'audit-code-review': 'audit-code-review',
            'audit-assign': 'audit-testing', 'problem-assign': 'audit-testing',
            'audit-verdict': 'audit-verdict'}.get(op)


def validate(s, mid, stage, ref, instance=None, draft=None, allow_blocked=False):
    report = read_json(check_ref(ref))
    require(report.get('stage') == stage, 'wrong context stage')
    producer = report.get('producer', {})
    require(producer.get('role') == ROLES[stage], 'wrong context producer role')
    require(instance is None or producer.get('instance_id') == instance, 'context receipt belongs to another worker')
    receipt = scope(s, mid).get('context_receipts', {}).get(stage + ':' + producer.get('instance_id', ''))
    require(receipt and receipt['report_ref'] == ref and receipt['report'] == report, 'context receipt not submitted/current')
    require(report['subject_sha256'] == subject(s, mid, stage), 'context subject stale; re-read and resubmit')
    require(report['verdict'] == 'ready' or allow_blocked, 'context blocked; record suspension or resolve missing inputs')
    if draft:
        require(report.get('draft_ref') == draft, 'context report must bind the reviewed draft')
    verify_refs(report)
    return report


def gate(s, req, actor):
    """Existing owner action accepts the read-only preflight; no extra human approval."""
    if not enabled(s):
        return
    op, p, mid = req['operation'], req.get('payload', {}), req.get('module_id')
    stage = requirement(op, p, s)
    if not stage:
        return
    obj = scope(s, mid)
    ref = p.get('context_ref')
    if op in ('freeze', 'decompose-accept'):
        ref = obj.get('context_acceptances', {}).get('plan' if op == 'freeze' else 'decompose', {}).get('report_ref')
    require(ref, 'context readiness receipt required for ' + op)
    instance = p.get('instance_id') if op in ('assign', 'audit-assign', 'problem-assign') else None
    if op in ('register', 'global-plan', 'decompose', 'plan', 'audit-plan', 'audit-verdict', 'source-review', 'audit-code-review'):
        instance = actor['instance_id']
    draft = p.get('plan_ref') if op in ('global-plan', 'decompose', 'plan', 'audit-plan') else obj.get('plan_ref') if op == 'freeze' else None
    if op in ('source-review', 'audit-code-review'): draft = p.get('report_ref')
    validate(s, mid, stage, ref, instance, draft)
    obj.setdefault('context_acceptances', {})[op] = {'report_ref': copy.deepcopy(ref), 'accepted_by': copy.deepcopy(actor)}


def requirements(s):
    """Read-only host API; receipts never authorize execution without owner gates."""
    if not enabled(s):
        return {}
    result = {}
    for mid in [None, *s['modules']]:
        stages = GLOBAL if mid is None else ('decomposition',) if s['modules'][mid].get('decomposition_required') else ('planning', 'coding', 'building', 'testing', 'fixing')
        result[mid or 'GLOBAL'] = {stage: {'subject_sha256': subject(s, mid, stage),
            'producer_role': ROLES[stage], 'required_checks': list(CHECKS[stage]),
            'required_input_refs': input_refs(s, mid, stage)} for stage in sorted(stages)}
    return result


def annotate(s, mid, step):
    stage = requirement(step.get('operation'), {'role': step.get('worker_role'), 'test_scope': step.get('test_scope')}, s)
    if not enabled(s) or not stage:
        return step
    step = copy.deepcopy(step)
    step['context_gate'] = {'stage': stage, 'producer_role': ROLES[stage],
                            'subject_sha256': subject(s, mid, stage), 'required_checks': list(CHECKS[stage])}
    available = []
    accepted = None
    if step.get('operation') in ('freeze', 'decompose-accept'):
        original = 'plan' if step['operation'] == 'freeze' else 'decompose'
        accepted = scope(s, mid).get('context_acceptances', {}).get(original, {}).get('report_ref')
    for receipt in scope(s, mid).get('context_receipts', {}).values():
        if receipt['report']['stage'] != stage:
            continue
        if step.get('operation') in ('freeze', 'decompose-accept') and receipt['report_ref'] != accepted:
            continue
        try:
            validate(s, mid, stage, receipt['report_ref'])
            available.append(receipt['report_ref'])
        except (Rejected, OSError, ValueError):
            pass
    step['context_gate']['ready_receipts'] = available
    if step.get('ready') and not available:
        if stage in ('testing', 'audit-testing'):
            import test_validation as tv
            for receipt in scope(s, mid).get('context_receipts', {}).values():
                ref = receipt['report_ref']
                try:
                    tv.blocked_report(s, mid, ref, stage)
                    if mid:
                        require(tv.build_ready(s['modules'][mid]), 'build not ready')
                        require(not any(r['quality'] == 'red-bug' and r.get('code_baseline', s['modules'][mid]['code_baseline']) == s['modules'][mid]['code_baseline']
                                        for r in s['modules'][mid]['results'].values()), 'observed failure')
                    step.update(operation='automation-unavailable' if mid else 'audit-unavailable',
                                role='module-orchestrator' if mid else 'auditor', ready=True,
                                payload={'context_ref': ref}, reason='record-automation-not-run-and-continue')
                    return step
                except (Rejected, OSError, ValueError):
                    pass
        step.update(ready=False, reason='context-readiness-required', context_next_action='context-submit or record explicit blocker')
        if step.get('operation') in ('freeze', 'decompose-accept'):
            step['context_next_action'] = 'refresh context-submit and resubmit plan/decompose, or record explicit blocker'
    return step


def check_execution(s, assignment, argv, cwd, path_id=None):
    if not enabled(s):
        return
    report = read_json(check_ref(assignment.get('context_ref')))
    require(report['stage'] in ('building', 'testing', 'audit-testing') and report['verdict'] == 'ready', 'test context missing')
    verify_refs(report)
    expected = report['execution'].get('commands', {}).get(path_id, report['execution'])
    require(argv == expected['argv'] and str(Path(cwd).resolve()) == str(Path(expected['cwd']).resolve()),
            'test command differs from approved context; obtain a new preflight/assignment')
