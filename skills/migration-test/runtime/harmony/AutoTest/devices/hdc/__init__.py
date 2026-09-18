"""HDC utilities for HarmonyOS device interaction."""

from .screenshot import get_screenshot, start_screen_record, stop_screen_record
from .input import type_text, clear_text
from .apps import APP_PACKAGES, APP_ABILITIES, get_package_name
from .device import get_current_app, tap, double_tap, long_press, swipe, launch_app, back, home, reset_status, \
    set_always_screen_on_enable, set_always_screen_on_disable, drag, pinch_in, pinch_out

__all__ = [
    # Screenshot
    "get_screenshot",
    # input
    "type_text",
    "clear_text",
    # app info
    "APP_PACKAGES",
    "APP_ABILITIES",
    "get_package_name",
    # device
    "get_current_app",
    "tap",
    "double_tap",
    "long_press",
    "swipe",
    "drag",
    "launch_app",
    "back",
    "home",
    "reset_status",
    "set_always_screen_on_enable",
    "set_always_screen_on_disable",
    "pinch_in",
    "pinch_out",
    "start_screen_record",
    "stop_screen_record"
]
