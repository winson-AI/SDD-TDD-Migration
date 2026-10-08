"""A step hands a role what it needs for that step and nothing it already holds."""
import ast
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import context_readiness as cr
import reading
import test_context_readiness
import test_ledger


def rejection_messages():
    """The literal part of every message a Ledger rule can refuse with."""
    found = set()
    for path in sorted(SCRIPTS.glob('*.py')):
        if path.name.startswith('lean_') or path.name == 'reading.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'require' and len(node.args) >= 2:
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
                elif isinstance(arg, ast.BinOp) and isinstance(arg.left, ast.Constant) and isinstance(arg.left.value, str):
                    found.add(arg.left.value)
                elif isinstance(arg, ast.JoinedStr):
                    found.add(''.join(v.value for v in arg.values if isinstance(v, ast.Constant)))
    return found - {''}


class CardTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def step(self):
        return self.f.state()['next_steps'][0]

    def test_a_section_reaches_a_card_once(self):
        f = self.f; f.global_plan()
        state = f.state()
        for step in ({'role': 'spec-designer', 'operation': 'plan'},
                     {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': 'test-runner', 'mode': 'design'}):
            keys = [reading.key(row) for row in reading.card(state, state['modules']['M001'], step)]
            self.assertEqual(len(keys), len(set(keys)), step)

    def test_a_step_submitted_without_a_model_turn_carries_no_card(self):
        f = self.f; f.prepare()
        step = self.step()
        self.assertEqual((step['operation'], step['mechanical'], step['worker_role']), ('assign', True, 'implementer'))
        self.assertTrue(step['must_read'])  # a dispatch carries the card of the worker it starts
        f.implementation()
        a, result = f.make_test_result(); f.submit(result, a)
        step = self.step()
        self.assertEqual((step['operation'], step['mechanical']), ('accept', True))
        self.assertEqual(step['must_read'], [])  # nobody reads a card to accept a Green result

    def test_without_a_host_report_the_instance_that_acted_holds_its_card(self):
        f = self.f; f.global_plan()
        full = self.step()
        self.assertEqual((full['operation'], full['role']), ('plan', 'spec-designer'))
        self.assertNotIn('must_read_new', full)  # nobody has acted yet: the whole card applies
        f.call('plan', {'plan_ref': f.ref('plan.json', f.plan())}, role='spec-designer')
        m = f.state()['modules']['M001']
        self.assertEqual(m['actors'], {'spec-designer': 'spec-designer'})
        self.assertEqual(set(m['delivered_cards']['spec-designer']), {reading.key(row) for row in full['must_read']})
        f.call('planning-reopen', {'reason_ref': f.ref('reopen.md', 'a gap found before coding')})
        again = self.step()
        self.assertEqual((again['operation'], again['card_new_for']), ('plan', 'spec-designer'))
        self.assertEqual([row['ref'] for row in again['must_read_new']], ['AGENTS.md'])  # only the red lines again
        self.assertEqual(m['card_load']['dispatches'], 1)

    def test_a_dispatched_worker_holds_its_card_and_a_host_step_records_nothing(self):
        f = self.f; f.prepare()
        f.assign('implementer', 'I1')
        m = f.state()['modules']['M001']
        self.assertIn('implementer', m['delivered_cards'])
        self.assertEqual(m['actors']['implementer'], 'implementer')
        # The plan and the freeze were read by the instances that submitted them. The dispatch itself may be submitted by
        # the host as the module orchestrator without a model turn, so it records a card for the worker only.
        self.assertEqual(set(m['delivered_cards']), {'spec-designer', 'module-orchestrator', 'implementer'})
        self.assertEqual(m['card_load']['dispatches'], 3)


class WorkerInputTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()

    def test_a_worker_reads_what_its_step_executes(self):
        state = self.f.state(); m = state['modules']['M001']
        paths = lambda stage: {ref['path'] for ref in cr.input_refs(state, 'M001', stage)}
        plan = {m['plan_ref']['path']}
        sources = {ref['path'] for ref in m.get('context_refs', [])} | {state['global_spec']['path']}
        self.assertEqual(paths('testing'), plan | {d['path'] for d in m['plan']['definitions'] if d['kind'].startswith('test-') and d['kind'] != 'test-design'})
        self.assertEqual(paths('building'), paths('testing'))
        self.assertLessEqual(plan | {state['new_architecture']['path']}, paths('coding'))
        self.assertEqual(paths('fixing'), paths('coding'))  # plus the diagnosis once there is one
        for stage in ('testing', 'building', 'coding', 'fixing'):
            self.assertFalse(sources & paths(stage), stage)  # the legacy sources of the allocation are reference material
        self.assertLessEqual(sources, paths('planning'))  # a planner still stands on all of it

    def test_a_ready_report_still_stands_on_everything_the_run_holds_for_the_module(self):
        state = self.f.state()
        standing = {ref['path'] for ref in cr.standing_refs(state, 'M001', 'coding')}
        self.assertLess({ref['path'] for ref in cr.input_refs(state, 'M001', 'coding')}, standing)
        self.assertIn(state['global_spec']['path'], standing)


class HintTests(unittest.TestCase):
    def test_most_rejections_name_the_section_that_states_their_rule(self):
        messages = rejection_messages()
        hinted = [message for message in messages if reading.read_hint(message)]
        self.assertGreaterEqual(len(hinted) / len(messages), reading.HINT_COVERAGE,
                                'a rule added without a hint leaves its rejection without a section to read')
        for hint in {(h['ref'], h['section']) for h in map(reading.read_hint, messages) if h}:
            reading.section(*hint)  # every hinted section exists

    def test_a_rejection_points_at_the_rule_not_at_a_word_in_its_message(self):
        for message, heading in (('configuration mapping differs from source or target qualifier', '精确性纪律'),
                                 ('dependencies not complete', 'Module-Orchestrator 唯一模块守卫'),
                                 ('global coverage review required', '3. 分配与登记门禁'),
                                 ('verification boundary required', '验证边界'),
                                 ('run impact revise needs a frozen, unblocked leaf whose boundary the revision keeps; replan otherwise', '同 Run 上游修订'),
                                 ('absolute evidence path required, got None', '请求与事件')):
            self.assertEqual(reading.read_hint(message)['section'], heading, message)


if __name__ == '__main__':
    unittest.main()
