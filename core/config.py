# -*- coding: utf-8 -*-
"""配置模型：默认值 + 读取/写入 + 校验 + 旧 config.json 一次性迁移。

设计要点
--------
1. 默认配置**不含任何** SSID / 账号 / 密码 / 运营商 / 阈值 / 时间硬编码，
   全部由用户配置或插件提供；`DEFAULT_CONFIG["networks"]` 为空字典。
2. 读取时用 deep_merge 把默认值补进用户配置，因此旧版本配置新增字段后可自动兼容。
3. `migrate_from_legacy()` 把上一阶段单体程序的 config.json（wlan/schedule/health/
   traffic_guard/portal/logging）转换成新结构，并返回人类可读的迁移报告。
"""
from __future__ import annotations

import copy
import json
import os
import time

from . import paths
from .logging_setup import get_logger

# --------------------------------------------------------------------------- #
# 默认配置
# --------------------------------------------------------------------------- #
DEFAULT_NETWORK = {
    "profile": "",            # Windows 无线配置文件名称，留空表示与网络名相同
    "label": "",              # 界面展示名
    "need_login": False,      # 本网络是否需要网页登录（每个 WiFi 独立开关）
    "plugin": "",             # 登录插件目录名，留空表示与网络名相同
    "login": {
        "enabled": None,      # None = 跟随 need_login
        "url": "",            # 登录页地址（可自定义；留空则用插件 manifest 里的地址）
        "driver": "",         # ""=跟随全局 portal.driver；可选 browser / requests
        "credentials": {},    # 账号/密码等凭据：{"account": "...", "password": "..."}
        "options": {},        # 自定义选项：{"isp": "@unicom", ...}
        "timeout_seconds": 0,  # 0 = 跟随全局
    },
    # 下载流量保护（每个 WiFi 独立配置）
    "guard": {
        "enabled": False,
        "speed": {"value": 2.0, "unit": "MB/s"},
        "sustained_seconds": 10,
        "volume": {"value": 50.0, "unit": "MB"},
        "sample_interval_seconds": 2,
        "deny_keeps_disconnected": True,
        "inspect_processes": True,
        "top_processes": 5,
    },
}

DEFAULT_CONFIG = {
    "_comment": "CampusNet 通用配置。可被 GUI 修改；守护进程每次循环重新读取，改完即生效。",
    "app": {
        "name": "CampusNet",
        "version": "2.0.0",
        "ui": {
            "theme": "light",          # light | dark
            "start_minimized": True,
            "close_to_tray": True,
            "tray_show_network_status": True,
        },
        "startup": {
            "autostart": False,        # 开关一：开机自启动
            "autostart_delay_seconds": 20,
            "scheduled_tasks": False,  # 开关二：Windows 计划任务
            "task_prefix": "CampusNet",
        },
    },
    "wlan": {
        "interface": "auto",           # auto = 自动探测网卡接口名
        "connect_timeout": 25,
        "verify_after_connect": True,
    },
    "networks": {},                    # 由用户/迁移生成，例如 {"JOU": {...}}
    "health": {
        "enabled": True,               # 开关：网络连通性检测（托盘绿/红状态）
        "interval_seconds": 60,
        "ping_target": "www.baidu.com",
        "ping_timeout_ms": 3000,
        "fail_threshold": 3,
        "restart": {
            "enabled": True,           # 开关：失败后重启网卡
            "cooldown_seconds": 300,
            "prefer_adapter_recycle": True,   # 优先禁用/启用网卡，权限不足时降级为断线重连
            "reconnect_after_restart": True,
        },
    },
    "schedules": [],                   # 智能闹钟式计划规则，见 scheduler.py
    "traffic": {
        "enabled": True,               # 流量保护总开关（各网络的 guard.enabled 为分开关）
        "sample_interval_seconds": 2,
        "inspect_processes": True,
        "top_processes": 5,
        "defaults": copy.deepcopy(DEFAULT_NETWORK["guard"]),
    },
    "portal": {
        "driver": "auto",              # auto | browser | requests
        "browser": "edge",             # edge | chrome
        "headless": False,
        "timeout_seconds": 30,
        "js_wait_seconds": 2,
        "allow_requests_fallback": True,
        "verify_tls": False,
        "plugins_dir": "",             # 空 = 程序目录下 plugins/
        "auto_discover_options": False,  # 登录前用浏览器按插件 JS 规则回读自定义选项
    },
    "popup": {
        "enabled": True,
        "title": "CampusNet 提醒",
        "timeout_seconds": 0,          # 0 = 一直等待用户操作
        "deny_keeps_disconnected": True,
    },
    "logging": {
        "level": "INFO",
        "max_bytes": 2097152,
        "backup_count": 5,
        "memory_records": 500,
    },
}


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def deep_merge(base, override):
    """把 override 合并进 base 的副本（base 提供默认值，override 优先）。"""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on", "是"):
            return True
        if v in ("0", "false", "no", "off", "否"):
            return False
    return default


