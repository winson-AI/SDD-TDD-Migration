"""v2 Green reuses the exact frozen source and an executed current-build capture."""
import copy
import sys
from pathlib import Path
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, read_json
import lean_visual_adapter
import test_validation
import visual_evidence
import test_lean_native_contracts as native


class VisualExecutionProofTests(unittest.TestCase):
    def setUp(self):
        self.f = native.NativeContractTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.alignment = self.f.alignment()
        self.alignment['required_interactions'] = []; self.alignment['interaction_checks'] = []
        self.assignment = {'assignment_id': 'capture-assignment', 'fencing_token': 'capture-fence'}

    def bind(self, codes='current-code'):
        self.run_root, self.frozen = self.f.bind_execution(self.alignment, codes,
            assignment=getattr(self, 'capture_assignments', self.assignment))
        self.path = {'path_id': 'VISUAL', 'kind': 'visual', 'coverage': self.frozen['coverage'],
                     'node_ids': ['node:root'], 'baseline_ref': self.frozen['baseline_refs'][0],
                     'visual_evidence': self.frozen}
        self.module = {'evidence_contract_version': 2, 'code_baseline': 'current-code',
                       'build_artifacts': [self.alignment['rounds'][-1]['hap']]}
        self.query = {**self.path, 'run_id': 'visual-test', 'run_root': self.run_root, 'module_id': 'GLOBAL',
                      'freeze_id': 'freeze', 'code_baseline': 'current-code', 'evidence_contract_version': 2,
                      'frozen_visual_evidence': self.frozen,
                      'execution_assignment': self.assignment,
                      'expected_assertions': [{'assertion_id': 'A', 'expected': True}]}

    def report(self):
        ref = file_ref(self.f.write('target/alignment.json', self.alignment))
        return lean_visual_adapter.report(self.query, ref, self.f.target)

    def accept(self, report):
        test_validation.visual_result(self.module, self.path, report, report, run_root=self.run_root,
                                      assignment=self.assignment)

    def test_managed_external_capture_passes_both_adapter_and_formal_gate(self):
        self.bind(); report = self.report(); self.accept(report)
        self.assertEqual(report['quality'], 'green-passed')
        self.assertEqual(report['visual_alignment']['capture_evidence'][0]['code_baseline'], 'current-code')

    def test_old_capture_cannot_be_relabelled_with_current_build_or_code(self):
        self.bind()
        old_hap = self.alignment['rounds'][0]['hap']
        current = file_ref(self.f.write('target/build/new.hap', b'new never captured binary'))
        self.alignment['rounds'][0]['hap'] = current
        self.module['build_artifacts'] = [current]
        with self.assertRaisesRegex(Rejected, 'capture execution HAP'):
            self.report()
        self.alignment['rounds'][0]['hap'] = old_hap
        self.query['code_baseline'] = 'new-code'
        with self.assertRaisesRegex(Rejected, 'code baseline is stale'):
            self.report()

    def test_sidecar_cannot_override_original_metadata(self):
        self.bind()
        self.f.write('evidence/meta.json', {'artifact_ref': file_ref(self.f.write('target/build/old.hap', b'old')),
                                          'code_baseline': 'old-code'})
        with self.assertRaisesRegex(Rejected, 'capture metadata differs'):
            self.report()

    def test_sidecar_requires_installation_and_observation_command_evidence(self):
        self.bind()
        manifest_path = Path(self.alignment['rounds'][0]['capture_manifest'])
        manifest = read_json(manifest_path)
        snapshot = manifest['targets'][1]['snapshot']
        original_ref = snapshot['capture_execution_ref']
        receipt = read_json(original_ref['path'])
        for field, value, message in (
                ('install_ref', None, 'evidence path'),
                ('command_log_ref', file_ref(self.f.write(
                    '.sdd-runs/visual-test/runs/harmony/sandbox/test/labels.json',
                    [{'argv': ['echo', 'CAPTURED'], 'exit_code': 0}])), 'capture command evidence')):
            changed = self.f.write('.sdd-runs/visual-test/runs/harmony/sandbox/test/changed.json', {**receipt, field: value})
            snapshot['capture_execution_ref'] = file_ref(changed)
            self.f.write(str(manifest_path), manifest)
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, message):
                self.report()

    def test_formal_gate_rechecks_receipt_instead_of_trusting_adapter(self):
        self.bind(); report = self.report()
        report['visual_alignment']['capture_evidence'][0]['code_baseline'] = 'invented'
        with self.assertRaisesRegex(Rejected, 'capture.*differs|execution.*differs'):
            self.accept(report)

    def test_new_auditor_assignment_cannot_reuse_previous_capture_as_retest(self):
        self.bind(); report = self.report()
        for assignment in ({**self.assignment, 'assignment_id': 'fresh-audit'},
                           {**self.assignment, 'fencing_token': 'fresh-fence'}):
            with self.subTest(assignment=assignment), self.assertRaisesRegex(Rejected, 'current test/audit assignment'):
                test_validation.visual_result(self.module, self.path, report, report,
                    run_root=self.run_root, assignment=assignment)
        self.query['execution_assignment'] = {'assignment_id': 'fresh-audit', 'fencing_token': 'fresh-fence'}
        with self.assertRaisesRegex(Rejected, 'current test/audit assignment'):
            self.report()

    def semantic(self, **values):
        c = self.alignment['rounds'][0]['comparisons'][0]
        import lean_adapter
        score = lean_adapter.normalize_ref(c['score'], self.f.target)
        ref = file_ref(self.f.write('target/semantic.json', {'status': 'COMPLETE', 'score_sha256': score['sha256'], **values}))
        c['semantic'] = ref['path']
        return c, ref

    def test_semantic_findings_require_bound_evidenced_dispositions(self):
        self.bind()
        issue = {'severity': 'critical', 'summary': 'Wrong route'}
        c, ref = self.semantic(issues=[issue], comparability=0.1, comparable=False)
        with self.assertRaisesRegex(Rejected, 'explicit disposition'):
            self.report()
        proof = file_ref(self.f.write('evidence/review.json', {'observed_route': 'settings', 'review': 'Verified source/candidate state'}))
        c['semantic_dispositions'] = [
            {'semantic_ref': ref, 'finding': finding, 'decision': 'dismissed',
             'reason': 'Reviewer inspected the matching route and state', 'evidence_refs': [proof]}
            for finding in ({'kind': 'issue', 'index': 0, 'issue': issue},
                            {'kind': 'comparability', 'value': 0.1}, {'kind': 'comparable', 'value': False})]
        self.accept(self.report())
        original = copy.deepcopy(c['semantic_dispositions'])
        for field, value, message in (('semantic_ref', proof, 'original semantic'),
                                      ('finding', {'kind': 'issue', 'index': 99}, 'finding differs'),
                                      ('evidence_refs', [ref], 'supporting evidence')):
            c['semantic_dispositions'] = copy.deepcopy(original)
            c['semantic_dispositions'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, message):
                self.report()
        c['semantic_dispositions'] = original
        Path(proof['path']).write_text('changed review')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.report()

    def test_clear_semantic_result_needs_no_synthetic_dispositions(self):
        self.bind(); self.semantic(issues=[], comparability=0.8)
        self.accept(self.report())

    def test_formal_gate_rechecks_original_semantic_findings(self):
        self.bind(); c, _ = self.semantic(issues=[], comparability=0.8)
        report = self.report()
        self.semantic(issues=[{'severity': 'critical', 'summary': 'Unresolved after adapter'}], comparability=0.8)
        report['visual_alignment']['evidence_ref'] = file_ref(self.f.write('target/alignment.json', self.alignment))
        with self.assertRaisesRegex(Rejected, 'explicit disposition'):
            self.accept(report)

    def scroll(self, repeated_pixels=False):
        row = self.alignment['rounds'][0]
        manifest = read_json(row['capture_manifest'])
        first = manifest['targets'][0]['snapshot']['captures'][0]
        second = first['screenshot'] if repeated_pixels else str(self.f.write('evidence/second.png', b'source-second'))
        for target in manifest['targets']:
            target['coverage'] = target['snapshot']['coverage'] = {
                'requested': 'scroll', 'achieved': 'scroll-complete', 'capture_count': 2, 'termination': 'end-reached'}
            target['snapshot']['captures'].append({**first, 'index': 1, 'screenshot': second, 'view_signature': 'second-position'})
        self.f.write(str(row['capture_manifest']), manifest)
        self.alignment['required_targets'][0]['coverage'] = 'scroll'
        row['comparisons'][0].update(coverage='scroll', reference_capture_index=0, candidate_capture_index=0)
        score = self.f.write('target/score-second.json', {'reference': file_ref(second), 'candidate': file_ref(second)})
        row['comparisons'].append({'page_id': 'settings', 'state_id': 'base', 'coverage': 'scroll',
            'reference_capture_index': 1, 'candidate_capture_index': 1, 'semantic_region': 'main', 'score': str(score)})

    def test_unfrozen_second_scroll_reference_is_rejected_by_adapter_and_gate(self):
        self.scroll(); self.bind(); valid = self.report(); self.accept(valid)
        path = Path(self.alignment['rounds'][0]['capture_manifest'])
        manifest = read_json(path)
        replacement = file_ref(self.f.write('evidence/replacement.png', b'unfrozen replacement'))
        manifest['targets'][0]['snapshot']['captures'][1]['screenshot'] = replacement['path']
        self.f.write(str(path), manifest)
        self.f.write('target/score-second.json', {'reference': replacement,
                                               'candidate': file_ref(self.f.root / 'evidence/second.png')})
        with self.assertRaisesRegex(Rejected, 'original frozen Android record'):
            self.report()
        # An invented adapter receipt cannot hide the mismatch on the formal path either.
        import lean_adapter
        ref = file_ref(self.f.write('target/alignment.json', self.alignment))
        valid['visual_alignment'].update(evidence_ref=ref,
            comparison_evidence=lean_adapter.comparison_evidence(self.alignment, self.f.target, self.path['coverage']))
        with self.assertRaisesRegex(Rejected, 'original frozen Android record'):
            self.accept(valid)

    def test_identical_pixels_in_distinct_frozen_viewports_remain_valid(self):
        self.scroll(repeated_pixels=True); self.bind()
        self.frozen['baseline_refs'] = [self.frozen['baseline_refs'][0]]
        self.accept(self.report())

    def test_carried_alignment_keeps_old_capture_and_requires_current_regression_capture(self):
        first = self.alignment['rounds'][0]
        manifest = read_json(first['capture_manifest'])
        candidate = copy.deepcopy(manifest['targets'][1]); candidate['round'] = 2
        current_shot = file_ref(self.f.write('evidence/current.png', b'current captured pixels'))
        candidate['snapshot']['screenshot'] = current_shot['path']
        candidate['snapshot']['captures'][0]['screenshot'] = current_shot['path']
        manifest['targets'].append(candidate)
        self.f.write(str(first['capture_manifest']), manifest)
        regression = self.f.write('target/regression.json', {
            'reference': file_ref(self.f.root / 'evidence/screenshot.png'), 'candidate': current_shot})
        new_hap = file_ref(self.f.write('target/build/current.hap', b'current build'))
        self.alignment['rounds'].append({**first, 'round': 2, 'hap': new_hap, 'comparisons': [], 'target_results': [
            {'page_id': 'settings', 'state_id': 'base', 'status': 'ALIGNED_CARRIED',
             'carried_from_round': 1, 'regression_score': str(regression)}]})
        self.alignment['current_round'] = 2
        self.capture_assignments = {1: {'assignment_id': 'historical-capture', 'fencing_token': 'old-fence'},
                                    2: self.assignment}
        self.bind({1: 'old-code', 2: 'current-code'})
        report = self.report(); self.accept(report)
        captures = report['visual_alignment']['capture_evidence']
        self.assertEqual([p['code_baseline'] for p in captures], ['old-code', 'current-code'])
        latest = Path(self.alignment['rounds'][-1]['capture_manifest'])
        manifest = read_json(latest)
        manifest['targets'][-1]['snapshot']['capture_execution_ref'] = captures[0]['capture_execution_ref']
        self.f.write(str(latest), manifest)
        with self.assertRaisesRegex(Rejected, 'target/round differs'):
            self.report()

    def test_global_has_no_inferred_source_owner_and_other_runs_are_rejected(self):
        self.bind()
        own = {k: v for k, v in self.path.items() if k != 'visual_evidence'}
        self.assertIsNone(visual_evidence.frozen_evidence({'path_dimension_analysis_refs': {}}, own))
        self.query['frozen_visual_evidence'] = None
        with self.assertRaisesRegex(Rejected, 'complete frozen visual evidence'):
            self.report()
        self.query['frozen_visual_evidence'] = self.frozen
        self.query['run_root'] = str(self.f.root / '.sdd-runs/another-run')
        with self.assertRaisesRegex(Rejected, 'outside selected run'):
            self.report()

    def test_v1_and_non_green_do_not_require_new_capture_proof(self):
        self.bind()
        self.query.pop('frozen_visual_evidence'); self.query.pop('run_root')
        self.query['evidence_contract_version'] = 1
        self.assertEqual(self.report()['quality'], 'green-passed')
        self.query['evidence_contract_version'] = 2
        self.alignment.update(status='NEEDS_IMPLEMENTATION_FIX', issues=[{'owner': 'lean', 'summary': 'observed failure'}])
        self.assertEqual(self.report()['quality'], 'red-bug')


if __name__ == '__main__':
    unittest.main()
