"""
Reflector - 定期执行反思逻辑，帮助智能体回顾任务进展和检测问题。

这个模块提供定期反思功能，当对话历史达到一定长度时（10/20/30...步），
自动触发反思，让智能体回顾：
1. 任务目标
2. 已完成步骤
3. 当前进度
4. 问题检测（重复操作、死循环、偏离目标）
5. 调整建议
"""
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from ..logger import logger
from ..utils.utils import extract_text_from_response, filter_images_from_message


@dataclass
class ReflectionConfig:
    """反思配置。

    Attributes:
        initial_step: 首次触发反思的步数（默认 10）
        interval: 反思间隔步数（默认 10，即每 10 步反思一次）
        recent_messages: 构建反思 prompt 时提取的最近消息数量（默认 10）
    """
    initial_step: int = 10
    interval: int = 10
    recent_messages: int = 10


class Reflector:
    """
    反思器 - 定期执行反思逻辑。

    当对话历史长度达到 10 的倍数时触发反思，将反思结果作为 user 消息
    添加到对话历史中，帮助智能体纠正偏离目标的行为。
    """

    REFLECTION_PROMPT = """
你是一个执行反思专家。请分析当前的对话历史，进行深度反思：

1. **任务目标**：用户的原始任务是什么？
2. **已完成步骤**：目前为止执行了哪些关键步骤？
3. **当前进度**：任务完成度如何？还有哪些步骤待完成？
4. **问题检测**：是否存在重复操作、死循环或偏离目标的情况？
5. **建议**：接下来应该如何调整策略以更好地完成任务？

请用简洁的中文输出反思结果。"""

    def __init__(self, config: Optional[ReflectionConfig] = None):
        """初始化反思器。

        Args:
            config: 反思配置，如果为 None 则使用默认配置
        """
        self._config = config or ReflectionConfig()
        self._last_reflection_step: int = 0
        self._reflection_model = None

    def should_reflect(self, current_count: int) -> bool:
        """
        检查是否应该触发反思。

        Args:
            current_count: 当前对话历史长度

        Returns:
            是否应该触发反思
        """
        # 小于初始步数不反思
        if current_count < self._config.initial_step:
            return False

        # 是间隔的倍数才反思
        if current_count % self._config.interval != 0:
            return False

        # 避免重复反思同一个步数
        if current_count == self._last_reflection_step:
            return False

        return True

    def mark_reflection_done(self, current_count: int) -> None:
        """标记某个步数已完成反思。"""
        self._last_reflection_step = current_count

    def reset_reflection(self, current_count: int) -> None:
        """重置反思状态。

        在会话压缩后调用，根据当前消息数量重新计算反思点。

        Args:
            current_count: 压缩后的消息数量
        """
        # 计算已经过了多少个反思点，设置_last_reflection_step 为最近的反思点
        # 例如：current_count=15, interval=10, 则_last_reflection_step=10
        # 这样下次反思会在 20 步触发
        if current_count >= self._config.initial_step:
            # 计算最近的反思点
            intervals_passed = (current_count - self._config.initial_step) // self._config.interval
            self._last_reflection_step = self._config.initial_step + intervals_passed * self._config.interval
        else:
            # 还没到首次反思点，完全重置
            self._last_reflection_step = 0

    def build_reflection_prompt(self, items: List[Dict[str, Any]]) -> str:
        """
        从对话历史构建反思 prompt。

        Args:
            items: 对话历史列表

        Returns:
            用于反思的 prompt 文本
        """
        # 直接转换为 JSON 格式（紧凑格式，节省 token）
        filtered_items = [filter_images_from_message(item) for item in items]
        return json.dumps(filtered_items, ensure_ascii=False)

    async def perform_reflection(
            self,
            items: List[Dict[str, Any]],
            config
    ) -> Optional[str]:
        """
        执行反思。

        Args:
            items: 当前对话历史
            config: 配置对象，包含 decision_models

        Returns:
            反思结果文本，如果失败则返回 None
        """
        # 获取模型
        model = None
        model_settings = None
        try:
            if hasattr(config, 'decision_models') and config.decision_models:
                from ..layered_agent_cli.model_factory import create_multi_model
                model, model_settings = create_multi_model(config.decision_models)
        except Exception as e:
            logger.warning(f"Failed to create reflection model: {e}")
            return None

        if not model:
            logger.warning("No model available for reflection")
            return None

        # 构建反思 prompt
        reflection_prompt = self.build_reflection_prompt(items)

        try:
            from agents.model_settings import ModelSettings
            from agents.models.interface import ModelTracing

            system_instruction = self.REFLECTION_PROMPT

            user_input = {
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": f"请分析以下执行历史并进行反思：\n{reflection_prompt}"
                }]
            }

            response = await model.get_response(
                system_instructions=system_instruction,
                input=[user_input],
                model_settings=model_settings,
                tools=[],
                output_schema=None,
                handoffs=[],
                tracing=ModelTracing.DISABLED,
                previous_response_id=None,
                conversation_id=None,
                prompt=None
            )

            reflection_text = extract_text_from_response(response)
            logger.info("reflection_text: {}".format(reflection_text))

            if response.usage:
                logger.info(f"[Reflection] Token Usage: Input={response.usage.input_tokens}, "
                            f"Output={response.usage.output_tokens}, "
                            f"Total={response.usage.total_tokens}")

            return reflection_text

        except Exception as e:
            logger.warning(f"Reflection failed: {e}")
            return None

    def create_reflection_message(self, reflection_text: str, step_count: int) -> Dict[str, str]:
        """
        创建反思消息。

        Args:
            reflection_text: 反思结果文本
            step_count: 当前步数

        Returns:
            user 消息字典
        """
        return {
            "role": "user",
            "content": f"【执行反思 - 前{step_count}步】\n{reflection_text}"
        }
