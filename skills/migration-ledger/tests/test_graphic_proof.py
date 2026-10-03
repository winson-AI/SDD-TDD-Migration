"""A graphic the target does not copy is measured on the screen or disclosed as a deviation a human approved."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref
import resource_fidelity as rf

VECTOR = ('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp" '
          'android:viewportWidth="24" android:viewportHeight="24"><path android:fillColor="#FF000000" android:pathData="M0,0h24v24h-24z"/></vector>')
APPROVED = 'draw the back arrow as a shape when the vector cannot be reproduced'


class GraphicProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.plan = {'decision_envelope': {'allowed_alternatives': [APPROVED]}}

    def ref(self, name='review.json'):
        path = self.base / name; path.write_text(json.dumps({'inspected': True})); return file_ref(path)

    def item(self, **over):
        item = {'item_id': 'back', 'source_resource': '@drawable/ic_back', 'qualifier': 'base', 'resource_kind': 'vector',
                'resource_strategy': 'manual_exact', 'adaptation_evidence_ref': self.ref()}
        item.update(over)
        return item

    def check(self, cid='back-icon', resource='@drawable/ic_back', qualifier='default'):
        return {'id': cid, 'node_id': 'node:back', 'source_resource': resource, 'qualifier': qualifier}

    def deviation(self, **over):
        return {'alternative': APPROVED, 'kind': 'redraw', 'reason': 'the vector uses a gradient the target cannot express', **over}

    def prove(self, *items, declared=(), carried=()):
        known = {check['id']: (check, 'login:default:viewport') for check in declared}
        rf.require_graphic_proof(list(items), self.plan, known, set(carried))

    def refuses(self, message, *items, **proof):
        with self.assertRaisesRegex(Rejected, message):
            self.prove(*items, **proof)

    def test_exactness_names_how_the_target_differs(self):
        self.assertEqual(rf.exactness({'item_id': 'x'}), 'unrecorded')
        self.assertEqual(rf.exactness(self.item(resource_strategy='exact_vector_xml')), 'exact')
        self.assertEqual(rf.exactness(self.item()), 'non-exact')
        self.assertEqual(rf.exactness(self.item(deviation=self.deviation())), 'approved-deviation')
        self.assertEqual(rf.exactness(self.item(resource_strategy='blocked')), 'blocked')
        self.assertEqual(rf.exactness(self.item(resource_kind='shape')), 'manual')
        self.assertEqual(rf.exactness(self.item(resource_kind='code-drawn')), 'manual')  # not rendered offline: reviewed, not measured
        self.assertEqual(rf.exactness(self.item(resource_kind='animated-vector')), 'manual')
        photo = {'resource_kind': 'asset', 'source_resource_ref': {'path': '/legacy/assets/photo.webp'}}
        self.assertEqual(rf.exactness(self.item(**photo)), 'non-exact')
        font = {'resource_kind': 'asset', 'source_resource_ref': {'path': '/legacy/assets/body.ttf'}}
        self.assertEqual(rf.exactness(self.item(**font)), 'manual')

    def test_a_replaced_graphic_needs_a_measured_check_or_a_deviation_not_neither(self):
        self.refuses('either an image_check .* or an approved deviation', self.item())
        self.refuses('not both and not neither', self.item(image_check='back-icon', deviation=self.deviation()),
                     declared=[self.check()], carried=['back-icon'])
        self.prove(self.item(resource_kind='shape'))  # not a picture: untouched
        self.prove(self.item(resource_strategy='exact_vector_xml'))
        self.prove(self.item(resource_strategy='blocked', blocked_reason='no converter'))

    def test_image_check_must_be_declared_carried_and_about_this_resource(self):
        item = self.item(image_check='back-icon')
        self.prove(item, declared=[self.check()], carried=['back-icon'])
        self.prove(item, declared=[self.check(qualifier='base')], carried=['back-icon'])
        self.refuses('declared by a UI model and carried by a visual path', item)
        self.refuses('declared by a UI model and carried by a visual path', item, declared=[self.check()])
        self.refuses('check of this resource and qualifier', item, declared=[self.check(resource='@drawable/ic_next')], carried=['back-icon'])
        self.refuses('check of this resource and qualifier', item, declared=[self.check(qualifier='xhdpi')], carried=['back-icon'])

    def test_drawing_code_and_animation_keep_their_reviewed_port_and_are_never_measured(self):
        lottie = {'resource_kind': 'asset', 'source_resource_ref': {'path': '/legacy/assets/loading.json'}}
        kinds = [{'resource_kind': kind} for kind in ('code-drawn', 'animated-vector', 'animation-list', 'adaptive-icon')] + [lottie]
        for kind in kinds:
            with self.subTest(kind):
                self.refuses('not rendered offline', self.item(image_check='back-icon', **kind), declared=[self.check()], carried=['back-icon'])
                self.prove(self.item(**kind))  # a reviewed manual port needs no measurement it cannot have
                self.prove(self.item(deviation=self.deviation(), **kind))
                self.refuses('allowed_alternatives', self.item(deviation=self.deviation(alternative='skip it'), **kind))

    def test_a_deviation_is_one_of_the_alternatives_a_human_approved(self):
        self.prove(self.item(deviation=self.deviation()))
        self.prove(self.item(deviation=self.deviation(kind='absent', evidence_refs=[self.ref('screenshot.json')])))
        self.refuses('allowed_alternatives', self.item(deviation=self.deviation(alternative='use a Material icon')))
        self.refuses('allowed_alternatives', self.item(deviation=self.deviation(alternative=None)))
        self.refuses('needs a kind', self.item(deviation=self.deviation(kind='approximate')))
        self.refuses('needs a kind', self.item(deviation=self.deviation(reason=' ')))
        self.refuses('needs a kind', self.item(deviation='redraw'))
        self.plan = {'decision_envelope': {'allowed_alternatives': []}}
        self.refuses('allowed_alternatives', self.item(deviation=self.deviation()))

    def test_deviation_evidence_must_still_match_what_was_cited(self):
        evidence = self.ref('screenshot.json')
        item = self.item(deviation=self.deviation(evidence_refs=[evidence]))
        self.prove(item)
        Path(evidence['path']).write_text('replaced')
        self.refuses('hash mismatch', item)

    def test_a_deviation_only_describes_a_manual_replacement(self):
        self.refuses('manual_exact replacement', self.item(resource_strategy='exact_vector_xml', deviation=self.deviation()))

    def freeze(self, *items, paths=(), alternatives=(APPROVED,)):
        path = self.base / 'analysis.json'
        ui = {'dimension': 'UI', 'status': 'applicable', 'items': [{'item_id': 'login', 'semantic_model': {
            'image_checks': [self.check()], 'ui_evidence': {'coverage': 'login:default:viewport'}}}]}
        path.write_text(json.dumps({'dimensions': [ui, {'dimension': 'Resource', 'status': 'applicable', 'items': list(items)}]}))
        rf.freeze_gate({'legacy_root': str(self.base / 'legacy')},
                       {'plan': {'dimension_analysis_ref': file_ref(path), 'paths': list(paths),
                                 'decision_envelope': {'allowed_alternatives': list(alternatives)}}})

    def resource(self, **over):
        source = self.base / 'legacy/res/drawable/ic_back.xml'
        source.parent.mkdir(parents=True, exist_ok=True); source.write_text(VECTOR)
        return self.item(source_resource_ref=file_ref(source), target_resource=str(self.base / 'target/res/drawable/ic_back.xml'),
                         consumer=str(self.base / 'target/Screen.kt') + '#Back', **over)

    def test_freeze_reads_declared_checks_and_the_visual_paths_that_carry_them(self):
        visual = {'path_id': 'P1', 'kind': 'visual', 'image_check_ids': ['back-icon']}
        self.freeze(self.resource(image_check='back-icon'), paths=[visual])
        with self.assertRaisesRegex(Rejected, 'carried by a visual path'):
            self.freeze(self.resource(image_check='back-icon'), paths=[{'path_id': 'P1', 'kind': 'unit', 'image_check_ids': ['back-icon']}])
        with self.assertRaisesRegex(Rejected, 'carried by a visual path'):
            self.freeze(self.resource(image_check='back-icon'))
        with self.assertRaisesRegex(Rejected, 'either an image_check'):
            self.freeze(self.resource(), paths=[visual])

    def test_freeze_binds_the_deviation_to_the_approved_plan(self):
        self.freeze(self.resource(deviation=self.deviation()))
        with self.assertRaisesRegex(Rejected, 'allowed_alternatives'):
            self.freeze(self.resource(deviation=self.deviation()), alternatives=())


if __name__ == '__main__':
    unittest.main()
