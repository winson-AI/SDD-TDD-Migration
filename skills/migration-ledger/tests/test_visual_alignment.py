"""Independent post-build visual parity round (lean Aligner semantics), flag-gated."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ui_fidelity
from contracts import Rejected, file_ref


def analysis(coverage='login:phone:viewport', visual_mode='runtime', interactions=None):
    model = {'kind': 'ui-component-spec',
             'ui_evidence': {'coverage': coverage, 'visual_mode': visual_mode}}
    if interactions is not None:
        model['interactions'] = interactions
    return {'dimensions': [{'dimension': 'UI', 'status': 'applicable',
                            'items': [{'item_id': 'M001-UI', 'semantic_model': model}]}]}


class VisualAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.a = analysis()
        ui_fidelity._analysis = lambda m, _a=self.a: _a   # isolate from the four-dim loader

    def ref(self, name='ev.json', content=None):
        p = self.base / name; p.write_text(json.dumps(content or {'evidence': True})); return file_ref(p)

    def result(self, status='ALIGNED', rounds=1, **over):
        base = {'schema_version': 2, 'current_round': rounds, 'max_rounds': 3,
                'required_targets': [{'page_id': 'login', 'state_id': 'phone', 'coverage': 'viewport'}],
                'target_results': [{'page_id': 'login', 'state_id': 'phone', 'coverage': 'viewport',
                                    'status': status, 'round': rounds, 'capture_round': rounds,
                                    'evidence_ref': self.ref()}]}
        base.update(over)
        return base

    def test_targets_and_pending(self):
        self.assertEqual(ui_fidelity.runtime_targets(self.a), ['login:phone:viewport'])
        self.assertFalse(ui_fidelity.alignment_pending({}, {}))                     # flag off
        self.assertTrue(ui_fidelity.alignment_pending({'ui_fidelity_required': True}, {}))
        # source-only owes no runtime parity
        self.assertEqual(ui_fidelity.runtime_targets(analysis(visual_mode='source-only')), [])

    def test_aligned_moves_to_dod(self):
        m = {'module_id': 'M001'}
        self.assertEqual(ui_fidelity.accept_alignment({}, m, self.result(), self.ref('r.json')), 'dod')
        self.assertEqual(m['alignment']['status'], 'aligned')
        self.assertFalse(ui_fidelity.alignment_pending({'ui_fidelity_required': True}, m))

    def test_needs_ui_fix_routes_back_and_spends_a_round(self):
        m = {'module_id': 'M001'}
        self.assertEqual(ui_fidelity.accept_alignment({}, m, self.result('NEEDS_UI_FIX'), self.ref('r.json')), 'diagnosing')
        self.assertEqual((m['alignment_rounds_used'], m['alignment']['unaligned']), (1, ['login:phone:viewport']))

    def test_round_budget_is_three(self):
        m = {'module_id': 'M001', 'alignment_rounds_used': 3}
        with self.assertRaisesRegex(Rejected, 'budget exhausted'):
            ui_fidelity.accept_alignment({}, m, self.result(rounds=4), self.ref('r.json'))

    def test_round_must_advance_and_targets_must_match(self):
        m = {'module_id': 'M001'}
        with self.assertRaisesRegex(Rejected, 'current_round must advance'):
            ui_fidelity.accept_alignment({}, m, self.result(rounds=2), self.ref('r.json'))
        with self.assertRaisesRegex(Rejected, 'required_targets must equal'):
            ui_fidelity.accept_alignment({}, m, self.result(required_targets=[]), self.ref('r.json'))
        with self.assertRaisesRegex(Rejected, 'missing targets'):
            ui_fidelity.accept_alignment({}, m, self.result(target_results=[]), self.ref('r.json'))

    def test_declared_gesture_needs_passing_device_check(self):
        decl = [{'id': 'edge-back', 'action': 'edge_back_gesture',
                 'from': {'page_id': 'login', 'state_id': 'phone'},
                 'expected': {'page_id': 'home', 'state_id': 'base', 'app_foreground': True}}]
        a = analysis(interactions=decl)
        ui_fidelity._analysis = lambda m, _a=a: _a
        m = {'module_id': 'M001'}
        with self.assertRaisesRegex(Rejected, 'lack device checks'):
            ui_fidelity.accept_alignment({}, m, self.result(), self.ref('r.json'))
        passing = self.result(rounds=2, hap_sha256='h1', interaction_checks=[
            {'id': 'edge-back', 'status': 'PASSED', 'hap_sha256': 'h1', 'evidence_ref': self.ref('t.json')}])
        self.assertEqual(ui_fidelity.accept_alignment({}, m, passing, self.ref('r2.json')), 'dod')


if __name__ == '__main__':
    unittest.main()