def normalize_guard(raw: dict | None, fallback: dict | None = None) -> dict:
    """规范化单个网络的流量保护配置，单位非法时回退到默认单位。"""
    from . import traffic  # 延迟导入，避免 config <-> traffic 循环依赖

    base = copy.deepcopy(fallback or DEFAULT_NETWORK["guard"])
    raw = raw if isinstance(raw, dict) else {}
    guard = deep_merge(base, raw)

    speed = guard.get("speed") or {}
    if not isinstance(speed, dict):
        speed = {"value": speed, "unit": base["speed"]["unit"]}
    guard["speed"] = {
        "value": max(0.0, _as_float(speed.get("value"), base["speed"]["value"])),
        "unit": traffic.normalize_speed_unit(speed.get("unit"), base["speed"]["unit"]),
    }
    volume = guard.get("volume") or {}
    if not isinstance(volume, dict):
        volume = {"value": volume, "unit": base["volume"]["unit"]}
    guard["volume"] = {
        "value": max(0.0, _as_float(volume.get("value"), base["volume"]["value"])),
        "unit": traffic.normalize_volume_unit(volume.get("unit"), base["volume"]["unit"]),
    }
    guard["enabled"] = _as_bool(guard.get("enabled"), False)
    guard["sustained_seconds"] = max(1, _as_int(guard.get("sustained_seconds"), 10))
    guard["sample_interval_seconds"] = max(1, _as_int(guard.get("sample_interval_seconds"), 2))
    guard["deny_keeps_disconnected"] = _as_bool(guard.get("deny_keeps_disconnected"), True)
    guard["inspect_processes"] = _as_bool(guard.get("inspect_processes"), True)
    guard["top_processes"] = max(0, _as_int(guard.get("top_processes"), 5))
    return guard


def normalize_network(name: str, raw: dict | None, guard_fallback: dict | None = None) -> dict:
    net = deep_merge(DEFAULT_NETWORK, raw if isinstance(raw, dict) else {})
    net["name"] = name
    net["profile"] = str(net.get("profile") or "").strip() or name
    net["plugin"] = str(net.get("plugin") or "").strip() or name
    net["need_login"] = _as_bool(net.get("need_login"), False)
    login = net.get("login") or {}
    if not isinstance(login, dict):
        login = {}
    login["enabled"] = None if login.get("enabled") is None else _as_bool(login.get("enabled"))
    login["url"] = str(login.get("url") or "").strip()
    login["driver"] = str(login.get("driver") or "").strip().lower()
    login["credentials"] = {str(k): "" if v is None else str(v)
                            for k, v in (login.get("credentials") or {}).items()}
    login["options"] = dict(login.get("options") or {})
    login["timeout_seconds"] = max(0, _as_int(login.get("timeout_seconds"), 0))
    net["login"] = login
    net["guard"] = normalize_guard(net.get("guard"), guard_fallback)
    return net


