"""Image checks in the frozen plan: what a Spec may declare and which visual paths may carry it."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, check_ref, file_ref, read_json
import lean_visual_adapter
import reference_render
import test_resource_scope as scope_fixtures
import ui_evidence
import ui_fidelity
import semantics


class ImagePlanTests(unittest.TestCase):
    def setUp(self):
        self.s = scope_fixtures.ResourceScopeTests('test_all_actual_indexed_resources_have_source_hashes')
        self.s.setUp(); self.addCleanup(self.s.doCleanups)
        self.n, self.f = self.s.n, self.s.f
        icon = self.n.android / 'app/src/main/res/drawable-xxhdpi/ic_back.png'
        icon.parent.mkdir(parents=True)
        Image.new('RGBA', (72, 72), (0, 0, 0, 255)).save(icon)
        self.f.fixture['tree']['screens'][0]['root']['presentation']['resourceRefs'].append('@drawable/ic_back')
        source = self.n.android / 'app/src/main/java/example/SettingsFragment.kt'
        source.write_text(source.read_text() + '\nfun back() = R.drawable.ic_back\n')
        self.index = self.s.recollect()
        self.out = self.n.write('references/reference.json', '{}').parent
        reference_render.render(self.index, '@drawable/ic_back', 'xxhdpi', self.out)
        self.check = {'id': 'back-arrow', 'node_id': 'node:settings.row', 'source_resource': '@drawable/ic_back', 'qualifier': 'xxhdpi',
                      'reference': {'render_ref': file_ref(self.out / 'reference.json')}, 'target': {'selector': {'resource-id': 'back'}}}
        self.coverage = self.f.evidence['coverage']

    def declare(self, *checks):
        self.f.model['image_checks'] = [copy.deepcopy(c) for c in checks]

    def tree(self):
        return read_json(check_ref(self.f.evidence['ui_tree_ref']))

    def defect(self, message, **change):
        check = {**copy.deepcopy(self.check), **change}
        with self.assertRaisesRegex(Rejected, message):
            ui_evidence.validate_image_checks({'image_checks': [check]}, self.tree(), self.index)

    def asset_path(self, **over):
        return {'path_id': 'PI', 'kind': 'visual', 'case_id': 'C1', 'name': 'icons', 'coverage': self.coverage,
                'node_ids': ['node:settings.row'], 'image_check_ids': ['back-arrow'], **over}

    def gate(self, *paths):
        module = self.f.module()
        module['plan']['paths'].extend(paths)
        ui_fidelity.baseline_gate(self.f.state, module)
        return module

    def without_runnable_legacy(self):
        tree, evidence = self.f.fixture['tree'], self.f.evidence
        tree['generatedFrom'].pop('runtimeIndex'); tree['generatedFrom'].pop('runtimeIndexSha256')
        tree['screens'][0]['root'].pop('runtimeObservations')
        evidence.update(visual_mode='source-only', legacy_executable=False, ui_tree_ref=file_ref(self.n.write('evidence/ui-tree.json', tree)))
        for key in ('runtime_index_ref', 'baseline_refs', 'capture_manifest_ref'):
            evidence.pop(key)

    # ------------------------------------------------------------------ what a Spec may declare

    def test_a_declared_check_is_accepted_and_the_model_is_validated_with_it(self):
        self.assertEqual(ui_evidence.validate_image_checks({'image_checks': [self.check]}, self.tree(), self.index), ['back-arrow'])
        self.assertEqual(ui_evidence.validate_image_checks({}, self.tree(), self.index), [])
        self.assertEqual(ui_evidence.image_check_reference(self.check)['sha256'], read_json(check_ref(self.check['reference']['render_ref']))['png_ref']['sha256'])
        self.assertEqual(ui_fidelity.declared_image_checks({'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'semantic_model': {'image_checks': [self.check], 'ui_evidence': {'coverage': self.coverage}}}]}]}), {'back-arrow': (self.check, self.coverage)})

    def test_a_check_is_a_stable_node_a_resource_a_reference_and_a_selector(self):
        self.defect('stable lowercase id', id='Back Arrow')
        self.defect('needs a stable node', node_id='back')
        self.defect('names a node the UI tree does not have', node_id='node:settings.gone')
        self.defect('needs source_resource and qualifier', qualifier='')
        self.defect('needs target.selector', target={'selector': {'resource-id': ''}})
        self.defect('needs target.selector', target={})
        self.defect('capture_index must be a non-negative', target={'selector': {'resource-id': 'back'}, 'capture_index': -1})
        self.defect('shape_iou_min must be between', tolerance={'shape_iou_min': 2})

    def test_the_reference_must_be_the_rendering_of_this_resource_from_the_indexed_file(self):
        self.defect('rendering of its source_resource and qualifier', source_resource='@drawable/ic_next')
        self.defect('rendering of its source_resource and qualifier', qualifier='hdpi')
        other = self.n.write('references/other/reference.json', {'producer': 'a-person', 'source_resource': '@drawable/ic_back', 'qualifier': 'xxhdpi'})
        self.defect('rendering of its source_resource', reference={'render_ref': file_ref(other)})
        index = copy.deepcopy(self.index)
        index['resources'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(Rejected, 'source index does not hold'):
            ui_evidence.validate_image_checks({'image_checks': [self.check]}, self.tree(), index)

    def test_duplicate_ids_and_non_lists_are_rejected(self):
        for declared, message in (({'image_checks': [self.check, self.check]}, 'duplicate image check id'), ({'image_checks': {}}, 'must be a list')):
            with self.subTest(message), self.assertRaisesRegex(Rejected, message):
                ui_evidence.validate_image_checks(declared, self.tree(), self.index)

    def test_the_semantic_model_validates_its_checks_with_the_rest_of_the_item(self):
        self.declare(self.check)
        item = {'dimension': 'UI', 'item_id': 'UI-1', 'target_strategy': 'new', 'semantic_model': {
            **self.f.model, 'source': {'origin': 'authored', 'evidence_refs': []}, 'implementation_location': {'target_path': str(self.n.target / 'Screen.kt')},
            'model_ref': file_ref(self.n.write('evidence/ui-spec.json', {'root': {'type': 'Column'}}))}}
        semantics.validate_item(item)
        item['semantic_model']['image_checks'][0]['id'] = 'BAD'
        with self.assertRaisesRegex(Rejected, 'stable lowercase id'):
            semantics.validate_item(item)

    # ------------------------------------------------------------------ which visual paths may carry them

    def test_a_declared_check_needs_a_visual_path_that_carries_it(self):
        self.declare(self.check)
        with self.assertRaisesRegex(Rejected, 'declared image checks need a visual path carrying device proof: back-arrow'):
            self.gate()
        self.gate(self.asset_path())

    def test_an_asset_path_adds_to_the_baseline_comparison_of_a_runnable_legacy_never_replaces_it(self):
        self.declare(self.check)
        module = self.f.module()
        module['plan']['paths'] = [self.asset_path()]
        with self.assertRaisesRegex(Rejected, 'runtime UI targets lack visual paths: ' + self.coverage):
            ui_fidelity.baseline_gate(self.f.state, module)

    def test_without_a_runnable_legacy_the_asset_path_is_the_visual_proof(self):
        self.without_runnable_legacy()
        self.declare(self.check)
        module = self.f.module()
        self.assertEqual(module['plan']['paths'], [])
        with self.assertRaisesRegex(Rejected, 'declared image checks need a visual path'):
            ui_fidelity.baseline_gate(self.f.state, module)
        module['plan']['paths'] = [self.asset_path()]
        ui_fidelity.baseline_gate(self.f.state, module)

    def test_a_path_with_a_baseline_may_carry_checks_of_the_nodes_the_baseline_observes(self):
        root = {**self.check, 'id': 'root-icon', 'node_id': 'node:settings.root'}
        self.declare(root)
        module = self.f.module()
        module['plan']['paths'][0]['image_check_ids'] = ['root-icon']
        ui_fidelity.baseline_gate(self.f.state, module)
        self.declare(self.check)  # its node is in the tree but the legacy capture did not observe it
        module = self.f.module()
        module['plan']['paths'][0].update(image_check_ids=['back-arrow'], node_ids=['node:settings.root', 'node:settings.row'])
        with self.assertRaisesRegex(Rejected, 'nodes do not belong to target'):
            ui_fidelity.baseline_gate(self.f.state, module)

    def test_an_asset_path_names_a_frozen_target_the_nodes_of_it_and_the_node_of_its_check(self):
        self.declare(self.check)
        for over, message in (({'coverage': 'elsewhere:base:viewport'}, 'must name a frozen UI target'),
                              ({'coverage': None}, 'must name a frozen UI target'),
                              ({'node_ids': ['node:settings.gone']}, 'nodes do not belong to target'),
                              ({'node_ids': []}, 'visual path node_ids'),
                              ({'node_ids': ['node:settings.root']}, 'nodes must include the node of image check back-arrow'),
                              ({'image_check_ids': ['ghost']}, 'does not belong to its target')):
            with self.subTest(over), self.assertRaisesRegex(Rejected, message):
                self.gate(self.asset_path(**over))

    def test_the_frozen_checks_of_a_path_come_from_the_analysis_that_owns_it(self):
        self.declare(self.check)
        module = self.f.module()
        module['plan']['paths'].append(self.asset_path())
        self.assertEqual(ui_fidelity.frozen_image_checks(module, module['plan']['paths'][-1]), [self.check])
        self.assertEqual(ui_fidelity.frozen_image_checks(module, module['plan']['paths'][0]), [])

    # ------------------------------------------------------------------ a path with a baseline and image checks

    def combined(self, alignment, image):
        query = {'kind': 'visual', 'coverage': self.coverage, 'node_ids': ['node:settings.row'], 'baseline_ref': {'path': 'baseline.png', 'sha256': 'b' * 64},
                 'frozen_image_checks': [self.check], 'run_id': 'r1', 'module_id': 'M001', 'path_id': 'PV', 'freeze_id': 'F1',
                 'code_baseline': 'code-1', 'expected_assertions': [{'assertion_id': 'VISUAL', 'expected': True}]}
        baseline_proof = {'coverage': self.coverage, 'node_ids': query['node_ids'], 'baseline_ref': query['baseline_ref'], 'code_baseline': 'code-1',
                          'hap_ref': {'path': 'app.hap', 'sha256': 'a' * 64}, 'linked_refs': [{'path': 'screen.png', 'sha256': 'c' * 64}]}
        cause = {'category': 'visual-alignment', 'summary': 'x', 'confidence': 'observed', 'owner': 'fixer', 'next_action': 'diagnose', 'evidence_refs': []}
        image_proof = {'capture_evidence': {'captures': []}, 'checks': [{'id': 'back-arrow', 'status': 'MATCH'}]}
        parts = {'green-passed': (None, baseline_proof), 'red-bug': (cause, baseline_proof), 'yellow-blocked': (cause, baseline_proof)}
        with patch.object(lean_visual_adapter, 'alignment_part', return_value=(alignment, *parts[alignment])), \
                patch.object(lean_visual_adapter, 'image_part', return_value=(image, *(parts[image][0:1] + (image_proof,)))), \
                patch.object(lean_visual_adapter.lean_adapter, 'linked_refs', return_value=[{'path': 'crop.png', 'sha256': 'd' * 64}]):
            return lean_visual_adapter.report(query, {'path': 'alignment.json', 'sha256': 'e' * 64}, self.n.target, [], {'path': 'parity.json', 'sha256': 'f' * 64})

    def test_the_weaker_result_decides_and_the_proof_keeps_both_parts(self):
        report = self.combined('green-passed', 'green-passed')
        self.assertEqual(report['quality'], 'green-passed')
        proof = report['visual_alignment']
        self.assertEqual(proof['baseline_ref']['sha256'], 'b' * 64)
        self.assertEqual(proof['image_parity']['checks'], [{'id': 'back-arrow', 'status': 'MATCH'}])
        self.assertEqual([r['path'] for r in proof['linked_refs']], ['screen.png', 'crop.png'])
        for alignment, image, expected in (('green-passed', 'red-bug', 'red-bug'), ('red-bug', 'green-passed', 'red-bug'),
                                           ('green-passed', 'yellow-blocked', 'yellow-blocked'), ('yellow-blocked', 'red-bug', 'red-bug')):
            with self.subTest(alignment=alignment, image=image):
                combined = self.combined(alignment, image)
                self.assertEqual(combined['quality'], expected)
                self.assertEqual([a['passed'] for a in combined['assertions']], [False])
                self.assertEqual(combined['root_cause']['category'], 'visual-alignment')

    def test_a_visual_path_needs_a_baseline_or_checks(self):
        with self.assertRaisesRegex(Rejected, 'a baseline, image checks, or both'):
            lean_visual_adapter.report({'kind': 'visual', 'coverage': self.coverage, 'node_ids': ['n']}, None, self.n.target)
        with self.assertRaisesRegex(Rejected, 'needs the image-parity report'):
            lean_visual_adapter.report({'kind': 'visual', 'coverage': self.coverage, 'node_ids': ['n'], 'frozen_image_checks': [self.check],
                                        'expected_assertions': [{'assertion_id': 'VISUAL', 'expected': True}]}, None, self.n.target)


if __name__ == '__main__':
    unittest.main()
