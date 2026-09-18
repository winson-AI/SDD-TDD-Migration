import json
from typing import Any, Callable
from datetime import datetime

from openai import OpenAI

from ...actions import ActionHandler, ActionResult
from ...config import AgentConfig, ModelConfig, StepResult
from ...devices.device_protocol import DeviceProtocol
from ...logger import logger
from ...reporter.reporter_types import TimeCalculate

from .i18n import get_messages
from ..message_builder import MessageBuilder
from .parser import GLMParser
from .prompts_en import SYSTEM_PROMPT as SYSTEM_PROMPT_EN
from .prompts_zh import SYSTEM_PROMPT as SYSTEM_PROMPT_ZH
from .mcp_prompts import MCP_SYSTEM_PROMPT_ZH
from ..agents_factory import AgentFactory
from ..base_agent import BaseAgent


def get_system_prompt(lang: str = "cn", mode: str = None) -> str:
    if mode == "mcp":
        return MCP_SYSTEM_PROMPT_ZH
    if lang == "en":
        return SYSTEM_PROMPT_EN
    return SYSTEM_PROMPT_ZH


@AgentFactory.register("glm")
class GLMAgent(BaseAgent):
    def __init__(
            self,
            model_config: ModelConfig,
            agent_config: AgentConfig,
            device: DeviceProtocol,
            confirmation_callback: Callable[[str], bool] | None = None,
            takeover_callback: Callable[[str], None] | None = None,
            thinking_callback: Callable[[str], None] | None = None,
            report_generator=None,
    ):
        super().__init__(
            model_config=model_config,
            agent_config=agent_config,
            device=device,
            confirmation_callback=confirmation_callback,
            thinking_callback=thinking_callback,
            report_generator=report_generator
        )

        self.openai_client = OpenAI(
            base_url=model_config.base_url,
            api_key=model_config.api_key,
            timeout=120,
            max_retries=3
        )
        self.parser = GLMParser()

        self.action_handler = ActionHandler(
            device=self.device,
            confirmation_callback=confirmation_callback,
            takeover_callback=takeover_callback,
        )

        self._context: list[dict[str, Any]] = []
        self._screenshot: list[str] = []
        self._step_count = 0
        self._is_running = False

    def run(self, task: str) -> str:
        self._context = []
        self._step_count = 0
        self._is_running = True

        try:
            result = self._execute_step(task, is_first=True)

            if result.finished:
                return result.message or "Task completed"

            while self._step_count < self.agent_config.max_steps and self._is_running:
                result = self._execute_step(is_first=False)

                if result.finished:
                    return result.message or "Task completed"

            return "Max steps reached"
        finally:
            self._is_running = False

    def step(self, task: str | None = None) -> StepResult:
        is_first = len(self._context) == 0

        if is_first and not task:
            raise ValueError("Task is required for the first step")

        return self._execute_step(task, is_first)

    def reset(self) -> None:
        self._context = []
        self._screenshot = []
        self._step_count = 0
        self._is_running = False

    def abort(self) -> None:
        self._is_running = False
        logger.info("Agent aborted by user")

    def _stream_request(
            self,
            messages: list[dict[str, Any]],
            on_thinking_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, str, str]:
        stream = self.openai_client.chat.completions.create(
            messages=messages,  # type: ignore[arg-type]
            model=self.model_config.model_name,
            max_tokens=self.model_config.max_tokens,
            temperature=self.model_config.temperature,
            top_p=self.model_config.top_p,
            frequency_penalty=self.model_config.frequency_penalty,
            extra_body=self.model_config.extra_body,
            stream=True,
            stream_options={"include_usage": True}
        )

        raw_content = ""
        buffer = ""
        action_markers = ["finish(message=", "do(action="]
        in_action_phase = False

        for chunk in stream:
            if chunk.usage:
                if self._report_generator:
                    self._report_generator.token_usage(usage={
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens
                    }, source="Executor(GLM)")
                continue

            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                raw_content += content

                if in_action_phase:
                    continue

                buffer += content

                marker_found = False
                for marker in action_markers:
                    if marker in buffer:
                        thinking_part = buffer.split(marker, 1)[0]
                        if on_thinking_chunk:
                            on_thinking_chunk(thinking_part)
                        in_action_phase = True
                        marker_found = True
                        break

                if marker_found:
                    continue

                is_potential_marker = False
                for marker in action_markers:
                    for i in range(1, len(marker)):
                        if buffer.endswith(marker[:i]):
                            is_potential_marker = True
                            break
                    if is_potential_marker:
                        break

                if not is_potential_marker:
                    if on_thinking_chunk:
                        on_thinking_chunk(buffer)
                    buffer = ""

        thinking, action = self._parse_raw_response(raw_content)
        return thinking, action, raw_content

    def _parse_raw_response(self, content: str) -> tuple[str, str]:
        if "finish(message=" in content:
            parts = content.split("finish(message=", 1)
            thinking = parts[0].strip()
            action = "finish(message=" + parts[1]
            return thinking, action

        if "do(action=" in content:
            parts = content.split("do(action=", 1)
            thinking = parts[0].strip()
            action = "do(action=" + parts[1]
            return thinking, action

        if "<answer>" in content:
            parts = content.split("<answer>", 1)
            thinking = parts[0].replace("<think>", "").replace("</think>", "").strip()
            action = parts[1].replace("</answer>", "").strip()
            return thinking, action

        return "", content

    def _execute_step(
            self, user_prompt: str | None = None, is_first: bool = False
    ) -> StepResult:
        step_start_time = datetime.now()
        self._step_count += 1
        current_time = step_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        if self._report_generator:
            self._report_generator.execute_agent_step_start(step_count=self._step_count)

        screenshot = self.device.get_screenshot(save_to_report=True)
        self._screenshot.append(screenshot.screenshot_path)
        current_app = self.device.get_current_app()

        if is_first:
            system_prompt = self.agent_config.system_prompt
            if system_prompt is None:
                system_prompt = get_system_prompt(self.agent_config.lang, self.agent_config.mode)

            self._context.append(MessageBuilder.create_system_message(system_prompt))

            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"{user_prompt}\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)
            # 如果有新的用户消息（多轮对话场景），把它加入消息中
            if user_prompt:
                text_content = f"{user_prompt}\n\n** Screen Info **\n\n{screen_info}"
            else:
                # 继续执行当前任务，只需要屏幕信息
                text_content = f"** Screen Info **\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )

        try:
            msgs = get_messages(self.agent_config.lang)
            if self.agent_config.verbose:
                logger.info("\n" + "=" * 50)
                logger.info(f"[{current_time}] 💭 {msgs['thinking']}:")
                logger.info("-" * 50)

            callback = self._thinking_callback
            if callback is None and self.agent_config.verbose:
                def print_chunk(chunk: str) -> None:
                    print(chunk, end="", flush=True)

                callback = print_chunk

            llm_start_time = datetime.now()
            thinking, action_str, raw_content = self._stream_request(
                self._context, on_thinking_chunk=callback
            )
            llm_end_time = datetime.now()
            llm_duration = (llm_end_time - llm_start_time).total_seconds()
            llm_duration_str = f"{llm_duration:.2f}s"

            current_time = llm_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            logger.info(f"[{current_time}] Thinking (Duration: {llm_duration_str}): {thinking}")
            if callback is None and self.agent_config.verbose:
                print()

        except Exception as e:
            logger.exception(e)
            return StepResult(
                success=False,
                finished=True,
                action=None,
                thinking="",
                message=f"Model error: {e}",
            )

        try:
            action = self.parser.parse(action_str, screenshot.width, screenshot.height)
        except ValueError as e:
            if self.agent_config.verbose:
                logger.warning(f"Failed to parse action: {e}, treating as finish")
            action = {"_metadata": "finish", "message": action_str}

        time_calculate = TimeCalculate(llm_start_time, llm_end_time)
        if self._report_generator:
            self._report_generator.execute_agent_do_start(
                time_calculate=time_calculate, thinking=thinking,
                screenshot=screenshot, action=action,
                step_count=self._step_count
            )

        if self.agent_config.verbose:
            logger.info("-" * 50)
            logger.info(f"[{current_time}] 🎯 {msgs['action']}:")
            logger.info(json.dumps(action, ensure_ascii=False, indent=2))
            logger.info("=" * 50 + "\n")

        self._context[-1] = MessageBuilder.remove_images_from_message(self._context[-1])

        action_start_time = datetime.now()
        try:
            result = self.action_handler.execute(action)
        except Exception as e:
            logger.exception(e)
            result = ActionResult(success=False, should_finish=True, message=str(e))

        action_end_time = datetime.now()
        action_time_calculate = TimeCalculate(action_start_time, action_end_time)

        if self._report_generator:
            post_screenshot = self.device.get_screenshot(save_to_report=True)

            self._report_generator.execute_agent_do_end(
                time_calculate=action_time_calculate, screenshot=post_screenshot,
                result=result, step_count=self._step_count
            )

            self._report_generator.execute_agent_step_end()

        self._context.append(
            MessageBuilder.create_assistant_message(
                f"</think>{thinking}</think><answer>{action_str}</answer>"
            )
        )

        finished = action.get("_metadata") == "finish" or result.should_finish

        if finished and self.agent_config.verbose:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            msgs = get_messages(self.agent_config.lang)
            logger.info("\n" + "🎉 " + "=" * 48)
            logger.info(
                f"[{current_time}] ✅ {msgs['task_completed']}: {result.message or action.get('message', msgs['done'])}"
            )
            logger.info("=" * 50 + "\n")

        return StepResult(
            success=result.success,
            finished=finished,
            action=action,
            thinking=thinking,
            message=result.message or action.get("message"),
        )

    @property
    def context(self) -> list[dict[str, Any]]:
        return self._context.copy()

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def screenshot(self) -> list[Any]:
        return self._screenshot.copy()

    @property
    def is_running(self) -> bool:
        return self._is_running