def normalize_schedule(raw: dict | None, index: int = 0) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    repeat = raw.get("repeat") if isinstance(raw.get("repeat"), dict) else {}
    mode = str(repeat.get("mode") or "daily").strip().lower()
    if mode not in ("once", "daily", "weekly", "monthly"):
        mode = "daily"
    weekdays = [int(d) for d in (repeat.get("weekdays") or []) if str(d).isdigit() and 1 <= int(d) <= 7]
    days = [int(d) for d in (repeat.get("days") or []) if str(d).lstrip("-").isdigit()]
    months = [int(m) for m in (repeat.get("months") or []) if str(m).isdigit() and 1 <= int(m) <= 12]
    rule = {
        "id": str(raw.get("id") or f"rule-{int(time.time())}-{index}"),
        "name": str(raw.get("name") or f"计划 {index + 1}"),
        "enabled": _as_bool(raw.get("enabled"), True),
        "action": str(raw.get("action") or "connect").strip().lower(),
        "target_network": str(raw.get("target_network") or "").strip(),
        "need_login": None if raw.get("need_login") is None else _as_bool(raw.get("need_login")),
        "time": str(raw.get("time") or "00:00").strip(),
        "window_minutes": max(0, _as_int(raw.get("window_minutes"), 180)),
        "retry_interval_seconds": max(0, _as_int(raw.get("retry_interval_seconds"), 300)),
        "max_attempts_per_day": max(0, _as_int(raw.get("max_attempts_per_day"), 10)),
        "repeat": {
            "mode": mode,
            "weekdays": sorted(set(weekdays)),
            "days": sorted(set(days)),
            "months": sorted(set(months)),
            "date": str(repeat.get("date") or "").strip(),
        },
    }
    # 时间格式兜底
    try:
        hh, mm = rule["time"].split(":")
        rule["time"] = f"{int(hh):02d}:{int(mm):02d}"
    except Exception:  # noqa: BLE001
        rule["time"] = "00:00"
    return rule


def normalize(cfg: dict | None) -> dict:
    """把任意输入配置规范化成完整配置。"""
    cfg = deep_merge(DEFAULT_CONFIG, cfg if isinstance(cfg, dict) else {})
    guard_fallback = normalize_guard(cfg["traffic"].get("defaults"))
    cfg["traffic"]["defaults"] = guard_fallback

    networks = {}
    for name, raw in (cfg.get("networks") or {}).items():
        if not str(name).strip():
            continue
        networks[str(name)] = normalize_network(str(name), raw, guard_fallback)
    cfg["networks"] = networks

    if not isinstance(cfg.get("schedules"), list):
        cfg["schedules"] = []
    cfg["schedules"] = [normalize_schedule(r, i) for i, r in enumerate(cfg["schedules"])]

    cfg["health"]["enabled"] = _as_bool(cfg["health"].get("enabled"), True)
    cfg["health"]["interval_seconds"] = max(5, _as_int(cfg["health"].get("interval_seconds"), 60))
    cfg["health"]["ping_timeout_ms"] = max(200, _as_int(cfg["health"].get("ping_timeout_ms"), 3000))
    cfg["health"]["fail_threshold"] = max(1, _as_int(cfg["health"].get("fail_threshold"), 3))
    cfg["health"]["restart"]["enabled"] = _as_bool(cfg["health"]["restart"].get("enabled"), True)
    cfg["health"]["restart"]["cooldown_seconds"] = max(0, _as_int(
        cfg["health"]["restart"].get("cooldown_seconds"), 300))

    cfg["traffic"]["sample_interval_seconds"] = max(1, _as_int(
        cfg["traffic"].get("sample_interval_seconds"), 2))

    cfg["portal"]["driver"] = str(cfg["portal"].get("driver") or "auto").lower()
    if cfg["portal"]["driver"] not in ("auto", "browser", "requests"):
        cfg["portal"]["driver"] = "auto"
    cfg["portal"]["browser"] = str(cfg["portal"].get("browser") or "edge").lower()
    if cfg["portal"]["browser"] not in ("edge", "chrome"):
        cfg["portal"]["browser"] = "edge"
    theme = str((cfg["app"].get("ui") or {}).get("theme") or "light").lower()
    cfg["app"]["ui"]["theme"] = theme if theme in ("light", "dark") else "light"
    return cfg


