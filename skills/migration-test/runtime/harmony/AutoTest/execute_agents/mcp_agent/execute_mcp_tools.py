"""
MCP tools generated from hdc_device.py
All tools are generated based on the HDCDevice class methods.
"""
import json
import asyncio
from hypium import UiDriver

from agents import function_tool
from ...layered_agent_cli.agent_registry import agent_registry

# 在模块顶部创建一个注册表
EXECUTE_TOOL_REGISTRY = {}


def collect_function_tool(func):
    """
    收集并注册 function_tool 函数
    """
    # 先应用装饰器，得到装饰后的对象
    decorated_func = function_tool(func)
    # 将装饰后的函数存储到注册表
    EXECUTE_TOOL_REGISTRY[func.__name__] = decorated_func
    return decorated_func


def get_registered_tools():
    """
    获取所有注册的工具函数列表
    """
    return list(EXECUTE_TOOL_REGISTRY.values())


def get_executor_agent():
    """获取 executor agent 实例"""
    return agent_registry.get_executor_agent()


def get_driver() -> UiDriver:
    executor_agent = get_executor_agent()
    hdc_device = executor_agent.device
    return hdc_device.driver


# === Tap Operations ===
def _tap(x: int, y: int, delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import tap as hdc_tap
    hdc_tap(driver, x, y, delay)
    return json.dumps({
        "action": "tap",
        "normalized": (x, y),
        "message": "tap ({}, {}) successfully".format(x, y)
    })


@collect_function_tool
async def tap(x: int, y: int, delay: float | None = None):
    """
    点击屏幕上的指定位置。

    Args:
        x: X 坐标
        y: Y 坐标
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_tap, x, y, delay)


# === Double Tap Operations ===
def _double_tap(x: int, y: int, delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import double_tap as hdc_double_tap
    hdc_double_tap(driver, x, y, delay)
    return json.dumps({
        "action": "double_tap",
        "normalized": (x, y),
        "message": "double tap ({}, {}) successfully".format(x, y)
    })


@collect_function_tool
async def double_tap(x: int, y: int, delay: float | None = None):
    """
    双击屏幕上的指定位置。

    Args:
        x: X 坐标
        y: Y 坐标
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_double_tap, x, y, delay)


# === Long Press Operations ===
def _long_press(x: int, y: int, duration_s: float = 3.0, delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import long_press as hdc_long_press
    hdc_long_press(driver, x, y, duration_s, delay)
    return json.dumps({
        "action": "long_press",
        "normalized": (x, y),
        "duration_s": duration_s,
        "message": "long press ({}, {}) for {}s successfully".format(x, y, duration_s)
    })


@collect_function_tool
async def long_press(x: int, y: int, duration_s: float = 3.0, delay: float | None = None):
    """
    长按屏幕上的指定位置。

    Args:
        x: X 坐标
        y: Y 坐标
        duration_s: 长按持续时间（秒），默认 3.0s
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_long_press, x, y, duration_s, delay)


# === Swipe Operations ===
def _swipe(start_x: int, start_y: int, end_x: int, end_y: int, duration_s: float | None = None,
           delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import swipe as hdc_swipe
    hdc_swipe(driver, start_x, start_y, end_x, end_y, duration_s, delay)
    return json.dumps({
        "action": "swipe",
        "normalized_start": (start_x, start_y),
        "normalized_end": (end_x, end_y),
        "message": "swipe from ({}, {}) to ({}, {}) successfully".format(
            start_x, start_y, end_x, end_y
        )
    })


@collect_function_tool
async def swipe(start_x: int, start_y: int, end_x: int, end_y: int, duration_s: float | None = None,
                delay: float | None = None):
    """
    从一个位置滑动到另一个位置。

    Args:
        start_x: 起始 X 坐标
        start_y: 起始 Y 坐标
        end_x: 结束 X 坐标
        end_y: 结束 Y 坐标
        duration_s: 滑动持续时间（秒）
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_swipe, start_x, start_y, end_x, end_y, duration_s, delay)


# === Drag Operations ===
def _drag(start_x: int, start_y: int, end_x: int, end_y: int, press_time: float = 1.5, drag_time: float = 1):
    driver = get_driver()
    from ...devices.hdc import drag as hdc_drag
    hdc_drag(driver, start_x, start_y, end_x, end_y, press_time, drag_time)
    return json.dumps({
        "action": "drag",
        "normalized_start": (start_x, start_y),
        "normalized_end": (end_x, end_y),
        "press_time": press_time,
        "drag_time": drag_time,
        "message": "drag from ({}, {}) to ({}, {}) successfully".format(
            start_x, start_y, end_x, end_y
        )
    })


@collect_function_tool
async def drag(start_x: int, start_y: int, end_x: int, end_y: int, press_time: float = 1.5,
               drag_time: float = 1):
    """
    从一个位置拖动到另一个位置。

    Args:
        start_x: 起始 X 坐标
        start_y: 起始 Y 坐标
        end_x: 结束 X 坐标
        end_y: 结束 Y 坐标
        press_time: 按压时间（秒），默认 1.5 秒
        drag_time: 拖动时间（秒），默认 1 秒
    """
    return await asyncio.to_thread(_drag, start_x, start_y, end_x, end_y, press_time, drag_time)


