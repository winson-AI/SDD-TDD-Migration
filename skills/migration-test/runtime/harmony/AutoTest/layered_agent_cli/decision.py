import asyncio
import json
from pathlib import Path

from agents import Runner
from agents.exceptions import MaxTurnsExceeded
from agents.run import ModelInputData, RunConfig

from .decision_hooks import DecisionHooks
from .planner_agent import create_planner_agent
from ..config import AppConfig
from ..devices.device_protocol import DeviceProtocol
from ..logger import logger
from ..memory.compressed_session import CompressedSession
from ..memory.tool_recorder import ToolRecorder
from ..reporter.reporter_abs import ReporterAbs
from ..storage import output_path
from ..utils.utils import capture_stable_snapshot

TASK_TYPES = ('test', 'snapshot', 'recording')
NO_VERIFY_TASK_TYPES = ('snapshot', 'recording')


def media_outcome(task_type, reached, snapshot_path, report_generator, task_result):
    """What a snapshot or recording task walked to, as a managed JSON artifact beside the report: the SDD adapter reads
    this file, not the prose summary."""
    video_dir = getattr(report_generator, 'video_dir', None)
    recording = Path(video_dir) / 'final.mp4' if task_type == 'recording' and video_dir else None
    layout = None
    if snapshot_path:
        candidate = Path(getattr(report_generator, 'layout_dir', None) or '') / (Path(snapshot_path).stem + '.json')
        layout = str(candidate) if candidate.is_file() else None
    outcome = {'task_type': task_type, 'reached': bool(reached),
               'snapshot_path': snapshot_path if snapshot_path and Path(snapshot_path).is_file() else None,
               'layout_path': layout,
               'recording_path': str(recording) if recording is not None and recording.is_file() else None,
               'reason': None if reached else task_result}
    lines = [f"任务类型: {task_type}", '路径结果: ' + ('已到达路径终点' if reached else '未到达路径终点，需人工review')]
    lines.append(f"最终截图: {outcome['snapshot_path'] or '（截图失败）'}" if task_type == 'snapshot'
                 else f"录屏文件: {outcome['recording_path'] or '（录屏缺失）'}")
    if not reached:
        lines.append(f"中断原因: {task_result}")
    outcome['text'] = '\n'.join(lines)
    report_dir = getattr(report_generator, 'report_dir', None)
    if report_dir:
        target = output_path(Path(report_dir) / 'media_outcome.json', boundary=Path(report_dir))
        target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
    return outcome


async def create_session_input_filter(session: CompressedSession):
    """
    Create an input filter that fetches compressed history from session.
    
    This ensures that each LLM call uses the compressed history from the session,
    not just the first one. The filter is created once and reused for all calls.
    
    Args:
        session: The CompressedSession instance to fetch history from
        
    Returns:
        An async function that filters model input using session history
    """

    # Cache the items reference to avoid repeated async calls
    # The session items are managed by the Runner, so we just need to fetch them
    async def session_aware_input_filter(call_model_data):
        # Get compressed history from session - this contains all conversation history
        # including the original task and all previous responses (compressed if needed)
        compressed_history = await session.get_items()

        # Use the compressed history directly as the model input
        # This replaces the original input which may contain uncompressed history
        return ModelInputData(
            input=compressed_history,
            instructions=call_model_data.model_data.instructions
        )

    return session_aware_input_filter





async def decision(task: str, config: AppConfig, report_generator: ReporterAbs, device: DeviceProtocol,
                   task_type: str = 'test'):
    # test judges pass/fail through Verify; snapshot and recording walk the path and keep its media, never a test result.
    if task_type not in TASK_TYPES:
        raise ValueError('SDD automation task_type must be one of ' + ', '.join(TASK_TYPES))
    task_result = None
    needs_manual_review = False
    snapshot_path = None

    # Initialize Planner
    logger.info(f"Initializing Planner ({config.decision_model_name})...")
    planner = create_planner_agent(config, device, report_generator)
    if not planner:
        raise ValueError("Failed to create planner agent.Check configuration and logs")

    # Run Task
    logger.info(f"\nTask: {task}")
    logger.info("Planner is thinking...")

    report_generator.task_start()

    task_timeout = config.task_timeout

    # Initialize Tool Recorder
    tool_recorder = ToolRecorder(task)

    # Create CompressedSession for persistent compression
    session = CompressedSession(auto_compress=True)

    # Create input filter that fetches compressed history from session
    # This ensures each LLM call uses the compressed history
    input_filter = await create_session_input_filter(session)

    try:
        run_config = RunConfig(
            call_model_input_filter=input_filter,
        )

        result = await asyncio.wait_for(
            Runner.run(planner, task, max_turns=config.max_steps,
                       hooks=DecisionHooks(device, session, report_generator, tool_recorder, task,
                                           require_verify=task_type not in NO_VERIFY_TASK_TYPES),
                       session=session,
                       run_config=run_config),
            timeout=task_timeout
        )

        logger.info(f"\nFinal Result: {result.final_output}")
        task_result = str(result.final_output)

    except MaxTurnsExceeded:
        needs_manual_review = True
        task_result = f"Error: 任务结果: 不通过，超过步数{config.max_steps}"
        logger.error(task_result)

    except asyncio.TimeoutError:
        needs_manual_review = True
        task_result = f"Error: 任务结果: 不通过，任务执行超时，已运行超过{task_timeout // 60}分钟，自动终止"
        logger.error(task_result)

    except Exception as e:
        needs_manual_review = True
        logger.exception(f"\nError: {e}")
        task_result = f"Error: 任务结果: 不通过，Error: {e}"

    finally:
        if task_type == 'snapshot':  # the final frame before teardown touches the screen; best effort even when the path was cut short
            try:
                snapshot_path = await capture_stable_snapshot(device, report_generator)
                logger.info(f"[Snapshot] Final snapshot saved: {snapshot_path}")
            except Exception as e:
                logger.warning(f"[Snapshot] Failed to capture final snapshot: {e}")
        device.teardown()  # a recording task's final.mp4 is pulled here; decision_cli keeps it by forcing keep_raw_video
        try:
            report_generator.task_end(task_result=task_result)
        except Exception as e:
            logger.exception(f"Generate report error {e}")

        try:
            if task_result and "任务结果: 不通过" in task_result:
                logger.info(f"[Decision] Task not passed, skip saving tool recording")
            else:
                recording_path = tool_recorder.save_to_file()
                logger.info(f"[Decision] Tool calls saved to: {recording_path}")
        except Exception as e:
            logger.warning(f"Failed to save tool recording: {e}")

    if task_type in NO_VERIFY_TASK_TYPES:
        task_result = media_outcome(task_type, not needs_manual_review, snapshot_path, report_generator, task_result)['text']
        logger.info(f"\n{task_result}")
    return task_result
