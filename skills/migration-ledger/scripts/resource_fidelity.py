"""Exact-resource discipline absorbed from android-resources-to-cmp.

There is no `approximate` strategy: Material-icon substitution, hand redraw, semantic
approximation, automatic rasterization and bitmap fallback are forbidden. A Resource
dimension item declares one exact strategy that must agree with its Android source type;
`manual_exact` needs inspected adaptation evidence and `blocked` is an explicit gap that can
never count as Green. Closure may not be reduced to the convenient subset: every presentation
reference the UI tree declares (including code-owned runtime overrides) must be covered.
Structural gates only; exactness itself is reviewed by the owning agent.
"""
from contracts import check_ref, require

STRATEGIES = ('exact_vector_xml', 'byte_copy', 'value_xml_exact', 'design_token_exact',
              'compose_semantic_exact', 'manual_exact', 'blocked')
# Android source kind -> the normal exact strategy it must use.
NORMAL = {'vector': 'exact_vector_xml', 'bitmap': 'byte_copy', 'font': 'byte_copy', 'raw': 'byte_copy',
          'string': 'value_xml_exact', 'plurals': 'value_xml_exact', 'array': 'value_xml_exact',
          'color': 'design_token_exact', 'dimen': 'design_token_exact', 'attr': 'design_token_exact',
          'selector': 'compose_semantic_exact', 'layer-list': 'compose_semantic_exact',
          'shape': 'compose_semantic_exact'}
# Available for any kind only when exactness cannot be proven.
ESCAPES = ('manual_exact', 'blocked')


def validate_item(item):
    """Presence-triggered: an item declaring a strategy is held to the exact-resource rules."""
    strategy = item.get('resource_strategy')
    if strategy is None:
        return
    require(strategy in STRATEGIES, 'invalid resource strategy; approximation is not a strategy')
    kind = item.get('resource_kind')
    require(kind in NORMAL, 'resource_kind required, one of: ' + ', '.join(sorted(NORMAL)))
    if item.get('nine_patch'):
        # Byte-copying .9.png pixels never proves its stretch/content regions survive in CMP.
        require(strategy in ('compose_semantic_exact',) + ESCAPES,
                '.9.png needs compose_semantic_exact, manual_exact or blocked, never byte_copy')
    else:
        require(strategy in (NORMAL[kind],) + ESCAPES,
                kind + ' requires ' + NORMAL[kind] + ' (or an evidenced manual_exact/blocked)')
    if strategy == 'manual_exact':
        check_ref(item.get('adaptation_evidence_ref'))
    if strategy == 'blocked':
        require(item.get('blocked_reason'), 'blocked resource needs an explicit reason')
    # An Android sp dimension consumed by spacing scales with font scale; never a silent fixed Dp.
    if kind == 'dimen' and item.get('source_unit') == 'sp':
        require(item.get('scales_with_font') is True or strategy in ESCAPES,
                'sp dimension must stay font-scale aware, or be recorded as manual_exact/blocked')


def covered_ids(item):
    ids = [item.get('source_resource')] + list(item.get('covered_resource_ids', []))
    return {i for i in ids if isinstance(i, str) and i}


def blocked(analysis):
    """Resource items explicitly recorded as not exactly migratable."""
    return sorted(item['item_id'] for row in analysis.get('dimensions', [])
                  if row.get('dimension') == 'Resource' and row.get('status') == 'applicable'
                  for item in row.get('items', []) if item.get('resource_strategy') == 'blocked')


def closure_gaps(analysis, declared_refs):
    """Presentation refs the UI tree declares but no Resource item covers (reduced closure)."""
    covered = set()
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'Resource':
            continue
        for item in row.get('items', []):
            covered |= covered_ids(item)
    return sorted(set(declared_refs) - covered)
