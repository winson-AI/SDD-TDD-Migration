"""解析 .xmind 文件，提取测试用例主题树。

.xmind 本质上是 ZIP 压缩包，其中 content.json（新格式）包含完整的主题树结构。
"""
import json
import os
import tempfile
import zipfile
from typing import List, Optional

from ..logger import logger


class XMindParseError(Exception):
    """XMind 文件解析异常。"""


def _build_tree(node, depth: int, lines: List[str]) -> None:
    """递归把节点转成缩进文本行。"""
    title = node.get("title", "")
    indent = "  " * depth
    line = indent + title
    labels = node.get("labels")
    if labels:
        line += "  [" + ",".join(labels) + "]"
    lines.append(line)

    children = node.get("children")
    if children and children.get("attached"):
        for child in children["attached"]:
            _build_tree(child, depth + 1, lines)


def extract_tree(xmind_path: str) -> str:
    """从 .xmind 文件提取主题树文本。

    Args:
        xmind_path: .xmind 文件路径。

    Returns:
        缩进后的主题树文本（UTF-8 字符串）。

    Raises:
        XMindParseError: 文件不存在或解析失败。
    """
    if not os.path.exists(xmind_path):
        raise XMindParseError(f"xmind 文件不存在: {xmind_path}")

    content_json_path = None
    try:
        with zipfile.ZipFile(xmind_path, "r") as zf:
            names = zf.namelist()
            if "content.json" in names:
                content_json_path = "content.json"
            elif "content.xml" in names:
                raise XMindParseError("该 xmind 只有 content.xml（旧格式），暂不支持")
            else:
                raise XMindParseError(f"xmind 中未找到 content.json: {xmind_path}")

            with zf.open(content_json_path) as f:
                text = f.read().decode("utf-8")
    except zipfile.BadZipFile:
        raise XMindParseError(f"文件不是有效的 xmind/zip 包: {xmind_path}")
    except Exception as e:
        raise XMindParseError(f"读取 xmind 失败: {e}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise XMindParseError(f"content.json 解析失败: {e}")

    if not isinstance(data, list) or not data:
        raise XMindParseError("content.json 结构异常：应为非空列表")

    lines: List[str] = []
    for sheet in data:
        root_topic = sheet.get("rootTopic")
        if not root_topic:
            raise XMindParseError("content.json 中未找到 rootTopic")
        _build_tree(root_topic, 0, lines)
    tree_text = "\n".join(lines)
    logger.info(f"[XMindParse] 提取主题树共 {len(lines)} 行")
    return tree_text


def parse_task_file_md(md_path: str) -> List[dict]:
    """解析标准 Markdown 测试用例文件（与 main.parse_task_file 兼容）。

    Args:
        md_path: Markdown 文件路径。

    Returns:
        测试用例列表：[{'name': ..., 'task': ...}]
    """
    if not os.path.isfile(md_path):
        raise XMindParseError(f"md 文件不存在: {md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    case_blocks = content.split("---")
    test_cases = []
    for block in case_blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("## 用例描述："):
            lines = block.split("\n", 1)
            if len(lines) < 2:
                continue
            case_name = lines[0].replace("## 用例描述：", "").strip()
            task_content = lines[1].strip()
            if case_name and task_content:
                test_cases.append({"name": case_name, "task": task_content})
    return test_cases