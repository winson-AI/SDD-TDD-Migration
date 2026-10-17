import asyncio
import json
import os
import functools
import time
from typing import Dict, Any, Optional

from ..logger import logger

_KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "knowledge")


def normalize_coord(coord: float) -> float:
    if 0 <= coord <= 1:
        return coord
    return coord / 1000


def extract_text_from_response(response) -> str:
    """
    Extract text content from the model response.

    Args:
        response: The model response object

    Returns:
        Extracted text content
    """
    text_parts = []
    for item in response.output:
        item_type = getattr(item, "type", None)

        # Check for Reasoning (Thinking)
        if item_type == "reasoning":
            thinking_parts = []
            for summary in getattr(item, "summary", []):
                if getattr(summary, "type", None) == "summary_text":
                    thinking_parts.append(getattr(summary, "text", ""))

            if thinking_parts:
                logger.debug(f"\n[Model Thinking]\n{''.join(thinking_parts)}")

        # Check for ResponseOutputMessage (type='message', role='assistant')
        if item_type == "message" and getattr(item, "role", None) == "assistant":
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "output_text":
                    text_parts.append(getattr(content, "text", ""))

    return "".join(text_parts)


def retry_on_exception(max_retries=3, delay=1, backoff=2, exceptions=(Exception,)):
    """通用重试装饰器"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None

        return wrapper

    return decorator


async def capture_stable_snapshot(
        device,
        report_generator,
        interval: float = 1.0,
        max_attempts: int = 8,
) -> Optional[str]:
    """Poll screenshots until two consecutive captures are pixel-identical, then
    save that frame as the task's final snapshot artifact.

    Used by the "snapshot" task type to avoid capturing a mid-animation or
    still-loading frame as the deliverable. If the screen never settles within
    max_attempts, the last captured frame is saved anyway (best effort) so
    there's still something for manual review.

    Returns:
        The saved snapshot file path, or None if no screenshot could be captured.
    """
    previous = None
    for attempt in range(max_attempts):
        shot = device.get_screenshot(save_to_report=False)
        if previous is not None and shot.base64_data == previous.base64_data:
            logger.info(f"[capture_stable_snapshot] Screen stable after {attempt} check(s)")
            return report_generator.save_screenshot(
                shot.base64_data, layout_data=shot.layout_data, prefix="final_snapshot"
            )
        previous = shot
        await asyncio.sleep(interval)

    logger.warning(f"[capture_stable_snapshot] Screen never stabilized within {max_attempts} attempts, saving last frame")
    if previous is not None:
        return report_generator.save_screenshot(
            previous.base64_data, layout_data=previous.layout_data, prefix="final_snapshot"
        )
    return None


def filter_images_from_message(message: Dict[str, Any]) -> Dict[str, Any]:
    filtered_msg = message.copy()
    content = filtered_msg.get("content", "")

    if isinstance(content, list):
        filtered_content = []
        for item in content:
            if isinstance(item, dict) and item.get("type") not in ["input_image", "image_url"]:
                filtered_content.append(item)
        filtered_msg["content"] = filtered_content

    return filtered_msg


def flatten_categories(data: Dict[str, Any]) -> Dict[str, str]:
    """Flatten a {category: {name: value}} knowledge dict into one {name: value} dict.

    Skips keys starting with '_' (e.g. '_comment', '_unverified') so editorial
    notes and unconfirmed entries in the data file don't leak into lookups.
    """
    flat: Dict[str, str] = {}
    for category, entries in data.items():
        if category.startswith("_") or not isinstance(entries, dict):
            continue
        for name, value in entries.items():
            if not name.startswith("_"):
                flat[name] = value
    return flat


def load_knowledge_json(*relative_path: str) -> Dict[str, Any]:
    """Load a JSON data file from the knowledge/ directory.

    Keeps app/vendor-specific data (e.g. app name -> package name tables)
    out of source files - callers merge the returned categories themselves.
    Returns {} if the file doesn't exist.
    """
    path = os.path.join(_KNOWLEDGE_DIR, *relative_path)
    if not os.path.exists(path):
        logger.warning(f"Knowledge data file not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
