"""tool_player.py 核心回放逻辑单元测试。

测试覆盖范围：
1.  类常量与数据结构
2.  _is_progress_bar_capture_message     — 进度条指令识别
3.  _extract_progress_bar_coords          — 进度条坐标解析
4.  _build_swipe_args_from_progress_bar_result — swipe 参数构造
5.  _parse_verify_result                  — verify 结果解析
6.  _parse_bounds_center                  — bounds 中心点解析
7.  _normalize_cached_point               — 坐标归一化
8.  _get_component_center                 — 控件中心获取
9.  _find_best_component_by_xpath         — xpath 控件查找
10. _build_replan_prompt                  — 重规划 prompt 构造
11. load_record / load_by_task            — 录制加载
12. get_session / get_total_steps / …     — 状态查询
13. _call_mcp_tool                        — MCP 工具调用（mock）
14. play_async 基本流程（mock）            — 回放主流程
"""

import json
import os
import asyncio
from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

from AutoTest.memory.tool_player import (
    ToolPlayer,
    MockTool,
    PopupHandlingConfig,
)
from AutoTest.memory.tool_recorder import ToolRecorder


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

class FakeCenter:
    """模拟 hypium getBoundsCenter() 返回值。"""

    def __init__(self, x, y):
        self.X = x
        self.Y = y


class FakeComponent:
    """模拟 UI 控件对象。"""

    def __init__(self, cx, cy):
        self._center = FakeCenter(cx, cy)

    def getBoundsCenter(self):
        return self._center


class FakeDriver:
    """模拟 UiDriver，支持 find_components / find_component。"""

    def __init__(self, components=None, single_component=None):
        self._components = components or []
        self._single = single_component

    def find_components(self, locator, index=0):
        if self._components:
            return self._components
        return []

    def find_component(self, locator, index=0):
        return self._single


@pytest.fixture
def mock_device():
    """最小化的 mock 设备。"""
    dev = MagicMock()
    dev.driver = FakeDriver()
    dev.get_screenshot = MagicMock(return_value=MagicMock(
        width=1080, height=2400, screenshot_path="/tmp/fake.png",
        base64_data="fake_base64"
    ))
    dev.tap = MagicMock()
    return dev


@pytest.fixture
def player(mock_device):
    """创建一个 ToolPlayer 实例，依赖全部 mock。"""
    return ToolPlayer(
        device=mock_device,
        report_generator=None,
        executor_agent=None,
        verify_agent=None,
        planner_agent=None,
        config=None,
    )


@pytest.fixture
def player_with_driver(mock_device):
    """创建带 mock driver 的 ToolPlayer。"""
    return ToolPlayer(device=mock_device)


@pytest.fixture
def tmp_recording(tmp_path):
    """创建一个临时录制文件并返回路径。"""
    memory_dir = str(tmp_path.resolve() / ".sdd-runs/test/runs/harmony/automation/attempt/memory")
    r = ToolRecorder(task="回放测试任务", memory_dir=memory_dir)
    r.record_tool_call("execute", {"message": "点击播放按钮"}, "成功")
    r.record_tool_call("verify", {"description": "检查播放状态"}, '{"result": true}')
    return r.save_to_file(), memory_dir


# ===========================================================================
# 1. 类常量与数据结构
# ===========================================================================

class TestClassConstants:
    """测试类常量和数据结构。"""

    def test_action_map_content(self):
        """ACTION_MAP 包含关键动作映射。"""
        assert ToolPlayer.ACTION_MAP["click"] == "Tap"
        assert ToolPlayer.ACTION_MAP["swipe"] == "Swipe"
        assert ToolPlayer.ACTION_MAP["input_text"] == "Type"
        assert ToolPlayer.ACTION_MAP["long_click"] == "Long Press"

    def test_skip_replay_tools(self):
        """SKIP_REPLAY_TOOLS 包含 load_skill。"""
        assert "load_skill" in ToolPlayer.SKIP_REPLAY_TOOLS

    def test_failure_keywords(self):
        """FAILURE_KEYWORDS 包含常见失败关键词。"""
        for kw in ("无法", "未找到", "不存在", "失败"):
            assert kw in ToolPlayer.FAILURE_KEYWORDS

    def test_mock_tool_dataclass(self):
        """MockTool 数据结构正确。"""
        tool = MockTool(name="test_tool")
        assert tool.name == "test_tool"

    def test_popup_config_defaults(self):
        """PopupHandlingConfig 默认值正确。"""
        cfg = PopupHandlingConfig()
        assert cfg.enabled is True
        assert cfg.max_retry_attempts == 1
        assert cfg.skip_popup_steps is True


