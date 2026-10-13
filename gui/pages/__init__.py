# -*- coding: utf-8 -*-
"""各分页导出：主窗口与托盘菜单都从这里取页面元信息。"""
from __future__ import annotations

from .health import HealthPage
from .overview import OverviewPage
from .plugins import PluginPage
from .schedule import SchedulePage
from .settings import SettingsPage
from .traffic import TrafficPage
from .wlan import WlanPage

# (key, 标题, 图标字符, 页面类) —— 顺序即左侧导航顺序
PAGES = [
    ("overview", "概览", "◎", OverviewPage),
    ("wlan", "WLAN", "≋", WlanPage),
    ("schedule", "计划", "⏱", SchedulePage),
    ("plugins", "插件", "⚙", PluginPage),
    ("health", "网络检测", "♥", HealthPage),
    ("traffic", "流量", "⇅", TrafficPage),
    ("settings", "设置", "☰", SettingsPage),
]


def page_title(key: str) -> str:
    for item in PAGES:
        if item[0] == key:
            return item[1]
    return key


__all__ = ["PAGES", "page_title", "OverviewPage", "WlanPage", "SchedulePage",
           "PluginPage", "HealthPage", "TrafficPage", "SettingsPage"]
