"""Direct freeze and execution consume original native evidence, without gate mocks."""
import copy
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, baseline, file_ref, read_json
import lean_adapter
import lean_visual_adapter
import ledger
import test_validation
import ui_evidence
import ui_fidelity
import test_lean_native_contracts as native_fixtures
import test_ui_fidelity as dimension_fixtures
from lean_tools import select_runtime_ui


class FrozenUiContracts(unittest.TestCase):
    def setUp(self):
        self.n = native_fixtures.NativeContractTests()
        self.n.setUp(); self.addCleanup(self.n.doCleanups)
        self.f = dimension_fixtures.UiFidelityTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.fixture = self.n.native_ui()
        self.evidence = self.n.import_ui(self.fixture)
        self.analysis = read_json(self.f.analysis_ref(ui_evidence=True, kinds=('UI', 'Resource'), resource_over={
            'source_resource': '@string/settings_title', 'resource_kind': 'string',
            'resource_strategy': 'value_xml_exact', 'source_resource_ref': file_ref(
                self.n.android / 'app/src/main/res/values/strings.xml')})['path'])
        self.model = self.analysis['dimensions'][0]['items'][0]['semantic_model']
        self.model['ui_evidence'] = self.evidence
        self.state = {'ui_fidelity_required': True}
        self.sequence = 0

    def module(self):
        self.sequence += 1
        ref = self.f.f.ref('native-analysis-' + str(self.sequence) + '.json', self.analysis)
        module = self.f.module(ref)
        if self.evidence['visual_mode'] == 'runtime':
            module['plan']['paths'][0].update(coverage=self.evidence['coverage'], node_ids=['node:settings.root'],
                                            baseline_ref=self.evidence['baseline_refs'][0])
        else:
            module['plan']['paths'] = []
        return module

    def freeze(self):
        module = self.module()
        ui_fidelity.freeze_gate(self.state, module)
        return module

    def update_runtime(self, index):
        ref = file_ref(self.n.write('evidence/runtime-ui-index.json', index))
        self.evidence['runtime_index_ref'] = ref
        self.fixture['tree']['generatedFrom']['runtimeIndexSha256'] = ref['sha256']
        self.evidence['ui_tree_ref'] = file_ref(self.n.write('evidence/ui-tree.json', self.fixture['tree']))

    def test_direct_freeze_rejects_missing_or_unrelated_manifest_and_baseline(self):
        self.freeze()
        original = copy.deepcopy(self.evidence)
        variants = [('capture_manifest_ref', None, 'capture_manifest_ref'),
                    ('capture_manifest_ref', self.f.f.ref('unrelated.json', {'targets': []}), 'capture target'),
                    ('baseline_refs', [self.f.f.ref('unrelated.png', 'other pixels')], 'selected runtime capture')]
        for field, value, message in variants:
            self.evidence.clear(); self.evidence.update(copy.deepcopy(original))
            if value is None: self.evidence.pop(field)
            else: self.evidence[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(Rejected, message):
                self.freeze()

    def test_manifest_hash_and_selected_index_content_are_both_bound(self):
        manifest = self.fixture['manifest']; manifest['capture_id'] = 'different-capture'
        self.evidence['capture_manifest_ref'] = file_ref(self.n.write('evidence/manifest.json', manifest))
        with self.assertRaisesRegex(Rejected, 'different manifest'):
            self.freeze()
        index = read_json(self.fixture['runtime'])
        index['manifestSha256'] = self.evidence['capture_manifest_ref']['sha256']
        index['captureId'] = manifest['capture_id']
        alternate = file_ref(self.n.write('evidence/unrelated.png', b'other pixels'))
        index['captures'][0]['screenshot'] = alternate
        index['captures'][0]['viewports'][0]['screenshot'] = alternate
        self.evidence['baseline_refs'] = [alternate]
        self.update_runtime(index)
        with self.assertRaisesRegex(Rejected, 'differs from original capture'):
            self.freeze()

    def test_unrelated_shared_manifest_and_index_targets_do_not_block_freeze(self):
        manifest = self.fixture['manifest']
        manifest['targets'].append({'phase': 'android-reference', 'platform': 'android', 'page_id': 'orders',
                                   'state_id': 'error', 'status': 'COMPLETE', 'snapshot': {'screenshot': '/missing/orders.png'}})
        ref = file_ref(self.n.write('evidence/manifest.json', manifest))
        self.evidence['capture_manifest_ref'] = ref
        index = select_runtime_ui.select(Path(ref['path']), [self.evidence['coverage']])
        index['captures'].append({'pageId': 'orders', 'stateId': 'error', 'requestedCoverage': 'viewport',
                                  'screenshot': {'path': '/missing/orders.png', 'sha256': '0' * 64}})
        self.update_runtime(index)
        self.freeze()

    def test_source_only_needs_source_but_no_invented_capture(self):
        tree = self.fixture['tree']
        tree['generatedFrom'].pop('runtimeIndex'); tree['generatedFrom'].pop('runtimeIndexSha256')
        tree['screens'][0]['root'].pop('runtimeObservations')
        self.evidence.update(visual_mode='source-only', legacy_executable=False,
                             ui_tree_ref=file_ref(self.n.write('evidence/ui-tree.json', tree)))
        self.evidence.pop('runtime_index_ref'); self.evidence.pop('baseline_refs')
        manifest_ref = self.evidence.pop('capture_manifest_ref')
        self.freeze()
        self.evidence['capture_manifest_ref'] = manifest_ref
        with self.assertRaisesRegex(Rejected, 'modes differ'):
            self.freeze()
        manifest = self.fixture['manifest']
        manifest['targets'][0].update(status='SOURCE_ONLY', snapshot=None)
        self.evidence['capture_manifest_ref'] = file_ref(self.n.write('evidence/manifest.json', manifest))
        self.freeze()
        self.evidence['baseline_refs'] = [self.f.f.ref('fake.png', 'not captured')]
        with self.assertRaisesRegex(Rejected, 'source-only cannot claim'):
            self.freeze()

    def alignment_query(self):
        result = self.n.alignment()
        self.model['interactions'] = copy.deepcopy(result['required_interactions'])
        module = self.module()
        path = module['plan']['paths'][0]
        path['interaction_id'] = 'settings-edge-back'
        ui_fidelity.freeze_gate(self.state, module)
        module.update(code_baseline='current-code', build_artifacts=[result['rounds'][0]['hap']])
        self.visual_run_root, frozen = self.n.bind_execution(result)
        self.visual_assignment = {'assignment_id': 'capture-assignment', 'fencing_token': 'capture-fence'}
        query = {**path, 'run_id': 'r1', 'module_id': 'M001', 'freeze_id': 'freeze-1',
                 'code_baseline': module['code_baseline'],
                 'frozen_interaction': ui_fidelity.frozen_interaction(module, path),
                 'run_root': self.visual_run_root, 'frozen_visual_evidence': frozen,
                 'execution_assignment': self.visual_assignment,
                 'expected_assertions': [{'assertion_id': 'VISUAL', 'expected': True}]}
        return result, module, path, query

    def report(self, result, query):
        ref = file_ref(self.n.write('target/alignment-result.json', result))
        return lean_visual_adapter.report(query, ref, self.n.target, ['settings-edge-back'])

    def test_formal_green_rechecks_complete_frozen_interaction(self):
        result, module, path, query = self.alignment_query()
        report = self.report(result, query)
        test_validation.visual_result(module, path, report, report, run_root=self.visual_run_root,
                                      assignment=self.visual_assignment)
        for field, value in [('action', 'tap_exit_button'), ('from', {'page_id': 'other', 'state_id': 'base'}),
                             ('expected', {'app_foreground': False}), ('spec_ref', 'unrelated-spec')]:
            changed = copy.deepcopy(result)
            changed['required_interactions'][0][field] = value
            if field == 'action': changed['interaction_checks'][0]['action'] = value
            if field == 'expected': changed['interaction_checks'][0]['observed'] = value
            # The native import contract still accepts its internally consistent ID list.
            self.assertEqual(self.n.import_alignment(changed)['settings:base:viewport']['quality'], 'green-passed')
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'requirement differs'):
                self.report(changed, query)
        report = self.report(result, query)  # Restore the original artifact after the mutation checks.
        forged = copy.deepcopy(report)
        forged['visual_alignment']['required_interaction']['action'] = 'tap_exit_button'
        with self.assertRaisesRegex(Rejected, 'requirement differs'):
            test_validation.visual_result(module, path, forged, forged, run_root=self.visual_run_root,
                                          assignment=self.visual_assignment)

    def test_module_frozen_definition_wins_over_path_self_report(self):
        _, module, path, query = self.alignment_query()
        path['frozen_interaction'] = {**query['frozen_interaction'], 'action': 'tap_exit_button'}
        module['frozen_interactions'] = {path['path_id']: path['frozen_interaction']}
        self.assertEqual(ui_fidelity.frozen_interaction(module, path), query['frozen_interaction'])
        self.assertIsNone(ui_fidelity.frozen_interaction({}, {'kind': 'automation'}))

    def test_audit_scope_retains_only_selected_module_and_global_contracts(self):
        _, module, path, query = self.alignment_query()
        code = file_ref(self.n.write('target/Main.kt', 'fun main() = Unit'))
        module.update(code_files=[code], code_baseline=baseline([code]), freeze_id='freeze-1',
                      results={path['path_id']: {'quality': 'yellow-blocked'}})
        global_contract = {**query['frozen_interaction'], 'id': 'global-back'}
        global_path = {**path, 'path_id': 'GLOBAL-VISUAL', 'interaction_id': 'global-back',
                       'frozen_interaction': global_contract}
        state = {'modules': {'M001': module}, 'global_paths': [global_path]}
        scope = ledger.audit_scope(state)
        self.assertEqual(ui_fidelity.frozen_interaction(scope, path), query['frozen_interaction'])
        self.assertEqual(ui_fidelity.frozen_interaction(scope, global_path), global_contract)
        module['results'][path['path_id']]['quality'] = 'green-passed'
        scope = ledger.audit_scope(state)
        self.assertNotIn(path['path_id'], scope['frozen_interactions'])
        global_path.pop('frozen_interaction')
        with self.assertRaises(Rejected):
            ledger.audit_scope(state)

    def test_red_yellow_do_not_require_new_green_proof(self):
        original, module, path, query = self.alignment_query()
        query.pop('frozen_interaction')
        for overall, status, quality in [('NEEDS_IMPLEMENTATION_FIX', 'FAILED', 'red-bug'),
                                         ('BLOCKED', 'BLOCKED', 'yellow-blocked')]:
            result = copy.deepcopy(original)
            result.update(status=overall, issues=[{'owner': 'lean', 'summary': 'observed issue'}])
            result['interaction_checks'][0].update(status=status, observed={'app_foreground': False})
            report = self.report(result, query)
            self.assertEqual(report['quality'], quality)
            test_validation.visual_result(module, path, report, report)


if __name__ == '__main__':
    unittest.main()
