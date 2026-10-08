"""ui_fidelity_required enforcement: exact UI/resource evidence before freeze, none Green while blocked.

Off by default (backward-compatible). When enabled at init/prepare, freezing a module whose
four-dim analysis has applicable UI items requires:

- each applicable UI item carries a ui-component-spec model bound to ui_evidence (extracted,
  structurally validated ui_tree_ref + page:state:coverage);
- the resource closure is not reduced: every presentation reference the UI trees declare,
  including code-owned runtime overrides, is covered by a Resource item;
- the source closure names the renderers that mutate visible state (a layout alone is incomplete).

Completion additionally refuses a module that still carries an explicitly `blocked` resource, so an
inexact resource can never be reported as Green. Visual parity itself is a test-stage verdict: the
visual automation layer aligns baseline nodes and reports three-state like any other path.
"""
import copy
import re

import dimensions
import resource_fidelity
import semantics
import ui_evidence as ue
from contracts import check_ref, file_ref, intact, nonempty, read_json, require


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
                tree = read_json(check_ref(evidence['ui_tree_ref']))
                if evidence.get('source_index_ref'):
                    index = read_json(check_ref(evidence['source_index_ref']))
                    refs.extend(resource_fidelity.obligations(index, tree, evidence.get('resource_scope'))['refs'])
                else:
                    refs.extend(ue.resource_refs(tree))
    return sorted(set(refs))


def allocation_gate(s, analysis):
    """What a leaf's allocation owes its UI before the leaf can be frozen: evidence for every screen and an unreduced closure."""
    gaps = semantics.ui_fidelity_gaps(analysis)
    require(not gaps, 'ui_fidelity_required: UI items lack capture-bound ui_evidence before freeze: ' + ', '.join(gaps))
    declared_refs = _declared_refs(analysis)
    uncovered = resource_fidelity.closure_gaps(analysis, declared_refs)
    require(not uncovered, 'ui_fidelity_required: resource closure reduced; uncovered presentation refs: ' + ', '.join(uncovered))
    resource_fidelity.require_exact_closure(analysis, declared_refs, s.get('legacy_root'))


def freeze_gate(s, m, allocation=True):
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    if allocation:
        allocation_gate(s, analysis)
    else:
        intact(lambda: allocation_gate(s, analysis))
    if any(row.get('dimension') == 'UI' and row.get('status') == 'applicable' for row in analysis.get('dimensions', [])):
        closure = ((m.get('plan') or {}).get('source_closure') or {})
        renderers = closure.get('ui_renderers')
        require(isinstance(renderers, list) and renderers,
                'ui_fidelity_required: source_closure.ui_renderers must name the renderers that mutate visible state')
        # A prose widget list is not a closure. Topology, the presentation states that actually exist,
        # navigation identity/back behaviour and the platform/lifecycle surface each need evidence.
        # Resources are covered more strictly by the unreduced-closure check above.
        for facet in ('ui_topology', 'states', 'navigation', 'platform_lifecycle'):
            require(closure.get(facet),
                    'ui_fidelity_required: source_closure.' + facet + ' required for UI scope')
    baseline_gate(s, m, allocation)
    import parameter_file
    parameter_file.gate(s, m.get('plan') or {}, analysis)


def runtime_targets(analysis):
    """page:state:coverage targets whose legacy screen is previewable, so a baseline exists."""
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
    found = []
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item.get('semantic_model')
            if model:
                found.extend(ue.validate_interactions(model))
    return sorted(set(found))


def declared_image_checks(analysis):
    """{id: (check, coverage)} for every image check the applicable UI models declare."""
    found = {}
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item.get('semantic_model') or {}
            for check in model.get('image_checks') or []:
                require(check['id'] not in found or found[check['id']][0] == check, 'conflicting declared image check: ' + check['id'])
                found[check['id']] = (check, (model.get('ui_evidence') or {}).get('coverage'))
    return found


STILL_FORMATS = ('png', 'jpeg', 'jpg', 'webp', 'gif', 'vector-xml')


def picture_uses(tree, index):
    """{(node id, reference)}: every still picture a node of the tree declares, which is what a screen shows of it.

    A nine-patch, an animation and a drawable described by XML have no single picture to compare with."""
    still = set()
    for row in index.get('resources', []):
        if row['ref'].split('/')[0] in ('@drawable', '@mipmap') and (row.get('facts') or {}).get('format') in STILL_FORMATS \
                and not str(row.get('path', '')).lower().endswith('.9.png'):
            still.add(row['ref'])
    uses = set()
    for node in ue.tree_nodes(tree):
        refs = set(node.get('presentation', {}).get('resourceRefs', []))
        for rule in node.get('dynamicRules', []):
            refs.update(rule.get('resourceRefs', []))
        uses.update((ue.stable_node_id(node['id']), ref) for ref in refs & still)
    return uses


