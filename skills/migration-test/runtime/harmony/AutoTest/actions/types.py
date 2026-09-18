"""Action result types."""

from dataclasses import dataclass


@dataclass
class ActionResult:
    """Result of an action execution."""
    success: bool
    should_finish: bool
    message: str | None = None


@dataclass
class StepResult:
    """Result of an agent step."""
    success: bool
    finished: bool
    action: dict | None
    thinking: str
    message: str | None = None