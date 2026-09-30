"""Exact-resource discipline absorbed from android-resources-to-cmp.

There is no `approximate` strategy: Material-icon substitution, hand redraw, semantic
approximation, automatic rasterization and bitmap fallback are forbidden. A Resource
dimension item declares one exact strategy that must agree with its Android source type;
`manual_exact` needs inspected adaptation evidence and `blocked` is an explicit gap that can
never count as Green. Closure may not be reduced to the convenient subset: every presentation
reference the UI tree declares (including code-owned runtime overrides) must be covered.
Structural gates only; exactness itself is reviewed by the owning agent.
"""
import copy
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from contracts import Rejected, check_ref, file_ref, read_json, require

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
    if item.get('source_resource_ref'):
        check_ref(item['source_resource_ref'])
    if item.get('platform_resource') is not None:
        platform_facts(item)
    require(strategy in STRATEGIES, 'invalid resource strategy; approximation is not a strategy')
    kind = item.get('resource_kind')
    require(isinstance(kind, str) and kind.strip(), 'resource_kind required')
    require(kind in NORMAL or strategy in ESCAPES,
            'unsupported resource kind requires manual_exact with review evidence or blocked')
    if item.get('nine_patch'):
        # Byte-copying .9.png pixels never proves its stretch/content regions survive in CMP.
        require(strategy in ('compose_semantic_exact',) + ESCAPES,
                '.9.png needs compose_semantic_exact, manual_exact or blocked, never byte_copy')
    elif kind in NORMAL:
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
    if item.get('configuration_mapping') is not None:
        validate_configuration(item, item.get('qualifier', 'base'))


def consumers(item):
    """Normalize the historical scalar and current multi-consumer contract."""
    values = item.get('consumer')
    values = [values] if isinstance(values, str) else values
    require(isinstance(values, list) and values and
            all(isinstance(value, str) and value.strip() for value in values),
            'resource consumer must be a nonempty string or list of strings')
    require(len(values) == len(set(values)), 'duplicate resource consumer')
    return values


def covered_ids(item, *, strict=True):
    # Additional names are historical annotations, not proof that a resource exists.
    # Each v2 source/variant (including aliases) gets its own evidence-backed item.
    ids = [item.get('source_resource')]
    if not strict:
        ids += list(item.get('covered_resource_ids', []))
    return {i for i in ids if isinstance(i, str) and i}


def blocked(analysis):
    """Resource items explicitly recorded as not exactly migratable."""
    return sorted(item['item_id'] for row in analysis.get('dimensions', [])
                  if row.get('dimension') == 'Resource' and row.get('status') == 'applicable'
                  for item in row.get('items', []) if item.get('resource_strategy') == 'blocked')


def closure_gaps(analysis, declared_refs, *, strict=True):
    """Presentation refs the UI tree declares but no Resource item covers (reduced closure)."""
    covered = set()
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'Resource':
            continue
        for item in row.get('items', []):
            covered |= covered_ids(item, strict=strict)
    return sorted(set(declared_refs) - covered)


def xml_root(path):
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise Rejected('invalid resource XML: ' + str(exc)) from exc


def source_facts(source, source_id):
    """Read the actual Android file/values entry; never infer kind from an agent label."""
    source = Path(source)
    match = re.fullmatch(r'[@?]([a-z-]+)/([A-Za-z0-9_]+)', source_id or '')
    require(match, 'resource source ID must name a local Android resource')
    namespace, name = match.groups()
    directory, _, qualifier = source.parent.name.partition('-')
    require(source.parent.parent.name == 'res', 'resource source must be under Android res/')
    fact = {'source_ref': file_ref(source), 'qualifier': qualifier or 'base', 'nine_patch': source.name.endswith('.9.png')}
    if directory == 'values':
        root = xml_root(source)
        entries = [e for e in root if e.get('name') == name and
                   (e.get('type') if e.tag == 'item' else 'array' if e.tag in ('string-array', 'integer-array') else e.tag) == namespace]
        require(len(entries) == 1, 'resource source must contain exactly one matching values entry')
        entry = entries[0]
        fact['kind'] = namespace
        if namespace == 'dimen':
            unit = re.fullmatch(r'\s*-?[0-9.]+(sp|dp|dip|px|pt|in|mm)\s*', entry.text or '')
            fact['source_unit'] = unit.group(1) if unit else None
    else:
        require(directory == namespace and source.name.split('.')[0] == name, 'source ID differs from resource file')
        if namespace in ('drawable', 'mipmap', 'color'):
            fact['kind'] = xml_root(source).tag if source.suffix == '.xml' else 'bitmap'
        else:
            fact['kind'] = namespace
    return fact


