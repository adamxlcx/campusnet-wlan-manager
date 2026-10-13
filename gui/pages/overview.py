# -*- coding: utf-8 -*-
"""概览页：当前 WiFi / 网卡 / 连通状态 / 托盘配色 / 下次计划 / 实时速率与会话流量。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QLabel, QWidget

from .. import theme as theme_mod
from .. import widgets as W
from .base import Page


class OverviewPage(Page):
    title = "概览"
    subtitle = "一屏掌握当前网络状态、托盘配色、下次计划与下载流量。"
    triggers = ("connection", "health", "traffic", "schedules", "service")

    def build(self) -> None:
        # ---------------- 当前连接 ----------------
        card = self.add_card("当前连接")
        self.btn_refresh = W.Button("刷新状态", "ghost", self._refresh)
        self.btn_connect_primary = W.Button("连接主网络", "primary", self._connect_primary)
        card.add_head_widget(self.btn_refresh)
        card.add_head_widget(self.btn_connect_primary)

        self.dot = W.StatusDot("gray")
        self.state_text = QLabel("等待核心层状态…")
        self.state_text.setObjectName("Value")
        card.add(self.row(self.dot, self.state_text))

        self.conn_grid = W.grid_of([("当前 WiFi", "—"), ("网卡", "—"),
                                    ("连接状态", "—"), ("当前配置网络", "—"),
                                    ("信号", "—"), ("后台服务", "—")], columns=2)
        card.add(self.conn_grid)
        self._conn_labels = self.conn_grid.findChildren(QLabel)

        # ---------------- 托盘与检测 ----------------
        card2 = self.add_card("托盘图标配色", "托盘图标随连通性检测结果实时刷新。")
        self.tray_state_label = QLabel("灰：连通性检测未开启或状态未知")
        self.tray_hint = W.muted("")
        card2.add(self.tray_state_label)
        card2.add(self.tray_hint)

        # ---------------- 指标 ----------------
        card3 = self.add_card("实时速率 / 会话流量")
        self.metric_speed = W.Metric("当前下载速率", "—")
        self.metric_session = W.Metric("本会话累计下载", "—")
        self.metric_next = W.Metric("下次计划执行", "—")
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.addWidget(self.metric_speed, 0, 0)
        grid.addWidget(self.metric_session, 0, 1)
        grid.addWidget(self.metric_next, 0, 2)
        grid.setColumnStretch(3, 1)
        card3.add(holder)

        # ---------------- 计划摘要 ----------------
        card4 = self.add_card("计划任务摘要", "来自核心层调度器（scheduler）的下次执行时间。")
        self.sched_label = QLabel("暂无启用的计划规则")
        self.sched_label.setWordWrap(True)
        card4.add(self.sched_label)

        self.add_widget(W.muted("提示：所有开关（连通性检测、重启网卡、开机自启动、计划任务）"
                                "都可在「网络检测」与「设置」页独立调整。"))
        self._refresh()

    # ------------------------------------------------------------------ #
    def _refresh(self) -> None:
        self.ctx.refresh_status()

    def _connect_primary(self) -> None:
        primary = self._primary_network()
        if not primary:
            self.warn("连接主网络", "当前配置里没有主网络，请先在「WLAN」页设置。")
            return
        self.async_call(self.ctx.service.connect_network, (primary,), "连接主网络",
                        tag="connect-primary", busy_text=f"正在连接 {primary}…")

    def _primary_network(self) -> str:
        for name, net in (self.ctx.cfg.get("networks") or {}).items():
            if net.get("primary"):
                return name
        names = list((self.ctx.cfg.get("networks") or {}).keys())
        return names[0] if names else ""

    # ------------------------------------------------------------------ #
    def on_status(self, status: dict) -> None:
        conn = status.get("connection") or {}
        health = status.get("health") or {}
        traffic = status.get("traffic") or {}
        service = status.get("service") or {}

        state = theme_mod.tray_state(status)
        self.dot.set_state(state, self.ctx.theme())
        self.state_text.setText(theme_mod.tray_state_text(state))
        self.state_text.setProperty("state", state)

        values = [
            conn.get("ssid") or "未连接",
            conn.get("interface") or "—",
            ("已连接" if conn.get("connected") else "未连接") + f"（{conn.get('state') or 'unknown'}）",
            conn.get("current_network") or "—",
            ("%s%%" % conn.get("signal")) if conn.get("signal") not in (None, "") else "—",
            ("运行中 pid=%s" % (service.get("pid") or "—")) if service.get("running") else "未运行",
        ]
        labels = self._conn_labels
        for index, value in enumerate(values):
            # grid 顺序为 键/值 交替，值在奇数位
            if 2 * index + 1 < len(labels):
                labels[2 * index + 1].setText(str(value))

        if health.get("enabled"):
            self.tray_state_label.setText(
                f"连通性检测：已开启（间隔 {self.ctx.cfg.get('health', {}).get('interval_seconds', '—')} 秒，"
                f"检测地址 {self.ctx.cfg.get('health', {}).get('ping_target', '—')}）")
            self.tray_hint.setText("绿=连通，红=不通；重启网卡开关："
                                   + ("已开启" if health.get("restart_enabled") else "已关闭"))
        else:
            self.tray_state_label.setText("连通性检测：已关闭 → 托盘图标使用中性灰")
            self.tray_hint.setText("可在「网络检测」页开启连通性检测，开启后托盘图标实时显示绿/红。")

        self.metric_speed.set_value(traffic.get("down_speed") or "—")
        self.metric_session.set_value(traffic.get("session_recv_human") or "—")

        schedules = status.get("schedules") or []
        enabled = [s for s in schedules if s.get("enabled")]
        if enabled:
            first = sorted(enabled, key=lambda s: str(s.get("next_run") or "9999"))[0]
            self.metric_next.set_value(str(first.get("next_run") or "—"))
            lines = []
            for rule in enabled[:6]:
                lines.append(f"· {rule.get('name') or rule.get('id')} → "
                             f"{rule.get('target_network') or '—'}，下次 {rule.get('next_run') or '—'}"
                             f"（{rule.get('schedule') or ''}）")
            self.sched_label.setText("\n".join(lines))
        else:
            self.metric_next.set_value("—")
            self.sched_label.setText("暂无启用的计划规则（可在「计划」页新建）。")

    def on_show(self) -> None:
        self._refresh()
