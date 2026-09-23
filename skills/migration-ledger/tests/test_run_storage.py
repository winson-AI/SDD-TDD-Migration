"""Storage location, restart, output ownership and full lifecycle contracts."""
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_project_context
import project_context as pc
import ledger
import run_storage
from contracts import Rejected, file_ref
from simulate_storage import simulate, inventory


class RunStorageTests(unittest.TestCase):
    def fixture(self):
        f = test_project_context.ProjectContextTests(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def test_cli_default_creates_three_sibling_roots_and_hub(self):
        f = self.fixture()
        req = f.base / 'request.json'; req.write_text(json.dumps(f.run_request()))
        actor = f.base / 'actor.json'; actor.write_text(json.dumps(f.actor))
        result = subprocess.run([sys.executable, pc.__file__, 'prepare', '--root', str(f.root),
            '--request', str(req), '--host-context', str(actor)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        prepared = json.loads(result.stdout)
        self.assertEqual(prepared['run_root'], str(f.run))
        self.assertEqual(pc.current(f.root)['config']['workspace_root'], str(f.base))
        f.start(f.init_payload(prepared)); status = ledger.status(f.run)
        hub = Path(status['openspec_hub']['json'])
        self.assertEqual(hub, f.base / 'openspec/runs/r1/workflow.json')
        self.assertFalse((f.run / 'openspec').exists())
        self.assertEqual(json.loads(hub.read_text())['routing']['global_next_step'], status['global_next_step'])
        hub.unlink(); ledger.status(f.run); self.assertTrue(hub.exists())

    def test_ledger_projection_ignores_old_temp_link_and_rejects_redirected_destination(self):
        f = self.fixture(); f.start(f.init_payload(f.prepare()))
        outside = f.base / 'external.txt'; outside.write_text('unchanged')
        output = f.run / 'ledger/global.json'
        output.with_name('global.json.tmp').symlink_to(outside)
        ledger.status(f.run)
        self.assertEqual(outside.read_text(), 'unchanged')
        self.assertFalse(output.is_symlink())
        output.unlink(); output.symlink_to(outside)
        before = (f.run / 'ledger/events.jsonl').read_bytes()
        status = ledger.status(f.run)
        self.assertEqual(status['projection']['status'], 'pending')
        self.assertIn('symlink', str(status['projection']['errors']))
        self.assertTrue(status['workflow_progress']['notify_user'])
        self.assertEqual(outside.read_text(), 'unchanged')
        self.assertEqual((f.run / 'ledger/events.jsonl').read_bytes(), before)

    def test_ledger_journal_and_artifact_links_cannot_redirect_writes(self):
        f = self.fixture(); f.start(f.init_payload(f.prepare()))
        journal = f.run / 'ledger/events.jsonl'
        outside = f.base / 'journal'; journal.rename(outside); journal.symlink_to(outside)
        before = outside.read_bytes()
        with self.assertRaisesRegex(Rejected, 'symlink'): ledger.status(f.run)
        self.assertEqual(outside.read_bytes(), before)
        journal.unlink(); outside.rename(journal)
        outside_dir = f.base / 'external-artifacts'; outside_dir.mkdir()
        shutil.rmtree(f.run / 'artifacts')
        (f.run / 'artifacts').symlink_to(outside_dir, target_is_directory=True)
        with self.assertRaisesRegex(Rejected, 'symlink'):
            ledger.preserve_refs(f.run, file_ref(f.source))
        self.assertEqual(list(outside_dir.iterdir()), [])

    def test_linked_context_never_uses_redirected_temp_or_view(self):
        f = self.fixture()
        (f.base / 'knowledge.md').write_text('architecture details')
        f.arch.write_text('[knowledge](knowledge.md)')
        files = f.run / 'context/files'
        first = pc.copy_ref(files, file_ref(f.arch)); view = Path(first['path'])
        view.unlink()
        outside = f.base / 'external.txt'; outside.write_text('unchanged')
        view.with_suffix('.tmp').symlink_to(outside)
        second = pc.copy_ref(files, file_ref(f.arch))
        self.assertEqual(first, second)
        self.assertTrue(Path(second['path']).is_relative_to(files))
        self.assertEqual(outside.read_text(), 'unchanged')
        self.assertFalse(view.is_symlink())
        view.unlink(); view.symlink_to(outside)
        with self.assertRaisesRegex(Rejected, 'symlink'): pc.copy_ref(files, file_ref(f.arch))
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_copied_run_rejected_before_projection_events_or_diagnostics_change(self):
        f = self.fixture(); payload = f.init_payload(f.prepare()); f.start(payload)
        clone = f.base / '.sdd-runs/copied'; shutil.copytree(f.run, clone)
        (clone / 'ledger/global.json').write_text('preserve copied projection')
        before = inventory(f.base)
        with self.assertRaisesRegex(Rejected, 'different run root'): ledger.status(clone)
        with self.assertRaisesRegex(Rejected, 'different run root'): f.start(payload, root=clone)
        self.assertEqual(inventory(f.base), before)
        self.assertEqual(ledger.status(f.run)['run_id'], 'r1')

    def test_prepare_retry_preserves_snapshot_and_registry_after_config_update(self):
        f = self.fixture(); first = pc.prepare(f.root, None, f.run_request(), f.actor)
        before = inventory(f.run); index = (f.root / 'runs/r1.json').read_bytes()
        pc.update(f.root, f.request('update', 1, {'human_owner': 'new-owner'}), f.actor)
        again = pc.prepare(f.root, None, f.run_request(), f.actor)
        self.assertTrue(again['duplicate']); self.assertEqual(first['project_context_ref'], again['project_context_ref'])
        self.assertEqual(before, inventory(f.run)); self.assertEqual(index, (f.root / 'runs/r1.json').read_bytes())
        with self.assertRaisesRegex(Rejected, 'different root'):
            pc.prepare(f.root, f.base / 'duplicate', f.run_request(), f.actor)
        self.assertFalse((f.base / 'duplicate').exists())

    def test_prepare_unregistered_copy_cannot_poison_index_and_original_can_recover(self):
        f = self.fixture(); first = f.prepare()
        clone = f.base / 'restored-copy'; shutil.copytree(f.run, clone)
        index = f.root / 'runs/r1.json'; index.unlink()
        (f.root / 'preparations/r1.json').unlink()
        before = inventory(f.base)
        with self.assertRaisesRegex(Rejected, 'different run root'):
            pc.prepare(f.root, clone, f.run_request(), f.actor)
        self.assertFalse(index.exists())
        self.assertEqual(inventory(f.base), before)
        recovered = f.prepare()
        self.assertTrue(recovered['duplicate'])
        self.assertEqual(recovered['project_context_ref'], first['project_context_ref'])
        self.assertEqual(recovered['run_root'], recovered['input']['run_root'])
        self.assertEqual(json.loads(index.read_text())['run_root'], str(f.run))
        before = inventory(f.base)
        self.assertTrue(pc.prepare(f.root, None, f.run_request(), f.actor)['duplicate'])
        self.assertEqual(inventory(f.base), before)

    def test_prepare_recovers_unregistered_legacy_snapshot_at_original_location(self):
        f = self.fixture(); prepared = f.prepare()
        snapshot = pc.verify_snapshot(prepared['project_context_ref'])
        (f.root / 'runs/r1.json').unlink(); (f.root / 'preparations/r1.json').unlink()
        legacy_root = f.base / 'legacy-runs/r1'; legacy_root.parent.mkdir()
        # Construct a pre-layout fixture; production recovery must not rewrite it.
        shutil.move(str(f.run), legacy_root)
        snapshot.pop('storage_layout'); snapshot.pop('storage_owner_ref')
        snapshot = json.loads(json.dumps(snapshot).replace(str(f.run), str(legacy_root)))
        data = pc.encoded(snapshot)
        pc.archive(legacy_root / 'context/files', data, '.snapshot')
        pc.atomic(legacy_root / 'context/snapshot.json', data)
        before = inventory(legacy_root)
        restored = pc.prepare(f.root, legacy_root, f.run_request(), f.actor)
        self.assertTrue(restored['duplicate'])
        self.assertEqual(restored['run_root'], str(legacy_root))
        self.assertEqual(restored['input']['run_root'], str(legacy_root))
        self.assertIsNone(restored['input']['storage_layout'])
        self.assertEqual(inventory(legacy_root), before)
        self.assertFalse(f.run.exists())
        self.assertTrue(pc.prepare(f.root, None, f.run_request(), f.actor)['duplicate'])
        self.assertEqual(inventory(legacy_root), before)

    def test_new_roots_cannot_escape_or_be_overridden_per_run(self):
        f = self.fixture()
        for path in (f.base / 'outside', f.base / 'openspec/migrations/r1'):
            with self.assertRaisesRegex(Rejected, 'new run root'):
                pc.prepare(f.root, path, f.run_request(), f.actor)
            self.assertFalse(path.exists())
        with self.assertRaisesRegex(Rejected, 'project-owned'):
            pc.prepare(f.root, None, f.run_request(overrides={'workspace_root': str(f.base / 'elsewhere')}), f.actor)
        outside = f.base / 'outside'; outside.mkdir(); (f.base / '.sdd-runs').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(Rejected, 'symlink'):
            pc.prepare(f.root, None, f.run_request(), f.actor)

    def test_existing_foreign_openspec_change_is_not_overwritten(self):
        f = self.fixture(); foreign = f.base / 'openspec/changes/r1-m001/proposal.md'
        foreign.parent.mkdir(parents=True); foreign.write_text('preexisting user document')
        with self.assertRaisesRegex(Rejected, 'owned run namespace'):
            pc.prepare(f.root, None, f.run_request(), f.actor)
        self.assertEqual(foreign.read_text(), 'preexisting user document')
        self.assertFalse((f.run / 'context/snapshot.json').exists())
        self.assertFalse(f.run.exists())

    def test_missing_prepare_input_creates_no_runtime_assets(self):
        f = self.fixture(); f.arch.unlink()
        with self.assertRaises((Rejected, OSError)):
            f.prepare()
        self.assertFalse(f.run.exists())
        self.assertFalse((f.base / 'openspec').exists())
        self.assertFalse((f.root / 'preparations/r1.json').exists())

    def test_interrupted_prepare_has_receipt_and_can_resume(self):
        f = self.fixture()
        with patch.object(pc, 'copy_ref', side_effect=OSError('simulated freeze interruption')):
            with self.assertRaisesRegex(OSError, 'interruption'): f.prepare()
        receipt = f.root / 'preparations/r1.json'
        self.assertEqual(json.loads(receipt.read_text())['phase'], 'failed')
        self.assertTrue((f.base / 'openspec/runs/r1/owner.json').is_file())
        self.assertFalse((f.root / 'runs/r1.json').exists())
        result = f.prepare()
        self.assertFalse(result['duplicate'])
        self.assertTrue((f.root / 'runs/r1.json').is_file())
        record = json.loads(receipt.read_text())
        self.assertEqual(record['phase'], 'prepared')
        self.assertIn('interruption', record['failures'][0]['reason'])
        before = inventory(f.base)
        self.assertTrue(f.prepare()['duplicate'])
        self.assertEqual(inventory(f.base), before)

    def test_auxiliary_outputs_require_this_runs_staging(self):
        f = self.fixture(); f.prepare()
        self.assertEqual(run_storage.staging_output(f.run, f.run / 'staging/test-runner/new/result.json'),
                         f.run / 'staging/test-runner/new/result.json')
        for path in (f.base / 'out', f.run / 'context/bad.json', f.base / '.sdd-runs/r2/staging/bad.json'):
            with self.assertRaisesRegex(Rejected, 'boundary'): run_storage.staging_output(f.run, path)
        (f.run / 'staging').mkdir()
        (f.run / 'staging/link').symlink_to(f.base, target_is_directory=True)
        with self.assertRaisesRegex(Rejected, 'symlink'):
            run_storage.staging_output(f.run, f.run / 'staging/link/out')

    def source_fixture(self):
        import test_source_changes
        f = test_source_changes.SourceChangeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def test_interrupted_projection_recovers_committed_plan_without_manifest(self):
        import openspec_projection as projection
        f = self.source_fixture()
        original = projection.write
        def interrupt(path, content):
            if path.name == 'design.md': raise OSError('simulated projection interruption')
            return original(path, content)
        with patch.object(projection, 'write', side_effect=interrupt):
            f.freeze('M001')
            state = ledger.status(f.f.root)
            self.assertEqual(state['projection']['status'], 'pending')
            self.assertIn('interruption', str(state['projection']['errors']))
        change = f.f.base / 'openspec/changes/demo-m001'
        self.assertTrue((change / 'proposal.md').exists())
        self.assertFalse((change / 'manifest.json').exists())
        before = (f.f.root / 'ledger/events.jsonl').read_bytes()
        state = ledger.status(f.f.root)
        self.assertIsNotNone(state['modules']['M001']['plan'])
        self.assertTrue((change / 'specs/m001/spec.md').is_file())
        self.assertTrue((change / 'manifest.json').is_file())
        self.assertEqual(before, (f.f.root / 'ledger/events.jsonl').read_bytes())

    def test_nested_projection_symlink_does_not_write_or_delete_outside(self):
        import shutil
        f = self.source_fixture(); f.freeze('M001')
        change = f.f.base / 'openspec/changes/demo-m001'
        nested = change / 'specs/m001'
        shutil.rmtree(nested)
        outside = f.f.base / 'outside'; outside.mkdir()
        sentinel = outside / 'spec.md'; sentinel.write_text('user-owned content')
        nested.symlink_to(outside, target_is_directory=True)
        state = ledger.status(f.f.root)
        self.assertEqual(state['projection']['status'], 'pending')
        self.assertIn('symlink', str(state['projection']['errors']))
        self.assertEqual(sentinel.read_text(), 'user-owned content')
        nested.unlink()
        ledger.status(f.f.root)
        self.assertTrue((nested / 'spec.md').is_file())

    def test_projection_does_not_follow_file_or_predictable_temp_symlinks(self):
        import openspec_projection as projection
        f = self.fixture()
        outside = f.base / 'external'; outside.write_text('unchanged')
        output = f.base / 'view.md'; output.symlink_to(outside)
        with self.assertRaisesRegex(Rejected, 'symlink'): projection.write(output, 'bad')
        output.unlink()
        output.with_name('view.md.tmp').symlink_to(outside)
        projection.write(output, 'new view')
        self.assertEqual(output.read_text(), 'new view')
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_managed_test_output_stays_inside_own_run(self):
        f = self.fixture(); result = f.prepare(); f.start(f.init_payload(result)); state = ledger.status(f.run)
        self.assertEqual(run_storage.test_output(f.run, state, f.run / 'runs/attempt-1'), f.run / 'runs/attempt-1')
        for path in (f.base / 'outside', f.run / 'ledger', f.base / '.sdd-runs/r2/runs/a'):
            with self.assertRaisesRegex(Rejected, 'inside this run'):
                run_storage.test_output(f.run, state, path)
        (f.run / 'runs').mkdir(); (f.run / 'runs/escape').symlink_to(f.base, target_is_directory=True)
        with self.assertRaisesRegex(Rejected, 'inside this run'):
            run_storage.test_output(f.run, state, f.run / 'runs/escape/out')

    def test_legacy_unprepared_run_keeps_existing_openspec_location(self):
        import test_ledger
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups); f.prepare()
        self.assertIsNone(run_storage.for_state(f.root, f.state()))
        self.assertTrue((f.root / 'openspec/changes/demo-m001/status.md').exists())

    def test_full_lifecycle_restart_and_new_run_preserve_first_run(self):
        original = ledger.apply
        polls = []
        def poll_active_fix(root, request, actor):
            if request['operation'] == 'submit' and actor['role'] == 'fixer':
                step = next(x for x in ledger.status(root)['next_steps'] if x['module_id'] == request['module_id'])
                self.assertEqual(step['operation'], 'await-result')
                polls.append(step)
            return original(root, request, actor)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ledger, 'apply', side_effect=poll_active_fix):
                summary = simulate(Path(tmp) / 'simulation')
            self.assertEqual(len(polls), 1)
            self.assertEqual(summary['first_run_quality'], 'green-passed')
            self.assertEqual(summary['changes']['same_run_restart'], {'added': [], 'removed': [], 'modified': []})
            changes = summary['changes']['new_run_start']
            self.assertFalse(changes['removed'])
            self.assertIn('.sdd-migration/project-context.json', changes['modified'])
            self.assertIn('.sdd-runs/demo-next/context/snapshot.json', changes['added'])
            self.assertIn('openspec/runs/demo-next/workflow.md', changes['added'])


if __name__ == '__main__': unittest.main()
