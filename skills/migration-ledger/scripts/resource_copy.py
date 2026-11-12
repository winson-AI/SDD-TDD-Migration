"""File resources travel by path: what the scoped UI uses is copied into the target and named by one convention.

A picture, an animation file or a font is a file. Nobody re-creates it: the source index records its
path and hash, the project states once where such files go in the target and how code names them, and
the copy plan follows from the two. The plan is derived, never authored, so the Ledger recomputes it at
freeze and a row cannot be edited; acceptance compares each copy with the legacy bytes and looks for
its name in the submitted code. A resource the target cannot load as it is stays an authored item.
"""
import hashlib
from pathlib import Path
import re

from contracts import check_ref, digest, file_ref, named, read_json, require
import resource_facts
import resource_fidelity

PRODUCER = 'sdd-resource-plan'
PLACEHOLDERS = ('kind', 'name', 'ext', 'variant', 'density', 'path')
TEXT_LIMIT = 4 * 1024 * 1024


def _template(value, label, allowed):
    require(isinstance(value, str) and value.strip(), 'target_resources.copy.' + label + ' must be a template string')
    names = re.findall(r'\{(\w*)\}', value)
    require(all(name in allowed for name in names) and value.count('{') == value.count('}') == len(names),
            'target_resources.copy.' + label + ' may use only ' + ', '.join('{' + name + '}' for name in allowed))
    return value


def convention(value, target_root=None):
    """The project's statement of where copied files go and how target code names them."""
    require(isinstance(value, dict) and set(value) <= {'root', 'path', 'accessor', 'formats', 'density', 'preserve_density'},
            'target_resources.copy takes root, path, accessor, formats and density')
    root = value.get('root')
    require(isinstance(root, str) and Path(root).is_absolute(), 'target_resources.copy.root must be an absolute directory')
    root = Path(root).resolve()
    if target_root:
        require(root.is_relative_to(Path(target_root).resolve()), 'target_resources.copy.root must lie inside target_root')
    path = _template(value.get('path'), 'path', PLACEHOLDERS[:-1])
    require('{name}' in path and not Path(path.replace('{', '').replace('}', '')).is_absolute() and '..' not in Path(path).parts,
            'target_resources.copy.path is a relative path that contains {name}')
    accessor = _template(value.get('accessor'), 'accessor', PLACEHOLDERS)
    formats = value.get('formats')
    require(isinstance(formats, list) and formats and all(isinstance(name, str) and name for name in formats)
            and len(set(formats)) == len(formats), 'target_resources.copy.formats lists the file formats the target loads as they are')
    density = value.get('density', [])
    require(isinstance(density, list) and all(isinstance(name, str) and name for name in density),
            'target_resources.copy.density is an ordered list of densities to prefer')
    preserve = value.get('preserve_density', False)
    require(type(preserve) is bool and (not preserve or '{density}' in path),
            'target_resources.copy.preserve_density requires a path template containing {density}')
    return {'root': str(root), 'path': path, 'accessor': accessor, 'formats': list(formats), 'density': list(density),
            **({'preserve_density': True} if preserve else {})}


def _names(ref, source, variant, qualifier):
    path = Path(source['path'])
    if ref.startswith('asset:'):
        relative = Path(ref[len('asset:'):])
        kind, name, ext = 'asset', relative.with_suffix('').as_posix(), relative.suffix
    else:
        kind, name = ref.lstrip('@').split('/', 1)
        ext = '.9.png' if path.name.lower().endswith('.9.png') else path.suffix
    return {'kind': kind, 'name': name, 'ext': ext, 'variant': variant, 'density': resource_facts.variant(qualifier)[1] or ''}


def _ui_items(analysis):
    for row in analysis.get('dimensions', []):
        if row.get('dimension') == 'UI' and row.get('status') == 'applicable':
            for item in row.get('items', []):
                evidence = (item.get('semantic_model') or {}).get('ui_evidence')
                if evidence and evidence.get('source_index_ref') and evidence.get('ui_tree_ref'):
                    yield item, evidence


