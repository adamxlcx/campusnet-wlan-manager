# -*- coding: utf-8 -*-
"""白色（明）/ 黑色（暗）两套配色，以及统一的 Qt 样式表。

主题名会持久化到 `config.json` 的 `app.ui.theme`，重启后保持。
"""
from __future__ import annotations

from string import Template

THEMES = ("light", "dark")
THEME_LABELS = {"light": "白色（明）", "dark": "黑色（暗）"}

LIGHT = {
    "name": "light",
    "label": THEME_LABELS["light"],
    "bg": "#f4f6f9",
    "panel": "#ffffff",
    "panel_alt": "#eef1f6",
    "nav_bg": "#e9edf3",
    "border": "#d5dae2",
    "text": "#1f2329",
    "text_dim": "#7a828c",
    "accent": "#2f6fed",
    "accent_hover": "#2a63d8",
    "accent_text": "#ffffff",
    "hover": "#dde4ee",
    "sel_bg": "#dbe6ff",
    "input_bg": "#ffffff",
    "input_border": "#c9d0da",
    "scroll": "#c2c9d4",
    "ok": "#17a34a",
    "bad": "#e04345",
    "neutral": "#98a1ab",
    "tooltip_bg": "#2b3038",
    "tooltip_text": "#ffffff",
}

DARK = {
    "name": "dark",
    "label": THEME_LABELS["dark"],
    "bg": "#1b1e23",
    "panel": "#23272e",
    "panel_alt": "#2a2f37",
    "nav_bg": "#20242a",
    "border": "#383e47",
    "text": "#e7eaee",
    "text_dim": "#9aa3ad",
    "accent": "#4c8dff",
    "accent_hover": "#3f7ae8",
    "accent_text": "#0d1117",
    "hover": "#313741",
    "sel_bg": "#31405c",
    "input_bg": "#1e2228",
    "input_border": "#3b424c",
    "scroll": "#454c57",
    "ok": "#2ecc71",
    "bad": "#ff5f57",
    "neutral": "#8b939c",
    "tooltip_bg": "#f0f2f5",
    "tooltip_text": "#1b1e23",
}

# 托盘 / 状态灯配色（绿=连通，红=不通，灰=检测关闭或未知）
STATE_COLORS = {"green": LIGHT["ok"], "red": LIGHT["bad"], "gray": LIGHT["neutral"]}

TOKENS = {"light": LIGHT, "dark": DARK}


def normalize(theme: str) -> str:
    """把任意输入规范化为 light / dark。"""
    theme = str(theme or "").strip().lower()
    return theme if theme in THEMES else "light"


def colors(theme: str) -> dict:
    return TOKENS[normalize(theme)]


def state_color(theme: str, state: str) -> str:
    """状态色（绿/红/灰）随主题微调。"""
    palette = colors(theme)
    state = str(state or "gray").lower()
    if state in ("green", "ok", "online"):
        return palette["ok"]
    if state in ("red", "bad", "offline"):
        return palette["bad"]
    return palette["neutral"]


