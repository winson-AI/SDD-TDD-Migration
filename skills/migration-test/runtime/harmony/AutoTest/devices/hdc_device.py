"""HDC Device implementation of DeviceProtocol."""
import os.path
import time
from pathlib import Path
from typing import Tuple

from ..logger import logger
from ..devices.device_protocol import (
    DeviceProtocol,
    Screenshot
)

from . import hdc
from ..config import AppConfig
from ..storage import output_path
from hypium import UiDriver


class HDCDevice(DeviceProtocol):
    """
    HDC device implementation using local subprocess calls.
    """

    def __init__(self, device_sn: str, ip: str = "127.0.0.1", port: int = 8710, report_generator=None,
                 config: AppConfig = None):
        """
        Initialize HDC device.

        Args:
            device_sn: Device serial number
            ip: Device IP address
            port: Device port
            report_generator: Optional report generator for saving screenshots
            config: config
        """
        report_dir = str(output_path(report_generator.report_dir if report_generator else None, default='sdk'))
        self._driver = UiDriver.connect(device_sn=device_sn, connector_server=(ip, port),
                                        report_path=report_dir)
        self._device_sn = self._driver._device.device_sn
        self._ip = self._driver._device.host
        self._port = self._driver._device.port
        self._report_generator = report_generator
        self._config = config
        self._teardown_callbacks = []
        self.setup()

    def setup(self):
        self.reset_status()
        self.set_always_screen_on_enable()
        if self._config and self._config.verify_video_enable:
            self.start_screen_record()
            if self._report_generator and hasattr(self._report_generator, "step_content"):
                if self._report_generator.step_content:
                    self._report_generator.step_content[0].timestamp = time.time()

    def teardown(self):
        """run device teardown after task"""
        self.set_always_screen_on_disable()
        if self._config and self._config.verify_video_enable:
            try:
                if self._report_generator and getattr(self._report_generator, "video_dir", None):
                    final_path = os.path.join(self._report_generator.video_dir, "final.mp4")
                    self.stop_screen_record(final_path)
                    if not self._config.keep_raw_video:
                        # 清理 screen_record 和 final.mp4
                        if os.path.exists(final_path):
                            output_path(final_path).unlink()
                        for f in Path(self._report_generator.video_dir).glob("screen_record*.mp4"):
                            try:
                                output_path(f).unlink()
                                logger.info(f"[teardown] 清理 screen_record: {f}")
                            except Exception as e:
                                logger.warning(f"[teardown] 清理 screen_record 失败: {f}, 错误: {e}")
                        # 清理片段元数据文件
                        segment_meta = Path(self._report_generator.video_dir) / "_segment_starts.json"
                        if segment_meta.exists():
                            try:
                                output_path(segment_meta).unlink()
                            except Exception as e:
                                logger.warning(f"[teardown] 清理片段元数据失败: {e}")
                else:
                    self.stop_screen_record()
            except Exception as e:
                logger.warning(f"stop screen record failed, reason: {e}")

        for callback in self._teardown_callbacks:
            try:
                callback()
            except Exception as e:
                logger.warning(f"teardown callback failed, reason: {e}")

        self._teardown_callbacks.clear()
        self.driver.close()

    @property
    def device_id(self) -> str:
        """Unique device identifier."""
        return self._device_sn

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return int(self._port)

    @property
    def driver(self):
        """Get the driver instance."""
        return self._driver

    def get_display_size(self) -> Tuple[int, int]:
        return self._driver.get_display_size()

    # === Screenshot ===
    def get_screenshot(self, timeout: int = 10, save_to_report: bool = True) -> Screenshot:
        """
        Capture current screen.

        Args:
            timeout: Timeout in seconds
            save_to_report: Whether to save screenshot to report directory

        Returns:
            Screenshot object containing base64 data and dimensions.
        """
        screenshot = hdc.get_screenshot(self._driver)
        screenshot_path = None

        if save_to_report and self._report_generator:
            try:
                screenshot_path = self._report_generator.save_screenshot(
                    screenshot.base64_data,
                    layout_data=screenshot.layout_data,
                    prefix=f"step_"
                           f"{self._report_generator.events[-1].step_number if self._report_generator.events else 0}"
                )
            except Exception as e:
                logger.exception("save screenshot error {}".format(e))

        return Screenshot(
            base64_data=screenshot.base64_data,
            layout_data=screenshot.layout_data,
            width=screenshot.width,
            height=screenshot.height,
            is_sensitive=screenshot.is_sensitive,
            screenshot_path=screenshot_path
        )

    # === Input Operations ===
    def tap(self, x: int, y: int, delay: float | None = None) -> None:
        """Tap at specified coordinates."""
        hdc.tap(self._driver, x, y, delay)

    def double_tap(self, x: int, y: int, delay: float | None = None) -> None:
        """Double tap at specified coordinates."""
        hdc.double_tap(self._driver, x, y, delay)

    def long_press(
            self, x: int, y: int, duration: int = 3, delay: float | None = None
    ) -> None:
        """Long press at specified coordinates."""
        hdc.long_press(self._driver, x, y, duration, delay)

    def swipe(
            self,
            start_x: int,
            start_y: int,
            end_x: int,
            end_y: int,
            duration_ms: int | None = None,
            delay: float | None = None,
    ) -> None:
        """Swipe from start to end coordinates."""
        hdc.swipe(self._driver, start_x, start_y, end_x, end_y, duration_ms, delay)

    def type_text(self, text: str) -> None:
        """Type text into the currently focused input field."""
        hdc.type_text(self._driver, text)

    def clear_text(self) -> None:
        """Clear text in the currently focused input field."""
        hdc.clear_text(self._driver)

    # === Navigation ===
    def back(self, delay: float | None = None) -> None:
        """Press the back button."""
        hdc.back(self._driver, delay)

    def home(self, delay: float | None = None) -> None:
        """Press the home button."""
        hdc.home(self._driver, delay)

    def drag(self,
             start_x: int,
             start_y: int,
             end_x: int,
             end_y: int,
             press_time: float = 1.5,
             drag_time: float = 1) -> None:
        return hdc.drag(self._driver, start_x, start_y, end_x, end_y, press_time, drag_time)

    def launch_app(self, app_name: str, delay: float | None = None) -> bool:
        """Launch an app by name."""
        return hdc.launch_app(self._driver, app_name, delay)

    # === State Query ===
    def get_current_app(self) -> str:
        """Get the currently focused app name."""
        return hdc.get_current_app(self._driver)

    def reset_status(self):
        """Reset the device."""
        return hdc.reset_status(self._driver)

    def register_teardown_callback(self, callback):
        """
        Register a callback to be called during teardown.

        Args:
            callback: A callable that will be invoked during teardown.
                     The callback will receive no arguments.
        """
        if callable(callback):
            self._teardown_callbacks.append(callback)
        else:
            logger.warning(f"Attempted to register non-callable teardown callback: {callback}")

    def set_always_screen_on_enable(self):
        """Set always screen on."""
        return hdc.set_always_screen_on_enable(self._driver)

    def set_always_screen_on_disable(self):
        """Set always screen off."""
        return hdc.set_always_screen_on_disable(self._driver)

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
            left: Left boundary (0-1000 normalized coordinates)
            top: Top boundary (0-1000 normalized coordinates)
            right: Right boundary (0-1000 normalized coordinates)
            bottom: Bottom boundary (0-1000 normalized coordinates)
            scale: Scale factor for the pinch gesture (0-1), smaller value means longer distance (default 0.4)
            direction: Direction of the gesture, "diagonal" or "horizontal" (default "diagonal")
            delay: Delay in seconds after gesture. If None, uses configured default.
        """
        hdc.pinch_in(self._driver, left, top, right, bottom, scale, direction, delay)

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
        hdc.pinch_out(self._driver, left, top, right, bottom, scale, direction, delay)

    def start_screen_record(self) -> None:
        hdc.start_screen_record(self._driver)

    def stop_screen_record(self, path: str = None) -> None:
        hdc.stop_screen_record(self._driver, path)