# === Input Operations ===
def _type_text(text: str):
    driver = get_driver()
    from ...devices.hdc.input import type_text as hdc_type_text
    hdc_type_text(driver, text)
    return json.dumps({
        "action": "type_text",
        "text": text,
        "message": "type text '{}' successfully".format(text)
    })


@collect_function_tool
async def type_text(text: str):
    """
    在当前聚焦的输入框中输入文本。

    Args:
        text: 要输入的文本
    """
    return await asyncio.to_thread(_type_text, text)


def _clear_text():
    driver = get_driver()
    from ...devices.hdc.input import clear_text as hdc_clear_text
    hdc_clear_text(driver)
    return json.dumps({
        "action": "clear_text",
        "message": "clear text successfully"
    })


@collect_function_tool
async def clear_text():
    """
    清除当前聚焦的输入框中的文本。
    """
    return await asyncio.to_thread(_clear_text)


# === Navigation Operations ===
def _back(delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import back as hdc_back
    hdc_back(driver, delay)
    return json.dumps({
        "action": "back",
        "message": "press back button successfully"
    })


@collect_function_tool
async def back(delay: float | None = None):
    """
    按下返回键。

    Args:
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_back, delay)


def _home(delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import home as hdc_home
    hdc_home(driver, delay)
    return json.dumps({
        "action": "home",
        "message": "press home button successfully"
    })


@collect_function_tool
async def home(delay: float | None = None):
    """
    按下主页键。

    Args:
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_home, delay)


# === App Operations ===
def _launch_app(app_name: str, delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import launch_app as hdc_launch_app
    result = hdc_launch_app(driver, app_name, delay)
    return json.dumps({
        "action": "launch_app",
        "app_name": app_name,
        "success": result,
        "message": "launch app '{}' successfully".format(app_name) if result else "failed to launch app '{}'".format(
            app_name)
    })


@collect_function_tool
async def launch_app(app_name: str, delay: float | None = None):
    """
    启动应用程序。

    Args:
        app_name: 应用名称
        delay: 可选的延迟时间（秒）

    Returns:
        bool: 启动是否成功
    """
    return await asyncio.to_thread(_launch_app, app_name, delay)


# === Pinch Operations ===
def _pinch_in(left: int, top: int, right: int, bottom: int, scale: float = 0.4, direction: str = "diagonal",
              delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import pinch_in as hdc_pinch_in

    hdc_pinch_in(driver, left, top, right, bottom, scale, direction, delay)
    return json.dumps({
        "action": "pinch_in",
        "rect": [left, top, right, bottom],
        "scale": scale,
        "direction": direction,
        "message": "pinch in (zoom out) successfully"
    })


@collect_function_tool
async def pinch_in(left: int, top: int, right: int, bottom: int, scale: float = 0.4, direction: str = "diagonal",
                   delay: float | None = None):
    """
    捏合手势（缩小/zoom out）- 双指向中心移动。

    Args:
        left: 矩形左边界
        top: 矩形上边界
        right: 矩形右边界
        bottom: 矩形下边界
        scale: 缩放比例 (0-1)，值越小表示缩放距离越长 (默认 0.4)
        direction: 手势方向，"diagonal" (对角线) 或 "horizontal" (水平，默认 "diagonal")
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_pinch_in, left, top, right, bottom, scale, direction, delay)


def _pinch_out(left: int, top: int, right: int, bottom: int, scale: float = 1.6, direction: str = "diagonal",
               delay: float | None = None):
    driver = get_driver()
    from ...devices.hdc import pinch_out as hdc_pinch_out

    hdc_pinch_out(driver, left, top, right, bottom, scale, direction, delay)
    return json.dumps({
        "action": "pinch_out",
        "rect": [left, top, right, bottom],
        "scale": scale,
        "direction": direction,
        "message": "pinch out (zoom in) successfully"
    })


@collect_function_tool
async def pinch_out(left: int, top: int, right: int, bottom: int, scale: float = 1.6, direction: str = "diagonal",
                    delay: float | None = None):
    """
    张开手势（放大/zoom in）- 双指从中心向外移动。

    Args:
        left: 矩形左边界
        top: 矩形上边界
        right: 矩形右边界
        bottom: 矩形下边界
        scale: 缩放比例 (1-2)，值越大表示缩放距离越长 (默认 1.6)
        direction: 手势方向，"diagonal" (对角线) 或 "horizontal" (水平，默认 "diagonal")
        delay: 可选的延迟时间（秒）
    """
    return await asyncio.to_thread(_pinch_out, left, top, right, bottom, scale, direction, delay)


@collect_function_tool
async def swipe_to_back():
    """
    侧滑返回，可用于返回
    """
    driver = get_driver()
    await asyncio.to_thread(driver.swipe_to_back)
    return json.dumps({
        "action": "swipe_to_back",
        "message": "swipe to back successfully"
    })
