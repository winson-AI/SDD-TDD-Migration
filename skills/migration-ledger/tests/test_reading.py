"""Reading cards stay small, cite real sections and always carry the red lines."""
import itertools
import re
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
        ops = (None, 'audit-code-review', 'audit-plan', 'audit-assign', 'source-review', 'audit-work', 'register', 'accept', 'freeze')
        for role in reading.ROLE:
            scopes = list(reading.TEST_SCOPE) if role == 'test-runner' else [None]
            for scope, ui, reuse, op, tel, lean in itertools.product(scopes, (False, True), (False, True), ops,
                                                                    (False, True), (False, True)):
                rows = reading.entries(role, scope, ui, reuse, op, tel, lean, rows=[op] if op else [])
                with self.subTest(role=role, scope=scope, ui=ui, reuse=reuse, op=op, telemetry=tel, lean=lean):
                    self.assertTrue(set(reading.CORE) <= set(rows))
                    self.assertIn((reading.ROLE[role][0], None), rows)
                    total = sum(len(reading.section(path, heading).encode()) for path, heading in rows)
                    self.assertLessEqual(total, reading.READ_BUDGET)

    def test_cards_follow_the_operation_and_the_triggers(self):
        def has(rows, path, heading=None):
            return (path, heading) in rows or (path, None) in rows
        def refs(*args, **kwargs):
            return reading.entries(*args, **kwargs)
        audit, review, decomposition = (reading.P + n for n in ('audit-scope.md', 'audit-code-review.md', 'module-decomposition.md'))
        code_review = refs('auditor', operation='audit-code-review')
        self.assertIn((review, None), code_review)
        self.assertFalse(has(code_review, audit, reading.D2))
        plan = refs('auditor', operation='audit-plan')
        self.assertTrue(has(plan, audit, reading.D2))
        self.assertFalse(has(plan, audit, reading.D5))
        self.assertNotIn((review, None), plan)
        go_plan, go_collect = refs('global-orchestrator', operation='register'), refs('global-orchestrator', operation='audit-collect')
        self.assertTrue(has(go_plan, decomposition, '3. 分配与登记门禁'))
        self.assertFalse(has(go_plan, decomposition, '父 MO 统一命名'))
        self.assertFalse(has(go_collect, decomposition, '3. 分配与登记门禁'))
        self.assertTrue(has(go_collect, audit, reading.D1))
        self.assertFalse(has(go_plan, audit, reading.D1))
        self.assertIn((reading.P + 'migration-report.md', '总则'), refs('global-orchestrator', operation='audit-assign'))
        self.assertNotIn((reading.P + 'migration-report.md', '总则'), go_collect)
        self.assertIn((reading.P + 'source-changes.md', None), refs('global-orchestrator', operation='source-review'))
        accept, freeze = refs('module-orchestrator', operation='accept'), refs('module-orchestrator', operation='freeze')
        self.assertFalse(has(accept, reading.P + 'state-machine.md', 'Freeze / DoD 分开'))
        self.assertTrue(has(freeze, reading.P + 'state-machine.md', 'Freeze / DoD 分开'))
        self.assertTrue(has(freeze, decomposition, '总则'))
        self.assertFalse(has(accept, decomposition, '总则'))
        self.assertNotIn((reading.P + 'openspec.md', None), refs('spec-designer'))
        self.assertNotIn((reading.P + 'openspec.md', 'Ledger 物化与修复记忆'), refs('spec-designer'))
        self.assertNotIn((reading.P + 'telemetry.md', '总则'), refs('implementer'))
        self.assertIn((reading.P + 'telemetry.md', '总则'), refs('implementer', telemetry=True))
        self.assertIn((reading.P + 'reuse-dependencies.md', '总则'), refs('auditor', reuse=True))
        self.assertNotIn((reading.P + 'reuse-dependencies.md', '总则'), refs('auditor'))
        self.assertIn((decomposition, '总则'), refs('fixer', lean=True))

    def test_a_step_without_triggers_stays_in_the_typical_budget(self):
        worker_roles = ('implementer', 'fixer', 'diagnostician', 'spec-designer')
        steps = [{'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': r} for r in worker_roles]
        steps += [{'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': 'test-runner', 'test_scope': sc}
                  for sc in reading.TEST_SCOPE]
        steps += [{'role': 'module-orchestrator', 'operation': op} for op in
                  ('accept', 'freeze', 'complete', 'diagnosis-accept', 'audit-work', 'audit-resume', 'decompose')]
        steps += [{'role': 'global-orchestrator', 'operation': op} for op in
                  ('register', 'global-plan', 'audit-collect', 'audit-assign', 'audit-route-batch', 'problem-assign', 'source-review')]
        steps += [{'role': 'auditor', 'operation': op} for op in ('audit-code-review', 'audit-plan', 'audit-verdict', 'audit')]
        steps += [{'role': 'escalation', 'operation': 'decision'}]
        for step in steps:
            with self.subTest(step=step):
                total = sum(row['bytes'] for row in reading.card({}, None, step))
                self.assertGreater(total, 0)
                self.assertLessEqual(total, reading.TYPICAL_BUDGET)

    def test_skills_contribute_their_rules_not_their_boilerplate(self):
        skill = 'skills/migration-test/SKILL.md'
        build = reading.entries('test-runner', 'build')
        self.assertIn((skill, '2. 核心规约'), build)
        self.assertNotIn((skill, '1. 定位'), build)
        self.assertNotIn((skill, '4. 接口契约'), build)
        self.assertFalse([h for p, h in build if p == skill and (h or '').startswith('7. Harmony')])
        self.assertTrue([h for p, h in reading.entries('test-runner', 'automation') if p == skill and (h or '').startswith('7. Harmony')])

    def test_operation_rows_deliver_one_row_of_the_matrix(self):
        text = reading.section(reading.P + 'local-runtime.md', '操作矩阵@accept,submit')
        rows = [line for line in text.splitlines() if line.startswith('| ') and not line.startswith('| ---')]
        self.assertEqual([line.split('|')[1].strip() for line in rows], ['operation', 'submit', 'accept'])
        self.assertLess(len(text), 1000)
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        step = f.state()['next_steps'][0]
        row = next(r for r in step['must_read'] if r['section'] and r['section'].startswith('操作矩阵@'))
        self.assertEqual(row['section'], '操作矩阵@assign,submit')
        with self.assertRaises(KeyError):
            reading.section(reading.P + 'local-runtime.md', '没有这一节@x')

    def test_agent_obligation_rows_follow_the_triggers(self):
        quiet = reading.agent_topics('Agents/test-runner.md', {})
        full = reading.agent_topics('Agents/test-runner.md', {'ui': True, 'reuse': True, 'telemetry': True, 'audit': True})
        self.assertIn('上下文就绪', quiet)
        self.assertNotIn('埋点', quiet); self.assertIn('埋点', full)
        self.assertNotIn('视觉', quiet); self.assertIn('视觉', full)
        short = reading.section('Agents/test-runner.md', None, quiet)
        self.assertLess(len(short), len(reading.section('Agents/test-runner.md')))
        self.assertIn('| 上下文就绪 |', short)
        self.assertNotIn('| 埋点 |', short)
        self.assertIn('## 10. Harmony 执行器', short)  # only the obligation table is filtered

    def test_every_moved_topic_rule_is_reachable_from_some_card(self):
        """The topic index in AGENTS.md points at each 总则 section; some card must deliver it when its trigger holds."""
        index = (reading.PACKAGE / 'AGENTS.md').read_text()
        wanted = set(re.findall(r'\]\(([^)#]+\.md)#总则\)', index))
        reachable = set()
        for role in reading.ROLE:
            for scope in (list(reading.TEST_SCOPE) if role == 'test-runner' else [None]):
                for op in (None, 'audit-code-review', 'audit-plan', 'audit-assign', 'source-review', 'register'):
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
