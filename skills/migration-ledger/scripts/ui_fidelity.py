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
    uncovered = resource_fidelity.closure_gaps(analysis, _declared_refs(analysis))
    require(not uncovered, 'ui_fidelity_required: resource closure reduced; uncovered presentation refs: ' + ', '.join(uncovered))
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
    proven = {path.get('interaction_id') for path in visual}
    missing = sorted(set(declared) - proven)
    require(not missing, 'declared interactions need a visual path carrying device proof: ' + ', '.join(missing))


def completion_gate(s, m):
    """An explicitly blocked (inexact) resource can never be recorded as Green."""
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    stuck = resource_fidelity.blocked(analysis)
    require(not stuck, 'ui_fidelity_required: blocked resources cannot complete as Green: ' + ', '.join(stuck))
