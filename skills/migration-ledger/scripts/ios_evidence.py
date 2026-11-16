"""The device and deployment an iOS execution receipt is allowed to attest."""
from pathlib import Path
from bisect import bisect_right
import math
import plistlib
import re
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile, BadZipFile

from contracts import Rejected, check_ref, read_json, require

RECORDING_CONTRACT = 4


def document(ref):
    value = read_json(check_ref(ref))
    require(isinstance(value, dict), 'invalid iOS evidence document')
    return value


def deployment(binding, code_baseline):
    ref = binding.get('deployment_ref')
    require(ref, 'iOS physical device requires a host deployment receipt')
    value = document(ref)
    from project_context import wda_endpoint
    require(isinstance(value, dict) and value.get('schema_version') in (1, 2)
            and all(isinstance(value.get(k), str) and value[k].strip()
                    for k in ('udid', 'wda_uuid', 'bundle_id', 'build_version', 'wda_url')),
            'invalid iOS deployment receipt')
    require(re.fullmatch(r'[A-Za-z0-9-]+', value['udid']) and re.fullmatch(r'[A-Za-z0-9.-]+', value['bundle_id'])
            and value['udid'].lower() == (binding.get('udid') or '').lower()
            and value['bundle_id'] == binding.get('app_id')
            and wda_endpoint(value['wda_url']) == wda_endpoint(binding.get('wda_url')),
            'iOS deployment does not match this device and App')
    require('avfoundation_uid' not in value or (isinstance(value['avfoundation_uid'], str)
            and value['avfoundation_uid'].strip()), 'iOS deployment AVFoundation UID is invalid')
    if value['schema_version'] == 1:
        require(value.get('code_baseline') == code_baseline, 'iOS deployment code baseline mismatch')
        check_ref(value.get('artifact_ref'))
    else:
        covered = document(value.get('build_coverage_ref'))
        expected = binding.get('module_baselines') or {}
        require(covered.get('artifact_ref') == value.get('artifact_ref') and covers(covered.get('module_baselines'), expected),
                'iOS signed artifact does not cover the frozen PATH code and providers')
        install = document(value.get('installation_ref'))
        require(install.get('artifact_ref') == value.get('artifact_ref')
                and str(install.get('udid', '')).lower() == value['udid'].lower() and install.get('core_device_id'),
                'iOS installation evidence does not bind the deployed artifact and device')
        raw = document(install.get('devicectl_ref'))
        info = raw.get('info') or {}
        args = info.get('arguments') or []
        require(isinstance(args, list) and all(isinstance(a, str) for a in args), 'invalid CoreDevice install arguments')
        if args and Path(args[0]).name == 'devicectl':
            args = args[1:]
        apps = [a for a in (raw.get('result') or {}).get('installedApplications', []) if a.get('bundleID') == value['bundle_id']]
        targets = [right for left, right in zip(args, args[1:]) if left == '--device']
        require(info.get('outcome') == 'success' and args[:3] == ['device', 'install', 'app']
                and install.get('extracted_app') == args[-1] and args[-1].endswith('.app')
                and len(targets) == 1 and targets[0] in (value['udid'], install['core_device_id'])
                and len(apps) == 1 and bundle_path(apps[0].get('installationURL')),
                'iOS deployment needs a successful CoreDevice installation on the bound device')
        value.update(core_device_id=install['core_device_id'], installed_bundle_path=bundle_path(apps[0]['installationURL']))
        info = package_info(value['artifact_ref'])
        require(info.get('CFBundleIdentifier') == value['bundle_id']
                and str(info.get('CFBundleVersion')) == value['build_version'], 'IPA bundle identity differs from deployment')
    return value


def bundle_path(url):
    if not isinstance(url, str):
        return None
    path = urlsplit(url)
    return '/' + unquote(path.path).strip('/') if path.scheme == 'file' and path.path else None


def package_info(ref):
    artifact = check_ref(ref)
    try:
        with ZipFile(artifact) as archive:
            plists = [name for name in archive.namelist() if re.fullmatch(r'Payload/[^/]+\.app/Info\.plist', name)]
            require(len(plists) == 1, 'IPA must contain one main App bundle')
            info = plistlib.loads(archive.read(plists[0]))
    except (BadZipFile, plistlib.InvalidFileException) as exc:
        raise ValueError('invalid iOS package or Info.plist') from exc
    require(isinstance(info, dict), 'iOS package Info.plist is invalid')
    return info


