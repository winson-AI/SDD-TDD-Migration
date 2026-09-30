"""Instantiate the shipped UI template against real native collector outputs."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_lean_native_contracts as native_contracts
from contracts import file_ref, read_json
from lean_tools import validate_ui_tree


class NativeUITemplateTests(unittest.TestCase):
    def setUp(self):
        self.native = native_contracts.NativeContractTests(methodName='runTest')
        self.native.setUp()
        self.addCleanup(self.native.doCleanups)
        self.fixture = self.native.native_ui()

    def instantiate(self):
        template = Path(__file__).resolve().parents[3] / 'template' / 'semantic-model.json'
        tree = read_json(template)['ui_tree_contract']
        index = read_json(self.fixture['source'])
        main = 'app/src/main/res/layout/settings.xml'
        row = 'app/src/main/res/layout/row_setting.xml'
        layouts = {item['path']: item['root'] for item in index['layouts']}
        values = {
            'change-id': 'settings',
            'source-index-path': str(self.fixture['source']),
            'source-index-sha256': file_ref(self.fixture['source'])['sha256'],
            'runtime-index-path': str(self.fixture['runtime']),
            'runtime-index-sha256': file_ref(self.fixture['runtime'])['sha256'],
            'screen-layout-path': main,
            'screen-root-selector': layouts[main]['selector'],
            'title-selector': layouts[main]['children'][0]['selector'],
            'row-layout-path': row,
            'row-root-selector': layouts[row]['selector'],
            'renderer-source-path': 'app/src/main/java/example/SettingsFragment.kt',
            'source-backed-root-appearance': 'Full-size LinearLayout containing the title',
            'binding-target': 'root.layout',
            'binding-source': 'SettingsFragment.create()',
            'binding-source-selector': 'SettingsFragment#create',
            'event-trigger': 'create',
            'event-handler': 'SettingsFragment.create',
            'event-source-selector': 'SettingsFragment#create',
            'dynamic-condition': 'create returns',
            'dynamic-property': 'layout',
            'dynamic-result': '@layout/settings',
            'dynamic-source-selector': 'SettingsFragment#create',
            'runtime-view-signature': 'sig',
        }

        # Only fill scalar placeholders. The template owns every node, list/object
        # shape, XML attribute, semantic record and closure entry under test.
        def fill(value):
            if isinstance(value, dict):
                return {key: fill(item) for key, item in value.items()}
            if isinstance(value, list):
                return [fill(item) for item in value]
            if isinstance(value, str) and value.startswith('{{') and value.endswith('}}'):
                return values[value[2:-2]]
            return value

        tree = fill(tree)
        self.assertNotIn('{{', json.dumps(tree))
        return tree

    def test_runtime_template_passes_native_strict_validator(self):
        path = self.native.write('evidence/template-ui-tree.json', self.instantiate())
        result = validate_ui_tree.validate(path, self.fixture['source'], self.fixture['runtime'])
        self.assertEqual(result['nodes'], 3)

    def test_source_only_template_passes_without_runtime_claims(self):
        tree = self.instantiate()
        tree['generatedFrom'].pop('runtimeIndex')
        tree['generatedFrom'].pop('runtimeIndexSha256')
        tree['screens'][0]['root'].pop('runtimeObservations')
        path = self.native.write('evidence/template-source-only-tree.json', tree)
        result = validate_ui_tree.validate(path, self.fixture['source'])
        self.assertEqual(result['nodes'], 3)


if __name__ == '__main__':
    unittest.main()
