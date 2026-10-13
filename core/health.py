# -*- coding: utf-8 -*-
"""网络连通性检测与重启网卡。

两个独立开关：
    health.enabled          —— 是否做连通性检测（托盘绿/红状态即由它决定）
    health.restart.enabled  —— 是否在连续失败后重启网卡
检测关闭时不会自动触发重启（仍可通过 cli / GUI 手动触发 restart_once）。
"""
from __future__ import annotations

import re
import socket
import time

from . import sysutil, wlan
from .logging_setup import get_logger

_RE_LATENCY = re.compile(r"(?:时间|time)[=<]\s*(\d+)\s*ms", re.I)


def get_local_ip(target: str = "8.8.8.8", port: int = 53) -> str:
    """获取本机在默认路由上的局域网 IP（不实际发包）。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        sock.connect((target, port))
        return sock.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass


def ping(host: str, timeout_ms: int = 3000) -> dict:
    """执行一次 ping。返回 {ok, latency_ms, message}。"""
    host = (host or "").strip()
    if not host:
        return {"ok": False, "latency_ms": None, "message": "未配置检测目标"}
    rc, out, err = sysutil.run(
        ["ping", "-n", "1", "-w", str(int(timeout_ms)), host],
        timeout=max(5.0, timeout_ms / 1000.0 + 3),
    )
    text = out or err or ""
    m = _RE_LATENCY.search(text)
    ok = rc == 0 and ("ttl=" in text.lower())
    latency = int(m.group(1)) if (ok and m) else None
    if ok:
        message = f"{host} 可达" + (f"（{latency}ms）" if latency is not None else "")
    else:
        message = f"{host} 不可达"
    return {"ok": ok, "latency_ms": latency, "message": message}


def tcp_probe(host: str, port: int = 443, timeout: float = 3.0) -> dict:
    """ICMP 被墙时的兜底探测（TCP 握手）。"""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return {"ok": True, "message": f"{host}:{port} TCP 可达"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"{host}:{port} TCP 不可达（{e.__class__.__name__}）"}


def check(cfg: dict | None = None) -> dict:
    """一次连通性检测：先 ping，失败且开启兜底时再 TCP 探测。"""
    health = ((cfg or {}).get("health") or {})
    target = str(health.get("ping_target") or "www.baidu.com")
    timeout_ms = int(health.get("ping_timeout_ms") or 3000)
    started = time.time()
    result = ping(target, timeout_ms)
    method = "icmp"
    if not result["ok"] and health.get("tcp_fallback", True):
        probe = tcp_probe(target, int(health.get("tcp_port", 443)))
        if probe["ok"]:
            result = {"ok": True, "latency_ms": None, "message": probe["message"]}
            method = "tcp"
    result.update({
        "target": target,
        "method": method,
        "checked_at": time.time(),
        "elapsed": round(time.time() - started, 2),
        "local_ip": get_local_ip(),
        "interface": wlan.detect_interface(cfg),
    })
    return result


class HealthMonitor:
    """状态机：连续失败达到阈值后按冷却时间触发一次网卡重启。"""

    def __init__(self, cfg: dict | None = None, on_status=None, state: dict | None = None):
        self.cfg = cfg or {}
        self.on_status = on_status
        self.state = state if state is not None else {}
        self.fail_count = int(self.state.get("health_fail_count") or 0)
        self.last_result = {"ok": None, "message": "尚未检测"}

    def reload(self, cfg: dict, state: dict | None = None) -> None:
        self.cfg = cfg or {}
        if state is not None:
            self.state = state

    # ---- 配置读取 ----
    @property
    def enabled(self) -> bool:
        return bool((self.cfg.get("health") or {}).get("enabled", True))

    @property
    def restart_enabled(self) -> bool:
        return bool(((self.cfg.get("health") or {}).get("restart") or {}).get("enabled", True))

    @property
    def interval(self) -> int:
        return int((self.cfg.get("health") or {}).get("interval_seconds") or 60)

    @property
    def threshold(self) -> int:
        return int((self.cfg.get("health") or {}).get("fail_threshold") or 3)

    # ---- 巡检 ----
    def tick(self, now: float | None = None, allow_restart: bool = True) -> dict:
        """执行一次检测；返回含 online / fail_count / restarted 的结果。"""
        now = now or time.time()
        if not self.enabled:
            out = {"online": None, "enabled": False, "fail_count": self.fail_count,
                   "message": "连通性检测已关闭"}
            self._emit(out)
            return out

        result = check(self.cfg)
        if result["ok"]:
            self.fail_count = 0
        else:
            self.fail_count += 1

        out = {
            "online": bool(result["ok"]),
            "enabled": True,
            "fail_count": self.fail_count,
            "threshold": self.threshold,
            "latency_ms": result.get("latency_ms"),
            "message": result.get("message"),
            "target": result.get("target"),
            "method": result.get("method"),
            "local_ip": result.get("local_ip"),
            "checked_at": result.get("checked_at"),
            "restarted": False,
        }
        self.last_result = out

        if (not result["ok"]) and self.restart_enabled and allow_restart \
                and self.fail_count >= self.threshold:
            if self._cooldown_ok(now):
                out["restart"] = self.restart_once()
                out["restarted"] = bool(out["restart"].get("ok"))
                self.fail_count = 0
            else:
                out["restart"] = {"ok": False, "method": "skipped",
                                  "message": "重启冷却中，暂不重启"}

        self._emit(out)
        return out

    def _cooldown_ok(self, now: float) -> bool:
        cooldown = int(((self.cfg.get("health") or {}).get("restart") or {})
                       .get("cooldown_seconds") or 0)
        last = float(self.state.get("last_restart_ts") or 0)
        return (now - last) >= cooldown

    def restart_once(self, reconnect_profile: str = "") -> dict:
        """立即重启网卡（不受开关限制，供手动调用）。"""
        restart_cfg = (self.cfg.get("health") or {}).get("restart") or {}
        profile = reconnect_profile or self.state.get("last_ssid") or ""
        if not restart_cfg.get("reconnect_after_restart", True):
            profile = ""
        if not restart_cfg.get("prefer_adapter_recycle", True) and sysutil.is_admin() is False:
            pass
        result = wlan.restart_adapter(self.cfg, reconnect_profile=profile)
        self.state["last_restart_ts"] = time.time()
        get_logger().info("网卡重启（%s）：%s", result.get("method"), result.get("message"))
        return result

    def _emit(self, payload: dict) -> None:
        if callable(self.on_status):
            try:
                self.on_status(payload)
            except Exception as e:  # noqa: BLE001
                get_logger().debug("状态回调异常：%s", e)


def health_check(cfg: dict | None = None) -> dict:
    """命令行用的一次性检测（不触发重启）。"""
    return check(cfg)