# ===========================================================================
# 2. _is_progress_bar_capture_message
# ===========================================================================

class TestProgressBarDetection:
    """测试 _is_progress_bar_capture_message 方法。"""

    @pytest.mark.parametrize("message", [
        "点击视频画面唤起进度条，获取x1y1x2y2x3y3坐标",
        "点击视频画面获取进度条坐标x1y1x2y2",
        "唤起进度条获取x2y2x3y3",
    ])
    def test_progress_bar_messages(self, player, message):
        """包含进度条+唤起/获取+坐标变量 → True。"""
        assert player._is_progress_bar_capture_message(message) is True

    @pytest.mark.parametrize("message", [
        "点击播放按钮",
        "滑动屏幕",
        "进度条坐标",  # 缺少"唤起"/"获取"
        "唤起进度条",  # 缺少坐标变量
        "",
        None,
    ])
    def test_non_progress_bar_messages(self, player, message):
        """不满足条件的消息 → False。"""
        assert player._is_progress_bar_capture_message(message) is False


# ===========================================================================
# 3. _extract_progress_bar_coords
# ===========================================================================

class TestExtractProgressBarCoords:
    """测试 _extract_progress_bar_coords 方法。"""

    def test_main_format(self, player):
        """主格式：起点坐标 (x1, y1)：(80, 820)。"""
        text = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(300, 820)"
        )
        coords = player._extract_progress_bar_coords(text)
        assert coords is not None
        assert coords["x1"] == 80
        assert coords["y1"] == 820
        assert coords["x2"] == 1000
        assert coords["y2"] == 820
        assert coords["x3"] == 300
        assert coords["y3"] == 820

    def test_fallback_format(self, player):
        """兜底格式：x1=80, y1=820。"""
        text = "x1=80, y1=820, x2=1000, y2=820, x3=300, y3=820"
        coords = player._extract_progress_bar_coords(text)
        assert coords is not None
        assert coords["x1"] == 80
        assert coords["x2"] == 1000
        assert coords["x3"] == 300

    def test_json_wrapper(self, player):
        """JSON 包装的结果能解析。"""
        text = json.dumps({
            "result": (
                "起点坐标 (x1, y1)：(80, 820)\n"
                "终点坐标 (x2, y2)：(1000, 820)\n"
                "当前进度坐标 (x3, y3)：(300, 820)"
            )
        })
        coords = player._extract_progress_bar_coords(text)
        assert coords is not None
        assert coords["x1"] == 80

    def test_missing_coords(self, player):
        """缺少必需坐标 → None。"""
        text = "起点坐标 (x1, y1)：(80, 820)"
        coords = player._extract_progress_bar_coords(text)
        assert coords is None

    def test_empty_input(self, player):
        """空输入 → None。"""
        assert player._extract_progress_bar_coords("") is None
        assert player._extract_progress_bar_coords(None) is None

    def test_chinese_colon_and_parentheses(self, player):
        """中文冒号和括号兼容。"""
        text = "起点坐标（x1，y1）：（80，820）\n终点坐标（x2，y2）：（1000，820）\n当前进度坐标（x3，y3）：（300，820）"
        coords = player._extract_progress_bar_coords(text)
        assert coords is not None
        assert coords["x1"] == 80
        assert coords["x3"] == 300


# ===========================================================================
# 4. _build_swipe_args_from_progress_bar_result
# ===========================================================================

