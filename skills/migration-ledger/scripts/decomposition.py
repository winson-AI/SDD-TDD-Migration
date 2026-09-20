"""MO-owned functional decomposition, GO registration review, and parent summaries.

Executable leaves stay in modules; coordinating parents stay in module_groups.
This keeps code/test evidence owned by exactly the MO that executed the leaf.
"""
import copy
import reuse
from pathlib import Path

from contracts import Rejected, check_ref, digest, nonempty, read_json, require

OPERATIONS = {'decompose', 'decompose-accept', 'module-summary'}
TERMINAL = {'completed', 'waiting-auditor', 'waiting-dependency', 'waiting-human', 'automation-deferred'}


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
    plan = (s.get('global_plan') or {}).get('content', {})
    if plan.get('feature_inventory_ref'):
        result.update(feature_inventory_ref=plan['feature_inventory_ref'], feature_owners=plan['feature_owners'])
    return result


def check_planning_context(s, plan):
    require(plan.get('planning_context') == planning_context(s),
            'planning requires current global code/architecture/knowledge/allocation context')


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
    plan = (s.get('global_plan') or {}).get('content', {})
    if plan.get('feature_inventory_ref'):
        result['feature_inventory_ref'] = copy.deepcopy(plan['feature_inventory_ref'])
        owned = set(leaves(s, module['module_id'])) if module['module_id'] in s.get('module_groups', {}) else {module['module_id']}
        result['feature_ids'] = sorted(fid for fid, owners in plan['feature_owners'].items() if owned.intersection(owners))
    return result


def check_assignment(s, module, plan):
    check_scope(module)
    parent = s.get('module_groups', {}).get(module.get('parent_module_id'))
    if parent:
        check_scope(parent)
    require(plan.get('assigned_module') == assigned_module(s, module),
            'planning must acknowledge current assigned module scope and context')


def check_module_plan(s, module, plan):
    check_planning_context(s, plan)
    check_assignment(s, module, plan)
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


def summary_current(s, group):
    if any(s['modules'][mid].get('effective_quality') == 'yellow-blocked' for mid in leaves(s, group['module_id'])):
        return False
    if group.get('summary_subject') != summary_subject(s, group):
        return False
    try:
        check_ref(group.get('summary_ref'))
        return True
    except (Rejected, OSError):
        return False


def group_step(s, group):
    from ledger import current, next_step
    step = {'module_id': group['module_id'], 'phase': group['phase'],
            'expected_revision': group['revision'], 'operation': None,
            'role': 'module-orchestrator', 'agent_name': 'parent-mo-' + group['module_id'],
            'ready': False, 'reason': 'await-child-modules'}
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
        if mid in s.get('module_groups', {}) and not summary_current(s, s['module_groups'][mid]):
            return step
    if summary_current(s, group):
        step['reason'] = 'parent-summary-current'
    else:
        step.update(operation='module-summary', ready=True, reason='all-children-settled',
                    payload={'subject_sha256': summary_subject(s, group)})
    return step


def refresh_groups(s):
    for group in s.get('module_groups', {}).values():
        children = [s['modules'][mid] for mid in leaves(s, group['module_id'])]
        green = bool(children) and all(m['quality'] == 'green-passed' for m in children)
        group['quality'] = ('red-bug' if any(m['quality'] == 'red-bug' for m in children)
                            else 'green-passed' if green and summary_current(s, group) else 'yellow-blocked')
        group['phase'] = ('completed' if green else 'waiting-auditor') if summary_current(s, group) else 'coordinating'


def validate(s, parent, plan):
    from ledger import new_module
    require(plan.get('parent_module_id') == parent['module_id'], 'decomposition parent mismatch')
    require(plan.get('rationale'), 'functional decomposition rationale required')
    check_planning_context(s, plan)
    check_assignment(s, parent, plan)
    children = nonempty(plan.get('children'), 'submodules')
    ids = [c.get('module_id') for c in children]
    require(len(set(ids)) == len(ids), 'duplicate child module')
    require(not set(ids).intersection(set(s['modules']) | set(s.get('module_groups', {}))), 'child module id already exists')
    cases, requirements = set(), set()
    for child in children:
        require(child.get('name'), 'child functional name required')
        new_module(child)
        check_scope(child)
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
    graph = {mid: list(m['dependencies']) for mid, m in s['modules'].items() if mid != parent['module_id']}
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
        parent['decomposition_submission'] = {'plan_ref': p['plan_ref'], 'actor_instance_id': actor['instance_id']}
    else:
        role(actor, 'global-orchestrator')
        submission = parent.get('decomposition_submission')
        require(submission, 'MO decomposition proposal required')
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
