"""Logging setup for the A-share analysis system.

Provides a consistent logging format across all modules.
Format: [%(asctime)s] %(levelname)s %(name)s: %(message)s
Per PRD NFR-003 logging standards.
"""

import logging
import sys


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Get a configured logger instance.

    Args:
        name: Logger name (typically __name__ or module path).
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).

    Returns:
        Configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
