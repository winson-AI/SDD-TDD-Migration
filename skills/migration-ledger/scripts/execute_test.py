#!/usr/bin/env python3
"""Host adapter: execute one approved query and preserve command/output evidence.

Host MUST authorize argv/cwd/role before calling. This utility is not a sandbox.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid
import workflow
import context_readiness
import test_validation as tv

from contracts import baseline, file_ref, read_json, require
from ledger import status, atomic, audit_scope


def execute(root, module_id, assignment_id, path_id, argv, cwd, output, timeout=300):
    s = status(root)
    if module_id == 'GLOBAL':
        require(all(tv.available(m) for m in s['modules'].values()), 'audit modules no longer ready')
        m = audit_scope(s)
        a = s.get('audit_assignment', {})
        require(not a.get('closed', True) and a.get('assignment_id') == assignment_id and a.get('snapshot') ==
                {k:v['code_baseline'] for k,v in s['modules'].items()}, 'audit assignment required')
        require(a.get('scope_policy') == 'non-green-only', 'legacy full audit assignment; revoke and reassign')
        require(path_id in a.get('path_ids', []), 'path outside collected audit scope')
    else:
        m = s['modules'][module_id]
        if s.get('audit_assignment', {}).get('mode') == 'problem' and s['audit_assignment'].get('assignment_id') == assignment_id:
            a = workflow.problem_assignment(s, module_id)
            require(workflow.runnable(s, module_id), 'problem path unavailable; record Yellow')
        else:
            a = m['assignments'][assignment_id]
        require(not a['closed'] and ((a['role'] == 'test-runner' and m['phase'] == 'testing') or a.get('mode') == 'problem'), 'test assignment required')
    context_readiness.check_execution(s, a, argv, cwd, path_id)
    require(baseline(m['code_files']) == m['code_baseline'], 'code changed before execution')
    path = next(p for p in m['plan']['paths'] if p['path_id'] == path_id)
    is_build = path.get('kind') == 'build'
    if tv.split(m) and module_id != 'GLOBAL':
        require((a.get('test_scope') == 'build') == is_build, 'path outside test assignment scope')
        require(is_build or tv.build_ready(m), 'build must pass before automation')
    if is_build:
        require(argv == path['command']['argv'] and str(Path(cwd).resolve()) == str(Path(path['command']['cwd']).resolve()), 'build command differs from frozen plan')
        timeout = path['command']['timeout_seconds']
    out = Path(output).resolve()
    require(not out.exists(), 'execution output must be new')
    out.mkdir(parents=True)
    query = {**path, 'run_id': s['run_id'], 'module_id': module_id,
             'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline']}
    atomic(out / 'query.json', query)
    command = argv if is_build else [*argv, '--query-file', str(out / 'query.json'), '--result-file', str(out / 'result.json')]
    require(command and argv and Path(cwd).is_dir(), 'argv/cwd required')
    started = datetime.now(timezone.utc).isoformat()
    try:
        # An agentic adapter can spawn media/tools processes; stop the whole attempt.
        proc = subprocess.Popen(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code, log = proc.returncode, stdout + '\n' + stderr
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
            exit_code, log = 124, stdout + '\n' + stderr + '\nHost timeout: process group stopped.'
    except OSError as exc:
        exit_code, log = 127, f'Adapter launch failed: {exc}'
    (out / 'execution.log').write_text(log)
    if is_build:
        quality = 'green-passed' if exit_code == 0 else 'yellow-blocked' if exit_code in (124, 127) else 'red-bug'
        atomic(out / 'result.json', {'producer': 'build-executor', 'quality': quality,
            'assertions': [{'assertion_id': path['expected_assertions'][0]['assertion_id'], 'expected': 0,
                            'actual': exit_code, 'passed': exit_code == 0}],
            'root_cause': None if exit_code == 0 else {'category': 'tooling' if exit_code in (124,127) else 'build',
                'summary': 'Build exit ' + str(exit_code) + '; inspect captured compiler/tool log',
                'confidence': 'observed', 'owner': module_id, 'next_action': 'diagnose',
                'evidence_refs': [file_ref(out / 'execution.log')]}})
    receipt = {'schema_version': 1, 'producer': 'host-executor', 'run_id': s['run_id'],
               'module_id': module_id, 'path_id': path_id, 'test_run_id': str(uuid.uuid4()),
               'assignment_id': assignment_id, 'actor_instance_id': a['instance_id'],
               'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
               'argv': command, 'cwd': str(Path(cwd).resolve()), 'started_at': started,
               'finished_at': datetime.now(timezone.utc).isoformat(), 'exit_code': exit_code,
               'log_ref': file_ref(out / 'execution.log'), 'query_ref': file_ref(out / 'query.json'),
               'result_ref': file_ref(out / 'result.json') if (out / 'result.json').is_file() else None}
    atomic(out / 'receipt.json', receipt)
    # Result acceptance rechecks the baseline and active assignment after the subprocess.
    return file_ref(out / 'receipt.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('root', 'module', 'assignment', 'path-id', 'adapter', 'cwd', 'output'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--timeout', type=int)
    args = parser.parse_args()
    try:
        adapter = read_json(args.adapter)
        print(json.dumps(execute(args.root, args.module, args.assignment, args.path_id,
                                 adapter['argv'], args.cwd, args.output, args.timeout or adapter.get('timeout', 300))))
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
