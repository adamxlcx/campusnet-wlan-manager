# -*- coding: utf-8 -*-
"""WLAN 控制（基于 netsh）。

职责：
    * 接口名自动探测（config.wlan.interface = "auto" 时）
    * 读取本机已保存的无线配置文件列表（供 GUI 下拉选择）
    * 连接 / 断开 / 状态查询 / 重启网卡（禁用-启用，权限不足时降级为断线重连）
    * 网卡字节计数器读取（供流量统计使用）

设计：所有函数都显式接收 cfg（配置字典），不依赖全局状态，便于 GUI 直接调用。
"""
from __future__ import annotations

import re
import time

from . import sysutil
from .logging_setup import get_logger

# 状态字段（中文/英文双兼容）
_RE_NAME = re.compile(r"^\s*(?:名称|Name)\s*:\s*(.+?)\s*$", re.M)
_RE_STATE = re.compile(r"^\s*(?:状态|State)\s*:\s*(.+?)\s*$", re.M)
_RE_SSID = re.compile(r"^\s*SSID\s*:\s*(.+?)\s*$", re.M)
_RE_BSSID = re.compile(r"^\s*BSSID\s*:\s*(.+?)\s*$", re.M)
_RE_SIGNAL = re.compile(r"^\s*(?:信号|Signal)\s*:\s*(\d+)\s*%", re.M)
_RE_PROFILE = re.compile(r"^\s*(?:All User Profile|所有用户配置文件)\s*:\s*(.+?)\s*$", re.M)
_RE_IF_ROW = re.compile(
    r"^\s*(Enabled|Disabled|已启用|已禁用)\s+(Connected|Disconnected|已连接|已断开)\s+"
    r"(Dedicated|Loopback|专用|环回)\s+(.+?)\s*$", re.M | re.I)

CONNECTED_WORDS = ("已连接", "connected")
DISCONNECTED_WORDS = ("已断开", "disconnected")


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
def netsh(args, timeout: float = 20) -> tuple:
    return sysutil.run(["netsh"] + list(args), timeout=timeout)


def _is_connected_word(word: str) -> bool:
    w = (word or "").strip().lower()
    return any(k in w for k in CONNECTED_WORDS)


def show_interfaces_text(timeout: float = 15) -> str:
    rc, out, err = netsh(["wlan", "show", "interfaces"], timeout=timeout)
    return out or err or ""


def _parse_interface_blocks(text: str) -> list:
    """解析 `netsh wlan show interfaces`，返回每个无线接口的字典。"""
    blocks = []
    for chunk in re.split(r"\r?\n\r?\n", text or ""):
        name = _RE_NAME.search(chunk)
        if not name:
            continue
        ssid = _RE_SSID.search(chunk)
        state = _RE_STATE.search(chunk)
        sig = _RE_SIGNAL.search(chunk)
        blocks.append({
            "interface": name.group(1).strip(),
            "ssid": (ssid.group(1).strip() if ssid else ""),
            "state": (state.group(1).strip() if state else ""),
            "signal": int(sig.group(1)) if sig else None,
            "connected": _is_connected_word(state.group(1) if state else ""),
            "raw": chunk,
        })
    return blocks


def list_interface_rows(timeout: float = 15) -> list:
    """`netsh interface show interface` 的解析结果（含管理员启用状态）。"""
    rc, out, err = netsh(["interface", "show", "interface"], timeout=timeout)
    rows = []
    for m in _RE_IF_ROW.finditer(out or ""):
        admin, state, itype, name = m.groups()
        rows.append({
            "name": name.strip(),
            "admin": "enabled" if admin.lower() in ("enabled", "已启用") else "disabled",
            "state": "connected" if state.lower() in ("connected", "已连接") else "disconnected",
            "type": itype,
        })
    return rows


def interface_candidates() -> list:
    """返回可用的无线接口候选名（按可靠性排序）。"""
    names = []
    for blk in _parse_interface_blocks(show_interfaces_text()):
        if blk["interface"] not in names:
            names.append(blk["interface"])
    for row in list_interface_rows():
        if row["admin"] == "enabled" and row["type"].lower().startswith("ded") \
                and row["name"] not in names:
            names.append(row["name"])
    return names


def detect_interface(cfg: dict | None = None, save_to_cfg: bool = False) -> str:
    """探测无线网卡接口名；cfg.wlan.interface 非 auto 时直接返回配置值。"""
    iface = str(((cfg or {}).get("wlan") or {}).get("interface") or "auto").strip()
    if iface and iface.lower() != "auto":
        return iface
    candidates = interface_candidates()
    if not candidates:
        return "WLAN"  # 保底值，调用方仍可拿到明确的失败信息
    chosen = candidates[0]
    for name in candidates:
        if name.lower() in ("wlan", "wi-fi", "wifi", "无线网络连接"):
            chosen = name
            break
    if save_to_cfg and isinstance(cfg, dict):
        cfg.setdefault("wlan", {})["interface"] = chosen
    get_logger().debug("自动探测无线接口：%s（候选 %s）", chosen, candidates)
    return chosen