def check_coverage(model, tree, index):
    """Which picture uses of one UI target an image check measures, which a waiver sets aside, and which nothing covers."""
    uses = picture_uses(tree, index)
    checked = {(c['node_id'], c['source_resource']) for c in model.get('image_checks') or [] if c.get('kind', 'image') == 'image'} & uses
    waivers = model.get('image_check_waivers', [])
    require(isinstance(waivers, list), 'image_check_waivers must be a list')
    waived = set()
    for row in waivers:
        require(isinstance(row, dict) and isinstance(row.get('reason'), str) and row['reason'].strip(), 'an image check waiver needs a reason')
        refs = row.get('evidence_refs')
        require(isinstance(refs, list) and refs, 'an image check waiver needs evidence')
        for ref in refs:
            check_ref(ref)
        matched = {(node, ref) for node, ref in uses if row.get('node_id') in (None, node) and row.get('source_resource') in (None, ref)}
        require(matched or not (row.get('node_id') or row.get('source_resource')), 'an image check waiver names a picture no node of this target shows')
        waived |= matched
    return {'uses': uses, 'checked': checked, 'waived': waived - checked, 'open': uses - checked - waived}


def derive_checks(analysis, out, rules=None):
    """Image checks for every picture use of a module that has none yet, each with its reference rendered under `out`.

    A check finds its node by the node's own id (`resource-id` = the id without `node:`), so the target only has
    to give each such node that key. `unrendered` lists uses whose picture could not be rendered, with the reason;
    `texts` suggests a text check for every string a node declares, for the Spec to keep where the state shows it."""
    import reference_render
    slug = lambda value: re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    found, unrendered, texts, taken, rendered = {}, [], {}, set(), {}
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item.get('semantic_model') or {}
            evidence = model.get('ui_evidence') or {}
            if not (evidence.get('source_index_ref') and evidence.get('ui_tree_ref')):
                continue
            index, tree = read_json(check_ref(evidence['source_index_ref'])), read_json(check_ref(evidence['ui_tree_ref']))
            scope = evidence.get('resource_scope')
            groups = resource_fidelity.resource_groups(resource_fidelity.indexed_resources(
                index, resource_fidelity.obligations(index, tree, scope)['refs'], scope))
            for node, ref in sorted(check_coverage(model, tree, index)['open']):
                renditions = groups.get((ref, 'base')) or next((g for (r, _), g in sorted(groups.items()) if r == ref), None)
                qualifier = renditions and resource_fidelity.rendition(renditions, (rules or {}).get('formats'), (rules or {}).get('density'))
                if not qualifier:
                    unrendered.append({'node_id': node, 'source_resource': ref, 'reason': 'the source index holds no rendition of it for this target'})
                    continue
                if (ref, qualifier) not in rendered:
                    directory = out / 'references' / (slug(ref) + '-' + slug(qualifier))
                    directory.mkdir(parents=True, exist_ok=True)
                    try:
                        reference_render.render(index, ref, qualifier, directory)
                        rendered[(ref, qualifier)] = directory / 'reference.json'
                    except (reference_render.RenderError, OSError) as exc:   # a file that is not the picture its name says
                        rendered[(ref, qualifier)] = str(exc)
                if isinstance(rendered[(ref, qualifier)], str):
                    unrendered.append({'node_id': node, 'source_resource': ref, 'reason': rendered[(ref, qualifier)]})
                    continue
                name = base = 'img-' + slug(node[len('node:'):]) + '-' + slug(ref.split('/', 1)[1])
                count = 1
                while name in taken:
                    count += 1
                    name = base + '-' + str(count)
                taken.add(name)
                found.setdefault(item['item_id'], []).append({
                    'id': name, 'node_id': node, 'source_resource': ref, 'qualifier': qualifier,
                    'reference': {'render_ref': file_ref(rendered[(ref, qualifier)])}, 'target': {'selector': {'resource-id': node[len('node:'):]}}})
            values = {r['ref']: r['value'] for r in index.get('resources', []) if r['ref'].startswith('@string/')
                      and r.get('qualifier') in ('default', 'base') and isinstance(r.get('value'), str)}
            for node in ue.tree_nodes(tree):
                node_id = ue.stable_node_id(node['id'])
                for ref in sorted(set(node.get('presentation', {}).get('resourceRefs', [])) & set(values)):
                    texts.setdefault(item['item_id'], []).append({
                        'id': 'txt-' + slug(node_id[len('node:'):]) + '-' + slug(ref.split('/', 1)[1]), 'kind': 'text', 'node_id': node_id,
                        'source_resource': ref, 'qualifier': 'default', 'expect': {'text': values[ref]},
                        'target': {'selector': {'resource-id': node_id[len('node:'):]}}})
    return {'checks': found, 'texts': texts, 'unrendered': unrendered}


