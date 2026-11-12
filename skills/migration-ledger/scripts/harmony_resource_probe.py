"""Qualified Harmony resources from the app's resolver and the HDC viewport that used it."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from xml.etree import ElementTree
import zipfile

from contracts import check_ref, read_json, require
import device_configuration
from lean_tools.mobile_snapshot import harmony_node

KINDS = ('image', 'bounds', 'color', 'text')
SYSTEM_FIELDS = ('density_dpi', 'night', 'locale')
MODEL = ('shell', 'param', 'get', 'const.product.model')
OS_BUILD = ('shell', 'param', 'get', 'const.product.software.version')
MAIN_DISPLAY = ('-d', '0')
WINDOWS = ('shell', "hidumper -s WindowManagerService -a '-a'")


def focused_window(stdout):
    focused = re.findall(r'^\s*Focus window:\s*(\d+)\s*$', stdout, re.MULTILINE)
    require(len(focused) == 1, 'WindowManager did not identify one focused Harmony window')
    rows = []
    for line in stdout.splitlines():
        row = re.fullmatch(r'\s*.+?\s+(\d+)\s+\d+\s+(\d+)(?:\s+-?\d+){5}\s+'
                           r'\[\s*(-?\d+)[,\s]+(-?\d+)[,\s]+(\d+)[,\s]+(\d+)\s*\]'
                           r'(?:\s+\[([^\]]+)\]\s+\[([^\]]+)\])?\s*', line)
        if row and row[2] == focused[0]:
            display, win, left, top, width, height = map(int, row.groups()[:6])
            if row[7] is not None:
                require(re.fullmatch(r'\s*0\s+0\s*', row[7]) and re.match(r'\s*1(?:\.0+)?\s+1(?:\.0+)?\s+', row[8]),
                        'focused Harmony window has an unsupported display transform')
            rows.append({'display_id': display, 'window_id': win,
                         'window_bounds_px': [left, top, left + width, top + height]})
    require(len(rows) == 1 and rows[0]['display_id'] == 0, 'focused Harmony window is missing from main display')
    return rows[0]


def layout_command(window=None):
    return ['shell', 'uitest', 'dumpLayout', *MAIN_DISPLAY, '-w', str(window['window_id'])] if window else [
        'shell', 'uitest', 'dumpLayout']


def device_identity(rows, serial):
    def read(command):
        return next((row.get('stdout', '').strip() for row in reversed(rows)
                     if row.get('exit_code') == 0 and row['argv'][1:] == ['-t', serial, *command]
                     and Path(row['argv'][0]).name == 'hdc'), '')
    model, os_build = read(MODEL), read(OS_BUILD)
    require(model and os_build and '\n' not in model and '\n' not in os_build
            and all(not value.lower().startswith(('fail', 'error', 'unknown')) for value in (model, os_build)),
            'physical Harmony capture lacks HDC model/OS readback')
    require(all(not value.lower().startswith('emulator') for value in (model, os_build)),
            'HDC reports an emulator for the physical Harmony profile')
    return {'model': model, 'os_build': os_build}


def physical_viewport(observed, xml, screenshot, build_id, native_window):
    from PIL import Image
    from lean_tools.mobile_snapshot import bounds_box
    viewport = observed.get('viewport') or {}
    require(observed.get('build_id') == build_id and build_id, 'running app build marker differs from accepted HAP')
    require(type(viewport.get('display_id')) is int and viewport['display_id'] == 0
            and type(viewport.get('window_id')) is int and viewport['window_id'] > 0
            and viewport.get('orientation') in ('portrait', 'landscape'),
            'physical Harmony capture needs main display, app window and orientation readback')
    require(all(viewport.get(key) == value for key, value in native_window.items()),
            'Harmony app viewport differs from the focused WindowManager window')
    require(observed['configuration'].get('harmony_api_level', 0) >= 20,
            'physical Harmony capture needs API 20+ display selection')
    app = ElementTree.fromstring(xml)
    bounds = bounds_box(app.get('bounds', ''))
    require(bounds, 'physical Harmony capture needs a bounded app content tree')
    left, top, right, bottom = native_window['window_bounds_px']
    x1, y1, x2, y2 = bounds
    require(left <= x1 < x2 <= right and top <= y1 < y2 <= bottom,
            'physical Harmony app content lies outside the WindowManager window')
    with Image.open(screenshot) as image:
        width, height = image.size
        require(image.format == 'PNG' and 0 <= left < right <= width and 0 <= top < bottom <= height
                and viewport['orientation'] == ('landscape' if width > height else 'portrait'),
                'physical Harmony window coordinates do not match the main display PNG')
    return {**viewport, 'content_bounds_px': list(bounds)}



def contract(path, checks=None):
    probe = path.get('harmony_resource_probe')
    require(path.get('platform') == 'harmony' and path.get('kind') == 'visual' and path.get('device_configuration')
            and isinstance(probe, dict) and {'node_id', 'selections'} <= set(probe)
            <= {'node_id', 'selections', 'configuration_scope', 'system_configuration'},
            'Harmony qualified visual PATH requires harmony_resource_probe and device_configuration')
    require(isinstance(probe['node_id'], str) and probe['node_id']
            and isinstance(probe['selections'], dict) and probe['selections'],
            'Harmony resource probe needs a stable accessibility node and resource selections')
    require(set(probe['selections']) <= set(path.get('image_check_ids', [])),
            'Harmony resource selections must belong to this visual PATH')
    scope = probe.get('configuration_scope')
    require(scope in (None, 'system', 'window'), 'invalid Harmony configuration scope')
    if 'system_configuration' in probe:
        expected = device_configuration.validate(probe['system_configuration'])
        require(scope and set(expected) <= set(SYSTEM_FIELDS), 'freeze an explicit scope and system resource configuration fields')
    if scope == 'system':
        require(any(key in path['device_configuration'] for key in SYSTEM_FIELDS),
                'system scope needs at least one frozen density, night or locale value')
    for mapping in probe['selections'].values():
        require(isinstance(mapping, dict) and {'resource_id', 'target_qualifier'} <= set(mapping) <= {'resource_id', 'target_qualifier', 'target_sha256', 'target_entry', 'target_branch'}
                and all(isinstance(value, str) and value for value in mapping.values()),
                'Harmony resource selection needs the runtime resource_id and mapped target_qualifier')
        if 'target_sha256' in mapping:
            require(re.fullmatch(r'[0-9a-f]{64}', mapping['target_sha256']),
                    'Harmony converted image needs its reviewed packaged SHA-256')
        if entry := mapping.get('target_entry'):
            require(entry.startswith('resources/') and PurePosixPath(entry).as_posix() == entry
                    and '..' not in PurePosixPath(entry).parts and '\\' not in entry and not entry.endswith('/'),
                    'Harmony image target_entry must be a safe HAP resource member')
        require(not (mapping.get('target_entry') and mapping.get('target_branch')),
                'freeze either a HAP image entry or an XML resource branch')
    if checks is not None:
        expected = {check['id'] for check in checks if check.get('kind', 'image') in KINDS}
        require(expected == set(probe['selections']), 'Harmony resource probe must bind every resource measurement')
        for check in checks:
            mapping = probe['selections'].get(check['id'], {})
            image = check.get('kind', 'image') == 'image'
            require((image or not {'target_entry', 'target_sha256'}.intersection(mapping))
                    and (not image or 'target_branch' not in mapping), 'Harmony resource proof must match its check type')
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


def normalized_config(config):
    require(isinstance(config, dict), 'Harmony resource probe needs observed configuration')
    locale = config.get('locale')
    if isinstance(locale, str) and not re.fullmatch(device_configuration.LOCALE, locale):
        parts = re.split('[-_]', locale)
        locale = '-r'.join(parts) if len(parts) == 2 and re.fullmatch('[A-Z]{2}', parts[1]) else 'b+' + '+'.join(parts)
        config = {**config, 'locale': locale}
    return device_configuration.validate(config)


def matches_configuration(observed, expected, probe):
    if not device_configuration.matches(observed['configuration'], expected):
        return False
    scope = probe.get('configuration_scope')
    if not scope:
        return True  # Legacy probes describe the app's effective configuration.
    system = observed.get('system_configuration')
    if not system or not device_configuration.matches(system, probe.get('system_configuration', {})):
        return False
    selected = {key: expected[key] for key in SYSTEM_FIELDS if key in expected}
    return scope != 'system' or device_configuration.matches(system, selected)


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
    require(isinstance(value, dict) and value.get('schema_version') in (1, 2, 3)
            and isinstance(value.get('resources'), dict), 'invalid Harmony resource probe payload')
    config = normalized_config(value.get('configuration'))
    require(config.get('vp_scale') and config.get('window_width_vp'),
            'Harmony resource probe needs actual window width and logical pixel scale')
    extra = {}
    if value['schema_version'] >= 2:
        require(isinstance(value.get('build_id'), str) and isinstance(value.get('viewport'), dict),
                'invalid Harmony build or viewport readback')
        extra = {'build_id': value['build_id'], 'viewport': value['viewport']}
        v3 = value['schema_version'] == 3
        if v3:
            system = normalized_config(value.get('system_configuration'))
            require(set(system) <= set(SYSTEM_FIELDS), 'invalid Harmony system resource configuration')
            extra['system_configuration'] = system
        for entry in value['resources'].values():
            require(isinstance(entry, dict) and {'value', 'resolved_qualifier'} <= set(entry)
                    <= ({'value', 'resolved_qualifier', 'identity'} if v3 else {'value', 'resolved_qualifier'}),
                    'invalid Harmony resource selection')
            qualifier = entry['resolved_qualifier']
            require((isinstance(qualifier, str) and qualifier) or (v3 and qualifier is None),
                    'invalid Harmony resolved resource qualifier')
            require(entry.get('identity') is None or isinstance(entry['identity'], str) and entry['identity'],
                    'invalid Harmony resolved resource identity')
    return {'configuration': config, 'resources': value['resources'], **extra}


def expected_value(check):
    kind = check.get('kind', 'image')
    if kind == 'image':
        reference = read_json(check_ref(check['reference']['render_ref']))
        return reference['source_ref']['sha256']
    expect = check['expect']
    if kind == 'bounds':
        return {'unit': expect['unit'], 'value': expect['value']}
    return expect['color' if kind == 'color' else 'text']


def packaged_sha256(artifact, entry):
    if artifact is None:
        return None
    try:
        with zipfile.ZipFile(artifact) as archive:
            if archive.namelist().count(entry) != 1:
                return None
            with archive.open(entry) as member:
                return hashlib.file_digest(member, 'sha256').hexdigest()
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile):
        return None


def selection(check, mapping, resources, artifact=None):
    if mapping is None:
        return None
    value = resources.get(mapping['resource_id'])
    identity = qualifier = None
    if isinstance(value, dict) and 'resolved_qualifier' in value:
        qualifier, identity, value = value['resolved_qualifier'], value.get('identity'), value['value']
    require('target_sha256' not in mapping or check.get('kind', 'image') == 'image',
            'only a reviewed image conversion may use target_sha256')
    expected = mapping.get('target_sha256') or expected_value(check)
    target = mapping.get('target_entry') or mapping.get('target_branch')
    packaged = packaged_sha256(artifact, target) if mapping.get('target_entry') else None
    matches = (value == expected and (qualifier is None or qualifier == mapping['target_qualifier'])
               and (not target or identity is None or identity == target)
               and (packaged is None or packaged == value))
    missing = value is None or (target and (identity is None or mapping.get('target_entry') and packaged is None))
    status = 'missing' if missing else 'match' if matches else 'mismatch'
    return {**mapping, 'observed': value, 'status': status,
            **({'resolved_qualifier': qualifier} if qualifier is not None else {}),
            **({'observed_identity': identity} if identity is not None else {}),
            **({'packaged_sha256': packaged} if packaged else {})}


def with_selection(row, check, probe, resources, *, require_qualifier=False, artifact=None):
    mapping = probe['selections'].get(check['id'])
    evidence = selection(check, mapping, resources, artifact)
    if evidence is None:
        return row
    row['resource_selection'] = evidence
    if evidence['status'] == 'mismatch':
        row.update(status='MISMATCH', reason='the app resolved a different resource value or qualifier')
    elif evidence['status'] == 'missing' or require_qualifier and not evidence.get('resolved_qualifier'):
        row.update(status='INCOMPARABLE', reason='the app did not expose this resource selection or its resolved qualifier')
    return row


def capture_proof(raw_refs, observation_refs, rows, device_id, app_id, node_id, run_root, *, physical_build=None):
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
            dumps = [(i, args) for i, args, stdout in commands if i < index
                     and args[:3] == ['shell', 'uitest', 'dumpLayout']
                     and re.search(r'saved to:\s*' + re.escape(remote) + r'(?:\s|$)', stdout)]
            require(dumps, 'Harmony probe layout is not a recorded device dump')
            produced, argv = dumps[-1]
            native = None
            start = produced
            if physical_build:
                prior = next(((i, args, stdout) for i, args, stdout in reversed(commands) if i < produced), None)
                require(prior and prior[1] == list(WINDOWS), 'physical Harmony layout lacks its WindowManager readback')
                start, _, stdout = prior
                native = focused_window(stdout)
            require(argv == layout_command(native), 'Harmony layout command differs from the verified window')
            return start, index, native
        screenshot_argv = (['shell', 'uitest', 'screenCap', '-p', remote, *MAIN_DISPLAY] if physical_build
                           else ['shell', 'snapshot_display', '-f', remote, '-t', 'png'])
        captured = [i for i, args, _ in commands if i < index and args == screenshot_argv]
        require(len(captured) == 1, 'Harmony qualified capture requires one native lossless PNG command')
        return captured[0], index, None

    observations = {}
    for pair, captured in zip(raw_refs, observation_refs):
        require(pair['index'] == captured['index'], 'Harmony resource probe viewport differs from screenshot')
        before, after = pair['before_ref'], pair['after_ref']
        _, before_recv, before_window = transfer(before, 'layout')
        screen_capture, screen_recv, _ = transfer(captured['screenshot_ref'], 'screenshot')
        after_query, _, after_window = transfer(after, 'layout')
        require(before_recv < screen_capture < screen_recv < after_query and before_window == after_window,
                'Harmony layout commands and downloads must bracket the screenshot on the same window')
        for ref in (before, after):
            tree = harmony_node(read_json(managed_ref(ref, run_root)))
            require(tree is not None and app_tree(ElementTree.tostring(tree, encoding='unicode'), app_id)
                    == check_ref(captured['view_ref']).read_text(),
                    'Harmony resource probe layout differs from the accepted app view tree')
        xml = check_ref(captured['view_ref']).read_text()
        observed = observation(xml, node_id, app_id)
        if physical_build:
            observed['viewport'] = physical_viewport(observed, xml, check_ref(captured['screenshot_ref']),
                                                      physical_build, before_window)
        observations[str(captured['index'])] = observed
    first = next(iter(observations.values()), None)
    require(first and all(all(value.get(key) == first.get(key) for key in ('configuration', 'system_configuration', 'viewport'))
                          for value in observations.values()), 'Harmony resource configuration changed during capture')
    return observations
