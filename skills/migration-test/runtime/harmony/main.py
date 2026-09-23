import argparse
import asyncio

import re
import sys
import os

sys.dont_write_bytecode = True
import hashlib
import datetime

from hypium import UiDriver
from agents import set_tracing_disabled

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "", "")))

# Disable openai-agents SDK tracing: it reports to OpenAI's tracing endpoint
# using OPENAI_API_KEY regardless of the dashscope base_url/api_key configured
# for the actual model calls, which causes noisy 401 errors.
set_tracing_disabled(True)

from AutoTest.config import config_manager
from AutoTest.logger import configure_logger, logger
from AutoTest.devices.hdc_device import HDCDevice
from AutoTest.devices.hdc.apps import get_package_name
from AutoTest.reporter import ReportGenerator
from AutoTest.reporter.summary import generate_summary_report

from AutoTest.layered_agent_cli.decision import decision
from AutoTest.layered_agent_cli.mcp_tools import load_tools_from_directory
from AutoTest.layered_agent_cli.skill_manager import SkillManager
from AutoTest.layered_agent_cli.agent_registry import agent_registry
from AutoTest.verify_agent.agent import VerifyAgent
from AutoTest.memory.tool_player import ToolPlayer
from AutoTest.memory.tool_recorder import ToolRecorder
from AutoTest.layered_agent_cli.planner_agent import create_planner_agent


async def decision_cli(args, config):
    load_tools_from_directory(os.path.join(os.path.dirname(__file__), "mcp_tools"))

    SkillManager().load_skills(os.path.join(os.path.dirname(__file__), "skills"))

    # Initialize Report Generator
    report_generator = ReportGenerator(args.task, args.task_name, output_dir=args.report_dir)

    # Create hdc Device directly
    hdc_device = HDCDevice(args.device, args.ip, args.port, report_generator=report_generator, config=config)

    # init 验证工具
    verify_agent = VerifyAgent(report_generator, config, hdc_device)
    agent_registry.set_verify_agent(verify_agent)

    return await decision(args.task, config, report_generator, hdc_device)


