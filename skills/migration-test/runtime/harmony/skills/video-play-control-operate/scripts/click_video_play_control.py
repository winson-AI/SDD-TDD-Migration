from hypium import UiDriver


def _create_driver(context):
    driver = getattr(context, "driver", None)
    if driver is not None:
        return driver

    if getattr(context, "hypium_device", None) is not None:
        return UiDriver(context.hypium_device)

    raise RuntimeError("No hypium device or UiDriver found in skill script context")

def _parse_point(argv):
    if len(argv) not in (2, 3):
        raise ValueError("Usage: click_video_play_control.py <x> <y> [wait_seconds]")

    try:
        x = int(argv[0])
        y = int(argv[1])
        wait = int(argv[2]) if len(argv) == 3 else 2
    except ValueError as e:
        raise ValueError("x, y and wait_seconds must be integers") from e

    if not 0 <= x <= 1000 or not 0 <= y <= 1000:
        raise ValueError("x and y must be between 0 and 1000")

    if wait < 0:
        raise ValueError("wait_seconds must be >= 0")

    return x, y, wait

def run(context):
    driver = _create_driver(context)
    x, y, wait_seconds = _parse_point(getattr(context, "argv", []) or [])

    float_x = x / 1000.0
    float_y = y / 1000.0

    driver.click((float_x, float_y))
    driver.wait(2)
    driver.click((float_x, float_y))
    driver.wait(wait_seconds)

    return {
        "success": True,
        "action": "click_video_play_control",
        "x": float_x,
        "y": float_y,
        "wait_seconds": wait_seconds,
        "message": "click_video_play_control successfully"
    }
