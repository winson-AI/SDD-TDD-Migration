"""MO-owned functional decomposition, GO registration review, and parent summaries.

Executable leaves stay in modules; coordinating parents stay in module_groups.
This keeps code/test evidence owned by exactly the MO that executed the leaf.
"""
import copy
import reuse
import dimensions
from pathlib import Path

from contracts import Rejected, check_ref, digest, nonempty, read_json, require

OPERATIONS = {'decompose', 'decompose-accept', 'module-summary', 'realloc-request', 'redecompose', 'redecompose-accept'}
ALLOCATION_KEYS = ('name', 'scope', 'case_ids', 'write_paths', 'context_refs', 'dimension_analysis_ref', 'behavior_review')

TERMINAL = {'completed', 'waiting-auditor', 'waiting-dependency', 'waiting-human', 'automation-deferred', 'waiting-upstream'}


def parent_mo_names(s):
    """Stable host display names, deliberately outside frozen allocation content."""
    ids = set(s.get('module_groups', {})) | {mid for mid, m in s['modules'].items() if m.get('decomposition_required')}
    return {mid: 'parent-mo-' + mid for mid in sorted(ids)}


def planning_context(s):
    """Global read context, separate from any particular module's write scope."""
    sources = {}
    if s.get('project_context_ref'):
        sources = read_json(check_ref(s['project_context_ref'])).get('source_refs', {})
    result = {
        'legacy_root': s['legacy_root'], 'target_root': s['target_root'],
        'reuse_sources': reuse.sources(s),
        **({'build': copy.deepcopy(s.get('build', {})), 'split_testing_required': True} if s.get('split_testing_required') else {}),
        'global_spec': s['global_spec'], 'new_architecture': s['new_architecture'],
        'project_context_ref': s.get('project_context_ref'), 'project_sources': sources,
        'modules': {mid: {key: m.get(key) for key in ('parent_module_id', 'scope', 'context_refs', 'case_ids', 'write_paths', 'dependencies')}
                    for mid, m in s['modules'].items()},
        'parents': {mid: group['children'] for mid, group in s.get('module_groups', {}).items()},
    }
    if s.get('dimension_slicing_required'):
        result['dimension_slicing_required'] = True
    if s.get('behavior_contract_required'):
        result['behavior_contract_required'] = s['behavior_contract_required']
    if s.get('target_resources'):
        result['target_resources'] = copy.deepcopy(s['target_resources'])
    if s.get('project_context_ref'):
        layout = read_json(check_ref(s['project_context_ref'])).get('storage_layout')
        if layout:
            result['storage_layout'] = copy.deepcopy(layout)
    plan = (s.get('global_plan') or {}).get('content', {})
    if (s.get('global_plan') or {}).get('source_review_ref'):
        result['source_change_ref'] = s['global_plan']['source_review_ref']
    if plan.get('feature_inventory_ref'):
        result.update(feature_inventory_ref=plan['feature_inventory_ref'], feature_owners=plan['feature_owners'])
    allocations = {mid: m['dimension_analysis_ref'] for mid, m in
        {**s.get('module_groups', {}), **s['modules']}.items() if m.get('dimension_analysis_ref')}
    if allocations or s.get('dimension_slicing_required'):
        result['dimension_allocations'] = allocations
    return result


def standing(s, mid, context=None):
    """The part of a planning context a leaf stands on: what the run shares, the leaf itself, the parents above it and
    the slices it depends on. What concerns only other slices may be rewritten without making its reports or its plan
    stale - their owners keep them apart (one writer per path, one holder per case), not every leaf's digest.
    A parent, a module still to be split and the run itself stand on all of it."""
    context = planning_context(s) if context is None else context
    own, parents = context['modules'].get(mid), context['parents']
    if own is None or (s['modules'].get(mid) or {}).get('decomposition_required'):
        return context
    above = lambda node: next((parent for parent, children in parents.items() if node in children), None)
    keep, parent = {mid}, own.get('parent_module_id') or above(mid)
    while parent and parent not in keep:
        keep.add(parent)
        parent = above(parent)
    pending = list(own.get('dependencies') or [])
    while pending:
        node = pending.pop()
        if node not in keep:
            keep.add(node)
            pending.extend(parents.get(node, []))
    scoped = {**context, **{key: {k: v for k, v in context[key].items() if k in keep}
                            for key in ('modules', 'parents', 'dimension_allocations') if key in context}}
    if 'feature_owners' in context:
        scoped['feature_owners'] = {fid: owners for fid, owners in context['feature_owners'].items() if keep.intersection(owners)}
    return scoped


