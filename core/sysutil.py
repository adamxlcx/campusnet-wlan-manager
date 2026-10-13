# -*- coding: utf-8 -*-
"""系统级工具：命令执行、编码解码、权限判断、单位格式化。

说明：本模块是 wlan / health / portal 等模块的公共底座，不含业务逻辑。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def decode(raw) -> str:
    """解码系统命令输出。

    中文 Windows 的 netsh / ping 输出为 GBK 码页，故 Windows 下优先按 GBK 解码，
    否则中文状态下 `netsh wlan show interfaces` 的状态字段会解出乱码。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    encodings = ("gbk", "utf-8", "latin-1") if IS_WINDOWS else ("utf-8", "gbk", "latin-1")
    for enc in encodings:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def run(cmd: list, timeout: float = 30, cwd: str | None = None) -> tuple:
    """执行命令，返回 (returncode, stdout, stderr)。命令不存在等异常统一转成 rc=-1。"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode, decode(proc.stdout), decode(proc.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", f"命令超时（{timeout}s）：{' '.join(str(c) for c in cmd)}"
    except FileNotFoundError:
        return -1, "", f"命令不存在：{cmd[0] if cmd else ''}"
    except Exception as e:  # noqa: BLE001
        return -1, "", f"命令执行失败：{e}"


def is_admin() -> bool:
    """当前进程是否具备管理员权限（禁用/启用网卡需要）。"""
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def pythonw_path() -> str:
    """返回同名 pythonw.exe 路径（无控制台窗口），找不到则回退到当前解释器。"""
    exe = sys.executable or "python"
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.isfile(cand) else exe


def ensure_console_streams(log_path: str = "") -> bool:
    """窗口化程序（无控制台）下 sys.stdout / sys.stderr 为 None。

    此时任何 ``print`` 都会抛 AttributeError；本函数把它们兜底到日志文件
    （写不进去则丢弃），返回是否发生了替换。有控制台时不做任何事。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return False
    sink = None
    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            sink = open(log_path, "a", encoding="utf-8", errors="replace")
            # 打标记：日志层据此避免再加一个写同一文件的 StreamHandler（否则每行日志会重复写两次）
            try:
                sink._campusnet_redirect = os.path.abspath(log_path)
            except Exception:  # noqa: BLE001
                pass
        except OSError:
            sink = None
    if sink is None:
        try:
            sink = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return False
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink
    return True


def human_bytes(n: float | int) -> str:
    n = float(n or 0)
    neg = n < 0
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            text = f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
            return ("-" + text) if neg else text
        n /= 1024.0
    return f"{n:.2f} TB"


def human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    if seconds < 60:
        return f"{int(seconds)}秒"
    if seconds < 3600:
        return f"{int(seconds // 60)}分{int(seconds % 60)}秒"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}小时{minutes}分"


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return time.strftime(fmt, time.localtime())


def sleep(seconds: float) -> None:
    try:
        time.sleep(max(0.0, float(seconds)))
    except Exception:  # noqa: BLE001
        pass
