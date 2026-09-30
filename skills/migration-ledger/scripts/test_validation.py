"""Build, functional automation and baseline visual alignment are separate Test-Runner stages."""
import copy
from pathlib import Path

from contracts import require, check_ref, nonempty, verify_plan, baseline

OPS = {'automation-unavailable', 'automation-resume', 'audit-unavailable'}


def split(m):
    return any(p.get('kind') == 'build' for p in (m.get('plan') or {}).get('paths', []))


def paths(m, scope):
    """Stages are build -> automation (functional cases) -> visual (baseline node alignment)."""
    return [p for p in m['plan']['paths'] if (p.get('kind') or 'automation') == scope]


def build_ready(m):
    return bool(split(m) and m.get('build_baseline') == m.get('code_baseline') and m.get('code_baseline')
                and all(m.get('results', {}).get(p['path_id'], {}).get('quality') == 'green-passed'
                        for p in paths(m, 'build')))


def _green_at_baseline(m, scope):
    results = m.get('results', {})
    return all((results.get(p['path_id']) or {}).get('quality') == 'green-passed'
               and (results.get(p['path_id']) or {}).get('code_baseline') == m.get('code_baseline')
               for p in paths(m, scope))


def functional_ready(m):
    """Layer 1 passed at the current baseline, so rendering may be compared to the baseline."""
    return bool(build_ready(m) and _green_at_baseline(m, 'automation'))


def next_scope(m):
    """Ordered stages; visual only after the functional layer is Green."""
    if not split(m):
        return None
    if not build_ready(m):
        return 'build'
    if paths(m, 'visual') and functional_ready(m):
        return 'visual'
    return 'automation'


def all_green(m):
    planned = {p['path_id'] for p in (m.get('plan') or {}).get('paths', [])}
    results = m.get('results', {})
    return bool(planned) and all((results.get(pid) or {}).get('quality') == 'green-passed' for pid in planned)


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
    require(all(p.get('kind') in ('build', 'automation', 'visual') for p in plan['paths']), 'test path kind required')
    require({p.get('case_id') for p in plan['paths']} ==
            {p.get('case_id') for p in plan['paths'] if p['kind'] == 'automation'},
            'every module case needs an automation path; build/visual cannot cover a business case')
    for path in [p for p in plan['paths'] if p.get('kind') == 'visual']:
        # Visual alignment compares named UI-tree nodes against the captured legacy baseline.
        nodes = nonempty(path.get('node_ids'), 'visual path node_ids')
        require(all(isinstance(n, str) and n.startswith('node:') for n in nodes),
                'visual path node_ids must be stable node:<id> references')
        check_ref(path.get('baseline_ref'))
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


def visual_result(module, path, record, captured, run_root=None, assignment=None):
    """A v2 visual Green binds the frozen target and the current HAP/code/gesture evidence."""
    if (module.get('evidence_contract_version', 1) < 2 or path.get('kind') != 'visual'
            or record.get('quality') != 'green-passed'):
        return
    proof = captured.get('visual_alignment')
    require(isinstance(proof, dict) and record.get('visual_alignment') == proof,
            'visual alignment must match the captured report')
    require(proof.get('coverage') == path.get('coverage') and path.get('coverage'),
            'visual alignment coverage differs from frozen path')
    nodes = nonempty(proof.get('node_ids'), 'visual alignment node_ids')
    require(set(nodes) == set(path['node_ids']), 'visual alignment nodes differ from frozen path')
    require(proof.get('baseline_ref') == path['baseline_ref'],
            'visual alignment baseline differs from frozen path')
    check_ref(proof['baseline_ref'])
    require(proof.get('code_baseline') == module.get('code_baseline') and module.get('code_baseline'),
            'visual alignment code baseline is stale')
    check_ref(proof.get('hap_ref'))
    builds = (module['path_build_artifacts'].get(path['path_id'], []) if 'path_build_artifacts' in module
              else module.get('build_artifacts', []))
    require(proof['hap_ref'] in builds,
            'visual alignment HAP must belong to the accepted current build')
    import lean_adapter
    from contracts import read_json
    source = read_json(check_ref(proof.get('evidence_ref')))
    root = proof.get('alignment_root')
    require(isinstance(root, str) and Path(root).is_absolute(), 'visual alignment_root required')
    rows = lean_adapter.visual_results(source, [i['id'] for i in source.get('required_interactions', [])],
                                      target_root=root, result_ref=proof['evidence_ref'])
    derived = rows.get(path['coverage'], {})
    require(derived.get('quality') == 'green-passed' and derived.get('hap_ref') == proof['hap_ref'],
            'original visual verdict/HAP differs from captured proof')
    expected = lean_adapter.comparison_evidence(source, root, path['coverage'])
    require(proof.get('comparison_evidence') == expected, 'visual comparison proof differs from original evidence')
    require(any(p['kind'] == 'comparison' and p['reference_ref']['sha256'] == path['baseline_ref']['sha256'] for p in expected),
            'comparison does not use frozen baseline screenshot')
    import visual_evidence
    require(run_root is not None, 'visual acceptance requires the current Ledger run root')
    capture_proof = visual_evidence.validate_alignment(source, root, path['coverage'],
        frozen_evidence=visual_evidence.frozen_evidence(module, path),
        code_baseline=module['code_baseline'], run_root=run_root, assignment=assignment)
    require(proof.get('capture_evidence') == capture_proof,
            'visual capture proof differs from frozen source or current build execution')
    interaction_id = path.get('interaction_id')
    if interaction_id:
        import ui_evidence as ue
        import ui_fidelity
        frozen = ui_fidelity.frozen_interaction(module, path)
        ue.match_interaction(proof.get('required_interaction'), frozen)
        alignment = {'hap_sha256': proof['hap_ref']['sha256'],
                     'interaction_checks': proof.get('interaction_checks', [])}
        ue.validate_interaction_checks([interaction_id], alignment)
        checks = [c for c in alignment['interaction_checks'] if c.get('id') == interaction_id]
        require(len(checks) == 1, 'visual path needs one unambiguous interaction check')
        require(checks[0].get('code_baseline') == module['code_baseline'],
                'interaction check must bind the current code baseline')
        ue.match_interaction_observation(checks[0], frozen)


