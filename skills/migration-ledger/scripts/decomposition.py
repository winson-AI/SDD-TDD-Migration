"""MO-owned functional decomposition, GO registration review, and parent summaries.

Executable leaves stay in modules; coordinating parents stay in module_groups.
This keeps code/test evidence owned by exactly the MO that executed the leaf.
"""
import copy
import reuse
import dimensions
from pathlib import Path
import re

from contracts import Rejected, check_ref, digest, keyed, nonempty, read_json, require

OPERATIONS = {'decompose', 'decompose-accept', 'module-summary', 'realloc-request', 'redecompose', 'redecompose-accept'}
ALLOCATION_KEYS = ('name', 'scope', 'case_ids', 'write_paths', 'context_refs', 'dimension_analysis_ref', 'behavior_review', 'kind', 'anchor_ui', 'functional_paths')
KINDS = ('feature', 'scaffold')  # a feature leaf anchors on a UI surface; a scaffold is the shell the features plug into
LEAF_MIN_CASES = 3   # fewer is a screen or a branch of a flow, not a leaf: it merges into the flow it belongs to
LEAF_CASES = 20      # more is a wide flow: recorded as a fact, the split is the orchestrator's call
LEAF_MAX_CASES = 30  # more than this is a flow to split by sub-flow
FEATURE_LEAVES = 6   # more feature leaves under one parent says the split went by screen
SKELETON_TASKS = 3  # the tasks that make a scaffold's shell: what its features are released on before the rest of it is written
SKELETON_PATHS = ('build', 'unit', 'static')
TASK_FILES = 40  # more files than this in one version of a task is a task to split

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
    if 'feature_inventory_ref' in context:  # the leaf stands on the rows of its own features, not on the inventory file
        scoped['features'] = feature_rows(scoped.pop('feature_inventory_ref'), scoped.get('feature_owners', {}))
    return scoped


def feature_rows(inventory_ref, owners):
    """The rows of an inventory for the given features, by id: what a leaf holds of the global feature list."""
    try:
        rows = read_json(check_ref(inventory_ref)).get('features') or []
    except (Rejected, OSError, ValueError, TypeError, KeyError):
        return {'unreadable': inventory_ref}
    return {row['feature_id']: row for row in rows if row.get('feature_id') in owners}


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
        owned = set(leaves(s, module['module_id'])) if module['module_id'] in s.get('module_groups', {}) else {module['module_id']}
        result['feature_ids'] = sorted(fid for fid, owners in plan['feature_owners'].items() if owned.intersection(owners))
        if module['module_id'] in s.get('module_groups', {}) or module.get('decomposition_required'):
            result['feature_inventory_ref'] = copy.deepcopy(plan['feature_inventory_ref'])  # a split reads the whole list
        else:  # a leaf holds its own features: a rewritten inventory that leaves them as they were does not move its allocation
            result['features'] = feature_rows(plan['feature_inventory_ref'], {fid: True for fid in result['feature_ids']})
    elif module.get('feature_inventory_ref') or (parent or {}).get('feature_inventory_ref'):  # before the global plan: the root's
        result['feature_inventory_ref'] = copy.deepcopy(module.get('feature_inventory_ref') or parent['feature_inventory_ref'])
    import target_profile
    profile = target_profile.of_module(s, module)
    if profile:
        result['target_profile'] = profile  # what the target already holds for this leaf's features
    import reference_media
    media = reference_media.of_module(s, module)
    if media:
        result['reference_media'] = media  # what the user showed of this leaf's cases
    if module.get('dimension_analysis_ref'):
        result['dimension_analysis_ref'] = module['dimension_analysis_ref']
    if parent and parent.get('dimension_analysis_ref'):
        result['parent_context']['dimension_analysis_ref'] = parent['dimension_analysis_ref']
    if module.get('functional_paths'):
        result['functional_paths'] = list(module['functional_paths'])
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
    check_path_evidence(s, module, plan)


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


