import os
import json
import re
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
from ..logger import logger


# 匹配成对引号包围的内容：英文 "..."、中文 “...”、英文 '...'
# 分别匹配避免左右引号被当作独立可互换字符
# 替换为"文字"时会同时吃掉紧跟的"文字"字面量，避免产生"文字文字"重复
_QUOTED_CONTENT_PATTERN = re.compile(r'(?:"([^"]+)"|“([^”]+)”|‘([^’]+)’)(?:文字)?')

# 搜索框/输入框场景关键字
_SEARCH_BOX_KEYWORDS = ("搜索框", "输入框")

# 输入动作模式：输入动作后紧跟引号（如 输入"xxx、输入“xxx），此类需保留实际文本
_INPUT_ACTION_PATTERN = re.compile(r'输入\s*["“”\']')


def _desensitize_search_box_message(message: str) -> str:
    """对涉及搜索框/输入框操作的 message 进行脱敏。

    规则：
    - message 包含"搜索框"或"输入框"关键字
    - 但若为"输入"动作（输入后紧跟引号，如 在输入框输入"xxx"），保留实际文本
    - 将成对引号（英文"/中文“”/英文'）包围的具体内容统一替换为"文字"

    Args:
        message: 原始 message 字符串

    Returns:
        脱敏后的 message；若不匹配脱敏条件则原样返回
    """
    if not message or not isinstance(message, str):
        return message

    if not any(kw in message for kw in _SEARCH_BOX_KEYWORDS):
        return message

    if _INPUT_ACTION_PATTERN.search(message):
        return message

    def _replace(match: re.Match) -> str:
        # 替换后的"文字"不加引号（移除原引号）
        return "文字"

    return _QUOTED_CONTENT_PATTERN.sub(_replace, message)


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""
    order: int
    tool_name: str
    arguments: Dict[str, Any]
    result: str
    timestamp: str
    # 工具内部可能触发多步 click，按顺序记录每一步的缓存
    # 单步操作时列表长度为 1；非点击类工具为 None/空
    click_caches: Optional[List[Dict[str, Any]]] = None


@dataclass
class RecordingSession:
    """Complete recording session for a task."""
    task: str
    task_hash: str
    total_calls: int
    recordings: List[Dict[str, Any]]
    created_at: str


