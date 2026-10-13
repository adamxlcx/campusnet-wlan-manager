# -*- coding: utf-8 -*-
"""计划页：智能闹钟式交互（频率 / 月份 / 星期 / 时间 / 目标网络 / 是否需要登录 / 补执行窗口）。

界面上只做“录入 + 预览”，真正的触发判定由核心层 `core.scheduler` 负责，
对话框里实时调用 `scheduler.next_run()` 展示下次执行时间，避免两套逻辑。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from PyQt5.QtCore import QDate, QTime, Qt
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit,
                             QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QSpinBox, QTableWidget,
                             QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from core import scheduler as scheduler_mod

from .. import config_ops
from .. import widgets as W
from .base import Page

MODES = [("once", "仅一次"), ("daily", "每天"), ("weekly", "每周"), ("monthly", "每月")]
WEEKDAYS = [(1, "周一"), (2, "周二"), (3, "周三"), (4, "周四"),
            (5, "周五"), (6, "周六"), (7, "周日")]
MONTHS = [(m, f"{m}月") for m in range(1, 13)]


# --------------------------------------------------------------------------- #
# 编辑对话框
# --------------------------------------------------------------------------- #
class ScheduleDialog(QDialog):
    """计划规则编辑框（智能闹钟式）。"""

    def __init__(self, networks: list, rule: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("计划规则")
        self.setMinimumWidth(560)
        self.networks = list(networks or [])
        rule = dict(rule or {})
        repeat = dict(rule.get("repeat") or {})

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # ---- 基本信息 ----
        base = QGroupBox("基本信息")
        grid = QGridLayout(base)
        self.edit_name = QLineEdit(str(rule.get("name") or "新计划"))
        self.combo_network = QComboBox()
        self.combo_network.setEditable(True)
        for name in self.networks:
            self.combo_network.addItem(name)
        target = str(rule.get("target_network") or (self.networks[0] if self.networks else ""))
        if target and self.combo_network.findText(target) < 0:
            self.combo_network.addItem(target)
        self.combo_network.setCurrentText(target)

        self.combo_action = QComboBox()
        self.combo_action.addItem("连接网络", "connect")
        self.combo_action.addItem("断开网络", "disconnect")
        index = self.combo_action.findData(str(rule.get("action") or "connect"))
        self.combo_action.setCurrentIndex(max(0, index))

        self.check_login = QCheckBox("连接后需要登录（调用该 WiFi 的登录插件）")
        self.check_login.setChecked(bool(rule.get("need_login", True)))
        self.check_enabled = QCheckBox("启用该规则")
        self.check_enabled.setChecked(bool(rule.get("enabled", True)))

        grid.addWidget(QLabel("名称"), 0, 0)
        grid.addWidget(self.edit_name, 0, 1, 1, 3)
        grid.addWidget(QLabel("目标网络"), 1, 0)
        grid.addWidget(self.combo_network, 1, 1)
        grid.addWidget(QLabel("动作"), 1, 2)
        grid.addWidget(self.combo_action, 1, 3)
        grid.addWidget(self.check_login, 2, 1, 1, 3)
        grid.addWidget(self.check_enabled, 3, 1, 1, 3)
        outer.addWidget(base)

        # ---- 频率 / 时间 ----
        when = QGroupBox("时间（智能闹钟）")
        when_grid = QGridLayout(when)
        self.combo_mode = QComboBox()
        for mode, label in MODES:
            self.combo_mode.addItem(label, mode)
        index = self.combo_mode.findData(str(repeat.get("mode") or "daily"))
        self.combo_mode.setCurrentIndex(max(0, index))

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        parsed = scheduler_mod.parse_hhmm(str(rule.get("time") or "08:00"))
        self.time_edit.setTime(QTime(parsed.hour, parsed.minute))

        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        date_value = scheduler_mod.parse_date(str(repeat.get("date") or ""))
        self.date_edit.setDate(QDate(date_value.year, date_value.month, date_value.day)
                               if date_value else QDate.currentDate())

        when_grid.addWidget(QLabel("频率"), 0, 0)
        when_grid.addWidget(self.combo_mode, 0, 1)
        when_grid.addWidget(QLabel("时间"), 0, 2)
        when_grid.addWidget(self.time_edit, 0, 3)
        self.label_date = QLabel("日期（仅一次）")
        when_grid.addWidget(self.label_date, 1, 0)
        when_grid.addWidget(self.date_edit, 1, 1, 1, 3)

        # 月份多选
        self.group_months = QGroupBox("限定月份（不勾选 = 每月都可）")
        months_lay = QHBoxLayout(self.group_months)
        months_lay.setSpacing(4)
        self.month_checks = {}
        selected_months = {int(m) for m in (repeat.get("months") or [])}
        for month, label in MONTHS:
            box = QCheckBox(str(month))
            box.setToolTip(label)
            box.setChecked(month in selected_months)
            self.month_checks[month] = box
            months_lay.addWidget(box)
        months_lay.addStretch(1)
        when_grid.addWidget(self.group_months, 2, 0, 1, 4)

        # 星期多选
        self.group_weekdays = QGroupBox("星期")
        week_lay = QHBoxLayout(self.group_weekdays)
        week_lay.setSpacing(4)
        self.weekday_checks = {}
        selected_weekdays = {int(d) for d in (repeat.get("weekdays") or [])}
        for day, label in WEEKDAYS:
            box = QCheckBox(label)
            box.setChecked(day in selected_weekdays)
            self.weekday_checks[day] = box
            week_lay.addWidget(box)
        week_lay.addStretch(1)
        when_grid.addWidget(self.group_weekdays, 3, 0, 1, 4)

        # 日期多选（每月）
        self.group_days = QGroupBox("每月第几天（勾选「月末」= 当月最后一天，可多选）")
        days_lay = QGridLayout(self.group_days)
        days_lay.setSpacing(4)
        self.day_checks = {}
        selected_days = {int(d) for d in (repeat.get("days") or [])}
        for day in range(1, 32):
            box = QCheckBox(str(day))
            box.setChecked(day in selected_days)
            self.day_checks[day] = box
            days_lay.addWidget(box, (day - 1) // 8, (day - 1) % 8)
        self.day_last = QCheckBox("月末")
        self.day_last.setChecked(-1 in selected_days)
        days_lay.addWidget(self.day_last, 3, 0, 1, 2)
        when_grid.addWidget(self.group_days, 4, 0, 1, 4)

        outer.addWidget(when)

        # ---- 补执行 / 重试 ----
        extra = QGroupBox("补执行与重试")
        extra_grid = QGridLayout(extra)
        self.spin_window = QSpinBox()
        self.spin_window.setRange(0, 1440)
        self.spin_window.setSuffix(" 分钟")
        self.spin_window.setValue(int(rule.get("window_minutes") or 0))
        self.spin_retry = QSpinBox()
        self.spin_retry.setRange(30, 7200)
        self.spin_retry.setSuffix(" 秒")
        self.spin_retry.setValue(int(rule.get("retry_interval_seconds") or 300))
        self.spin_max_attempts = QSpinBox()
        self.spin_max_attempts.setRange(1, 200)
        self.spin_max_attempts.setValue(int(rule.get("max_attempts_per_day") or 10))
        extra_grid.addWidget(QLabel("补执行窗口"), 0, 0)
        extra_grid.addWidget(self.spin_window, 0, 1)
        extra_grid.addWidget(QLabel("失败重试间隔"), 0, 2)
        extra_grid.addWidget(self.spin_retry, 0, 3)
        extra_grid.addWidget(QLabel("每天最多尝试"), 1, 0)
        extra_grid.addWidget(self.spin_max_attempts, 1, 1)
        extra_grid.addWidget(W.muted("窗口内错过的时间点会被补执行（0 表示不补执行）。"),
                             1, 2, 1, 2)
        outer.addWidget(extra)

        # ---- 预览 ----
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setObjectName("chip")
        outer.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.combo_mode.currentIndexChanged.connect(self._sync_mode)
        self.time_edit.timeChanged.connect(self._update_preview)
        for box in list(self.month_checks.values()) + list(self.weekday_checks.values()) \
                + list(self.day_checks.values()) + [self.day_last, self.date_edit]:
            try:
                box.toggled.connect(self._update_preview)
            except AttributeError:
                box.dateChanged.connect(self._update_preview)
        self._sync_mode()
        self._update_preview()

    # ------------------------------------------------------------------ #
    def mode(self) -> str:
        return str(self.combo_mode.currentData() or "daily")

    def _sync_mode(self) -> None:
        mode = self.mode()
        self.date_edit.setVisible(mode == "once")
        self.label_date.setVisible(mode == "once")
        self.group_months.setVisible(mode != "once")
        self.group_weekdays.setVisible(mode == "weekly")
        self.group_days.setVisible(mode == "monthly")
        self._update_preview()

    def rule(self) -> dict:
        mode = self.mode()
        months = [m for m, box in self.month_checks.items() if box.isChecked()] \
            if mode != "once" else []
        weekdays = [d for d, box in self.weekday_checks.items() if box.isChecked()] \
            if mode == "weekly" else []
        days = [d for d, box in self.day_checks.items() if box.isChecked()] \
            if mode == "monthly" else []
        if mode == "monthly" and self.day_last.isChecked():
            days.append(-1)
        if mode == "once":
            date_text = self.date_edit.date().toString("yyyy-MM-dd")
        else:
            date_text = ""
        return {
            "id": getattr(self, "_rule_id", "") or f"gui-{uuid.uuid4().hex[:8]}",
            "name": self.edit_name.text().strip() or "未命名计划",
            "enabled": self.check_enabled.isChecked(),
            "action": str(self.combo_action.currentData() or "connect"),
            "target_network": self.combo_network.currentText().strip(),
            "need_login": self.check_login.isChecked(),
            "time": self.time_edit.time().toString("HH:mm"),
            "window_minutes": int(self.spin_window.value()),
            "retry_interval_seconds": int(self.spin_retry.value()),
            "max_attempts_per_day": int(self.spin_max_attempts.value()),
            "repeat": {"mode": mode, "weekdays": weekdays, "days": days,
                       "months": months, "date": date_text},
        }

    def set_rule_id(self, rule_id: str) -> None:
        self._rule_id = rule_id

    def _update_preview(self, *_args) -> None:
        rule = self.rule()
        try:
            described = scheduler_mod.describe(rule)
        except Exception as exc:  # noqa: BLE001
            described = f"规则描述生成失败：{exc}"
        try:
            next_time = scheduler_mod.next_run(rule)
        except Exception:  # noqa: BLE001
            next_time = None
        next_text = next_time.strftime("%Y-%m-%d %H:%M") if isinstance(next_time, datetime) \
            else "无（例如“仅一次”的日期已过，或未选择星期/日期）"
        self.preview.setText(f"规则预览：{described}\n下次执行：{next_text}")


# --------------------------------------------------------------------------- #
# 计划页
# --------------------------------------------------------------------------- #
class SchedulePage(Page):
    title = "计划"
    subtitle = ("按智能闹钟的方式配置网络切换时间：频率、月份、星期、时间、目标网络、"
                "是否需要登录、补执行窗口。")
    triggers = ("schedules",)

    def build(self) -> None:
        card = self.add_card("计划规则", "下次执行时间由核心层 scheduler 计算。")
        btn_new = W.Button("新建规则", "primary", self.add_rule)
        btn_edit = W.Button("编辑", "ghost", self.edit_rule)
        btn_copy = W.Button("复制", "ghost", self.copy_rule)
        btn_del = W.Button("删除", "danger", self.delete_rule)
        for button in (btn_new, btn_edit, btn_copy, btn_del):
            card.add_head_widget(button)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "时间规则", "目标网络",
                                              "需要登录", "下次执行"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(lambda *_: self.edit_rule())
        card.add(self.table)

        self.hint = W.muted("")
        card.add(self.hint)
        self.refresh()

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        rules = config_ops.schedules(self.ctx.cfg)
        self.table.blockSignals(True)
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            enabled.setCheckState(Qt.Checked if rule.get("enabled") else Qt.Unchecked)
            enabled.setData(Qt.UserRole, rule.get("id"))
            self.table.setItem(row, 0, enabled)

            name = QTableWidgetItem(str(rule.get("name") or rule.get("id")))
            name.setData(Qt.UserRole, rule.get("id"))
            self.table.setItem(row, 1, name)
            try:
                described = scheduler_mod.describe(rule)
            except Exception:  # noqa: BLE001
                described = "—"
            self.table.setItem(row, 2, QTableWidgetItem(described))
            self.table.setItem(row, 3, QTableWidgetItem(str(rule.get("target_network") or "—")))
            self.table.setItem(row, 4, QTableWidgetItem("是" if rule.get("need_login") else "否"))
            try:
                nxt = scheduler_mod.next_run(rule)
            except Exception:  # noqa: BLE001
                nxt = None
            text = nxt.strftime("%Y-%m-%d %H:%M") if nxt else "—"
            if rule.get("enabled") and not nxt:
                text = "无未来触发点"
            self.table.setItem(row, 5, QTableWidgetItem(text))
        self.table.blockSignals(False)
        self.hint.setText(f"共 {len(rules)} 条规则；"
                          f"启用 {sum(1 for r in rules if r.get('enabled'))} 条。"
                          "打勾/取消勾选可直接启用或停用规则。")

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        rule_id = item.data(Qt.UserRole)
        rules = config_ops.schedules(self.ctx.cfg)
        for rule in rules:
            if rule.get("id") == rule_id:
                rule["enabled"] = item.checkState() == Qt.Checked
        self._persist(rules)

    def _persist(self, rules: list) -> None:
        config_ops.save_schedules(self.ctx.cfg, rules)
        self.ctx.save_config()
        self.refresh()
        self.ctx.refresh_status()

    # ------------------------------------------------------------------ #
    def _networks(self) -> list:
        return sorted((self.ctx.cfg.get("networks") or {}).keys())

    def add_rule(self) -> None:
        dialog = ScheduleDialog(self._networks(), {}, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        rules = config_ops.schedules(self.ctx.cfg)
        rules.append(dialog.rule())
        self._persist(rules)

    def _selected_rule(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        rule_id = self.table.item(row, 1).data(Qt.UserRole)
        for rule in config_ops.schedules(self.ctx.cfg):
            if rule.get("id") == rule_id:
                return rule
        return None

    def edit_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            self.warn("编辑规则", "请先选择一条规则。")
            return
        dialog = ScheduleDialog(self._networks(), rule, self)
        dialog.set_rule_id(rule.get("id"))
        if dialog.exec_() != QDialog.Accepted:
            return
        updated = dialog.rule()
        updated["id"] = rule.get("id")
        rules = [updated if r.get("id") == rule.get("id") else r
                 for r in config_ops.schedules(self.ctx.cfg)]
        self._persist(rules)

    def copy_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            self.warn("复制规则", "请先选择一条规则。")
            return
        clone = dict(rule)
        clone["id"] = f"gui-{uuid.uuid4().hex[:8]}"
        clone["name"] = f"{rule.get('name')}（副本）"
        rules = config_ops.schedules(self.ctx.cfg)
        rules.append(clone)
        self._persist(rules)

    def delete_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            self.warn("删除规则", "请先选择一条规则。")
            return
        if not self.confirm("删除规则", f"确认删除规则「{rule.get('name')}」？"):
            return
        rules = [r for r in config_ops.schedules(self.ctx.cfg)
                 if r.get("id") != rule.get("id")]
        self._persist(rules)

    # ------------------------------------------------------------------ #
    def on_status(self, status: dict) -> None:
        rows = status.get("schedules") or []
        if len(rows) == self.table.rowCount():
            for row, rule in enumerate(rows):
                item = self.table.item(row, 5)
                if item is not None:
                    item.setText(str(rule.get("next_run") or "—"))

    def on_show(self) -> None:
        self.refresh()
