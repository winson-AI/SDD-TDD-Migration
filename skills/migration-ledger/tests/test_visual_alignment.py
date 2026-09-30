"""Baseline determination guides coding; visual alignment is automation layer 2, not a phase."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import test_validation as tv
import ui_fidelity
from contracts import Rejected, file_ref


def plan(paths):
    return {'paths': paths}


def path(pid, kind, case='C1', **over):
    base = {'path_id': pid, 'kind': kind, 'case_id': case, 'name': pid}
    base.update(over)
    return base


class StageOrderTests(unittest.TestCase):
    """build -> automation (functional) -> visual (baseline node alignment)."""

    def module(self, results=None, baseline=None, code='B1'):
        return {'plan': plan([path('PB', 'build'), path('PA', 'automation'), path('PV', 'visual')]),
                'results': results or {}, 'code_baseline': code, 'build_baseline': baseline}

    def green(self, code='B1'):
        return {'quality': 'green-passed', 'code_baseline': code}

    def test_paths_split_three_ways(self):
        m = self.module()
        self.assertEqual([p['path_id'] for p in tv.paths(m, 'build')], ['PB'])
        self.assertEqual([p['path_id'] for p in tv.paths(m, 'automation')], ['PA'])
        self.assertEqual([p['path_id'] for p in tv.paths(m, 'visual')], ['PV'])

    def test_kindless_path_counts_as_automation(self):
        m = {'plan': plan([path('PB', 'build'), {'path_id': 'PX', 'case_id': 'C1'}]), 'results': {}}
        self.assertEqual([p['path_id'] for p in tv.paths(m, 'automation')], ['PX'])

    def test_stage_order(self):
        m = self.module()
        self.assertEqual(tv.next_scope(m), 'build')                       # nothing yet
        m = self.module(results={'PB': self.green()}, baseline='B1')
        self.assertEqual(tv.next_scope(m), 'automation')                  # build Green
        m = self.module(results={'PB': self.green(), 'PA': self.green()}, baseline='B1')
        self.assertEqual(tv.next_scope(m), 'visual')                      # layer 1 Green -> layer 2
        self.assertTrue(tv.functional_ready(m))

    def test_visual_not_offered_before_functional_green(self):
        m = self.module(results={'PB': self.green(), 'PA': {'quality': 'red-bug', 'code_baseline': 'B1'}}, baseline='B1')
        self.assertEqual(tv.next_scope(m), 'automation')
        self.assertFalse(tv.functional_ready(m))

    def test_dod_requires_every_stage_green(self):
        m = self.module(results={'PB': self.green(), 'PA': self.green()}, baseline='B1')
        self.assertFalse(tv.all_green(m))                                 # visual has no result yet
        m['results']['PV'] = self.green()
        self.assertTrue(tv.all_green(m))

    def test_no_visual_paths_keeps_two_stages(self):
        m = {'plan': plan([path('PB', 'build'), path('PA', 'automation')]),
             'results': {'PB': self.green()}, 'code_baseline': 'B1', 'build_baseline': 'B1'}
        self.assertEqual(tv.next_scope(m), 'automation')


class BaselineGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        original = ui_fidelity._analysis           # never leak the patch into other suites
        self.addCleanup(setattr, ui_fidelity, '_analysis', original)

    def ref(self, name='shot.png', content='img'):
        p = self.base / name; p.write_text(content); return file_ref(p)

    def analysis(self, **evidence_over):
        evidence = {'coverage': 'login:phone:viewport', 'visual_mode': 'runtime',
                    'legacy_executable': True, 'baseline_refs': [self.ref()]}
        evidence.update(evidence_over)
        return {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'M001-UI', 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': evidence}}]}]}

    def gate(self, analysis, paths, flag=True):
        ui_fidelity._analysis = lambda m, _a=analysis: _a
        ui_fidelity.baseline_gate({'ui_fidelity_required': flag}, {'module_id': 'M001', 'plan': plan(paths)})

    def visual(self, **over):
        return path('PV', 'visual', node_ids=['node:root'], baseline_ref=self.ref(), **over)

    def test_flag_off_is_noop(self):
        self.gate(self.analysis(legacy_executable=None), [], flag=False)

    def test_executability_must_be_decided(self):
        with self.assertRaisesRegex(Rejected, 'executability must be decided'):
            self.gate(self.analysis(legacy_executable=None), [self.visual()])

    def test_previewable_legacy_needs_baseline_and_visual_path(self):
        self.gate(self.analysis(), [self.visual()])                       # ok
        with self.assertRaisesRegex(Rejected, 'baseline screenshots'):
            self.gate(self.analysis(baseline_refs=[]), [self.visual()])
        with self.assertRaisesRegex(Rejected, 'needs a visual test path'):
            self.gate(self.analysis(), [])

    def test_non_previewable_falls_back_to_source_only(self):
        self.gate(self.analysis(legacy_executable=False, visual_mode='source-only', baseline_refs=None), [])
        with self.assertRaisesRegex(Rejected, 'falls back to source-only'):
            self.gate(self.analysis(legacy_executable=False), [self.visual()])

    def test_declared_interaction_needs_a_visual_path(self):
        a = self.analysis()
        a['dimensions'][0]['items'][0]['semantic_model']['interactions'] = [
            {'id': 'edge-back', 'action': 'edge_back_gesture',
             'from': {'page_id': 'login', 'state_id': 'phone'},
             'expected': {'page_id': 'home', 'state_id': 'base', 'app_foreground': True}}]
        with self.assertRaisesRegex(Rejected, 'device proof'):
            self.gate(a, [self.visual()])
        self.gate(a, [self.visual(interaction_id='edge-back')])


class VisualResultTests(unittest.TestCase):
    def setUp(self):
        import test_lean_native_contracts as fixtures
        import lean_visual_adapter
        self.native = fixtures.NativeContractTests(); self.native.setUp(); self.addCleanup(self.native.doCleanups)
        self.base = self.native.root
        alignment = self.native.alignment()
        self.run_root, frozen = self.native.bind_execution(alignment)
        self.assignment = {'assignment_id': 'capture-assignment', 'fencing_token': 'capture-fence'}
        self.module = {'evidence_contract_version': 2, 'code_baseline': 'current-code'}
        self.path = path('PV', 'visual', coverage='settings:base:viewport', node_ids=['node:root'],
                         baseline_ref=file_ref(self.base / 'evidence/screenshot.png'), interaction_id='settings-edge-back',
                         visual_evidence=frozen)
        hap = alignment['rounds'][0]['hap']
        self.module['build_artifacts'] = [hap]
        interaction = alignment['required_interactions'][0]
        self.module['frozen_interactions'] = {'PV': interaction}
        query = {**self.path, 'run_id': 'r1', 'module_id': 'M001', 'freeze_id': 'f1',
                 'code_baseline': 'current-code', 'evidence_contract_version': 2, 'frozen_interaction': interaction,
                 'run_root': self.run_root, 'frozen_visual_evidence': frozen,
                 'execution_assignment': self.assignment,
                 'expected_assertions': [{'assertion_id': 'visual', 'expected': True}]}
        self.proof = lean_visual_adapter.report(query,
            file_ref(self.native.write('target/alignment.json', alignment)), self.native.target, [interaction['id']])['visual_alignment']

    def ref(self, name, content):
        p = self.base / name; p.write_text(content); return file_ref(p)

    def validate(self, proof=None):
        proof = self.proof if proof is None else proof
        tv.visual_result(self.module, self.path, {'quality': 'green-passed', 'visual_alignment': proof},
                         {'visual_alignment': proof}, run_root=self.run_root, assignment=self.assignment)

    def test_green_binds_target_baseline_hap_and_gesture(self):
        self.validate()

    def test_stale_or_unrelated_visual_proof_cannot_be_green(self):
        for field, value, message in (
                ('coverage', 'login:other:viewport', 'coverage differs'),
                ('node_ids', ['node:other'], 'nodes differ'),
                ('baseline_ref', self.ref('other.png', 'unrelated'), 'baseline differs'),
                ('code_baseline', 'old-code', 'baseline is stale')):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, message):
                self.validate({**self.proof, field: value})

    def test_replaced_hap_is_rejected(self):
        Path(self.proof['hap_ref']['path']).write_text('different build')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.validate()

    def test_unrelated_valid_hap_is_not_current_build_evidence(self):
        other = self.ref('other.hap', 'a different valid build')
        with self.assertRaisesRegex(Rejected, 'accepted current build'):
            self.validate({**self.proof, 'hap_ref': other})

    def test_gesture_requires_same_hap_current_code_and_pass(self):
        original = self.proof['interaction_checks'][0]
        for field, value, message in (('hap_sha256', 'different-hap', 'aligned HAP'),
                                     ('code_baseline', 'old-code', 'current code baseline'),
                                     ('status', 'FAILED', 'not PASSED')):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, message):
                self.validate({**self.proof, 'interaction_checks': [{**original, field: value}]})
        with self.assertRaisesRegex(Rejected, 'lack device checks'):
            self.validate({**self.proof, 'interaction_checks': []})

    def test_worker_cannot_replace_captured_visual_evidence(self):
        with self.assertRaisesRegex(Rejected, 'captured report'):
            tv.visual_result(self.module, self.path, {'quality': 'green-passed', 'visual_alignment': self.proof},
                             {'visual_alignment': {**self.proof, 'code_baseline': 'other'}})

    def test_same_id_cannot_replace_frozen_interaction_semantics(self):
        import copy
        for field, value in (('action', 'tap_exit_button'), ('from', {'page_id': 'other', 'state_id': 'base'}),
                             ('expected', {'app_foreground': False})):
            proof = copy.deepcopy(self.proof)
            proof['required_interaction'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'requirement differs'):
                self.validate(proof)
        for field, value, message in (('action', 'tap_exit_button', 'action differs'),
                                     ('observed', {'app_foreground': False}, 'observation differs')):
            proof = copy.deepcopy(self.proof)
            proof['interaction_checks'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, message):
                self.validate(proof)

    def test_missing_evidence_still_allows_red_yellow_and_legacy_results(self):
        for quality in ('red-bug', 'yellow-blocked'):
            tv.visual_result(self.module, self.path, {'quality': quality}, {})
        tv.visual_result({'code_baseline': 'current-code'}, self.path, {'quality': 'green-passed'}, {})
        tv.visual_result(self.module, path('PA', 'automation'), {'quality': 'green-passed'}, {})


if __name__ == '__main__':
    unittest.main()