def derive(analysis, rules):
    """The copy plan of one module: a row for every file resource its UI targets must cover that the target loads as it is.

    `uncovered` lists what the rows leave to authored items, with the reason."""
    import ui_evidence
    rules = convention(rules)
    rows, uncovered, inventory = {}, {}, {}
    for item, evidence in _ui_items(analysis):
        index = read_json(check_ref(evidence['source_index_ref']))
        tree = read_json(check_ref(evidence['ui_tree_ref']))
        scope = evidence.get('resource_scope')
        needed = resource_fidelity.obligations(index, tree, scope)
        declared_by = {}
        for node in ui_evidence.tree_nodes(tree):
            refs = set(node.get('presentation', {}).get('resourceRefs', []))
            for rule in node.get('dynamicRules', []):
                refs.update(rule.get('resourceRefs', []))
            for ref in refs:
                declared_by.setdefault(ref, set()).add(ui_evidence.stable_node_id(node['id']))
        active = resource_fidelity.indexed_resources(index, needed['refs'], scope)
        for (ref, variant), renditions in sorted(resource_fidelity.resource_groups(active).items()):
            kind = 'asset' if ref.startswith('asset:') else ref.lstrip('@').split('/')[0]
            if kind not in resource_fidelity.FILE_KINDS + ('asset',):
                continue
            preferred = resource_fidelity.rendition(renditions, rules['formats'], rules['density'])
            qualifiers = [preferred] if preferred and len(renditions[preferred]) == 1 else []
            if rules.get('preserve_density'):
                qualifiers = sorted(q for q, sources in renditions.items() if len(sources) == 1
                                    and resource_facts.format_of(sources[0]['path']) in rules['formats'])
            if not qualifiers:
                loaded = sorted({resource_facts.format_of(sources[0]['path']) for sources in renditions.values()})
                uncovered[(ref, variant)] = ('several source files declare it' if preferred else
                                             'the target does not load ' + '/'.join(loaded) + ' as it is')
            for qualifier, sources in sorted(renditions.items()):
                key = (ref, variant, qualifier)
                if qualifier in qualifiers:
                    status, reason = 'copied', 'target preserves this density' if rules.get('preserve_density') else 'selected by target rendition preference'
                elif len(sources) > 1:
                    status, reason = 'ambiguous', 'several source files declare this rendition'
                elif resource_facts.format_of(sources[0]['path']) not in rules['formats']:
                    status, reason = 'unsupported', 'target does not load this format unchanged'
                else:
                    status, reason = 'folded', 'target uses the selected rendition for this density'
                entry = {'source_resource': ref, 'variant': variant, 'qualifier': qualifier,
                         'source_refs': [dict(source) for source in sources], 'status': status, 'reason': reason}
                require(inventory.setdefault(key, entry) == entry,
                        'UI targets of one module index different files for ' + ref + ' / ' + qualifier)
            for qualifier in qualifiers:
                source = renditions[qualifier][0]
                names = _names(ref, source, variant, qualifier)
                relative = rules['path'].format(**names)
                target = (Path(rules['root']) / relative).resolve()
                require(target.is_relative_to(Path(rules['root'])), 'copy path leaves target_resources.copy.root: ' + relative)
                row = rows.setdefault((ref, variant, qualifier), {
                    'source_resource': ref, 'variant': variant, 'qualifier': qualifier, 'format': resource_facts.format_of(source['path']),
                    'source_ref': dict(source), 'target_path': str(target), 'accessor': rules['accessor'].format(path=relative, **names),
                    'used_by': set(), 'ui_items': set()})
                require(row['source_ref'] == source, 'UI targets of one module index different files for ' + ref + ' / ' + variant)
                row['used_by'].update(declared_by.get(ref, ()))
                row['ui_items'].add(item['item_id'])
    targets = {}
    for key, row in rows.items():
        targets.setdefault(row['target_path'], []).append(key)
    clash = sorted(keys for keys in targets.values() if len(keys) > 1)
    require(not clash, 'several resources map to one target file; add {kind} or {variant} to target_resources.copy.path: '
            + '; '.join(', '.join(ref + ' / ' + variant for ref, variant, _ in keys) for keys in clash))
    ordered = [{**row, 'used_by': sorted(row['used_by']), 'ui_items': sorted(row['ui_items'])} for _, row in sorted(rows.items())]
    copied = {(ref, variant) for ref, variant, _ in rows}
    return ({'schema_version': 1, 'producer': PRODUCER, 'convention': rules, 'rows': ordered,
             'renditions': [inventory[key] for key in sorted(inventory)]},
            [{'source_resource': ref, 'variant': variant, 'reason': reason} for (ref, variant), reason in sorted(uncovered.items())
             if (ref, variant) not in copied])


def undeclared(analysis):
    """File resources the scoped code uses that no node of a module's trees declares, with where they are used."""
    found = {}
    for _, evidence in _ui_items(analysis):
        index, tree = read_json(check_ref(evidence['source_index_ref'])), read_json(check_ref(evidence['ui_tree_ref']))
        for ref, sites in resource_fidelity.obligations(index, tree, evidence.get('resource_scope'))['undeclared'].items():
            found.setdefault(ref, sites)
    return [{'ref': ref, 'sites': sites} for ref, sites in sorted(found.items())]


def plan_ref(analysis):
    for row in analysis.get('dimensions', []):
        if row.get('dimension') == 'Resource' and row.get('copy_plan_ref'):
            require(row.get('status') == 'applicable', 'a copy plan belongs to an applicable Resource dimension')
            return row['copy_plan_ref']
    return None