def covers(baselines, expected):
    return isinstance(baselines, dict) and bool(expected) and all(value and baselines.get(mid) == value for mid, value in expected.items())


def accepted_build(state, receipt, expected):
    coverage = receipt.get('build_coverage_ref')
    installed = receipt.get('artifact_ref')
    if not isinstance(installed, dict) or not installed.get('sha256'):
        return False
    for mod in state['modules'].values():
        current = [ref for ref in mod.get('build_artifacts', []) if ref['sha256'] == installed['sha256']]
        if not current:
            continue
        for row in mod['results'].values():
            if row['quality'] != 'green-passed' or row.get('stale') or row.get('code_baseline') != mod.get('code_baseline'):
                continue
            proofs = row.get('ios_build_coverage_refs', [])
            for artifact in current:
                if artifact not in row.get('build_artifacts', []):
                    continue
                if artifact == installed and coverage in proofs:
                    return True  # The runtime verifies this exact, accepted manifest.
                for proof in proofs:
                    try:
                        candidate = document(proof)
                        if candidate.get('artifact_ref') == artifact and covers(candidate.get('module_baselines'), expected):
                            check_ref(artifact)
                            return True  # A subsequent Build accepted the same bytes and slice coverage.
                    except (ValueError, OSError):
                        continue
    return False


def execution_binding(state, module_id, path):
    from ledger import dependency_closure
    from project_context import device_inputs, path_device

    devices = (state.get('test_adapter') or {}).get('device') or {}
    binding = dict(device_inputs(devices).get(path_device(path)) or {})
    if path.get('ios_device_profile'):
        binding['profile'] = path['ios_device_profile']
    if binding.get('deployment_ref'):
        try:
            receipt = document(binding['deployment_ref'])
        except (ValueError, OSError):
            return binding  # The runner reports the unavailable binding on this PATH.
        if receipt.get('schema_version') == 2:
            if module_id == 'GLOBAL':
                from integration import owners
                roots = (owners(state, path) if path in state.get('global_paths', []) else
                         [mid for mid, mod in state['modules'].items() if path in (mod.get('plan') or {}).get('paths', [])])
            else:
                roots = [module_id]
            expected = {mid: state['modules'][mid].get('code_baseline') for mid in dependency_closure(state, roots)}
            if accepted_build(state, receipt, expected):
                binding['module_baselines'] = expected
    return binding


