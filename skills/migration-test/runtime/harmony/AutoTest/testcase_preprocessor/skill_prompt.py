"""加载 xmind-to-testcase 技能说明，组装 LLM 提示词。

技能文件：AutoTest/testcase_preprocessor/xmind-to-testcase/SKILL.md
该技能定义了将 XMind 思维导图用例改写为标准书面测试用例的完整规则。
"""
import os
from typing import Optional, Tuple

from ..logger import logger

# 技能文件位于本包目录下（不依赖项目 .opencode 目录）
SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xmind-to-testcase")
SKILL_FILE = os.path.join(SKILL_DIR, "SKILL.md")

# 系统提示词前缀：引导模型作为用例改写专家
SYSTEM_PREFIX = (
    "你是一名专业的软件测试用例撰写专家。"
    "用户会提供一份 XMind 思维导图中提取的测试用例主题树（含 Feature / Scenario / Given / When / Then 节点），"
    "请你严格遵循下方《技能说明》中的改写规则，把它改写为标准书面测试用例。\n"
    "输出只需包含 Markdown 用例正文（每个用例以 `## 用例描述：...` 开头，用例之间用 `---` 分隔），不要输出额外解释。"
)


def _strip_frontmatter(content: str) -> str:
    """去掉 SKILL.md 的 YAML frontmatter，只保留正文。"""
    content = content.strip()
    if content.startswith("---"):
        lines = content.split("\n")
        end_index = -1
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = i
                break
        if end_index != -1:
            return "\n".join(lines[end_index + 1:]).strip()
    return content


def resolve_skill_path(project_root: str) -> str:
    """解析技能文件路径。

    Args:
        project_root: 项目根目录（保留参数以兼容，未实际使用）。

    Returns:
        SKILL.md 的绝对路径。
    """
    # 优先环境变量
    env_path = os.environ.get("XMIND_TO_TESTCASE_SKILL")
    if env_path:
        return env_path
    return SKILL_FILE


def load_skill_content(project_root: str) -> str:
    """加载技能说明正文。

    Args:
        project_root: 项目根目录。

    Returns:
        技能正文（去掉 frontmatter）。找不到时返回空字符串但记录日志。
    """
    skill_path = resolve_skill_path(project_root)
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
        body = _strip_frontmatter(content)
        logger.info(f"[Skill] 加载技能说明: {skill_path}")
        return body
    except FileNotFoundError:
        logger.warning(f"[Skill] 技能文件不存在: {skill_path}，将使用内置默认规则")
        return ""
    except Exception as e:
        logger.error(f"[Skill] 加载技能文件失败: {skill_path}, error: {e}")
        return ""


def build_prompts(project_root: str, tree_text: str, app_name: Optional[str] = None) -> Tuple[str, str]:
    """构建系统提示词与用户消息。

    Args:
        project_root: 项目根目录，用于定位技能文件。
        tree_text: 从 xmind 提取的主题树文本。
        app_name: 被测应用名称；非空时明确告知模型，用于步骤1"打开<应用>"，
                  避免从模块名自行推断。

    Returns:
        (system_prompt, user_message)
    """
    skill_body = load_skill_content(project_root)
    if skill_body:
        system_prompt = (
            SYSTEM_PREFIX
            + "\n\n========== 技能说明 Start ==========\n"
            + skill_body
            + "\n========== 技能说明 End =========="
        )
    else:
        # 技能文件缺失时的内置兜底规则
        system_prompt = (
            SYSTEM_PREFIX
            + "\n改写规则：\n"
            "1. 每个 Scenario 生成一条用例，格式：`## 用例描述：<标题>（<优先级>）`\n"
            "2. 步骤 1 固定为“打开<被测应用>”，后续为纯动作步骤，用 `1、` 编号。\n"
            "3. 预期结果单行，多个结果用 `；` 连接。\n"
            "4. 用例之间用 `---` 分隔。"
        )

    user_parts = []
    if app_name and app_name.strip():
        app_name = app_name.strip()
        user_parts.append(
            "被测应用名称：{app_name}。所有用例的“步骤 1”必须为：打开{app_name}。"
            "不要从思维导图模块名自行推断应用名，以本处提供的为准。".format(app_name=app_name)
        )
    user_parts.append("以下是 XMind 主题树内容：\n\n" + tree_text)
    user_message = "\n\n".join(user_parts)
    return system_prompt, user_message