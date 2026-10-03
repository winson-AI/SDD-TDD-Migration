"""File resources travel by path: what the scoped UI uses is copied into the target and named by one convention.

A picture, an animation file or a font is a file. Nobody re-creates it: the source index records its
path and hash, the project states once where such files go in the target and how code names them, and
the copy plan follows from the two. The plan is derived, never authored, so the Ledger recomputes it at
freeze and a row cannot be edited; acceptance compares each copy with the legacy bytes and looks for
its name in the submitted code. A resource the target cannot load as it is stays an authored item.
"""
from pathlib import Path
import re

from contracts import check_ref, digest, file_ref, read_json, require
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
    require(isinstance(value, dict) and set(value) <= {'root', 'path', 'accessor', 'formats', 'density'},
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
    return {'root': str(root), 'path': path, 'accessor': accessor, 'formats': list(formats), 'density': list(density)}


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
    rows, uncovered = {}, {}
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
            qualifier = resource_fidelity.rendition(renditions, rules['formats'], rules['density'])
            if qualifier is None or len(renditions[qualifier]) != 1:
                loaded = sorted({resource_facts.format_of(sources[0]['path']) for sources in renditions.values()})
                uncovered[(ref, variant)] = ('several source files declare it' if qualifier else
                                             'the target does not load ' + '/'.join(loaded) + ' as it is')
                continue
            source = renditions[qualifier][0]
            names = _names(ref, source, variant, qualifier)
            relative = rules['path'].format(**names)
            target = (Path(rules['root']) / relative).resolve()
            require(target.is_relative_to(Path(rules['root'])), 'copy path leaves target_resources.copy.root: ' + relative)
            row = rows.setdefault((ref, variant), {
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
            + '; '.join(', '.join(ref + ' / ' + variant for ref, variant in keys) for keys in clash))
    ordered = [{**row, 'used_by': sorted(row['used_by']), 'ui_items': sorted(row['ui_items'])} for _, row in sorted(rows.items())]
    return ({'schema_version': 1, 'producer': PRODUCER, 'convention': rules, 'rows': ordered},
            [{'source_resource': ref, 'variant': variant, 'reason': reason} for (ref, variant), reason in sorted(uncovered.items())
             if (ref, variant) not in rows])


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
    if plan is None:
        return
    rules = (s.get('target_resources') or {}).get('copy')
    require(rules, 'a copy plan needs the project to state target_resources.copy')
    expected, _ = derive(analysis, rules)
    require(plan.get('convention') == expected['convention'], 'copy plan was derived under another target resource convention')
    require(digest(plan['rows']) == digest(expected['rows']),
            'copy plan differs from the one its UI evidence gives; derive it again with resource-plan')
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
              if not any(row['accessor'] in text for text in texts)]
    require(not unused, 'copied resources are not named by the submitted code: ' + ', '.join(unused[:12])
            + (' and ' + str(len(unused) - 12) + ' more' if len(unused) > 12 else ''))


def sync(analysis, allowed):
    """Copy every planned file. `allowed(path)` says whether this assignment may write there; identical files are kept."""
    done = []
    for row in rows(analysis):
        source, target = check_ref(row['source_ref']), Path(row['target_path'])
        payload = source.read_bytes()
        if target.exists():
            require(target.read_bytes() == payload, 'target file already differs from the legacy resource; refusing to overwrite: ' + str(target))
            action = 'kept'
        else:
            require(allowed(target), 'copy target outside the assigned write scope: ' + str(target))
            action = 'copied'
        done.append((row, target, payload, action))
    return done
