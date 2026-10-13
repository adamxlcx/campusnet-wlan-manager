# -*- coding: utf-8 -*-
"""CampusNet GUI 层（PyQt5）。

本包只做「界面 + 与核心层对接」，所有业务逻辑仍然在 `core/` 中：
    * `core.service.Service`  后台主循环（调度 / 连通性巡检 / 下载保护）
    * `core.wlan` / `core.portal` / `core.plugins` / `core.scheduler` 等能力模块

对外入口是项目根目录的 `app.py`。

说明：本包把项目根目录加入 `sys.path`，因此包内可以统一使用 `from core import ...`
的绝对导入，无论以脚本方式还是以模块方式启动。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

__all__ = ["__version__"]
__version__ = "2.0.0"