_QSS = Template("""
* { outline: 0; }
QWidget {
    background-color: $bg;
    color: $text;
    font-family: "Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background-color: $bg; }
QLabel { background: transparent; }
QLabel#PageTitle { font-size: 20px; font-weight: 600; }
QLabel#PageSubtitle { color: $text_dim; }
QLabel#SectionTitle { font-size: 14px; font-weight: 600; }
QLabel#Hint { color: $text_dim; }
QLabel#Dim { color: $text_dim; }
QLabel#Value { font-weight: 600; }
QLabel#StateChip { padding: 2px 10px; border-radius: 9px; font-weight: 600; }

/* ---- GUI 分页通用 ---- */
QWidget#pageHeader { background: transparent; }
QLabel#pageTitle { font-size: 20px; font-weight: 600; }
QLabel#pageSubtitle { color: $text_dim; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; }
QLabel#muted { color: $text_dim; }
QLabel#metricValue { font-size: 18px; font-weight: 600; }
QLabel#metricValue[state="green"] { color: $ok; }
QLabel#metricValue[state="red"] { color: $bad; }
QLabel#metricValue[state="gray"] { color: $text_dim; }
QFrame#hline, QFrame#Divider {
    background-color: $border; border: none; max-height: 1px; min-height: 1px;
}
QPushButton[kind="primary"], QPushButton#Primary {
    background-color: $accent; color: $accent_text; border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[kind="primary"]:hover { background-color: $accent_hover; }
QPushButton[kind="danger"], QPushButton#Danger { color: $bad; }
QPushButton[kind="ghost"] { background-color: $panel_alt; }
QPushButton[kind="ghost"]:hover { background-color: $hover; }
QToolButton { background: transparent; border: none; color: $text; padding: 4px; }
QToolButton:hover { background-color: $hover; border-radius: 6px; }
QLabel#chip {
    background-color: $panel_alt; border: 1px solid $border; border-radius: 9px;
    padding: 2px 8px;
}

QFrame#Card, QFrame#CardPlain {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 10px;
}
QFrame#CardPlain { background-color: $panel_alt; }
QFrame#Divider { background-color: $border; max-height: 1px; border: none; }

QGroupBox {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: $text;
}

QListWidget {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:selected { background-color: $sel_bg; color: $text; }
QListWidget#NavList {
    background-color: $nav_bg;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#NavList::item {
    padding: 10px 12px;
    margin: 2px 0;
    border-radius: 8px;
    color: $text;
}
QListWidget#NavList::item:hover { background-color: $hover; }
QListWidget#NavList::item:selected { background-color: $accent; color: $accent_text; }

QPushButton {
    background-color: $panel_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background-color: $hover; }
QPushButton:pressed { background-color: $sel_bg; }
QPushButton:disabled { color: $text_dim; border-color: $border; }
QPushButton#Primary {
    background-color: $accent;
    color: $accent_text;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton#Primary:hover { background-color: $accent_hover; }
QPushButton#Danger { color: $bad; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QDateEdit, QTimeEdit, QDateTimeEdit {
    background-color: $input_bg;
    color: $text;
    border: 1px solid $input_border;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: $accent;
    selection-color: $accent_text;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $text_dim; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: $panel;
    color: $text;
    border: 1px solid $border;
    selection-background-color: $sel_bg;
    selection-color: $text;
}
QPlainTextEdit#LogView, QPlainTextEdit#CodeView {
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; }
QCheckBox::indicator:unchecked {
    border: 1px solid $input_border; background: $input_bg; border-radius: 3px;
}
QCheckBox::indicator:checked {
    border: 1px solid $accent; background: $accent; border-radius: 3px;
}
QRadioButton::indicator:unchecked {
    border: 1px solid $input_border; background: $input_bg; border-radius: 8px;
}
QRadioButton::indicator:checked {
    border: 4px solid $accent; background: $panel; border-radius: 8px;
}

QTableWidget, QTableView {
    background-color: $panel;
    alternate-background-color: $panel_alt;
    gridline-color: $border;
    border: 1px solid $border;
    border-radius: 8px;
    selection-background-color: $sel_bg;
    selection-color: $text;
}
QHeaderView::section {
    background-color: $panel_alt;
    color: $text;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px;
    font-weight: 600;
}
QTableCornerButton::section { background-color: $panel_alt; border: none; }

QTabWidget::pane { border: 1px solid $border; border-radius: 8px; background: $panel; }
QTabBar::tab {
    background: $panel_alt;
    border: 1px solid $border;
    padding: 6px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: $panel; color: $text; }

QStatusBar { background: $panel_alt; border-top: 1px solid $border; color: $text_dim; }
QStatusBar::item { border: none; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QMenu { background-color: $panel; color: $text; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background-color: $accent; color: $accent_text; }
QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }

QToolTip { background-color: $tooltip_bg; color: $tooltip_text; border: none; padding: 4px 6px; }

QProgressBar {
    border: 1px solid $border; border-radius: 6px; background: $panel_alt;
    text-align: center; color: $text;
}
QProgressBar::chunk { background: $accent; border-radius: 5px; }
""")


def stylesheet(theme: str) -> str:
    """返回该主题的完整 QSS。"""
    return _QSS.substitute(colors(theme))


def accent(theme: str) -> str:
    return colors(theme)["accent"]


def tray_state(status: dict | None) -> str:
    """从核心层状态快照推导托盘配色：

    * 连通性检测关闭（health.enabled = False）→ gray（中性灰，界面另行说明）
    * 检测开启：online = True → green；False → red；None（未知）→ gray
    """
    status = status or {}
    health = status.get("health") or {}
    if not health.get("enabled"):
        return "gray"
    online = health.get("online")
    if online is True:
        return "green"
    if online is False:
        return "red"
    return "gray"


def tray_state_text(state: str) -> str:
    return {"green": "连通（绿）", "red": "不通（红）",
            "gray": "检测关闭 / 未知（灰）"}.get(str(state), str(state))


__all__ = ["THEMES", "THEME_LABELS", "LIGHT", "DARK", "STATE_COLORS", "normalize",
           "colors", "state_color", "stylesheet", "accent", "tray_state",
           "tray_state_text"]
