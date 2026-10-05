"""Step ordering and real subprocess deadlines; device/media fixtures are synthetic."""
import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest

import test_harmony
from harmony_adapter import observing_verifier
from harmony_contract import write
from harmony_steps import Steps
from path_execution import inspect


async def drive_fixture_steps(sink, action=None):
    """Exercise the registered step tool with explicit synthetic native action events."""
    from unittest.mock import patch
    from AutoTest.layered_agent_cli import mcp_tools
    from AutoTest.layered_agent_cli.agent_registry import agent_registry
    from AutoTest.reporter.reporter_types import ReportEvent, EventType
    report = agent_registry.get_verify_agent().report
    async def invoke(context, raw):
        number = sink.current_step + 1
        if action: action(number)
        report.events += [
            ReportEvent(EventType.GLM_ACTION, step_number=number, data={'action': {'_metadata': 'do', 'action': 'Tap'}}),
            ReportEvent(EventType.GLM_STEP_END, step_number=number, data={'success': True})]
        return '{"success":true,"result":"synthetic test action"}'
    with patch.object(mcp_tools.execute, 'on_invoke_tool', new=invoke):
        for number in range(1, len(sink.query['steps']) + 1):
            await mcp_tools.TOOL_REGISTRY['execute_step'].on_invoke_tool(None, json.dumps({'step_number': number}))


class StepTests(unittest.TestCase):
    def setUp(self):
        fixture = test_harmony.ContractTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.out, self.sink = fixture.out, fixture.sink
        self.config = SimpleNamespace(step_timeout=2, task_timeout=10)
        self.steps = Steps(self.sink, self.config, SimpleNamespace(arm=lambda *a: None))
        self.report = SimpleNamespace(step_content=[], events=[])
        self.counter = 0
        self.verifier = SimpleNamespace(report=self.report, device=SimpleNamespace(get_screenshot=self.capture))

    def capture(self, **kwargs):
        self.counter += 1
        file = self.out / f'fixture-{self.counter}.png'; file.write_bytes(b'explicit synthetic pixels')
        return SimpleNamespace(screenshot_path=str(file))

    async def invoke(self, message):
        from AutoTest.reporter.reporter_types import ReportEvent, EventType
        self.report.events += [
            ReportEvent(EventType.GLM_ACTION, step_number=1, data={'action': {'_metadata': 'do', 'action': 'Tap'}}),
            ReportEvent(EventType.GLM_STEP_END, step_number=1, data={'success': True})]
        return json.dumps({'success': True, 'result': 'fixture action'})

    def execute(self, number, invoke=None):
        return asyncio.run(self.steps.execute(number, self.verifier, invoke or self.invoke))

    def test_steps_cannot_skip_repeat_or_pass_with_only_prose(self):
        with self.assertRaises(ValueError): self.execute(2)
        self.execute(1)
        with self.assertRaises(ValueError): self.execute(1)
        self.assertEqual(self.sink.report()['quality'], 'yellow-blocked')
        self.execute(2)
        self.sink.record('[ASSERT:A1]', True, 'fixture', 'one_image_assert', [self.out / 'fixture-4.png'])
        self.assertEqual(self.sink.report()['quality'], 'green-passed')
        events = copy.deepcopy(self.sink.observations); events[0]['after_step'] = 1
        self.assertTrue(inspect(self.sink.query, self.sink.step_trace, events, lambda r: r['path']))

    def test_verify_before_checkpoint_does_not_call_model(self):
        class Native:
            def _verify(self, description): raise AssertionError('must not run')
        self.assertFalse(observing_verifier(Native, self.sink)().verify('[ASSERT:A1]')[0])
        self.assertEqual(self.sink.observations[0]['error'], 'step mismatch')

    def test_steps_alone_do_not_prove_checkpoint_completion(self):
        self.execute(1); self.execute(2)
        issues = inspect(self.sink.query, self.sink.step_trace, [], lambda r: r['path'])
        self.assertTrue(any('missing checkpoint' in issue for issue in issues))
        self.sink.query['expected_assertions'][0].pop('after_step')
        self.assertIn('replan within this Run', inspect(self.sink.query, self.sink.step_trace, [], lambda r: r['path'])[0])

    def test_current_assertion_required_before_next_step(self):
        self.sink.query['expected_assertions'][0]['after_step'] = 1
        self.execute(1)
        with self.assertRaisesRegex(ValueError, 'checkpoint first'): self.execute(2)

    def test_no_action_requires_explicit_frozen_permission(self):
        async def no_action(message): return '{"success": true}'
        self.execute(1, no_action)
        self.assertEqual(self.sink.step_trace['steps'][0]['status'], 'blocked')
        with self.assertRaisesRegex(ValueError, 'interrupted'): self.execute(2)

    def test_already_satisfied_step_is_evidenced_and_opt_in(self):
        self.sink.query['steps'][0] = {'instruction': 'ensure tab selected', 'allow_already_satisfied': True}
        self.steps = Steps(self.sink, self.config, SimpleNamespace(arm=lambda *a: None))
        async def no_action(message): return '{"success": true}'
        self.execute(1, no_action)
        self.assertEqual(self.sink.step_trace['steps'][0]['status'], 'already-satisfied')
        self.assertIn('before_ref', self.sink.step_trace['steps'][0])

    def test_fixed_selector_never_calls_model_and_uses_exact_checkpoint(self):
        self.execute(1); self.execute(2)
        class Native:
            def _select_tool_and_steps(self, description): raise AssertionError('unnecessary model call')
        selected = observing_verifier(Native, self.sink)()._select_tool_and_steps('[ASSERT:A1]')
        self.assertEqual(selected['tool'], 'one_image_assert')
        self.assertEqual(selected['current_step_index'], self.sink.step_trace['steps'][1]['after_index'])

    def test_media_or_device_action_receipt_tamper_is_not_green(self):
        self.execute(1); self.execute(2)
        self.sink.record('[ASSERT:A1]', True, 'fixture', 'one_image_assert', [self.out / 'fixture-4.png'])
        self.sink.step_trace['steps'][0]['actions'] = [{'action': 'invented'}]
        self.assertEqual(self.sink.report()['quality'], 'yellow-blocked')

    def test_deadline_stops_blocking_call_and_descendant_without_late_action(self):
        marker = self.out / 'late-device-action'
        child = "import time;from pathlib import Path;time.sleep(1);Path(" + repr(str(marker)) + ").write_text('late')"
        code = f'''import sys,time,subprocess
sys.path.insert(0,{str(test_harmony.SCRIPTS)!r})
from pathlib import Path
from types import SimpleNamespace
from harmony_steps import Deadline
sink=SimpleNamespace(output=Path({str(self.out)!r}),current_step=1)
subprocess.Popen([sys.executable,'-c',{child!r}])
deadline=Deadline(sink,.15)
time.sleep(30)
'''
        started = time.monotonic()
        result = subprocess.run([sys.executable, '-B', '-c', code], start_new_session=True, capture_output=True, timeout=4)
        self.assertLess(result.returncode, 0)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(json.loads((self.out / 'interruption.json').read_text())['after_step'], 1)
        time.sleep(1)
        self.assertFalse(marker.exists())

    def test_interrupted_evidence_replace_keeps_prior_observations(self):
        from unittest.mock import patch
        target = self.out / 'observations.json'
        write(target, [{'result': False}])
        with patch('harmony_contract.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): write(target, [{'result': True}])
        self.assertEqual(json.loads(target.read_text()), [{'result': False}])
        self.assertFalse(target.with_name('observations.json.tmp').exists())


if __name__ == '__main__': unittest.main()
