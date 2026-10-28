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
import context_readiness
import test_validation as tv
import run_storage
import runner_storage
import prepared_tests
from execution_capture import Capture

from contracts import baseline, check_ref, file_ref, read_json, require
from ledger import status, atomic, audit_scope


OUTPUT_DRAIN_TIMEOUT_SECONDS = 2


def finish_timeout(proc, capture):
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
        capture.wait(proc, OUTPUT_DRAIN_TIMEOUT_SECONDS)
        termination['output_drained'] = True
    except subprocess.TimeoutExpired:
        pass  # Already captured bytes remain on disk; never wait for detached writers.
    except (OSError, ValueError) as exc:
        termination['recovery_error'] = type(exc).__name__
    termination['direct_process_exited'] = proc.poll() is not None
    termination['host_stop_required'] = (not termination['output_drained'] or
        not termination['direct_process_exited'] or termination['signal_result'] == 'failed')
    # Pipe EOF is not a general proof that arbitrary detached descendants exited.
    termination['descendants_status'] = 'unknown'
    termination['next_action'] = ('Host verify stop/isolation, then revoke with evidence; retain runner temp'
                                  if termination['host_stop_required'] else 'interpret timeout receipt')
    return termination


INIT = b'''def runner = new File(System.getenv('SDD_RUNNER_DIR'))
gradle.beforeProject { p ->
    def key = java.security.MessageDigest.getInstance('SHA-256').digest(p.projectDir.canonicalPath.bytes).encodeHex().toString()
    def outputs = new File(runner, 'outputs/' + key)
    p.layout.buildDirectory.set(outputs)
    p.afterEvaluate {
        if (!p.layout.buildDirectory.get().asFile.canonicalFile.toPath().startsWith(runner.canonicalFile.toPath())) {
            throw new GradleException('Build output escapes SDD runner; configure buildDirectory under SDD_RUNNER_DIR')
        }
    }
    if (System.getenv('SDD_UNIT_REPORTS_REQUIRED') == '1') {
        p.tasks.withType(org.gradle.api.tasks.testing.Test).configureEach { task ->
            task.outputs.upToDateWhen { false }
            task.outputs.cacheIf { false }
            task.reports.junitXml.required.set(true)
        }
    }
}
'''


def redirected(env):
    """Send every project's build directory into the runner directory `env` names: its Gradle home carries the init
    script, so a Gradle started with this environment builds outside the target tree. Returns the script."""
    init = Path(env['GRADLE_USER_HOME']) / 'init.d/sdd-storage.init.gradle'
    run_storage.atomic_bytes(init, INIT)
    return init


