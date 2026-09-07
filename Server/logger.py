import logging
import os
import sys

# Directory where log files can be saved
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(LOG_DIR, "server.log")


def setup_logger(name: str = "ChatServer", level: int = logging.INFO) -> logging.Logger:
    """
    Configures and returns a centralized logger with both console and file handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.hasHandlers():
        return logger

    # Log message format
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler (server.log)
    try:
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not configure file logging: {e}", file=sys.stderr)

    return logger


# Default logger instance ready to import across modules
logger = setup_logger()
