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
        source = refs('global-orchestrator', operation='source-review')
        self.assertTrue(has(source, reading.P + 'source-changes.md', '1. GO：评估来源、归属与影响范围'))
        self.assertFalse(has(source, reading.P + 'source-changes.md', '2. Host：版本事务与明确恢复'))
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
                names = reading.templates({}, None, step)
                self.assertLessEqual(sum((reading.PACKAGE / n).stat().st_size for n in names), reading.TEMPLATE_BUDGET)

    def test_agent_blocks_follow_the_test_scope(self):
        def text(scope):
            step = {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': 'test-runner', 'test_scope': scope}
            row = next(r for r in reading.card({}, None, step) if r['ref'] == 'Agents/test-runner.md')
            return reading.text_of(row)
        build, automation, design = text('build'), text('automation'), text('design')
        self.assertIn('### 构建', build); self.assertIn('### 单测与静态审查', build)
        self.assertNotIn('### 自动化', build); self.assertNotIn('## 10. Harmony 执行器', build)
        self.assertIn('### 自动化', automation); self.assertIn('## 10. Harmony 执行器', automation); self.assertNotIn('### 设计', automation)
        self.assertIn('### 设计', design); self.assertNotIn('### 构建', design)
        for part in (build, automation, design):
            self.assertIn('## 6. 硬约束', part); self.assertIn('## 专题义务', part)

    def test_steps_name_the_templates_they_instantiate(self):
        names = set()
        for table in reading.TEMPLATES.values():
            for group in table.values(): names |= set(group)
        for group in reading.SCOPE_TEMPLATES.values(): names |= set(group)
        for by_role in reading.TRIGGER_TEMPLATES.values():
            for group in by_role.values(): names |= set(group)
        self.assertEqual([n for n in sorted(names) if not (reading.PACKAGE / 'template' / n).is_file()], [])
        visual = reading.templates({}, None, {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': 'test-runner', 'test_scope': 'visual'})
        self.assertIn('template/visual-alignment.json', visual)
        self.assertNotIn('template/visual-alignment.json',
                         reading.templates({}, None, {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': 'test-runner', 'test_scope': 'build'}))
        self.assertIn('template/reuse-plan.json', reading.templates({'reuse_required': True}, None, {'role': 'spec-designer', 'operation': 'plan'}))
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        self.assertIn('template/implementation.md', f.state()['next_steps'][0]['templates'])

    def test_a_rendered_card_has_no_link_into_a_whole_protocol_file(self):
        text = reading.unlink('见 [状态机](state-machine.md)、[有限循环](state-machine.md#有限循环)、[模板](../../../template/fix-note.json)、'
                              '[清单](../../../template/checklist.md) 和 [官网](https://example.invalid/x)。', reading.P + 'testing.md')
        self.assertEqual(text, '见 状态机、有限循环（skills/migration-protocol/references/state-machine.md § 有限循环）、'
                               '模板（template/fix-note.json）、清单（template/checklist.md） 和 [官网](https://example.invalid/x)。')
        import tempfile
        for role in reading.ROLE:
            rows = reading.card({}, None, {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': role, 'test_scope': 'automation'})
            with tempfile.TemporaryDirectory() as tmp:
                body = Path(reading.render(rows, tmp, ['template/x.json'])['path']).read_text()
            self.assertEqual(re.findall(r'\]\((?![a-z]+:)[^)]*\)', body), [], role)
            self.assertIn('reading.py show', body)
            self.assertIn('- template/x.json', body)

    def test_no_card_names_a_whole_protocol_file(self):
        """A link in a card selects a section or names a template; a role is never sent to a whole protocol file."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            analysis = Path(tmp) / 'dimensions.json'
            analysis.write_text(json.dumps({'dimensions': [{'dimension': 'UI', 'status': 'applicable'}]}))
            s = {'reuse_required': True, 'dependency_resolution_required': True, 'fixer_self_diagnosis': True}
            m = {'lean_leaf': True, 'audit_batch_id': 'B1',
                 'plan': {'dimension_analysis_ref': {'path': str(analysis)}, 'telemetry': {'status': 'applicable'}}}
            operations = set(reading.AUDIT_OPS) | set(reading.MO_OPS) | {
                None, 'register', 'global-plan', 'source-review', 'reconfigure-sources', 'audit-code-review', 'plan', 'diagnose', 'decision'}
            steps = [{'role': role, 'operation': op} for role in reading.ROLE for op in operations]
            steps += [{'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': role, 'test_scope': scope,
                       'mode': 'design' if scope == 'design' else None}
                      for role in reading.ROLE for scope in (None, *reading.TEST_SCOPE)]
            whole = set()
            for step in steps:
                for row in reading.card(s, m, step):
                    base = (reading.PACKAGE / row['ref']).parent
                    for label, target in re.findall(r'\[([^\]]+)\]\(([^)\s]+)\)', reading.text_of(row)):
                        path, _, anchor = target.partition('#')
                        resolved = (base / path).resolve() if path else (reading.PACKAGE / row['ref']).resolve()
                        if re.match(r'[a-z]+:', target) or resolved.suffix != '.md' or not resolved.is_relative_to(reading.PACKAGE):
                            continue
                        rel = str(resolved.relative_to(reading.PACKAGE))
                        if rel.startswith('template/') and rel != 'template/INDEX.md':
                            continue  # a template is instantiated as a file
                        if not (anchor and reading._heading_of(rel, anchor)):
                            whole.add((row['ref'], row['section'], label, rel))
            self.assertEqual(sorted(whole, key=str), [])
            self.assertTrue(any(row['ref'].endswith('ui-fidelity.md') for row in reading.card(s, m, {'role': 'spec-designer', 'operation': 'plan'})))

    def test_a_card_carries_an_agent_without_its_pointer_only_sections(self):
        row = next(r for r in reading.card({}, None, {'role': 'implementer', 'operation': 'submit'}) if r['ref'] == 'Agents/implementer.md')
        text = reading.text_of(row)
        self.assertNotIn('Used Skills', text)
        for title in ('## 4. 规则优先级', '## 5. 阻塞与异常', '## 7. 输出格式'):
            self.assertNotIn(title, text)  # these only point at the shared conventions, which the card holds
        self.assertIn('## 9. Checkpoints', text); self.assertIn('## 6. 硬约束', text)
        shared = [r for r in reading.card({}, None, {'role': 'implementer', 'operation': 'submit'}) if r['ref'] == reading.SHARED]
        self.assertNotIn('1. 定位', [r['section'] for r in shared]); self.assertIn('通用约定', [r['section'] for r in shared])
        self.assertNotIn('专题规则', ''.join(reading.text_of(r) for r in shared))  # the card itself answers where rules sit
        definition = reading.section('Agents/implementer.md')  # the definition itself keeps them
        self.assertIn('## 8. Used Skills', definition); self.assertIn('## 7. 输出格式', definition)
        runner = next(r for r in reading.card({}, None, {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': 'test-runner',
                                                         'test_scope': 'build'}) if r['ref'] == 'Agents/test-runner.md')
        self.assertIn('## 5. 阻塞与异常', reading.text_of(runner))  # a section with rules of its own stays

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
        self.assertEqual(row['section'], '操作矩阵@assign,context-submit,submit')  # a dispatched worker reports, then submits
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
        for reason in ('back: a non-exact graphic needs either an image_check carried by a visual PATH or an approved deviation',
                       'declared image checks need a visual path carrying device proof: back-icon',
                       'UI image source closure requires one item for src:remote-image:ab12 (remote-image)',
                       'image-parity row differs from its recomputation for back-icon'):
            self.assertEqual(reading.read_hint(reason)['section'], reading.PICTURES, reason)
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
