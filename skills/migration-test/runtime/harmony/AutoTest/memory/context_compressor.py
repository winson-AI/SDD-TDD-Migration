"""
Context Compressor for reducing token usage in conversation history using AI summarization.

This module provides functionality to compress conversation context by:
1. Using an AI model to summarize old conversation history
2. Keeping recent messages in full detail
3. Preserving all images as-is (not compressed)

Usage:
    from AutoTest.utils.context_compressor import compress_context
    from AutoTest.config import config_manager
    
    config = config_manager.get_effective_config()
    compressed_items = await compress_context(input_items, config)
"""

import json
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

from ..logger import logger
from ..utils.utils import extract_text_from_response, filter_images_from_message

# Compression prompt for AI summarization
COMPRESSION_PROMPT = """你是一个对话摘要专家。你的任务是将一段对话历史压缩成一个简洁的摘要，同时保留关键信息。

## 要求
1. 保留所有重要的任务进展和操作步骤
2. 保留所有关键的观察结果和发现
3. 保留所有的错误、问题和解决方案
4. 移除冗余的、重复的或无关紧要的内容
5. 使用简洁的语言，但要确保信息完整

## 输出格式
输出应该是一个简洁的摘要，格式如下：

【对话摘要】
- 任务目标：[描述用户的目标]
- 已完成步骤：[列出已完成的关键步骤]
- 当前状态：[描述当前的屏幕状态或应用状态]
- 关键发现：[记录重要的观察结果]
- 待完成任务：[列出还需要完成的任务]

请根据以下对话历史生成摘要：

{conversation_history}
"""


@dataclass
class CompressionConfig:
    """Compression configuration."""
    enabled: bool = True
    max_tokens: int = 50000
    max_recent_messages: int = 5


@dataclass
class CompressionResult:
    """Result of context compression."""
    compressed_text: str
    original_token_count: int
    compressed_token_count: int
    compression_ratio: float


def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """
    Estimate the total tokens in the message list by converting to JSON.
    
    This is a more accurate method that counts all fields including:
    - role, content, id, tool_call_id, tool_calls, etc.
    All these fields are sent to the model, so they should be counted.
    
    Args:
        messages: List of message dictionaries
        
    Returns:
        Estimated token count (roughly 3-4 chars per token for mixed Chinese/English)
    """
    import json

    # Convert messages to JSON string
    # This includes all fields: id, role, content, tool_calls, tool_call_id, etc.
    json_str = json.dumps(messages, ensure_ascii=False)

    # Estimate tokens: roughly 3.5 chars per token for mixed Chinese/English
    # For pure Chinese it's about 3 chars/token, for English about 4 chars/token
    estimated_tokens = len(json_str) // 3

    return estimated_tokens


def count_images_in_messages(messages: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
    """
    Count and extract image data from messages.
    
    Args:
        messages: List of message dictionaries
        
    Returns:
        List of (message_index, base64_image_data) tuples
    """
    images = []

    for idx, msg in enumerate(messages):
        content = msg.get("content", "")

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in ["input_image", "image_url"]:
                    image_url = item.get("image_url", "")
                    # Extract base64 data from data URL
                    if image_url.startswith("data:image"):
                        base64_data = image_url.split(",", 1)[-1]
                        images.append((idx, base64_data))
                    else:
                        images.append((idx, image_url))

    return images


def extract_text_from_messages(messages: List[Dict[str, Any]]) -> str:
    """
    Extract text content from messages for compression.
    
    Args:
        messages: List of message dictionaries
        
    Returns:
        Concatenated text content
    """
    text_parts = []

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, str):
            text_parts.append(f"[{role}]: {content}")
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    text_parts.append(f"[{role}]: {text}")

    return "\n".join(text_parts)


def _fallback_compression(text: str) -> str:
    """Fallback compression when AI is not available."""
    # Simple truncation as fallback
    if len(text) <= 5000:
        return text

    # Take first and last parts
    first_part = text[:3000]
    last_part = text[-2000:]

    return f"{first_part}\n\n... [中间内容已省略] ...\n\n{last_part}"


