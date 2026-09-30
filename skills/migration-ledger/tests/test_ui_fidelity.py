"""ui_fidelity_required: capture-bound UI evidence, unreduced resource closure, no Green while blocked."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import test_dimensions
import semantics
import ui_fidelity
from contracts import Rejected, check_ref, read_json

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

    def module(self, ref, renderers=('ui/LoginActivity.java',), closure=None):
        plan = {'dimension_analysis_ref': ref,
                'paths': [{'path_id': 'PV', 'kind': 'visual', 'case_id': 'C1', 'name': 'PV',
                           'node_ids': ['node:root'], 'baseline_ref': self.f.ref('baseline.png', {'shot': 1})}]}
        if renderers is not None:
            plan['source_closure'] = {'ui_renderers': list(renderers), **(closure or {
                'ui_topology': 'phone input + country row + dialog',
                'states': ['loading', 'content', 'error'],
                'navigation': 'phone -> code; back cancels the code request',
                'platform_lifecycle': 'no permissions; network via AuthRepository; cancellation on leave'})}
        return {'module_id': 'M001', 'plan': plan}

    def freeze(self, required, **kw):
        renderers = kw.pop('renderers', ('ui/LoginActivity.java',))
        closure = kw.pop('closure', None)
        ui_fidelity.freeze_gate({'ui_fidelity_required': required},
                                self.module(self.analysis_ref(**kw), renderers, closure))

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

    def test_source_closure_facets_required_for_ui_scope(self):
        for facet in ('ui_topology', 'states', 'navigation', 'platform_lifecycle'):
            partial = {'ui_topology': 't', 'states': ['content'], 'navigation': 'n', 'platform_lifecycle': 'p'}
            del partial[facet]
            with self.assertRaisesRegex(Rejected, 'source_closure.' + facet):
                self.freeze(True, ui_evidence=True, closure=partial)

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

    def strict_module(self, resources=False):
        kinds = ('UI', 'Resource') if resources else ('UI',)
        refs = ('@dimen/pad',) if resources else ()
        ref = self.analysis_ref(ui_evidence=True, refs=refs, kinds=kinds,
                                resource_over={'source_resource': '@dimen/pad'} if resources else None)
        analysis = read_json(ref['path'])
        source = self.f.ref('source-index.json', {'source': 'reviewed'})
        runtime = self.f.ref('runtime-index.json', {'runtime': 'captured'})
        ui_tree = tree(refs)
        ui_tree['generatedFrom'] = {'sourceIndex': source['path'], 'sourceIndexSha256': source['sha256'],
                                   'runtimeIndex': runtime['path'], 'runtimeIndexSha256': runtime['sha256']}
        ui_tree['screens'][0]['root']['runtimeObservations'] = [{'pageId': 'login', 'stateId': 'phone'}]
        ui_tree['screens'][0]['root']['children'] = [
            {'id': 'node:error', 'runtimeObservations': [{'pageId': 'login', 'stateId': 'error'}]}]
        evidence = analysis['dimensions'][0]['items'][0]['semantic_model']['ui_evidence']
        evidence['ui_tree_ref'] = self.f.ref('strict-tree.json', ui_tree)
        evidence['source_index_ref'] = source
        evidence['runtime_index_ref'] = runtime
        module = self.module(self.f.ref('strict-analysis.json', analysis))
        module['plan']['paths'][0]['coverage'] = evidence['coverage']
        return module, analysis

    def strict_freeze(self, module):
        # Isolate target/path association here; native source-index validation has its own
        # integration fixture. Keep real tree traversal, node targeting and all path gates.
        with patch.object(ui_fidelity.resource_fidelity, 'require_indexed_closure'), \
             patch.object(ui_fidelity.ue, 'validate_native_evidence',
                          side_effect=lambda evidence: ui_fidelity.ue.validate_tree(read_json(check_ref(evidence['ui_tree_ref'])))):
            ui_fidelity.freeze_gate({'ui_fidelity_required': True, 'evidence_contract_version': 2}, module)

    def test_v2_target_passes_and_legacy_keeps_its_existing_contract(self):
        module, _ = self.strict_module()
        self.strict_freeze(module)
        del module['plan']['paths'][0]['coverage']
        with self.assertRaisesRegex(Rejected, 'coverage'):
            self.strict_freeze(module)
        ui_fidelity.freeze_gate({'ui_fidelity_required': True}, module)

    def test_v2_visual_path_cannot_borrow_another_state_or_baseline(self):
        for change, message in (({'coverage': 'login:code:viewport'}, 'coverage'),
                                ({'node_ids': ['node:missing']}, 'nodes do not belong'),
                                ({'node_ids': ['node:error']}, 'nodes do not belong'),
                                ({'baseline_ref': self.f.ref('other-shot.png', 'other state')}, 'baseline differs')):
            with self.subTest(change=change):
                module, _ = self.strict_module()
                module['plan']['paths'][0].update(change)
                with self.assertRaisesRegex(Rejected, message):
                    self.strict_freeze(module)

    def test_v2_every_runtime_target_needs_its_own_visual_path(self):
        import copy
        module, analysis = self.strict_module()
        other = copy.deepcopy(analysis['dimensions'][0]['items'][0])
        other['item_id'] = 'M001-UI-error'
        other['semantic_model']['ui_evidence']['coverage'] = 'login:error:viewport'
        analysis['dimensions'][0]['items'].append(other)
        module['plan']['dimension_analysis_ref'] = self.f.ref('strict-analysis.json', analysis)
        with self.assertRaisesRegex(Rejected, 'runtime UI targets lack visual paths: login:error:viewport'):
            self.strict_freeze(module)
        module['plan']['paths'].append({**module['plan']['paths'][0], 'path_id': 'PV-error',
                                       'coverage': 'login:error:viewport', 'node_ids': ['node:error']})
        self.strict_freeze(module)

    def test_v2_ui_resources_require_exact_strategy(self):
        module, analysis = self.strict_module(resources=True)
        with self.assertRaisesRegex(Rejected, 'requires resource_strategy'):
            self.strict_freeze(module)
        analysis['dimensions'][3]['items'][0].update(resource_strategy='design_token_exact', resource_kind='dimen',
            source_resource_ref=self.f.ref('legacy/res/values/dimens.xml', '<resources><dimen name="pad">8dp</dimen></resources>'),
            source_unit='dp')
        module['plan']['dimension_analysis_ref'] = self.f.ref('strict-analysis.json', analysis)
        self.strict_freeze(module)

    def test_v2_non_ui_module_does_not_gain_visual_or_resource_requirements(self):
        module = self.module(self.analysis_ref(kinds=('Logic', 'Resource')), renderers=None)
        module['plan']['paths'] = []
        self.strict_freeze(module)

    def test_v2_source_only_keeps_source_provenance_without_visual_paths(self):
        module, analysis = self.strict_module()
        evidence = analysis['dimensions'][0]['items'][0]['semantic_model']['ui_evidence']
        ui_tree = read_json(evidence['ui_tree_ref']['path'])
        ui_tree['generatedFrom'].update(runtimeIndex=None, runtimeIndexSha256=None)
        ui_tree['screens'][0]['root'].pop('runtimeObservations')
        ui_tree['screens'][0]['root']['children'] = []
        evidence.update(ui_tree_ref=self.f.ref('strict-tree.json', ui_tree),
                        visual_mode='source-only', legacy_executable=False, baseline_refs=[])
        evidence.pop('runtime_index_ref')
        module['plan']['dimension_analysis_ref'] = self.f.ref('strict-analysis.json', analysis)
        module['plan']['paths'] = []
        self.strict_freeze(module)

    def test_v2_interaction_path_uses_the_declared_starting_state(self):
        module, analysis = self.strict_module()
        model = analysis['dimensions'][0]['items'][0]['semantic_model']
        model['interactions'] = [{'id': 'edge-back', 'action': 'edge_back_gesture',
                                 'from': {'page_id': 'login', 'state_id': 'error'},
                                 'expected': {'app_foreground': False}}]
        module['plan']['dimension_analysis_ref'] = self.f.ref('strict-analysis.json', analysis)
        module['plan']['paths'][0]['interaction_id'] = 'edge-back'
        with self.assertRaisesRegex(Rejected, 'declared starting page/state'):
            self.strict_freeze(module)


if __name__ == '__main__':
    unittest.main()
