# -*- coding: utf-8 -*-
"""流量页：下载保护按每个 WiFi 独立配置（网速阈值 / 持续时长 / 累计流量阈值 + 单位）。"""
from __future__ import annotations

from PyQt5.QtWidgets import QComboBox, QLabel

from .. import widgets as W
from .base import Page

SPEED_UNITS = ["KB/s", "MB/s", "GB/s"]
VOLUME_UNITS = ["KB", "MB", "GB"]


class TrafficPage(Page):
    title = "流量"
    subtitle = ("总开关开启后，按当前连接的 WiFi 读取其独立配置："
                "持续 x 秒超过网速阈值且本会话累计流量超过阈值时触发下载保护。")
    triggers = ("traffic",)

    def build(self) -> None:
        traffic = self.ctx.cfg.setdefault("traffic", {})

        # ---------------- 全局 ----------------
        card = self.add_card("下载保护总开关")
        card.add_head_widget(W.Button("保存", "primary", self.save_global))
        self.check_enabled = W.CheckRow("启用下载流量检测（所有 WiFi 的前提）",
                                        bool(traffic.get("enabled", True)))
        card.add(self.check_enabled)
        self.spin_interval = W.int_spin(1, 60, int(traffic.get("sample_interval_seconds") or 2),
                                        " 秒")
        self.spin_top = W.int_spin(1, 20, int(traffic.get("top_processes") or 5), " 个")
        self.check_inspect = W.CheckRow("检测占用带宽的进程（用于弹窗提示）",
                                        bool(traffic.get("inspect_processes", True)))
        card.add(W.form_grid([("采样间隔", self.spin_interval),
                              ("提示占用进程数量", self.spin_top)]))
        card.add(self.check_inspect)

        # ---------------- 当前实时 ----------------
        card_now = self.add_card("当前实时（本会话，仅统计不切断）")
        self.metric = W.metric_row([("实时下载速率", "—"), ("本会话累计接收", "—"),
                                    ("当前 WiFi", "—"), ("本会话峰值速率", "—"),
                                    ("触发保护次数", "0")])
        card_now.add(self.metric)
        self.rate_label = self.metric.findChildren(W.Metric)[0]
        self.total_label = self.metric.findChildren(W.Metric)[1]
        self.net_label = self.metric.findChildren(W.Metric)[2]
        self.peak_label = self.metric.findChildren(W.Metric)[3]
        self.trip_label = self.metric.findChildren(W.Metric)[4]
        self.guard_hint = W.muted("")
        card_now.add(self.guard_hint)

        # ---------------- 按 WiFi 配置 ----------------
        card2 = self.add_card("按 WiFi 分别配置下载保护")
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(lambda _i: self.load_network())
        card2.add(W.form_grid([("目标 WiFi", self.combo)]))

        self.check_net_enabled = W.CheckRow("该 WiFi 启用下载保护", False)
        card2.add(self.check_net_enabled)

        self.speed = W.UnitSpinBox(SPEED_UNITS, 2.0, "MB/s", decimals=2, maximum=100000.0)
        self.spin_sustained = W.int_spin(1, 3600, 10, " 秒")
        self.volume = W.UnitSpinBox(VOLUME_UNITS, 50.0, "MB", decimals=2, maximum=1_000_000.0)
        self.check_deny = W.CheckRow("触发保护后保持断网（不允许自动重连）", True)
        card2.add(W.form_grid([
            ("网速阈值（持续超速）", self.speed),
            ("持续时间", self.spin_sustained),
            ("累计流量阈值", self.volume),
        ]))
        card2.add(self.check_deny)
        card2.add(W.muted("单位可切换：网速 KB/s、MB/s、GB/s；流量 KB、MB、GB。"
                          "语义为「网速持续 x 秒 ≥ 阈值，且累计消耗 y 流量」时触发。"))
        card2.add(self.row(W.Button("保存该 WiFi 配置", "primary", self.save_network),
                           W.Button("恢复该 WiFi 默认值", "ghost", self.reset_network)))

        self.reload_networks()
        self.on_status(self.ctx.status)

    # ------------------------------------------------------------------ #
    def reload_networks(self) -> None:
        self.combo.blockSignals(True)
        current = self.combo.currentData()
        self.combo.clear()
        for name in self.ctx.cfg.get("networks", {}):
            label = (self.ctx.cfg["networks"][name] or {}).get("label") or name
            self.combo.addItem(f"{label}（{name}）", name)
        index = self.combo.findData(current)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.combo.blockSignals(False)
        self.load_network()

    def _network_cfg(self, name: str) -> dict:
        return self.ctx.cfg.setdefault("networks", {}).setdefault(name, {})

    def load_network(self) -> None:
        name = self.combo.currentData()
        if not name:
            return
        guard = dict(self._network_cfg(name).get("guard") or {})
        defaults = dict(self.ctx.cfg.get("traffic", {}).get("defaults") or {})
        speed = dict(guard.get("speed") or defaults.get("speed") or {})
        volume = dict(guard.get("volume") or defaults.get("volume") or {})
        self.check_net_enabled.setChecked(bool(guard.get("enabled")))
        self.speed.set_value(float(speed.get("value") or 0), str(speed.get("unit") or "MB/s"))
        self.spin_sustained.setValue(int(guard.get("sustained_seconds")
                                         or defaults.get("sustained_seconds") or 10))
        self.volume.set_value(float(volume.get("value") or 0), str(volume.get("unit") or "MB"))
        self.check_deny.setChecked(bool(guard.get("deny_keeps_disconnected", True)))

    def save_global(self) -> None:
        traffic = self.ctx.cfg.setdefault("traffic", {})
        traffic["enabled"] = self.check_enabled.isChecked()
        traffic["sample_interval_seconds"] = int(self.spin_interval.value())
        traffic["top_processes"] = int(self.spin_top.value())
        traffic["inspect_processes"] = self.check_inspect.isChecked()
        self.ctx.save_config()
        self.ctx.refresh_status()
        self.ctx.notify("下载保护总开关已保存")

    def save_network(self) -> None:
        name = self.combo.currentData()
        if not name:
            return
        net = self._network_cfg(name)
        net["guard"] = {
            "enabled": self.check_net_enabled.isChecked(),
            "speed": {"value": self.speed.value(), "unit": self.speed.unit()},
            "sustained_seconds": int(self.spin_sustained.value()),
            "volume": {"value": self.volume.value(), "unit": self.volume.unit()},
            "sample_interval_seconds": int(self.ctx.cfg.get("traffic", {})
                                           .get("sample_interval_seconds") or 2),
            "deny_keeps_disconnected": self.check_deny.isChecked(),
        }
        self.ctx.save_config()
        self.ctx.notify(f"{name} 的下载保护配置已保存")

    def reset_network(self) -> None:
        name = self.combo.currentData()
        if not name:
            return
        if not self.confirm("恢复默认值", f"确认把 {name} 的下载保护恢复为全局默认值？"):
            return
        defaults = dict(self.ctx.cfg.get("traffic", {}).get("defaults") or {})
        net = self._network_cfg(name)
        net["guard"] = dict(defaults)
        self.ctx.save_config()
        self.load_network()
        self.ctx.notify(f"{name} 已恢复默认值")

    # ------------------------------------------------------------------ #
    def on_status(self, status: dict) -> None:
        now = (status or {}).get("traffic") or {}
        connection = (status or {}).get("connection") or {}
        current = now.get("network") or connection.get("current_network") or "—"
        self.rate_label.set_value(now.get("down_speed") or "0 B/s")
        self.total_label.set_value(now.get("session_recv_human") or "0 B")
        self.net_label.set_value(current)
        self.peak_label.set_value(now.get("peak_down_speed") or "0 B/s")
        self.trip_label.set_value(str(now.get("trip_count") or 0))
        guard = now.get("guard") or {}
        if guard:
            self.guard_hint.setText(
                f"当前 WiFi {current} 的下载保护："
                f"{'已启用' if guard.get('enabled') else '未启用（仅统计网速与流量）'}；"
                f"网速 {guard.get('speed', {}).get('value', '—')} "
                f"{guard.get('speed', {}).get('unit', '')}，"
                f"持续 {guard.get('sustained_seconds', '—')} 秒，"
                f"累计 {guard.get('volume', {}).get('value', '—')} "
                f"{guard.get('volume', {}).get('unit', '')}。"
                + (f"　状态：{now.get('message')}" if now.get("message") else ""))
        else:
            self.guard_hint.setText(f"当前 WiFi {current} 暂无下载保护配置（走全局默认值）。")

    def on_show(self) -> None:
        self.reload_networks()
        self.on_status(self.ctx.status)


__all__ = ["TrafficPage"]