async def _compress_with_ai(text_to_compress: str, model) -> str:
    """
    Use AI to compress/summarize the given text.
    
    Args:
        text_to_compress: The text content to compress
        model: The AI model to use for compression
        
    Returns:
        Compressed/summarized text
    """
    import time
    from agents.model_settings import ModelSettings
    from agents.models.interface import ModelTracing

    start_time = time.time()
    step_start = start_time

    if not model:
        logger.warning("No model available for AI compression, using fallback")
        return _fallback_compression(text_to_compress)

    try:
        # Prepare the prompt
        prompt = COMPRESSION_PROMPT.format(conversation_history=text_to_compress)

        now = time.time()
        logger.debug(f"[_compress_with_ai] Prompt preparation took {now - step_start:.3f}s")
        step_start = now

        # Build LLM input
        system_instruction = (
            "你是一位对话摘要专家。你的任务是将一段对话历史压缩成一个简洁的摘要，同时保留关键信息。\n"
            "要求：\n"
            "1. 保留所有重要的任务进展和操作步骤\n"
            "2. 保留所有关键的观察结果和发现\n"
            "3. 保留所有的错误、问题和解决方案\n"
            "4. 移除冗余的、重复的或无关紧要的内容\n"
            "5. 使用简洁的语言，但要确保信息完整\n"
            "\n"
            "输出格式：\n"
            "【对话摘要】\n"
            "- 任务目标：[描述用户的目标]\n"
            "- 已完成步骤：[列出已完成的关键步骤]\n"
            "- 当前状态：[描述当前的屏幕状态或应用状态]\n"
            "- 关键发现：[记录重要的观察结果]\n"
            "- 待完成任务：[列出还需要完成的任务]"
        )

        user_input = {
            "role": "user",
            "content": [{"type": "input_text", "text": f"请根据以下对话历史生成摘要：\n{prompt}"}]
        }

        now = time.time()
        logger.debug(f"[_compress_with_ai] Building request took {now - step_start:.3f}s")
        step_start = now

        # Call model directly using get_response
        response = await model.get_response(
            system_instructions=system_instruction,
            input=[user_input],
            model_settings=ModelSettings(),
            tools=[],
            output_schema=None,
            handoffs=[],
            tracing=ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None
        )

        now = time.time()
        logger.debug(f"[_compress_with_ai] model.get_response() took {now - step_start:.3f}s")

        # Extract text from response
        summary = extract_text_from_response(response)

        if response.usage:
            logger.info(f"[ContextCompressor] Summary Token Usage: Input={response.usage.input_tokens}, "
                        f"Output={response.usage.output_tokens}, "
                        f"Total={response.usage.total_tokens}")

        total_time = time.time() - start_time
        logger.info(f"AI compression completed. Original length: {len(text_to_compress)}, "
                    f"Compressed length: {len(summary)}, total time: {total_time:.3f}s")

        return summary

    except Exception as e:
        logger.warning(f"AI compression failed: {e}, using fallback")
        return _fallback_compression(text_to_compress)