class TestBuildSwipeArgs:
    """测试 _build_swipe_args_from_progress_bar_result 方法。"""

    def test_matching_coordinates(self, player):
        """录制坐标与新坐标匹配 → 映射后的参数。"""
        fresh_result = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(300, 820)"
        )
        recorded_result = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(200, 820)"
        )
        # original_args: from_x from_y to_x to_y，录制时 from=200(x3), to=1000(x2)
        original_args = "200 820 1000 820"
        result = player._build_swipe_args_from_progress_bar_result(
            fresh_result, recorded_result, original_args
        )
        assert result is not None
        # 200 匹配 x3 → fresh x3=300, 1000 匹配 x2 → fresh x2=1000
        parts = result.split()
        assert parts[0] == "300"  # from_x = fresh x3
        assert parts[1] == "820"  # from_y
        assert parts[2] == "1000"  # to_x = fresh x2
        assert parts[3] == "820"  # to_y

    def test_fallback_mode(self, player):
        """录制坐标无法匹配 → 退化到 当前进度->终点 模式。"""
        fresh_result = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(300, 820)"
        )
        recorded_result = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(500, 820)"
        )
        # 999 不匹配任何录制坐标 → fallback
        original_args = "999 820 888 820"
        result = player._build_swipe_args_from_progress_bar_result(
            fresh_result, recorded_result, original_args
        )
        assert result is not None
        parts = result.split()
        # fallback: x3 y3 x2 y2
        assert parts[0] == "300"
        assert parts[2] == "1000"

    def test_no_fresh_coords(self, player):
        """无法从 fresh_result 解析坐标 → None。"""
        result = player._build_swipe_args_from_progress_bar_result(
            "无效文本", "录制结果", "200 820 1000 820"
        )
        assert result is None

    def test_no_recorded_coords(self, player):
        """无录制坐标 → fallback 模式。"""
        fresh_result = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(300, 820)"
        )
        result = player._build_swipe_args_from_progress_bar_result(
            fresh_result, "", "200 820 1000 820"
        )
        assert result is not None
        parts = result.split()
        assert parts[0] == "300"
        assert parts[2] == "1000"

    def test_wrong_args_length(self, player):
        """original_args 非4段 → fallback。"""
        fresh_result = (
            "起点坐标 (x1, y1)：(80, 820)\n"
            "终点坐标 (x2, y2)：(1000, 820)\n"
            "当前进度坐标 (x3, y3)：(300, 820)"
        )
        result = player._build_swipe_args_from_progress_bar_result(
            fresh_result, fresh_result, "200 820"
        )
        assert result is not None


# ===========================================================================
# 5. _parse_verify_result
# ===========================================================================

class TestParseVerifyResult:
    """测试 _parse_verify_result 方法。"""

    def test_result_true(self, player):
        """result=true → business_pass=True。"""
        result = '{"result": true, "reason": "验证通过"}'
        info = player._parse_verify_result(result)
        assert info["business_pass"] is True
        assert info["verify_reason"] == "验证通过"

    def test_result_false(self, player):
        """result=false → business_pass=False。"""
        result = '{"result": false, "reason": "元素不存在"}'
        info = player._parse_verify_result(result)
        assert info["business_pass"] is False
        assert info["verify_reason"] == "元素不存在"

    def test_no_result_field(self, player):
        """JSON 无 result 字段 → business_pass=False。"""
        result = '{"message": "ok"}'
        info = player._parse_verify_result(result)
        assert info["business_pass"] is False
        assert info["verify_reason"] == "无法解析验证结果"

    def test_non_json(self, player):
        """非 JSON 字符串 → business_pass=False。"""
        info = player._parse_verify_result("这不是JSON")
        assert info["business_pass"] is False

    def test_empty_string(self, player):
        """空字符串 → business_pass=False。"""
        info = player._parse_verify_result("")
        assert info["business_pass"] is False

    def test_result_non_bool(self, player):
        """result 为非布尔值 → business_pass=False。"""
        result = '{"result": "yes"}'
        info = player._parse_verify_result(result)
        assert info["business_pass"] is False


# ===========================================================================
# 6. _parse_bounds_center (static)
# ===========================================================================

class TestParseBoundsCenter:
    """测试 _parse_bounds_center 静态方法。"""

    def test_valid_bounds(self):
        """标准 bounds 格式 → 中心点。"""
        center = ToolPlayer._parse_bounds_center("[100,200][300,400]")
        assert center == (200, 300)

    def test_none_input(self):
        """None → None。"""
        assert ToolPlayer._parse_bounds_center(None) is None

    def test_empty_string(self):
        """空字符串 → None。"""
        assert ToolPlayer._parse_bounds_center("") is None

    def test_invalid_format(self):
        """无效格式 → None。"""
        assert ToolPlayer._parse_bounds_center("invalid") is None
        assert ToolPlayer._parse_bounds_center("[100,200]") is None


