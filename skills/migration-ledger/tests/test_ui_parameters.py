"""The parameter sheet: what the legacy UI gives each component and layer, read mechanically and classed by what the target must do with it."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref
from lean_tools import collect_ui_sources
import parameter_fixture
import parameter_records as records
import ui_parameters

A = 'xmlns:android="http://schemas.android.com/apk/res/android"'


class RecordTests(unittest.TestCase):
    def test_a_literal_is_a_typed_value_with_its_unit(self):
        for text, expected in (('16dp', {'type': 'dimension', 'value': 16, 'unit': 'dp'}), ('12.5dip', {'type': 'dimension', 'value': 12.5, 'unit': 'dp'}),
                               ('18sp', {'type': 'dimension', 'value': 18, 'unit': 'sp'}), ('50%', {'type': 'dimension', 'value': 50, 'unit': '%'}),
                               ('#abc', {'type': 'color', 'value': '#FFAABBCC'}), ('#8abc', {'type': 'color', 'value': '#88AABBCC'}),
                               ('#3390ec', {'type': 'color', 'value': '#FF3390EC'}), ('#223390EC', {'type': 'color', 'value': '#223390EC'}),
                               ('2', {'type': 'number', 'value': 2}), ('0.5', {'type': 'number', 'value': 0.5}),
                               ('true', {'type': 'boolean', 'value': True}), ('match_parent', {'type': 'keyword', 'value': 'match_parent'}),
                               ('center|bottom', {'type': 'keyword', 'value': 'center|bottom'}), ('@null', {'type': 'keyword', 'value': 'null'}),
                               ('@dimen/gap', {'type': 'reference', 'ref': '@dimen/gap'}), ('@+id/title', {'type': 'reference', 'ref': '@id/title'}),
                               ('?attr/inkColor', {'type': 'token', 'token': '?attr/inkColor'})):
            self.assertEqual(records.literal(text), expected, text)
        self.assertEqual(records.literal('12', 'text'), {'type': 'string', 'value': '12'})  # what a person reads is text, whatever it looks like
        self.assertEqual(records.literal('Back', 'contentDescription'), {'type': 'string', 'value': 'Back'})

    def test_a_drawable_states_its_layers_by_place(self):
        root = ET.fromstring(f'<layer-list {A}><item android:left="4dp"><shape android:shape="oval"><solid android:color="#fff"/></shape></item>'
                             f'<item android:drawable="@drawable/ic_dot" android:gravity="center"/></layer-list>')
        rows = {(row['path'], row['name']): {k: v for k, v in row.items() if k not in ('path', 'name')} for row in records.xml_parameters(root)}
        self.assertEqual(rows[('layer-list/item[1]', 'left')], {'type': 'dimension', 'value': 4, 'unit': 'dp'})
        self.assertEqual(rows[('layer-list/item[1]/shape', 'shape')], {'type': 'keyword', 'value': 'oval'})
        self.assertEqual(rows[('layer-list/item[1]/shape/solid', 'color')], {'type': 'color', 'value': '#FFFFFFFF'})
        self.assertEqual(rows[('layer-list/item[2]', 'drawable')], {'type': 'reference', 'ref': '@drawable/ic_dot'})

    def test_a_setter_argument_is_a_length_a_colour_a_text_a_reference_a_keyword_a_token_or_an_expression(self):
        for text, unit, colour, expected in (
                ('Screen.dp(16)', None, False, {'type': 'dimension', 'value': 16, 'unit': 'dp'}),
                ('dpToPx(8.5f)', None, False, {'type': 'dimension', 'value': 8.5, 'unit': 'dp'}), ('14.sp', None, False, {'type': 'dimension', 'value': 14, 'unit': 'sp'}),
                ('48', 'dp', False, {'type': 'dimension', 'value': 48, 'unit': 'dp'}), ('0.5f', None, False, {'type': 'number', 'value': 0.5}),
                ('0xff3390ec', None, False, {'type': 'color', 'value': '#FF3390EC'}), ('0x3390ec', None, True, {'type': 'color', 'value': '#FF3390EC'}),
                ('Color.parseColor("#abc")', None, True, {'type': 'color', 'value': '#FFAABBCC'}), ('"Next"', None, False, {'type': 'string', 'value': 'Next'}),
                ('getString("OK", R.string.ok)', None, False, {'type': 'reference', 'ref': '@string/ok'}),
                ('ctx.getResources().getColor(R.color.brand)', None, True, {'type': 'reference', 'ref': '@color/brand'}),
                ('Gravity.CENTER | Gravity.TOP', None, False, {'type': 'keyword', 'value': 'Gravity.CENTER | Gravity.TOP'}),
                ('View.GONE', None, False, {'type': 'keyword', 'value': 'View.GONE'}), ('null', None, False, {'type': 'keyword', 'value': 'null'})):
            self.assertEqual(records.expression(text, unit, colour), expected, text)
        token = records.expression('Palette.color(Palette.ink, provider)')
        self.assertEqual((token['type'], token['token']), ('token', 'Palette.ink'))  # the field is the value; what receives it is not
        self.assertEqual(records.expression('Fonts.bold()')['token'], 'Fonts.bold')
        for text in ('visible ? 1f : 0f', 'dp(isTablet ? 20 : 16)', 'flag ? R.string.a : R.string.b', 'Util.dp(margin)', 'width + 200', 'progress',
                     'String.format(Locale.getDefault(), "%d", count)'):
            self.assertEqual(records.expression(text)['type'], 'expression', text)

    def test_setters_property_assignments_and_layout_parameters_are_read_with_their_owner(self):
        text = parameter_fixture.FILES['java/demo/Home.kt']
        rows = {(row['receiver'], row['name']): row for row in records.code_parameters(text, 'demo/Home.kt', helpers=parameter_fixture.HELPERS)}
        self.assertEqual({k: rows[('title', 'textSize')][k] for k in ('type', 'value', 'unit', 'symbol')},
                         {'type': 'dimension', 'value': 20, 'unit': 'dp', 'symbol': 'Home.build'})
        self.assertEqual([rows[('title', name)]['value'] for name in ('paddingLeft', 'paddingTop', 'paddingRight', 'paddingBottom')], [16, 0, 16, 0])
        self.assertEqual(rows[('title', 'text')]['ref'], '@string/home_title')
        self.assertEqual((rows[('title', 'layout_height')]['value'], rows[('title', 'layout_height')]['unit']), (48, 'dp'))  # the helper's unit
        self.assertEqual(rows[('title', 'layout_width')]['value'], 'Frames.MATCH')
        self.assertEqual(rows[('title', 'marginLeft')]['value'], 16)
        self.assertEqual(rows[('badge', 'alpha')]['value'], 0.8)  # a Kotlin property assignment
        self.assertEqual(rows[('footer', 'textSize')]['symbol'], 'Home.Legacy.old')
        self.assertEqual(records.code_parameters('// title.setAlpha(0.2f)\nval s = "x.setAlpha(1f)"\n', 'demo/A.kt'), [])
        java = records.code_parameters('class A { void f() { this.alpha = 0.5f; root.addView(v, new FrameLayout.LayoutParams(MATCH_PARENT, dp(48))); } }', 'A.java')
        self.assertEqual([(r['receiver'], r['name'], r['type']) for r in java], [('v', 'layout_height', 'dimension'), ('v', 'layout_width', 'keyword')])


class SheetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.args = parameter_fixture.build(self.root / 'android')
        self.index = collect_ui_sources.collect(self.args)

    def rows(self, scope=None):
        return {row['id']: row for row in ui_parameters.sheet(self.index, None, scope)}

    def test_the_collector_records_setter_values_and_drawable_layers(self):
        source = next(s for s in self.index['sourceFiles'] if s['path'].endswith('Home.kt'))
        self.assertIn(('title', 'textSize'), {(p['receiver'], p['name']) for p in source['parameters']})
        card = next(r for r in self.index['resources'] if r['ref'] == '@drawable/bg_card')
        self.assertIn({'path': 'shape/corners', 'name': 'radius', 'type': 'dimension', 'value': 8, 'unit': 'dp'}, card['parameters'])
        self.assertNotIn('parameters', next(r for r in self.index['resources'] if r['ref'] == '@drawable/ic_back'))  # a picture has no layers

    def test_a_layout_attribute_is_a_value_a_link_a_layer_a_picture_or_a_keyword(self):
        rows = self.rows()
        self.assertEqual({k: rows['layout:home/LinearLayout1.ImageView1.layout_width'][k] for k in ('class', 'value', 'unit')},
                         {'class': 'value', 'value': 24, 'unit': 'dp'})
        self.assertEqual(rows['layout:home/LinearLayout1.padding'], {**rows['layout:home/LinearLayout1.padding'], 'class': 'linked', 'uses': 'values:dimen/gap'})
        self.assertEqual((rows['values:dimen/gap']['value'], rows['values:dimen/gap']['unit']), (16, 'dp'))
        self.assertEqual((rows['layout:home/LinearLayout1.background']['class'], rows['layout:home/LinearLayout1.background']['uses']), ('layer', '@drawable/bg_card'))
        self.assertEqual((rows['layout:home/LinearLayout1.ImageView1.src']['class'], rows['layout:home/LinearLayout1.ImageView1.src']['uses']), ('picture', '@drawable/ic_back'))
        self.assertEqual(rows['layout:home/LinearLayout1.orientation']['class'], 'keyword')
        self.assertEqual((rows['layout:home/LinearLayout1.ImageView1.contentDescription']['type'], rows['layout:home/LinearLayout1.ImageView1.contentDescription']['value']), ('string', 'Back'))
        self.assertEqual(rows['layout:home/title.text']['origin'], {'path': 'app/src/main/res/layout/home.xml', 'selector': "/LinearLayout[1]/TextView[@android:id='@+id/title']"})

    def test_a_style_fills_what_the_node_does_not_state_and_a_theme_attribute_is_followed_to_its_value(self):
        rows = self.rows()
        size = rows['layout:home/title.textSize']
        self.assertEqual((size['class'], size['uses'], size['via']), ('linked', 'values:dimen/title_size', ['@style/Title']))
        self.assertEqual(rows['layout:home/title.maxLines']['value'], 2)  # the node's own attribute wins over the style's 1
        self.assertNotIn('via', rows['layout:home/title.maxLines'])
        ink = rows['layout:home/title.textColor']
        self.assertEqual((ink['uses'], ink['via']), ('values:color/ink', ['?attr/inkColor']))
        self.assertEqual((rows['values:color/ink']['class'], rows['values:color/ink']['uses']), ('linked', 'values:color/brand'))  # an alias is followed
        self.assertEqual(rows['values:color/brand']['value'], '#FF3390EC')

    def test_a_theme_attribute_with_no_single_value_stays_a_token(self):
        values = self.root / 'android/app/src/main/res/values/values.xml'
        values.write_text(values.read_text().replace('</resources>', '<style name="Dark"><item name="inkColor">#FFFFFF</item></style></resources>'))
        rows = {row['id']: row for row in ui_parameters.sheet(collect_ui_sources.collect(self.args))}
        self.assertEqual((rows['layout:home/title.textColor']['class'], rows['layout:home/title.textColor']['token']), ('token', '?attr/inkColor'))

    def test_layers_carry_their_own_parameters_and_follow_what_they_name(self):
        rows = self.rows()
        self.assertEqual({k: rows['layer:drawable/bg_card/shape/corners.radius'][k] for k in ('owner', 'class', 'value', 'unit')},
                         {'owner': 'layer:drawable/bg_card', 'class': 'value', 'value': 8, 'unit': 'dp'})
        self.assertEqual(rows['layer:drawable/bg_card/shape/solid.color']['uses'], 'values:color/brand')
        self.assertEqual(rows['layer:color/tint/selector/item[1].color']['value'], '#FFFF0000')
        self.assertEqual(rows['layer:color/tint/selector/item[1].state_pressed']['class'], 'keyword')

    def test_code_gives_values_tokens_expressions_and_structure(self):
        rows = self.rows()
        self.assertEqual({k: rows['code:Home/title.textSize'][k] for k in ('owner', 'class', 'value', 'unit')},
                         {'owner': 'code:Home/title', 'class': 'value', 'value': 20, 'unit': 'dp'})
        self.assertEqual(rows['code:Home/title.text']['uses'], 'values:string/home_title')
        self.assertEqual((rows['code:Home/title.textColor']['class'], rows['code:Home/title.textColor']['token']), ('token', 'Palette.ink'))
        self.assertEqual(rows['code:Home/title.alpha']['class'], 'expression')
        self.assertEqual(rows['code:Home/title.paddingTop']['class'], 'keyword')  # a zero length is the absence of a gap
        self.assertEqual(rows['code:Home/title.paddingLeft']['class'], 'value')
        self.assertEqual(rows['code:Home/title.layout_gravity']['class'], 'keyword')
        self.assertEqual(rows['code:Home.Legacy/footer.textSize']['origin']['path'], 'app/src/main/java/demo/Home.kt')

    def test_a_text_is_a_value_with_its_other_locales_and_only_texts_in_use_are_listed(self):
        rows = self.rows()
        title = rows['values:string/home_title']
        self.assertEqual((title['class'], title['type'], title['value'], title['variants']), ('value', 'string', 'Home', {'zh': '首页'}))
        self.assertNotIn('values:string/unused', rows)

    def test_a_repeated_setter_keeps_each_occurrence(self):
        source = self.root / 'android/app/src/main/java/demo/Home.kt'
        source.write_text(source.read_text().replace('badge.alpha = 0.8f', 'badge.alpha = 0.8f\n        badge.alpha = 0.4f'))
        rows = {row['id']: row for row in ui_parameters.sheet(collect_ui_sources.collect(self.args))}
        self.assertEqual((rows['code:Home/badge.alpha']['value'], rows['code:Home/badge.alpha#2']['value']), (0.8, 0.4))

    def test_code_a_reviewer_scoped_out_gives_no_parameters(self):
        evidence = self.root / 'review.json'; evidence.write_text('{}')
        scope = {'usage_exclusions': [{'symbol': 'Home.Legacy', 'reason': 'a retired screen', 'evidence_refs': [file_ref(evidence)]}]}
        self.assertIn('code:Home.Legacy/footer.textSize', self.rows())
        self.assertNotIn('code:Home.Legacy/footer.textSize', self.rows(scope))

    def test_a_key_is_the_id_as_an_identifier(self):
        self.assertEqual(ui_parameters.key('layout:home/title.textSize'), 'layout_home_title_textSize')
        self.assertEqual(ui_parameters.key('layer:drawable/bg_card/selector/item[2].color'), 'layer_drawable_bg_card_selector_item_2_color')
        self.assertEqual(ui_parameters.key('code:Home/badge.alpha#2'), 'code_Home_badge_alpha_2')
        keys = [ui_parameters.key(pid) for pid in self.rows()]
        self.assertEqual(len(set(keys)), len(keys))

    # ------------------------------------------------------------------ the sheet of a module

    def analysis(self, **ui):
        index_ref = file_ref(self.write('index.json', self.index))
        return {'module_id': 'M001', 'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'UI-1', 'semantic_model': {'ui_evidence': {'source_index_ref': index_ref}}},
            {'item_id': 'UI-2', 'semantic_model': {'ui_evidence': {'source_index_ref': index_ref}}}], **ui}]}

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def test_a_module_sheet_holds_each_parameter_once_and_is_recomputed_at_freeze(self):
        analysis = self.analysis()
        document = ui_parameters.derive(analysis)
        self.assertEqual((document['producer'], document['module_id'], document['convention']), ('sdd-parameter-sheet', 'M001', None))
        self.assertEqual([p['id'] for p in document['parameters']], sorted(self.rows()))
        analysis = self.analysis(parameter_sheet_ref=file_ref(self.write('sheet.json', document)))
        ui_parameters.freeze_check(analysis)
        self.assertEqual(len(ui_parameters.parameters(analysis)), len(document['parameters']))
        for change in (lambda d: d['parameters'][0].update(value=99), lambda d: d['parameters'].pop(), lambda d: d.update(module_id='M002')):
            edited = copy.deepcopy(document); change(edited)
            with self.assertRaisesRegex(Rejected, 'differs from the one its UI evidence gives'):
                ui_parameters.freeze_check(self.analysis(parameter_sheet_ref=file_ref(self.write('sheet.json', edited))))
        with self.assertRaisesRegex(Rejected, 'must name a derived parameter sheet'):
            ui_parameters.load(self.analysis(parameter_sheet_ref=file_ref(self.write('sheet.json', {'parameters': []}))))
        self.assertIsNone(ui_parameters.load(self.analysis()))

    def test_the_outline_says_what_a_spec_still_has_to_decide(self):
        outline = ui_parameters.outline(ui_parameters.derive(self.analysis())['parameters'])
        self.assertEqual(outline['tokens'], ['Fonts.bold', 'Palette.ink'])
        self.assertEqual(outline['expressions'], [{'id': 'code:Home/title.alpha', 'text': 'if (visible) 1f else 0f'}])
        self.assertGreater(outline['counts']['value'], 10)


if __name__ == '__main__':
    unittest.main()
