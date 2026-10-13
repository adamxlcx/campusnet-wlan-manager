# -*- coding: utf-8 -*-
"""开机自启动（注册表 Run 项）与 Windows 计划任务（schtasks）的注册 / 注销。

两个开关彼此独立，互不依赖：

* **开机自启动**：写 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`，
  普通用户即可，登录后随系统启动（默认带 `--minimized` 参数，直接进托盘）。
* **Windows 计划任务**：用 `schtasks /Create /SC ONLOGON` 注册。
  普通用户可以创建“以当前用户身份运行”的登录任务；若要求“最高权限运行”
  （`/RL HIGHEST`）或以系统账户运行，必须以管理员身份启动本程序。

**降级方案**（当计划任务不可用时）：
1. 改用上面的「开机自启动」开关（HKCU Run，无需管理员）；
2. 以管理员身份重新运行本程序后再试；
3. 界面会把完整的 ``schtasks`` 命令行显示出来，可手动在「任务计划程序」中创建。
"""
from __future__ import annotations

import os
import sys

from core import paths, sysutil

IS_WINDOWS = os.name == "nt"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
TASK_FOLDER = ""  # 任务名不加文件夹前缀，普通用户可直接创建


# --------------------------------------------------------------------------- #
# 名称 / 命令行
# --------------------------------------------------------------------------- #
def startup_cfg(cfg: dict | None) -> dict:
    return dict(((cfg or {}).get("app") or {}).get("startup") or {})


def name_prefix(cfg: dict | None) -> str:
    return str(startup_cfg(cfg).get("task_prefix") or "CampusNet").strip() or "CampusNet"


def autostart_value_name(cfg: dict | None) -> str:
    return name_prefix(cfg)


def task_name(cfg: dict | None) -> str:
    return f"{TASK_FOLDER}{name_prefix(cfg)}GUI"


def app_entry() -> str:
    """程序入口脚本路径。冻结运行时为 exe 自身，返回空串。"""
    if paths.is_frozen():
        return ""
    return os.path.join(paths.PROJECT_DIR, "app.py")


def launcher() -> str:
    """启动器：源码运行=pythonw.exe；冻结运行=exe 自身。"""
    if paths.is_frozen():
        return sys.executable
    return sysutil.pythonw_path()


def launch_command(minimized: bool = True) -> str:
    """程序启动命令行（带引号，可直接用于 Run 项 / schtasks）。"""
    arg = " --minimized" if minimized else ""
    entry = app_entry()
    if entry:
        return f'"{launcher()}" "{entry}"{arg}'
    return f'"{launcher()}"{arg}'


def is_admin() -> bool:
    return bool(sysutil.is_admin())


# --------------------------------------------------------------------------- #
# 开机自启动（HKCU Run）
# --------------------------------------------------------------------------- #
def get_autostart(cfg: dict | None = None) -> dict:
    name = autostart_value_name(cfg)
    if not IS_WINDOWS:
        return {"ok": False, "enabled": False, "name": name, "command": "",
                "message": "当前系统不支持注册表自启动（仅 Windows）"}
    try:
        import winreg  # noqa: PLC0415
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                value = ""
        return {"ok": True, "enabled": bool(str(value).strip()), "name": name,
                "command": str(value or ""), "message": ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "enabled": False, "name": name, "command": "",
                "message": f"读取注册表失败：{exc}"}


def set_autostart(cfg: dict | None = None, enabled: bool = True) -> dict:
    """注册 / 注销开机自启动。返回 {ok, enabled, command, message}。"""
    name = autostart_value_name(cfg)
    command = launch_command()
    if not IS_WINDOWS:
        return {"ok": False, "enabled": False, "command": command,
                "message": "当前系统不支持注册表自启动（仅 Windows）"}
    try:
        import winreg  # noqa: PLC0415
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        return {"ok": True, "enabled": bool(enabled), "command": command,
                "message": f"已{'启用' if enabled else '关闭'}开机自启动（{name}）"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "enabled": False, "command": command,
                "message": f"写入注册表失败：{exc}"}


