"""Structural validation of the extracted UI tree (absorbed from the lean UI pipeline).

A frozen ui_evidence.ui_tree_ref stops being an opaque blob: nodes carry stable ids, every
direct presentation reference is recorded, code-owned runtime presentation changes appear as
dynamicRules, and conflicts stay in an explicit `unresolved` list instead of being dropped.
Structural gates only; semantic completeness stays with the analysing agent.
"""
import re

from contracts import nonempty, require

# Stable ids shared with OpenSpec: screen:/node:/binding:/event:/resource:/interaction:
ID = re.compile(r'^(screen|node|binding|event|resource|interaction):[A-Za-z0-9][A-Za-z0-9/_.\-]*$')


def _refs(value, label):
    require(isinstance(value, list), label + ' must be a list')
    for ref in value:
        require(isinstance(ref, str) and ref, label + ' entries must be non-empty strings')
    return value


def _node(node, label='nodes'):
    require(isinstance(node, dict), label + ' entry must be an object')
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
    children = node.get('children', [])
    require(isinstance(children, list), nid + ' children must be a list')
    for child in children:
        _node(child, nid)


def validate(tree):
    require(isinstance(tree, dict) and tree.get('schema_version') == 1, 'ui tree schema_version 1 required')
    screen = tree.get('screen', '')
    require(isinstance(screen, str) and screen.startswith('screen:') and ID.match(screen),
            'ui tree needs a stable screen:<id>')
    for node in nonempty(tree.get('nodes'), 'ui tree nodes'):
        _node(node)
    require(isinstance(tree.get('unresolved'), list), 'ui tree must keep an explicit unresolved list')
    return tree


def resource_refs(tree):
    """Every presentation reference the tree declares, including code-owned runtime overrides."""
    found = []

    def walk(node):
        found.extend(node.get('presentation', {}).get('resourceRefs', []))
        for rule in node.get('dynamicRules', []):
            found.extend(rule.get('resourceRefs', []))
        for child in node.get('children', []):
            walk(child)
    for node in tree.get('nodes', []):
        walk(node)
    return sorted(set(found))