def platform_facts(item):
    """Bind a system resource to its real, versioned SDK definition, read-only."""
    source_id = item.get('source_resource') or ''
    match = re.fullmatch(r'([@?])android:([a-z-]+)/([A-Za-z0-9_]+)', source_id)
    require(match, 'platform_resource requires an Android platform resource ID')
    platform = item.get('platform_resource')
    require(isinstance(platform, dict), 'Android platform resource requires platform_resource')
    api = platform.get('api_level')
    require(type(api) is int and api > 0, 'platform_resource requires a positive Android api_level')
    metadata = check_ref(platform.get('sdk_metadata_ref')).resolve()
    require(metadata.name == 'source.properties', 'platform resource requires SDK source.properties metadata')
    versions = re.findall(r'^\s*AndroidVersion\.ApiLevel\s*=\s*([0-9]+)\s*$', metadata.read_text(), re.MULTILINE)
    require(len(versions) == 1 and int(versions[0]) == api, 'platform api_level differs from SDK metadata')
    source = check_ref(item.get('source_resource_ref')).resolve()
    definitions = (metadata.parent / 'data/res').resolve()
    require(source.is_relative_to(definitions), 'platform definition must belong to the pinned SDK data/res')
    prefix, namespace, name = match.groups()
    facts = source_facts(source, prefix + namespace + '/' + name)
    facts['platform_resource'] = {'api_level': api, 'sdk_metadata_ref': platform['sdk_metadata_ref']}
    return facts


def validate_facts(item, legacy_root=None, *, check_configuration=False):
    if item.get('resource_strategy') == 'blocked' and not item.get('source_resource_ref'):
        validate_item(item)
        return {'status': 'source-unavailable', 'reason': item['blocked_reason']}
    if (item.get('source_resource') or '').startswith(('@android:', '?android:')):
        facts = platform_facts(item)
    else:
        source = check_ref(item.get('source_resource_ref'))
        if legacy_root:
            require(source.resolve().is_relative_to(Path(legacy_root).resolve()), 'resource source escapes legacy root')
        facts = source_facts(source, item.get('source_resource'))
    require(item.get('resource_kind') == facts['kind'], 'resource_kind differs from actual source')
    require(item.get('qualifier', 'base') == facts['qualifier'], 'resource qualifier differs from actual source')
    require(bool(item.get('nine_patch')) == facts['nine_patch'], 'nine_patch differs from actual source')
    if facts['kind'] == 'dimen':
        require(item.get('source_unit') == facts.get('source_unit'), 'source_unit differs from actual dimension')
    validate_item(item)
    if check_configuration or item.get('configuration_mapping') is not None:
        validate_configuration(item, facts['qualifier'])
    return facts


def target_qualifier(item):
    """Read directory routing; code-based routing must be explained by the mapping."""
    target = Path(item.get('target_resource', '').split('#', 1)[0])
    for parent in target.parents:
        directory, _, qualifier = parent.name.partition('-')
        if directory in ('values', 'drawable', 'mipmap', 'font', 'raw', 'color'):
            return qualifier or 'base'
    return 'code'


def validate_configuration(item, source_qualifier):
    """Require a reviewed route when the destination changes a source configuration."""
    if item.get('resource_strategy') == 'blocked':
        return  # An explicit gap has no completed destination to certify.
    destination = target_qualifier(item)
    mapping = item.get('configuration_mapping')
    if mapping is None:
        require(source_qualifier == destination or source_qualifier == 'base' and destination == 'code',
                'resource configuration changes require frozen configuration_mapping with scope evidence')
        return
    require(isinstance(mapping, dict), 'configuration_mapping must be an object')
    require(mapping.get('source_qualifier') == source_qualifier and mapping.get('target_qualifier') == destination,
            'configuration mapping differs from source or target qualifier')
    scope = mapping.get('scope')
    require(isinstance(scope, dict) and scope.get('reason'), 'configuration mapping needs scoped rationale')
    configs = scope.get('configurations')
    require(isinstance(configs, list) and configs and all(isinstance(c, str) and c.strip() for c in configs)
            and len(configs) == len(set(configs)) and source_qualifier in configs,
            'configuration scope must enumerate the source configuration')
    refs = mapping.get('evidence_refs')
    require(isinstance(refs, list) and refs, 'configuration mapping needs scope/condition evidence')
    for ref in refs:
        check_ref(ref)
    condition = mapping.get('consumer_condition')
    if source_qualifier != destination and set(configs) != {source_qualifier}:
        require(condition, 'multi-configuration adaptation requires consumer_condition')
    if condition is not None:
        require(isinstance(condition, dict) and isinstance(condition.get('expression'), str)
                and condition['expression'].strip(), 'consumer_condition needs a routing expression')
        require(isinstance(condition.get('consumers'), list)
                and all(isinstance(value, str) for value in condition['consumers'])
                and set(condition['consumers']) == set(consumers(item)),
                'consumer_condition must cover every planned consumer')