def selfcheck(argv, cwd, output, root=None, module_id=None, path_id=None):
    """A build or test run a role makes for itself, under the storage policy of an official execution: nothing it
    builds lands in the tree it builds. It leaves a note (selfcheck.json: command, exit code, times, log; for a frozen
    unit PATH the state of each required test) and no receipt: a note is no result, but two notes of one PATH, failing
    before a task's code and passing after it, are that task's red evidence."""
    out = Path(output).resolve()
    require(argv and Path(cwd).is_dir(), 'argv/cwd required')
    require(not out.exists() and not out.is_relative_to(Path(cwd).resolve()), 'self-check output must be a new directory outside the tree it builds')
    path, m = None, None
    if path_id:
        require(root and module_id, 'a note of a PATH needs the run root and the module')
        m = status(Path(root).resolve())['modules'][module_id]
        path = next((p for p in m['plan']['paths'] if p['path_id'] == path_id), None)
        require(path and path.get('kind') == 'unit' and path.get('unit_report'), 'a self-check note names a frozen unit PATH')
    out.mkdir(parents=True)
    env = runner_storage.environment(out)
    redirected(env)
    if path:
        env['SDD_UNIT_REPORTS_REQUIRED'] = '1'
    started = datetime.now(timezone.utc).isoformat()
    with (out / 'selfcheck.log').open('wb') as log:
        code = subprocess.run(runner_storage.build_command(argv, out, unit_report=bool(path)), cwd=cwd, env=env,
                              stdout=log, stderr=subprocess.STDOUT).returncode
    note = {'schema_version': 1, 'producer': 'author-selfcheck', 'argv': list(argv), 'cwd': str(Path(cwd).resolve()),
            'exit_code': code, 'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'log_ref': file_ref(out / 'selfcheck.log')}
    if path:
        import unit_reports
        import xml.etree.ElementTree as ET
        seen = {}
        for pattern in path['unit_report']['patterns']:
            for report in sorted(out.glob(pattern)):
                try:
                    seen.update({row['test_id']: row['status'] for row in unit_reports.parse(report)})
                except (ValueError, ET.ParseError):
                    pass
        note.update(module_id=module_id, path_id=path_id, freeze_id=m['freeze_id'],
                    required={tid: seen.get(tid, 'missing') for tid in path['unit_report']['required_test_ids']})
    atomic(out / 'selfcheck.json', note)
    return code


def builtin_main(platform, root):
    """The package's own Main for a device platform the project states without an adapter: the Harmony kernel drives
    android and harmony, web_main a browser."""
    package = Path(__file__).resolve().parents[2]
    env = Path(root) / 'runs/harmony/sandbox/environment'
    python = package / 'migration-test/runtime/harmony/.venv/bin/python'
    python = str(python) if python.is_file() else sys.executable
    if platform == 'web':
        return {'argv': [python, str(package / 'migration-test/scripts/web_main.py'), '--root', str(root),
                         *(['--config', str(env / 'web.json')] if (env / 'web.json').is_file() else [])], 'timeout_seconds': 600}
    files = [arg for name in ('config.json', '.env') if (env / name).is_file()
             for arg in ('--config' if name == 'config.json' else '--env-file', str(env / name))]
    return {'argv': [python, str(package / 'migration-test/runtime/harmony/sandbox.py'), 'test', '--root', str(root),
                     '--platform', platform, *files], 'timeout_seconds': 1860}


def adapter_for(s, path, root):
    """What runs a PATH when the host names nothing: build, unit and in-process functional PATHs have their frozen command;
    a device PATH runs the adapter the project states for its platform (test_adapter.adapters), else the project's one
    adapter. `{run_root}` in a stated argv is this run."""
    if path.get('command'):
        return {'argv': list(path['command']['argv']), 'cwd': path['command']['cwd'], 'timeout': path['command'].get('timeout_seconds') or 300}
    adapter = s.get('test_adapter') or {}
    platform = path.get('platform')
    row = (adapter.get('adapters') or {}).get(platform)
    if row is None and adapter.get('executable'):
        row = {'argv': [adapter['executable'], *adapter.get('args', [])], 'cwd': adapter.get('cwd'), 'timeout_seconds': adapter.get('timeout_seconds')}
    if row is None and platform in ((adapter.get('device') or {}).get('platforms') or []):
        row = builtin_main(platform, root)
    require(row, 'no adapter runs platform ' + str(platform) + ' PATHs: state test_adapter.adapters.' + str(platform) + ' in the project context, or pass --adapter')
    return {'argv': [a.replace('{run_root}', str(root)) for a in row['argv']], 'cwd': (row.get('cwd') or s['target_root']).replace('{run_root}', str(root)),
            'timeout': row.get('timeout_seconds') or 300}


def execute(root, module_id, assignment_id, path_id, argv=None, cwd=None, output=None, timeout=None):
    """One approved execution. `path_id` names one PATH, or several unit PATHs that froze the same command: those run
    once, and each gets its own receipt and JUnit attribution out of the one run (a list of receipt references).
    With no `argv` the command is resolved from the frozen PATH or the project's adapters (`adapter_for`)."""
    require(output, 'output required')
    root = Path(root).resolve()
    s = status(root)
    pids = [path_id] if isinstance(path_id, str) else list(path_id)
    require(pids and len(set(pids)) == len(pids), 'path_id required, each once')
    batch = len(pids) > 1
    path_id = pids[0]
    import integration
    if module_id == 'GLOBAL' and (integration.task(s) or {}).get('assignment_id') == assignment_id:
        a = integration.task(s)
        m = integration.scope(s)
        require(all(pid in a['path_ids'] for pid in pids), 'path outside the integration assignment')
    elif module_id == 'GLOBAL':
        require(all(tv.available(m) for m in s['modules'].values()), 'audit modules no longer ready')
        m = audit_scope(s)
        a = s.get('audit_test_assignment', {})
        require(not s.get('audit_assignment', {}).get('closed', True), 'host-task audit inactive')
        require(not a.get('closed', True) and a.get('assignment_id') == assignment_id and a.get('snapshot') ==
                {k:v['code_baseline'] for k,v in s['modules'].items()}, 'audit assignment required')
        require(a.get('scope_policy') == 'non-green-only', 'legacy full audit assignment; revoke and reassign')
        require(all(pid in a.get('path_ids', []) for pid in pids), 'path outside collected audit scope')
    else:
        m = s['modules'][module_id]
        a = m['assignments'][assignment_id]
        require(not a['closed'] and (a['role'] == 'test-runner' and m['phase'] == 'testing'), 'test assignment required')
        require(a.get('execution_contract'), 'assignment execution contract missing; revoke and reassign')
    if a.get('execution_contract'):
        require(all(pid in a['execution_contract']['path_ids'] for pid in pids), 'execution outside assigned PATHs')
    planned = {p['path_id']: p for p in m['plan']['paths']}
    paths = [planned[pid] for pid in pids]
    path = paths[0]
    if batch:
        require(all(p.get('kind') in ('unit', 'automation') and p.get('unit_report') for p in paths), 'a batch runs unit or in-process functional PATHs with JUnit reports')
        require(all((p['command']['argv'], str(Path(p['command']['cwd']).resolve())) ==
                    (path['command']['argv'], str(Path(path['command']['cwd']).resolve())) for p in paths),
                'a batch runs PATHs that froze the same command')
    if argv is None:  # the host named no command: the frozen one, or the run's adapter for the PATH's platform
        chosen = adapter_for(s, path, root)
        argv, cwd, timeout = chosen['argv'], cwd or chosen['cwd'], timeout or chosen['timeout']
    timeout = timeout or 300
    for pid in pids:
        context_readiness.check_execution(s, a, argv, cwd, pid)
    require(baseline(m['code_files']) == m['code_baseline'], 'code changed before execution')
    bindings = {pid: prepared_tests.binding(m, p) for pid, p in zip(pids, paths)}
    require(not batch or all(a['kind'] == 'test-source' for b in bindings.values() for a in (b or {}).get('assets', [])),
            'a batch carries no prepared test assets other than frozen test sources')
    test_binding = bindings[path_id]
    prepared = (test_binding or {}).get('assets', [])
    sources = {pid: prepared_tests.frozen_sources(b) for pid, b in bindings.items()}
    for row in {r['path']: r for rows in sources.values() for r in rows}.values():  # what the freeze wrote lands in the target verbatim
        require(Path(row['path']).is_file() and file_ref(Path(row['path']))['sha256'] == row['sha256'],
                'frozen test source missing or changed at ' + row['path'])
    is_build = path.get('kind') in ('build', 'unit') or bool(path.get('kind') == 'automation' and path.get('unit_report'))  # a frozen, host-bound command
    if tv.split(m) and module_id != 'GLOBAL':
        kind = path.get('kind') or 'automation'
        if a.get('role') == 'test-runner':
            # The build assignment runs build, unit and static in turn; their order is judged when the result is submitted.
            # A functional dispatch may carry the static closure ahead of its paths; that order too is judged on submit.
            reviewed = a.get('test_scope') == 'automation' and tv.review_first(m)
            require(kind in tv.PRE if a.get('test_scope') == 'build' else a.get('test_scope') == kind or reviewed and kind == 'static',
                    'path outside test assignment scope')
            require(kind != 'visual' or tv.functional_ready(m), 'functional tests must pass before visual')
        else:
            reviewed = False
            require(kind == 'build' or tv.build_ready(m), 'build must pass before automation')
            require(kind != 'static' or tv.unit_ready(m), 'unit tests must pass before the static review')
        require(kind in tv.PRE or reviewed or tv.static_ready(m), 'static spec review must pass before automation')
    if is_build:
        require(argv == path['command']['argv'] and str(Path(cwd).resolve()) == str(Path(path['command']['cwd']).resolve()), 'build command differs from frozen plan')
        timeout = max(p['command']['timeout_seconds'] for p in paths)
    out = run_storage.test_output(root, s, output)
    if run_storage.for_state(root, s) or root.parent.name == '.sdd-runs':
        run_storage.checked_path(out, Path(root) / ('runs/build' if is_build else 'runs/harmony/automation'))
    require(not out.exists(), 'execution output must be new')
    command = runner_storage.build_command(argv, out, unit_report=bool(path.get('unit_report'))) if is_build else [*argv, '--query-file', str(out / 'query.json'), '--result-file', str(out / 'result.json')]
    require(command and argv and Path(cwd).is_dir(), 'argv/cwd required')
    out.mkdir(parents=True)
    execution_env = runner_storage.environment(out)
    execution_env['SDD_TEST_QUERY_FILE'] = str(out / 'query.json')
    execution_env['SDD_TEST_ASSET_USAGE_FILE'] = str(out / 'test-assets-used.json')
    # Retain the output policy; cache flags must be set before Gradle starts. A path whose own script calls the build
    # inherits this environment, so what it builds lands in the runner too, not in the target tree.
    init = redirected(execution_env) if not is_build or runner_storage.gradle_command(argv) else None
    if path.get('unit_report'):
        execution_env['SDD_UNIT_REPORTS_REQUIRED'] = '1'
    test_run_id = str(uuid.uuid4())  # the run; in a batch every PATH keeps its own id under it
    run_ids = {pid: str(uuid.uuid4()) if batch else test_run_id for pid in pids}
    named = lambda stem, pid: stem + ('.' + pid if batch else '') + '.json'
    query = {**path, 'run_id': s['run_id'], 'module_id': module_id,
             'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'], 'execution_contract_version': 2}
    if path.get('kind', 'automation') == 'automation' and path.get('platform') in ('android', 'harmony'):
        query['step_contract_version'] = 1
    if prepared: query['frozen_test_assets'] = prepared
    if test_binding: query['test_asset_binding'] = test_binding
    if path.get('unit_report'):
        query.update(assignment_id=assignment_id, test_run_id=run_ids[path_id])
    queries = {path_id: query, **{pid: {**p, 'run_id': s['run_id'], 'module_id': module_id, 'freeze_id': m['freeze_id'],
                                        'code_baseline': m['code_baseline'], 'execution_contract_version': 2,
                                        'assignment_id': assignment_id, 'test_run_id': run_ids[pid],
                                        **({'frozen_test_assets': bindings[pid]['assets'], 'test_asset_binding': bindings[pid]} if bindings[pid] else {})}
                                  for pid, p in zip(pids[1:], paths[1:])}}
    if path.get('kind') == 'static':
        query['unit_tests_present'] = bool(tv.paths(m, 'unit'))
        query['scenario_requirement_ids'] = sorted({r for t in m['plan']['tasks'] for r in t['requirement_ids']})
        if m.get('scenario_index'):
            query['scenario_index'] = m['scenario_index']
            query['scenario_ids'] = sorted(row['scenario_id'] for row in m['scenario_index'])
    if path.get('kind') in ('automation', 'visual'):
        import ui_fidelity
        interaction = ui_fidelity.frozen_interaction(m, path)
        if interaction:
            query['frozen_interaction'] = interaction
        import reference_media
        pictures = reference_media.assertion_refs(s, path)  # the user's screenshot an assertion compares against, by hash
        if pictures:
            query['expected_assertions'] = [{**a, 'reference_media_ref': pictures[a['assertion_id']]} if a.get('assertion_id') in pictures else a
                                            for a in query.get('expected_assertions') or []]
        if path.get('kind') == 'visual':
            import visual_evidence
            query['frozen_visual_evidence'] = visual_evidence.frozen_evidence(m, path)
            query['frozen_image_checks'] = ui_fidelity.frozen_image_checks(m, path)
            query['run_root'] = str(root)
            query['execution_assignment'] = {'assignment_id': a['assignment_id'],
                                             'fencing_token': a.get('fencing_token')}
    for pid in pids:
        atomic(out / named('query', pid), queries[pid])
    execution_env['SDD_TEST_QUERY_FILE'] = str(out / named('query', path_id))
    started = datetime.now(timezone.utc).isoformat()
    termination, proc, aborted = None, None, None
    capture = Capture(out, {
        'run_id': s['run_id'], 'module_id': module_id, 'assignment_id': assignment_id,
        'actor_instance_id': a['instance_id'], 'test_run_id': test_run_id, 'path_id': ','.join(pids),
        'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline']})
    note = ''
    try:
        # An agentic adapter can spawn media/tools processes; stop the whole attempt.
        proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, env=execution_env)
        capture.attach(proc)
        try:
            capture.wait(proc, timeout)
            exit_code = proc.returncode
            if exit_code < 0 or exit_code == 124:
                termination = finish_timeout(proc, capture)
                note = 'Adapter interrupted: ' + json.dumps(termination)
        except subprocess.TimeoutExpired:
            termination = finish_timeout(proc, capture)
            exit_code, note = 124, 'Host timeout: ' + json.dumps(termination)
    except BaseException as exc:
        if proc is None and isinstance(exc, OSError):
            exit_code, note = 127, f'Adapter launch failed: {exc}'
        else:
            # Record cancellation, then re-raise it after persisting the receipt.
            # It must not be converted into an automatic retry or a successful run.
            aborted = exc
            termination = {'host_stop_required': True, 'direct_process_exited': False,
                           'descendants_status': 'unknown'}
            if proc is not None:
                try:
                    termination = finish_timeout(proc, capture)
                except BaseException as recovery_error:
                    # A second interruption must never make cleanup assume exit.
                    termination['recovery_error'] = type(recovery_error).__name__
            termination.update(executor_aborted=True, exception_type=type(exc).__name__,
                               next_action='Host review cancellation and stop/isolation evidence; revoke; no automatic restart')
            exit_code = (exc.code if isinstance(exc, SystemExit) and type(exc.code) is int and exc.code != 0
                         else 130 if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 125)
            note = 'Executor aborted: ' + json.dumps(termination)
    finally:
        try:
            capture.finish('interrupted' if aborted else 'timeout' if exit_code == 124 else
                           'launch-failed' if proc is None else 'finished', exit_code,
                           not aborted and termination is None and proc is not None, note)
        finally:
            capture.close()
            if proc is not None:
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None: stream.close()
        def cleanup(directory):
            if termination and termination['host_stop_required']:
                return {'path': str(directory / 'temp'), 'status': 'retained-in-run',
                        'reason': 'process-stop-unconfirmed; Host stop/isolation verification required'}
            if termination and directory == out / 'harmony':
                return {'path': str(directory / 'temp'), 'status': 'retained-in-run',
                        'reason': 'interrupted-mobile-attempt; retain raw recording for diagnosis'}
            return runner_storage.cleanup(directory)
        scratch = cleanup(out)
        # Nested Harmony owns its temp normally; SIGKILL prevents its finally.
        nested = []
        if (out / 'harmony/temp').exists():
            nested.append(cleanup(out / 'harmony'))
        atomic(out / 'cleanup.json', {'scratch': scratch, 'nested': nested})
    if path.get('unit_report'):
        import unit_reports
        for pid in pids:
            atomic(out / named('result', pid), unit_reports.collect(queries[pid], out, started, exit_code))
    elif is_build:
        quality = 'green-passed' if exit_code == 0 else 'yellow-blocked' if aborted or exit_code in (124, 127) else 'red-bug'
        cause = None
        if exit_code != 0:
            # The status first; on a failure the locations grepped from the log, not the log, are what the repair reads.
            # Every location inside the module's write scope is a code defect where it broke: confirmed, no diagnosis needed.
            import failures
            located, rows = failures.write(out / 'execution.log', out / 'failures.json')
            ours = quality == 'red-bug' and failures.inside(rows, m.get('write_paths') or [])
            cause = {'category': 'tooling' if aborted or exit_code in (124, 127) else 'code' if path.get('kind') == 'unit' or ours else 'build',
                     'summary': ('Unit tests' if path.get('kind') == 'unit' else 'Build') + ' exit ' + str(exit_code) + '; ' + failures.summary(rows),
                     'confidence': 'confirmed' if ours else 'observed', 'owner': module_id, 'next_action': 'fix' if ours else 'diagnose',
                     'evidence_refs': [file_ref(out / 'execution.log'), *([file_ref(located)] if located else [])],
                     **({'failures_ref': file_ref(located)} if located else {})}
        atomic(out / 'result.json', {'producer': 'build-executor',
            'build_artifacts': [file_ref(run_storage.checked_path(f, out)) for f in sorted(out.rglob('*'))
                                if f.is_file() and f.suffix.lower() in ('.hap', '.hsp', '.apk')], 'quality': quality,
            'assertions': [{'assertion_id': path['expected_assertions'][0]['assertion_id'], 'expected': 0,
                            'actual': exit_code, 'passed': exit_code == 0}],
            'root_cause': cause})
    finished = datetime.now(timezone.utc).isoformat()
    shared = {'schema_version': 1, 'producer': 'host-executor', 'execution_contract_version': 2, 'run_id': s['run_id'],
              'module_id': module_id, 'assignment_id': assignment_id, 'actor_instance_id': a['instance_id'],
              'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
              'argv': command, 'cwd': str(Path(cwd).resolve()), 'started_at': started,
              'requested_argv': argv, 'storage_command_version': 1, 'finished_at': finished, 'exit_code': exit_code,
              'capture': capture.references(), 'cleanup_ref': file_ref(out / 'cleanup.json'),
              'storage_policy_ref': file_ref(init) if init else None, 'log_ref': file_ref(out / 'execution.log'),
              **({'batch': {'path_ids': pids, 'test_run_id': test_run_id}} if batch else {})}
    receipts = []
    for pid in reversed(pids):  # the first PATH's receipt is finished below with what only a single run records
        receipt = {**shared, 'path_id': pid, 'test_run_id': run_ids[pid], 'query_ref': file_ref(out / named('query', pid)),
                   'result_ref': file_ref(out / named('result', pid)) if (out / named('result', pid)).is_file() else None,
                   'frozen_test_sources': sources[pid]}
        if termination:
            receipt['termination'] = termination
        if pid != path_id and bindings[pid]:
            usage_file = run_storage.checked_path(out / 'test-assets-used.json', out)
            receipt.update(test_asset_binding=bindings[pid], test_asset_usage=prepared_tests.usage(bindings[pid], argv, usage_file),
                           test_asset_usage_ref=file_ref(usage_file) if usage_file.is_file() else None)
        if pid != path_id:
            atomic(out / named('receipt', pid), receipt)
            receipts.insert(0, file_ref(out / named('receipt', pid)))
    if test_binding:
        usage_file = run_storage.checked_path(out / 'test-assets-used.json', out)
        receipt.update(test_asset_binding=test_binding,
            test_asset_usage=prepared_tests.usage(test_binding, argv, usage_file),
            test_asset_usage_ref=file_ref(usage_file) if usage_file.is_file() else None)
    if not is_build:
        for observations in (out / 'harmony/observations.json', out / 'observations.json'):
            if observations.is_file():
                run_storage.checked_path(observations, out)
                receipt['partial_observations_ref'] = file_ref(observations)
                break
        for name, key in [('step-trace.json', 'partial_step_trace_ref'), ('interruption.json', 'interruption_ref')]:
            artifact = out / 'harmony' / name
            if artifact.is_file():
                run_storage.checked_path(artifact, out)
                receipt[key] = file_ref(artifact)
    atomic(out / named('receipt', path_id), receipt)
    receipts.insert(0, file_ref(out / named('receipt', path_id)))
    if aborted is not None:
        raise aborted
    # Result acceptance rechecks the baseline and active assignment after the subprocess.
    return receipts if batch else receipts[0]


