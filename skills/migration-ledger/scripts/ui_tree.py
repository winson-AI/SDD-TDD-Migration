"""The merged source+runtime UI tree contract, as the lean UI pipeline actually emits it.

A frozen ui_tree_ref is not an opaque blob. Each screen has one recursive source-backed root plus
typed attachments; every node keeps stable ids and every direct presentation reference; code-owned
presentation mutations appear as dynamicRules; contradictions stay in an explicit `unresolved` list.
`generatedFrom` records which source/runtime indexes produced it, so a source-only tree cannot carry
invented runtime observations. Structural gates only — semantic completeness stays with the
analysing agent.
"""
import re

from contracts import nonempty, require

# Stable ids shared with OpenSpec.
ID = re.compile(r'^(screen|state|node|binding|event|resource|interaction):[A-Za-z0-9][A-Za-z0-9/_.\-]*$')
# Typed attachments a screen may carry beside its root (repeated rows are represented once).
ATTACHMENTS = ('drawers', 'dialogs', 'menus', 'overlays', 'pagerPages', 'listItems', 'headers', 'footers')


def _refs(value, label):
    require(isinstance(value, list), label + ' must be a list')
    for ref in value:
        require(isinstance(ref, str) and ref, label + ' entries must be non-empty strings')
    return value


def _node(node, label, runtime_merged):
    require(isinstance(node, dict), label + ' must be an object')
    nid = node.get('id', '')
    require(isinstance(nid, str) and nid.startswith('node:') and ID.match(nid), label + ' needs a stable node:<id>')
    presentation = node.get('presentation', {})
    require(isinstance(presentation, dict), nid + ' presentation must be an object')
    _refs(presentation.get('resourceRefs', []), nid + ' presentation.resourceRefs')
    for key in ('bindings', 'events'):
        for ref in _refs(node.get(key, []), nid + ' ' + key):
            require(ID.match(ref), nid + ' ' + key + ' needs stable ids')
    rules = node.get('dynamicRules', [])
    require(isinstance(rules, list), nid + ' dynamicRules must be a list')
    for rule in rules:
        require(isinstance(rule, dict) and rule.get('condition'), nid + ' dynamicRule needs a condition')
        _refs(rule.get('resourceRefs', []), nid + ' dynamicRule resourceRefs')
    require(isinstance(node.get('capabilities', []), list), nid + ' capabilities must be a list')
    observations = node.get('runtimeObservations', [])
    require(isinstance(observations, list), nid + ' runtimeObservations must be a list')
    require(not observations or runtime_merged,
            nid + ' carries runtimeObservations but the tree has no runtime index')
    for observation in observations:
        require(isinstance(observation, dict) and observation.get('pageId') and observation.get('stateId'),
                nid + ' runtimeObservation needs pageId/stateId')
    children = node.get('children', [])
    require(isinstance(children, list), nid + ' children must be a list')
    for child in children:
        _node(child, nid + ' child', runtime_merged)


def _screen(screen, runtime_merged):
    require(isinstance(screen, dict), 'screen must be an object')
    sid = screen.get('id', '')
    require(isinstance(sid, str) and sid.startswith('screen:') and ID.match(sid), 'screen needs a stable screen:<id>')
    _node(screen.get('root'), sid + ' root', runtime_merged)
    attachments = screen.get('attachments', {})
    require(isinstance(attachments, dict), sid + ' attachments must be an object')
    require(set(attachments) <= set(ATTACHMENTS), sid + ' attachments must be typed: ' + ', '.join(ATTACHMENTS))
    for kind, nodes in attachments.items():
        require(isinstance(nodes, list), sid + ' ' + kind + ' must be a list')
        for node in nodes:
            _node(node, sid + ' ' + kind, runtime_merged)


def merged_runtime(tree):
    """True when a runtime capture index was merged in (source-only trees have none)."""
    return bool((tree.get('generatedFrom') or {}).get('runtimeIndex'))


def validate(tree):
    require(isinstance(tree, dict) and tree.get('schemaVersion') == 1, 'ui tree schemaVersion 1 required')
    require(isinstance(tree.get('scope'), str) and tree['scope'], 'ui tree needs its change scope')
    origin = tree.get('generatedFrom')
    require(isinstance(origin, dict), 'ui tree needs generatedFrom provenance')
    for key in ('sourceIndex', 'sourceIndexSha256'):
        require(isinstance(origin.get(key), str) and origin[key], 'generatedFrom needs ' + key)
    require(bool(origin.get('runtimeIndex')) == bool(origin.get('runtimeIndexSha256')),
            'runtimeIndex and runtimeIndexSha256 must both be present or both be null')
    runtime_merged = merged_runtime(tree)
    for screen in nonempty(tree.get('screens'), 'ui tree screens'):
        _screen(screen, runtime_merged)
    for key in ('layoutClosure', 'criticalLayoutContracts', 'unresolved'):
        require(isinstance(tree.get(key), list), 'ui tree must keep an explicit ' + key + ' list')
    return tree


def nodes(tree):
    """Every node in the tree, roots and typed attachments alike."""
    found = []

    def walk(node):
        found.append(node)
        for child in node.get('children', []):
            walk(child)
    for screen in tree.get('screens', []):
        walk(screen.get('root') or {})
        for group in (screen.get('attachments') or {}).values():
            for node in group:
                walk(node)
    return found


def node_ids(tree):
    return sorted({node['id'] for node in nodes(tree) if node.get('id')})


def resource_refs(tree):
    """Every presentation reference the tree declares, including code-owned runtime overrides."""
    found = []
    for node in nodes(tree):
        found.extend(node.get('presentation', {}).get('resourceRefs', []))
        for rule in node.get('dynamicRules', []):
            found.extend(rule.get('resourceRefs', []))
    return sorted(set(found))
