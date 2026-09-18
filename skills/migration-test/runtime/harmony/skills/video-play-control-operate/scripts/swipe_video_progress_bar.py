from hypium import UiDriver


def _create_driver(context):
    driver = getattr(context, "driver", None)
    if driver is not None:
        return driver

    if getattr(context, "hypium_device", None) is not None:
        return UiDriver(context.hypium_device)

    raise RuntimeError("No hypium device or UiDriver found in skill script context")

def _parse_point(argv):
    if len(argv) != 4:
        raise ValueError("Usage: swipe_video_progress_bar.py <x1> <y1> <x2> <y2>")

    try:
        x1 = int(argv[0])
        y1 = int(argv[1])
        x2 = int(argv[2])
        y2 = int(argv[3])
    except ValueError as e:
        raise ValueError("x and y must be an integer") from e

    if not 0 <= x1 <= 1000 or not 0 <= y1 <= 1000 or not 0 <= x2 <= 1000 or not 0 <= y2 <= 1000:
        raise ValueError("x and y must be between 0 and 1000")

    return x1, y1, x2, y2

def run(context):
    driver = _create_driver(context)
    x1, y1, x2, y2 = _parse_point(getattr(context, "argv", []) or [])

    float_x1 = x1 / 1000.0
    float_y1 = y1 / 1000.0

    float_x2 = x2 / 1000.0
    float_y2 = y2 / 1000.0

    float_center_x = (float_x1 + float_x2) / 2.0
    float_center_y = (float_y1 + float_y2) / 2.0

    driver.click((float_center_x, float_center_y))
    driver.wait(2)
    driver.slide((float_x1, float_y1), (float_x2, float_y2), slide_time=0.5)
    driver.wait(1)
    return {
        "success": True,
        "action": "swipe_video_progress_bar",
        "x1": float_x1,
        "y1": float_y1,
        "x2": float_x2,
        "y2": float_y2,
        "message": "swipe_video_progress_bar successfully"
    }
