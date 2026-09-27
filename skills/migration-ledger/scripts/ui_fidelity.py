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


ALIGNED_OK = ('ALIGNED', 'ALIGNED_CARRIED')
TARGET_STATUS = ALIGNED_OK + ('NEEDS_UI_FIX', 'CAPTURE_BLOCKED', 'NEEDS_IMPLEMENTATION_FIX')
MAX_ALIGN_ROUNDS = 3


def runtime_targets(analysis):
    """page:state:coverage targets that owe visual parity (they carry runtime capture evidence)."""
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
    import interactions
    found = []
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item.get('semantic_model')
            if model:
                found.extend(interactions.validate_declarations(model))
    return sorted(set(found))


def alignment_pending(s, m):
    """After tests go Green, runtime UI targets still owe an independent visual comparison."""
    if not s.get('ui_fidelity_required'):
        return False
    analysis = _analysis(m)
    if analysis is None:
        return False
    return bool(runtime_targets(analysis)) and (m.get('alignment') or {}).get('status') != 'aligned'


def accept_alignment(s, m, result, result_ref):
    """Independent post-build parity round (lean Aligner semantics); returns the next phase."""
    import interactions
    analysis = _analysis(m)
    require(analysis is not None, 'alignment requires a frozen dimension analysis')
    targets = runtime_targets(analysis)
    require(targets, 'no runtime UI targets owe visual parity')
    require(result.get('schema_version') == 2, 'alignment result schema_version 2 required')
    rounds = m.get('alignment_rounds_used', 0) + 1
    require(rounds <= MAX_ALIGN_ROUNDS,
            'visual alignment budget exhausted; record the residual gap and hand to the Auditor')
    require(result.get('current_round') == rounds, 'alignment current_round must advance to ' + str(rounds))

    def key(target):
        return '{}:{}:{}'.format(target.get('page_id'), target.get('state_id'), target.get('coverage'))
    require(sorted({key(t) for t in result.get('required_targets', [])}) == targets,
            'alignment required_targets must equal the frozen UI coverage set')
    rows = {key(r): r for r in result.get('target_results', [])}
    missing = sorted(set(targets) - set(rows))
    require(not missing, 'alignment result missing targets: ' + ', '.join(missing))
    for name in targets:
        row = rows[name]
        require(row.get('status') in TARGET_STATUS, 'invalid alignment target status for ' + name)
        check_ref(row.get('evidence_ref'))
    m['alignment_rounds_used'] = rounds
    unaligned = sorted(name for name in targets if rows[name]['status'] not in ALIGNED_OK)
    if unaligned:
        # Route back to the owner for a narrow repair; the round is spent either way.
        m['alignment'] = {'status': 'needs-fix', 'result_ref': result_ref, 'round': rounds, 'unaligned': unaligned}
        return 'diagnosing'
    interactions.validate_checks(declared_interactions(analysis), result)
    m['alignment'] = {'status': 'aligned', 'result_ref': result_ref, 'round': rounds}
    return 'dod'


def completion_gate(s, m):
    """An explicitly blocked (inexact) resource can never be recorded as Green."""
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    stuck = resource_fidelity.blocked(analysis)
    require(not stuck, 'ui_fidelity_required: blocked resources cannot complete as Green: ' + ', '.join(stuck))
