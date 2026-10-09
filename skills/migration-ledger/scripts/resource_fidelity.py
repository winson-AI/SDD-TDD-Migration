"""Exact-resource discipline absorbed from android-resources-to-cmp.

There is no `approximate` strategy: Material-icon substitution, hand redraw, semantic
approximation, automatic rasterization and bitmap fallback are forbidden. A Resource
dimension item declares one exact strategy that must agree with its Android source type;
`manual_exact` needs inspected adaptation evidence and `blocked` is an explicit gap that can
never count as Green. Closure may not be reduced to the convenient subset: every presentation
reference the UI tree declares (including code-owned runtime overrides) must be covered.
Structural gates only; exactness itself is reviewed by the owning agent.
"""
from collections import deque
import copy
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from contracts import Rejected, check_ref, file_ref, intact, named, nonempty, read_json, require
import resource_facts
import resource_signals

STRATEGIES = ('exact_vector_xml', 'byte_copy', 'value_xml_exact', 'design_token_exact',
              'compose_semantic_exact', 'source_equivalent', 'manual_exact', 'blocked')
# Android source kind -> the normal exact strategy it must use.
NORMAL = {'vector': 'exact_vector_xml', 'bitmap': 'byte_copy', 'font': 'byte_copy', 'raw': 'byte_copy', 'asset': 'byte_copy',
          'string': 'value_xml_exact', 'plurals': 'value_xml_exact', 'array': 'value_xml_exact',
          'color': 'design_token_exact', 'dimen': 'design_token_exact', 'attr': 'design_token_exact',
          'selector': 'compose_semantic_exact', 'layer-list': 'compose_semantic_exact',
          'shape': 'compose_semantic_exact', 'inset': 'compose_semantic_exact', 'rotate': 'compose_semantic_exact',
          'clip': 'compose_semantic_exact', 'scale': 'compose_semantic_exact', 'level-list': 'compose_semantic_exact',
          'transition': 'compose_semantic_exact', 'ripple': 'compose_semantic_exact'}
# Available for any kind only when exactness cannot be proven.
ESCAPES = ('manual_exact', 'blocked')
# Resources that are files the UI shows or uses as they are; code that names one must be accounted for.
FILE_KINDS = ('drawable', 'mipmap', 'raw', 'font')
# Strategies that leave a resource in the target which consumers name; a hand replacement or a gap leaves none.
WIRED = ('exact_vector_xml', 'byte_copy', 'value_xml_exact', 'design_token_exact', 'compose_semantic_exact', 'source_equivalent')
# What the user sees as a picture; only a still image or a vector drawable renders offline to something a check can measure.
GRAPHIC_KINDS = ('bitmap', 'vector', 'code-drawn', 'animation-list', 'animated-selector', 'animated-vector', 'adaptive-icon')
DEVIATIONS = ('redraw', 'degrade', 'absent')
# Image sources with no resource file: what the target must do, per kind of recorded source.
SIGNAL_STRATEGIES = {'remote-image': ('source_equivalent', 'manual_exact', 'blocked'),
                     'dynamic-resource': ('manual_exact', 'blocked'), 'data-binding': ('manual_exact', 'blocked'),
                     'code-drawn': ('manual_exact', 'blocked')}


def validate_item(item):
    """Presence-triggered: an item declaring a strategy is held to the exact-resource rules."""
    strategy = item.get('resource_strategy')
    if strategy is None:
        return
    if item.get('source_signal'):
        return validate_signal_strategy(item, strategy)
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


def replacement(item):
    """A picture the legacy app ships is copied. An item that replaces it by hand says what stops the copy."""
    replaced = item.get('resource_strategy') == 'manual_exact' and not item.get('source_signal') and is_graphic(item)
    require(not replaced or isinstance(item.get('copy_blocker'), str) and item['copy_blocker'].strip(),
            'a picture replaced by hand states why the legacy file cannot be copied as it is (copy_blocker)')


