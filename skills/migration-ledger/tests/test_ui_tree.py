"""UI tree content is structurally validated: stable ids, presentation refs, dynamic rules."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ui_tree
from contracts import Rejected


def tree(nodes=None, **over):
    base = {'schema_version': 1, 'screen': 'screen:login', 'unresolved': [],
            'nodes': nodes if nodes is not None else [{'id': 'node:root', 'presentation': {'resourceRefs': []}}]}
    base.update(over)
    return base


class UiTreeTests(unittest.TestCase):
    def bad(self, value, msg):
        with self.assertRaises((Rejected, ValueError, KeyError, TypeError)) as ctx:
            ui_tree.validate(value)
        self.assertIn(msg, str(ctx.exception))

    def test_minimal_tree_ok(self):
        ui_tree.validate(tree())

    def test_schema_screen_and_unresolved_required(self):
        self.bad(tree(schema_version=2), 'schema_version 1')
        self.bad(tree(screen='login'), 'stable screen:')
        t = tree(); del t['unresolved']
        self.bad(t, 'unresolved list')
        self.bad(tree(nodes=[]), 'ui tree nodes')

    def test_node_needs_stable_id_and_typed_refs(self):
        self.bad(tree(nodes=[{'presentation': {}}]), 'stable node:')
        self.bad(tree(nodes=[{'id': 'node:a', 'presentation': {'resourceRefs': 'x'}}]), 'must be a list')
        self.bad(tree(nodes=[{'id': 'node:a', 'bindings': ['phone']}]), 'stable ids')

    def test_dynamic_rules_need_condition(self):
        self.bad(tree(nodes=[{'id': 'node:a', 'dynamicRules': [{'resourceRefs': []}]}]), 'condition')

    def test_resource_refs_collect_presentation_and_runtime_overrides(self):
        t = tree(nodes=[{'id': 'node:a', 'presentation': {'resourceRefs': ['@dimen/pad']},
                         'dynamicRules': [{'condition': 'selected', 'resourceRefs': ['@color/sel']}],
                         'children': [{'id': 'node:b', 'presentation': {'resourceRefs': ['@string/hi']}}]}])
        ui_tree.validate(t)
        self.assertEqual(ui_tree.resource_refs(t), ['@color/sel', '@dimen/pad', '@string/hi'])


if __name__ == '__main__':
    unittest.main()
