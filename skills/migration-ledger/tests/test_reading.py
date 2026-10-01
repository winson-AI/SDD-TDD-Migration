"""Reading cards stay small, cite real sections and always carry the red lines."""
import itertools
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reading
import test_ledger


class ReadingCardTests(unittest.TestCase):
    def test_every_card_cites_existing_sections_within_budget(self):
        for role in reading.ROLE:
            scopes = list(reading.TEST_SCOPE) if role == 'test-runner' else [None]
            for scope, ui, reuse in itertools.product(scopes, (False, True), (False, True)):
                rows = reading.entries(role, scope, ui, reuse)
                with self.subTest(role=role, scope=scope, ui=ui, reuse=reuse):
                    self.assertIn(('AGENTS.md', '四条红线'), rows)
                    self.assertTrue(all((path, None) in rows for path in reading.ROLE[role]))
                    total = sum(len(reading.section(path, heading).encode()) for path, heading in rows)
                    self.assertLessEqual(total, reading.READ_BUDGET)

    def test_section_stops_at_next_heading_of_same_level(self):
        text = reading.section('skills/migration-protocol/references/testing.md', '静态规格闭合')
        self.assertTrue(text.startswith('## 静态规格闭合'))
        self.assertNotIn('## Harmony Main', text)
        with self.assertRaises(KeyError):
            reading.section('AGENTS.md', 'no such heading')

    def test_cursor_steps_carry_cards(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        step = f.state()['next_steps'][0]
        self.assertEqual(step['worker_role'], 'test-runner')
        refs = {row['ref'] for row in step['must_read']}
        self.assertIn('Agents/test-runner.md', refs)
        self.assertNotIn('Agents/implementer.md', refs)
        self.assertTrue(all(row['bytes'] > 0 for row in step['must_read']))


if __name__ == '__main__':
    unittest.main()
