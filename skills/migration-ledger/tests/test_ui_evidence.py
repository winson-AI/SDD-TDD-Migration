"""UI evidence contracts: merged UI tree, capture manifest, declared gestures."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ui_evidence as ue
from contracts import Rejected, file_ref


def node(nid='node:root', **over):
    base = {'id': nid, 'presentation': {'resourceRefs': []}}
    base.update(over)
    return base


def tree(screens=None, runtime=True, **over):
    origin = {'sourceIndex': 'ui-source-index.json', 'sourceIndexSha256': 'aa',
              'runtimeIndex': 'runtime-ui-index.json' if runtime else None,
              'runtimeIndexSha256': 'bb' if runtime else None}
    base = {'schemaVersion': 1, 'scope': 'migrate-login', 'generatedFrom': origin,
            'screens': screens if screens is not None else [{'id': 'screen:login', 'root': node()}],
            'layoutClosure': [], 'criticalLayoutContracts': [], 'unresolved': []}
    base.update(over)
    return base


class UiTreeTests(unittest.TestCase):
    def bad(self, value, msg):
        with self.assertRaises((Rejected, ValueError, KeyError, TypeError)) as ctx:
            ue.validate_tree(value)
        self.assertIn(msg, str(ctx.exception))

    def test_minimal_tree_ok(self):
        ue.validate_tree(tree())
        ue.validate_tree(tree(runtime=False))

    def test_lean_camel_case_schema_is_the_contract(self):
        self.bad({'schema_version': 1, 'screen': 'screen:login', 'nodes': []}, 'schemaVersion 1')
        self.bad(tree(schemaVersion=2), 'schemaVersion 1')
        self.bad(tree(scope=''), 'change scope')

    def test_generated_from_provenance(self):
        t = tree(); del t['generatedFrom']
        self.bad(t, 'generatedFrom provenance')
        self.bad(tree(generatedFrom={'sourceIndex': 'i.json'}), 'needs sourceIndexSha256')
        self.bad(tree(generatedFrom={'sourceIndex': 'i.json', 'sourceIndexSha256': 'a',
                                     'runtimeIndex': 'r.json', 'runtimeIndexSha256': None}),
                 'both be present or both be null')
        self.assertTrue(ue.merged_runtime(tree()))
        self.assertFalse(ue.merged_runtime(tree(runtime=False)))

    def test_screens_need_root_and_typed_attachments(self):
        self.bad(tree(screens=[]), 'ui tree screens')
        self.bad(tree(screens=[{'id': 'login', 'root': node()}]), 'stable screen:')
        self.bad(tree(screens=[{'id': 'screen:login'}]), 'root must be an object')
        self.bad(tree(screens=[{'id': 'screen:login', 'root': node(),
                                'attachments': {'popups': [node('node:p')]}}]), 'attachments must be typed')
        ue.validate_tree(tree(screens=[{'id': 'screen:login', 'root': node(),
                                        'attachments': {'dialogs': [node('node:confirm')]}}]))

    def test_node_ids_and_refs(self):
        self.bad(tree(screens=[{'id': 'screen:login', 'root': {'presentation': {}}}]), 'stable node:')
        self.bad(tree(screens=[{'id': 'screen:login', 'root': node(bindings=['phone'])}]), 'stable ids')
        self.bad(tree(screens=[{'id': 'screen:login',
                                'root': node(dynamicRules=[{'resourceRefs': []}])}]), 'condition')

    def test_source_only_tree_cannot_carry_runtime_observations(self):
        observed = node(runtimeObservations=[{'pageId': 'login', 'stateId': 'phone', 'text': 'Next'}])
        ue.validate_tree(tree(screens=[{'id': 'screen:login', 'root': observed}]))          # runtime merged
        self.bad(tree(screens=[{'id': 'screen:login', 'root': observed}], runtime=False),
                 'no runtime index')

    def test_required_lists(self):
        for key in ('layoutClosure', 'criticalLayoutContracts', 'unresolved'):
            t = tree(); del t[key]
            self.bad(t, 'explicit ' + key)

    def test_collects_nodes_and_refs_across_root_and_attachments(self):
        t = tree(screens=[{'id': 'screen:login',
                           'root': node(presentation={'resourceRefs': ['@dimen/pad']},
                                        dynamicRules=[{'condition': 'selected', 'resourceRefs': ['@color/sel']}],
                                        children=[node('node:child', presentation={'resourceRefs': ['@string/hi']})]),
                           'attachments': {'dialogs': [node('node:dlg', presentation={'resourceRefs': ['@style/D']})]}}])
        ue.validate_tree(t)
        self.assertEqual(ue.node_ids(t), ['node:child', 'node:dlg', 'node:root'])
        self.assertEqual(ue.resource_refs(t), ['@color/sel', '@dimen/pad', '@string/hi', '@style/D'])


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
            ue.validate_capture(value)
        self.assertIn(msg, str(ctx.exception))

    def test_complete_entry_ok(self):
        ue.validate_capture(entry())

    def test_schema_two_required(self):
        self.bad(entry(schema_version=1), 'schema_version 2')

    def test_complete_needs_full_triple(self):
        self.bad(entry(snapshot={'screenshot': 's.png', 'view_xml': 'v.xml', 'captures': ['s']}), 'needs meta')
        self.bad(entry(snapshot={'screenshot': 's.png', 'view_xml': 'v.xml', 'meta': 'm.json', 'captures': []}), 'captures')

    def test_scroll_requires_scroll_complete(self):
        self.bad(entry(coverage='scroll', achieved_coverage='scroll-partial'), 'scroll-complete')
        ue.validate_capture(entry(coverage='scroll', achieved_coverage='scroll-complete'))

    def test_complete_needs_variant_and_backend(self):
        self.bad(entry(observed_variant=None), 'observed_variant')
        self.bad(entry(backend=None), 'device backend')

    def test_source_only_must_not_invent_captures(self):
        ue.validate_capture(entry(status='SOURCE_ONLY', snapshot=None, achieved_coverage=None,
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
        self.assertEqual(ue.validate_interactions({}), [])
        ue.validate_interaction_checks([], None)

    def test_declaration_contract(self):
        self.assertEqual(ue.validate_interactions(self.decl()), ['detail-edge-back'])
        with self.assertRaisesRegex(Rejected, 'stable lowercase id'):
            ue.validate_interactions(self.decl(id='Edge Back'))
        with self.assertRaisesRegex(Rejected, 'action modality'):
            ue.validate_interactions(self.decl(action=None))
        with self.assertRaisesRegex(Rejected, 'starting page/state'):
            ue.validate_interactions(self.decl(**{'from': {}}))
        with self.assertRaisesRegex(Rejected, 'expected page/state unless the app exits'):
            ue.validate_interactions(self.decl(expected={'app_foreground': True}))
        # app exit needs no destination
        ue.validate_interactions(self.decl(expected={'app_foreground': False}))

    def test_checks_must_pass_against_aligned_hap(self):
        declared = ['detail-edge-back']
        with self.assertRaisesRegex(Rejected, 'lack device checks'):
            ue.validate_interaction_checks(declared, {'interaction_checks': []})
        check = {'id': 'detail-edge-back', 'status': 'PASSED', 'hap_sha256': 'h1', 'evidence_ref': self.ref()}
        with self.assertRaisesRegex(Rejected, 'aligned hap_sha256'):
            ue.validate_interaction_checks(declared, {'interaction_checks': [check]})
        ue.validate_interaction_checks(declared, {'hap_sha256': 'h1', 'interaction_checks': [check]})
        with self.assertRaisesRegex(Rejected, 'bind the aligned HAP'):
            ue.validate_interaction_checks(declared, {'hap_sha256': 'h2', 'interaction_checks': [check]})
        with self.assertRaisesRegex(Rejected, 'not PASSED'):
            ue.validate_interaction_checks(declared, {'hap_sha256': 'h1',
                                                    'interaction_checks': [{**check, 'status': 'FAILED'}]})



if __name__ == '__main__':
    unittest.main()
