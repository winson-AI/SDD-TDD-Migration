"""Session changes preserve one Run and require host evidence of cold restoration."""
import copy
from contracts import check_ref, digest, nonempty, read_json, require


def checkpoint(s, m, role, previous):
    if m is None:
        import context_readiness
        refs = context_readiness.global_refs(s)
        refs += [r for r in ((s.get('global_plan') or {}).get('plan_ref'), s.get('lessons_ref')) if r]
        version = {'global_spec_ref': s['global_spec'], 'registry_sha256': digest({
            mid: {k: value.get(k) for k in ('revision', 'plan_ref', 'freeze_id', 'code_baseline')}
            for mid, value in {**s.get('module_groups', {}), **s['modules']}.items()}), 'run_revision': s['revision']}
    else:
        refs = [r for r in (m.get('plan_ref'), m.get('execution_context_ref'), m.get('planning_lessons_ref'),
                            m.get('decomposition_ref')) if r]
        version = {k: m.get(k) for k in ('plan_ref', 'freeze_id', 'code_baseline')}
        if s.get('host_handoff_required'): version['module_revision'] = m['revision']
    return {'run_id': s['run_id'], 'module_id': m['module_id'] if m else None, 'role': role,
            'previous_session_id': previous, **version, 'resume_refs': refs}


def replace(s, m, p, previous):
    if p.get('reason') in ('session-unavailable', 'context-rotation'):
        require(previous and previous['session_id'] != p['session_id'], 'cold recovery needs a distinct new session')
    if not previous or previous['session_id'] == p['session_id']: return
    require(p.get('reason') in ('session-unavailable', 'context-rotation') and p.get('checkpoint_ref'), 'replacement requires cold recovery record')
    check_ref(p['checkpoint_ref'])
    modules = [m] if m else [*s['modules'].values(), *s.get('module_groups', {}).values()]
    require(not any(not a.get('closed') for value in modules for a in value.get('assignments', {}).values()),
            'revoke old worker before cold recovery')
    if m is None:
        require(not s.get('audit_assignment') or s['audit_assignment'].get('closed'), 'close audit before global cold recovery')
    if p['reason'] == 'context-rotation' or s.get('host_handoff_required') or p.get('host_receipt_ref'):
        doc = read_json(check_ref(p['checkpoint_ref']))
        expected = checkpoint(s, m, p['role'], previous['session_id'])
        require(all(doc.get(k) == v for k, v in expected.items() if k != 'resume_refs'), 'rotation checkpoint stale or wrong scope')
        refs = doc.get('resume_refs')
        require(isinstance(refs, list) and all(r in refs for r in expected['resume_refs']), 'rotation checkpoint omits current resume references')
        for ref in refs: check_ref(ref)
    if s.get('host_handoff_required') or p.get('host_receipt_ref'):
        receipt = read_json(check_ref(p.get('host_receipt_ref')))
        require(receipt.get('producer') == 'host' and all(receipt.get(k) == v for k, v in {
            'run_id': s['run_id'], 'module_id': m['module_id'] if m else None, 'role': p['role'],
            'previous_session_id': previous['session_id'], 'session_id': p['session_id'],
            'checkpoint_ref': p['checkpoint_ref']}.items()), 'host handoff receipt binding mismatch')
        require(receipt.get('status') == 'restored', 'host must confirm independent session restoration')
        restored = receipt.get('restored_refs')
        require(isinstance(restored, list) and all(r in restored for r in read_json(check_ref(p['checkpoint_ref']))['resume_refs']),
                'host handoff omitted restored inputs')
        for ref in restored + nonempty(receipt.get('evidence_refs'), 'host session creation/restore evidence'): check_ref(ref)
    (m if m is not None else s).setdefault('session_history', []).append(copy.deepcopy(previous))
