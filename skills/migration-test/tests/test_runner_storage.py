"""Runner storage under success, failure, abrupt termination and SDK overrides."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / 'migration-ledger/scripts'
sys.path.insert(0, str(SCRIPTS))
from runner_storage import harmony_output, environment, cleanup, scope
from contracts import Rejected


class RunnerStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / '.sdd-runs/run-one'
        self.out = self.root / 'runs/harmony/automation/M001-attempt-1'

    def test_standalone_and_workflow_share_boundary_and_reject_cross_run(self):
        self.assertEqual(harmony_output(None, self.out), self.out)
        self.assertEqual(harmony_output(self.root, self.out), self.out)
        for p in (self.base / 'outside', self.root / 'staging/draft',
                  self.base / '.sdd-runs/run-two/runs/harmony/automation/a'):
            with self.assertRaises(Rejected): harmony_output(self.root, p)
        self.out.parent.mkdir(parents=True)
        self.out.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(Rejected): harmony_output(self.root, self.out / 'result.json')

    def test_exception_cleans_scratch_preserves_evidence_and_restores_host(self):
        old_cwd, old_env, old_temp = Path.cwd(), dict(os.environ), tempfile.tempdir
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with scope(self.out):
                with tempfile.NamedTemporaryFile(delete=False) as f:
                    f.write(b'temporary screenshot')
                    self.assertTrue(Path(f.name).is_relative_to(self.out / 'temp'))
                (self.out / 'evidence.json').write_text('{}')
                self.assertEqual(Path.cwd(), self.out)
                raise RuntimeError('fixture')
        self.assertFalse((self.out / 'temp').exists())
        self.assertTrue((self.out / 'evidence.json').exists())
        self.assertEqual(json.loads((self.out / 'cleanup.json').read_text())['status'], 'removed')
        self.assertEqual((Path.cwd(), dict(os.environ), tempfile.tempdir), (old_cwd, old_env, old_temp))

    def test_killed_runner_leaves_only_owned_scratch_and_cleanup_is_local(self):
        sibling = self.out.parent / 'other-attempt/temp'; sibling.mkdir(parents=True)
        (sibling / 'keep').write_text('another worker')
        env = environment(self.out)
        script = "import tempfile,os,signal;f=tempfile.NamedTemporaryFile(delete=False);f.write(b'pending');f.close();os.kill(os.getpid(),signal.SIGKILL)"
        result = subprocess.run([sys.executable, '-c', script], env=env, cwd=self.out)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(list((self.out / 'temp').iterdir()))
        self.assertEqual(cleanup(self.out)['status'], 'removed')
        self.assertEqual((sibling / 'keep').read_text(), 'another worker')

    def test_cleanup_failure_is_retained_in_run_with_reason(self):
        environment(self.out)
        with patch('runner_storage.shutil.rmtree', side_effect=PermissionError('fixture')):
            result = cleanup(self.out)
        self.assertEqual(result['status'], 'retained-in-run')
        self.assertEqual(result['reason'], 'PermissionError')
        self.assertTrue((self.out / 'temp').is_dir())

    def test_sdk_environment_cannot_redirect_to_external_directory(self):
        outside = self.base / 'unmanaged'
        with patch.dict(os.environ, {'HYPIUM_MCP_OUTPUT_DIR': str(outside), 'HYPIUM_MCP_WORKING_DIR': str(outside)}):
            with scope(self.out):
                subprocess.run([sys.executable, '-c',
                    "from hypium_mcp.config.config import get_config;from hypium_mcp.utils.log import get_logger;get_logger().info('fixture');print(get_config().output_dir)"],
                    check=True, capture_output=True)
        self.assertFalse(outside.exists())
        self.assertTrue(list((self.out / 'sdk').glob('*.log')))

    def test_device_lease_survives_cross_process_contention_and_releases_on_kill(self):
        from harmony_adapter import device_lock
        adapter_scripts = Path(__file__).resolve().parents[1] / 'scripts'
        script = (f'import sys;sys.path.insert(0,{str(adapter_scripts)!r});'
                  'from harmony_adapter import device_lock;import time\n'
                  "with device_lock('kill-fixture','localhost',9971):\n print('ready',flush=True);time.sleep(30)\n")
        worker = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(worker.stdout.readline().strip(), 'ready')
            with self.assertRaisesRegex(ValueError, 'lease unavailable'):
                with device_lock('kill-fixture', 'localhost', 9971): pass
        finally:
            worker.kill(); worker.communicate(timeout=5)
        with device_lock('kill-fixture', 'localhost', 9971): pass


if __name__ == '__main__': unittest.main()