def consumers(item):
    """Normalize the historical scalar and current multi-consumer contract."""
    values = item.get('consumer')
    values = [values] if isinstance(values, str) else values
    require(isinstance(values, list) and values and
            all(isinstance(value, str) and value.strip() for value in values),
            'resource consumer must be a nonempty string or list of strings')
    require(len(values) == len(set(values)), 'duplicate resource consumer')
    return values


def covered_ids(item):
    # Each source/variant (including aliases) gets its own evidence-backed item; extra names prove nothing.
    source = item.get('source_resource')
    return {source} if isinstance(source, str) and source else set()


def blocked(analysis):
    """Resource items explicitly recorded as not exactly migratable."""
    return sorted(item['item_id'] for row in analysis.get('dimensions', [])
                  if row.get('dimension') == 'Resource' and row.get('status') == 'applicable'
                  for item in row.get('items', []) if item.get('resource_strategy') == 'blocked')


def carried(analysis):
    """The values a module's parameter sheet carries (`values:string/title` is `@string/title`). Each is materialised
    for the target with its variants and used there by its key, and the sheet is derived again and compared at freeze:
    a value travels by the sheet and needs no Resource item of its own."""
    import ui_parameters
    return {'@' + row['id'][len('values:'):] for row in ui_parameters.parameters(analysis) if str(row.get('id', '')).startswith('values:')}


def closure_gaps(analysis, declared_refs):
    """Presentation refs the UI tree declares but neither a Resource item, the copy plan nor the parameter sheet covers
    (reduced closure)."""
    import resource_copy
    covered = {row['source_resource'] for row in resource_copy.rows(analysis)} | carried(analysis)
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'Resource':
            continue
        for item in row.get('items', []):
            covered |= covered_ids(item)
    return sorted(set(declared_refs) - covered)


def xml_root(path):
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise Rejected('invalid resource XML: ' + str(exc)) from exc


def source_facts(source, source_id):
    """Read the actual Android file/values entry; never infer kind from an agent label."""
    source = Path(source)
    if (source_id or '').startswith('asset:'):
        parts = source.parts
        require('assets' in parts and '/'.join(parts[parts.index('assets') + 1:]) == source_id[len('asset:'):],
                'asset source ID differs from the asset file')
        return {'source_ref': file_ref(source), 'qualifier': 'base', 'nine_patch': False, 'kind': 'asset'}
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
    if item.get('source_signal'):
        validate_item(item)
        return {'status': 'signal', 'signal': item['source_signal']}
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
    if (item.get('source_resource') or '').split('/')[0] in ('@drawable', '@mipmap'):
        # A density names a rendition of the same picture, not a configuration the target has to route.
        source_qualifier = resource_facts.variant(source_qualifier)[0]
        destination = destination if destination == 'code' else resource_facts.variant(destination)[0]
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


def require_target_binding(item, target_root):
    """A migrated resource is a file of the target project, has a name consumers use, and is used by target files."""
    strategy = item.get('resource_strategy')
    if strategy in (None, 'blocked'):
        return
    label, root = item.get('item_id', '?'), Path(target_root).resolve()
    target, _, name = item.get('target_resource', '').partition('#')
    require(Path(target).is_absolute() and Path(target).resolve().is_relative_to(root),
            label + ': target_resource must be a file of the target project')
    for consumer in consumers(item):
        path = Path(consumer.split('#', 1)[0])
        require(path.is_absolute() and path.resolve().is_relative_to(root),
                label + ': a consumer is a file of the target project, not a document about it')
    require(strategy not in WIRED or name.strip(), label + ': target_resource needs #<the name consumers use for it>')


def require_consumer_files(item, write_paths):
    """What an implementation result is held to is asked of the plan it is written from: a migrated resource is
    consumed by named production files, each one the module writes or one the target already holds. A directory or a
    note about the consumer cannot be shown in a result, so it is refused before code is written."""
    if item.get('resource_strategy') in (None, 'blocked'):
        return
    label, scope = item.get('item_id', '?'), [Path(path).resolve() for path in write_paths or []]
    for consumer in consumers(item):
        path = Path(consumer.split('#', 1)[0])
        require(path.suffix and not path.is_dir(), label + ': a consumer is a production file, not a directory or a note: ' + consumer)
        # A module registered without write paths (the minimal low-level API) is held to the shape alone.
        require(not scope or path.is_file() or any(path.resolve().is_relative_to(base) for base in scope),
                label + ': a consumer is a file this module writes or the target already holds: ' + consumer)


