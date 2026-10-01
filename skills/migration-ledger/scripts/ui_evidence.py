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

from pathlib import Path

from contracts import check_ref, file_ref, nonempty, read_json, require

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


def _legacy_tree(tree):
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


def native_tree(tree):
    return any(isinstance(s.get('attachments'), list) or
               isinstance((s.get('root') or {}).get('capabilities'), dict)
               for s in tree.get('screens', []))


def stable_node_id(value):
    return value if str(value).startswith('node:') else 'node:' + str(value)


def tree_nodes(tree):
    """Preserve original trees; expose a stable index for either recorded contract."""
    found = []
    def walk(node):
        found.append(node)
        for child in node.get('children', []):
            walk(child)
    for screen in tree.get('screens', []):
        walk(screen.get('root') or {})
        attachments = screen.get('attachments') or {}
        if isinstance(attachments, list):
            for item in attachments:
                walk(item.get('root') or {})
        else:
            for group in attachments.values():
                for node in group:
                    walk(node)
    return found


def node_ids(tree):
    return sorted({stable_node_id(n['id']) for n in tree_nodes(tree) if n.get('id')})


def target_node_ids(tree, page, state):
    return sorted({stable_node_id(n['id']) for n in tree_nodes(tree)
                   if any(o.get('pageId') == page and o.get('stateId') == state
                          for o in n.get('runtimeObservations', []))})


def validate_tree(tree):
    if not isinstance(tree, dict) or not native_tree(tree):
        return _legacy_tree(tree)
    require(tree.get('schemaVersion') == 1 and tree.get('scope'), 'native UI tree schema/scope required')
    origin = tree.get('generatedFrom') or {}
    require(origin.get('sourceIndex') and origin.get('sourceIndexSha256'), 'UI tree source provenance required')
    require(bool(origin.get('runtimeIndex')) == bool(origin.get('runtimeIndexSha256')), 'runtime index/hash must agree')
    ids = []
    for node in tree_nodes(tree):
        require(isinstance(node.get('id'), str) and node['id'], 'native node id required')
        ids.append(stable_node_id(node['id']))
        require(isinstance(node.get('capabilities'), dict), 'native capabilities must be an object')
        for name in ('bindings', 'events', 'dynamicRules'):
            require(isinstance(node.get(name), list) and all(isinstance(v, dict) for v in node[name]),
                    'native ' + name + ' must contain records')
        observations = node.get('runtimeObservations', [])
        require(isinstance(observations, list), 'runtime observations must be a list')
        require(not observations or merged_runtime(tree), 'source-only tree cannot contain runtime observations')
        for observation in observations:
            require(isinstance(observation, dict) and observation.get('pageId') and observation.get('stateId'),
                    'runtime observation needs pageId/stateId')
    require(ids and len(set(ids)) == len(ids), 'duplicate/missing UI node ids')
    for key in ('layoutClosure', 'criticalLayoutContracts', 'unresolved'):
        require(isinstance(tree.get(key), list), 'UI tree requires ' + key)
    return tree


def validate_tree_ref(ref, source_index_ref=None, runtime_index_ref=None, target=None, resource_scope=None):
    """Recheck the original collector/tree contract, not a reduced copy of its rules."""
    path = check_ref(ref)
    tree = validate_tree(read_json(path))
    require(native_tree(tree), 'UI evidence requires the native source-backed UI tree contract')
    require(source_index_ref, 'UI evidence requires source_index_ref')
    source = check_ref(source_index_ref)
    runtime = check_ref(runtime_index_ref) if runtime_index_ref else None
    require(bool(runtime) == merged_runtime(tree), 'runtime index evidence does not match tree mode')
    from lean_tools import validate_ui_tree
    try:
        validate_ui_tree.validate(path, source, runtime)
    except (RuntimeError, KeyError, TypeError) as exc:
        require(False, 'native UI validation: ' + str(exc))
    require(not tree['unresolved'], 'UI tree has unresolved source conflicts')
    index = read_json(source)
    require(not index.get('unresolved'), 'source index has unresolved closure')
    # Index hashes bind extracted facts; file hashes bind them to the actual source revision.
    base = Path(index.get('androidRoot', ''))
    require(base.is_absolute(), 'source index needs absolute androidRoot')
    for group in ('sourceFiles', 'layouts'):
        for item in index.get(group, []):
            if item.get('path') and item.get('sha256'):
                check_ref({'path': str(base / item['path']), 'sha256': item['sha256']})
    import resource_fidelity
    resource_fidelity.indexed_resources(index, set(resource_refs(tree)), resource_scope)
    if runtime:
        data = read_json(runtime)
        for capture in data['captures']:
            if target and (capture.get('pageId'), capture.get('stateId'), capture.get('requestedCoverage')) != tuple(target.split(':')):
                continue
            for key in ('screenshot', 'viewTree', 'meta'):
                check_ref(capture.get(key))
            for viewport in capture.get('viewports', []):
                for key in ('screenshot', 'viewTree'):
                    check_ref(viewport.get(key))
    return tree


