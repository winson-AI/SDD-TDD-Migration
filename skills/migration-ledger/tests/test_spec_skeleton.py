"""A generated SPEC skeleton cites the allocation instead of restating it, and leaves decisions to the decision records."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import spec_skeleton
from contracts import Rejected, check_ref, file_ref
import test_control_policy
import test_source_changes


class DocumentCapTests(unittest.TestCase):
    def setUp(self):
        t = test_control_policy.ControlPolicyTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f; self.f.global_plan()

    def test_the_skeleton_cites_the_allocation_and_has_no_decisions_section(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        result = spec_skeleton.write(t.f.root, 'M001', t.f.root / 'staging/spec-designer/skeleton')
        text = {name: check_ref(ref).read_text() for name, ref in result['files'].items()}
        self.assertNotIn('## Decisions', text['design.md'])
        self.assertIn('dimension_analysis_ref', text['design.md']); self.assertIn('M001-Logic', text['design.md'])
        out = t.f.state()['modules']['M001']['scope']['out']
        for name in ('proposal.md', 'design.md'):
            self.assertIn(f'scope.out（{len(out)} 条）', text[name])
            for line in out:
                self.assertNotIn(f'- {line}\n', text[name])


if __name__ == '__main__':
    unittest.main()