def interaction_result(module, path, record, captured):
    """Behavior-only device proof does not require an Android visual baseline."""
    if (module.get('evidence_contract_version', 1) < 2 or path.get('kind') != 'automation'
            or not path.get('interaction_id') or record.get('quality') != 'green-passed'):
        return
    import ui_evidence as ue
    import ui_fidelity
    proof = captured.get('interaction_evidence')
    require(isinstance(proof, dict) and record.get('interaction_evidence') == proof,
            'interaction evidence must match the captured report')
    frozen = ui_fidelity.frozen_interaction(module, path)
    ue.match_interaction(proof.get('required_interaction'), frozen)
    require(proof.get('code_baseline') == module.get('code_baseline') and module.get('code_baseline'),
            'interaction code baseline is stale')
    check_ref(proof.get('hap_ref'))
    builds = (module['path_build_artifacts'].get(path['path_id'], []) if 'path_build_artifacts' in module
              else module.get('build_artifacts', []))
    require(proof['hap_ref'] in builds, 'interaction HAP must belong to the accepted current build')
    checks = proof.get('interaction_checks')
    require(isinstance(checks, list) and len(checks) == 1 and isinstance(checks[0], dict),
            'automation path needs one unambiguous interaction check')
    ue.validate_interaction_checks([frozen['id']],
        {'hap_sha256': proof['hap_ref']['sha256'], 'interaction_checks': checks})
    require(checks[0].get('code_baseline') == module['code_baseline'], 'interaction observation has stale code')
    require(checks[0].get('from') == frozen['from'], 'interaction did not start at the frozen page/state')
    ue.match_interaction_observation(checks[0], frozen)


def blocked_report(s, mid, ref, stage, instance=None):
    import context_readiness as cr
    require(cr.enabled(s), 'environment deferral requires context evidence')
    report = cr.validate(s, mid, stage, ref, instance=instance, allow_blocked=True)
    blocked = {k for k, v in report['checks'].items() if v['status'] == 'blocked'}
    require(blocked == {'test-environment'}, 'only automation environment may be deferred; resolve other blockers')
    return report


def retained_execution(previous, code_baseline):
    """Retain one accepted execution, never an unbounded chain of omitted attempts."""
    previous = previous or {}
    execution = previous if previous.get('executed') else previous.get('last_execution') or {}
    if (not execution.get('executed') or not execution.get('execution_receipt')
            or execution.get('code_baseline') != code_baseline):
        return None
    return copy.deepcopy({k: v for k, v in execution.items() if k != 'last_execution'})


def untested(path, report_ref, report, token, previous=None, code_baseline=None):
    issue = report['checks']['test-environment']
    row = {'path_id': path['path_id'], 'test_run_id': token + ':' + path['path_id'],
            'quality': 'yellow-blocked', 'executed': False, 'reason_code': 'automation-not-run',
            'code_baseline': code_baseline,
            'assertions': [], 'retest_of': previous.get('test_run_id') if previous else None,
            'root_cause': {'category': 'automation-environment', 'summary': issue['summary'],
                           'confidence': 'confirmed', 'owner': issue['owner'], 'next_action': issue['next_action'],
                           'missing': issue['missing'], 'evidence_refs': [report_ref]}}
    execution = retained_execution(previous, code_baseline)
    if execution:
        row['last_execution'] = execution
    return row


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
        owners = {path['path_id']: m for m in s['modules'].values() for path in m['plan']['paths']}
        rows = [untested(x, p['context_ref'], report, req['request_id'], scope['results'].get(x['path_id']),
                        owners.get(x['path_id'], scope)['code_baseline']) for x in scope['plan']['paths']]
        s.setdefault('audit_results', {}).update({r['path_id']: r for r in rows})
        s['audit'] = {'quality': 'yellow-blocked', 'environment_deferred': True,
                      'report_ref': p['context_ref'], 'paths': rows,
                      'context_receipts_at_deferral': [r['report_ref'] for r in s.get('context_receipts', {}).values()
                                                       if r['report']['stage'] == 'audit-testing'],
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
    for path in paths(m, 'automation') + paths(m, 'visual'):
        previous = m['results'].get(path['path_id'], {})
        if previous.get('quality') == 'green-passed' and previous.get('code_baseline') == m['code_baseline']:
            continue
        m['results'][path['path_id']] = untested(path, p['context_ref'], report, req['request_id'],
                                               m['results'].get(path['path_id']), m['code_baseline'])
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


def audit_resume_context(s):
    """A newly submitted, current preflight reopens the existing audit route only."""
    import context_readiness as cr
    if not final_deferred_current(s):
        return None
    instance = s.get('audit_code_review', {}).get('auditor_instance_id')
    receipt = s.get('context_receipts', {}).get('audit-testing:' + (instance or ''))
    if not instance or not receipt:
        return None
    ref = receipt['report_ref']
    audit = s['audit']
    if ref in audit.get('context_receipts_at_deferral', [audit.get('report_ref')]):
        return None
    try:
        cr.validate(s, None, 'audit-testing', ref, instance)
    except (ValueError, OSError):
        return None
    return ref
