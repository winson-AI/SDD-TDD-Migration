"""Bounded device capture and semantic comparison for a current SDD test assignment.

Only lean_worker calls this module after authentication/phase/plan checks. Host supplies a
live device-lock attestation; this is not a device lock service or an OS sandbox. No Ledger
events, acceptance, repair loop, arbitrary shell, implicit configuration or output directory.
"""
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import zipfile

from contracts import check_ref, digest, file_ref, read_json, require
import run_storage
import runner_storage
import visual_evidence
from lean_tools import mobile_snapshot, semantic_visual_inspect, validate_manifest

OPERATIONS = {'visual-install', 'visual-capture', 'semantic-inspect'}


def save(path, value):
    run_storage.atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
    return file_ref(path)


def blocked(reason, kind='environment-unavailable', **extra):
    return {'status': 'BLOCKED', 'quality_candidate': 'yellow-blocked', 'executed': False,
            'root_cause': {'kind': kind, 'reason': reason}, 'acceptance': 'staged-evidence-only', **extra}


def token(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value),
            label + ' must be a safe nonempty identifier')
    return value


class DeviceFailure(RuntimeError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def image_valid(path, formats=('PNG', 'JPEG')):
    try:
        from PIL import Image
    except ImportError as exc:
        raise DeviceFailure('environment-unavailable', 'Pillow is required to decode screenshot evidence') from exc
    try:
        with Image.open(path) as image:
            if image.format not in formats:
                raise ValueError('unsupported screenshot format')
            image.verify()
        with Image.open(path) as image:
            image.load()
    except Exception as exc:
        raise DeviceFailure('capture-incomplete', 'screenshot could not be decoded and verified') from exc


def hap_identity(artifact):
    try:
        with zipfile.ZipFile(artifact) as archive:
            for name in ('module.json', 'pack.info'):
                if name not in archive.namelist():
                    continue
                if archive.getinfo(name).file_size > 1024 * 1024:
                    continue
                data = json.loads(archive.read(name))
                if not isinstance(data, dict):
                    continue
                summary = data.get('summary') if isinstance(data.get('summary'), dict) else {}
                app = data.get('app') if name == 'module.json' else summary.get('app')
                if not isinstance(app, dict):
                    continue
                version = app.get('version') if isinstance(app.get('version'), dict) else {}
                code = app.get('versionCode', version.get('code'))
                if app.get('bundleName') and isinstance(code, (str, int)) and not isinstance(code, bool):
                    return {'bundleName': app['bundleName'], 'versionCode': str(code),
                            'versionName': app.get('versionName', version.get('name')), 'metadata_member': name}
    except (OSError, ValueError, TypeError, zipfile.BadZipFile):
        pass
    raise DeviceFailure('artifact-identity-unverified', 'accepted HAP lacks readable app bundle/version metadata')


def installed_identity(output, expected):
    if not isinstance(expected, dict) or not expected.get('bundleName') or not expected.get('versionCode'):
        return False
    try:
        start, end = output.index('{'), output.rindex('}') + 1
        data = json.loads(output[start:end])
    except (ValueError, TypeError):
        return False
    def walk(value):
        if isinstance(value, dict):
            if value.get('bundleName') == expected['bundleName'] and \
                    str(value.get('versionCode')) == expected['versionCode'] and \
                    (expected.get('versionName') is None or value.get('versionName') == expected['versionName']):
                return True
            return any(walk(child) for child in value.values())
        return isinstance(value, list) and any(walk(child) for child in value)
    return walk(data)


class Device:
    """Fixed HDC argv; remote file deletion is limited to this attempt's generated files."""
    def __init__(self, settings, out):
        require(settings.get('backend') == 'hdc', 'visual capture requires explicitly configured hdc backend')
        self.tool = settings.get('tool', 'hdc')
        require(isinstance(self.tool, str) and Path(self.tool).name == 'hdc', 'configured executable must be hdc')
        self.device = token(settings.get('device_id'), 'device_id')
        self.out = out
        self.logs = []
        self.remote_files = []
        self.version = None

    def call(self, *args, timeout=30):
        argv = [self.tool, '-t', self.device, *map(str, args)]
        try:
            result = subprocess.run(argv, cwd=self.out, env=runner_storage.environment(self.out),
                                    capture_output=True, text=True, errors='replace', timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            self.logs.append({'argv': argv, 'error': type(exc).__name__})
            raise DeviceFailure('environment-unavailable', type(exc).__name__) from exc
        self.logs.append({'argv': argv, 'exit_code': result.returncode,
                          'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise DeviceFailure('device-execution-error', f'command {args[0]} exited {result.returncode}; see command log')
        return result.stdout

    def layout(self, index):
        output = self.call('shell', 'uitest', 'dumpLayout')
        match = re.search(r'saved to:\s*(/data/local/tmp/[A-Za-z0-9_.-]+\.json)', output)
        if not match:
            raise DeviceFailure('device-execution-error', 'cannot parse managed dumpLayout path')
        remote = match.group(1)
        self.remote_files.append(remote)
        local = run_storage.checked_path(self.out / 'temp' / f'layout-{index}.json', self.out)
        local.parent.mkdir(parents=True, exist_ok=True)
        self.call('file', 'recv', remote, local)
        raw = read_json(local)
        node = mobile_snapshot.harmony_node(raw)
        if node is None:
            raise DeviceFailure('target-precondition', 'layout contains no application nodes')
        return ET.tostring(node, encoding='unicode'), mobile_snapshot.harmony_page_name(raw)

    def screenshot(self, index):
        nonce = digest(str(self.out))[:20]
        remote = f'/data/local/tmp/sdd-{nonce}-{index}.jpeg'
        self.remote_files.append(remote)
        self.call('shell', 'snapshot_display', '-f', remote)
        local = run_storage.checked_path(self.out / f'screenshot-{index}.jpeg', self.out)
        self.call('file', 'recv', remote, local)
        if not local.is_file() or not local.stat().st_size:
            raise DeviceFailure('capture-incomplete', 'device screenshot is missing or empty')
        image_valid(local, ('JPEG',))
        return local

    def finish(self):
        cleanup = []
        for remote in dict.fromkeys(self.remote_files):
            try:
                self.call('shell', 'rm', remote)
                cleanup.append({'path': remote, 'status': 'removed'})
            except DeviceFailure as exc:
                cleanup.append({'path': remote, 'status': 'retained-on-device', 'reason': str(exc)})
        return {'command_log_ref': save(self.out / 'commands.json', self.logs),
                'remote_cleanup_ref': save(self.out / 'remote-cleanup.json', cleanup)}


def path_context(args, module, task):
    selected = [p for p in module['plan']['paths'] if p['path_id'] == args.get('path_id')]
    require(len(selected) == 1, 'frozen test path_id required')
    path = selected[0]
    require(path.get('kind') in ('automation', 'visual'), 'device tools require automation or visual PATH')
    require(task.get('role') == 'auditor' or task.get('test_scope') == path['kind'], 'PATH outside test assignment scope')
    if 'path_ids' in task:
        require(path['path_id'] in task['path_ids'], 'PATH outside audit assignment selection')
    return path


def accepted_artifact(args, module, path):
    ref = args.get('artifact_ref')
    artifact = check_ref(ref)
    require(artifact.suffix.lower() == '.hap', 'visual installation requires one accepted HAP artifact')
    artifacts = (module.get('path_build_artifacts', {}).get(path['path_id'], [])
                 if 'path_build_artifacts' in module else module.get('build_artifacts', []))
    require(ref in artifacts, 'artifact must belong to this PATH current accepted build')
    return artifact


def configuration(root, path):
    contract = path.get('visual_execution')
    if not isinstance(contract, dict) or not contract.get('environment_ref'):
        return None, None
    source = check_ref(contract['environment_ref'])
    run_storage.checked_path(source, root / 'runs/harmony/sandbox/environment')
    settings = read_json(source)
    require(isinstance(settings, dict), 'visual environment must be an object')
    return contract, settings


def frozen_visual_evidence(module, path):
    return visual_evidence.frozen_evidence(module, path)


def device_lock(actor, settings, task):
    lock = actor.get('device_lock')
    require(isinstance(lock, dict) and lock.get('held') is True
            and lock.get('device_id') == settings.get('device_id')
            and lock.get('assignment_id') == task['assignment_id']
            and lock.get('fencing_token') == task.get('fencing_token'),
            'Host must attest a current exclusive device lock for this assignment')
    return lock


def frozen_actions(device, actions):
    require(isinstance(actions, list) and len(actions) <= 30, 'at most 30 frozen navigation actions')
    for action in actions:
        require(isinstance(action, dict), 'action must be an object')
        kind = action.get('action')
        if kind == 'back':
            device.call('shell', 'uitest', 'uiInput', 'keyEvent', 'Back')
        elif kind in ('tap', 'swipe'):
            keys = ('x', 'y') if kind == 'tap' else ('x1', 'y1', 'x2', 'y2', 'velocity')
            values = [action.get(k) for k in keys]
            require(all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 40000 for v in values),
                    'frozen action coordinates/velocity must be bounded integers')
            device.call('shell', 'uitest', 'uiInput', 'click' if kind == 'tap' else 'swipe', *values)
        else:
            require(False, 'unsupported navigation action; no arbitrary shell, text, or script execution')


def target_matches(xml, expected, app_id):
    require(isinstance(expected, list) and expected, 'frozen target_match selectors required')
    nodes = list(ET.fromstring(xml).iter('node'))
    for selector in expected:
        require(isinstance(selector, dict) and selector and
                set(selector) <= {'class', 'resource-id', 'text', 'content-desc', 'focused'}
                and all(isinstance(value, str) and value for value in selector.values()),
                'target_match supports nonempty exact UI attribute selectors only')
        if not any(all(n.get(key) == value for key, value in selector.items()) and
                   n.get('package') in ('', app_id) for n in nodes):
            return False
    return True


def foreground_app(output):
    current = None
    for line in output.splitlines():
        match = re.search(r'app name \[([^]]+)]', line)
        if match:
            current = match.group(1)
        if 'foreground' in line.lower() and current:
            return current
    return None


def scoped_scroll_region(xml, selector, app):
    if not selector:
        return None, None
    # Reuse the exact selector schema, then require an unambiguous actual scrollable node.
    target_matches(xml, [selector], app)
    matches = [node for node in ET.fromstring(xml).iter('node')
               if all(node.get(key) == value for key, value in selector.items())
               and node.get('package') in ('', app) and node.get('scrollable') == 'true']
    if len(matches) != 1:
        return None, None
    return matches[0], mobile_snapshot.bounds_box(matches[0].get('bounds', ''))


def capture(device, contract, args, path, module, task, out, root):
    target = validate_manifest.parse_target(path['coverage'])
    evidence = frozen_visual_evidence(module, path)
    if not evidence:
        return blocked('PATH lacks a frozen original capture manifest; use the existing adapter or review SPEC evidence',
                       'source-evidence-unavailable')
    manifest = read_json(check_ref(args.get('reference_manifest_ref')))
    validate_manifest.validate_manifest(manifest, [target])
    # A later attempt may append Harmony rounds. Its Android target is an exact copy of
    # the original frozen record, including every viewport, never just the first screenshot.
    reference = visual_evidence.match_source(args['reference_manifest_ref'], evidence, path['coverage'])
    require(reference['status'] == 'COMPLETE', 'source-only cannot authorize a visual candidate capture')
    require(any(file_ref(row['screenshot'])['sha256'] == path['baseline_ref']['sha256']
                for row in reference['snapshot']['captures']), 'Android reference differs from frozen baseline')
    install_path = check_ref(args.get('install_ref'))
    run_storage.checked_path(install_path, out.parents[1])
    install = visual_evidence.installation(args['install_ref'], artifact_ref=args['artifact_ref'],
        code_baseline=module['code_baseline'], device_id=device.device, app_id=contract['app_id'],
        assignment_id=task['assignment_id'], fencing_token=task.get('fencing_token'), run_root=str(root))
    round_id = args.get('round')
    require(isinstance(round_id, int) and not isinstance(round_id, bool) and round_id > 0,
            'positive explicit capture round required')
    require(not any(row.get('platform') == 'harmony' and row.get('page_id') == target['page_id']
                    and row.get('state_id') == target['state_id'] and row.get('round') == round_id
                    for row in manifest['targets']), 'preserve previous capture round; select a new round')
    app = token(contract.get('app_id'), 'app_id')
    if not installed_identity(device.call('shell', 'bm', 'dump', '-n', app), install.get('artifact_identity') or {}):
        return blocked('installed app identity no longer matches the accepted HAP', 'artifact-identity-unverified')
    ability = token(contract.get('ability', 'EntryAbility'), 'ability')
    device.call('shell', 'aa', 'start', '-b', app, '-a', ability)
    frozen_actions(device, contract.get('actions', []))
    foreground = device.call('shell', 'aa', 'dump', '-l')
    if foreground_app(foreground) != app:
        return blocked('requested app is not the observed foreground app', 'target-precondition')
    xml, page = device.layout(0)
    # A matching exact selector plus app ownership is required; caller supplied state labels alone
    # never produce COMPLETE. Current app dump is retained as evidence, not inferred from a launch.
    if not target_matches(xml, contract.get('target_match'), app):
        save(out / 'target-mismatch.json', {'foreground': foreground, 'view_xml': xml})
        return blocked('frozen target selectors not observed', 'target-precondition')
    region, region_bounds = scoped_scroll_region(xml, contract.get('scroll_region'), app)
    end_match = contract.get('scroll_end_match')
    if end_match:
        target_matches(xml, end_match, app)  # Validate before any scroll action.
    max_scrolls = contract.get('max_scrolls', 8)
    require(isinstance(max_scrolls, int) and not isinstance(max_scrolls, bool) and 0 <= max_scrolls <= 20,
            'max_scrolls must be 0..20')
    captures = []
    current_xml, page_name = xml, page
    termination = ('viewport' if target['coverage'] == 'viewport' else
                   'missing-frozen-scroll-region-or-endpoint' if not region_bounds or not end_match else 'scroll-limit')
    limit = 0 if termination != 'scroll-limit' else max_scrolls
    for index in range(limit + 1):
        if index:
            x1, y1, x2, y2 = region_bounds
            device.call('shell', 'uitest', 'uiInput', 'swipe', (x1 + x2) // 2,
                        y1 + (y2 - y1) * 3 // 4, (x1 + x2) // 2, y1 + (y2 - y1) // 4, 1000)
            current_xml, _ = device.layout(index)
        foreground = device.call('shell', 'aa', 'dump', '-l')
        if foreground_app(foreground) != app:
            return blocked('foreground app changed during capture', 'target-precondition')
        image_path = device.screenshot(index)
        if foreground_app(device.call('shell', 'aa', 'dump', '-l')) != app:
            return blocked('foreground app changed during screenshot', 'target-precondition')
        view = out / f'view-{index}.xml'
        run_storage.atomic_bytes(view, current_xml.encode())
        signature = mobile_snapshot.view_signature(current_xml, foreground)
        after_xml, _ = device.layout(f'{index}-after')
        after_view = out / f'view-{index}-after.xml'
        run_storage.atomic_bytes(after_view, after_xml.encode())
        if after_xml != current_xml:
            return blocked('page/state changed while screenshot was taken; retain both trees and recapture a new attempt',
                           'capture-incomplete', screenshot_ref=file_ref(image_path),
                           before_view_ref=file_ref(view), after_view_ref=file_ref(after_view))
        record = {'index': index, 'screenshot': str(image_path), 'view_tree': str(view),
                  'view_signature': signature}
        region, region_bounds = scoped_scroll_region(current_xml, contract.get('scroll_region'), app)
        endpoint_observed = bool(region_bounds and end_match and
                                 target_matches(ET.tostring(region, encoding='unicode'), end_match, app))
        if target['coverage'] == 'scroll' and endpoint_observed:
            captures.append(record)
            termination = 'frozen-scroll-end-observed'
            break
        if index and signature == captures[-1]['view_signature'] and \
                file_ref(image_path)['sha256'] == file_ref(captures[-1]['screenshot'])['sha256']:
            termination = 'observed-repeat-not-proof-of-end'
            break
        captures.append(record)
        if index and not region_bounds:
            termination = 'frozen-scroll-region-lost'
            break
    # Completeness is relative to the reviewed source-backed region/start/end contract.
    # A repeated first region or no exposed scroll attribute is never proof of the end.
    complete = target['coverage'] == 'viewport' or termination == 'frozen-scroll-end-observed'
    coverage = {'requested': target['coverage'], 'achieved': 'viewport' if target['coverage'] == 'viewport'
                else 'scroll-complete' if complete else 'scroll-partial', 'capture_count': len(captures),
                'termination': termination}
    backend = {'name': 'hdc', 'implementation': device.tool, 'version': device.version, 'device': device.device}
    meta = {'platform': 'harmony', 'device': device.device, 'app_id': app, 'foreground': foreground,
            'page_name': page_name, 'image_mime': 'image/jpeg', 'screenshot': Path(captures[0]['screenshot']).name,
            'view_signature': captures[0]['view_signature'], 'device_backend': backend, 'coverage': coverage,
            'captures': captures, 'install_ref': args['install_ref'], 'artifact_ref': args['artifact_ref'],
            'code_baseline': module['code_baseline'], 'assignment_id': task['assignment_id'],
            'fencing_token': task.get('fencing_token'),
            'target_match': contract['target_match']}
    if target['coverage'] == 'scroll':
        meta.update(scroll_region=contract.get('scroll_region'), scroll_end_match=end_match,
                    scroll_contract='frozen-source-backed-start-region-end')
    meta_ref = save(out / 'meta.json', meta)
    snapshot = {**captures[0], 'meta': meta_ref['path'], 'device_backend': backend,
                'coverage': coverage, 'captures': captures}
    result_manifest = copy.deepcopy(manifest)
    result_manifest['targets'].append({'mode': 'targeted', 'phase': 'harmony-candidate', 'platform': 'harmony',
            'page_id': target['page_id'], 'state_id': target['state_id'], 'observed_variant': target['state_id'],
            'round': round_id, 'status': 'COMPLETE' if complete else 'BLOCKED', 'coverage': coverage,
            'timestamp': datetime.now(timezone.utc).isoformat(), 'snapshot': snapshot,
            'target_match': {'kind': 'frozen-exact-selectors', 'matched': True}})
    manifest_ref = save(out / 'manifest.json', result_manifest)
    if not complete:
        return blocked('bounded scroll observations do not prove full scroll coverage; use the full runtime adapter',
                       'capture-incomplete', manifest_ref=manifest_ref)
    validate_manifest.validate_snapshot(snapshot, target['coverage'], path['coverage'])
    return {'status': 'CAPTURED', 'manifest_ref': manifest_ref, 'meta_ref': meta_ref,
            'artifact_ref': args['artifact_ref'], 'acceptance': 'capture-is-evidence-not-a-visual-verdict'}


def semantic(args, settings, path, out, root, module):
    model = settings.get('visual_model')
    if not isinstance(model, dict) or model.get('mode') != 'external' or model.get('enabled') is not True:
        return blocked('explicit enabled external visual_model configuration required')
    model = copy.deepcopy(model)
    require('api_key' not in model, 'store only an API key environment variable name in visual configuration')
    env_name = model.get('api_key_env')
    require(isinstance(env_name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env_name), 'api_key_env required')
    model['api_key'] = os.environ.get(env_name, '')
    if not model['api_key'] or not model.get('name') or not model.get('base_url'):
        return blocked('visual model name/base_url or configured API key environment variable missing')
    url = urlparse(model['base_url'])
    require(url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password,
            'visual model requires an explicit HTTP(S) endpoint without URL credentials')
    reference, candidate, score_file = [check_ref(args.get(k)) for k in ('reference_ref', 'candidate_ref', 'score_ref')]
    for evidence in (candidate, score_file):
        run_storage.checked_path(evidence, root)
    for screenshot in (reference, candidate):
        with screenshot.open('rb') as image:
            magic = image.read(8)
        require(screenshot.stat().st_size <= 32 * 1024 * 1024 and
                (magic == b'\x89PNG\r\n\x1a\n' or magic.startswith(b'\xff\xd8\xff')),
                'semantic images must be PNG/JPEG files no larger than 32 MiB')
        try:
            image_valid(screenshot)
        except DeviceFailure as exc:
            return blocked(str(exc), exc.kind)
    evidence = frozen_visual_evidence(module, path)
    baselines = evidence['baseline_refs'] if evidence else [path['baseline_ref']]
    require(file_ref(reference)['sha256'] in {ref['sha256'] for ref in baselines},
            'semantic reference differs from this coverage frozen baseline set')
    score = read_json(score_file)
    require(file_ref(score.get('reference')) == args['reference_ref'] and
            file_ref(score.get('candidate')) == args['candidate_ref'], 'score must bind the actual comparison images')
    timeout = model.get('timeout_seconds', 120)
    require(isinstance(timeout, int) and 1 <= timeout <= 180, 'visual model timeout must be 1..180 seconds')
    try:
        from lean_semantic_process import call
        raw = call(model, path['coverage'], reference, candidate, score, timeout)
        require(isinstance(raw, dict) and raw.get('status') == 'COMPLETE', 'model did not return COMPLETE semantic inspection')
        require(raw.get('visual_id', path['coverage']) == path['coverage'], 'semantic target mismatch')
        for key, maximum in (('overall', 100), ('comparability', 1)):
            value = raw.get(key)
            require(isinstance(value, (int, float)) and not isinstance(value, bool) and
                    math.isfinite(value) and 0 <= value <= maximum, 'invalid semantic ' + key)
        issues = raw.get('issues')
        require(isinstance(issues, list) and len(issues) <= 2 and all(isinstance(i, dict) and
                all(isinstance(i.get(k), str) and i[k].strip() for k in ('area', 'problem', 'likely_code_area', 'evidence'))
                and i.get('severity') in ('low', 'medium', 'high', 'critical') for i in issues),
                'semantic issues must follow the bounded evidence schema')
        result = semantic_visual_inspect.normalize_result(raw, path['coverage'], model)
        result.update(score_sha256=args['score_ref']['sha256'], reference=str(reference), candidate=str(candidate),
                      score_ref=args['score_ref'], reference_ref=args['reference_ref'], candidate_ref=args['candidate_ref'])
        return {'status': 'INSPECTED', 'semantic_ref': save(out / 'visual-issues.json', result),
                'acceptance': 'semantic-inspection-is-evidence-not-a-visual-verdict'}
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        # API error bodies and exception strings may echo credentials or inline screenshots.
        return blocked('semantic inspection failed: ' + type(exc).__name__, 'semantic-unavailable')


def run(operation, args, *, root, out, module, task, actor, config):
    require(operation in OPERATIONS and actor.get('role') in ('test-runner', 'auditor'), 'visual capability outside role')
    root, out = Path(root).resolve(), Path(out).resolve()
    runner_storage.harmony_output(root, out, 'sandbox')
    path = path_context(args, module, task)
    if operation != 'visual-install':
        require(path['kind'] == 'visual', 'capture/semantic inspection require a visual PATH')
    contract, settings = configuration(root, path)
    if contract is None:
        return blocked('frozen visual_execution.environment_ref missing; prepare run environment and review the PATH configuration')
    if operation == 'semantic-inspect':
        return semantic(args, settings, path, out, root, module)
    device_settings = settings.get('visual_capture')
    if not isinstance(device_settings, dict) or not device_settings.get('device_id'):
        return blocked('explicit run visual_capture backend and device_id required')
    device_lock(actor, device_settings, task)
    artifact = accepted_artifact(args, module, path)
    app = token(contract.get('app_id'), 'app_id')
    device = Device(device_settings, out)
    try:
        device.version = device.call('-v').strip()
        if not device.version:
            raise DeviceFailure('environment-unavailable', 'HDC version could not be observed')
        if operation == 'visual-install':
            identity = hap_identity(artifact)
            if identity['bundleName'] != app:
                raise DeviceFailure('artifact-identity-unverified', 'accepted HAP bundleName differs from frozen app_id')
            device.call('install', '-r', artifact, timeout=240)
            installed = device.call('shell', 'bm', 'dump', '-n', app)
            if not installed_identity(installed, identity):
                raise DeviceFailure('artifact-identity-unverified', 'installed app bundle/version differs from accepted HAP')
            result = {'producer': 'lean-visual-worker', 'operation': operation, 'status': 'INSTALLED',
                      'artifact_ref': args['artifact_ref'], 'code_baseline': module['code_baseline'],
                      'device_id': device.device, 'app_id': app, 'assignment_id': task['assignment_id'],
                      'fencing_token': task.get('fencing_token'), 'installed_metadata': installed,
                      'artifact_identity': identity,
                      'acceptance': 'installation-is-evidence-not-a-test-verdict'}
        else:
            result = capture(device, contract, args, path, module, task, out, root)
    except DeviceFailure as exc:
        result = blocked(str(exc), exc.kind)
    finally:
        evidence = device.finish()
    result.update(evidence)
    if result.get('status') == 'CAPTURED':
        manifest = read_json(check_ref(result['manifest_ref']))
        record = manifest['targets'][-1]
        execution = {'schema_version': 1, 'producer': 'sdd-visual-capture', 'status': 'CAPTURED',
            'executed': True, 'coverage': path['coverage'], 'capture_round': args['round'],
            'artifact_ref': args['artifact_ref'], 'code_baseline': module['code_baseline'],
            'assignment_id': task['assignment_id'], 'fencing_token': task.get('fencing_token'),
            'device_id': device.device, 'app_id': app, 'install_ref': args['install_ref'],
            'observations': visual_evidence.observations(record, out),
            'command_log_ref': evidence['command_log_ref']}
        record['snapshot']['capture_execution_ref'] = save(out / 'capture-execution.json', execution)
        result['manifest_ref'] = save(out / 'manifest.json', manifest)
        result['capture_execution_ref'] = record['snapshot']['capture_execution_ref']
    return result
