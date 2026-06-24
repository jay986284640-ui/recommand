"""日志配置"""

import logging
import sys


def setup_logging(level: str = "INFO", format_str: str = None) -> None:
    """初始化根日志"""
    fmt = format_str or "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
