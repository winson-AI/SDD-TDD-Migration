"""Closure gate: a real prepared run verifies; a hand-written run fails fail-closed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ledger
import test_ledger
import verify_openspec
from simulate_storage import simulate


class VerifyOpenspecTests(unittest.TestCase):
    def temp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, d, ignore_errors=True)
        return Path(d)

    def codes(self, run_root):
        return {item['check'] for item in verify_openspec.verify(run_root)}

    def test_real_prepared_run_verifies(self):
        out = self.temp() / 'sim'
        simulate(out)
        workspace = out / 'workspace'
        # Completed run and the planning-only second run both went through prepare+init.
        self.assertEqual(verify_openspec.verify(workspace / '.sdd-runs/demo'), [])
        self.assertEqual(verify_openspec.verify(workspace / '.sdd-runs/demo-next'), [])

    def test_hand_written_run_without_ledger_fails(self):
        # Reproduces the observed bypass: sdd dirs and a stub openspec, but no events.jsonl.
        ws = self.temp() / 'workspace'
        run = ws / '.sdd-runs/run-x'
        (run / 'ledger').mkdir(parents=True)
        (run / 'ledger/module-registry.json').write_text(json.dumps({'run_id': 'run-x', 'status': 'initialized'}))
        (run / 'openspec/changes/run-x-m010').mkdir(parents=True)
        codes = self.codes(run)
        self.assertIn('events-journal', codes)

    def test_missing_top_level_openspec_when_context_bound(self):
        # A real run whose top-level hub was deleted must not pass.
        out = self.temp() / 'sim'
        simulate(out)
        workspace = out / 'workspace'
        (workspace / 'openspec/runs/demo/workflow.md').unlink()
        self.assertIn('workflow-hub', self.codes(workspace / '.sdd-runs/demo'))

    def test_missing_change_manifest_fails(self):
        out = self.temp() / 'sim'
        simulate(out)
        workspace = out / 'workspace'
        (workspace / 'openspec/changes/demo-m001/manifest.json').unlink()
        self.assertIn('change-manifest', self.codes(workspace / '.sdd-runs/demo'))

    def test_hand_written_report_without_projection_json_fails(self):
        # P2.2: a prose migration-report.md without the projected JSON is not real.
        out = self.temp() / 'sim'
        simulate(out)
        workspace = out / 'workspace'
        (workspace / '.sdd-runs/demo/reports/migration-report.json').unlink()
        self.assertIn('migration-report', self.codes(workspace / '.sdd-runs/demo'))

    def test_off_layout_root_rejected(self):
        self.assertIn('managed-layout', self.codes(self.temp()))

    def test_status_reports_top_level_binding_for_prepared_run(self):
        # P2.1: a prepared run reports its OpenSpec projecting at the top level.
        out = self.temp() / 'sim'
        simulate(out)
        binding = ledger.status(out / 'workspace/.sdd-runs/demo')['openspec_binding']
        self.assertTrue(binding['bound'])
        self.assertEqual(binding['location'], 'top-level')

    def test_status_flags_in_run_fallback_for_unprepared_run(self):
        # P2.1: an unprepared run no longer hides that OpenSpec fell back inside the run.
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        binding = ledger.status(f.root)['openspec_binding']
        self.assertFalse(binding['bound'])
        self.assertEqual(binding['location'], 'in-run-fallback')
        self.assertTrue(binding['note'])


if __name__ == '__main__':
    unittest.main()
