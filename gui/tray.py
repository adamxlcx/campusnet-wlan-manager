# -*- coding: utf-8 -*-
"""任务栏托盘：图标颜色表示网络状态，左键双击打开主界面，右键菜单直达各分页。"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from . import icons as icons_mod
from . import theme as theme_mod
from .pages import PAGES


class Tray(QSystemTrayIcon):
    """托盘图标（绿=连通 / 红=不通 / 灰=检测关闭或未知）。"""

    page_requested = pyqtSignal(str)   # 打开某个分页
    show_requested = pyqtSignal()      # 打开主界面
    quit_requested = pyqtSignal()      # 退出程序

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._state = "gray"

        menu = QMenu()
        self.open_action = menu.addAction("打开主界面")
        self.open_action.triggered.connect(self.show_requested.emit)
        menu.addSeparator()
        self.page_actions = {}
        for key, title, glyph, _cls in PAGES:
            action = menu.addAction(f"{glyph}  {title}")
            action.triggered.connect(lambda _checked=False, k=key: self.page_requested.emit(k))
            self.page_actions[key] = action
        menu.addSeparator()
        self.status_action = menu.addAction("网络状态：未知")
        self.status_action.setEnabled(False)
        self.tray_hint_action = menu.addAction("托盘配色：绿=连通　红=不通　灰=检测关闭")
        self.tray_hint_action.setEnabled(False)
        menu.addSeparator()
        self.quit_action = menu.addAction("退出")
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.menu = menu
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self.show_requested.emit)

        self.apply_state("gray", "light", "")
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.setToolTip("CampusNet（当前环境没有系统托盘，界面仍可正常使用）")

    # ------------------------------------------------------------------ #
    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.show_requested.emit()

    def apply_state(self, state: str, theme: str = "light", detail: str = "") -> None:
        self._state = state or "gray"
        self.setIcon(icons_mod.tray_icon(self._state, theme))
        text = theme_mod.tray_state_text(self._state)
        tooltip = f"CampusNet　网络状态：{text}"
        if detail:
            tooltip += f"　({detail})"
        tooltip += "\n左键双击打开主界面，右键菜单可进入各分页"
        self.setToolTip(tooltip)
        self.status_action.setText(f"网络状态：{text}")
        if self._state == "gray" and detail:
            self.tray_hint_action.setText(f"说明：{detail}")
        else:
            self.tray_hint_action.setText("托盘配色：绿=连通　红=不通　灰=检测关闭")

    def notify(self, title: str, message: str, msecs: int = 5000) -> None:
        """托盘气泡提示（无托盘环境下静默忽略）。"""
        if not self.isVisible():
            return
        self.showMessage(title, message, self.icon(), int(msecs))


__all__ = ["Tray"]
