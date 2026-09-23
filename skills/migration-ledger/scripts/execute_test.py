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
sys.dont_write_bytecode = True
import uuid
import workflow
import context_readiness
import test_validation as tv
import run_storage
import runner_storage

from contracts import baseline, file_ref, read_json, require
from ledger import status, atomic, audit_scope


OUTPUT_DRAIN_TIMEOUT_SECONDS = 2


def finish_timeout(proc):
    """Bound pipe recovery even when a detached descendant retains the pipes."""
    termination = {'pid': proc.pid, 'process_group_id': proc.pid, 'signal': 'SIGKILL',
                   'output_drained': False, 'host_stop_required': True}
    try:
        os.killpg(proc.pid, signal.SIGKILL)
        termination['signal_result'] = 'sent'
    except ProcessLookupError:
        termination['signal_result'] = 'group-not-found'
    except OSError as exc:
        termination.update(signal_result='failed', signal_error=str(exc))
    try:
        stdout, stderr = proc.communicate(timeout=OUTPUT_DRAIN_TIMEOUT_SECONDS)
        termination['output_drained'] = True
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired carries all captured bytes, including the first wait.
        def decoded(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
        stdout, stderr = decoded(exc.stdout), decoded(exc.stderr)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None: stream.close()
    except (OSError, ValueError) as exc:
        stdout, stderr = '', ''
        termination['recovery_error'] = type(exc).__name__
        for stream in (proc.stdout, proc.stderr):
            if stream is not None: stream.close()
    termination['direct_process_exited'] = proc.poll() is not None
    termination['host_stop_required'] = (not termination['output_drained'] or
        not termination['direct_process_exited'] or termination['signal_result'] == 'failed')
    # Pipe EOF is not a general proof that arbitrary detached descendants exited.
    termination['descendants_status'] = 'unknown'
    termination['next_action'] = ('Host verify stop/isolation, then revoke with evidence; retain runner temp'
                                  if termination['host_stop_required'] else 'interpret timeout receipt')
    return stdout, stderr, termination


def execute(root, module_id, assignment_id, path_id, argv, cwd, output, timeout=300):
    root = Path(root).resolve()
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
    out = run_storage.test_output(root, s, output)
    if run_storage.for_state(root, s) or root.parent.name == '.sdd-runs':
        run_storage.checked_path(out, Path(root) / ('runs/build' if is_build else 'runs/harmony/automation'))
    require(not out.exists(), 'execution output must be new')
    command = runner_storage.build_command(argv, out) if is_build else [*argv, '--query-file', str(out / 'query.json'), '--result-file', str(out / 'result.json')]
    require(command and argv and Path(cwd).is_dir(), 'argv/cwd required')
    out.mkdir(parents=True)
    execution_env = runner_storage.environment(out)
    init = None
    if is_build and runner_storage.gradle_command(argv):
        # Retain the output policy; cache flags must be set before Gradle starts.
        init = Path(execution_env['GRADLE_USER_HOME']) / 'init.d/sdd-storage.init.gradle'
        run_storage.atomic_bytes(init, b'''def runner = new File(System.getenv('SDD_RUNNER_DIR'))
gradle.beforeProject { p ->
    def key = java.security.MessageDigest.getInstance('SHA-256').digest(p.projectDir.canonicalPath.bytes).encodeHex().toString()
    def outputs = new File(runner, 'outputs/' + key)
    p.layout.buildDirectory.set(outputs)
    p.afterEvaluate {
        if (!p.layout.buildDirectory.get().asFile.canonicalFile.toPath().startsWith(runner.canonicalFile.toPath())) {
            throw new GradleException('Build output escapes SDD runner; configure buildDirectory under SDD_RUNNER_DIR')
        }
    }
}
''')
    query = {**path, 'run_id': s['run_id'], 'module_id': module_id,
             'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline']}
    atomic(out / 'query.json', query)
    started = datetime.now(timezone.utc).isoformat()
    termination, proc, aborted = None, None, None
    try:
        # An agentic adapter can spawn media/tools processes; stop the whole attempt.
        proc = subprocess.Popen(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, errors='replace', start_new_session=True, env=execution_env)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code, log = proc.returncode, stdout + '\n' + stderr
        except subprocess.TimeoutExpired:
            stdout, stderr, termination = finish_timeout(proc)
            exit_code, log = 124, stdout + '\n' + stderr + '\nHost timeout: ' + json.dumps(termination)
    except BaseException as exc:
        if proc is None and isinstance(exc, OSError):
            exit_code, log = 127, f'Adapter launch failed: {exc}'
        else:
            # Record cancellation, then re-raise it after persisting the receipt.
            # It must not be converted into an automatic retry or a successful run.
            aborted = exc
            termination = {'host_stop_required': True, 'direct_process_exited': False,
                           'descendants_status': 'unknown'}
            stdout, stderr = '', ''
            if proc is not None:
                try:
                    stdout, stderr, termination = finish_timeout(proc)
                except BaseException as recovery_error:
                    # A second interruption must never make cleanup assume exit.
                    termination['recovery_error'] = type(recovery_error).__name__
            termination.update(executor_aborted=True, exception_type=type(exc).__name__,
                               next_action='Host review cancellation and stop/isolation evidence; revoke; no automatic restart')
            exit_code = (exc.code if isinstance(exc, SystemExit) and type(exc.code) is int and exc.code != 0
                         else 130 if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 125)
            log = stdout + '\n' + stderr + '\nExecutor aborted: ' + json.dumps(termination)
    finally:
        def cleanup(directory):
            if termination and termination['host_stop_required']:
                return {'path': str(directory / 'temp'), 'status': 'retained-in-run',
                        'reason': 'process-stop-unconfirmed; Host stop/isolation verification required'}
            return runner_storage.cleanup(directory)
        scratch = cleanup(out)
        # Nested Harmony owns its temp normally; SIGKILL prevents its finally.
        nested = []
        if (out / 'harmony/temp').exists():
            nested.append(cleanup(out / 'harmony'))
        atomic(out / 'cleanup.json', {'scratch': scratch, 'nested': nested})
    (out / 'execution.log').write_text(log)
    if is_build:
        quality = 'green-passed' if exit_code == 0 else 'yellow-blocked' if aborted or exit_code in (124, 127) else 'red-bug'
        atomic(out / 'result.json', {'producer': 'build-executor', 'quality': quality,
            'assertions': [{'assertion_id': path['expected_assertions'][0]['assertion_id'], 'expected': 0,
                            'actual': exit_code, 'passed': exit_code == 0}],
            'root_cause': None if exit_code == 0 else {'category': 'tooling' if aborted or exit_code in (124,127) else 'build',
                'summary': 'Build exit ' + str(exit_code) + '; inspect captured compiler/tool log',
                'confidence': 'observed', 'owner': module_id, 'next_action': 'diagnose',
                'evidence_refs': [file_ref(out / 'execution.log')]}})
    receipt = {'schema_version': 1, 'producer': 'host-executor', 'run_id': s['run_id'],
               'module_id': module_id, 'path_id': path_id, 'test_run_id': str(uuid.uuid4()),
               'assignment_id': assignment_id, 'actor_instance_id': a['instance_id'],
               'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
               'argv': command, 'cwd': str(Path(cwd).resolve()), 'started_at': started,
               'requested_argv': argv, 'storage_command_version': 1,
               'finished_at': datetime.now(timezone.utc).isoformat(), 'exit_code': exit_code,
               'cleanup_ref': file_ref(out / 'cleanup.json'),
               'storage_policy_ref': file_ref(init) if init else None,
               'log_ref': file_ref(out / 'execution.log'), 'query_ref': file_ref(out / 'query.json'),
               'result_ref': file_ref(out / 'result.json') if (out / 'result.json').is_file() else None}
    if termination:
        receipt['termination'] = termination
    if not is_build:
        for observations in (out / 'harmony/observations.json', out / 'observations.json'):
            if observations.is_file():
                run_storage.checked_path(observations, out)
                receipt['partial_observations_ref'] = file_ref(observations)
                break
    atomic(out / 'receipt.json', receipt)
    if aborted is not None:
        raise aborted
    # Result acceptance rechecks the baseline and active assignment after the subprocess.
    return file_ref(out / 'receipt.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('root', 'module', 'assignment', 'path-id', 'adapter', 'cwd', 'output'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--timeout', type=int)
    args = parser.parse_args()
    def terminated(signum, frame):
        raise SystemExit(128 + signum)
    previous_handler = signal.signal(signal.SIGTERM, terminated)
    try:
        canonical = Path(args.root).resolve()
        require(canonical.parent.name == '.sdd-runs', 'CLI execution requires .sdd-runs/<run_id>; import old evidence into a new run')
        run_storage.layout(canonical.parent.parent, canonical.name)
        adapter = read_json(args.adapter)
        print(json.dumps(execute(args.root, args.module, args.assignment, args.path_id,
                                 adapter['argv'], args.cwd, args.output, args.timeout or adapter.get('timeout', 300))))
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == '__main__':
    sys.exit(main())
