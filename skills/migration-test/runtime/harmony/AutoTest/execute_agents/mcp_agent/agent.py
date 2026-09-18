"""
MCP Agent - refactored to use general agent architecture with MCP tool support.
Uses OpenAI native client with function tools for MCP execution.
"""
import json
import asyncio
from typing import Any, Callable
from datetime import datetime

from openai import OpenAI

from ...config import AgentConfig, ModelConfig, StepResult
from ...devices.device_protocol import DeviceProtocol
from ...logger import logger
from ...reporter.reporter_types import TimeCalculate
from ...utils.utils import normalize_coord

from ..message_builder import MessageBuilder
from ..agents_factory import AgentFactory
from ..base_agent import BaseAgent
from .execute_mcp_tools import EXECUTE_TOOL_REGISTRY
from .prompts import MCP_AGENT_SYSTEM_PROMPT
from .prompts2 import MCP_AGENT_SYSTEM_PROMPT_V2
from ...utils.utils import retry_on_exception


@AgentFactory.register("mcp_agent")
class MCPAgent(BaseAgent):
    """
    MCP Agent - refactored to use general agent architecture.
    Supports MCP tool execution with coordinate conversion and reporting.
    """

    def __init__(
            self,
            model_config: ModelConfig,
            agent_config: AgentConfig,
            device: DeviceProtocol,
            confirmation_callback: Callable[[str], bool] | None = None,
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

        self._context: list[dict[str, Any]] = []
        self._screenshot: list[str] = []
        self._step_count = 0
        self._is_running = False
        self._current_screenshot = None
        self._history = []
        # Build tools for function calling
        self._tools = self._build_tools()

    def _build_tools(self) -> list[dict[str, Any]]:
        """Build tool definitions for OpenAI function calling"""
        tools = []
        for name, func in EXECUTE_TOOL_REGISTRY.items():
            # Manually convert FunctionTool to OpenAI tool format
            # FunctionTool from agents package doesn't have to_openai_tool() method
            params_schema = func.params_json_schema.copy()

            if "properties" in params_schema:
                params_schema["properties"]["log"] = {
                    "type": "string",
                    "description": "模型输入对应的描述"
                }

                if "required" in params_schema:
                    params_schema["required"] = list(params_schema["required"]) + ["log"]
                else:
                    params_schema["required"] = ["log"]

            tool_def = {
                "type": "function",
                "function": {
                    "name": func.name,
                    "description": func.description,
                    "strict": True,
                    "parameters": params_schema
                }
            }
            tools.append(tool_def)
        return tools

    def _execute_tool(self, name: str, arguments: str) -> str:
        """Execute a tool by name with JSON arguments"""
        try:
            args = json.loads(arguments)

            # 获取屏幕尺寸用于坐标转换
            screen_width = self._current_screenshot.width
            screen_height = self._current_screenshot.height

            # 坐标转换：将相对坐标转换为绝对坐标
            if name in ["tap", "double_tap", "long_press"]:
                if "x" in args and "y" in args:
                    x = normalize_coord(args["x"])
                    y = normalize_coord(args["y"])
                    args["x"] = int(float(x) * screen_width)
                    args["y"] = int(float(y) * screen_height)

            elif name in ["swipe", "drag"]:
                if all(k in args for k in ["start_x", "start_y", "end_x", "end_y"]):
                    start_x = normalize_coord(args["start_x"])
                    start_y = normalize_coord(args["start_y"])
                    end_x = normalize_coord(args["end_x"])
                    end_y = normalize_coord(args["end_y"])
                    args["start_x"] = int(float(start_x) * screen_width)
                    args["start_y"] = int(float(start_y) * screen_height)
                    args["end_x"] = int(float(end_x) * screen_width)
                    args["end_y"] = int(float(end_y) * screen_height)

            elif name in ["pinch_in", "pinch_out"]:
                if all(k in args for k in ["left", "top", "right", "bottom"]):
                    left = normalize_coord(args["left"])
                    top = normalize_coord(args["top"])
                    right = normalize_coord(args["right"])
                    bottom = normalize_coord(args["bottom"])
                    args["left"] = int(float(left) * screen_width)
                    args["top"] = int(float(top) * screen_height)
                    args["right"] = int(float(right) * screen_width)
                    args["bottom"] = int(float(bottom) * screen_height)

        except json.JSONDecodeError:
            logger.warning(f"解析工具参数失败：{arguments}")
            return json.dumps({"error": "Invalid JSON arguments"})
        except Exception as e:
            logger.warning(f"坐标转换失败：{e}")
            # 继续使用原始 arguments，不转换坐标
            try:
                args = json.loads(arguments)
            except:
                return json.dumps({"error": "Invalid JSON arguments"})

        log_param = args.pop("log", None)

        # Get the FunctionTool from registry and execute it
        if name not in EXECUTE_TOOL_REGISTRY:
            return json.dumps({"error": f"Tool '{name}' not found"})

        func_tool = EXECUTE_TOOL_REGISTRY[name]
        try:
            # FunctionTool uses on_invoke_tool which takes ToolContext and JSON args string
            from agents.tool import ToolContext
            from agents.usage import Usage

            # Create a minimal ToolContext
            # ToolContext requires: context, tool_name, tool_call_id, tool_arguments
            ctx = ToolContext(
                context={},  # Empty context dict
                usage=Usage(),
                tool_name=name,
                tool_call_id=f"call_{name}",
                tool_arguments=json.dumps(args)
            )

            # on_invoke_tool takes context and JSON string arguments
            result = asyncio.run(func_tool.on_invoke_tool(ctx, json.dumps(args)))
            return result
        except Exception as e:
            logger.exception(f"工具执行失败 {name}: {e}")
            return json.dumps({"error": str(e)})

    def run(self, task: str) -> str:
        self._context = []
        self._step_count = 0
        self._is_running = True

        try:
            # First step with user task
            result = self._execute_step(task, is_first=True)

            if result.finished:
                return result.message or "Task completed"

            # Continue steps until max_steps or finished
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
        self._current_screenshot = None
        self._history = []

    @retry_on_exception(max_retries=2)
    def _stream_request(
            self,
            messages: list[dict[str, Any]],
            on_thinking_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, str, str]:
        """Stream LLM request with tool support"""
        stream = self.openai_client.chat.completions.create(
            messages=messages,
            model=self.model_config.model_name,
            max_tokens=self.model_config.max_tokens,
            temperature=self.model_config.temperature,
            top_p=self.model_config.top_p,
            frequency_penalty=self.model_config.frequency_penalty,
            extra_body=self.model_config.extra_body,
            tools=self._tools if self._tools else None,
            stream=True,
            stream_options={"include_usage": True}
        )

        raw_content = ""
        thinking_buffer = ""
        # Use dict to accumulate tool calls by index, since streaming splits them
        tool_calls_by_index: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if chunk.usage:
                if self._report_generator:
                    self._report_generator.token_usage(usage={
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens
                    }, source="Executor(MCP)")
                continue

            if len(chunk.choices) == 0:
                continue

            delta = chunk.choices[0].delta

            # Handle reasoning content
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                thinking_buffer += delta.reasoning_content
                if on_thinking_chunk:
                    on_thinking_chunk(delta.reasoning_content)

            # Accumulate content
            if delta.content is not None:
                content = delta.content
                raw_content += content
                if not thinking_buffer and on_thinking_chunk:
                    on_thinking_chunk(content)

            # Accumulate tool calls by index
            # In streaming, each tool_call comes in chunks with the same index
            # We need to merge name and arguments fragments
            if hasattr(delta, 'tool_calls') and delta.tool_calls:
                for tc in delta.tool_calls:
                    index = tc.index if hasattr(tc, 'index') else 0

                    if index not in tool_calls_by_index:
                        tool_calls_by_index[index] = {
                            'id': '',
                            'type': 'function',
                            'function': {
                                'name': '',
                                'arguments': ''
                            }
                        }

                    # Accumulate id
                    if hasattr(tc, 'id') and tc.id:
                        tool_calls_by_index[index]['id'] = tc.id

                    # Accumulate function name and arguments
                    if hasattr(tc, 'function') and tc.function:
                        if hasattr(tc.function, 'name') and tc.function.name:
                            tool_calls_by_index[index]['function']['name'] += tc.function.name
                        if hasattr(tc.function, 'arguments') and tc.function.arguments:
                            tool_calls_by_index[index]['function']['arguments'] += tc.function.arguments

        # Convert to list for later processing
        tool_calls_list = list(tool_calls_by_index.values())

        # Store tool calls for later execution
        self._pending_tool_calls = tool_calls_list if tool_calls_list else None

        return thinking_buffer, raw_content, raw_content

    @retry_on_exception(max_retries=2)
    def _call_llm_and_build_action(self) -> tuple[datetime, datetime, str, str, str, dict]:
        """Call LLM and build action dict with retry support"""
        callback = self._thinking_callback
        if callback is None and self.agent_config.verbose:
            def print_chunk(chunk: str) -> None:
                print(chunk, end="", flush=True)

            callback = print_chunk

        llm_start_time = datetime.now()
        self._pending_tool_calls = None
        thinking, content, raw_content = self._stream_request(
            self._context, on_thinking_chunk=callback
        )
        llm_end_time = datetime.now()
        llm_duration = (llm_end_time - llm_start_time).total_seconds()
        llm_duration_str = f"{llm_duration:.2f}s"

        current_time = llm_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(f"[{current_time}] Thinking (Duration: {llm_duration_str}): {thinking}")

        # Build action dict for report (similar to general agent's parser output)
        # Format expected by report template (GLM_ACTION event):
        # {"action": "Tap", "element": [x_px, y_px]} (absolute coordinates in pixels)
        action = {"_metadata": "do", "action": "Unknown"}

        if self._pending_tool_calls:
            # Use the first tool call as the primary action for report visualization
            tc = self._pending_tool_calls[0]
            # tc is now a dict like: {'id': ..., 'function': {'name': ..., 'arguments': ...}}
            tool_name = tc.get('function', {}).get('name', 'unknown')
            tool_args = tc.get('function', {}).get('arguments', '{}')

            args_dict = json.loads(tool_args)

            # 提取并保存 log 参数
            log_param = args_dict.pop('log', None)
            if log_param:
                action["log"] = log_param

            # Get screen dimensions for coordinate conversion
            screen_width = self._current_screenshot.width
            screen_height = self._current_screenshot.height

            # Map MCP tool names to general agent action names
            action_map = {
                "tap": "Tap",
                "double_tap": "Double Tap",
                "long_press": "Long Press",
                "swipe": "Swipe",
                "drag": "Drag",
                "pinch_in": "Pinch In",
                "pinch_out": "Pinch Out",
                "type_text": "Type",
                "clear_text": "Clear Text",
                "back": "Back",
                "home": "Home",
                "launch_app": "Launch",
            }
            action["action"] = action_map.get(tool_name, tool_name.title())

            # Map parameters to general agent format (convert to absolute coordinates)
            if tool_name in ["tap", "double_tap", "long_press"]:
                # element: [x_px, y_px]
                if "x" in args_dict and "y" in args_dict:
                    x = normalize_coord(args_dict["x"])
                    y = normalize_coord(args_dict["y"])
                    action["element"] = [int(x * screen_width), int(y * screen_height)]

            elif tool_name in ["swipe", "drag"]:
                # start: [x1_px, y1_px], end: [x2_px, y2_px]
                if all(k in args_dict for k in ["start_x", "start_y", "end_x", "end_y"]):
                    start_x = normalize_coord(args_dict["start_x"])
                    start_y = normalize_coord(args_dict["start_y"])
                    end_x = normalize_coord(args_dict["end_x"])
                    end_y = normalize_coord(args_dict["end_y"])
                    action["start"] = [int(start_x * screen_width), int(start_y * screen_height)]
                    action["end"] = [int(end_x * screen_width), int(end_y * screen_height)]
                # Also add press_time and drag_time for drag
                if tool_name == "drag":
                    action["press_time"] = args_dict.get("press_time", 1.5)
                    action["drag_time"] = args_dict.get("drag_time", 1)

            elif tool_name in ["pinch_in", "pinch_out"]:
                # rect: [left_px, top_px, right_px, bottom_px]
                if all(k in args_dict for k in ["left", "top", "right", "bottom"]):
                    left = normalize_coord(args_dict["left"])
                    top = normalize_coord(args_dict["top"])
                    right = normalize_coord(args_dict["right"])
                    bottom = normalize_coord(args_dict["bottom"])
                    action["rect"] = [
                        int(left * screen_width), int(top * screen_height),
                        int(right * screen_width), int(bottom * screen_height)
                    ]
                action["scale"] = args_dict.get("scale", 0.4 if tool_name == "pinch_in" else 1.6)
                action["direction"] = args_dict.get("direction", "diagonal")

            elif tool_name == "type_text":
                action["text"] = args_dict.get("text", "")

            elif tool_name == "launch_app":
                action["app"] = args_dict.get("app_name", "")

        return llm_start_time, llm_end_time, thinking, content, raw_content, action

    def _execute_step(self, user_prompt: str | None = None, is_first: bool = False) -> StepResult:
        step_start_time = datetime.now()
        self._step_count += 1
        current_time = step_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        if self._report_generator:
            self._report_generator.execute_agent_step_start(step_count=self._step_count)

        # Get screenshot and store for coordinate conversion
        self._current_screenshot = self.device.get_screenshot(save_to_report=True)
        self._screenshot.append(self._current_screenshot.screenshot_path)
        current_app = self.device.get_current_app()
        screenshot_path = self._current_screenshot.screenshot_path

        if is_first:
            if self.agent_config.max_steps > 3:
                default_prompt = MCP_AGENT_SYSTEM_PROMPT
            else:
                default_prompt = MCP_AGENT_SYSTEM_PROMPT_V2

            system_prompt = self.agent_config.system_prompt or default_prompt
            self._context.append(MessageBuilder.create_system_message(system_prompt))

            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"{user_prompt}\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=self._current_screenshot.base64_data
                )
            )
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"** Screen Info **\n\n{screen_info}"
            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=self._current_screenshot.base64_data
                )
            )

        # LLM call
        try:
            llm_start_time, llm_end_time, thinking, content, raw_content, action = self._call_llm_and_build_action()
        except Exception as e:
            logger.exception(e)
            return StepResult(
                success=False,
                finished=True,
                action=None,
                thinking="",
                message=f"Model error: {e}",
            )

        # Determine log and action metadata
        if action.get("log", ""):
            # 有 log 参数，直接使用
            log = action.get("log")
        elif self._pending_tool_calls:
            # 有工具调用但无 log 参数，保留 action 并生成默认 log
            log = user_prompt
            action["log"] = log
        else:
            # 无工具调用，标记为 finish
            action = {"_metadata": "finish", "message": raw_content}
            log = raw_content

        self._history.append(f"{len(self._history) + 1}、{log}")

        time_calculate = TimeCalculate(llm_start_time, llm_end_time)
        if self._report_generator:
            self._report_generator.execute_agent_do_start(
                time_calculate=time_calculate, thinking=thinking,
                screenshot=self._current_screenshot, action=action,
                step_count=self._step_count
            )

        # Manage history images: keep only the last N images
        self._manage_history_images(getattr(self.agent_config, "max_history_image", 2))

        # Add assistant message to context
        self._context.append(
            MessageBuilder.create_assistant_message(raw_content)
        )

        # Handle tool calls if any
        action_start_time = datetime.now()
        tool_results = []
        action_result = {"success": True, "message": "", "should_finish": False}

        if self._pending_tool_calls:
            for tc in self._pending_tool_calls:
                # tc is a dict like: {'id': ..., 'function': {'name': ..., 'arguments': ...}}
                tool_call_id = tc.get('id', f"call_{len(self._context)}")
                tool_name = tc.get('function', {}).get('name', 'unknown')
                tool_args = tc.get('function', {}).get('arguments', '{}')

                logger.info(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] Tool Call: {tool_name} args: {tool_args}")

                # Add tool call message to context
                self._context.append(
                    MessageBuilder.create_tool_call_message(tool_call_id, tool_name, tool_args)
                )

                # Execute tool
                tool_result = self._execute_tool(tool_name, tool_args)
                tool_results.append({"name": tool_name, "result": tool_result})
                action_result["message"] = tool_result

                # Add tool result message to context
                self._context.append(
                    MessageBuilder.create_tool_result_message(tool_call_id, tool_name, tool_result)
                )

        action_end_time = datetime.now()
        action_time_calculate = TimeCalculate(action_start_time, action_end_time)

        if self._report_generator:
            post_screenshot = self.device.get_screenshot(save_to_report=True)

            self._report_generator.execute_agent_do_end(
                time_calculate=action_time_calculate, screenshot=post_screenshot,
                result=type('obj', (object,), action_result), step_count=self._step_count
            )

            self._report_generator.execute_agent_step_end()

        # Check if finished
        # If no tool calls, the model is responding with text only, so we should finish
        if not self._pending_tool_calls:
            # No tool calls means the model is done and responding with text
            finished = True
            action_result["message"] = raw_content
        else:
            # Has tool calls, check if model indicated completion in content
            finished = "finish" in content.lower() or action_result.get("should_finish", False)

        return StepResult(
            success=action_result.get("success", True),
            finished=finished,
            action=action,
            thinking=thinking,
            message=action_result.get("message", ""),
        )

    def _manage_history_images(self, keep_count: int):
        """Keep only the last `keep_count` images in the context."""
        if keep_count < 0:
            return

        image_msg_indices = []
        for i, msg in enumerate(self._context):
            if msg["role"] == "user" and isinstance(msg["content"], list):
                has_image = any(item.get("type") == "image_url" for item in msg["content"])
                if has_image:
                    image_msg_indices.append(i)

        if len(image_msg_indices) > keep_count:
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
        return self._history.copy()
