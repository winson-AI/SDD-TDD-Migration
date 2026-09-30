"""ui_fidelity_required enforcement: exact UI/resource evidence before freeze, none Green while blocked.

Off by default (backward-compatible). When enabled at init/prepare, freezing a module whose
four-dim analysis has applicable UI items requires:

- each applicable UI item carries a ui-component-spec model bound to ui_evidence (extracted,
  structurally validated ui_tree_ref + page:state:coverage);
- the resource closure is not reduced: every presentation reference the UI trees declare,
  including code-owned runtime overrides, is covered by a Resource item;
- the source closure names the renderers that mutate visible state (a layout alone is incomplete).

Completion additionally refuses a module that still carries an explicitly `blocked` resource, so an
inexact resource can never be reported as Green. Visual parity itself is a test-stage verdict: the
visual automation layer aligns baseline nodes and reports three-state like any other path.
"""
import dimensions
import resource_fidelity
import semantics
import ui_evidence as ue
from contracts import check_ref, nonempty, read_json, require


def _analysis(m):
    ref = (m.get('plan') or {}).get('dimension_analysis_ref')
    return dimensions.load(ref, m['module_id'])[0] if ref else None


def _declared_refs(analysis):
    """Presentation references collected from every UI item's frozen UI tree."""
    refs = []
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            evidence = (item.get('semantic_model') or {}).get('ui_evidence')
            if evidence:
                refs.extend(ue.resource_refs(read_json(check_ref(evidence['ui_tree_ref']))))
    return sorted(set(refs))


def freeze_gate(s, m):
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    gaps = semantics.ui_fidelity_gaps(analysis)
    require(not gaps, 'ui_fidelity_required: UI items lack capture-bound ui_evidence before freeze: ' + ', '.join(gaps))
    declared_refs = _declared_refs(analysis)
    uncovered = resource_fidelity.closure_gaps(analysis, declared_refs,
                                              strict=s.get('evidence_contract_version', 1) >= 2)
    require(not uncovered, 'ui_fidelity_required: resource closure reduced; uncovered presentation refs: ' + ', '.join(uncovered))
    if s.get('evidence_contract_version', 1) >= 2:
        resource_fidelity.require_exact_closure(analysis, declared_refs, s.get('legacy_root'))
    if any(row.get('dimension') == 'UI' and row.get('status') == 'applicable' for row in analysis.get('dimensions', [])):
        closure = ((m.get('plan') or {}).get('source_closure') or {})
        renderers = closure.get('ui_renderers')
        require(isinstance(renderers, list) and renderers,
                'ui_fidelity_required: source_closure.ui_renderers must name the renderers that mutate visible state')
        # A prose widget list is not a closure. Topology, the presentation states that actually exist,
        # navigation identity/back behaviour and the platform/lifecycle surface each need evidence.
        # Resources are covered more strictly by the unreduced-closure check above.
        for facet in ('ui_topology', 'states', 'navigation', 'platform_lifecycle'):
            require(closure.get(facet),
                    'ui_fidelity_required: source_closure.' + facet + ' required for UI scope')
    baseline_gate(s, m)


def runtime_targets(analysis):
    """page:state:coverage targets whose legacy screen is previewable, so a baseline exists."""
    targets = []
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            evidence = (item.get('semantic_model') or {}).get('ui_evidence')
            if evidence and evidence.get('visual_mode') == 'runtime':
                targets.append(evidence['coverage'])
    return sorted(set(targets))


def declared_interactions(analysis):
    found = []
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item.get('semantic_model')
            if model:
                found.extend(ue.validate_interactions(model))
    return sorted(set(found))


def frozen_interaction(module, path):
    """Derive the PATH's full requirement from frozen SPEC; audit scopes carry the same value."""
    if (module.get('evidence_contract_version', 1) < 2 or
            path.get('kind') not in ('automation', 'visual') or not path.get('interaction_id')):
        return None
    iid = path['interaction_id']
    if not (module.get('plan') or {}).get('dimension_analysis_ref') and 'frozen_interactions' in module:
        # This map is assembled by Ledger.audit_scope from each owning module.
        require(module.get('module_id') in (None, 'GLOBAL'), 'module interaction requires frozen UI dimension evidence')
        item = module['frozen_interactions'].get(path['path_id'])
        require(item and item.get('id') == iid, 'audit visual path lacks its frozen interaction')
        return ue.interaction_contract(item)
    analysis = _analysis(module)
    require(analysis, 'visual interaction requires frozen UI dimension evidence')
    matches = [ue.interaction_contract(item) for row in analysis.get('dimensions', [])
               if row.get('dimension') == 'UI' and row.get('status') == 'applicable'
               for ui_item in row.get('items', [])
               for item in (ui_item.get('semantic_model') or {}).get('interactions', []) if item.get('id') == iid]
    require(matches and all(item == matches[0] for item in matches), 'missing/conflicting frozen interaction: ' + iid)
    return matches[0]


