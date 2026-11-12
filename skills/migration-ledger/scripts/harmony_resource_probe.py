"""Qualified Harmony resources from the app's resolver and the HDC viewport that used it."""
import json
from pathlib import Path
import re
from xml.etree import ElementTree

from contracts import check_ref, read_json, require
import device_configuration
from lean_tools.mobile_snapshot import harmony_node

KINDS = ('image', 'bounds', 'color', 'text')


def contract(path, checks=None):
    probe = path.get('harmony_resource_probe')
    require(path.get('platform') == 'harmony' and path.get('kind') == 'visual' and path.get('device_configuration')
            and isinstance(probe, dict) and set(probe) == {'node_id', 'selections'},
            'Harmony qualified visual PATH requires harmony_resource_probe and device_configuration')
    require(isinstance(probe['node_id'], str) and probe['node_id']
            and isinstance(probe['selections'], dict) and probe['selections'],
            'Harmony resource probe needs a stable accessibility node and resource selections')
    require(set(probe['selections']) <= set(path.get('image_check_ids', [])),
            'Harmony resource selections must belong to this visual PATH')
    for mapping in probe['selections'].values():
        require(isinstance(mapping, dict) and set(mapping) == {'resource_id', 'target_qualifier'}
                and all(isinstance(value, str) and value for value in mapping.values()),
                'Harmony resource selection needs the runtime resource_id and mapped target_qualifier')
    if checks is not None:
        expected = {check['id'] for check in checks if check.get('kind', 'image') in KINDS}
        require(expected == set(probe['selections']), 'Harmony resource probe must bind every resource measurement')
    return probe


def app_tree(view_xml, app_id):
    """Select the foreground app's window before comparing a qualified viewport."""
    def windows(node):
        if node.get('package') == app_id:
            yield node
        else:
            for child in node:
                yield from windows(child)

    owned = list(windows(ElementTree.fromstring(view_xml)))
    require(len(owned) == 1, 'Harmony resource probe needs one foreground application window')
    return ElementTree.tostring(owned[0], encoding='unicode')


def observation(view_xml, node_id, app_id):
    def matching(node, owner):
        owner = node.get('package') or owner
        if node.get('resource-id') == node_id and owner == app_id:
            yield node
        for child in node:
            yield from matching(child, owner)

    nodes = list(matching(ElementTree.fromstring(view_xml), None))
    require(len(nodes) == 1, 'Harmony resource probe needs one node of the foreground app')
    raw = nodes[0].get('text') or nodes[0].get('content-desc') or ''
    require(len(raw) <= 16384, 'Harmony resource probe exceeds the capture payload limit')
    value = json.loads(raw)
    require(isinstance(value, dict) and value.get('schema_version') == 1
            and isinstance(value.get('resources'), dict), 'invalid Harmony resource probe payload')
    config = value.get('configuration')
    require(isinstance(config, dict), 'Harmony resource probe needs observed configuration')
    locale = config.get('locale')
    if isinstance(locale, str) and not re.fullmatch(device_configuration.LOCALE, locale):
        parts = re.split('[-_]', locale)
        if len(parts) == 2 and re.fullmatch('[A-Z]{2}', parts[1]):
            locale = '-r'.join(parts)
        else:
            locale = 'b+' + '+'.join(parts)
        config = {**config, 'locale': locale}
    device_configuration.validate(config)
    require(config.get('vp_scale') and config.get('window_width_vp'),
            'Harmony resource probe needs actual window width and logical pixel scale')
    return {'configuration': config, 'resources': value['resources']}


def expected_value(check):
    kind = check.get('kind', 'image')
    if kind == 'image':
        reference = read_json(check_ref(check['reference']['render_ref']))
        return reference['source_ref']['sha256']
    expect = check['expect']
    if kind == 'bounds':
        return {'unit': expect['unit'], 'value': expect['value']}
    return expect['color' if kind == 'color' else 'text']


def selection(check, mapping, resources):
    if mapping is None:
        return None
    value = resources.get(mapping['resource_id'])
    expected = expected_value(check)
    status = 'missing' if value is None else 'match' if value == expected else 'mismatch'
    return {**mapping, 'observed': value, 'status': status}


def with_selection(row, check, probe, resources):
    mapping = probe['selections'].get(check['id'])
    evidence = selection(check, mapping, resources)
    if evidence is None:
        return row
    row['resource_selection'] = evidence
    if evidence['status'] == 'mismatch':
        row.update(status='MISMATCH', reason='the app resolved a different resource value')
    elif evidence['status'] == 'missing':
        row.update(status='INCOMPARABLE', reason='the app did not expose this resource selection')
    return row


def capture_proof(raw_refs, observation_refs, rows, device_id, app_id, node_id, run_root):
    """Re-read HDC's layout downloads bracketing each PNG, including every viewport of a scroll."""
    from visual_evidence import managed_ref
    require(len(raw_refs) == len(observation_refs), 'Harmony probe must cover every captured viewport')
    commands = [(i, argv[3:], row.get('stdout') or '') for i, row in enumerate(rows) if row.get('exit_code') == 0
                and (argv := row['argv']) and Path(argv[0]).name == 'hdc' and argv[1:3] == ['-t', device_id]]
    def transfer(ref, kind):
        path = str(managed_ref(ref, run_root))
        matches = [(i, args[2]) for i, args, _ in commands if args[:2] == ['file', 'recv']
                   and len(args) == 4 and args[3] == path]
        require(len(matches) == 1, 'Harmony probe file lacks one HDC download on the captured device')
        index, remote = matches[0]
        if kind == 'layout':
            require(any(i < index and args == ['shell', 'uitest', 'dumpLayout']
                        and re.search(r'saved to:\s*' + re.escape(remote) + r'(?:\s|$)', stdout)
                        for i, args, stdout in commands), 'Harmony probe layout is not a recorded device dump')
        else:
            require(any(i < index and args == ['shell', 'snapshot_display', '-f', remote, '-t', 'png']
                        for i, args, _ in commands), 'Harmony qualified capture requires native lossless PNG')
        return index

    observations = {}
    for pair, captured in zip(raw_refs, observation_refs):
        require(pair['index'] == captured['index'], 'Harmony resource probe viewport differs from screenshot')
        before, after = pair['before_ref'], pair['after_ref']
        require(transfer(before, 'layout') < transfer(captured['screenshot_ref'], 'screenshot') < transfer(after, 'layout'),
                'Harmony resource probe must bracket the screenshot')
        for ref in (before, after):
            tree = harmony_node(read_json(managed_ref(ref, run_root)))
            require(tree is not None and app_tree(ElementTree.tostring(tree, encoding='unicode'), app_id)
                    == check_ref(captured['view_ref']).read_text(),
                    'Harmony resource probe layout differs from the accepted app view tree')
        observations[str(captured['index'])] = observation(check_ref(captured['view_ref']).read_text(), node_id, app_id)
    require(observations and all(value['configuration'] == next(iter(observations.values()))['configuration']
                                 for value in observations.values()), 'Harmony resource configuration changed during capture')
    return observations