# The only parts of the planning context a reviewed source append changes for a module that keeps its frozen plan.
SOURCE_KEYS = ('project_context_ref', 'reuse_sources', 'source_change_ref')
STALE_CONTEXT = 'planning requires current global code/architecture/knowledge/allocation context'


def context_binding(s, module):
    """Digests of the global context and the allocation a plan or split proposal was accepted under.

    Authors do not copy either object into their document: the Ledger binds what is current at
    acceptance and compares these digests whenever the document is used again."""
    context = standing(s, module['module_id'])
    return {'planning_context_sha256': digest(context),
            'planning_base_sha256': digest({k: v for k, v in context.items() if k not in SOURCE_KEYS}),
            'assigned_module_sha256': digest(assigned_module(s, module))}


def check_scope(module):
    scope = module.get('scope', {})
    require(isinstance(scope, dict), 'allocated scope object required')
    nonempty(scope.get('in'), 'allocated business scope')
    require(isinstance(scope.get('out'), list), 'explicit scope exclusions required (may be empty)')
    nonempty(scope.get('requirement_ids'), 'allocated global requirement IDs')
    for ref in nonempty(module.get('context_refs'), 'focused module context references'):
        check_ref(ref)


def assigned_module(s, module):
    """Authoritative allocation; context visibility never expands this ownership."""
    result = {key: copy.deepcopy(module.get(key)) for key in
              ('module_id', 'parent_module_id', 'scope', 'context_refs', 'case_ids', 'write_paths', 'dependencies')}
    parent = s.get('module_groups', {}).get(module.get('parent_module_id'))
    result['parent_context'] = ({key: copy.deepcopy(parent[key]) for key in
                                ('module_id', 'scope', 'context_refs')} if parent else None)
    if module.get('behavior_review'):
        result['behavior_review'] = copy.deepcopy(module['behavior_review'])
    if module.get('acceptance_case_ids') is not None:
        result['acceptance_case_ids'] = list(module['acceptance_case_ids'])
    if parent and parent.get('behavior_review'):
        result['parent_context']['behavior_review'] = copy.deepcopy(parent['behavior_review'])
    if s.get('dimension_slicing_required'):
        result['dimension_slicing_required'] = True
    plan = (s.get('global_plan') or {}).get('content', {})
    if plan.get('feature_inventory_ref'):
        result['feature_inventory_ref'] = copy.deepcopy(plan['feature_inventory_ref'])
        owned = set(leaves(s, module['module_id'])) if module['module_id'] in s.get('module_groups', {}) else {module['module_id']}
        result['feature_ids'] = sorted(fid for fid, owners in plan['feature_owners'].items() if owned.intersection(owners))
    if module.get('dimension_analysis_ref'):
        result['dimension_analysis_ref'] = module['dimension_analysis_ref']
    if parent and parent.get('dimension_analysis_ref'):
        result['parent_context']['dimension_analysis_ref'] = parent['dimension_analysis_ref']
    return result


def check_scopes(s, module):
    check_scope(module)
    parent = s.get('module_groups', {}).get(module.get('parent_module_id'))
    if parent:
        check_scope(parent)


def check_assignment(s, module):
    """The allocation a stored plan was accepted under is still the module's current one."""
    check_scopes(s, module)
    continuation = module.get('allocation_continuation')
    if continuation and continuation.get('plan_hash') == digest(module.get('plan')):
        return
    require((module.get('plan_binding') or {}).get('assigned_module_sha256') == digest(assigned_module(s, module)),
            'assigned module scope or context changed after planning; replan against the current allocation')


def check_module_plan(s, module, plan):
    """A child's stored plan still stands on the global context and the allocation it was accepted under."""
    binding, now = module.get('plan_binding') or {}, context_binding(s, module)
    continued = module.get('source_context_continuation', {})
    alloc_cont = module.get('allocation_continuation', {})
    if continued and continued.get('plan_hash') == digest(plan) and continued.get('context_ref') == s.get('project_context_ref'):
        check_ref(continued['review_ref'])
        require(binding.get('planning_base_sha256') == now['planning_base_sha256']
                and planning_context(s).get('source_change_ref') == continued['review_ref'], STALE_CONTEXT)
    elif alloc_cont and alloc_cont.get('plan_hash') == digest(plan):
        check_ref(alloc_cont['review_ref'])
    else:
        require(binding.get('planning_context_sha256') == now['planning_context_sha256'], STALE_CONTEXT)
    check_assignment(s, module)
    check_tasks(module, plan)


