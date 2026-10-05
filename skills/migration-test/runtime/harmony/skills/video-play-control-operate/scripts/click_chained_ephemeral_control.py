from AutoTest.devices.device_protocol import skill_driver as _create_driver


def _parse_points(argv):
    if len(argv) != 4:
        raise ValueError("Usage: click_chained_ephemeral_control.py <x1> <y1> <x2> <y2>")

    try:
        x1 = int(argv[0])
        y1 = int(argv[1])
        x2 = int(argv[2])
        y2 = int(argv[3])
    except ValueError as e:
        raise ValueError("x1, y1, x2, y2 must be integers") from e

    for name, val in [("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)]:
        if not 0 <= val <= 1000:
            raise ValueError(f"{name} must be between 0 and 1000")

    return x1, y1, x2, y2


def run(context):
    driver = _create_driver(context)
    x1, y1, x2, y2 = _parse_points(getattr(context, "argv", []) or [])

    float_x1 = x1 / 1000.0
    float_y1 = y1 / 1000.0
    float_x2 = x2 / 1000.0
    float_y2 = y2 / 1000.0

    driver.click((float_x1, float_y1))
    driver.wait(2)
    
    driver.click((float_x1, float_y1))
    driver.wait(3)

    driver.click((float_x2, float_y2))
    driver.wait(2)

    return {
        "success": True,
        "action": "click_chained_ephemeral_control",
        "x1": float_x1,
        "y1": float_y1,
        "x2": float_x2,
        "y2": float_y2,
        "message": "click_chained_ephemeral_control successfully"
    }