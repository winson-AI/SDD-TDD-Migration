"""UI evidence contracts: the merged UI tree, the capture manifest, and declared gestures.

One module because these are one concern — the evidence a UI slice owes before it may freeze and be
verified. All three are absorbed from the lean UI pipeline and validated structurally only; semantic
completeness stays with the analysing agent.

- `validate_tree`: the merged source+runtime UI tree (screens, typed attachments, stable ids, every
  presentation reference, code-owned dynamicRules, explicit unresolved conflicts, merge provenance).
- `validate_capture`: a schema-2 capture manifest record; a COMPLETE record owes a real
  screenshot/view_xml/meta triple whose achieved coverage satisfies the request.
- `validate_interactions` / `validate_interaction_checks`: only Spec-declared gestures exist, and
  each needs PASSED device evidence bound to the HAP that was aligned.
"""
import re

from contracts import check_ref, nonempty, require

# Stable ids shared with OpenSpec.
STABLE_ID = re.compile(r'^(screen|state|node|binding|event|resource|interaction):[A-Za-z0-9][A-Za-z0-9/_.\-]*$')
# Typed attachments a screen may carry beside its root (repeated rows are represented once).
ATTACHMENTS = ('drawers', 'dialogs', 'menus', 'overlays', 'pagerPages', 'listItems', 'headers', 'footers')
CAPTURE_COVERAGE = ('viewport', 'scroll')
CAPTURE_STATUS = ('COMPLETE', 'SOURCE_ONLY')
INTERACTION_ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')


# --------------------------------------------------------------------------- merged UI tree

def _refs(value, label):
    require(isinstance(value, list), label + ' must be a list')
    for ref in value:
        require(isinstance(ref, str) and ref, label + ' entries must be non-empty strings')
    return value


def _node(node, label, runtime_merged):
    require(isinstance(node, dict), label + ' must be an object')
    nid = node.get('id', '')
    require(isinstance(nid, str) and nid.startswith('node:') and STABLE_ID.match(nid),
            label + ' needs a stable node:<id>')
    presentation = node.get('presentation', {})
    require(isinstance(presentation, dict), nid + ' presentation must be an object')
    _refs(presentation.get('resourceRefs', []), nid + ' presentation.resourceRefs')
    for key in ('bindings', 'events'):
        for ref in _refs(node.get(key, []), nid + ' ' + key):
            require(STABLE_ID.match(ref), nid + ' ' + key + ' needs stable ids')
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
    require(isinstance(sid, str) and sid.startswith('screen:') and STABLE_ID.match(sid),
            'screen needs a stable screen:<id>')
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


def validate_tree(tree):
    require(isinstance(tree, dict) and tree.get('schemaVersion') == 1, 'ui tree schemaVersion 1 required')
    require(isinstance(tree.get('scope'), str) and tree['scope'], 'ui tree needs its change scope')
    origin = tree.get('generatedFrom')
    require(isinstance(origin, dict), 'ui tree needs generatedFrom provenance')
    for key in ('sourceIndex', 'sourceIndexSha256'):
        require(isinstance(origin.get(key), str) and origin[key], 'generatedFrom needs ' + key)
    require(bool(origin.get('runtimeIndex')) == bool(origin.get('runtimeIndexSha256')),
            'runtimeIndex and runtimeIndexSha256 must both be present or both be null')
    runtime = merged_runtime(tree)
    for screen in nonempty(tree.get('screens'), 'ui tree screens'):
        _screen(screen, runtime)
    for key in ('layoutClosure', 'criticalLayoutContracts', 'unresolved'):
        require(isinstance(tree.get(key), list), 'ui tree must keep an explicit ' + key + ' list')
    return tree


def tree_nodes(tree):
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
    return sorted({node['id'] for node in tree_nodes(tree) if node.get('id')})