def check_tasks(module, plan):
    allowed = set(module['scope']['requirement_ids'])
    requirements = set()
    for task in plan.get('tasks', []):
        ids = set(nonempty(task.get('global_requirement_ids', task.get('requirement_ids')),
                           'task global requirement mapping'))
        require(ids <= allowed, 'task requirements outside assigned submodule scope')
        requirements.update(ids)
    require(requirements == allowed, 'tasks must cover assigned submodule requirements')
    require({p.get('case_id') for p in plan.get('paths', [])} <= set(module['case_ids']),
            'test cases outside assigned submodule scope')


def leaves(s, mid):
    if mid in s['modules']:
        return [mid]
    return [leaf for child in s['module_groups'][mid]['children'] for leaf in leaves(s, child)]


def summary_subject(s, group):
    return digest({
        'decomposition_ref': group['decomposition_ref'],
        'leaves': {mid: s['modules'][mid]['revision'] for mid in leaves(s, group['module_id'])},
        'child_summaries': {mid: s['module_groups'][mid].get('summary_subject')
                            for mid in group['children'] if mid in s.get('module_groups', {})},
    })


def summary_current(s, group, ref_check=check_ref):
    if any(s['modules'][mid].get('effective_quality') == 'yellow-blocked' for mid in leaves(s, group['module_id'])):
        return False
    if group.get('summary_subject') != summary_subject(s, group):
        return False
    try:
        ref_check(group.get('summary_ref'))
        return True
    except (Rejected, OSError):
        return False


def group_step(s, group, ref_check=check_ref):
    from ledger import current, next_step
    step = {'module_id': group['module_id'], 'phase': group['phase'],
            'expected_revision': group['revision'], 'operation': None,
            'role': 'module-orchestrator', 'agent_name': 'parent-mo-' + group['module_id'],
            'ready': False, 'reason': 'await-child-modules'}
    if group.get('realloc_request'):
        step.update(role='global-orchestrator', reason='await-global-reallocation')
        return step
    if group.get('redecomposition_submission'):
        affected = group['redecomposition_submission'].get('affected_modules', leaves(s, group['module_id']))
        busy = any(not a.get('closed') for mid in affected for a in s['modules'].get(mid, {}).get('assignments', {}).values())
        step.update(operation='redecompose-accept', role='global-orchestrator', ready=not busy,
                    reason='wait-for-affected-workers' if busy else 'redecomposition-proposal-ready')
        return step
    if group.get('replanning_required'):
        step.update(operation='redecompose', ready=True, reason='root-allocation-revised',
                    affected_children=group.get('replanning_children', group['children']))
        return step
    realloc_reqs = [mid for mid in group['children'] if mid in s['modules'] and (
        s['modules'][mid].get('realloc_request') or s['modules'][mid].get('phase') == 'waiting-upstream'
    )]
    if realloc_reqs:
        step.update(operation='redecompose', ready=True, role='module-orchestrator',
                    reason='child-reallocation-requested',
                    affected_children=realloc_reqs)
        return step
    import issues
    owed = [row['issue_id'] for row in issues.of_module(s, group['module_id'])[0]]
    if owed:  # recorded for this parent: its split is revised, or the issue is settled with what answers it
        step.update(operation='redecompose', ready=True, role='module-orchestrator', reason='open-issues', issue_ids=owed)
        return step
    for mid in leaves(s, group['module_id']):
        m = s['modules'][mid]
        if m.get('plan'):
            try:
                current(m)
            except (Rejected, OSError):
                step['reason'] = 'child-evidence-stale'
                return step
        if (m.get('effective_quality') == 'yellow-blocked' or m['phase'] not in TERMINAL or
                (m['phase'] != 'completed' and not m.get('blocked')) or
                any(not a.get('closed') for a in m['assignments'].values()) or
                next_step(s, m)['ready']):
            return step
    for mid in group['children']:
        if mid in s.get('module_groups', {}) and not summary_current(s, s['module_groups'][mid], ref_check):
            return step
    if summary_current(s, group, ref_check):
        step['reason'] = 'parent-summary-current'
    else:
        step.update(operation='module-summary', ready=True, reason='all-children-settled',
                    payload={'subject_sha256': summary_subject(s, group)})
    return step


def refresh_groups(s, ref_check=check_ref):
    for group in s.get('module_groups', {}).values():
        children = [s['modules'][mid] for mid in leaves(s, group['module_id'])]
        green = bool(children) and all(m['quality'] == 'green-passed' for m in children)
        group['quality'] = ('red-bug' if any(m['quality'] == 'red-bug' for m in children)
                            else 'green-passed' if green and summary_current(s, group, ref_check) else 'yellow-blocked')
        group['phase'] = ('completed' if green else 'waiting-auditor') if summary_current(s, group, ref_check) else 'coordinating'