# ===========================================================================
# 7. _normalize_cached_point (static)
# ===========================================================================

class TestNormalizeCachedPoint:
    """测试 _normalize_cached_point 静态方法。"""

    def test_int_values(self):
        """整数输入。"""
        assert ToolPlayer._normalize_cached_point(100, 200) == (100, 200)

    def test_string_values(self):
        """字符串数字输入。"""
        assert ToolPlayer._normalize_cached_point("100", "200") == (100, 200)

    def test_float_string_values(self):
        """浮点数字符串输入。"""
        assert ToolPlayer._normalize_cached_point("100.5", "200.9") == (100, 200)

    def test_none_values(self):
        """None → None。"""
        assert ToolPlayer._normalize_cached_point(None, 200) is None
        assert ToolPlayer._normalize_cached_point(100, None) is None

    def test_invalid_string(self):
        """非法字符串 → None。"""
        assert ToolPlayer._normalize_cached_point("abc", "200") is None


# ===========================================================================
# 8. _get_component_center (static)
# ===========================================================================

class TestGetComponentCenter:
    """测试 _get_component_center 静态方法。"""

    def test_valid_component(self):
        """有效控件 → 中心坐标。"""
        comp = FakeComponent(150, 250)
        center = ToolPlayer._get_component_center(comp)
        assert center == (150, 250)

    def test_none_component(self):
        """None → None。"""
        assert ToolPlayer._get_component_center(None) is None

    def test_component_without_method(self):
        """控件无 getBoundsCenter 方法 → None。"""
        comp = MagicMock()
        del comp.getBoundsCenter
        assert ToolPlayer._get_component_center(comp) is None


# ===========================================================================
# 9. _find_best_component_by_xpath
# ===========================================================================

class TestFindBestComponentByXPath:
    """测试 _find_best_component_by_xpath 方法。"""

    def test_single_candidate(self, player):
        """只有一个候选 → 直接返回。"""
        comp = FakeComponent(100, 200)
        driver = FakeDriver(components=[comp])
        result = player._find_best_component_by_xpath(driver, "//node")
        assert result is comp

    def test_multiple_candidates_nearest(self, player):
        """多个候选 → 选距离 target 最近的。"""
        comp1 = FakeComponent(100, 200)
        comp2 = FakeComponent(500, 600)
        comp3 = FakeComponent(300, 400)
        driver = FakeDriver(components=[comp1, comp2, comp3])
        # target = (310, 410)，comp3 最近
        result = player._find_best_component_by_xpath(
            driver, "//node", bounds="[290,390][320,420]"
        )
        assert result is comp3

    def test_no_candidates_with_fallback_single(self, player):
        """find_components 为空但 find_component 有结果。"""
        comp = FakeComponent(100, 200)
        driver = FakeDriver(components=[], single_component=comp)
        result = player._find_best_component_by_xpath(driver, "//node")
        assert result is comp

    def test_no_candidates_at_all(self, player):
        """无任何候选 → None。"""
        driver = FakeDriver(components=[], single_component=None)
        result = player._find_best_component_by_xpath(driver, "//node")
        assert result is None

    def test_no_target_uses_first(self, player):
        """多个候选但无 target → 返回第一个。"""
        comp1 = FakeComponent(100, 200)
        comp2 = FakeComponent(500, 600)
        driver = FakeDriver(components=[comp1, comp2])
        result = player._find_best_component_by_xpath(
            driver, "//node", bounds=None, fallback_x=None, fallback_y=None
        )
        assert result is comp1

    def test_fallback_coordinates(self, player):
        """使用 fallback_x/fallback_y 作为 target。"""
        comp1 = FakeComponent(100, 200)
        comp2 = FakeComponent(450, 550)
        driver = FakeDriver(components=[comp1, comp2])
        # fallback target = (440, 540)，comp2 最近
        result = player._find_best_component_by_xpath(
            driver, "//node", fallback_x=440, fallback_y=540
        )
        assert result is comp2


# ===========================================================================
# 10. _build_replan_prompt
# ===========================================================================