async def playback_cli(args, config):
    load_tools_from_directory(os.path.join(os.path.dirname(__file__), "mcp_tools"))
    SkillManager().load_skills(os.path.join(os.path.dirname(__file__), "skills"))
    task_hash = hashlib.md5(args.task.encode('utf-8')).hexdigest()[:16]
    logger.info(f"[Playback] Task hash: {task_hash}")

    file_path = os.path.join(args.memory_dir, f"{task_hash}.json")
    session = ToolRecorder.load_from_file(file_path)

    if not session:
        logger.warning(
            f"[Playback] No recording found for task hash: {task_hash}, "
            f"falling back to normal execution mode"
        )
        logger.info(f"[Playback] Looked path: {file_path}")
        if not config.decision_base_url or not config.decision_model_name:
            logger.error("Error: Decision model not configured. Cannot fall back to normal execution.")
            return f"Error: 未找到录制文件且决策模型未配置 (task_hash: {task_hash})"
        return await decision_cli(args, config)

    logger.info(f"[Playback] Loaded: {session.task} ({session.total_calls} calls)")

    report_generator = ReportGenerator(session.task, f"playback_{session.task_hash}",
                                       output_dir=args.report_dir)

    hdc_device = HDCDevice(args.device, args.ip, args.port, report_generator=report_generator, config=config)

    verify_agent = VerifyAgent(report_generator, config, hdc_device)
    agent_registry.set_verify_agent(verify_agent)

    # Create planner agent for replanning on failure
    planner_agent = None
    try:

        planner_agent = create_planner_agent(config, hdc_device, report_generator)
        logger.info("[Playback] Planner agent initialized for replanning")
    except Exception as e:
        logger.warning(f"[Playback] Planner agent not initialized: {e}")

    player = ToolPlayer(
        device=hdc_device,
        report_generator=report_generator,
        executor_agent=agent_registry.get_executor_agent(),
        verify_agent=verify_agent,
        planner_agent=planner_agent,
        config=config
    )

    if not player.load_record(
            os.path.join(args.memory_dir, f"{session.task_hash}.json")
    ):
        logger.error("[Playback] Failed to load recording for playback")
        return

    logger.info("[Playback] Starting playback...")

    report_generator.task_start()

    try:
        result = await player.play_async()

        logger.info("\n" + "=" * 60)
        logger.info("Playback Summary")
        logger.info("=" * 60)

        if result.get("timeout"):
            logger.info(f"Task: {result.get('task','Unknown')}")
            logger.info(f"Status: Timeout")
            message = result.get('message','')
            logger.info(f"Message: {message}")
            logger.info(f"Step Count: {result.get('step_count',0)}")
            logger.info(f"Elapsed Time: {result.get('elapsed_seconds',0)}")
            task_result = f"Error: 回放超时, {message}"
        elif result.get("replan_triggered"):
            logger.info(f"Task: {result.get('task','Unknown')}")
            logger.info(f"Status: Replan Triggered")
            logger.info(f"Message: {result.get('message','')}")
            task_result = ""
            if player.last_playback_results:
                task_result = player.last_playback_results[-1].get("playback_result",'')
            if not task_result:
                failure_info = result.get("failure_info", {})
                failure_reason = failure_info.get('failure_reason','Unknown')
                logger.info(f"Failure Reason: {failure_reason}")
                logger.info(f"Failure Step: {failure_info.get('failure_step',0)}")
                task_result = f"Error: 回放中断, 触发重新规划, {failure_reason}"
        else:
            logger.info(f"Task: {result.get('task','Unknown')}")
            logger.info(f"Hash: {result.get('task_hash','Unknown')}")
            total_calls = result.get("total_calls", 0)
            successful_calls = result.get('successful_calls',0)
            logger.info(f"Total Calls: {total_calls}")
            logger.info(f"Successful: {successful_calls}")
            logger.info(f"Failed: {result.get('failed_calls',0)}")
            logger.info(f"Duration: {result.get('duration_seconds',0):.2f}s")
            logger.info("=" * 60)
            if result.get('results'):
                logger.info("\nDetailed Results:")
                for r in result['results']:
                    status = "[OK]" if r.get('success') else "[FAIL]"
                    logger.info(f"  {status} #{r.get('order')} {r.get('tool_name')}")
                    if not r.get('success'):
                        logger.info(f"      Error: {r.get('error', 'Unknown error')}")

            logger.info("\n" + "=" * 60)
            logger.info("Task Result Judgment")
            logger.info("=" * 60)
            logger.info("Requesting AI judgment...")

            try:
                judge_result = await player.judge_result(config)
                judge_reason = judge_result.get('reason','Unknown')
                model_used = judge_result.get('model_used','Unknown')
                logger.info(f"\nJudge Result:\n{judge_reason}")
                logger.info(f"\nModel: {model_used}")

                if judge_result.get('pass'):
                    task_result = (
                        f"任务结果: 通过\n"
                        f"执行摘要: {successful_calls}/{total_calls} 步骤成功\n"
                        f"详细原因: {judge_reason}\n"
                        f"评判模型: {model_used}"
                    )
                elif judge_result['fail']:
                    task_result = (
                        f"任务结果: 不通过\n"
                        f"执行摘要: {successful_calls}/{total_calls} 步骤成功\n"
                        f"失败原因: {judge_reason}\n"
                        f"评判模型: {model_used}"
                    )
                else:
                    task_result = (
                        f"回放完成: {successful_calls}/{total_calls} 成功\n"
                        f"评判结果: {judge_reason}"
                    )
            except Exception as e:
                logger.warning(f"[Playback] Judge request failed: {e}")
                task_result = (
                    f"回放完成: {successful_calls}/{total_calls} 成功\n"
                    f"错误信息: 无法获取 AI 评判结果 ({str(e)})"
                )
                logger.error(f"\nJudge Error: {e}")

    except Exception as e:
        logger.exception(f"[Playback] Error during playback: {e}")
        task_result = f"回放失败: {e}"

    finally:
        hdc_device.teardown()
        try:
            report_generator.task_end(task_result=task_result)
        except Exception as e:
            logger.exception(f"Generate report error {e}")

    return task_result


