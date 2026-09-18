"""Report data types."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List
import json


class EventType(Enum):
    """Event types for execution tracking."""

    TASK_START = "task_start"
    TASK_END = "task_end"

    PLANNER_START = "planner_start"
    PLANNER_OBSERVATION = "planner_observation"
    PLANNER_THINKING = "planner_thinking"
    PLANNER_TOOL_CALL = "planner_tool_call"
    PLANNER_END = "planner_end"

    MCP_TOOL_START = "mcp_tool_start"
    MCP_TOOL_END = "mcp_tool_end"

    GLM_STEP_START = "glm_step_start"
    GLM_THINKING = "glm_thinking"
    GLM_ACTION = "glm_action"
    GLM_STEP_END = "glm_step_end"

    SCREENSHOT = "screenshot"


@dataclass
class ReportEvent:
    """Single event in execution timeline."""

    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    step_number: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "data": self.data,
            "screenshot_path": self.screenshot_path,
            "step_number": self.step_number,
        }


@dataclass
class TimeCalculate:
    """Time calculate"""
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime = field(default_factory=datetime.now)

    @property
    def duration(self) -> float:
        return (self.end_time - self.start_time).total_seconds()


@dataclass
class Step:
    index: int = -1
    step_type: str = ''
    title: str = ''
    desc: str = ''
    timestamp: float = 0
    screenshot_path: str = ''
