"""ui_fidelity_required: UI owner cannot freeze without capture-bound ui_evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import test_dimensions
import dimensions
import semantics
import ui_fidelity
from contracts import Rejected


class UiFidelityTests(unittest.TestCase):
    def setUp(self):
        self.d = test_dimensions.DimensionTests(); self.d.setUp(); self.addCleanup(self.d.doCleanups)
        self.f = self.d.f

    def analysis_ref(self, ui_evidence=False):
        a = self.d.analysis('M001', ('UI',))  # UI applicable, item M001-UI, no model
        if ui_evidence:
            for row in a['dimensions']:
                if row['dimension'] == 'UI':
                    tree = self.f.ref('ui-tree.json', {'nodes': []})
                    row['items'][0]['semantic_model'] = {
                        'kind': 'ui-component-spec', 'model_ref': self.f.ref('ui.json', {'root': {'type': 'Col'}}),
                        'ui_evidence': {'ui_tree_ref': tree, 'coverage': 'login:phone:viewport', 'visual_mode': 'runtime'},
                        'source': {'origin': 'authored', 'evidence_refs': []},
                        'implementation_location': {'target_path': str(self.f.target / 'm1/Login.kt')}}
        return self.f.ref('a.json', a)

    def gate(self, required, ui_evidence):
        ref = self.analysis_ref(ui_evidence)
        ui_fidelity.freeze_gate({'ui_fidelity_required': required}, {'module_id': 'M001', 'plan': {'dimension_analysis_ref': ref}})

    def test_flag_off_is_noop(self):
        self.gate(False, ui_evidence=False)  # no evidence, but flag off -> allowed

    def test_required_blocks_missing_ui_evidence(self):
        with self.assertRaisesRegex(Rejected, 'ui_fidelity_required'):
            self.gate(True, ui_evidence=False)

    def test_required_passes_with_ui_evidence(self):
        self.gate(True, ui_evidence=True)

    def test_gaps_helper_scopes_to_applicable_ui(self):
        analysis = {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [
                {'item_id': 'u1', 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'p:s:viewport'}}},
                {'item_id': 'u2'}]},
            {'dimension': 'Logic', 'status': 'applicable', 'items': [{'item_id': 'l1'}]}]}
        self.assertEqual(semantics.ui_fidelity_gaps(analysis), ['u2'])


if __name__ == '__main__':
    unittest.main()
