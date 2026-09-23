"""XMind 转换管线入口。

负责判断是否需要转换、决定输出路径、调用转换/复用已有 md。
"""
import os
from typing import List, Optional

from ..config import AppConfig
from ..logger import logger
from ..storage import output_path
from .converter import XMindConvertError, convert_tree_to_md
from .xmind_parser import XMindParseError, extract_tree, parse_task_file_md


def is_xmind(path: str) -> bool:
    """判断是否为 .xmind 文件（忽略大小写）。"""
    return os.path.splitext(path)[1].lower() == ".xmind"


def resolve_output_path(xmind_path: str, output: Optional[str]) -> str:
    """确定转换后的 md 输出路径。

    --xmind-output 指向一个目录；转换后的 md 写入该目录下、与 xmind 同名的 .md 文件。
    未指定时使用当前 runner/design；没有 runner 时必须显式指定受管目录。
    """
    if output and os.path.exists(output) and not os.path.isdir(output):
        raise XMindParseError(f"--xmind-output 必须是目录，但传入的是文件: {output}")
    directory = output_path(output, default='design')
    name = os.path.splitext(os.path.basename(xmind_path))[0] + '.md'
    return str(output_path(directory / name, boundary=directory))


async def ensure_task_file(task_file: str, config: AppConfig, project_root: str,
                           output: Optional[str] = None, force_overwrite: bool = False,
                           app_name: Optional[str] = None) -> str:
    """确保输入为可用的 Markdown 用例文件路径。

    若输入为 .xmind，则：
    - 已存在对应 md 且未强制覆盖 → 直接复用，加快整体测试时间。
    - 否则调用模型转换生成 md。

    Args:
        task_file: 用户传入的任务文件路径（.md 或 .xmind）。
        config: 应用配置。
        project_root: 项目根目录。
        output: 转换输出的 md 目录（可选）。
        force_overwrite: 是否强制重新转换覆盖已有 md。
        app_name: 被测应用名称（用于转换时步骤1"打开<应用>"）。

    Returns:
        可用的 Markdown 用例文件绝对路径。
    """
    if not is_xmind(task_file):
        if not os.path.isfile(task_file):
            raise XMindParseError(f"用例文件不存在: {task_file}")
        return task_file

    if not os.path.isfile(task_file):
        raise XMindParseError(f"xmind 文件不存在: {task_file}")

    md_path = resolve_output_path(task_file, output)

    if os.path.isfile(md_path) and not force_overwrite:
        logger.info(f"[Pipeline] 已存在 {md_path}，跳过转换，直接复用已有 md")
        return md_path

    logger.info(f"[Pipeline] 开始转换 xmind: {task_file}")
    tree_text = extract_tree(task_file)
    md_text = None
    try:
        md_text = await convert_tree_to_md(project_root, tree_text, config, app_name=app_name)
    except XMindConvertError as e:
        # 若已有旧 md 且非强制覆盖，转换失败时回退复用旧文件
        if os.path.isfile(md_path) and not force_overwrite:
            logger.warning(f"[Pipeline] 转换失败({e})，回退复用已有 md: {md_path}")
            return md_path
        raise

    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(md_path))
    os.makedirs(out_dir, exist_ok=True)

    with open(output_path(md_path), "w", encoding="utf-8") as f:
        f.write(md_text)
    logger.info(f"[Pipeline] 转换完成，已写入: {md_path}")
    return md_path


def parse_cases_from_file(task_file: str) -> List[dict]:
    """从（转后的）Markdown 用例文件解析测试用例列表。"""
    return parse_task_file_md(task_file)
