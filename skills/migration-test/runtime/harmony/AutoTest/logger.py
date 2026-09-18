"""Logger package."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any


def configure_logger(console_level: str = "INFO", log_file: Optional[str] = None):
    """Configure logger."""
    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, console_level))
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Create file handler if log_file is provided
    if log_file:
        # Create directory if it doesn't exist
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    # Suppress verbose HTTP logs (httpx/openai) to avoid printing base64 image data
    # These loggers print full request bodies including large base64-encoded images
    for logger_name in ["httpx", "httpcore", "openai", "openai._base_client"]:
        http_logger = logging.getLogger(logger_name)
        http_logger.setLevel(logging.INFO)


class BaseLogger(ABC):
    """Abstract base class for logger implementations."""

    @abstractmethod
    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log a debug message."""
        pass

    @abstractmethod
    def info(self, msg: str, *args, **kwargs) -> None:
        """Log an info message."""
        pass

    @abstractmethod
    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log a warning message."""
        pass

    @abstractmethod
    def error(self, msg: str, *args, **kwargs) -> None:
        """Log an error message."""
        pass

    @abstractmethod
    def exception(self, msg: str, *args, **kwargs) -> None:
        """Log an exception message."""
        pass


class Logger:
    """Logger class with singleton pattern and customizable logger backend."""

    _instance: Optional["Logger"] = None
    _logger: Optional[Any] = None

    def __new__(cls) -> "Logger":
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize with default logging handler if not set."""
        if self._logger is None:
            self._logger = logging.getLogger(__name__)

    def set_logger(self, base_logger: BaseLogger) -> None:
        """Set a custom logger implementation.

        Args:
            base_logger: An object implementing the BaseLogger interface.
        """
        self._logger = base_logger

    def __getattr__(self, name: str):
        """Allow logger.info(), logger.debug() etc. to work directly."""
        return getattr(self._logger, name)


# Create default logger instance
logger = Logger()
logger.set_logger(logging.getLogger(__name__))
configure_logger()