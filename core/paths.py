# -*- coding: utf-8 -*-
"""统一路径管理。

区分两类目录：
    RESOURCE_DIR —— 只读资源目录（源码运行=项目目录；冻结运行=打包解包目录 sys._MEIPASS）
    PROJECT_DIR  —— 可写数据目录（源码运行=项目目录；冻结运行=exe 同级，不可写则回退 LOCALAPPDATA）
    HOME_DIR    —— 用户数据目录（%LOCALAPPDATA%\\CampusNet，日志/状态/运行时文件）

可用环境变量 CAMPUSNET_HOME 覆盖用户数据目录（便于测试与便携运行）。
"""
from __future__ import annotations

import os
import shutil
import sys

APP_NAME = "CampusNet"

# 是否处于 PyInstaller 冻结环境（--onefile / --onedir 均为 True）
FROZEN = bool(getattr(sys, "frozen", False))

_THIS_FILE = os.path.abspath(__file__)
DEV_PROJECT_DIR = os.path.dirname(os.path.dirname(_THIS_FILE))       # .../CampusNet
PROJECT_PARENT_DIR = os.path.dirname(DEV_PROJECT_DIR)                # .../output


def is_frozen() -> bool:
    return FROZEN


def _frozen_exe_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.executable or "."))


def _frozen_resource_dir() -> str:
    base = getattr(sys, "_MEIPASS", "")
    if base and os.path.isdir(base):
        return os.path.abspath(base)
    return _frozen_exe_dir()


def _writable(path: str) -> bool:
    """探测目录是否可写（不存在则尝试创建，创建失败即视为不可写）。"""
    probe = os.path.join(path, f".{APP_NAME.lower()}-write-probe")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:  # noqa: BLE001
        return False


def _local_appdata_home() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def _compute_app_root() -> str:
    """可写数据根目录（源码运行 = 项目目录；冻结运行 = exe 同级，不可写则回退）。"""
    env = os.environ.get("CAMPUSNET_HOME", "").strip()
    if env:
        return os.path.abspath(env)
    if FROZEN:
        exe_dir = _frozen_exe_dir()
        if _writable(exe_dir):
            return exe_dir
        return _local_appdata_home()
    return DEV_PROJECT_DIR


# 只读资源目录（随包分发的默认配置 / 插件 / 文档）
RESOURCE_DIR = _frozen_resource_dir() if FROZEN else DEV_PROJECT_DIR
# 可写数据根目录（配置、插件、日志、状态）
APP_ROOT = _compute_app_root()
# 兼容既有引用：PROJECT_DIR 语义为“程序数据目录”
PROJECT_DIR = APP_ROOT


def resource_dir() -> str:
    """只读资源目录。"""
    return _frozen_resource_dir() if FROZEN else DEV_PROJECT_DIR


def app_root() -> str:
    """可写数据根目录。"""
    return APP_ROOT


def get_home_dir() -> str:
    """用户数据目录（每次调用读取，便于测试中通过环境变量切换）。

    源码运行：``CAMPUSNET_HOME`` 或 ``%LOCALAPPDATA%\\CampusNet``（原行为不变）；
    冻结运行：``CAMPUSNET_HOME`` 或可写数据根目录（exe 同级，便携）。
    """
    env = os.environ.get("CAMPUSNET_HOME", "").strip()
    if env:
        return os.path.abspath(env)
    return APP_ROOT if FROZEN else _local_appdata_home()


# ---- 程序数据目录（配置 + 插件；便携模式下即 exe 同级）----
CONFIG_FILE = os.path.join(APP_ROOT, "config.json")
CONFIG_EXAMPLE_FILE = os.path.join(APP_ROOT, "config.example.json")
PLUGINS_DIR = os.path.join(APP_ROOT, "plugins")
TOOLS_DIR = os.path.join(RESOURCE_DIR if FROZEN else APP_ROOT, "tools")


def spec_file() -> str:
    """插件规范文档：优先取数据目录中的副本，其次取打包资源。"""
    for candidate in (os.path.join(APP_ROOT, "PLUGIN_SPEC.md"),
                      os.path.join(RESOURCE_DIR, "PLUGIN_SPEC.md")):
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(APP_ROOT, "PLUGIN_SPEC.md")


