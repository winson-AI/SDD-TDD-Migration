import asyncio
import json
import re
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

from openai import AsyncAzureOpenAI, AsyncOpenAI

from hypium import BY

from ..layered_agent_cli.mcp_tools import TOOL_REGISTRY
from ..layered_agent_cli.decision_hooks import DecisionHooks
from ..layered_agent_cli.decision import create_session_input_filter
from ..memory.compressed_session import CompressedSession
from ..logger import logger
from ..utils.utils import retry_on_exception
from .tool_recorder import ToolRecorder, RecordingSession, ToolCallRecord
from agents import Runner, RunConfig


@dataclass
class MockTool:
    """Mock tool object for report generator."""
    name: str


@dataclass
class PopupHandlingConfig:
    """Configuration for popup handling during playback."""
    enabled: bool = True
    max_retry_attempts: int = 1
    skip_popup_steps: bool = True


class ToolPlayer:
    """
    Player for replaying recorded MCP tool calls.

    Loads a recording from JSON file and executes the tool calls
    in order without calling the LLM model.
    """

    ACTION_MAP = {
        "click": "Tap",
        "double_click": "Double Tap",
        "long_click": "Long Press",
        "drag": "Drag",
        "swipe": "Swipe",
        "pinch_in": "Pinch In",
        "pinch_out": "Pinch Out",
        "input_text": "Type",
        "clear_text": "Clear Text",
    }
    # 回放时直接跳过的工具（这些工具仅用于录制阶段获取上下文，回放无需执行）
    SKIP_REPLAY_TOOLS = {"load_skill"}
    # 执行 agent 返回结果中的失败语义关键词，用于判断操作是否真正成功
    FAILURE_KEYWORDS = ("无法", "未找到", "不存在", "失败")

    def __init__(
            self,
            device,
            report_generator=None,
            executor_agent=None,
            verify_agent=None,
            planner_agent=None,
            config=None
    ):
        """
        Initialize the player.

        Args:
            device: Device protocol instance (HDCDevice)
            report_generator: Optional report generator
            executor_agent: Optional executor agent for execute tool
            verify_agent: Optional verify agent for verify tool
            planner_agent: Optional planner agent for replanning on failure
            config: Optional configuration for replanning
        """
        self.device = device
        self.report_generator = report_generator
        self.executor_agent = executor_agent
        self.verify_agent = verify_agent
        self.planner_agent = planner_agent
        self.config = config
        self.popup_config = PopupHandlingConfig()
        self._current_session: Optional[RecordingSession] = None
        self._current_recordings: List[Dict] = []  # 保存所有执行记录，用于合并
        self._current_index = 0
        self._last_playback_results: Optional[List[Dict]] = None
        self._step_count = 0
        self._replan_triggered: bool = False
        self._last_execute_failure = None
        self._popup_stats = {
            "detected": 0,
            "closed": 0,
            "skipped": 0,
            "retry_success": 0,
            "retry_failed": 0
        }

        logger.info(f"[ToolPlayer] Available tools: {list(TOOL_REGISTRY.keys())}")

    def load_record(self, file_path: str) -> bool:
        """Load recording from JSON file."""
        session = ToolRecorder.load_from_file(file_path)
        if session:
            self._current_session = session
            self._current_index = 0
            # 加载历史记录
            self._current_recordings = list(session.recordings)
            logger.info(
                f"[ToolPlayer] Loaded: {session.task} ({session.total_calls} calls), {len(self._current_recordings)} recordings")
            return True
        logger.error(f"[ToolPlayer] Failed to load: {file_path}")
        return False

    def load_by_task(self, task: str, memory_dir: str = "memory") -> bool:
        """Load recording by task hash or full task description."""
        session = ToolRecorder.find_recording(task, memory_dir)
        if session:
            self._current_session = session
            self._current_index = 0
            # 加载历史记录
            self._current_recordings = list(session.recordings)
            logger.info(
                f"[ToolPlayer] Loaded: {session.task} ({session.total_calls} calls), {len(self._current_recordings)} recordings")
            return True
        logger.error(f"[ToolPlayer] Failed to load for task: {task}")
        return False

    def _build_replan_prompt(self, original_task: str, full_history: List[Dict], failure_info: dict) -> str:
        """构造重新规划的 prompt

        Args:
            original_task: 原始任务（从 RecordingSession 获取）
            full_history: 完整的执行历史记录列表
            failure_info: 包含失败信息的字典

        Returns:
            重新规划的 prompt 字符串
        """
        failure_reason = failure_info.get('failure_reason', '未知原因')
        failed_step = failure_info.get('failed_step', '未知步骤')
        suggestion = failure_info.get('suggestion', '')

        # 格式化完整历史记录（只显示简洁摘要）
        history_text = ""
        if full_history:
            history_lines = []
            for i, rec in enumerate(full_history, 1):
                tool_name = rec.get('tool_name', 'unknown')
                arguments = rec.get('arguments', {})
                result = rec.get('result', '')
                message_text = arguments.get('message', '') if isinstance(arguments, dict) else str(arguments)

                # 如果 message 是 JSON 格式，提取操作意图
                if isinstance(message_text, str) and message_text.strip().startswith('{'):
                    try:
                        msg_data = json.loads(message_text)
                        action = msg_data.get('action', '操作')
                        log = msg_data.get('log', '')
                        if log:
                            message_text = log
                        else:
                            # 生成简短描述
                            x = msg_data.get('x', '')
                            y = msg_data.get('y', '')
                            if action == 'click':
                                message_text = f"点击"
                            elif action == 'double_click':
                                message_text = f"双击"
                            elif action == 'long_click':
                                message_text = f"长按"
                            elif action == 'swipe':
                                message_text = f"滑动"
                            elif action == 'input':
                                message_text = f"输入"
                            else:
                                message_text = action
                    except:
                        pass

                # 通用结果解析函数
                def parse_result(result_obj):
                    """解析各种类型的结果对象，返回 (result_text, result_data, is_success)"""
                    result_data = {}
                    result_text = ""
                    is_success = True

                    # 处理 None
                    if result_obj is None:
                        return "无结果", {}, True

                    # 处理 bool 类型（MCP 调用常见）
                    if isinstance(result_obj, bool):
                        is_success = result_obj
                        return "成功" if result_obj else "失败", {}, result_obj

                    # 处理 dict 类型
                    if isinstance(result_obj, dict):
                        result_data = result_obj
                        # 尝试从 dict 中提取有用信息
                        if 'success' in result_obj:
                            is_success = bool(result_obj['success'])
                        if 'result' in result_obj:
                            result_text = str(result_obj['result'])
                        elif 'message' in result_obj:
                            result_text = str(result_obj['message'])
                        elif 'error' in result_obj:
                            result_text = str(result_obj['error'])
                            is_success = False
                        else:
                            # 如果没有明确字段，尝试序列化整个 dict
                            result_text = str(result_obj)
                        return result_text, result_data, is_success

                    # 处理列表类型
                    if isinstance(result_obj, list):
                        if len(result_obj) == 0:
                            return "空列表", {}, True
                        elif len(result_obj) == 1:
                            return parse_result(result_obj[0])
                        else:
                            return f"列表({len(result_obj)}项)", {}, True

                    # 处理字符串类型
                    if isinstance(result_obj, str):
                        result_text = result_obj
                        # 尝试解析 JSON 字符串
                        if result_text.startswith('{') or result_text.startswith('['):
                            try:
                                parsed = json.loads(result_text)
                                return parse_result(parsed)
                            except:
                                pass

                        # 检查成功/失败标记
                        if '[FAILURE]' in result_text or '[FAIL]' in result_text or '[ERROR]' in result_text:
                            is_success = False
                        elif '[SUCCESS]' in result_text or '[OK]' in result_text or '[DONE]' in result_text:
                            is_success = True
                        elif result_text.lower().startswith('error'):
                            is_success = False

                        return result_text, {}, is_success

                    # 处理其他类型（int, float 等）
                    return str(result_obj), {}, True

                # 解析结果
                result_text, result_data, is_success = parse_result(result)

                # 生成简洁的摘要（从解析后的结果中提取关键信息）
                import re
                if '[SUCCESS]' in result_text:
                    success_match = re.search(r'\[SUCCESS\]\s*(.+)', result_text, re.DOTALL)
                    if success_match:
                        result_text = success_match.group(1).strip().split('\n')[0][:60]
                elif '[FAILURE]' in result_text:
                    failure_match = re.search(r'\[FAILURE\]\s*(.+)', result_text, re.DOTALL)
                    if failure_match:
                        result_text = failure_match.group(1).strip().split('\n')[0][:60]

                # 生成步骤摘要
                if tool_name == 'execute':
                    step_summary = f"执行：{message_text or '操作'}"
                elif tool_name == 'verify':
                    desc = arguments.get('description', '检查') if isinstance(arguments, dict) else '检查'
                    step_summary = f"验证：{desc}"
                    # 添加简短结果
                    if result_text and len(result_text) > 5:
                        step_summary += f" - {result_text[:40]}"
                else:
                    step_summary = f"{tool_name}"
                    if result_text and len(result_text) > 5:
                        step_summary += f" - {result_text[:40]}"

                status_icon = "✅" if is_success else "❌"
                history_lines.append(f"  {i}. {status_icon} {step_summary}")

            history_text = "\n".join(history_lines)
        else:
            history_text = "无执行历史"

        replan_prompt = f"""## 任务执行失败，需要重新规划

### 原始任务
{original_task}

### 已回放的步骤
{history_text}

### 当前失败信息
- **失败原因**: {failure_reason}
- **失败步骤**: {failed_step}

### 重新规划要求
请分析失败原因和执行历史，重新规划执行方案：
1. 查看完整执行历史，理解之前的成功步骤和当前失败
2. 检查失败原因，判断是否需要更换操作方式
3. 如果目标选项不存在，尝试寻找替代方案
4. 如果操作方式不对，调整操作策略
5. 输出新的执行指令

{suggestion if suggestion else ""}

请根据以上分析，给出新的执行方案。
"""

        return replan_prompt

    async def _trigger_replan(self, failure_info: dict, remaining_timeout: float = None):
        """触发重新规划

        当回放时 execute 失败，调用规划器重新执行任务。
        完全参照 decision.py 的实现，使用 Runner.run() 完整参数。

        Args:
            failure_info: 包含失败信息的字典
        """
        if self._replan_triggered:
            logger.warning("[ToolPlayer] Replan already triggered, skipping duplicate call")
            return

        self._replan_triggered = True

        if not self.planner_agent:
            logger.warning("[ToolPlayer] No planner agent available, cannot replan")
            return

        if not self.config:
            logger.warning("[ToolPlayer] No config available, cannot replan")
            return

        # 获取原始任务和完整历史（从 RecordingSession 获取）
        original_task = self._current_session.task if self._current_session else failure_info.get('original_task',
                                                                                                  '未知任务')

        # 获取失败步骤索引
        failed_step_index = failure_info.get('failed_step_index', 0)

        # 获取失败步骤之前的完整历史记录
        full_history = self._current_recordings[:failed_step_index]

        replan_prompt = self._build_replan_prompt(original_task, full_history, failure_info)
        logger.warning(f"[ToolPlayer] Triggering replan with prompt:\n{replan_prompt}")

        # 计算重新规划的超时时间
        if remaining_timeout is None:
            remaining_timeout = self.config.task_timeout
        logger.info(f"[ToolPlayer] Replan timeout: {remaining_timeout}s")
        max_turns = self.config.max_steps

        tool_recorder = ToolRecorder(original_task)

        # 合并失败步骤之前的记录（只取已回放的步骤）
        failed_step_index = failure_info.get('failed_step_index', 0)
        history_records = [rec for rec in self._current_recordings if rec.get('is_played', False)]
        if history_records:
            logger.info(
                f"[ToolPlayer] Merging {len(history_records)} history records before failed step {failed_step_index}")
            for rec in history_records:
                tool_recorder.record_tool_call(
                    tool_name=rec.get('tool_name'),
                    arguments=rec.get('arguments', {}),
                    result=rec.get('result', ''),
                    click_caches=rec.get('click_caches')
                )

        session = CompressedSession(auto_compress=True)

        input_filter = await create_session_input_filter(session)

        run_config = RunConfig(
            call_model_input_filter=input_filter,
        )

        try:
            result = await asyncio.wait_for(
                Runner.run(
                    self.planner_agent,
                    replan_prompt,
                    max_turns=max_turns,
                    hooks=DecisionHooks(self.device, session, self.report_generator, tool_recorder),
                    session=session,
                    run_config=run_config
                ),
                timeout=remaining_timeout
            )
            replan_result = str(result.final_output)
            logger.info(f"[ToolPlayer] Replan completed: {replan_result}")

            if self._last_playback_results is None:
                self._last_playback_results = []

            self._last_playback_results.append({
                "order": -1,
                "tool_name": "replan",
                "arguments": {"prompt": replan_prompt},
                "original_result": None,
                "playback_result": replan_result,
                "success": True,
                "is_replan": True
            })

            try:
                if replan_result and "任务结果: 不通过" in replan_result:
                    logger.info(f"[ToolPlayer] Replan task not passed, skip saving tool recording")
                else:
                    recording_path = tool_recorder.save_to_file()
                    logger.info(f"[ToolPlayer] Tool calls saved to: {recording_path}")
            except Exception as e:
                logger.warning(f"[ToolPlayer] Failed to save tool recording: {e}")

        except asyncio.TimeoutError:
            logger.error(f"[ToolPlayer] Replan timed out after {remaining_timeout}s")
            if self._last_playback_results is None:
                self._last_playback_results = []
            self._last_playback_results.append({
                "order": -1,
                "tool_name": "replan",
                "arguments": {"prompt": replan_prompt},
                "original_result": None,
                "playback_result": f"Timeout after {remaining_timeout}s",
                "success": False,
                "error": "Replan timeout",
                "is_replan": True
            })
        except Exception as e:
            logger.error(f"[ToolPlayer] Replan failed: {e}")
            if self._last_playback_results is None:
                self._last_playback_results = []
            self._last_playback_results.append({
                "order": -1,
                "tool_name": "replan",
                "arguments": {"prompt": replan_prompt},
                "original_result": None,
                "playback_result": str(e),
                "success": False,
                "error": str(e),
                "is_replan": True
            })
        finally:
            try:
                # 将重新规划后的记录合并回 _current_recordings
                new_recordings = tool_recorder.get_recordings()
                if new_recordings:
                    # 将 ToolCallRecord 转换为字典
                    recordings_dict = [
                        {
                            "order": rec.order,
                            "tool_name": rec.tool_name,
                            "arguments": rec.arguments,
                            "result": rec.result,
                            "timestamp": rec.timestamp,
                            "click_caches": rec.click_caches
                        }
                        for rec in new_recordings
                    ]
                    self._current_recordings = recordings_dict
                    logger.info(f"[ToolPlayer] Replaced recordings with {len(recordings_dict)} records from replan")
            except Exception as e:
                logger.warning(f"[ToolPlayer] Failed to process replan recordings: {e}")

    def _ensure_first_verify_screenshot(self, tool_name: str, screenshot) -> None:
        """Attach the current screenshot to step 0 before the first verify playback."""
        if tool_name != "verify" or self._current_index != 0:
            return

        if not self.report_generator or not screenshot:
            return

        step_content = getattr(self.report_generator, "step_content", None)
        if not step_content:
            return

        first_step = step_content[0]
        if getattr(first_step, "screenshot_path", ""):
            return

        first_step.screenshot_path = screenshot.screenshot_path
        first_step.timestamp = time.time()

        if not getattr(first_step, "step_type", ""):
            first_step.step_type = "task"

        logger.info(
            "[ToolPlayer] Attached initial screenshot to step 0 before first verify: "
            f"{screenshot.screenshot_path}"
        )

    async def _execute_tool_async(
            self,
            tool_name: str,
            arguments: Dict[str, Any],
            click_caches: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Execute a single tool call."""
        from ..reporter.reporter_types import TimeCalculate

        logger.info(f"[ToolPlayer] #{self._current_index + 1}: {tool_name}({arguments})")
        if click_caches:
            logger.info(
                f"[ToolPlayer]   click_caches: {len(click_caches)} sub-steps, "
                f"actions={[c.get('action') for c in click_caches if c]}, "
                f"use_xpath_flags={[c.get('use_xpath') for c in click_caches if c]}"
            )

        tool_start_time = datetime.now()
        result = None

        screenshot = self.device.get_screenshot(save_to_report=True)
        self._current_screenshot = screenshot
        self._ensure_first_verify_screenshot(tool_name, screenshot)

        # === execute 工具的多步缓存回放 ===
        # 当 execute 工具在录制阶段触发了 Executor 内部的多步 click 时，
        # click_caches 列表按顺序记录了每一步的缓存。
        # 回放时按顺序执行所有子步骤：
        #   - use_xpath=True 的子步骤走 xpath 精确回放
        #   - use_xpath=False 的子步骤交给执行 agent 单步执行
        # 失败处理：中间步骤失败继续执行后续；最后一步失败则中断。
        if (tool_name == "execute"
                and click_caches
                and len(click_caches) > 0):
            logger.info(
                f"[ToolPlayer] execute 多步缓存回放: {len(click_caches)} 个子步骤"
            )
            sub_results = []
            all_success = True
            last_error = None
            total = len(click_caches)
            # click_caches 只有 1 个子步骤时视为单步操作：
            # 回放时优先用外层 message（用户原始意图），而非 target_text
            is_single_step = (total == 1)

            for idx, sub_cache in enumerate(click_caches):
                is_last_step = (idx == total - 1)
                step_desc = (
                    f"子步骤 {idx + 1}/{total}: "
                    f"action={sub_cache.get('action')}, "
                    f"use_xpath={sub_cache.get('use_xpath')}, "
                    f"is_last={is_last_step}"
                )
                logger.info(f"[ToolPlayer]   {step_desc}")

                # 每个子步骤前重新截图，保证 xpath 查找基于最新 UI
                try:
                    screenshot = self.device.get_screenshot(save_to_report=True)
                    self._current_screenshot = screenshot
                except Exception as e:
                    logger.warning(f"[ToolPlayer]   子步骤 {idx + 1} 截图失败: {e}")

                sub_result = None
                try:
                    sub_action = sub_cache.get('action')
                    if sub_action in ('input_text', 'clear_text'):
                        # 文本类操作：与单步回放一致，直接走 MCP 执行
                        sub_result = self._replay_text_action(
                            sub_cache, arguments, screenshot, tool_start_time
                        )
                    elif sub_cache.get('use_xpath') and sub_cache.get('xpath'):
                        # 修改点 1 前半部分：有 xpath，精确回放
                        sub_result = await self._replay_single_click_cache(
                            sub_cache, screenshot, tool_start_time, arguments
                        )
                        # xpath 回放返回 None 表示查找失败，
                        # fallback 到执行 agent 单步执行
                        if sub_result is None:
                            logger.info(
                                f"[ToolPlayer]   子步骤 {idx + 1} xpath 回放失败，fallback 到执行 agent"
                            )
                            sub_result = await self._replay_step_via_executor(
                                sub_cache, arguments, screenshot,
                                is_single_step=is_single_step
                            )
                    else:
                        # 修改点 2：无 xpath，单步交给执行 agent 执行
                        sub_result = await self._replay_step_via_executor(
                            sub_cache, arguments, screenshot,
                            is_single_step=is_single_step
                        )
                except Exception as e:
                    logger.warning(
                        f"[ToolPlayer]   子步骤 {idx + 1} 执行异常: {e}"
                    )
                    sub_result = json.dumps(
                        {"error": f"sub-step {idx + 1} exception: {str(e)}"},
                        ensure_ascii=False
                    )

                sub_results.append(sub_result)

                # 判断本子步骤是否失败
                sub_failed = (
                    isinstance(sub_result, str)
                    and ('"error"' in sub_result or sub_result.startswith('{"error"'))
                )

                if sub_failed:
                    all_success = False
                    last_error = sub_result
                    logger.warning(
                        f"[ToolPlayer]   子步骤 {idx + 1} 失败"
                        f"{'（最后一步，中断）' if is_last_step else '（中间步骤，继续）'}: "
                        f"{sub_result[:200]}"
                    )
                    if is_last_step:
                        # 最后一步失败，中断后续（无后续子步骤，但仍要 break 以便汇总失败）
                        break
                    # 中间步骤失败，继续执行下一步
                else:
                    logger.info(
                        f"[ToolPlayer]   子步骤 {idx + 1} 完成"
                    )

            # 只有最后一个子步骤失败才触发 replan
            # 中间步骤失败不影响整体结果（与循环中"中间步骤失败继续执行"的设计一致）
            replan_required = False
            failure_reason = ""
            failed_step = ""
            last_sub_result = sub_results[-1] if sub_results else None
            if isinstance(last_sub_result, str):
                try:
                    last_sr_data = json.loads(last_sub_result)
                    if last_sr_data.get("replan_required"):
                        replan_required = True
                        failure_reason = last_sr_data.get("failure_reason", last_sr_data.get("error", ""))
                        failed_step = last_sr_data.get("failed_step", last_sr_data.get("instruction", ""))
                except (json.JSONDecodeError, AttributeError):
                    pass

            # 汇总结果：success 只取决于最后一个子步骤是否成功
            last_step_failed = replan_required
            result = json.dumps({
                "action": "execute_replay",
                "steps": total,
                "completed": len(sub_results),
                "success": not last_step_failed,
                "replan_required": replan_required,
                "failure_reason": failure_reason,
                "failed_step": failed_step,
                "history": sub_results,
                "message": (
                    f"回放 execute: 完成 {len(sub_results)}/{total} 步"
                    + (f"，最后一步失败: {last_error[:100]}" if last_error else "")
                )
            }, ensure_ascii=False)

            # 不再上报汇总 action：子步骤已在 _replay_single_click_cache /
            # _replay_text_action / _replay_step_via_executor 中各自上报，
            # 此处重复上报会导致步骤重复出现两次。
            logger.info(
                f"[ToolPlayer] execute 多步回放结束: success={not last_step_failed}, "
                f"completed={len(sub_results)}/{total}"
            )

        elif (click_caches
                and len(click_caches) == 1
                and click_caches[0]
                and click_caches[0].get('use_xpath')
                and click_caches[0].get('xpath')):
            # 单步 xpath 精确回放
            result = await self._replay_single_click_cache(
                click_caches[0], screenshot, tool_start_time, arguments
            )

        elif (click_caches
                and len(click_caches) == 1
                and click_caches[0]
                and click_caches[0].get('action') in ('input_text', 'clear_text')):
            result = self._replay_text_action(
                click_caches[0], arguments, screenshot, tool_start_time
            )

        if result is None:
            if tool_name not in TOOL_REGISTRY:
                result = f'{{"error": "Tool not found: {tool_name}"}}'
            else:
                try:
                    tool_obj = TOOL_REGISTRY[tool_name]
                    args_json = json.dumps(arguments)

                    # FunctionTool uses on_invoke_tool which takes ToolContext and JSON args string
                    from agents.tool import ToolContext
                    from agents.usage import Usage

                    # Create a minimal ToolContext
                    # ToolContext requires: context, tool_name, tool_call_id, tool_arguments
                    ctx = ToolContext(
                        context={},  # Empty context dict
                        usage=Usage(),
                        tool_name=tool_name,
                        tool_call_id=f"call_{tool_name}",
                        tool_arguments=args_json
                    )

                    # on_invoke_tool takes context and JSON string arguments
                    result = await tool_obj.on_invoke_tool(ctx, args_json)
                    result = str(result) if result is not None else "OK"

                    time.sleep(3)

                    # 根据工具类型生成有描述性的标题，便于验证代理准确选择步骤
                    if tool_name == "run_skill_script":
                        script_name = arguments.get('script_name', '')
                        script_args = arguments.get('args', '')
                        action_log = f"执行run_skill_script: {script_name} ({script_args})"
                    else:
                        action_log = f"执行{tool_name}工具"

                    action = {
                        "_metadata": "do",
                        "action": tool_name,
                        "log": action_log,
                        "element": []
                    }
                    self._report_action(action, screenshot, tool_start_time)
                except Exception as e:
                    logger.error(f"[ToolPlayer] {tool_name} failed: {e}")
                    result = f'{{"error": "{str(e)}"}}'

        return result or ""

    def _is_progress_bar_capture_message(self, message: str) -> bool:
        """判断 execute 指令是否为「唤起进度条并获取坐标」类操作。

        这类操作在录制时会返回进度条坐标（x1/y1/x2/y2/x3/y3），但回放时按
        click_caches 的 xpath 回放只会点击、不会返回坐标，需要特殊处理。
        """
        if not message:
            return False
        return ("进度条" in message
                and ("唤起" in message or "获取" in message)
                and ("x1" in message or "x2" in message or "x3" in message))

    async def _replay_progress_bar_capture(self, arguments: Dict[str, Any]) -> str:
        """实际调用 execute 工具执行「唤起进度条获取坐标」指令。

        回放时 execute 步骤通常按 click_caches 走 xpath 精确回放，只会点击对应控件
        而不会返回进度条坐标。这里直接调用 execute MCP 工具，让执行模型基于当前
        屏幕重新唤起进度条并分析最新坐标，返回与录制时同构的结果（execute 内部会
        自行处理动作上报）。

        Returns:
            execute 工具返回的 JSON 字符串（含 result/steps/success 等字段）。
        """
        try:
            screenshot = self.device.get_screenshot(save_to_report=True)
            self._current_screenshot = screenshot
        except Exception as e:
            logger.warning(f"[ToolPlayer] 进度条坐标获取截图失败: {e}")

        if "execute" not in TOOL_REGISTRY:
            return json.dumps({"error": "execute tool not registered"}, ensure_ascii=False)

        tool_obj = TOOL_REGISTRY["execute"]
        # 追加格式约束，避免模型返回各种自由格式导致坐标解析失败
        fmt_hint = (
            "\n\n请务必严格按以下格式返回坐标（括号内填实际坐标），"
            "每行一组，不要加 markdown 加粗、不要加多余说明：\n"
            "起点坐标 (x1, y1)：(x1值, y1值)\n"
            "终点坐标 (x2, y2)：(x2值, y2值)\n"
            "当前进度坐标 (x3, y3)：(x3值, y3值)"
        )
        pb_arguments = dict(arguments)
        pb_arguments["message"] = arguments.get("message", "") + fmt_hint
        args_json = json.dumps(pb_arguments, ensure_ascii=False)

        from agents.tool import ToolContext
        from agents.usage import Usage

        ctx = ToolContext(
            context={},
            usage=Usage(),
            tool_name="execute",
            tool_call_id="call_execute_progress_bar",
            tool_arguments=args_json,
        )
        try:
            result = await tool_obj.on_invoke_tool(ctx, args_json)
            return str(result) if result is not None else ""
        except Exception as e:
            logger.error(f"[ToolPlayer] 进度条坐标获取(execute)失败: {e}")
            return json.dumps(
                {"error": f"execute 调用失败: {str(e)}", "replan_required": True,
                 "failure_reason": str(e), "failed_step": arguments.get('message', '')},
                ensure_ascii=False
            )

    def _extract_progress_bar_coords(self, result_str: str) -> Optional[Dict[str, int]]:
        """从 execute 结果文本中解析进度条坐标 x1/y1/x2/y2/x3/y3。

        结果可能为 JSON 字符串（含 result 字段）或纯文本，均尝试解析。
        主格式（execute 格式约束输出）：起点坐标 (x1, y1)：(80, 820)
        兜底格式（录制时旧结果）：x1=80, y1=820
        """
        text = result_str or ""
        if text.strip().startswith('{'):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    text = data.get('result', '') or text
            except json.JSONDecodeError:
                pass
        if not text:
            return None
        coords: Dict[str, int] = {}
        # 主格式：起点坐标 (x1, y1)：(80, 820)
        # 冒号与值括号间可能有"约"/"**"等修饰，用 .*? 跳过
        for n in ('1', '2', '3'):
            xk, yk = f'x{n}', f'y{n}'
            m = re.search(
                rf'{xk}.*?{yk}.*?[：:].*?[\(（]\s*(\d+)\s*[,，]\s*(\d+)\s*[\)）]',
                text)
            if m:
                coords[xk] = int(m.group(1))
                coords[yk] = int(m.group(2))
        # 兜底格式：x1=80, y1=820（补全主格式未匹配到的坐标）
        for key in ('x1', 'y1', 'x2', 'y2', 'x3', 'y3'):
            if key in coords:
                continue
            m = re.search(rf'{key}\s*[=：:]\s*(\d+)', text)
            if m:
                coords[key] = int(m.group(1))
        # 至少需要 x2/y2/x3/y3 才能构造 swipe 参数
        if all(k in coords for k in ('x2', 'y2', 'x3', 'y3')):
            return coords
        return None

    def _build_swipe_args_from_progress_bar_result(
            self,
            fresh_result: str,
            recorded_result: str,
            original_args: str
    ) -> Optional[str]:
        """根据 execute 返回的最新进度条坐标，构造 swipe_video_progress_bar 脚本参数。

        录制时 swipe 参数顺序为 <from_x from_y to_x to_y>（from 为拖动起点，通常是
        当前播放位置；to 为拖动终点，即进度条起点或终点）。通过将录制时的参数值与
        录制时获取的坐标做匹配，确定每个参数对应的进度条坐标语义，再用最新坐标替换，
        保证回放时拖动到正确的终点。

        匹配失败时退化为「当前进度 -> 终点」的常见模式（快进到终点）。
        """
        fresh = self._extract_progress_bar_coords(fresh_result)
        if not fresh:
            return None
        # 退化模式：当前播放位置 -> 进度条终点
        fallback = f"{fresh['x3']} {fresh['y3']} {fresh['x2']} {fresh['y2']}"

        recorded = self._extract_progress_bar_coords(recorded_result)
        if not recorded or not original_args:
            return fallback

        parts = original_args.split()
        if len(parts) != 4:
            return fallback
        try:
            vals = [int(p) for p in parts]
        except ValueError:
            return fallback

        # 三个进度条坐标点：起点 / 终点 / 当前播放位置
        rec_pts = [('x1', recorded['x1'], recorded['y1']),
                   ('x2', recorded['x2'], recorded['y2']),
                   ('x3', recorded['x3'], recorded['y3'])]
        fresh_pts = {'x1': (fresh['x1'], fresh['y1']),
                     'x2': (fresh['x2'], fresh['y2']),
                     'x3': (fresh['x3'], fresh['y3'])}

        def map_point(px: int) -> Optional[str]:
            for key, rx, _ry in rec_pts:
                if rx == px:
                    fx, fy = fresh_pts[key]
                    return f"{fx} {fy}"
            return None

        # 参数第 1、3 位为 x 坐标，按 x 值匹配进度条坐标语义
        p1 = map_point(vals[0])
        p2 = map_point(vals[2])
        if p1 and p2:
            return f"{p1} {p2}"
        return fallback

    async def _replay_single_click_cache(
            self,
            sub_cache: Dict[str, Any],
            screenshot,
            tool_start_time: datetime,
            arguments: Dict[str, Any]
    ) -> Optional[str]:
        """单个子步骤缓存走 xpath 精确回放。

        抽取自原 _execute_tool_async 中的 xpath 回放分支，
        供单步回放和 execute 多步回放中的 use_xpath=True 子步骤复用。

        Args:
            sub_cache: 单步点击缓存，必须包含 use_xpath=True 和 xpath
            screenshot: 当前截图
            tool_start_time: 当前步骤起始时间（用于上报）
            arguments: 外层工具参数（用于 log 文案）

        Returns:
            成功时返回 JSON 字符串形式的结果（含 action/x/y/xpath）。
            失败时返回 None，调用方可据此决定是否 fallback。
        """
        action_type = sub_cache.get('action', 'click')
        xpath = sub_cache.get('xpath')
        logger.info(
            f"[ToolPlayer] Trying cached xpath: {xpath}, action={action_type} "
            f"(distance={sub_cache.get('distance')}px)"
        )
        try:
            driver = self._get_driver()
            if not driver:
                logger.warning("[ToolPlayer] Driver not available, fallback to execute")
                return None
            if not BY:
                logger.warning("[ToolPlayer] Hypium BY not available, fallback to execute")
                return None

            component = self._find_best_component_by_xpath(
                driver,
                xpath,
                bounds=sub_cache.get('start_bounds') or sub_cache.get('element_bounds'),
                fallback_x=sub_cache.get('click_x'),
                fallback_y=sub_cache.get('click_y'),
                label='start'
            )
            if not component:
                logger.warning(
                    f"[ToolPlayer] Cached xpath not found: {xpath}, fallback to execute"
                )
                return None

            center = component.getBoundsCenter()
            cx, cy = center.X, center.Y
            logger.info(f"[ToolPlayer] Found component at center ({cx}, {cy})")

            # 通过 MCP 执行操作（坐标需要缩放到 0-1000）
            mcp_tool_name = action_type if action_type != 'long_click' else 'long_click'
            screen_width = screenshot.width if screenshot else None
            screen_height = screenshot.height if screenshot else None

            def normalize_for_mcp(px: int, py: int) -> tuple[int, int]:
                if screen_width and screen_height:
                    normalized_x = int((px / screen_width) * 1000)
                    normalized_y = int((py / screen_height) * 1000)
                    logger.info(
                        f"[ToolPlayer] Coordinate conversion: ({px}, {py}) -> "
                        f"({normalized_x}, {normalized_y}) for screen {screen_width}x{screen_height}"
                    )
                    return normalized_x, normalized_y
                logger.warning("[ToolPlayer] No screenshot available for coordinate normalization")
                return int(px), int(py)

            if action_type in ('swipe', 'drag'):
                xpath_end = sub_cache.get('xpath_end')
                # 滑动操作直接使用录制坐标，xpath 仅用于验证当前页面
                rec_start_x = sub_cache.get('click_x')
                rec_start_y = sub_cache.get('click_y')
                if rec_start_x is not None and rec_start_y is not None:
                    cx, cy = int(float(rec_start_x)), int(float(rec_start_y))
                    logger.info(f"[ToolPlayer] Using recorded start ({cx}, {cy})")

                end_x = sub_cache.get('click_x_end')
                end_y = sub_cache.get('click_y_end')
                if end_x is not None and end_y is not None:
                    end_x, end_y = int(float(end_x)), int(float(end_y))
                    logger.info(f"[ToolPlayer] Using recorded end ({end_x}, {end_y})")
                else:
                    logger.warning(f"[ToolPlayer] Missing end coordinate for {action_type}")
                    return None

                normalized_start_x, normalized_start_y = normalize_for_mcp(cx, cy)
                normalized_end_x, normalized_end_y = normalize_for_mcp(end_x, end_y)
                # MCP swipe/drag 工具签名：start: Tuple[int,int], end: Tuple[int,int]
                mcp_args = {
                    'start': [normalized_start_x, normalized_start_y],
                    'end': [normalized_end_x, normalized_end_y]
                }
                mcp_result = self._call_mcp_tool(mcp_tool_name, mcp_args)

                if mcp_result:
                    result = json.dumps({
                        "action": action_type,
                        "start": [cx, cy],
                        "end": [end_x, end_y],
                        "normalized_start": [normalized_start_x, normalized_start_y],
                        "normalized_end": [normalized_end_x, normalized_end_y],
                        "xpath": xpath,
                        "xpath_end": xpath_end,
                        "message": f"{action_type.title()} from ({cx}, {cy}) to ({end_x}, {end_y}) using xpath"
                    })
                else:
                    result = f'{{"error": "MCP {action_type} failed from ({cx}, {cy}) to ({end_x}, {end_y})"}}'

                action = {
                    "_metadata": "do",
                    "action": self.ACTION_MAP.get(action_type, action_type.title()),
                    "log": arguments.get('message', ''),
                    "start": [cx, cy],
                    "end": [end_x, end_y]
                }
                self._report_action(action, screenshot, tool_start_time)
            else:
                normalized_x, normalized_y = normalize_for_mcp(cx, cy)
                # MCP click/double_click/long_click 工具签名：pos: Tuple[int,int]
                mcp_args = {'pos': [normalized_x, normalized_y]}
                mcp_result = self._call_mcp_tool(mcp_tool_name, mcp_args)

                if mcp_result:
                    result = json.dumps({
                        "action": action_type,
                        "x": cx,
                        "y": cy,
                        "normalized_x": normalized_x,
                        "normalized_y": normalized_y,
                        "xpath": xpath,
                        "message": f"{action_type.title()} at ({cx}, {cy}) using xpath"
                    })
                else:
                    result = f'{{"error": "MCP {action_type} failed at ({cx}, {cy})"}}'

                action = {
                    "_metadata": "do",
                    "action": self.ACTION_MAP.get(action_type, action_type.title()),
                    "log": arguments.get('message', ''),
                    "element": [cx, cy]
                }
                self._report_action(action, screenshot, tool_start_time)

            return result
        except Exception as e:
            logger.warning(f"[ToolPlayer] Cached click failed: {e}, fallback to execute")
            return None

    def _replay_text_action(
            self,
            sub_cache: Dict[str, Any],
            arguments: Dict[str, Any],
            screenshot,
            tool_start_time: datetime
    ) -> str:
        """回放文本类操作（input_text/clear_text）。

        供单步回放和 execute 多步回放中的 input_text/clear_text 子步骤复用。
        直接通过 MCP 执行文本操作，不走 xpath 定位（文本操作作用于当前焦点元素）。

        Args:
            sub_cache: 单步文本缓存，必须包含 action='input_text'/'clear_text'
            arguments: 外层工具参数（用于 log 文案）
            screenshot: 当前截图
            tool_start_time: 当前步骤起始时间（用于上报）

        Returns:
            JSON 字符串形式的结果。成功时含 action/text，失败时含 error 字段。
        """
        text_action = sub_cache.get('action')
        text = sub_cache.get('text', '')
        logger.info(
            f"[ToolPlayer]   MCP execution: action={text_action}, "
            f"text_len={len(text)}, has_text={bool(text)}"
        )

        if text_action == 'input_text' and text:
            mcp_result = self._call_mcp_tool('input_text', {'text': text})
            if mcp_result:
                result = json.dumps({
                    "action": "input_text",
                    "text": text,
                    "message": f"Input text: {text[:50]}..."
                }, ensure_ascii=False)
                action = {
                    "_metadata": "do",
                    "action": self.ACTION_MAP.get("input_text", "Type"),
                    "log": arguments.get('message', ''),
                    "element": []
                }
                self._report_action(action, screenshot, tool_start_time)
            else:
                result = '{"error": "MCP input_text failed"}'
            return result

        if text_action == 'clear_text':
            mcp_result = self._call_mcp_tool('clear_text', {})
            if mcp_result:
                result = json.dumps({
                    "action": "clear_text",
                    "message": "Cleared text"
                }, ensure_ascii=False)
                action = {
                    "_metadata": "do",
                    "action": self.ACTION_MAP.get("clear_text", "Clear Text"),
                    "log": arguments.get('message', ''),
                    "element": []
                }
                self._report_action(action, screenshot, tool_start_time)
            else:
                result = '{"error": "MCP clear_text failed"}'
            return result

        # 既不是 input_text 也不是 clear_text，交给调用方处理
        return json.dumps(
            {"error": f"Unsupported text action: {text_action}"},
            ensure_ascii=False
        )

    async def _replay_step_via_executor(
            self,
            sub_cache: Dict[str, Any],
            arguments: Dict[str, Any],
            screenshot,
            is_single_step: bool = False
    ) -> str:
        """无 xpath 的单步动作，交给执行 agent 执行这一个动作。

        根据 sub_cache 中的坐标和动作类型，构造单步指令调用执行 agent
        完成。执行 agent 会基于当前 UI 状态智能执行（而非死板按坐标点击），
        能适应分辨率/布局变化。

        Args:
            sub_cache: 单步点击缓存，use_xpath=False 或无 xpath
            arguments: 外层 execute 工具的参数（含 message 等）
            screenshot: 当前截图
            is_single_step: 是否为单步操作（click_caches 只有这一个子步骤）。
                单步时优先用外层 message（用户原始意图，最稳定）；
                多步时优先用 target_text（message 描述的是整体序列，非单步）。

        Returns:
            JSON 字符串形式的结果。
        """
        action = sub_cache.get('action', 'click')
        click_x = sub_cache.get('click_x')
        click_y = sub_cache.get('click_y')
        target_text = sub_cache.get('target_text', '')
        step_log = sub_cache.get('log', '')
        outer_message = arguments.get('message', '')

        action_map = {
            "click": "点击",
            "double_click": "双击",
            "long_click": "长按",
            "drag": "拖动",
            "swipe": "滑动",
        }
        verb = action_map.get(action, "点击")

        # 构造单步指令：
        # - 单步操作（click_caches 只有这一个）：优先用外层 message（用户原始意图，最稳定），
        #   其次用 log（该步骤的语义描述），再其次用 target_text，最后退化为坐标描述
        # - 多步操作中的子步骤：优先用 log（每个子步骤自己的语义描述，最精确），
        #   其次用 target_text，再其次用外层 message，最后退化为坐标描述
        if is_single_step:
            if outer_message:
                step_instruction = outer_message
            elif step_log:
                step_instruction = step_log
            elif target_text:
                step_instruction = f"{verb}\"{target_text}\""
            elif click_x is not None and click_y is not None:
                step_instruction = f"在坐标 ({click_x}, {click_y}) 附近执行 {action} 操作"
            else:
                return json.dumps(
                    {"error": "无法构造单步指令：缺少 target_text/log/message/坐标"},
                    ensure_ascii=False
                )
        else:
            if step_log:
                step_instruction = step_log
            elif target_text:
                step_instruction = f"{verb}\"{target_text}\""
            elif outer_message:
                step_instruction = outer_message
            elif click_x is not None and click_y is not None:
                step_instruction = f"在坐标 ({click_x}, {click_y}) 附近执行 {action} 操作"
            else:
                return json.dumps(
                    {"error": "无法构造单步指令：缺少 log/target_text/message/坐标"},
                    ensure_ascii=False
                )

        logger.info(
            f"[ToolPlayer] 无 xpath 子步骤，交给执行 agent 单步执行: {step_instruction}"
        )

        # 获取执行 agent
        executor_agent = self.executor_agent
        if not executor_agent:
            # 尝试从 agent_registry 获取
            try:
                from ..layered_agent_cli.agent_registry import agent_registry
                executor_agent = agent_registry.get_executor_agent()
            except Exception:
                executor_agent = None

        if not executor_agent:
            logger.warning("[ToolPlayer] 执行 agent 不可用，无法回放无 xpath 子步骤")
            return json.dumps(
                {"error": "执行 agent 不可用"},
                ensure_ascii=False
            )

        try:
            # 调用执行 agent 执行单步指令
            # 在独立线程中同步运行 executor_agent.run，避免阻塞 asyncio loop
            def run_sync():
                executor_agent.reset()
                run_result = executor_agent.run(step_instruction)
                return run_result, executor_agent.step_count

            run_result, steps = await asyncio.to_thread(run_sync)
            result_str = str(run_result)
            logger.info(
                f"[ToolPlayer] 执行 agent 完成: steps={steps}, result={result_str[:200]}"
            )
            # 检测执行 agent 返回结果中的失败语义关键词
            if any(keyword in result_str for keyword in self.FAILURE_KEYWORDS):
                logger.warning(
                    f"[ToolPlayer] 执行 agent 返回失败语义: {result_str[:200]}"
                )
                return json.dumps({
                    "error": f"执行 agent 返回失败语义: {result_str}",
                    "action": action,
                    "instruction": step_instruction,
                    "steps": steps,
                    "replan_required": True,
                    "failure_reason": result_str,
                    "failed_step": step_instruction
                }, ensure_ascii=False)
            return json.dumps({
                "action": action,
                "instruction": step_instruction,
                "steps": steps,
                "result": result_str,
                "message": f"无 xpath 子步骤由执行 agent 完成: {step_instruction}"
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[ToolPlayer] 执行 agent 单步执行失败: {e}")
            return json.dumps(
                {"error": f"执行 agent 单步执行失败: {str(e)}"},
                ensure_ascii=False
            )

    def _report_action(self, action: Dict[str, Any], screenshot, tool_start_time: datetime):
        """
        上报动作到报告生成器。

        只在 xpath 命中成功时调用，execute 本身会自己处理上报。
        """
        from ..reporter.reporter_types import TimeCalculate

        try:
            time_calculate_start = TimeCalculate(tool_start_time, tool_start_time)
            self.report_generator.execute_agent_do_start(
                time_calculate=time_calculate_start,
                thinking="",
                screenshot=screenshot,
                action=action,
                step_count=self._current_index + 1
            )

            post_screenshot = self.device.get_screenshot(save_to_report=True)
            tool_end_time = datetime.now()
            time_calculate_end = TimeCalculate(tool_start_time, tool_end_time)
            action_result = {"success": True, "message": ""}
            self.report_generator.execute_agent_do_end(
                time_calculate=time_calculate_end,
                screenshot=post_screenshot,
                result=type('obj', (object,), action_result),
                step_count=self._current_index + 1
            )
        except Exception as e:
            logger.warning(f"[ToolPlayer] _report_action failed: {e}")

    async def _analyze_screenshot_with_llm(self, prompt: str) -> str:
        """Analyze current screenshot with LLM and return response text."""
        try:
            screenshot = self.device.get_screenshot(save_to_report=True)
            if not screenshot or not screenshot.base64_data:
                logger.warning("[ToolPlayer] No screenshot available for LLM analysis")
                return ""

            api_version = self.config.decision_api_version if self.config else None
            api_key = self.config.decision_api_key if self.config else ""
            base_url = self.config.decision_base_url if self.config else ""
            model_name = self.config.decision_model_name if self.config else ""

            if api_version:
                client = AsyncAzureOpenAI(
                    azure_endpoint=base_url,
                    api_key=api_key,
                    api_version=api_version,
                    timeout=120,
                    max_retries=1
                )
            else:
                client = AsyncOpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    timeout=120,
                    max_retries=1
                )

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{screenshot.base64_data}"
                                    }
                                }
                            ]
                        }
                    ],
                    temperature=0.1,
                    max_tokens=500
                ),
                timeout=60
            )

            result_text = response.choices[0].message.content or ""
            logger.info(f"[ToolPlayer] LLM analysis result: {result_text[:200]}")
            return result_text

        except asyncio.TimeoutError:
            logger.error("[ToolPlayer] LLM screenshot analysis timed out")
            return ""
        except Exception as e:
            logger.error(f"[ToolPlayer] LLM screenshot analysis failed: {e}")
            return ""

    async def _retry_failed_step(self, failed_step_index: int) -> bool:
        """Retry a failed playback step."""
        try:
            if not self._current_session or failed_step_index >= len(self._current_session.recordings):
                logger.error(f"[ToolPlayer] Invalid failed_step_index: {failed_step_index}")
                return False

            original_recording = self._current_session.recordings[failed_step_index]
            tool_name = original_recording.get('tool_name', '')
            arguments = original_recording.get('arguments', {})
            click_caches = original_recording.get('click_caches')

            # 跳过无需回放的工具
            if tool_name in self.SKIP_REPLAY_TOOLS:
                logger.info(f"[ToolPlayer] 跳过重试工具: {tool_name}")
                return True

            logger.info(f"[ToolPlayer] Retrying step {failed_step_index}: {tool_name}({arguments})")

            retry_result = await self._execute_tool_async(
                tool_name, arguments, click_caches
            )

            is_success = True
            if tool_name == "execute":
                try:
                    result_data = json.loads(retry_result) if retry_result.startswith('{') else {}
                    if result_data.get('replan_required', False):
                        is_success = False
                except json.JSONDecodeError:
                    if any(keyword in retry_result for keyword in self.FAILURE_KEYWORDS):
                        is_success = False

            playback_record = {
                "order": original_recording.get('order', failed_step_index),
                "tool_name": tool_name,
                "arguments": arguments,
                "result": retry_result,
                "timestamp": original_recording.get('timestamp', ''),
                "click_caches": click_caches,
                "is_played": True,
                "is_retry": True
            }

            if failed_step_index < len(self._current_recordings):
                self._current_recordings[failed_step_index] = playback_record
            else:
                self._current_recordings.append(playback_record)

            logger.info(f"[ToolPlayer] Retry step {failed_step_index}: {'SUCCESS' if is_success else 'FAILED'}")
            return is_success

        except Exception as e:
            logger.error(f"[ToolPlayer] Retry failed step {failed_step_index} error: {e}")
            return False

    async def _is_popup_still_exists(self) -> Optional[Dict]:
        """Check if a popup still exists on screen via LLM screenshot analysis."""
        try:
            screenshot = self.device.get_screenshot(save_to_report=True)
            img_width = screenshot.width
            img_height = screenshot.height

            prompt = """请仔细分析当前屏幕截图，判断是否存在弹窗（popup/dialog/alert/对话框/弹窗/系统弹窗/广告弹窗）。

请按以下JSON格式回答（只返回JSON，不要包含其他文字）：
如果存在弹窗，请找出处理该弹窗需要点击的按钮的中心坐标（用0-1000的归一化坐标表示，0=最左边/最上边，1000=最右边/最下边）：
{
    "has_popup": true,
    "popup_type": "弹窗类型（如：隐私协议确认、系统权限弹窗、广告弹窗、更新提示、确认对话框等）",
    "action": "需要点击的按钮文本（如：同意、关闭、确定、取消、允许等）",
    "close_x": 按钮中心的X坐标（0-1000范围）,
    "close_y": 按钮中心的Y坐标（0-1000范围）
}
如果不存在弹窗：
{
    "has_popup": false
}"""

            response_text = await self._analyze_screenshot_with_llm(prompt)
            if not response_text:
                return None

            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)

                if result.get('has_popup', False):
                    close_x = result.get('close_x')
                    close_y = result.get('close_y')
                    device_x = int(close_x / 1000 * img_width) if close_x is not None else 0
                    device_y = int(close_y / 1000 * img_height) if close_y is not None else 0
                    device_x = max(0, min(device_x, img_width - 1))
                    device_y = max(0, min(device_y, img_height - 1))
                    action = result.get('action', '关闭')
                    logger.warning(f"[ToolPlayer] Popup detected: type={result.get('popup_type')}, "
                                   f"action={action}, "
                                   f"normalized ({close_x}, {close_y}) "
                                   f"-> device ({device_x}, {device_y}), "
                                   f"device={img_width}x{img_height}")
                    self._popup_stats["detected"] += 1
                    return {
                        "popup_type": result.get("popup_type", "unknown"),
                        "action": action,
                        "device_x": device_x,
                        "device_y": device_y
                    }
                else:
                    logger.info("[ToolPlayer] No popup detected on screen")
                    return None

            logger.warning("[ToolPlayer] Failed to parse popup detection response")
            return None

        except json.JSONDecodeError as e:
            logger.warning(f"[ToolPlayer] Failed to parse popup detection JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"[ToolPlayer] _is_popup_still_exists failed: {e}")
            return None

    async def _handle_unexpected_popup(self, failed_step_index: int) -> bool:
        """Detect and handle unexpected popups, then retry the failed step."""
        if not self.popup_config.enabled:
            logger.info("[ToolPlayer] Popup handling disabled, skipping")
            return False

        max_attempts = self.popup_config.max_retry_attempts
        logger.warning(
            f"[ToolPlayer] Checking for unexpected popup (step {failed_step_index}, max_attempts={max_attempts})")

        for attempt in range(max_attempts):
            popup_info = await self._is_popup_still_exists()
            if popup_info is None:
                logger.info("[ToolPlayer] No popup detected, cannot handle")
                return False

            device_x = popup_info.get('device_x')
            device_y = popup_info.get('device_y')
            action = popup_info.get('action', '关闭')

            logger.warning(f"[ToolPlayer] Attempt {attempt + 1}/{max_attempts}: Handling popup - "
                           f"type={popup_info.get('popup_type')}, "
                           f"action={action}, "
                           f"device at ({device_x}, {device_y})")

            try:
                if device_x is not None and device_y is not None:
                    await self._tap_at_coordinates(device_x, device_y)
                else:
                    logger.warning("[ToolPlayer] No close coordinates from LLM, falling back to go_back")
                    await self._execute_tool_async("go_back", {})

                await asyncio.sleep(1)

                verify_result = await self._is_popup_still_exists()
                if verify_result is None:
                    logger.warning(f"[ToolPlayer] Popup closed successfully on attempt {attempt + 1}")
                    self._popup_stats["closed"] += 1

                    retry_success = await self._retry_failed_step(failed_step_index)
                    if retry_success:
                        self._popup_stats["retry_success"] += 1
                        logger.warning(f"[ToolPlayer] Retry succeeded after popup handling")
                        return True
                    else:
                        self._popup_stats["retry_failed"] += 1
                        logger.warning(f"[ToolPlayer] Retry failed after popup handling")
                        return False
                else:
                    logger.warning(f"[ToolPlayer] Popup still exists after attempt {attempt + 1}, retrying...")

            except Exception as e:
                logger.error(f"[ToolPlayer] Failed to close popup on attempt {attempt + 1}: {e}")

        logger.warning(f"[ToolPlayer] Failed to handle popup after {max_attempts} attempts")
        return False

    async def _tap_at_coordinates(self, device_x: int, device_y: int):
        """Tap at pre-calculated device pixel coordinates."""
        try:
            logger.info(f"[ToolPlayer] Tapping at device ({device_x}, {device_y})")
            self.device.tap(device_x, device_y)

        except Exception as e:
            logger.error(f"[ToolPlayer] _tap_at_coordinates failed: {e}")
            raise

    async def _try_resolve_step_failure(self, failed_step_index: int, recording: Dict, arguments: Dict) -> str:
        """Try to resolve a step failure through popup handling.

        Returns:
            "skip" - step was a popup operation and popup is gone, skipped
            "retry_success" - unexpected popup closed and step retried successfully
            "failed" - couldn't resolve, needs replan
        """
        if not self.popup_config.enabled:
            return "failed"

        # 场景一：用一次 LLM 调用同时判断"是否是弹窗步骤"和"当前是否有弹窗"
        if self.popup_config.skip_popup_steps:
            analysis = await self._analyze_step_and_screen(arguments)
            if analysis.get("is_popup_operation") and (
                    not analysis.get("has_popup") or (analysis.get("device_x") == 0 and analysis.get("device_y") == 0)):
                await self._skip_popup_step(recording, failed_step_index)
                return "skip"

        # 场景二：检查是否有新弹窗遮挡
        handled = await self._handle_unexpected_popup(failed_step_index)
        if handled:
            return "retry_success"

        return "failed"

    async def _analyze_step_and_screen(self, arguments: Dict) -> Dict:
        """One LLM call to check if step is popup-related AND if popup exists on screen.

        Returns:
            Dict with keys: is_popup_operation, has_popup, device_x, device_y, popup_type
        """
        try:
            message_text = arguments.get('message', '') if isinstance(arguments, dict) else str(arguments)
            screenshot = self.device.get_screenshot(save_to_report=True)
            img_width = screenshot.width
            img_height = screenshot.height

            prompt = f"""请分析以下操作步骤描述和当前屏幕截图，回答两个问题。

问题1：该操作步骤是否与"关闭弹窗/对话框/弹窗广告/系统弹窗/权限申请弹窗"相关？
操作描述：{message_text}

问题2：当前屏幕截图是否存在弹窗（对话框、弹窗广告、系统权限请求、提示框等）？

请按以下JSON格式回答（只返回JSON，不要包含其他文字）：
{{
    "is_popup_operation": true或false,
    "has_popup": true或false,
    "popup_type": "如果存在弹窗，填写弹窗类型；否则填空字符串",
    "close_x": 如果存在弹窗，填写处理该弹窗需要点击的按钮的X坐标（0-1000归一化）；否则填0,
    "close_y": 如果存在弹窗，填写处理该弹窗需要点击的按钮的Y坐标（0-1000归一化）；否则填0
}}"""

            response_text = await self._analyze_screenshot_with_llm(prompt)
            if not response_text:
                return {"is_popup_operation": False, "has_popup": False,
                        "device_x": 0, "device_y": 0, "popup_type": ""}

            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)

                close_x = result.get('close_x', 0)
                close_y = result.get('close_y', 0)
                device_x = int(close_x / 1000 * img_width) if close_x else 0
                device_y = int(close_y / 1000 * img_height) if close_y else 0
                device_x = max(0, min(device_x, img_width - 1))
                device_y = max(0, min(device_y, img_height - 1))

                logger.info(f"[ToolPlayer] Step analysis: is_popup={result.get('is_popup_operation')}, "
                            f"has_popup={result.get('has_popup')}, "
                            f"popup_type={result.get('popup_type')}, "
                            f"device=({device_x}, {device_y})")
                return {
                    "is_popup_operation": result.get("is_popup_operation", False),
                    "has_popup": result.get("has_popup", False),
                    "device_x": device_x,
                    "device_y": device_y,
                    "popup_type": result.get("popup_type", "")
                }

            return {"is_popup_operation": False, "has_popup": False,
                    "device_x": 0, "device_y": 0, "popup_type": ""}

        except json.JSONDecodeError as e:
            logger.warning(f"[ToolPlayer] Failed to parse step and screen analysis JSON: {e}")
            return {"is_popup_operation": False, "has_popup": False,
                    "device_x": 0, "device_y": 0, "popup_type": ""}
        except Exception as e:
            logger.warning(f"[ToolPlayer] _analyze_step_and_screen failed: {e}")
            return {"is_popup_operation": False, "has_popup": False,
                    "device_x": 0, "device_y": 0, "popup_type": ""}

    async def _skip_popup_step(self, recording: Dict, step_index: int) -> bool:
        """Skip a popup-related step when the popup no longer exists."""
        message_text = recording.get('arguments', {}).get('message', '') if isinstance(recording.get('arguments'),
                                                                                       dict) else str(
            recording.get('arguments', ''))
        logger.info(
            f"[ToolPlayer] Skipping popup step {step_index}: LLM confirmed popup no longer exists (message: {message_text[:80]})")
        self._popup_stats["skipped"] += 1

        recording['is_played'] = True
        recording['is_skipped'] = True
        recording['result'] = '[SKIPPED] Popup no longer exists, step skipped'

        return True

    async def play_async(self) -> Dict[str, Any]:
        """Play all recorded tool calls in order."""
        if not self._current_session:
            return {"success": False, "error": "No recording loaded"}

        logger.info(f"[ToolPlayer] Starting playback: {self._current_session.total_calls} calls")

        start_time = datetime.now()
        results = []
        self._current_index = 0
        self._step_count = 0
        # 清空之前的记录，只保留回放成功的新记录
        self._current_recordings = []
        # 重置重规划标记
        self._replan_triggered = False

        # 超时管理
        task_timeout = self.config.task_timeout if self.config else 1800
        playback_start_time = datetime.now()

        def get_remaining_timeout():
            """获取剩余的超时时间（秒）"""
            elapsed = (datetime.now() - playback_start_time).total_seconds()
            return max(0, task_timeout - elapsed)

        for i, recording in enumerate(self._current_session.recordings):
            self._current_index = i
            self._step_count += 1

            if self.report_generator:
                try:
                    self.report_generator.execute_agent_step_start(step_count=self._step_count)
                except Exception as e:
                    logger.warning(f"[ToolPlayer] execute_agent_step_start failed: {e}")

            click_caches = recording.get('click_caches')
            record = ToolCallRecord(
                order=recording['order'],
                tool_name=recording['tool_name'],
                arguments=recording['arguments'],
                result=recording['result'],
                timestamp=recording['timestamp']
            )

            # 跳过无需回放的工具（如 load_skill，仅用于录制阶段获取上下文）
            if record.tool_name in self.SKIP_REPLAY_TOOLS:
                logger.info(f"[ToolPlayer] 跳过回放工具: {record.tool_name}")
                if self.report_generator:
                    try:
                        self.report_generator.execute_agent_step_end()
                    except Exception as e:
                        logger.warning(f"[ToolPlayer] execute_agent_step_end failed: {e}")
                continue

            # 检查是否已超时
            remaining = get_remaining_timeout()
            if remaining <= 0:
                logger.warning(f"[ToolPlayer] Playback timeout after {self._step_count} steps")
                return {
                    "success": False,
                    "timeout": True,
                    "task": self._current_session.task if self._current_session else "",
                    "message": f"Playback timeout after {self._step_count} steps",
                    "step_count": self._step_count,
                    "elapsed_seconds": task_timeout
                }

            # 当 run_skill_script 紧跟在 execute 之后时，等待时效性控件消失。
            # 录制时模型决策耗时长，控件已消失；回放时需模拟这一时间差，
            # 避免脚本内置的双击逻辑在控件仍可见时重复命中实际控件。
            if (i > 0
                    and record.tool_name == "run_skill_script"
                    and self._current_session.recordings[i - 1].get("tool_name") == "execute"):
                logger.info("[ToolPlayer] run_skill_script 紧跟 execute，等待5秒让时效性控件消失")
                await asyncio.sleep(5)

            # === 视频进度条拖动专用回放 ===
            # 录制时常见模式：第 N 步 execute「点击视频画面唤起进度条，获取进度条坐标...」，
            # 第 N+1 步 run_skill_script swipe_video_progress_bar.py <x3 y3 x2 y2>。
            # 回放时进度条当前位置可能与录制时不同，若沿用录制时的硬编码坐标，拖动起点会
            # 落在错误位置导致拖不到终点。因此检测到该连续两步模式时，先实际执行 execute
            # 指令获取最新进度条坐标，再用最新坐标替换下一步 swipe 脚本的参数。
            progress_bar_capture_handled = False
            if (record.tool_name == "execute"
                    and i + 1 < len(self._current_session.recordings)):
                next_recording_pb = self._current_session.recordings[i + 1]
                next_args_pb = next_recording_pb.get('arguments') or {}
                if (next_recording_pb.get('tool_name') == "run_skill_script"
                        and next_args_pb.get('script_name') == "swipe_video_progress_bar.py"
                        and self._is_progress_bar_capture_message(record.arguments.get('message', ''))):
                    logger.info(
                        "[ToolPlayer] 检测到「唤起进度条获取坐标 + swipe_video_progress_bar」"
                        "连续两步模式，实际执行 execute 获取最新进度条坐标"
                    )
                    try:
                        pb_result = await self._replay_progress_bar_capture(record.arguments)
                    except Exception as e:
                        logger.warning(
                            f"[ToolPlayer] 进度条坐标获取异常，回退到常规回放: {e}"
                        )
                        pb_result = None

                    if pb_result is not None:
                        new_args = self._build_swipe_args_from_progress_bar_result(
                            pb_result,
                            str(record.result or ''),
                            next_args_pb.get('args', '')
                        )
                        if new_args:
                            next_recording_pb['arguments']['args'] = new_args
                            logger.info(
                                f"[ToolPlayer] 已用最新进度条坐标更新下一步 swipe 参数: {new_args}"
                            )
                        else:
                            logger.warning(
                                "[ToolPlayer] 未能从 execute 结果解析进度条坐标，"
                                "下一步 swipe 将沿用录制时的原始参数"
                            )
                        result = pb_result
                        progress_bar_capture_handled = True

            try:
                if not progress_bar_capture_handled:
                    result = await self._execute_tool_async(
                        record.tool_name,
                        record.arguments,
                        click_caches
                    )

                # 记录执行结果
                playback_record = {
                    "order": record.order,
                    "tool_name": record.tool_name,
                    "arguments": record.arguments,
                    "result": result,
                    "timestamp": record.timestamp,
                    "click_caches": click_caches,
                    "is_played": True  # 标记为已回放
                }

                # Check if execute failed in playback mode
                failed_step_index = None
                popup_resolved = False
                if record.tool_name == "execute":
                    try:
                        result_data = json.loads(result) if result.startswith('{') else {}
                        if result_data.get('replan_required', False):
                            failed_step_index = len(self._current_recordings)
                            logger.warning(
                                f"[ToolPlayer] Execute failed at step {failed_step_index}: "
                                f"failure_reason={result_data.get('failure_reason')}, "
                                f"failed_step={result_data.get('failed_step')}"
                            )
                            resolve_status = await self._try_resolve_step_failure(failed_step_index, recording,
                                                                                  record.arguments)
                            if resolve_status == "skip":
                                popup_resolved = True
                                results.append({
                                    "order": record.order,
                                    "tool_name": record.tool_name,
                                    "arguments": record.arguments,
                                    "original_result": record.result,
                                    "playback_result": "[SKIPPED] Popup no longer exists, step skipped",
                                    "success": True,
                                    "skipped": True
                                })
                                logger.info(f"[ToolPlayer] #{record.order} SKIPPED (popup no longer exists)")
                            elif resolve_status == "retry_success":
                                popup_resolved = True
                                logger.warning(
                                    f"[ToolPlayer] Popup handling resolved step {failed_step_index}, continuing playback")
                                results.append({
                                    "order": record.order,
                                    "tool_name": record.tool_name,
                                    "arguments": record.arguments,
                                    "original_result": record.result,
                                    "playback_result": "[POPUP_HANDLED] Popup closed and step retried successfully",
                                    "success": True,
                                    "popup_handled": True
                                })
                            else:
                                failure_info = result_data
                                failure_info['failed_step_index'] = failed_step_index
                                await self._trigger_replan(failure_info, remaining_timeout=get_remaining_timeout())
                                return {
                                    "success": True,
                                    "replan_triggered": True,
                                    "task": self._current_session.task if self._current_session else "",
                                    "failure_info": failure_info,
                                    "message": "Playback interrupted, replan triggered"
                                }

                    except json.JSONDecodeError:
                        if any(keyword in result for keyword in self.FAILURE_KEYWORDS):
                            failed_step_index = len(self._current_recordings)
                            logger.warning(
                                f"[ToolPlayer] Execute failed (keyword detected) at step {failed_step_index}")
                            resolve_status = await self._try_resolve_step_failure(failed_step_index, recording,
                                                                                  record.arguments)
                            if resolve_status == "skip":
                                popup_resolved = True
                                results.append({
                                    "order": record.order,
                                    "tool_name": record.tool_name,
                                    "arguments": record.arguments,
                                    "original_result": record.result,
                                    "playback_result": "[SKIPPED] Popup no longer exists, step skipped",
                                    "success": True,
                                    "skipped": True
                                })
                                logger.info(f"[ToolPlayer] #{record.order} SKIPPED (popup no longer exists)")
                            elif resolve_status == "retry_success":
                                popup_resolved = True
                                logger.warning(
                                    f"[ToolPlayer] Popup handling resolved step {failed_step_index}, continuing playback")
                                results.append({
                                    "order": record.order,
                                    "tool_name": record.tool_name,
                                    "arguments": record.arguments,
                                    "original_result": record.result,
                                    "playback_result": "[POPUP_HANDLED] Popup closed and step retried successfully",
                                    "success": True,
                                    "popup_handled": True
                                })
                            else:
                                failure_info = {
                                    "replan_required": True,
                                    "result": result,
                                    "failure_reason": result,
                                    "failed_step": record.arguments.get('message', 'Unknown'),
                                    "failed_step_index": failed_step_index
                                }
                                await self._trigger_replan(failure_info, remaining_timeout=get_remaining_timeout())
                                return {
                                    "success": True,
                                    "replan_triggered": True,
                                    "task": self._current_session.task if self._current_session else "",
                                    "failure_info": failure_info,
                                    "message": "Playback interrupted, replan triggered"
                                }

                if popup_resolved:
                    if self.report_generator:
                        try:
                            self.report_generator.execute_agent_step_end()
                        except Exception as e:
                            logger.warning(f"[ToolPlayer] execute_agent_step_end failed: {e}")
                    continue

                # 如果没有触发重新规划，则追加到 _current_recordings
                if failed_step_index is None:
                    self._current_recordings.append(playback_record)

                # 对于 verify 工具，解析业务验证结果
                business_pass = True
                if record.tool_name == 'verify':
                    verify_info = self._parse_verify_result(result)
                    business_pass = verify_info['business_pass']

                results.append({
                    "order": record.order,
                    "tool_name": record.tool_name,
                    "arguments": record.arguments,
                    "original_result": record.result,
                    "playback_result": result,
                    "success": True,
                    "business_pass": business_pass
                })
                logger.info(f"[ToolPlayer] #{record.order} OK: {result[:80]}...")
            except Exception as e:
                # 对于 verify 工具，解析业务验证结果（即使工具调用失败，也要检查业务验证是否通过）
                business_pass = False
                if record.tool_name == 'verify':
                    verify_info = self._parse_verify_result(f'{{"result": false, "reason": "{str(e)}"}}')
                    business_pass = verify_info['business_pass']

                results.append({
                    "order": record.order,
                    "tool_name": record.tool_name,
                    "arguments": record.arguments,
                    "original_result": record.result,
                    "playback_result": f'{{"error": "{str(e)}"}}',
                    "success": False,
                    "error": str(e),
                    "business_pass": business_pass
                })
                logger.error(f"[ToolPlayer] #{record.order} FAILED: {e}")

            if self.report_generator:
                try:
                    self.report_generator.execute_agent_step_end()
                except Exception as e:
                    logger.warning(f"[ToolPlayer] execute_agent_step_end failed: {e}")

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        success_count = sum(1 for r in results if r['success'])
        business_pass_count = sum(1 for r in results if r.get('business_pass', r['success']))
        verify_count = sum(1 for r in results if r['tool_name'] == 'verify')
        verify_pass_count = sum(1 for r in results if r['tool_name'] == 'verify' and r.get('business_pass', False))

        summary = {
            "success": True,
            "task": self._current_session.task,
            "task_hash": self._current_session.task_hash,
            "total_calls": len(results),
            "successful_calls": success_count,
            "failed_calls": len(results) - success_count,
            "business_pass_count": business_pass_count,
            "verify_count": verify_count,
            "verify_pass_count": verify_pass_count,
            "duration_seconds": duration,
            "results": results
        }

        logger.info(f"[ToolPlayer] Done: {success_count}/{len(results)} OK in {duration:.1f}s")
        if verify_count > 0:
            logger.info(f"[ToolPlayer] Business verification: {verify_pass_count}/{verify_count} verify steps passed")

        self._last_playback_results = results

        return summary

    def play(self) -> Dict[str, Any]:
        """Sync version of play_async."""
        return asyncio.run(self.play_async())

    def _parse_verify_result(self, playback_result: str) -> Dict[str, Any]:
        """
        解析 verify 工具的 playback_result，提取业务验证结果。

        Args:
            playback_result: verify 工具返回的结果字符串

        Returns:
            包含 business_pass, verify_result, verify_reason 的字典
        """
        try:
            if playback_result.startswith('{'):
                result_data = json.loads(playback_result)
                if 'result' in result_data:
                    return {
                        "business_pass": result_data['result'] is True,
                        "verify_result": result_data['result'],
                        "verify_reason": result_data.get('reason', '')
                    }
        except json.JSONDecodeError:
            pass

        # 如果无法解析，默认认为工具调用成功但业务验证未通过
        return {
            "business_pass": False,
            "verify_result": None,
            "verify_reason": "无法解析验证结果"
        }

    @retry_on_exception(max_retries=2)
    async def judge_result(self, config) -> Dict[str, Any]:
        """
        让大模型判断回放结果是否通过。

        Args:
            config: 配置对象，包含模型信息

        Returns:
            包含判断结果的字典
        """

        if not self._current_session:
            return {"pass": False, "reason": "No recording loaded"}

        if self._last_playback_results is not None:
            results = []
            for r in self._last_playback_results:
                step_info = {
                    "step": r['order'],
                    "tool": r['tool_name'],
                    "arguments": r['arguments'],
                    "tool_call_success": r.get('success', False),
                    "playback_result": r.get('playback_result', '')
                }

                # 对于 verify 工具，区分"工具调用成功"和"业务验证通过"
                if r['tool_name'] == 'verify':
                    verify_info = self._parse_verify_result(r.get('playback_result', ''))
                    step_info.update({
                        "business_pass": verify_info['business_pass'],
                        "verify_result": verify_info['verify_result'],
                        "verify_reason": verify_info['verify_reason']
                    })
                else:
                    step_info["business_pass"] = r.get('success', False)

                results.append(step_info)
        else:
            results = [
                {
                    "step": recording['order'],
                    "tool": recording['tool_name'],
                    "arguments": recording['arguments'],
                    "playback_result": "N/A (playback not executed)",
                    "tool_call_success": False,
                    "business_pass": False
                }
                for recording in self._current_session.recordings
            ]

        task_info = self._current_session.task
        results_text = json.dumps(results, ensure_ascii=False, indent=2)

        judge_prompt = f"""## 任务信息
任务描述: {task_info}

## 回放结果详情
{results_text}

## 字段说明
- tool_call_success: 工具调用是否成功（是否正常执行，无异常）
- business_pass: 业务验证是否通过（是否符合预期结果）
- verify_result: verify 工具的业务验证结果（true/false）
- verify_reason: verify 工具的验证理由
- playback_result: 回放时的实际结果

## 评审要求
请仔细分析每个步骤的执行情况，特别注意：
1. **工具调用成功 ≠ 业务验证通过**
   - 工具调用成功只表示工具正常执行，没有抛出异常
   - 对于 verify 工具，必须检查 business_pass 和 verify_result 字段
   - 业务验证通过才表示实际结果符合预期

2. **判断标准**：
   - 如果是 verify 工具：以 business_pass 为准
   - 如果是其他工具（execute 等）：以 tool_call_success 为准

3. 请按以下格式输出评审结果：

### 步骤执行详情
请逐个描述每个步骤的执行情况：
- **步骤1**: [工具名称] - [执行动作描述] - 工具调用: [成功/失败] - 业务验证: [通过/失败] - [详细说明]
- **步骤2**: [工具名称] - [执行动作描述] - 工具调用: [成功/失败] - 业务验证: [通过/失败] - [详细说明]
...（以此类推）

### 执行摘要
总共 [总数] 个步骤，工具调用成功 [工具成功数]，业务验证通过 [验证通过数]。

### 任务判断
**任务结果: 通过/不通过**

### 判断理由
[详细说明为什么任务通过或不通过，包括：]
1. 每个步骤的工具调用是否成功
2. 每个步骤的业务验证是否通过
3. 关键操作是否成功完成
4. 最终目标是否达成
5. 如果失败，具体原因是什么
6. **注意**关注最终verify结果，过程中业务失败不一定导致任务不通过，需要综合考虑

请确保输出完整、详细的评审报告。"""

        try:
            api_version = config.decision_api_version or config.verify_api_version
            api_key = config.decision_api_key or config.verify_api_key or config.execute_api_key or ""
            base_url = config.decision_base_url or config.verify_base_url or config.execute_base_url or ""

            if api_version:
                client = AsyncAzureOpenAI(
                    azure_endpoint=base_url,
                    api_key=api_key,
                    api_version=api_version,
                    timeout=300,
                    max_retries=2
                )
            else:
                client = AsyncOpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    timeout=300,
                    max_retries=2
                )

            model_name = config.decision_model_name or config.verify_model_name or "glm-4"
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "你是一个测试结果评审专家，负责判断自动化测试回放结果是否通过。"},
                    {"role": "user", "content": judge_prompt}
                ],
                temperature=0.1,
                max_tokens=4000
            )

            judge_result = response.choices[0].message.content

            pass_marker = "任务结果: 通过" in judge_result
            fail_marker = "任务结果: 不通过" in judge_result

            return {
                "pass": pass_marker,
                "fail": fail_marker,
                "reason": judge_result,
                "model_used": model_name
            }

        except Exception as e:
            logger.error(f"[ToolPlayer] Judge failed: {e}")
            return {
                "pass": False,
                "reason": f"Judge error: {str(e)}",
                "model_used": model_name if 'model_name' in dir() else "unknown"
            }

    def get_session(self) -> Optional[RecordingSession]:
        return self._current_session

    def get_total_steps(self) -> int:
        return self._current_session.total_calls if self._current_session else 0

    def get_current_step(self) -> int:
        return self._current_index

    def _get_driver(self):
        """Get UiDriver from device or executor_agent."""
        if hasattr(self.device, 'driver') and self.device.driver:
            return self.device.driver
        if self.executor_agent and hasattr(self.executor_agent, 'device'):
            device = self.executor_agent.device
            if hasattr(device, 'driver'):
                return device.driver
        return None

    @staticmethod
    def _parse_bounds_center(bounds: Optional[str]) -> Optional[tuple[int, int]]:
        """Parse '[x1,y1][x2,y2]' bounds and return center point."""
        if not bounds:
            return None
        match = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', str(bounds))
        if not match:
            return None
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2

    @staticmethod
    def _normalize_cached_point(x: Any, y: Any) -> Optional[tuple[int, int]]:
        if x is None or y is None:
            return None
        try:
            return int(float(x)), int(float(y))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_component_center(component) -> Optional[tuple[int, int]]:
        if not component:
            return None
        try:
            center = component.getBoundsCenter()
            return int(center.X), int(center.Y)
        except Exception as e:
            logger.warning(f"[ToolPlayer] Failed to get component center: {e}")
            return None

    def _find_best_component_by_xpath(
            self,
            driver,
            xpath: str,
            bounds: Optional[str] = None,
            fallback_x: Any = None,
            fallback_y: Any = None,
            label: str = ""
    ):
        """Find xpath candidates and choose the one nearest to cached bounds or coordinate."""
        locator = BY.xpath(xpath)
        candidates = []

        if hasattr(driver, 'find_components'):
            try:
                found = driver.find_components(locator, 0)
                if isinstance(found, (list, tuple)):
                    candidates.extend(item for item in found if item)
                elif found:
                    candidates.append(found)
            except Exception as e:
                logger.warning(f"[ToolPlayer] find_components failed for {label or 'component'} xpath: {e}")

        if not candidates:
            component = driver.find_component(locator, 0)
            if component:
                candidates.append(component)

        if not candidates:
            return None

        target_center = self._parse_bounds_center(bounds) or self._normalize_cached_point(fallback_x, fallback_y)
        if len(candidates) == 1 or not target_center:
            if len(candidates) > 1:
                logger.info(
                    f"[ToolPlayer] XPath matched {len(candidates)} components, "
                    f"but no cached target for {label or 'component'}; using first"
                )
            return candidates[0]

        def distance_to_target(component) -> float:
            center = self._get_component_center(component)
            if not center:
                return float('inf')
            return (center[0] - target_center[0]) ** 2 + (center[1] - target_center[1]) ** 2

        best_component = min(candidates, key=distance_to_target)
        best_center = self._get_component_center(best_component)
        logger.info(
            f"[ToolPlayer] XPath matched {len(candidates)} components for {label or 'component'}, "
            f"target_center={target_center}, selected_center={best_center}"
        )
        return best_component

    @property
    def last_playback_results(self):
        return self._last_playback_results

    def _call_mcp_tool(self, tool_name: str, args: dict) -> Optional[str]:
        """
        通过 MCP 调用工具

        Args:
            tool_name: 工具名称 (e.g., 'click', 'double_click', 'long_click')
            args: 工具参数字典 (e.g., {'x': 500, 'y': 500})

        Returns:
            成功时返回 JSON 字符串结果，失败时返回 None
        """
        try:
            if not self.executor_agent or not hasattr(self.executor_agent, '_mcp_extension'):
                logger.error(f"[ToolPlayer] executor_agent 或 _mcp_extension 不可用")
                return None

            mcp_ext = self.executor_agent._mcp_extension
            if not mcp_ext or not hasattr(mcp_ext, 'call_tool'):
                logger.error(f"[ToolPlayer] _mcp_extension 不可用")
                return None

            logger.info(f"[ToolPlayer] MCP: {tool_name}({args})")
            result = mcp_ext.call_tool(tool_name, args)

            if result.success:
                return result.output
            else:
                logger.error(f"[ToolPlayer] MCP {tool_name} failed: {result.error_msg or result.output}")
                return None

        except Exception as e:
            logger.error(f"[ToolPlayer] MCP {tool_name} exception: {e}")
            return None
