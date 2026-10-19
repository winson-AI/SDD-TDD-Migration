"""A legacy web application's evidence chain: the browser scrolls a frozen region to its end, the DOM it kept becomes the
runtime index and a tree derived from it alone, and the UI evidence the planner freezes stands on that tree with no source index."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, read_json
import lean_adapter
import lean_visual_worker as worker
import lean_worker
import semantics
import test_legacy_capture
import ui_evidence

LOGO = 'https://legacy.example.test/static/logo.png'


def element(tag, id='', cls='', text='', aria='', src='', bounds=(0, 0, 0, 0), scrollable=False, children=()):
    return {'tag': tag, 'id': id, 'cls': cls, 'text': text, 'aria': aria, 'src': src, 'bounds': list(bounds), 'scrollable': scrollable, 'children': list(children)}


class ScrollingPage(test_legacy_capture.FakePage):
    """A list page that shows three more rows per wheel turn and its End after two turns."""
    def __init__(self, png, end_after=2):
        super().__init__(png); self.scrolls, self.end_after = 0, end_after

    def wheel(self, x, y, dy): self.calls.append(('wheel', x, y, dy)); self.scrolls += 1

    def dom(self):
        start = self.scrolls * 3
        rows = [element('li', cls='row', text=f'Item {i}', bounds=(0, 100 + (i - start) * 40, 1280, 140 + (i - start) * 40)) for i in range(start, start + 3)]
        if self.scrolls >= self.end_after:
            rows.append(element('li', id='end', cls='row', text='End', bounds=(0, 700, 1280, 740)))
        return element('body', bounds=(0, 0, 1280, 800), children=[
            element('h1', id='title', cls='hero', text=self.text, bounds=(0, 0, 1280, 80)),
            element('img', id='logo', aria='logo', src=LOGO, bounds=(0, 80, 120, 100)),
            element('ul', id='list', aria='items', bounds=(0, 100, 1280, 800), scrollable=True, children=rows)])


class WebEvidenceTests(test_legacy_capture.CaptureFixture):
    def setUp(self):
        super().setUp()
        self.page = ScrollingPage(self.png(1))
        self.web = {'kind': 'browser', 'url': 'https://legacy.example.test/list'}
        self.actor['device_lock']['device_id'] = self.web['url']
        self.open = patch.object(worker, 'open_browser', lambda out, viewport=None: self.page); self.open.start(); self.addCleanup(self.open.stop)
        self.targets = [{'coverage': 'login:base:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]},
                        {'coverage': 'list:base:scroll', 'target_match': [{'resource-id': 'list'}], 'scroll_region': {'resource-id': 'list'},
                         'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 5}]

    def chain(self):
        result = self.capture(self.targets, stated=self.web)
        self.assertEqual((result['status'], result['captured']), ('CAPTURED', ['login:base:viewport', 'list:base:scroll']))
        out = Path(result['manifest_ref']['path']).parent / 'analysis'; out.mkdir()
        analysis = lean_worker.web_analysis({'platform': 'web', 'capture_ref': result['manifest_ref'], 'targets': ['login:base:viewport', 'list:base:scroll']}, 'M001', out)
        return result, analysis

    def test_the_browser_scrolls_the_frozen_region_to_its_end(self):
        result, _ = self.chain()
        record = ui_evidence.capture_target(result['manifest_ref'], 'list:base:scroll')
        self.assertEqual((record['coverage']['achieved'], record['coverage']['capture_count'], record['coverage']['termination'], record['platform'], record['snapshot']['device_backend']['name']),
                         ('scroll-complete', 3, 'frozen-scroll-end-observed', 'web', 'playwright'))
        self.assertEqual(len([c for c in self.page.calls if c[0] == 'wheel']), 2)

    def test_the_tree_is_derived_from_the_dom_alone_and_the_evidence_stands_on_it(self):
        result, analysis = self.chain()
        tree = read_json(analysis['ui_tree_ref']['path'])
        self.assertEqual((tree['generatedFrom']['platform'], tree['generatedFrom']['sourceIndex'], [s['id'] for s in tree['screens']]),
                         ('web', None, ['screen:login.base', 'screen:list.base']))
        self.assertIn('node:title', ui_evidence.target_node_ids(tree, 'login', 'base'))
        self.assertEqual([(i['nodeId'], i['src']) for i in tree['imageSources']][:1], [('node:logo', LOGO)])
        self.assertEqual(ui_evidence.validate_tree_ref(analysis['ui_tree_ref'], runtime_index_ref=analysis['runtime_index_ref'])['scope'], 'M001')
        evidence = lean_adapter.ui_evidence(read_json(result['manifest_ref']['path']), analysis['ui_tree_ref'], target='login:base:viewport',
                                            capture_ref=result['manifest_ref'], runtime_index_ref=analysis['runtime_index_ref'])
        self.assertEqual((evidence['visual_mode'], evidence['legacy_executable'], len(evidence['baseline_refs']), evidence.get('source_index_ref')), ('runtime', True, 1, None))
        semantics._ui_evidence({'ui_evidence': evidence})
        with self.assertRaisesRegex(Rejected, 'takes no source index'):
            ui_evidence.validate_tree_ref(analysis['ui_tree_ref'], source_index_ref=analysis['runtime_index_ref'], runtime_index_ref=analysis['runtime_index_ref'])
        forged = json.loads(json.dumps(tree)); forged['screens'][0]['root']['children'][0]['id'] = 'node:missing'
        path = Path(analysis['ui_tree_ref']['path']).with_name('forged.json'); path.write_text(json.dumps(forged))
        with self.assertRaisesRegex(Rejected, 'not an element id the DOM'):
            ui_evidence.validate_tree_ref(file_ref(path), runtime_index_ref=analysis['runtime_index_ref'])
        self.actor['device_lock']['device_id'] = 'emulator-5554'
        android = self.capture([self.login()])
        with self.assertRaisesRegex(Rejected, 'reads a browser legacy capture'):
            lean_worker.web_analysis({'platform': 'web', 'capture_ref': android['manifest_ref']}, 'M001', Path(android['manifest_ref']['path']).parent / 'analysis')


if __name__ == '__main__':
    unittest.main()
