"""Action handler for executing phone operations."""

import time
from typing import Any, Callable

from ..devices.device_protocol import DeviceProtocol

from .types import ActionResult


class ActionHandler:
    def __init__(
            self,
            device: DeviceProtocol,
            confirmation_callback: Callable[[str], bool] | None = None,
            takeover_callback: Callable[[str], None] | None = None,
    ):
        self.device = device
        self.confirmation_callback = confirmation_callback or self._default_confirmation
        self.takeover_callback = takeover_callback or self._default_takeover

    def execute(self, action: dict[str, Any]) -> ActionResult:
        action_type = action.get("_metadata")

        if action_type == "finish":
            return ActionResult(
                success=True, should_finish=True, message=action.get("message")
            )

        if action_type != "do":
            return ActionResult(
                success=False,
                should_finish=True,
                message=f"Unknown action type: {action_type}",
            )

        action_name = action.get("action")
        if not isinstance(action_name, str) or not action_name:
            return ActionResult(
                success=False,
                should_finish=False,
                message=f"Unknown action: {action_name}",
            )

        handler_method = self._get_handler(action_name)

        if handler_method is None:
            return ActionResult(
                success=False,
                should_finish=False,
                message=f"Unknown action: {action_name}",
            )

        try:
            return handler_method(action)
        except Exception as e:
            return ActionResult(
                success=False, should_finish=False, message=f"Action failed: {e}"
            )

    def _get_handler(self, action_name: str) -> Callable | None:
        handlers = {
            "Launch": self._handle_launch,
            "Tap": self._handle_tap,
            "Type": self._handle_type,
            "Type_Name": self._handle_type,
            "Swipe": self._handle_swipe,
            "Drag": self._handle_drag,
            "Back": self._handle_back,
            "Home": self._handle_home,
            "Double Tap": self._handle_double_tap,
            "Long Press": self._handle_long_press,
            "Wait": self._handle_wait,
            "Take_over": self._handle_takeover,
            "Note": self._handle_note,
            "Clear Text": self._handle_clear_text,
            "Pinch In": self._handle_pinch_in,
            "Pinch Out": self._handle_pinch_out,
        }
        return handlers.get(action_name)

    def _handle_launch(self, action: dict) -> ActionResult:
        app_name = action.get("app")
        if not app_name:
            return ActionResult(False, False, "No app name specified")

        success = self.device.launch_app(app_name)
        if success:
            return ActionResult(True, False)
        return ActionResult(False, False, f"App not found: {app_name}")

    def _handle_tap(self, action: dict) -> ActionResult:
        element = action.get("element")
        if not element:
            return ActionResult(False, False, "No element coordinates")

        x, y = element

        if "message" in action:
            if not self.confirmation_callback(action["message"]):
                return ActionResult(
                    success=False,
                    should_finish=True,
                    message="User cancelled sensitive operation",
                )

        self.device.tap(x, y)
        return ActionResult(True, False)

    def _handle_type(self, action: dict) -> ActionResult:
        text = action.get("text", "")

        self.device.clear_text()
        time.sleep(0.3)
        self.device.type_text(text)
        time.sleep(0.5)

        return ActionResult(True, False)

    def _handle_swipe(self, action: dict) -> ActionResult:
        start = action.get("start")
        end = action.get("end")

        if not start or not end:
            return ActionResult(False, False, "Missing swipe coordinates")

        start_x, start_y = start
        end_x, end_y = end

        self.device.swipe(start_x, start_y, end_x, end_y)
        return ActionResult(True, False)

    def _handle_drag(self, action: dict) -> ActionResult:
        start = action.get("start")
        end = action.get("end")

        if not start or not end:
            return ActionResult(False, False, "Missing drag coordinates")

        start_x, start_y = start
        end_x, end_y = end
        press_time = float(action.get("press_time", 1.5))
        drag_time = float(action.get("drag_time", 1))

        self.device.drag(start_x, start_y, end_x, end_y, press_time, drag_time)
        return ActionResult(True, False)

    def _handle_back(self, action: dict) -> ActionResult:
        self.device.back()
        return ActionResult(True, False)

    def _handle_home(self, action: dict) -> ActionResult:
        self.device.home()
        return ActionResult(True, False)

    def _handle_double_tap(self, action: dict) -> ActionResult:
        element = action.get("element")
        if not element:
            return ActionResult(False, False, "No element coordinates")

        x, y = element
        self.device.double_tap(x, y)
        return ActionResult(True, False)

    def _handle_long_press(self, action: dict) -> ActionResult:
        element = action.get("element")
        if not element:
            return ActionResult(False, False, "No element coordinates")

        x, y = element
        duration = int(action.get("duration", 2))
        self.device.long_press(x, y, duration)
        return ActionResult(True, False)

    def _handle_wait(self, action: dict) -> ActionResult:
        duration_str = action.get("duration", "1 seconds")
        try:
            duration = float(duration_str.replace("seconds", "").strip())
        except ValueError:
            duration = 1.0

        time.sleep(duration)
        return ActionResult(True, False)

    def _handle_takeover(self, action: dict) -> ActionResult:
        message = action.get("message", "User intervention required")
        self.takeover_callback(message)
        return ActionResult(True, False)

    def _handle_note(self, action: dict) -> ActionResult:
        return ActionResult(True, False)

    def _handle_clear_text(self, action: dict) -> ActionResult:
        self.device.clear_text()
        time.sleep(0.5)
        return ActionResult(True, False)

    def _handle_pinch_in(self, action: dict) -> ActionResult:
        rect = action.get("rect")
        if not rect:
            return ActionResult(False, False, "No rect coordinates")

        left, top, right, bottom = rect
        scale = float(action.get("scale", 0.4))
        direction = action.get("direction", "diagonal")

        self.device.pinch_in(left, top, right, bottom, scale=scale, direction=direction)
        return ActionResult(True, False)

    def _handle_pinch_out(self, action: dict) -> ActionResult:
        rect = action.get("rect")
        if not rect:
            return ActionResult(False, False, "No rect coordinates")

        left, top, right, bottom = rect
        scale = float(action.get("scale", 1.6))
        direction = action.get("direction", "diagonal")

        self.device.pinch_out(left, top, right, bottom, scale=scale, direction=direction)
        return ActionResult(True, False)

    @staticmethod
    def _default_confirmation(message: str) -> bool:
        response = input(f"\n⚠️  Confirm action: {message} (y/n): ")
        return response.lower() in ("y", "yes")

    @staticmethod
    def _default_takeover(message: str) -> None:
        input(f"\n🤚 {message}. Press Enter to continue...")
