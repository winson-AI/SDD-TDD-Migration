"""ui_fidelity_required enforcement: a UI owner cannot freeze without capture-bound evidence.

Off by default (backward-compatible). When enabled at init/prepare, freezing a module whose
four-dim analysis has applicable UI items requires each such item to carry a ui-component-spec
model bound to ui_evidence (extracted ui_tree_ref + page:state:coverage). Visual parity itself
is enforced at implementation by semantics.implementation (visual_alignment). Together these make
"UI implemented from prose with no evidence" impossible to freeze or accept when the flag is on.
"""
import dimensions
import semantics
from contracts import require


def freeze_gate(s, m):
    if not s.get('ui_fidelity_required'):
        return
    ref = (m.get('plan') or {}).get('dimension_analysis_ref')
    if not ref:
        return
    data, _ = dimensions.load(ref, m['module_id'])
    gaps = semantics.ui_fidelity_gaps(data)
    require(not gaps, 'ui_fidelity_required: UI items lack capture-bound ui_evidence before freeze: ' + ', '.join(gaps))