def frozen_image_checks(module, path):
    """The full frozen checks a visual PATH carries, from the dimension analysis that owns the PATH."""
    ids = path.get('image_check_ids')
    if path.get('kind') != 'visual' or not ids:
        return []
    ref = (module.get('path_dimension_analysis_refs', {}).get(path['path_id']) or (module.get('plan') or {}).get('dimension_analysis_ref'))
    require(ref, 'visual image checks require frozen UI dimension evidence')
    declared = declared_image_checks(read_json(check_ref(ref)))
    absent = [cid for cid in ids if cid not in declared]
    require(not absent, 'visual path carries undeclared image checks: ' + ', '.join(absent))
    return [copy.deepcopy(declared[cid][0]) for cid in ids]


def frozen_interaction(module, path):
    """Derive the PATH's full requirement from frozen SPEC; audit scopes carry the same value."""
    if path.get('kind') not in ('automation', 'visual') or not path.get('interaction_id'):
        return None
    iid = path['interaction_id']
    if not (module.get('plan') or {}).get('dimension_analysis_ref') and 'frozen_interactions' in module:
        # This map is assembled by Ledger.audit_scope from each owning module.
        require(module.get('module_id') in (None, 'GLOBAL'), 'module interaction requires frozen UI dimension evidence')
        item = module['frozen_interactions'].get(path['path_id'])
        require(item and item.get('id') == iid, 'audit visual path lacks its frozen interaction')
        return ue.interaction_contract(item)
    analysis = _analysis(module)
    require(analysis, 'visual interaction requires frozen UI dimension evidence')
    matches = [ue.interaction_contract(item) for row in analysis.get('dimensions', [])
               if row.get('dimension') == 'UI' and row.get('status') == 'applicable'
               for ui_item in row.get('items', [])
               for item in (ui_item.get('semantic_model') or {}).get('interactions', []) if item.get('id') == iid]
    require(matches and all(item == matches[0] for item in matches), 'missing/conflicting frozen interaction: ' + iid)
    return matches[0]


def baseline_gate(s, m, allocation=True):
    """Legacy executability is decided before freeze and drives SPEC/coding inputs.

    Previewable legacy screens contribute captured baseline screenshots that guide the SPEC and the
    Implementer, and are later compared node-by-node in the visual test stage. A legacy screen that
    cannot be previewed falls back to retained UI source, but still owes the four-dimension UI
    intermediate representation, so coding is never guided by prose alone.
    """
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    plan = m.get('plan') or {}
    visual = [path for path in plan.get('paths', []) if path.get('kind') == 'visual']
    for row in analysis.get('dimensions', []) if allocation else []:
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            evidence = ((item.get('semantic_model') or {}).get('ui_evidence')) or {}
            executable = evidence.get('legacy_executable')
            require(isinstance(executable, bool),
                    'legacy executability must be decided before freeze for ' + item['item_id'])
            if executable:
                require(evidence.get('visual_mode') == 'runtime',
                        'a previewable legacy screen must carry runtime baseline evidence: ' + item['item_id'])
                for ref in nonempty(evidence.get('baseline_refs'), 'baseline screenshots for ' + item['item_id']):
                    check_ref(ref)
            else:
                require(evidence.get('visual_mode') == 'source-only',
                        'a non-previewable legacy screen falls back to source-only: ' + item['item_id'])
    covered = {node for path in visual for node in path.get('node_ids', [])}
    for target in runtime_targets(analysis):
        require(visual, 'baseline target ' + target + ' needs a visual test path aligning its nodes')
    require(not runtime_targets(analysis) or covered,
            'visual paths must name the UI-tree nodes they align')
    declared = declared_interactions(analysis)
    interaction_paths = [path for path in plan.get('paths', []) if path.get('kind') in ('automation', 'visual')]
    proven = {path.get('interaction_id') for path in interaction_paths}
    missing = sorted(set(declared) - proven)
    require(not missing, 'declared interactions need an automation/visual path carrying device proof: ' + ', '.join(missing))
    for path in plan.get('paths', []):
        if not path.get('interaction_id'):
            continue
        require(path.get('kind') in ('automation', 'visual'), 'interaction requires an automation/visual path')
        interaction = frozen_interaction(m, path)
        if path.get('coverage'):
            require(path['coverage'].split(':')[:2] ==
                    [interaction['from']['page_id'], interaction['from']['state_id']],
                    'interaction path must use its declared starting page/state')
    visual_plan_gate(analysis, visual)
    carried = {cid for path in visual for cid in path.get('image_check_ids', [])}
    missing = sorted(set(declared_image_checks(analysis)) - carried)
    require(not missing, 'declared image checks need a visual path carrying device proof: ' + ', '.join(missing))