def validate(cfg: dict) -> list:
    """返回配置问题列表（空列表表示无问题）。仅告警，不阻断运行。"""
    problems = []
    if cfg["portal"]["driver"] == "auto" and not cfg["portal"]["allow_requests_fallback"]:
        problems.append("portal.driver=auto 且禁用了 requests 兜底，浏览器通道失败后将无法登录")
    for name, net in cfg["networks"].items():
        if net["need_login"] and not net["login"]["url"]:
            problems.append(f"网络 {name} 需要登录但未配置登录页 URL（将使用插件的默认 URL）")
        guard = net["guard"]
        if guard["enabled"] and guard["speed"]["value"] <= 0 and guard["volume"]["value"] <= 0:
            problems.append(f"网络 {name} 开启了流量保护但阈值全为 0")
    ids = [r["id"] for r in cfg["schedules"]]
    if len(ids) != len(set(ids)):
        problems.append("计划规则的 id 存在重复")
    for rule in cfg["schedules"]:
        if rule["enabled"] and rule["action"] == "connect" and not rule["target_network"]:
            problems.append(f"计划规则 {rule['id']} 未指定目标网络")
        if rule["repeat"]["mode"] == "weekly" and not rule["repeat"]["weekdays"]:
            problems.append(f"计划规则 {rule['id']} 为每周模式但未选择星期")
        if rule["repeat"]["mode"] == "monthly" and not rule["repeat"]["days"]:
            problems.append(f"计划规则 {rule['id']} 为每月模式但未选择日期")
        if rule["repeat"]["mode"] == "once" and not rule["repeat"]["date"]:
            problems.append(f"计划规则 {rule['id']} 为仅一次模式但未指定日期")
    return problems


