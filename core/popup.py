# -*- coding: utf-8 -*-
"""弹窗模块（行为与上一阶段实现保持一致）。

    * 独立子进程渲染，避免守护进程被 tkinter 阻塞
    * 无人应答时按“拒绝”处理（保持断开），与旧实现一致
    * 支持隐藏的自测参数 --auto-answer {allow|deny}，便于自动化验证
    * tkinter 不可用时降级为系统 MessageBox
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid

from . import paths, sysutil
from .logging_setup import get_logger

DEFAULT_MESSAGE = "检测到疑似大流量下载，可能正在消耗手机热点流量。"


def _build_message(info: dict | None = None, message: str = "") -> str:
    if message:
        return message
    info = info or {}
    lines = [DEFAULT_MESSAGE, ""]
    if info.get("network"):
        lines.append(f"当前网络：{info['network']}")
    if info.get("human_speed"):
        lines.append(f"当前下行速度：{info['human_speed']}")
    if info.get("human_total"):
        lines.append(f"本会话累计下行：{info['human_total']}")
    if info.get("threshold"):
        lines.append(f"触发规则：{info['threshold']}")
    procs = info.get("processes") or []
    if procs:
        names = "、".join(f"{p.get('name')}({p.get('connections')}连接)" for p in procs[:5])
        lines.append(f"疑似进程：{names}")
    lines.append("")
    lines.append("允许 = 继续使用；切断 = 立即断开 WLAN 并保持断开。")
    return "\n".join(lines)


def show_popup_dialog(title: str, message: str, allow_text: str = "允许继续",
                      deny_text: str = "立即切断", timeout: int = 0,
                      auto_answer: str | None = None,
                      auto_close_seconds: float = 0,
                      result_path: str = "") -> bool:
    """在当前进程显示弹窗（阻塞）。返回 True=用户允许，False=拒绝/超时。

    与旧实现一致：无人点击（关闭窗口/超时）一律按拒绝处理。
    """
    result = False
    try:
        import tkinter as tk
        from tkinter import messagebox  # noqa: F401  保持与旧实现一致的导入行为

        root = tk.Tk()
        root.title(title or "CampusNet 提醒")
        root.attributes("-topmost", True)
        root.resizable(False, False)

        frame = tk.Frame(root, padx=18, pady=14)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=message, justify="left", anchor="w",
                 wraplength=460).pack(fill="x")
        tk.Label(frame, text="", height=1).pack()

        state = {"answer": None}

        def answer(value: bool):
            state["answer"] = value
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass

        buttons = tk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))
        tk.Button(buttons, text=allow_text, width=14, command=lambda: answer(True)).pack(side="right")
        tk.Button(buttons, text=deny_text, width=14, command=lambda: answer(False)).pack(
            side="right", padx=(0, 10))

        root.protocol("WM_DELETE_WINDOW", lambda: answer(False))
        root.update_idletasks()
        try:
            w, h = root.winfo_width(), root.winfo_height()
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        except Exception:  # noqa: BLE001
            pass

        if auto_answer in ("allow", "deny"):
            root.after(600, lambda: answer(auto_answer == "allow"))
        elif auto_close_seconds and auto_close_seconds > 0:
            root.after(int(auto_close_seconds * 1000), lambda: answer(False))
        elif timeout and timeout > 0:
            root.after(int(timeout * 1000), lambda: answer(False))

        root.mainloop()
        result = bool(state["answer"])
    except Exception as e:  # noqa: BLE001
        get_logger().warning("tkinter 弹窗不可用（%s），降级为系统 MessageBox", e)
        result = _fallback_messagebox(title, message)

    if result_path:
        try:
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump({"allow": result}, f)
        except Exception as e:  # noqa: BLE001
            get_logger().warning("弹窗结果写入失败：%s", e)
    return result


def _fallback_messagebox(title: str, message: str) -> bool:
    try:
        import ctypes
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        MB_TOPMOST = 0x40000
        ret = ctypes.windll.user32.MessageBoxW(
            None, message, title or "CampusNet 提醒",
            MB_YESNO | MB_ICONWARNING | MB_TOPMOST)
        return ret == 6  # IDYES
    except Exception as e:  # noqa: BLE001
        get_logger().error("无法显示任何弹窗（%s），按拒绝处理", e)
        return False


def popup_in_subprocess(info: dict | None = None, title: str = "", message: str = "",
                        timeout: int = 0, auto_answer: str | None = None,
                        allow_text: str = "允许继续", deny_text: str = "立即切断") -> bool:
    """在独立子进程中弹窗（守护进程不被阻塞）。返回 True=允许。"""
    title = title or "CampusNet 提醒"
    message = _build_message(info, message)
    paths.ensure_dirs()
    result_path = os.path.join(paths.popup_dir(), f"popup_{uuid.uuid4().hex}.json")

    # 冻结运行时用 exe 自身作为子进程入口（app.py 内部把 `_popup` 转交 CLI）；
    # 源码运行时沿用 pythonw + cli.py，行为不变。
    if paths.is_frozen():
        cmd = [sys.executable, "_popup"]
        cwd = paths.app_root()
    else:
        cmd = [sysutil.pythonw_path(), os.path.join(paths.PROJECT_DIR, "cli.py"), "_popup"]
        cwd = paths.PROJECT_DIR
    cmd += ["--title", title, "--message", message,
            "--allow-text", allow_text, "--deny-text", deny_text,
            "--timeout", str(int(timeout or 0)), "--result-file", result_path]
    if auto_answer in ("allow", "deny"):
        cmd += ["--auto-answer", auto_answer]

    try:
        proc = subprocess.Popen(cmd, cwd=cwd,
                                creationflags=sysutil.CREATE_NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        get_logger().error("弹窗子进程启动失败：%s，按拒绝处理", e)
        return False

    try:
        proc.wait(timeout=(timeout + 300) if timeout else None)
    except subprocess.TimeoutExpired:
        get_logger().warning("弹窗超时未响应，按拒绝处理")
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass

    allow = False
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            allow = bool(json.load(f).get("allow"))
    except Exception:  # noqa: BLE001
        allow = False
    try:
        os.remove(result_path)
    except OSError:
        pass
    get_logger().info("弹窗结果：%s", "允许" if allow else "拒绝")
    return allow