def prepare_exact(source, destination, source_id, strategy):
    """Pure preparation of bounded byte or single values-entry transfers."""
    source, destination = Path(source), Path(destination)
    if strategy == 'byte_copy':
        payload = source.read_bytes()
        require(not destination.exists() or destination.read_bytes() == payload,
                'target resource already differs; review adaptation before overwrite')
        return payload
    require(strategy == 'value_xml_exact', 'strategy requires reviewed manual implementation')
    namespace, name = source_id[1:].split('/')
    source_tree = xml_root(source)
    entries = [e for e in source_tree if e.get('name') == name and
               (e.get('type') if e.tag == 'item' else 'array' if e.tag in ('string-array', 'integer-array') else e.tag) == namespace]
    require(len(entries) == 1 and entries[0].tag in ('string', 'plurals', 'string-array', 'integer-array'),
            'value_xml_exact worker supports string/plurals/string-array/integer-array only')
    entry = copy.deepcopy(entries[0]); entry.tail = None
    require(not any((e.text or '').strip().startswith(('@', '?')) or any(str(v).startswith(('@', '?')) for v in e.attrib.values())
                    for e in entry.iter()), 'value_xml_exact unresolved references require reviewed adaptation')
    require(destination.parent.name.startswith('values') and destination.suffix == '.xml', 'values target must be values*/file.xml')
    target = xml_root(destination) if destination.exists() else ET.Element('resources')
    require(target.tag == 'resources', 'values destination must have resources root')
    existing = [e for e in target if e.get('name') == name]
    require(len(existing) <= 1, 'duplicate target values entry')
    if existing:
        old = copy.deepcopy(existing[0]); old.tail = None
        require(ET.tostring(old) == ET.tostring(entry), 'target values entry differs; refusing overwrite')
    else:
        target.append(entry)
    return ET.tostring(target, encoding='utf-8', xml_declaration=True) + b'\n'