def parse_task_file(file_path, knowledge_path):
    """解析MD格式的测试用例文件"""
    if not os.path.isfile(file_path):
        logger.error(f"用例文件不存在: {file_path}")
        return []

    knowledge = {}
    if os.path.exists(knowledge_path):
        try:
            with open(knowledge_path, 'r', encoding='utf-8') as kf:
                knowledge = __import__('json').load(kf)
        except Exception as e:
            logger.warning(f"加载知识库失败: {e}")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 按分割线拆分用例
    case_blocks = content.split('---')
    test_cases = []

    for block in case_blocks:
        block = block.strip()
        if not block:
            continue

        # 提取用例描述
        if block.startswith('## 用例描述：'):
            lines = block.split('\n', 1)
            if len(lines) < 2:
                continue

            case_name = lines[0].replace('## 用例描述：', '').strip()
            task_content = lines[1].strip()

            matched_knowledge = []
            for key, value in knowledge.items():
                if key in block:
                    matched_knowledge.append(f"{key}: {value}")

            if matched_knowledge:
                knowledge_text = "\n\n知识库：\n" + "\n".join(f"{i+1}、{item}" for i, item in enumerate(matched_knowledge))
                task_content += knowledge_text

            if case_name and task_content:
                test_cases.append({
                    'name': case_name,
                    'task': task_content
                })

    logger.info(f"解析到 {len(test_cases)} 个测试用例")
    return test_cases


async def main():
    parser = argparse.ArgumentParser(description="AutoGLM Layered Agent CLI")
    parser.add_argument("--device", default=None, help="Device serial number (e.g., emulator-5554)")
    parser.add_argument("--ip", default="127.0.0.1", help="Device ip")
    parser.add_argument("--port", default=8710, help="Device port")
    parser.add_argument("--task", help="Task description")
    parser.add_argument("--report-dir", default=None, help="Directory to save execution reports")
    parser.add_argument("--task-name", default=None,
                        help="Test case name. If not provided, defaults to report-dir name.")
    parser.add_argument("--playback", action='store_true',
                        help="Enable playback mode, automatically finds recording based on task hash")
    parser.add_argument("--memory-dir", default=None, help="Optional historical recording directory to copy into this execution")
    parser.add_argument("--task-file", help="MD格式测试用例文件路径，批量执行多个任务")
    parser.add_argument("--xmind-output", default=None,
                        help="XMind 转换输出必须位于 runs/harmony/sandbox；默认当前执行 design 目录")
    parser.add_argument("--force-overwrite", action='store_true',
                        help="强制重新转换 xmind（即使已存在对应 md 也覆盖）")
    parser.add_argument("--app-name", default=None,
                        help="被测应用名称（如 抖音）；使用 --task-file 批量执行时为必填")
    args = parser.parse_args()
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'migration-ledger/scripts'))
    from runner_storage import harmony_output, scope
    from run_storage import checked_path
    if not args.report_dir:
        parser.error('--report-dir must be under .sdd-runs/<run_id>/runs/harmony/automation/')
    args.report_dir = str(harmony_output(None, args.report_dir, 'automation'))

    if args.report_dir:
        run_dir = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        for i in range(1000):
            candidate = os.path.join(args.report_dir, run_dir + (f"-{i}" if i else ""))
            try:
                os.makedirs(candidate, exist_ok=False)
                args.report_dir = candidate
                break
            except FileExistsError:
                continue
        else:
            print(f"无法创建唯一的报告目录 {args.report_dir}", file=sys.stderr)
            return
        log_file = os.path.join(args.report_dir, "agent.log")
    else:
        log_file = None

    import shutil
    recordings = Path(args.memory_dir).resolve() if args.memory_dir else None
    args.memory_dir = str(checked_path(Path(args.report_dir) / 'memory', args.report_dir))
    if recordings:
        if not recordings.is_dir(): parser.error('--memory-dir must be an existing recording source')
        Path(args.memory_dir).mkdir()
        for source in recordings.glob('*.json'):
            shutil.copyfile(source, Path(args.memory_dir) / source.name)
    args.xmind_output = str(harmony_output(next(p for p in Path(args.report_dir).parents if p.parent.name == '.sdd-runs'), args.xmind_output, 'sandbox') if args.xmind_output else Path(args.report_dir) / 'design')
    with scope(Path(args.report_dir)):
        return await run_native(args, log_file)


