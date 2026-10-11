"""A resumed session is told which sections of its card it has never been handed and which it holds in another text."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reading


class CardSectionTests(unittest.TestCase):
    def test_new_and_changed_sections_are_named(self):
        rows = [{'ref': 'AGENTS.md', 'section': '四条红线', 'sha256': 'a' * 64}, {'ref': 'x.md', 'section': 'S1', 'sha256': 'b' * 64},
                {'ref': 'x.md', 'section': 'S2', 'sha256': 'c' * 64}, {'ref': 'y.md', 'section': None, 'sha256': 'd' * 64}]
        held = {'AGENTS.md#四条红线': 'a' * 16, 'x.md#S1': 'f' * 16, 'y.md#': ['e' * 16, 'd' * 16]}
        self.assertEqual(reading.changed(rows, held), {'new': ['x.md#S2'], 'changed': ['x.md#S1']})  # y.md was handed in this text once
        self.assertEqual(reading.changed(rows, None), {'new': [reading.key(row) for row in rows], 'changed': []})
        self.assertEqual([reading.key(row) for row in reading.fresh(rows, held)], ['AGENTS.md#四条红线', 'x.md#S1', 'x.md#S2'])  # the red lines ride every card


if __name__ == '__main__':
    unittest.main()
