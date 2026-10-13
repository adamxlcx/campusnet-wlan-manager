# -*- coding: utf-8 -*-
"""图标：全部用 QPainter 现画，不依赖任何外部图片资源。

* `tray_icon(state)`  → 托盘图标（绿=连通 / 红=不通 / 灰=检测关闭或未知）
* `app_icon()`        → 主窗口 / 任务栏图标
* `state_color(state)`→ 状态色（CSS 颜色字符串）
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap

from . import theme as theme_mod

_SIZES = (16, 20, 24, 32, 48, 64, 128)


def state_color(state: str, theme: str = "light") -> str:
    return theme_mod.state_color(theme, state)


def _circle_pixmap(size: int, fill: str, ring_alpha: int = 60) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    margin = max(1.0, size * 0.07)
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    color = QColor(fill)
    # 外圈加深，模拟指示灯玻璃感
    edge = QColor(color)
    edge = edge.darker(135)
    painter.setPen(QPen(edge, max(1.0, size * 0.06)))
    painter.setBrush(QBrush(color))
    painter.drawEllipse(rect)
    # 高光
    glow = QColor(255, 255, 255, ring_alpha)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(QRectF(rect.left() + rect.width() * 0.22,
                               rect.top() + rect.height() * 0.18,
                               rect.width() * 0.34, rect.height() * 0.28))
    painter.end()
    return pm


def tray_icon(state: str = "gray", theme: str = "light") -> QIcon:
    """按网络状态生成托盘图标。"""
    color = state_color(state, theme)
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(_circle_pixmap(size, color))
    return icon


def app_icon(accent: str = "#2f6fed") -> QIcon:
    """程序图标：圆角方块 + 字母 C。"""
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(accent)))
        painter.drawRoundedRect(rect, size * 0.24, size * 0.24)
        painter.setPen(QPen(QColor("#ffffff")))
        font = QFont("Microsoft YaHei UI")
        font.setBold(True)
        font.setPixelSize(int(size * 0.62))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, "C")
        painter.end()
        icon.addPixmap(pm)
    return icon


def pulse_pixmap(size: int = 12, color: str = "#17a34a") -> QPixmap:
    """界面里的小圆点（状态灯）。"""
    return _circle_pixmap(size, color, ring_alpha=90)


def dot_pixmap(size: int = 12, color: str = "#98a1ab") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(color)))
    painter.drawEllipse(QRectF(0, 0, size, size))
    painter.end()
    return pm


__all__ = ["tray_icon", "app_icon", "state_color", "dot_pixmap", "pulse_pixmap", "QPointF"]
