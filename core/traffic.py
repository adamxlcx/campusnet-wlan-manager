# -*- coding: utf-8 -*-
"""流量统计与下载流量保护。

两部分能力：
    1. 单次连接（连上 → 断开）的上下行流量统计：SessionMeter
    2. 按“每个 WiFi 各自配置”的下载保护：TrafficGuard
       （网速阈值 + 持续时长 + 累计流量阈值；网速单位可选 MB/s 等，流量单位可选 KB/MB/GB）

单位约定：1 KB = 1024 B，1 MB = 1024 KB，1 GB = 1024 MB（二进制单位）。
也接受 bps 类单位（Kbit/s / Mbit/s / Gbit/s，按 1000 进制换算成字节/秒）。
"""
from __future__ import annotations

import time

from . import sysutil, wlan
from .logging_setup import get_logger

# --------------------------------------------------------------------------- #
# 单位换算
# --------------------------------------------------------------------------- #
SPEED_UNITS = {
    "B/S": 1.0,
    "KB/S": 1024.0,
    "MB/S": 1024.0 ** 2,
    "GB/S": 1024.0 ** 3,
    "TB/S": 1024.0 ** 4,
    "KBIT/S": 1000.0 / 8,
    "MBIT/S": 1000.0 ** 2 / 8,
    "GBIT/S": 1000.0 ** 3 / 8,
}
VOLUME_UNITS = {
    "B": 1.0,
    "KB": 1024.0,
    "MB": 1024.0 ** 2,
    "GB": 1024.0 ** 3,
    "TB": 1024.0 ** 4,
}
SPEED_UNIT_ALIASES = {
    "B/S": "B/s", "KB/S": "KB/s", "MB/S": "MB/s", "GB/S": "GB/s", "TB/S": "TB/s",
    "KBIT/S": "Kbit/s", "MBIT/S": "Mbit/s", "GBIT/S": "Gbit/s",
    "Kb/s": "Kbit/s", "Mb/s": "Mbit/s", "Gb/s": "Gbit/s",
    "KBPS": "KB/s", "MBPS": "MB/s", "GBPS": "GB/s",
}
VOLUME_UNIT_ALIASES = {
    "B": "B", "KB": "KB", "MB": "MB", "GB": "GB", "TB": "TB",
    "K": "KB", "M": "MB", "G": "GB", "T": "TB",
}


def normalize_speed_unit(unit, default: str = "MB/s") -> str:
    key = str(unit or "").strip().upper()
    if key in SPEED_UNITS:
        return SPEED_UNIT_ALIASES.get(key, key)
    alt = SPEED_UNIT_ALIASES.get(str(unit or "").strip())
    if alt and alt.upper() in SPEED_UNITS:
        return alt
    return default


def normalize_volume_unit(unit, default: str = "MB") -> str:
    key = str(unit or "").strip().upper()
    if key in VOLUME_UNITS:
        return VOLUME_UNIT_ALIASES.get(key, key)
    return default


def speed_to_bps(value: float, unit: str) -> float:
    """把 “2 MB/s” 换算成字节/秒。"""
    return float(value or 0) * SPEED_UNITS[normalize_speed_unit(unit).upper()]


def volume_to_bytes(value: float, unit: str) -> float:
    """把 “50 MB” 换算成字节。"""
    return float(value or 0) * VOLUME_UNITS[normalize_volume_unit(unit)]


def bytes_to_volume(num_bytes: float, unit: str) -> float:
    return float(num_bytes or 0) / VOLUME_UNITS[normalize_volume_unit(unit)]


def bytes_to_speed(num_bytes_per_sec: float, unit: str) -> float:
    return float(num_bytes_per_sec or 0) / SPEED_UNITS[normalize_speed_unit(unit).upper()]


def format_speed(bps: float, unit: str = "MB/s") -> str:
    return f"{bytes_to_speed(bps, unit):.2f} {normalize_speed_unit(unit)}"


def format_volume(num_bytes: float, unit: str = "MB") -> str:
    return f"{bytes_to_volume(num_bytes, unit):.2f} {normalize_volume_unit(unit)}"


def human_speed(bps: float) -> str:
    """自适应单位的人类可读网速。"""
    bps = float(bps or 0)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < SPEED_UNITS[unit.upper()] * 1024 or unit == "GB/s":
            return f"{bytes_to_speed(bps, unit):.2f} {unit}"
    return f"{bytes_to_speed(bps, 'GB/s'):.2f} GB/s"


