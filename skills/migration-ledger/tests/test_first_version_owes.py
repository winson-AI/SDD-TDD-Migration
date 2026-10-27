"""What a first version may leave incomplete is owed by the leaf, not refused: the plan freezes and the code is written,
and the gap is settled before the module completes. Outside a leaf's judging (a tool, a direct call) it still refuses."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import behavior_contract
import design_stage
from contracts import Rejected, carrying, file_ref


class FirstVersionOwesTests(unittest.TestCase):
    def test_a_held_case_without_a_path_is_owed_and_a_foreign_case_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / 'test-plan.md'; note.write_text('paths')
            path = lambda pid, cid: {'path_id': pid, 'case_id': cid, 'name': pid, 'requirement_id': 'R1',
                                     'expected_assertions': [{'assertion_id': 'A-' + pid, 'expected': True}]}
            result = {'design_ref': file_ref(note), 'paths': [path('P1', 'C1')]}
            m, tasks = {'case_ids': ['C1', 'C2']}, [{'requirement_ids': ['R1']}]
            with carrying() as gaps:
                design_stage.coverage({}, m, result, tasks)
            self.assertEqual(gaps, ['design leaves assigned cases without a PATH: C2'])
            with self.assertRaisesRegex(Rejected, 'without a PATH'):
                design_stage.coverage({}, m, result, tasks)  # not a leaf's judging: still refused
            with carrying(), self.assertRaisesRegex(Rejected, 'cover assigned cases'):
                design_stage.coverage({}, m, {**result, 'paths': [path('P1', 'C1'), path('P9', 'C9')]}, tasks)  # a case it does not hold

    def test_a_behaviour_review_missing_its_words_is_owed_but_its_structure_is_not(self):
        module = {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'scope': {'in': ['q'], 'out': [], 'requirement_ids': ['R1']}}
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / 'review.md'; note.write_text('read the source')
            value = {'unresolved': [], 'shared_capabilities': [], 'evidence_refs': [file_ref(note)]}
            with carrying() as gaps:
                behavior_contract.review(module, value)
            self.assertEqual(sorted(gaps), sorted('behavior review missing ' + f for f in ('entry', 'observable_result', 'production_binding', 'boundary_rationale')))
            with carrying(), self.assertRaisesRegex(Rejected, 'shared_capabilities must be explicit'):
                behavior_contract.review(module, {**value, 'shared_capabilities': None})


if __name__ == '__main__':
    unittest.main()
