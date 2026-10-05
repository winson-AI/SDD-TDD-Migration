import time

import uiautomator2 as u2

from .apps import APP_PACKAGES, LAUNCHER_PACKAGES, get_package_name
from ...logger import logger


def get_current_app(device: u2.Device) -> str:
    """
    Get the currently focused app name.

    Args:
        device: uiautomator2 device instance.

    Returns:
        The app name if recognized, otherwise "System Home".
    """
    try:
        info = device.app_current()
    except Exception as e:
        logger.info(f"[ADB] get_current_app failed: {e}")
        return "System Home"

    package = info.get("package") if info else None
    if not package or package in LAUNCHER_PACKAGES:
        return "System Home"

    for app_name, pkg in APP_PACKAGES.items():
        if pkg == package:
            return app_name

    logger.info(f"[ADB] Package is running but not in our known apps: {package}")
    return package


def tap(device: u2.Device, x: int, y: int, delay: float | None = None) -> None:
    """Tap at the specified coordinates."""
    device.click(x, y)
    if delay:
        time.sleep(delay)


def double_tap(device: u2.Device, x: int, y: int, delay: float | None = None) -> None:
    """Double tap at the specified coordinates."""
    device.double_click(x, y)
    if delay:
        time.sleep(delay)


def long_press(
        device: u2.Device,
        x: int,
        y: int,
        duration: float = 2,
        delay: float | None = None,
) -> None:
    """Long press at the specified coordinates."""
    device.long_click(x, y, duration=duration)
    if delay:
        time.sleep(delay)


def swipe(
        device: u2.Device,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_s: float | None = None,
        delay: float | None = None,
) -> None:
    """Swipe from start to end coordinates."""
    if duration_s is not None:
        device.swipe(start_x, start_y, end_x, end_y, duration=duration_s)
    else:
        device.swipe(start_x, start_y, end_x, end_y)
    if delay:
        time.sleep(delay)


def drag(
        device: u2.Device,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        press_time: float = 1.5,
        drag_time: float = 1,
) -> None:
    """Drag from start to end coordinates."""
    device.drag(start_x, start_y, end_x, end_y, duration=drag_time)


def back(device: u2.Device, delay: float | None = None) -> None:
    """Press the back button."""
    device.press("back")
    if delay:
        time.sleep(delay)


def home(device: u2.Device, delay: float | None = None) -> None:
    """Press the home button."""
    device.press("home")
    if delay:
        time.sleep(delay)


def launch_app(
        device: u2.Device,
        app_name: str,
        delay: float | None = None
) -> bool:
    """
    Launch an app by name.

    Args:
        device: uiautomator2 device instance.
        app_name: The app name (must be in APP_PACKAGES).
        delay: Delay in seconds after launching. If None, uses configured default.

    Returns:
        True if app was launched, False if app not found.
    """
    package_name = get_package_name(app_name) or app_name
    # No activity given -> uiautomator2 resolves the launcher activity itself
    # via `monkey -c android.intent.category.LAUNCHER`, mirroring how
    # hypium's start_app() needs no explicit ability name either.
    device.app_start(package_name, use_monkey=True)
    if delay:
        time.sleep(delay)
    return True


def stop_app(device: u2.Device, app_name: str) -> None:
    """Stop an app by name."""
    package_name = get_package_name(app_name) or app_name
    device.app_stop(package_name)


def clear_app_data(device: u2.Device, app_name: str) -> None:
    """Clear an app's data (simulates a fresh install)."""
    package_name = get_package_name(app_name) or app_name
    device.app_clear(package_name)