def check_skeleton(module, plan):
    """A scaffold names the tasks that make its shell - the module shell and wiring, the interface facade with its fakes, the
    shared resource table - and its features are released once those are accepted and built. A scaffold of a few tasks is
    its own shell. A feature declares none."""
    declared = plan.get('skeleton_task_ids')
    if module.get('kind') != 'scaffold':
        require(not declared, 'only a scaffold declares skeleton tasks')
        return
    tasks = {t['task_id']: t for t in plan.get('tasks', [])}
    if not declared:
        require(len(tasks) <= SKELETON_TASKS, 'a scaffold of more than %d tasks declares skeleton_task_ids: the shell its features are released on' % SKELETON_TASKS)
        return
    require(isinstance(declared, list) and 0 < len(declared) <= SKELETON_TASKS and set(declared) <= set(tasks),
            'skeleton_task_ids names at most %d tasks of the plan' % SKELETON_TASKS)
    kinds = {p['path_id']: p.get('kind', 'automation') for p in plan.get('paths', [])}
    for tid in declared:
        require(all(kinds.get(pid) in SKELETON_PATHS for pid in tasks[tid].get('path_ids', [])),
                'a skeleton task is verified by build, unit and static paths only: ' + tid)


FILE_TOKEN = re.compile(r'[\w./-]+\.(?:kt|kts|java|swift|mm?|ts|tsx|js|py|xml|json|ya?ml|toml|gradle|ets|h|cpp)\b')
MODULE_TOKEN = re.compile(r'\bM\d{3,}\b')


def check_path_evidence(s, module, plan):
    """A PATH is verified on the leaf's own code and its providers': its preconditions and steps name no registered leaf that
    is not a provider, and no target file outside the leaf's and its providers' write scopes. A split that puts a flow's
    screen and its logic in two leaves shows up here, before anything is parked on the sibling."""
    allowed = {module['module_id'], *module.get('dependencies', [])}
    roots = [Path(p).resolve() for mid in allowed for p in (s['modules'].get(mid) or module if mid == module['module_id'] else s['modules'].get(mid) or {}).get('write_paths', [])]
    target = Path(s['target_root']).resolve() if s.get('target_root') else None
    for path in plan.get('paths', []):
        text = ' '.join(str(x) for x in (path.get('preconditions') or []) + (path.get('steps') or []))
        strangers = sorted(mid for mid in set(MODULE_TOKEN.findall(text)) if mid in s['modules'] and mid not in allowed)
        require(not strangers, 'PATH %s takes evidence from %s, which is not a provider of this leaf: a leaf verifies on its own code and its providers' % (path.get('path_id'), ', '.join(strangers)))
        for token in FILE_TOKEN.findall(text):
            p = Path(token)
            if p.is_absolute() and target and p.resolve().is_relative_to(target):
                require(any(p.resolve().is_relative_to(root) for root in roots),
                        'PATH %s takes evidence from %s, outside this leaf and its providers' % (path.get('path_id'), token))