def verify_exact(item, target):
    """The target holds what the frozen strategy promises: the legacy bytes, the legacy entry, or the converted vector."""
    strategy, source, label = item.get('resource_strategy'), item.get('source_resource_ref') or {}, item.get('item_id', '?')
    if strategy == 'byte_copy':
        require(file_ref(target)['sha256'] == source.get('sha256'), label + ': byte_copy target is not the legacy file')
    elif strategy == 'value_xml_exact':
        prepare_exact(source.get('path', ''), target, item['source_resource'], strategy)  # rejects an entry that differs
        name = item['source_resource'][1:].split('/')[1]
        require(any(entry.get('name') == name for entry in xml_root(target)), label + ': value_xml_exact target lacks the legacy entry')
    elif strategy == 'exact_vector_xml':
        from types import SimpleNamespace
        from lean_tools import resource_tool
        try:
            resource_tool.prepare_vector(SimpleNamespace(
                android_root=Path(source.get('path', '')).anchor, target_root=Path(target).anchor, source=source.get('path', ''),
                destination=str(target), source_id=item['source_resource'], target_ref=item.get('target_resource', '').partition('#')[2] or '-',
                consumer=consumers(item), resolve_ref=item.get('resolve_ref', []), consumer_tint=item.get('consumer_tint')))
        except resource_tool.ResourceError as exc:
            require(False, label + ': exact_vector_xml target is not the conversion of the legacy vector (' + str(exc) + ')')


def verify_wiring(item, consumer_paths):
    """Each consumer names the migrated resource; a file that never mentions it does not use it."""
    name = item.get('target_resource', '').partition('#')[2].strip()
    if item.get('resource_strategy') not in WIRED or not name:
        return
    for path in consumer_paths:
        require(named(Path(path).read_text(encoding='utf-8', errors='replace'), name),
                item.get('item_id', '?') + ': consumer ' + Path(path).name + ' never names ' + name)


def _suffix(item):
    return Path((item.get('source_resource_ref') or {}).get('path') or '').suffix.lower()


def is_graphic(item):
    """A picture the user sees: drawables, animations, drawing code, and image or animation files in raw/assets.

    A raw or asset file is judged by its suffix; other files there (data, fonts, XML) are not pictures."""
    kind = item.get('resource_kind')
    return kind in GRAPHIC_KINDS or kind in ('raw', 'asset') and _suffix(item) in resource_facts.RASTER_SUFFIXES + ('.svg', '.json')


def is_picture(item):
    """Anything the user sees as an image: a graphic, or an image source with no resource file."""
    return is_graphic(item) or item.get('resource_kind') in SIGNAL_STRATEGIES


def measurable(item):
    """Whether the source renders offline to one still picture an image check can compare.

    A nine-patch does not: what the screen shows is its stretched form, never the file's own pixels."""
    kind = item.get('resource_kind')
    still = kind in ('bitmap', 'vector') or kind in ('raw', 'asset') and _suffix(item) in resource_facts.RASTER_SUFFIXES
    return still and not item.get('nine_patch')


def exactness(item):
    """How closely the target reproduces the source: exact, non-exact, approved-deviation, blocked, manual or unrecorded.

    A picture the legacy app ships that is replaced by hand (manual_exact) is non-exact: only a measurement on the
    target stands behind it. Drawing code has no file to copy and is ported like other code, so its hand port stays
    manual: reviewed, not measured. A human-approved deviation is still a difference; it is disclosed as one."""
    strategy = item.get('resource_strategy')
    if strategy is None:
        return 'unrecorded'
    if strategy == 'blocked':
        return 'blocked'
    if item.get('deviation'):
        return 'approved-deviation'
    if strategy == 'manual_exact':
        return 'non-exact' if is_graphic(item) and item.get('resource_kind') != 'code-drawn' else 'manual'
    return 'exact'


