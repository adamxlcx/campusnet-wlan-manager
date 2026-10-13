# -*- coding: utf-8 -*-
"""插件页：插件按 WiFi 名称列出；可视化编辑 manifest（登录页 URL / 是否需要登录等）；
按插件声明的 credentials + options 自动渲染表单（密码掩码）；编辑 login.js；校验；一键新建。

一个 WiFi 一个插件、登录规则各自独立，互不影响。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                             QDialogButtonBox, QGridLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit,
                             QVBoxLayout, QWidget)

from .. import config_ops
from .. import widgets as W
from .base import Page

_MASK_TYPES = {"password", "passwd", "pwd"}


# --------------------------------------------------------------------------- #
# login.js 编辑器
# --------------------------------------------------------------------------- #
class CodeDialog(QDialog):
    """轻量代码编辑器（用于编辑 login.js）。"""

    def __init__(self, title: str, path: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560)
        self.path = path
        layout = QVBoxLayout(self)
        layout.addWidget(W.muted(path))
        self.editor = QPlainTextEdit(text)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setObjectName("CodeView")
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.editor.toPlainText()


# --------------------------------------------------------------------------- #
# 新建插件对话框
# --------------------------------------------------------------------------- #
class NewPluginDialog(QDialog):
    def __init__(self, candidates: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建插件")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.combo_wifi = QComboBox()
        self.combo_wifi.setEditable(True)
        for name in candidates:
            self.combo_wifi.addItem(name)
        self.edit_name = QLineEdit("")
        self.edit_name.setPlaceholderText("留空则使用「WiFi 名称 登录插件」")
        self.edit_url = QLineEdit("http://")
        self.check_login = QCheckBox("该网络需要登录（need_login）")
        self.check_login.setChecked(True)
        self.check_js = QCheckBox("同时生成 login.js 骨架（满足插件契约）")
        self.check_js.setChecked(True)
        self.check_register = QCheckBox("同时写入 config.json 的网络配置")
        self.check_register.setChecked(True)
        grid.addWidget(QLabel("WiFi 名称（= 插件目录名）"), 0, 0)
        grid.addWidget(self.combo_wifi, 0, 1)
        grid.addWidget(QLabel("插件名称"), 1, 0)
        grid.addWidget(self.edit_name, 1, 1)
        grid.addWidget(QLabel("登录页 URL"), 2, 0)
        grid.addWidget(self.edit_url, 2, 1)
        layout.addLayout(grid)
        layout.addWidget(self.check_login)
        layout.addWidget(self.check_js)
        layout.addWidget(self.check_register)
        layout.addWidget(W.muted("插件目录名必须与 WiFi 名称一致；不同 WiFi 使用各自插件。"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("创建")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {
            "wifi": self.combo_wifi.currentText().strip(),
            "name": self.edit_name.text().strip(),
            "url": self.edit_url.text().strip(),
            "need_login": self.check_login.isChecked(),
            "with_js": self.check_js.isChecked(),
            "register_network": self.check_register.isChecked(),
        }


# --------------------------------------------------------------------------- #
# 插件页
# --------------------------------------------------------------------------- #
class PluginPage(Page):
    title = "插件"
    subtitle = "每个 WiFi 一个插件（目录名 = WiFi 名称）；登录页匹配由 login.js 完成，规则互不影响。"
    triggers = ("plugins",)

    def build(self) -> None:
        self._wifi = ""
        self._fields: list = []

        card = self.add_card("插件列表（按 WiFi 名称）")
        card.add_head_widget(W.Button("刷新", "ghost", self.reload))
        card.add_head_widget(W.Button("校验全部", "ghost", self.validate_all))
        card.add_head_widget(W.Button("一键新建插件", "primary", self.new_plugin))
        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        self.list.currentRowChanged.connect(self._on_select)
        card.add(self.list)
        self.list_hint = W.muted("")
        card.add(self.list_hint)

        card2 = self.add_card("登录设置（写入 manifest）",
                              "URL 同时写入 config.json 的 networks[WiFi].login.url，供核心层优先使用。")
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("http://…")
        self.check_need_login = QCheckBox("该 WiFi 需要登录（need_login）")
        self.combo_driver = QComboBox()
        self.combo_driver.addItems(["auto", "edge", "chrome", "requests"])
        card2.add(W.form_grid([("登录页 URL", self.edit_url),
                               ("浏览器驱动", self.combo_driver)]))
        card2.add(self.check_need_login)
        self.need_login_hint = W.muted("")
        card2.add(self.need_login_hint)
        card2.add_head_widget(W.Button("保存登录设置", "primary", self.save_login))

        card3 = self.add_card("自定义选项（按插件声明渲染）",
                              "账号 / 密码来自 manifest.credentials，运营商等来自 manifest.options；"
                              "值写入 config.json 的 networks[WiFi].login.*。")
        self.options_holder = QWidget()
        self.options_layout = QVBoxLayout(self.options_holder)
        self.options_layout.setContentsMargins(0, 0, 0, 0)
        self.options_layout.setSpacing(8)
        card3.add(self.options_holder)
        card3.add_head_widget(W.Button("保存选项", "primary", self.save_options))
        self.options_hint = W.muted("")
        card3.add(self.options_hint)

        card4 = self.add_card("login.js", "网页匹配与填写逻辑（fill / submit / success / request）。")
        card4.add_head_widget(W.Button("编辑 login.js", "primary", self.edit_js))
        card4.add_head_widget(W.Button("打开所在文件夹", "ghost", self.open_folder))
        self.js_path_label = W.muted("—")
        self.js_path_label.setWordWrap(True)
        card4.add(self.js_path_label)
        self.js_preview = QLabel("—")
        self.js_preview.setObjectName("CodeView")
        self.js_preview.setWordWrap(True)
        self.js_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card4.add(self.js_preview)

        self.reload()

    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        self.plugins = config_ops.list_plugins(self.ctx.cfg)
        current = self._wifi
        self.list.blockSignals(True)
        self.list.clear()
        for plugin in self.plugins:
            wifi = str(plugin.wifi)
            state = "正常" if not plugin.errors else "校验不通过"
            item = QListWidgetItem(f"{wifi}　·　{wifi and str(plugin.manifest.get('id') or '')}"
                                   f"　·　{state}")
            item.setData(Qt.UserRole, wifi)
            self.list.addItem(item)
        self.list.blockSignals(False)

        networks = set((self.ctx.cfg.get("networks") or {}).keys())
        wifi_names = {str(p.wifi) for p in self.plugins}
        missing = sorted(wifi_names - networks)
        self.list_hint.setText(
            f"共 {len(self.plugins)} 个插件。"
            + (f"以下 WiFi 有插件但未在 config.json 注册为网络：{'、'.join(missing)}。" if missing else "")
            + (f"  配置中有网络但缺插件：{'、'.join(sorted(networks - wifi_names))}。"
               if networks - wifi_names else ""))

        target = current if current and any(str(p.wifi) == current for p in self.plugins) else ""
        if not target and self.plugins:
            target = str(self.plugins[0].wifi)
        self._wifi = target
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == target:
                self.list.setCurrentRow(row)
                break
        self._load_detail()

    def _current_plugin(self):
        for plugin in getattr(self, "plugins", []):
            if str(plugin.wifi) == self._wifi:
                return plugin
        return None

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= self.list.count():
            return
        self._wifi = self.list.item(row).data(Qt.UserRole) or ""
        self._load_detail()

    # ------------------------------------------------------------------ #
    def _load_detail(self) -> None:
        plugin = self._current_plugin()
        if plugin is None:
            self.edit_url.setText("")
            self.check_need_login.setChecked(False)
            self.need_login_hint.setText("未选择插件。")
            self.js_path_label.setText("—")
            self.js_preview.setText("—")
            self._clear_options()
            self.options_hint.setText("未选择插件。")
            return

        manifest = plugin.manifest or {}
        login = manifest.get("login") or {}
        net = (self.ctx.cfg.get("networks") or {}).get(self._wifi) or {}
        net_login = net.get("login") or {}

        self.edit_url.setText(str(net_login.get("url") or login.get("url") or ""))
        self.check_need_login.setChecked(bool(manifest.get("need_login", True)))
        index = self.combo_driver.findText(str(login.get("driver") or "auto"))
        self.combo_driver.setCurrentIndex(max(0, index))
        self.need_login_hint.setText(
            "config.json：need_login=%s　|　manifest：need_login=%s"
            % (net.get("need_login"), manifest.get("need_login"))
            + ("　　一致" if bool(net.get("need_login")) == bool(manifest.get("need_login"))
               else "　　不一致，保存后以本次设置为准"))

        js_file = config_ops.js_path(self.ctx.cfg, self._wifi)
        if os.path.isfile(js_file):
            text = config_ops.read_js(js_file) or ""
            lines = text.splitlines()
            self.js_path_label.setText(js_file)
            self.js_preview.setText("\n".join(lines[:18]) + ("\n…" if len(lines) > 18 else ""))
        else:
            self.js_path_label.setText(f"{js_file}（尚未创建）")
            self.js_preview.setText("login.js 不存在，可点击「一键新建插件」生成骨架，或手动创建。")

        self._render_options(manifest, net_login)

    # ------------------------------------------------------------------ #
    def _clear_options(self) -> None:
        self._fields = []
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_options(self, manifest: dict, net_login: dict) -> None:
        self._clear_options()
        credentials = manifest.get("credentials") or []
        options = manifest.get("options") or []
        rows = []
        for spec in list(credentials) + list(options):
            key = str(spec.get("key") or "")
            if not key:
                continue
            label = str(spec.get("label") or key)
            if spec.get("required"):
                label += " *"
            kind = str(spec.get("type") or "text").lower()
            if kind in _MASK_TYPES:
                group = "credentials"
                widget = QLineEdit()
                widget.setEchoMode(QLineEdit.Password)
                widget.setText(str((net_login.get("credentials") or {}).get(key, "")))
            elif kind == "select":
                group = "options"
                widget = QComboBox()
                widget.setEditable(str(spec.get("type")) in ("select-editable",))
                choices = spec.get("choices") or []
                for choice in choices:
                    if isinstance(choice, dict):
                        widget.addItem(str(choice.get("label")), str(choice.get("value")))
                    else:
                        widget.addItem(str(choice), str(choice))
                stored = (net_login.get("options") or {}).get(key, spec.get("default", ""))
                idx = widget.findData(str(stored))
                if idx < 0:
                    idx = widget.findText(str(stored))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                elif widget.isEditable():
                    widget.setEditText(str(stored))
            else:
                group = "credentials" if spec in credentials else "options"
                widget = QLineEdit()
                widget.setText(str((net_login.get(group) or {}).get(key, "")))
                placeholder = spec.get("placeholder")
                if placeholder:
                    widget.setPlaceholderText(str(placeholder))
            rows.append((label, widget))
            self._fields.append({"key": key, "group": group, "widget": widget,
                                 "spec": spec})
        if rows:
            form = W.FormGrid()
            for label, widget in rows:
                form.add_row(label, widget)
            self.options_layout.addWidget(form)
        else:
            self.options_layout.addWidget(W.muted("该插件未声明自定义选项。"))
        help_texts = [f"{spec.get('label') or spec.get('key')}：{spec.get('help')}"
                      for spec in list(credentials) + list(options) if spec.get("help")]
        self.options_hint.setText(
            (f"共 {len(rows)} 个可配置项。" if rows else "") +
            ("\n".join(help_texts) if help_texts else ""))

    def _collect_options(self) -> tuple:
        credentials, options = {}, {}
        for field in self._fields:
            widget = field["widget"]
            if isinstance(widget, QComboBox):
                value = widget.currentData()
                if value is None:
                    value = widget.currentText()
            else:
                value = widget.text()
            if field["group"] == "credentials":
                credentials[field["key"]] = str(value)
            else:
                options[field["key"]] = str(value)
        return credentials, options

    # ------------------------------------------------------------------ #
    def save_login(self) -> None:
        plugin = self._current_plugin()
        if plugin is None:
            self.warn("保存登录设置", "请先在左侧选择一个插件。")
            return
        wifi = self._wifi
        url = self.edit_url.text().strip()
        need_login = self.check_need_login.isChecked()
        driver = self.combo_driver.currentText()

        manifest = dict(plugin.manifest or {})
        login = dict(manifest.get("login") or {})
        login["url"] = url
        login["driver"] = driver
        manifest["login"] = login
        manifest["need_login"] = need_login
        errors = config_ops.validate_manifest(manifest, wifi,
                                             config_ops.read_js(config_ops.js_path(
                                                 self.ctx.cfg, wifi)) or "")
        if errors:
            self.warn("保存登录设置", "校验未通过，未写入：\n" + "\n".join(errors))
            return
        config_ops.save_manifest(self.ctx.cfg, wifi, manifest)

        net = config_ops.ensure_network(self.ctx.cfg, wifi)
        net["need_login"] = need_login
        net["plugin"] = net.get("plugin") or wifi
        net.setdefault("login", {})["url"] = url
        self.ctx.save_config()
        self.ctx.reload_plugins()
        self.reload()
        self.ctx.notify(f"已保存 {wifi} 的登录设置")

    def save_options(self) -> None:
        plugin = self._current_plugin()
        if plugin is None:
            self.warn("保存选项", "请先在左侧选择一个插件。")
            return
        credentials, options = self._collect_options()
        net = config_ops.ensure_network(self.ctx.cfg, self._wifi)
        login = net.setdefault("login", {})
        login["credentials"] = credentials
        login["options"] = options
        self.ctx.save_config()
        self.ctx.notify(f"已保存 {self._wifi} 的账号 / 选项（写入 config.json）")

    def edit_js(self) -> None:
        plugin = self._current_plugin()
        if plugin is None:
            self.warn("编辑 login.js", "请先在左侧选择一个插件。")
            return
        js_file = config_ops.js_path(self.ctx.cfg, self._wifi)
        if not os.path.isfile(js_file):
            if not self.confirm("编辑 login.js",
                                "login.js 不存在，是否按插件契约生成骨架？"):
                return
            config_ops.write_js(js_file, config_ops.js_skeleton(self._wifi,
                                                                self.edit_url.text()))
        dialog = CodeDialog(f"{self._wifi} / login.js", js_file,
                            config_ops.read_js(js_file) or "", self)
        if dialog.exec_() != QDialog.Accepted:
            return
        config_ops.write_js(js_file, dialog.text())
        self.ctx.reload_plugins()
        self._load_detail()
        self.ctx.notify(f"已保存 {js_file}")

    def open_folder(self) -> None:
        directory = config_ops.plugin_dir(self.ctx.cfg, self._wifi)
        if not os.path.isdir(directory):
            self.warn("打开所在文件夹", f"目录不存在：{directory}")
            return
        self.ctx.open_in_explorer(directory)

    def new_plugin(self) -> None:
        networks = sorted((self.ctx.cfg.get("networks") or {}).keys())
        existing = {str(p.wifi) for p in getattr(self, "plugins", [])}
        candidates = [n for n in networks if n not in existing] or networks
        dialog = NewPluginDialog(candidates, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values["wifi"]:
            self.warn("新建插件", "请填写 WiFi 名称。")
            return
        result = config_ops.create_plugin(
            self.ctx.cfg, values["wifi"], name=values["name"], url=values["url"],
            need_login=values["need_login"], with_js=values["with_js"],
            register_network=values["register_network"])
        if values["register_network"]:
            net = config_ops.ensure_network(self.ctx.cfg, values["wifi"])
            net["need_login"] = values["need_login"]
            net["plugin"] = values["wifi"]
            if values["url"]:
                net.setdefault("login", {})["url"] = values["url"]
            self.ctx.save_config()
        self.ctx.reload_plugins()
        self.reload()
        self.result_dialog("新建插件", result)

    def validate_all(self) -> None:
        self.ctx.reload_plugins()
        report = config_ops.plugin_report(self.ctx.cfg)
        lines = []
        bad = 0
        for item in report:
            errors = item.get("errors") or []
            bad += 1 if errors else 0
            lines.append(f"[{'OK' if not errors else 'NG'}] {item.get('wifi')}"
                         + ("" if not errors else " → " + "；".join(errors)))
        summary = f"共 {len(report)} 个插件，{len(report) - bad} 个通过，{bad} 个异常。"
        self.reload()
        message = summary + ("\n\n" + "\n".join(lines) if lines else "")
        if bad:
            self.warn("插件校验", message)
        else:
            self.info("插件校验", message)

    # ------------------------------------------------------------------ #
    def on_status(self, status: dict) -> None:
        pass

    def on_show(self) -> None:
        self.reload()

    def focus_wifi(self, wifi: str) -> None:
        wifi = str(wifi or "")
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == wifi:
                self.list.setCurrentRow(row)
                return
        self.ctx.notify(f"未找到插件：{wifi}")
