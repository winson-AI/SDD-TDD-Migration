"""preserve_refs tolerates drift of nested live target code only; else stays strict."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import ledger
from contracts import Rejected, file_ref


class PreserveRefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'run'; (self.root / 'artifacts').mkdir(parents=True)
        self.target = self.base / 'target'; self.target.mkdir()

    def nested_evidence(self, inner_ref, name='result.json'):
        f = self.base / name
        f.write_text(json.dumps({'code_files': [inner_ref]}))
        return {'result_ref': file_ref(f)}

    def drifted_ref(self, path):
        path.write_text('v1'); ref = file_ref(path); path.write_text('v2-DRIFTED')
        return ref

    def test_nested_target_drift_recorded_not_rejected(self):
        code = self.target / 'code.kt'
        payload = self.nested_evidence(self.drifted_ref(code))
        saved = ledger.preserve_refs(self.root, payload, target_root=str(self.target))
        self.assertTrue(any(s.get('status') == 'drifted-or-missing-live-target-code' for s in saved))
        self.assertTrue(any(str(s.get('source_path', '')).endswith('result.json') for s in saved))

    def test_nested_target_missing_recorded_not_rejected(self):
        code = self.target / 'gone.kt'; code.write_text('x'); ref = file_ref(code); code.unlink()
        saved = ledger.preserve_refs(self.root, self.nested_evidence(ref), target_root=str(self.target))
        self.assertTrue(any(s.get('status') == 'drifted-or-missing-live-target-code' for s in saved))

    def test_nested_nontarget_drift_still_strict(self):
        legacy = self.base / 'legacy'; legacy.mkdir()
        payload = self.nested_evidence(self.drifted_ref(legacy / 'x.kt'))
        with self.assertRaises((Rejected, ValueError, OSError)):
            ledger.preserve_refs(self.root, payload, target_root=str(self.target))

    def test_top_level_target_drift_still_strict(self):
        ref = self.drifted_ref(self.target / 'y.kt')
        with self.assertRaises((Rejected, ValueError, OSError)):
            ledger.preserve_refs(self.root, {'ref': ref}, target_root=str(self.target))


if __name__ == '__main__':
    unittest.main()
