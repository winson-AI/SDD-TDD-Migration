import json
import time
import urllib.request

import wda

from .apps import get_package_name

SPRINGBOARD_BUNDLE_ID = "com.apple.springboard"


def get_current_app(client: wda.Client) -> str:
    """
    Get the currently focused app name.

    Args:
        client: facebook-wda client instance.

    Returns:
        The app name if recognized, otherwise "System Home".
    """
    info = client.app_current()
    bundle_id = info.get("bundleId") if info else None
    if not bundle_id:
        raise RuntimeError("iOS foreground bundle ID unavailable")
    if bundle_id == SPRINGBOARD_BUNDLE_ID:
        return "System Home"

    from .apps import get_app_name
    name = get_app_name(bundle_id)
    if name:
        return name

    return bundle_id


def tap(client: wda.Client, x: int, y: int, delay: float | None = None) -> None:
    """Tap at the specified coordinates."""
    client.tap(x, y)
    if delay:
        time.sleep(delay)


def double_tap(client: wda.Client, x: int, y: int, delay: float | None = None) -> None:
    """Double tap at the specified coordinates."""
    client.double_tap(x, y)
    if delay:
        time.sleep(delay)


def long_press(
        client: wda.Client,
        x: int,
        y: int,
        duration: float = 2,
        delay: float | None = None,
) -> None:
    """Long press at the specified coordinates."""
    client.tap_hold(x, y, duration=duration)
    if delay:
        time.sleep(delay)


def swipe(
        client: wda.Client,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_s: float | None = None,
        delay: float | None = None,
) -> None:
    """Swipe from start to end coordinates."""
    client.swipe(start_x, start_y, end_x, end_y, duration=duration_s or 0)
    if delay:
        time.sleep(delay)


def drag(
        client: wda.Client,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        press_time: float = 1.5,
        drag_time: float = 1,
) -> None:
    """
    Drag from start to end coordinates.

    Note: facebook-wda's swipe() is actually backed by WDA's
    `/wda/dragfromtoforduration` endpoint (a genuine press-hold-then-move
    primitive, not a flick), so this is a real drag rather than an
    approximation - just routed through the same client method.
    """
    client.swipe(start_x, start_y, end_x, end_y, duration=press_time + drag_time)


