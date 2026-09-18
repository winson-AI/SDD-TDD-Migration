"""HypiumMCPAgent - Agent using HypiumMCP tools."""
import json
import asyncio
from typing import Any, Callable
from datetime import datetime

from devicetest import driver
from openai import OpenAI

from ...config import AgentConfig, ModelConfig, StepResult
from ...devices.device_protocol import DeviceProtocol
from ...logger import logger
from ...reporter.reporter_types import TimeCalculate
from ...layered_agent_cli.agent_registry import agent_registry
from ..message_builder import MessageBuilder
from ..agents_factory import AgentFactory
from ..base_agent import BaseAgent
from .mcp_extension import MCPExtension
from .prompts import MCP_AGENT_SYSTEM_PROMPT, MCP_AGENT_SYSTEM_PROMPT_V2
from .custom_tools import get_custom_tools, get_custom_tool
from ...utils.utils import retry_on_exception, normalize_coord


@AgentFactory.register("hypium_mcp_agent")
class HypiumMCPAgent(BaseAgent):
    DISTANCE_THRESHOLD = 100
    XPATH_CACHE_TOOLS = {'click', 'double_click', 'long_click', 'drag', 'swipe', 'pinch_in', 'pinch_out'}
    # 搜索框/输入框场景关键字：命中此类场景时强制使用完整层级路径 xpath，
    # 避免记录到搜索历史/热搜/联想词等动态内容的 text-based xpath
    SEARCH_BOX_KEYWORDS = ("搜索框", "输入框", "搜索栏")

    """
    HypiumMCPAgent - Uses HypiumMCP tools for UI automation.

    This agent is based on the mcp_agent architecture but uses HypiumMCP
    instead of native HCDC tools. It provides:
    - Complete logging system
    - Report generation
    - Token usage statistics
    - Streaming response handling
    """

    def __init__(
            self,
            model_config: ModelConfig,
            agent_config: AgentConfig,
            device: DeviceProtocol,
            confirmation_callback: Callable[[str], bool] | None = None,
            thinking_callback: Callable[[str], None] | None = None,
            report_generator=None
    ):
        """
        Initialize HypiumMCPAgent.

        Args:
            model_config: Model configuration
            agent_config: Agent configuration
            device: Device protocol instance
            confirmation_callback: Optional callback for user confirmations
            thinking_callback: Optional callback for thinking content
            report_generator: Optional report generator
        """
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

        self._mcp_extension = MCPExtension(
            device=device,
            special_test=agent_config.special_test_enabled
        )

        self._context: list[dict[str, Any]] = []
        self._screenshot: list[str] = []
        self._step_count = 0
        self._is_running = False
        self._current_screenshot = None
        self._history = []

        self._tools = self._build_tools()

        self._current_layout_data = None
        self._last_action_log = None  # Track last action's log for repeat detection
        self._current_task = ""  # 当前任务文本，用于判定搜索框/输入框场景

    def _build_tools(self) -> list[dict[str, Any]]:
        """Build tool definitions from HypiumMCP and custom tools for OpenAI function calling."""
        tools = []

        for tool in self._mcp_extension.list_tools():
            params_schema = tool.input_schema.copy()

            if "properties" in params_schema:
                params_schema["properties"]["log"] = {
                    "type": "string",
                    "description": "模型输入对应的描述"
                }
                if tool.name in self.XPATH_CACHE_TOOLS:
                    params_schema["properties"]["target_text"] = {
                        "type": "string",
                        "description": "目标元素的可见文本;如果目标没有文本则填空字符串"
                    }

                if "required" in params_schema:
                    params_schema["required"] = list(params_schema["required"]) + ["log"]
                else:
                    params_schema["required"] = ["log"]
                if tool.name in self.XPATH_CACHE_TOOLS and "target_text" not in  params_schema["required"]:
                    params_schema["required"].append("target_text")

            tool_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "strict": True,
                    "description": tool.description,
                    "parameters": params_schema
                }
            }
            tools.append(tool_def)

        for tool in get_custom_tools():
            params_schema = tool["params_schema"].copy()
            params_schema["properties"]["log"] = {
                "type": "string",
                "description": "模型输入对应的描述"
            }
            if tool["name"] in self.XPATH_CACHE_TOOLS:
                params_schema["properties"]["target_text"] = {
                    "type": "string",
                    "description": "目标元素的可见文本;如果目标没有文本则填空字符串"
                }
            params_schema["required"] = list(params_schema["required"]) + ["log"]
            if tool["name"] in self.XPATH_CACHE_TOOLS and "target_text" not in params_schema["required"]:
                params_schema["required"].append("target_text")

            tool_def = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "strict": True,
                    "description": tool["description"],
                    "parameters": params_schema
                }
            }
            tools.append(tool_def)

        return tools

    def _execute_tool(self, name: str, arguments: str) -> str:
        """Execute a HypiumMCP tool or custom tool by name with JSON arguments."""
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            logger.warning(f"解析工具参数失败：{arguments}")
            return json.dumps({"error": "Invalid JSON arguments"})

        log = args.pop("log", None)
        target_text = args.pop("target_text", "")
        cache_args = dict(args)
        if target_text:
            cache_args["target_text"] = target_text
        if log:
            cache_args["log"] = log

        custom_tool = get_custom_tool(name)
        if custom_tool:
            try:
                result = custom_tool["func"](**args)
                self._save_click_info(name, cache_args)
                return json.dumps({
                    "output": result,
                    "success": True
                })
            except Exception as e:
                logger.exception(f"Custom tool execution failed {name}: {e}")
                return json.dumps({
                    "output": str(e),
                    "success": False
                })

        result = self._mcp_extension.call_tool(name, args)
        self._save_click_info(name, cache_args)
        return json.dumps({
            "output": result.output,
            "success": result.success
        })

    def _save_click_info(self, tool_name: str, args: dict):
        """Save click info and xpath to agent_registry for later use in recording."""
        # 定义需要 xpath 缓存的工具及其坐标参数
        single_point_tools = ['click', 'double_click', 'long_click']
        dual_point_tools = ['drag', 'swipe']
        rect_tools = ['pinch_in', 'pinch_out']
        
        # 定义不需要 xpath 但需要缓存参数的工具
        text_tools = ['input_text', 'clear_text']
        
        screen_width = 1216
        screen_height = 2688
        if self._current_screenshot:
            screen_width = self._current_screenshot.width
            screen_height = self._current_screenshot.height
        
        try:
            from ...memory.xpath_cache import LayoutToXPath
            
            if tool_name in single_point_tools:
                self._save_single_point_xpath(tool_name, args, screen_width, screen_height)
            elif tool_name in dual_point_tools:
                self._save_dual_point_xpath(tool_name, args, screen_width, screen_height)
            elif tool_name in rect_tools:
                self._save_rect_xpath(tool_name, args, screen_width, screen_height)
            elif tool_name in text_tools:
                self._save_text_cache(tool_name, args)
        except Exception as e:
            logger.warning(f"[HypiumMCPAgent] Failed to generate click cache: {e}")
    
    def _save_single_point_xpath(self, tool_name: str, args: dict, screen_width: int, screen_height: int):
        """为单点工具（click, double_click, long_click）保存 xpath"""
        # 新版 hypium_mcp SDK 入参为 pos: [x, y]；兼容旧版 x/y
        pos = args.get('pos')
        if pos is not None and len(pos) == 2:
            x, y = pos[0], pos[1]
        else:
            x = args.get('x')
            y = args.get('y')
        target_text = str(args.get('target_text', '') or '').strip()
        if x is None or y is None:
            return
            
        normalized_x = normalize_coord(x)
        normalized_y = normalize_coord(y)
        scaled_x = int(normalized_x * screen_width)
        scaled_y = int(normalized_y * screen_height)
        
        agent_registry.set_last_click_info(scaled_x, scaled_y, tool_name)
        logger.info(
            f"[HypiumMCPAgent] Saved click info: ({scaled_x}, {scaled_y}), "
            f"normalized=({normalized_x:.2f}, {normalized_y:.2f}), "
            f"screen={screen_width}x{screen_height}, action={tool_name}"
        )
        
        if not self._current_layout_data:
            return
            
        from ...memory.xpath_cache import LayoutToXPath
        layout = LayoutToXPath(self._current_layout_data)
        element = layout.find_element_at(scaled_x, scaled_y, target_text=target_text)

        if element:
            distance = element.distance_to_point(scaled_x, scaled_y)
            # 搜索框/输入框场景：命中元素通常是搜索历史/热搜/联想词等动态内容，
            # 其 text-based xpath（如 //Text[@text='xxx']）在回放时不可靠，
            # 此类场景强制使用完整层级路径 xpath（如 /orgRoot/root/.../Text）
            is_search_box_scenario = self._is_search_box_scenario()
            if is_search_box_scenario:
                xpath = layout.to_full_xpath(element)
                logger.info(
                    f"[HypiumMCPAgent] Search-box scenario detected, using full-path xpath: {xpath}"
                )
            else:
                xpath = layout.to_xpath(element)

            click_cache = {
                'action': tool_name,
                'xpath': xpath if xpath else None,
                'element_type': element.element_type,
                'element_text': element.text,
                'element_id': element.id,
                'element_bounds': element.bounds,
                'target_text': target_text,
                'log': self._desensitize_log(str(args.get('log', '') or '')),
                'click_x': scaled_x,
                'click_y': scaled_y,
                'distance': round(distance, 2),
                'use_xpath': distance <= self.DISTANCE_THRESHOLD and bool(xpath)
            }
            agent_registry.set_last_click_cache(click_cache)
            logger.info(
                f"[HypiumMCPAgent] Saved click_cache: action={tool_name}, "
                f"xpath={xpath}, distance={distance:.2f}px, use_xpath={distance <= self.DISTANCE_THRESHOLD and bool(xpath)}, "
                f"search_box_scenario={is_search_box_scenario}"
            )
        else:
            click_cache = {
                'action': tool_name,
                'xpath': None,
                'element_type': None,
                'element_text': None,
                'element_id': None,
                'element_bounds': None,
                'target_text': target_text,
                'log': self._desensitize_log(str(args.get('log', '') or '')),
                'click_x': scaled_x,
                'click_y': scaled_y,
                'distance': None,
                'use_xpath': False
            }
            agent_registry.set_last_click_cache(click_cache)
            logger.info(
                f"[HypiumMCPAgent] Saved click_cache WITHOUT element: action={tool_name}, "
                f"click=({scaled_x}, {scaled_y})"
            )

    def _is_search_box_scenario(self) -> bool:
        """判定当前是否为搜索框/输入框场景。

        基于当前任务文本（外层 execute 的 message）检测搜索框/输入框关键字。
        此类场景下点击命中的往往是搜索历史/热搜/联想词等动态内容，
        其 text-based xpath 不可靠，应使用完整层级路径 xpath。

        Returns:
            True 表示当前为搜索框/输入框场景
        """
        task = getattr(self, '_current_task', '') or ''
        return any(kw in task for kw in self.SEARCH_BOX_KEYWORDS)

    def _desensitize_log(self, log: str) -> str:
        """对搜索框/输入框场景的 log 进行脱敏。

        将成对引号（英文"/中文“”/英文'）包围的具体内容统一替换为"文字"，
        同时吃掉紧跟的"文字"字面量避免重复。
        非搜索框场景原样返回。

        与 tool_recorder._desensitize_search_box_message 保持一致。
        """
        if not log or not isinstance(log, str):
            return log
        if not self._is_search_box_scenario():
            return log
        import re
        # 与 tool_recorder 中的正则保持一致
        pattern = re.compile(r'(?:"([^"]+)"|“([^”]+)”|‘([^’]+)’)(?:文字)?')
        return pattern.sub('文字', log)

    def _save_dual_point_xpath(self, tool_name: str, args: dict, screen_width: int, screen_height: int):
        """为双点工具（drag, swipe）保存起点和终点的 xpath"""
        # 新版 hypium_mcp SDK 入参为 start: [x, y] / end: [x, y]；兼容旧版 start_x/start_y/end_x/end_y
        start = args.get('start')
        end = args.get('end')
        if start is not None and len(start) == 2:
            start_x, start_y = start[0], start[1]
        else:
            start_x = args.get('start_x')
            start_y = args.get('start_y')
        if end is not None and len(end) == 2:
            end_x, end_y = end[0], end[1]
        else:
            end_x = args.get('end_x')
            end_y = args.get('end_y')
        target_text = str(args.get('target_text', '') or '').strip()

        if None in [start_x, start_y, end_x, end_y]:
            return
        
        # 归一化和缩放坐标
        norm_start_x = normalize_coord(start_x)
        norm_start_y = normalize_coord(start_y)
        norm_end_x = normalize_coord(end_x)
        norm_end_y = normalize_coord(end_y)
        
        scaled_start_x = int(norm_start_x * screen_width)
        scaled_start_y = int(norm_start_y * screen_height)
        scaled_end_x = int(norm_end_x * screen_width)
        scaled_end_y = int(norm_end_y * screen_height)
        
        agent_registry.set_last_click_info(scaled_start_x, scaled_start_y, tool_name)
        logger.info(
            f"[HypiumMCPAgent] Saved dual-point info: start=({scaled_start_x}, {scaled_start_y}), "
            f"end=({scaled_end_x}, {scaled_end_y}), action={tool_name}"
        )
        
        if not self._current_layout_data:
            return
            
        from ...memory.xpath_cache import LayoutToXPath
        layout = LayoutToXPath(self._current_layout_data)
        
        # 查找起点和终点元素
        start_element = layout.find_element_at(scaled_start_x, scaled_start_y, target_text=target_text)
        end_element = layout.find_element_at(scaled_end_x, scaled_end_y, target_text=target_text)
        
        start_xpath = layout.to_xpath(start_element) if start_element else None
        end_xpath = layout.to_xpath(end_element) if end_element else None
        
        start_distance = start_element.distance_to_point(scaled_start_x, scaled_start_y) if start_element else None
        end_distance = end_element.distance_to_point(scaled_end_x, scaled_end_y) if end_element else None
        
        click_cache = {
            'action': tool_name,
            'xpath': start_xpath,
            'xpath_end': end_xpath,
            'start_element_type': start_element.element_type if start_element else None,
            'start_element_text': start_element.text if start_element else None,
            'end_element_type': end_element.element_type if end_element else None,
            'end_element_text': end_element.text if end_element else None,
            'start_bounds': start_element.bounds if start_element else None,
            'end_bounds': end_element.bounds if end_element else None,
            'target_text': target_text,
            'log': self._desensitize_log(str(args.get('log', '') or '')),
            'click_x': scaled_start_x,
            'click_y': scaled_start_y,
            'click_x_end': scaled_end_x,
            'click_y_end': scaled_end_y,
            'start_distance': round(start_distance, 2) if start_distance else None,
            'end_distance': round(end_distance, 2) if end_distance else None,
            'use_xpath': (start_distance <= self.DISTANCE_THRESHOLD and bool(start_xpath)) or (end_distance <= self.DISTANCE_THRESHOLD and bool(end_xpath))
        }
        agent_registry.set_last_click_cache(click_cache)
        logger.info(
            f"[HypiumMCPAgent] Saved dual-point click_cache: action={tool_name}, "
            f"start_xpath={start_xpath}, end_xpath={end_xpath}, "
            f"start_distance={start_distance:.2f}px, end_distance={end_distance:.2f}px"
        )
    
    def _save_rect_xpath(self, tool_name: str, args: dict, screen_width: int, screen_height: int):
        """为矩形工具（pinch_in, pinch_out）保存中心点的 xpath"""
        left = args.get('left')
        top = args.get('top')
        right = args.get('right')
        bottom = args.get('bottom')
        target_text = str(args.get('target_text', '') or '').strip()

        if None in [left, top, right, bottom]:
            return
        
        # 归一化和缩放坐标
        norm_left = normalize_coord(left)
        norm_top = normalize_coord(top)
        norm_right = normalize_coord(right)
        norm_bottom = normalize_coord(bottom)
        
        scaled_left = int(norm_left * screen_width)
        scaled_top = int(norm_top * screen_height)
        scaled_right = int(norm_right * screen_width)
        scaled_bottom = int(norm_bottom * screen_height)
        
        # 计算矩形中心点
        center_x = (scaled_left + scaled_right) // 2
        center_y = (scaled_top + scaled_bottom) // 2
        
        agent_registry.set_last_click_info(center_x, center_y, tool_name)
        logger.info(
            f"[HypiumMCPAgent] Saved rect info: rect=[{scaled_left},{scaled_top}][{scaled_right},{scaled_bottom}], "
            f"center=({center_x}, {center_y}), action={tool_name}"
        )
        
        if not self._current_layout_data:
            return
            
        from ...memory.xpath_cache import LayoutToXPath
        layout = LayoutToXPath(self._current_layout_data)
        
        # 查找中心点元素
        center_element = layout.find_element_at(center_x, center_y, target_text=target_text)
        center_xpath = layout.to_xpath(center_element) if center_element else None
        center_distance = center_element.distance_to_point(center_x, center_y) if center_element else None
        
        click_cache = {
            'action': tool_name,
            'xpath': center_xpath,
            'rect': {
                'left': scaled_left,
                'top': scaled_top,
                'right': scaled_right,
                'bottom': scaled_bottom
            },
            'element_type': center_element.element_type if center_element else None,
            'element_text': center_element.text if center_element else None,
            'element_bounds': center_element.bounds if center_element else None,
            'target_text': target_text,
            'log': self._desensitize_log(str(args.get('log', '') or '')),
            'click_x': center_x,
            'click_y': center_y,
            'distance': round(center_distance, 2) if center_distance else None,
            'use_xpath': center_distance <= self.DISTANCE_THRESHOLD and bool(center_xpath) if center_distance else False
        }
        agent_registry.set_last_click_cache(click_cache)
        logger.info(
            f"[HypiumMCPAgent] Saved rect click_cache: action={tool_name}, "
            f"center_xpath={center_xpath}, center_distance={center_distance:.2f}px"
        )
    
    def _save_text_cache(self, tool_name: str, args: dict):
        """为文本操作工具（input_text, clear_text）保存缓存"""
        
        if tool_name == 'input_text':
            text = args.get('text', '')
            click_cache = {
                'action': 'input_text',
                'text': text,
                'log': self._desensitize_log(str(args.get('log', '') or '')),
                'use_xpath': False
            }
            agent_registry.set_last_click_cache(click_cache)
            logger.info(f"[HypiumMCPAgent] Saved input_text cache: text={text[:30]}...")
        
        elif tool_name == 'clear_text':
            click_cache = {
                'action': 'clear_text',
                'log': self._desensitize_log(str(args.get('log', '') or '')),
                'use_xpath': False
            }
            agent_registry.set_last_click_cache(click_cache)
            logger.info(f"[HypiumMCPAgent] Saved clear_text cache")

    def run(self, task: str) -> str:
        """Run the agent to complete the given task."""
        self._context = []
        self._step_count = 0
        self._is_running = True
        # 记录当前任务文本，供 _save_click_xpath 判定搜索框/输入框场景
        self._current_task = task or ""

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
        """Reset the agent internal state."""
        self._context = []
        self._screenshot = []
        self._step_count = 0
        self._is_running = False
        self._current_screenshot = None
        self._history = []
        self._last_action_log = None
        self._current_task = ""

    @retry_on_exception(max_retries=2)
    def _stream_request(
            self,
            messages: list[dict[str, Any]],
            on_thinking_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, str, str]:
        """Stream LLM request with tool support."""
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
        tool_calls_by_index: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if chunk.usage:
                if self._report_generator:
                    self._report_generator.token_usage(usage={
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens
                    }, source="HypiumMCPAgent")
                continue

            if len(chunk.choices) == 0:
                continue

            delta = chunk.choices[0].delta

            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                thinking_buffer += delta.reasoning_content
                if on_thinking_chunk:
                    on_thinking_chunk(delta.reasoning_content)

            if delta.content is not None:
                content = delta.content
                raw_content += content
                if not thinking_buffer and on_thinking_chunk:
                    on_thinking_chunk(content)

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

                    if hasattr(tc, 'id') and tc.id:
                        tool_calls_by_index[index]['id'] = tc.id

                    if hasattr(tc, 'function') and tc.function:
                        if hasattr(tc.function, 'name') and tc.function.name:
                            tool_calls_by_index[index]['function']['name'] += tc.function.name
                        if hasattr(tc.function, 'arguments') and tc.function.arguments:
                            tool_calls_by_index[index]['function']['arguments'] += tc.function.arguments

        tool_calls_list = list(tool_calls_by_index.values())
        self._pending_tool_calls = tool_calls_list if tool_calls_list else None

        return thinking_buffer, raw_content, raw_content

    @retry_on_exception(max_retries=2)
    def _call_llm_and_build_action(self) -> tuple[datetime, datetime, str, str, str, dict]:
        """Call LLM and build action dict with retry support."""
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

        logger.info(self._pending_tool_calls)
        logger.info(f"Thinking: {thinking}")
        logger.info(f"content: {content}")
        logger.info(f"raw_content: {raw_content}")

        llm_end_time = datetime.now()
        llm_duration = (llm_end_time - llm_start_time).total_seconds()
        llm_duration_str = f"{llm_duration:.2f}s"

        current_time = llm_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(f"[{current_time}] Thinking (Duration: {llm_duration_str}): {thinking}")

        action = {"_metadata": "do", "action": "Unknown"}

        if self._pending_tool_calls:
            tc = self._pending_tool_calls[0]
            tool_name = tc.get('function', {}).get('name', 'unknown')
            tool_args = tc.get('function', {}).get('arguments', '{}')

            logger.info(f"[{current_time}] Thinking ({tool_name}): {tool_args}")

            args_dict = json.loads(tool_args)

            log_param = args_dict.pop('log', None)
            if log_param:
                action["log"] = log_param

            action_map = {
                "click": "Tap",
                "double_click": "Double Tap",
                "long_click": "Long Press",
                "drag": "Drag",
                "swipe": "Swipe",
                "pinch_in": "Pinch In",
                "pinch_out": "Pinch Out",
            }
            action["action"] = action_map.get(tool_name, tool_name.title())

            if self._current_screenshot:
                screen_width = self._current_screenshot.width
                screen_height = self._current_screenshot.height

                if tool_name in ["click", "double_click", "long_click"]:
                    # 新版 hypium_mcp SDK 入参为 pos: [x, y]；兼容旧版 x/y
                    pos = args_dict.get("pos")
                    if pos is not None and len(pos) == 2:
                        x = normalize_coord(pos[0])
                        y = normalize_coord(pos[1])
                    elif "x" in args_dict and "y" in args_dict:
                        x = normalize_coord(args_dict["x"])
                        y = normalize_coord(args_dict["y"])
                    else:
                        x = y = None
                    if x is not None and y is not None:
                        action["element"] = [
                            int(float(x) * screen_width),
                            int(float(y) * screen_height)
                        ]

                elif tool_name in ["drag", "swipe"]:
                    # 新版 hypium_mcp SDK 入参为 start: [x, y] / end: [x, y]；兼容旧版 start_x/start_y/end_x/end_y
                    start = args_dict.get("start")
                    end = args_dict.get("end")
                    if (start is not None and len(start) == 2
                            and end is not None and len(end) == 2):
                        start_x = normalize_coord(start[0])
                        start_y = normalize_coord(start[1])
                        end_x = normalize_coord(end[0])
                        end_y = normalize_coord(end[1])
                    elif all(k in args_dict for k in ["start_x", "start_y", "end_x", "end_y"]):
                        start_x = normalize_coord(args_dict["start_x"])
                        start_y = normalize_coord(args_dict["start_y"])
                        end_x = normalize_coord(args_dict["end_x"])
                        end_y = normalize_coord(args_dict["end_y"])
                    else:
                        start_x = start_y = end_x = end_y = None
                    if None not in [start_x, start_y, end_x, end_y]:
                        action["start"] = [
                            int(float(start_x) * screen_width),
                            int(float(start_y) * screen_height)
                        ]
                        action["end"] = [
                            int(float(end_x) * screen_width),
                            int(float(end_y) * screen_height)
                        ]

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

        return llm_start_time, llm_end_time, thinking, content, raw_content, action

    def _execute_step(self, user_prompt: str | None = None, is_first: bool = False) -> StepResult:
        """Execute a single step of the agent's task."""
        step_start_time = datetime.now()
        self._step_count += 1
        current_time = step_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        if self._report_generator:
            self._report_generator.execute_agent_step_start(step_count=self._step_count)

        self._current_screenshot = self.device.get_screenshot(save_to_report=True)
        self._screenshot.append(self._current_screenshot.screenshot_path)
        self._current_layout_data = getattr(self._current_screenshot, 'layout_data', None)
        if self._current_layout_data:
            logger.info(f"[HypiumMCPAgent] Saved layout_data: {len(self._current_layout_data)} chars")
        else:
            logger.warning("[HypiumMCPAgent] No layout_data available in screenshot")
        current_app = self.device.get_current_app()

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
                    text=text_content,
                    image_base64=self._current_screenshot.base64_data
                )
            )
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"** Screen Info **\n\n{screen_info}"
            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content,
                    image_base64=self._current_screenshot.base64_data
                )
            )

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

        if action.get("log", ""):
            log = action.get("log")
        elif self._pending_tool_calls:
            log = user_prompt
            action["log"] = log
        else:
            action = {"_metadata": "finish", "message": raw_content}
            log = raw_content

        # Guard: detect repeated identical actions to prevent infinite loops.
        # When the model tries to execute the same action (same log) as the
        # previous step, skip execution and force finish. This handles cases
        # where the page still shows the target element after clicking (e.g.
        # episode selector "2" button remains visible after selection).
        if (self._pending_tool_calls and log and self._last_action_log
                and log == self._last_action_log):
            logger.info(
                f"[HypiumMCPAgent] Detected repeated action: '{log}', "
                f"auto-finishing to prevent duplicate execution"
            )
            action = {"_metadata": "finish",
                      "message": f"任务已完成（检测到重复操作：{log}）"}
            self._pending_tool_calls = None
            log = f"任务已完成（检测到重复操作，自动结束）"

        # Update last action log for next step's repeat detection
        self._last_action_log = log if self._pending_tool_calls else None

        self._history.append(f"{len(self._history) + 1}、{log}")

        time_calculate = TimeCalculate(llm_start_time, llm_end_time)
        if self._report_generator:
            self._report_generator.execute_agent_do_start(
                time_calculate=time_calculate,
                thinking=thinking,
                screenshot=self._current_screenshot,
                action=action,
                step_count=self._step_count
            )

        self._manage_history_images(getattr(self.agent_config, "max_history_image", 2))

        self._context.append(
            MessageBuilder.create_assistant_message(raw_content)
        )

        action_start_time = datetime.now()
        tool_results = []
        action_result = {"success": True, "message": "", "should_finish": False}

        if self._pending_tool_calls:
            for tc in self._pending_tool_calls:
                tool_call_id = tc.get('id', f"call_{len(self._context)}")
                tool_name = tc.get('function', {}).get('name', 'unknown')
                tool_args_str = tc.get('function', {}).get('arguments', '{}')

                tool_args = json.loads(tool_args_str)
                tool_args_str = json.dumps(tool_args, ensure_ascii=False)

                logger.info(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] "
                    f"Tool Call: {tool_name} args: {tool_args_str}")

                self._context.append(
                    MessageBuilder.create_tool_call_message(tool_call_id, tool_name, tool_args_str)
                )

                tool_result = self._execute_tool(tool_name, tool_args_str)
                tool_results.append({"name": tool_name, "result": tool_result})
                action_result["message"] = tool_result

                self._context.append(
                    MessageBuilder.create_tool_result_message(tool_call_id, tool_name, tool_result)
                )

        action_end_time = datetime.now()
        action_time_calculate = TimeCalculate(action_start_time, action_end_time)

        if self._report_generator:
            post_screenshot = self.device.get_screenshot(save_to_report=True)

            self._report_generator.execute_agent_do_end(
                time_calculate=action_time_calculate,
                screenshot=post_screenshot,
                result=type('obj', (object,), action_result),
                step_count=self._step_count
            )

            self._report_generator.execute_agent_step_end()

        if not self._pending_tool_calls:
            finished = True
            action_result["message"] = raw_content
        else:
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
        """Get the current step count."""
        return self._step_count

    @property
    def screenshot(self) -> list[Any]:
        """Get the list of screenshots taken during execution."""
        return self._screenshot.copy()

    @property
    def context(self) -> list[dict[str, Any]]:
        """Get the current conversation context (messages)."""
        return self._context.copy()

    @property
    def is_running(self) -> bool:
        """Check if the agent is currently running a task."""
        return self._is_running

    @property
    def history(self) -> list[str]:
        """Get the execution history."""
        return self._history.copy()