async def compress_context(
        messages: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[CompressionResult]]:
    """
    Compress context messages using AI summarization.
    
    This is the main entry point for context compression. It:
    1. Checks if compression is enabled and needed
    2. Keeps only the most recent N messages
    3. Uses AI to summarize older messages
    4. Returns the compressed message list (without images)
    
    Note: Configuration is automatically loaded from the global config_manager.
    Note: Images are NOT preserved during compression.
    
    Args:
        messages: Original message list to compress
        
    Returns:
        Tuple of (compressed messages, compression result info)
        If no compression was performed, returns (original messages, None)
    """
    import time
    start_time = time.time()
    step_start = start_time

    # Get config from global config_manager
    from ..config import config_manager
    config = config_manager.get_effective_config()

    now = time.time()
    logger.debug(f"[compress_context] Config loading took {now - step_start:.3f}s")
    step_start = now

    # Check if compression is enabled
    if not hasattr(config, 'context_compression') or not config.context_compression:
        logger.debug(f"[compress_context] Compression disabled by config, took {time.time() - start_time:.3f}s total")
        return messages, None

    compression_config = config.context_compression
    if not compression_config.enabled:
        logger.debug(f"[compress_context] Compression disabled, took {time.time() - start_time:.3f}s total")
        return messages, None

    if not messages:
        logger.debug(f"[compress_context] No messages to compress, took {time.time() - start_time:.3f}s total")
        return messages, None

    # Check if compression is needed based on token count
    estimated_tokens = estimate_tokens([filter_images_from_message(msg) for msg in messages])
    now = time.time()
    logger.debug(f"[compress_context] Token estimation ({estimated_tokens} tokens) took {now - step_start:.3f}s")
    step_start = now

    if estimated_tokens <= compression_config.max_tokens:
        logger.debug(f"No compression needed: {estimated_tokens} tokens <= {compression_config.max_tokens} "
                     f"threshold, took {time.time() - start_time:.3f}s total")
        return messages, None

    logger.info(f"Compression triggered: {estimated_tokens} tokens > {compression_config.max_tokens} threshold")

    # Always keep the first user message (the initial task)
    first_message = messages[0] if messages else None

    # Determine which messages to keep in full detail (only the most recent N)
    messages_to_keep = []
    if compression_config.max_recent_messages > 0:
        # Keep the last N messages
        start_idx = max(1, len(messages) - compression_config.max_recent_messages)  # Start from 1 to skip first message
        messages_to_keep = messages[start_idx:]

    # Find messages to compress (older messages, excluding the first one)
    messages_to_compress = [filter_images_from_message(msg) for msg in
                            messages[1:len(messages) - len(messages_to_keep)]]

    now = time.time()
    logger.debug(f"[compress_context] Message preparation took {now - step_start:.3f}s")
    step_start = now

    if not messages_to_compress:
        logger.info(f"No messages to compress, keeping all {len(messages)} messages, "
                    f"took {time.time() - start_time:.3f}s total")
        return messages, None

    logger.info(f"Compressing {len(messages_to_compress)} old messages using AI")

    # Extract text from messages to compress
    text_to_compress = extract_text_from_messages(messages_to_compress)
    original_token_count = estimate_tokens(messages_to_compress)

    now = time.time()
    logger.debug(f"[compress_context] Text extraction ({len(text_to_compress)} chars) took {now - step_start:.3f}s")
    step_start = now

    # Create model from config for compression
    model = await create_compression_model(config)

    now = time.time()
    logger.debug(f"[compress_context] Model creation took {now - step_start:.3f}s")
    step_start = now

    # Use AI to compress
    compressed_summary = await _compress_with_ai(text_to_compress, model)

    now = time.time()
    logger.debug(f"[compress_context] AI compression ({len(compressed_summary)} chars) took {now - step_start:.3f}s")
    step_start = now

    # Build new message list
    new_messages = []

    # Always keep the first message (user's initial task)
    if first_message:
        new_messages.append(first_message)

    # Add the compressed summary as a system message
    new_messages.append({
        "role": "system",
        "content": f"【历史对话摘要 - AI 压缩】\n{compressed_summary}"
    })

    # Add the kept messages (only the most recent N, no images preserved)
    new_messages.extend(messages_to_keep)

    compressed_token_count = estimate_tokens(new_messages)

    now = time.time()
    logger.debug(f"[compress_context] Result building took {now - step_start:.3f}s")
    step_start = now

    # Only use compression if it actually reduces token count
    # If compression increases tokens, return original messages
    if compressed_token_count >= original_token_count:
        logger.info(
            f"Compression skipped: compressed tokens ({compressed_token_count}) >= "
            f"original tokens ({original_token_count}), total time: {time.time() - start_time:.3f}s"
        )
        return messages, None

    compression_ratio = (original_token_count - compressed_token_count) / max(original_token_count, 1)

    result = CompressionResult(
        compressed_text=compressed_summary,
        original_token_count=original_token_count,
        compressed_token_count=compressed_token_count,
        compression_ratio=compression_ratio,
    )

    total_time = time.time() - start_time
    logger.info(f"Compressed messages from {len(messages)} to {len(new_messages)} items, "
                f"tokens: {original_token_count} -> {compressed_token_count}, "
                f"ratio: {compression_ratio:.1%}, total time: {total_time:.3f}s")

    return new_messages, result


async def create_compression_model(config):
    """
    Create a model for compression from config.
    
    Args:
        config: AppConfig instance containing decision_models configuration
        
    Returns:
        A model instance or None if creation failed
    """
    if not hasattr(config, 'decision_models') or not config.decision_models:
        logger.warning("No decision_models config available for compression")
        return None

    try:
        from ..layered_agent_cli.model_factory import create_multi_model
        model, _ = create_multi_model(config.decision_models)
        logger.info("Created compression model from decision_models config")
        return model
    except Exception as e:
        logger.warning(f"Failed to create compression model: {e}")
        return None
