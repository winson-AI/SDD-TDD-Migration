"""The Resource closure covers everything the collector records, not only the references a tree names."""
import copy
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, check_ref, file_ref, read_json
import resource_fidelity as rf
import ui_evidence
import test_resource_scope as scope_fixtures

VECTOR = ('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp" '
          'android:viewportWidth="24" android:viewportHeight="24"%s><path android:fillColor="#FF000000" android:pathData="M0,0h24v24h-24z"/></vector>')
SELECTOR = ('<selector xmlns:android="http://schemas.android.com/apk/res/android">'
            '<item android:state_selected="true" android:drawable="@drawable/ic_on"/><item android:drawable="@drawable/ic_off"/></selector>')


class SignalClosureTests(unittest.TestCase):
    def setUp(self):
        self.s = scope_fixtures.ResourceScopeTests('test_all_actual_indexed_resources_have_source_hashes')
        self.s.setUp(); self.addCleanup(self.s.doCleanups)
        self.n, self.f = self.s.n, self.s.f
        # These tests are about what must be recorded and covered; what a screen shows of a picture has its own tests.
        self.f.model['image_check_waivers'] = [{'reason': 'screen checks are exercised with the image checks',
                                                'evidence_refs': [file_ref(self.n.write('evidence/waiver.json', {'reviewed': True}))]}]

    def write(self, name, text):
        return self.n.write('android/app/src/main/' + name, text)

    def code(self, text):
        source = self.n.android / 'app/src/main/java/example/SettingsFragment.kt'
        source.write_text(source.read_text() + text)
        return self.s.recollect()

    def declare(self, *refs):
        self.f.fixture['tree']['screens'][0]['root']['presentation']['resourceRefs'].extend(refs)

    def index(self):
        return read_json(check_ref(self.f.evidence['source_index_ref']))

    def tree(self):
        return read_json(check_ref(self.f.evidence['ui_tree_ref']))

    def needs(self):
        return rf.obligations(self.index(), self.tree(), self.f.evidence.get('resource_scope'))

    def item_for(self, skeleton, **over):
        item = {**copy.deepcopy(self.s.item), 'item_id': skeleton['source_resource'].replace('/', '-').lstrip('@'),
                'source_resource': skeleton['source_resource'], 'qualifier': skeleton['qualifier'],
                'source_resource_ref': skeleton['source_resource_ref'], 'resource_kind': skeleton['resource_kind'],
                'resource_strategy': skeleton['normal_strategy'],
                'target_resource': str(self.n.target / ('res/' + skeleton['source_resource'].replace(':', '/').split('/')[-1])),
                'consumer': str(self.n.target / 'Screen.kt') + '#Icon'}
        for key in ('configuration_mapping', 'adaptation_evidence_ref', 'blocked_reason', 'platform_resource', 'semantic_model'):
            item.pop(key, None)
        item.update(over)
        return item

    def cover_files(self):
        for skeleton in rf.skeletons(self.index(), self.tree(), self.f.evidence.get('resource_scope'))['resources']:
            if skeleton['source_resource'] in {i['source_resource'] for i in self.f.analysis['dimensions'][3]['items']}:
                continue
            self.f.analysis['dimensions'][3]['items'].append(self.item_for(skeleton))

    def nested_selector(self):
        self.write('res/drawable/ic_toggle.xml', SELECTOR)
        self.write('res/drawable/ic_on.xml', VECTOR % '')
        self.write('res/drawable/ic_off.xml', VECTOR % '')
        self.declare('@drawable/ic_toggle')
        self.code('\nfun toggle() = R.drawable.ic_toggle\n')

    def test_drawables_nested_in_a_declared_drawable_must_be_covered(self):
        self.nested_selector()
        self.assertEqual({r for r in self.needs()['refs'] if r.startswith('@drawable')},
                         {'@drawable/ic_toggle', '@drawable/ic_on', '@drawable/ic_off'})
        with self.assertRaisesRegex(Rejected, 'resource closure reduced; uncovered presentation refs: @drawable/ic_off'):
            self.s.freeze()
        self.cover_files()
        self.s.freeze()

    def test_a_theme_attribute_reached_through_a_drawable_is_followed_to_its_values(self):
        self.write('res/drawable/ic_tinted.xml', VECTOR % ' android:tint="?attr/tintColor"')
        self.write('res/values/theme.xml', '<resources><color name="brand">#FF112233</color>'
                   '<style name="AppTheme"><item name="tintColor">@color/brand</item></style></resources>')
        self.declare('@drawable/ic_tinted')
        self.code('\nfun tinted() = R.drawable.ic_tinted\n')
        refs = self.needs()['refs']
        self.assertIn('@color/brand', refs)
        self.assertNotIn('?attr/tintColor', refs)  # the project's theme is followed, not copied as a resource
        self.cover_files()
        self.s.freeze()

    def test_a_declared_theme_attribute_keeps_its_own_obligation(self):
        self.write('res/layout/other.xml', '<TextView xmlns:android="http://schemas.android.com/apk/res/android" '
                   'android:textColor="?attr/inkColor"/>')
        self.declare('?attr/inkColor')
        self.s.recollect()
        self.assertIn('?attr/inkColor', self.needs()['refs'])

    def test_menu_icons_and_assets_the_sources_reach_are_obligations(self):
        self.write('res/menu/top.xml', '<menu xmlns:android="http://schemas.android.com/apk/res/android">'
                   '<item android:id="@+id/find" android:icon="@drawable/ic_find"/></menu>')
        self.write('res/drawable/ic_find.xml', VECTOR % '')
        self.write('assets/hero.png', b'\x89PNG\r\n\x1a\nasset bytes')
        self.code('\nfun menu() { inflate(R.menu.top); load("file:///android_asset/hero.png") }\n')
        refs = self.needs()['refs']
        self.assertTrue({'@drawable/ic_find', 'asset:hero.png'} <= refs)
        self.assertNotIn('@menu/top', refs)  # a document's content is covered, the document itself is not an item
        skeletons = {s['source_resource']: s for s in rf.skeletons(self.index(), self.tree())['resources']}
        asset = skeletons['asset:hero.png']
        self.assertEqual((asset['resource_kind'], asset['normal_strategy'], asset['qualifier']), ('asset', 'byte_copy', 'base'))
        self.cover_files()
        self.s.freeze()
        mismatched = [i for i in self.f.analysis['dimensions'][3]['items'] if i['source_resource'] == 'asset:hero.png'][0]
        mismatched['source_resource_ref'] = file_ref(self.write('assets/other.png', b'\x89PNG\r\n\x1a\nanother asset'))
        with self.assertRaisesRegex(Rejected, 'asset source ID differs'):
            self.s.freeze()

    def loader(self, extra=''):
        self.write('res/drawable/ic_loading.xml', VECTOR % '')
        self.write('res/drawable/ic_fail.xml', VECTOR % '')
        self.write('java/example/Account.kt', 'class Account(@SerializedName("avatar_url") val avatarUrl: String)\n')
        return self.code('\nfun show(account: Account) {\n  Glide.with(this).load(account.avatarUrl)\n'
                         '    .placeholder(R.drawable.ic_loading).error(R.drawable.ic_fail).circleCrop().into(avatar)\n' + extra + '}\n')

    def signal(self, kind='remote-image'):
        return next(s for s in self.index()['imageSources'] if s['kind'] == kind)

    def signal_item(self, signal, **over):
        item = {**copy.deepcopy(self.s.item), 'item_id': 'remote-1', 'source_signal': signal['id'],
                'resource_kind': 'remote-image', 'resource_strategy': 'source_equivalent',
                'target_source': 'account.avatarUrl', 'target_resource': str(self.n.target / 'Avatar.kt') + '#load',
                'consumer': str(self.n.target / 'Screen.kt') + '#Avatar',
                'loader_mapping': {'placeholder': 'drawable-ic_loading', 'error': 'drawable-ic_fail',
                                   'transforms': [{'legacy': 'circleCrop()', 'target': 'clip(CircleShape)'}]}}
        for key in ('source_resource', 'source_resource_ref', 'qualifier', 'configuration_mapping', 'semantic_model'):
            item.pop(key, None)
        item.update(over)
        return item

    def test_every_recorded_image_source_needs_one_item(self):
        self.loader()
        signal = self.signal()
        self.assertEqual(signal['api']['candidates'][0]['jsonKey'], 'avatar_url')
        self.cover_files()
        with self.assertRaisesRegex(Rejected, 'UI image source closure requires one item for ' + signal['id']):
            self.s.freeze()
        self.f.analysis['dimensions'][3]['items'].append(self.signal_item(signal))
        self.s.freeze()

    def test_a_loader_replacement_states_the_url_the_placeholders_and_the_transforms(self):
        self.loader('  Picasso.get().load("https://img.example.com/hero.png").into(hero)\n')
        self.cover_files()
        items = self.f.analysis['dimensions'][3]['items']
        remote = {s['source']['kind']: s for s in self.index()['imageSources'] if s['kind'] == 'remote-image'}
        literal = self.signal_item(remote['url-literal'], item_id='remote-2', target_source='https://img.example.com/hero.png',
                                   loader_mapping={})
        expression = self.signal_item(remote['expression'])
        items.extend([literal, expression])
        self.s.freeze()
        for change, message in ((lambda i: i.update(target_source='https://elsewhere.example.com/hero.png'), 'same URL'),
                                (lambda i: i.pop('target_source'), 'target_source'),
                                (lambda i: i.pop('loader_mapping'), 'loader_mapping')):
            broken = copy.deepcopy(literal); change(broken)
            items[-2] = broken
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.s.freeze()
        items[-2] = literal
        for key, message in (('placeholder', 'loader_mapping.placeholder'), ('error', 'loader_mapping.error')):
            broken = copy.deepcopy(expression); broken['loader_mapping'].pop(key)
            items[-1] = broken
            with self.subTest(key=key), self.assertRaisesRegex(Rejected, message):
                self.s.freeze()
        broken = copy.deepcopy(expression); broken['loader_mapping']['transforms'] = []
        items[-1] = broken
        with self.assertRaisesRegex(Rejected, 'must map the legacy transform circleCrop'):
            self.s.freeze()
        items[-1] = expression
        absent = copy.deepcopy(expression); absent['loader_mapping']['error'] = {'absent': 'the target shows nothing on failure by design'}
        items[-1] = absent
        self.s.freeze()

    def test_a_signal_item_must_match_the_kind_and_use_a_strategy_that_kind_allows(self):
        self.loader()
        self.cover_files()
        items = self.f.analysis['dimensions'][3]['items']
        signal = self.signal()
        # An item is checked on its own first (kind with strategy), then against the source it claims to cover.
        for over, message in (({'resource_kind': 'code-drawn'}, 'code-drawn source requires manual_exact or blocked'),
                              ({'resource_kind': 'code-drawn', 'resource_strategy': 'manual_exact', 'adaptation_evidence_ref': self.f.f.f.ref('review.md', 'inspected')},
                               'differs from the recorded image source'),
                              ({'resource_strategy': 'byte_copy'}, 'requires source_equivalent or manual_exact or blocked'),
                              ({'resource_strategy': 'blocked'}, 'explicit reason'),
                              ({'resource_strategy': 'manual_exact'}, 'absolute evidence')):
            with self.subTest(over=over), self.assertRaisesRegex(Rejected, message):
                items.append(self.signal_item(signal, **over))
                try:
                    self.s.freeze()
                finally:
                    items.pop()
        items.append(self.signal_item(signal, resource_strategy='blocked', blocked_reason='the target has no equivalent loader'))
        self.s.freeze()  # an explicit gap passes the freeze; completion refuses it (see the ui_fidelity completion gate)

    def test_a_scoped_out_image_source_needs_a_reason_and_evidence_and_drops_its_obligations(self):
        self.loader()
        signal = self.signal()
        evidence = self.f.f.f.ref('scope-review.md', 'The loader belongs to another UI scope')
        for row, message in (({'signal_id': 'src:remote-image:absent', 'reason': 'x', 'evidence_refs': [evidence]}, 'one recorded image source'),
                             ({'signal_id': signal['id'], 'reason': ' ', 'evidence_refs': [evidence]}, 'signal_id and reason'),
                             ({'signal_id': signal['id'], 'reason': 'x', 'evidence_refs': []}, 'review evidence')):
            self.f.evidence['resource_scope'] = {'signal_exclusions': [row]}
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.needs()
        self.f.evidence['resource_scope'] = {'signal_exclusions': [{'signal_id': signal['id'], 'reason': 'owned by the feed screen', 'evidence_refs': [evidence]}]}
        needed = self.needs()
        self.assertNotIn(signal['id'], needed['signals'])
        self.assertFalse({'@drawable/ic_loading', '@drawable/ic_fail'} & needed['refs'])  # its placeholders leave with it
        duplicate = copy.deepcopy(self.f.evidence['resource_scope']['signal_exclusions'][0])
        self.f.evidence['resource_scope']['signal_exclusions'].append(duplicate)
        with self.assertRaisesRegex(Rejected, 'one recorded image source'):
            self.needs()

    def test_design_time_samples_are_not_obligations(self):
        self.write('res/layout/sample.xml', '<ImageView xmlns:android="http://schemas.android.com/apk/res/android" '
                   'xmlns:tools="http://schemas.android.com/tools" tools:src="@tools:sample/avatars"/>')
        index = self.index()
        self.s.source_index({**index, 'imageSources': index.get('imageSources', []) + [
            {'id': 'src:design-sample:x', 'kind': 'design-sample', 'sourcePath': 'a.xml', 'selector': '/ImageView', 'attr': 'tools:src',
             'value': '@tools:sample/avatars', 'hasRuntimeSource': False}]})
        self.assertNotIn('src:design-sample:x', self.needs()['signals'])

    def test_skeletons_carry_every_recorded_fact_and_who_declares_the_reference(self):
        self.nested_selector()
        found = {s['source_resource']: s for s in rf.skeletons(self.index(), self.tree())['resources']}
        toggle, on = found['@drawable/ic_toggle'], found['@drawable/ic_on']
        self.assertEqual((toggle['resource_kind'], toggle['normal_strategy'], toggle['declared_by']),
                         ('selector', 'compose_semantic_exact', ['node:settings.root']))
        self.assertEqual({(r['ref'], tuple(sorted(r.get('when', {}).items()))) for r in toggle['references']},
                         {('@drawable/ic_on', (('state_selected', 'true'),)), ('@drawable/ic_off', ())})
        self.assertEqual((on['resource_kind'], on['normal_strategy'], on['via'], on['facts']['size_dp']),
                         ('vector', 'exact_vector_xml', ['@drawable/ic_toggle'], [24.0, 24.0]))
        self.assertNotIn('declared_by', on)  # reached through the selector, not named by a node
        self.assertEqual(on['source_resource_ref'], file_ref(self.n.android / 'app/src/main/res/drawable/ic_on.xml'))

    def test_signal_skeletons_name_the_strategies_the_kind_allows(self):
        self.loader()
        signals = rf.skeletons(self.index(), self.tree())['signals']
        remote = next(s for s in signals if s['resource_kind'] == 'remote-image')
        self.assertEqual(remote['strategies'], ['source_equivalent', 'manual_exact', 'blocked'])
        self.assertEqual((remote['source']['value'], remote['loader']['placeholder']), ('account.avatarUrl', ['@drawable/ic_loading']))
        self.assertNotIn('id', remote)


if __name__ == '__main__':
    unittest.main()
