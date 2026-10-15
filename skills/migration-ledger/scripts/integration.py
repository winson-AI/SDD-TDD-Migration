"""Integration at the wave boundary: a global PATH runs as soon as every leaf that holds its case has completed, not
only at the final audit. Its result enters the audit results bound to its owners' baselines, so the audit re-runs it
only when an owner's code moved; a failure is routed to the owning leaves like an audit finding."""
import copy

from contracts import Drifted, Rejected, check_ref, digest, read_json, require, validate_result

OPS = {'integration-assign', 'integration-submit'}


def owners(s, path):
    """The leaves that hold a global path's case: the global plan's case owners, else the leaves registered on it."""
    held = (s.get('global_plan') or {}).get('content', {}).get('case_owners', {}).get(path.get('case_id'))
    if held is None:
        held = [mid for mid, m in s['modules'].items() if path.get('case_id') in m.get('case_ids', [])]
    return sorted(mid for mid in held if mid in s['modules'])


def owner_baselines(s, path):
    return {mid: s['modules'][mid].get('code_baseline') for mid in owners(s, path)}


def current(s, path, previous, code_baseline):
    """A green result stands while the whole code is what it ran on, or while every owner's code is."""
    if not previous or previous.get('stale') or previous.get('quality') != 'green-passed':
        return False
    return previous.get('code_baseline') == code_baseline or (
        bool(previous.get('owner_baselines')) and previous['owner_baselines'] == owner_baselines(s, path))


def work_remaining(s):
    """Some leaf is still at work: the boundary of a wave, not the end of the run (the audit takes it from there)."""
    import audit_closure
    return any(m['phase'] not in audit_closure.TERMINAL for m in s['modules'].values())


def task(s):
    item = s.get('integration_assignment') or {}
    return item if item and not item.get('closed', True) else None


def due(s):
    """The global paths whose owners have all completed and that have no current green result."""
    import audit_closure
    from ledger import global_baseline
    if audit_closure.active(s) or not (s.get('audit_assignment') or {}).get('closed', True) or task(s):
        return []
    try:
        baseline = global_baseline(s)
    except (Rejected, Drifted, OSError):
        return []  # some code evidence drifted: that module's own cursor says so first
    results = s.get('audit_results', {})
    selected = []
    for path in s.get('global_paths', []):
        held = owners(s, path)
        done = held and all(s['modules'][mid]['phase'] == 'completed' and not s['modules'][mid].get('stale')
                            and not any(not a.get('closed') for a in s['modules'][mid]['assignments'].values()) for mid in held)
        previous = results.get(path['path_id'])
        routed = previous and previous.get('quality') != 'green-passed' and previous.get('owner_baselines') == owner_baselines(s, path)
        if done and not routed and not current(s, path, previous, baseline):  # a red on this very code is routed, not re-run
            selected.append(path)
    return selected


def scope(s):
    from ledger import scope_of
    return scope_of(s, due(s) if not task(s) else [p for p in s.get('global_paths', []) if p['path_id'] in task(s)['path_ids']], leftovers=False)


def handle(s, req, actor, sequence):
    from ledger import role
    import prepared_tests
    p = req['payload']
    if req['operation'] == 'integration-assign':
        role(actor, 'global-orchestrator')
        require(not task(s), 'integration Test-Runner still active')
        selected = due(s)
        require(selected, 'no global path is due: its owners are still at work, or it is green on their code')
        require(p.get('instance_id') and p.get('assignment_id'), 'integration Test-Runner identity required')
        authors = {a['instance_id'] for m in s['modules'].values() for a in m['assignments'].values() if a['role'] in ('implementer', 'fixer')}
        require(p['instance_id'] not in authors | prepared_tests.global_authors(s), 'integration Test-Runner must be independent of code and script authors')
        require(p.get('path_ids') == [x['path_id'] for x in selected], 'integration assignment must cover exactly the due paths')
        require(p['assignment_id'] not in s.get('integration_assignment_ids', []), 'duplicate integration assignment')
        s.setdefault('integration_assignment_ids', []).append(p['assignment_id'])
        if s.get('integration_assignment'):
            s.setdefault('integration_history', []).append(copy.deepcopy(s['integration_assignment']))
        from ledger import scope_of
        value = scope_of(s, selected, leftovers=False)
        s['integration_assignment'] = {**copy.deepcopy(p), 'role': 'test-runner', 'mode': 'integration', 'run_id': s['run_id'],
            'module_id': 'GLOBAL', 'freeze_id': value['freeze_id'], 'code_baseline': value['code_baseline'],
            'snapshot': {mid: m['code_baseline'] for mid, m in s['modules'].items()},
            'owner_baselines': {x['path_id']: owner_baselines(s, x) for x in selected},
            'scope_policy': 'non-green-only', 'closed': False, 'fencing_token': sequence}
    else:
        role(actor, 'test-runner')
        item = task(s)
        require(item and item['instance_id'] == actor['instance_id'], 'integration task inactive/mismatch')
        value = scope(s)
        require(item['path_ids'] == [x['path_id'] for x in value['plan']['paths']] and value['code_baseline'] == item['code_baseline'],
                'integration selection or code changed; the task is stale, assign again')
        result = read_json(check_ref(p.get('result_ref')))
        validate_result(result, value, item)
        require(result['kind'] == 'tests', 'integration task needs execution evidence')
        paths = {x['path_id']: x for x in s.get('global_paths', [])}
        for row in result['paths']:
            s.setdefault('audit_results', {})[row['path_id']] = {**row, 'code_baseline': value['code_baseline'],
                                                                'owner_baselines': item['owner_baselines'][row['path_id']]}
            if row['quality'] != 'green-passed':
                s.setdefault('audit_repairs', {})[row['path_id']] = {'finding': row, 'report_ref': p['result_ref'],
                    'module_ids': owners(s, paths[row['path_id']]), 'accepted_by': []}
            else:
                s.get('audit_repairs', {}).pop(row['path_id'], None)
        item.update(closed=True, result_ref=p['result_ref'])
