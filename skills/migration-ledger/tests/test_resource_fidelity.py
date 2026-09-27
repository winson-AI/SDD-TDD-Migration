"""Exact-resource strategies: no approximation, strategy matches source kind, closure not reduced."""
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
        self.assertEqual(rf.closure_gaps(analysis, ['@dimen/pad', '@color/y', '@string/miss']), ['@string/miss'])


if __name__ == '__main__':
    unittest.main()