def artifact_inputs(state, module_id, path):
    """Return the narrower inputs only for the built-in runner on an accepted signed IPA."""
    from execute_test import builtin_platform

    if builtin_platform(state, path) != 'ios':
        return None
    try:
        binding = execution_binding(state, module_id, path)
        if not binding.get('module_baselines'):
            return None
        artifact = deployment(binding, None)['artifact_ref']
        return {'path': path, 'binding': binding, 'artifact_ref': artifact,
                'environment_revision': state.get('harmony_environment_revision'), 'package': state.get('package_sha')}
    except (Rejected, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return None


def assignment_inputs(state, module, path_ids):
    paths = {p['path_id']: p for p in module['plan']['paths']}
    selected = {pid: artifact_inputs(state, module['module_id'], paths[pid]) if pid in paths else None for pid in path_ids}
    return selected if selected and all(selected.values()) else {}


def check_device(binding, code_baseline, observed):
    """Check host-provisioned identity against what WDA and the installation probe returned."""
    from project_context import wda_endpoint
    require(isinstance(observed, dict) and type(observed.get('is_simulator')) is bool
            and isinstance(observed.get('wda_uuid'), str) and observed['wda_uuid'] not in ('', 'unknown'),
            'iOS device identity unavailable')
    if binding.get('wda_url'):
        require(wda_endpoint(binding['wda_url']) == observed.get('endpoint'), 'iOS WDA endpoint mismatch')
    if binding.get('udid'):
        require(binding['udid'].lower() == (observed.get('configured_udid') or '').lower(), 'iOS provisioned UDID mismatch')
    if profile := binding.get('profile'):
        require(observed['is_simulator'] == (profile == 'simulator'), 'iOS device does not match the frozen profile')
    if not observed['is_simulator'] or binding.get('deployment_ref'):
        receipt = deployment(binding, code_baseline)
        installed = observed.get('installed') or {}
        require(observed.get('deployment_ref') == binding['deployment_ref']
                and observed.get('avfoundation_uid') == receipt.get('avfoundation_uid')
                and observed['wda_uuid'] == receipt['wda_uuid']
                and (installed.get('udid') or '').lower() == receipt['udid'].lower()
                and (observed['is_simulator'] or installed.get('core_device_id'))
                and installed.get('bundle_id') == receipt['bundle_id']
                and installed.get('build_version') == receipt['build_version'],
                'iOS observed device or installed App differs from deployment')
        if receipt['schema_version'] == 2:
            require(not observed['is_simulator'] and installed.get('core_device_id') == receipt['core_device_id']
                    and bundle_path(installed.get('bundle_url')) == receipt['installed_bundle_path'],
                    'iOS installed App instance differs from the signed artifact installation')
            return receipt['artifact_ref']


def check_checkpoints(binding, query, trace, output):
    if not query.get('expected_assertions'):
        return
    steps = trace.get('steps', [])
    for assertion in query['expected_assertions']:
        number = assertion.get('after_step')
        require(type(number) is int and 1 <= number <= len(steps), 'iOS assertion checkpoint unavailable')
        checkpoint = steps[number - 1].get('after_device') or {}
        require(isinstance(checkpoint.get('foreground_bundle_id'), str) and checkpoint['foreground_bundle_id'],
                'iOS checkpoint requires an observed foreground bundle ID')
        expected = assertion.get('foreground_bundle_id') or binding.get('app_id')
        require(not expected or checkpoint['foreground_bundle_id'] == expected, 'iOS checkpoint App mismatch')
        layout = check_ref(checkpoint.get('layout_ref'))
        require(layout.resolve().is_relative_to(Path(output).resolve()), 'iOS UI tree is outside this execution')


def check_video(refs, trace, assertion, device, output):
    """The recordings offered for this assertion cover its frozen before/after checkpoints."""
    steps = trace['steps']
    begin = steps[assertion.get('reference_step', assertion['after_step']) - 1]['before_device']['captured_at']
    end = steps[assertion['after_step'] - 1]['after_device']['captured_at']
    intervals = []
    boundary = Path(output).resolve()
    for ref in refs:
        if not ref['path'].endswith('.ios-capture.json'):
            continue
        path = check_ref(ref)
        facts = read_json(path)
        movie = check_ref(facts['video_ref'])
        require(path.resolve().is_relative_to(boundary) and movie.resolve().is_relative_to(boundary),
                'iOS recording evidence is outside this execution')
        require(facts['wda_uuid'] == device['wda_uuid'] and facts['udid'] == device['configured_udid']
                and facts['backend'] == ('simctl' if device['is_simulator'] else 'avfoundation')
                and (device['is_simulator'] or facts.get('core_device_id') == device['installed'].get('core_device_id')),
                'iOS recording source differs from the observed device')
        start, stop, duration = (facts[k] for k in ('started_at', 'ended_at', 'decoded_duration'))
        require(all(isinstance(value, (int, float)) and math.isfinite(value) for value in (start, stop, duration))
                and 0 < stop - start <= duration + 0.001, 'iOS recording interval is invalid')
        intervals.append((start, stop))
    require(isinstance(begin, (int, float)) and isinstance(end, (int, float)) and 0 < begin < end,
            'iOS video checkpoint timestamps are invalid')
    covered = begin
    for start, stop in sorted(intervals):
        if start > covered:
            break
        covered = max(covered, stop)
    require(covered >= end, 'iOS recording does not cover the frozen assertion interval')


def interval(trace, assertion=None):
    steps = trace['steps']
    first = assertion.get('reference_step', assertion['after_step']) - 1 if assertion else 0
    last = assertion['after_step'] - 1 if assertion else -1
    begin = steps[first]['before_device']['captured_at']
    end = steps[last]['after_device']['captured_at']
    require(all(type(t) in (int, float) and math.isfinite(t) for t in (begin, end)) and 0 < begin < end,
            'iOS recording checkpoint times are invalid')
    return begin, end


def local_ref(ref, output):
    path = check_ref(ref).resolve()
    require(path.is_relative_to(Path(output).resolve()), 'iOS recording evidence is outside this attempt')
    return path


def frame_range(capture, begin, end):
    start = capture['started_at']
    require(start <= begin < end <= capture['ended_at'], 'iOS recording does not cover the frozen interval')
    require(all(end <= left or begin >= right for left, right in capture['gaps']),
            'iOS recording has a gap within the frozen interval')
    pts = capture['frame_pts']
    first, last = [bisect_right(pts, t - start) - 1 for t in (begin, end)]
    require(0 <= first <= last < len(pts), 'iOS recording does not have the requested frames')
    return first, last


def check_recording(ref, trace, device, output):
    path = local_ref(ref, output)
    data = read_json(path)
    local_ref(data.get('video_ref'), output)
    require(path.name.endswith('.ios-capture.json') and data.get('timeline_version') == 1
            and data['wda_uuid'] == device['wda_uuid'] and data['udid'] == device['configured_udid'],
            'iOS recording identity or decoded timeline is missing')
    if device['is_simulator']:
        require(data['backend'] == 'simctl', 'iOS simulator recording source mismatch')
        return data
    require(data['backend'] == 'avfoundation' and data['core_device_id'] == device['installed']['core_device_id'],
            'iOS AVFoundation device differs from the installation')
    if data.get('capture_uid'):
        require(data['capture_uid'] == device.get('avfoundation_uid'), 'iOS AVFoundation selected UID differs from deployment')
        return data
    images = [(r[f'{phase}_ref'], r[f'{phase}_device']['captured_at'])
              for r in trace['steps'] for phase in ('before', 'after') if f'{phase}_device' in r]
    anchors = data.get('wda_matches') or []
    require(len(anchors) == 2, 'iOS AVFoundation screen source was not corroborated by WDA')
    before, after = anchors
    for anchor in anchors:
        image = anchor['screenshot_ref']
        local_ref(image, output)
        require((image, anchor['captured_at']) in images
                and 0 <= anchor['frame_index'] < len(data['frame_pts'])
                and abs(data['started_at'] + data['frame_pts'][anchor['frame_index']] - anchor['captured_at']) <= .35,
                'iOS AVFoundation frame is not from a timed WDA checkpoint')
    require(before['frame_index'] < after['frame_index'] and before['captured_at'] < after['captured_at']
            and before['screenshot_ref']['sha256'] != after['screenshot_ref']['sha256'],
            'iOS AVFoundation requires two distinct ordered screen states')
    return data


def check_clip(refs, trace, assertion, device, output):
    proofs = [ref for ref in refs if ref['path'].endswith('.ios-assert-clip.json')]
    require(len(proofs) == 1, 'iOS video assertion needs its exact model clip receipt')
    proof = read_json(local_ref(proofs[0], output))
    require(proof.get('assertion_id') == assertion['assertion_id']
            and proof.get('query_sha256') == trace['query_sha256']
            and proof.get('clip_ref') in refs and proof.get('capture_ref') in refs,
            'iOS model clip does not belong to this assertion and recording')
    local_ref(proof['clip_ref'], output)
    capture = check_recording(proof['capture_ref'], trace, device, output)
    begin, end = interval(trace, assertion)
    first, last = frame_range(capture, begin, end)
    require(proof.get('interval') == [begin, end] and proof.get('frame_range') == [first, last]
            and proof.get('frame_count') == last - first + 1,
            'iOS model clip does not match the frozen frame interval')


def check_path_recording(media, trace, device, output):
    captures = [m['ref'] for m in media if m['kind'] == 'recording-proof']
    recordings = [m['ref'] for m in media if m['kind'] == 'recording']
    require(len(captures) == 1, 'iOS PATH requires a continuous device-bound recording')
    facts = check_recording(captures[0], trace, device, output)
    require(recordings == [facts['video_ref']], 'iOS PATH recording differs from its source proof')
    frame_range(facts, *interval(trace))
