# -*- coding: utf-8 -*-
"""运行时状态持久化与跨进程互斥。

state.json 内容（全部为可选键，读取时自动补默认值）：
    daemon_pid / daemon_start / heartbeat    后台服务心跳（供 GUI 与计划任务判断存活）
    last_ssid / current_profile              当前连接的网络（重启网卡后用于回连）
    session                                  单次连接会话（起止时间、起止计数器）
    last_run / last_attempt / attempts       调度规则的执行记录（按规则 id，按天）
    health_fail_count / last_restart_ts      连通性巡检的失败计数与重启冷却
    guard                                     流量保护运行时（按网络名分桶）
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from . import paths
from .logging_setup import get_logger

_local_lock = threading.RLock()


def today_key(day: datetime | None = None) -> str:
    return (day or datetime.now()).date().isoformat()


def load_state() -> dict:
    path = paths.state_file()
    with _local_lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as e:  # noqa: BLE001
            get_logger().warning("状态文件解析失败，按空状态处理：%s", e)
            return {}


def save_state(state: dict) -> None:
    """原子写入（先写临时文件再替换），避免读到半个 JSON。"""
    path = paths.state_file()
    paths.ensure_dirs()
    with _local_lock:
        try:
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001
            get_logger().warning("状态文件写入失败：%s", e)


def update_state(**kwargs) -> dict:
    state = load_state()
    state.update(kwargs)
    save_state(state)
    return state


class ActionLock:
    """跨进程动作互斥锁（防止守护进程与计划任务同时改网络状态）。

    使用 O_CREAT|O_EXCL 原子创建；超过 stale_seconds 视为残留锁自动回收。
    """

    def __init__(self, timeout: float = 1.0, stale_seconds: float = 600):
        self.path = paths.lock_file()
        self.timeout = float(timeout)
        self.stale_seconds = float(stale_seconds)
        self.acquired = False
        self._fd = None

    def __enter__(self):
        paths.ensure_dirs()
        deadline = time.time() + self.timeout
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    age = 0.0
                if age > self.stale_seconds:
                    get_logger().warning("发现残留锁（%.0fs 前），自动回收", age)
                    self._remove()
                    continue
                if time.time() >= deadline:
                    self.acquired = False
                    return self
                time.sleep(0.1)
            except Exception as e:  # noqa: BLE001
                get_logger().warning("获取动作锁失败，按未获取处理：%s", e)
                self.acquired = False
                return self

    def __exit__(self, exc_type, exc, tb):
        self._remove()
        return False

    def _remove(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:  # noqa: BLE001
                pass
            self._fd = None
        try:
            os.remove(self.path)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# 调度规则的执行记录
# --------------------------------------------------------------------------- #
def mark_rule_done(rule_id: str, when: datetime | None = None) -> None:
    state = load_state()
    state.setdefault("last_run", {})[rule_id] = (when or datetime.now()).isoformat(timespec="seconds")
    state.setdefault("attempts", {})[rule_id] = 0
    save_state(state)


def mark_rule_attempt(rule_id: str) -> None:
    state = load_state()
    last = state.setdefault("last_attempt", {})
    last[rule_id] = time.time()
    att = state.setdefault("attempts", {})
    att[rule_id] = int(att.get(rule_id, 0)) + 1
    save_state(state)


# --------------------------------------------------------------------------- #
# 单次连接会话
# --------------------------------------------------------------------------- #
def get_session(state: dict | None = None) -> dict:
    st = state if state is not None else load_state()
    return dict(st.get("session") or {})


# --------------------------------------------------------------------------- #
# 下载流量保护运行时（按网络名分桶）
# --------------------------------------------------------------------------- #
def guard_bucket(state: dict, network: str, create: bool = True) -> dict:
    guards = state.setdefault("guard", {}) if create else (state.get("guard") or {})
    if not create:
        return guards.get(network) or {}
    return guards.setdefault(network, {})


def allowlist_add(state: dict, network: str, process_name: str, day: str | None = None) -> None:
    day = day or today_key()
    node = state.setdefault("allowlist", {}).setdefault(network, {})
    names = node.setdefault(day, [])
    if process_name and process_name not in names:
        names.append(process_name)


def allowlist_has(state: dict, network: str, process_name: str, day: str | None = None) -> bool:
    day = day or today_key()
    node = (state.get("allowlist") or {}).get(network) or {}
    return process_name in (node.get(day) or [])


def allowlist_prune(state: dict, keep_days: int = 7) -> None:
    """清理过期的放行清单，避免 state.json 无限膨胀。"""
    node = state.get("allowlist") or {}
    cutoff = datetime.now().date().toordinal() - int(keep_days)
    for net, days in list(node.items()):
        for day in list(days.keys()):
            try:
                if datetime.fromisoformat(day).date().toordinal() < cutoff:
                    days.pop(day, None)
            except Exception:  # noqa: BLE001
                days.pop(day, None)
