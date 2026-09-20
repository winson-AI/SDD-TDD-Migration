"""Evidence-backed reuse guidance; semantic extraction/review is performed by agents."""
import copy
from pathlib import Path
import re

from contracts import check_ref, keyed, nonempty, read_json, require


def normalize_sources(items, target_root=None, existing=False):
    require(isinstance(items, list), 'reuse_sources must be a list')
    result, ids = [], {'TARGET'}
    for item in items:
        require(isinstance(item, dict) and set(item) <= {'source_id', 'root', 'module_paths', 'description'}, 'invalid reuse source fields')
        sid = item.get('source_id', '')
        require(isinstance(sid, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', sid) and sid not in ids, 'duplicate/reserved/invalid reuse source id')
        ids.add(sid)
        require(isinstance(item.get('root'), str) and Path(item['root']).is_absolute(), 'absolute reuse source root required')
        root = Path(item['root']).resolve()
        paths = nonempty(item.get('module_paths', [str(root)]), 'reuse module paths')
        require(all(isinstance(p, str) and Path(p).is_absolute() and Path(p).resolve().is_relative_to(root) for p in paths), 'reuse module path outside source root')
        if target_root:
            target = Path(target_root).resolve()
            require(all(not (Path(p).resolve().is_relative_to(target) or target.is_relative_to(Path(p).resolve()))
                        for p in paths), 'target reuse source is implicit; external module must be separate')
        if existing:
            require(root.is_dir() and all(Path(p).exists() for p in paths), 'reuse source/module not available')
        result.append({**item, 'root': str(root), 'module_paths': sorted(set(str(Path(p).resolve()) for p in paths))})
    return result


def sources(state):
    return [{'source_id': 'TARGET', 'root': state['target_root'], 'module_paths': [state['target_root']],
             'description': 'Target project existing capabilities'}] + copy.deepcopy(state.get('reuse_sources', []))


def in_source(path, source):
    p = Path(path).resolve()
    return any(p.is_relative_to(Path(root).resolve()) for root in source['module_paths'])


def catalog(ref, expected_sources):
    data = read_json(check_ref(ref))
    require(data.get('schema_version') in (1, 2) and data.get('sources') == expected_sources, 'reuse catalogue source set mismatch')
    by_source = {s['source_id']: s for s in expected_sources}
    reviews = keyed(data.get('source_reviews'), 'source_id')
    require(set(reviews) == set(by_source), 'every reuse source must be reviewed')
    for sid, review in reviews.items():
        require(review.get('status') == 'reviewed' and review.get('conclusion'), 'reuse source review incomplete; resolve before freeze')
        paths = nonempty(review.get('scanned_paths'), 'reuse scanned paths')
        require(all(Path(p).is_absolute() and in_source(p, by_source[sid]) for p in paths), 'reuse scan outside declared modules')
        for evidence in nonempty(review.get('evidence_refs'), 'reuse review evidence'):
            check_ref(evidence)
    capabilities = data.get('capabilities')
    require(isinstance(capabilities, list), 'reuse capabilities list required (may be empty)')
    caps = keyed(capabilities, 'capability_id') if capabilities else {}
    for cap in caps.values():
        if data['schema_version'] == 2:
            require('provider_owner_module_id' in cap, 'explicit provider owner required (null means reviewed baseline)')
            owner = cap['provider_owner_module_id']
            require(owner is None or (isinstance(owner, str) and re.fullmatch(r'M[0-9]{3,}', owner)), 'invalid provider owner')
            require(cap.get('source_id') == 'TARGET' or owner is None, 'external provider must be read-only baseline')
            check_ref(cap.get('ownership_evidence_ref'))
        require(cap.get('source_id') in by_source and cap.get('name') and cap.get('version'), 'reuse capability source/name/version required')
        semantic = cap.get('semantics', {})
        require(all(semantic.get(k) for k in ('intent', 'inputs', 'outputs', 'preconditions', 'side_effects', 'errors', 'state_lifecycle')), 'incomplete functional semantics')
        nonempty(cap.get('api_surface'), 'reuse API surface')
        require(isinstance(cap.get('constraints'), list), 'reuse constraints list required')
        for evidence in nonempty(cap.get('provider_refs'), 'reuse provider evidence'):
            path = check_ref(evidence)
            require(in_source(path, by_source[cap['source_id']]), 'reuse provider evidence outside declared modules')
    return data, caps


def validate_fidelity(row, plan, legacy_root=None):
    """Bind source alignment to real frozen assertions; agents still judge semantic fidelity."""
    fidelity = row.get('fidelity', {})
    root = fidelity.get('legacy_root')
    require(isinstance(root, str) and Path(root).is_absolute(), 'reuse fidelity needs legacy root')
    if legacy_root is not None:
        require(Path(root).resolve() == Path(legacy_root).resolve(), 'reuse fidelity legacy root mismatch')
    for ref in nonempty(fidelity.get('legacy_source_refs'), 'reuse fidelity legacy source evidence'):
        require(check_ref(ref).resolve().is_relative_to(Path(root).resolve()), 'fidelity baseline outside legacy source')
    check_ref(fidelity.get('alignment_ref'))
    scenarios = keyed(fidelity.get('scenarios'), 'scenario_id')
    require(bool(scenarios), 'reuse fidelity scenarios required')
    paths = {p['path_id']: p for p in plan['paths']}
    covered = set()
    for scenario in scenarios.values():
        pid = scenario.get('path_id')
        require(pid in row['path_ids'] and pid in paths, 'fidelity path outside reuse mapping')
        aids = set(nonempty(scenario.get('assertion_ids'), 'fidelity assertions'))
        require(aids <= {a['assertion_id'] for a in paths[pid]['expected_assertions']}, 'fidelity assertion not frozen in path')
        require(all(scenario.get(k) for k in ('legacy_behavior', 'reuse_behavior', 'reproduction_strategy')),
                'fidelity needs source behavior, reuse comparison and reproduction strategy')
        covered.add(pid)
    require(covered == set(row['path_ids']), 'fidelity must cover every mapped path')


def validate_plan(plan, module, expected_sources, modules=None, legacy_root=None):
    review = read_json(check_ref(plan.get('reuse_plan_ref')))
    require(review.get('schema_version') == 1 and review.get('module_id') == module['module_id'], 'reuse plan module mismatch')
    data, caps = catalog(review.get('catalog_ref'), expected_sources)
    if data['schema_version'] == 2:
        validate_owners(caps, modules or {})
    mappings = keyed(review.get('mappings'), 'mapping_id')
    tasks = {t['task_id']: t for t in plan['tasks']}
    paths = {p['path_id'] for p in plan['paths']}
    allowed = set(module.get('scope', {}).get('requirement_ids') or
                  [rid for t in tasks.values() for rid in t.get('global_requirement_ids', t.get('requirement_ids', []))])
    covered = set()
    for row in mappings.values():
        reqs = set(nonempty(row.get('requirement_ids'), 'reuse requirement mapping'))
        tids = set(nonempty(row.get('task_ids'), 'reuse task mapping'))
        pids = set(nonempty(row.get('path_ids'), 'reuse test mapping'))
        require(reqs <= allowed and tids <= set(tasks) and pids <= paths, 'reuse mapping outside assigned requirements/tasks/paths')
        require(reqs <= {r for tid in tids for r in tasks[tid].get('global_requirement_ids', tasks[tid].get('requirement_ids', []))}, 'reuse requirement/task trace mismatch')
        require(pids <= {pid for tid in tids for pid in tasks[tid]['path_ids']}, 'reuse path/task trace mismatch')
        require(row.get('decision') in ('reuse', 'adapt', 'reference', 'new'), 'invalid reuse decision')
        require(all(row.get(k) for k in ('rationale', 'behavior_delta', 'binding_plan', 'verification')), 'reuse decision needs semantic delta, binding and verification guidance')
        if row['decision'] == 'new':
            require(row.get('capability_id') is None, 'new implementation must not claim a reused capability')
        else:
            cap = caps.get(row.get('capability_id'))
            require(cap, 'unknown reusable capability')
            if cap['source_id'] == 'TARGET':
                if data['schema_version'] == 2:
                    owner = cap['provider_owner_module_id']
                    require(owner in (None, module['module_id']) or owner in module.get('dependencies', []),
                            'explicit provider owner requires registered dependency')
                    for peer_id, peer in (modules or {}).items():
                        if peer_id == module['module_id']: continue
                        for existing in peer.get('provider_owners', []):
                            if existing['source_id'] == cap['source_id'] and existing['capability_id'] == cap['capability_id']:
                                require(existing['owner'] == owner, 'conflicting active capability owners; review and invalidate affected plans')
                else:
                    for mid, owner in (modules or {}).items():
                        if mid != module['module_id'] and any(in_source(ref['path'], {'module_paths': owner['write_paths']})
                                                             for ref in cap['provider_refs']):
                            require(mid in module.get('dependencies', []), 'reused provider under another module requires registered dependency')
            integration = row.get('integration', {})
            require(integration.get('mode') in ('existing-target', 'package', 'source-module', 'reference-only') and
                    integration.get('version') == cap['version'], 'reuse integration mode/version mismatch')
            require((row['decision'] == 'reference') == (integration['mode'] == 'reference-only'), 'reference is guidance, not a runtime dependency')
            require(integration['mode'] != 'existing-target' or cap['source_id'] == 'TARGET', 'external source is not an existing target dependency')
            require(all(integration.get(k) for k in ('locator', 'configuration', 'transitive_dependencies', 'compatibility')), 'incomplete dependency integration guidance')
            for evidence in nonempty(integration.get('evidence_refs'), 'integration feasibility evidence'):
                check_ref(evidence)
            validate_fidelity(row, plan, legacy_root)
        covered.update(reqs)
    require(covered == allowed, 'reuse decisions must cover every module requirement')
    return review


def validate_owners(caps, modules):
    """Ownership is semantic evidence; write scope only limits authorized changes."""
    for cap in caps.values():
        owner = cap['provider_owner_module_id']
        if owner is not None:
            require(owner in modules and not modules[owner].get('decomposition_required'), 'provider owner must be an execution leaf')
            require(all(in_source(ref['path'], {'module_paths': modules[owner]['write_paths']})
                        for ref in cap['provider_refs']), 'provider outside owner write scope')
    visiting, visited = set(), set()
    def visit(mid):
        require(mid in modules and mid not in visiting, 'provider dependency cycle or missing module')
        if mid in visited: return
        visiting.add(mid)
        for dependency in modules[mid].get('dependencies', []): visit(dependency)
        visiting.remove(mid); visited.add(mid)
    for mid in modules: visit(mid)


def selected_owners(plan):
    if not plan.get('reuse_plan_ref'): return []
    review = read_json(check_ref(plan['reuse_plan_ref']))
    data = read_json(check_ref(review['catalog_ref']))
    if data.get('schema_version') != 2: return []
    selected = {row.get('capability_id') for row in review['mappings'] if row['decision'] != 'new'}
    return [{'source_id': cap['source_id'], 'capability_id': cap['capability_id'], 'owner': cap['provider_owner_module_id']}
            for cap in data['capabilities'] if cap['capability_id'] in selected]


def verify(plan):
    """Only selected providers are live dependencies; unrelated candidates do not invalidate consumers."""
    if not plan.get('reuse_plan_ref'):
        return None
    review = read_json(check_ref(plan['reuse_plan_ref']))
    data = read_json(check_ref(review['catalog_ref']))
    for source_review in data['source_reviews']:
        for ref in source_review['evidence_refs']:
            check_ref(ref)
    caps = {c['capability_id']: c for c in data['capabilities']}
    for row in review['mappings']:
        if row['decision'] == 'new':
            continue
        if data.get('schema_version') == 2:
            check_ref(caps[row['capability_id']]['ownership_evidence_ref'])
        for ref in caps[row['capability_id']]['provider_refs'] + row['integration']['evidence_refs']:
            check_ref(ref)
        validate_fidelity(row, plan)
    return review


def validate_implementation(plan, result):
    review = verify(plan)
    if not review:
        return
    selected = {r['mapping_id']: r for r in review['mappings'] if r['decision'] != 'new'}
    traces = result.get('reuse_trace', [])
    require(isinstance(traces, list), 'reuse implementation trace must be a list')
    traces = keyed(traces, 'mapping_id') if traces else {}
    require(set(traces) == set(selected), 'implementation must trace every selected reuse mapping')
    task_files = {t['task_id']: set(t['files']) for t in result['task_trace']}
    for mid, row in selected.items():
        trace = traces[mid]
        require(trace.get('resolved_version') == row['integration']['version'], 'resolved dependency version differs from frozen plan')
        files = set(nonempty(trace.get('files'), 'reuse binding files'))
        require(files <= {p for tid in row['task_ids'] for p in task_files[tid]}, 'reuse binding not traced to mapped task files')
        check_ref(trace.get('binding_evidence_ref'))


def implementation_gap(state, module, payload):
    """MO-reviewed inability under current constraints, not merely missing reuse."""
    require(payload.get('kind') == 'human' and payload.get('next_action'),
            'not-implemented requires human review and next action')
    report = read_json(check_ref(payload.get('implementation_gap_ref')))
    require(report.get('schema_version') == 1 and report.get('module_id') == module['module_id'],
            'implementation gap module mismatch')
    require(report.get('module_revision') == module['revision'], 'implementation gap review stale')
    require(report.get('conclusion') == 'not-implementable-under-current-constraints' and report.get('goal'),
            'implementation gap requires verified current constraints')
    for key in ('legacy_root', 'target_root', 'global_spec', 'new_architecture'):
        require(report.get(key) == state[key], 'implementation gap context mismatch: ' + key)
    check_ref(report['global_spec']); check_ref(report['new_architecture'])
    allowed = module.get('scope', {}).get('requirement_ids') or [rid for rid, owners in
        (state.get('global_plan') or {}).get('content', {}).get('requirement_owners', {}).items()
        if module['module_id'] in owners]
    require(set(nonempty(report.get('requirement_ids'), 'unimplemented requirements')) <= set(allowed),
            'implementation gap outside assigned requirements')
    require(set(nonempty(report.get('case_ids'), 'unimplemented cases')) <= set(module['case_ids']),
            'implementation gap outside assigned cases')
    tasks = report.get('task_ids')
    require(isinstance(tasks, list) and set(tasks) <= {t['task_id'] for t in (module.get('plan') or {}).get('tasks', [])},
            'implementation gap outside planned tasks')
    for key in ('context_review_ref', 'reuse_unavailable_ref'):
        check_ref(report.get(key))
    alternatives = report.get('alternatives', {})
    require(isinstance(alternatives, dict) and set(alternatives) == {'adapt', 'reference', 'new'}, 'assess adaptation, reference and new implementation first')
    for alternative in alternatives.values():
        require(isinstance(alternative, dict) and alternative.get('conclusion') == 'not-feasible' and alternative.get('reason'),
                'viable alternative must proceed to planning/coding')
        for ref in nonempty(alternative.get('evidence_refs'), 'alternative feasibility evidence'):
            check_ref(ref)
    verification = report.get('verification', {})
    require(isinstance(verification, dict) and verification.get('summary') and verification.get('method') in ('implementation-attempt', 'constraint-analysis'),
            'implementation gap verification required')
    for ref in nonempty(verification.get('evidence_refs'), 'implementation gap verification evidence'):
        check_ref(ref)
    return report
