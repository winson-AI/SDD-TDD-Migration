from dataclasses import dataclass
from typing import Any, Callable
from datetime import datetime

from openai import OpenAI

from ...actions import ActionHandler, ActionResult
from ...config import AgentConfig, ModelConfig, StepResult
from ...devices.device_protocol import DeviceProtocol
from ...logger import logger
from ...reporter.reporter_types import TimeCalculate
from ...reporter.reporter_abs import ReporterAbs

from ..message_builder import MessageBuilder
from .parser import GeneralParser
from .prompts_zh import SYSTEM_PROMPT as SYSTEM_PROMPT_ZH
from .prompts_zh2 import SYSTEM_PROMPT as SYSTEM_PROMPT_ZH2
from ..agents_factory import AgentFactory
from ..base_agent import BaseAgent
from ...utils.utils import retry_on_exception


@dataclass
class MockDelta:
    content: str | None


@dataclass
class MockChoice:
    delta: MockDelta


@dataclass
class MockChunk:
    choices: list[MockChoice]


@AgentFactory.register("general")
class GeneralAgent(BaseAgent):
    def __init__(
            self,
            model_config: ModelConfig,
            agent_config: AgentConfig,
            device: DeviceProtocol,
            confirmation_callback: Callable[[str], bool] | None = None,
            thinking_callback: Callable[[str], None] | None = None,
            report_generator: ReporterAbs = None,
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
        self.parser = GeneralParser()

        self.action_handler = ActionHandler(
            device=self.device,
            confirmation_callback=confirmation_callback,
        )

        self._context: list[dict[str, Any]] = []
        self._screenshot: list[str] = []
        self._step_count = 0
        self._is_running = False
        self._history = []

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

    def reset(self) -> None:
        self._context = []
        self._screenshot = []
        self._step_count = 0
        self._is_running = False
        self._history = []

    @retry_on_exception(max_retries=2)
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
        thinking_buffer = ""

        for chunk in stream:
            if chunk.usage:
                if self._report_generator:
                    self._report_generator.token_usage(usage={
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens
                    }, source="Executor(General)")
                continue

            if len(chunk.choices) == 0:
                continue

            # Handle deepseek-reasoner thinking content
            if hasattr(chunk.choices[0], 'delta') and hasattr(chunk.choices[0].delta, 'reasoning_content'):
                reasoning = chunk.choices[0].delta.reasoning_content
                if reasoning:
                    thinking_buffer += reasoning
                    if on_thinking_chunk:
                        on_thinking_chunk(reasoning)

            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                raw_content += content
                # If we haven't received specific reasoning_content,
                # and we are inside <thought> tags (simple heuristic or always for non-reasoning models),
                # we might want to stream it.
                # BUT, based on the previous code, it was streaming ALL content as thinking.
                # To restore previous behavior for non-DeepSeek models while supporting DeepSeek:
                if not thinking_buffer and on_thinking_chunk:
                    # Only stream content as thinking if we haven't seen reasoning_content
                    # This is a bit heuristic. A better way is to check if the model is a reasoning model.
                    # For now, let's stream content if we aren't seeing reasoning_content updates.
                    on_thinking_chunk(content)

        return thinking_buffer, raw_content, raw_content

    def _chat_and_parse(self, screenshot):

        raw_content = ""
        action = {}
        thinking = ""
        llm_start_time = 0
        llm_end_time = 0

        for _ in range(2):
            callback = self._thinking_callback
            if callback is None and self.agent_config.verbose:
                def print_chunk(chunk: str) -> None:
                    print(chunk, end="", flush=True)

                callback = print_chunk

            llm_start_time = datetime.now()
            thinking, content, raw_content = self._stream_request(
                self._context, on_thinking_chunk=callback
            )
            llm_end_time = datetime.now()
            llm_duration = (llm_end_time - llm_start_time).total_seconds()
            llm_duration_str = f"{llm_duration:.2f}s"

            current_time = llm_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            logger.info(f"[{current_time}] Thinking (Duration: {llm_duration_str}): {thinking}")

            try:
                action = self.parser.parse(content, screenshot.width, screenshot.height)
            except ValueError as e:
                action = {"_metadata": "finish", "message": str(e)}

            if "Unsupported action" not in action.get("message", ""):
                break
            else:
                logger.warning("action parse error: {}. try again".format(action))
        return raw_content, action, thinking, llm_start_time, llm_end_time

    def _execute_step(self, user_prompt: str | None = None, is_first: bool = False) -> StepResult:
        self._step_count += 1

        if self._report_generator:
            self._report_generator.execute_agent_step_start(step_count=self._step_count)

        screenshot = self.device.get_screenshot(save_to_report=True)
        self._screenshot.append(screenshot.screenshot_path)
        current_app = self.device.get_current_app()

        if is_first:
            if self.agent_config.max_steps > 3:
                default_prompt = SYSTEM_PROMPT_ZH
            else:
                default_prompt = SYSTEM_PROMPT_ZH2
            system_prompt = self.agent_config.system_prompt or default_prompt
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
            text_content = f"** Screen Info **\n\n{screen_info}"
            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )
        try:
            raw_content, action, thinking, llm_start_time, llm_end_time = self._chat_and_parse(screenshot)
        except Exception as e:
            return StepResult(
                success=False,
                finished=True,
                action=None,
                thinking="",
                message=f"Model error: {e}",
            )
        log = action.get("log", "") or action.get("message", "")
        self._history.append(f"{len(self._history) + 1}、{log}")

        time_calculate = TimeCalculate(llm_start_time, llm_end_time)
        if self._report_generator:
            self._report_generator.execute_agent_do_start(time_calculate=time_calculate, thinking=thinking,
                                                          screenshot=screenshot, action=action,
                                                          step_count=self._step_count)

        # Manage history images: keep only the last N images
        self._manage_history_images(getattr(self.agent_config, "max_history_image", 2))

        self._context.append(
            MessageBuilder.create_assistant_message(raw_content)
        )

        action_start_time = datetime.now()
        try:
            result = self.action_handler.execute(action)
        except Exception as e:
            logger.exception(e)
            result = ActionResult(success=False, should_finish=True, message=str(e))

        action_end_time = datetime.now()
        action_time_calculate = TimeCalculate(action_start_time, action_end_time)

        if self._report_generator:
            screenshot = self.device.get_screenshot(save_to_report=True)

            self._report_generator.execute_agent_do_end(time_calculate=action_time_calculate, screenshot=screenshot,
                                                        result=result, step_count=self._step_count)

            self._report_generator.execute_agent_step_end()

        finished = action.get("_metadata") == "finish" or result.should_finish

        return StepResult(
            success=result.success,
            finished=finished,
            action=action,
            thinking=thinking,
            message=result.message or action.get("message"),
        )

    def _manage_history_images(self, keep_count: int):
        """
        Keep only the last `keep_count` images in the context.
        Remove images from older messages to save tokens.
        """
        if keep_count < 0:
            return

        image_msg_indices = []
        for i, msg in enumerate(self._context):
            if msg["role"] == "user" and isinstance(msg["content"], list):
                # Check if message has image
                has_image = any(item.get("type") == "image_url" for item in msg["content"])
                if has_image:
                    image_msg_indices.append(i)

        # If we have more images than we want to keep
        if len(image_msg_indices) > keep_count:
            # Indices to prune (all except the last `keep_count`)
            # If keep_count is 0, prune all
            if keep_count == 0:
                indices_to_prune = image_msg_indices
            else:
                indices_to_prune = image_msg_indices[:-keep_count]

            for idx in indices_to_prune:
                self._context[idx] = MessageBuilder.remove_images_from_message(self._context[idx])

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def screenshot(self) -> list[Any]:
        return self._screenshot.copy()

    @property
    def context(self) -> list[dict[str, Any]]:
        return self._context.copy()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def history(self) -> list[str]:
        return self._history