def resource_refs(tree):
    """Every presentation reference the tree declares, including code-owned runtime overrides."""
    found = []
    for node in tree_nodes(tree):
        found.extend(node.get('presentation', {}).get('resourceRefs', []))
        for rule in node.get('dynamicRules', []):
            found.extend(rule.get('resourceRefs', []))
    return sorted(set(found))


# --------------------------------------------------------------------------- capture manifest

def validate_capture(entry):
    """A schema-2 manifest record; partial scroll evidence never advances UI evidence."""
    require(isinstance(entry, dict), 'capture entry must be an object')
    require(entry.get('schema_version') == 2, 'capture manifest schema_version 2 required')
    for key in ('page_id', 'state_id'):
        require(isinstance(entry.get(key), str) and entry[key], 'capture entry needs ' + key)
    require(entry.get('coverage') in CAPTURE_COVERAGE, 'capture coverage must be viewport/scroll')
    status = entry.get('status')
    require(status in CAPTURE_STATUS, 'capture status must be COMPLETE/SOURCE_ONLY')
    if status == 'SOURCE_ONLY':
        require(not entry.get('snapshot'), 'SOURCE_ONLY must not carry invented runtime captures')
        return entry
    snapshot = entry.get('snapshot') or {}
    require(isinstance(snapshot, dict), 'COMPLETE needs a snapshot object')
    for key in ('screenshot', 'view_xml', 'meta'):
        require(isinstance(snapshot.get(key), str) and snapshot[key], 'COMPLETE snapshot needs ' + key)
    nonempty(snapshot.get('captures'), 'COMPLETE snapshot captures')
    expected = 'scroll-complete' if entry['coverage'] == 'scroll' else 'viewport'
    require(entry.get('achieved_coverage') == expected,
            'achieved coverage must be ' + expected + '; partial evidence never advances the cursor')
    require(entry.get('observed_variant'), 'COMPLETE needs observed_variant (selected tab/dialog/page identity)')
    require(entry.get('backend'), 'COMPLETE needs the recording device backend')
    return entry


# --------------------------------------------------------------------------- declared gestures

def validate_interactions(model):
    """Only gestures the frozen Spec declares exist; never inferred from stacks or screenshots."""
    declared = model.get('interactions')
    if declared is None:
        return []
    require(isinstance(declared, list), 'interactions must be a list')
    seen = []
    for item in declared:
        require(isinstance(item, dict) and INTERACTION_ID.match(str(item.get('id', ''))),
                'interaction needs a stable lowercase id')
        require(item['id'] not in seen, 'duplicate interaction id ' + item['id'])
        seen.append(item['id'])
        require(item.get('action'), 'interaction ' + item['id'] + ' needs an exact action modality')
        start = item.get('from') or {}
        require(start.get('page_id') and start.get('state_id'),
                'interaction ' + item['id'] + ' needs a starting page/state')
        expected = item.get('expected') or {}
        require(isinstance(expected.get('app_foreground'), bool),
                'interaction ' + item['id'] + ' needs expected app_foreground')
        require(expected['app_foreground'] is False or (expected.get('page_id') and expected.get('state_id')),
                'interaction ' + item['id'] + ' needs an expected page/state unless the app exits')
    return seen


def validate_interaction_checks(declared_ids, alignment):
    """Every declared gesture has a PASSED check against the HAP that was aligned."""
    if not declared_ids:
        return
    checks = {c.get('id'): c for c in (alignment or {}).get('interaction_checks', []) if isinstance(c, dict)}
    missing = sorted(set(declared_ids) - set(checks))
    require(not missing, 'declared interactions lack device checks: ' + ', '.join(missing))
    hap = (alignment or {}).get('hap_sha256')
    require(hap, 'interaction checks require the aligned hap_sha256')
    for iid in declared_ids:
        check = checks[iid]
        require(check.get('status') == 'PASSED', 'interaction check not PASSED: ' + iid)
        require(check.get('hap_sha256') == hap, 'interaction check must bind the aligned HAP: ' + iid)
        check_ref(check.get('evidence_ref'))
