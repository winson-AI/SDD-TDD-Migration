"""Reading cards are materialised once per digest; polling hosts get a bounded status."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import contracts
import ledger
import reading
import test_context_readiness
import test_decomposition
import test_design_stage
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


class StepViewTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def test_a_role_gets_its_step_the_request_fields_and_the_stage_requirement(self):
        f = self.f; f.prepare()
        full, view = ledger.status(f.root), ledger.status(f.root, 'step', 'M001')
        step = full['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role'], step['context_gate']['stage']), ('assign', 'implementer', 'coding'))
        self.assertEqual(view['request'], {'schema_version': 1, 'run_id': full['run_id'], 'module_id': 'M001',
                                           'expected_revision': full['modules']['M001']['revision'], 'operation': 'assign'})
        # The mandatory reads of the stage were only listed by the full view.
        requirement = full['context_requirements']['M001']['coding']
        self.assertEqual(view['context'], {'stage': 'coding', **requirement, 'ready_receipts': []})
        self.assertTrue(view['context']['required_input_refs'])
        self.assertNotIn('context_gate', view['step']); self.assertNotIn('must_read', view['step'])
        self.assertEqual(view['cards'][view['step']['card_sha256']], reading.summary(step['must_read']))
        self.assertEqual(view['module_input'], full['module_inputs']['M001'])
        self.assertEqual(view['module']['freeze_id'], full['modules']['M001']['freeze_id'])
        for key in ('modules', 'module_inputs', 'context_requirements', 'global_plan', 'planning_context', 'next_steps'):
            self.assertNotIn(key, view)
        self.assertLess(len(json.dumps(view)), len(json.dumps(ledger.status(f.root, 'module', 'M001'))) / 2)
        self.assertLess(len(json.dumps(view)), len(json.dumps(full)) / 8)
        with self.assertRaises(ValueError):
            ledger.status(f.root, 'step', 'M999')

    def test_a_worker_finds_its_assignment_and_the_orchestrator_the_submission(self):
        f = self.f; f.prepare(); f.implementation()
        a, result = f.make_test_result()
        view = ledger.status(f.root, 'step', 'M001')
        self.assertEqual((view['step']['operation'], view['request']['operation']), ('await-result', 'submit'))
        self.assertEqual({k: view['assignment'][k] for k in ('assignment_id', 'fencing_token', 'freeze_id', 'code_baseline')},
                         {k: a[k] for k in ('assignment_id', 'fencing_token', 'freeze_id', 'code_baseline')})
        self.assertNotIn('submission', view)
        f.submit(result, a)
        view = ledger.status(f.root, 'step', 'M001')
        self.assertEqual(view['step']['operation'], 'accept')
        self.assertEqual((view['submission']['kind'], view['submission']['green']), ('tests', True))
        self.assertEqual(view['submission']['ref'], f.state()['modules']['M001']['submissions']['TEST1']['ref'])
        self.assertEqual(view['module']['code_baseline'], a['code_baseline'])

    def test_the_global_step_and_planning_steps_carry_the_planning_context(self):
        f = self.f
        full, view = ledger.status(f.root), ledger.status(f.root, 'step')
        self.assertEqual((view['step']['operation'], view['request']['module_id']), ('global-plan', None))
        self.assertEqual(view['request']['expected_revision'], full['revision'])
        self.assertEqual(view['planning_context'], full['planning_context'])
        self.assertEqual(view['context']['stage'], 'global-planning')
        self.assertNotIn('module_input', view)
        f.prepare()  # frozen: dispatching the Implementer is not a planning operation
        self.assertNotIn('planning_context', ledger.status(f.root, 'step', 'M001'))

    def test_a_designer_reads_its_own_stage_requirement_while_its_assignment_runs(self):
        f = self.f; f.global_plan()
        a, _ = test_design_stage.start_design(f, f.plan())
        full, view = ledger.status(f.root), ledger.status(f.root, 'step', 'M001')
        self.assertEqual((view['step']['operation'], view['request']['operation']), ('await-result', 'submit'))
        self.assertEqual(view['context'], {'stage': 'test-design', **full['context_requirements']['M001']['test-design']})
        self.assertEqual(view['assignment']['design_input_ref'], a['design_input_ref'])
        self.assertIn('planning_context', view)

    def test_a_parent_summary_step_has_a_card_like_any_other_step(self):
        d = test_decomposition.DecompositionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        d.root_scope(); d.split(); d.global_plan()
        for mid in ('M001', 'M002'):
            d.prepare_leaf(mid); d.complete_leaf(mid)
        step = next(x for x in d.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertEqual(step['operation'], 'module-summary')
        self.assertEqual(step['card_sha256'], reading.digest_card(step['must_read']))
        self.assertIn('template/status.md', step['templates'])
        view = ledger.status(d.root, 'step', 'M010')
        self.assertEqual(view['request']['expected_revision'], d.state()['module_groups']['M010']['revision'])
        self.assertEqual(view['step']['payload'], step['payload'])


class HashCommandTests(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['contracts.py', *argv]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = contracts.main()
        return code, out.getvalue()

    def test_a_role_computes_references_and_baselines_the_way_the_ledger_checks_them(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'b.py', Path(tmp) / 'a.py'
            a.write_text('x = 1\n'); b.write_text('y = 2\n')
            code, text = self.run_main('ref', str(a), str(b))
            refs = json.loads(text)
            self.assertEqual((code, refs), (0, [contracts.file_ref(a), contracts.file_ref(b)]))
            code, text = self.run_main('baseline', str(a), str(b))
            self.assertEqual(json.loads(text), {'code_files': refs, 'code_baseline': contracts.baseline(refs)})
            doc = Path(tmp) / 'doc.json'; doc.write_text(json.dumps({'b': 1, 'a': [2, 3]}, indent=4))
            code, text = self.run_main('digest', str(doc))
            self.assertEqual(json.loads(text), {'sha256': contracts.digest({'a': [2, 3], 'b': 1})})
            self.assertEqual(self.run_main('ref', str(Path(tmp) / 'missing.py'))[0], 1)


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