def main():
    if sys.argv[1:2] == ['selfcheck']:  # execute_test.py selfcheck --cwd <tree> --output <new dir> -- <command...>
        parser = argparse.ArgumentParser(prog='execute_test.py selfcheck', description=selfcheck.__doc__)
        parser.add_argument('--cwd', required=True); parser.add_argument('--output', required=True)
        for arg in ('root', 'module', 'path-id'):
            parser.add_argument('--' + arg, help='together: note the state of the frozen unit PATH\'s required tests')
        parser.add_argument('command', nargs=argparse.REMAINDER)
        args = parser.parse_args(sys.argv[2:])
        try:
            return selfcheck([arg for arg in args.command if arg != '--'], args.cwd, args.output, args.root, args.module, args.path_id)
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('root', 'module', 'assignment', 'path-id', 'output'):
        parser.add_argument('--' + arg, required=True, help='several unit PATHs of one frozen command: a,b,c' if arg == 'path-id' else None)
    parser.add_argument('--adapter', help='explicit {argv, timeout}; otherwise the frozen command or the project adapter of the PATH platform runs')
    parser.add_argument('--cwd', help='working directory; otherwise the frozen command cwd or the target project')
    parser.add_argument('--timeout', type=int)
    args = parser.parse_args()
    def terminated(signum, frame):
        raise SystemExit(128 + signum)
    previous_handler = signal.signal(signal.SIGTERM, terminated)
    try:
        canonical = Path(args.root).resolve()
        require(canonical.parent.name == '.sdd-runs', 'CLI execution requires .sdd-runs/<run_id>; import old evidence into a new run')
        run_storage.layout(canonical.parent.parent, canonical.name)
        adapter = read_json(args.adapter) if args.adapter else None
        pids = [pid for pid in args.path_id.split(',') if pid]
        print(json.dumps(execute(args.root, args.module, args.assignment, pids if len(pids) > 1 else args.path_id,
                                 adapter['argv'] if adapter else None, args.cwd, args.output, args.timeout or (adapter or {}).get('timeout'))))
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == '__main__':
    sys.exit(main())