class ToolRecorder:
    """
    Records MCP tool calls during agent execution.

    Records are saved as JSON files with task hash as filename,
    enabling later playback without calling the model.
    """

    def __init__(self, task: str, memory_dir: str = "memory"):
        """
        Initialize the recorder.

        Args:
            task: The task description, used to generate hash for filename
            memory_dir: Directory to save recordings (default: "memory")
        """
        self.task = task
        self.task_hash = self._generate_hash(task)
        self.memory_dir = memory_dir
        self._call_records: List[ToolCallRecord] = []
        self._call_order = 0

        os.makedirs(self.memory_dir, exist_ok=True)

        logger.info(f"[ToolRecorder] Initialized for task: {task}")
        logger.info(f"[ToolRecorder] Hash: {self.task_hash}")

    def _generate_hash(self, task: str, length: int = 16) -> str:
        """
        Generate a hash from task string.

        Args:
            task: Task description
            length: Length of hash to return (10-20)

        Returns:
            Hex string of hash (default 16 chars)
        """
        if length < 10 or length > 20:
            length = 16

        hash_obj = hashlib.md5(task.encode('utf-8'))
        return hash_obj.hexdigest()[:length]

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        click_caches: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Record a tool call.

        Args:
            tool_name: Name of the tool being called
            arguments: Arguments passed to the tool
            result: Result returned by the tool
            click_caches: Optional list of click cache info for click operations.
                          单步操作时列表长度为 1；非点击类工具为 None/空。
        """
        self._call_order += 1

        # 对涉及搜索框/输入框操作的 message 进行脱敏（保留输入动作的实际文本）
        if tool_name == "execute" and isinstance(arguments, dict):
            message = arguments.get("message")
            if isinstance(message, str):
                desensitized = _desensitize_search_box_message(message)
                if desensitized != message:
                    logger.info(
                        f"[ToolRecorder] Desensitize search-box message BEFORE: {message}"
                    )
                    logger.info(
                        f"[ToolRecorder] Desensitize search-box message AFTER:  {desensitized}"
                    )
                    arguments = {**arguments, "message": desensitized}

        record = ToolCallRecord(
            order=self._call_order,
            tool_name=tool_name,
            arguments=arguments,
            result=str(result),
            timestamp=datetime.now().isoformat(timespec='milliseconds'),
            click_caches=click_caches
        )
        self._call_records.append(record)

        logger.info(
            f"[ToolRecorder] Recorded call #{self._call_order}: "
            f"{tool_name}({arguments})"
        )
        if click_caches:
            logger.info(
                f"[ToolRecorder]   Click caches: {len(click_caches)} sub-steps, "
                f"use_xpath_flags={[c.get('use_xpath') for c in click_caches if c]}"
            )

    def get_record_path(self) -> str:
        """Get the path where the recording will be saved."""
        return os.path.join(self.memory_dir, f"{self.task_hash}.json")

    def save_to_file(self) -> str:
        """
        Save all recorded tool calls to JSON file.

        Returns:
            Path to the saved file
        """
        recordings = [asdict(record) for record in self._call_records]
        # 后处理：删除冗余的"点击视频画面唤起播控"步骤
        recordings = self._cleanup_redundant_steps(recordings)

        session = RecordingSession(
            task=self.task,
            task_hash=self.task_hash,
            total_calls=len(recordings),
            recordings=recordings,
            created_at=datetime.now().isoformat(timespec='seconds')
        )

        file_path = self.get_record_path()

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(session), f, ensure_ascii=False, indent=2)

            logger.info(
                f"[ToolRecorder] Saved {len(recordings)} calls to {file_path}"
            )
            return file_path

        except Exception as e:
            logger.error(f"[ToolRecorder] Failed to save recording: {e}")
            raise

    @staticmethod
    def _cleanup_redundant_steps(recordings: List[Dict]) -> List[Dict]:
        """后处理：删除冗余的"点击视频画面唤起播控"步骤。

        对于连续的、以"点击视频画面中央唤出播控层"等模式开头的 execute 步骤，
        只保留最后一条（优先保留带"查看"的），删除其余冗余步骤。
        """
        # 匹配"点击视频画面中央唤出播控层"类操作的前缀（含变体写法）
        VIDEO_CONTROL_PREFIXES = [
            "点击视频画面中央唤",
            "点击视频中央画面唤",
            "点击视频画面唤",
            "点击视频画面中央，唤",
            "点击视频画面，唤"
        ]

        def is_video_control_click(recording):
            if recording.get('tool_name') != 'execute':
                return False
            message = recording.get('arguments', {}).get('message', '')
            return any(message.startswith(p) for p in VIDEO_CONTROL_PREFIXES)

        def has_view(recording):
            message = recording.get('arguments', {}).get('message', '')
            return "查看" in message

        # 找到连续匹配的步骤组，每组只保留一条
        to_remove = set()
        i = 0
        while i < len(recordings):
            if not is_video_control_click(recordings[i]):
                i += 1
                continue

            # 找到连续匹配组的结束位置
            group_start = i
            group_end = i
            while group_end + 1 < len(recordings) and is_video_control_click(recordings[group_end + 1]):
                group_end += 1

            if group_end > group_start:
                # 多条连续匹配，优先保留最后一条带"查看"的
                keep_idx = None
                for j in range(group_end, group_start - 1, -1):
                    if has_view(recordings[j]):
                        keep_idx = j
                        break
                if keep_idx is None:
                    keep_idx = group_end  # 没有带"查看"的，保留最后一条

                for j in range(group_start, group_end + 1):
                    if j != keep_idx:
                        to_remove.add(j)

            i = group_end + 1

        if to_remove:
            removed_orders = [recordings[idx].get('order') for idx in sorted(to_remove)]
            new_recordings = [rec for idx, rec in enumerate(recordings) if idx not in to_remove]
            logger.info(
                f"[ToolRecorder] 后处理删除了 {len(to_remove)} 条冗余步骤: orders={removed_orders}"
            )
            return new_recordings

        return recordings

    @staticmethod
    def load_from_file(file_path: str) -> Optional[RecordingSession]:
        """
        Load a recording session from JSON file.

        Args:
            file_path: Path to the JSON file

        Returns:
            RecordingSession object or None if loading fails
        """
        if not os.path.exists(file_path):
            logger.error(f"[ToolRecorder] File not found: {file_path}")
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            session = RecordingSession(
                task=data['task'],
                task_hash=data['task_hash'],
                total_calls=data['total_calls'],
                recordings=data['recordings'],
                created_at=data.get('created_at', '')
            )

            logger.info(
                f"[ToolRecorder] Loaded {session.total_calls} calls from {file_path}"
            )
            return session

        except Exception as e:
            logger.error(f"[ToolRecorder] Failed to load recording: {e}")
            return None

    @staticmethod
    def load_by_task(task: str, memory_dir: str = "memory") -> Optional[RecordingSession]:
        """
        Load recording by task hash.

        Args:
            task: Task hash to look for (or full task description)

        Returns:
            RecordingSession object or None if not found
        """
        hash_obj = hashlib.md5(task.encode('utf-8'))
        task_hash = hash_obj.hexdigest()[:16]

        file_path = os.path.join(memory_dir, f"{task_hash}.json")

        if not os.path.exists(file_path):
            logger.warning(
                f"[ToolRecorder] No recording found for hash: {task_hash}"
            )
            return None

        return ToolRecorder.load_from_file(file_path)

    @staticmethod
    def find_recording(
        identifier: str,
        memory_dir: str = "memory"
    ) -> Optional[RecordingSession]:
        """
        Find recording by hash or file path.

        Args:
            identifier: Task hash (16 chars) or file path
            memory_dir: Directory to search in

        Returns:
            RecordingSession object or None if not found
        """
        if os.path.sep in identifier or os.path.exists(identifier):
            if os.path.exists(identifier):
                return ToolRecorder.load_from_file(identifier)
            else:
                return ToolRecorder.load_from_file(
                    os.path.join(memory_dir, f"{identifier}.json")
                )
        else:
            return ToolRecorder.load_by_task(identifier, memory_dir)

    def get_recordings(self) -> List[ToolCallRecord]:
        """Get all recorded tool calls."""
        return self._call_records.copy()

    def clear(self) -> None:
        """Clear all recorded calls."""
        self._call_records.clear()
        self._call_order = 0
        logger.info("[ToolRecorder] Recording cleared")