# Candidate selectors for the "clear all recents" button, covering common
# AOSP/Pixel/Samsung/MIUI/Huawei-EMUI label and resource-id variants. There is
# no unified id across OEMs the way HarmonyOS has one system-wide component,
# so this tries each in turn and clicks whichever is actually present.
_CLEAR_ALL_CANDIDATES = [
    {"resourceId": "com.android.systemui:id/clear_all_button"},
    {"resourceId": "com.android.systemui:id/recents_clear_all"},
    {"text": "Clear all"},
    {"text": "清除全部"},
    {"text": "全部清除"},
    {"text": "一键清理"},
    {"description": "Clear all"},
    {"description": "清除全部"},
]


def reset_status(device: u2.Device) -> None:
    device.press("home")
    time.sleep(1)
    device.press("home")
    time.sleep(1)
    # open the recent-apps overview and try to tap "clear all" if present
    device.press("recent")
    time.sleep(1)
    for kwargs in _CLEAR_ALL_CANDIDATES:
        try:
            element = device(**kwargs)
            if element.exists(timeout=0.5):
                element.click()
                break
        except Exception as e:
            logger.info(f"[ADB] reset_status clear-all candidate {kwargs} failed: {e}")
    device.press("home")
    time.sleep(1)
    device.press("home")


def set_always_screen_on_enable(device: u2.Device) -> None:
    device.shell("svc power stayon true")


def set_always_screen_on_disable(device: u2.Device) -> None:
    device.shell("svc power stayon false")


_PINCH_OUT_START_FRACTION = 0.15  # how close together fingers start for pinch_out, as a fraction of the half-extent


def _rect_axis_points(left: int, top: int, right: int, bottom: int, direction: str):
    """Return the rect's two corner points along the pinch axis (scale=1.0 reference)."""
    cx, cy = (left + right) // 2, (top + bottom) // 2
    if direction == "horizontal":
        return (left, cy), (right, cy)
    return (left, top), (right, bottom)  # diagonal


def _scale_point(center, pt, scale: float):
    cx, cy = center
    return (
        cx - int((cx - pt[0]) * scale),
        cy - int((cy - pt[1]) * scale),
    )


def _gesture_selector(device: u2.Device):
    """Best-effort selector to anchor the two-finger gesture RPC to the
    current app's window. The gesture itself operates on the absolute
    coordinates passed in, not the selector's own bounds - this just gives
    the on-device UiAutomator2 server a context to run in.
    """
    try:
        package = device.app_current().get("package")
        if package:
            return device(packageName=package)
    except Exception:
        pass
    return device(index=0)


def pinch_in(
        device: u2.Device,
        left: int,
        top: int,
        right: int,
        bottom: int,
        scale: float = 0.4,
        direction: str = "diagonal",
        delay: float | None = None,
) -> None:
    """Pinch in (zoom out): fingers start at the rect's corners and move inward to `scale` of the half-extent."""
    cx, cy = (left + right) // 2, (top + bottom) // 2
    p1, p2 = _rect_axis_points(left, top, right, bottom, direction)
    end1, end2 = _scale_point((cx, cy), p1, scale), _scale_point((cx, cy), p2, scale)
    _gesture_selector(device).gesture(p1, p2, end1, end2, steps=50)
    if delay:
        time.sleep(delay)


def pinch_out(
        device: u2.Device,
        left: int,
        top: int,
        right: int,
        bottom: int,
        scale: float = 1.6,
        direction: str = "diagonal",
        delay: float | None = None,
) -> None:
    """Pinch out (zoom in): fingers start close together near center and move outward to `scale` of the half-extent (may exceed the rect)."""
    cx, cy = (left + right) // 2, (top + bottom) // 2
    p1, p2 = _rect_axis_points(left, top, right, bottom, direction)
    start1 = _scale_point((cx, cy), p1, _PINCH_OUT_START_FRACTION)
    start2 = _scale_point((cx, cy), p2, _PINCH_OUT_START_FRACTION)
    end1, end2 = _scale_point((cx, cy), p1, scale), _scale_point((cx, cy), p2, scale)
    _gesture_selector(device).gesture(start1, start2, end1, end2, steps=50)
    if delay:
        time.sleep(delay)
