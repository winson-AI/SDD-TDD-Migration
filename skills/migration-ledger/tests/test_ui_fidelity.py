"""ui_fidelity_required: capture-bound UI evidence, unreduced resource closure, no Green while blocked."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import test_dimensions
import semantics
import ui_fidelity
from contracts import Rejected

def tree(refs=()):
    return {'schemaVersion': 1, 'scope': 'migrate-login',
            'generatedFrom': {'sourceIndex': 'ui-source-index.json', 'sourceIndexSha256': 'aa',
                              'runtimeIndex': 'runtime-ui-index.json', 'runtimeIndexSha256': 'bb'},
            'screens': [{'id': 'screen:login',
                         'root': {'id': 'node:root', 'presentation': {'resourceRefs': list(refs)}}}],
            'layoutClosure': [], 'criticalLayoutContracts': [], 'unresolved': []}


class UiFidelityTests(unittest.TestCase):
    def setUp(self):
        self.d = test_dimensions.DimensionTests(); self.d.setUp(); self.addCleanup(self.d.doCleanups)
        self.f = self.d.f

    def analysis_ref(self, ui_evidence=False, refs=(), kinds=('UI',), resource_over=None, name='a.json'):
        a = self.d.analysis('M001', kinds)
        for row in a['dimensions']:
            if row['dimension'] == 'UI' and ui_evidence:
                row['items'][0]['semantic_model'] = {
                    'kind': 'ui-component-spec', 'model_ref': self.f.ref('ui.json', {'root': {'type': 'Col'}}),
                    'ui_evidence': {'ui_tree_ref': self.f.ref('ui-tree.json', tree(refs)),
                                    'coverage': 'login:phone:viewport', 'visual_mode': 'runtime',
                                    'legacy_executable': True,
                                    'baseline_refs': [self.f.ref('baseline.png', {'shot': 1})]},
                    'source': {'origin': 'authored', 'evidence_refs': []},
                    'implementation_location': {'target_path': str(self.f.target / 'm1/Login.kt')}}
            if row['dimension'] == 'Resource' and resource_over and row['items']:
                row['items'][0].update(resource_over)
        return self.f.ref(name, a)

    def module(self, ref, renderers=('ui/LoginActivity.java',)):
        plan = {'dimension_analysis_ref': ref,
                'paths': [{'path_id': 'PV', 'kind': 'visual', 'case_id': 'C1', 'name': 'PV',
                           'node_ids': ['node:root'], 'baseline_ref': self.f.ref('baseline.png', {'shot': 1})}]}
        if renderers is not None:
            plan['source_closure'] = {'ui_renderers': list(renderers)}
        return {'module_id': 'M001', 'plan': plan}

    def freeze(self, required, **kw):
        renderers = kw.pop('renderers', ('ui/LoginActivity.java',))
        ui_fidelity.freeze_gate({'ui_fidelity_required': required}, self.module(self.analysis_ref(**kw), renderers))

    def test_flag_off_is_noop(self):
        self.freeze(False, ui_evidence=False, renderers=None)  # nothing required when off

    def test_required_blocks_missing_ui_evidence(self):
        with self.assertRaisesRegex(Rejected, 'lack capture-bound ui_evidence'):
            self.freeze(True, ui_evidence=False)

    def test_required_passes_with_ui_evidence(self):
        self.freeze(True, ui_evidence=True)

    def test_required_needs_mutating_renderers(self):
        with self.assertRaisesRegex(Rejected, 'ui_renderers'):
            self.freeze(True, ui_evidence=True, renderers=None)

    def test_reduced_resource_closure_blocks_freeze(self):
        # the UI tree declares a presentation ref that no Resource item covers
        with self.assertRaisesRegex(Rejected, 'closure reduced'):
            self.freeze(True, ui_evidence=True, refs=('@dimen/pad',))

    def test_blocked_resource_cannot_complete(self):
        ref = self.analysis_ref(kinds=('UI', 'Resource'), name='blocked.json',
                                resource_over={'resource_strategy': 'blocked', 'resource_kind': 'shape',
                                               'blocked_reason': 'selector semantics unsupported'})
        with self.assertRaisesRegex(Rejected, 'blocked resources cannot complete'):
            ui_fidelity.completion_gate({'ui_fidelity_required': True}, self.module(ref))
        ui_fidelity.completion_gate({'ui_fidelity_required': False}, self.module(ref))  # off -> no-op

    def test_gaps_helper_scopes_to_applicable_ui(self):
        analysis = {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [
                {'item_id': 'u1', 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'p:s:viewport'}}},
                {'item_id': 'u2'}]},
            {'dimension': 'Logic', 'status': 'applicable', 'items': [{'item_id': 'l1'}]}]}
        self.assertEqual(semantics.ui_fidelity_gaps(analysis), ['u2'])


if __name__ == '__main__':
    unittest.main()