def registered(s, child):
    """A child a re-split restates unchanged is the allocation the Ledger already holds; it is read, not judged again."""
    import behavior_contract
    held = s['modules'].get(child.get('module_id'))
    return bool(held) and all(held.get(key) == child.get(key) for key in ALLOCATION_KEYS) \
        and set(held['dependencies']) == set(child.get('dependencies', [])) \
        and behavior_contract.accepts(held) == behavior_contract.accepts(child)


def validate(s, parent, plan, redecompose=False):
    from ledger import new_module
    require(plan.get('parent_module_id') == parent['module_id'], 'decomposition parent mismatch')
    require(plan.get('rationale'), 'functional decomposition rationale required')
    check_scope(parent)
    if plan.get('kind') == 'atomic-leaf':
        require(not redecompose and set(plan) == {'kind', 'parent_module_id', 'rationale', 'leaf_review_ref'},
                'atomic leaf confirmation retains the current allocation; no children or scope changes')
        check_ref(plan['leaf_review_ref'])
        dimensions.allocation(s, parent)
        if s.get('behavior_contract_required'):
            import behavior_contract
            behavior_contract.review(parent, parent.get('behavior_review'))
            behavior_contract.verification(parent)
        return [], {mid: list(m['dependencies']) for mid, m in s['modules'].items()}
    require(plan.get('kind') in (None, 'split'), 'unknown decomposition kind')
    children = nonempty(plan.get('children'), 'submodules')
    ids = [c.get('module_id') for c in children]
    require(len(set(ids)) == len(ids), 'duplicate child module')
    import behavior_contract
    behavior_contract.assign(children, plan)
    existing_all = set(s['modules']) | set(s.get('module_groups', {}))
    allowed_existing = set(parent.get('children', [])) if redecompose else set()
    conflicts = (set(ids) & existing_all) - allowed_existing
    require(not conflicts, 'child module id already exists')
    cases, requirements = set(), set()
    for child in children:
        require(child.get('name'), 'child functional name required')
        new_module(child)
        check_scope(child)
        if s.get('behavior_contract_required') and not registered(s, child):
            import behavior_contract
            behavior_contract.review(child, child.get('behavior_review'))
        require(not child.get('decomposition_required') and not child.get('parent_module_id'),
                'child MO decomposes tasks; child hierarchy is assigned by GO acceptance')
        require(set(child['scope']['requirement_ids']) <= set(parent['scope']['requirement_ids']),
                'child requirements outside parent scope')
        # A child the Ledger already holds keeps the exclusions it restated when it was accepted; the parent's current
        # ones reach its planner with the parent's allocation.
        require(registered(s, child) or set(parent['scope']['out']) <= set(child['scope']['out']), 'child must retain parent exclusions')
        require(set(child['case_ids']) <= set(parent['case_ids']), 'child cases outside selected function')
        require(all(any(Path(path).resolve().is_relative_to(Path(scope).resolve())
                        for scope in parent['write_paths']) for path in child['write_paths']), 'child write scope outside parent')
        require(set(child.get('dependencies', [])) <= set(ids) | set(parent['dependencies']), 'child dependency outside approved parent boundary')
        cases.update(child['case_ids'])
        requirements.update(child['scope']['requirement_ids'])
    require(cases == set(parent['case_ids']), 'submodules must cover every parent case')
    require(requirements == set(parent['scope']['requirement_ids']), 'submodules must cover every parent requirement')
    dimensions.partition(s, parent, plan)
    import behavior_contract
    if s.get('behavior_contract_required') or any(c.get('behavior_review') for c in children):
        for child in children:
            if not registered(s, child):
                behavior_contract.verification(child)
        behavior_contract.distinct(children)
    old_child_ids = set(parent.get('children', [])) if redecompose else set()
    graph = {mid: list(m['dependencies']) for mid, m in s['modules'].items() if mid != parent['module_id'] and mid not in old_child_ids}
    for mid, deps in graph.items():
        replaced = {parent['module_id']} | (old_child_ids - set(ids))
        if replaced.intersection(deps):
            bindings = plan.get('consumer_dependencies', {}).get(mid)
            require(isinstance(bindings, list) and bool(bindings) and set(bindings) <= set(ids), 'consumer_dependencies must name actual provider children')
            graph[mid] = sorted((set(deps) - replaced) | set(bindings))
        else:
            graph[mid] = sorted(deps)
    import copy
    for cid, deps in graph.items():
        if deps != s['modules'][cid]['dependencies']:
            candidate = copy.deepcopy(s['modules'][cid])
            candidate['dependencies'] = deps
            require(candidate.get('behavior_review'), 'consumer behavior review required before dependency reallocation')
            candidate['behavior_review']['verification'] = plan.get('consumer_verifications', {}).get(cid)
            behavior_contract.verification(candidate)
    for child in children:
        graph[child['module_id']] = sorted(set(child.get('dependencies', [])))
    visiting, visited = set(), set()
    def visit(mid):
        require(mid in graph, 'missing decomposition dependency')
        require(mid not in visiting, 'decomposition dependency cycle')
        if mid in visited:
            return
        visiting.add(mid)
        for dep in graph[mid]:
            visit(dep)
        visiting.remove(mid)
        visited.add(mid)
    for mid in graph:
        visit(mid)
    if (s.get('behavior_contract_required') or any(c.get('behavior_review') for c in children)) \
            and not all(registered(s, child) for child in children):
        inside = {parent['module_id'], *ids, *parent.get('children', [])}
        behavior_contract.independence(parent, children, graph, plan, {
            cid for mid, module in {**s.get('module_groups', {}), **s['modules']}.items() if mid not in inside
            for cid in behavior_contract.accepts(module)}, {child['module_id'] for child in children if not registered(s, child)})
    return children, graph


