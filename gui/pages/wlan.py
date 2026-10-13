# -*- coding: utf-8 -*-
"""WLAN 页：读取本机已保存的无线配置、设置主/备网络、连接/断开/重启网卡。

每个网络一个「是否需要登录」开关，并与该网络插件的 need_login 联动
（插件目录名 = WiFi 名称，登录规则各自独立，互不影响）。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QHeaderView,
                             QListWidget, QListWidgetItem, QTableWidget,
                             QTableWidgetItem, QWidget)

from core import wlan as wlan_mod

from .. import config_ops
from .. import widgets as W
from .base import Page

_COL_PRIMARY, _COL_NAME, _COL_PROFILE, _COL_LOGIN, _COL_PLUGIN = range(5)


class WlanPage(Page):
    title = "WLAN"
    subtitle = ("本机已保存的无线配置可直接选用；每个 WiFi 一个「是否需要登录」开关，"
                "并与其专属插件联动（插件目录名 = WiFi 名称）。")
    triggers = ("connection", "networks", "plugins")

    def build(self) -> None:
        self._loading = False

        # ---------------- 本机已保存的无线配置 ----------------
        card = self.add_card("本机已保存的无线配置",
                             "来自 netsh wlan show profiles（核心层 wlan 能力）。")
        btn_reload = W.Button("刷新本机配置", "ghost", self.reload_profiles)
        btn_add = W.Button("加入配置", "primary", self.add_selected_to_config)
        card.add_head_widget(btn_reload)
        card.add_head_widget(btn_add)

        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_list.setMinimumHeight(140)
        card.add(self.profile_list)
        self.profile_hint = W.muted("点击「刷新本机配置」读取本机无线记录。")
        card.add(self.profile_hint)

        # ---------------- 网络配置 ----------------
        card2 = self.add_card("网络配置（主 / 备）",
                              "勾选「主网络」表示断线时优先恢复该网络；"
                              "「需要登录」开关会同步写入对应插件 manifest 的 need_login。")
        btn_del = W.Button("删除选中网络", "danger", self.remove_selected)
        btn_plugin = W.Button("打开该 WiFi 插件", "ghost", self.open_plugin_page)
        card2.add_head_widget(btn_plugin)
        card2.add_head_widget(btn_del)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["主网络", "网络名称", "无线配置文件",
                                              "需要登录", "插件状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_PRIMARY, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_PROFILE, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_LOGIN, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PLUGIN, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        card2.add(self.table)
        self.table_hint = W.muted("")
        card2.add(self.table_hint)

        # ---------------- 网络操作 ----------------
        card3 = self.add_card("网络操作", "重启网卡需要管理员权限（禁用/启用无线网卡）。")
        self.action_target = QComboBox()
        self.action_target.setMinimumWidth(180)
        btn_conn = W.Button("连接", "primary", self.do_connect)
        btn_disc = W.Button("断开", "ghost", self.do_disconnect)
        btn_restart = W.Button("重启网卡", "ghost", self.do_restart)
        card3.add(self.row(W.muted("目标网络"), self.action_target, btn_conn, btn_disc,
                           btn_restart))
        self.action_hint = W.muted("")
        card3.add(self.action_hint)

        self.refresh_table()
        self.reload_profiles()

    # ------------------------------------------------------------------ #
    # 数据刷新
    # ------------------------------------------------------------------ #
    def reload_profiles(self) -> None:
        self.profile_hint.setText("正在读取本机无线配置…")
        self.ctx.load_profiles(on_done=self._on_profiles, on_error=self._on_profiles_error)

    def _on_profiles(self, _tag, payload) -> None:
        payload = payload or {}
        profiles = payload.get("detailed") or []
        names = [p.get("name") for p in profiles] or list(payload.get("profiles") or [])
        self.profile_list.clear()
        for entry in profiles:
            name = str(entry.get("name") or "")
            iface = str(entry.get("interface") or "")
            item = QListWidgetItem(f"{name}" + (f"　（{iface}）" if iface else ""))
            item.setData(Qt.UserRole, name)
            self.profile_list.addItem(item)
        if not names:
            names = [str(n) for n in (payload.get("profiles") or [])]
            for name in names:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, name)
                self.profile_list.addItem(item)
        self.profile_hint.setText(
            f"共读取到 {len(names)} 个已保存的无线配置；网卡：{payload.get('interface') or '—'}")

    def _on_profiles_error(self, _tag, err) -> None:
        self.profile_hint.setText(f"读取本机无线配置失败：{err}")

    def refresh_table(self) -> None:
        self._loading = True
        rows = config_ops.networks_view(self.ctx.cfg)
        self.table.setRowCount(len(rows))
        for row, info in enumerate(rows):
            primary = QTableWidgetItem()
            primary.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            primary.setCheckState(Qt.Checked if info["primary"] else Qt.Unchecked)
            primary.setData(Qt.UserRole, info["name"])
            self.table.setItem(row, _COL_PRIMARY, primary)

            name_item = QTableWidgetItem(info["name"])
            name_item.setData(Qt.UserRole, info["name"])
            self.table.setItem(row, _COL_NAME, name_item)
            self.table.setItem(row, _COL_PROFILE, QTableWidgetItem(info["profile"] or ""))

            login = QTableWidgetItem()
            login.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            login.setCheckState(Qt.Checked if info["need_login"] else Qt.Unchecked)
            login.setData(Qt.UserRole, info["name"])
            self.table.setItem(row, _COL_LOGIN, login)

            if not info["plugin_exists"]:
                state = "未创建插件"
            elif info["plugin_ok"]:
                state = "正常"
            else:
                state = "校验不通过：" + "；".join(info["plugin_errors"][:2])
            self.table.setItem(row, _COL_PLUGIN, QTableWidgetItem(state))

        self._loading = False
        self._refresh_action_targets(rows)
        missing = [r["name"] for r in rows if not r["plugin_exists"] and r["need_login"]]
        self.table_hint.setText(
            "以下网络开启了「需要登录」但没有插件，请在「插件」页一键新建：" + "、".join(missing)
            if missing else "所有开启「需要登录」的网络都已具备插件。")

    def _refresh_action_targets(self, rows=None) -> None:
        rows = rows if rows is not None else config_ops.networks_view(self.ctx.cfg)
        current = self.action_target.currentText()
        self.action_target.clear()
        for info in rows:
            self.action_target.addItem(info["name"])
        if current:
            index = self.action_target.findText(current)
            if index >= 0:
                self.action_target.setCurrentIndex(index)

    # ------------------------------------------------------------------ #
    # 交互
    # ------------------------------------------------------------------ #
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        name = item.data(Qt.UserRole)
        if not name:
            return
        column = item.column()
        checked = item.checkState() == Qt.Checked
        if column == _COL_PRIMARY:
            net = self.ctx.cfg.setdefault("networks", {}).setdefault(name, {})
            if checked:
                for other, other_net in self.ctx.cfg["networks"].items():
                    other_net["primary"] = (other == name)
            else:
                net["primary"] = False
            self.ctx.save_config()
            self.refresh_table()
        elif column == _COL_LOGIN:
            self.set_need_login(name, checked)

    def set_need_login(self, name: str, need_login: bool) -> None:
        net = config_ops.ensure_network(self.ctx.cfg, name)
        net["need_login"] = bool(need_login)
        net["plugin"] = net.get("plugin") or name
        net.setdefault("login", {})["enabled"] = bool(need_login)
        self.ctx.save_config()

        plugin = config_ops.get_plugin(self.ctx.cfg, name)
        if plugin is not None:
            manifest = dict(plugin.manifest)
            manifest["need_login"] = bool(need_login)
            config_ops.save_manifest(self.ctx.cfg, name, manifest)
            self.ctx.reload_plugins()
            self.ctx.notify(f"{name}：已同步更新插件 need_login = {need_login}")
        elif need_login:
            self.ctx.notify(f"{name} 已开启登录，但还没有插件，请到「插件」页新建")
        self.refresh_table()

    def add_selected_to_config(self) -> None:
        item = self.profile_list.currentItem()
        if item is None:
            self.warn("加入配置", "请先在上方列表中选择一个本机无线配置。")
            return
        name = item.data(Qt.UserRole) or item.text()
        already = name in (self.ctx.cfg.get("networks") or {})
        net = config_ops.ensure_network(self.ctx.cfg, name)
        net["profile"] = name
        if not already:
            net["primary"] = not any(
                n.get("primary") for n in (self.ctx.cfg.get("networks") or {}).values()
                if n.get("name") != name)
        self.ctx.save_config()
        self.refresh_table()
        self.ctx.notify(("已更新" if already else "已加入") + f"网络配置：{name}")

    def remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.warn("删除选中网络", "请先在下方表格中选择一行。")
            return
        name = self.table.item(row, _COL_NAME).text()
        if not self.confirm("删除选中网络", f"确认从配置中移除网络「{name}」？\n"
                                          "（只删除配置项，不会删除该 WiFi 的插件目录与文件）"):
            return
        config_ops.remove_network(self.ctx.cfg, name)
        self.ctx.save_config()
        self.refresh_table()

    def open_plugin_page(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.warn("打开插件", "请先在下方表格中选择一个网络。")
            return
        wifi = self.table.item(row, _COL_NAME).text()
        window = self.window()
        if hasattr(window, "open_page_with_wifi"):
            window.open_page_with_wifi("插件", wifi)
        elif hasattr(window, "show_page"):
            window.show_page("插件")

    # ------------------------------------------------------------------ #
    # 网络动作
    # ------------------------------------------------------------------ #
    def _target(self) -> str:
        return self.action_target.currentText().strip()

    def do_connect(self) -> None:
        name = self._target()
        if not name:
            return
        self.action_hint.setText(f"正在连接 {name}…")
        self.async_call(self.ctx.service.connect_network, (name,), "连接网络",
                        tag="wlan-connect",
                        on_done=lambda r: self._after_action("连接", r))

    def do_disconnect(self) -> None:
        self.action_hint.setText("正在断开当前无线连接…")
        self.async_call(self.ctx.service.disconnect, (), "断开网络", tag="wlan-disconnect",
                        on_done=lambda r: self._after_action("断开", r))

    def do_restart(self) -> None:
        if not self.confirm("重启网卡",
                            "重启网卡会先禁用再启用无线网卡，期间网络会短暂中断，"
                            "且通常需要管理员权限。确认继续？"):
            return
        self.action_hint.setText("正在重启网卡…")
        target = self._target()
        self.async_call(lambda: wlan_mod.restart_adapter(self.ctx.cfg,
                                                        reconnect_profile=target),
                        (), "重启网卡", tag="wlan-restart",
                        on_done=lambda r: self._after_action("重启网卡", r))

    def _after_action(self, label: str, result) -> None:
        result = result or {}
        message = str(result.get("message") or ("成功" if result.get("ok") else "失败"))
        self.action_hint.setText(f"{label}：{message}")
        self.result_dialog(label, result)
        self.ctx.refresh_status()

    # ------------------------------------------------------------------ #
    def on_status(self, status: dict) -> None:
        conn = status.get("connection") or {}
        self.action_hint.setText(
            f"当前：{conn.get('ssid') or '未连接'}　"
            f"网卡：{conn.get('interface') or '—'}　"
            f"配置网络：{conn.get('current_network') or '—'}")

    def on_show(self) -> None:
        self.refresh_table()
