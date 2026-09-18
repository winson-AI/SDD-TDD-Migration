import json
from datetime import datetime
from typing import Any
from agents import Agent, AgentHookContext, RunContextWrapper, ModelResponse, Tool, RunHooks
from openai.types.responses import ResponseReasoningItem, ResponseFunctionToolCall, ResponseOutputMessage

from ..devices.device_protocol import DeviceProtocol
from ..memory.compressed_session import CompressedSession
from ..reporter.reporter_abs import ReporterAbs
from ..memory.tool_recorder import ToolRecorder
from ..reporter.reporter_types import TimeCalculate
from .agent_registry import agent_registry
from ..logger import logger


class DecisionHooks(RunHooks):
    """正确实现 agents 框架支持的钩子"""

    def __init__(
            self,
            device: DeviceProtocol,
            session: CompressedSession,
            report_generator: ReporterAbs = None,
            tool_recorder: ToolRecorder = None,
            task: str = "",
    ):
        """
        Initialize DecisionHooks.

        Args:
            device: Device protocol instance
            session: Compressed session for history
            report_generator: Optional report generator for tracking execution
            tool_recorder: Optional tool recorder for saving tool calls
            task: Original task description (may contain matched knowledge)
        """
        self.report_generator = report_generator
        self.session = session
        self.tool_recorder = tool_recorder
        self._turn_count = 0
        self._tool_call_count = 0
        self._agent_start_time = None
        self._agent_end_time = None
        self._llm_start_time = None
        self._llm_end_time = None
        self._tool_start_time = None
        self._tool_end_time = None
        self.device = device
        self._last_tool_name = None
        self._last_tool_args = None
        self._verify_called = False
        self._premature_conclusion_count = 0

        # 从任务描述中提取知识库内容（从"知识库："开始到末尾）
        self._knowledge = ""
        if task:
            idx = task.find("知识库：")
            if idx != -1:
                self._knowledge = task[idx:]
        # 存入 agent_registry 供 execute 工具读取，避免修改会话历史
        agent_registry.set_knowledge(self._knowledge)

    async def on_agent_start(
            self,
            context: AgentHookContext,
            agent: Agent,
    ) -> None:
        self._agent_start_time = datetime.now()
        current_time = self._agent_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(f"[{current_time}] [{agent.name}] Agent started")
        if self.report_generator:
            self.report_generator.planner_agent_start(agent=agent)

    async def on_agent_end(
            self,
            context: AgentHookContext,
            agent: Agent,
            output: Any,
    ) -> None:
        self._agent_end_time = datetime.now()
        time_calculate = TimeCalculate(self._agent_start_time, self._agent_end_time)
        current_time = self._agent_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(f"[{current_time}] [{agent.name}] Agent finished with output: {output}")
        if self.report_generator:
            self.report_generator.planner_agent_end(time_calculate=time_calculate, agent=agent, output=output)

    async def on_llm_start(
            self,
            context: RunContextWrapper,
            agent: Agent,
            system_prompt: str | None,
            input_items: list,
    ) -> None:
        self._llm_start_time = datetime.now()
        current_time = self._llm_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(f"[{current_time}] [{agent.name}] Preparing LLM input with screenshot...")

        try:
            screenshot = self.device.get_screenshot(save_to_report=True)

            if screenshot and screenshot.base64_data:
                # Add screenshot to report
                if self.report_generator:
                    self.report_generator.planner_llm_start(screenshot=screenshot, turn_count=self._turn_count)

                image_url = f"data:image/jpeg;base64,{screenshot.base64_data}"
                current_app = self.device.get_current_app()

                # Build screen info
                screen_info = f"Current app: {current_app}"
                text_content = f"** Screen Info **\n\n{screen_info}"

                # 强制性拦截反思
                if self._tool_call_count >= 10:
                    reflection_warning = (
                        "\n\n"
                        "⚠️⚠️⚠️ 系统级警告 (SYSTEM WARNING) ⚠️⚠️⚠️\n"
                        "你已连续执行了超过 10 步工具调用而没有进行反思总结。\n"
                        "确认当前是否正在按照skill操作步骤执行，如果是的话，继续按照skill操作步骤执行；否则，为了防止任务由于上下文过长而进入死循环或者记忆丢失，你【必须】立即调用 `summary` 工具来梳理进度、记录障碍并制定下一步计划。\n"
                        "在调用 `summary` 工具之前，禁止继续执行任何业务操作 (如 `execute`)。"
                    )
                    text_content += reflection_warning
                    logger.warning(f"[{current_time}] [{agent.name}] Mandatory reflection "
                                   f"warning injected (count: {self._tool_call_count})]")

                # Construct image message
                image_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": text_content
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url
                        }
                    ]
                }

                # Append to input_items
                input_items.append(image_message)

                await self.session.add_items([image_message])

                logger.info(f"[{current_time}] [{agent.name}] Injected screenshot into LLM input")

        except Exception as e:
            logger.warning(f"Failed to inject screenshot in on_llm_start: {e}")

    async def on_llm_end(
            self,
            context: RunContextWrapper,
            agent: Agent,
            response: ModelResponse,
    ) -> None:
        self._llm_end_time = datetime.now()
        current_time = self._llm_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        duration = (self._llm_end_time - self._llm_start_time).total_seconds() if self._llm_start_time else 0.0
        duration_str = f"{duration:.2f}s"

        time_calculate = TimeCalculate(self._llm_start_time, self._llm_end_time)

        if self.report_generator:
            self.report_generator.planner_llm_end(time_calculate=time_calculate, response=response, agent=agent,
                                                  turn_count=self._turn_count)

        logger.info(f"[{current_time}] [{agent.name}] --- LLM Response Summary (Duration: {duration_str}) ---")

        self._turn_count += 1

        screenshot_path = None

        # 1. 打印普通文本回复（如果有）
        for item in response.output:
            if isinstance(item, ResponseOutputMessage):
                message = ""
                for content in item.content:
                    if hasattr(content, 'text'):
                        message = content.text
                        break
                logger.info(f"[{current_time}] [{agent.name}] content: {message}")

        # 2. 解析并打印 Reasoning（思维链）
        for item in response.output:
            if isinstance(item, ResponseReasoningItem):
                summary_text = ""
                for summary in item.summary:
                    if hasattr(summary, 'text'):
                        summary_text = summary.text
                        break
                logger.info(f"[{current_time}] [{agent.name}] Reasoning: {summary_text}")

        # 3. 解析并打印工具调用，保存参数用于录制
        for item in response.output:
            if isinstance(item, ResponseFunctionToolCall):
                try:
                    args = json.loads(item.arguments)
                    logger.info(f"[{current_time}] [{agent.name}] Tool Call -> {item.name} args: {args}")
                    # 保存工具名称和参数，用于 on_tool_end 时录制
                    self._last_tool_name = item.name
                    self._last_tool_args = args
                except json.JSONDecodeError:
                    logger.warning(f"[{agent.name}] Failed to parse tool arguments: {item.arguments}")

        if response.usage:
            logger.info(f"[{current_time}] [{agent.name}] Token Usage: "
                        f"Input={response.usage.input_tokens}, "
                        f"Output={response.usage.output_tokens}. "
                        f"Total={response.usage.total_tokens}")

            if self.report_generator:
                self.report_generator.token_usage({
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.total_tokens
                }, source="Planner")

        logger.info(f"[{current_time}] [{agent.name}] --- End of LLM Response ---")

        # 检测任务结项但未调用verify工具的情况
        # 如果模型输出"任务结果: 通过/不通过"且从未调用过verify工具，
        # 则注入一个summary工具调用，强制循环继续并提示模型先验证
        if not self._verify_called and self._premature_conclusion_count < 2:
            has_tool_calls = any(
                isinstance(item, ResponseFunctionToolCall) for item in response.output
            )
            if not has_tool_calls:
                response_text = ""
                for item in response.output:
                    if isinstance(item, ResponseOutputMessage):
                        for content in item.content:
                            if hasattr(content, 'text'):
                                response_text = content.text
                                break
                        if response_text:
                            break

                if "任务结果: 通过" in response_text or "任务结果: 不通过" in response_text:
                    self._premature_conclusion_count += 1
                    logger.warning(
                        f"[{current_time}] [{agent.name}] 检测到任务结项但未调用verify工具进行断言，"
                        f"注入summary工具调用提示模型先验证 (count: {self._premature_conclusion_count})"
                    )

                    summary_args = json.dumps({
                        "executed_tasks": "任务操作步骤已执行完成，但尚未进行结果验证",
                        "current_blockers": "还没有调用过verify工具进行断言，不能自行断言",
                        "next_plan": "还没有调用过verify工具进行断言，不能自行断言。"
                                     "请立即调用 verify 工具验证预期结果，验证完成后再进行任务结项。"
                                     "禁止在没有调用verify工具的情况下直接给出任务结果。"
                    }, ensure_ascii=False)

                    tool_call = ResponseFunctionToolCall(
                        arguments=summary_args,
                        call_id=f"premature_verify_{self._premature_conclusion_count}",
                        name="summary",
                        type="function_call",
                        id=f"fc_premature_verify_{self._premature_conclusion_count}",
                        status="completed",
                    )
                    response.output.append(tool_call)

                    self._last_tool_name = "summary"
                    self._last_tool_args = json.loads(summary_args)

    async def on_tool_start(
            self,
            context: RunContextWrapper,
            agent: Agent,
            tool: Tool,
    ) -> None:
        self._tool_start_time = datetime.now()
        current_time = self._tool_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(f"[{current_time}] [{agent.name}] Calling tool: {tool.name}")

        # 确保 tool.name 与之前保存的一致（如果已从 on_llm_end 保存）
        if self._last_tool_name is None or self._last_tool_name != tool.name:
            self._last_tool_name = tool.name
            self._last_tool_args = {}

        screenshot = None
        layout_data = None
        try:
            screenshot = self.device.get_screenshot(save_to_report=True)
            layout_data = screenshot.layout_data if hasattr(screenshot, 'layout_data') else None
        except Exception as e:
            logger.warning(f"Failed to capture screenshot in on_tool_start: {e}")

        if self.report_generator:
            self.report_generator.planner_tools_start(screenshot=screenshot, tool=tool)

    async def on_tool_end(
            self,
            context: RunContextWrapper,
            agent: Agent,
            tool: Tool,
            result: str,
    ) -> None:
        self._tool_end_time = datetime.now()
        current_time = self._tool_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        duration = (self._tool_end_time - self._tool_start_time).total_seconds() if self._tool_start_time else 0.0
        duration_str = f"{duration:.2f}s"

        result = str(result)
        logger.info(f"[{current_time}] [{agent.name}] Tool {tool.name} finished with "
                    f"result: {result[:200]}... (Duration: {duration_str})")
        time_calculate = TimeCalculate(self._tool_start_time, self._tool_end_time)
        screenshot = None

        try:
            screenshot = self.device.get_screenshot(save_to_report=True)
        except Exception as e:
            logger.warning(f"Failed to capture screenshot in on_tool_end: {e}")

        if self.report_generator:
            self.report_generator.planner_tools_end(screenshot=screenshot, time_calculate=time_calculate, tool=tool,
                                                    result=result)

        if tool.name == "summary":
            self._tool_call_count = 0
            logger.info(f"[{current_time}] [{agent.name}] Tool count reset by 'summary'")
        else:
            self._tool_call_count += 1
            logger.info(f"[{current_time}] [{agent.name}] Continuous tool calls: {self._tool_call_count}")

        if tool.name == "verify":
            self._verify_called = True
            logger.info(f"[{current_time}] [{agent.name}] verify tool called, assertion recorded")

        if self.tool_recorder:
            tool_name = self._last_tool_name or tool.name
            tool_args = self._last_tool_args or {}
            # 获取 execute 期间累积的所有 click 缓存列表
            click_caches = agent_registry.get_last_click_caches()

            logger.info(
                f"[DecisionHooks] Recording tool_call: tool_name={tool_name}, "
                f"click_cache_count={len(click_caches)}"
            )

            self.tool_recorder.record_tool_call(
                tool_name, tool_args, result,
                click_caches=click_caches if click_caches else None
            )
            agent_registry.clear_last_click_cache()

        # Check for start_app failure and terminate task immediately
        if tool.name == "start_app" and "failed!" in result:
            logger.error(f"[{current_time}] [{agent.name}] Tool {tool.name} failed. result: {result[:200]}")
            raise RuntimeError(f"任务终止: {result}, 启动app超时！")