def built_on(s, providers):
    """The leaves that hold code built on one of `providers` and are not among them."""
    return {cid for cid, mod in s['modules'].items()
            if cid not in providers and mod.get('code_baseline') and set(providers).intersection(mod['dependencies'])}


def redecomposition_impact(s, parent, children, graph):
    """The leaves a re-split reaches: the children it changes, the leaves whose providers it rebinds, and the leaves
    holding code built on a changed child. A leaf that only plans next to them is not reached."""
    old, new = set(parent['children']), {c['module_id']: c for c in children}
    impact = old.symmetric_difference(new)
    import behavior_contract
    impact.update(cid for cid in old.intersection(new) if
        any(s['modules'][cid].get(key) != new[cid].get(key) for key in ALLOCATION_KEYS)
        or behavior_contract.accepts(s['modules'][cid]) != behavior_contract.accepts(new[cid])
        or graph[cid] != s['modules'][cid]['dependencies'])
    impact.update(cid for cid, mod in s['modules'].items() if graph.get(cid, mod['dependencies']) != mod['dependencies'])
    return impact | built_on(s, impact)


def boundary_kept(old, new, dependencies):
    """Nothing a leaf was already asked for is taken away: every statement of its scope, its requirements, cases, accepted
    cases and write scope stay inside the revised allocation, no exclusion is added and it depends on the same slices.
    A reworded scope statement cannot be told from a moved one, so it does not count as kept."""
    import behavior_contract
    inside = lambda path: any(Path(path).resolve().is_relative_to(Path(scope).resolve()) for scope in new['write_paths'])
    return (set(old['scope']['in']) <= set(new['scope']['in'])
            and set(old['scope']['requirement_ids']) <= set(new['scope']['requirement_ids'])
            and set(old['case_ids']) <= set(new['case_ids'])
            and set(behavior_contract.accepts(old)) <= set(behavior_contract.accepts(new))
            and all(inside(path) for path in old['write_paths'])
            and set(new['scope']['out']) <= set(old['scope']['out'])
            and set(dependencies) == set(old['dependencies']))


def revisable(old, new, dependencies):
    """A frozen, unblocked leaf whose boundary a revision keeps: it takes the revision as a change to its contract and
    keeps its code. Any other leaf the revision changes plans again from its new allocation."""
    return bool(old.get('freeze_id')) and not old.get('blocked') and boundary_kept(old, new, dependencies)


def revision_plan(s, parent, children, graph):
    """(leaves that plan again, leaves that revise their contract) for a re-split. A leaf that only depends on one of
    them is in neither: it keeps its plan, and if it already holds code it waits for its provider like after any
    provider change."""
    import behavior_contract
    old, new = set(parent['children']), {c['module_id']: c for c in children}
    changed = {cid for cid in old.intersection(new) if
               any(s['modules'][cid].get(key) != new[cid].get(key) for key in ALLOCATION_KEYS)
               or behavior_contract.accepts(s['modules'][cid]) != behavior_contract.accepts(new[cid])
               or graph[cid] != s['modules'][cid]['dependencies']}
    revised = {cid for cid in changed if revisable(s['modules'][cid], new[cid], graph[cid])}
    reset = old.symmetric_difference(new) | (changed - revised) | {
        cid for cid, mod in s['modules'].items() if graph.get(cid, mod['dependencies']) != mod['dependencies']}
    return reset, revised - reset


