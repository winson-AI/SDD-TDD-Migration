"""Open issues are counted by family before they are listed: a step, a preview and the report say how many gaps each rule
family still owes, however many rows the step shows."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import issues
import ledger
import migration_report
import test_reuse


class OwedFamilyTests(unittest.TestCase):
    def test_every_owed_rule_family_is_named_and_other_issues_count_by_kind(self):
        samples = {'资源闭包': 'UI resource closure requires one item for @drawable/ic_off', '源闭包': 'ui_fidelity_required: source_closure.states required for UI scope',
                   'UI 目标与证据': 'runtime UI targets lack visual paths: login:error:viewport', '场景追溯': 'scenario_trace must cover every frozen Scenario exactly once',
                   '四维追溯': 'dimension behavior requires case paths; build alone is not fidelity', 'API 契约': 'API behavior assertion coverage incomplete: ACCOUNT',
                   '数据契约': 'data fidelity requires actual behavior tests', '复用': 'reuse source review incomplete; resolve before freeze',
                   '测试准备': 'resolve deferred test preparation before freeze', '参数表': 'tokens the Spec must map or mark not applicable: Fonts.bold',
                   '埋点': 'telemetry review must cover scoped tasks', '测试路径': 'spec_closure_required: plan one static spec-closure PATH',
                   '用户媒体': 'the user showed C1: cite its screenshot in P1', '目标画像': 'the target already holds Kotlin code for login: reuse or adapt it',
                   '计划': 'a leaf plans at most 8 tasks: the fine grain is the task', 'UI 树': 'native UI validation: node:root lacks a source', '其他': 'something new the table does not know'}
        self.assertEqual({issues.family('gap', text) for text in samples.values()}, set(samples))
        self.assertEqual([issues.family('gap', text) for text in samples.values()], list(samples))
        self.assertEqual(issues.family('defect', 'reuse provider crashed'), 'defect')
        rows = [{'kind': 'gap', 'summary': 'telemetry review must cover scoped tasks'}, {'kind': 'defect', 'summary': 'a crash'}, {'kind': 'gap', 'summary': 'telemetry path not traced by event tasks'}]
        self.assertEqual(list(issues.families(rows).items()), [('埋点', 2), ('defect', 1)])

    def test_the_step_the_preview_and_the_report_count_what_the_leaf_owes_by_family(self):
        t = test_reuse.ReuseTests('setUp'); t.setUp(); self.addCleanup(t.doCleanups)
        plan, review, cat, _ = t.selected_plan()
        cat['source_reviews'][0]['status'] = 'unavailable'
        review['catalog_ref'] = t.ref('pending-catalog.json', cat); t.save_review(plan, review)
        t.global_plan()
        plan_ref = t.ref('pending-plan.json', plan)
        preview = ledger.preview(t.root, 'M001', plan_ref)
        self.assertIn('复用', preview['owed_by_family'])
        self.assertTrue(all(r.startswith('reuse') for r in preview['owed_by_family']['复用']))
        t.call('plan', {'plan_ref': plan_ref}, role='spec-designer')
        step = ledger.status(t.root, 'step', 'M001')
        self.assertEqual(step['open_issue_families'], {'复用': 1})
        self.assertEqual([row['kind'] for row in step['open_issues']], ['gap'])
        s = t.state()
        report = migration_report.build(t.root, s, s['last_sequence'])
        self.assertEqual(report['open_issue_families'], {'复用': 1})
        self.assertIn('按族：复用 1', migration_report.render(report))


if __name__ == '__main__':
    unittest.main()


class FamilyCoverageTests(unittest.TestCase):
    def test_every_gap_the_scripts_owe_belongs_to_a_named_family(self):
        import ast, glob
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        def text(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str): return node.value
            if isinstance(node, ast.BinOp): return text(node.left) + (text(node.right) if isinstance(node.op, ast.Add) else '')
            if isinstance(node, ast.JoinedStr): return ''.join(text(v) for v in node.values if not isinstance(v, ast.FormattedValue))
            return ''
        unnamed = []
        for file in sorted(glob.glob(str(scripts / '*.py'))):
            for node in ast.walk(ast.parse(Path(file).read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'owed' and len(node.args) >= 2:
                    message = text(node.args[1])
                    if message and issues.family('gap', message) == '其他':
                        unnamed.append((Path(file).name, node.lineno, message[:60]))
        self.assertEqual(unnamed, [], 'an owed gap without a family: add its rule to issues.FAMILIES')
