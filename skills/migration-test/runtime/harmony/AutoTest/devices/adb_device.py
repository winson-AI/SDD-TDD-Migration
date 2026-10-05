"""ADB/uiautomator2 device implementation of DeviceProtocol."""
import os.path
import time
from pathlib import Path
from typing import Tuple

import uiautomator2 as u2

from ..logger import logger
from ..devices.device_protocol import (
    DeviceProtocol,
    Screenshot
)

from . import adb
from ..config import AppConfig
from ..storage import output_path


class AdbDevice(DeviceProtocol):
    """
    Android device implementation using uiautomator2 (ADB + on-device
    automation service), mirroring HDCDevice's structure for HarmonyOS.
    """

    platform = 'android'

    def __init__(self, device_sn: str, report_generator=None, config: AppConfig = None):
        """
        Initialize ADB device.

        Args:
            device_sn: Device serial number (USB serial, or "ip:port" for wireless adb).
            report_generator: Optional report generator for saving screenshots.
            config: config
        """
        if not device_sn:
            raise ValueError('explicit Android device serial required')
        self._driver = u2.connect(device_sn)
        self._device_sn = self._driver.serial
        self._report_generator = report_generator
        self._config = config
        self._teardown_callbacks = []
        self.setup()

    def setup(self):
        # Preserve the approved fixture; resets must be explicit frozen steps.
        self.set_always_screen_on_enable()
        if self._config and self._config.verify_video_enable:
            self.start_screen_record()
            if self._report_generator and hasattr(self._report_generator, "step_content"):
                if self._report_generator.step_content:
                    self._report_generator.step_content[0].timestamp = time.time()

    def teardown(self):
        """run device teardown after task"""
        try:
            self.set_always_screen_on_disable()
        except Exception as e:
            logger.warning(f"set_always_screen_on_disable failed, reason: {e}")
        if self._config and self._config.verify_video_enable:
            try:
                if self._report_generator and getattr(self._report_generator, "video_dir", None):
                    final_path = str(output_path(self._report_generator.video_dir / "final.mp4"))
                    self.stop_screen_record(final_path)
                    if not self._config.keep_raw_video:
                        if os.path.exists(final_path):
                            os.remove(final_path)
                        for f in Path(self._report_generator.video_dir).glob("screen_record*.mp4"):
                            try:
                                output_path(f).unlink()
                                logger.info(f"[teardown] 清理 screen_record: {f}")
                            except Exception as e:
                                logger.warning(f"[teardown] 清理 screen_record 失败: {f}, 错误: {e}")
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

    @property
    def device_id(self) -> str:
        """Unique device identifier."""
        return self._device_sn

    @property
    def ip(self) -> str:
        # uiautomator2 talks to the local adb server, not a per-device
        # connector endpoint - this is a placeholder for protocol compliance.
        return "127.0.0.1"

    @property
    def port(self) -> int:
        return 5037

    @property
    def driver(self):
        """Get the underlying uiautomator2 Device instance."""
        return self._driver

    def get_display_size(self) -> Tuple[int, int]:
        return self._driver.window_size()

    # === Screenshot ===
    def get_screenshot(self, timeout: int = 10, save_to_report: bool = True) -> Screenshot:
        """
        Capture current screen.

        Args:
            timeout: Timeout in seconds (unused, kept for protocol parity).
            save_to_report: Whether to save screenshot to report directory

        Returns:
            Screenshot object containing base64 data and dimensions.
        """
        screenshot = adb.get_screenshot(self._driver)
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
        adb.tap(self._driver, x, y, delay)

    def double_tap(self, x: int, y: int, delay: float | None = None) -> None:
        """Double tap at specified coordinates."""
        adb.double_tap(self._driver, x, y, delay)

    def long_press(
            self, x: int, y: int, duration: int = 3, delay: float | None = None
    ) -> None:
        """Long press at specified coordinates."""
        adb.long_press(self._driver, x, y, duration, delay)

    def swipe(
            self,
            start_x: int,
            start_y: int,
            end_x: int,
            end_y: int,
            duration_s: float | None = None,
            delay: float | None = None,
    ) -> None:
        """Swipe from start to end coordinates."""
        adb.swipe(self._driver, start_x, start_y, end_x, end_y, duration_s, delay)

    def type_text(self, text: str) -> None:
        """Type text into the currently focused input field."""
        adb.type_text(self._driver, text)

    def clear_text(self) -> None:
        """Clear text in the currently focused input field."""
        adb.clear_text(self._driver)

    # === Navigation ===
    def back(self, delay: float | None = None) -> None:
        """Press the back button."""
        adb.back(self._driver, delay)

    def home(self, delay: float | None = None) -> None:
        """Press the home button."""
        adb.home(self._driver, delay)

    def drag(self,
             start_x: int,
             start_y: int,
             end_x: int,
             end_y: int,
             press_time: float = 1.5,
             drag_time: float = 1) -> None:
        return adb.drag(self._driver, start_x, start_y, end_x, end_y, press_time, drag_time)

    def launch_app(self, app_name: str, delay: float | None = None) -> bool:
        """Launch an app by name."""
        return adb.launch_app(self._driver, app_name, delay)

    def stop_app(self, app_name: str) -> None:
        """Stop an app by name."""
        adb.stop_app(self._driver, app_name)

    def clear_app_data(self, app_name: str) -> None:
        """Clear an app's data (simulates a fresh install)."""
        adb.clear_app_data(self._driver, app_name)

    # === State Query ===
    def get_current_app(self) -> str:
        """Get the currently focused app name."""
        return adb.get_current_app(self._driver)

    def reset_status(self):
        """Reset the device."""
        return adb.reset_status(self._driver)

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
        return adb.set_always_screen_on_enable(self._driver)

    def set_always_screen_on_disable(self):
        """Set always screen off."""
        return adb.set_always_screen_on_disable(self._driver)

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
        Implemented via uiautomator2's raw two-finger gesture RPC (see adb/device.py::pinch_in).
        """
        adb.pinch_in(self._driver, left, top, right, bottom, scale, direction, delay)

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
        Implemented via uiautomator2's raw two-finger gesture RPC (see adb/device.py::pinch_out).
        """
        adb.pinch_out(self._driver, left, top, right, bottom, scale, direction, delay)

    def start_screen_record(self) -> None:
        adb.start_screen_record(self._driver)

    def stop_screen_record(self, path: str = None) -> None:
        adb.stop_screen_record(self._driver, path)
