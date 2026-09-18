import json
from types import SimpleNamespace
from typing import Any

try:
    from agents import ModelResponse
    from agents.usage import Usage
except ImportError:
    ModelResponse = None
    Usage = None
from agents.models.interface import Model
from openai.types.responses import ResponseFunctionToolCall, ResponseReasoningItem

from ..logger import logger
from .agent_registry import agent_registry

try:
    from hypium import BY, UiDriver
except ImportError:
    BY = None
    UiDriver = Any


SENSITIVE_CONTENT_ERROR_CODE = "-4316"
SENSITIVE_CONTENT_ERROR_HINTS = (
    "data_inspection_failed",
    "InternalError.Algo.DataInspectionFailed",
    "Input image data may contain inappropriate content",
)
SENSITIVE_CONTENT_REASONING = "测试过程中遇到敏感内容，需要向上滑动页面进行切换。"
SENSITIVE_CONTENT_EXECUTE_MESSAGE = "向上滑动页面进行切换"
# 连续触发敏感内容回退（滑动）的最大次数，超过此次数将不再滑动，直接抛出异常
SENSITIVE_CONTENT_FALLBACK_MAX = 3


def get_driver() -> UiDriver:
    executor_agent = agent_registry.get_executor_agent()
    if executor_agent is None:
        raise RuntimeError("executor_agent is not available")
    hdc_device = executor_agent.device
    if hdc_device is None:
        raise RuntimeError("executor_agent.device is not available")
    return hdc_device.driver


class PlannerSensitiveContentFallbackModel(Model):
    def __init__(
        self,
        base_model: Any,
    ):
        self.base_model = base_model
        self._sensitive_content_fallback_count = 0

    def __getattr__(self, item):
        return getattr(self.base_model, item)

    @staticmethod
    def _is_data_inspection_failed_error(exception: Exception) -> bool:
        error_message = str(exception)
        if SENSITIVE_CONTENT_ERROR_CODE in error_message:
            return True
        return all(hint in error_message for hint in SENSITIVE_CONTENT_ERROR_HINTS)

    @staticmethod
    def _create_response_reasoning_item(summary_text: str):
        payload = {
            "id": "rs_sensitive_content_fallback",
            "type": "reasoning",
            "summary": [{"text": summary_text, "type": "summary_text"}],
        }
        return ResponseReasoningItem(**payload)

    @staticmethod
    def _create_function_tool_call(tool_name: str, arguments: dict[str, Any]):
        payload = {
            "id": "fc_sensitive_content_fallback",
            "type": "function_call",
            "call_id": "call_sensitive_content_fallback",
            "name": tool_name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
        return ResponseFunctionToolCall(**payload)

    @classmethod
    def _build_sensitive_content_fallback_response(cls, exception: Exception):
        summary_text = f"{str(exception)} {SENSITIVE_CONTENT_REASONING}"
        output = [
            cls._create_response_reasoning_item(summary_text),
            cls._create_function_tool_call(
                "execute",
                {"message": SENSITIVE_CONTENT_EXECUTE_MESSAGE},
            ),
        ]
        if ModelResponse is not None and Usage is not None:
            return ModelResponse(
                output=output,
                usage=Usage(),
                response_id="resp_sensitive_content_fallback",
            )
        return SimpleNamespace(
            output=output,
            usage=None,
            response_id="resp_sensitive_content_fallback",
        )

    async def get_response(self, *args, **kwargs):
        try:
            response = await self.base_model.get_response(*args, **kwargs)
        except Exception as exc:
            if not self._is_data_inspection_failed_error(exc):
                raise
            self._sensitive_content_fallback_count += 1
            if self._sensitive_content_fallback_count > SENSITIVE_CONTENT_FALLBACK_MAX:
                logger.error(
                    "Sensitive content fallback limit (%s) exceeded, "
                    "stop swiping and re-raise the original exception.",
                    SENSITIVE_CONTENT_FALLBACK_MAX,
                )
                self._sensitive_content_fallback_count = 0
                raise
            logger.warning(
                "Planner model failed due to sensitive image inspection "
                "(consecutive count: %s/%s). "
                "Injecting fallback planner response to swipe away current content.",
                self._sensitive_content_fallback_count,
                SENSITIVE_CONTENT_FALLBACK_MAX,
            )
            return self._build_sensitive_content_fallback_response(exc)
        else:
            # 连续链被正常响应打断，重置计数
            self._sensitive_content_fallback_count = 0
            return response

    def stream_response(self, *args, **kwargs):
        return self.base_model.stream_response(*args, **kwargs)