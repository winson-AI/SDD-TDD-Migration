"""Exact-resource strategies: no approximation, strategy matches source kind, closure not reduced."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import resource_fidelity as rf
from contracts import Rejected, file_ref


class ResourceFidelityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name='ev.json'):
        p = self.base / name; p.write_text(json.dumps({'inspected': True})); return file_ref(p)

    def item(self, **over):
        base = {'item_id': 'R1', 'source_resource': '@drawable/ic_tv'}
        base.update(over)
        return base

    def bad(self, item, msg=None):
        with self.assertRaises((Rejected, ValueError, KeyError, TypeError)) as ctx:
            rf.validate_item(item)
        if msg:
            self.assertIn(msg, str(ctx.exception))

    def test_absent_strategy_is_presence_triggered(self):
        rf.validate_item(self.item())  # legacy items untouched

    def test_no_approximate_strategy(self):
        self.bad(self.item(resource_strategy='approximate', resource_kind='vector'), 'approximation is not a strategy')

    def test_strategy_must_match_source_kind(self):
        rf.validate_item(self.item(resource_strategy='exact_vector_xml', resource_kind='vector'))
        rf.validate_item(self.item(resource_strategy='value_xml_exact', resource_kind='string'))
        self.bad(self.item(resource_strategy='byte_copy', resource_kind='vector'), 'requires exact_vector_xml')
        self.bad(self.item(resource_strategy='exact_vector_xml'), 'resource_kind required')

    def test_escapes_need_evidence_or_reason(self):
        self.bad(self.item(resource_strategy='manual_exact', resource_kind='shape'))  # needs inspected evidence ref
        rf.validate_item(self.item(resource_strategy='manual_exact', resource_kind='shape',
                                   adaptation_evidence_ref=self.ref()))
        self.bad(self.item(resource_strategy='blocked', resource_kind='shape'), 'explicit reason')
        rf.validate_item(self.item(resource_strategy='blocked', resource_kind='shape', blocked_reason='unsupported'))

    def test_sp_dimension_must_stay_font_scale_aware(self):
        self.bad(self.item(resource_strategy='design_token_exact', resource_kind='dimen', source_unit='sp'),
                 'font-scale aware')
        rf.validate_item(self.item(resource_strategy='design_token_exact', resource_kind='dimen',
                                   source_unit='sp', scales_with_font=True))

    def test_nine_patch_never_byte_copy(self):
        self.bad(self.item(resource_strategy='byte_copy', resource_kind='bitmap', nine_patch=True), '.9.png')
        rf.validate_item(self.item(resource_strategy='compose_semantic_exact', resource_kind='bitmap', nine_patch=True))

    def test_blocked_and_closure_helpers(self):
        analysis = {'dimensions': [{'dimension': 'Resource', 'status': 'applicable', 'items': [
            {'item_id': 'R1', 'source_resource': '@dimen/pad'},
            {'item_id': 'R2', 'source_resource': '@color/x', 'resource_strategy': 'blocked',
             'covered_resource_ids': ['@color/y']}]}]}
        self.assertEqual(rf.blocked(analysis), ['R2'])
        self.assertEqual(rf.closure_gaps(analysis, ['@dimen/pad', '@color/y', '@string/miss']), ['@color/y', '@string/miss'])

    def resource(self, source_id='@string/title', qualifier='base', content=None, **over):
        namespace, name = source_id[1:].split('/')
        directory = 'drawable' if namespace == 'drawable' else 'values'
        source = self.base / 'legacy/res' / (directory + ('-' + qualifier if qualifier != 'base' else '')) / (name + '.xml')
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content or '<resources><string name="title">Title</string></resources>')
        item = {'item_id': name + '-' + qualifier, 'source_resource': source_id, 'source_resource_ref': file_ref(source),
                'qualifier': qualifier, 'resource_kind': 'string', 'resource_strategy': 'value_xml_exact',
                'target_resource': str(self.base / 'target/values/strings.xml') + '#Res.string.title',
                'consumer': str(self.base / 'target/Screen.kt') + '#Title'}
        item.update(over)
        return item

    def analysis(self, *items):
        return {'dimensions': [{'dimension': 'Resource', 'status': 'applicable', 'items': list(items)}]}

    def freeze(self, *items, alternatives=()):
        path = self.base / 'analysis.json'; path.write_text(json.dumps(self.analysis(*items)))
        rf.freeze_gate({'legacy_root': str(self.base / 'legacy')},
                       {'plan': {'dimension_analysis_ref': file_ref(path), 'decision_envelope': {'allowed_alternatives': list(alternatives)}}})

    def config(self, item, configurations=None, condition=None):
        proof = self.ref('configuration-review.json')
        item['configuration_mapping'] = {'source_qualifier': item['qualifier'], 'target_qualifier': rf.target_qualifier(item),
            'scope': {'configurations': configurations or [item['qualifier']], 'reason': 'Source/theme scope inspected'},
            'evidence_refs': [proof]}
        if condition:
            item['configuration_mapping']['consumer_condition'] = {'expression': condition, 'consumers': rf.consumers(item)}
        return item

    def test_extra_ids_cannot_close_missing_resource_and_real_alias_has_own_evidence(self):
        title = self.resource(covered_resource_ids=['@string/alias', '@string/nonexistent'])
        analysis = self.analysis(title)
        self.assertEqual(rf.closure_gaps(analysis, ['@string/title', '@string/alias']), ['@string/alias'])
        alias = self.resource('@string/alias', content='<resources><string name="alias">@string/title</string></resources>',
                              resource_strategy='manual_exact', adaptation_evidence_ref=self.ref(),
                              target_resource=str(self.base / 'target/values/strings.xml') + '#Res.string.alias')
        analysis = self.analysis(title, alias)
        self.assertEqual(rf.closure_gaps(analysis, ['@string/title', '@string/alias']), [])
        rf.require_exact_closure(analysis, ['@string/title', '@string/alias'], self.base / 'legacy')
        alias['source_resource'] = '@string/nonexistent'
        with self.assertRaisesRegex(Rejected, 'matching values entry'):
            rf.require_exact_closure(self.analysis(title, alias), ['@string/title', '@string/nonexistent'])

    def test_unknown_actual_kind_has_blocked_or_reviewed_and_approved_manual_exit(self):
        item = self.resource('@drawable/motion', content='<animated-vector/>', resource_kind='animated-vector',
                             resource_strategy='blocked', blocked_reason='Requires animator port; no exact converter')
        self.assertEqual(rf.validate_facts(item)['kind'], 'animated-vector')
        self.freeze(item)
        self.assertEqual(rf.blocked(self.analysis(item)), ['motion-base'])
        item['resource_strategy'] = 'byte_copy'
        with self.assertRaisesRegex(Rejected, 'unsupported resource kind'):
            rf.validate_facts(item)
        item['resource_strategy'] = 'manual_exact'
        with self.assertRaises(Rejected):
            rf.validate_facts(item)
        item['adaptation_evidence_ref'] = self.ref()
        rf.validate_facts(item)
        with self.assertRaisesRegex(Rejected, 'copy_blocker'):
            rf.replacement(item)  # a picture the legacy app ships: the planned item states what stops the copy
        rf.replacement({**item, 'copy_blocker': 'the target has no animated vector loader'})
        rf.replacement({**item, 'resource_kind': 'string'})  # a value is not a picture
        with self.assertRaisesRegex(Rejected, 'needs an approved deviation'):  # a review alone does not replace a shipped animation
            self.freeze(item)
        approved = 'the animator is re-implemented with the target animation API'
        item['deviation'] = {'alternative': approved, 'kind': 'redraw', 'reason': 'no exact converter for animated vectors'}
        with self.assertRaisesRegex(Rejected, 'allowed_alternatives'):
            self.freeze(item)
        self.freeze(item, alternatives=[approved])
        Path(item['adaptation_evidence_ref']['path']).write_text('changed review')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.freeze(item, alternatives=[approved])

    def test_variant_change_needs_scope_evidence_but_scoped_night_only_is_valid(self):
        item = self.resource(qualifier='night')
        with self.assertRaisesRegex(Rejected, 'configuration_mapping'):
            self.freeze(item)
        self.config(item)
        self.freeze(item)
        item['configuration_mapping']['scope']['configurations'] = ['base', 'night']
        with self.assertRaisesRegex(Rejected, 'consumer_condition'):
            self.freeze(item)
        self.config(item, ['base', 'night'], 'isDarkTheme')
        self.freeze(item)
        item['configuration_mapping']['consumer_condition']['consumers'] = ['other']
        with self.assertRaisesRegex(Rejected, 'every planned consumer'):
            self.freeze(item)

    def test_same_configuration_and_legacy_base_need_no_new_mapping(self):
        base = self.resource()
        self.freeze(base)
        night = self.resource(qualifier='night', target_resource=str(self.base / 'target/values-night/strings.xml'))
        self.freeze(base, night)
        night['target_resource'] = str(self.base / 'target/Theme.kt') + '#nightTitle'
        with self.assertRaisesRegex(Rejected, 'configuration_mapping'):
            self.freeze(night)

    def test_configuration_proof_is_bound_to_source_target_and_evidence(self):
        item = self.config(self.resource(qualifier='night'))
        for field, wrong in (('source_qualifier', 'base'), ('target_qualifier', 'night')):
            changed = copy.deepcopy(item); changed['configuration_mapping'][field] = wrong
            with self.assertRaisesRegex(Rejected, 'differs from source or target'):
                self.freeze(changed)
        item['configuration_mapping']['evidence_refs'] = []
        with self.assertRaisesRegex(Rejected, 'scope/condition evidence'):
            self.freeze(item)

    def test_configuration_evidence_is_rechecked_when_frozen_item_is_read(self):
        item = self.config(self.resource(qualifier='night'))
        self.freeze(item)
        Path(item['configuration_mapping']['evidence_refs'][0]['path']).write_text('changed configuration review')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            rf.validate_item(item)

    def test_shared_destination_requires_distinct_consumer_routing(self):
        base = self.resource(); night = self.config(self.resource(qualifier='night'))
        with self.assertRaisesRegex(Rejected, 'share a destination'):
            self.freeze(base, night)
        self.config(base, ['base', 'night'], '!isDarkTheme')
        self.config(night, ['base', 'night'], 'isDarkTheme')
        self.freeze(base, night)
        night['configuration_mapping']['consumer_condition']['expression'] = '!isDarkTheme'
        with self.assertRaisesRegex(Rejected, 'indistinguishable routing'):
            self.freeze(base, night)

    def test_duplicate_source_variant_is_one_item_with_multiple_consumers(self):
        first = self.resource(); duplicate = copy.deepcopy(first); duplicate['item_id'] = 'second'
        with self.assertRaisesRegex(Rejected, 'duplicate resource source/qualifier'):
            self.freeze(first, duplicate)
        first['consumer'] = [first['consumer'], str(self.base / 'target/Other.kt') + '#Title']
        self.freeze(first)


if __name__ == '__main__':
    unittest.main()
