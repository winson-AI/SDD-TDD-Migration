from abc import ABC, abstractmethod
from typing import Any, Callable, List, Dict

from ..config import AgentConfig, ModelConfig
from ..devices.device_protocol import DeviceProtocol
from ..reporter.reporter_abs import ReporterAbs


class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    All agent implementations must inherit from this class and implement the required methods.
    """

    def __init__(
            self,
            model_config: ModelConfig,
            agent_config: AgentConfig,
            device: DeviceProtocol,
            confirmation_callback: Callable[[str], bool] | None = None,
            thinking_callback: Callable[[str], None] | None = None,
            report_generator: ReporterAbs = None,
            **kwargs
    ):
        self.model_config = model_config
        self.agent_config = agent_config
        self.device = device
        self.confirmation_callback = confirmation_callback
        self._thinking_callback = thinking_callback
        self._report_generator = report_generator

    @abstractmethod
    def run(self, task: str) -> str:
        """
        Run the agent to complete the given task.
        
        Args:
            task: The task description string.
            
        Returns:
            The result of the task execution.
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """
        Reset the agent internal state (context, step count, etc.).
        """
        pass

    @property
    @abstractmethod
    def step_count(self) -> int:
        """
        Get the current step count.
        """
        pass

    @property
    @abstractmethod
    def screenshot(self) -> list[Any]:
        """
        Get the list of screenshots taken during execution.
        """
        pass

    @property
    @abstractmethod
    def context(self) -> list[dict[str, Any]]:
        """
        Get the current conversation context (messages).
        """
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """
        Check if the agent is currently running a task.
        """
        pass
