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

from contracts import check_ref, read_json, require

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


def rows(items):
    return [{'item_id': iid, 'dimension': item['dimension'], **item['semantic_model']}
            for iid, item in items.items() if item.get('semantic_model')]


def implementation(items):
    """After coding, the recorded implementation location must actually exist."""
    for item in items.values():
        model = item.get('semantic_model')
        if model:
            path = Path(model['implementation_location']['target_path'])
            require(path.exists(), 'semantic implementation_location does not exist: ' + str(path))