def back(client: wda.Client, delay: float | None = None) -> None:
    """
    Press "back".

    Note: iOS has no system-wide back button/gesture the OS provides
    externally (unlike Android/HarmonyOS) - navigation is per-app. This
    approximates it with the standard edge-swipe-to-go-back gesture that
    UINavigationController-based screens respond to; apps not using that
    pattern (or a screen with no back stack) will simply ignore it.
    """
    width, height = client._unsafe_window_size()
    if width <= 0 or height <= 0:
        raise RuntimeError("iOS logical screen size unavailable")
    client.swipe(2, height // 2, int(width * 0.6), height // 2, duration=0.2)
    if delay:
        time.sleep(delay)


def home(client: wda.Client, delay: float | None = None) -> None:
    """Press the home button."""
    client.home()
    if delay:
        time.sleep(delay)


def launch_app(
        client: wda.Client,
        app_name: str,
        delay: float | None = None
) -> bool:
    """
    Launch an app by name.

    Args:
        client: facebook-wda client instance.
        app_name: The app name (must be in APP_PACKAGES).
        delay: Delay in seconds after launching. If None, uses configured default.

    Returns:
        True if app was launched, False if app not found.
    """
    bundle_id = get_package_name(app_name)
    if not bundle_id:
        return False
    client.app_launch(bundle_id)
    if delay:
        time.sleep(delay)
    return True


def stop_app(client: wda.Client, app_name: str) -> None:
    """Stop an app by name."""
    bundle_id = get_package_name(app_name)
    if not bundle_id:
        raise ValueError("a known app name or iOS bundle ID is required")
    client.app_stop(bundle_id)


def reset_status(client: wda.Client) -> None:
    """
    Reset the device to a known state.

    Note: unlike Android/HarmonyOS, iOS's app switcher has no scriptable
    "clear all" - closing every recent app means swiping up on each card
    individually, which needs discovering their positions in the springboard
    UI first. This just returns to the home screen, same floor as the
    Android backend when it can't find a matching "clear all" control.
    """
    client.home()
    time.sleep(1)
    client.home()


def _perform_w3c_actions(client: wda.Client, wda_url: str, actions: list) -> None:
    """
    POST a W3C WebDriver Actions payload directly to the session's /actions
    endpoint, bypassing facebook-wda's own Session.http wrapper.

    facebook-wda's `wda.Client.session()`-returned Session object sets
    `self.http = client._session_http` (the with_session=True-scoped
    request helper) in __init__, but `http` is also a @property on the base
    class - a data descriptor always wins over an instance __dict__ entry of
    the same name in Python, so `session.http` silently resolves back to the
    *non*-session-scoped client instead. The effect: any endpoint that isn't
    already wrapped as a named method (send_keys, tap, ...) and that you try
    to call via `session.http.post(...)` gets requested WITHOUT the
    `/session/<id>/` prefix, and WDA rejects it as an unknown top-level
    route. Posting directly with an explicit URL sidesteps that entirely.
    """
    url = f"{wda_url.rstrip('/')}/session/{client.session_id}/actions"
    req = urllib.request.Request(
        url,
        data=json.dumps({"actions": actions}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def _pinch_pointer_actions(pointer_id: str, start: tuple, end: tuple, duration_ms: int = 400) -> dict:
    """One finger's W3C pointer-action sequence: move to start, press, move to end, release."""
    return {
        "type": "pointer", "id": pointer_id,
        "parameters": {"pointerType": "touch"},
        "actions": [
            {"type": "pointerMove", "duration": 0, "x": start[0], "y": start[1]},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": 50},
            {"type": "pointerMove", "duration": duration_ms, "x": end[0], "y": end[1]},
            {"type": "pointerUp", "button": 0},
        ],
    }


def _pinch(
        client: wda.Client,
        wda_url: str,
        left: int, top: int, right: int, bottom: int,
        scale: float, direction: str, zoom_in: bool,
) -> None:
    cx, cy = (left + right) // 2, (top + bottom) // 2
    if direction == "horizontal":
        p1, p2 = (left, cy), (right, cy)
    else:  # diagonal
        p1, p2 = (left, top), (right, bottom)

    def scaled(pt, s):
        return cx - int((cx - pt[0]) * s), cy - int((cy - pt[1]) * s)

    corner1, corner2 = scaled(p1, 1.0), scaled(p2, 1.0)
    edge1, edge2 = scaled(p1, scale), scaled(p2, scale)

    if zoom_in:  # pinch out: fingers start together near center, move apart
        start1, start2, end1, end2 = scaled(p1, 0.15), scaled(p2, 0.15), edge1, edge2
    else:  # pinch in: fingers start at the rect's corners, move together
        start1, start2, end1, end2 = corner1, corner2, edge1, edge2

    actions = [
        _pinch_pointer_actions("finger1", start1, end1),
        _pinch_pointer_actions("finger2", start2, end2),
    ]
    _perform_w3c_actions(client, wda_url, actions)


def pinch_in(
        client: wda.Client,
        left: int,
        top: int,
        right: int,
        bottom: int,
        scale: float = 0.4,
        direction: str = "diagonal",
        delay: float | None = None,
        wda_url: str = None,
) -> None:
    """Pinch in (zoom out): fingers start at the rect's corners and move inward to `scale` of the half-extent."""
    _pinch(client, wda_url, left, top, right, bottom, scale, direction, zoom_in=False)
    if delay:
        time.sleep(delay)


def pinch_out(
        client: wda.Client,
        left: int,
        top: int,
        right: int,
        bottom: int,
        scale: float = 1.6,
        direction: str = "diagonal",
        delay: float | None = None,
        wda_url: str = None,
) -> None:
    """Pinch out (zoom in): fingers start close together near center and move outward to `scale` of the half-extent."""
    _pinch(client, wda_url, left, top, right, bottom, scale, direction, zoom_in=True)
    if delay:
        time.sleep(delay)