def indexed_resources(index, declared_refs, resource_scope=None):
    """Bind this tree's resource candidates and reviewed exclusions, never another UI scope."""
    base = Path(index.get('androidRoot', ''))
    require(base.is_absolute(), 'source index needs absolute androidRoot')
    base = base.resolve()
    candidates = {}
    for row in index.get('resources', []):
        if row.get('ref') not in declared_refs:
            continue  # Other tree scopes are unrelated.
        if row['ref'].startswith(('@android:', '?android:')):
            continue  # Platform references have no local file.
        require(isinstance(row.get('path'), str) and row['path'], 'source index resource requires a source path')
        path = Path(row['path'])
        require(not path.is_absolute() and (base / path).resolve().is_relative_to(base),
                'source index resource escapes androidRoot')
        qualifier = row.get('qualifier', 'base')
        qualifier = 'base' if qualifier == 'default' else qualifier
        require(isinstance(qualifier, str) and qualifier, 'source index resource qualifier required')
        key = (row['ref'], qualifier, path.as_posix())
        require(key not in candidates, 'duplicate source index resource candidate')
        require(isinstance(row.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', row['sha256']),
                'source index resource requires sha256: ' + row['path'])
        candidates[key] = {'path': str((base / path).resolve()), 'sha256': row['sha256']}
    scope = resource_scope if resource_scope is not None else {}
    require(isinstance(scope, dict), 'resource_scope must be an object')
    exclusions = scope.get('exclusions', [])
    require(isinstance(exclusions, list), 'resource_scope.exclusions must be a list')
    excluded = set()
    for exclusion in exclusions:
        require(isinstance(exclusion, dict) and all(isinstance(exclusion.get(field), str) and exclusion[field].strip()
                for field in ('source_resource', 'qualifier', 'path', 'reason')),
                'resource exclusion needs source_resource, qualifier, path and reason')
        key = (exclusion['source_resource'], exclusion['qualifier'], exclusion['path'])
        require(key in candidates and key not in excluded, 'resource exclusion must name one indexed candidate in this UI scope')
        refs = exclusion.get('evidence_refs')
        require(isinstance(refs, list) and refs, 'resource exclusion requires review evidence')
        for ref in refs:
            check_ref(ref)
        excluded.add(key)
    active = {key: ref for key, ref in candidates.items() if key not in excluded}
    require({key[0] for key in active} == {key[0] for key in candidates},
            'resource scope excludes every source candidate for a declared reference')
    for ref in active.values():
        check_ref(ref)
    return active


def require_indexed_closure(analysis, legacy_root=None):
    """Every applicable indexed variant needs the same source baseline in a Resource item."""
    import ui_evidence
    items = [item for row in analysis.get('dimensions', [])
             if row.get('dimension') == 'Resource' and row.get('status') == 'applicable'
             for item in row.get('items', [])]
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for ui_item in row.get('items', []):
            evidence = (ui_item.get('semantic_model') or {}).get('ui_evidence')
            if not evidence:
                continue
            index = read_json(check_ref(evidence.get('source_index_ref')))
            tree = read_json(check_ref(evidence.get('ui_tree_ref')))
            require(index.get('scope') == tree.get('scope'), 'UI source index and tree scopes differ')
            if legacy_root:
                require(Path(index.get('androidRoot', '')).resolve() == Path(legacy_root).resolve(),
                        'UI resource source index belongs to another legacy root')
            scope = evidence.get('resource_scope')
            declared = set(ui_evidence.resource_refs(tree))
            active = indexed_resources(index, declared, scope)
            # Platform rows intentionally have no legacy file candidate; their SDK
            # definition and version are still rechecked whenever this plan is read.
            for item in items:
                if item.get('source_resource') in declared and item['source_resource'].startswith(('@android:', '?android:')):
                    validate_facts(item, legacy_root, check_configuration=True)
            for exclusion in (scope or {}).get('exclusions', []):
                configurations = {config for item in items if item.get('source_resource') == exclusion['source_resource']
                                  for config in ((item.get('configuration_mapping') or {}).get('scope') or {}).get('configurations', [])}
                require(exclusion['qualifier'] not in configurations,
                        'resource exclusion conflicts with frozen configuration scope')
            for (source_id, qualifier, _), source_ref in active.items():
                matches = [item for item in items if item.get('source_resource') == source_id
                           and item.get('qualifier', 'base') == qualifier]
                require(len(matches) == 1, 'UI resource closure requires one item for ' + source_id + ' / ' + qualifier)
                planned = matches[0].get('source_resource_ref') or {}
                require(Path(planned.get('path', '')).resolve() == Path(source_ref['path'])
                        and planned.get('sha256') == source_ref['sha256'],
                        'UI resource facts and Resource item use different source baselines: ' + source_id + ' / ' + qualifier)


def require_exact_closure(analysis, declared_refs, legacy_root=None):
    """Version 2 requires an exact strategy for resources consumed by the UI closure."""
    declared = set(declared_refs)
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'Resource' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            if not covered_ids(item).intersection(declared):
                continue
            require(item.get('resource_strategy'),
                    'UI resource closure requires resource_strategy: ' + item['item_id'])
            validate_item(item)
            validate_facts(item, legacy_root, check_configuration=True)
    require_indexed_closure(analysis, legacy_root)


def freeze_gate(s, m):
    """New v2 freezes verify every declared exact resource, including non-UI resources."""
    ref = (m.get('plan') or {}).get('dimension_analysis_ref')
    if s.get('evidence_contract_version', 1) < 2 or not ref:
        return
    variants, destinations = set(), {}
    for row in read_json(check_ref(ref))['dimensions']:
        if row.get('dimension') == 'Resource' and row.get('status') == 'applicable':
            for item in row.get('items', []):
                if item.get('resource_strategy'):
                    facts = validate_facts(item, s.get('legacy_root'), check_configuration=True)
                    if facts.get('status') == 'source-unavailable':
                        continue
                    key = (item['source_resource'], facts['qualifier'])
                    require(key not in variants, 'duplicate resource source/qualifier; share one item across consumers')
                    variants.add(key)
                    if item['resource_strategy'] != 'blocked':
                        target_path = Path(item.get('target_resource', '').split('#', 1)[0]).resolve()
                        target = (item['source_resource'], target_path)
                        destinations.setdefault(target, []).append(item)
    for items in destinations.values():
        if len(items) <= 1:
            continue
        conditions = [(item.get('configuration_mapping') or {}).get('consumer_condition') for item in items]
        require(all(conditions), 'resource variants share a destination without explicit consumer routing')
        require(len({condition['expression'] for condition in conditions}) == len(conditions),
                'resource variants share a destination with indistinguishable routing')
