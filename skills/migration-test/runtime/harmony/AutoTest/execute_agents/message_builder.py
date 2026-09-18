"""Message builder for GLM agent - copied from phone_agent.model.client.

This is an exact copy of the upstream MessageBuilder to ensure consistent behavior.
"""

import json
from typing import Any


class MessageBuilder:
    """Helper class for building conversation messages."""

    @staticmethod
    def create_system_message(content: str) -> dict[str, Any]:
        """Create a system message."""
        return {"role": "system", "content": content}

    @staticmethod
    def create_user_message(
        text: str, image_base64: str | None = None
    ) -> dict[str, Any]:
        """
        Create a user message with optional image.

        Args:
            text: Text content.
            image_base64: Optional base64-encoded image.

        Returns:
            Message dictionary.
        """
        content = []

        if image_base64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                }
            )

        content.append({"type": "text", "text": text})

        return {"role": "user", "content": content}

    @staticmethod
    def create_assistant_message(content: str) -> dict[str, Any]:
        """Create an assistant message."""
        return {"role": "assistant", "content": content}

    @staticmethod
    def remove_images_from_message(message: dict[str, Any]) -> dict[str, Any]:
        """
        Remove image content from a message to save context space.

        Args:
            message: Message dictionary.

        Returns:
            Message with images removed.
        """
        if isinstance(message.get("content"), list):
            message["content"] = [
                item for item in message["content"] if item.get("type") == "text"
            ]
        return message

    @staticmethod
    def build_screen_info(current_app: str, **extra_info) -> str:
        """
        Build screen info string for the model.

        Args:
            current_app: Current app name.
            **extra_info: Additional info to include.

        Returns:
            JSON string with screen info.
        """
        info = {"current_app": current_app, **extra_info}
        return json.dumps(info, ensure_ascii=False)

    @staticmethod
    def create_tool_call_message(
        tool_call_id: str, tool_name: str, tool_arguments: str
    ) -> dict[str, Any]:
        """
        Create a tool call message for assistant.

        Args:
            tool_call_id: Unique ID for the tool call.
            tool_name: Name of the tool being called.
            tool_arguments: JSON string of tool arguments.

        Returns:
            Assistant message with tool_calls.
        """
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_arguments,
                    },
                }
            ],
        }

    @staticmethod
    def create_tool_result_message(
        tool_call_id: str, tool_name: str, tool_result: str
    ) -> dict[str, Any]:
        """
        Create a tool result message.

        Args:
            tool_call_id: Unique ID for the tool call.
            tool_name: Name of the tool being called.
            tool_result: Result from the tool execution.

        Returns:
            Tool role message with result.
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": tool_result,
        }
