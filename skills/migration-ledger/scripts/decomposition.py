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


# The only parts of the planning context a reviewed source append changes for a module that keeps its frozen plan.
SOURCE_KEYS = ('project_context_ref', 'reuse_sources', 'source_change_ref')
STALE_CONTEXT = 'planning requires current global code/architecture/knowledge/allocation context'


def context_binding(s, module):
    """Digests of the global context and the allocation a plan or split proposal was accepted under.

    Authors do not copy either object into their document: the Ledger binds what is current at
    acceptance and compares these digests whenever the document is used again."""
    context = planning_context(s)
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
    if group.get('redecomposition_submission'):
        step.update(operation='redecompose-accept', role='global-orchestrator', ready=True,
                    reason='redecomposition-proposal-ready')
        return step
    realloc_reqs = [mid for mid in group['children'] if mid in s['modules'] and (
        s['modules'][mid].get('realloc_request') or s['modules'][mid].get('phase') == 'waiting-upstream'
    )]
    if realloc_reqs:
        step.update(operation='redecompose', ready=True, role='module-orchestrator',
                    reason='child-reallocation-requested',
                    affected_children=realloc_reqs)
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


def validate(s, parent, plan, redecompose=False):
    from ledger import new_module
    require(plan.get('parent_module_id') == parent['module_id'], 'decomposition parent mismatch')
    require(plan.get('rationale'), 'functional decomposition rationale required')
    check_scope(parent)
    children = nonempty(plan.get('children'), 'submodules')
    ids = [c.get('module_id') for c in children]
    require(len(set(ids)) == len(ids), 'duplicate child module')
    existing_all = set(s['modules']) | set(s.get('module_groups', {}))
    allowed_existing = set(parent.get('children', [])) if redecompose else set()
    conflicts = (set(ids) & existing_all) - allowed_existing
    require(not conflicts, 'child module id already exists')
    cases, requirements = set(), set()
    for child in children:
        require(child.get('name'), 'child functional name required')
        new_module(child)
        check_scope(child)
        if s.get('behavior_contract_required'):
            import behavior_contract
            behavior_contract.review(child, child.get('behavior_review'))
        require(not child.get('decomposition_required') and not child.get('parent_module_id'),
                'child MO decomposes tasks; child hierarchy is assigned by GO acceptance')
        require(set(child['scope']['requirement_ids']) <= set(parent['scope']['requirement_ids']),
                'child requirements outside parent scope')
        require(set(parent['scope']['out']) <= set(child['scope']['out']), 'child must retain parent exclusions')
        require(set(child['case_ids']) <= set(parent['case_ids']), 'child cases outside selected function')
        require(all(any(Path(path).resolve().is_relative_to(Path(scope).resolve())
                        for scope in parent['write_paths']) for path in child['write_paths']), 'child write scope outside parent')
        require(set(child.get('dependencies', [])) <= set(ids) | set(parent['dependencies']), 'child dependency outside approved parent boundary')
        cases.update(child['case_ids'])
        requirements.update(child['scope']['requirement_ids'])
    require(cases == set(parent['case_ids']), 'submodules must cover every parent case')
    require(requirements == set(parent['scope']['requirement_ids']), 'submodules must cover every parent requirement')
    dimensions.partition(s, parent, plan)
    old_child_ids = set(parent.get('children', [])) if redecompose else set()
    graph = {mid: list(m['dependencies']) for mid, m in s['modules'].items() if mid != parent['module_id'] and mid not in old_child_ids}
    for mid, deps in graph.items():
        graph[mid] = sorted((set(deps) - {parent['module_id']}) | (set(ids) if parent['module_id'] in deps else set()))
    for child in children:
        graph[child['module_id']] = sorted(set(child.get('dependencies', [])) | set(parent['dependencies']))
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
    return children, graph


