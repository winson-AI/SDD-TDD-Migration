from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Tuple


@dataclass
class Screenshot:
    """Screenshot result from device."""

    base64_data: str
    layout_data: str
    width: int
    height: int
    is_sensitive: bool = False
    screenshot_path: str = None


@runtime_checkable
class DeviceProtocol(Protocol):
    """
    Device operation protocol - all device implementations must follow this interface.

    This protocol abstracts device operations, allowing the control logic to be
    independent of the actual device implementation (HDC, Accessibility, Remote, etc.).

    The concrete implementation decides HOW to perform operations:
    - HDCDevice: Uses `HDC shell input tap` commands
    - AccessibilityDevice: Uses Android Accessibility Service
    - RemoteDevice: Sends HTTP/gRPC requests to a remote agent
    - MockDevice: Routes operations through a state machine for testing
    """

    @property
    def device_id(self) -> str:
        """Unique device identifier."""
        ...

    @property
    def ip(self) -> str:
        """IP address of the device."""
        ...

    @property
    def port(self) -> int:
        """Port number of the device."""
        ...

    def get_display_size(self) -> Tuple[int, int]:
        """display size"""
        ...

    # === Screenshot ===
    def get_screenshot(self, timeout: int = 10, save_to_report: bool = False) -> Screenshot:
        """
        Capture current screen.

        Args:
            save_to_report: 是否保存到报告
            timeout: Timeout in seconds for the operation.

        Returns:
            Screenshot object containing base64 data and dimensions.
        """
        ...

    # === Input Operations ===
    def tap(self, x: int, y: int, delay: float | None = None) -> None:
        """
        Tap at specified coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            delay: Optional delay after tap in seconds.
        """
        ...

    def double_tap(self, x: int, y: int, delay: float | None = None) -> None:
        """
        Double tap at specified coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            delay: Optional delay after double tap in seconds.
        """
        ...

    def long_press(
            self, x: int, y: int, duration: int = 3, delay: float | None = None
    ) -> None:
        """
        Long press at specified coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            duration: Duration of press in seconds.
            delay: Optional delay after long press in seconds.
        """
        ...

    def swipe(
            self,
            start_x: int,
            start_y: int,
            end_x: int,
            end_y: int
    ) -> None:
        """
        Swipe from start to end coordinates.

        Args:
            start_x: Starting X coordinate.
            start_y: Starting Y coordinate.
            end_x: Ending X coordinate.
            end_y: Ending Y coordinate
        """
        ...

    def drag(
            self,
            start_x: int,
            start_y: int,
            end_x: int,
            end_y: int,
            press_time: float = 1.5,
            drag_time: float = 1,
    ) -> None:
        """
        Drag from start to end coordinates.

        Args:
            start_x: Starting X coordinate.
            start_y: Starting Y coordinate.
            end_x: Ending X coordinate.
            end_y: Ending Y coordinate.
            press_time: Hold time before dragging in seconds.
            drag_time: Drag movement duration in seconds.
        """
        ...

    def type_text(self, text: str) -> None:
        """
        Type text into the currently focused input field.

        Args:
            text: The text to type.
        """
        ...

    def clear_text(self) -> None:
        """Clear text in the currently focused input field."""
        ...

    # === Navigation ===
    def back(self, delay: float | None = None) -> None:
        """
        Press the back button.

        Args:
            delay: Optional delay after pressing back in seconds.
        """
        ...

    def home(self, delay: float | None = None) -> None:
        """
        Press the home button.

        Args:
            delay: Optional delay after pressing home in seconds.
        """
        ...

    def launch_app(self, app_name: str, delay: float | None = None) -> bool:
        """
        Launch an app by name.

        Args:
            app_name: The app name to launch.
            delay: Optional delay after launching in seconds.

        Returns:
            True if app was launched successfully, False otherwise.
        """
        ...

    # === State Query ===
    def get_current_app(self) -> str:
        """
        Get the currently focused app name.

        Returns:
            The app name if recognized, otherwise "System Home".
        """
        ...

    def pinch_in(
            self,
            left: int,
            top: int,
            right: int,
            bottom: int,
            scale: float = 0.4,
            direction: str = "diagonal",
            delay: float | None = None,
    ) -> None:
        """
        Pinch in (zoom out) gesture - two fingers move toward each other.

        Args:
            left: Left boundary
            top: Top boundary
            right: Right boundary
            bottom: Bottom boundary
            scale: Scale factor for the pinch gesture (0-1), smaller value means longer distance (default 0.4)
            direction: Direction of the gesture, "diagonal" or "horizontal" (default "diagonal")
            delay: Delay in seconds after gesture. If None, uses configured default.
        """
        ...

    def pinch_out(
            self,
            left: int,
            top: int,
            right: int,
            bottom: int,
            scale: float = 1.6,
            direction: str = "diagonal",
            delay: float | None = None,
    ) -> None:
        """
        Pinch out (zoom in) gesture - two fingers move away from each other.

        Args:
            left: Left boundary
            top: Top boundary
            right: Right boundary
            bottom: Bottom boundary
            scale: Scale factor for the pinch gesture (1-2), larger value means longer distance (default 1.6)
            direction: Direction of the gesture, "diagonal" or "horizontal" (default "diagonal")
            delay: Delay in seconds after gesture. If None, uses configured default.
        """
        ...

    def setup(self):
        """run device setup before task"""
        ...

    def teardown(self):
        """run device teardown after task"""
        ...

    def register_teardown_callback(self, callback) -> None:
        """
        Register a callback to be called during teardown.

        This allows external code to inject custom cleanup logic
        that will be executed when the device teardown is called.

        Args:
            callback: A callable that will be invoked during teardown.
                     The callback will receive no arguments.
        """
        ...
