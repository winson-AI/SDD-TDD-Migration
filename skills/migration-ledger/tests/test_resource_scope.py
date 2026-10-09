"""Stateful colors, current UI resource facts, and scoped configuration closure."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref, read_json, verify_plan
from lean_tools import collect_ui_sources, resource_tool
import dimensions
import resource_fidelity as rf
import ui_evidence
import ui_fidelity
import test_ui_frozen_contracts as frozen


class ResourceScopeTests(unittest.TestCase):
    def setUp(self):
        self.f = frozen.FrozenUiContracts()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.n = self.f.n

    @property
    def item(self):
        return self.f.analysis['dimensions'][3]['items'][0]

    def freeze(self):
        module = self.f.module()
        state = {**self.f.state, 'legacy_root': str(self.n.android)}
        dimensions.judge(module['plan']['dimension_analysis_ref'], module['module_id'])  # what registering it does
        ui_fidelity.freeze_gate(state, module)
        rf.freeze_gate(state, module)

    def source_index(self, index):
        ref = file_ref(self.n.write('evidence/ui-source-index.json', index))
        self.f.evidence['source_index_ref'] = ref
        self.f.fixture['tree']['generatedFrom']['sourceIndexSha256'] = ref['sha256']
        self.f.evidence['ui_tree_ref'] = file_ref(self.n.write('evidence/ui-tree.json', self.f.fixture['tree']))

    def recollect(self):
        previous = read_json(self.f.fixture['source'])
        index = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.n.android), scope='settings',
            entry=[entry['requested'] for entry in previous['entries']],
            source_file=[source['path'] for source in previous['sourceFiles']], layout=[]))
        self.source_index(index)
        return index

    def variant(self, qualifier='night', module='app'):
        return self.n.write('android/' + module + '/src/main/res/values-' + qualifier + '/strings.xml',
            '<resources><string name="settings_title">Night title</string></resources>')

    def exclusion(self, path, qualifier='night'):
        return {'source_resource': '@string/settings_title', 'qualifier': qualifier,
                'path': path.relative_to(self.n.android).as_posix(), 'reason': 'Outside this approved UI scope',
                'evidence_refs': [file_ref(self.n.write('evidence/scope-review.json', {'active': ['base']}))]}

    def test_a_plan_whose_resource_is_consumed_by_a_directory_is_refused_at_freeze(self):
        """Not after the code is written: an implementation result has to show the consumer files."""
        self.freeze()
        consumer = self.item['consumer']
        self.item['consumer'] = str(Path(str(consumer if isinstance(consumer, str) else consumer[0]).split('#', 1)[0]).parent)
        with self.assertRaisesRegex(Rejected, 'a consumer is a production file, not a directory or a note'):
            self.freeze()

    def test_stateful_colors_are_scanned_and_require_semantic_strategy(self):
        color = self.n.write('android/app/src/main/res/color-night/title.xml',
            '<selector xmlns:android="http://schemas.android.com/apk/res/android">'
            '<item android:state_enabled="false" android:color="#808080"/>'
            '<item android:color="#ffffff"/></selector>')
        fixed = self.n.write('android/app/src/main/res/values/colors.xml',
            '<resources><color name="title">#000000</color></resources>')
        found = resource_tool.source_candidates(self.n.android, '@color/title')
        self.assertEqual(set(found), {p.relative_to(self.n.android).as_posix() for p in (color, fixed)})
        rows = collect_ui_sources.discover_resource(self.n.android, '@color/title')
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['sha256'], file_ref(self.n.android / row['path'])['sha256'])
        item = {'source_resource': '@color/title', 'source_resource_ref': file_ref(color),
                'qualifier': 'night', 'resource_kind': 'selector', 'resource_strategy': 'compose_semantic_exact'}
        self.assertEqual(rf.validate_facts(item)['kind'], 'selector')
        with self.assertRaisesRegex(Rejected, 'requires compose_semantic_exact'):
            rf.validate_facts({**item, 'resource_strategy': 'design_token_exact'})
        with self.assertRaisesRegex(Rejected, 'resource_kind differs'):
            rf.validate_facts({**item, 'resource_kind': 'color', 'resource_strategy': 'design_token_exact'})
        self.assertEqual(rf.source_facts(fixed, '@color/title')['kind'], 'color')

    def test_all_actual_indexed_resources_have_source_hashes(self):
        index = read_json(self.f.fixture['source'])
        for row in index['resources']:
            if row.get('path'):
                self.assertEqual(row['sha256'], file_ref(self.n.android / row['path'])['sha256'])
        self.assertEqual(collect_ui_sources.discover_resource(self.n.android, '@android:color/black'),
                         [{'ref': '@android:color/black', 'kind': 'platform', 'status': 'platform'}])
        self.freeze()

    def add_reference(self, source_id):
        source = self.n.android / 'app/src/main/java/example/SettingsFragment.kt'
        expression = ('android.R.' + source_id.split(':')[1] if source_id.startswith('@android:')
                      else 'R.' + source_id[1:]).replace('/', '.')
        source.write_text(source.read_text() + '\nfun referenced() = ' + expression + '\n')
        root = self.f.fixture['tree']['screens'][0]['root']
        root['presentation']['resourceRefs'].append(source_id)
        return self.recollect()

    def test_code_node_id_remains_source_fact_without_resource_freeze_block(self):
        source = self.n.android / 'app/src/main/java/example/SettingsFragment.kt'
        source.write_text(source.read_text() + '\nfun lookup() = findViewById(R.id.title)\n')
        index = self.recollect()
        self.assertIn('@id/title', str(index['sourceFiles']))
        self.assertNotIn('@id/title', str(index['unresolved']))
        self.freeze()

    def test_array_collection_freeze_and_exact_worker_keep_both_array_types(self):
        for tag, name, value in (('string-array', 'choices', 'Choice'), ('integer-array', 'numbers', '3')):
            with self.subTest(tag=tag):
                source_id = '@array/' + name
                source = self.n.write('android/app/src/main/res/values/' + name + '.xml',
                    '<resources><' + tag + ' name="' + name + '"><item>' + value + '</item></' + tag + '></resources>')
                index = self.add_reference(source_id)
                self.assertTrue(any(r['ref'] == source_id and r.get('sha256') for r in index['resources']))
                item = {**copy.deepcopy(self.item), 'item_id': name, 'source_resource': source_id,
                        'resource_kind': 'array', 'source_resource_ref': file_ref(source),
                        'target_resource': str(self.n.target / ('values/' + name + '.xml'))}
                self.f.analysis['dimensions'][3]['items'].append(item)
                self.freeze()
                target = Path(item['target_resource'])
                payload = rf.prepare_exact(source, target, source_id, 'value_xml_exact')
                self.assertIn(('<' + tag).encode(), payload)
                self.assertIn(value.encode(), payload)

    def platform(self):
        metadata = self.n.write('sdk/platforms/android-35/source.properties', 'AndroidVersion.ApiLevel=35\n')
        source = self.n.write('sdk/platforms/android-35/data/res/values/colors.xml',
                             '<resources><color name="black">#ff000000</color></resources>')
        item = {**copy.deepcopy(self.item), 'item_id': 'platform-black', 'source_resource': '@android:color/black',
                'resource_kind': 'color', 'resource_strategy': 'design_token_exact',
                'source_resource_ref': file_ref(source), 'target_resource': str(self.n.target / 'Color.kt'),
                'platform_resource': {'api_level': 35, 'sdk_metadata_ref': file_ref(metadata)}}
        self.f.analysis['dimensions'][3]['items'].append(item)
        self.add_reference(item['source_resource'])
        return item

    def test_pinned_sdk_platform_resource_freezes_and_is_continuously_checked(self):
        item = self.platform(); self.freeze()
        module = self.f.module(); module['plan'].update(module_id='M001', definitions=[], tasks=[])
        verify_plan(module['plan'], module)
        Path(item['platform_resource']['sdk_metadata_ref']['path']).write_text('AndroidVersion.ApiLevel=36\n')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            verify_plan(module['plan'], module)

    def test_platform_source_cannot_escape_sdk_or_invent_api_version(self):
        item = self.platform()
        item['platform_resource']['api_level'] = 34
        with self.assertRaisesRegex(Rejected, 'api_level differs'):
            self.freeze()
        item['platform_resource']['api_level'] = 35
        item['source_resource_ref'] = file_ref(self.n.write('android/app/src/main/res/values/colors.xml',
                                      '<resources><color name="black">#000</color></resources>'))
        with self.assertRaisesRegex(Rejected, 'pinned SDK'):
            self.freeze()

    def test_platform_source_missing_remains_explicit_gap(self):
        item = self.platform(); item.pop('platform_resource'); item.pop('source_resource_ref')
        with self.assertRaisesRegex(Rejected, 'platform_resource'):
            self.freeze()
        item.update(resource_strategy='blocked', blocked_reason='SDK definition unavailable')
        self.freeze()
        self.assertIn(item['item_id'], rf.blocked(self.f.analysis))

    def test_rejects_resource_row_without_hash(self):
        index = read_json(self.f.fixture['source'])
        next(row for row in index['resources'] if row['ref'] == '@string/settings_title').pop('sha256')
        self.source_index(index)
        with self.assertRaisesRegex(Rejected, 'resource requires sha256'):
            ui_evidence.validate_native_evidence(self.f.evidence)

    def test_resource_edits_reject_old_ui_facts_even_with_new_resource_item_hash(self):
        source = Path(self.item['source_resource_ref']['path'])
        source.write_text('<resources><string name="settings_title">Changed title</string></resources>')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            ui_evidence.validate_native_evidence(self.f.evidence)
        self.item['source_resource_ref'] = file_ref(source)
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.freeze()
        self.recollect()
        self.freeze()

    def test_resource_item_must_use_indexed_source_baseline(self):
        alternate = self.n.write('android/other/src/main/res/values/strings.xml',
            '<resources><string name="settings_title">Other module</string></resources>')
        self.item['source_resource_ref'] = file_ref(alternate)
        with self.assertRaisesRegex(Rejected, 'different source baselines'):
            self.freeze()

    def test_missing_indexed_night_variant_rejected_and_exact_mapping_passes(self):
        night = self.variant(); self.recollect()
        with self.assertRaisesRegex(Rejected, '@string/settings_title / night'):
            self.freeze()
        item = copy.deepcopy(self.item)
        item.update(item_id='R-night', qualifier='night', source_resource_ref=file_ref(night),
                    target_resource=str(self.n.target / 'values-night/strings.xml'))
        self.f.analysis['dimensions'][3]['items'].append(item)
        self.freeze()

    def test_reviewed_exclusion_does_not_track_unrelated_configuration_edits(self):
        night = self.variant(); self.recollect()
        self.f.evidence['resource_scope'] = {'exclusions': [self.exclusion(night)]}
        self.freeze()
        night.write_text('<resources><string name="settings_title">Unrelated night change</string></resources>')
        self.freeze()
        proof = self.f.evidence['resource_scope']['exclusions'][0]['evidence_refs'][0]
        Path(proof['path']).write_text('changed scope review')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.freeze()

    def test_exclusion_requires_evidence_and_cannot_remove_all_candidates(self):
        night = self.variant(); self.recollect()
        exclusion = self.exclusion(night)
        self.f.evidence['resource_scope'] = {'exclusions': [exclusion]}
        exclusion['evidence_refs'] = []
        with self.assertRaisesRegex(Rejected, 'requires review evidence'):
            self.freeze()
        exclusion.update(self.exclusion(night))
        base = Path(self.item['source_resource_ref']['path'])
        self.f.evidence['resource_scope']['exclusions'].append(self.exclusion(base, 'base'))
        with self.assertRaisesRegex(Rejected, 'excludes every source candidate'):
            self.freeze()

    def test_exclusion_cannot_contradict_explicit_active_configurations(self):
        night = self.variant(); self.recollect()
        exclusion = self.exclusion(night)
        self.f.evidence['resource_scope'] = {'exclusions': [exclusion]}
        self.item['configuration_mapping'] = {
            'source_qualifier': 'base', 'target_qualifier': rf.target_qualifier(self.item),
            'scope': {'configurations': ['base', 'night'], 'reason': 'Both variants are active'},
            'consumer_condition': {'expression': '!isDarkTheme', 'consumers': rf.consumers(self.item)},
            'evidence_refs': exclusion['evidence_refs']}
        with self.assertRaisesRegex(Rejected, 'conflicts with frozen configuration scope'):
            self.freeze()

    def test_other_module_same_id_requires_path_specific_exclusion(self):
        other = self.n.write('android/other/src/main/res/values/strings.xml',
            '<resources><string name="settings_title">Unrelated module</string></resources>')
        self.recollect()
        with self.assertRaisesRegex(Rejected, 'different source baselines'):
            self.freeze()
        self.f.evidence['resource_scope'] = {'exclusions': [self.exclusion(other, 'base')]}
        other.write_text('unrelated malformed XML')
        self.freeze()

    def test_unreferenced_resource_from_another_scope_does_not_block(self):
        index = read_json(self.f.fixture['source'])
        index['resources'].append({'ref': '@string/unrelated', 'qualifier': 'night',
                                  'path': 'other/res/values-night/strings.xml', 'sha256': '0' * 64})
        self.source_index(index)
        self.freeze()

    def test_verify_plan_rechecks_frozen_resource_exclusion_evidence(self):
        night = self.variant(); self.recollect()
        exclusion = self.exclusion(night)
        self.f.evidence['resource_scope'] = {'exclusions': [exclusion]}
        self.freeze()
        module = self.f.module()
        module['plan'].update(module_id='M001', definitions=[], tasks=[])
        verify_plan(module['plan'], module)
        Path(exclusion['evidence_refs'][0]['path']).write_text('scope review changed after freeze')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            verify_plan(module['plan'], module)

    def test_ui_and_resource_source_baselines_must_agree_when_the_leaf_is_first_frozen(self):
        self.freeze()
        alternate = self.n.write('android/other/src/main/res/values/strings.xml',
            '<resources><string name="settings_title">Another valid source file</string></resources>')
        self.item['source_resource_ref'] = file_ref(alternate)
        module = self.f.module()
        module['plan'].update(module_id='M001', definitions=[], tasks=[])
        # Both source refs remain real/current, so file hashes alone cannot expose the mismatch: the first freeze judges it.
        with self.assertRaisesRegex(Rejected, 'different source baselines'):
            ui_fidelity.freeze_gate({**self.f.state, 'legacy_root': str(self.n.android)}, module)
        verify_plan(module['plan'], module)  # once accepted, a plan is refused for drift only; this is rule debt


if __name__ == '__main__':
    unittest.main()