def accepted_over(s):
    """What a global plan was accepted over: who holds which cases and requirements, who depends on whom at which
    stage, who writes where and who owns what is shared. How a review words or evidences a boundary is not part of it."""
    def boundary(review):
        verification = (review or {}).get('verification') or {}
        return {'shared_capabilities': (review or {}).get('shared_capabilities'),
                **{key: verification.get(key) for key in ('acceptance_owner', 'case_ids', 'integration_case_ids')},
                'provider_inputs': [{key: row.get(key) for key in ('module_id', 'required_stage')} for row in verification.get('provider_inputs') or []]}
    return digest({mid: {**{key: m.get(key) for key in ('case_ids', 'dependencies', 'write_paths', 'scope', 'acceptance_case_ids', 'parent_module_id')},
                         'boundary': boundary(m.get('behavior_review'))}
                   for mid, m in {**s.get('module_groups', {}), **s['modules']}.items()})


def allocation_delta(old, new):
    """What a re-split changed for a child it keeps: the fields of its allocation that differ and, where its analysis
    was rewritten, the items and API contracts whose ask differs or that are new. Its planner starts from this instead
    of comparing two documents."""
    delta = {'fields': sorted(key for key in (*ALLOCATION_KEYS, 'acceptance_case_ids') if old.get(key) != new.get(key))}
    before, after = old.get('dimension_analysis_ref'), new.get('dimension_analysis_ref')
    if before and after and before != after:
        import dimensions
        try:
            items, apis = dimensions.revised(before, after, old['module_id'])
            added = set(dimensions.load(after, old['module_id'])[1]) - set(dimensions.load(before, old['module_id'])[1])
            delta.update(items=sorted(items | added), apis=sorted(apis))
        except (Rejected, OSError, KeyError):
            pass  # an analysis that cannot be read is reported by the gates; the fields still say what moved
    return delta


def continue_unaffected(s, affected, review_ref, run_root):
    """An accepted allocation refinement preserves unrelated SPEC and test design inputs."""
    import context_readiness
    import design_stage
    context_readiness.pin_execution(run_root, s, affected)
    for mid, m in s['modules'].items():
        if mid in affected:
            continue
        if m.get('design_input_ref'):
            m['planning_continuation'] = {
                'subject_sha256': design_stage.subject(s, m), 'context_ref': s.get('project_context_ref'),
                'allocation_sha256': digest({key: m.get(key) for key in (*ALLOCATION_KEYS, 'dependencies')}),
                'generation': m.get('design_generation', 0), 'review_ref': review_ref}
        if m.get('plan'):
            m['allocation_continuation'] = {'plan_hash': m['plan_hash'], 'review_ref': review_ref}


