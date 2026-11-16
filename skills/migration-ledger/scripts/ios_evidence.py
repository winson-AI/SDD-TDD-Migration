"""The device and deployment an iOS execution receipt is allowed to attest."""
from pathlib import Path
import math
import re

from contracts import check_ref, read_json, require


def deployment(binding, code_baseline):
    ref = binding.get('deployment_ref')
    require(ref, 'iOS physical device requires a host deployment receipt')
    value = read_json(check_ref(ref))
    from project_context import wda_endpoint
    require(isinstance(value, dict) and value.get('schema_version') == 1
            and all(isinstance(value.get(k), str) and value[k].strip()
                    for k in ('udid', 'wda_uuid', 'bundle_id', 'build_version', 'wda_url')),
            'invalid iOS deployment receipt')
    require(re.fullmatch(r'[A-Za-z0-9-]+', value['udid']) and re.fullmatch(r'[A-Za-z0-9.-]+', value['bundle_id'])
            and value['udid'].lower() == (binding.get('udid') or '').lower()
            and value['bundle_id'] == binding.get('app_id')
            and wda_endpoint(value['wda_url']) == wda_endpoint(binding.get('wda_url'))
            and value.get('code_baseline') == code_baseline, 'iOS deployment does not match this device, App and code baseline')
    check_ref(value.get('artifact_ref'))
    return value


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
                and observed['wda_uuid'] == receipt['wda_uuid']
                and (installed.get('udid') or '').lower() == receipt['udid'].lower()
                and (observed['is_simulator'] or installed.get('core_device_id'))
                and installed.get('bundle_id') == receipt['bundle_id']
                and installed.get('build_version') == receipt['build_version'],
                'iOS observed device or installed App differs from deployment')


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
