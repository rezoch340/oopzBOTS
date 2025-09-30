#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志配置模块
统一管理应用日志
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

# 日志目录
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 日志文件路径
LOG_FILE = os.path.join(LOG_DIR, "oopz_bot.log")

# 日志格式
LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str = "OopzBot", level=logging.INFO) -> logging.Logger:
    """设置并返回 logger
    
    Args:
        name: logger 名称
        level: 日志级别
    
    Returns:
        配置好的 logger 对象
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    # 文件处理器 - 使用 RotatingFileHandler 自动轮转日志
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,  # 保留 5 个备份
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    file_handler.setFormatter(file_formatter)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """获取 logger 实例
    
    Args:
        name: logger 名称，如果为 None 则返回根 logger
    
    Returns:
        logger 对象
    """
    if name:
        return logging.getLogger(f"OopzBot.{name}")
    return logging.getLogger("OopzBot")


# 创建默认 logger
default_logger = setup_logger()

