# -*- coding: utf-8 -*-
"""日志配置：滚动文件 + 可选控制台输出。

GUI 阶段可通过 add_gui_handler() 把日志转发到界面；本阶段只提供文件/控制台。
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import paths

ROOT_LOGGER_NAME = "campusnet"
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_lock = threading.RLock()
_configured = False
_memory_handler = None


class MemoryHandler(logging.Handler):
    """环形缓冲，供 GUI 读取历史日志（本阶段即可用，GUI 阶段直接复用）。"""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self.capacity = capacity
        self.records: list = []

    def emit(self, record):  # noqa: D102
        try:
            self.records.append(self.format(record))
            if len(self.records) > self.capacity:
                del self.records[: len(self.records) - self.capacity]
        except Exception:  # noqa: BLE001
            pass


def get_logger(name: str = ROOT_LOGGER_NAME) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers and name != ROOT_LOGGER_NAME:
        # 确保子 logger 会向根 logger 冒泡（默认即如此，这里只是兜底）
        logger.setLevel(logging.NOTSET)
    return logger


def setup_logging(cfg: dict | None = None, console: bool = True,
                  level: str | None = None) -> logging.Logger:
    """初始化日志。重复调用只更新级别，不会重复添加 handler。"""
    global _configured, _memory_handler
    log_cfg = (cfg or {}).get("logging", {}) if isinstance(cfg, dict) else {}
    level_name = (level or log_cfg.get("level") or "INFO").upper()
    level_value = getattr(logging, level_name, logging.INFO)

    with _lock:
        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(level_value)
        root.propagate = False

        if not _configured:
            paths.ensure_dirs()
            try:
                fh = RotatingFileHandler(
                    paths.log_file(),
                    maxBytes=int(log_cfg.get("max_bytes", 2 * 1024 * 1024)),
                    backupCount=int(log_cfg.get("backup_count", 5)),
                    encoding="utf-8",
                )
                fh.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
                root.addHandler(fh)
            except Exception as e:  # noqa: BLE001
                print(f"[campusnet] 无法创建日志文件 handler: {e}", file=sys.stderr)

            if console and getattr(sys.stdout, "_campusnet_redirect", ""):
                # 窗口化冻结运行时 sysutil.ensure_console_streams() 已把 sys.stdout 指向日志
                # 文件本身，此时再加 StreamHandler(sys.stdout) 会让每行日志重复写两遍（也会
                # 让「插件加载」等日志刷屏），这里直接跳过控制台 handler。
                console = False

            if console:
                try:
                    sh = logging.StreamHandler(sys.stdout)
                    sh.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
                    root.addHandler(sh)
                except Exception:  # noqa: BLE001
                    pass

            _memory_handler = MemoryHandler(int(log_cfg.get("memory_records", 500)))
            _memory_handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
            _memory_handler.setLevel(logging.INFO)
            root.addHandler(_memory_handler)

            _configured = True
        else:
            for h in root.handlers:
                if isinstance(h, RotatingFileHandler):
                    h.setLevel(level_value)

        for h in root.handlers:
            h.setLevel(level_value if not isinstance(h, MemoryHandler) else logging.INFO)
    return logging.getLogger(ROOT_LOGGER_NAME)


def add_gui_handler(handler: logging.Handler) -> None:
    """供 GUI 阶段接入：把日志同时投递给自定义 handler。"""
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if handler not in logger.handlers:
        logger.addHandler(handler)


def recent_log_lines(limit: int = 200) -> list:
    if _memory_handler is None:
        return []
    return list(_memory_handler.records)[-limit:]
