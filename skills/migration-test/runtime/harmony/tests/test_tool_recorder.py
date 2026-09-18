"""tool_recorder.py 核心代码单元测试。

测试覆盖范围：
1. _desensitize_search_box_message — 搜索框/输入框消息脱敏
2. ToolRecorder._generate_hash        — 任务哈希生成
3. ToolRecorder.__init__             — 初始化
4. ToolRecorder.record_tool_call      — 工具调用记录 + 脱敏
5. ToolRecorder.get_record_path       — 录制文件路径
6. ToolRecorder.save_to_file          — 保存为 JSON
7. ToolRecorder._cleanup_redundant_steps — 冗余步骤清理
8. ToolRecorder.load_from_file        — 从文件加载
9. ToolRecorder.load_by_task          — 按任务加载
10. ToolRecorder.find_recording       — 智能查找录制
11. ToolRecorder.get_recordings       — 获取所有记录
12. ToolRecorder.clear                — 清空记录
"""

import json
import os
import tempfile
import hashlib
from pathlib import Path

import pytest

from AutoTest.memory.tool_recorder import (
    ToolRecorder,
    ToolCallRecord,
    RecordingSession,
    _desensitize_search_box_message,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_memory_dir(tmp_path):
    """每次测试使用独立的临时 memory 目录。"""
    return str(tmp_path / "memory")


@pytest.fixture
def recorder(tmp_memory_dir):
    """创建一个干净的 ToolRecorder 实例。"""
    return ToolRecorder(task="测试任务", memory_dir=tmp_memory_dir)


@pytest.fixture
def sample_recordings_data():
    """构造一组用于 _cleanup_redundant_steps 测试的原始 recording dict 列表。"""

    def _make_rec(order, message):
        return {
            "order": order,
            "tool_name": "execute",
            "arguments": {"message": message},
            "result": "",
            "timestamp": "",
            "click_caches": None,
        }

    return _make_rec


# ===========================================================================
# 1. _desensitize_search_box_message 脱敏函数
# ===========================================================================

class TestDesensitizeSearchBoxMessage:
    """测试 _desensitize_search_box_message 函数。"""

    @pytest.mark.parametrize("invalid_input", [None, "", 123, []])
    def test_invalid_input_returns_original(self, invalid_input):
        """空字符串或非字符串输入应原样返回。"""
        assert _desensitize_search_box_message(invalid_input) == invalid_input

    def test_no_search_box_keyword(self):
        """不含搜索框/输入框关键字时原样返回。"""
        msg = '点击"播放"按钮'
        assert _desensitize_search_box_message(msg) == msg

    def test_search_box_english_quotes(self):
        """英文引号内容应被脱敏为"文字"（非输入动作）。"""
        msg = '在搜索框中找到"斗罗大陆"结果'
        result = _desensitize_search_box_message(msg)
        assert "斗罗大陆" not in result
        assert "文字" in result

    def test_search_box_chinese_quotes(self):
        """中文引号内容应被脱敏（非输入动作）。"""
        msg = '在搜索框中找到\u201c斗罗大陆\u201d结果'
        result = _desensitize_search_box_message(msg)
        assert "斗罗大陆" not in result
        assert "文字" in result

    def test_search_box_single_quotes(self):
        """中文单引号内容应被脱敏（非输入动作）。"""
        msg = '在搜索框中找到\u2018斗罗大陆\u2019结果'
        result = _desensitize_search_box_message(msg)
        assert "斗罗大陆" not in result
        assert "文字" in result

    def test_input_box_keyword(self):
        """输入框关键字同样触发脱敏（非输入动作）。"""
        msg = '在输入框旁点击"清空"按钮'
        result = _desensitize_search_box_message(msg)
        assert "清空" not in result
        assert "文字" in result

    def test_input_action_preserves_text(self):
        """输入动作（输入后紧跟引号）应保留实际文本不脱敏。"""
        msg = '在输入框输入"斗罗大陆"'
        result = _desensitize_search_box_message(msg)
        assert result == msg
        assert "斗罗大陆" in result

    def test_input_action_with_chinese_quote(self):
        """中文引号的输入动作也保留。"""
        msg = '在输入框输入\u201c斗罗大陆\u201d'
        result = _desensitize_search_box_message(msg)
        assert result == msg

    def test_multiple_quoted_segments(self):
        """多个引号片段都应被脱敏（非输入动作）。"""
        msg = '在搜索框中找到"斗罗大陆"后点击"搜索"按钮'
        result = _desensitize_search_box_message(msg)
        assert "斗罗大陆" not in result
        assert "文字" in result


# ===========================================================================
# 2. ToolRecorder._generate_hash
# ===========================================================================

class TestGenerateHash:
    """测试 _generate_hash 方法。"""

    def test_default_length(self, recorder):
        """默认长度为 16。"""
        h = recorder._generate_hash("test task")
        assert len(h) == 16

    def test_custom_length(self, recorder):
        """自定义长度。"""
        h = recorder._generate_hash("test task", length=12)
        assert len(h) == 12

    def test_too_short_falls_back(self, recorder):
        """长度 < 10 回退到 16。"""
        h = recorder._generate_hash("test task", length=5)
        assert len(h) == 16

    def test_too_long_falls_back(self, recorder):
        """长度 > 20 回退到 16。"""
        h = recorder._generate_hash("test task", length=25)
        assert len(h) == 16

    def test_same_input_same_output(self, recorder):
        """相同输入产生相同哈希。"""
        h1 = recorder._generate_hash("相同任务")
        h2 = recorder._generate_hash("相同任务")
        assert h1 == h2

    def test_different_input_different_output(self, recorder):
        """不同输入产生不同哈希。"""
        h1 = recorder._generate_hash("任务A")
        h2 = recorder._generate_hash("任务B")
        assert h1 != h2

    def test_matches_md5(self, recorder):
        """哈希值与手动 MD5 一致。"""
        task = "验证哈希"
        expected = hashlib.md5(task.encode("utf-8")).hexdigest()[:16]
        assert recorder._generate_hash(task) == expected


# ===========================================================================
# 3. ToolRecorder.__init__
# ===========================================================================

class TestInit:
    """测试 __init__ 方法。"""

    def test_attributes_set(self, tmp_memory_dir):
        """初始化后属性正确。"""
        r = ToolRecorder(task="我的任务", memory_dir=tmp_memory_dir)
        assert r.task == "我的任务"
        assert r.memory_dir == tmp_memory_dir
        assert r._call_records == []
        assert r._call_order == 0

    def test_hash_generated(self, tmp_memory_dir):
        """task_hash 在初始化时已生成。"""
        r = ToolRecorder(task="我的任务", memory_dir=tmp_memory_dir)
        expected_hash = hashlib.md5("我的任务".encode("utf-8")).hexdigest()[:16]
        assert r.task_hash == expected_hash

    def test_directory_created(self, tmp_memory_dir):
        """memory 目录被自动创建。"""
        assert not os.path.exists(tmp_memory_dir)
        ToolRecorder(task="测试", memory_dir=tmp_memory_dir)
        assert os.path.isdir(tmp_memory_dir)


# ===========================================================================
# 4. ToolRecorder.record_tool_call
# ===========================================================================

class TestRecordToolCall:
    """测试 record_tool_call 方法。"""

    def test_basic_record(self, recorder):
        """基本工具调用记录。"""
        recorder.record_tool_call("execute", {"message": "点击按钮"}, "成功")
        records = recorder.get_recordings()
        assert len(records) == 1
        rec = records[0]
        assert rec.order == 1
        assert rec.tool_name == "execute"
        assert rec.arguments == {"message": "点击按钮"}
        assert rec.result == "成功"
        assert rec.click_caches is None

    def test_order_auto_increment(self, recorder):
        """order 自动递增。"""
        recorder.record_tool_call("execute", {"message": "步骤1"}, "r1")
        recorder.record_tool_call("execute", {"message": "步骤2"}, "r2")
        records = recorder.get_recordings()
        assert records[0].order == 1
        assert records[1].order == 2

    def test_with_click_caches(self, recorder):
        """click_caches 正确记录。"""
        caches = [{"use_xpath": True, "xpath": "//node[1]"}]
        recorder.record_tool_call(
            "execute", {"message": "点击"}, "ok", click_caches=caches
        )
        rec = recorder.get_recordings()[0]
        assert rec.click_caches == caches

    def test_result_converted_to_string(self, recorder):
        """result 被转为字符串。"""
        recorder.record_tool_call("execute", {"message": "test"}, 12345)
        rec = recorder.get_recordings()[0]
        assert rec.result == "12345"
        assert isinstance(rec.result, str)

    def test_timestamp_format(self, recorder):
        """timestamp 包含毫秒级 ISO 格式。"""
        recorder.record_tool_call("execute", {"message": "test"}, "ok")
        rec = recorder.get_recordings()[0]
        assert "T" in rec.timestamp
        assert "." in rec.timestamp

    def test_desensitize_on_execute(self, recorder):
        """execute 工具的搜索框 message 被脱敏（非输入动作）。"""
        original_msg = '在搜索框中找到"斗罗大陆"结果'
        recorder.record_tool_call("execute", {"message": original_msg}, "ok")
        rec = recorder.get_recordings()[0]
        assert rec.arguments["message"] != original_msg
        assert "斗罗大陆" not in rec.arguments["message"]

    def test_no_desensitize_on_non_execute(self, recorder):
        """非 execute 工具不做脱敏。"""
        original_msg = '在搜索框中输入"斗罗大陆"后点击搜索'
        recorder.record_tool_call("other_tool", {"message": original_msg}, "ok")
        rec = recorder.get_recordings()[0]
        assert rec.arguments["message"] == original_msg

    def test_no_desensitize_on_input_action(self, recorder):
        """输入动作的 execute 不脱敏。"""
        original_msg = '在输入框输入"斗罗大陆"'
        recorder.record_tool_call("execute", {"message": original_msg}, "ok")
        rec = recorder.get_recordings()[0]
        assert rec.arguments["message"] == original_msg

    def test_no_message_key(self, recorder):
        """arguments 中没有 message 键时不报错。"""
        recorder.record_tool_call("execute", {"other": "val"}, "ok")
        rec = recorder.get_recordings()[0]
        assert rec.arguments == {"other": "val"}

    def test_arguments_not_message_str(self, recorder):
        """message 不是字符串时不报错。"""
        recorder.record_tool_call("execute", {"message": 12345}, "ok")
        rec = recorder.get_recordings()[0]
        assert rec.arguments["message"] == 12345


# ===========================================================================
# 5. ToolRecorder.get_record_path
# ===========================================================================

class TestGetRecordPath:
    """测试 get_record_path 方法。"""

    def test_path_format(self, recorder, tmp_memory_dir):
        """路径格式正确。"""
        path = recorder.get_record_path()
        assert path.startswith(tmp_memory_dir)
        assert path.endswith(".json")
        assert recorder.task_hash in path


# ===========================================================================
# 6. ToolRecorder.save_to_file
# ===========================================================================

class TestSaveToFile:
    """测试 save_to_file 方法。"""

    def test_save_and_readback(self, recorder):
        """保存后能正确读回。"""
        recorder.record_tool_call("execute", {"message": "点击按钮"}, "成功")
        recorder.record_tool_call("execute", {"message": "滑动屏幕"}, "完成")

        file_path = recorder.save_to_file()
        assert os.path.exists(file_path)

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["task"] == "测试任务"
        assert data["total_calls"] == 2
        assert len(data["recordings"]) == 2
        assert data["recordings"][0]["order"] == 1
        assert data["recordings"][1]["order"] == 2

    def test_save_empty(self, recorder):
        """空录制也能保存。"""
        file_path = recorder.save_to_file()
        assert os.path.exists(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["total_calls"] == 0
        assert data["recordings"] == []

    def test_save_returns_path(self, recorder):
        """返回值为文件路径。"""
        file_path = recorder.save_to_file()
        assert file_path == recorder.get_record_path()

    def test_save_includes_created_at(self, recorder):
        """保存的 JSON 包含 created_at 字段。"""
        recorder.record_tool_call("execute", {"message": "x"}, "y")
        file_path = recorder.save_to_file()
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "created_at" in data
        assert data["created_at"]


# ===========================================================================
# 7. ToolRecorder._cleanup_redundant_steps
# ===========================================================================

class TestCleanupRedundantSteps:
    """测试 _cleanup_redundant_steps 静态方法。"""

    def test_no_redundant(self, sample_recordings_data):
        """没有冗余步骤时原样返回。"""
        recordings = [
            sample_recordings_data(1, "点击播放按钮"),
            sample_recordings_data(2, "滑动屏幕"),
        ]
        result = ToolRecorder._cleanup_redundant_steps(recordings)
        assert len(result) == 2

    def test_consecutive_redundant_keep_last_with_view(self, sample_recordings_data):
        """连续冗余步骤保留最后一条带"查看"的。"""
        recordings = [
            sample_recordings_data(1, "点击视频画面中央唤出播控层"),
            sample_recordings_data(2, "点击视频画面中央唤出播控层，查看进度条"),
            sample_recordings_data(3, "点击视频画面中央唤出播控层"),
        ]
        result = ToolRecorder._cleanup_redundant_steps(recordings)
        assert len(result) == 1
        assert "查看" in result[0]["arguments"]["message"]

    def test_consecutive_redundant_no_view_keep_last(self, sample_recordings_data):
        """连续冗余步骤无"查看"时保留最后一条。"""
        recordings = [
            sample_recordings_data(1, "点击视频画面中央唤出播控层"),
            sample_recordings_data(2, "点击视频画面中央唤出播控层"),
        ]
        result = ToolRecorder._cleanup_redundant_steps(recordings)
        assert len(result) == 1
        assert result[0]["order"] == 2

    def test_single_match_not_removed(self, sample_recordings_data):
        """单独一条匹配不删除。"""
        recordings = [
            sample_recordings_data(1, "点击视频画面中央唤出播控层"),
            sample_recordings_data(2, "点击播放按钮"),
        ]
        result = ToolRecorder._cleanup_redundant_steps(recordings)
        assert len(result) == 2

    def test_multiple_groups(self, sample_recordings_data):
        """多组冗余步骤分别清理。"""
        recordings = [
            sample_recordings_data(1, "点击视频画面中央唤出播控层"),
            sample_recordings_data(2, "点击视频画面中央唤出播控层"),
            sample_recordings_data(3, "点击播放按钮"),
            sample_recordings_data(4, "点击视频画面中央唤出播控层"),
            sample_recordings_data(5, "点击视频画面中央唤出播控层，查看按钮"),
        ]
        result = ToolRecorder._cleanup_redundant_steps(recordings)
        assert len(result) == 3
        # 第一组保留 order=2
        # 中间保留 order=3
        # 第二组保留 order=5
        orders = [r["order"] for r in result]
        assert orders == [2, 3, 5]

    def test_non_execute_not_matched(self, sample_recordings_data):
        """非 execute 工具的步骤不参与清理。"""
        recordings = [
            sample_recordings_data(1, "点击视频画面中央唤出播控层"),
            {**sample_recordings_data(2, "点击视频画面中央唤出播控层"),
             "tool_name": "other_tool"},
        ]
        result = ToolRecorder._cleanup_redundant_steps(recordings)
        assert len(result) == 2


# ===========================================================================
# 8. ToolRecorder.load_from_file
# ===========================================================================

class TestLoadFromFile:
    """测试 load_from_file 静态方法。"""

    def test_load_valid_file(self, recorder):
        """正常加载文件。"""
        recorder.record_tool_call("execute", {"message": "点击"}, "ok")
        file_path = recorder.save_to_file()

        session = ToolRecorder.load_from_file(file_path)
        assert session is not None
        assert session.task == "测试任务"
        assert session.total_calls == 1
        assert len(session.recordings) == 1

    def test_load_nonexistent_file(self, tmp_path):
        """文件不存在返回 None。"""
        result = ToolRecorder.load_from_file(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_corrupted_file(self, tmp_path):
        """损坏的 JSON 文件返回 None。"""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")
        result = ToolRecorder.load_from_file(str(bad_file))
        assert result is None


# ===========================================================================
# 9. ToolRecorder.load_by_task
# ===========================================================================

class TestLoadByTask:
    """测试 load_by_task 静态方法。"""

    def test_load_existing_task(self, recorder, tmp_memory_dir):
        """通过任务描述加载已存在的录制。"""
        recorder.record_tool_call("execute", {"message": "点击"}, "ok")
        recorder.save_to_file()

        session = ToolRecorder.load_by_task("测试任务", tmp_memory_dir)
        assert session is not None
        assert session.task == "测试任务"

    def test_load_nonexistent_task(self, tmp_memory_dir):
        """不存在的任务返回 None。"""
        result = ToolRecorder.load_by_task("不存在的任务", tmp_memory_dir)
        assert result is None


# ===========================================================================
# 10. ToolRecorder.find_recording
# ===========================================================================

class TestFindRecording:
    """测试 find_recording 静态方法。"""

    def test_find_by_file_path(self, recorder, tmp_memory_dir):
        """通过完整文件路径查找。"""
        recorder.record_tool_call("execute", {"message": "x"}, "y")
        file_path = recorder.save_to_file()

        session = ToolRecorder.find_recording(file_path, tmp_memory_dir)
        assert session is not None
        assert session.task == "测试任务"

    def test_find_by_task_description(self, recorder, tmp_memory_dir):
        """通过任务描述（非路径）查找。"""
        recorder.record_tool_call("execute", {"message": "x"}, "y")
        recorder.save_to_file()

        session = ToolRecorder.find_recording("测试任务", tmp_memory_dir)
        assert session is not None

    def test_find_nonexistent(self, tmp_memory_dir):
        """查找不存在的录制返回 None。"""
        result = ToolRecorder.find_recording("不存在的任务xyz", tmp_memory_dir)
        assert result is None


# ===========================================================================
# 11. ToolRecorder.get_recordings
# ===========================================================================

class TestGetRecordings:
    """测试 get_recordings 方法。"""

    def test_empty(self, recorder):
        """空录制返回空列表。"""
        assert recorder.get_recordings() == []

    def test_returns_copy(self, recorder):
        """返回的是副本，修改不影响内部状态。"""
        recorder.record_tool_call("execute", {"message": "x"}, "y")
        records = recorder.get_recordings()
        records.clear()
        assert len(recorder.get_recordings()) == 1


# ===========================================================================
# 12. ToolRecorder.clear
# ===========================================================================

class TestClear:
    """测试 clear 方法。"""

    def test_clear_records(self, recorder):
        """清空后记录为空。"""
        recorder.record_tool_call("execute", {"message": "x"}, "y")
        recorder.record_tool_call("execute", {"message": "a"}, "b")
        assert len(recorder.get_recordings()) == 2

        recorder.clear()
        assert recorder.get_recordings() == []
        assert recorder._call_order == 0

    def test_order_resets_after_clear(self, recorder):
        """清空后 order 重置为 0，新记录从 1 开始。"""
        recorder.record_tool_call("execute", {"message": "x"}, "y")
        recorder.clear()
        recorder.record_tool_call("execute", {"message": "z"}, "w")
        rec = recorder.get_recordings()[0]
        assert rec.order == 1


# ===========================================================================
# 端到端集成测试
# ===========================================================================

class TestIntegration:
    """端到端集成测试：录制 → 保存 → 加载 → 校验。"""

    def test_full_lifecycle(self, tmp_memory_dir):
        """完整生命周期测试。"""
        r = ToolRecorder(task="集成测试任务", memory_dir=tmp_memory_dir)

        # 录制多个步骤
        r.record_tool_call("execute", {"message": "点击首页"}, "进入首页")
        r.record_tool_call(
            "execute", {"message": '在搜索框中找到"斗罗大陆"结果'}, "搜索结果"
        )
        r.record_tool_call(
            "execute",
            {"message": "点击视频画面中央唤出播控层"},
            "播控出现",
        )
        r.record_tool_call(
            "execute",
            {"message": "点击视频画面中央唤出播控层，查看进度条"},
            "进度条可见",
        )

        # 保存
        file_path = r.save_to_file()
        assert os.path.exists(file_path)

        # 加载
        session = ToolRecorder.load_from_file(file_path)
        assert session is not None
        assert session.task == "集成测试任务"
        # 冗余步骤被清理后应为 3 条（搜索框脱敏后 + 冗余清理后）
        assert session.total_calls == 3

        # 验证搜索框脱敏生效
        search_record = None
        for rec in session.recordings:
            msg = rec["arguments"].get("message", "")
            if "搜索框" in msg:
                search_record = rec
                break
        assert search_record is not None
        assert "斗罗大陆" not in search_record["arguments"]["message"]
