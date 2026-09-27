"""ui_fidelity_required enforcement: exact UI/resource evidence before freeze, none Green while blocked.

Off by default (backward-compatible). When enabled at init/prepare, freezing a module whose
four-dim analysis has applicable UI items requires:

- each applicable UI item carries a ui-component-spec model bound to ui_evidence (extracted,
  structurally validated ui_tree_ref + page:state:coverage);
- the resource closure is not reduced: every presentation reference the UI trees declare,
  including code-owned runtime overrides, is covered by a Resource item;
- the source closure names the renderers that mutate visible state (a layout alone is incomplete).

Completion additionally refuses a module that still carries an explicitly `blocked` resource, so an
inexact resource can never be reported as Green. Visual parity itself is enforced at implementation
by semantics.implementation (visual_alignment).
"""
import dimensions
import resource_fidelity
import semantics
import ui_tree
from contracts import check_ref, read_json, require


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
                refs.extend(ui_tree.resource_refs(read_json(check_ref(evidence['ui_tree_ref']))))
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
        renderers = ((m.get('plan') or {}).get('source_closure') or {}).get('ui_renderers')
        require(isinstance(renderers, list) and renderers,
                'ui_fidelity_required: source_closure.ui_renderers must name the renderers that mutate visible state')


def completion_gate(s, m):
    """An explicitly blocked (inexact) resource can never be recorded as Green."""
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    stuck = resource_fidelity.blocked(analysis)
    require(not stuck, 'ui_fidelity_required: blocked resources cannot complete as Green: ' + ', '.join(stuck))
