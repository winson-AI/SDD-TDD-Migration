"""Config package."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ModelConfig:
    """Model configuration."""
    model_name: str = ""
    base_url: str = ""
    api_key: str = ""
    api_version: str = ""
    max_tokens: int = 2048
    temperature: float = 0.1
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    extra_body: Optional[Dict[str, Any]] = None
    provider: str = "glm"
    max_steps: int = 5


@dataclass
class AgentConfig:
    """Agent configuration."""
    verbose: bool = False
    max_steps: int = 5
    system_prompt: Optional[str] = None
    lang: str = "zh"
    mode: str = "mcp"
    # not support autoGLM
    max_history_image: int = 2
    special_test_enabled: bool = False


@dataclass
class ContextCompressionConfig:
    """Context compression configuration."""
    enabled: bool = True
    max_tokens: int = 50000
    max_recent_messages: int = 5


@dataclass
class ReflectionConfig:
    """Reflection configuration."""
    enabled: bool = False
    initial_step: int = 10
    interval: int = 10
    recent_messages: int = 10


@dataclass
class SpecialTestConfig:
    """Special test configuration."""
    enabled: bool = False


@dataclass
class AppConfig:
    """Application configuration."""
    execute_model_name: str = ""
    execute_base_url: str = ""
    execute_api_key: str = ""
    execute_provider: str = ""
    execute_api_version: str = ""
    execute_mode: str = "mcp"
    execute_system_prompt: str = ""
    execute_max_steps: int = 5
    execute_max_history_image: int = 2
    decision_model_name: str = ""
    decision_base_url: str = ""
    decision_api_key: str = ""
    decision_api_version: str = ""
    decision_provider: str = "openai"
    decision_temperature: float = 0.0
    decision_top_p: float = 0.1
    decision_max_token: int = 8192
    decision_frequency_penalty: float = 1.0
    decision_max_history_image: int = 2
    decision_models: list[Dict[str, Any]] = field(default_factory=list)
    xmind_convert_models: list[Dict[str, Any]] = field(default_factory=list)
    verify_model_name: str = ""
    verify_base_url: str = ""
    verify_api_key: str = ""
    verify_api_version: str = ""
    verify_provider: str = "openai"
    verify_temperature: float = 0.0
    verify_top_p: float = 0.1
    verify_frequency_penalty: float = 1.0
    verify_video_enable: bool = False
    keep_raw_video: bool = False
    device_serial: str = ""
    hdc_path: str = "hdc"
    screenshot_quality: int = 70
    screenshot_max_width: int = 1024
    max_steps: int = 100
    verbose: bool = False
    lang: str = "zh"
    task_timeout: int = 1800
    context_compression: ContextCompressionConfig = field(default_factory=ContextCompressionConfig)
    reflection: ReflectionConfig = field(default_factory=ReflectionConfig)
    special_test: SpecialTestConfig = field(default_factory=SpecialTestConfig)


@dataclass
class StepResult:
    """Result of a single agent step."""
    success: bool
    finished: bool
    action: Optional[Dict[str, Any]]
    thinking: str
    message: Optional[str] = None


@dataclass
class ScreenInfo:
    """Screen information."""
    width: int = 0
    height: int = 0
    app: str = ""


class ConfigManager:
    """Configuration manager."""

    def __init__(self):
        self._config = AppConfig()

    def load_file_config(self, config_file: Optional[str] = None):
        """Load configuration from file."""
        import yaml
        import os

        if config_file is None:
            # First try relative to this file
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(base_dir, "config", "config.yaml")

        if not os.path.exists(config_file):
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            # Load model config
            if "execute_model" in data:
                model_data = data["execute_model"]
                self._config.execute_model_name = model_data.get("name", "")
                self._config.execute_base_url = model_data.get("base_url", "")
                self._config.execute_api_key = model_data.get("api_key", "")
                self._config.execute_provider = model_data.get("provider", "")
                self._config.execute_api_version = model_data.get("api_version", "")
                self._config.execute_mode = model_data.get("mode", "mcp")
                self._config.execute_system_prompt = model_data.get("system_prompt", "")
                self._config.execute_max_steps = model_data.get("max_steps", 5)
                self._config.execute_max_history_image = model_data.get("max_history_image", 2)

            # Load decision model config
            decision_models_list = []

            if "decision_model" in data:
                decision_model_data = data["decision_model"]
                if isinstance(decision_model_data, list):
                    decision_models_list = decision_model_data
                else:
                    decision_models_list = [decision_model_data]

            self._config.decision_models = decision_models_list

            if self._config.decision_models:
                first_model = self._config.decision_models[0]
                if isinstance(first_model, dict):
                    self._config.decision_model_name = first_model.get("name", "")
                    self._config.decision_base_url = first_model.get("base_url", "")
                    self._config.decision_api_key = first_model.get("api_key", "")
                    self._config.decision_api_version = first_model.get("api_version", "")
                    self._config.decision_provider = first_model.get("provider", "openai")
                    self._config.decision_temperature = first_model.get("temperature", None)
                    self._config.decision_top_p = first_model.get("top_p", None)
                    self._config.decision_frequency_penalty = first_model.get("frequency_penalty", None)
                    self._config.decision_max_token = first_model.get("max_token", None)
                    self._config.decision_max_history_image = first_model.get("max_history_image", 2)

            # Load xmind convert model config (independent, falls back to decision_model)
            self._config.xmind_convert_models = []
            if "xmind_convert_model" in data:
                xmind_m = data["xmind_convert_model"]
                if isinstance(xmind_m, list):
                    self._config.xmind_convert_models = xmind_m
                else:
                    self._config.xmind_convert_models = [xmind_m]

            # Load verify model config
            if "verify_model" in data:
                verify_model_data = data["verify_model"]
                self._config.verify_model_name = verify_model_data.get("name", "")
                self._config.verify_base_url = verify_model_data.get("base_url", "")
                self._config.verify_api_key = verify_model_data.get("api_key", "")
                self._config.verify_api_version = verify_model_data.get("api_version", "")
                self._config.verify_temperature = verify_model_data.get("temperature", None)
                self._config.verify_top_p = verify_model_data.get("top_p", None)
                self._config.verify_frequency_penalty = verify_model_data.get("frequency_penalty", None)
                self._config.verify_video_enable = verify_model_data.get("video_enable", False)
                self._config.keep_raw_video = verify_model_data.get("keep_raw_video", False)

            # Load device config
            if "device" in data:
                device_data = data["device"]
                self._config.device_sn = device_data.get("device_sn", "")
                self._config.ip = device_data.get("ip", "127.0.0.1")
                self._config.port = device_data.get("port", 8710)

            # Load agent config
            if "agent" in data:
                agent_data = data["agent"]
                self._config.max_steps = agent_data.get("max_steps", 100)
                self._config.lang = agent_data.get("lang", "zh")
                self._config.verbose = agent_data.get("verbose", False)
                self._config.task_timeout = agent_data.get("task_timeout", 1800)

            # Load context compression config
            if "context_compression" in data:
                compression_data = data["context_compression"]
                self._config.context_compression = ContextCompressionConfig(
                    enabled=compression_data.get("enabled", True),
                    max_tokens=compression_data.get("max_tokens", 50000),
                    max_recent_messages=compression_data.get("max_recent_messages", 5),
                )

            # Load reflection config
            if "reflection" in data:
                reflection_data = data["reflection"]
                self._config.reflection = ReflectionConfig(
                    enabled=reflection_data.get("enabled", True),
                    initial_step=reflection_data.get("initial_step", 10),
                    interval=reflection_data.get("interval", 10),
                    recent_messages=reflection_data.get("recent_messages", 10),
                )

            # Load special test config
            if "special_test" in data:
                special_test_data = data["special_test"]
                self._config.special_test = SpecialTestConfig(
                    enabled=special_test_data.get("enabled", False),
                )

        except Exception as e:
            print(f"Error loading config file: {e}")

    def get_effective_config(self) -> AppConfig:
        """Get effective configuration."""
        return self._config


config_manager = ConfigManager()
