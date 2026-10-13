# -*- coding: utf-8 -*-
"""后台任务：把耗时/阻塞的核心层调用（netsh、ping、selenium 登录）放到线程池执行。

Qt 规则：QRunnable 在子线程里跑，但 `TaskSignals` 对象创建于 GUI 线程，
因此 connect 到 GUI 槽函数的信号会被 Qt 自动排队到 GUI 线程执行，界面不会被阻塞。

回调约定（`run_async` 的 `on_done` / `on_error`）：

* 推荐单参数写法 `fn(payload)`；同时兼容两参数写法 `fn(tag, payload)`，
  由 `_dispatch` 按回调实际的形参数量自动适配（历史代码两种写法都存在）；
* `on_done` 收到任务返回值，`on_error` 收到 `"异常类型: 描述"` 文本；
* 回调内部的异常会被捕获并写日志：PyQt5 中未被捕获的槽函数异常会直接终止
  进程（Windows 下表现为静默崩溃、退出码 0xC0000409），这里统一兜底，
  保证界面不会因为一次回调报错而整体崩溃。
"""
from __future__ import annotations

import inspect

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from core import logging_setup


class TaskSignals(QObject):
    finished = pyqtSignal(str, object)   # (tag, result)
    failed = pyqtSignal(str, str)        # (tag, error message)


def _takes_two_args(callback) -> bool:
    """判断回调是 `fn(tag, payload)`（True）还是 `fn(payload)`（False）形态。"""
    try:
        parameters = list(inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):   # 内建函数 / 取不到签名 → 沿用两参数约定
        return True

    positional = 0
    for param in parameters:
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            return True
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY,
                          inspect.Parameter.POSITIONAL_OR_KEYWORD,
                          inspect.Parameter.KEYWORD_ONLY):
            positional += 1
    return positional >= 2


def _dispatch(callback, stage: str):
    """把 (tag, payload) 形态的信号适配成回调实际需要的签名，并兜底异常。"""
    if callback is None:
        return None
    two_args = _takes_two_args(callback)

    def _slot(tag, payload):
        try:
            if two_args:
                callback(tag, payload)
            else:
                callback(payload)
        except Exception as exc:  # noqa: BLE001 - 槽函数异常绝不能冒泡回 Qt
            logging_setup.get_logger().warning(
                "后台任务%s回调出错（tag=%s）：%s: %s", stage, tag,
                type(exc).__name__, exc)

    return _slot


class FunctionTask(QRunnable):
    """把一个可调用对象丢到线程池执行。"""

    def __init__(self, fn, args=(), kwargs=None, tag: str = ""):
        super().__init__()
        self.fn = fn
        self.args = tuple(args)
        self.kwargs = dict(kwargs or {})
        self.tag = tag or getattr(fn, "__name__", "task")
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D102
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001
            logging_setup.get_logger().warning("后台任务 %s 失败：%s", self.tag, exc)
            self.signals.failed.emit(self.tag, f"{type(exc).__name__}: {exc}")
            return
        self.signals.finished.emit(self.tag, result)


def run_async(pool: QThreadPool, fn, args=(), kwargs=None, tag: str = "",
              on_done=None, on_error=None) -> FunctionTask:
    """提交任务；返回 task 对象（可继续连信号）。"""
    task = FunctionTask(fn, args, kwargs, tag)
    done_slot = _dispatch(on_done, "完成")
    fail_slot = _dispatch(on_error, "失败")
    if done_slot is not None:
        task.signals.finished.connect(done_slot)
    if fail_slot is not None:
        task.signals.failed.connect(fail_slot)
    pool.start(task)
    return task


__all__ = ["FunctionTask", "TaskSignals", "run_async"]