def resolve_interface(cfg: dict | None = None) -> str:
    return detect_interface(cfg)


# --------------------------------------------------------------------------- #
# 配置文件（本机已保存的无线网络）
# --------------------------------------------------------------------------- #
def list_profiles(timeout: float = 20) -> list:
    """读取本机已保存的无线配置文件列表（netsh wlan show profiles）。"""
    rc, out, err = netsh(["wlan", "show", "profiles"], timeout=timeout)
    text = out or err or ""
    profiles = []
    for m in _RE_PROFILE.finditer(text):
        name = m.group(1).strip()
        if name and name not in profiles:
            profiles.append(name)
    if not profiles:
        get_logger().warning("未能解析到任何无线配置文件（netsh 返回码 %s）", rc)
    return profiles


def list_profiles_detailed(timeout: float = 20) -> list:
    """返回 [{name, interface}]，便于 GUI 展示与搜索。"""
    rc, out, err = netsh(["wlan", "show", "profiles"], timeout=timeout)
    text = out or err or ""
    current_iface = ""
    result = []
    for line in text.splitlines():
        low = line.strip()
        if low.lower().startswith("profiles on interface") or low.startswith("接口"):
            parts = low.split(":", 1)
            if len(parts) == 2:
                current_iface = parts[1].strip()
            continue
        m = _RE_PROFILE.match(line)
        if m:
            name = m.group(1).strip()
            if name:
                result.append({"name": name, "interface": current_iface})
    return result


def profile_exists(profile: str, timeout: float = 20) -> bool:
    if not profile:
        return False
    return profile in list_profiles(timeout=timeout)


def profile_password(profile: str) -> str:
    """读取本机保存的无线密码明文（需要管理员权限）。

    失败返回空串——程序正常连接并不需要密码，此函数仅用于 GUI 展示/诊断。
    """
    rc, out, err = netsh(["wlan", "show", "profile", f"name={profile}", "key=clear"], timeout=20)
    m = re.search(r"^\s*(?:关键内容|Key Content)\s*:\s*(.+?)\s*$", out or "", re.M)
    return m.group(1).strip() if m else ""


# --------------------------------------------------------------------------- #
# 状态查询
# --------------------------------------------------------------------------- #
def current_connection(cfg: dict | None = None) -> dict:
    """当前无线连接状态：{connected, ssid, state, signal, interface}。"""
    iface = resolve_interface(cfg)
    blocks = _parse_interface_blocks(show_interfaces_text())
    pick = None
    for blk in blocks:
        if blk["interface"].lower() == iface.lower():
            pick = blk
            break
    if pick is None and blocks:
        pick = blocks[0]
    if pick is None:
        return {"connected": False, "ssid": "", "state": "unknown",
                "signal": None, "interface": iface}
    return {
        "connected": bool(pick["connected"] and pick["ssid"]),
        "ssid": pick["ssid"],
        "state": pick["state"] or "unknown",
        "signal": pick["signal"],
        "interface": pick["interface"],
    }


def is_connected(cfg: dict | None = None) -> bool:
    return bool(current_connection(cfg).get("connected"))


def is_target_connected(ssid: str, cfg: dict | None = None) -> bool:
    conn = current_connection(cfg)
    return bool(conn.get("connected") and conn.get("ssid") == ssid)


def status(cfg: dict | None = None) -> dict:
    """给 GUI / 托盘用的综合状态。"""
    conn = current_connection(cfg)
    conn["profiles"] = list_profiles()
    conn["is_admin"] = sysutil.is_admin()
    return conn


# --------------------------------------------------------------------------- #
# 连接 / 断开
# --------------------------------------------------------------------------- #
def connect(profile: str, cfg: dict | None = None, timeout: float | None = None,
            wait: bool = True) -> dict:
    """连接指定无线配置文件。

    返回 {"ok", "message", "ssid", "seconds"}。密码不在此处填写——取自本机保存的
    Windows 无线配置文件，因此程序无需硬编码任何 WiFi 密码。
    """
    cfg = cfg or {}
    iface = resolve_interface(cfg)
    timeout = float(timeout or (cfg.get("wlan") or {}).get("connect_timeout") or 25)
    profile = (profile or "").strip()
    if not profile:
        return {"ok": False, "message": "未指定无线配置文件", "ssid": "", "seconds": 0.0}

    started = time.time()
    rc, out, err = netsh(["wlan", "connect", f"name={profile}", f"interface={iface}"],
                         timeout=timeout)
    msg = (out or err or "").strip()
    if rc != 0:
        return {"ok": False, "message": f"netsh 连接失败：{msg or rc}", "ssid": profile,
                "seconds": round(time.time() - started, 2)}

    if not wait:
        return {"ok": True, "message": msg or "已下发连接指令", "ssid": profile,
                "seconds": round(time.time() - started, 2)}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_target_connected(profile, cfg):
            return {"ok": True, "message": f"已连接 {profile}",
                    "ssid": profile, "seconds": round(time.time() - started, 2)}
        sysutil.sleep(1.0)
    return {"ok": False, "message": f"连接 {profile} 超时（{timeout:.0f}s）",
            "ssid": profile, "seconds": round(time.time() - started, 2)}


