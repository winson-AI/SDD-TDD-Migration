"""Real process termination, receipt acceptance and audit build failure routing."""
import copy
import json
import os
from pathlib import Path
import sys
import signal
import subprocess
import time
import unittest
from unittest.mock import patch

import test_ledger
import test_split_testing
from contracts import Rejected, digest, file_ref
from execute_test import execute
from harmony_stage import build


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_split_testing.SplitTestingTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = f = t.f
        original = f.plan
        def plan():
            p = original()
            p['paths'][0].update(steps=['verify fixture'], expected_assertions=[{
                'assertion_id': 'A1', 'expected': True, 'description': 'fixture is correct',
                'verification': 'one_image_assert', 'matcher': 'exact', 'after_step': 1}])
            return p
        f.plan = plan; t.prepare(); t.compile()

    def run_fault(self, body):
        f = self.f
        script = f.base / 'fault.py'; f.test_argv = [sys.executable, str(script)]
        a = f.assign('test-runner', 'AUTO')
        scripts = str(Path(__file__).resolve().parents[2] / 'migration-test/scripts')
        script.write_text(f'''import argparse,json,time,sys
from pathlib import Path
sys.path.insert(0,{scripts!r})
from harmony_contract import ObservationSink,write
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
q=json.loads(Path(a.query_file).read_text());out=Path(a.result_file).parent
s=ObservationSink(q,out);media=out/'evidence.txt';media.write_text('fixture observation')
''' + body)
        out = f.base / '.sdd-runs/fixture/runs/harmony/automation/attempt'
        rr = execute(f.root, 'M001', 'AUTO', 'P1', f.test_argv, str(f.target), out, timeout=1)
        return a, rr, out

    def accept(self, a, result):
        self.f.submit(result, a); self.f.call('accept', {'assignment_id': 'AUTO'})
        self.assertTrue(self.f.state()['modules']['M001']['assignments']['AUTO']['closed'])

    def test_completed_failure_survives_timeout_and_cannot_be_deferred(self):
        a, rr, out = self.run_fault("s.record('[ASSERT:A1]',False,'mismatch','one_image_assert',[media]);write(a.result_file,s.report());time.sleep(30)\n")
        raw = (out / 'result.json').read_bytes()
        result = build(self.f.root, 'M001', 'AUTO', [rr]); row = result['paths'][0]
        self.assertEqual(row['quality'], 'red-bug'); self.assertTrue(row['executed'])
        self.assertIn('Host exit 124', row['root_cause']['summary'])
        self.assertEqual(row['root_cause']['category'], 'behavior')
        self.assertIs(row['assertions'][0]['actual'], False)
        self.accept(a, result)
        with self.assertRaisesRegex(Rejected, 'cannot conceal'): self.t.defer()
        self.assertEqual((out / 'result.json').read_bytes(), raw)

    def test_partial_failed_observation_without_result_survives_timeout(self):
        a, rr, out = self.run_fault("s.record('[ASSERT:A1]',False,'mismatch','one_image_assert',[media]);s.record('[ASSERT:A1]',True,'retry matches','one_image_assert',[media]);time.sleep(30)\n")
        self.assertFalse((out / 'result.json').exists())
        result = build(self.f.root, 'M001', 'AUTO', [rr]); row = result['paths'][0]
        self.assertEqual(row['quality'], 'yellow-blocked'); self.assertTrue(row['executed'])
        self.assertIs(row['assertions'][0]['actual'], False)
        self.assertTrue(row['flaky'])
        self.accept(a, result)
        with self.assertRaisesRegex(Rejected, 'cannot conceal'): self.t.defer()

    def test_success_report_followed_by_timeout_never_becomes_green(self):
        a, rr, out = self.run_fault("s.record('[ASSERT:A1]',True,'matches','one_image_assert',[media]);write(a.result_file,s.report());time.sleep(30)\n")
        result = build(self.f.root, 'M001', 'AUTO', [rr])
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        forged = copy.deepcopy(result); forged['paths'][0]['quality'] = 'green-passed'
        with self.assertRaises(Rejected): self.f.submit(forged, a)
        self.accept(a, result)

    def test_truncated_json_becomes_accepted_yellow_and_closes_assignment(self):
        a, rr, out = self.run_fault("Path(a.result_file).write_text('{\"producer\":');raise SystemExit(2)\n")
        raw = (out / 'result.json').read_bytes()
        result = build(self.f.root, 'M001', 'AUTO', [rr])
        self.assertIn('JSONDecodeError', result['paths'][0]['root_cause']['summary'])
        self.assertFalse(result['paths'][0]['executed'])
        forged = copy.deepcopy(result); forged['paths'][0].pop('execution_receipt')
        with self.assertRaisesRegex(Rejected, 'host completion receipt required'): self.f.submit(forged, a)
        self.accept(a, result); self.t.defer()
        self.assertEqual(self.f.state()['modules']['M001']['phase'], 'automation-deferred')
        self.assertEqual((out / 'result.json').read_bytes(), raw)

    def test_wrong_json_shape_is_a_format_error(self):
        a, rr, _ = self.run_fault("write(a.result_file,['not','a','report']);raise SystemExit(2)\n")
        result = build(self.f.root, 'M001', 'AUTO', [rr])
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        self.accept(a, result)

    def test_format_fallback_still_rejects_receipt_identity_or_hash_change(self):
        a, rr, out = self.run_fault("Path(a.result_file).write_text('{');raise SystemExit(2)\n")
        result = build(self.f.root, 'M001', 'AUTO', [rr])
        receipt = json.loads(Path(rr['path']).read_text()); receipt['assignment_id'] = 'FOREIGN'
        wrong = self.f.ref('foreign.json', receipt)
        with self.assertRaises(Rejected): build(self.f.root, 'M001', 'AUTO', [wrong])
        (out / 'result.json').write_text('changed after receipt')
        with self.assertRaises(Rejected): build(self.f.root, 'M001', 'AUTO', [rr])
        with self.assertRaises(Rejected): self.f.submit(result, a)

    def test_recovered_observation_media_is_rechecked_on_acceptance(self):
        a, rr, out = self.run_fault("s.record('[ASSERT:A1]',False,'mismatch','one_image_assert',[media]);time.sleep(30)\n")
        result = build(self.f.root, 'M001', 'AUTO', [rr])
        (out / 'evidence.txt').write_text('tampered')
        with self.assertRaises(Rejected): self.f.submit(result, a)

    def test_detached_pipe_holder_returns_bounded_receipt_and_requires_host_stop(self):
        pid_path = self.f.base / 'detached.pid'
        try:
            start = time.monotonic()
            with patch('execute_test.OUTPUT_DRAIN_TIMEOUT_SECONDS', 0.2):
                a, rr, out = self.run_fault(f'''import subprocess
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
Path({str(pid_path)!r}).write_text(str(child.pid))
(out/'temp/keep.txt').write_text('still owned by attempt')
(out/'harmony/temp').mkdir(parents=True)
(out/'harmony/temp/keep.txt').write_text('nested scratch')
print('partial stdout',flush=True);print('partial stderr',file=sys.stderr,flush=True)
s.record('[ASSERT:A1]',False,'observed failure','one_image_assert',[media]);write(a.result_file,s.report())
time.sleep(30)
''')
            self.assertLess(time.monotonic() - start, 5)
            receipt = json.loads(Path(rr['path']).read_text())
            self.assertEqual(receipt['exit_code'], 124)
            self.assertTrue(receipt['termination']['host_stop_required'])
            self.assertTrue(receipt['termination']['direct_process_exited'])
            self.assertFalse(receipt['termination']['output_drained'])
            log = (out / 'execution.log').read_text()
            self.assertIn('partial stdout', log); self.assertIn('partial stderr', log)
            self.assertTrue((out / 'temp/keep.txt').exists())
            self.assertTrue((out / 'harmony/temp/keep.txt').exists())
            cleanup = json.loads((out / 'cleanup.json').read_text())
            self.assertEqual(cleanup['scratch']['status'], 'retained-in-run')
            self.assertEqual(cleanup['nested'][0]['status'], 'retained-in-run')
            result = build(self.f.root, 'M001', 'AUTO', [rr])
            self.assertEqual(result['paths'][0]['quality'], 'red-bug')
            with self.assertRaisesRegex(Rejected, 'process stop unconfirmed'): self.f.submit(result, a)
            self.assertFalse(self.f.state()['modules']['M001']['assignments']['AUTO']['closed'])
            os.kill(int(pid_path.read_text()), signal.SIGKILL); pid_path.unlink()
            self.f.call('revoke', {'assignment_id': 'AUTO', 'stopped_worker_ref':
                self.f.ref('stop-detached.md', 'Fixture child terminated; attempt isolated')}, role='host')
            self.assertTrue(self.f.state()['modules']['M001']['assignments']['AUTO']['closed'])
        finally:
            if pid_path.exists():
                try: os.kill(int(pid_path.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def test_normal_group_timeout_drains_output_cleans_temp_and_accepts(self):
        a, rr, out = self.run_fault("print('before timeout',flush=True);time.sleep(30)\n")
        receipt = json.loads(Path(rr['path']).read_text())
        self.assertTrue(receipt['termination']['output_drained'])
        self.assertFalse(receipt['termination']['host_stop_required'])
        self.assertFalse((out / 'temp').exists())
        self.assertIn('before timeout', (out / 'execution.log').read_text())
        self.accept(a, build(self.f.root, 'M001', 'AUTO', [rr]))

    def interrupted_attempt(self, error, detached=False):
        marker = self.f.base / 'interrupt-ready'; pid_file = self.f.base / 'interrupt-child'
        processes = []; original = subprocess.Popen
        def spawn(*args, **kwargs):
            process = original(*args, **kwargs); communicate = process.communicate
            processes.append((process, communicate))
            def interrupted(*args, **kwargs):
                process.communicate = communicate  # The subsequent bounded drain is real.
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
                if not marker.exists(): raise RuntimeError('fixture did not start')
                raise error
            process.communicate = interrupted
            return process
        body = f'''import subprocess
(out/'temp/keep').write_text('active scratch')
'''
        if detached:
            body += f"child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)\nPath({str(pid_file)!r}).write_text(str(child.pid))\n"
        body += f"print('before interrupt',flush=True)\nPath({str(marker)!r}).write_text('ready')\ntime.sleep(30)\n"
        try:
            start = time.monotonic()
            with patch('execute_test.subprocess.Popen', side_effect=spawn), \
                    patch('execute_test.OUTPUT_DRAIN_TIMEOUT_SECONDS', .2), self.assertRaises(type(error)):
                self.run_fault(body)
            self.assertLess(time.monotonic() - start, 5)
            out = self.f.base / '.sdd-runs/fixture/runs/harmony/automation/attempt'
            receipt = json.loads((out / 'receipt.json').read_text())
            self.assertTrue(receipt['termination']['executor_aborted'])
            self.assertEqual(receipt['termination']['exception_type'], type(error).__name__)
            self.assertEqual(receipt['termination']['host_stop_required'], detached)
            self.assertEqual((out / 'temp/keep').exists(), detached)
            self.assertIn('before interrupt', (out / 'execution.log').read_text())
            self.assertIsNotNone(processes[0][0].poll())
            result = build(self.f.root, 'M001', 'AUTO', [file_ref(out / 'receipt.json')])
            a = self.f.state()['modules']['M001']['assignments']['AUTO']
            with self.assertRaisesRegex(Rejected, 'executor aborted'): self.f.submit(result, a)
            self.assertFalse(self.f.state()['modules']['M001']['assignments']['AUTO']['closed'])
            return receipt
        finally:
            if pid_file.exists():
                try: os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass
            for process, communicate in processes:
                if process.poll() is None: os.killpg(process.pid, signal.SIGKILL)
                communicate(timeout=3)

    def test_keyboard_interrupt_stops_attempt_records_receipt_and_propagates(self):
        self.assertEqual(self.interrupted_attempt(KeyboardInterrupt())['exit_code'], 130)

    def test_runtime_io_error_is_not_misreported_as_launch_failure(self):
        self.assertEqual(self.interrupted_attempt(OSError('fixture I/O fault'))['exit_code'], 125)

    def test_system_exit_retains_host_cancellation_code(self):
        self.assertEqual(self.interrupted_attempt(SystemExit(143))['exit_code'], 143)

    def test_interruption_with_detached_writer_retains_scratch(self):
        self.interrupted_attempt(KeyboardInterrupt(), detached=True)


class CliCancellationTests(unittest.TestCase):
    def test_sigterm_stops_attempt_and_persists_cancellation_before_cli_exit(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        root = f.base / '.sdd-runs/demo'; root.parent.mkdir(); f.root.rename(root); f.root = root
        f.prepare(); f.implementation(); f.assign('test-runner', 'CLI-AUTO')
        out = root / 'runs/harmony/automation/cancel'
        adapter = f.base / 'cancel-adapter.py'
        adapter.write_text("import os,time\nfrom pathlib import Path\np=Path(os.environ['SDD_RUNNER_DIR']);(p/'pid').write_text(str(os.getpid()))\nprint('ready',flush=True)\ntime.sleep(30)\n")
        config = f.ref('cli-adapter.json', {'argv': [sys.executable, str(adapter)], 'timeout': 30})
        script = Path(__file__).resolve().parents[1] / 'scripts/execute_test.py'
        runner = subprocess.Popen([sys.executable, '-B', str(script), '--root', str(root), '--module', 'M001',
            '--assignment', 'CLI-AUTO', '--path-id', 'P1', '--adapter', config['path'], '--cwd', str(f.target),
            '--output', str(out)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not (out / 'pid').exists() and runner.poll() is None and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue((out / 'pid').exists())
            runner.send_signal(signal.SIGTERM)
            _, stderr = runner.communicate(timeout=5)
            self.assertEqual(runner.returncode, 143, stderr)
            receipt = json.loads((out / 'receipt.json').read_text())
            self.assertEqual(receipt['exit_code'], 143)
            self.assertTrue(receipt['termination']['executor_aborted'])
            self.assertTrue(receipt['termination']['direct_process_exited'])
            self.assertFalse((out / 'temp').exists())
            self.assertFalse(f.state()['modules']['M001']['assignments']['CLI-AUTO']['closed'])
        finally:
            if runner.poll() is None: runner.kill()
            runner.communicate(timeout=5)
            if (out / 'pid').exists():
                try: os.killpg(int((out / 'pid').read_text()), signal.SIGKILL)
                except ProcessLookupError: pass


class AuditBuildTests(unittest.TestCase):
    def prepare_audit(self, failing=True, peer=False, timeout=False):
        t = test_split_testing.SplitTestingTests(); t.setUp(); self.addCleanup(t.doCleanups); f = t.f
        if failing:
            t.build_code = "from pathlib import Path; raise SystemExit(0 if '2' in Path('m1/code.py').read_text() else 1)"
        if timeout:
            t.build_timeout = 1
            t.build_code = "import time; from pathlib import Path; time.sleep(0 if '2' in Path('m1/code.py').read_text() else 30)"
        if peer:
            f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm2')]},
                   role='global-orchestrator', module=None)
        t.prepare(); t.compile()
        cause = {'category': 'environment', 'summary': 'service absent', 'confidence': 'confirmed', 'owner': 'host', 'next_action': 'verify'}
        if peer:
            p = f.plan(); p['module_id'] = 'M002'
            for path in p['paths']: path['path_id'] += '-M2'
            p['tasks'][0]['path_ids'] = [path['path_id'] for path in p['paths']]
            f.call('plan', {'plan_ref': f.ref('peer.json', p)}, role='spec-designer', module='M002')
            f.call('decision', {'decision_id': 'D2', 'module_id': 'M002', 'decision': 'approved',
                'subject_sha256': digest(p), 'human_source_ref': f.ref('approve.md', 'Approved fixture')}, role='host', module=None)
            f.call('freeze', {'decision_id': 'D2'}, module='M002'); f.implement('M002', 'I2')
            f.raw('audit-defer', {'root_cause': cause, 'evidence_ref': f.ref('peer-env.md', 'Service absent')}, module='M002')
        f.raw('audit-defer', {'root_cause': cause, 'evidence_ref': f.ref('env.md', 'Service absent')})
        test_ledger.code_review(f)
        f.raw('audit-collect', {'batch_id': 'A1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = f.state()['audit_batch']; routes = []
        for fid, finding in b['findings'].items():
            mid = finding['source_module_id']; owners = ['M001'] if mid == 'M001' else []
            routes.append({'finding_id': fid, 'source_module_id': mid, 'action': 'fix' if owners else 'verify',
                'owner_module_ids': owners, 'source_context': b['contexts'][mid],
                'owner_contexts': {owner: b['contexts'][owner] for owner in owners},
                'root_cause': cause, 'analysis_ref': f.ref('analysis.md', 'SPEC and paths reviewed')})
        f.call('audit-plan', {'plan_ref': f.ref('audit-plan.json', {'routes': routes})}, role='auditor', module=None)
        f.raw('audit-route-batch', {'review_ref': f.ref('route.md', 'Existing scope')}, role='global-orchestrator', module=None)
        f.raw('audit-work'); f.implementation('fixer', 'AUDITFIX')
        return t, f

    def test_audit_build_failure_reports_cause_for_human(self):
        t, f = self.prepare_audit(); t.compile('AUDITBUILD'); s = f.state()
        self.assertEqual(s['audit_batch']['status'], 'awaiting-human')
        self.assertEqual(s['modules']['M001']['phase'], 'waiting-human')
        self.assertEqual(s['audit_batch']['human_report']['reason'], 'build-verification-failed')
        self.assertEqual(s['audit_batch']['human_report']['root_causes'][0]['category'], 'build')
        self.assertEqual(s['modules']['M001']['fix_memory'][0]['status'], 'failed')
        self.assertFalse(s['audit_batch']['owner_tests'])
        self.assertNotEqual(s['next_steps'][0]['operation'], 'audit-defer')

    def test_successful_audit_build_still_requires_automation(self):
        t, f = self.prepare_audit(failing=False); t.compile('AUDITBUILD'); s = f.state()
        self.assertEqual(s['audit_batch']['status'], 'repairing')
        self.assertFalse(s['audit_batch']['owner_tests'])
        self.assertEqual(s['next_steps'][0]['test_scope'], 'automation')

    def test_audit_build_timeout_is_human_failure_not_automation_omission(self):
        t, f = self.prepare_audit(timeout=True); t.compile('AUDITBUILD'); s = f.state()
        self.assertEqual(s['modules']['M001']['results']['B1']['quality'], 'yellow-blocked')
        self.assertEqual(s['audit_batch']['status'], 'awaiting-human')
        self.assertEqual(s['audit_batch']['human_report']['root_causes'][0]['category'], 'tooling')
        self.assertFalse(s['audit_batch'].get('automation_deferred'))

    def test_failed_build_does_not_stop_independent_audit_branch(self):
        t, f = self.prepare_audit(peer=True); before = copy.deepcopy(f.state()['modules']['M002'])
        t.compile('AUDITBUILD'); s = f.state()
        self.assertEqual(s['audit_batch']['blocked_modules'], ['M001'])
        self.assertEqual(s['modules']['M002'], before)
        step = next(x for x in s['next_steps'] if x['module_id'] == 'M002')
        self.assertEqual(step['operation'], 'audit-retest'); self.assertTrue(step['ready'])
        f.raw('audit-retest', module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'], 'testing')