def visual_plan_gate(analysis, visual):
    """Bind each visual path to its own frozen target, screenshots and observed tree nodes.

    A path with a baseline compares whole screens with the legacy capture. A path without one carries
    image checks only: it captures the target and compares named nodes with rendered legacy pictures."""
    targets, interactions, screens, checks = {}, {}, {}, {}
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            model = item['semantic_model']
            evidence = model['ui_evidence']
            tree = ue.validate_native_evidence(evidence)
            index = read_json(check_ref(evidence['source_index_ref'])) if evidence.get('source_index_ref') else None
            for cid in ue.validate_image_checks(model, tree, index):
                checks[cid] = (next(c for c in model['image_checks'] if c['id'] == cid), evidence['coverage'])
            if index is not None:
                # What a screen shows of a legacy picture is measured there; a copy in the right folder proves nothing about the screen.
                uncovered = sorted(check_coverage(model, tree, index)['open'])
                require(not uncovered, 'pictures shown by ' + evidence['coverage'] + ' need an image check or a waiver with evidence: '
                        + ', '.join(node + ' ' + ref for node, ref in uncovered[:10]) + (' and ' + str(len(uncovered) - 10) + ' more' if len(uncovered) > 10 else ''))
            screens.setdefault(evidence['coverage'], set()).update(ue.node_ids(tree))
            for interaction in model.get('interactions', []):
                require(interaction['id'] not in interactions or interactions[interaction['id']] == interaction,
                        'conflicting declared interaction: ' + interaction['id'])
                interactions[interaction['id']] = interaction
            if evidence['visual_mode'] != 'runtime':
                continue
            coverage = evidence['coverage']
            page, state, _ = coverage.split(':')
            nodes = ue.target_node_ids(tree, page, state)
            require(nodes, 'runtime UI target has no observed tree nodes: ' + coverage)
            target = targets.setdefault(coverage, {'nodes': set(), 'baselines': []})
            target['nodes'].update(nodes)
            target['baselines'].extend(evidence['baseline_refs'])
    covered = set()
    for path in visual:
        coverage = path.get('coverage')
        ids = path.get('image_check_ids', [])
        if path.get('baseline_ref') is None and ids:
            require(isinstance(coverage, str) and coverage in screens, 'visual path coverage must name a frozen UI target')
            nodes = nonempty(path.get('node_ids'), 'visual path node_ids')
            require(set(nodes) <= screens[coverage], 'visual path nodes do not belong to target ' + coverage)
        else:
            require(isinstance(coverage, str) and coverage in targets,
                    'visual path coverage must name a frozen runtime UI target')
            target = targets[coverage]
            nodes = nonempty(path.get('node_ids'), 'visual path node_ids')
            require(set(nodes) <= target['nodes'], 'visual path nodes do not belong to target ' + coverage)
            require(path.get('baseline_ref') in target['baselines'],
                    'visual path baseline differs from frozen target ' + coverage)
            check_ref(path['baseline_ref'])
        for cid in ids:
            require(cid in checks and checks[cid][1] == coverage,
                    'visual path carries image check ' + cid + ' that does not belong to its target')
            require(checks[cid][0]['node_id'] in nodes, 'visual path nodes must include the node of image check ' + cid)
        if path.get('interaction_id'):
            interaction = interactions.get(path['interaction_id'])
            require(interaction, 'visual path references an undeclared interaction')
            start = interaction['from']
            require(coverage.split(':')[:2] == [start['page_id'], start['state_id']],
                    'interaction visual path must use its declared starting page/state')
        if path.get('baseline_ref') is not None:
            covered.add(coverage)
    missing = sorted(set(targets) - covered)
    require(not missing, 'runtime UI targets lack visual paths: ' + ', '.join(missing))


def completion_gate(s, m):
    """An explicitly blocked (inexact) resource can never be recorded as Green."""
    if not s.get('ui_fidelity_required'):
        return
    analysis = _analysis(m)
    if analysis is None:
        return
    stuck = resource_fidelity.blocked(analysis)
    require(not stuck, 'ui_fidelity_required: blocked resources cannot complete as Green: ' + ', '.join(stuck))