def require_graphic_proof(items, plan, declared, carried):
    """A picture replaced by hand is measured on the target or is a deviation a human approved with the plan.

    The check is declared by the UI model and carried by a visual path, so the result shows on the screen; the
    deviation names one of the plan's allowed alternatives, so the difference is part of what was approved.
    A still image takes either. An animation or a nine-patch cannot be rendered offline, which leaves the deviation:
    a review alone never backs the replacement of a picture the legacy app ships. Drawing code has no file to copy;
    it is ported like other code, keeps its review, and takes no check."""
    allowed = (plan.get('decision_envelope') or {}).get('allowed_alternatives', [])
    for item in items:
        label = item.get('item_id', '?')
        replaced = item.get('resource_strategy') == 'manual_exact' and is_graphic(item)
        require(replaced or item.get('deviation') is None, label + ': a deviation describes a manual_exact replacement of a graphic')
        if not replaced:
            continue
        check, deviation = item.get('image_check'), item.get('deviation')
        if measurable(item):
            require(bool(check) != bool(deviation),
                    label + ': a non-exact graphic needs either an image_check carried by a visual PATH or an approved deviation, not both and not neither')
        else:
            require(not check, label + ': animations, nine-patches and drawing code are not rendered offline, so an image_check cannot measure them')
            require(deviation or item.get('resource_kind') == 'code-drawn',
                    label + ': an animation or nine-patch replaced by hand cannot be measured, so it needs an approved deviation')
        if check:
            found = declared.get(check)
            require(found and check in carried, label + ': image_check ' + str(check) + ' must be declared by a UI model and carried by a visual path')
            family = lambda value: 'base' if value in (None, '', 'default') else value
            require(found[0]['source_resource'] == item.get('source_resource') and family(found[0]['qualifier']) == family(item.get('qualifier')),
                    label + ': image_check must be the check of this resource and qualifier')
        elif deviation is not None:
            require(isinstance(deviation, dict) and deviation.get('kind') in DEVIATIONS
                    and isinstance(deviation.get('reason'), str) and deviation['reason'].strip(),
                    label + ': deviation needs a kind (' + ', '.join(DEVIATIONS) + ') and a reason')
            require(deviation.get('alternative') in allowed,
                    label + ': deviation.alternative must be one of decision_envelope.allowed_alternatives, which a human approves with the plan')
            for ref in deviation.get('evidence_refs') or []:
                check_ref(ref)


def validate_signal_strategy(item, strategy):
    """An image source without a resource file: its kind must match the strategy the target can honestly use."""
    kind = item.get('resource_kind')
    require(kind in SIGNAL_STRATEGIES, 'image source item needs resource_kind remote-image, dynamic-resource, data-binding or code-drawn')
    require(strategy in SIGNAL_STRATEGIES[kind], kind + ' source requires ' + ' or '.join(SIGNAL_STRATEGIES[kind]))
    if strategy == 'manual_exact':
        check_ref(item.get('adaptation_evidence_ref'))
    if strategy == 'blocked':
        require(item.get('blocked_reason'), 'blocked image source needs an explicit reason')