def load(analysis, resolve=check_ref):
    """The copy plan a dimension analysis names, structurally checked; None when it names none."""
    ref = plan_ref(analysis)
    if ref is None:
        return None
    plan = read_json(resolve(ref))
    require(plan.get('schema_version') == 1 and plan.get('producer') == PRODUCER and isinstance(plan.get('rows'), list),
            'copy_plan_ref must name a derived resource copy plan')
    for row in plan['rows']:
        require(isinstance(row, dict) and all(isinstance(row.get(key), str) and row[key] for key in
                ('source_resource', 'variant', 'qualifier', 'target_path', 'accessor'))
                and isinstance(row.get('source_ref'), dict), 'copy plan row is incomplete')
    return plan


def rows(analysis, resolve=check_ref):
    plan = load(analysis, resolve)
    return plan['rows'] if plan else []


def freeze_check(s, analysis):
    """The plan a Spec names is the one its evidence and the project's convention give, row for row."""
    plan = load(analysis)
    rules = (s.get('target_resources') or {}).get('copy')
    if plan is None:
        # A stated convention is used: what the target loads as it is is copied, not authored item by item.
        require(not rules or not derive(analysis, rules)[0]['rows'],
                'the project states target_resources.copy: a module whose UI uses files the target loads as they are names its copy_plan_ref')
        return
    require(rules, 'a copy plan needs the project to state target_resources.copy')
    expected, _ = derive(analysis, rules)
    require(plan.get('convention') == expected['convention'], 'copy plan was derived under another target resource convention')
    require(digest(plan['rows']) == digest(expected['rows']),
            'copy plan differs from the one its UI evidence gives; derive it again with resource-plan')
    if 'renditions' in plan or rules.get('preserve_density'):
        require(plan.get('renditions') == expected['renditions'], 'copy plan rendition inventory differs from the source index')
        for rendition in expected['renditions']:
            for ref in rendition['source_refs']:
                check_ref(ref)
    for row in plan['rows']:
        check_ref(row['source_ref'])
        if s.get('target_root'):
            require(Path(row['target_path']).resolve().is_relative_to(Path(s['target_root']).resolve()), 'copy target outside target_root')


def _texts(code_files, skip):
    texts = []
    for ref in code_files or []:
        path = Path(ref['path'])
        if str(path.resolve()) in skip or not path.is_file() or path.stat().st_size > TEXT_LIMIT:
            continue
        data = path.read_bytes()
        if b'\0' not in data[:4096]:
            texts.append(data.decode('utf-8', errors='replace'))
    return texts


def verify_files(analysis):
    """Each planned copy is in the target and holds the legacy bytes."""
    for row in rows(analysis):
        target = Path(row['target_path'])
        require(target.is_file() and file_ref(target)['sha256'] == row['source_ref']['sha256'],
                'copied resource is missing or is not the legacy file: ' + row['source_resource'] + ' -> ' + row['target_path'])


def verify(analysis, code_files):
    """Acceptance: every copy is the legacy file, and the submitted code names each one by its accessor."""
    plan_rows = rows(analysis)
    if not plan_rows:
        return
    verify_files(analysis)
    texts = _texts(code_files, {str(Path(row['target_path']).resolve()) for row in plan_rows})
    unused = [row['source_resource'] + ' (' + row['accessor'] + ')' for row in plan_rows
              if not any(named(text, row['accessor']) for text in texts)]
    require(not unused, 'copied resources are not named by the submitted code: ' + ', '.join(unused[:12])
            + (' and ' + str(len(unused) - 12) + ' more' if len(unused) > 12 else ''))


def output_action(target, payload, allowed, previous_hash=None):
    """Plan a write against either missing output or the last accepted bytes."""
    if target.exists():
        old = target.read_bytes()
        if old == payload:
            return 'kept'
        require(previous_hash and hashlib.sha256(old).hexdigest() == previous_hash,
                'target file already differs from the legacy resource; refusing to overwrite: ' + str(target))
        require(allowed(target), 'copy target outside the assigned write scope: ' + str(target))
        return 'updated'
    require(allowed(target), 'copy target outside the assigned write scope: ' + str(target))
    return 'copied'


def sync(analysis, allowed, *, selected=None, previous=None):
    """Preflight the selected rows. With no selection, retain the whole-plan tool contract."""
    done = []
    for row in rows(analysis):
        target = Path(row['target_path'])
        if selected is not None and str(target) not in selected:
            continue
        payload = check_ref(row['source_ref']).read_bytes()
        action = output_action(target, payload, allowed, (previous or {}).get(str(target)))
        done.append((row, target, payload, action))
    return done
