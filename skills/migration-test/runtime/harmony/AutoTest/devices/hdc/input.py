"""Input utilities for HarmonyOS device text input."""
from hypium import UiDriver, BY
from ...logger import logger


def input_text(driver: UiDriver, text: str):
    try:
        driver.input_text_on_current_cursor(text)
    except Exception as e:
        logger.error(f"[HDC] Failed to input text: {e}")
        driver.input_text((10, 10), text)


def type_text(driver: UiDriver, text: str) -> None:
    """
    Type text into the currently focused input field.

    Args:
        text: The text to type. Supports multi-line text with newline characters.
        driver: Optional HDC device ID for multi-device setups.

    Note:
        HarmonyOS uses: hdc shell uitest uiInput text "文本内容"
        This command works without coordinates when input field is focused.
        For multi-line text, the function splits by newlines and sends ENTER keyEvents.
        ENTER key code in HarmonyOS: 2054
        Recommendation: Click on the input field first to focus it, then use this function.
    """

    # Handle multi-line text by splitting on newlines
    if '\n' in text:
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if line:  # Only process non-empty lines
                # Escape special characters for shell
                escaped_line = line.replace('"', '\\"').replace("$", "\\$")
                input_text(driver, escaped_line)

            # Send ENTER key event after each line except the last one
            if i < len(lines) - 1:
                try:
                    driver.press_key(2054)

                except Exception as e:
                    logger.error(f"[HDC] ENTER keyEvent failed: {e}")
    else:
        # Single line text - original logic
        # Escape special characters for shell (keep quotes for proper text handling)
        # The text will be wrapped in quotes in the command
        escaped_text = text.replace('"', '\\"').replace("$", "\\$")

        # HarmonyOS uitest uiInput text command
        # Format: hdc shell uitest uiInput text "文本内容"
        input_text(driver, escaped_text)

    # 规避小艺输入法高情商回复
    component = driver.find_component(BY.key("clipboardSimpleCloseIcon"))
    if component:
        driver.touch(component)


def clear_text(driver: UiDriver) -> None:
    """
    Clear text in the currently focused input field.

    Args:
        driver: Optional HDC device ID for multi-device setups.

    Note:
        This method uses repeated delete key events to clear text.
        For HarmonyOS, you might also use select all + delete for better efficiency.
    """
    driver.press_combination_key(2072, 2017)

    driver.press_key(2055)
