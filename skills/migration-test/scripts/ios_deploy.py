#!/usr/bin/env python3
"""Install a build's signed IPA on a designated iOS device and write its deployment receipt."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-ledger/scripts'))
from contracts import check_ref, file_ref, require
from device_lease import lock
from ios_evidence import check_device, document, package_info
from project_context import wda_endpoint
from ledger import atomic


def install(coverage_path, out, udid, endpoint, *, capture_uid=None):
    from AutoTest.devices.ios.screenshot import physical_device, physical_installation
    import wda

    coverage_ref = file_ref(coverage_path)
    coverage = document(coverage_ref)
    baselines = coverage.get('module_baselines')
    require(isinstance(baselines, dict) and baselines and all(baselines.values()), 'a build coverage manifest is required')
    artifact = coverage['artifact_ref']
    info = package_info(artifact)
    bundle, version = info['CFBundleIdentifier'], str(info['CFBundleVersion'])
    endpoint = wda_endpoint(endpoint)
    out.mkdir(parents=True, exist_ok=False)
    with lock(endpoint, 'ios', udid), TemporaryDirectory(prefix='provision-', dir=out) as staging:
        device = physical_device(udid)
        wda_info = wda.Client(endpoint).http.get('/wda/device/info', timeout=3).value
        require(wda_info.get('isSimulator') is False and wda_info.get('uuid') not in (None, '', 'unknown'),
                'a ready WDA on the designated physical device is required')
        copy = Path(staging) / 'signed.ipa'
        shutil.copyfile(check_ref(artifact), copy)
        check_ref({'path': str(copy), 'sha256': artifact['sha256']})
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(copy), staging], check=True, timeout=120)
        applications = list((Path(staging) / 'Payload').glob('*.app'))
        require(len(applications) == 1, 'signed IPA must contain one main App bundle')
        app = applications[0]
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '--deep', str(app)], check=True, timeout=60)
        raw = out / 'devicectl-install.json'
        core_device = device['identifier']
        subprocess.run(['xcrun', 'devicectl', 'device', 'install', 'app', '--device', core_device,
                        '--json-output', str(raw), str(app)], check=True, timeout=120)
        installation = out / 'installation.json'
        atomic(installation, {'artifact_ref': artifact, 'udid': udid, 'core_device_id': core_device,
                              'devicectl_ref': file_ref(raw), 'extracted_app': str(app)})
        receipt = {'schema_version': 2, 'udid': udid, 'wda_uuid': wda_info['uuid'], 'wda_url': endpoint, 'bundle_id': bundle,
                   'build_version': version, 'artifact_ref': artifact, 'build_coverage_ref': coverage_ref,
                   'installation_ref': file_ref(installation), **({'avfoundation_uid': capture_uid} if capture_uid else {})}
        candidate = Path(staging) / 'deployment.json'
        atomic(candidate, receipt)
        binding = {'udid': udid, 'app_id': bundle, 'wda_url': endpoint, 'deployment_ref': file_ref(candidate), 'module_baselines': baselines}
        installed = physical_installation(device, bundle)
        observed = {'wda_uuid': wda_info['uuid'], 'endpoint': endpoint, 'is_simulator': False, 'configured_udid': udid,
                    'installed': installed, 'deployment_ref': binding['deployment_ref'], 'avfoundation_uid': capture_uid}
        check_device(binding, None, observed)
        path = out / 'deployment.json'
        candidate.replace(path)
        return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('coverage', 'output', 'udid', 'wda-url'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--avfoundation-uid')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/harmony'))
    print(install(Path(args.coverage).resolve(), Path(args.output).resolve(), args.udid, args.wda_url,
                  capture_uid=args.avfoundation_uid))


if __name__ == '__main__':
    main()