# --------------------------------------------------------------------------- #
# 单次连接会话统计
# --------------------------------------------------------------------------- #
class SessionMeter:
    """统计“连上 → 断开”这一段时间的上下行流量。

    实现：连接建立时记录网卡计数器基线，之后每次 sample() 计算增量。
    """

    def __init__(self, interface: str = "", network: str = ""):
        self.interface = interface or wlan.detect_interface()
        self.network = network
        self.base = None
        self.last = None
        self.started_at = None
        self.stopped_at = None
        self.sent = 0
        self.recv = 0
        self.peak_down_bps = 0.0
        self.peak_up_bps = 0.0

    def start(self) -> bool:
        counters = wlan.get_iface_counters(self.interface)
        if counters is None:
            return False
        self.base = counters
        self.last = dict(counters)
        self.started_at = time.time()
        self.stopped_at = None
        self.sent = self.recv = 0
        self.peak_down_bps = self.peak_up_bps = 0.0
        get_logger().info("流量会话开始：%s（网卡 %s）", self.network or "(未命名)", self.interface)
        return True

    def sample(self) -> dict:
        """采样一次，返回本次增量与瞬时速率。"""
        counters = wlan.get_iface_counters(self.interface)
        if counters is None or self.last is None:
            return {"ok": False, "reason": "计数器不可用"}
        now = counters["ts"]
        elapsed = max(0.001, now - self.last["ts"])
        d_sent = max(0, counters["bytes_sent"] - self.last["bytes_sent"])
        d_recv = max(0, counters["bytes_recv"] - self.last["bytes_recv"])
        up_bps = d_sent / elapsed
        down_bps = d_recv / elapsed
        self.last = counters
        self.sent += d_sent
        self.recv += d_recv
        self.peak_down_bps = max(self.peak_down_bps, down_bps)
        self.peak_up_bps = max(self.peak_up_bps, up_bps)
        return {
            "ok": True, "elapsed": elapsed,
            "delta_sent": d_sent, "delta_recv": d_recv,
            "up_bps": up_bps, "down_bps": down_bps,
            "total_sent": self.sent, "total_recv": self.recv,
            "duration": (now - self.started_at) if self.started_at else 0.0,
        }

    def stop(self) -> dict:
        self.sample()
        self.stopped_at = time.time()
        result = self.summary()
        get_logger().info("流量会话结束：%s，上行 %s，下行 %s，时长 %s",
                          self.network or "(未命名)",
                          sysutil.human_bytes(result["bytes_sent"]),
                          sysutil.human_bytes(result["bytes_recv"]),
                          sysutil.human_duration(result["duration"]))
        return result

    def summary(self) -> dict:
        return {
            "network": self.network,
            "interface": self.interface,
            "bytes_sent": self.sent,
            "bytes_recv": self.recv,
            "bytes_total": self.sent + self.recv,
            "duration": (self.stopped_at or time.time()) - (self.started_at or time.time()),
            "peak_down_bps": self.peak_down_bps,
            "peak_up_bps": self.peak_up_bps,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
        }


def measure(interface: str = "", network: str = "", duration: float = 5.0,
            interval: float = 1.0) -> dict:
    """CLI/自测用：在 duration 秒内采样并返回统计结果。"""
    meter = SessionMeter(interface, network)
    if not meter.start():
        return {"ok": False, "reason": "无法开始流量统计（psutil 或网卡计数器不可用）"}
    deadline = time.time() + max(0.0, duration)
    while time.time() < deadline:
        sysutil.sleep(interval)
        meter.sample()
    return {"ok": True, **meter.stop()}