def validate_signal_item(item, signal, item_ids, api_contracts=None):
    """The item for one recorded image source states how the target reproduces what the legacy source does."""
    require(item.get('resource_kind') == signal['kind'], 'resource_kind differs from the recorded image source ' + signal['id'])
    validate_signal_strategy(item, item.get('resource_strategy'))
    if item['resource_strategy'] != 'source_equivalent':
        return
    target = item.get('target_source')
    require(isinstance(target, str) and target.strip(), 'source_equivalent needs target_source: the URL or field the target loads')
    if signal['source']['kind'] == 'url-literal':
        require(target == signal['source']['value'], 'target_source must load the same URL the legacy source loads')
    if signal.get('api') and (api_contracts is not None or item.get('api_binding')):
        origin = item.get('image_source_review') or {}
        if origin.get('kind') == 'non-api':
            require(not item.get('api_binding') and origin.get('reason'), 'non-API image origin conflicts with API binding or lacks rationale')
            for ref in nonempty(origin.get('evidence_refs'), 'non-API image origin evidence'): check_ref(ref)
        else:
            binding = item.get('api_binding') or {}; contract = (api_contracts or {}).get(binding.get('api_id'))
            require(contract, 'image API source requires api_binding to an in-scope contract')
            field = binding.get('response_field'); source = signal['api']
            known = {source.get('field')} | {row.get('jsonKey') for row in source.get('candidates', [])}
            require(field in known and field in contract['target']['response_mapping'], 'image API response field differs from recorded source')
            require(target == contract['target']['response_mapping'][field], 'image target_source differs from API response mapping')
    mapping = item.get('loader_mapping')
    require(isinstance(mapping, dict), 'source_equivalent needs loader_mapping for the loader behaviour it replaces')
    for key in resource_signals.PLACEHOLDERS:
        if (signal.get('loader') or {}).get(key):
            value = mapping.get(key)
            require((isinstance(value, str) and value in item_ids) or (isinstance(value, dict) and value.get('absent')),
                    'loader_mapping.' + key + ' must name the Resource item for the legacy ' + key + ' image, or state why it is absent')
    for name in (signal.get('loader') or {}).get('transforms', []):
        require(any(isinstance(row, dict) and row.get('legacy') == name and row.get('target')
                    for row in mapping.get('transforms', []) if isinstance(mapping.get('transforms'), list)),
                'loader_mapping.transforms must map the legacy transform ' + name)


def signal_exclusions(index, scope):
    """Image sources a reviewer scoped out of this UI target, each with its reason and evidence."""
    rows = (scope or {}).get('signal_exclusions', [])
    require(isinstance(rows, list), 'resource_scope.signal_exclusions must be a list')
    known, excluded = {s['id'] for s in index.get('imageSources', [])}, {}
    for row in rows:
        require(isinstance(row, dict) and all(isinstance(row.get(field), str) and row[field].strip()
                for field in ('signal_id', 'reason')), 'signal exclusion needs signal_id and reason')
        require(row['signal_id'] in known and row['signal_id'] not in excluded,
                'signal exclusion must name one recorded image source of this UI scope')
        refs = row.get('evidence_refs')
        require(isinstance(refs, list) and refs, 'signal exclusion requires review evidence')
        for ref in refs:
            check_ref(ref)
        excluded[row['signal_id']] = row
    return excluded


def _scoped_out(site, rows):
    symbol = site.get('symbol') or ''
    return any((not row.get('ref') or row['ref'] == site['ref']) and
               (not row.get('symbol') or symbol == row['symbol'] or symbol.startswith(row['symbol'] + '.')) for row in rows)


def usage_exclusions(index, scope):
    """Code a reviewer scoped out of this UI target: a class or function, a reference, or a reference inside one."""
    rows = (scope or {}).get('usage_exclusions', [])
    require(isinstance(rows, list), 'resource_scope.usage_exclusions must be a list')
    sites = [site for source in index.get('sourceFiles', []) for site in source.get('resourceUsages', [])]
    # A class may hold no resource reference at all and still set sizes and colours; it can be scoped out just the same.
    sites += [{'ref': '', 'symbol': row.get('symbol')} for source in index.get('sourceFiles', []) for row in source.get('parameters', [])]
    for row in rows:
        require(isinstance(row, dict) and all(isinstance(row.get(key, ''), str) for key in ('symbol', 'ref'))
                and (row.get('symbol') or row.get('ref')) and isinstance(row.get('reason'), str) and row['reason'].strip(),
                'usage exclusion needs a symbol or a ref, and a reason')
        require(any(_scoped_out(site, [row]) for site in sites),
                'usage exclusion must name a class, function or reference the scoped code uses')
        refs = row.get('evidence_refs')
        require(isinstance(refs, list) and refs, 'usage exclusion requires review evidence')
        for ref in refs:
            check_ref(ref)
    return rows


