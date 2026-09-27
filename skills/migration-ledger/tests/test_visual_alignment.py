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


if __name__ == '__main__':
    unittest.main()
