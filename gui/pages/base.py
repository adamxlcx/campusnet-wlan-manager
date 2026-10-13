# -*- coding: utf-8 -*-
"""分页基类：统一的页头 + 可滚动卡片容器 + 状态回调接口。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QScrollArea,
                             QVBoxLayout, QWidget)

from .. import widgets as W


class Page(QWidget):
    """所有分页的基类。

    * `title` / `subtitle`：页头文案
    * `triggers`：状态变化时关心的字段路径，主窗口据此决定是否调用 `on_status`
    * `on_status(status)`：接收核心层状态快照
    * `on_show()`：页面被切换到前台时调用（用于刷新列表等）
    """

    title = "页面"
    subtitle = ""
    triggers: tuple = ()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._built = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head.setObjectName("pageHeader")
        head_lay = QVBoxLayout(head)
        head_lay.setContentsMargins(20, 16, 20, 12)
        head_lay.setSpacing(2)
        self.title_label = QLabel(self.title)
        self.title_label.setObjectName("pageTitle")
        self.sub_label = QLabel(self.subtitle)
        self.sub_label.setObjectName("pageSubtitle")
        self.sub_label.setWordWrap(True)
        head_lay.addWidget(self.title_label)
        if self.subtitle:
            head_lay.addWidget(self.sub_label)
        outer.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        container = QWidget()
        self.body = QVBoxLayout(container)
        self.body.setContentsMargins(20, 4, 20, 20)
        self.body.setSpacing(12)
        self.scroll.setWidget(container)
        outer.addWidget(self.scroll, 1)

        self.build()
        self.body.addStretch(1)
        self._built = True

    # ------------------------------------------------------------------ #
    # 子类接口
    # ------------------------------------------------------------------ #
    def build(self) -> None:  # pragma: no cover - 由子类实现
        """构建页面内容（在 __init__ 末尾自动调用一次）。"""

    def on_status(self, status: dict) -> None:
        """核心层状态刷新。"""

    def on_show(self) -> None:
        """页面进入前台。"""

    def on_theme(self, theme: str) -> None:
        """主题切换（需要重绘自绘控件的页面覆写）。"""

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #
    def add_widget(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_card(self, title: str = "", subtitle: str = "") -> W.Card:
        card = W.Card(title, subtitle)
        self.body.addWidget(card)
        return card

    def row(self, *widgets, spacing: int = 8, stretch_last: bool = True) -> QWidget:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        for widget in widgets:
            if isinstance(widget, str):
                widget = QLabel(widget)
            lay.addWidget(widget)
        if stretch_last:
            lay.addStretch(1)
        return holder

    def info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, str(text))

    def warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, str(text))

    def error(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, str(text))

    def confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, str(text),
                                      QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)
        return answer == QMessageBox.Yes

    def result_dialog(self, title: str, result: dict) -> None:
        """统一展示 {ok, message} 形式的执行结果。"""
        result = dict(result or {})
        message = str(result.get("message") or ("执行成功" if result.get("ok") else "执行失败"))
        if result.get("ok"):
            self.info(title, message)
        else:
            self.warn(title, message)

    def async_call(self, fn, args=(), title: str = "", tag: str = "",
                   on_done=None, busy_text: str = "") -> None:
        """后台执行并在结束后提示结果。"""
        if busy_text:
            self.ctx.notify(busy_text)

        def _done(_tag, result):
            if callable(on_done):
                on_done(result)
            elif isinstance(result, dict) and ("ok" in result or "message" in result):
                self.result_dialog(title or "执行结果", result)

        def _fail(_tag, err):
            self.warn(title or "执行失败", err)

        self.ctx.run_async(fn, args, tag=tag or (title or "task"),
                           on_done=_done, on_error=_fail)


__all__ = ["Page"]
