# -*- coding: utf-8 -*-
"""设置页：主题、开机自启动、Windows 计划任务（两开关独立）、日志、关于。"""
from __future__ import annotations

import os

from PyQt5.QtWidgets import QComboBox, QPlainTextEdit

from core import paths

from .. import startup as startup_mod
from .. import widgets as W
from .base import Page


class SettingsPage(Page):
    title = "设置"
    subtitle = "主题、开机自启动、Windows 计划任务（两个开关彼此独立）、日志与关于。"
    triggers = ()

    def build(self) -> None:
        # ---------------- 外观 ----------------
        card = self.add_card("外观")
        self.combo_theme = QComboBox()
        self.combo_theme.addItem("浅色（白）", "light")
        self.combo_theme.addItem("深色（黑）", "dark")
        index = self.combo_theme.findData(self.ctx.theme())
        self.combo_theme.setCurrentIndex(index if index >= 0 else 0)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        card.add(W.form_grid([("配色主题", self.combo_theme)]))
        card.add(W.muted("主题会写入配置文件，重启程序后保持。"))

        # ---------------- 启动项 ----------------
        card2 = self.add_card("开机自启动（普通用户可用）",
                              "写入 HKCU\\...\\CurrentVersion\\Run，登录后最小化到托盘启动。")
        self.check_autostart = W.CheckRow("开机自动启动 CampusNet（最小化到托盘）", False,
                                          self.on_autostart_toggled)
        card2.add(self.check_autostart)
        self.autostart_state = W.muted("状态读取中…")
        card2.add(self.autostart_state)

        # ---------------- 计划任务 ----------------
        card3 = self.add_card("Windows 计划任务（独立开关）",
                              "登录时触发；以最高权限运行时需要管理员身份，失败会自动降级为当前用户权限。")
        self.check_task = W.CheckRow("注册 Windows 计划任务（登录时自动启动）", False,
                                     self.on_task_toggled)
        card3.add(self.check_task)
        self.task_state = W.muted("状态读取中…")
        card3.add(self.task_state)
        self.command_preview = QPlainTextEdit()
        self.command_preview.setObjectName("CodeView")
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(70)
        card3.add(self.command_preview)
        card3.add(self.row(W.Button("刷新状态", "ghost", self.refresh_startup),
                           W.Button("以管理员身份重启程序（可选）", "ghost",
                                    self.hint_admin)))

        # ---------------- 日志 ----------------
        card4 = self.add_card("日志")
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("CodeView")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(160)
        self.log_view.setPlainText("\n".join(f"[{lv}] {msg}" for lv, msg in
                                             self.ctx.recent_logs[-200:]) or "暂无日志。")
        card4.add(self.log_view)
        card4.add(self.row(W.Button("刷新日志", "ghost", self.reload_log),
                           W.Button("打开日志所在目录", "ghost", self.open_log_dir)))

        # ---------------- 关于 ----------------
        card5 = self.add_card("关于")
        info = self.ctx.info()
        app = (self.ctx.cfg.get("app") or {})
        card5.add(W.grid_of([
            ("程序", app.get("name") or "CampusNet"),
            ("版本", app.get("version") or "—"),
            ("配置文件", info.get("config_path")),
            ("插件目录", info.get("plugins_dir")),
            ("日志文件", info.get("log_file")),
            ("进程 PID", info.get("pid")),
            ("界面框架", "PyQt5（系统托盘 + 分页导航）"),
        ], columns=1))

        self.ctx.log_line.connect(self.append_log)
        self.refresh_startup()

    # ------------------------------------------------------------------ #
    # 外观
    # ------------------------------------------------------------------ #
    def on_theme_changed(self, _index: int) -> None:
        theme = self.combo_theme.currentData() or "light"
        if theme == self.ctx.theme():
            return
        self.ctx.set_theme(theme)   # 写盘 + 广播 config_changed，主窗口据此换肤
        self.ctx.notify(f"已切换到{'深色' if theme == 'dark' else '浅色'}主题")

    # ------------------------------------------------------------------ #
    # 启动项
    # ------------------------------------------------------------------ #
    def refresh_startup(self) -> None:
        def _work():
            return startup_mod.status(self.ctx.cfg)

        def _done(state):
            state = state or {}
            auto = state.get("autostart") or {}
            task = state.get("task") or {}
            self.check_autostart.blockSignals(True)
            self.check_autostart.setChecked(bool(auto.get("enabled")))
            self.check_autostart.blockSignals(False)
            self.autostart_state.setText(
                f"当前状态：{'已启用' if auto.get('enabled') else '未启用'}　"
                f"注册表项：{auto.get('name')}　命令：{auto.get('command') or '—'}"
                + (f"　（{auto.get('message')}）" if auto.get("message") else ""))
            self.check_task.blockSignals(True)
            self.check_task.setChecked(bool(task.get("exists")))
            self.check_task.blockSignals(False)
            self.task_state.setText(
                f"当前状态：{'已注册' if task.get('exists') else '未注册'}　"
                f"任务名：{task.get('name')}　"
                f"管理员权限：{'是' if state.get('admin') else '否（注册最高权限任务会降级）'}")
            self.command_preview.setPlainText(state.get("task_command") or "")

        self.ctx.run_async(_work, tag="startup-status", on_done=_done,
                           on_error=lambda _t, e: self.task_state.setText(f"读取失败：{e}"))

    def on_autostart_toggled(self, checked: bool) -> None:
        def _work():
            return startup_mod.set_autostart(self.ctx.cfg, bool(checked))

        def _done(result):
            result = result or {}
            self.result_dialog("开机自启动", result)
            if not result.get("ok"):
                self.check_autostart.blockSignals(True)
                self.check_autostart.setChecked(not checked)
                self.check_autostart.blockSignals(False)
            self.refresh_startup()

        self.ctx.run_async(_work, tag="autostart", on_done=_done,
                           on_error=lambda _t, e: self.warn("开机自启动", e))

    def on_task_toggled(self, checked: bool) -> None:
        def _work():
            if checked:
                return startup_mod.create_task(self.ctx.cfg)
            return startup_mod.delete_task(self.ctx.cfg)

        def _done(result):
            result = result or {}
            message = str(result.get("message") or "")
            if result.get("ok"):
                self.info("计划任务", message)
            else:
                self.warn("计划任务", message + "\n\n降级方案：\n"
                                         "1) 改用「开机自启动」开关（无需管理员）；\n"
                                         "2) 以管理员身份重新运行本程序；\n"
                                         "3) 手动在「任务计划程序」中创建（命令见上方预览）。")
            self.refresh_startup()

        self.ctx.run_async(_work, tag="task", on_done=_done,
                           on_error=lambda _t, e: self.warn("计划任务", e))

    def hint_admin(self) -> None:
        self.info("权限说明",
                  "注册“最高权限运行”的计划任务需要管理员身份。\n"
                  "普通权限下将注册为当前用户登录触发的任务，功能等效。\n"
                  "如需要管理员权限，请右键以管理员身份重新运行本程序。")

    # ------------------------------------------------------------------ #
    # 日志
    # ------------------------------------------------------------------ #
    def append_log(self, level: str, message: str) -> None:
        self.log_view.appendPlainText(f"[{level}] {message}")

    def reload_log(self) -> None:
        lines = list(self.ctx.recent_logs[-200:])
        text = "\n".join(f"[{lv}] {msg}" for lv, msg in lines)
        path = paths.log_file() if hasattr(paths, "log_file") else ""
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    tail = handle.readlines()[-200:]
                text = "".join(tail) + ("\n\n--- 以上为文件尾部 ---\n" + text if text else "")
            except Exception as exc:  # noqa: BLE001
                text = f"读取日志文件失败：{exc}\n\n" + text
        self.log_view.setPlainText(text or "暂无日志。")

    def open_log_dir(self) -> None:
        path = paths.log_file() if hasattr(paths, "log_file") else ""
        target = os.path.dirname(path) if path else paths.PROJECT_DIR
        self.ctx.open_in_explorer(target)
        self.ctx.notify(f"已打开：{target}")

    # ------------------------------------------------------------------ #
    def on_show(self) -> None:
        self.refresh_startup()


__all__ = ["SettingsPage"]
