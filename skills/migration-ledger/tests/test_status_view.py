"""Reading cards are materialised once per digest; polling hosts get a bounded status."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import reading
import test_ledger


class StatusViewTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()

    def test_cursor_view_drops_module_bodies_and_dedups_cards(self):
        f = self.f
        full, cursor = ledger.status(f.root), ledger.status(f.root, 'cursor')
        for key in ('modules', 'module_inputs', 'planning_context', 'global_plan', 'decisions'):
            self.assertIn(key, full); self.assertNotIn(key, cursor)
        self.assertLess(len(json.dumps(cursor)), len(json.dumps(full)) / 2)
        step = cursor['next_steps'][0]
        self.assertNotIn('must_read', step)
        self.assertEqual(cursor['cards'][step['card_sha256']], reading.summary(full['next_steps'][0]['must_read']))
        self.assertNotIn('must_read', json.dumps(cursor))
        self.assertNotIn('evidence', json.dumps(cursor['workflow_progress']))
        self.assertEqual(cursor['workflow_progress']['state'], full['workflow_progress']['state'])
        for key in ('openspec_binding', 'migration_report', 'parent_mo_names'):
            self.assertIn(key, full); self.assertNotIn(key, cursor)
        self.assertLess(len(json.dumps(cursor)), 2500)
        self.assertEqual(cursor['operation_ready'] if 'operation_ready' in cursor else None, None)
        self.assertEqual(cursor['view'], 'cursor')

    def test_global_step_carries_a_digest_when_it_has_a_card(self):
        step = ledger.status(self.f.root)['global_next_step']
        if step.get('must_read'):
            self.assertEqual(step['card_sha256'], reading.digest_card(step['must_read']))

    def test_module_view_is_limited_to_one_module(self):
        f = self.f
        view = ledger.status(f.root, 'module', 'M001')
        self.assertEqual(view['module']['module_id'], 'M001')
        self.assertEqual([x['module_id'] for x in view['next_steps']], ['M001'])
        self.assertIn('module_input', view)
        self.assertNotIn('modules', view)
        with self.assertRaises(ValueError):
            ledger.status(f.root, 'module', 'M999')
        with self.assertRaises(ValueError):
            ledger.status(f.root, 'nonsense')

    def test_a_poll_that_saw_the_current_sequence_gets_a_brief_answer(self):
        f = self.f
        seen = ledger.status(f.root, 'cursor')['last_sequence']
        again = ledger.status(f.root, 'cursor', since=seen)
        self.assertEqual((again['unchanged'], again['last_sequence']), (True, seen))
        self.assertNotIn('next_steps', again)
        self.assertIn('signals', again['workflow_progress'])
        self.assertLess(len(json.dumps(again)), 700)
        self.assertIn('next_steps', ledger.status(f.root, 'cursor', since=seen - 1))
        f.assign('test-runner', 'TEST1')
        self.assertIn('next_steps', ledger.status(f.root, 'cursor', since=seen))

    def test_full_view_is_the_default_api(self):
        self.assertIn('modules', ledger.status(self.f.root))


class CardFileTests(unittest.TestCase):
    ROWS = [('AGENTS.md', '四条红线'), ('skills/migration-protocol/references/testing.md', '静态规格闭合')]

    def rows(self):
        return [{'ref': p, 'section': h, 'bytes': 1, 'sha256': reading.hashlib.sha256(reading.section(p, h).encode()).hexdigest()}
                for p, h in self.ROWS]

    def test_digest_follows_section_content(self):
        rows = self.rows()
        changed = [dict(rows[0], sha256='0' * 64), rows[1]]
        self.assertNotEqual(reading.digest_card(rows), reading.digest_card(changed))

    def test_render_writes_one_idempotent_file_named_by_digest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            first = reading.render(self.rows(), tmp)
            again = reading.render(self.rows(), tmp)
            self.assertEqual(first, again)
            self.assertEqual(Path(first['path']).name, first['card_sha256'] + '.md')
            text = Path(first['path']).read_text()
            for path, heading in self.ROWS:
                self.assertIn(reading.unlink(reading.section(path, heading), path).rstrip(), text)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_show_returns_one_section_and_refuses_escapes(self):
        text = reading.show('skills/migration-protocol/references/testing.md', '静态规格闭合')
        self.assertTrue(text.startswith('## 静态规格闭合'))
        for bad in ('../outside.md', '/etc/hosts', 'skills/migration-ledger/scripts/ledger.py'):
            with self.assertRaises(KeyError):
                reading.show(bad)

    def test_render_command_writes_the_current_step_card(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['reading.py', 'render', '--root', str(f.root), '--module', 'M001']), \
                contextlib.redirect_stdout(out):
            self.assertEqual(reading.main(), 0)
        result = json.loads(out.getvalue())
        step = ledger.status(f.root)['next_steps'][0]
        self.assertEqual(result['card_sha256'], step['card_sha256'])
        self.assertEqual(Path(result['path']).resolve(), (f.root / 'reports/reading' / (step['card_sha256'] + '.md')).resolve())
        self.assertTrue(Path(result['path']).is_file())


if __name__ == '__main__':
    unittest.main()