# --------------------------------------------------------------------------- #
# Config 对象
# --------------------------------------------------------------------------- #
class Config:
    """配置对象。所有 core 模块都接收它的 .data（普通 dict），保持无状态耦合。"""

    def __init__(self, data: dict | None = None, path: str | None = None):
        self.path = path or paths.CONFIG_FILE
        self.data = normalize(data)

    # ---- 读写 ----
    @classmethod
    def load(cls, path: str | None = None, create_if_missing: bool = True) -> "Config":
        path = path or paths.CONFIG_FILE
        raw = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if not isinstance(raw, dict):
                    get_logger().warning("配置文件顶层不是对象，已忽略：%s", path)
                    raw = {}
            except Exception as e:  # noqa: BLE001
                get_logger().error("配置读取失败（将使用默认值）：%s", e)
                raw = {}
        elif create_if_missing:
            get_logger().info("未找到配置文件 %s，尝试从旧配置迁移或使用默认值", path)
            cfg = cls(None, path)
            cfg.save()
            return cfg
        return cls(raw, path)

    def save(self, path: str | None = None) -> str:
        target = path or self.path
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        tmp = f"{target}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        return target

    # ---- 访问 ----
    def get(self, dotted: str, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    @property
    def networks(self) -> dict:
        return self.data["networks"]

    def network(self, name: str) -> dict | None:
        return self.data["networks"].get(name)

    def ensure_network(self, name: str) -> dict:
        if name not in self.data["networks"]:
            self.data["networks"][name] = normalize_network(name, {}, self.data["traffic"]["defaults"])
        return self.data["networks"][name]

    def validate(self) -> list:
        return validate(self.data)


# --------------------------------------------------------------------------- #
# 旧配置迁移
# --------------------------------------------------------------------------- #
def _first(mapping: dict, *keys, default=None):
    for k in keys:
        if isinstance(mapping, dict) and k in mapping and mapping[k] not in (None, ""):
            return mapping[k]
    return default


def migrate_from_legacy(legacy: dict) -> tuple:
    """把旧单体程序配置转换为新配置。

    返回 (new_config_dict, report_list)。识别不到的键会忽略并记入报告。
    """
    report = []
    legacy = legacy if isinstance(legacy, dict) else {}
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    old_wlan = legacy.get("wlan") or {}
    old_sched = legacy.get("schedule") or {}
    old_health = legacy.get("health") or {}
    old_guard = legacy.get("traffic_guard") or {}
    old_portal = legacy.get("portal") or {}
    old_logging = legacy.get("logging") or {}

    iface = str(old_wlan.get("interface") or "").strip()
    cfg["wlan"]["interface"] = iface or "auto"
    cfg["wlan"]["connect_timeout"] = _as_int(old_wlan.get("connect_timeout"), 25)
    if iface:
        report.append(f"wlan.interface = {iface}")

    billing = str(_first(old_wlan, "billing_profile", "billing_ssid", default="") or "").strip()
    campus = str(_first(old_wlan, "campus_profile", "campus_ssid", default="") or "").strip()

    # 账号 / 密码 / 运营商 / 登录页 —— 全部落到“校园网络”的登录配置与 JOU 插件上
    account = str(_first(old_portal, "account", "username", default="") or "")
    password = str(_first(old_portal, "password", default="") or "")
    isp = str(_first(old_portal, "isp", default="") or "")
    url = str(_first(old_portal, "url", "login_url", default="") or "")

    guard = {
        "enabled": _as_bool(_first(old_guard, "enabled", default=False), False),
        "speed": {"value": _as_float(_first(old_guard, "speed_threshold_mbps", "speed_threshold_mb",
                                            default=2.0), 2.0), "unit": "MB/s"},
        "sustained_seconds": _as_int(old_guard.get("sustained_seconds"), 10),
        "volume": {"value": _as_float(_first(old_guard, "cumulative_limit_mb", "cumulative_limit",
                                             default=50.0), 50.0), "unit": "MB"},
        "sample_interval_seconds": _as_int(old_guard.get("sample_interval_seconds"), 2),
        "deny_keeps_disconnected": _as_bool(old_guard.get("deny_keeps_disconnected"), True),
    }

    networks = {}
    if billing:
        networks[billing] = {
            "profile": billing,
            "label": "计费网络",
            "need_login": False,
            "plugin": billing,
            "guard": dict(guard),
        }
        report.append(f"networks[{billing}]：计费网络，流量保护启用={guard['enabled']}，"
                      f"阈值 {guard['speed']['value']} {guard['speed']['unit']} / "
                      f"{guard['volume']['value']} {guard['volume']['unit']}")
    if campus:
        networks[campus] = {
            "profile": campus,
            "label": "校园网络",
            "need_login": True,
            "plugin": campus,
            "login": {
                "url": url,
                "driver": "",
                "credentials": {"account": account, "password": password},
                "options": {"isp": isp} if isp else {},
            },
            "guard": {"enabled": False},
        }
        report.append(f"networks[{campus}]：校园网络，需要登录，插件={campus}，"
                      f"登录页={url or '（用插件默认）'}，运营商={isp or '（未设置）'}")
    cfg["networks"] = networks

    if not networks:
        report.append("旧配置中未找到 billing_profile / campus_profile，networks 保持为空，"
                      "请在 GUI 中添加网络")

    # ---- 计划规则 ----
    schedules = []
    window = _as_int(old_sched.get("window_minutes"), 180)
    retry = _as_int(old_sched.get("retry_interval_seconds"), 300)
    max_attempts = _as_int(old_sched.get("max_attempts_per_day"), 10)
    billing_days = [int(d) for d in (old_sched.get("billing_weekdays") or [])]
    campus_days = [int(d) for d in (old_sched.get("campus_weekdays") or [])]
    if billing:
        schedules.append({
            "id": "legacy-billing",
            "name": f"连接计费网络 {billing}",
            "enabled": True,
            "action": "connect",
            "target_network": billing,
            "need_login": False,
            "time": str(old_sched.get("billing_time") or "22:00"),
            "window_minutes": window,
            "retry_interval_seconds": retry,
            "max_attempts_per_day": max_attempts,
            "repeat": {"mode": "weekly", "weekdays": billing_days or [1, 2, 3, 4]},
        })
        report.append(f"计划规则 legacy-billing：每周 {billing_days or [1,2,3,4]} "
                      f"{old_sched.get('billing_time') or '22:00'} → {billing}")
    if campus:
        schedules.append({
            "id": "legacy-campus",
            "name": f"切换到校园网络 {campus}",
            "enabled": True,
            "action": "connect",
            "target_network": campus,
            "need_login": True,
            "time": str(old_sched.get("campus_time") or "06:10"),
            "window_minutes": window,
            "retry_interval_seconds": retry,
            "max_attempts_per_day": max_attempts,
            "repeat": {"mode": "weekly", "weekdays": campus_days or [2, 3, 4, 5]},
        })
        report.append(f"计划规则 legacy-campus：每周 {campus_days or [2,3,4,5]} "
                      f"{old_sched.get('campus_time') or '06:10'} → {campus}（登录）")
    cfg["schedules"] = schedules

    # ---- 健康检查 ----
    cfg["health"].update({
        "enabled": _as_bool(old_health.get("enabled"), True),
        "interval_seconds": _as_int(old_health.get("interval_seconds"), 60),
        "ping_target": str(old_health.get("ping_target") or "www.baidu.com"),
        "ping_timeout_ms": _as_int(old_health.get("ping_timeout_ms"), 3000),
        "fail_threshold": _as_int(old_health.get("fail_threshold"), 3),
    })
    cfg["health"]["restart"].update({
        "enabled": _as_bool(old_health.get("restart_adapter"), True),
        "cooldown_seconds": _as_int(old_health.get("restart_cooldown_seconds"), 300),
    })
    report.append(f"health：检测开关={cfg['health']['enabled']}，"
                  f"重启网卡开关={cfg['health']['restart']['enabled']}，"
                  f"目标={cfg['health']['ping_target']}，间隔={cfg['health']['interval_seconds']}s")

    # ---- 浏览器/请求通道 ----
    method = str(_first(old_portal, "method", default="auto") or "auto").lower()
    cfg["portal"]["driver"] = {"selenium": "browser", "browser": "browser",
                               "requests": "requests"}.get(method, "auto")
    cfg["portal"]["timeout_seconds"] = _as_int(old_portal.get("timeout"), 30)
    cfg["portal"]["verify_tls"] = _as_bool(old_portal.get("verify"), False)
    endpoints = old_portal.get("eportal_endpoints") or []
    if endpoints:
        report.append(f"portal.eportal_endpoints（{len(endpoints)} 条）已迁移到 plugins/{campus or 'JOU'}"
                      f"/manifest.json 的 http.attempts，可继续自定义")

    # ---- 日志 ----
    cfg["logging"].update({
        "level": str(old_logging.get("level") or "INFO"),
        "max_bytes": _as_int(old_logging.get("max_bytes"), 2097152),
        "backup_count": _as_int(old_logging.get("backup_count"), 5),
    })

    cfg = normalize(cfg)
    report.append("已去除全部硬编码：SSID/账号/密码/运营商/阈值/时间均改为配置或插件提供")
    return cfg, report


def load_legacy_config(path: str | None = None) -> dict:
    path = path or paths.find_legacy_config()
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        get_logger().warning("旧配置读取失败：%s", e)
        return {}


def ensure_config(path: str | None = None, force_migrate: bool = False) -> tuple:
    """确保配置文件存在。

    返回 (Config, report)。若配置不存在且能找到旧配置，则自动迁移。
    """
    path = path or paths.CONFIG_FILE
    report = []
    if force_migrate or not os.path.isfile(path):
        legacy = load_legacy_config()
        if legacy:
            data, report = migrate_from_legacy(legacy)
            cfg = Config(data, path)
            cfg.save()
            return cfg, report
        cfg = Config(None, path)
        cfg.save()
        report.append("未找到旧配置，已生成默认配置（networks 为空，请在 GUI 或 plugins 中添加）")
        return cfg, report
    return Config.load(path), report
