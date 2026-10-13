# -*- coding: utf-8 -*-
"""网络检测页：连通性检测开关（间隔 + 检测地址）与重启网卡开关（触发条件）独立生效。"""
from __future__ import annotations

from PyQt5.QtWidgets import QLabel

from .. import theme as theme_mod
from .. import widgets as W
from .base import Page


class HealthPage(Page):
    title = "网络检测"
    subtitle = ("连通性检测与重启网卡是两个相互独立的开关："
                "前者决定托盘图标颜色，后者决定断网时是否自动重启网卡。")
    triggers = ("health",)

    def build(self) -> None:
        health = self.ctx.cfg.setdefault("health", {})
        restart = health.setdefault("restart", {})

        # ---------------- 连通性检测 ----------------
        card = self.add_card("连通性检测（决定托盘图标颜色）")
        card.add_head_widget(W.Button("保存", "primary", self.save_health))
        self.check_enabled = W.CheckRow("启用连通性检测", bool(health.get("enabled", True)),
                                        self._sync_enabled)
        card.add(self.check_enabled)

        self.spin_interval = W.int_spin(10, 3600, int(health.get("interval_seconds") or 60), " 秒")
        self.edit_target = W.text_edit(str(health.get("ping_target") or "www.baidu.com"))
        self.spin_timeout = W.int_spin(500, 20000, int(health.get("ping_timeout_ms") or 3000),
                                       " 毫秒", step=500)
        self.spin_threshold = W.int_spin(1, 20, int(health.get("fail_threshold") or 3), " 次")
        card.add(W.form_grid([
            ("检测间隔", self.spin_interval),
            ("检测地址", self.edit_target),
            ("超时", self.spin_timeout),
            ("连续失败判定次数", self.spin_threshold),
        ]))

        self.state_label = QLabel("—")
        self.state_label.setObjectName("Value")
        dot_row = self.row(W.StatusDot("gray", 12), self.state_label)
        card.add(dot_row)
        self.dot = dot_row.findChild(W.StatusDot)
        self.hint = W.muted("")
        card.add(self.hint)

        # ---------------- 重启网卡 ----------------
        card2 = self.add_card("重启网卡（独立开关）",
                              "需要管理员权限；禁用/启用无线网卡期间网络会短暂中断。")
        card2.add_head_widget(W.Button("保存", "primary", self.save_restart))
        self.check_restart = W.CheckRow("断网时自动重启网卡", bool(restart.get("enabled")),
                                        self._sync_enabled)
        card2.add(self.check_restart)
        self.spin_cooldown = W.int_spin(30, 7200, int(restart.get("cooldown_seconds") or 300),
                                        " 秒", step=30)
        self.check_recycle = W.CheckRow("优先禁用/启用网卡（否则仅重连）",
                                        bool(restart.get("prefer_adapter_recycle", True)))
        self.check_reconnect = W.CheckRow("重启后自动重连主网络",
                                          bool(restart.get("reconnect_after_restart", True)))
        card2.add(W.form_grid([("触发冷却时间", self.spin_cooldown)]))
        card2.add(self.check_recycle)
        card2.add(self.check_reconnect)
        self.restart_state = W.muted("")
        card2.add(self.restart_state)

        # ---------------- 托盘配色说明 ----------------
        card3 = self.add_card("托盘图标配色")
        card3.add(QLabel("绿：网络连通　|　红：网络不通　|　灰：连通性检测关闭或状态未知"))
        card3.add(W.muted("托盘左键双击打开主界面，右键菜单可直接进入各分页或退出。"))
        card3.add(self.row(W.Button("立即检测一次", "ghost", self.check_now),
                           W.Button("刷新状态", "ghost", self.ctx.refresh_status)))

        self.on_status(self.ctx.status)
        self._sync_enabled()

    # ------------------------------------------------------------------ #
    def _sync_enabled(self) -> None:
        enabled = self.check_enabled.isChecked()
        for widget in (self.spin_interval, self.edit_target, self.spin_timeout,
                       self.spin_threshold):
            widget.setEnabled(enabled)
        restart_enabled = self.check_restart.isChecked()
        for widget in (self.spin_cooldown, self.check_recycle, self.check_reconnect):
            widget.setEnabled(restart_enabled)
        if hasattr(self, "hint"):
            self.hint.setText(
                "连通性检测已开启：托盘图标实时显示绿 / 红。"
                if enabled else
                "连通性检测已关闭：托盘图标固定为中性灰，不做 ping 检测。")

    def save_health(self) -> None:
        health = self.ctx.cfg.setdefault("health", {})
        health["enabled"] = self.check_enabled.isChecked()
        health["interval_seconds"] = int(self.spin_interval.value())
        health["ping_target"] = self.edit_target.text().strip() or "www.baidu.com"
        health["ping_timeout_ms"] = int(self.spin_timeout.value())
        health["fail_threshold"] = int(self.spin_threshold.value())
        self.ctx.save_config()
        self._sync_enabled()
        self.ctx.refresh_status()
        self.ctx.notify("连通性检测设置已保存")

    def save_restart(self) -> None:
        restart = self.ctx.cfg.setdefault("health", {}).setdefault("restart", {})
        restart["enabled"] = self.check_restart.isChecked()
        restart["cooldown_seconds"] = int(self.spin_cooldown.value())
        restart["prefer_adapter_recycle"] = self.check_recycle.isChecked()
        restart["reconnect_after_restart"] = self.check_reconnect.isChecked()
        self.ctx.save_config()
        self._sync_enabled()
        self.ctx.notify("重启网卡设置已保存")

    def check_now(self) -> None:
        from core import health as health_mod
        self.async_call(lambda: health_mod.check(self.ctx.cfg), (), "连通性检测",
                        tag="health-now", busy_text="正在检测网络连通性…",
                        on_done=self._show_result)

    def _show_result(self, result) -> None:
        result = result or {}
        self.result_dialog("连通性检测", {
            "ok": bool(result.get("ok")),
            "message": (f"连通：{'是' if result.get('ok') else '否'}\n"
                        f"方式：{result.get('method') or '—'}\n"
                        f"延迟：{result.get('latency_ms') if result.get('latency_ms') is not None else '—'} ms\n"
                        f"说明：{result.get('message') or '—'}"),
        })
        self.ctx.refresh_status()

    # ------------------------------------------------------------------ #
    def on_status(self, status: dict) -> None:
        health = (status or {}).get("health") or {}
        if not health and not status:
            return
        state = theme_mod.tray_state(status)
        if self.dot is not None:
            self.dot.set_state(state, self.ctx.theme())
        self.state_label.setText(
            f"当前判定：{theme_mod.tray_state_text(state)}　"
            f"在线：{health.get('online')}　延迟：{health.get('latency_ms') or '—'} ms　"
            f"连续失败：{health.get('fail_count')}")
        if hasattr(self, "restart_state"):
            self.restart_state.setText(
                "重启网卡：已开启（上次重启时间戳 "
                f"{health.get('last_restart_ts') or '无'}）"
                if health.get("restart_enabled") else "重启网卡：已关闭")

    def on_theme(self, theme: str) -> None:
        self.on_status(self.ctx.status)

    def on_show(self) -> None:
        self.on_status(self.ctx.status)


__all__ = ["HealthPage"]
