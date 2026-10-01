"""Reading cards stay small, cite real sections and always carry the red lines."""
import itertools
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import progress_signals
import reading
import test_ledger


class ReadingCardTests(unittest.TestCase):
    def test_every_card_cites_existing_sections_within_budget(self):
        for role in reading.ROLE:
            scopes = list(reading.TEST_SCOPE) if role == 'test-runner' else [None]
            operations = (None, 'audit-code-review', 'audit-plan', 'source-review', 'audit-work', 'register')
            for scope, ui, reuse, op, tel, lean in itertools.product(scopes, (False, True), (False, True), operations,
                                                                    (False, True), (False, True)):
                rows = reading.entries(role, scope, ui, reuse, op, tel, lean)
                with self.subTest(role=role, scope=scope, ui=ui, reuse=reuse, op=op, telemetry=tel, lean=lean):
                    self.assertTrue(set(reading.CORE) <= set(rows))
                    self.assertTrue(all((path, None) in rows for path in reading.ROLE[role]))
                    total = sum(len(reading.section(path, heading).encode()) for path, heading in rows)
                    self.assertLessEqual(total, reading.READ_BUDGET)

    def test_cards_follow_the_operation_and_the_triggers(self):
        def refs(*args, **kwargs):
            return {(p, h) for p, h in reading.entries(*args, **kwargs)}
        audit = reading.P + 'audit-scope.md'
        review = reading.P + 'audit-code-review.md'
        self.assertIn((review, None), refs('auditor', operation='audit-code-review'))
        self.assertNotIn((review, None), refs('auditor', operation='audit-plan'))
        self.assertNotIn((audit, None), refs('auditor', operation='audit-code-review'))
        go_plan, go_audit = refs('global-orchestrator', operation='register'), refs('global-orchestrator', operation='audit-assign')
        self.assertIn((reading.P + 'module-decomposition.md', None), go_plan)
        self.assertNotIn((reading.P + 'module-decomposition.md', None), go_audit)
        self.assertIn((audit, None), go_audit)
        self.assertNotIn((audit, None), go_plan)
        self.assertIn((reading.P + 'source-changes.md', None), refs('global-orchestrator', operation='source-review'))
        self.assertNotIn((reading.P + 'openspec.md', None), refs('spec-designer'))
        self.assertNotIn((reading.P + 'openspec.md', 'Ledger 物化与修复记忆'), refs('spec-designer'))
        self.assertNotIn((reading.P + 'telemetry.md', '总则'), refs('implementer'))
        self.assertIn((reading.P + 'telemetry.md', '总则'), refs('implementer', telemetry=True))
        self.assertIn((reading.P + 'reuse-dependencies.md', '总则'), refs('auditor', reuse=True))
        self.assertNotIn((reading.P + 'reuse-dependencies.md', '总则'), refs('auditor'))
        self.assertIn((reading.P + 'module-decomposition.md', '总则'), refs('fixer', lean=True))

    def test_every_moved_topic_rule_is_reachable_from_some_card(self):
        """The topic index in AGENTS.md points at each 总则 section; some card must deliver it when its trigger holds."""
        import re
        index = (reading.PACKAGE / 'AGENTS.md').read_text()
        wanted = set(re.findall(r'\]\(([^)#]+\.md)#总则\)', index))
        reachable = set()
        for role in reading.ROLE:
            for scope in (list(reading.TEST_SCOPE) if role == 'test-runner' else [None]):
                for op in (None, 'audit-code-review', 'audit-plan', 'source-review', 'register'):
                    reachable |= {p for p, h in reading.entries(role, scope, True, True, op, True, True) if h in ('总则', None)}
        host_only = {reading.P + 'host-integration.md', reading.P + 'model-routing.md', reading.P + 'watchdog.md'}
        missing = sorted(path for path in wanted if path not in reachable and path not in host_only)
        self.assertEqual(missing, [])

    def test_rejections_point_at_the_section_stating_the_gate(self):
        for _, name, heading in reading.GATES:
            reading.section(reading.P + name, heading)  # every pointer resolves
        hint = reading.read_hint('undeclared change inside module scope: /t/x.py')
        self.assertEqual((hint['ref'], hint['section']), (reading.P + 'engineering-disciplines.md', '写范围核验（可选，默认关闭）'))
        self.assertIsNone(reading.read_hint('something nobody documented'))
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        progress_signals.record_rejection(f.root, {'operation': 'accept', 'module_id': 'M001'}, {'role': 'host'},
                                          'unit tests must pass before the static review')
        record = json.loads((f.root / 'reports/rejected-operation.json').read_text())
        self.assertEqual(record['read_hint']['section'], '逻辑单测')

    def test_protocol_text_stays_within_its_ratchet(self):
        files = [p for pattern in reading.PROTOCOL_GLOBS for p in reading.PACKAGE.glob(pattern)]
        sizes = {str(p.relative_to(reading.PACKAGE)): p.stat().st_size for p in files}
        self.assertLessEqual(sum(sizes.values()), reading.PROTOCOL_BUDGET)
        self.assertEqual([f for f, n in sizes.items() if n > reading.FILE_BUDGET], [])

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
