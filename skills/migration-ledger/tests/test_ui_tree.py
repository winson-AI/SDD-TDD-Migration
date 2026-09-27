"""The merged source+runtime UI tree contract as the lean pipeline emits it."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ui_tree
from contracts import Rejected


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
            ui_tree.validate(value)
        self.assertIn(msg, str(ctx.exception))

    def test_minimal_tree_ok(self):
        ui_tree.validate(tree())
        ui_tree.validate(tree(runtime=False))

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
        self.assertTrue(ui_tree.merged_runtime(tree()))
        self.assertFalse(ui_tree.merged_runtime(tree(runtime=False)))

    def test_screens_need_root_and_typed_attachments(self):
        self.bad(tree(screens=[]), 'ui tree screens')
        self.bad(tree(screens=[{'id': 'login', 'root': node()}]), 'stable screen:')
        self.bad(tree(screens=[{'id': 'screen:login'}]), 'root must be an object')
        self.bad(tree(screens=[{'id': 'screen:login', 'root': node(),
                                'attachments': {'popups': [node('node:p')]}}]), 'attachments must be typed')
        ui_tree.validate(tree(screens=[{'id': 'screen:login', 'root': node(),
                                        'attachments': {'dialogs': [node('node:confirm')]}}]))

    def test_node_ids_and_refs(self):
        self.bad(tree(screens=[{'id': 'screen:login', 'root': {'presentation': {}}}]), 'stable node:')
        self.bad(tree(screens=[{'id': 'screen:login', 'root': node(bindings=['phone'])}]), 'stable ids')
        self.bad(tree(screens=[{'id': 'screen:login',
                                'root': node(dynamicRules=[{'resourceRefs': []}])}]), 'condition')

    def test_source_only_tree_cannot_carry_runtime_observations(self):
        observed = node(runtimeObservations=[{'pageId': 'login', 'stateId': 'phone', 'text': 'Next'}])
        ui_tree.validate(tree(screens=[{'id': 'screen:login', 'root': observed}]))          # runtime merged
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
        ui_tree.validate(t)
        self.assertEqual(ui_tree.node_ids(t), ['node:child', 'node:dlg', 'node:root'])
        self.assertEqual(ui_tree.resource_refs(t), ['@color/sel', '@dimen/pad', '@string/hi', '@style/D'])


if __name__ == '__main__':
    unittest.main()
