"""Report generator for execution tracking."""

import os
import json
import base64
import re
import math
import time
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from openai.types.responses import ResponseReasoningItem, ResponseFunctionToolCall

from .reporter_abs import ReporterAbs
from .reporter_types import ReportEvent, EventType, Step
from ..logger import logger
from ..storage import output_path


class ReportGenerator(ReporterAbs):
    """测试执行报告生成器，继承自 ReporterAbs 抽象基类。"""

    def __init__(self, task: str, task_name: str, output_dir: Optional[str] = None):
        """
        Initialize report generator.

        Args:
            output_dir: Managed output directory. If None, uses the current runner's reports directory.
        """
        if output_dir:
            self.base_output_dir = output_path(output_dir)
            self.use_timestamp_dir = False
        else:
            self.base_output_dir = output_path(default='reports')
            self.use_timestamp_dir = True

        self.base_output_dir.mkdir(parents=True, exist_ok=True)

        self.events: List[ReportEvent] = []
        self.task: str = ""
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.report_dir: Optional[Path] = None
        self.screenshot_dir: Optional[Path] = None
        self.video_dir: Optional[Path] = None
        self.layout_dir: Optional[Path] = None
        self.status: Optional[str] = None
        self.test_case: str = ""
        self.total_tokens: dict[str, int] = {"total": 0}
        self.set_test_case(task_name)
        self.initialize_report_dir()
        self.step_content: list[Step] = []
        self.set_task(task)

    # ==================== 实现 ReporterAbs 抽象方法 ====================

    def task_start(self, *args, **kwargs) -> None:
        """任务开始事件"""
        """Mark task start time."""
        self.start_time = datetime.now()
        self.add_event(ReportEvent(
            event_type=EventType.TASK_START,
            content=f"Task started: {self.task}"
        ))

    def task_end(self, *args, **kwargs) -> None:
        """任务结束事件"""
        task_result = kwargs.get("task_result", "")
        self.end_task(task_result)
        # Generate and save reports
        logger.info("\nGenerating execution reports...")
        saved_files = self.save_all()
        logger.info("Reports saved:")
        for format_name, filepath in saved_files.items():
            absolute_path = os.path.abspath(filepath).replace('\\', '/')
            logger.info(f"  - {format_name.upper()}: file://{absolute_path}")

    def planner_agent_start(self, *args, **kwargs) -> None:
        """决策代理启动事件"""
        agent = kwargs.get("agent")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.add_event(ReportEvent(
            event_type=EventType.PLANNER_START,
            content=f"[{current_time}] Agent {agent.name} started"
        ))

    def planner_agent_end(self, *args, **kwargs) -> None:
        """决策代理结束事件"""
        agent = kwargs.get("agent")
        output = kwargs.get("output")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.add_event(ReportEvent(
            event_type=EventType.PLANNER_END,
            content=f"[{current_time}] Agent {agent.name} finished",
            data={"output": str(output)}
        ))

    def planner_llm_start(self, *args, **kwargs) -> None:
        """LLM 调用开始事件"""
        turn_count = kwargs.get("turn_count")
        screenshot = kwargs.get("screenshot")
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.add_event(ReportEvent(
            event_type=EventType.PLANNER_OBSERVATION,
            content=f"[{current_time}] Current Screen Observation",
            screenshot_path=screenshot.screenshot_path,
            step_number=turn_count + 1
        ))
        step = Step(
            index=len(self.step_content),
            step_type="planner",
            screenshot_path=screenshot.screenshot_path,
            timestamp=time.time()
        )
        self.step_content.append(step)

    def planner_llm_end(self, *args, **kwargs) -> None:
        """LLM 调用结束事件"""
        response = kwargs.get("response")
        agent = kwargs.get("agent")
        turn_count = kwargs.get("turn_count")
        time_calculate = kwargs.get("time_calculate")
        current_time = time_calculate.end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        duration = time_calculate.duration
        # 2. 解析并打印 Reasoning（思维链）
        summary_text = ""
        for item in response.output:
            if isinstance(item, ResponseReasoningItem):
                summary_text = ""
                for summary in item.summary:
                    if hasattr(summary, 'text'):
                        summary_text = summary.text
                        break
                self.add_event(ReportEvent(
                    event_type=EventType.PLANNER_THINKING,
                    content=f"[{current_time}] [Duration: {duration:.2f}s] {summary_text}",
                    screenshot_path=None,
                    step_number=turn_count,
                    data={"duration_seconds": duration}
                ))

        summary_title = "规划Agent任务总结"
        # 3. 解析并打印工具调用
        for item in response.output:
            if isinstance(item, ResponseFunctionToolCall):
                try:
                    args = json.loads(item.arguments)
                    if item.name == "execute":
                        tool_args = json.loads(item.arguments)
                        message = tool_args.get("message", "")
                        summary_title = f"调用执行Agent执行: {message}"
                    else:
                        summary_title = f"调用{item.name}工具, args: {args}"
                    self.add_event(ReportEvent(
                        event_type=EventType.PLANNER_TOOL_CALL,
                        content=f"[{current_time}] Called tool: {item.name}",
                        data={"tool_name": item.name, "arguments": args, "duration_seconds": duration},
                        screenshot_path=None,
                        step_number=turn_count
                    ))
                except json.JSONDecodeError:
                    logger.warning(f"[{agent.name}] Failed to parse tool arguments: {item.arguments}")

        if response.usage:
            self.add_token_usage({
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens
            }, source="Planner")

        self.step_content[-1].title = summary_title
        self.step_content[-1].desc = summary_text

    def planner_tools_start(self, *args, **kwargs) -> None:
        """工具调用开始事件"""
        tool = kwargs.get("tool")
        screenshot = kwargs.get("screenshot")
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # Extract tool arguments for visualization
        event_data = {"tool_name": tool.name}

        self.add_event(ReportEvent(
            event_type=EventType.MCP_TOOL_START,
            content=f"[{current_time}] Starting tool: {tool.name}",
            data=event_data,
            screenshot_path=screenshot.screenshot_path
        ))

        step = Step(
            index=len(self.step_content),
            step_type='tool_start',
            screenshot_path=screenshot.screenshot_path,
            timestamp=time.time(),
            title=f"调用{tool.name}工具",
        )

        self.step_content.append(step)

    def planner_tools_end(self, *args, **kwargs) -> None:
        """工具调用结束事件"""
        screenshot = kwargs.get("screenshot")
        tool = kwargs.get("tool")
        result = kwargs.get("result")
        time_calculate = kwargs.get("time_calculate")
        duration = time_calculate.duration
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # Parse result if it's JSON to extract action data for visualization
        event_data = {"tool_name": tool.name, "result": result, "duration_seconds": duration}
        try:
            parsed_result = json.loads(result)
            if isinstance(parsed_result, dict):
                event_data.update(parsed_result)
        except json.JSONDecodeError:
            pass

        self.add_event(ReportEvent(
            event_type=EventType.MCP_TOOL_END,
            content=f"[{current_time}] [Duration: {duration:.2f}s] Tool {tool.name} completed",
            data=event_data,
            screenshot_path=screenshot.screenshot_path
        ))
        step = Step(
            index=len(self.step_content),
            step_type='tool_end',
            screenshot_path=screenshot.screenshot_path,
            timestamp=time.time(),
            title=f"结束{tool.name}工具调用",
            desc=result
        )

        self.step_content.append(step)

    def execute_agent_step_start(self, *args, **kwargs) -> None:
        """执行步骤开始事件"""
        step_count = kwargs.get("step_count")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.add_event(ReportEvent(
            event_type=EventType.GLM_STEP_START,
            content=f"[{current_time}] Step {step_count} started",
            step_number=step_count
        ))

    def execute_agent_do_start(self, *args, **kwargs) -> None:
        """执行动作开始事件"""
        time_calculate = kwargs.get("time_calculate")
        thinking = kwargs.get("thinking")
        screenshot = kwargs.get("screenshot")
        action = kwargs.get("action")
        step_count = kwargs.get("step_count")
        llm_duration_str = f"{time_calculate.duration:.2f}s"
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        metadata = action.get("_metadata", "")
        if metadata == "finish":
            title = action.get("message", "")
        else:
            title = action.get("log", "")

        self.add_event(ReportEvent(
            event_type=EventType.GLM_THINKING,
            content=f"[{current_time}] [Duration: {llm_duration_str}] {thinking}",
            step_number=step_count,
            data={"duration_seconds": time_calculate.duration}
        ))

        self.add_event(ReportEvent(
            event_type=EventType.GLM_ACTION,
            content=f"[{current_time}] Action: {json.dumps(action, ensure_ascii=False)}",
            data={
                "action": action,
                "screen_width": screenshot.width,
                "screen_height": screenshot.height
            },
            screenshot_path=screenshot.screenshot_path,
            step_number=step_count
        ))

        step = Step(
            index=len(self.step_content),
            step_type='execute_agent_start',
            screenshot_path=screenshot.screenshot_path,
            timestamp=time_calculate.start_time.timestamp(),
            title=title,
            desc=thinking
        )
        self.step_content.append(step)

    def execute_agent_do_end(self, *args, **kwargs) -> None:
        """执行动作结束事件"""
        time_calculate = kwargs.get("time_calculate")
        result = kwargs.get("result")
        screenshot = kwargs.get("screenshot")
        step_count = kwargs.get("step_count")
        action_duration_str = f"{time_calculate.duration:.2f}s"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.add_event(ReportEvent(
            event_type=EventType.GLM_STEP_END,
            content=f"[{current_time}] [Duration: {action_duration_str}] Step {step_count} completed",
            data={"result": result.message, "success": result.success, "duration_seconds": time_calculate.duration},
            screenshot_path=screenshot.screenshot_path,
            step_number=step_count
        ))

        step = Step(
            index=len(self.step_content),
            step_type='execute_agent_end',
            screenshot_path=screenshot.screenshot_path,
            timestamp=time_calculate.end_time.timestamp(),
            title="动作执行结束"
        )
        self.step_content.append(step)

    def execute_agent_step_end(self, *args, **kwargs) -> None:
        """执行步骤结束事件"""
        pass

    def token_usage(self, *args, **kwargs) -> None:
        """token 统计事件"""
        usage = kwargs.get("usage", {})
        source = kwargs.get("source", "Unknown")
        self.add_token_usage(usage, source)

    def verify_start(self, *args, **kwargs) -> None:
        pass

    def verify_end(self, *args, **kwargs) -> None:
        pass

    # ==================== 原有方法 ====================

    def add_token_usage(self, usage: dict, source: str = "Unknown") -> None:
        """Accumulate token usage."""
        if usage and "total_tokens" in usage:
            total = usage["total_tokens"]
            self.total_tokens["total"] += total

            if source not in self.total_tokens:
                self.total_tokens[source] = 0
            self.total_tokens[source] += total

    def add_event(self, event: ReportEvent) -> None:
        """Add an event to the timeline."""
        self.events.append(event)

    def set_task(self, task: str) -> None:
        """Set the task."""
        self.task = task
        self.step_content.append(
            Step(index=0, step_type="task", title=task, desc=task, timestamp=time.time())
        )

    def set_test_case(self, test_case: str) -> None:
        """Set the test case name."""
        self.test_case = test_case

    def end_task(self, result: str) -> None:
        """Mark task end time."""
        self.end_time = datetime.now()

        # Determine status based on result content
        if result.startswith("Error:"):
            self.status = "FAIL"
        else:
            # Regex for Chinese task result
            match = re.search(r"结果\s*[:：]\s*(不?通过)", result)
            if match:
                self.status = "PASS" if match.group(1) == "通过" else "FAIL"
            else:
                self.status = "UNKNOWN"

        self.add_event(ReportEvent(
            event_type=EventType.TASK_END,
            content=f"Task completed: {result}"
        ))

    def save_screenshot(self, base64_data: str, layout_data: str = "", prefix: str = "screenshot") -> str:
        """
        Save screenshot to report directory.

        Args:
            base64_data: Base64 encoded image data
            layout_data: str layout
            prefix: Prefix for filename

        Returns:
            Path to saved screenshot
        """
        if self.screenshot_dir is None:
            raise RuntimeError("Screenshot directory not initialized. Call save_all() first or set report directory.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}_{timestamp}.jpeg"
        filepath = output_path(self.screenshot_dir / filename, boundary=self.screenshot_dir)

        image_data = base64.b64decode(base64_data)
        with open(filepath, "wb") as f:
            f.write(image_data)

        layout_filepath = output_path(self.layout_dir / f"{prefix}_{timestamp}.json", boundary=self.layout_dir)
        with open(layout_filepath, "w", encoding="utf-8") as f:
            f.write(layout_data)

        return str(filepath)

    def generate_html(self) -> str:
        """Generate HTML report."""
        events_data = [event.to_dict() for event in self.events]

        status_badge = ""
        if self.status == "PASS":
            status_badge = '<span class="status-badge status-pass">PASS</span>'
        elif self.status == "FAIL":
            status_badge = '<span class="status-badge status-fail">FAIL</span>'
        elif self.status == "UNKNOWN":
            status_badge = '<span class="status-badge status-unknown">UNKNOWN</span>'

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>执行报告 - {self.task}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .meta {{
            background-color: #f9f9f9;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .meta-item {{
            margin: 5px 0;
            color: #666;
        }}
        .timeline {{
            margin-top: 30px;
        }}
        .event {{
            margin-bottom: 20px;
            padding: 15px;
            border-left: 4px solid #ddd;
            background-color: #fafafa;
            border-radius: 0 5px 5px 0;
        }}
        .event.task {{
            border-left-color: #607D8B;
            background-color: #ECEFF1;
        }}
        .event.planner {{
            border-left-color: #2196F3;
            background-color: #E3F2FD;
        }}
        .event.mcp {{
            border-left-color: #FF9800;
            background-color: #FFF3E0;
        }}
        .event.glm {{
            border-left-color: #4CAF50;
            background-color: #E8F5E9;
        }}
        .event.screenshot {{
            border-left-color: #9C27B0;
            background-color: #F3E5F5;
        }}
        .event-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .event-type {{
            font-weight: bold;
            text-transform: uppercase;
            font-size: 12px;
            padding: 3px 8px;
            border-radius: 3px;
            color: white;
        }}
        .event-type.planner {{ background-color: #2196F3; }}
        .event-type.mcp {{ background-color: #FF9800; }}
        .event-type.glm {{ background-color: #4CAF50; }}
        .event-type.screenshot {{ background-color: #9C27B0; }}
        .event-type.task {{ background-color: #607D8B; }}
        .event-time {{
            color: #999;
            font-size: 12px;
        }}
        .event-content {{
            margin: 10px 0;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        .event-data {{
            background-color: rgba(0,0,0,0.05);
            padding: 10px;
            border-radius: 5px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            overflow-x: auto;
        }}
        .screenshot-container {{
            margin: 15px auto;
            border: 1px solid #ddd;
            border-radius: 8px;
            overflow: hidden;
            background-color: white;
            display: block; /* Changed back to block */
            position: relative; /* Context for markers */
            width: fit-content; /* Ensure width fits the content */
            max-width: 100%; /* Prevent overflow */
        }}
        .screenshot-label {{
            background-color: #f0f0f0;
            padding: 8px 12px;
            font-size: 13px;
            font-weight: 500;
            color: #555;
            border-bottom: 1px solid #ddd;
        }}
        .screenshot-img {{
            display: block;
            width: auto;
            height: auto;
            max-width: 100%;
            max-height: 600px;
            object-fit: contain;
        }}
        .click-marker {{
            position: absolute;
            width: 20px;
            height: 20px;
            background-color: rgba(255, 0, 0, 0.6);
            border: 2px solid white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            z-index: 10;
            pointer-events: none;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        .click-marker::before {{
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 4px;
            height: 4px;
            background-color: white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
        }}
        .double-tap-marker {{
            position: absolute;
            width: 24px;
            height: 24px;
            background-color: rgba(33, 150, 243, 0.6);
            border: 2px solid white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            z-index: 10;
            pointer-events: none;
            box-shadow: 0 0 0 4px rgba(33, 150, 243, 0.3);
        }}
        .double-tap-marker::before {{
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 4px;
            height: 4px;
            background-color: white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
        }}
        .long-press-marker {{
            position: absolute;
            width: 30px;
            height: 30px;
            background-color: rgba(156, 39, 176, 0.6);
            border: 2px solid white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            z-index: 10;
            pointer-events: none;
            box-shadow: 0 0 10px rgba(156, 39, 176, 0.5);
        }}
        .long-press-marker::before {{
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 6px;
            height: 6px;
            background-color: white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
        }}
        .swipe-arrow {{
            position: absolute;
            width: 4px;
            height: 60px;
            background-color: rgba(33, 150, 243, 0.8);
            z-index: 9;
            pointer-events: none;
            transform-origin: top center;
            border-radius: 2px;
        }}
        .swipe-arrow::after {{
            content: '';
            position: absolute;
            bottom: -10px;
            left: 50%;
            transform: translateX(-50%);
            border-left: 6px solid transparent;
            border-right: 6px solid transparent;
            border-top: 10px solid rgba(33, 150, 243, 0.8);
        }}
        .drag-arrow {{
            position: absolute;
            width: 4px;
            height: 60px;
            background-color: rgba(255, 152, 0, 0.8);
            z-index: 9;
            pointer-events: none;
            transform-origin: top center;
            border-radius: 2px;
        }}
        .drag-arrow::after {{
            content: '';
            position: absolute;
            bottom: -10px;
            left: 50%;
            transform: translateX(-50%);
            border-left: 6px solid transparent;
            border-right: 6px solid transparent;
            border-top: 10px solid rgba(255, 152, 0, 0.8);
        }}
        .pinch-container {{
            position: absolute;
            z-index: 9;
            pointer-events: none;
        }}
        .pinch-point {{
            width: 16px;
            height: 16px;
            background-color: rgba(156, 39, 176, 0.7);
            border: 2px solid white;
            border-radius: 50%;
            position: absolute;
            transform: translate(-50%, -50%);
        }}
        .pinch-line {{
            position: absolute;
            height: 2px;
            background-color: rgba(156, 39, 176, 0.5);
            transform-origin: left center;
        }}
        .step-badge {{
            display: inline-block;
            background-color: #607D8B;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            margin-left: 10px;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 15px;
            color: white;
            font-weight: bold;
            font-size: 12px;
            text-transform: uppercase;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            margin-left: 10px;
            vertical-align: middle;
        }}
        .status-pass {{
            background-color: #4CAF50;
        }}
        .status-fail {{
            background-color: #F44336;
        }}
        .status-unknown {{
            background-color: #9E9E9E;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 执行报告</h1>
        <div class="meta">
            <div class="meta-item"><strong>测试用例:</strong> {self.test_case}</div>
            <div class="meta-item"><strong>任务:</strong> {self.task}</div>
            <div class="meta-item"><strong>开始时间:</strong> {self.start_time.isoformat() if self.start_time else 'N/A'}</div>
            <div class="meta-item"><strong>结束时间:</strong> {self.end_time.isoformat() if self.end_time else 'N/A'}</div>
            <div class="meta-item">
                <strong>Token消耗:</strong> {self.total_tokens.get('total', 0)}
                <span style="font-size: 0.9em; color: #888;">
                    ({', '.join([f"{k}: {v}" for k, v in self.total_tokens.items() if k != 'total'])})
                </span>
            </div>
            <div class="meta-item"><strong>执行结果:</strong> {status_badge}</div>
            <div class="meta-item"><strong>总事件数:</strong> {len(self.events)}</div>
        </div>
        <div class="timeline">
"""

        for event in self.events:
            event_class = event.event_type.value.split('_')[0]
            html_content += f"""
            <div class="event {event_class}">
                <div class="event-header">
                    <span class="event-type {event_class}">{event.event_type.value}</span>
                    {f'<span class="step-badge">Step {event.step_number}</span>' if event.step_number else ''}
                    <span class="event-time">{event.timestamp.strftime('%H:%M:%S.%f')[:-3]}</span>
                </div>
                <div class="event-content">{event.content}</div>
"""

            if event.data:
                html_content += f"""
                <div class="event-data">{json.dumps(event.data, ensure_ascii=False, indent=2)}</div>
"""

            if event.screenshot_path:
                filename = os.path.basename(event.screenshot_path)
                marker_html = ""

                # Check for click coordinates in GLM_ACTION
                if event.event_type == EventType.GLM_ACTION and event.data and "action" in event.data:
                    action = event.data["action"]
                    screen_width = event.data.get("screen_width")
                    screen_height = event.data.get("screen_height")

                    if screen_width and screen_height:
                        action_name = action.get("action")

                        if action_name in ["Tap", "tap", "click"]:
                            element = action.get("element")
                            if element and isinstance(element, list) and len(element) == 2:
                                x, y = element
                                left_pct = (x / screen_width) * 100
                                top_pct = (y / screen_height) * 100
                                marker_html = f'<div class="click-marker" style="left: {left_pct}%; top: {top_pct}%;" title="Tap: {x},{y}"></div>'

                        elif action_name in ["Double Tap", "double_tap"]:
                            element = action.get("element")
                            if element and isinstance(element, list) and len(element) == 2:
                                x, y = element
                                left_pct = (x / screen_width) * 100
                                top_pct = (y / screen_height) * 100
                                marker_html = f'<div class="double-tap-marker" style="left: {left_pct}%; top: {top_pct}%;" title="Double Tap: {x},{y}"></div>'

                        elif action_name in ["Long Press", "long_press"]:
                            element = action.get("element")
                            if element and isinstance(element, list) and len(element) == 2:
                                x, y = element
                                left_pct = (x / screen_width) * 100
                                top_pct = (y / screen_height) * 100
                                marker_html = f'<div class="long-press-marker" style="left: {left_pct}%; top: {top_pct}%;" title="Long Press: {x},{y}"></div>'

                        elif action_name in ["Swipe", "swipe"]:
                            start = action.get("start")
                            end = action.get("end")
                            if start and end:
                                sx, sy = start
                                ex, ey = end
                                sl_pct = (sx / screen_width) * 100
                                st_pct = (sy / screen_height) * 100
                                el_pct = (ex / screen_width) * 100
                                et_pct = (ey / screen_height) * 100
                                dx = ex - sx
                                dy = ey - sy
                                angle = math.degrees(math.atan2(dy, dx))
                                # 计算箭头长度（像素距离转换为相对于 60px 基准的缩放比例）
                                distance = math.sqrt(dx * dx + dy * dy)
                                marker_html = (
                                    f'<div class="click-marker" style="left: {sl_pct}%; top: {st_pct}%; background-color: rgba(0,255,0,0.7);" title="Swipe Start: {sx},{sy}"></div>'
                                    f'<div class="click-marker" style="left: {el_pct}%; top: {et_pct}%;" title="Swipe End: {ex},{ey}"></div>'
                                    f'<div class="swipe-arrow" style="left: {sl_pct}%; top: {st_pct}%; transform: rotate({angle}deg) scaleY({max(0.1, distance / 60)});"></div>'
                                )

                        elif action_name in ["Drag", "drag"]:
                            start = action.get("start")
                            end = action.get("end")
                            if start and end:
                                sx, sy = start
                                ex, ey = end
                                sl_pct = (sx / screen_width) * 100
                                st_pct = (sy / screen_height) * 100
                                el_pct = (ex / screen_width) * 100
                                et_pct = (ey / screen_height) * 100
                                dx = ex - sx
                                dy = ey - sy
                                angle = math.degrees(math.atan2(dy, dx))
                                # 计算箭头长度（像素距离转换为相对于 60px 基准的缩放比例）
                                distance = math.sqrt(dx * dx + dy * dy)
                                marker_html = (
                                    f'<div class="click-marker" style="left: {sl_pct}%; top: {st_pct}%; background-color: rgba(255,152,0,0.7);" title="Drag Start: {sx},{sy}"></div>'
                                    f'<div class="click-marker" style="left: {el_pct}%; top: {et_pct}%; background-color: rgba(255,152,0,0.7);" title="Drag End: {ex},{ey}"></div>'
                                    f'<div class="drag-arrow" style="left: {sl_pct}%; top: {st_pct}%; transform: rotate({angle}deg) scaleY({max(0.1, distance / 60)});"></div>'
                                )

                        elif action_name in ["Pinch In", "pinch_in", "Pinch Out", "pinch_out"]:
                            rect = action.get("rect")
                            if rect and isinstance(rect, list) and len(rect) == 4:
                                left, top, right, bottom = rect
                                left_pct = (left / screen_width) * 100
                                top_pct = (top / screen_height) * 100
                                right_pct = (right / screen_width) * 100
                                bottom_pct = (bottom / screen_height) * 100
                                center_x = ((left + right) / 2 / screen_width) * 100
                                center_y = ((top + bottom) / 2 / screen_height) * 100

                                pinch_direction = "缩小" if action_name in ["Pinch In", "pinch_in"] else "放大"
                                direction = action.get("direction", "diagonal")

                                if direction == "horizontal":
                                    marker_html = (
                                        f'<div class="pinch-container" style="left: {left_pct}%; top: {top_pct}%; width: {right_pct - left_pct}%; height: {bottom_pct - top_pct}%;">'
                                        f'<div class="pinch-point" style="left: 0%; top: 50%;" title="左手指起始位置"></div>'
                                        f'<div class="pinch-point" style="left: 100%; top: 50%;" title="右手指起始位置"></div>'
                                        f'<div class="pinch-line" style="left: 10%; top: 50%; width: 80%;"></div>'
                                        f'</div>'
                                        f'<div class="screenshot-label" style="position: absolute; left: {center_x}%; top: {center_y}%; transform: translate(-50%, -50%); background-color: rgba(156,39,176,0.8); color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px;">Pinch {pinch_direction} (水平)</div>'
                                    )
                                else:
                                    marker_html = (
                                        f'<div class="pinch-container" style="left: {left_pct}%; top: {top_pct}%; width: {right_pct - left_pct}%; height: {bottom_pct - top_pct}%;">'
                                        f'<div class="pinch-point" style="left: 0%; top: 0%;" title="左上手指起始位置"></div>'
                                        f'<div class="pinch-point" style="left: 100%; top: 100%;" title="右下手指起始位置"></div>'
                                        f'<div class="pinch-line" style="left: 10%; top: 10%; width: 80%; transform: rotate(45deg);"></div>'
                                        f'</div>'
                                        f'<div class="screenshot-label" style="position: absolute; left: {center_x}%; top: {center_y}%; transform: translate(-50%, -50%); background-color: rgba(156,39,176,0.8); color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px;">Pinch {pinch_direction} (对角)</div>'
                                    )

                html_content += f"""
                <div class="screenshot-container">
                    <div class="screenshot-label">📸 截图</div>
                    <div style="position: relative;">
                        <img class="screenshot-img" src="screenPath/{filename}" alt="Screenshot" loading="lazy">
                        {marker_html}
                    </div>
                </div>
"""

            html_content += """
            </div>
"""

        html_content += """
        </div>
    </div>
</body>
</html>
"""
        return html_content

    def generate_markdown(self) -> str:
        """Generate Markdown report."""
        md_content = f"""# 执行报告

## 任务信息
- **测试用例**: {self.test_case}
- **任务名称**: {self.task}
- **开始时间**: {self.start_time.isoformat() if self.start_time else 'N/A'}
- **结束时间**: {self.end_time.isoformat() if self.end_time else 'N/A'}
- **Token消耗**: {self.total_tokens.get('total', 0)} ({', '.join([f"{k}: {v}" for k, v in self.total_tokens.items() if k != 'total'])})
- **总事件数**: {len(self.events)}

## 执行时间线

"""

        for event in self.events:
            event_type_emoji = {
                EventType.TASK_START: "🚀",
                EventType.TASK_END: "✅",
                EventType.PLANNER_START: "🧠",
                EventType.PLANNER_OBSERVATION: "👀",
                EventType.PLANNER_THINKING: "💭",
                EventType.PLANNER_TOOL_CALL: "🔧",
                EventType.PLANNER_END: "🏁",
                EventType.MCP_TOOL_START: "⚙️",
                EventType.MCP_TOOL_END: "✨",
                EventType.GLM_STEP_START: "📱",
                EventType.GLM_THINKING: "🤔",
                EventType.GLM_ACTION: "👆",
                EventType.GLM_STEP_END: "🎯",
                EventType.SCREENSHOT: "📸",
            }.get(event.event_type, "📌")

            md_content += f"""
### {event_type_emoji} {event.event_type.value}
**时间**: {event.timestamp.strftime('%H:%M:%S.%f')[:-3]}
{f'**步骤**: {event.step_number}' if event.step_number else ''}

{event.content}
"""

            if event.data:
                md_content += f"""
```json
{json.dumps(event.data, ensure_ascii=False, indent=2)}
```
"""

            if event.screenshot_path:
                filename = os.path.basename(event.screenshot_path)
                md_content += f"""
<img src="screenPath/{filename}" width="300" />
"""

            md_content += "\n---\n"

        return md_content

    def generate_json(self) -> str:
        """Generate JSON report."""
        report_data = {
            "test_case": self.test_case,
            "task": self.task,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_tokens": self.total_tokens,
            "events": [event.to_dict() for event in self.events],
        }
        return json.dumps(report_data, ensure_ascii=False, indent=2)

    def initialize_report_dir(self, base_filename: Optional[str] = None) -> None:
        """
        Initialize report directory structure.

        Args:
            base_filename: Base filename (without extension). If None, uses timestamp.
        """
        if base_filename is None:
            base_filename = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        # Create report directory
        if self.use_timestamp_dir:
            self.report_dir = self.base_output_dir / base_filename
        else:
            self.report_dir = self.base_output_dir

        if not self.test_case:
            self.test_case = os.path.basename(self.report_dir)

        self.report_dir = output_path(self.report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        # Create screenPath subdirectory for screenshots
        self.screenshot_dir = output_path(self.report_dir / "screenPath")
        self.screenshot_dir.mkdir(exist_ok=True)

        # Create layout subdirectory for layout
        self.layout_dir = output_path(self.report_dir / "layout")
        self.layout_dir.mkdir(exist_ok=True)

        # video path
        self.video_dir = output_path(self.report_dir / "videoPath")
        self.video_dir.mkdir(exist_ok=True)

    def save_all(self, base_filename: Optional[str] = None) -> dict[str, str]:
        """
        Save all report formats.

        Args:
            base_filename: Base filename (without extension). If None, uses timestamp.

        Returns:
            Dictionary mapping format to filepath
        """
        if base_filename is None:
            base_filename = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        # Initialize report directory if not already done
        if self.report_dir is None or self.screenshot_dir is None:
            self.initialize_report_dir(base_filename)

        saved_files = {}

        html_path = output_path(self.report_dir / f"{base_filename}.html", boundary=self.report_dir)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(self.generate_html())
        saved_files["html"] = str(html_path)

        md_path = output_path(self.report_dir / f"{base_filename}.md", boundary=self.report_dir)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown())
        saved_files["markdown"] = str(md_path)

        json_path = output_path(self.report_dir / f"{base_filename}.json", boundary=self.report_dir)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(self.generate_json())
        saved_files["json"] = str(json_path)

        return saved_files
