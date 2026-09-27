"""Capture manifest schema-2 contract and declared-gesture device proof."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import capture_manifest as cm
import interactions
from contracts import Rejected, file_ref


def entry(**over):
    base = {'schema_version': 2, 'page_id': 'login', 'state_id': 'phone', 'coverage': 'viewport',
            'status': 'COMPLETE', 'achieved_coverage': 'viewport', 'observed_variant': 'phone',
            'backend': 'autotest',
            'snapshot': {'screenshot': 's.png', 'view_xml': 'view.xml', 'meta': 'meta.json',
                         'captures': ['s.png']}}
    base.update(over)
    return base


class CaptureManifestTests(unittest.TestCase):
    def bad(self, value, msg):
        with self.assertRaises((Rejected, ValueError, KeyError, TypeError)) as ctx:
            cm.validate_entry(value)
        self.assertIn(msg, str(ctx.exception))

    def test_complete_entry_ok(self):
        cm.validate_entry(entry())

    def test_schema_two_required(self):
        self.bad(entry(schema_version=1), 'schema_version 2')

    def test_complete_needs_full_triple(self):
        self.bad(entry(snapshot={'screenshot': 's.png', 'view_xml': 'v.xml', 'captures': ['s']}), 'needs meta')
        self.bad(entry(snapshot={'screenshot': 's.png', 'view_xml': 'v.xml', 'meta': 'm.json', 'captures': []}), 'captures')

    def test_scroll_requires_scroll_complete(self):
        self.bad(entry(coverage='scroll', achieved_coverage='scroll-partial'), 'scroll-complete')
        cm.validate_entry(entry(coverage='scroll', achieved_coverage='scroll-complete'))

    def test_complete_needs_variant_and_backend(self):
        self.bad(entry(observed_variant=None), 'observed_variant')
        self.bad(entry(backend=None), 'device backend')

    def test_source_only_must_not_invent_captures(self):
        cm.validate_entry(entry(status='SOURCE_ONLY', snapshot=None, achieved_coverage=None,
                                observed_variant=None, backend=None))
        self.bad(entry(status='SOURCE_ONLY'), 'must not carry invented runtime captures')


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name='trace.json'):
        p = self.base / name; p.write_text(json.dumps({'trace': True})); return file_ref(p)

    def decl(self, **over):
        base = {'id': 'detail-edge-back', 'action': 'edge_back_gesture',
                'from': {'page_id': 'detail', 'state_id': 'base'},
                'expected': {'page_id': 'home', 'state_id': 'base', 'app_foreground': True}}
        base.update(over)
        return {'interactions': [base]}

    def test_no_interactions_is_noop(self):
        self.assertEqual(interactions.validate_declarations({}), [])
        interactions.validate_checks([], None)

    def test_declaration_contract(self):
        self.assertEqual(interactions.validate_declarations(self.decl()), ['detail-edge-back'])
        with self.assertRaisesRegex(Rejected, 'stable lowercase id'):
            interactions.validate_declarations(self.decl(id='Edge Back'))
        with self.assertRaisesRegex(Rejected, 'action modality'):
            interactions.validate_declarations(self.decl(action=None))
        with self.assertRaisesRegex(Rejected, 'starting page/state'):
            interactions.validate_declarations(self.decl(**{'from': {}}))
        with self.assertRaisesRegex(Rejected, 'expected page/state unless the app exits'):
            interactions.validate_declarations(self.decl(expected={'app_foreground': True}))
        # app exit needs no destination
        interactions.validate_declarations(self.decl(expected={'app_foreground': False}))

    def test_checks_must_pass_against_aligned_hap(self):
        declared = ['detail-edge-back']
        with self.assertRaisesRegex(Rejected, 'lack device checks'):
            interactions.validate_checks(declared, {'interaction_checks': []})
        check = {'id': 'detail-edge-back', 'status': 'PASSED', 'hap_sha256': 'h1', 'evidence_ref': self.ref()}
        with self.assertRaisesRegex(Rejected, 'aligned hap_sha256'):
            interactions.validate_checks(declared, {'interaction_checks': [check]})
        interactions.validate_checks(declared, {'hap_sha256': 'h1', 'interaction_checks': [check]})
        with self.assertRaisesRegex(Rejected, 'bind the aligned HAP'):
            interactions.validate_checks(declared, {'hap_sha256': 'h2', 'interaction_checks': [check]})
        with self.assertRaisesRegex(Rejected, 'not PASSED'):
            interactions.validate_checks(declared, {'hap_sha256': 'h1',
                                                    'interaction_checks': [{**check, 'status': 'FAILED'}]})


if __name__ == '__main__':
    unittest.main()
