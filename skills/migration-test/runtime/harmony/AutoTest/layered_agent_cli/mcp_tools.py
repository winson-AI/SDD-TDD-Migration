import json
import asyncio
import time
import os
import sys
import subprocess
import importlib.util
import glob
import re
import shlex
import traceback
import ast
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace

from typing import Any, Optional, Dict, List

from agents.model_settings import ModelSettings
from agents.models.interface import ModelTracing
from agents import function_tool
from hypium import UiDriver

from ..logger import logger
from ..config import config_manager
from ..layered_agent_cli.model_factory import create_multi_model
from ..utils.utils import extract_text_from_response

from .agent_registry import agent_registry
from .skill_manager import SkillManager
from ..devices.hdc import APP_PACKAGES, APP_ABILITIES

# 在模块顶部创建一个注册表
TOOL_REGISTRY = {}
_CUSTOM_TOOLS_LOADED = False
CHAT_LOCK = asyncio.Lock()

skill_manager = SkillManager()

def _run_shell_command_sync(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 120,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Synchronously run a shell command and return structured result."""
    shell_env = dict(os.environ)
    if env:
        shell_env.update(env)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=shell_env,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout + stderr if stderr else stdout

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output": combined[-8000:] if len(combined) > 8000 else combined,
            "truncated": len(combined) > 8000,
            "command": command,
            "cwd": cwd or os.getcwd(),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "output": f"Command timed out after {timeout} seconds",
            "truncated": False,
            "command": command,
            "cwd": cwd or os.getcwd(),
            "timeout": True,
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "output": f"Error executing command: {e}",
            "truncated": False,
            "command": command,
            "cwd": cwd or os.getcwd(),
        }

# 失败关键词列表
FAILURE_KEYWORDS = [
    "无法", "未找到", "不存在", "失败", "错误",
    "不能执行", "无法完成", "没有找到", "不存在",
    "不存在", "不能", "无能为力", "不可能"
]

# V2 prompt 的结构化输出格式
SUCCESS_PATTERN = re.compile(r'\[SUCCESS\]\s*(.+)', re.DOTALL)
FAILURE_PATTERN = re.compile(r'\[FAILURE\]\s*(.+)', re.DOTALL)
FAILED_STEP_PATTERN = re.compile(r'\[FAILED_STEP\]\s*(.+)', re.DOTALL)
STEP_PATTERN = re.compile(r'\[STEP\]\s*(.+)', re.DOTALL)


def parse_v2_output(output: str) -> Dict[str, Any]:
    """解析 V2 prompt 的结构化输出格式"""
    result = {
        "success": True,
        "result": output,
        "history": [],
        "failure_reason": None,
        "failed_step": None,
        "replan_required": False
    }
    
    # 检查是否是失败
    failure_match = FAILURE_PATTERN.search(output)
    if failure_match:
        result["success"] = False
        result["result"] = failure_match.group(1).strip()
        result["failure_reason"] = failure_match.group(1).strip()
        result["replan_required"] = True
        
        # 提取失败步骤
        failed_step_match = FAILED_STEP_PATTERN.search(output)
        if failed_step_match:
            result["failed_step"] = failed_step_match.group(1).strip()
    else:
        # 检查成功标记
        success_match = SUCCESS_PATTERN.search(output)
        if success_match:
            result["result"] = success_match.group(1).strip()
    
    # 提取所有步骤
    for step_match in STEP_PATTERN.finditer(output):
        result["history"].append(step_match.group(1).strip())
    
    # 如果没有找到任何步骤标记，但结果是失败，也尝试提取一些信息
    if not result["history"]:
        # 尝试从结果中提取历史信息
        lines = output.split('\n')
        for line in lines:
            if '[SUCCESS]' in line or '[FAILURE]' in line or '[FAILED_STEP]' in line or '[STEP]' in line:
                continue
            if line.strip() and len(line.strip()) > 10:
                result["history"].append(line.strip())
                break
    
    return result


def detect_failure(result: str) -> tuple[bool, str, Optional[str]]:
    """检测执行结果是否失败
    
    Args:
        result: 执行结果字符串
        
    Returns:
        (is_failed, failure_reason, failed_step)
    """
    # 1. 先尝试解析 JSON
    try:
        if result.startswith('{') or result.startswith('['):
            data = json.loads(result)
            if isinstance(data, dict):
                # 检查 success 字段
                if 'success' in data:
                    return not data['success'], data.get('failure_reason', ''), data.get('failed_step')
                # 检查 result 字段
                result_text = data.get('result', '')
                if result_text:
                    # 如果 result 包含失败关键词
                    for keyword in FAILURE_KEYWORDS:
                        if keyword in result_text:
                            return True, result_text, data.get('failed_step')
    except json.JSONDecodeError:
        pass
    
    # 2. 尝试解析 V2 的结构化输出
    parsed = parse_v2_output(result)
    if parsed['success'] is False:
        return True, parsed['failure_reason'], parsed['failed_step']
    
    # 3. 使用关键词检测
    for keyword in FAILURE_KEYWORDS:
        if keyword in result:
            return True, result, None
    
    return False, '', None


def collect_function_tool(func):
    """
    收集并注册 function_tool 函数
    """
    # 先应用装饰器，得到装饰后的对象
    decorated_func = function_tool(func)
    # 将装饰后的函数存储到注册表
    if func.__name__ not in TOOL_REGISTRY:
        TOOL_REGISTRY[func.__name__] = decorated_func
    return decorated_func


def get_registered_tools():
    """
    获取所有注册的工具函数列表
    """
    return list(TOOL_REGISTRY.values())


def get_driver() -> UiDriver:
    executor_agent = agent_registry.get_executor_agent()
    hdc_device = executor_agent.device
    return hdc_device.driver


def _build_skill_script_context(
    skill_name: str,
    script_name: str,
    script_path: str,
    skill_dir: Optional[str],
    args: str,
    base_cwd: Optional[str] = None,
) -> SimpleNamespace:
    """Build runtime context injected into in-process skill scripts."""
    executor_agent = agent_registry.get_executor_agent()
    device = getattr(executor_agent, "device", None)
    driver = getattr(device, "driver", None) if device else None
    hypium_device = getattr(driver, "_device", None) if driver else None
    report_generator = (
        getattr(executor_agent, "_report_generator", None)
        or getattr(executor_agent, "report_generator", None)
        or getattr(device, "_report_generator", None)
        or getattr(device, "report_generator", None)
    )
    report_dir = getattr(report_generator, "report_dir", None) if report_generator else None
    if report_dir is not None:
        report_dir = os.fspath(report_dir)
        if not os.path.isabs(report_dir) and base_cwd:
            report_dir = os.path.join(base_cwd, report_dir)
        report_dir = os.path.abspath(report_dir)

    return SimpleNamespace(
        skill_name=skill_name,
        script_name=script_name,
        script_path=script_path,
        skill_dir=skill_dir,
        args=args,
        argv=shlex.split(args) if args else [],
        executor_agent=executor_agent,
        device=device,
        driver=driver,
        hypium_device=hypium_device,
        report_dir=report_dir,
    )


def _json_safe(value: Any) -> Any:
    """Return value if JSON-serializable, otherwise return its repr."""
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return repr(value)


def _python_skill_has_in_process_entrypoint(script_path: str) -> bool:
    """Return whether a Python skill script declares run(context)/main(context)."""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=script_path)
    except Exception as e:
        logger.warning(f"[SkillScript] Failed to parse Python script {script_path}: {e}")
        return False

    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in ("run", "main")
        and (node.args.args or node.args.posonlyargs)
        for node in tree.body
    )


def _run_python_skill_script_in_process_sync(
    skill_name: str,
    script_name: str,
    script_path: str,
    skill_dir: Optional[str],
    args: str,
) -> Dict[str, Any]:
    """Run a Python skill script in the current process if it exposes run/main."""
    stdout = StringIO()
    stderr = StringIO()
    old_cwd = os.getcwd()
    added_sys_path = False
    module_name = f"_skill_script_{re.sub(r'[^0-9a-zA-Z_]', '_', skill_name)}_{int(time.time() * 1000)}"

    try:
        if skill_dir:
            os.chdir(skill_dir)
            if skill_dir not in sys.path:
                sys.path.insert(0, skill_dir)
                added_sys_path = True

        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if not spec or not spec.loader:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "",
                "output": f"Unable to load Python script: {script_path}",
                "truncated": False,
                "script_path": script_path,
                "cwd": skill_dir or old_cwd,
                "in_process": True,
            }

        module = importlib.util.module_from_spec(spec)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            spec.loader.exec_module(module)

            entry = getattr(module, "run", None) or getattr(module, "main", None)
            if not callable(entry):
                return {
                    "success": False,
                    "fallback_to_subprocess": True,
                    "returncode": -1,
                    "stdout": stdout.getvalue(),
                    "stderr": stderr.getvalue(),
                    "output": "Python script has no callable run(context) or main(context) entrypoint",
                    "truncated": False,
                    "script_path": script_path,
                    "cwd": skill_dir or old_cwd,
                    "in_process": True,
                }

            context = _build_skill_script_context(skill_name, script_name, script_path, skill_dir, args, old_cwd)
            result = entry(context)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)

        stdout_value = stdout.getvalue()
        stderr_value = stderr.getvalue()
        output_parts = []
        if stdout_value:
            output_parts.append(stdout_value)
        if stderr_value:
            output_parts.append(stderr_value)
        if result is not None:
            output_parts.append(result if isinstance(result, str) else json.dumps(_json_safe(result), ensure_ascii=False))
        combined = "".join(output_parts)

        return {
            "success": True,
            "returncode": 0,
            "stdout": stdout_value,
            "stderr": stderr_value,
            "result": _json_safe(result),
            "output": combined[-8000:] if len(combined) > 8000 else combined,
            "truncated": len(combined) > 8000,
            "script_path": script_path,
            "cwd": skill_dir or old_cwd,
            "in_process": True,
        }
    except Exception as e:
        stdout_value = stdout.getvalue()
        stderr_value = stderr.getvalue()
        error = traceback.format_exc()
        combined = stdout_value + stderr_value + error
        return {
            "success": False,
            "returncode": -1,
            "stdout": stdout_value,
            "stderr": stderr_value + error,
            "error": repr(e),
            "output": combined[-8000:] if len(combined) > 8000 else combined,
            "truncated": len(combined) > 8000,
            "script_path": script_path,
            "cwd": skill_dir or old_cwd,
            "in_process": True,
        }
    finally:
        if added_sys_path:
            try:
                sys.path.remove(skill_dir)
            except ValueError:
                pass
        os.chdir(old_cwd)


async def _summarize_context(executor_agent) -> str:
    # Filter out system prompts and images from history
    filtered_context = []
    for msg in executor_agent.context:
        if msg.get("role") == "system":
            continue

        new_msg = msg.copy()
        content = msg.get("content")
        if isinstance(content, list):
            # Filter out image content, keep text and other types
            new_msg["content"] = [
                item for item in content
                if not isinstance(item, dict) or item.get("type") not in ["image_url", "image"]
            ]

        filtered_context.append(new_msg)
    try:

        report_generator = getattr(executor_agent, "_report_generator", None)
        if not report_generator:
            report_generator = getattr(executor_agent, "report_generator", None)

        config = config_manager.get_effective_config()

        summary_model, summary_settings = create_multi_model(config.decision_models)
        # 构建 LLM 输入
        system_instruction = (
            "你是一位自动化执行审计专家。请将智能体的执行历史总结为一份简明的中文报告。\n"
            "要求：\n"
            "1. 格式：采用编号列表形式（如 '1. 智能体启动应用...'）。\n"
            "2. 内容重点：聚焦于智能体的关键操作和可见结果。除非涉及故障排查，否则省略底层技术细节。\n"
            "3. 异常处理：明确标出智能体遇到的任何错误或异常情况。\n"
            "4. 总结目标：清晰呈现智能体完成了哪些任务，以及在何处停止。\n"
            "5. 术语规范：在报告中统一使用'智能体'称呼执行主体。\n"
            "6. 简洁性：描述务必简短，直接陈述事实，去除任何冗余修饰。"
        )

        message = json.dumps(filtered_context, ensure_ascii=False)
        user_input = {
            "role": "user",
            "content": [{"type": "input_text", "text": f"历史执行记录: {message}"}]
        }

        response = await summary_model.get_response(
            system_instructions=system_instruction,
            input=[user_input],
            model_settings=summary_settings,
            tools=[],
            output_schema=None,
            handoffs=[],
            tracing=ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None
        )

        if response.usage:
            logger.info(f"[Executor] Summary Token Usage: Input={response.usage.input_tokens}, "
                        f"Output={response.usage.output_tokens}, "
                        f"Total={response.usage.total_tokens}")
            if report_generator:
                report_generator.token_usage(usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.total_tokens
                }, source="Executor(Summary)")
        return extract_text_from_response(response)
    except Exception as e:
        logger.info(f"[Executor] Summary Error: {e}")
        context_json = json.dumps(
            filtered_context, ensure_ascii=False
        )
        summary_text = context_json
        return summary_text


@collect_function_tool
async def execute(message: str) -> str:
    """向执行模型发送子任务指令。"""
    async with CHAT_LOCK:

        # 从 agent_registry 读取知识库内容，拼接到子任务指令后供执行模型参考
        knowledge = agent_registry.get_knowledge()
        executor_message = message + "\n\n" + knowledge if knowledge else message
        logger.info(f"\n[Executor] Running: {executor_message}")

        executor_agent = agent_registry.get_executor_agent()
        MCP_MAX_STEPS = executor_agent.agent_config.max_steps

        try:
            # 在同步方法中调用同步的 agent.run
            # 由于我们是在 executor 的独立上下文运行，这里直接调用
            # 注意：这里会阻塞 asyncio loop，但在 CLI 工具中是可以接受的
            # 或者使用 asyncio.to_thread 包装

            def run_sync():
                executor_agent.reset()
                run_result = executor_agent.run(executor_message)
                return run_result, executor_agent.step_count

            result, steps = await asyncio.to_thread(run_sync)

            logger.info(f"[Executor] Result ({steps} steps): {result}")

            history = getattr(executor_agent, "history", None)

            if history:
                summary_text = history
            else:
                summary_text = await _summarize_context(executor_agent)

            # 检测是否失败
            is_failed, failure_reason, failed_step = detect_failure(result)

            # 构建结构化返回结果
            if steps >= MCP_MAX_STEPS and result == "Max steps reached":
                return json.dumps({
                    "result": f"⚠️ 已达到最大步数限制（{MCP_MAX_STEPS}步）。执行模型可能遇到了困难，任务未完成。"
                              f"\n\n请查看执行历史\n\n建议: 请重新规划任务或将其拆分为更小的子任务",
                    "steps": MCP_MAX_STEPS,
                    "success": False,
                    "history": summary_text if isinstance(summary_text, list) else [summary_text],
                    "failure_reason": "达到最大步数限制",
                    "failed_step": "未知",
                    "replan_required": True,
                    "original_task": message,
                    "suggestion": "请重新规划任务或将其拆分为更小的子任务"
                }, ensure_ascii=False)

            # 如果检测到失败
            if is_failed:
                logger.warning(f"[Executor] Detected failure: {failure_reason}")
                return json.dumps({
                    "result": failure_reason or result,
                    "steps": steps,
                    "success": False,
                    "history": summary_text if isinstance(summary_text, list) else [summary_text],
                    "failure_reason": failure_reason or result,
                    "failed_step": failed_step or message,
                    "replan_required": True,
                    "original_task": message,
                    "suggestion": "请重新规划任务，检查目标选项名称是否正确，或使用替代方案"
                }, ensure_ascii=False)

            # 成功情况
            return json.dumps({
                "result": result,
                "steps": steps,
                "success": True,
                "history": summary_text if isinstance(summary_text, list) else [summary_text]
            }, ensure_ascii=False)

        except Exception as e:
            logger.info(f"[Executor] Error: {e}")
            return json.dumps({
                "result": str(e),
                "success": False,
                "history": [],
                "failure_reason": f"执行异常: {str(e)}",
                "failed_step": message,
                "replan_required": True,
                "original_task": message,
                "suggestion": "请重新规划任务"
            }, ensure_ascii=False)


@collect_function_tool
async def get_package_name() -> dict[str, str]:
    """获取所有支持的包名"""
    return APP_PACKAGES


def _start_app(app_name: str) -> str:
    bundle_name = APP_PACKAGES.get(app_name, app_name)
    ability = APP_ABILITIES.get(bundle_name)
    driver = get_driver()
    start_time = time.time()
    driver.start_app(bundle_name, ability)
    from ..devices.hdc import get_current_app
    while time.time() - start_time < 10:
        current_app_name = get_current_app(driver)
        if current_app_name == app_name or APP_PACKAGES.get(current_app_name, current_app_name) == app_name:
            driver.wait(6)
            return "start {} successfully".format(app_name)
        driver.wait(0.5)
    return "start {} failed!".format(app_name)


@collect_function_tool
async def start_app(app_name: str) -> str:
    """启动对应名称的app，优先使用此方法来启动应用"""
    return await asyncio.to_thread(_start_app, app_name)


def _stop_app(app_name: str) -> str:
    bundle_name = APP_PACKAGES.get(app_name, app_name)
    driver = get_driver()
    driver.stop_app(bundle_name)
    return "stop {} successfully. Task Finished. Please output the final result now.".format(app_name)


@collect_function_tool
async def stop_app(app_name: str) -> str:
    """杀掉对应名称的app"""
    return await asyncio.to_thread(_stop_app, app_name)


def _clear_app(app_name: str) -> str:
    bundle_name = APP_PACKAGES.get(app_name, app_name)
    driver = get_driver()
    driver.clear_app_data(bundle_name)
    return "clear {} successfully".format(app_name)


@collect_function_tool
async def clear_app(app_name: str) -> str:
    """清除对应应用的数据，用于模拟应用首次安装的情况"""
    return await asyncio.to_thread(_clear_app, app_name)


def _go_back() -> str:
    driver = get_driver()
    driver.press_back()
    return "go back successfully"


@collect_function_tool
async def go_back() -> str:
    """单次返回"""
    return await asyncio.to_thread(_go_back)


def _go_back_twice() -> str:
    driver = get_driver()
    driver.press_back()
    driver.wait(1)
    driver.press_back()
    return "go back twice successfully"


@collect_function_tool
async def go_back_twice() -> str:
    """连续两次返回"""
    return await asyncio.to_thread(_go_back_twice)


@collect_function_tool
async def wait(times: int) -> str:
    """等待几秒，用于等待应用加载或者其他事情"""
    await asyncio.sleep(times)
    return json.dumps({
        "action": "wait",
        "seconds": times,
        "message": "wait {} seconds successfully".format(times)
    })


def _go_home() -> str:
    driver = get_driver()
    driver.press_home()
    return "go home successfully"


@collect_function_tool
async def go_home() -> str:
    """回到桌面"""
    return await asyncio.to_thread(_go_home)


@collect_function_tool
async def load_skill(skill_name: str) -> str:
    """
    加载指定技能的详细步骤。
    当你想使用某个技能时，请先调用此工具获取技能的具体操作步骤。
    如果技能包含脚本，你可以使用 list_skill_scripts 查看可用脚本，再用 run_skill_script 执行。
    如果技能引用文档，可以使用 read_skill_reference 阅读。
    """
    content = skill_manager.get_skill_content(skill_name)
    if not content:
        available = ", ".join(skill_manager.list_skills()) or "无"
        return f"未找到技能 '{skill_name}'。可用技能列表: {available}"

    scripts = skill_manager.list_scripts(skill_name)
    references = skill_manager.list_references(skill_name)
    extra_info = []
    if scripts:
        extra_info.append(f"\n\n📜 可用脚本 ({len(scripts)} 个): {', '.join(scripts)}\n使用 run_skill_script('{skill_name}', '<script_name>', [args...]) 执行脚本。")
    if references:
        extra_info.append(f"\n\n📚 可用参考文档 ({len(references)} 个): {', '.join(references)}\n使用 read_skill_reference('{skill_name}', '<filename>') 阅读文档。")

    return f"技能 '{skill_name}' 加载成功。内容如下：\n\n{content}" + "".join(extra_info)


@collect_function_tool
async def list_skill_scripts(skill_name: str) -> str:
    """
    列出指定技能的 scripts 目录下所有可用脚本文件。
    """
    scripts = skill_manager.list_scripts(skill_name)
    if not scripts:
        has_skill = skill_manager.get_skill(skill_name) is not None
        if not has_skill:
            return f"未找到技能 '{skill_name}'"
        return f"技能 '{skill_name}' 没有可用的脚本文件。"
    script_list = "\n".join(f"  - {s}" for s in scripts)
    return f"技能 '{skill_name}' 的可用脚本:\n{script_list}\n\n使用 run_skill_script('{skill_name}', '<script_name>', [args...]) 执行。"


async def _run_skill_script_impl(skill_name: str, script_name: str, args: str = "", timeout: int = 300) -> str:
    """
    执行指定技能 scripts 目录下的脚本文件。

    Python 脚本如果定义了 run(context) 或 main(context)，会在当前进程内执行，并注入当前运行时上下文：
    context.device 为当前 DeviceProtocol 实例，context.driver 为已连接的 UiDriver，
    context.hypium_device 为 UiDriver 内部的 hypium device 对象，可用于 UiDriver(context.hypium_device) 初始化。
    context.report_dir 为当前报告目录的绝对路径。
    未定义 run/main 的 Python 脚本会回退到原有子进程执行方式。

    Args:
        skill_name: 技能名称
        script_name: 脚本文件名（如 quick_diagnose.sh）
        args: 传递给脚本的命令行参数字符串（如 "start/ stop/ CardCellViewModel"）
        timeout: 超时时间（秒），默认300秒

    Returns:
        JSON格式的执行结果，包含 success, stdout, stderr, returncode 等字段。
    """
    script_path = skill_manager.get_script_path(skill_name, script_name)
    if not script_path:
        scripts = skill_manager.list_scripts(skill_name)
        available = ", ".join(scripts) if scripts else "无"
        return json.dumps({
            "success": False,
            "error": f"脚本 '{script_name}' 未在技能 '{skill_name}' 中找到。可用脚本: {available}",
        }, ensure_ascii=False)

    skill_dir = skill_manager.get_skill_dir(skill_name)

    if script_name.endswith(".py") and _python_skill_has_in_process_entrypoint(script_path):
        logger.info(f"[SkillScript] Running in-process: skill={skill_name}, script={script_name}, cwd={skill_dir}")
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_python_skill_script_in_process_sync,
                    skill_name,
                    script_name,
                    script_path,
                    skill_dir,
                    args,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            result = {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "",
                "output": f"In-process Python script timed out after {timeout} seconds",
                "truncated": False,
                "script_path": script_path,
                "cwd": skill_dir or os.getcwd(),
                "timeout": True,
                "in_process": True,
            }

        if not result.get("fallback_to_subprocess"):
            logger.info(
                f"[SkillScript] In-process result: success={result['success']}, returncode={result['returncode']}"
            )
            return json.dumps(result, ensure_ascii=False)

        logger.info(
            f"[SkillScript] Python script has no in-process entrypoint, fallback to subprocess: {script_name}"
        )
    elif script_name.endswith(".py"):
        logger.info(f"[SkillScript] Python script has no in-process entrypoint, use subprocess: {script_name}")

    if script_name.endswith(".sh"):
        command = f"bash {shlex.quote(script_path)}"
    elif script_name.endswith(".py"):
        command = f"python3 {shlex.quote(script_path)}"
    elif script_name.endswith(".js"):
        command = f"node {shlex.quote(script_path)}"
    else:
        command = shlex.quote(script_path)

    if args:
        command += f" {args}"

    logger.info(f"[SkillScript] Running: skill={skill_name}, script={script_name}, cwd={skill_dir}")
    logger.info(f"[SkillScript] Command: {command}")

    result = await asyncio.to_thread(
        _run_shell_command_sync,
        command,
        skill_dir,
        timeout,
    )

    logger.info(f"[SkillScript] Result: success={result['success']}, returncode={result['returncode']}")
    return json.dumps(result, ensure_ascii=False)


@collect_function_tool
async def run_skill_script(skill_name: str, script_name: str, args: str = "", timeout: int = 300) -> str:
    """
    执行指定技能 scripts 目录下的脚本文件。

    Python 脚本如果定义了 run(context) 或 main(context)，会在当前进程内执行，并注入当前运行时上下文：
    context.device 为当前 DeviceProtocol 实例，context.driver 为已连接的 UiDriver，
    context.hypium_device 为 UiDriver 内部的 hypium device 对象，可用于 UiDriver(context.hypium_device) 初始化。
    context.report_dir 为当前报告目录的绝对路径。
    未定义 run/main 的 Python 脚本会回退到原有子进程执行方式。

    Args:
        skill_name: 技能名称
        script_name: 脚本文件名（如 quick_diagnose.sh）
        args: 传递给脚本的命令行参数字符串（如 "start/ stop/ CardCellViewModel"）
        timeout: 超时时间（秒），默认300秒

    Returns:
        JSON格式的执行结果，包含 success, stdout, stderr, returncode 等字段。
    """
    return await _run_skill_script_impl(skill_name, script_name, args, timeout)


@collect_function_tool
async def read_skill_reference(skill_name: str, filename: str) -> str:
    """
    读取指定技能 references 目录下的参考文档内容。

    Args:
        skill_name: 技能名称
        filename: 参考文档文件名（如 workflow.md）
    """
    content = skill_manager.read_reference(skill_name, filename)
    if content is None:
        refs = skill_manager.list_references(skill_name)
        available = ", ".join(refs) if refs else "无"
        has_skill = skill_manager.get_skill(skill_name) is not None
        if not has_skill:
            return f"未找到技能 '{skill_name}'"
        return f"参考文档 '{filename}' 未在技能 '{skill_name}' 中找到。可用文档: {available}"
    return f"参考文档 '{skill_name}/{filename}' 内容：\n\n{content}"


@collect_function_tool
async def run_shell_command(command: str, cwd: str = "", timeout: int = 120) -> str:
    """
    在终端执行 shell 命令并返回输出结果。
    可用于执行脚本、运行命令行工具、查看文件等操作。

    Args:
        command: 要执行的 shell 命令（如 "ls -la", "bash scripts/test.sh arg1", "node htool.js mem diff a.hprof b.hprof"）
        cwd: 执行命令的工作目录（可选，默认为当前工作目录）
        timeout: 超时时间（秒），默认120秒

    Returns:
        JSON格式的执行结果，包含 success, stdout, stderr, returncode, output, cwd 等字段。
        output 字段包含 stdout 和 stderr 的合并输出（超长时会截断，truncated=true 表示被截断）。

    注意事项:
    - 请使用安全的命令，避免执行危险操作（如 rm -rf /）
    - 对于长时间运行的命令，请适当增加 timeout 值
    - 执行技能脚本时，优先使用 run_skill_script 工具（它会自动设置正确的工作目录）
    """
    work_dir = cwd if cwd else None
    logger.info(f"[ShellCommand] Running: {command} (cwd={work_dir})")

    result = await asyncio.to_thread(
        _run_shell_command_sync,
        command,
        work_dir,
        timeout,
    )

    logger.info(f"[ShellCommand] Result: success={result['success']}, returncode={result['returncode']}")
    return json.dumps(result, ensure_ascii=False)


@collect_function_tool
async def summary(executed_tasks: str, current_blockers: str, next_plan: str) -> str:
    """
    梳理和记录当前的执行进度，防止陷入死循环
    当任务执行了多个步骤、遇到反复失败的错误、或者你需要重新规划时，请务必调用此工具

    Args:
        executed_tasks: 总结到目前为止已经成功完成的关键步骤。
        current_blockers: 当前遇到的困难、错误或一直卡住的地方 (如果没有请填“无”)
        next_plan: 基于当前现状，接下来的一到两步具体计划是什么？如果有 blocker，必须提出与之前不同的新方案。
    """
    logger.info("\n" + "=" * 40)
    logger.info("[Planner Summary & Reflection]")
    logger.info(f"✅ 已完成: {executed_tasks}")
    logger.info(f"⚠️ 当前障碍: {current_blockers}")
    logger.info(f"🚀 下一步计划: {next_plan}")
    logger.info("=" * 40 + "\n")
    return (
        f"✅ 进度已记录。你当前的思路非常清晰。\n"
        f"请严格按照你制定的【下一步计划】执行：{next_plan}\n"
        f"注意：如果【当前障碍】中记录了错误，请确保下一步使用了全新的思路，不要重复之前的无效操作！"
    )


def load_tools_from_file(file_path: str) -> list[str]:
    """
    从指定的 Python 文件中动态导入工具函数。

    该方法会：
    1. 加载指定路径的 .py 文件
    2. 执行其中的代码（这会触发 @collect_function_tool 装饰器）
    3. 返回所有成功导入的工具名称列表

    Args:
        file_path: 要导入的 Python 文件的绝对路径或相对路径

    Returns:
        成功导入的工具名称列表

    Example:
        >>> load_tools_from_file("mcp_tools/media_generator.py")
        ['generate_random_gradient_image_to_device', 'generate_random_gradient_video_to_device']
    """

    if not os.path.exists(file_path):
        logger.error(f"file not exist: {file_path}")
        return []

    try:
        # 从文件路径生成模块名
        file_name = os.path.basename(file_path)
        module_name = f"custom_tool_{os.path.splitext(file_name)[0]}"

        # 使用 importlib 动态导入
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.error(f"Cannot create module spec: {file_path}")
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        # 执行模块代码，这会触发装饰器注册
        spec.loader.exec_module(module)

        logger.info(f"success import {file_path}")

        return list(TOOL_REGISTRY.keys())

    except Exception as e:
        logger.error(f"import file failed: {e}")
        return []


def load_tools_from_directory(dir_path: str, pattern: str = "*.py") -> list[str]:
    """
    从指定目录批量导入 Python 文件中的工具函数。

    Args:
        dir_path: 要扫描的目录路径
        pattern: 文件匹配模式，默认为 "*.py"

    Returns:
        成功导入的工具名称列表
    """
    if not os.path.isdir(dir_path):
        logger.error(f"dir is no exist {dir_path}")
        return []

    loaded_tools = []
    for file_path in glob.glob(os.path.join(dir_path, pattern)):
        # 跳过私有文件（以_开头的）
        if os.path.basename(file_path).startswith("_"):
            continue
        tools = load_tools_from_file(file_path)
        loaded_tools.extend(tools)

    return loaded_tools