def handle(s, req, actor):
    from ledger import idle, new_module, role
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
        m = s['modules'][mid]
        parent_id = m.get('parent_module_id')
        require(parent_id and parent_id in s.get('module_groups', {}), 'realloc-request requires a parent module')
        idle(m)
        reason = p.get('reason')
        require(isinstance(reason, str) and bool(reason.strip()), 'realloc-request reason required')
        evidence_refs = nonempty(p.get('evidence_refs'), 'realloc-request evidence required')
        for ref in evidence_refs:
            check_ref(ref)
        m['realloc_request'] = {'reason': reason, 'evidence_refs': evidence_refs,
                                'actor_instance_id': actor['instance_id'], 'status': 'pending'}
        m['phase'] = 'waiting-upstream'
        m['revision'] += 1
        return
    if op == 'redecompose':
        role(actor, 'module-orchestrator')
        parent = s.get('module_groups', {}).get(mid)
        require(parent, 'redecompose requires a parent module group')
        for child_id in parent['children']:
            if child_id in s['modules']:
                require(all(a.get('closed') for a in s['modules'][child_id]['assignments'].values()),
                        'finish or stop/revoke child workers before redecompose')
        plan = read_json(check_ref(p.get('plan_ref')))
        validate(s, parent, plan, redecompose=True)
        parent['redecomposition_submission'] = {'plan_ref': p['plan_ref'], 'actor_instance_id': actor['instance_id'],
                                                'binding': context_binding(s, parent)}
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
        affected_ids = set(added_ids)

        for cid in common_ids:
            old_mod = s['modules'][cid]
            new_spec = new_children[cid]
            changed = (old_mod.get('scope') != new_spec.get('scope') or
                       set(old_mod.get('case_ids', [])) != set(new_spec.get('case_ids', [])) or
                       old_mod.get('write_paths') != new_spec.get('write_paths') or
                       graph[cid] != old_mod.get('dependencies', []))
            if changed:
                affected_ids.add(cid)
                from ledger import reset_plan
                reset_plan(old_mod, reason='parent-redecomposed', evidence_ref=submission['plan_ref'])
                old_mod['scope'] = copy.deepcopy(new_spec['scope'])
                old_mod['case_ids'] = copy.deepcopy(new_spec['case_ids'])
                old_mod['write_paths'] = copy.deepcopy(new_spec['write_paths'])
                old_mod['dependencies'] = graph[cid]
                if 'context_refs' in new_spec:
                    old_mod['context_refs'] = copy.deepcopy(new_spec['context_refs'])
                old_mod['phase'] = 'specifying'
                old_mod.pop('realloc_request', None)
                old_mod['revision'] += 1
            else:
                old_mod['dependencies'] = graph[cid]
                old_mod['allocation_continuation'] = {
                    'plan_hash': old_mod.get('plan_hash'),
                    'review_ref': p['review_ref']
                }
                old_mod.pop('realloc_request', None)
                old_mod['revision'] += 1

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
            if m_id not in new_child_ids:
                if any(dep in (affected_ids | retired_ids) for dep in mod.get('dependencies', [])):
                    if mod.get('plan'):
                        from ledger import reset_plan
                        reset_plan(mod, reason='upstream-dependency-redecomposed', evidence_ref=submission['plan_ref'])
                    mod['phase'] = 'specifying'
                    mod['revision'] += 1
                elif mod.get('dependencies') != graph.get(m_id, mod.get('dependencies')):
                    mod['dependencies'] = graph[m_id]
                    mod['revision'] += 1

        parent['children'] = [c['module_id'] for c in children]
        parent['decomposition_ref'] = submission['plan_ref']
        parent['decomposition_review_ref'] = p['review_ref']
        parent.pop('redecomposition_submission', None)
        parent.pop('summary_ref', None)
        parent.pop('summary_subject', None)
        parent['revision'] += 1

        s.setdefault('redecomposition_history', []).append({
            'parent_module_id': mid,
            'plan_ref': submission['plan_ref'],
            'review_ref': p['review_ref'],
            'affected_modules': sorted(affected_ids),
            'retired_modules': sorted(retired_ids),
            'added_modules': sorted(added_ids),
            'triggering_requests': triggers
        })
        s['global_plan'] = None
        s['audit'] = {}
        return
    parent = s['modules'][mid]
    require(not parent.get('parent_module_id'), 'child MO decomposes tasks, not another MO hierarchy')
    idle(parent)
    require(parent['phase'] in ('context', 'specifying', 'clarifying') and
            not parent.get('freeze_id') and not parent.get('code_files') and not parent.get('blocked'),
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
        children, graph = validate(s, parent, read_json(check_ref(submission['plan_ref'])))
        del s['modules'][mid]
        parent.update(kind='parent-module', phase='coordinating', children=[c['module_id'] for c in children],
                      decomposition_ref=submission['plan_ref'], decomposition_review_ref=p['review_ref'])
        s.setdefault('module_groups', {})[mid] = parent
        for child in children:
            child = copy.deepcopy(child)
            child.update(parent_module_id=mid, dependencies=graph[child['module_id']])
            s['modules'][child['module_id']] = new_module(child)
        for leaf_id, module in s['modules'].items():
            if module['dependencies'] != graph[leaf_id]:
                module['dependencies'] = graph[leaf_id]
                module['revision'] += 1
        s['global_plan'] = None
        s['audit'] = {}