def skeleton(m):
    """The tasks a scaffold releases its features on, when it named them."""
    return set((m.get('plan') or {}).get('skeleton_task_ids') or [])


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
        # The summary binds the children's recorded facts: the Ledger writes it and the host submits it without a model turn.
        step.update(operation='module-summary', ready=True, reason='all-children-settled', mechanical=True,
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
        if not registered(s, child):  # the parent's exclusions hold for every child: the Ledger carries the ones a child does not restate
            child['scope']['out'] = list(child['scope'].get('out', [])) + [line for line in parent['scope']['out'] if line not in child['scope'].get('out', [])]
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
    standard(s, parent, children, plan)
    if (s.get('behavior_contract_required') or any(c.get('behavior_review') for c in children)) \
            and not all(registered(s, child) for child in children):
        inside = {parent['module_id'], *ids, *parent.get('children', [])}
        behavior_contract.independence(parent, children, graph, plan, {
            cid for mid, module in {**s.get('module_groups', {}), **s['modules']}.items() if mid not in inside
            for cid in behavior_contract.accepts(module)}, {child['module_id'] for child in children if not registered(s, child)})
    return children, graph


def applicable(ref, module_id):
    """The dimensions an analysis finds applicable and gives items."""
    data, items = dimensions.load(ref, module_id)
    return {row['dimension'] for row in data.get('dimensions', []) if row.get('status') == 'applicable' and row.get('items')}


def standard(s, parent, children, plan, record=True):
    """The slicing standard: a leaf is a sub-business flow - the screens a user crosses to one outcome with the Logic, Adhesive
    and Resource items behind them - a scaffold is the shell they plug into, features depend on scaffolds only, and a feature
    leaf holds LEAF_MIN_CASES..LEAF_MAX_CASES cases. A wide leaf and a parent of many feature leaves are recorded as facts
    (`record`); a split without dimension analyses is judged on its kinds and dependencies alone."""
    import issues
    scaffolds = {c['module_id'] for c in children if c.get('kind') == 'scaffold'}
    features = [c for c in children if c.get('kind') != 'scaffold' and not registered(s, c)]
    if record and len(features) > FEATURE_LEAVES:
        issues.record(s, 'SLICE-%s-features' % parent['module_id'], 'fact', '%s splits into %d feature leaves (over %d): a flow is one leaf, its screens are tasks'
                      % (parent['module_id'], len(features), FEATURE_LEAVES), [parent['module_id']], issues.LEDGER, resolved={parent['module_id']: {'by': issues.LEDGER, 'recorded': True}})
    ids = {c['module_id'] for c in children}
    parent_dims = applicable(parent['dimension_analysis_ref'], parent['module_id']) \
        if s.get('dimension_slicing_required') and parent.get('dimension_analysis_ref') else set()
    for child in children:
        if registered(s, child):
            continue
        require(child.get('kind') in (None, *KINDS), 'unknown child kind: feature or scaffold')
        require(set(child.get('dependencies', [])) & ids <= scaffolds, 'a leaf depends only on scaffold leaves; features do not depend on each other')
        if child.get('kind') == 'scaffold':
            import target_profile
            require(target_profile.shell_missing(s, parent) is not False,
                    'a scaffold is set only where the target profile says the shell is missing (absent or shell-only)')
            continue
        cases = len(child['case_ids'])
        require(cases <= LEAF_MAX_CASES, 'a leaf holds at most %d cases: split it by sub-flow' % LEAF_MAX_CASES)
        require(cases >= LEAF_MIN_CASES or len(parent.get('case_ids') or []) < LEAF_MIN_CASES,  # a parent with fewer cannot give three
                'a leaf holds at least %d cases: merge it into the flow it belongs to; a screen is a task' % LEAF_MIN_CASES)
        if record and cases > LEAF_CASES:
            issues.record(s, 'SLICE-%s-wide' % child['module_id'], 'fact', '%s holds %d cases (over %d): consider a split by sub-flow' % (child['module_id'], cases, LEAF_CASES),
                          [parent['module_id']], issues.LEDGER, resolved={parent['module_id']: {'by': issues.LEDGER, 'recorded': True}})
        if parent_dims and child.get('dimension_analysis_ref'):
            dims = applicable(child['dimension_analysis_ref'], child['module_id'])
            if 'UI' in parent_dims:
                anchor = child.get('anchor_ui')
                anchored = isinstance(anchor, str) and anchor.strip() or isinstance(anchor, list) and anchor and all(isinstance(x, str) and x.strip() for x in anchor)
                require('UI' in dims and anchored, 'a feature leaf anchors on a UI surface: declare anchor_ui (the flow\'s screens) and UI items, or mark the child scaffold')
            if len(parent_dims) >= 2:
                require(len(dims) >= 2, 'a leaf is not a single layer: it carries the Logic, Adhesive and Resource items behind its UI, or is a scaffold')
    bound(s, parent, children, plan, record)


def node_features(features, paths):
    """The features at or below the feature-tree nodes `paths` name: a node is a functional_path, its subtree the paths under it."""
    return {fid for fid, f in features.items()
            if any(f.get('functional_path') == p or str(f.get('functional_path') or '').startswith(p + '/') for p in paths)}


def bound(s, parent, children, plan, record=True):
    """The slices and the cases come from one inventory: a functional leaf is one or more nodes of the feature tree the split
    cuts (plan.feature_inventory_ref), holds the features at or below its nodes and exactly their cases; leaves do not share
    a feature and together hold every feature of the parent; a scaffold holds none. Over a supplied test summary a leaf
    anchors on at least one feature the supplied cases cover, and what it holds beyond them is recorded as a fact."""
    import issues
    ref = plan.get('feature_inventory_ref') or parent.get('feature_inventory_ref')  # the root's inventory unless the split names one
    if not ref:
        require(not s.get('context_readiness_required') or any(registered(s, c) for c in children),
                'a split names the feature inventory it cuts: feature_inventory_ref on the root or the plan')
        return
    inventory = read_json(check_ref(ref))
    features = keyed(inventory.get('features'), 'feature_id')
    parent_cases = set(parent.get('case_ids') or [])
    mine = {fid: f for fid, f in features.items() if parent_cases.intersection(f.get('case_ids') or [])}
    for fid, f in mine.items():
        require(set(f['case_ids']) <= parent_cases, 'feature %s reaches outside the parent: a feature belongs to one root' % fid)
    supplied = {fid for u in inventory.get('source_units') or [] if u.get('kind') == 'test-case-group' for fid in u.get('feature_ids') or []} \
        if inventory.get('test_summary_ref') else None
    held = {}
    for child in children:
        paths = child.get('functional_paths')
        if child.get('kind') == 'scaffold':
            require(not paths, 'a scaffold holds no feature-tree node: it is the shell the flows plug into')
            continue
        require(isinstance(paths, list) and paths and all(isinstance(p, str) and p.strip() for p in paths),
                'a feature leaf names its feature-tree nodes: functional_paths')
        found = node_features(mine, paths)
        require(found, '%s names no feature of the parent: functional_paths are nodes of the feature tree under it' % child['module_id'])
        for fid in sorted(found):
            require(fid not in held, 'feature %s is held by %s and %s: leaves do not overlap' % (fid, held.get(fid), child['module_id']))
            held[fid] = child['module_id']
        require({cid for fid in found for cid in mine[fid]['case_ids']} <= set(child.get('case_ids') or []),
                "%s accepts exactly the cases of the features it holds: its case_ids are not its nodes' cases" % child['module_id'])
        if supplied is not None:
            require(found & supplied, '%s holds only features derived from source: merge them into the flow of the supplied cases they extend, '
                    'or take them to boundary review' % child['module_id'])
            derived = sorted(found - supplied)
            if record and derived:
                issues.record(s, 'SLICE-%s-derived' % child['module_id'], 'fact', '%s holds %d features found in source beyond the supplied cases: %s'
                              % (child['module_id'], len(derived), ', '.join(derived)), [parent['module_id']], issues.LEDGER,
                              resolved={parent['module_id']: {'by': issues.LEDGER, 'recorded': True}})
    carried = carriers(mine, held, children)
    for child in children:
        if child.get('kind') == 'scaffold':
            continue
        own = {cid for fid, mid in held.items() if mid == child['module_id'] for cid in mine[fid]['case_ids']}
        rides = {cid for fid in carried.get(child['module_id'], ()) for cid in mine[fid]['case_ids']}
        require(set(child.get('case_ids') or []) <= own | rides,
                "%s accepts exactly the cases of the features it holds: its case_ids are not its nodes' cases" % child['module_id'])
        if record and carried.get(child['module_id']):
            issues.record(s, 'SLICE-%s-carried' % child['module_id'], 'fact', '%s carries %s: no node of their own, their cases are on its flow'
                          % (child['module_id'], ', '.join(sorted(carried[child['module_id']]))), [parent['module_id']], issues.LEDGER,
                          resolved={parent['module_id']: {'by': issues.LEDGER, 'recorded': True}})


def carriers(features, held, leaves, strict=True):
    """{leaf: features it carries}: a feature no leaf names - a failure, cancel or retry outcome with no node of its own -
    rides with the one leaf that lists all its cases; one that no leaf, or more than one, lists stays without a leaf."""
    carried = {}
    for fid in sorted(set(features) - set(held)):
        holders = [leaf['module_id'] for leaf in leaves if leaf.get('kind') != 'scaffold'
                   and set(features[fid].get('case_ids') or []) <= set(leaf.get('case_ids') or [])]
        require(len(holders) == 1 or not strict, 'features without a leaf: %s; list its cases on the leaf of the flow it belongs to' % fid)
        if len(holders) == 1:
            carried.setdefault(holders[0], set()).add(fid)
    return carried


def task_shape_facts(s, mid, plan, sequence=None):
    """Record, once per module, that most of a plan's behaviour paths bind at least half of its tasks: tasks cut by layer,
    none of which a path can verify alone. A fact for the trace and the audit, never a gate."""
    import issues
    tasks = plan.get('tasks') or []
    paths = [p['path_id'] for p in plan.get('paths') or [] if p.get('kind', 'automation') == 'automation']
    if len(tasks) < 2 or not paths or 'SLICE-%s-tasks-by-layer' % mid in s.get('issues', {}):
        return
    held = {}
    for task in tasks:
        for pid in task.get('path_ids') or []:
            held[pid] = held.get(pid, 0) + 1
    shared = [pid for pid in paths if held.get(pid, 0) * 2 >= len(tasks)]
    if len(shared) * 2 >= len(paths):
        issues.record(s, 'SLICE-%s-tasks-by-layer' % mid, 'fact', '%s: %d of %d behaviour paths bind at least half of its %d tasks - tasks cut by layer, '
                      'none verifiable on its own; cut tasks by behaviour, each with paths of its own' % (mid, len(shared), len(paths), len(tasks)),
                      [mid], issues.LEDGER, sequence=sequence, resolved={mid: {'by': issues.LEDGER, 'recorded': True}})


def slicing_signals(s):
    """What the audit reads back about the split: per leaf, the issues it shares with other modules, its change requests
    and the depth of its provider chain; a flag names the bound a leaf exceeds."""
    modules = s['modules']
    def depth(mid, seen=()):
        deps = [d for d in modules.get(mid, {}).get('dependencies', []) if d in modules and d not in seen]
        return 1 + max([depth(d, (*seen, mid)) for d in deps] or [0])
    out = {}
    for mid, m in modules.items():
        cross = sum(1 for it in (s.get('issues') or {}).values() if mid in (it.get('applies_to') or []) and len(it.get('applies_to') or []) > 1)
        crs = len(m.get('change_request_history') or []) + (1 if m.get('change_request') else 0)
        chain = depth(mid)
        large = sorted(tid for tid, files in (m.get('task_files') or {}).items() if len(files) > TASK_FILES)
        wide = len(m.get('case_ids', [])) > LEAF_CASES and m.get('kind') != 'scaffold'
        flags = [name for name, hit in (('cross-module-issues', cross > 3), ('change-request-cascade', crs > 1), ('chain-depth', chain > 2),
                                        ('large-tasks', bool(large)), ('wide-leaf', wide)) if hit]
        out[mid] = {'cross_module_issues': cross, 'change_requests': crs, 'chain_depth': chain, 'large_tasks': large, 'flags': flags}
    for pid, group in (s.get('module_groups') or {}).items():
        n = sum(1 for cid in group.get('children', []) if modules.get(cid, {}).get('kind') != 'scaffold')
        out[pid] = {'feature_leaves': n, 'flags': ['many-features'] if n > FEATURE_LEAVES else []}
    return out


def task_size_facts(s, mid, trace, sequence=None):
    """Record, once per task, that a version of it touched more than TASK_FILES files: a fact for the trace and the audit,
    settled as it is recorded - the first version goes on, the split is the MO's call."""
    import issues
    for row in trace:
        files = row.get('files') or []
        if len(files) > TASK_FILES:
            issues.record(s, 'SIZE-%s-%s' % (mid, row['task_id']), 'fact',
                          'task %s touched %d files in one version (over %d): a smaller task is easier to verify and to adjust' % (row['task_id'], len(files), TASK_FILES),
                          [mid], issues.LEDGER, resolved={mid: {'by': issues.LEDGER, 'recorded': True}}, sequence=sequence)


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


def boundary_kept(old, new, dependencies, inherited=()):
    """Nothing a leaf was already asked for is taken away: every statement of its scope, its requirements, cases, accepted
    cases and write scope stay inside the revised allocation, no exclusion is added and it depends on the same slices.
    A reworded scope statement cannot be told from a moved one, so it does not count as kept. An exclusion the parent
    now states for every child (`inherited`) narrows the parent, not this child: it is carried, not counted."""
    import behavior_contract
    inside = lambda path: any(Path(path).resolve().is_relative_to(Path(scope).resolve()) for scope in new['write_paths'])
    return (set(old['scope']['in']) <= set(new['scope']['in'])
            and set(old['scope']['requirement_ids']) <= set(new['scope']['requirement_ids'])
            and set(old['case_ids']) <= set(new['case_ids'])
            and set(behavior_contract.accepts(old)) <= set(behavior_contract.accepts(new))
            and all(inside(path) for path in old['write_paths'])
            and set(new['scope']['out']) - set(old['scope']['out']) <= set(inherited)
            and set(dependencies) == set(old['dependencies']))


def revisable(old, new, dependencies, inherited=()):
    """A frozen, unblocked leaf whose boundary a revision keeps: it takes the revision as a change to its contract and
    keeps its code. Any other leaf the revision changes plans again from its new allocation."""
    return bool(old.get('freeze_id')) and not old.get('blocked') and boundary_kept(old, new, dependencies, inherited)


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
    inherited = (parent.get('scope') or {}).get('out') or []  # what the parent now excludes for every child
    revised = {cid for cid in changed if revisable(s['modules'][cid], new[cid], graph[cid], inherited)}
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
        from contracts import marked
        require(not marked(p.get('plan_ref')), 'unfilled skeleton field left in ' + Path(p['plan_ref']['path']).name)
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
            parent.update(decomposition_required=False, leaf_review_ref=plan['leaf_review_ref'])
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
