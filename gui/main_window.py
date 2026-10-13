# -*- coding: utf-8 -*-
"""主窗口：左侧导航 + 右侧分页 + 托盘联动 + 主题切换。"""
from __future__ import annotations

import functools

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QMainWindow, QStackedWidget, QStatusBar, QWidget)

from core import logging_setup

from . import icons as icons_mod
from . import theme as theme_mod
from .pages import PAGES
from .tray import Tray

STATUS_TICK_MS = 4000


def _safe_slot(func):
    """Qt 槽函数护栏：槽内未捕获异常在 PyQt5 中会直接终止进程，这里统一兜底记录。"""
    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logging_setup.get_logger().warning(
                "界面槽函数 %s 出错：%s: %s", func.__name__, type(exc).__name__, exc)
            return None
    return _wrapper


class MainWindow(QMainWindow):
    def __init__(self, ctx, start_minimized: bool = False, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.quitting = False
        self.pages = {}
        self._hint_shown = False

        app = (ctx.cfg.get("app") or {})
        self.setWindowTitle(f"{app.get('name') or 'CampusNet'} "
                            f"{app.get('version') or ''}　校园网 WLAN 自动管理")
        self.setWindowIcon(icons_mod.app_icon(theme_mod.accent(ctx.theme())))
        self.resize(1180, 760)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ---------------- 左侧导航 ----------------
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setFixedWidth(186)
        self.nav.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.nav)

        # ---------------- 右侧分页 ----------------
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        for key, title, glyph, page_cls in PAGES:
            page = page_cls(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
            item = QListWidgetItem(f"{glyph}   {title}")
            item.setData(Qt.UserRole, key)
            self.nav.addItem(item)

        self.nav.currentRowChanged.connect(self.on_nav_changed)
        self.nav.setCurrentRow(0)

        # ---------------- 状态栏 ----------------
        self.status_dot = QLabel("●")
        self.status_text = QLabel("状态初始化中…")
        bar = QStatusBar()
        bar.addWidget(self.status_dot)
        bar.addWidget(self.status_text, 1)
        self.theme_label = QLabel("")
        bar.addPermanentWidget(self.theme_label)
        self.setStatusBar(bar)

        # ---------------- 托盘 ----------------
        self.tray = Tray(ctx, self)
        self.tray.show_requested.connect(self.show_main)
        self.tray.page_requested.connect(self.open_page)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.show()

        # ---------------- 信号 ----------------
        ctx.status_changed.connect(self.on_status)
        ctx.toast.connect(self.on_toast)
        ctx.config_changed.connect(lambda _cfg: self.apply_theme(ctx.theme()))
        ctx.service_event.connect(self.on_service_event)

        self.apply_theme(ctx.theme())
        self.on_status(ctx.status)

        self.timer = QTimer(self)
        self.timer.setInterval(STATUS_TICK_MS)
        self.timer.timeout.connect(self.ctx.refresh_status)
        self.timer.start()

        if start_minimized:
            self.hide()

    # ------------------------------------------------------------------ #
    # 导航 / 分页
    # ------------------------------------------------------------------ #
    @_safe_slot
    def on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        item = self.nav.item(row)
        key = item.data(Qt.UserRole) if item else ""
        page = self.pages.get(key)
        if page is not None and hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception:  # noqa: BLE001 - 单页刷新失败不影响主界面
                pass

    def open_page(self, key: str) -> None:
        keys = [item[0] for item in PAGES]
        if key not in keys:
            return
        self.show_main()
        self.nav.setCurrentRow(keys.index(key))

    def show_main(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ #
    # 主题
    # ------------------------------------------------------------------ #
    @_safe_slot
    def apply_theme(self, theme: str) -> None:
        theme = theme_mod.normalize(theme)
        self.setStyleSheet(theme_mod.stylesheet(theme))
        self.setWindowIcon(icons_mod.app_icon(theme_mod.accent(theme)))
        self.theme_label.setText(f"主题：{theme_mod.THEME_LABELS.get(theme, theme)}")
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            key = item.data(Qt.UserRole)
            if key in self.pages and hasattr(self.pages[key], "on_theme"):
                try:
                    self.pages[key].on_theme(theme)
                except Exception:  # noqa: BLE001
                    pass
        self.on_status(self.ctx.status)

    # ------------------------------------------------------------------ #
    # 状态 / 提示
    # ------------------------------------------------------------------ #
    @_safe_slot
    def on_status(self, status: dict) -> None:
        status = dict(status or {})
        state = theme_mod.tray_state(status)
        detail = ((status.get("health") or {}).get("message") or "")
        for key in self.pages:
            page = self.pages[key]
            if hasattr(page, "on_status"):
                try:
                    page.on_status(status)
                except Exception:  # noqa: BLE001 - 单页刷新失败不影响其它页
                    pass
        theme = self.ctx.theme()
        color = icons_mod.state_color(state, theme)
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 15px;")
        self.tray.apply_state(state, theme, detail)

        connection = status.get("connection") or {}
        health = status.get("health") or {}
        ci = (status.get("connection") or {})
        parts = [
            f"当前 WiFi：{connection.get('ssid') or '未连接'}",
            f"网卡：{connection.get('interface') or '—'}",
            f"连通：{theme_mod.tray_state_text(state)}",
        ]
        if health.get("latency_ms") is not None:
            parts.append(f"延迟 {health.get('latency_ms')} ms")
        if ci.get("session", {}).get("connected_at"):
            parts.append(f"本次连接：{ci['session']['connected_at']}")
        traffic = status.get("traffic") or {}
        if traffic.get("down_speed"):
            parts.append(f"下载 {traffic.get('down_speed')}")
        self.status_text.setText("　|　".join(parts))

    @_safe_slot
    def on_toast(self, message: str) -> None:
        self.statusBar().showMessage(str(message), 6000)

    @_safe_slot
    def on_service_event(self, name: str, payload: dict) -> None:
        """核心层事件（连接 / 登录 / 触发下载保护等）——弹窗仍走核心层原逻辑。"""
        text = {
            "connected": "已连接网络",
            "disconnected": "网络已断开",
            "login": "登录流程完成",
            "guard": "下载保护已触发",
            "restart": "已重启网卡",
        }.get(str(name), str(name))
        detail = (payload or {}).get("message") or (payload or {}).get("ssid") or ""
        self.on_toast(f"{text}{('：' + str(detail)) if detail else ''}")

    # ------------------------------------------------------------------ #
    # 关闭 / 退出
    # ------------------------------------------------------------------ #
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._hint_shown:
            self._hint_shown = True
            self.tray.notify("CampusNet 仍在后台运行",
                             "程序已最小化到任务栏托盘：双击托盘图标可打开主界面，"
                             "右键菜单可退出。")

    def quit_app(self) -> None:
        self.quitting = True
        self.timer.stop()
        try:
            self.ctx.shutdown()
        finally:
            self.tray.hide()
            from PyQt5.QtWidgets import QApplication
            QApplication.instance().quit()


__all__ = ["MainWindow"]
