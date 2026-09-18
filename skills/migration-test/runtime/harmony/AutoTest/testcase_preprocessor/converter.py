"""调用大模型把 XMind 主题树改写为标准 Markdown 测试用例。

复用现有 model_factory 的客户端/配置构建逻辑，但使用普通文本模型
（不走 MultiProviderModel 的 tool-calling 判定），与用例实际执行流程
（decision/playback）完全分离。
"""
from typing import List, Optional, Tuple

from agents import Agent, Runner
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

from ..config import AppConfig
from ..logger import logger
from ..layered_agent_cli.model_factory import create_client_from_dict
from .skill_prompt import build_prompts


class XMindConvertError(Exception):
    """XMind 转换异常。"""


def _resolve_model_config(config: AppConfig) -> List[dict]:
    """解析转换用的模型配置。

    优先使用独立配置的 xmind_convert_model；若未配置，回退到 decision_model。
    """
    if getattr(config, "xmind_convert_models", None):
        return config.xmind_convert_models
    if getattr(config, "decision_models", None):
        logger.info("[Convert] 未配置独立转换模型，回退使用 decision_model")
        return config.decision_models
    raise XMindConvertError("未配置 xmind 转换模型，且无 decision_model 可回退")


def _build_text_models(model_configs: List[dict]) -> Tuple[list, Optional[object]]:
    """构建普通文本聊天模型列表（含各模型自身 settings）。

    返回 ([(model, settings), ...], default_settings)。
    """
    models_data = []
    default_settings = None
    for conf in model_configs:
        try:
            client, settings = create_client_from_dict(conf)
            model = OpenAIChatCompletionsModel(
                model=conf.get("name", ""),
                openai_client=client,
            )
            models_data.append((model, settings))
            if default_settings is None:
                default_settings = settings
        except Exception as e:
            logger.error(f"[Convert] 初始化模型失败: {conf.get('name', 'unknown')}, error: {e}")
    if not models_data:
        raise XMindConvertError("没有可用的转换模型")
    return models_data, default_settings


async def convert_tree_to_md(project_root: str, tree_text: str, config: AppConfig,
                             app_name: Optional[str] = None) -> str:
    """将主题树文本改写为标准 Markdown 测试用例。

    Args:
        project_root: 项目根目录，用于定位技能文件。
        tree_text: 从 xmind 提取的主题树文本。
        config: 应用配置。
        app_name: 被测应用名称（用于步骤1"打开<应用>"）。

    Returns:
        生成的 Markdown 测试用例文本。

    Raises:
        XMindConvertError: 模型调用失败。
    """
    system_prompt, user_message = build_prompts(project_root, tree_text, app_name=app_name)

    try:
        model_configs = _resolve_model_config(config)
        models_data, default_settings = _build_text_models(model_configs)
    except Exception as e:
        raise XMindConvertError(f"初始化转换模型失败: {e}") from e

    logger.info("[Convert] 正在调用大模型改写测试用例...")

    last_exception = None
    for model, settings in models_data:
        try:
            agent = Agent(
                name="XMindTestcaseConverter",
                instructions=system_prompt,
                model=model,
                model_settings=settings,
            )
            result = await Runner.run(agent, user_message)
            md_text = str(result.final_output).strip()
            if not md_text or not md_text.startswith("## 用例描述"):
                raise XMindConvertError("未生成有效的用例描述")
            logger.info(f"[Convert] 模型改写完成，输出 {len(md_text)} 字符")
            return md_text
        except Exception as e:
            last_exception = e
            logger.warning(f"[Convert] 模型 {getattr(model, 'model', 'unknown')} 调用失败: {e}，尝试下一个")

    raise XMindConvertError(f"所有转换模型均失败: {last_exception}")