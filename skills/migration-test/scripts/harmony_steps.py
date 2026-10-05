"""Ordered frozen-step execution over the native device/executor; one trace per PATH."""
from datetime import datetime, timezone
import json
import os
import signal
import threading
import time

from harmony_contract import digest, ref, write


class Deadline:
    """A hard attempt limit also interrupts blocking SDK calls and executor threads.

    The formal host owns the process group and interprets the flushed evidence.
    A timeout never permits another step while a device worker may still be alive.
    """
    def __init__(self, sink, seconds):
        self.sink, self.ends = sink, time.monotonic() + seconds
        self.timer = None
        self.lock, self.generation = threading.Lock(), 0
        self.arm(seconds, 'path')

    def arm(self, seconds, stage):
        with self.lock:
            if self.timer: self.timer.cancel()
            self.generation += 1
            generation = self.generation
            def expired():
                with self.lock:
                    if generation != self.generation: return
                    self.sink.error = stage + ' deadline exceeded'
                    try:
                        write(self.sink.output / 'interruption.json', {'reason': self.sink.error,
                              'after_step': getattr(self.sink, 'current_step', 0), 'pid': os.getpid()})
                    finally:
                        # Stop even if evidence storage fails; never leave a late device action running.
                        if os.getpgrp() == os.getpid(): os.killpg(os.getpid(), signal.SIGKILL)
                        else: os.kill(os.getpid(), signal.SIGKILL)
            self.timer = threading.Timer(max(.001, min(seconds, self.ends - time.monotonic())), expired)
            self.timer.daemon = True
            self.timer.start()

    def close(self):
        with self.lock:
            self.generation += 1
            if self.timer: self.timer.cancel()


class Steps:
    def __init__(self, sink, config, deadline):
        self.sink, self.config, self.deadline = sink, config, deadline
        self.busy = False
        sink.current_step = 0
        sink.step_trace = {'schema_version': 1, 'query_sha256': digest(sink.query), 'steps': [
            {'step_number': i, 'step_sha256': digest(step), 'status': 'not-executed'}
            for i, step in enumerate(sink.query['steps'], 1)]}
        self.flush()

    def flush(self):
        write(self.sink.output / 'step-trace.json', self.sink.step_trace)

    async def execute(self, number, verifier, invoke):
        sink = self.sink
        if sink.error: raise ValueError('PATH interrupted; stop without retry')
        if self.busy or type(number) is not int or number != sink.current_step + 1 or number > len(sink.query['steps']):
            raise ValueError('execute the next frozen step once, in order')
        pending = [a['assertion_id'] for a in sink.query['expected_assertions']
                   if a['after_step'] == sink.current_step and not any(
                       e['assertion_ids'] == [a['assertion_id']] for e in sink.observations)]
        if pending: raise ValueError('verify the current checkpoint first: ' + ', '.join(pending))
        row = sink.step_trace['steps'][number - 1]
        if row['status'] != 'not-executed': raise ValueError('step already attempted; preserve failure and stop')
        self.busy = True
        row.update(status='running', started_at=datetime.now(timezone.utc).isoformat())
        self.flush()
        self.deadline.arm(self.config.step_timeout, f'step {number}')
        try:
            def capture(label):
                from AutoTest.reporter.reporter_types import Step
                shot = verifier.device.get_screenshot(save_to_report=True)
                index = len(verifier.report.step_content)
                verifier.report.step_content.append(Step(index=index, step_type='frozen_step', title=label,
                    timestamp=time.time(), screenshot_path=shot.screenshot_path))
                return index, ref(shot.screenshot_path)
            row['before_index'], row['before_ref'] = capture(f'step {number} before')
            self.flush()
            start = len(verifier.report.events)
            step = sink.query['steps'][number - 1]
            instruction = step if isinstance(step, str) else step['instruction']
            allow = isinstance(step, dict) and step.get('allow_already_satisfied') is True
            message = instruction + ('\n仅当前置状态已满足时可不重复动作。' if allow else '\n必须执行该步骤，不得因页面已满足而省略动作。')
            result = await invoke(message)
            events = [e.to_dict() for e in verifier.report.events[start:]]
            # Pair dispatched device actions with their successful completion events.
            completed = {e['step_number'] for e in events if e['event_type'] == 'glm_step_end' and e['data'].get('success') is True}
            row['actions'] = [e['data']['action'] for e in events if e['event_type'] == 'glm_action'
                              and e['step_number'] in completed and e['data']['action'].get('_metadata') != 'finish']
            action_file = sink.output / f'step-{number}-actions.json'
            write(action_file, {'result': result, 'events': events})
            row['action_ref'] = ref(action_file)
            row['after_index'], row['after_ref'] = capture(f'step {number} after')
            parsed = json.loads(result)
            ok = parsed.get('success') is True
            row['status'] = 'executed' if ok and row['actions'] else 'already-satisfied' if ok and allow else 'blocked'
            if row['status'] == 'blocked': sink.error = f'step {number}: missing successful execution evidence'
            sink.current_step = number
            return json.dumps({'step_number': number, 'status': row['status'], 'result': parsed}, ensure_ascii=False)
        except BaseException:
            row['status'] = 'blocked'
            sink.error = f'step {number}: execution interrupted'
            raise
        finally:
            row['finished_at'] = datetime.now(timezone.utc).isoformat()
            self.flush()
            self.busy = False
            self.deadline.arm(self.config.task_timeout, 'path')


def install(sink, config, deadline):
    from agents import function_tool
    from AutoTest.layered_agent_cli import mcp_tools, planner_agent
    from AutoTest.layered_agent_cli.agent_registry import agent_registry
    steps = Steps(sink, config, deadline)
    previous = (mcp_tools.TOOL_REGISTRY.get('execute_step'), planner_agent.get_registered_tools, planner_agent.PLANNER_INSTRUCTIONS)
    native_execute = mcp_tools.execute

    @function_tool
    async def execute_step(step_number: int) -> str:
        """Execute exactly the next frozen PATH step; no rewritten instruction or retry."""
        return await steps.execute(step_number, agent_registry.get_verify_agent(),
            lambda message: native_execute.on_invoke_tool(None, json.dumps({'message': message}, ensure_ascii=False)))

    mcp_tools.TOOL_REGISTRY['execute_step'] = execute_step
    planner_agent.get_registered_tools = lambda: [execute_step, mcp_tools.TOOL_REGISTRY['verify']]
    planner_agent.PLANNER_INSTRUCTIONS += ('\n本 PATH 只能使用 execute_step(step_number) 逐一执行冻结步骤，'
        '再用 verify 验证该步骤的每个 ASSERT。不能跳步、重试、改写步骤或合并断言；步骤 blocked 时停止并保留证据。')
    def restore():
        tool, planner_agent.get_registered_tools, planner_agent.PLANNER_INSTRUCTIONS = previous
        if tool is None: mcp_tools.TOOL_REGISTRY.pop('execute_step', None)
        else: mcp_tools.TOOL_REGISTRY['execute_step'] = tool
    steps.restore = restore
    return steps
