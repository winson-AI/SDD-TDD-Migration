"""Projected JSON does not depend on the key order a replay happens to give the state."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import openspec_projection


class SortedProjectionTests(unittest.TestCase):
    def test_the_same_value_in_another_key_order_projects_to_the_same_text(self):
        one = {'scenario_trace': [{'scenario_id': 'S1', 'path_ids': ['P1'], 'task_ids': ['T1']}], 'scenario_index': {'S1': {'requirement_id': 'R1', 'case_id': 'C1'}}}
        other = {'scenario_index': {'S1': {'case_id': 'C1', 'requirement_id': 'R1'}}, 'scenario_trace': [{'task_ids': ['T1'], 'path_ids': ['P1'], 'scenario_id': 'S1'}]}
        self.assertNotEqual(list(one), list(other))
        self.assertEqual(openspec_projection.dumps(one), openspec_projection.dumps(other))
        self.assertIn('\n  "scenario_index"', openspec_projection.dumps(one))  # still indented and readable
        source = Path(openspec_projection.__file__).read_text()
        self.assertNotIn('json.dumps(', source.split('def dumps(')[0] + source.split('def dumps(')[1].split('\n', 3)[3])  # every projection goes through it


if __name__ == '__main__':
    unittest.main()
