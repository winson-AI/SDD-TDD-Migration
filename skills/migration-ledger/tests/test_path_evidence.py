"""A PATH is verified on the leaf's own code and its providers': it takes no evidence from a sibling leaf."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
from contracts import Rejected


class PathEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.target = Path('/tmp/target-x2')
        self.s = {'target_root': str(self.target), 'module_groups': {'M010': {}},
                  'modules': {'M001': {'module_id': 'M001', 'dependencies': [], 'write_paths': [str(self.target / 'logic')]},
                              'M002': {'module_id': 'M002', 'dependencies': ['M001'], 'write_paths': [str(self.target / 'ui')]}}}

    def plan(self, *lines, steps=()):
        return {'paths': [{'path_id': 'P1', 'preconditions': list(lines), 'steps': list(steps)}]}

    def test_a_path_names_no_sibling_and_no_file_outside_its_scope(self):
        s, logic, ui = self.s, self.s['modules']['M001'], self.s['modules']['M002']
        decomposition.check_path_evidence(s, ui, self.plan("M001's LoginStore wired", str(self.target / 'ui/Page.kt'), 'parent M010 accepted'))  # its provider, its own file, its parent
        decomposition.check_path_evidence(s, logic, self.plan('/legacy/src/Login.java read', 'M999 is nobody'))  # outside the target and an unknown id say nothing
        with self.assertRaisesRegex(Rejected, 'PATH P1 takes evidence from M002, which is not a provider'):
            decomposition.check_path_evidence(s, logic, self.plan("M002's ui/Page.kt on disk"))  # the leaf that depends on it
        with self.assertRaisesRegex(Rejected, 'takes evidence from ' + str(self.target / 'ui/Page.kt') + ', outside this leaf'):
            decomposition.check_path_evidence(s, logic, self.plan(str(self.target / 'ui/Page.kt') + ' present'))
        with self.assertRaisesRegex(Rejected, 'takes evidence from M002'):
            decomposition.check_path_evidence(s, logic, self.plan(steps=['wait for M002 to land']))


if __name__ == '__main__':
    unittest.main()
