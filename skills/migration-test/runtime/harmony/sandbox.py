#!/usr/bin/env python3
"""uv entry point; dependency isolation only, not an OS permission sandbox."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT.parents[1] / 'scripts'


def load_environment(path):
    from dotenv import load_dotenv
    # Explicit location, never search the target project's cwd for credentials.
    load_dotenv(Path(path).resolve(), override=False)


def doctor(config_path, device=None):
    """Offline check only: never contact a model or operate a device."""
    checks = []
    for module in ('openai', 'agents', 'hypium', 'hypium_mcp', 'cv2', 'PIL',
                   'numpy', 'ffmpeg', 'imageio_ffmpeg', 'yaml', 'dotenv'):
        try:
            importlib.import_module(module)
            checks.append({'name': module, 'status': 'ready'})
        except Exception as exc:
            # Exceptions from libraries can contain configuration; don't echo them.
            checks.append({'name': module, 'status': 'blocked', 'reason': type(exc).__name__})
    try:
        from harmony_adapter import configure
        config = json.loads(Path(config_path).read_text())
        cfg = configure(config['models'])
        checks.append({'name': 'llm-configuration', 'status': 'ready',
                       'planner': [m['name'] for m in cfg.decision_models],
                       'executor': cfg.execute_model_name, 'verify': cfg.verify_model_name,
                       'provider': cfg.execute_provider})
        serial = device or config.get('device') or os.environ.get('HARMONY_DEVICE')
        checks.append({'name': 'explicit-device', 'status': 'ready' if serial else 'blocked'})
        checks.append({'name': 'hdc-on-path', 'status': 'ready' if shutil.which('hdc') else 'blocked'})
    except Exception as exc:
        checks.append({'name': 'configuration', 'status': 'blocked', 'reason': type(exc).__name__})
    ready = all(c['status'] == 'ready' for c in checks)
    return {'status': 'ready-for-live-preflight' if ready else 'yellow-blocked',
            'checks': checks, 'automated_tests_executed': False,
            'note': 'Offline only; host must check device connectivity, model access, fixtures and installed app baseline.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'test', 'design', 'adapter'):
        c = sub.add_parser(name)
        c.add_argument('--config', default=str(ROOT / 'config.default.json'))
        c.add_argument('--env-file', default=str(ROOT / '.env'))
        if name != 'design': c.add_argument('--device')
        if name == 'test':
            c.add_argument('--query-file', required=True)
            c.add_argument('--result-file', required=True)
        if name == 'design':
            for arg in ('input', 'module', 'output'): c.add_argument('--' + arg, required=True)
            c.add_argument('--app-name')
        if name == 'adapter':
            c.add_argument('--output', required=True)
            c.add_argument('--timeout', type=int, default=1860)
    a = p.parse_args()
    config = str(Path(a.config).resolve())
    env_file = str(Path(a.env_file).resolve())
    sys.path.insert(0, str(SCRIPTS))
    if a.command == 'adapter':
        if a.timeout <= 0: p.error('--timeout must be positive')
        argv = [sys.executable, str(Path(__file__).resolve()), 'test', '--config', config,
                '--env-file', env_file]
        if a.device: argv += ['--device', a.device]
        with Path(a.output).open('x') as f:
            json.dump({'argv': argv, 'timeout': a.timeout}, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print(str(Path(a.output).resolve()))
        return 0
    load_environment(env_file)
    if a.command == 'doctor':
        result = doctor(config, a.device)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'ready-for-live-preflight' else 2
    if a.command == 'test':
        argv = [sys.executable, str(SCRIPTS / 'harmony_adapter.py'), '--config', config,
                '--query-file', str(Path(a.query_file).resolve()),
                '--result-file', str(Path(a.result_file).resolve())]
        if a.device: argv += ['--device', a.device]
    else:
        argv = [sys.executable, str(SCRIPTS / 'harmony_design.py'), '--config', config,
                '--input', str(Path(a.input).resolve()), '--module', a.module,
                '--output', str(Path(a.output).resolve())]
        if a.app_name: argv += ['--app-name', a.app_name]
    # Preserve the host process-group timeout and native exit status; no shell.
    os.execv(sys.executable, argv)


if __name__ == '__main__':
    sys.exit(main())