SPEC_FILE = spec_file()

# 上一阶段（单体程序）遗留的配置，用于一次性迁移。
# 冻结运行时只认数据目录内的文件（避免扫描 exe 所在盘符根目录造成误迁移）。
LEGACY_CONFIG_CANDIDATES = (
    [os.path.join(APP_ROOT, "config.legacy.json")]
    if FROZEN else
    [os.path.join(PROJECT_PARENT_DIR, "config.json"),
     os.path.join(APP_ROOT, "config.legacy.json")]
)


# ---- 用户数据目录（可写）----
def home_dir() -> str:
    return get_home_dir()


def logs_dir() -> str:
    return os.path.join(get_home_dir(), "logs")


def runtime_dir() -> str:
    return os.path.join(get_home_dir(), "runtime")


def popup_dir() -> str:
    return os.path.join(runtime_dir(), "popup")


def state_file() -> str:
    return os.path.join(get_home_dir(), "state.json")


def lock_file() -> str:
    return os.path.join(runtime_dir(), "action.lock")


def temp_dir() -> str:
    """程序自用临时目录（自测夹具、一次性导出等，位于用户数据目录下）。"""
    return os.path.join(get_home_dir(), "temp")


def log_file() -> str:
    return os.path.join(logs_dir(), "campusnet.log")


def selftest_result_file() -> str:
    """--selftest 的结构化结果文件（无界面验证用）。"""
    return os.path.join(logs_dir(), "selftest-result.json")


ALL_DIRS = (logs_dir, runtime_dir, popup_dir, temp_dir)


def ensure_dirs() -> None:
    """确保所有可写目录存在。"""
    for maker in ALL_DIRS:
        try:
            os.makedirs(maker(), exist_ok=True)
        except OSError:
            pass


def find_legacy_config() -> str:
    """返回存在的遗留配置文件路径，找不到返回空串。"""
    for p in LEGACY_CONFIG_CANDIDATES:
        if os.path.isfile(p):
            return p
    return ""


# --------------------------------------------------------------------------- #
# 首次运行：释放随程序分发的默认配置与插件
# --------------------------------------------------------------------------- #
def _copy_file(src: str, dst: str) -> bool:
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def bootstrap() -> list:
    """首次运行准备（幂等）：

    1. 建立可写目录（logs / runtime / popup / temp）；
    2. 若 ``config.json`` 缺失，从打包资源释放默认配置；
    3. 补齐 ``plugins/`` 中缺失的随包插件文件（已存在的文件不覆盖，用户改动不丢）；
    4. 补齐 ``PLUGIN_SPEC.md``。

    返回本次新增的文件路径列表（无动作时为空）。源码运行时只读资源目录与数据目录
    相同，本函数直接返回空列表，不改变开发态行为。
    """
    notes = []
    ensure_dirs()

    res = resource_dir()
    if os.path.abspath(res) == os.path.abspath(APP_ROOT):
        return notes

    if not os.path.isfile(CONFIG_FILE):
        src = os.path.join(res, "config.json")
        if os.path.isfile(src) and _copy_file(src, CONFIG_FILE):
            notes.append(CONFIG_FILE)

    src_plugins = os.path.join(res, "plugins")
    if os.path.isdir(src_plugins) and os.path.abspath(src_plugins) != os.path.abspath(PLUGINS_DIR):
        for root, _dirs, files in os.walk(src_plugins):
            rel = os.path.relpath(root, src_plugins)
            target_dir = PLUGINS_DIR if rel == "." else os.path.join(PLUGINS_DIR, rel)
            for name in files:
                dst = os.path.join(target_dir, name)
                if not os.path.isfile(dst) and _copy_file(os.path.join(root, name), dst):
                    notes.append(dst)

    spec = os.path.join(APP_ROOT, "PLUGIN_SPEC.md")
    if not os.path.isfile(spec):
        src = os.path.join(res, "PLUGIN_SPEC.md")
        if os.path.isfile(src) and _copy_file(src, spec):
            notes.append(spec)

    return notes