def scoped_out_refs(index, scope):
    """References whose every use in the scoped code a reviewer scoped out: no node of this UI target shows them."""
    excluded, kept, dropped = usage_exclusions(index, scope), set(), set()
    for source in index.get('sourceFiles', []):
        for site in source.get('resourceUsages', []):
            (dropped if _scoped_out(site, excluded) else kept).add(site['ref'])
    return dropped - kept


def used_files(index, scope=None):
    """{reference: where it is used} for the file resources the scoped code names, less what a reviewer scoped out.

    A setter the collector knows is one way to show a picture; a project's own method, a constructor or a
    texture loader is another. Whatever receives it, the reference is used and has to be accounted for."""
    excluded, used = usage_exclusions(index, scope), {}
    for source in index.get('sourceFiles', []):
        for site in source.get('resourceUsages', []):
            if site['ref'].lstrip('@').split('/')[0] in FILE_KINDS and not _scoped_out(site, excluded):
                used.setdefault(site['ref'], []).append({**site, 'sourcePath': source['path']})
    return used


def require_declared(needed):
    """Every file resource the scoped code uses is on a node of the tree, so it has an owner and enters the closure."""
    missing = needed['undeclared']
    if not missing:
        return
    def shown(ref):
        site = missing[ref][0]
        where = site['sourcePath'].rsplit('/', 1)[-1] + ':' + str(site['line'])
        return ref + ' (' + ' '.join(part for part in (where, site.get('symbol'), 'via ' + site['call'] if site.get('call') else None) if part) + ')'
    listed = sorted(missing)
    require(False, 'UI tree omits file resources the scoped code uses: ' + ', '.join(shown(ref) for ref in listed[:12])
            + (' and ' + str(len(listed) - 12) + ' more' if len(listed) > 12 else '')
            + '; declare each on the node that shows it, or scope it out in resource_scope.usage_exclusions with evidence')


def resource_groups(active):
    """{(reference, variant): {qualifier: [source]}}: one entry per resource the target needs.

    The densities of a drawable are renditions of one picture, so they share an entry; night, locale and
    every other qualifier name different content and keep their own."""
    groups = {}
    for (ref, qualifier, _), source in active.items():
        picture = ref.split('/')[0] in ('@drawable', '@mipmap')
        key = (ref, resource_facts.variant(qualifier)[0] if picture else qualifier)
        groups.setdefault(key, {}).setdefault(qualifier, []).append(source)
    return groups


def item_variant(item):
    ref, qualifier = item.get('source_resource') or '', item.get('qualifier', 'base')
    return resource_facts.variant(qualifier)[0] if ref.split('/')[0] in ('@drawable', '@mipmap') else qualifier


def rendition(renditions, formats=None, order=None):
    """Which density of a picture to take: the first of a project's order that the target loads, else a vector, else the densest."""
    usable = [q for q in renditions if formats is None or resource_facts.format_of(renditions[q][0]['path']) in formats]
    for qualifier in order or []:
        named = [q for q in usable if resource_facts.variant(q)[1] == qualifier or (qualifier == 'base' and resource_facts.variant(q)[1] is None)]
        if named:
            return named[0]
    rank = lambda q: (renditions[q][0]['path'].endswith('.xml'), resource_facts.density_scale(q) or 0, q)
    return max(usable, key=rank) if usable else None