def handle(s, req, actor, run_root):
    from ledger import idle, new_module, open_change, role, replan_module
    mid, op, p = req['module_id'], req['operation'], req.get('payload', {})
    if op == 'module-summary':
        role(actor, 'module-orchestrator')
        group = s.get('module_groups', {}).get(mid)
        require(group and group_step(s, group)['ready'], 'parent summary requires all descendants settled')
        require(p.get('subject_sha256') == summary_subject(s, group), 'parent summary snapshot stale')
        check_ref(p.get('summary_ref'))
        group.update(summary_subject=summary_subject(s, group), summary_ref=p['summary_ref'],
                     summary_actor=actor['instance_id'])
        return
    if op == 'realloc-request':
        role(actor, 'module-orchestrator')
        m = s['modules'].get(mid) or s.get('module_groups', {})[mid]
        idle(m)
        reason = p.get('reason')
        require(isinstance(reason, str) and bool(reason.strip()), 'realloc-request reason required')
        evidence_refs = nonempty(p.get('evidence_refs'), 'realloc-request evidence required')
        for ref in evidence_refs:
            check_ref(ref)
        m['realloc_request'] = {'reason': reason, 'evidence_refs': evidence_refs,
                                'actor_instance_id': actor['instance_id'], 'status': 'pending', 'resume_phase': m['phase']}
        m['phase'] = 'waiting-upstream'
        m['revision'] += 1
        return
    if op == 'redecompose':
        role(actor, 'module-orchestrator')
        parent = s.get('module_groups', {}).get(mid)
        require(parent, 'redecompose requires a parent module group')
        plan = read_json(check_ref(p.get('plan_ref')))
        children, graph = validate(s, parent, plan, redecompose=True)
        parent['redecomposition_submission'] = {'plan_ref': p['plan_ref'], 'actor_instance_id': actor['instance_id'],
                                                'binding': context_binding(s, parent),
                                                'affected_modules': sorted(redecomposition_impact(s, parent, children, graph))}
        return
    if op == 'redecompose-accept':
        role(actor, 'global-orchestrator')
        parent = s.get('module_groups', {}).get(mid)
        require(parent, 'redecompose-accept requires a parent module group')
        submission = parent.get('redecomposition_submission')
        require(submission, 'MO redecomposition proposal required')
        require(submission.get('binding') == context_binding(s, parent), STALE_CONTEXT)
        check_ref(p.get('review_ref'))
        plan = read_json(check_ref(submission['plan_ref']))
        children, graph = validate(s, parent, plan, redecompose=True)

        old_children = set(parent['children'])
        # Keep why children asked upstream: accept clears each realloc_request, history must not.
        triggers = [{'module_id': cid, **{k: copy.deepcopy(s['modules'][cid]['realloc_request'][k]) for k in ('reason', 'evidence_refs')}}
                    for cid in sorted(old_children) if (s['modules'].get(cid) or {}).get('realloc_request')]
        new_children = {c['module_id']: c for c in children}
        new_child_ids = set(new_children.keys())

        retired_ids = old_children - new_child_ids
        added_ids = new_child_ids - old_children
        common_ids = old_children & new_child_ids
        impact = redecomposition_impact(s, parent, children, graph)
        reset, revised = revision_plan(s, parent, children, graph)
        waiting = built_on(s, reset)
        held = accepted_over(s)
        for cid in impact & set(s['modules']):
            idle(s['modules'][cid])
        continue_unaffected(s, reset | revised, p['review_ref'], run_root)
        for cid in common_ids:
            old_mod, new_spec = s['modules'][cid], new_children[cid]
            if cid in reset or cid in revised:
                request = old_mod.get('realloc_request') or {}
                if cid in reset:
                    replan_module(old_mod, 'parent-redecomposed', submission['plan_ref'])
                elif old_mod['phase'] == 'waiting-upstream':
                    old_mod['phase'] = request.get('resume_phase', 'frozen')
                old_mod['allocation_changes'] = allocation_delta(old_mod, new_spec)
                for key in (*ALLOCATION_KEYS, 'acceptance_case_ids'):
                    if key in new_spec:
                        old_mod[key] = copy.deepcopy(new_spec[key])
                    else:
                        old_mod.pop(key, None)
                if cid in revised:
                    open_change(s, old_mod, {'request_ref': submission['plan_ref'], 'impact_ref': p['review_ref'], 'upstream': True})
                old_mod['revision'] += 1
            else:
                old_mod['allocation_continuation'] = {
                    'plan_hash': old_mod.get('plan_hash'), 'review_ref': p['review_ref']}
                request = old_mod.get('realloc_request') or {}
                if old_mod['phase'] == 'waiting-upstream':
                    old_mod['phase'] = request.get('resume_phase', 'specifying')
                    old_mod['revision'] += 1
            old_mod['dependencies'] = graph[cid]
            old_mod.pop('realloc_request', None)

        for cid in retired_ids:
            mod = s['modules'].pop(cid)
            if mod.get('code_files') or mod.get('code_baseline'):
                mod['phase'] = 'superseded'
                mod['superseded_by'] = {'parent_module_id': mid, 'evidence_ref': submission['plan_ref']}
                s.setdefault('superseded_modules', {})[cid] = mod

        for cid in added_ids:
            child = copy.deepcopy(new_children[cid])
            child.update(parent_module_id=mid, dependencies=graph[cid])
            s['modules'][cid] = new_module(child)

        for m_id, mod in s['modules'].items():
            if m_id not in new_child_ids and m_id in reset:
                replan_module(mod, 'upstream-dependency-redecomposed', submission['plan_ref'])
                if mod['dependencies'] != graph[m_id]:
                    mod['behavior_review']['verification'] = copy.deepcopy(plan['consumer_verifications'][m_id])
                mod['dependencies'] = graph[m_id]
                mod['revision'] += 1

        for group_id, group in s.get('module_groups', {}).items():
            if group_id == mid:
                continue
            deps = set(group['dependencies'])
            if retired_ids.intersection(deps):
                group['dependencies'] = sorted((deps - retired_ids) | new_child_ids)
            if retired_ids.intersection(deps) or impact.intersection(leaves(s, group_id)):
                group.pop('summary_ref', None)
                group.pop('summary_subject', None)
                group['revision'] += 1

        parent['children'] = [c['module_id'] for c in children]
        parent['decomposition_ref'] = submission['plan_ref']
        parent['decomposition_review_ref'] = p['review_ref']
        parent.pop('redecomposition_submission', None)
        parent.pop('replanning_required', None)
        parent.pop('replanning_children', None)
        parent.pop('realloc_request', None)
        from ledger import await_provider
        for cid in waiting & set(s['modules']):
            await_provider(s['modules'][cid])
        parent.pop('summary_ref', None)
        parent.pop('summary_subject', None)
        parent['revision'] += 1

        s.setdefault('redecomposition_history', []).append({
            'kind': 'planning-history', 'executable': False,
            'parent_module_id': mid,
            'plan_ref': submission['plan_ref'],
            'review_ref': p['review_ref'],
            'affected_modules': sorted(impact - retired_ids),
            'revised_modules': sorted(revised),
            'retired_modules': sorted(retired_ids),
            'added_modules': sorted(added_ids),
            'triggering_requests': triggers
        })
        if accepted_over(s) != held:  # a revision that only renews evidence leaves the accepted coverage as it was
            s['global_plan'] = None
        if s.get('audit'):
            s.setdefault('audit_history', []).append(copy.deepcopy(s['audit']))
        s['audit'] = {}
        return
    parent = s['modules'][mid]
    require(not parent.get('parent_module_id'), 'child MO decomposes tasks, not another MO hierarchy')
    idle(parent)
    import control_policy
    require(parent['phase'] in ('context', 'specifying', 'clarifying') and
            not parent.get('freeze_id') and not parent.get('code_files') and not parent.get('blocked')
            and not control_policy.execution_started(parent),
            'decompose before freezing/coding; resolve parent blocker first')
    if op == 'decompose':
        role(actor, 'module-orchestrator')
        plan = read_json(check_ref(p.get('plan_ref')))
        validate(s, parent, plan)
        parent['decomposition_submission'] = {'plan_ref': p['plan_ref'], 'actor_instance_id': actor['instance_id'],
                                              'binding': context_binding(s, parent)}
    else:
        role(actor, 'global-orchestrator')
        submission = parent.get('decomposition_submission')
        require(submission, 'MO decomposition proposal required')
        require(submission.get('binding') == context_binding(s, parent), STALE_CONTEXT)
        check_ref(p.get('review_ref'))
        plan = read_json(check_ref(submission['plan_ref']))
        children, graph = validate(s, parent, plan)
        if plan.get('kind') == 'atomic-leaf':
            replan_module(parent, 'atomic-leaf-confirmed', submission['plan_ref'])
            parent['planning_history'][-1]['review_ref'] = p['review_ref']
            parent.update(lean_leaf=True, decomposition_required=False, leaf_review_ref=plan['leaf_review_ref'])
            parent.pop('decomposition_submission', None)
            return
        parent.setdefault('planning_history', []).append({'kind': 'planning-history', 'executable': False,
            'reason': 'scope-decomposed', 'plan_ref': submission['plan_ref'], 'review_ref': p['review_ref']})
        impact = {mid} | {cid for cid, deps in graph.items() if cid in s['modules'] and deps != s['modules'][cid]['dependencies']}
        while True:
            expanded = impact | {cid for cid, m in s['modules'].items() if impact.intersection(m['dependencies'])}
            if expanded == impact: break
            impact = expanded
        for cid in impact:
            idle(s['modules'][cid])
        continue_unaffected(s, impact, p['review_ref'], run_root)
        del s['modules'][mid]
        parent.update(kind='parent-module', phase='coordinating', children=[c['module_id'] for c in children],
                      decomposition_ref=submission['plan_ref'], decomposition_review_ref=p['review_ref'])
        parent.pop('decomposition_required', None)
        parent.pop('decomposition_submission', None)
        s.setdefault('module_groups', {})[mid] = parent
        for child in children:
            child = copy.deepcopy(child)
            child.update(parent_module_id=mid, dependencies=graph[child['module_id']])
            s['modules'][child['module_id']] = new_module(child)
        for leaf_id, module in s['modules'].items():
            if leaf_id in impact:
                replan_module(module, 'upstream-dependency-decomposed', submission['plan_ref'])
                module['revision'] += 1
            if module['dependencies'] != graph[leaf_id]:
                module['dependencies'] = graph[leaf_id]
                module['behavior_review']['verification'] = copy.deepcopy(plan['consumer_verifications'][leaf_id])
        s['global_plan'] = None
        s['audit'] = {}
