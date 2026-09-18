import functools
import time
from typing import Dict, Any

from ..logger import logger


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
