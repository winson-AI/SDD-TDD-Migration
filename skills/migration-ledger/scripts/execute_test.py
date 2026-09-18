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

from contracts import baseline, file_ref, read_json, require
from ledger import status, atomic, audit_scope


def execute(root, module_id, assignment_id, path_id, argv, cwd, output, timeout=300):
    s = status(root)
    if module_id == 'GLOBAL':
        require(all(m['phase'] == 'completed' and not m['stale'] for m in s['modules'].values()), 'audit modules no longer ready')
        m = audit_scope(s)
        a = s.get('audit_assignment', {})
        require(not a.get('closed', True) and a.get('assignment_id') == assignment_id and a.get('snapshot') ==
                {k:v['code_baseline'] for k,v in s['modules'].items()}, 'audit assignment required')
    else:
        m = s['modules'][module_id]
        if s.get('audit_assignment', {}).get('mode') == 'problem' and s['audit_assignment'].get('assignment_id') == assignment_id:
            a = workflow.problem_assignment(s, module_id)
            require(workflow.runnable(s, module_id), 'problem path unavailable; record Yellow')
        else:
            a = m['assignments'][assignment_id]
        require(not a['closed'] and ((a['role'] == 'test-runner' and m['phase'] == 'testing') or a.get('mode') == 'problem'), 'test assignment required')
    context_readiness.check_execution(s, a, argv, cwd)
    require(baseline(m['code_files']) == m['code_baseline'], 'code changed before execution')
    path = next(p for p in m['plan']['paths'] if p['path_id'] == path_id)
    out = Path(output).resolve()
    require(not out.exists(), 'execution output must be new')
    out.mkdir(parents=True)
    query = {**path, 'run_id': s['run_id'], 'module_id': module_id,
             'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline']}
    atomic(out / 'query.json', query)
    command = [*argv, '--query-file', str(out / 'query.json'), '--result-file', str(out / 'result.json')]
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