# --------------------------------------------------------------------------- #
# Windows 计划任务（schtasks）
# --------------------------------------------------------------------------- #
def _schtasks(args: list, timeout: float = 30) -> tuple:
    return sysutil.run(["schtasks"] + [str(a) for a in args], timeout=timeout)


def query_task(cfg: dict | None = None) -> dict:
    """只读查询计划任务是否已注册。"""
    name = task_name(cfg)
    if not IS_WINDOWS:
        return {"ok": False, "exists": False, "name": name, "detail": "",
                "message": "当前系统不支持 schtasks（仅 Windows）"}
    rc, out, err = _schtasks(["/Query", "/TN", name])
    text = (out or err or "").strip()
    exists = (rc == 0)
    return {"ok": True, "exists": exists, "name": name, "detail": text,
            "rc": rc, "message": "" if exists else "未注册"}


def create_task(cfg: dict | None = None, highest: bool = True,
                minimized: bool = True) -> dict:
    """注册登录时触发的计划任务。

    先尝试以最高权限（/RL HIGHEST，需要管理员）注册，失败后自动降级为普通权限。
    """
    name = task_name(cfg)
    command = launch_command(minimized=minimized)
    base = ["/Create", "/TN", name, "/TR", command, "/SC", "ONLOGON", "/F"]
    if not IS_WINDOWS:
        return {"ok": False, "name": name, "command": command, "mode": "",
                "message": "当前系统不支持 schtasks（仅 Windows）"}

    attempts = []
    if highest and is_admin():
        attempts.append(("highest", base + ["/RL", "HIGHEST"]))
    attempts.append(("limited", list(base)))

    last = ""
    for mode, args in attempts:
        rc, out, err = _schtasks(args)
        detail = (out or err or "").strip()
        if rc == 0 and query_task(cfg).get("exists"):
            return {"ok": True, "name": name, "command": command, "mode": mode,
                    "message": f"已注册计划任务（{'最高权限' if mode == 'highest' else '当前用户权限'}，"
                               f"登录时触发）"}
        last = detail or f"schtasks 返回码 {rc}"
    hint = "；如仍失败，请以管理员身份运行本程序，或改用「开机自启动」开关"
    return {"ok": False, "name": name, "command": command, "mode": "",
            "message": f"注册计划任务失败：{last}{hint}"}


def delete_task(cfg: dict | None = None) -> dict:
    name = task_name(cfg)
    if not IS_WINDOWS:
        return {"ok": False, "name": name, "message": "当前系统不支持 schtasks（仅 Windows）"}
    rc, out, err = _schtasks(["/Delete", "/TN", name, "/F"])
    detail = (out or err or "").strip()
    if rc == 0:
        return {"ok": True, "name": name, "message": f"已注销计划任务（{name}）"}
    return {"ok": False, "name": name, "message": f"注销计划任务失败：{detail or rc}"}


def task_command_preview(cfg: dict | None = None) -> str:
    """给界面展示的手动创建命令（降级方案用）。"""
    name = task_name(cfg)
    return (f'schtasks /Create /TN "{name}" /TR "{launch_command()}" '
            f'/SC ONLOGON /F')


def status(cfg: dict | None = None) -> dict:
    """汇总两个开关的真实状态（只读）。"""
    auto = get_autostart(cfg)
    task = query_task(cfg)
    return {
        "admin": is_admin(),
        "autostart": auto,
        "task": task,
        "task_command": task_command_preview(cfg),
        "launcher": launcher(),
        "app_entry": app_entry(),
    }


__all__ = [
    "get_autostart", "set_autostart", "query_task", "create_task", "delete_task",
    "status", "task_name", "launch_command", "task_command_preview", "is_admin",
    "app_entry", "launcher",
]
