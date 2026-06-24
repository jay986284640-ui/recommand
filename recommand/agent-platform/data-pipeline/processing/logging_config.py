"""日志配置模块"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(
    name: str = None,
    level: int = logging.INFO,
    log_file: str = None,
    console: bool = True
) -> logging.Logger:
    """
    配置日志记录器

    Args:
        name: 日志记录器名称（默认使用根日志记录器）
        level: 日志级别
        log_file: 日志文件路径（可选）
        console: 是否输出到控制台

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 清除已有的处理器，避免重复添加
    logger.handlers.clear()

    # 日志格式
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件处理器
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    获取日志记录器

    如果已有同名的日志记录器，直接返回；否则创建一个新的。

    Args:
        name: 日志记录器名称，通常使用 __name__

    Returns:
        日志记录器
    """
    return logging.getLogger(name)


# 默认日志级别
DEFAULT_LEVEL = logging.INFO

# 默认日志配置
DEFAULT_CONFIG = {
    "level": logging.INFO,
    "console": True,
    "log_file": None
}