"""A live smoke of the Android lanes on an emulator: the stated device is booted when it does not answer, the legacy
application is installed and its first screen captured as an android-reference record, the runtime index is selected from
it, then the same package is installed again as the candidate build, hashed on the device and captured as an
android-candidate record against that reference. Not collected by pytest: it needs adb, an AVD (Android Studio's) and the
application's APK, which the package does not carry; every project value is an argument. The emulator the worker boots is
left running, as a run would leave it for the host. Exit code 0 means both lanes walked end to end.

    python3 skills/migration-ledger/tests/smoke_device_capture.py --apk <absolute.apk> --app <package> --launch <activity>
        [--serial emulator-5554] [--avd <name>] [--adb <absolute adb>] [--match class=android.widget.FrameLayout]... [--keep]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import file_ref, read_json
import lean_visual_worker as worker
import ui_evidence
from lean_tools import select_runtime_ui, validate_manifest

COVERAGE = 'home:base:viewport'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--apk', required=True, help='absolute path of the application, installed as the legacy and again as the candidate')
    parser.add_argument('--app', required=True, help='its package name')
    parser.add_argument('--launch', required=True, help='its launch activity, as am start names it after the package')
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('--avd', help='the AVD the worker boots when the serial does not answer')
    parser.add_argument('--adb', default=shutil.which('adb'), help='absolute adb; default: the one on PATH')
    parser.add_argument('--match', action='append', default=[], help='key=value selector of the first screen; repeatable')
    parser.add_argument('--keep', action='store_true')
    a = parser.parse_args()
    apk, adb = Path(a.apk).resolve(), Path(a.adb).resolve() if a.adb else None
    if adb and adb.parent.name == 'platform-tools' and not (os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME')):
        os.environ['ANDROID_SDK_ROOT'] = str(adb.parent.parent)  # the AVD boots through this SDK's emulator
    match = [dict([m.split('=', 1)]) for m in a.match] or [{'class': 'android.widget.FrameLayout'}]
    targets = [{'coverage': COVERAGE, 'target_match': match}]
    base = Path(tempfile.mkdtemp(prefix='sdd-device-smoke-')).resolve()  # managed paths never pass through a symlink
    root = base / '.sdd-runs/run-1'; (root / 'context').mkdir(parents=True)
    row, started, passed = {'case': 'android-lanes', 'device': a.serial}, time.time(), False
    try:
        stated = {'kind': 'android-emulator', 'app_id': a.app, 'device': {'serial': a.serial, **({'avd': a.avd} if a.avd else {})},
                  'artifact': str(apk), 'artifact_sha256': file_ref(apk)['sha256'], 'launch': a.launch}
        statement = root / 'context/legacy-preview.json'; statement.write_text(json.dumps({'effective_config': {'legacy_preview': stated}, 'source_refs': {}}))
        state = {'run_id': 'run-1', 'project_context_ref': file_ref(statement), 'modules': {}}
        out = root / 'runs/harmony/sandbox/spec-1/attempt-1'; out.mkdir(parents=True)
        legacy = worker.legacy_capture({'targets': targets, 'tool': str(adb)}, root=root, out=out, state=state,
                                       task={'role': 'spec-designer', 'assignment_id': 'A1', 'fencing_token': 'fence-1'},
                                       actor={'role': 'spec-designer', 'instance_id': 'spec-1', 'device_lock': {'held': True, 'device_id': a.serial, 'assignment_id': 'A1', 'fencing_token': 'fence-1'}}, module_id='M001')
        row['legacy'] = legacy['status']
        if legacy.get('boot_ref'):
            row['booted_after_seconds'] = read_json(legacy['boot_ref']['path'])['waited_seconds']
        if legacy['status'] != 'CAPTURED':
            row['blocked'] = legacy.get('blocked') or (legacy.get('root_cause') or {}).get('reason'); return row, False
        runtime = select_runtime_ui.select(Path(legacy['manifest_ref']['path']), [COVERAGE])
        row['runtime_index'] = len(runtime.get('captures') or runtime)
        reference = ui_evidence.capture_target(legacy['manifest_ref'], COVERAGE)
        baseline = file_ref(reference['snapshot']['captures'][0]['screenshot'])
        env = root / 'runs/harmony/sandbox/environment/visual-adb.json'; env.parent.mkdir(parents=True)
        env.write_text(json.dumps({'visual_capture': {'backend': 'adb', 'tool': str(adb), 'device_id': a.serial, **({'avd': a.avd} if a.avd else {})},
                                   'visual_model': {'mode': 'external', 'enabled': False, 'name': 'vision-smoke', 'base_url': 'https://model.example/v1', 'api_key_env': 'SDD_SMOKE_VISION_KEY'}}))
        candidate = root / 'runs/build/build-1/app.apk'; candidate.parent.mkdir(parents=True); shutil.copyfile(apk, candidate)
        path = {'path_id': 'V1', 'kind': 'visual', 'coverage': COVERAGE, 'baseline_ref': baseline,
                'visual_execution': {'environment_ref': file_ref(env), 'app_id': a.app, 'ability': a.launch, 'target_match': match, 'actions': []}}
        evidence = {'visual_mode': 'runtime', 'coverage': COVERAGE, 'capture_manifest_ref': legacy['manifest_ref'], 'baseline_refs': [baseline]}
        analysis = root / 'context/dimensions.json'
        analysis.write_text(json.dumps({'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [{'semantic_model': {'ui_evidence': evidence}}]}]}))
        module = {'module_id': 'M001', 'code_baseline': 'code-1', 'plan': {'paths': [path], 'dimension_analysis_ref': file_ref(analysis)}, 'build_artifacts': [file_ref(candidate)]}
        task = {'role': 'test-runner', 'assignment_id': 'T1', 'fencing_token': 'fence-2', 'test_scope': 'visual'}
        actor = {'role': 'test-runner', 'instance_id': 'test-1', 'device_lock': {'held': True, 'device_id': a.serial, 'assignment_id': 'T1', 'fencing_token': 'fence-2'}}
        args = {'path_id': 'V1', 'artifact_ref': file_ref(candidate)}
        def run_tool(operation, step, **extra):
            folder = root / 'runs/harmony/sandbox/test-1' / step; folder.mkdir(parents=True)
            result = worker.run(operation, {**args, **extra}, root=root, out=folder, module=module, task=task, actor=actor, config={})
            return result, worker.save(folder / 'result.json', result)
        install, install_ref = run_tool('visual-install', 'install')
        row['install'] = install['status']
        if install['status'] != 'INSTALLED':
            row['blocked'] = (install.get('root_cause') or {}).get('reason'); return row, False
        result, _ = run_tool('visual-capture', 'capture', install_ref=install_ref, round=1, reference_manifest_ref=legacy['manifest_ref'])
        row['status'] = result['status']
        if result['status'] != 'CAPTURED':
            row['blocked'] = (result.get('root_cause') or {}).get('reason'); return row, False
        record = read_json(result['manifest_ref']['path'])['targets'][-1]
        validate_manifest.validate_snapshot(record['snapshot'], 'viewport', 'candidate')
        execution = read_json(result['capture_execution_ref']['path'])
        row['candidate'] = (record['phase'], record['platform'], record['round'], len(execution['observations']))
        passed = record['phase'] == 'android-candidate' and bool(execution['observations']) and read_json(record['snapshot']['meta'])['artifact_identity']['sha256'] == stated['artifact_sha256']
        return row, passed
    except Exception as exc:  # the smoke reports, it does not hide
        row['error'] = type(exc).__name__ + ': ' + str(exc)[:200]
        return row, False
    finally:
        row['seconds'] = round(time.time() - started, 1)
        print(('PASS ' if passed else 'FAIL ') + json.dumps(row, ensure_ascii=False))
        if a.keep:
            print('kept', base)
        else:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(0 if main()[1] else 1)
