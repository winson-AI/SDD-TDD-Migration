"""Structural, presence-triggered gates for UI/Logic/Resource semantic models."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import semantics
from contracts import Rejected, file_ref


class SemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def ref(self, name, content):
        p = self.base / name
        p.write_text(json.dumps(content))
        return file_ref(p)

    def item(self, dimension, kind, model, **model_over):
        sm = {'kind': kind, 'model_ref': self.ref(kind + '.json', model),
              'source': {'origin': 'legacy', 'locator': 'legacy/File.java#Sym', 'evidence_refs': []},
              'implementation_location': {'target_path': str(self.base / 'Out.kt')}}
        sm.update(model_over)
        return {'dimension': dimension, 'target_strategy': 'adapt', 'semantic_model': sm}

    def ok(self, item):
        semantics.validate_item(item)

    def bad(self, item, msg):
        with self.assertRaises((Rejected, OSError, ValueError, KeyError)) as ctx:
            semantics.validate_item(item)
        if msg:
            self.assertIn(msg, str(ctx.exception))

    # presence-triggered
    def test_item_without_model_is_skipped(self):
        self.ok({'dimension': 'UI', 'target_strategy': 'new'})

    # UI
    def test_ui_component_spec_ok_and_kind_binding(self):
        self.ok(self.item('UI', 'ui-component-spec', {'root': {'type': 'Column', 'children': [{'type': 'Row'}]}}))
        self.bad(self.item('Logic', 'ui-component-spec', {'root': {'type': 'Column'}}), 'kind does not match')
        self.bad(self.item('UI', 'ui-component-spec', {'root': {'children': []}}), 'node needs a type')

    # Logic
    def test_statechart_and_jsonlogic_cond(self):
        chart = {'id': 's', 'initial': 'idle', 'states': {'idle': {'on': {'GO': {'target': 'run', 'cond': {'==': [1, 1]}}}}, 'run': {}}}
        self.ok(self.item('Logic', 'logic-statechart', chart))
        self.bad(self.item('Logic', 'logic-statechart', {'id': 's', 'initial': 'missing', 'states': {'idle': {}}}), 'initial must be')
        self.bad(self.item('Logic', 'logic-statechart', {'id': 's', 'initial': 'idle', 'states': {'idle': {'on': {'GO': {'cond': 'x'}}}}}), 'JSON-Logic object')

    # Resource
    def test_design_tokens_and_icu(self):
        self.ok(self.item('Resource', 'design-tokens', {'color': {'primary': {'$type': 'color', '$value': '#fff'}}}))
        self.bad(self.item('Resource', 'design-tokens', {'color': {'primary': {'note': 'no value'}}}), 'at least one $value')
        self.ok(self.item('Resource', 'icu-messages', {'k': 'Hello {name}'}))
        self.bad(self.item('Resource', 'icu-messages', {'k': 123}), 'key->message')

    # source / strategy / location
    def test_new_strategy_forbids_legacy_origin(self):
        item = self.item('Resource', 'icu-messages', {'k': 'v'})
        item['target_strategy'] = 'new'
        self.bad(item, 'strategy new has no legacy reference')
        item['semantic_model']['source'] = {'origin': 'authored', 'evidence_refs': []}
        self.ok(item)

    def test_target_origin_requires_locator_and_abs_path(self):
        item = self.item('Resource', 'icu-messages', {'k': 'v'}, source={'origin': 'target', 'evidence_refs': []})
        self.bad(item, 'locator required')
        item = self.item('Resource', 'icu-messages', {'k': 'v'})
        item['semantic_model']['implementation_location'] = {'target_path': 'relative/Out.kt'}
        self.bad(item, 'must be absolute')

    def test_implementation_location_and_conformance(self):
        item = self.item('Resource', 'icu-messages', {'k': 'v'})
        items = {'i1': item}
        ev = self.ref('conf.json', {'ok': True})
        good = {'i1': {'semantic_conformance': {'model_ref': item['semantic_model']['model_ref'], 'evidence_refs': [ev]}}}
        self.bad_impl(items, 'does not exist', good)          # location missing
        (self.base / 'Out.kt').write_text('done')
        self.bad_impl(items, 'semantic_conformance', None)    # exists but implementer recorded no conformance
        semantics.implementation(items, good)                 # exists + conformance -> ok

    def test_models_and_coverage_from_analysis(self):
        analysis = {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [
                {'item_id': 'u1', 'semantic_model': {'kind': 'ui-component-spec'}}, {'item_id': 'u2'}]},
            {'dimension': 'Logic', 'status': 'not-applicable', 'items': []}]}
        rows = semantics.models_from_analysis(analysis, 'M001')
        self.assertEqual([(r['module_id'], r['item_id']) for r in rows], [('M001', 'u1')])
        self.assertEqual(semantics.coverage_from_analysis(analysis),
                         {'applicable': ['u1', 'u2'], 'with_model': ['u1'], 'missing': ['u2']})

    def bad_impl(self, items, msg, traces=None):
        with self.assertRaises((Rejected, OSError, ValueError)) as ctx:
            semantics.implementation(items, traces)
        self.assertIn(msg, str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
