"""Closure gate: a real prepared run verifies; a hand-written run fails fail-closed."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ledger
import test_ledger
import verify_openspec
from simulate_storage import simulate
import test_source_changes
import openspec_projection
import workflow_hub


_SIMULATION = {}


def simulated():
    """One simulated run serves every test here; a test that removes a file restores it when it ends."""
    if 'output' not in _SIMULATION:
        temp = tempfile.TemporaryDirectory()
        _SIMULATION.update(temp=temp, output=Path(temp.name).resolve() / 'sim')
        simulate(_SIMULATION['output'])
    return _SIMULATION['output']


def tearDownModule():
    if 'temp' in _SIMULATION:
        _SIMULATION.pop('temp').cleanup()
        _SIMULATION.clear()


def remove(case, path):
    path = Path(path)
    before = path.read_bytes()
    case.addCleanup(path.write_bytes, before)
    path.unlink()


class VerifyOpenspecTests(unittest.TestCase):
    def temp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, d, ignore_errors=True)
        return Path(d)

    def codes(self, run_root):
        return {item['check'] for item in verify_openspec.verify(run_root)}

    def test_real_prepared_run_verifies(self):
        workspace = simulated() / 'workspace'
        # Completed run and the planning-only second run both went through prepare+init.
        self.assertEqual(verify_openspec.verify(workspace / '.sdd-runs/demo'), [])
        self.assertEqual(verify_openspec.verify(workspace / '.sdd-runs/demo-next'), [])
        self.assertEqual(verify_openspec.verify(workspace / '.sdd-runs/demo', 'final'), [])

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
        workspace = simulated() / 'workspace'
        remove(self, workspace / 'openspec/runs/demo/workflow.md')
        self.assertIn('workflow-hub', self.codes(workspace / '.sdd-runs/demo'))

    def test_missing_change_manifest_fails(self):
        workspace = simulated() / 'workspace'
        remove(self, workspace / 'openspec/changes/demo-m001/manifest.json')
        self.assertIn('change-manifest', self.codes(workspace / '.sdd-runs/demo'))

    def test_hand_written_report_without_projection_json_fails(self):
        # P2.2: a prose migration-report.md without the projected JSON is not real.
        workspace = simulated() / 'workspace'
        remove(self, workspace / '.sdd-runs/demo/reports/migration-report.json')
        self.assertIn('migration-report', self.codes(workspace / '.sdd-runs/demo'))

    def test_off_layout_root_rejected(self):
        self.assertIn('managed-layout', self.codes(self.temp()))

    def test_status_reports_top_level_binding_for_prepared_run(self):
        # P2.1: a prepared run reports its OpenSpec projecting at the top level.
        binding = ledger.status(simulated() / 'workspace/.sdd-runs/demo')['openspec_binding']
        self.assertTrue(binding['bound'])
        self.assertEqual(binding['location'], 'top-level')

    def test_status_flags_in_run_fallback_for_unprepared_run(self):
        # P2.1: an unprepared run no longer hides that OpenSpec fell back inside the run.
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        binding = ledger.status(f.root)['openspec_binding']
        self.assertFalse(binding['bound'])
        self.assertEqual(binding['location'], 'in-run-fallback')
        self.assertTrue(binding['note'])


class ScopedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_source_changes.SourceChangeTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f
        self.fixture.freeze('M001'); self.fixture.freeze('M002')
        self.f.state()
        self.root = self.f.root
        self.change = self.f.base / 'openspec/changes/demo-m001'

    def check(self, scope='module', mid='M001'):
        return verify_openspec.inspect(self.root, scope, mid if scope == 'module' else None)

    def test_scoped_check_ignores_unrelated_missing_spec(self):
        (self.change / 'design.md').unlink()
        broken = self.check()
        self.assertFalse(broken['verified'])
        self.assertEqual(broken['checked_modules'], ['M001', 'M010'])
        self.assertTrue(any(f['check'] == 'change-content' and f['module_id'] == 'M001' for f in broken['failures']))
        self.assertTrue(self.check(mid='M002')['verified'], self.check(mid='M002'))
        self.assertTrue(self.check('global')['verified'])
        self.assertFalse(self.check('projection')['verified'])

    def test_global_check_requires_real_hub_and_its_run_identity(self):
        path = self.f.base / 'openspec/runs/demo/workflow.json'
        value = json.loads(path.read_text())
        path.unlink()
        result = self.check('global')
        self.assertFalse(result['verified'])
        self.assertIn('workflow-hub', {f['check'] for f in result['failures']})
        path.write_text(json.dumps({**value, 'run_id': 'another-run'}))
        self.assertFalse(self.check('global')['verified'])
        self.f.state()
        self.assertTrue(self.check('global')['verified'])

    def test_exact_content_catches_hand_modified_markdown_without_writing(self):
        (self.change / 'proposal.md').write_text('# Claimed completed without approved scope')
        before = {str(p): p.read_bytes() for p in self.f.base.rglob('*') if p.is_file()}
        result = self.check()
        self.assertFalse(result['verified'])
        after = {str(p): p.read_bytes() for p in self.f.base.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn('change-content', {f['check'] for f in result['failures']})
        self.assertNotIn('init', ' '.join(result['next_actions']))
        self.f.state()
        self.assertTrue(self.check()['verified'], self.check())

    def test_stale_manifest_and_status_are_rejected(self):
        path = self.change / 'manifest.json'
        original = json.loads(path.read_text())
        path.write_text(json.dumps({**original, 'sequence': 1}))
        result = self.check()
        self.assertIn('change-manifest', {f['check'] for f in result['failures']})
        path.write_text(json.dumps(original))
        (self.change / 'status.md').write_text('# forged current status')
        self.assertIn('change-content', {f['check'] for f in self.check()['failures']})

    def test_foreign_owner_has_recovery_diagnostic_and_is_not_reclaimed(self):
        path = self.change / 'manifest.json'
        original = json.loads(path.read_text())
        path.write_text(json.dumps({**original, 'module_id': 'FOREIGN'}))
        before = path.read_bytes()
        self.assertFalse(self.check()['verified'])
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(self.check(mid='M002')['verified'])

    def test_peer_event_does_not_require_rewriting_current_module_projection(self):
        original = openspec_projection.write
        blocked = self.change.resolve()
        def skip_module(path, content):
            if Path(path).is_relative_to(blocked):
                raise OSError('fixture peer projection unavailable')
            return original(path, content)
        state, _ = ledger.read_events(self.root)
        request = {'schema_version': 1, 'request_id': 'peer-session', 'run_id': 'demo',
            'module_id': 'M002', 'expected_revision': state['modules']['M002']['revision'],
            'operation': 'session', 'payload': {'role': 'implementer', 'session_id': 'peer-session'}}
        with patch.object(openspec_projection, 'write', side_effect=skip_module):
            ledger.apply(self.root, request, {'role': 'module-orchestrator', 'instance_id': 'mo'})
        self.assertTrue(self.check()['verified'], self.check())
        self.assertFalse(self.check('projection')['verified'])

    def test_parent_allocation_corruption_is_local_to_children(self):
        path = self.root / 'ledger/modules/M010.json'
        data = json.loads(path.read_text()); data['children'] = []
        path.write_text(json.dumps(data))
        result = self.check()
        self.assertFalse(result['verified'])
        self.assertTrue(any(f['check'] == 'module-state' and f['module_id'] == 'M010' for f in result['failures']))
        self.assertTrue(self.check('global')['verified'])

    def test_parent_summary_change_does_not_age_unchanged_allocation(self):
        parent = {'module_id': 'P', 'scope': {'in': ['feature']}, 'children': ['A', 'B'], 'phase': 'coordinating'}
        events = [{'sequence': 1, 'effect': {'module_groups': {'P': parent}}},
                  {'sequence': 2, 'effect': {'module_groups': {'P': {**parent, 'phase': 'waiting-auditor'}}}}]
        self.assertEqual(verify_openspec._module_sequences(events)['P'], 1)

    def test_selected_dependency_closure_excludes_siblings(self):
        state = {'modules': {'A': {'parent_module_id': 'P', 'dependencies': ['B']},
                             'B': {'parent_module_id': 'Q', 'dependencies': ['C']},
                             'C': {'dependencies': []}, 'D': {'dependencies': []}},
                 'module_groups': {'P': {'children': ['A', 'D']}, 'Q': {'children': ['B']}}}
        self.assertEqual(verify_openspec._selected(state, 'A'), {'A', 'B', 'C', 'P', 'Q'})

    def test_projection_is_not_final_delivery_or_real_host_attestation(self):
        self.assertTrue(self.check('projection')['verified'], self.check('projection'))
        final = self.check('final')
        self.assertFalse(final['verified'])
        self.assertIn('delivery-incomplete', {f['check'] for f in final['failures']})
        self.assertIn('not authentic Host dispatch', ' '.join(final['limitations']))

    def test_modified_hub_and_report_are_not_authoritative(self):
        hub = self.f.base / 'openspec/runs/demo/workflow.md'
        hub.write_text('# everything passed')
        report = self.root / 'reports/migration-report.json'
        data = json.loads(report.read_text()); data['report_stage'] = 'completed'
        report.write_text(json.dumps(data))
        result = self.check('projection')
        self.assertTrue({'workflow-hub', 'migration-report'} <= {f['check'] for f in result['failures']})

    def test_global_state_missing_tampered_and_stale_are_detected_globally_only(self):
        path = self.root / 'ledger/global.json'
        original = path.read_bytes()
        for replacement in (None, b'{}', json.dumps({**json.loads(original), 'last_sequence': 1}).encode()):
            with self.subTest(replacement=replacement is None):
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                for scope in ('projection', 'final'):
                    result = self.check(scope)
                    self.assertIn('global-state', {f['check'] for f in result['failures']})
                self.assertTrue(self.check()['verified'], self.check())
                path.write_bytes(original)

    def test_forged_global_routes_cannot_be_verified_by_paired_markdown(self):
        state, events = ledger.read_events(self.root)
        before = copy.deepcopy(state)
        good = ledger.routing(state)
        self.assertEqual(state, before, 'routing must not modify Ledger facts')
        hub = workflow_hub.location(self.root, state)
        corruptions = {
            'global_next_step': {'operation': 'audit-assign', 'ready': True, 'role': 'global-orchestrator'},
            'source_change_next_step': {'operation': 'reconfigure-sources', 'ready': True},
            'module_rounds': {**good['module_rounds'], 'all_settled': True},
        }
        for field, value in corruptions.items():
            with self.subTest(field=field):
                routes = {**good, field: value}
                data, markdown = workflow_hub.render(self.root, state, len(events), routes)
                (hub / 'workflow.json').write_text(json.dumps(data))
                (hub / 'workflow.md').write_text(markdown)
                result = self.check('projection')
                self.assertIn('workflow-hub', {f['check'] for f in result['failures']})
                self.assertTrue(self.check()['verified'], self.check())
        self.f.state()
        self.assertTrue(self.check('projection')['verified'], self.check('projection'))

    def test_damaged_journal_does_not_suggest_reinitialization(self):
        path = self.root / 'ledger/events.jsonl'
        path.write_bytes(path.read_bytes() + b'partial')
        result = self.check('global')
        self.assertFalse(result['verified'])
        self.assertEqual(result['failures'][0]['check'], 'events-integrity')
        self.assertIn('verified backup', result['next_actions'][0])

    def test_invalidated_plan_is_historical_and_read_only_check_allows_replanning(self):
        old = ledger.read_events(self.root)[0]['modules']['M001']['plan_ref']
        self.f.call('invalidate', {'reason': 'scope review requires revised tasks'})
        before = {str(p): p.read_bytes() for p in self.f.base.rglob('*') if p.is_file()}
        result = self.check()
        self.assertTrue(result['verified'], result)
        self.assertIn('Replanning required', (self.change / 'status.md').read_text())
        self.assertTrue((self.root / 'artifacts' / old['sha256']).is_file())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.f.base.rglob('*') if p.is_file()})

    def test_explicit_scope_and_module_requirements(self):
        self.assertFalse(verify_openspec.inspect(self.root, 'module')['verified'])
        self.assertFalse(verify_openspec.inspect(self.root, 'global', 'M001')['verified'])
        self.assertIn('module-allocation', {f['check'] for f in self.check(mid='M999')['failures']})


class FinalEvidenceVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = simulated()
        cls.root = cls.output / 'workspace/.sdd-runs/demo'

    def remove(self, path):
        remove(self, path)

    def current(self):
        return ledger.read_events(self.root)[0]

    def receipt(self):
        return next(iter(self.current()['modules']['M001']['results'].values()))['execution_receipt']

    def final(self):
        return verify_openspec.inspect(self.root, 'final')

    def test_final_uses_archived_receipts_submissions_review_and_parent_summary(self):
        state = self.current()
        refs = []
        for module in state['modules'].values():
            for row in module['results'].values():
                receipt = row.get('execution_receipt')
                if receipt:
                    refs += [receipt, *verify_openspec.migration_report.refs(json.loads(Path(receipt['path']).read_text()))]
            refs += [sub['ref'] for sub in module['submissions'].values() if sub['kind'] != 'implementation']
        refs += [state['audit']['report_ref'], state['audit_code_review']['report_ref'],
                 *state['audit_code_review']['evidence_refs'], state['module_groups']['M010']['summary_ref']]
        for path in {ref['path'] for ref in refs}:
            if Path(path).is_relative_to(self.root):
                self.remove(path)
        before = {str(p): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        result = self.final()
        self.assertTrue(result['verified'], result)
        self.assertGreater(result['evidence_verification']['checked_refs'], 20)
        self.assertEqual(self.current(), state, 'verification must preserve Green and journal facts')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_final_missing_live_and_archived_receipt_is_incomplete(self):
        ref = self.receipt()
        self.remove(ref['path'])
        self.remove(self.root / 'artifacts' / ref['sha256'])
        result = self.final()
        failures = [f for f in result['failures'] if f['check'] == 'acceptance-evidence']
        self.assertTrue(failures, result)
        self.assertEqual(failures[0]['scope'], 'final')
        self.assertIn('restore', failures[0]['recovery_action'])
        self.assertEqual(self.current()['quality'], 'green-passed')
        self.assertTrue(verify_openspec.inspect(self.root, 'module', 'M002')['verified'])

    def test_live_evidence_does_not_hide_corrupt_required_archive(self):
        ref = self.receipt()
        path = self.root / 'artifacts' / ref['sha256']
        before = path.read_bytes(); self.addCleanup(path.write_bytes, before)
        path.write_text('corrupt archived receipt')
        result = self.final()
        self.assertIn('acceptance-evidence', {f['check'] for f in result['failures']})
        self.assertTrue(Path(ref['path']).is_file())

    def test_final_checks_nested_log_query_and_result_archives(self):
        receipt = json.loads(Path(self.receipt()['path']).read_text())
        for field in ('log_ref', 'query_ref', 'result_ref'):
            with self.subTest(field=field):
                ref = receipt[field]
                path = self.root / 'artifacts' / ref['sha256']
                before = path.read_bytes()
                try:
                    path.unlink()
                    result = self.final()
                    self.assertIn('acceptance-evidence', {f['check'] for f in result['failures']})
                finally:
                    path.write_bytes(before)

    def test_superseded_submission_is_not_a_new_final_gate(self):
        module = self.current()['modules']['M001']
        old = next(sub['ref'] for sub in module['submissions'].values()
                   if sub['kind'] == 'tests' and json.loads(Path(sub['ref']['path']).read_text())['code_baseline'] != module['code_baseline'])
        self.remove(old['path'])
        self.remove(self.root / 'artifacts' / old['sha256'])
        result = self.final()
        self.assertTrue(result['verified'], result)


class EvidenceArchiveCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.target = self.root / 'target'; self.target.mkdir()

    def test_old_target_bytes_are_read_from_archive_without_rechecking_live_source(self):
        from contracts import file_ref
        source = self.target / 'shared.kt'; source.write_text('previous source')
        original = file_ref(source)
        receipt = self.root / 'receipt.json'; receipt.write_text(json.dumps({'source_ref': original}))
        ref = file_ref(receipt)
        snapshots = ledger.preserve_refs(self.root, ref, target_root=str(self.target))
        source.write_text('current source from later authorized task')
        receipt.unlink()
        evidence = verify_openspec.AcceptanceEvidence(self.root, [{'artifact_snapshots': snapshots}], self.target)
        evidence.visit(ref)
        self.assertEqual(len(evidence.resolved), 2)
        self.assertEqual(evidence.check(original).read_text(), 'previous source')
        self.assertEqual(source.read_text(), 'current source from later authorized task')

    def test_legacy_live_refs_are_explicit_and_modern_unindexed_refs_rejected(self):
        from contracts import file_ref
        path = self.root / 'old-evidence.log'; path.write_text('legacy evidence')
        ref = file_ref(path)
        legacy = verify_openspec.AcceptanceEvidence(self.root, [{'effect': {'receipt': ref}}], self.target)
        legacy.visit(ref)
        self.assertEqual(legacy.summary()['legacy_live_only_refs'], [ref])
        modern = verify_openspec.AcceptanceEvidence(self.root, [{'artifact_snapshots': []}], self.target)
        with self.assertRaisesRegex(ValueError, 'no event archive entry'):
            modern.visit(ref)

    def test_explicit_unarchived_target_history_stays_visible_without_blocking(self):
        from contracts import file_ref
        source = self.target / 'historical.kt'; source.write_text('old target')
        old = file_ref(source)
        source.write_text('new target')
        receipt = self.root / 'receipt.json'; receipt.write_text(json.dumps({'old_target_ref': old}))
        ref = file_ref(receipt)
        snapshots = ledger.preserve_refs(self.root, ref, target_root=str(self.target))
        evidence = verify_openspec.AcceptanceEvidence(self.root, [{'artifact_snapshots': snapshots}], self.target)
        evidence.visit(ref)
        self.assertEqual(evidence.summary()['historical_target_unarchived_refs'], [old])
        with self.assertRaisesRegex(ValueError, 'no event archive entry'):
            evidence.check(old)  # The exception applies only to nested, explicitly recorded history.


if __name__ == '__main__':
    unittest.main()
