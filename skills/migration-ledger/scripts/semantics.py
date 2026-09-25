"""Machine-readable semantic extraction bound to UI/Logic/Resource dimension items.

Structural gates only: agents still review model fidelity and completeness.
Presence-triggered — an item without `semantic_model` is untouched, so extraction is
added incrementally. Each model records the abstraction result (`model_ref`), its
source (`origin`/`locator`/evidence) and the target `implementation_location`; it is
archived with the dimension analysis and frozen through the same hash, and rides the
existing item -> TASK -> PATH trace (task-driven). Strategy `new` has no legacy
reference, so it is authored from the target project (origin target/authored).
"""
from pathlib import Path

from contracts import check_ref, nonempty, read_json, require

# Which model kinds each dimension may carry. Adhesive keeps its existing structure.
KINDS = {
    'UI': {'ui-component-spec'},                       # AST-ized JSON component tree (AMIS/Formily-like)
    'Logic': {'logic-statechart'},                     # XState-like statechart; conditions are JSON-Logic
    'Resource': {'design-tokens', 'icu-messages'},     # W3C design tokens; ICU-compatible key->message
}
ORIGINS = ('legacy', 'target', 'authored')


def _component_node(node, label):
    require(isinstance(node, dict) and isinstance(node.get('type'), str) and node['type'], label + ' node needs a type')
    children = node.get('children', [])
    require(isinstance(children, list), label + ' children must be a list')
    for child in children:
        _component_node(child, label)


def _ui_component_spec(model):
    _component_node(model.get('root', model), 'ui-component-spec')


def _statechart(model):
    require(isinstance(model.get('id'), str) and model['id'], 'statechart needs an id')
    states = model.get('states')
    require(isinstance(states, dict) and states, 'statechart needs non-empty states')
    require(model.get('initial') in states, 'statechart initial must be a defined state')
    for state in states.values():
        require(isinstance(state, dict), 'statechart state must be an object')
        transitions = state.get('on', {})
        require(isinstance(transitions, dict), 'statechart transitions (on) must be an object')
        for event in transitions.values():
            for t in (event if isinstance(event, list) else [event]):
                if isinstance(t, dict) and 'cond' in t:
                    require(isinstance(t['cond'], dict) and t['cond'], 'statechart cond must be a JSON-Logic object')


def _design_tokens(model):
    require(isinstance(model, dict) and model, 'design tokens must be a non-empty object')
    found = []

    def walk(node):
        if isinstance(node, dict):
            if '$value' in node:
                found.append(node)
                if '$type' in node:
                    require(isinstance(node['$type'], str) and node['$type'], 'design token $type must be a string')
            else:
                for value in node.values():
                    walk(value)
    walk(model)
    require(found, 'design tokens require at least one $value token (W3C)')


def _icu_messages(model):
    require(isinstance(model, dict) and model, 'icu messages must be a non-empty object')
    for key, message in model.items():
        require(isinstance(key, str) and key and isinstance(message, str) and message, 'icu messages must be key->message strings')


VALIDATORS = {'ui-component-spec': _ui_component_spec, 'logic-statechart': _statechart,
              'design-tokens': _design_tokens, 'icu-messages': _icu_messages}


def validate_item(item):
    """Presence-triggered structural gate for one dimension item's semantic model."""
    model = item.get('semantic_model')
    if not model:
        return
    dimension = item.get('dimension')
    require(dimension in KINDS, 'semantic model only applies to UI/Logic/Resource dimensions')
    kind = model.get('kind')
    require(kind in KINDS[dimension], 'semantic model kind does not match its dimension')
    VALIDATORS[kind](read_json(check_ref(model.get('model_ref'))))
    source = model.get('source', {})
    require(source.get('origin') in ORIGINS, 'semantic source origin required (legacy/target/authored)')
    require(item.get('target_strategy') != 'new' or source['origin'] != 'legacy',
            'strategy new has no legacy reference; author the model from the target project')
    if source['origin'] in ('legacy', 'target'):
        require(isinstance(source.get('locator'), str) and source['locator'], 'semantic source locator required for legacy/target origin')
    for ref in source.get('evidence_refs', []):
        check_ref(ref)
    location = model.get('implementation_location', {})
    require(isinstance(location.get('target_path'), str) and Path(location['target_path']).is_absolute(),
            'semantic implementation_location.target_path must be absolute')


def validate_items(items):
    for item in items.values():
        validate_item(item)


def has_models(items):
    return any(item.get('semantic_model') for item in items.values())


def models_from_analysis(analysis, module_id=None):
    """Extract semantic-model rows straight from an archived dimension analysis."""
    rows = []
    for drow in analysis.get('dimensions', []):
        for item in drow.get('items', []):
            if item.get('semantic_model'):
                rows.append({**({'module_id': module_id} if module_id is not None else {}),
                             'item_id': item['item_id'], 'dimension': drow['dimension'], **item['semantic_model']})
    return rows


def coverage_from_analysis(analysis):
    """Which applicable UI/Logic/Resource items carry a semantic model (presence visibility)."""
    applicable, with_model = [], []
    for drow in analysis.get('dimensions', []):
        if drow.get('dimension') not in KINDS or drow.get('status') != 'applicable':
            continue
        for item in drow.get('items', []):
            applicable.append(item['item_id'])
            if item.get('semantic_model'):
                with_model.append(item['item_id'])
    return {'applicable': sorted(applicable), 'with_model': sorted(with_model),
            'missing': sorted(set(applicable) - set(with_model))}


def implementation(items, traces=None):
    """After coding: the implementation location must exist AND the implementer must record
    conformance binding the frozen model, so downstream provably consumed the design output."""
    traces = traces or {}
    for iid, item in items.items():
        model = item.get('semantic_model')
        if not model:
            continue
        path = Path(model['implementation_location']['target_path'])
        require(path.exists(), 'semantic implementation_location does not exist: ' + str(path))
        conformance = (traces.get(iid) or {}).get('semantic_conformance')
        require(conformance and conformance.get('model_ref') == model['model_ref'],
                'implementation must record semantic_conformance binding the frozen model for ' + iid)
        for ref in nonempty(conformance.get('evidence_refs'), 'semantic conformance evidence for ' + iid):
            check_ref(ref)
