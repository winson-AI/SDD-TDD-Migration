"""Live visibility, bounded pipe draining and retained evidence after a hard executor kill."""
import concurrent.futures
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from execution_capture import Capture, observe
from contracts import Rejected


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / '.sdd-runs/demo'
        self.out = self.root / 'runs/build/attempt'; self.out.mkdir(parents=True)
        self.identity = {'run_id': 'demo', 'module_id': 'M001', 'assignment_id': 'A1', 'test_run_id': 'T1'}

    def test_logs_are_visible_before_process_exit_and_stream_offsets_are_exact(self):
        release = self.out / 'release'
        program = ("import os,time;from pathlib import Path;os.write(1,b'first stdout');os.write(2,b'first stderr');"
                   f"p=Path({str(release)!r})\nwhile not p.exists(): time.sleep(.01)\n")
        proc = subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        capture = Capture(self.out, self.identity); capture.attach(proc)
        try:
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                future = pool.submit(capture.wait, proc, 4)
                try:
                    deadline = time.monotonic() + 3
                    while not all((self.out / (s + '.log')).stat().st_size for s in ('stdout', 'stderr')) and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertIsNone(proc.poll())
                    self.assertEqual((self.out / 'stdout.log').read_bytes(), b'first stdout')
                    self.assertEqual((self.out / 'stderr.log').read_bytes(), b'first stderr')
                    self.assertFalse(json.loads((self.out / 'execution-state.json').read_text())['output_complete'])
                finally:
                    release.touch()
                future.result(timeout=5)
            capture.finish('finished', proc.returncode, True)
            events = [json.loads(s) for s in (self.out / 'output-events.jsonl').read_text().splitlines()]
            self.assertEqual({e['stream'] for e in events}, {'stdout', 'stderr'})
            self.assertTrue(all(e['at'] and e['offset'] == 0 for e in events))
        finally:
            capture.close()
            if proc.poll() is None: proc.kill()
            proc.wait(); proc.stdout.close(); proc.stderr.close()

    def test_large_binary_output_does_not_deadlock_and_preserves_exact_bytes(self):
        program = "import os\nfor i in range(64):\n os.write(1,b'x'*16384);os.write(2,b'\\xff'*16384)\n"
        proc = subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        capture = Capture(self.out, self.identity); capture.attach(proc)
        try:
            capture.wait(proc, 5); capture.finish('finished', proc.returncode, True)
            self.assertEqual((self.out / 'stdout.log').read_bytes(), b'x' * 1048576)
            self.assertEqual((self.out / 'stderr.log').read_bytes(), b'\xff' * 1048576)
            self.assertEqual(capture.state['bytes'], {'stdout': 1048576, 'stderr': 1048576})
        finally:
            capture.close()
            if proc.poll() is None: proc.kill()
            proc.wait(); proc.stdout.close(); proc.stderr.close()

    def test_hard_killed_executor_leaves_live_bytes_and_incomplete_marker(self):
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        program = (f'import sys;sys.path.insert(0,{str(scripts)!r})\n'
                   'from execution_capture import Capture\nimport subprocess\n'
                   f'c=Capture({str(self.out)!r},{self.identity!r})\n'
                   "p=subprocess.Popen([sys.executable,'-c',\"print('durable',flush=True);import time;time.sleep(30)\"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)\n"
                   'c.attach(p);c.wait(p,30)\n')
        outer = subprocess.Popen([sys.executable, '-B', '-c', program])
        child = None
        try:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                log = self.out / 'stdout.log'
                if log.exists() and log.stat().st_size: break
                time.sleep(.01)
            outer.kill(); outer.wait(timeout=3)
            state = json.loads((self.out / 'execution-state.json').read_text()); child = state['pid']
            self.assertIn(b'durable', log.read_bytes())
            self.assertEqual(state['status'], 'running'); self.assertFalse(state['output_complete'])
            self.assertFalse((self.out / 'receipt.json').exists())
        finally:
            if outer.poll() is None: outer.kill(); outer.wait()
            if child:
                try: os.killpg(child, signal.SIGKILL)
                except ProcessLookupError: pass

    def test_observation_rejects_wrong_identity_and_path_escape(self):
        capture = Capture(self.out, self.identity); capture.close()
        path = self.out / 'execution-state.json'
        self.assertEqual(observe(self.root, path, self.identity)['status'], 'running')
        with self.assertRaisesRegex(Rejected, 'identity'):
            observe(self.root, path, {'module_id': 'M002'})
        with self.assertRaisesRegex(Rejected, 'boundary'):
            observe(self.root / 'other', path, self.identity)
        redirect = self.root / 'runs/redirect'; redirect.symlink_to(self.out, target_is_directory=True)
        with self.assertRaisesRegex(Rejected, 'symlink'):
            observe(self.root, redirect / 'execution-state.json', self.identity)
        path.write_text('[]')
        with self.assertRaisesRegex(Rejected, 'invalid execution observation'):
            observe(self.root, path, self.identity)