class TestBuildReplanPrompt:
    """测试 _build_replan_prompt 方法。"""

    def test_with_history(self, player):
        """有执行历史时 prompt 包含历史摘要。"""
        history = [
            {
                "tool_name": "execute",
                "arguments": {"message": "点击播放按钮"},
                "result": '{"result": true}',
            },
            {
                "tool_name": "verify",
                "arguments": {"description": "检查播放"},
                "result": '{"result": false, "reason": "未播放"}',
            },
        ]
        failure_info = {
            "failure_reason": "元素未找到",
            "failed_step": "点击播放",
            "suggestion": "尝试重新点击",
        }
        prompt = player._build_replan_prompt("测试任务", history, failure_info)
        assert "测试任务" in prompt
        assert "点击播放按钮" in prompt
        assert "元素未找到" in prompt
        assert "尝试重新点击" in prompt

    def test_empty_history(self, player):
        """空历史 → 显示"无执行历史"。"""
        prompt = player._build_replan_prompt("任务", [], {
            "failure_reason": "失败",
            "failed_step": "步骤1",
        })
        assert "无执行历史" in prompt
        assert "失败" in prompt

    def test_json_message_in_history(self, player):
        """历史记录中 message 为 JSON 时能解析操作意图。"""
        history = [
            {
                "tool_name": "execute",
                "arguments": {"message": json.dumps({
                    "action": "click",
                    "log": "点击搜索按钮"
                })},
                "result": '{"result": true}',
            },
        ]
        prompt = player._build_replan_prompt("任务", history, {
            "failure_reason": "失败", "failed_step": "步骤"
        })
        assert "点击搜索按钮" in prompt

    def test_no_suggestion(self, player):
        """无 suggestion 时 prompt 仍正常生成。"""
        prompt = player._build_replan_prompt("任务", [], {
            "failure_reason": "失败",
            "failed_step": "步骤",
        })
        assert "任务" in prompt
        assert "失败" in prompt


# ===========================================================================
# 11. load_record / load_by_task
# ===========================================================================

class TestLoadRecord:
    """测试 load_record 和 load_by_task。"""

    def test_load_valid_file(self, player, tmp_recording):
        """加载有效录制文件。"""
        file_path, _ = tmp_recording
        assert player.load_record(file_path) is True
        assert player._current_session is not None
        assert player._current_session.task == "回放测试任务"
        assert player._current_index == 0

    def test_load_nonexistent_file(self, player, tmp_path):
        """加载不存在的文件 → False。"""
        assert player.load_record(str(tmp_path / "nonexistent.json")) is False

    def test_load_corrupted_file(self, player, tmp_path):
        """加载损坏文件 → False。"""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid", encoding="utf-8")
        assert player.load_record(str(bad_file)) is False

    def test_load_by_task(self, player, tmp_recording):
        """按任务描述加载。"""
        _, memory_dir = tmp_recording
        assert player.load_by_task("回放测试任务", memory_dir) is True
        assert player._current_session is not None

    def test_load_by_task_not_found(self, player, tmp_path):
        """加载不存在的任务 → False。"""
        assert player.load_by_task("不存在的任务", str(tmp_path)) is False


# ===========================================================================
# 12. 状态查询方法
# ===========================================================================

class TestStateQueries:
    """测试 get_session / get_total_steps / get_current_step 等方法。"""

    def test_initial_state(self, player):
        """初始状态：无 session。"""
        assert player.get_session() is None
        assert player.get_total_steps() == 0
        assert player.get_current_step() == 0
        assert player.last_playback_results is None

    def test_after_load(self, player, tmp_recording):
        """加载后状态正确。"""
        file_path, _ = tmp_recording
        player.load_record(file_path)
        assert player.get_session() is not None
        assert player.get_total_steps() == 2
        assert player.get_current_step() == 0


# ===========================================================================
# 13. _call_mcp_tool
# ===========================================================================

