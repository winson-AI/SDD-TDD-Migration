"""lean skill outputs convert into exactly the SDD evidence shapes the gates accept."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import lean_adapter
import semantics
from contracts import Rejected, file_ref


class LeanAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name, content='{}'):
        p = self.base / name; p.write_text(content); return file_ref(p)

    def test_ui_evidence_from_capture(self):
        tree = self.ref('ui-tree.json', json.dumps({'schema_version': 1, 'screen': 'screen:login', 'nodes': [{'id': 'node:root', 'presentation': {'resourceRefs': []}}], 'unresolved': []}))
        ev = lean_adapter.ui_evidence({'schema_version': 2, 'page_id': 'login', 'state_id': 'phone', 'coverage': 'viewport', 'status': 'COMPLETE', 'achieved_coverage': 'viewport', 'observed_variant': 'phone', 'backend': 'autotest', 'snapshot': {'screenshot': 's.png', 'view_xml': 'v.xml', 'meta': 'm.json', 'captures': ['s.png']}}, tree)
        self.assertEqual(ev['coverage'], 'login:phone:viewport')
        self.assertEqual(ev['visual_mode'], 'runtime')
        # output passes the real semantics gate
        semantics._ui_evidence({'ui_evidence': ev})
        # SOURCE_ONLY -> source-only mode
        ev2 = lean_adapter.ui_evidence({'schema_version': 2, 'page_id': 'p', 'state_id': 's', 'coverage': 'scroll', 'status': 'SOURCE_ONLY'}, tree)
        self.assertEqual(ev2['visual_mode'], 'source-only')

    def test_ui_evidence_rejects_bad_capture(self):
        tree = self.ref('t.json', json.dumps({'schema_version': 1, 'screen': 'screen:login', 'nodes': [{'id': 'node:root', 'presentation': {'resourceRefs': []}}], 'unresolved': []}))
        with self.assertRaises((Rejected, ValueError, KeyError)):
            lean_adapter.ui_evidence({'schema_version': 2, 'page_id': 'p', 'state_id': 's', 'coverage': 'full', 'status': 'COMPLETE'}, tree)

    def test_visual_alignment_maps_status(self):
        res = self.ref('align.json')
        self.assertEqual(lean_adapter.visual_alignment({'status': 'ALIGNED'}, res)['status'], 'aligned')
        self.assertEqual(lean_adapter.visual_alignment({'status': 'RUNNABLE_PARTIAL'}, res)['status'], 'source-only')
        with self.assertRaises((Rejected, ValueError)):
            lean_adapter.visual_alignment({'status': 'NEEDS_UI_FIX'}, res)


if __name__ == '__main__':
    unittest.main()
