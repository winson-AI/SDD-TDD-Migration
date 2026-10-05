"""Input utilities for Android device text input."""
import uiautomator2 as u2

from ...logger import logger


def type_text(device: u2.Device, text: str) -> None:
    """
    Type text into the currently focused input field.

    Args:
        device: uiautomator2 device instance.
        text: The text to type. Supports multi-line text with newline characters.

    Note:
        uiautomator2's send_keys uses ADBKeyBoard/its own IME when available,
        falling back to the accessibility service otherwise - both handle
        multi-line text and unicode natively, unlike HarmonyOS's uiInput
        which needs manual newline splitting.
    """
    try:
        device.send_keys(text)
    except Exception as e:
        logger.error(f"[ADB] Failed to input text: {e}")
        raise


def clear_text(device: u2.Device) -> None:
    """Clear text in the currently focused input field."""
    device.clear_text()