class TestCallMcpTool:
    """测试 _call_mcp_tool 方法。"""

    def test_no_executor_agent(self, player):
        """无 executor_agent → None。"""
        assert player._call_mcp_tool("click", {"pos": [500, 500]}) is None

    def test_no_mcp_extension(self, mock_device):
        """executor_agent 无 _mcp_extension → None。"""
        agent = MagicMock()
        del agent._mcp_extension
        p = ToolPlayer(device=mock_device, executor_agent=agent)
        assert p._call_mcp_tool("click", {"pos": [500, 500]}) is None

    def test_mcp_call_success(self, mock_device):
        """MCP 调用成功 → 返回 output。"""
        agent = MagicMock()
        mcp_ext = MagicMock()
        mcp_ext.call_tool = MagicMock(return_value=MagicMock(
            success=True, output='{"result": true}'
        ))
        agent._mcp_extension = mcp_ext
        p = ToolPlayer(device=mock_device, executor_agent=agent)
        result = p._call_mcp_tool("click", {"pos": [500, 500]})
        assert result == '{"result": true}'

    def test_mcp_call_failure(self, mock_device):
        """MCP 调用失败 → None。"""
        agent = MagicMock()
        mcp_ext = MagicMock()
        mcp_ext.call_tool = MagicMock(return_value=MagicMock(
            success=False, error_msg="device error", output=""
        ))
        agent._mcp_extension = mcp_ext
        p = ToolPlayer(device=mock_device, executor_agent=agent)
        assert p._call_mcp_tool("click", {"pos": [500, 500]}) is None


# ===========================================================================
# 14. _get_driver
# ===========================================================================

class TestGetDriver:
    """测试 _get_driver 方法。"""

    def test_from_device(self, mock_device):
        """从 device.driver 获取。"""
        driver = FakeDriver()
        mock_device.driver = driver
        p = ToolPlayer(device=mock_device)
        assert p._get_driver() is driver

    def test_from_executor_agent(self, mock_device):
        """从 executor_agent.device.driver 获取。"""
        mock_device.driver = None
        driver = FakeDriver()
        agent = MagicMock()
        agent.device.driver = driver
        p = ToolPlayer(device=mock_device, executor_agent=agent)
        assert p._get_driver() is driver

    def test_no_driver_available(self, mock_device):
        """无可用 driver → None。"""
        mock_device.driver = None
        p = ToolPlayer(device=mock_device)
        assert p._get_driver() is None


# ===========================================================================
# 15. play_async 基本流程（mock）
# ===========================================================================

class TestPlayAsync:
    """测试 play_async 回放主流程。"""

    def test_no_session(self, player):
        """无录制时返回失败。"""
        result = asyncio.run(player.play_async())
        assert result["success"] is False
        assert "error" in result

    def test_skip_replay_tools(self, mock_device, tmp_path):
        """load_skill 等工具被跳过。"""
        memory_dir = str(tmp_path.resolve() / ".sdd-runs/test/runs/harmony/automation/attempt/memory")
        r = ToolRecorder(task="跳过测试", memory_dir=memory_dir)
        r.record_tool_call("load_skill", {"skill_name": "test"}, "loaded")
        file_path = r.save_to_file()

        p = ToolPlayer(device=mock_device)
        p.load_record(file_path)
        result = asyncio.run(p.play_async())
        assert result["success"] is True
        # load_skill 被跳过，results 为空
        assert result["total_calls"] == 0

    def test_timeout_handling(self, mock_device, tmp_path):
        """超时返回 timeout 标记。"""
        memory_dir = str(tmp_path.resolve() / ".sdd-runs/test/runs/harmony/automation/attempt/memory")
        r = ToolRecorder(task="超时测试", memory_dir=memory_dir)
        r.record_tool_call("execute", {"message": "步骤1"}, "ok")
        file_path = r.save_to_file()

        config = MagicMock()
        config.task_timeout = 0  # 立即超时
        p = ToolPlayer(device=mock_device, config=config)
        p.load_record(file_path)
        result = asyncio.run(p.play_async())
        assert result["success"] is False
        assert result.get("timeout") is True


# ===========================================================================
# 16. PopupHandlingConfig
# ===========================================================================

class TestPopupConfig:
    """测试弹窗处理配置。"""

    def test_custom_config(self):
        """自定义配置。"""
        cfg = PopupHandlingConfig(
            enabled=False,
            max_retry_attempts=3,
            skip_popup_steps=False,
        )
        assert cfg.enabled is False
        assert cfg.max_retry_attempts == 3
        assert cfg.skip_popup_steps is False

    def test_player_default_popup_config(self, mock_device):
        """ToolPlayer 默认弹窗配置。"""
        p = ToolPlayer(device=mock_device)
        assert p.popup_config.enabled is True
        assert p.popup_config.max_retry_attempts == 1