async def run_native(args, log_file):
    from pathlib import Path
    root = next(p for p in Path(args.report_dir).parents if p.parent.name == ".sdd-runs")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
    from harmony_environment import prepare_environment, load_environment
    config_path, env_path = prepare_environment(root)
    load_environment(env_path)
    config_manager.load_file_config(str(config_path.parent / 'config.native.yaml'))
    config = config_manager.get_effective_config()

    configure_logger(console_level="DEBUG" if config.verbose else "INFO", log_file=log_file)

    # 批量执行用例逻辑
    if args.task_file:
        if not (args.app_name and args.app_name.strip()):
            logger.error("使用 --task-file 批量执行时，必须传入非空的 --app-name（被测应用名称），用于停止对应应用及用例步骤1")
            return
        args.app_name = args.app_name.strip()
        # 若输入为 xmind，先转换为标准 md（复用现有 ai 模型与技能），再批量执行
        from AutoTest.testcase_preprocessor.pipeline import ensure_task_file
        try:
            task_file = await ensure_task_file(
                args.task_file, config,
                project_root=os.path.dirname(os.path.abspath(__file__)),
                output=args.xmind_output,
                force_overwrite=args.force_overwrite,
                app_name=args.app_name,
            )
        except Exception as e:
            logger.error(f"xmind 预处理失败: {e}")
            return

        knowledge_path = str(root.parent.parent / '.sdd-migration/harmony/knowledge' / f'{args.app_name}.json')
        test_cases = parse_task_file(task_file, knowledge_path)
        if not test_cases:
            logger.error("未解析到有效测试用例，请检查用例文件格式")
            return

        # 记录所有用例执行结果
        all_results = []
        total_start_time = asyncio.get_event_loop().time()

        # 创建临时设备实例用于关闭应用
        temp_driver = UiDriver.connect(device_sn=args.device, connector_server=(args.ip, args.port))

        def parse_case_result(task_result: str) -> str:
            """根据 task_result 解析用例执行结果: PASS / FAIL / UNKNOWN"""
            if not task_result:
                return "UNKNOWN"
            if task_result.startswith("Error:"):
                return "FAIL"
            match = re.search(r"结果\s*[:：]\s*(不?通过)", task_result)
            if match:
                return "PASS" if match.group(1) == "通过" else "FAIL"
            return "UNKNOWN"

        for idx, case in enumerate(test_cases, 1):
            logger.info(f"\n{'=' * 60}")
            logger.info(f"执行用例 {idx}/{len(test_cases)}: {case['name']}")
            logger.info(f"{'=' * 60}")

            try:
                package_name = get_package_name(args.app_name)
                temp_driver.stop_app(package_name)
                logger.info(f"已关闭{args.app_name}应用")
            except Exception as e:
                logger.warning(f"关闭应用失败: {e}")

            # 为每个用例生成独立的报告目录和日志文件
            case_report_dir = args.report_dir
            case_log_file = None
            if case_report_dir:
                # 替换非法文件名的字符
                safe_case_name = "".join([c for c in case['name'] if c.isalnum() or c in (' ', '-', '_')]).rstrip()
                case_report_dir = os.path.join(case_report_dir, safe_case_name)
                os.makedirs(case_report_dir, exist_ok=True)
                case_log_file = os.path.join(case_report_dir, "agent.log")

            # 复制args对象，修改为当前用例的参数
            import copy
            case_args = copy.deepcopy(args)
            case_args.task = case['task']
            case_args.task_name = case['name']
            case_args.report_dir = case_report_dir

            try:
                case_start_time = asyncio.get_event_loop().time()
                task_result = None
                if args.playback:
                    task_result = await playback_cli(case_args, config)
                    case_status = "success"
                else:
                    if not config.decision_base_url or not config.decision_model_name:
                        logger.error("Error: Decision model not configured. Please check config.yaml or env vars.")
                        all_results.append(
                            {"name": case['name'], "status": "fail", "error": "Decision model not configured",
                             "case_result": "FAIL",
                             "duration": 0, "report_dir": case_report_dir, "report_path": ""})
                        continue
                    task_result = await decision_cli(case_args, config)
                    case_status = "success"

                # 计算用例执行耗时
                case_duration = asyncio.get_event_loop().time() - case_start_time

                # 查找报告目录下的HTML报告文件
                report_path = ""
                if case_report_dir and os.path.exists(case_report_dir):
                    for filename in os.listdir(case_report_dir):
                        if filename.endswith(".html") and not filename == "index.html":
                            report_path = f"./{safe_case_name}/{filename}"
                            break

                # 根据任务执行结果解析用例业务结果(PASS/FAIL/UNKNOWN)
                case_result = parse_case_result(task_result)

                all_results.append({
                    "name": case['name'],
                    "status": case_status,
                    "case_result": case_result,
                    "duration": case_duration,
                    "report_dir": case_report_dir,
                    "report_path": report_path
                })
            except Exception as e:
                case_duration = asyncio.get_event_loop().time() - case_start_time
                logger.exception(f"用例 {case['name']} 执行失败: {e}")
                all_results.append({
                    "name": case['name'],
                    "status": "fail",
                    "case_result": "FAIL",
                    "error": str(e),
                    "duration": case_duration,
                    "report_dir": case_report_dir,
                    "report_path": ""
                })

        # 输出总览结果
        total_duration = asyncio.get_event_loop().time() - total_start_time
        success_count = sum(1 for r in all_results if r.get('case_result') == 'PASS')
        fail_count = sum(1 for r in all_results if r.get('case_result') == 'FAIL')

        logger.info(f"\n{'=' * 60}")
        logger.info("批量执行总览")
        logger.info(f"{'=' * 60}")
        logger.info(f"总用例数: {len(all_results)}")
        logger.info(f"成功: {success_count}")
        logger.info(f"失败: {fail_count}")
        logger.info(f"总耗时: {total_duration:.2f}s")
        logger.info(f"通过率: {(success_count / len(all_results) * 100):.1f}%")
        logger.info(f"{'=' * 60}")

        if fail_count > 0:
            logger.info("\n失败用例:")
            for r in all_results:
                if r.get('case_result') == 'FAIL':
                    logger.info(f"  - {r['name']}: {r.get('error', r.get('case_result', '失败'))}")

        # 生成汇总HTML报告
        if args.report_dir:
            generate_summary_report(all_results, total_duration, args.report_dir)

        # 关闭临时设备连接
        try:
            temp_driver.close()
        except Exception as e:
            logger.warning(f"关闭临时设备连接失败: {e}")

    else:

        if args.playback:
            if args.device:
                logger.info(f"Initializing Executor for device: {args.device}...")
            else:
                logger.info("Initializing Executor for random devices...")

            await playback_cli(args, config)
        else:
            if not args.task:
                logger.error("Error: --task is required in normal mode")
                return

            if not config.decision_base_url or not config.decision_model_name:
                logger.error("Error: Decision model not configured. Please check config.yaml or env vars.")
                return

            if args.device:
                logger.info(f"Initializing Executor for device: {args.device}...")
            else:
                logger.info("Initializing Executor for random devices...")

            await decision_cli(args, config)


if __name__ == "__main__":
    asyncio.run(main())
