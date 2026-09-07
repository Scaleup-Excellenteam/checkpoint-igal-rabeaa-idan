import logging
import os
import sys

# Directory where log files can be saved
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(LOG_DIR, "server.log")

# Enable Virtual Terminal Processing on Windows console for ANSI color support
if sys.platform == "win32":
    os.system("")

# Custom BLOCKED log level (named 'ERROR: BLOCKED' so log highlighters render it in RED)
BLOCKED_LEVEL = 35
logging.addLevelName(BLOCKED_LEVEL, "ERROR: BLOCKED")


def _blocked(self, message, *args, **kws):
    if self.isEnabledFor(BLOCKED_LEVEL):
        if sys.version_info >= (3, 8):
            kws.setdefault("stacklevel", 2)
        self._log(BLOCKED_LEVEL, message, args, **kws)


logging.Logger.blocked = _blocked


class ColoredConsoleFormatter(logging.Formatter):
    """
    Console formatter that highlights log level tags using ANSI colors.
    Specifically renders the [ERROR: BLOCKED] flag in bright red.
    """
    RED = "\033[1;31m"      # Bright / Bold Red
    YELLOW = "\033[93m"     # Yellow
    CYAN = "\033[96m"       # Cyan
    RESET = "\033[0m"       # Reset

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if record.levelno == BLOCKED_LEVEL or "BLOCKED" in record.levelname:
            formatted = formatted.replace(f"[{record.levelname}]", f"{self.RED}[{record.levelname}]{self.RESET}")
            # Also catch standalone [BLOCKED] if present
            formatted = formatted.replace("[BLOCKED]", f"{self.RED}[BLOCKED]{self.RESET}")
        elif record.levelname == "ERROR":
            formatted = formatted.replace("[ERROR]", f"{self.RED}[ERROR]{self.RESET}")
        elif record.levelname == "WARNING":
            formatted = formatted.replace("[WARNING]", f"{self.YELLOW}[WARNING]{self.RESET}")
        return formatted



def setup_logger(name: str = "ChatServer", level: int = logging.INFO) -> logging.Logger:
    """
    Configures and returns a centralized logger with both console and file handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.hasHandlers():
        return logger

    # Format template
    log_format = "[%(asctime)s] [%(levelname)s] [%(filename)s] [%(name)s]: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console Handler with color formatting (renders [BLOCKED] in red)
    console_formatter = ColoredConsoleFormatter(fmt=log_format, datefmt=date_format)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File Handler for server.log (plain text without ANSI escape codes)
    file_formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
    try:
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not configure file logging: {e}", file=sys.stderr)

    return logger


# Default logger instance ready to import across modules
logger = setup_logger()