# --------------------------------------------------------------------------- #
# 下载流量保护
# --------------------------------------------------------------------------- #
class GuardConfig:
    """单个 WiFi 的流量保护配置（单位已换算成字节）。"""

    def __init__(self, raw: dict | None):
        raw = raw if isinstance(raw, dict) else {}
        speed = raw.get("speed") or {}
        volume = raw.get("volume") or {}
        self.enabled = bool(raw.get("enabled"))
        self.speed_value = float(speed.get("value") or 0)
        self.speed_unit = normalize_speed_unit(speed.get("unit"))
        self.threshold_bps = speed_to_bps(self.speed_value, self.speed_unit)
        self.volume_value = float(volume.get("value") or 0)
        self.volume_unit = normalize_volume_unit(volume.get("unit"))
        self.limit_bytes = volume_to_bytes(self.volume_value, self.volume_unit)
        self.sustained_seconds = float(raw.get("sustained_seconds") or 10)
        self.sample_interval = float(raw.get("sample_interval_seconds") or 2)
        self.deny_keeps_disconnected = bool(raw.get("deny_keeps_disconnected", True))
        self.inspect_processes = bool(raw.get("inspect_processes", True))
        self.top_processes = int(raw.get("top_processes") or 5)

    def describe(self) -> str:
        return (f"持续 {self.sustained_seconds:.0f}s ≥ {self.speed_value} {self.speed_unit} "
                f"且累计 ≥ {self.volume_value} {self.volume_unit}")

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "speed": {"value": self.speed_value, "unit": self.speed_unit},
            "volume": {"value": self.volume_value, "unit": self.volume_unit},
            "sustained_seconds": self.sustained_seconds,
            "sample_interval_seconds": self.sample_interval,
        }


# 保护配置里受合并逻辑管理的键（其它自定义键原样保留）
GUARD_KEYS = ("enabled", "speed", "volume", "sustained_seconds",
              "sample_interval_seconds", "deny_keeps_disconnected",
              "inspect_processes", "top_processes")


def merge_guard(defaults: dict | None, guard: dict | None) -> dict:
    """合并「全局默认保护配置」与该 WiFi 的显式配置（后者优先）。

    用于修正只写了 ``{"enabled": false}`` 这类残缺配置：缺项自动继承
    ``traffic.defaults``，从而在用户打开开关后阈值依然有效。
    """
    defaults = defaults if isinstance(defaults, dict) else {}
    guard = guard if isinstance(guard, dict) else {}
    merged = {}
    for key in GUARD_KEYS:
        if guard.get(key) is not None:
            merged[key] = guard[key]
        elif defaults.get(key) is not None:
            merged[key] = defaults[key]
    for key, value in guard.items():
        merged.setdefault(key, value)
    return merged


def guard_summary(raw: dict | None) -> dict:
    """给界面/CLI 用的保护配置摘要（含开关与阈值描述）。"""
    cfg = GuardConfig(raw)
    return {
        "enabled": cfg.enabled,
        "speed": {"value": cfg.speed_value, "unit": cfg.speed_unit},
        "volume": {"value": cfg.volume_value, "unit": cfg.volume_unit},
        "sustained_seconds": cfg.sustained_seconds,
        "sample_interval_seconds": cfg.sample_interval,
        "deny_keeps_disconnected": cfg.deny_keeps_disconnected,
        "describe": cfg.describe(),
    }


def identify_downloaders(top_n: int = 5) -> list:
    """尽力识别当前正在联网的进程（按已建立的外部连接数排序）。

    Windows 无公开的“每进程网络流量”计数器，这里用连接数做启发式排序，
    只用于弹窗提示，不参与判定逻辑。
    """
    if top_n <= 0:
        return []
    try:
        import psutil
    except ImportError:
        return []
    counts = {}
    names = {}
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_ESTABLISHED or not conn.raddr:
                continue
            pid = conn.pid
            if not pid:
                continue
            counts[pid] = counts.get(pid, 0) + 1
    except Exception as e:  # noqa: BLE001
        get_logger().debug("枚举网络连接失败（忽略）：%s", e)
        return []
    for pid in counts:
        try:
            names[pid] = psutil.Process(pid).name()
        except Exception:  # noqa: BLE001
            names[pid] = f"pid-{pid}"
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[: int(top_n)]
    return [{"pid": pid, "name": names.get(pid, f"pid-{pid}"), "connections": cnt}
            for pid, cnt in ordered]


