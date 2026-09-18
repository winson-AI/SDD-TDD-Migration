import re
import time
from hypium import UiDriver, BY

from .apps import APP_PACKAGES, get_package_name
from ...logger import logger


def get_current_app(driver: UiDriver) -> str:
    """
    Get the currently focused app name.

    Args:
        driver: Optional HDC device ID for multi-device setups.

    Returns:
        The app name if recognized, otherwise "System Home".
    """
    output = driver.shell("aa dump -l")

    if not output:
        raise ValueError("No output from aa dump")

    # Parse missions and find the one with FOREGROUND state
    # Output format:
    # Mission ID #139
    # mission name #[#com.ss.hm.ugc.aweme:entry:MainAbility]
    # app name [com.ss.hm.ugc.aweme]
    # bundle name [com.ss.hm.ugc.aweme]
    # ability type [PAGE]
    # state #FOREGROUND
    # app state #FOREGROUND

    lines = output.split("\n")
    foreground_bundle = None
    current_bundle = None

    for line in lines:
        # Track the current mission's bundle name
        if "app name [" in line:
            match = re.search(r'\[([^\]]+)\]', line)
            if match:
                current_bundle = match.group(1)

        # Check if this mission is in FOREGROUND state
        if "state #FOREGROUND" in line or "state #foreground" in line.lower():
            if current_bundle:
                foreground_bundle = current_bundle
                break  # Found the foreground app, no need to continue

        # Reset current_bundle when starting a new mission
        if "Mission ID" in line:
            current_bundle = None

    # Match against known apps
    if foreground_bundle:
        for app_name, package in APP_PACKAGES.items():
            if package == foreground_bundle:
                return app_name
        # If bundle is found but not in our known apps, return the bundle name
        logger.info(f'Bundle is found but not in our known apps: {foreground_bundle}')
        return foreground_bundle
    logger.info(f'No bundle is found')
    return "System Home"


def tap(driver: UiDriver, x: int, y: int, delay: float | None = None) -> None:
    """
    Tap at the specified coordinates.

    Args:
        driver: HDC driver instance
        x: X coordinate.
        y: Y coordinate.
        delay: Delay in seconds after tap. If None, uses configured default.
    """
    driver.touch((x, y))
    if delay:
        time.sleep(delay)


def double_tap(driver: UiDriver, x: int, y: int, delay: float | None = None) -> None:
    """
    Double tap at the specified coordinates.

    Args:
        driver: HDC driver instance
        x: X coordinate.
        y: Y coordinate.
        delay: Delay in seconds after double tap. If None, uses configured default.
    """

    driver.double_click((x, y))
    if delay:
        time.sleep(delay)


def long_press(
        driver: UiDriver,
        x: int,
        y: int,
        duration: float = 2,  # 默认 2 秒
        delay: float | None = None,
) -> None:
    """
    Long press at the specified coordinates.

    Args:
        driver: HDC driver instance
        x: X coordinate.
        y: Y coordinate.
        duration: Duration of press in seconds.
        delay: Delay in seconds after long press. If None, uses configured default.
    """
    driver.long_click((x, y), press_time=duration)
    if delay:
        time.sleep(delay)


def swipe(
        driver: UiDriver,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_s: float | None = None,
        delay: float | None = None,
) -> None:
    """
    Swipe from start to end coordinates.

    Args:
        driver: HDC driver instance
        start_x: Starting X coordinate.
        start_y: Starting Y coordinate.
        end_x: Ending X coordinate.
        end_y: Ending Y coordinate.
        duration_s: Duration of swipe in seconds (auto-calculated if None).
        delay: Delay in seconds after swipe. If None, uses configured default.
    """
    driver.slide((start_x, start_y), (end_x, end_y))
    if delay:
        time.sleep(delay)


def drag(
        driver: UiDriver,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        press_time: float = 1.5,
        drag_time: float = 1,
) -> None:
    """
    Swipe from start to end coordinates.

    Args:
        driver: HDC driver instance
        start_x: Starting X coordinate.
        start_y: Starting Y coordinate.
        end_x: Ending X coordinate.
        end_y: Ending Y coordinate.
        press_time: press time before drag
        drag_time: drag times
    """
    driver.drag((start_x, start_y), (end_x, end_y), press_time=press_time, drag_time=drag_time)


def back(driver: UiDriver, delay: float | None = None) -> None:
    """
    Press the back button.

    Args:
        driver: HDC driver instance
        delay: Delay in seconds after pressing back. If None, uses configured default.
    """
    driver.press_back()
    if delay:
        time.sleep(delay)


def home(driver: UiDriver, delay: float | None = None) -> None:
    """
    Press the home button.

    Args:
        driver: HDC driver instance
        delay: Delay in seconds after pressing home. If None, uses configured default.
    """
    driver.press_home()
    if delay:
        time.sleep(delay)


def launch_app(
        driver: UiDriver,
        app_name: str,
        delay: float | None = None
) -> bool:
    """
    Launch an app by name.

    Args:
        driver: HDC driver instance
        app_name: The app name (must be in APP_PACKAGES).
        delay: Delay in seconds after launching. If None, uses configured default.

    Returns:
        True if app was launched, False if app not found.
    """
    bundle_name = get_package_name(app_name)
    driver.start_app(bundle_name)
    if delay:
        time.sleep(delay)
    return True


def reset_status(driver: UiDriver) -> None:
    driver.go_home()
    driver.wait(1)
    driver.go_home()
    driver.wait(1)

    driver.press_combination_key(2076, 2049)
    component = driver.find_component(BY.key("RecentClearAllView_Image_deleteFull"))
    if component:
        driver.touch(component)

    else:
        components = driver.find_all_components(BY.type("Column"))
        if components:
            driver.touch(components[-1])

    driver.go_home()
    driver.wait(1)
    driver.go_home()


def set_always_screen_on_enable(driver: UiDriver) -> None:
    driver.shell("hidumper -s 3301 -a -t")


def set_always_screen_on_disable(driver: UiDriver) -> None:
    driver.shell("hidumper -s 3301 -a -f")


def pinch_in(
        driver: UiDriver,
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
        driver: HDC driver instance
        left: Left boundary
        top: Top boundary
        right: Right boundary
        bottom: Bottom boundary
        scale: Scale factor for the pinch gesture (0-1), smaller value means longer distance (default 0.4)
        direction: Direction of the gesture, "diagonal" or "horizontal" (default "diagonal")
        delay: Delay in seconds after gesture. If None, uses configured default.
    """
    from hypium import Rect
    rect = Rect(left, right, top, bottom)
    driver.pinch_in(rect, scale=scale, direction=direction)

    if delay:
        time.sleep(delay)


def pinch_out(
        driver: UiDriver,
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
        driver: HDC driver instance
        left: Left boundary
        top: Top boundary
        right: Right boundary
        bottom: Bottom boundary
        scale: Scale factor for the pinch gesture (1-2), larger value means longer distance (default 1.6)
        direction: Direction of the gesture, "diagonal" or "horizontal" (default "diagonal")
        delay: Delay in seconds after gesture. If None, uses configured default.
    """
    from hypium import Rect
    rect = Rect(left, right, top, bottom)
    driver.pinch_out(rect, scale=scale, direction=direction)

    if delay:
        time.sleep(delay)
