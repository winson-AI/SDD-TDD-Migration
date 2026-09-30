"""Native verdict honesty and transitive evidence retention; no live device required."""
import json
import subprocess
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref, check_ref
import lean_adapter
import ledger
import test_lean_native_contracts as fixtures


class NativeVerdictTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.NativeContractTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def validation(self, **updates):
        log = self.f.write('target/build.log', 'observed command output')
        hap = self.f.write('target/build/app.hap', b'built package')
        value = {'schemaVersion': 1, 'stage': 'PRE_VISUAL', 'verdict': 'BUILD_READY',
                 'scope_kinds': ['logic'], 'issues': [],
                 'checks': [{'kind': kind, 'status': 'passed', 'exit_code': 0,
                             'command': 'fixture ' + kind, 'log_path': log.name}
                            for kind in ('test', 'compile', 'package')],
                 'spec_checks': [{'scenario': 'actual behavior', 'status': 'passed', 'evidence': str(log)}],
                 'artifacts': [file_ref(hap)]}
        value.update(updates)
        ref = file_ref(self.f.write('target/validation.json', value))
        return lean_adapter.validation_summary(value, target_root=self.f.target, result_ref=ref)

    def test_native_validation_verdicts_do_not_hide_missing_or_failed_work(self):
        for verdict, expected in [('BLOCKED', 'yellow-blocked'), ('FAILED', 'red-bug'),
                                  ('NEEDS_IMPLEMENTATION_FIX', 'red-bug')]:
            with self.subTest(verdict=verdict):
                result = self.validation(verdict=verdict, issues=[{'owner': 'lean', 'summary': 'action required'}])
                self.assertEqual(result['quality'], expected)
                self.assertEqual(result['root_cause']['summary'], verdict)
        self.assertEqual(self.validation(verdict='BLOCKED', checks=[], artifacts=[])['quality'], 'yellow-blocked')
        log = self.f.write('target/failed.log', 'actual failure')
        result = self.validation(verdict='BLOCKED', checks=[{'kind': 'test', 'status': 'failed',
                    'command': 'test', 'exit_code': 1, 'log_path': str(log)}], artifacts=[])
        self.assertEqual(result['quality'], 'red-bug')

    def test_native_stage_verdict_matrix_matches_original_rules(self):
        for stage, verdict in [('PRE_VISUAL', 'PASSED'), ('PRE_VISUAL', 'RUNNABLE_PARTIAL'),
                               ('FINAL', 'BUILD_READY'), ('FINAL', 'UNKNOWN')]:
            with self.subTest(stage=stage, verdict=verdict), self.assertRaisesRegex(Rejected, 'invalid for stage'):
                self.validation(stage=stage, verdict=verdict)
        self.assertEqual(self.validation()['quality'], 'green-passed')
        self.assertEqual(self.validation(stage='FINAL', verdict='PASSED')['quality'], 'green-passed')

    def test_pass_requires_current_package_and_all_spec_checks(self):
        with self.assertRaisesRegex(Rejected, 'HAP/HSP'):
            self.validation(artifacts=[file_ref(self.f.write('target/not-a-package.txt', 'text'))])
        with self.assertRaisesRegex(Rejected, 'spec'):
            self.validation(spec_checks=[])
        with self.assertRaisesRegex(Rejected, 'checks'):
            self.validation(checks=[])

    def test_source_only_partial_remains_yellow_and_retains_manifest(self):
        manifest = self.f.write('evidence/source-only.json', {'schema_version': 2, 'targets': [
            {'phase': 'android-reference', 'platform': 'android', 'page_id': 'settings', 'state_id': 'base',
             'status': 'SOURCE_ONLY', 'snapshot': None}]})
        visual = {'mode': 'source-only', 'manifest': str(manifest),
                  'targets': [{'page_id': 'settings', 'state_id': 'base'}]}
        result = self.validation(stage='FINAL', verdict='RUNNABLE_PARTIAL', visual_evidence=visual,
                                 issues=[{'summary': 'runtime proof missing'}])
        self.assertEqual(result['quality'], 'yellow-blocked')
        self.assertIn(file_ref(manifest), result['linked_refs'])
        visual['targets'][0]['state_id'] = 'other'
        with self.assertRaisesRegex(Rejected, 'SOURCE_ONLY'):
            self.validation(stage='FINAL', verdict='RUNNABLE_PARTIAL', visual_evidence=visual,
                            issues=[{'summary': 'runtime proof missing'}])

    def test_native_alignment_zero_round_preserves_implementation_failure(self):
        result = {'schemaVersion': 2, 'current_round': 0, 'max_rounds': 3, 'rounds': [],
                  'required_targets': [{'page_id': 'settings', 'state_id': 'base', 'coverage': 'viewport'}],
                  'required_interactions': [], 'issues': [{'owner': 'lean', 'summary': 'missing production code'}]}
        for status, quality in [('NEEDS_IMPLEMENTATION_FIX', 'red-bug'), ('FAILED', 'red-bug'), ('BLOCKED', 'yellow-blocked')]:
            result['status'] = status
            ref = file_ref(self.f.write('target/no-round.json', result))
            rows = lean_adapter.visual_results(result, target_root=self.f.target, result_ref=ref)
            self.assertEqual(rows['settings:base:viewport']['quality'], quality)
            self.assertFalse(rows['settings:base:viewport']['comparison_executed'])

    def test_native_alignment_targets_cannot_override_whole_result(self):
        for status, quality in [('NEEDS_IMPLEMENTATION_FIX', 'red-bug'), ('FAILED', 'red-bug'), ('BLOCKED', 'yellow-blocked')]:
            result = self.f.alignment()
            result.update(status=status, issues=[{'owner': 'lean', 'summary': 'whole-slice issue requires review'}])
            result.update(required_interactions=[], interaction_checks=[])
            ref = file_ref(self.f.write('target/whole-failure.json', result))
            row = lean_adapter.visual_results(result, target_root=self.f.target, result_ref=ref)['settings:base:viewport']
            self.assertEqual(row['quality'], quality)
            self.assertEqual(row['visual_quality'], 'green-passed')
            self.assertEqual(row['overall_verdict'], status)
            self.assertTrue(row['overall_issues'])

    def test_blocked_does_not_turn_existing_red_yellow(self):
        rows = {'a': {'quality': 'red-bug', 'root_cause': {'summary': 'assertion failed'}}}
        result = lean_adapter.overall_alignment(rows, {'status': 'BLOCKED', 'issues': ['environment lost']})
        self.assertEqual(result['a']['quality'], 'red-bug')
        self.assertEqual(result['a']['root_cause']['summary'], 'assertion failed')

    def test_relative_capture_closure_and_reference_baseline_survive_archiving(self):
        result = self.f.alignment()
        manifest = Path(result['rounds'][0]['capture_manifest'])
        data = json.loads(manifest.read_text())
        candidate = self.f.write('evidence/candidate.png', b'candidate pixels')
        for record in data['targets']:
            snapshot = record['snapshot']
            for entry in [snapshot, *snapshot['captures']]:
                for key in ('screenshot', 'view_tree', 'meta'):
                    if entry.get(key): entry[key] = Path(entry[key]).name
            if record['platform'] == 'harmony':
                snapshot['screenshot'] = candidate.name
                snapshot['captures'][0]['screenshot'] = candidate.name
        # A random prose field must not become a file inclusion instruction.
        decoy = self.f.write('evidence/unrelated-private.txt', 'not evidence')
        data['notes'] = str(decoy)
        data['targets'].append({'page_id': 'unrelated-module', 'state_id': 'base',
                                'snapshot': {'screenshot': 'missing-unrelated.png'}})
        manifest.write_text(json.dumps(data))
        row = self.f.import_alignment(result)['settings:base:viewport']
        expected = [self.f.root / ('evidence/' + name) for name in ('screenshot.png', 'candidate.png', 'view.xml', 'meta.json')]
        paths = {ref['path'] for ref in row['linked_refs']}
        self.assertTrue({str(p) for p in expected} <= paths)
        self.assertNotIn(str(decoy), paths)
        self.assertEqual(row['reference_refs'], [file_ref(expected[0])])
        archive_root = self.f.root / '.sdd-runs/archive-fixture'; archive_root.mkdir(parents=True)
        ledger.preserve_refs(archive_root, {'linked_refs': row['linked_refs']})
        for ref in row['linked_refs']:
            self.assertEqual(check_ref(ref).read_bytes(), (archive_root / 'artifacts' / ref['sha256']).read_bytes())

    def test_native_cli_accepts_original_capture_and_alignment(self):
        fixture = self.f.native_ui()
        command = [sys.executable, '-B', lean_adapter.__file__, 'ui-evidence', '--capture', str(fixture['manifest_path']),
                   '--ui-tree', str(fixture['tree_path']), '--target', 'settings:base:viewport',
                   '--source-index', str(fixture['source']), '--runtime-index', str(fixture['runtime'])]
        result = subprocess.run(command, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['contract_version'], 2)
        alignment = self.f.alignment()
        path = self.f.write('target/alignment.json', alignment)
        result = subprocess.run([sys.executable, '-B', lean_adapter.__file__, 'visual-results', '--alignment', str(path),
                                 '--target-root', str(self.f.target), '--interaction', 'settings-edge-back'],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['settings:base:viewport']['reference_refs'])

    def test_resource_references_resolve_source_and_consumer_from_their_roots(self):
        source = self.f.write('android/res/drawable/icon.png', b'original')
        target = self.f.write('target/assets/icon.png', b'original')
        consumer = self.f.write('target/src/Screen.kt', 'uses icon')
        mapping = {'sourceId': '@drawable/icon', 'sourcePath': 'res/drawable/icon.png',
                   'sourceSha256': file_ref(source)['sha256'], 'targetPath': 'assets/icon.png',
                   'targetRef': 'Res.drawable.icon', 'consumers': ['src/Screen.kt#Icon', 'Symbolic.Consumer'], 'strategy': 'byte_copy'}
        result = {'schemaVersion': 1, 'status': 'READY_FOR_LEAN', 'changeId': 'slice', 'approvedSpecHash': 'a' * 64,
                  'resourceMappings': [mapping], 'manualItems': [], 'filesChanged': ['assets/icon.png']}
        path = self.f.write('target/resources.json', result)
        out = lean_adapter.resource_summary(file_ref(path), target_root=self.f.target, legacy_root=self.f.android,
                                             approved_spec_hash='a' * 64)
        self.assertEqual({r['path'] for r in out['linked_refs']}, {str(source), str(target), str(consumer)})
        mapping['sourceSha256'] = 'b' * 64
        self.f.write('target/resources.json', result)
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            lean_adapter.resource_summary(file_ref(path), target_root=self.f.target, legacy_root=self.f.android,
                                          approved_spec_hash='a' * 64)


if __name__ == '__main__':
    unittest.main()
