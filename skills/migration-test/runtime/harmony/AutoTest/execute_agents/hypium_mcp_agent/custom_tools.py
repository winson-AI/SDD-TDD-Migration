"""
Custom tools for HypiumMCPAgent.
"""
import json
import asyncio
import inspect
from typing import Callable, Any

from hypium import UiDriver

from ...layered_agent_cli.agent_registry import agent_registry
from ...layered_agent_cli.mcp_tools import _run_skill_script_impl

CUSTOM_TOOL_REGISTRY: dict[str, Callable] = {}


def get_executor_agent():
    """获取 executor agent 实例"""
    return agent_registry.get_executor_agent()


def get_driver() -> UiDriver:
    executor_agent = get_executor_agent()
    hdc_device = executor_agent.device
    return hdc_device.driver


def collect_function_tool(func: Callable) -> Callable:
    CUSTOM_TOOL_REGISTRY[func.__name__] = func
    return func


def _infer_param_type(param: inspect.Parameter) -> str:
    """从类型注解或默认值推断 JSON schema 参数类型"""
    if param.annotation is not inspect.Parameter.empty:
        annotation_name = (
            param.annotation.__name__
            if hasattr(param.annotation, "__name__")
            else str(param.annotation)
        )
        
        if annotation_name in ("int", "integer"):
            return "integer"
        elif annotation_name in ("float", "number"):
            return "number"
        elif annotation_name == "bool":
            return "boolean"
        elif annotation_name in ("str", "string"):
            return "string"
    
    if param.default is not inspect.Parameter.empty:
        if isinstance(param.default, bool):
            return "boolean"
        elif isinstance(param.default, int):
            return "integer"
        elif isinstance(param.default, float):
            return "number"
        elif isinstance(param.default, str):
            return "string"
    
    return "string"


def get_custom_tools() -> list[dict[str, Any]]:
    tools = []
    for func in CUSTOM_TOOL_REGISTRY.values():
        sig = inspect.signature(func)
        params_schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for param_name, param in sig.parameters.items():
            if param.default is inspect.Parameter.empty:
                params_schema["required"].append(param_name)
            
            param_type = _infer_param_type(param)

            params_schema["properties"][param_name] = {
                "type": param_type,
                "description": param_name
            }

        tools.append({
            "name": func.__name__,
            "description": func.__doc__.strip() if func.__doc__ else func.__name__,
            "params_schema": params_schema,
            "func": func
        })
    return tools


def get_custom_tool(name: str):
    for tool in get_custom_tools():
        if tool["name"] == name:
            return tool
    return None


@collect_function_tool
def swipe_to_back():
    """
    侧滑返回，可用于返回。
    """
    get_driver().swipe_to_back()
    return json.dumps({
        "action": "swipe_to_back",
        "message": "swipe to back successfully"
    })


@collect_function_tool
def pinch_in(left: int, top: int, right: int, bottom: int, scale: float = 0.4, direction: str = "diagonal",
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
    driver = get_driver()
    from ...devices.hdc import pinch_in as hdc_pinch_in
    width, height = driver.get_display_size()

    left_actual = int(left / 1000 * width)
    top_actual = int(top / 1000 * height)
    right_actual = int(right / 1000 * width)
    bottom_actual = int(bottom / 1000 * height)

    hdc_pinch_in(driver, left_actual, top_actual, right_actual, bottom_actual, scale, direction, delay)
    return json.dumps({
        "action": "pinch_in",
        "rect": [left, top, right, bottom],
        "actual_rect": [left_actual, top_actual, right_actual, bottom_actual],
        "scale": scale,
        "direction": direction,
        "message": "pinch in (zoom out) successfully"
    })


@collect_function_tool
def pinch_out(left: int, top: int, right: int, bottom: int, scale: float = 1.6, direction: str = "diagonal",
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
    driver = get_driver()
    from ...devices.hdc import pinch_out as hdc_pinch_out
    width, height = driver.get_display_size()

    left_actual = int(left / 1000 * width)
    top_actual = int(top / 1000 * height)
    right_actual = int(right / 1000 * width)
    bottom_actual = int(bottom / 1000 * height)

    hdc_pinch_out(driver, left_actual, top_actual, right_actual, bottom_actual, scale, direction, delay)
    return json.dumps({
        "action": "pinch_out",
        "rect": [left, top, right, bottom],
        "actual_rect": [left_actual, top_actual, right_actual, bottom_actual],
        "scale": scale,
        "direction": direction,
        "message": "pinch out (zoom in) successfully"
    })


@collect_function_tool
def execute_run_skill_script(skill_name: str, script_name: str, args: str = "", timeout: int = 300) -> str:
    """
    执行指定技能 scripts 目录下的脚本文件。

    Args:
        skill_name: 技能名称
        script_name: 脚本文件名（如 quick_diagnose.sh）
        args: 传递给脚本的命令行参数字符串（如 "start/ stop/ CardCellViewModel"）
        timeout: 超时时间（秒），默认300秒

    Returns:
        JSON格式的执行结果，包含 success, stdout, stderr, returncode 等字段。
    """
    return asyncio.run(_run_skill_script_impl(skill_name, script_name, args, timeout))