def baseline_gate(s, m):
    """Legacy executability is decided before freeze and drives SPEC/coding inputs.

    Previewable legacy screens contribute captured baseline screenshots that guide the SPEC and the
    Implementer, and are later compared node-by-node in the visual test stage. A legacy screen that
    cannot be previewed falls back to retained UI source, but still owes the four-dimension UI
    intermediate representation, so coding is never guided by prose alone.
    """
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    plan = m.get('plan') or {}
    visual = [path for path in plan.get('paths', []) if path.get('kind') == 'visual']
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            evidence = ((item.get('semantic_model') or {}).get('ui_evidence')) or {}
            executable = evidence.get('legacy_executable')
            require(isinstance(executable, bool),
                    'legacy executability must be decided before freeze for ' + item['item_id'])
            if executable:
                require(evidence.get('visual_mode') == 'runtime',
                        'a previewable legacy screen must carry runtime baseline evidence: ' + item['item_id'])
                for ref in nonempty(evidence.get('baseline_refs'), 'baseline screenshots for ' + item['item_id']):
                    check_ref(ref)
            else:
                require(evidence.get('visual_mode') == 'source-only',
                        'a non-previewable legacy screen falls back to source-only: ' + item['item_id'])
    covered = {node for path in visual for node in path.get('node_ids', [])}
    for target in runtime_targets(analysis):
        require(visual, 'baseline target ' + target + ' needs a visual test path aligning its nodes')
    require(not runtime_targets(analysis) or covered,
            'visual paths must name the UI-tree nodes they align')
    declared = declared_interactions(analysis)
    interaction_paths = ([path for path in plan.get('paths', []) if path.get('kind') in ('automation', 'visual')]
                         if s.get('evidence_contract_version', 1) >= 2 else visual)
    proven = {path.get('interaction_id') for path in interaction_paths}
    missing = sorted(set(declared) - proven)
    require(not missing, 'declared interactions need an automation/visual path carrying device proof: ' + ', '.join(missing))
    if s.get('evidence_contract_version', 1) >= 2:
        for path in plan.get('paths', []):
            if not path.get('interaction_id'):
                continue
            require(path.get('kind') in ('automation', 'visual'), 'interaction requires an automation/visual path')
            interaction = frozen_interaction({**m, 'evidence_contract_version': 2}, path)
            if path.get('coverage'):
                require(path['coverage'].split(':')[:2] ==
                        [interaction['from']['page_id'], interaction['from']['state_id']],
                        'interaction path must use its declared starting page/state')
        visual_plan_gate(analysis, visual)


def visual_plan_gate(analysis, visual):
    """Bind each visual path to its own frozen target, screenshots and observed tree nodes."""
    targets, interactions = {}, {}
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item['semantic_model']
            evidence = model['ui_evidence']
            tree = ue.validate_native_evidence(evidence)
            for interaction in model.get('interactions', []):
                require(interaction['id'] not in interactions or interactions[interaction['id']] == interaction,
                        'conflicting declared interaction: ' + interaction['id'])
                interactions[interaction['id']] = interaction
            if evidence['visual_mode'] != 'runtime':
                continue
            coverage = evidence['coverage']
            page, state, _ = coverage.split(':')
            nodes = ue.target_node_ids(tree, page, state)
            require(nodes, 'runtime UI target has no observed tree nodes: ' + coverage)
            target = targets.setdefault(coverage, {'nodes': set(), 'baselines': []})
            target['nodes'].update(nodes)
            target['baselines'].extend(evidence['baseline_refs'])
    covered = set()
    for path in visual:
        coverage = path.get('coverage')
        require(isinstance(coverage, str) and coverage in targets,
                'visual path coverage must name a frozen runtime UI target')
        target = targets[coverage]
        nodes = nonempty(path.get('node_ids'), 'visual path node_ids')
        require(set(nodes) <= target['nodes'], 'visual path nodes do not belong to target ' + coverage)
        require(path.get('baseline_ref') in target['baselines'],
                'visual path baseline differs from frozen target ' + coverage)
        check_ref(path['baseline_ref'])
        if path.get('interaction_id'):
            interaction = interactions.get(path['interaction_id'])
            require(interaction, 'visual path references an undeclared interaction')
            start = interaction['from']
            require(coverage.split(':')[:2] == [start['page_id'], start['state_id']],
                    'interaction visual path must use its declared starting page/state')
        covered.add(coverage)
    missing = sorted(set(targets) - covered)
    require(not missing, 'runtime UI targets lack visual paths: ' + ', '.join(missing))


def completion_gate(s, m):
    """An explicitly blocked (inexact) resource can never be recorded as Green."""
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    stuck = resource_fidelity.blocked(analysis)
    require(not stuck, 'ui_fidelity_required: blocked resources cannot complete as Green: ' + ', '.join(stuck))
