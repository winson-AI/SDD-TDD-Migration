"""Display-bearing resource signals: nested drawables, non-layout XML, theme attributes, dynamic image sources, facts."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import resource_facts
import resource_signals
from lean_tools import collect_ui_sources

VECTOR = ('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp" '
          'android:viewportWidth="24" android:viewportHeight="24"><path android:fillColor="%s" android:pathData="M0,0h24v24h-24z"/></vector>')


def png(width, height, mode='RGBA'):
    out = io.BytesIO()
    Image.new(mode, (width, height), (10, 20, 30, 255)[:len(mode)]).save(out, format='PNG')
    return out.getvalue()


class FactsTests(unittest.TestCase):
    def test_raster_headers_match_the_decoder(self):
        cases = (('RGBA', 'PNG', {}), ('RGB', 'PNG', {}), ('RGB', 'JPEG', {}), ('RGBA', 'WEBP', {'lossless': True}),
                 ('RGB', 'WEBP', {'lossless': False, 'quality': 80}), ('RGBA', 'WEBP', {'lossless': False}), ('P', 'GIF', {}))
        for mode, kind, options in cases:
            with self.subTest(kind=kind, mode=mode, options=options):
                out = io.BytesIO()
                Image.new(mode, (72, 40), 0 if mode == 'P' else (200, 10, 10, 128)[:len(mode)]).save(out, format=kind, **options)
                parsed = resource_facts.raster_facts(out.getvalue())
                self.assertEqual((parsed['format'], parsed['width'], parsed['height']), (kind.lower(), 72, 40))
                if mode == 'RGBA':
                    self.assertIs(parsed['alpha'], True)
                elif kind != 'GIF':
                    self.assertIs(parsed['alpha'], False)
        self.assertIsNone(resource_facts.raster_facts(b'not an image at all'))

    def test_density_family_gives_the_size_in_dp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ic_back.png'
            path.write_bytes(png(72, 72))
            facts = resource_facts.file_facts(path, 'night-xxhdpi')
            self.assertEqual((facts['density'], facts['dp']), (3.0, [24.0, 24.0]))
            self.assertNotIn('dp', resource_facts.file_facts(path, 'nodpi'))

    def test_vector_and_animation_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            vector = Path(tmp) / 'v.xml'
            vector.write_text(VECTOR % '#FF000000')
            facts = resource_facts.file_facts(vector)
            self.assertEqual((facts['format'], facts['size_dp'], facts['viewport'], facts['paths']), ('vector-xml', [24.0, 24.0], [24.0, 24.0], 1))
            animation = Path(tmp) / 'a.json'
            animation.write_text(json.dumps({'v': '5', 'fr': 30, 'ip': 0, 'op': 60, 'w': 200, 'h': 100, 'layers': [{}, {}]}))
            facts = resource_facts.file_facts(animation)
            self.assertEqual((facts['format'], facts['width'], facts['height'], facts['duration_s'], facts['layers']),
                             ('animation-json', 200, 100, 2.0, 2))
            other = Path(tmp) / 'o.json'
            other.write_text('{"a": 1}')
            self.assertEqual(resource_facts.file_facts(other)['format'], 'json')

    def test_xml_references_keep_where_and_for_which_state(self):
        root = resource_facts.ET.fromstring(
            '<selector xmlns:android="http://schemas.android.com/apk/res/android">'
            '<item android:state_selected="true" android:drawable="@drawable/on"/>'
            '<item android:drawable="@drawable/off" android:tint="?attr/tintColor"/><item android:id="@+id/node"/></selector>')
        found = {(r['ref'], r['via'], json.dumps(r.get('when'))) for r in resource_facts.xml_references(root)}
        self.assertEqual(found, {('@drawable/on', 'item/drawable', '{"state_selected": "true"}'),
                                 ('@drawable/off', 'item/drawable', 'null'), ('?attr/tintColor', 'item/tint', 'null')})


class CollectorSignalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.main = self.root / 'app/src/main'

    def write(self, name, text):
        path = self.main / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
        return path

    def project(self, code=''):
        self.write('res/layout/home.xml',
                   '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android" '
                   'xmlns:app="http://schemas.android.com/apk/res-auto" xmlns:tools="http://schemas.android.com/tools">'
                   '<ImageView android:id="@+id/logo" android:src="@drawable/ic_logo" android:scaleType="centerCrop" '
                   'android:tint="?attr/iconTint" android:background="@drawable/bg_card"/>'
                   '<ImageButton android:id="@+id/toggle" app:srcCompat="@drawable/ic_toggle"/>'
                   '<ImageView android:id="@+id/bound" android:src="@{item.iconRes}"/>'
                   '<ImageView android:id="@+id/remote" tools:src="@tools:sample/avatars"/></LinearLayout>')
        self.write('res/drawable/ic_logo.xml', VECTOR % '@color/brand')
        self.write('res/drawable-night/ic_logo.xml', VECTOR % '@color/brand')
        self.write('res/drawable/ic_toggle.xml',
                   '<selector xmlns:android="http://schemas.android.com/apk/res/android">'
                   '<item android:state_selected="true" android:drawable="@drawable/ic_on"/>'
                   '<item android:drawable="@drawable/ic_off"/></selector>')
        self.write('res/drawable/bg_card.xml',
                   '<shape xmlns:android="http://schemas.android.com/apk/res/android"><solid android:color="@color/card"/>'
                   '<corners android:radius="@dimen/radius"/></shape>')
        for name in ('ic_on', 'ic_off', 'ic_menu', 'ic_setting', 'ic_loading', 'ic_fail', 'ic_row_a', 'ic_row_b'):
            self.write(f'res/drawable/{name}.xml', VECTOR % '#FF000000')
        self.write('res/drawable-xxhdpi/ic_photo.png', png(96, 96))
        self.write('res/mipmap-xxhdpi/ic_app.png', png(144, 144))
        self.write('res/menu/main.xml', '<menu xmlns:android="http://schemas.android.com/apk/res/android">'
                   '<item android:id="@+id/search" android:icon="@drawable/ic_menu"/></menu>')
        self.write('res/xml/prefs.xml', '<PreferenceScreen xmlns:android="http://schemas.android.com/apk/res/android">'
                   '<Preference android:icon="@drawable/ic_setting"/></PreferenceScreen>')
        self.write('res/values/values.xml',
                   '<resources><color name="brand">#FF6200EE</color><color name="card">#FFFFFFFF</color>'
                   '<dimen name="radius">8dp</dimen><string name="title">Title</string>'
                   '<style name="AppTheme" parent="Theme.Base"><item name="iconTint">@color/brand</item></style></resources>')
        self.write('res/raw/spinner.json', json.dumps({'v': '5', 'fr': 30, 'ip': 0, 'op': 60, 'w': 64, 'h': 64, 'layers': []}))
        self.write('assets/banner.png', png(10, 10))
        self.write('AndroidManifest.xml', '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                   '<application android:icon="@mipmap/ic_app" android:label="@string/title"/></manifest>')
        self.write('java/demo/Account.kt', 'data class Account(@SerializedName("avatar_url") val avatarUrl: String, val name: String)\n')
        self.write('java/demo/HomeActivity.kt', code or (
            'package demo\nimport coil.load\nclass HomeActivity {\n'
            '  fun bind(account: Account, kind: String) {\n'
            '    setContentView(R.layout.home)\n'
            '    Glide.with(this).load(account.avatarUrl)\n'
            '        .placeholder(R.drawable.ic_loading).error(R.drawable.ic_fail).circleCrop().into(binding.remote)\n'
            '    Picasso.get().load("https://img.example.com/hero.png").into(hero)\n'
            '    banner.setImageURI(Uri.parse("file:///android_asset/banner.png"))\n'
            '    cover.load(account.coverUrl) { crossfade(true); placeholder(R.drawable.ic_loading) }\n'
            '    val id = resources.getIdentifier("ic_row_" + kind, "drawable", packageName)\n'
            '    row.setImageResource(id)\n'
            '    card.setBackground(ContextCompat.getDrawable(this, R.drawable.bg_card))\n'
            '    logo.scaleType = ImageView.ScaleType.FIT_CENTER\n'
            '    spinner.setAnimation(R.raw.spinner)\n'
            '    photo.setImageResource(R.drawable.ic_photo)\n'
            '    inflater.inflate(R.menu.main, menu)\n'
            '    addPreferencesFromResource(R.xml.prefs)\n'
            '  }\n'
            '  override fun onDraw(canvas: Canvas) { canvas.drawRoundRect(r, 4f, 4f, paint); canvas.drawPath(p, paint) }\n'
            '}\n'))

    def collect(self, **options):
        self.project()
        namespace = dict(android_root=str(self.root), scope='probe', entry=['HomeActivity.kt'], source_file=[], layout=[])
        return collect_ui_sources.collect(SimpleNamespace(**namespace, **options))

    def rows(self, index, ref):
        return [row for row in index['resources'] if row['ref'] == ref]

    def sources(self, index, kind):
        return [row for row in index['imageSources'] if row['kind'] == kind]

    def test_nested_drawables_are_followed_with_their_states_and_parents(self):
        index = self.collect()
        toggle = self.rows(index, '@drawable/ic_toggle')[0]
        self.assertEqual({(r['ref'], tuple(sorted(r.get('when', {}).items()))) for r in toggle['references']},
                         {('@drawable/ic_on', (('state_selected', 'true'),)), ('@drawable/ic_off', ())})
        for ref in ('@drawable/ic_on', '@drawable/ic_off'):
            self.assertEqual(self.rows(index, ref)[0]['via'], ['@drawable/ic_toggle'])
        self.assertEqual({r['ref'] for r in self.rows(index, '@drawable/bg_card')[0]['references']}, {'@color/card', '@dimen/radius'})
        self.assertTrue(self.rows(index, '@color/card') and self.rows(index, '@dimen/radius'))
        self.assertEqual({r['qualifier'] for r in self.rows(index, '@drawable/ic_logo')}, {'default', 'night'})
        self.assertEqual(self.rows(index, '@drawable/ic_logo')[0]['facts']['size_dp'], [24.0, 24.0])

    def test_file_resources_carry_format_size_and_density_facts(self):
        index = self.collect()
        photo = self.rows(index, '@drawable/ic_photo')[0]['facts']
        self.assertEqual((photo['format'], photo['width'], photo['dp']), ('png', 96, [32.0, 32.0]))
        self.assertEqual(self.rows(index, '@raw/spinner')[0]['facts']['duration_s'], 2.0)

    def test_theme_attributes_are_resolved_or_named_as_library_defined(self):
        index = self.collect()
        attrs = {a['ref']: a for a in index['themeAttrs']}
        self.assertEqual(attrs['?attr/iconTint']['status'], 'project')
        self.assertEqual([(d['style'], d['value']) for d in attrs['?attr/iconTint']['definitions']], [('AppTheme', '@color/brand')])
        self.assertTrue(self.rows(index, '@color/brand'))
        self.write('res/layout/lib.xml', '<ImageView xmlns:android="http://schemas.android.com/apk/res/android" '
                   'android:tint="?attr/libraryTint"/>')
        library = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='lib', entry=[], source_file=[], layout=['lib']))
        self.assertEqual([(a['ref'], a['status']) for a in library['themeAttrs']], [('?attr/libraryTint', 'library')])
        self.assertEqual(library['unresolved'], [])

    def test_menu_preference_and_manifest_icons_join_the_scope(self):
        index = self.collect(manifest=['app/src/main/AndroidManifest.xml'])
        self.assertEqual({(d['kind'], d['name']) for d in index['xmlResources']},
                         {('menu', 'main'), ('xml', 'prefs'), ('manifest', 'app/src/main/AndroidManifest.xml')})
        for ref in ('@drawable/ic_menu', '@drawable/ic_setting', '@mipmap/ic_app'):
            self.assertTrue(self.rows(index, ref), ref)
        manifest = next(d for d in index['xmlResources'] if d['kind'] == 'manifest')
        self.assertEqual(manifest['icons'], [{'element': 'application', 'name': None, 'attr': 'android:icon', 'ref': '@mipmap/ic_app'}])
        self.assertNotIn('@string/title', manifest['resourceRefs'])
        self.assertEqual(collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='m', entry=['HomeActivity.kt'],
            source_file=[], layout=[], manifest=['missing.xml']))['unresolved'][-1]['kind'], 'manifest')

    def test_remote_images_record_source_loader_and_the_api_field(self):
        index = self.collect()
        remote = {(r['loader']['library'], r['source']['kind']): r for r in self.sources(index, 'remote-image')}
        glide = remote[('Glide', 'expression')]
        self.assertEqual(glide['source']['value'], 'account.avatarUrl')
        self.assertEqual((glide['loader']['placeholder'], glide['loader']['error'], glide['loader']['transforms'], glide['loader']['target']),
                         (['@drawable/ic_loading'], ['@drawable/ic_fail'], ['circleCrop()'], 'binding.remote'))
        self.assertEqual(glide['api']['field'], 'avatarUrl')
        self.assertEqual([c['jsonKey'] for c in glide['api']['candidates']], ['avatar_url'])
        self.assertTrue(glide['api']['candidates'][0]['declaredIn'].startswith('app/src/main/java/demo/Account.kt:'))
        picasso = remote[('Picasso', 'url-literal')]
        self.assertEqual(picasso['source']['value'], 'https://img.example.com/hero.png')
        self.assertNotIn('api', picasso)
        coil = remote[('Coil', 'expression')]
        self.assertEqual((coil['source']['value'], coil['loader']['placeholder'], coil['loader'].get('transforms')),
                         ('account.coverUrl', ['@drawable/ic_loading'], ['crossfade(true)']))
        for ref in ('@drawable/ic_loading', '@drawable/ic_fail'):
            self.assertTrue(self.rows(index, ref), ref)

    def test_a_project_loader_is_recorded_when_named(self):
        self.project()
        self.write('java/demo/Feed.kt', 'class Feed { fun show(item: Item) { avatarView.setPhoto(item.photoUrl) } }\n')
        found = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='feed', entry=['Feed.kt'], source_file=[],
                                                          layout=[], image_sinks=['setPhoto']))
        row = self.sources(found, 'remote-image')[0]
        self.assertEqual((row['loader']['library'], row['loader']['sink'], row['source']['value']), ('custom', 'setPhoto', 'item.photoUrl'))
        none = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='feed', entry=['Feed.kt'], source_file=[], layout=[]))
        self.assertEqual(self.sources(none, 'remote-image'), [])

    def test_run_time_names_list_their_candidates_and_assets_are_files(self):
        index = self.collect()
        dynamic = self.sources(index, 'dynamic-resource')[0]
        self.assertEqual((dynamic['prefix'], dynamic['resourceType'], dynamic['candidates']),
                         ('ic_row_', 'drawable', ['@drawable/ic_row_a', '@drawable/ic_row_b']))
        asset = self.rows(index, 'asset:banner.png')[0]
        self.assertEqual((asset['kind'], asset['facts']['width']), ('asset', 10))
        self.write('java/demo/Gone.kt', 'class Gone { fun f() = open("file:///android_asset/missing.png") }\n')
        missing = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='g', entry=['Gone.kt'], source_file=[], layout=[]))
        self.assertEqual([(u['kind'], u['requested']) for u in missing['unresolved']], [('asset', 'missing.png')])

    def test_bindings_design_samples_and_drawing_code_are_signals(self):
        index = self.collect()
        binding = self.sources(index, 'data-binding')[0]
        self.assertEqual((binding['attr'], binding['value'], binding['sourcePath']), ('android:src', '@{item.iconRes}', 'app/src/main/res/layout/home.xml'))
        sample = self.sources(index, 'design-sample')[0]
        self.assertEqual((sample['attr'], sample['value'], sample['hasRuntimeSource']), ('tools:src', '@tools:sample/avatars', False))
        drawn = self.sources(index, 'code-drawn')[0]
        self.assertEqual((drawn['owner'], drawn['constructs']), ('HomeActivity.onDraw', ['drawPath', 'drawRoundRect', 'onDraw']))
        layout = index['layouts'][0]['root']
        self.assertNotIn('tools:src', json.dumps(layout))  # raw attributes stay exactly the source XML's

    def test_display_mutations_cover_backgrounds_scaling_animation_and_property_assignment(self):
        index = self.collect()
        found = {(m['property'], m['method']) for f in index['sourceFiles'] for m in f['presentationMutations']}
        self.assertTrue({('background', 'setBackground'), ('scaleType', 'scaleType'), ('animation', 'setAnimation'),
                         ('image', 'setImageURI'), ('image', 'setImageResource')} <= found)
        refs = {r for f in index['sourceFiles'] for m in f['presentationMutations'] for r in m['resourceRefs']}
        self.assertTrue({'@drawable/bg_card', '@raw/spinner'} <= refs)

    def test_ids_survive_unrelated_edits_and_repeats_stay_distinct(self):
        first = self.collect()
        ids = {(r['kind'], r.get('expression') or r.get('value') or r.get('owner')): r['id'] for r in first['imageSources']}
        self.assertEqual(len(ids), len(first['imageSources']))
        path = self.main / 'java/demo/HomeActivity.kt'
        path.write_text('// moved by a comment\n\n' + path.read_text())
        second = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='probe', entry=['HomeActivity.kt'], source_file=[], layout=[]))
        self.assertEqual({(r['kind'], r.get('expression') or r.get('value') or r.get('owner')): r['id'] for r in second['imageSources']}, ids)
        repeated = 'Picasso.get().load("https://img.example.com/hero.png").into(hero)\n'
        path.write_text(path.read_text().replace(repeated, repeated * 2))
        third = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='probe', entry=['HomeActivity.kt'], source_file=[], layout=[]))
        literal = [r['id'] for r in third['imageSources'] if r['kind'] == 'remote-image' and r['source']['kind'] == 'url-literal']
        self.assertEqual(len(literal), 2); self.assertEqual(len(set(literal)), 2)

    def test_a_missing_nested_resource_is_unresolved_not_dropped(self):
        self.project()
        self.write('res/drawable/ic_toggle.xml', '<selector xmlns:android="http://schemas.android.com/apk/res/android">'
                   '<item android:drawable="@drawable/ic_absent"/></selector>')
        index = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.root), scope='probe', entry=['HomeActivity.kt'], source_file=[], layout=[]))
        self.assertIn(('resource', '@drawable/ic_absent'), [(u['kind'], u['requested']) for u in index['unresolved']])

    def test_one_catalog_answers_every_lookup(self):
        self.project()
        catalog = resource_signals.Catalog(self.root)
        self.assertEqual(len(catalog.rows('@drawable/ic_logo')), 2)
        self.assertEqual(catalog.rows('@android:color/black'), [{'ref': '@android:color/black', 'kind': 'platform', 'status': 'platform'}])
        self.assertEqual(collect_ui_sources.discover_resource(self.root, '@color/brand')[0]['value'], '#FF6200EE')


if __name__ == '__main__':
    unittest.main()