def disconnect(cfg: dict | None = None, wait: bool = True, timeout: float = 10) -> dict:
    cfg = cfg or {}
    iface = resolve_interface(cfg)
    rc, out, err = netsh(["wlan", "disconnect", f"interface={iface}"], timeout=timeout)
    msg = (out or err or "").strip()
    ok = rc == 0
    if ok and wait:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not is_connected(cfg):
                break
            sysutil.sleep(0.8)
        ok = not is_connected(cfg)
    return {"ok": ok, "message": msg or ("已断开" if ok else "断开失败"), "interface": iface}


def reconnect(cfg: dict | None = None, profile: str = "") -> dict:
    """断线重连（无管理员权限时的重启网卡降级方案）。"""
    cfg = cfg or {}
    if not profile:
        conn = current_connection(cfg)
        profile = conn.get("ssid") or ""
    disconnect(cfg)
    sysutil.sleep(2)
    if not profile:
        return {"ok": False, "method": "reconnect", "message": "无法确定要回连的网络"}
    result = connect(profile, cfg)
    return {"ok": bool(result.get("ok")), "method": "reconnect",
            "message": result.get("message", ""), "profile": profile}


def restart_adapter(cfg: dict | None = None, reconnect_profile: str = "",
                    wait_seconds: float = 6.0) -> dict:
    """重启无线网卡：优先禁用-启用（需管理员），否则降级为断线重连。

    返回 {"ok", "method", "message", "profile"}；method ∈ adapter-recycle | reconnect | failed
    """
    cfg = cfg or {}
    iface = resolve_interface(cfg)
    if not reconnect_profile:
        reconnect_profile = current_connection(cfg).get("ssid") or ""

    if sysutil.is_admin():
        rc1, o1, e1 = netsh(["interface", "set", "interface", f"name={iface}", "admin=DISABLED"],
                            timeout=20)
        if rc1 == 0:
            sysutil.sleep(wait_seconds / 2)
            rc2, o2, e2 = netsh(["interface", "set", "interface", f"name={iface}", "admin=ENABLED"],
                                timeout=20)
            if rc2 == 0:
                sysutil.sleep(wait_seconds)
                if reconnect_profile:
                    r = connect(reconnect_profile, cfg)
                    ok = bool(r.get("ok"))
                    return {"ok": ok, "method": "adapter-recycle", "profile": reconnect_profile,
                            "message": ("网卡已重启并回连 " + reconnect_profile) if ok
                                       else f"网卡已重启，但回连失败：{r.get('message')}"}
                return {"ok": True, "method": "adapter-recycle", "profile": "",
                        "message": "网卡已重启（未指定回连网络）"}
            get_logger().warning("启用网卡失败：%s", (o2 or e2).strip())
        else:
            get_logger().warning("禁用网卡失败（可能权限不足）：%s", (o1 or e1).strip())

    result = reconnect(cfg, reconnect_profile)
    result["method"] = "reconnect" if result.get("ok") else "failed"
    result["message"] = "（无管理员权限，已降级为断线重连）" + result.get("message", "")
    return result


# --------------------------------------------------------------------------- #
# 网卡计数器
# --------------------------------------------------------------------------- #
def get_iface_counters(interface: str = "") -> dict | None:
    """读取网卡累计收发字节（psutil）。返回 {bytes_sent, bytes_recv, ts}。"""
    try:
        import psutil
    except ImportError:
        get_logger().error("未安装 psutil，无法读取网卡计数器")
        return None
    try:
        counters = psutil.net_io_counters(pernic=True)
    except Exception as e:  # noqa: BLE001
        get_logger().warning("读取网卡计数器失败：%s", e)
        return None
    if not counters:
        return None
    if interface and interface in counters:
        node = counters[interface]
    else:
        # 名字不一致时按包含关系模糊匹配，最后回退到所有非环回网卡合计
        pick = None
        for name, node in counters.items():
            if interface and (interface.lower() in name.lower() or name.lower() in interface.lower()):
                pick = node
                break
        if pick is None:
            total_sent = sum(n.bytes_sent for n in counters.values())
            total_recv = sum(n.bytes_recv for n in counters.values())
            return {"bytes_sent": total_sent, "bytes_recv": total_recv, "ts": time.time(),
                    "interface": "(全部网卡合计)"}
        node = pick
    return {"bytes_sent": node.bytes_sent, "bytes_recv": node.bytes_recv,
            "ts": time.time(), "interface": interface}
