# -*- coding: utf-8 -*-
"""GUI 运行时上下文：持有配置、核心服务实例、后台线程池与状态缓存。

设计要点：
* 界面只和 `AppContext` 打交道，不直接碰核心层内部对象；
* 核心层 Service 的状态回调（`ServiceCallbacks`）在工作线程里触发，
  这里统一转成 Qt 信号（自动排队到 GUI 线程）后广播给托盘与各分页；
* 所有耗时调用（netsh / ping / selenium 登录 / 插件校验）都经 `run_async`
  丢进线程池，GUI 永不阻塞。
"""
from __future__ import annotations

import os
import threading

from PyQt5.QtCore import QObject, QThreadPool, pyqtSignal

from core import config as config_mod
from core import logging_setup
from core import paths
from core import service as service_mod

from . import config_ops, theme as theme_mod


class AppContext(QObject):
    """界面与核心层之间的唯一枢纽。"""

    status_changed = pyqtSignal(dict)      # 核心层状态快照
    log_line = pyqtSignal(str, str)        # (level, message)
    service_event = pyqtSignal(str, dict)  # (事件名, 负载)：connect / login / trip / ...
    config_changed = pyqtSignal(dict)      # 配置保存后广播
    toast = pyqtSignal(str)                # 需要提示给用户的短消息

    def __init__(self, config_path: str = "", start_service: bool = False,
                 dry_run: bool = False, parent=None):
        super().__init__(parent)
        self.config_path = config_path or paths.CONFIG_FILE
        self.config = config_mod.ensure_config(self.config_path)[0]
        self.cfg = self.config.data
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.status: dict = {}
        self.dry_run = bool(dry_run)
        self.recent_logs: list = []
        self.service = None
        self._service_started = False

        self.service = service_mod.build_service(
            self.config_path, dry_run=self.dry_run, callbacks=self._callbacks())
        if start_service:
            self.start_service()

    # ------------------------------------------------------------------ #
    # 主题
    # ------------------------------------------------------------------ #
    def theme(self) -> str:
        return theme_mod.normalize(((self.cfg.get("app") or {}).get("ui") or {}).get("theme"))

    def set_theme(self, theme: str, persist: bool = True) -> str:
        theme = theme_mod.normalize(theme)
        self.cfg.setdefault("app", {}).setdefault("ui", {})["theme"] = theme
        if persist:
            self.save_config()
        return theme

    # ------------------------------------------------------------------ #
    # 核心服务
    # ------------------------------------------------------------------ #
    def _callbacks(self):
        return service_mod.ServiceCallbacks(
            on_status=self._on_status,
            on_log=self._on_log,
            on_event=self._on_event,
        )

    def start_service(self, interval: float | None = None) -> None:
        if self.service is None or self._service_started:
            return
        self.service.start_background(interval=interval)
        self._service_started = True

    def stop_service(self) -> None:
        if self.service is None:
            return
        self._service_started = False
        try:
            self.service.stop()
        except Exception as exc:  # noqa: BLE001
            logging_setup.get_logger().warning("停止服务失败：%s", exc)

    def shutdown(self) -> None:
        """退出时调用：停线程 + 收尾（不阻塞界面）。"""
        if self.service is None:
            return
        self.stop_service()
        service = self.service
        Thread = threading.Thread

        def _close():
            try:
                service.close()
            except Exception:  # noqa: BLE001
                pass

        Thread(target=_close, name="campusnet-shutdown", daemon=True).start()

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    def _on_status(self, payload: dict) -> None:
        self.status = dict(payload or {})
        self.status_changed.emit(self.status)

    def _on_log(self, level: str, message: str) -> None:
        self.recent_logs.append((level, message))
        del self.recent_logs[:-500]
        self.log_line.emit(level, message)

    def _on_event(self, name: str, payload: dict) -> None:
        self.service_event.emit(name, dict(payload or {}))

    def refresh_status(self, on_done=None) -> None:
        """立刻抓一次状态快照（耗时操作在线程池里跑）。"""
        if self.service is None:
            return

        def _work():
            return self.service.status(include_profiles=False)

        def _done(_tag, payload):
            self._on_status(payload)
            if callable(on_done):
                on_done(payload)

        self.run_async(_work, tag="status", on_done=_done)

    def load_profiles(self, on_done=None, on_error=None) -> None:
        if self.service is None:
            return
        self.run_async(self.service.profiles, tag="profiles",
                       on_done=on_done, on_error=on_error)

    def reload_plugins(self, on_done=None) -> None:
        if self.service is None:
            return

        def _work():
            self.service.plugins.reload(force=True)
            return self.service.plugins.report()

        self.run_async(_work, tag="plugins", on_done=on_done)

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def save_config(self, notify_service: bool = True) -> dict:
        """规范化并写盘；成功后通知核心层热加载并广播。"""
        config_ops.save_config(self.config)
        self.cfg = self.config.data
        if notify_service and self.service is not None:
            self.service.cfg = self.config.data
            try:
                self.service.reload_config(force=True)
            except Exception as exc:  # noqa: BLE001
                logging_setup.get_logger().warning("核心层重载配置失败：%s", exc)
        self.config_changed.emit(self.cfg)
        return self.cfg

    # ------------------------------------------------------------------ #
    # 线程池
    # ------------------------------------------------------------------ #
    def run_async(self, fn, args=(), kwargs=None, tag: str = "",
                  on_done=None, on_error=None):
        from .workers import run_async  # 延迟导入，避免循环引用
        return run_async(self.pool, fn, args, kwargs, tag=tag,
                         on_done=on_done, on_error=on_error)

    def notify(self, message: str) -> None:
        self.toast.emit(str(message))

    def open_in_explorer(self, target: str) -> tuple:
        """用资源管理器打开目录 / 选中文件（只读操作，不改动任何文件）。"""
        from core import sysutil  # 延迟导入，保持 GUI 启动轻量
        target = str(target or "")
        if not target:
            return (-1, "", "路径为空")
        if os.path.isfile(target):
            return sysutil.run(["explorer", "/select,", target])
        return sysutil.run(["explorer", target])

    # ------------------------------------------------------------------ #
    def info(self) -> dict:
        return {
            "config_path": self.config_path,
            "project_dir": paths.PROJECT_DIR,
            "plugins_dir": config_ops.plugins_dir(self.cfg),
            "log_file": paths.log_file() if hasattr(paths, "log_file") else "",
            "dry_run": self.dry_run,
            "service_running": bool(self.service and self.service.running),
            "pid": os.getpid(),
        }


__all__ = ["AppContext"]
