# -*- coding: utf-8 -*-
"""可复用的小控件：卡片、表单行、单位下拉、指标标签、状态圆点等。"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import icons as icons_mod


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    line.setObjectName("hline")
    return line


def int_spin(minimum: int, maximum: int, value: int, suffix: str = "",
             step: int = 1) -> QSpinBox:
    """整数输入框（带单位后缀）。"""
    box = QSpinBox()
    box.setRange(int(minimum), int(maximum))
    box.setValue(int(value if value is not None else minimum))
    box.setSingleStep(int(step))
    if suffix:
        box.setSuffix(suffix)
    return box


def text_edit(text: str = "", placeholder: str = "") -> QLineEdit:
    """单行文本输入框。"""
    edit = QLineEdit(str(text or ""))
    if placeholder:
        edit.setPlaceholderText(placeholder)
    return edit


def form_grid(pairs: list) -> FormGrid:
    """由 [(label, widget), ...] 快速构造两列表单。"""
    form = FormGrid()
    for label, widget in pairs:
        form.add_row(label, widget)
    return form


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardTitle")
    return label


class Card(QFrame):
    """带标题的卡片容器，内容加到 `.body` 布局里。"""

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)
        if title:
            head = QHBoxLayout()
            head.setSpacing(8)
            head.addWidget(title_label(title))
            head.addStretch(1)
            self.head = head
            outer.addLayout(head)
        else:
            self.head = QHBoxLayout()
        if subtitle:
            outer.addWidget(muted(subtitle))
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def add_head_widget(self, widget: QWidget) -> QWidget:
        self.head.addWidget(widget)
        return widget


class FormGrid(QWidget):
    """两列表单：左侧标签、右侧控件，可附灰色提示。"""

    def __init__(self, parent=None, label_width: int = 108):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(1, 1)
        self._row = 0
        self._label_width = label_width

    def add_row(self, label: str, widget: QWidget, hint: str = "") -> QWidget:
        tag = QLabel(label)
        tag.setMinimumWidth(self._label_width)
        tag.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.grid.addWidget(tag, self._row, 0)
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(widget)
        if hint:
            lay.addWidget(muted(hint))
        self.grid.addWidget(holder, self._row, 1)
        self._row += 1
        return widget

    def add_widget_row(self, widget: QWidget, column_span: int = 2) -> QWidget:
        self.grid.addWidget(widget, self._row, 0, 1, column_span)
        self._row += 1
        return widget


class UnitSpinBox(QWidget):
    """数值 + 单位下拉（流量阈值 KB/MB/GB、网速阈值 KB/s - MB/s 等）。"""

    valueChanged = pyqtSignal(float, str)

    def __init__(self, units: list, value: float = 0.0, unit: str = "",
                 decimals: int = 2, maximum: float = 1_000_000.0,
                 minimum: float = 0.0, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if decimals:
            self.spin = QDoubleSpinBox()
            self.spin.setDecimals(decimals)
        else:
            self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(float(value or 0))
        self.combo = QComboBox()
        for item in units:
            if isinstance(item, (tuple, list)):
                self.combo.addItem(str(item[0]), item[1])
            else:
                self.combo.addItem(str(item), str(item))
        if unit:
            index = self.combo.findText(str(unit))
            if index >= 0:
                self.combo.setCurrentIndex(index)
        lay.addWidget(self.spin, 1)
        lay.addWidget(self.combo)
        if hasattr(self.spin, "valueChanged"):
            self.spin.valueChanged.connect(self._emit)
        self.combo.currentIndexChanged.connect(self._emit)

    def _emit(self, *_args) -> None:
        self.valueChanged.emit(self.value(), self.unit())

    def value(self) -> float:
        return float(self.spin.value())

    def unit(self) -> str:
        return str(self.combo.currentData() or self.combo.currentText())

    def set_value(self, value: float, unit: str = "") -> None:
        self.spin.setValue(float(value or 0))
        if unit:
            index = self.combo.findText(str(unit))
            if index < 0:
                index = self.combo.findData(str(unit))
            if index >= 0:
                self.combo.setCurrentIndex(index)


class StatusDot(QLabel):
    """状态圆点（托盘配色同款）。"""

    def __init__(self, state: str = "gray", size: int = 12, parent=None):
        super().__init__(parent)
        self._size = size
        self.set_state(state)

    def set_state(self, state: str, theme: str = "light") -> None:
        self.setPixmap(icons_mod.dot_pixmap(self._size, icons_mod.state_color(state, theme)))
        self.setToolTip({"green": "网络连通", "red": "网络不通",
                         "gray": "检测关闭 / 状态未知"}.get(state, state))


class Button(QPushButton):
    """统一按钮：kind = primary / ghost / danger。"""

    def __init__(self, text: str, kind: str = "ghost", on_click=None, parent=None):
        super().__init__(text, parent)
        self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)
        if callable(on_click):
            self.clicked.connect(on_click)


class CheckRow(QCheckBox):
    def __init__(self, text: str, checked: bool = False, on_toggle=None, parent=None):
        super().__init__(text, parent)
        self.setChecked(bool(checked))
        if callable(on_toggle):
            self.toggled.connect(on_toggle)


class Metric(QWidget):
    """指标块：上方大号数值，下方灰色说明。"""

    def __init__(self, caption: str, value: str = "—", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.caption_label = muted(caption)
        lay.addWidget(self.value_label)
        lay.addWidget(self.caption_label)

    def set_value(self, text: str, state: str = "") -> None:
        self.value_label.setText(str(text))
        self.value_label.setProperty("state", state)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)


def metric_row(items: list) -> QWidget:
    """一行多个指标块：items = [(caption, value), ...]"""
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(18)
    for caption, value in items:
        lay.addWidget(Metric(caption, value))
    lay.addStretch(1)
    return holder


def grid_of(pairs: list, columns: int = 2) -> QWidget:
    """[(k, v), ...] 的键值网格展示。"""
    holder = QWidget()
    grid = QGridLayout(holder)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(6)
    for index, (key, value) in enumerate(pairs):
        row, col = divmod(index, columns)
        key_label = QLabel(f"{key}")
        key_label.setObjectName("muted")
        val_label = QLabel(str(value))
        val_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(key_label, row, col * 2)
        grid.addWidget(val_label, row, col * 2 + 1)
    grid.setColumnStretch(columns * 2 - 1, 1)
    return holder


__all__ = ["Card", "FormGrid", "UnitSpinBox", "StatusDot", "Button", "CheckRow",
           "Metric", "metric_row", "grid_of", "hline", "muted", "title_label",
           "int_spin", "text_edit", "form_grid"]
