"""Four legacy-to-target lanes walked end to end with fakes: the legacy captured in the run, its record the frozen reference,
the candidate captured on its own platform, and the comparison, the alignment proof and the visual verdict reading both."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import file_ref, read_json
import lean_adapter
import lean_visual_worker as worker
import test_android_target_capture
import test_lean_visual_worker
import test_legacy_capture
import ui_evidence
import visual_evidence
from lean_tools import select_runtime_ui

COVERAGE = 'login:base:viewport'


class GoldenPathTests(unittest.TestCase):
    def legacy_android(self):
        """The legacy captured on an adb device: one android-reference record."""
        legacy = test_legacy_capture.CaptureFixture(); legacy.setUp(); self.addCleanup(legacy.doCleanups)
        result = legacy.capture([legacy.login()])
        self.assertEqual(result['status'], 'CAPTURED')
        return result['manifest_ref']

    def legacy_web(self):
        """The legacy captured in a browser: one legacy-reference record of platform web."""
        legacy = test_legacy_capture.CaptureFixture(); legacy.setUp(); self.addCleanup(legacy.doCleanups)
        page = test_legacy_capture.FakePage(legacy.png(1))
        web = {'kind': 'browser', 'url': 'https://legacy.example.test/login'}
        legacy.actor['device_lock']['device_id'] = web['url']
        with patch.object(worker, 'open_browser', lambda out, viewport=None: page):
            result = legacy.capture([{'coverage': COVERAGE, 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]}], stated=web)
        self.assertEqual(result['status'], 'CAPTURED')
        return result['manifest_ref']

    def candidate(self, fixture, legacy_manifest):
        """Bind the candidate fixture to the legacy reference, install and capture the candidate; return (fixture, M2, evidence)."""
        t = fixture if isinstance(fixture, test_lean_visual_worker.VisualExecutionTests) else fixture.t
        reference = ui_evidence.capture_target(legacy_manifest, COVERAGE)
        shots = [file_ref(c['screenshot']) for c in reference['snapshot']['captures']]
        t.path.update(coverage=COVERAGE, baseline_ref=shots[0])
        t.path['visual_execution']['target_match'] = [{'text': 'Home'}]
        evidence = {'visual_mode': 'runtime', 'coverage': COVERAGE, 'capture_manifest_ref': legacy_manifest, 'baseline_refs': shots}
        analysis = t.write('context/golden-dimensions.json', {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [{'semantic_model': {'ui_evidence': evidence}}]}]})
        t.module['plan']['dimension_analysis_ref'] = file_ref(analysis)
        runner = fixture.run_tool
        install, install_ref = runner('visual-install')
        self.assertEqual(install['status'], 'INSTALLED')
        captured, _ = runner('visual-capture', install_ref=install_ref, round=1, reference_manifest_ref=legacy_manifest)
        self.assertEqual(captured['status'], 'CAPTURED', captured)
        return t, captured['manifest_ref'], evidence

    def align(self, t, manifest_ref, evidence, expected_candidate):
        """An ALIGNED result over the captured round: the comparison, the capture proof and the verdict all read it."""
        manifest = read_json(manifest_ref['path'])
        candidate = next(r for r in manifest['targets'] if visual_evidence.is_candidate(r))
        self.assertEqual((candidate['phase'], candidate['platform']), expected_candidate)
        reference_shot = evidence['baseline_refs'][0]; candidate_shot = file_ref(candidate['snapshot']['captures'][0]['screenshot'])
        target_root = t.base / 'golden-target'; target_root.mkdir(exist_ok=True)
        score = file_ref(t.write('golden-target/score.json', {'reference': reference_shot, 'candidate': candidate_shot}))
        semantic = file_ref(t.write('golden-target/semantic.json', {'status': 'COMPLETE', 'issues': [], 'score_sha256': score['sha256']}))
        result = {'schemaVersion': 2, 'status': 'ALIGNED', 'current_round': 1, 'max_rounds': 3,
                  'required_targets': [{'page_id': 'login', 'state_id': 'base', 'coverage': 'viewport'}],
                  'required_interactions': [], 'interaction_checks': [],
                  'rounds': [{'round': 1, 'hap': t.args['artifact_ref'], 'capture_manifest': manifest_ref['path'],
                              'target_results': [{'page_id': 'login', 'state_id': 'base', 'status': 'ALIGNED'}],
                              'comparisons': [{'page_id': 'login', 'state_id': 'base', 'score': score['path'], 'semantic': semantic['path'], 'semantic_region': 'main'}],
                              'verdict': 'ALIGNED', 'files_changed': []}], 'issues': []}
        proofs = lean_adapter.comparison_evidence(result, str(target_root), COVERAGE)
        self.assertEqual([(p['reference_ref']['sha256'], p['candidate_ref']['sha256']) for p in proofs], [(reference_shot['sha256'], candidate_shot['sha256'])])
        capture_proof = visual_evidence.validate_alignment(result, str(target_root), COVERAGE, frozen_evidence=evidence, code_baseline='code-1',
                                                           run_root=str(t.root), assignment={'assignment_id': 'T1', 'fencing_token': 'fence-1'})
        self.assertEqual((capture_proof[0]['capture_round'], capture_proof[0]['artifact_ref']), (1, t.args['artifact_ref']))
        result_path = t.write('golden-target/alignment-result.json', result)
        rows = lean_adapter.visual_results(result, [], target_root=str(target_root), result_ref=file_ref(result_path))
        self.assertEqual(rows[COVERAGE]['quality'], 'green-passed')
        self.assertTrue(select_runtime_ui.select(Path(evidence['capture_manifest_ref']['path']), [COVERAGE])['captures'])

    def test_android_legacy_to_harmony_target(self):
        h = test_lean_visual_worker.VisualExecutionTests(); h.setUp(); self.addCleanup(h.doCleanups)
        t, m2, evidence = self.candidate(h, self.legacy_android())
        self.align(t, m2, evidence, ('harmony-candidate', 'harmony'))

    def test_android_legacy_to_android_target(self):
        a = test_android_target_capture.AndroidTargetTests(); a.setUp(); self.addCleanup(a.doCleanups)
        t, m2, evidence = self.candidate(a, self.legacy_android())
        self.align(t, m2, evidence, ('android-candidate', 'android'))

    def test_web_legacy_to_web_target(self):
        import test_web_target_capture
        w = test_web_target_capture.WebTargetTests(); w.setUp(); self.addCleanup(w.doCleanups)
        t, m2, evidence = self.candidate(w, self.legacy_web())
        self.align(t, m2, evidence, ('web-candidate', 'web'))

    def test_web_legacy_to_android_target(self):
        a = test_android_target_capture.AndroidTargetTests(); a.setUp(); self.addCleanup(a.doCleanups)
        t, m2, evidence = self.candidate(a, self.legacy_web())
        self.align(t, m2, evidence, ('android-candidate', 'android'))


if __name__ == '__main__':
    unittest.main()
