# -*- coding: utf-8 -*-
"""后台主循环：调度 + 连通性巡检 + 下载流量保护。

被两种方式驱动（同一份逻辑，不重复实现）：
    * 守护进程：cli.py daemon → Service.run_forever()
    * GUI：QThread/threading → Service.start_background()（或 GUI 自己按 tick 驱动）

对外回调（GUI / 托盘 / 弹窗都通过它接入，核心层不依赖任何 UI 库）：
    on_status(payload)        状态变化（托盘绿/红、当前网络、流量、计划下一次触发）
    on_log(level, message)    日志
    on_event(name, payload)   事件（connected / login / traffic_trip / restart_adapter ...）
    on_need_popup(info)->bool 需要弹窗时调用；返回 True=允许继续，False=拒绝（切断）
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import config as config_mod
from . import health as health_mod
from . import logging_setup
from . import paths
from . import plugins as plugins_mod
from . import popup as popup_mod
from . import portal as portal_mod
from . import scheduler as scheduler_mod
from . import state as state_mod
from . import sysutil
from . import traffic as traffic_mod
from . import wlan


class ServiceCallbacks:
    """回调集合（全部可选）。"""

    def __init__(self, on_status=None, on_log=None, on_event=None, on_need_popup=None):
        self.on_status = on_status
        self.on_log = on_log
        self.on_event = on_event
        self.on_need_popup = on_need_popup

    def emit_status(self, payload: dict) -> None:
        if callable(self.on_status):
            try:
                self.on_status(payload)
            except Exception:  # noqa: BLE001
                pass

    def emit_log(self, level: str, message: str) -> None:
        if callable(self.on_log):
            try:
                self.on_log(level, message)
            except Exception:  # noqa: BLE001
                pass

    def emit_event(self, name: str, payload: dict) -> None:
        if callable(self.on_event):
            try:
                self.on_event(name, payload)
            except Exception:  # noqa: BLE001
                pass


class Service:
    """核心服务：一个实例即“引擎”，不含任何界面。"""

    def __init__(self, config_path: str = "", cfg: dict | None = None,
                 callbacks: ServiceCallbacks | None = None, popup_handler=None,
                 dry_run: bool = False, reconnect_sessions: bool = True):
        self.config_path = config_path or paths.CONFIG_FILE
        if cfg is not None:
            self.config = config_mod.Config(cfg, self.config_path)
        else:
            self.config, self.migration_report = config_mod.ensure_config(self.config_path)
        self.cfg = self.config.data
        self.callbacks = callbacks or ServiceCallbacks()
        self.popup_handler = popup_handler
        self.dry_run = bool(dry_run)
        self.reconnect_sessions = bool(reconnect_sessions)

        self.logger = logging_setup.setup_logging(self.cfg, console=True)
        self.state = state_mod.load_state()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

        self._config_mtime = self._file_mtime(self.config_path)
        self.plugins = plugins_mod.PluginManager(self.cfg)
        self.health = health_mod.HealthMonitor(self.cfg, on_status=None, state=self.state)
        self.scheduler = scheduler_mod.Scheduler(self.cfg, self.state)
        self.traffic = traffic_mod.TrafficManager(
            self.cfg["traffic"], on_trip=self._on_trip,
            network_guards={name: traffic_mod.merge_guard(
                self.cfg["traffic"].get("defaults"), net.get("guard"))
                for name, net in self.cfg["networks"].items()})
        self.current_network = str(self.state.get("last_ssid") or "") or None
        self._prev_recv = None
        self.last_tick_at = 0.0
        self.last_result: dict = {}
        self.started_at = time.time()

    # ------------------------------------------------------------------ #
    # 配置 / 状态
    # ------------------------------------------------------------------ #
    @staticmethod
    def _file_mtime(path: str) -> float:
        try:
            import os
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    def reload_config(self, force: bool = False) -> bool:
        """重新读取配置（GUI 改完配置后调用；守护进程按 mtime 自动重载）。"""
        mtime = self._file_mtime(self.config_path)
        if not force and mtime == self._config_mtime:
            return False
        with self._lock:
            self.config = config_mod.Config.load(self.config_path)
            self.cfg = self.config.data
            self._config_mtime = mtime
            self.plugins.cfg = self.cfg
            self.plugins.maybe_reload(min_interval=0)
            self.health.reload(self.cfg, self.state)
            self.scheduler.reload(self.cfg, self.state)
            self.traffic.traffic_cfg = self.cfg["traffic"]
            for name, net in self.cfg["networks"].items():
                self.traffic.guard_for(name, traffic_mod.merge_guard(
                    self.cfg["traffic"].get("defaults"), net.get("guard")))
        self.logger.info("配置已重新加载：%s", self.config_path)
        self.callbacks.emit_event("config_reloaded", {"path": self.config_path})
        return True

    def save_state(self) -> None:
        state_mod.save_state(self.state)

    def _log(self, level: str, message: str) -> None:
        getattr(self.logger, level, self.logger.info)(message)
        self.callbacks.emit_log(level, message)

    # ------------------------------------------------------------------ #
    # 网络会话（连上 → 断开 的流量统计与保护生命周期）
    # ------------------------------------------------------------------ #
    def network_config(self, name: str) -> dict:
        net = self.cfg["networks"].get(name)
        if net is None:
            net = config_mod.normalize_network(name, {}, self.cfg["traffic"]["defaults"])
        return net

    def guard_config(self, name: str) -> dict:
        """某个 WiFi 的**生效**保护配置：全局默认值 + 该 WiFi 显式配置（后者优先）。

        这样即使配置里只写了 ``"guard": {"enabled": true}``，缺失的阈值也会
        继承 ``traffic.defaults``，不会退化成“阈值为 0 = 永不触发”。
        """
        net = self.network_config(name)
        return traffic_mod.merge_guard(self.cfg["traffic"].get("defaults"), net.get("guard"))

    def match_network_by_ssid(self, ssid: str) -> str:
        if not ssid:
            return ""
        for name, net in self.cfg["networks"].items():
            if name == ssid or (net.get("profile") or "") == ssid:
                return name
        return ""

    def _switch_session(self, old: str, new: str) -> dict:
        info = {"from": old or "", "to": new or ""}
        if old:
            guard = self.traffic.guards.get(old)
            if guard is not None:
                summary = guard.stop_session()
                info["previous"] = summary
                self._log("info", f"[{old}] 本次连接下行 {sysutil.human_bytes(summary.get('total_recv', 0))}")
        if new:
            guard = self.traffic.guard_for(new, self.guard_config(new))
            guard.start_session()
            self.state["session"] = {
                "network": new,
                "started_at": time.time(),
                "started_iso": datetime.now().isoformat(timespec="seconds"),
            }
        else:
            self.state.pop("session", None)
        self.state["last_ssid"] = new or ""
        self.current_network = new or None
        self.callbacks.emit_event("network_changed", info)
        if new:
            self._log("info", f"当前网络切换到 {new}")
        return info

    def sync_connection(self) -> dict:
        """同步当前 WLAN 连接状态，必要时切换流量会话。"""
        conn = wlan.current_connection(self.cfg)
        ssid = conn.get("ssid") if conn.get("connected") else ""
        if ssid != (self.current_network or ""):
            self._switch_session(self.current_network or "", ssid)
        self.state["current_profile"] = ssid
        conn["network"] = self.match_network_by_ssid(ssid) or ssid
        conn["configured"] = bool(self.match_network_by_ssid(ssid))
        return conn

    # ------------------------------------------------------------------ #
    # 连接 / 登录 / 断开
    # ------------------------------------------------------------------ #
    def connect_network(self, name: str, need_login: bool | None = None,
                        wait: bool = True, timeout: float | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "message": "未指定目标网络"}
        net = self.network_config(name)
        profile = net.get("profile") or name

        if not self.plugins.maybe_reload():
            self.logger.debug("插件无变化，沿用已加载插件")
        lock = state_mod.ActionLock(timeout=0.5, stale_seconds=300)
        with lock:
            if not lock.acquired:
                return {"ok": False, "message": "已有另一个进程正在执行网络操作，本次跳过"}
            result = wlan.connect(profile, self.cfg, timeout=timeout, wait=wait)
        result["network"] = name
        self.callbacks.emit_event("connect", result)
        if not result.get("ok"):
            self._log("warning", f"连接 {name} 失败：{result.get('message')}")
            return result

        self._log("info", f"已连接 {name}（{result.get('seconds')}s）")
        self.sync_connection()

        if need_login is None:
            need_login = bool(net.get("need_login"))
        if need_login:
            login_result = self.ensure_login(name)
            result["login"] = login_result
            result["ok"] = bool(result.get("ok") and login_result.get("ok", False))
            if not login_result.get("ok"):
                result["message"] = f"已连接 {name}，但登录未成功：{login_result.get('message')}"
        return result

    def ensure_login(self, name: str, force: bool = False,
                     probe_options: bool = False) -> dict:
        net = self.network_config(name)
        need_login = bool(net.get("need_login"))
        if net.get("login", {}).get("enabled") is not None:
            need_login = bool(net["login"]["enabled"])
        if not need_login and not force:
            return {"ok": True, "skipped": True, "message": f"{name} 配置为无需登录"}

        plugin = self.plugins.get(net.get("plugin") or name)
        if plugin is None:
            return {"ok": False, "message": f"未找到网络 {name} 对应的登录插件"
                                            f"（plugins/{net.get('plugin') or name}/）"}
        if plugin.errors:
            return {"ok": False, "message": "插件校验未通过：" + "；".join(plugin.errors)}

        ctx_extra = {}
        if probe_options or self.cfg["portal"].get("auto_discover_options"):
            probe = portal_mod.probe_options(plugin, net.get("login", {}).get("url"),
                                             self.cfg["portal"])
            if probe.get("ok"):
                discovered = {item.get("key"): item.get("default")
                              for item in (probe.get("options") or []) if item.get("key")}
                # 登录页回读的选项作为默认值，用户显式配置的值优先
                merged = dict(discovered)
                merged.update(net.get("login", {}).get("options") or {})
                ctx_extra["options"] = merged
                self._log("info", f"[{name}] 已按 login.js 规则回读 {len(discovered)} 个自定义选项")

        result = portal_mod.login(net, plugin, self.cfg["portal"], ctx_extra,
                                  plugins_map=self.plugins.plugins)
        record = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "ok": bool(result.get("ok")),
            "method": result.get("method"),
            "message": result.get("message"),
        }
        self.state.setdefault("login", {})[name] = record
        self.save_state()
        self.callbacks.emit_event("login", {"network": name, **record})
        if result.get("ok"):
            self._log("info", f"[{name}] 登录成功（{result.get('method')}）")
        else:
            self._log("warning", f"[{name}] 登录失败：{result.get('message')}")
        return result

    def disconnect(self, reason: str = "") -> dict:
        lock = state_mod.ActionLock(timeout=0.5, stale_seconds=300)
        with lock:
            if not lock.acquired:
                return {"ok": False, "message": "已有另一个进程正在执行网络操作"}
            result = wlan.disconnect(self.cfg)
        if result.get("ok"):
            self._log("info", f"已断开 WLAN{'（' + reason + '）' if reason else ''}")
            self._switch_session(self.current_network or "", "")
        else:
            self._log("warning", f"断开失败：{result.get('message')}")
        self.callbacks.emit_event("disconnect", result)
        return result

    # ------------------------------------------------------------------ #
    # 三个守护任务
    # ------------------------------------------------------------------ #
    def schedule_tick(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        if not self.plugins.maybe_reload():
            pass
        due = self.scheduler.due_rules(now)
        handled = []
        for rule in due:
            rid = rule.get("id")
            allowed, reason = scheduler_mod.can_attempt(rule, self.state, now)
            if not allowed:
                self._log("debug", f"计划 {rid} 暂不执行：{reason}")
                continue
            scheduler_mod.bump_attempt(self.state, rid, now)
            target = rule.get("target_network") or ""
            action = (rule.get("action") or "connect").lower()
            self._log("info", f"执行计划 {rid}（{action} → {target}）")

            if self.dry_run:
                result = {"ok": True, "dry_run": True, "message": "演练模式：未实际执行"}
            elif action == "check":
                result = health_mod.check(self.cfg)
            elif action == "reconnect":
                result = wlan.reconnect(self.cfg,
                                        profile=self.network_config(target).get("profile") if target else "")
            else:
                result = self.connect_network(target, need_login=rule.get("need_login"))

            ok = bool(result.get("ok"))
            if ok:
                scheduler_mod.mark_done(self.state, rid, now)
            handled.append({
                "id": rid, "action": action, "target": target, "ok": ok,
                "message": result.get("message", ""),
                "retry_in_seconds": int(rule.get("retry_interval_seconds") or 0) if not ok else 0,
            })
            self.callbacks.emit_event("schedule_run", handled[-1])
        if handled:
            self.save_state()
        return {"due": len(due), "handled": handled}

    def health_tick(self, now: float | None = None, allow_restart: bool = True) -> dict:
        result = self.health.tick(now or time.time(), allow_restart=allow_restart)
        self.state["health_fail_count"] = self.health.fail_count
        self.state["health"] = {k: v for k, v in result.items() if k != "restart"}
        if result.get("restarted"):
            self.callbacks.emit_event("restart_adapter", result.get("restart") or {})
        return result

    def traffic_tick(self, interval_ok: bool = True) -> dict:
        """流量采样 + 下载保护判定。

        **采样与保护解耦**：只要「流量统计总开关」打开，就持续采样并统计实时速率与
        本会话累计流量（供界面显示）；是否按阈值弹窗切断，取决于该 WiFi 自己的
        「下载保护」开关。未启用保护的网络也照样有实时数据。
        """
        if not self.cfg["traffic"].get("enabled", True):
            result = {"active": False, "sampling": False,
                      "message": "流量统计总开关已关闭（不采样、不保护）"}
            self._record_traffic_live(result, "")
            return result

        current = self.current_network
        if not current:
            conn = wlan.current_connection(self.cfg)
            current = self.match_network_by_ssid(conn.get("ssid") or "") or conn.get("ssid") or ""
        if not current:
            result = {"active": False, "sampling": False, "message": "当前未连接任何 WLAN"}
            self._record_traffic_live(result, "")
            return result

        guard = self.traffic.guard_for(current, self.guard_config(current))
        if not guard.session_active:
            guard.start_session()
        result = guard.tick(wlan.detect_interface(self.cfg), enforce=guard.cfg.enabled)
        if not result.get("enabled"):
            result["message"] = f"{current} 未启用下载保护（仍在统计实时速率）"
        self.state.setdefault("guard", {})[current] = {
            "down_bps": result.get("down_bps"),
            "up_bps": result.get("up_bps"),
            "total_recv": result.get("total_recv"),
            "total_sent": result.get("total_sent"),
            "should_trip": result.get("should_trip"),
            "at": time.time(),
        }
        self._record_traffic_live(result, current)
        return result

    def _record_traffic_live(self, result: dict, network: str) -> None:
        """把最近一次采样的“是否在采样 / 原因”写进状态，供界面显示提示。"""
        self.state["traffic_live"] = {
            "active": bool(result.get("active")),
            "sampling": bool(result.get("sampling")),
            "enabled": bool(result.get("enabled")),
            "network": network or "",
            "message": result.get("message") or "",
            "at": time.time(),
        }

    # ------------------------------------------------------------------ #
    # 弹窗（行为与原实现一致）
    # ------------------------------------------------------------------ #
    def _request_popup(self, info: dict) -> bool:
        if self.dry_run:
            self._log("info", "演练模式：跳过弹窗，按“拒绝”处理")
            return False
        if not self.cfg["popup"].get("enabled", True):
            self._log("warning", "弹窗已关闭，按“拒绝”处理并切断")
            return False
        if callable(self.popup_handler):
            try:
                return bool(self.popup_handler(info))
            except Exception as e:  # noqa: BLE001
                self._log("error", f"自定义弹窗回调异常，按拒绝处理：{e}")
                return False
        if callable(self.callbacks.on_need_popup):
            try:
                return bool(self.callbacks.on_need_popup(info))
            except Exception as e:  # noqa: BLE001
                self._log("error", f"弹窗回调异常，按拒绝处理：{e}")
                return False
        timeout = int(self.cfg["popup"].get("timeout_seconds") or 0)
        return popup_mod.popup_in_subprocess(info, title=self.cfg["popup"].get("title", ""),
                                            timeout=timeout)

    def _on_trip(self, info: dict) -> bool:
        """流量保护命中：弹窗询问 → 拒绝则切断（与原实现一致）。"""
        self._log("warning", f"[{info.get('network')}] 流量保护命中：{info.get('human_speed')}，"
                             f"累计 {info.get('human_total')}（{info.get('threshold')}）")
        self.callbacks.emit_event("traffic_trip", info)
        allowed = self._request_popup(info)
        info["user_allowed"] = allowed
        guard_cfg = self.guard_config(info.get("network") or "")
        keep = bool(guard_cfg.get("deny_keeps_disconnected", True))
        if not allowed:
            if keep:
                cut = self.disconnect(reason="流量保护触发，用户选择切断")
                info["disconnected"] = bool(cut.get("ok"))
            else:
                info["disconnected"] = False
                self._log("warning", "该网络配置为“拒绝后不自动切断”，仅记录")
            return False
        self._log("info", "用户选择继续使用，本次流量保护不再弹窗（累计值已重置）")
        return True

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #
    def tick(self, now: datetime | None = None, do_health: bool = True,
             do_traffic: bool = True, do_schedule: bool = True,
             sync: bool = True) -> dict:
        now = now or datetime.now()
        self.reload_config()
        events = {"at": now.isoformat(timespec="seconds")}
        if sync:
            events["connection"] = self.sync_connection()
        if do_schedule:
            events["schedule"] = self.schedule_tick(now)
        if do_health:
            events["health"] = self.health_tick(allow_restart=True)
        if do_traffic:
            events["traffic"] = self.traffic_tick()
        self.last_tick_at = time.time()
        self.last_result = events
        self._write_heartbeat()
        self._emit_status()
        return events

    def _write_heartbeat(self) -> None:
        self.state["daemon_pid"] = self.state.get("daemon_pid") or 0
        self.state["heartbeat"] = time.time()
        self.state["daemon_start"] = self.state.get("daemon_start") or self.started_at
        self.save_state()

    def run_forever(self, interval: float | None = None, max_ticks: int = 0) -> None:
        """守护进程主循环。interval 为最小轮询间隔（默认 2 秒）。"""
        import os
        poll = float(interval or 2.0)
        self.state["daemon_pid"] = os.getpid()
        self.state["daemon_start"] = time.time()
        self.state["heartbeat"] = time.time()
        self.save_state()
        self._log("info", f"守护进程启动（pid={os.getpid()}，配置 {self.config_path}）")

        health_every = max(5, int(self.cfg["health"].get("interval_seconds") or 60))
        traffic_every = max(1, int(self.cfg["traffic"].get("sample_interval_seconds") or 2))
        next_health = 0.0
        next_schedule = 0.0
        next_traffic = 0.0
        next_sync = 0.0
        next_save = 0.0
        ticks = 0

        while not self._stop.is_set():
            loop_start = time.time()
            now_dt = datetime.now()
            try:
                self.reload_config()
                if loop_start >= next_sync:
                    self.sync_connection()
                    next_sync = loop_start + 5.0
                if loop_start >= next_schedule:
                    self.schedule_tick(now_dt)
                    next_schedule = loop_start + 15.0
                if loop_start >= next_health:
                    self.health_tick(allow_restart=True)
                    health_every = max(5, int(self.cfg["health"].get("interval_seconds") or 60))
                    next_health = loop_start + health_every
                if loop_start >= next_traffic:
                    self.traffic_tick()
                    traffic_every = max(1, int(self.cfg["traffic"].get("sample_interval_seconds") or 2))
                    next_traffic = loop_start + traffic_every
                if loop_start >= next_save:
                    self.state["daemon_pid"] = os.getpid()
                    self.state["heartbeat"] = time.time()
                    self.state["daemon_start"] = self.state.get("daemon_start") or self.started_at
                    self.save_state()
                    next_save = loop_start + 30.0
                self._emit_status()
            except Exception as e:  # noqa: BLE001
                self._log("error", f"主循环异常（已跳过本轮）：{e}")
            ticks += 1
            if max_ticks and ticks >= max_ticks:
                break
            self._stop.wait(poll)
        self._log("info", "守护进程已停止")
        self.state["daemon_pid"] = 0
        self.save_state()

    def start_background(self, interval: float | None = None) -> threading.Thread:
        """GUI 可用：把主循环放到后台线程。"""
        if self._thread and self._thread.is_alive():
            return self._thread
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever, args=(interval,),
                                        name="campusnet-service", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------ #
    # 状态汇总（给托盘 / GUI）
    # ------------------------------------------------------------------ #
    def _emit_status(self) -> None:
        self.callbacks.emit_status(self.status())

    def _traffic_status(self) -> dict:
        """当前流量状态（供托盘 / 概览 / 流量页显示）。

        直接读取对应 TrafficGuard 的最近一次采样，不再只依赖 state["guard"]，
        避免“界面还没轮询到 / 状态未落盘”就显示空白。
        """
        total_enabled = bool(self.cfg["traffic"].get("enabled", True))
        current = self.current_network or ""
        guard = self.traffic.guards.get(current) if current else None
        live = self.traffic.live_info(current) if current else {}
        guard_cfg = self.guard_config(current) if current else {}
        sampling = bool(live.get("sampling"))
        down_bps = live.get("down_bps")
        total_recv = live.get("total_recv")
        if down_bps is None:
            fallback = (self.state.get("guard") or {}).get(current) or {}
            down_bps = fallback.get("down_bps")
            if total_recv is None:
                total_recv = fallback.get("total_recv")
            if down_bps is not None:
                sampling = True
        if not total_enabled:
            hint = "流量统计总开关已关闭"
        elif not current:
            hint = "当前未连接任何 WLAN，无流量数据"
        elif not sampling:
            hint = "正在建立采样基线，请稍候…"
        elif guard_cfg and not guard_cfg.get("enabled"):
            hint = "未启用下载保护（仅统计，不弹窗切断）"
        else:
            hint = ""
        return {
            "enabled": total_enabled,
            "sampling": sampling,
            "network": current,
            "guard_enabled": bool(guard_cfg.get("enabled")) if guard_cfg else False,
            "session_active": bool(guard.session_active) if guard else False,
            "down_bps": down_bps,
            "down_speed": traffic_mod.human_speed(down_bps or 0),
            "up_bps": live.get("up_bps"),
            "up_speed": traffic_mod.human_speed(live.get("up_bps") or 0),
            "session_recv": total_recv,
            "session_recv_human": sysutil.human_bytes(total_recv or 0),
            "session_sent": live.get("total_sent"),
            "session_sent_human": sysutil.human_bytes(live.get("total_sent") or 0),
            "session_total": (total_recv or 0) + (live.get("total_sent") or 0),
            "session_total_human": sysutil.human_bytes((total_recv or 0) + (live.get("total_sent") or 0)),
            "session_seconds": live.get("session_seconds"),
            "peak_down_bps": live.get("peak_down_bps"),
            "peak_down_speed": traffic_mod.human_speed(live.get("peak_down_bps") or 0),
            "trip_count": live.get("trip_count"),
            "message": hint,
            "guard": guard_cfg,
            "top_processes": live.get("processes") or [],
        }

    def status(self, include_profiles: bool = False, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        conn = wlan.current_connection(self.cfg)
        health_info = self.state.get("health") or {}
        online = health_info.get("online")
        if online is None:
            online = (self.health.last_result or {}).get("online")
        return {
            "app": {
                "name": self.cfg["app"]["name"],
                "version": self.cfg["app"]["version"],
                "theme": self.cfg["app"]["ui"]["theme"],
                "config_path": self.config_path,
                "dry_run": self.dry_run,
            },
            "service": {
                "running": self.running,
                "pid": self.state.get("daemon_pid") or 0,
                "started_at": self.state.get("daemon_start"),
                "heartbeat": self.state.get("heartbeat"),
                "last_tick_at": self.last_tick_at,
            },
            "connection": {
                "connected": bool(conn.get("connected")),
                "ssid": conn.get("ssid") or "",
                "state": conn.get("state") or "unknown",
                "signal": conn.get("signal"),
                "interface": conn.get("interface") or wlan.detect_interface(self.cfg),
                "current_network": self.current_network or "",
                "session": self.state.get("session") or {},
            },
            "health": {
                "enabled": bool(self.cfg["health"].get("enabled")),
                "restart_enabled": bool(self.cfg["health"]["restart"].get("enabled")),
                "online": online,           # True 绿 / False 红 / None 未知
                "message": health_info.get("message") or "",
                "latency_ms": health_info.get("latency_ms"),
                "fail_count": self.health.fail_count,
                "last_restart_ts": self.state.get("last_restart_ts"),
                "tray_color": ("green" if online else "red") if online is not None else "gray",
            },
            "traffic": self._traffic_status(),
            "popup": dict(self.cfg.get("popup") or {}),
            "schedules": self.scheduler.summary(now),
            "plugins": self.plugins.report(),
            "networks": {
                name: {
                    "label": net.get("label") or name,
                    "profile": net.get("profile"),
                    "need_login": bool(net.get("need_login")),
                    "plugin": net.get("plugin"),
                    "guard_enabled": bool(net.get("guard", {}).get("enabled")),
                    "guard": net.get("guard"),
                    "guard_effective": traffic_mod.guard_summary(self.guard_config(name)),
                } for name, net in self.cfg["networks"].items()
            },
        }

    def profiles(self) -> dict:
        """本机已保存的无线配置文件（供界面下拉选择）。"""
        return {"profiles": wlan.list_profiles(),
                "detailed": wlan.list_profiles_detailed(),
                "interface": wlan.detect_interface(self.cfg)}

    def close(self) -> None:
        self.stop()
        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.traffic.stop_all()
        except Exception:  # noqa: BLE001
            pass
        self.save_state()


def build_service(config_path: str = "", dry_run: bool = False,
                  callbacks: ServiceCallbacks | None = None) -> Service:
    """便捷入口：按配置文件构建 Service。"""
    return Service(config_path=config_path, callbacks=callbacks, dry_run=dry_run)
