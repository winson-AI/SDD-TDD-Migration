"""
Compressed Session - A custom Session implementation that automatically compresses history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import uuid

from agents.memory.session import SessionABC

if TYPE_CHECKING:
    from agents.items import TResponseInputItem

from ..memory.context_compressor import compress_context
from ..logger import logger
from ..memory.reflector import Reflector
from ..config import config_manager


class CompressedSession(SessionABC):
    """
    A session implementation that automatically compresses conversation history.
    
    This session stores conversation history and compresses it when new items are added,
    keeping only the most recent messages in full detail while summarizing older ones.
    """

    def __init__(
            self,
            session_id: str | None = None,
            auto_compress: bool = True,
    ):
        """
        Initialize the compressed session.

        Args:
            session_id: Optional session ID. If not provided, a random ID is generated.
            auto_compress: Whether to automatically compress when adding items.
        """

        config = config_manager.get_effective_config()

        self.session_id = session_id or str(uuid.uuid4())
        self.auto_compress = auto_compress
        self._items: List[TResponseInputItem] = []
        self._compressed_summary: str | None = None
        self._reflector = Reflector(config.reflection)
        self.reflector = config.reflection.enabled
        self.max_history_image = config.decision_max_history_image

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        """
        Retrieve the conversation history for this session.
        Compression is performed when adding items, so this method returns the already-compressed history.

        Args:
            limit: Maximum number of items to retrieve. If None, retrieves all items.

        Returns:
            List of input items representing the conversation history (compressed if auto_compress is enabled)
        """
        # Check if reflection is needed (only when limit is None, meaning getting all items)
        if limit is None:
            if self.reflector:
                await self._maybe_reflect()
            return self._items.copy()

        return self._items[-limit:].copy()

    def _filter_images_to_keep_recent(self, items: list[TResponseInputItem]) -> list[TResponseInputItem]:
        """
        Filter out images from the items to keep only the most recent ones.
        """
        image_positions = []

        for msg_idx, item in enumerate(items):
            content = item.get("content", "")
            if isinstance(content, list):
                for part_idx, part in enumerate(content):
                    if isinstance(part, dict) and part.get("type") in ["input_image", "image_url"]:
                        image_positions.append((msg_idx, part_idx))

        if len(image_positions) > self.max_history_image:
            positions_to_move = image_positions[:-self.max_history_image]

            filtered_items = []
            for msg_idx, item in enumerate(items):
                new_item = item.copy()
                content = new_item.get("content", "")

                if isinstance(content, list):
                    new_content = []
                    for part_idx, part in enumerate(content):
                        if (msg_idx, part_idx) not in positions_to_move:
                            new_content.append(part)
                    new_item["content"] = new_content

                filtered_items.append(new_item)

            return filtered_items

        return items

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        """
        Add new items to the conversation history.
        Compression is performed after adding items.
        Also keep only the most recent N images to avoid accumulation.

        Args:
            items: List of input items to add to the history
        """
        # Add new items first
        self._items.extend(items)

        # Filter to keep only the most recent N images
        self._items = self._filter_images_to_keep_recent(self._items)

        # Then compress if auto_compress is enabled
        if self.auto_compress:
            await self._maybe_compress()

    async def _maybe_compress(self) -> None:
        """
        Check if compression is needed and perform it.
        """
        from ..config import config_manager
        config = config_manager.get_effective_config()

        if not hasattr(config, 'context_compression') or not config.context_compression:
            return

        if not config.context_compression.enabled:
            return

        # Try to compress
        try:
            original_count = len(self._items)
            compressed_items, result = await compress_context(self._items)

            # Compress if result is returned (compression was performed)
            # The compression is based on token count, not message count
            if result:
                # Store compressed summary
                self._compressed_summary = result.compressed_text

                # Replace items with compressed version
                self._items = compressed_items

                # Reset reflection state after compression since item count changed
                self._reflector.reset_reflection(len(self._items))

                logger.info(
                    f"Session compressed: {original_count} -> {len(self._items)} items, "
                    f"tokens: {result.original_token_count} -> {result.compressed_token_count} "
                    f"({result.compression_ratio:.1%} reduction)"
                )
        except Exception as e:
            logger.warning(f"Failed to compress session: {e}")

    async def pop_item(self) -> TResponseInputItem | None:
        """
        Remove and return the most recent item from the session.
        
        Returns:
            The most recent item if it exists, None if the session is empty
        """
        if self._items:
            return self._items.pop()
        return None

    async def clear_session(self) -> None:
        """Clear all items for this session."""
        self._items = []
        self._compressed_summary = None
        # Preserve the same config when re-creating reflector
        config = self._reflector._config if self._reflector else None
        self._reflector = Reflector(config)

    def get_compressed_summary(self) -> str | None:
        """
        Get the current compressed summary.

        Returns:
            The compressed summary text, or None if no compression has been performed.
        """
        return self._compressed_summary

    async def _maybe_reflect(self) -> None:
        """
        Check if reflection is needed (at 10/20/30... items) and perform it.

        Reflection helps the agent review:
        1. Original task goal
        2. Steps completed so far
        3. Current progress
        4. Whether still on the right track
        """
        current_count = len(self._items)

        # Check if reflection is needed
        if not self._reflector.should_reflect(current_count):
            return

        logger.info(f"[Reflection] Triggering reflection at step {current_count}...")

        # Get config
        from ..config import config_manager
        config = config_manager.get_effective_config()

        # Perform reflection
        reflection_result = await self._reflector.perform_reflection(self._items, config)

        if reflection_result:
            # Mark reflection as done
            self._reflector.mark_reflection_done(current_count)

            # Create reflection message and append to the end
            reflection_message = self._reflector.create_reflection_message(reflection_result, current_count)
            self._items.append(reflection_message)

            logger.info(f"[Reflection] Reflection added at the end")


class MemorySession(CompressedSession):
    """
    A simple in-memory session with compression support.
    
    This is the default session type for most use cases.
    """
    pass