class TrafficGuard:
    """按网络配置的下载保护 + 实时流量统计。

    * **采样与保护解耦**：只要会话开始，每次 ``tick()`` 都会统计实时上下行速率与
      本会话累计流量（供界面展示），与该 WiFi 是否启用下载保护无关；
    * **是否保护由开关决定**：只有 ``enabled``（或调用方显式传入的 ``enforce``）为真时，
      才做阈值判定，命中时调用 ``on_trip(info)``，由上层决定弹窗与切断。
    """

    def __init__(self, network: str, guard_raw: dict | None, on_trip=None):
        self.network = network
        self.cfg = GuardConfig(guard_raw)
        self.on_trip = on_trip
        self.session_active = False
        self.session_started_at = None
        self.total_recv = 0          # 本会话累计（不因触发保护清零）
        self.total_sent = 0
        self.window_recv = 0         # 阈值判定窗口累计（触发后清零）
        self.high_since = None
        self.last_ts = None
        self._prev_recv = None
        self._prev_sent = None
        self.last_down_bps = 0.0
        self.last_up_bps = 0.0
        self.peak_down_bps = 0.0     # 本会话峰值（用于界面展示采样确实在工作）
        self.peak_up_bps = 0.0
        self.last_sampled_at = None
        self.tripped_count = 0
        self.last_result = {"active": False, "sampling": False}

    # ---- 会话生命周期 ----
    def start_session(self) -> None:
        self.session_active = True
        self.session_started_at = time.time()
        self.total_recv = 0
        self.total_sent = 0
        self.window_recv = 0
        self.high_since = None
        self.last_ts = None
        self._prev_recv = None
        self._prev_sent = None
        self.last_down_bps = 0.0
        self.last_up_bps = 0.0
        self.peak_down_bps = 0.0
        self.peak_up_bps = 0.0
        self.last_sampled_at = None
        get_logger().info("[%s] 流量统计会话开始（保护%s，%s）", self.network,
                          "已启用" if self.cfg.enabled else "未启用", self.cfg.describe())

    def stop_session(self) -> dict:
        self.session_active = False
        self.high_since = None
        duration = (time.time() - self.session_started_at) if self.session_started_at else 0.0
        return {"network": self.network, "total_recv": self.total_recv,
                "total_sent": self.total_sent, "duration": duration,
                "enabled": self.cfg.enabled, "trips": self.tripped_count}

    def session_seconds(self) -> float:
        if not self.session_started_at:
            return 0.0
        return max(0.0, time.time() - self.session_started_at)

    # ---- 采样 ----
    def tick(self, interface: str = "", counters: dict | None = None,
             enforce: bool | None = None) -> dict:
        """采样一次。

        * 只要会话开始，就统计实时上下行速率与本会话累计流量（与保护开关无关）；
        * ``enforce`` 为 None 时取该 WiFi 的保护开关，只有为真才做阈值判定与触发回调。
        """
        if not self.session_active:
            self.last_result = {"active": False, "sampling": False, "ok": False,
                                "network": self.network, "message": "流量会话未开始"}
            return self.last_result

        enforce = bool(self.cfg.enabled) if enforce is None else bool(enforce)
        counters = counters or wlan.get_iface_counters(interface or wlan.detect_interface())
        if not counters:
            self.last_result = self._base_info(enforce, False, 0.0, 0.0)
            self.last_result["message"] = "网卡计数器不可用（psutil 缺失或无权限）"
            return self.last_result

        now = float(counters["ts"])
        recv = counters["bytes_recv"]
        sent = counters.get("bytes_sent")
        if self.last_ts is None or self._prev_recv is None:
            # 首帧只对齐基线（速率记 0），避免把上一次会话以来的流量算进本次
            self.last_ts = now
            self._prev_recv = recv
            self._prev_sent = sent
            self.last_down_bps = 0.0
            self.last_up_bps = 0.0
            self.last_sampled_at = now
            self.last_result = self._base_info(enforce, True, 0.0, 0.0)
            return self.last_result

        elapsed = max(0.001, now - self.last_ts)
        delta_recv = max(0, recv - self._prev_recv)
        delta_sent = max(0, (sent or 0) - (self._prev_sent or 0)) if sent is not None else 0
        self._prev_recv = recv
        if sent is not None:
            self._prev_sent = sent
        self.last_ts = now
        self.total_recv += delta_recv       # 会话累计：不因触发保护而清零
        self.total_sent += delta_sent
        self.window_recv += delta_recv      # 判定窗口累计：触发后清零
        down_bps = delta_recv / elapsed
        up_bps = delta_sent / elapsed
        self.last_down_bps = down_bps
        self.last_up_bps = up_bps
        self.peak_down_bps = max(self.peak_down_bps, down_bps)
        self.peak_up_bps = max(self.peak_up_bps, up_bps)
        self.last_sampled_at = now

        info = self._base_info(enforce, True, down_bps, up_bps)

        over_speed = self.cfg.threshold_bps > 0 and down_bps >= self.cfg.threshold_bps
        if enforce and over_speed:
            if self.high_since is None:
                self.high_since = now
        else:
            self.high_since = None

        sustained = (self.high_since is not None
                     and (now - self.high_since) >= self.cfg.sustained_seconds)
        over_volume = self.cfg.limit_bytes > 0 and self.window_recv >= self.cfg.limit_bytes
        should_trip = bool(enforce and sustained and over_volume)

        info.update({
            "sustained_seconds": (now - self.high_since) if self.high_since else 0.0,
            "over_speed": bool(enforce and over_speed),
            "over_volume": bool(enforce and over_volume),
            "should_trip": should_trip,
            "threshold": self.cfg.describe(),
            "delta_recv": delta_recv,
            "delta_sent": delta_sent,
            "processes": identify_downloaders(self.cfg.top_processes)
            if (should_trip and self.cfg.inspect_processes) else [],
        })
        self.last_result = info

        if should_trip:
            self.tripped_count += 1
            info["action"] = "trip"
            if callable(self.on_trip):
                try:
                    info["user_allowed"] = bool(self.on_trip(info))
                except Exception as e:  # noqa: BLE001
                    get_logger().error("[%s] 流量保护回调异常：%s", self.network, e)
                    info["user_allowed"] = False
            else:
                info["user_allowed"] = False
            # 命中后重置计时与判定窗口，避免同一波流量反复弹窗
            self.high_since = None
            self.window_recv = 0
        return info

    # ---- 状态输出 ----
    def _base_info(self, enforce: bool, ok: bool, down_bps: float, up_bps: float) -> dict:
        total = self.total_recv + self.total_sent
        return {
            "active": True,
            "sampling": bool(ok),
            "ok": bool(ok),
            "enabled": bool(enforce),
            "network": self.network,
            "down_bps": float(down_bps),
            "up_bps": float(up_bps),
            "down_speed": human_speed(down_bps),
            "up_speed": human_speed(up_bps),
            "human_speed": human_speed(down_bps),
            "total_recv": self.total_recv,
            "total_sent": self.total_sent,
            "session_recv_human": sysutil.human_bytes(self.total_recv),
            "session_sent_human": sysutil.human_bytes(self.total_sent),
            "session_total_human": sysutil.human_bytes(total),
            "session_seconds": self.session_seconds(),
            "peak_down_bps": float(self.peak_down_bps),
            "peak_up_bps": float(self.peak_up_bps),
            "peak_down_speed": human_speed(self.peak_down_bps),
            "peak_up_speed": human_speed(self.peak_up_bps),
            "trip_count": int(self.tripped_count),
            "tripped_count": int(self.tripped_count),
            "total_volume": format_volume(self.total_recv, self.cfg.volume_unit),
            "human_total": sysutil.human_bytes(self.total_recv),
            "sampled_at": self.last_sampled_at,
            "message": "" if ok else "采样不可用",
        }

    def live(self) -> dict:
        """最近一次采样结果（只读，不触发新采样）。"""
        return dict(self.last_result or {})


class TrafficManager:
    """按网络名管理多个 TrafficGuard，供 service 使用。"""

    def __init__(self, traffic_cfg: dict | None, on_trip=None, network_guards: dict | None = None):
        self.traffic_cfg = traffic_cfg or {}
        self.on_trip = on_trip
        self.guards = {}
        for name, raw in (network_guards or {}).items():
            self.guards[name] = TrafficGuard(name, raw, on_trip)

    def guard_for(self, network: str, guard_raw: dict | None = None) -> TrafficGuard:
        if network not in self.guards:
            self.guards[network] = TrafficGuard(network, guard_raw, self.on_trip)
        elif guard_raw is not None:
            self.guards[network].cfg = GuardConfig(guard_raw)
        return self.guards[network]

    def live_info(self, network: str) -> dict:
        """某个网络的最近一次采样结果（只读）。"""
        guard = self.guards.get(network)
        return guard.live() if guard else {}

    def stop_all(self) -> list:
        return [g.stop_session() for g in self.guards.values()]

    def summary(self) -> list:
        return [{"network": name, **g.last_result} for name, g in self.guards.items()]
