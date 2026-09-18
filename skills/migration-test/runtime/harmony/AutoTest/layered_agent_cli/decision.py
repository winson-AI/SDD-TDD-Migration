import asyncio

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





async def decision(task: str, config: AppConfig, report_generator: ReporterAbs, device: DeviceProtocol):
    task_result = None

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
                       hooks=DecisionHooks(device, session, report_generator, tool_recorder, task),
                       session=session,
                       run_config=run_config),
            timeout=task_timeout
        )

        logger.info(f"\nFinal Result: {result.final_output}")
        task_result = str(result.final_output)

    except MaxTurnsExceeded:
        task_result = f"Error: 任务结果: 不通过，超过步数{config.max_steps}"
        logger.error(task_result)

    except asyncio.TimeoutError:
        task_result = f"Error: 任务结果: 不通过，任务执行超时，已运行超过{task_timeout // 60}分钟，自动终止"
        logger.error(task_result)

    except Exception as e:
        logger.exception(f"\nError: {e}")
        task_result = f"Error: 任务结果: 不通过，Error: {e}"

    finally:
        device.teardown()
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

    return task_result