def obligations(index, tree, scope=None):
    """What one UI target's Resource items must cover.

    Every reference the tree declares, whatever the drawables and theme attributes behind them name in
    turn, the images, menus and manifest icons the sources reach, and every recorded image source
    that no reviewer scoped out. A theme attribute reached only through another resource is followed
    to the values its styles give it; its own definition is the project's theme, not a resource to copy.
    `undeclared` lists file resources the scoped code uses that no node of the tree declares."""
    import ui_evidence
    rows = {}
    for row in index.get('resources', []):
        rows.setdefault(row['ref'], []).append(row)
    attrs = {a['ref']: a for a in index.get('themeAttrs', [])}
    excluded = signal_exclusions(index, scope)
    signals = {s['id']: s for s in index.get('imageSources', []) if s['kind'] != 'design-sample' and s['id'] not in excluded}
    declared = set(ui_evidence.resource_refs(tree))
    roots = set(declared) | {ref for ref in rows if ref.startswith('asset:')}
    for document in index.get('xmlResources', []):
        roots.update(document.get('resourceRefs', []))
    held = set()   # what a recorded image source names itself: its loader's placeholders, a run-time name's candidates
    for signal in signals.values():
        held.update(resource_signals.source_refs(signal))
    roots.update(held)
    required, seen, queue = set(), set(), deque(sorted(roots))
    while queue:
        ref = queue.popleft()
        if ref in seen:
            continue
        seen.add(ref)
        document = ref.lstrip('@?').partition('/')[0] in resource_signals.DOCUMENT_KINDS
        if ref in declared or not (document or ref.startswith('?attr/')):
            required.add(ref)
        for row in rows.get(ref, []):
            queue.extend(nested['ref'] for nested in row.get('references', []))
        for definition in attrs.get(ref, {}).get('definitions', []):
            queue.extend(resource_facts.references(definition['value']))
    return {'refs': required, 'signals': signals,
            'undeclared': {ref: sites for ref, sites in used_files(index, scope).items() if ref not in declared | held}}


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


def skeletons(index, tree, scope=None):
    """Item skeletons for everything one UI target's Resource items must cover, every recorded fact filled in.

    The Spec-Designer chooses strategy, target and consumer wiring; sizes, kinds, qualifiers, source
    hashes, nested references, who declares the reference and what a loader replaces come from the index."""
    import ui_evidence
    needed = obligations(index, tree, scope)
    declared_by = {}
    for node in ui_evidence.tree_nodes(tree):
        refs = set(node.get('presentation', {}).get('resourceRefs', []))
        for rule in node.get('dynamicRules', []):
            refs.update(rule.get('resourceRefs', []))
        for ref in refs:
            declared_by.setdefault(ref, set()).add(ui_evidence.stable_node_id(node['id']))
    rows = {}
    for row in index.get('resources', []):
        qualifier = 'base' if row.get('qualifier', 'base') == 'default' else row.get('qualifier', 'base')
        rows[(row['ref'], qualifier, str((Path(index['androidRoot']) / row['path']).resolve()) if row.get('path') else None)] = row
    resources = []
    for (ref, _), renditions in sorted(resource_groups(indexed_resources(index, needed['refs'], scope)).items()):
        qualifier = rendition(renditions)
        source = renditions[qualifier][0]
        row = rows[(ref, qualifier, source['path'])]
        skeleton = {'source_resource': ref, 'qualifier': qualifier, 'source_resource_ref': dict(source)}
        if len(renditions) > 1:
            skeleton['renditions'] = sorted(renditions)
        try:
            fact = source_facts(source['path'], ref)
            skeleton.update(resource_kind=fact['kind'], nine_patch=fact['nine_patch'])
            skeleton['normal_strategy'] = NORMAL.get(fact['kind'])
            if fact.get('source_unit'):
                skeleton['source_unit'] = fact['source_unit']
        except Rejected as exc:
            skeleton['problem'] = str(exc)
        for key in ('facts', 'references', 'via'):
            if row.get(key):
                skeleton[key] = row[key]
        if ref in declared_by:
            skeleton['declared_by'] = sorted(declared_by[ref])
        resources.append(skeleton)
    signals = [{'source_signal': sid, 'resource_kind': row['kind'], 'strategies': list(SIGNAL_STRATEGIES[row['kind']]),
                **{key: value for key, value in row.items() if key not in ('id', 'kind')}}
               for sid, row in sorted(needed['signals'].items())]
    return {'resources': resources, 'signals': signals}