def capture_target(capture_ref, coverage):
    """Validate only this Android target, leaving unrelated modules' captures alone."""
    from lean_tools import validate_manifest
    manifest = read_json(check_ref(capture_ref))
    try:
        target = validate_manifest.parse_target(coverage)
        records = [record for record in manifest.get('targets', []) if isinstance(record, dict)
                   and record.get('phase') == 'android-reference' and record.get('platform') == 'android'
                   and record.get('page_id') == target['page_id'] and record.get('state_id') == target['state_id']]
        require(len(records) == 1, 'capture target must be unique')
        validate_manifest.validate_manifest(manifest, [target])
    except RuntimeError as exc:
        require(False, 'native capture validation: ' + str(exc))
    return records[0]


def runtime_target(index, coverage):
    captures = [capture for capture in index.get('captures', []) if isinstance(capture, dict)
                and (capture.get('pageId'), capture.get('stateId'), capture.get('requestedCoverage')) == tuple(coverage.split(':'))]
    require(len(captures) == 1, 'runtime index must cover this exact target')
    return captures[0]


def runtime_baselines(capture):
    refs = [capture['screenshot'], *[viewport['screenshot'] for viewport in capture.get('viewports', [])]]
    return list({ref['sha256']: ref for ref in refs}.values())


def validate_native_evidence(evidence):
    """Freeze-time provenance, also used by import: a hash alone is not a capture association."""
    coverage = evidence.get('coverage', '')
    require(len(coverage.split(':')) == 3 and coverage.split(':')[2] in CAPTURE_COVERAGE,
            'UI evidence needs page:state:coverage')
    runtime = evidence.get('visual_mode') == 'runtime'
    require(evidence.get('visual_mode') in ('runtime', 'source-only'), 'UI evidence mode required')
    tree = validate_tree_ref(evidence.get('ui_tree_ref'),
                             source_index_ref=evidence.get('source_index_ref'),
                             runtime_index_ref=evidence.get('runtime_index_ref'), target=coverage,
                             resource_scope=evidence.get('resource_scope'))
    require(merged_runtime(tree) == runtime, 'capture and tree modes differ')
    capture_ref = evidence.get('capture_manifest_ref')
    require(not runtime or capture_ref, 'runtime UI evidence requires capture_manifest_ref')
    if capture_ref:
        record = capture_target(capture_ref, coverage)
        require((record['status'] == 'COMPLETE') == runtime, 'capture and tree modes differ')
    if not runtime:
        require(not evidence.get('baseline_refs'), 'source-only cannot claim runtime baseline screenshots')
        return tree
    from lean_tools import select_runtime_ui
    index = read_json(check_ref(evidence.get('runtime_index_ref')))
    require(index.get('manifestSha256') == capture_ref['sha256'], 'runtime index belongs to a different manifest')
    selected = runtime_target(index, coverage)
    try:
        collected = select_runtime_ui.select(check_ref(capture_ref), [coverage])['captures'][0]
    except RuntimeError as exc:
        require(False, 'native runtime validation: ' + str(exc))
    require(selected == collected, 'runtime target differs from original capture evidence')
    baselines = nonempty(evidence.get('baseline_refs'), 'runtime baseline screenshots')
    for ref in baselines:
        check_ref(ref)
    require(sorted(baselines, key=lambda ref: (ref['path'], ref['sha256'])) ==
            sorted(runtime_baselines(selected), key=lambda ref: (ref['path'], ref['sha256'])),
            'baseline screenshots must match the selected runtime capture')
    return tree


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


def interaction_contract(item):
    """Only frozen semantic fields enter the execution contract; retain an explicit SPEC anchor."""
    validate_interactions({'interactions': [item]})
    return {key: item[key] for key in ('id', 'action', 'from', 'expected', 'spec_ref') if key in item}


def match_interaction(actual, frozen):
    expected = interaction_contract(frozen)
    require(isinstance(actual, dict) and all(actual.get(key) == value for key, value in expected.items()),
            'interaction requirement differs from frozen action/from/expected/spec_ref')
    return {key: actual[key] for key in expected}


def match_interaction_observation(check, frozen):
    require(check.get('id') == frozen['id'] and check.get('action') == frozen['action'],
            'interaction action differs from frozen requirement')
    observed = check.get('observed')
    require(isinstance(observed, dict) and all(observed.get(key) == value for key, value in frozen['expected'].items()),
            'interaction observation differs from frozen expected outcome')


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