def require_indexed_closure(analysis, legacy_root=None):
    """Every applicable indexed variant needs the same source baseline in a Resource item."""
    import ui_evidence
    import resource_copy
    api_contracts = None
    if analysis.get('api_inventory_ref') or analysis.get('api_review'):
        import api_contract
        all_items = {item['item_id']: {**item, 'dimension': row['dimension']}
                     for row in analysis.get('dimensions', []) for item in row.get('items', [])}
        _, api_contracts = api_contract.read(analysis, all_items)
    items = [item for row in analysis.get('dimensions', [])
             if row.get('dimension') == 'Resource' and row.get('status') == 'applicable'
             for item in row.get('items', [])]
    copied = {(row['source_resource'], row['variant']): row for row in resource_copy.rows(analysis)}
    by_sheet = carried(analysis)
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
            needed = obligations(index, tree, scope)
            require_declared(needed)
            declared = needed['refs']
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
            for (source_id, variant), renditions in resource_groups(active).items():
                label = source_id + ' / ' + variant
                matches = [item for item in items if item.get('source_resource') == source_id and item_variant(item) == variant]
                copy = copied.get((source_id, variant))
                if source_id in by_sheet and not matches and not copy:
                    continue  # the sheet carries this value and its variants
                require(len(matches) + bool(copy) == 1, 'UI resource closure requires one item for ' + label)
                qualifier = copy['qualifier'] if copy else matches[0].get('qualifier', 'base')
                require(qualifier in renditions, 'resource item names a rendition the source index does not hold: ' + source_id + ' / ' + qualifier)
                planned = (copy['source_ref'] if copy else matches[0].get('source_resource_ref')) or {}
                # A second file declaring the same resource is another candidate: scope it out or the baselines differ.
                for source_ref in renditions[qualifier]:
                    require(Path(planned.get('path', '')).resolve() == Path(source_ref['path'])
                            and planned.get('sha256') == source_ref['sha256'],
                            'UI resource facts and Resource item use different source baselines: ' + label)
            item_ids = {item['item_id'] for item in items}
            for signal_id, signal in sorted(needed['signals'].items()):
                matches = [item for item in items if item.get('source_signal') == signal_id]
                require(len(matches) == 1, 'UI image source closure requires one item for ' + signal_id + ' (' + signal['kind'] + ')')
                validate_signal_item(matches[0], signal, item_ids, api_contracts)


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


def freeze_gate(s, m, allocation=True):
    """Freeze verifies every declared exact resource, including non-UI resources. What concerns the allocation alone
    is judged the first time a leaf is frozen on it (`allocation`) and can only be refused for drift afterwards; the
    plan's own share is judged at every freeze."""
    ref = (m.get('plan') or {}).get('dimension_analysis_ref')
    if not ref:
        return
    analysis = read_json(check_ref(ref))
    if allocation:
        allocation_gate(s, analysis)
    else:
        intact(lambda: allocation_gate(s, analysis))
    for row in analysis['dimensions']:
        if row.get('dimension') == 'Resource' and row.get('status') == 'applicable':
            for item in row.get('items', []):
                require_consumer_files(item, m.get('write_paths'))
    import ui_fidelity
    plan = m['plan']
    require_graphic_proof([item for row in analysis['dimensions'] if row.get('dimension') == 'Resource'
                           and row.get('status') == 'applicable' for item in row.get('items', [])],
                          plan, ui_fidelity.declared_image_checks(analysis),
                          {cid for path in plan.get('paths', []) if path.get('kind') == 'visual' for cid in path.get('image_check_ids', [])})


def allocation_gate(s, analysis):
    """The exact resources an allocation declares: where each lands, what it is made from and how variants are told apart."""
    import resource_copy
    variants, destinations = set(), {}
    resource_copy.freeze_check(s, analysis)
    for row in analysis['dimensions']:
        if row.get('dimension') == 'Resource' and row.get('status') == 'applicable':
            for item in row.get('items', []):
                if item.get('resource_strategy'):
                    if s.get('target_root'):
                        require_target_binding(item, s['target_root'])
                    facts = validate_facts(item, s.get('legacy_root'), check_configuration=True)
                    if facts.get('status') in ('source-unavailable', 'signal'):
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
