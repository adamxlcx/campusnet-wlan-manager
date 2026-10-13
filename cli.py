#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CampusNet 命令行入口。

核心层 CLI，同时也是 Windows 计划任务的“单次触发”入口（GUI 未启动也能用）：
    status / daemon / connect / connect-billing / connect-campus / disconnect
    login / health-check / traffic / profiles / networks / schedules
    plugins / plugin-validate / plugin-make / migrate / selftest

所有子命令都支持 --json，便于 GUI 或计划任务解析。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from core import config as config_mod          # noqa: E402
from core import health as health_mod          # noqa: E402
from core import logging_setup                 # noqa: E402
from core import paths                         # noqa: E402
from core import plugins as plugins_mod        # noqa: E402
from core import scheduler as scheduler_mod    # noqa: E402
from core import service as service_mod        # noqa: E402
from core import state as state_mod            # noqa: E402
from core import sysutil                       # noqa: E402
from core import traffic as traffic_mod        # noqa: E402
from core import wlan                          # noqa: E402


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def fix_console_encoding() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def dump(data, as_json: bool, lines=None) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    for line in (lines or []):
        if line is not None:
            print(line)


def ok_text(result: dict, prefix: str = "完成") -> str:
    flag = "成功" if result.get("ok") else "失败"
    return f"{prefix}：{flag} — {result.get('message', '')}"


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def make_service(args) -> service_mod.Service:
    cfg_path = args.config or paths.CONFIG_FILE
    if not os.path.isfile(cfg_path):
        config_mod.ensure_config(cfg_path)
    svc = service_mod.Service(config_path=cfg_path, dry_run=getattr(args, "dry_run", False))
    if getattr(args, "verbose", False):
        logging_setup.setup_logging(svc.cfg, console=True, level="DEBUG")
    return svc


def pick_network(cfg: dict, kind: str) -> str:
    """从配置里选目标网络（不硬编码任何 SSID）。"""
    nets = cfg.get("networks") or {}
    if kind == "billing":
        for name, net in nets.items():
            label = str(net.get("label") or "")
            if "计费" in label or "billing" in name.lower():
                return name
        for name, net in nets.items():
            if (net.get("guard") or {}).get("enabled"):
                return name
        return next(iter(nets), "")
    for name, net in nets.items():
        label = str(net.get("label") or "")
        if "校园" in label or "campus" in name.lower():
            return name
    for name, net in nets.items():
        if net.get("need_login"):
            return name
    keys = list(nets)
    return keys[-1] if keys else ""


def current_network_name(cfg: dict) -> str:
    conn = wlan.current_connection(cfg)
    ssid = conn.get("ssid") or ""
    for name, net in (cfg.get("networks") or {}).items():
        if name == ssid or (net.get("profile") or "") == ssid:
            return name
    return ssid


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_status(args) -> int:
    svc = make_service(args)
    data = svc.status(include_profiles=args.profiles, now=datetime.now())
    if args.profiles:
        data["profiles"] = svc.profiles()
    health = data["health"]
    conn = data["connection"]
    traffic = data["traffic"]
    lines = [
        f"配置：{data['app']['config_path']}（主题 {data['app']['theme']}）",
        f"服务：{'运行中 pid=' + str(data['service']['pid']) if data['service']['running'] else '未运行'}",
        f"连接：{conn['ssid'] or '未连接'}（{conn['state']}，信号 {conn['signal']}，网卡 {conn['interface']}）",
        f"连通性开关：{'开' if health['enabled'] else '关'}；重启网卡开关："
        f"{'开' if health['restart_enabled'] else '关'}；托盘颜色：{health['tray_color']}"
        f"（{health['message'] or '尚未检测'}）",
        f"流量保护：{'开' if traffic['enabled'] else '关'}；当前网络 {traffic['network'] or '-'}"
        f" 下行 {traffic['down_speed']}，本次累计 {traffic['session_recv_human']}",
        f"插件 {len(data['plugins'])} 个；计划规则 {len(data['schedules'])} 条",
    ]
    if args.profiles:
        lines.append(f"本机已保存无线配置 {len(data['profiles']['profiles'])} 个")
    dump(data, args.json, lines)
    return 0


def cmd_daemon(args) -> int:
    svc = make_service(args)
    if args.ticks:
        svc.run_forever(interval=args.interval, max_ticks=args.ticks)
    else:
        svc.run_forever(interval=args.interval)
    return 0


def cmd_connect(args, kind: str = "") -> int:
    svc = make_service(args)
    name = args.network or ""
    if kind:
        name = pick_network(svc.cfg, kind)
    if not name:
        dump({"ok": False, "message": "配置中没有任何网络，请先在 GUI 添加网络或运行 migrate"},
             args.json, ["失败：配置中没有任何网络（不硬编码 SSID，需先配置）"])
        return 2
    if name not in (svc.cfg.get("networks") or {}):
        print(f"提示：{name} 不在配置的 networks 中，将按同名无线配置文件尝试连接")
    result = svc.connect_network(name, need_login=False if args.no_login else None,
                                 wait=not args.no_wait, timeout=args.timeout)
    dump(result, args.json, [ok_text(result, f"连接 {name}")])
    return 0 if result.get("ok") else 1


def cmd_disconnect(args) -> int:
    svc = make_service(args)
    result = svc.disconnect(reason="命令行")
    dump(result, args.json, [ok_text(result, "断开 WLAN")])
    return 0 if result.get("ok") else 1


def cmd_login(args) -> int:
    svc = make_service(args)
    name = args.network or current_network_name(svc.cfg)
    if not name:
        dump({"ok": False, "message": "未指定网络且当前未连接任何 WLAN"}, args.json,
             ["失败：未指定网络（--network），且当前未连接 WLAN"])
        return 2
    result = svc.ensure_login(name, force=args.force or None, probe_options=args.probe_options)
    result = result if isinstance(result, dict) else {"ok": False, "message": "登录返回异常"}
    dump(result, args.json, [ok_text(result, f"登录 {name}")])
    return 0 if result.get("ok") else 1


def cmd_health_check(args) -> int:
    svc = make_service(args)
    result = health_mod.check(svc.cfg)
    if args.restart:
        result["restart"] = svc.health.restart_once()
    keys = ("online", "enabled", "fail_count", "threshold", "latency_ms", "message",
            "target", "method", "local_ip", "checked_at")
    result.setdefault("online", result.get("ok"))
    svc.state["health"] = {k: result.get(k) for k in keys if result.get(k) is not None}
    svc.save_state()
    lines = [f"连通性：{'通' if result.get('ok') else '不通'}（{result.get('message')}）"]
    if args.restart:
        lines.append(ok_text(result["restart"], "重启网卡"))
    dump(result, args.json, lines)
    return 0 if result.get("ok") else 1


def cmd_traffic(args) -> int:
    svc = make_service(args)
    name = args.network or current_network_name(svc.cfg)
    iface = wlan.detect_interface(svc.cfg)
    result = traffic_mod.measure(interface=iface, network=name, duration=args.duration,
                                 interval=args.interval)
    if not result.get("ok"):
        dump(result, args.json, [f"失败：{result.get('reason')}"])
        return 1
    lines = [
        f"网络：{result['network'] or '-'}（网卡 {result['interface']}）",
        f"上行：{sysutil.human_bytes(result['bytes_sent'])}，下行：{sysutil.human_bytes(result['bytes_recv'])}",
        f"合计：{sysutil.human_bytes(result['bytes_total'])}，时长：{sysutil.human_duration(result['duration'])}",
        f"峰值下行：{traffic_mod.human_speed(result['peak_down_bps'])}",
    ]
    dump(result, args.json, lines)
    return 0


def cmd_profiles(args) -> int:
    svc = make_service(args)
    data = svc.profiles()
    lines = [f"网卡接口：{data['interface']}", f"已保存无线配置 {len(data['profiles'])} 个："]
    lines += [f"  - {item['name']}" for item in data["detailed"][: args.limit] or []]
    if not data["profiles"]:
        lines.append("（未解析到任何配置，请确认 netsh wlan show profiles 可用）")
    dump(data, args.json, lines)
    return 0


def cmd_networks(args) -> int:
    svc = make_service(args)
    nets = svc.cfg.get("networks") or {}
    data = {
        "networks": {
            name: {
                "label": net.get("label") or name,
                "profile": net.get("profile"),
                "need_login": bool(net.get("need_login")),
                "plugin": net.get("plugin"),
                "login_url": (net.get("login") or {}).get("url"),
                "guard": net.get("guard"),
            } for name, net in nets.items()
        },
        "count": len(nets),
    }
    lines = [f"配置网络 {len(nets)} 个："]
    for name, item in data["networks"].items():
        lines.append(f"  - {name}（{item['label']}）登录={'是' if item['need_login'] else '否'}，"
                     f"插件={item['plugin']}，流量保护={'开' if item['guard']['enabled'] else '关'}")
    if not nets:
        lines.append("（暂无网络配置：默认不硬编码任何 SSID，请通过 GUI 添加或运行 migrate）")
    dump(data, args.json, lines)
    return 0


def cmd_schedules(args) -> int:
    svc = make_service(args)
    data = {"schedules": svc.scheduler.summary(datetime.now()),
            "next_seconds": svc.scheduler.seconds_until_next(datetime.now())}
    now = datetime.now()
    lines = [f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}，计划规则 {len(data['schedules'])} 条："]
    for item in data["schedules"]:
        lines.append(f"  - {item.get('id')}｜{item.get('name')}｜{item.get('schedule')}｜下次 "
                     f"{item.get('next_run') or '（无）'}")
    if not data["schedules"]:
        lines.append("（暂无计划规则）")
    dump(data, args.json, lines)
    return 0


def cmd_plugins(args) -> int:
    svc = make_service(args)
    report = svc.plugins.report()
    data = {"plugins_dir": svc.plugins.dir, "count": len(report), "plugins": report}
    lines = [f"插件目录：{svc.plugins.dir}（{len(report)} 个）"]
    for item in report:
        flag = "OK" if not item.get("errors") else "校验失败"
        lines.append(f"  - {item.get('wifi')}｜{flag}｜需登录="
                     f"{'是' if item.get('need_login') else '否'}｜{item.get('url') or '（无 URL）'}")
        for err in item.get("errors") or []:
            lines.append(f"      ! {err}")
    if not report:
        lines.append("（未发现插件，可用 plugin-make 生成）")
    dump(data, args.json, lines)
    return 0


def cmd_plugin_validate(args) -> int:
    target_dir = args.wifi or svc_dir(args)
    dirs = []
    if target_dir and os.path.isdir(target_dir) and os.path.isfile(
            os.path.join(target_dir, "manifest.json")):
        dirs = [target_dir]
    else:
        plugin_dir = args.plugins_dir or plugins_mod.resolve_plugins_dir(
            config_mod.Config.load(args.config or paths.CONFIG_FILE).data)
        dirs = [os.path.join(plugin_dir, name) for name in sorted(os.listdir(plugin_dir))
                if os.path.isdir(os.path.join(plugin_dir, name))] if os.path.isdir(plugin_dir) else []
        if args.wifi:
            dirs = [d for d in dirs if os.path.basename(d) == args.wifi]
    if not dirs:
        dump({"ok": False, "message": f"未找到插件：{args.wifi or '(全部)'}"}, args.json,
             [f"失败：未找到插件 {args.wifi or ''}"])
        return 1
    results = []
    for directory in dirs:
        plugin = plugins_mod.load_plugin(directory)
        results.append(plugin.to_dict())
    bad = [r for r in results if r["errors"]]
    lines = []
    for item in results:
        if item["errors"]:
            lines.append(f"[失败] {item['wifi']}：" + "；".join(item["errors"]))
        else:
            extra = "；".join(item.get("warnings") or [])
            lines.append(f"[通过] {item['wifi']}：登录页 {item.get('url') or '（无）'}｜"
                         f"契约函数 {'、'.join(item.get('js_functions') or []) or '（无）'}"
                         + (f"；提示 {extra}" if extra else ""))
    dump({"ok": not bad, "checked": len(results), "results": results}, args.json, lines)
    return 0 if not bad else 1


def svc_dir(args) -> str:
    return ""


def cmd_plugin_make(args) -> int:
    from tools import make_plugin_from_legacy as migrator

    plugins_dir, wifi = args.plugins_dir or "", args.wifi or ""
    if args.output_dir:
        plugins_dir = os.path.dirname(os.path.abspath(args.output_dir))
        wifi = os.path.basename(os.path.abspath(args.output_dir).rstrip("\\/"))

    try:
        result = migrator.generate(
            legacy_path=getattr(args, "legacy", "") or "",
            plugins_dir=plugins_dir, wifi=wifi,
            portal_type=getattr(args, "portal_type", "") or "",
            force=args.force)
    except SystemExit as e:
        dump({"ok": False, "message": str(e)}, args.json, [f"失败：{e}"])
        return 1

    merged = []
    if not args.no_config and result.get("network_snippet"):
        cfg = config_mod.Config.load(args.config or paths.CONFIG_FILE)
        name = result.get("wifi")
        network = cfg.data.setdefault("networks", {}).get(name) or {}
        network.update(result["network_snippet"])
        cfg.data["networks"][name] = network
        cfg.save()
        merged.append(f"config.json 已写入 networks[{name}]（账号/密码/运营商/登录页）")

    lines = [f"成功：生成插件 {result.get('wifi')}（门户类型 {result.get('portal_type')}）",
             f"插件目录：{result.get('plugin_dir')}"]
    for path in result.get("written") or []:
        lines.append(f"  已写入：{path}")
    for item in result.get("skipped") or []:
        lines.append(f"  已跳过：{item.get('path')}（{item.get('reason')}）")
    lines.extend(merged)
    lines.append("校验：python cli.py plugin-validate %s" % result.get("wifi"))
    dump(result, args.json, lines)
    return 0 if result.get("ok") else 1


def cmd_migrate(args) -> int:
    source = args.source or paths.find_legacy_config()
    if not source:
        dump({"ok": False, "message": "未找到旧程序 config.json"},
             args.json, ["失败：未找到旧版 config.json（可用 --source 指定）"])
        return 1
    legacy = config_mod.load_legacy_config(source)
    if not legacy:
        dump({"ok": False, "message": f"旧配置为空或不可读：{source}"},
             args.json, [f"失败：旧配置为空或不可读 {source}"])
        return 1
    data, report = config_mod.migrate_from_legacy(legacy)
    target = args.config or paths.CONFIG_FILE
    if os.path.isfile(target) and not args.force:
        dump({"ok": False, "message": f"目标配置已存在：{target}（加 --force 覆盖）"},
             args.json, [f"失败：目标配置已存在 {target}，如需覆盖请加 --force"])
        return 1
    cfg = config_mod.Config(data, target)
    cfg.save()
    problems = cfg.validate()
    lines = [f"已从 {source} 迁移到 {target}", "迁移报告："] + [f"  - {r}" for r in report]
    if problems:
        lines += ["配置告警："] + [f"  - {p}" for p in problems]
    dump({"ok": True, "source": source, "target": target, "report": report,
          "problems": problems}, args.json, lines)
    return 0


# --------------------------------------------------------------------------- #
# 自测
# --------------------------------------------------------------------------- #
def run_selftest(as_json: bool = False) -> int:
    """自测：模块 import、单位换算、调度 next_run、插件加载与校验。"""
    results = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. import
    modules = ["paths", "logging_setup", "sysutil", "state", "config", "wlan", "health",
               "traffic", "plugins", "popup", "portal", "scheduler", "service"]
    import importlib
    for mod in modules:
        try:
            importlib.import_module(f"core.{mod}")
            record(f"import core.{mod}", True)
        except Exception as e:  # noqa: BLE001
            record(f"import core.{mod}", False, f"{type(e).__name__}: {e}")

    # 2. 单位换算
    cases = [
        ("MB->bytes", traffic_mod.volume_to_bytes(1, "MB") == 1024 ** 2),
        ("KB->bytes", traffic_mod.volume_to_bytes(1, "KB") == 1024),
        ("GB->bytes", traffic_mod.volume_to_bytes(1, "GB") == 1024 ** 3),
        ("bytes->MB", traffic_mod.bytes_to_volume(1024 ** 2, "MB") == 1),
        ("bytes->KB", traffic_mod.bytes_to_volume(1024 ** 3, "KB") == 1024 ** 2),
        ("bytes->GB", traffic_mod.bytes_to_volume(2 * 1024 ** 3, "GB") == 2),
        ("50MB 阈值", traffic_mod.GuardConfig(
            {"enabled": True, "volume": {"value": 50, "unit": "MB"}}).limit_bytes == 50 * 1024 ** 2),
        ("小写单位别名", traffic_mod.volume_to_bytes(50, "mb") == 50 * 1024 ** 2),
        ("非法单位回退", traffic_mod.normalize_volume_unit("xx") == "MB"),
        ("网速 2MB/s->bps", traffic_mod.speed_to_bps(2, "MB/s") == 2 * 1024 ** 2),
        ("网速 8Mbit/s->bps", int(traffic_mod.speed_to_bps(8, "Mbit/s")) == 1000000),
        ("人类可读换算", traffic_mod.human_speed(1024 ** 2).startswith("1.00 MB/s")),
    ]
    for name, passed in cases:
        record(f"单位换算 {name}", passed)

    # 3. 调度 next_run
    now = datetime(2026, 10, 13, 22, 30)  # 周二
    weekly = config_mod.normalize_schedule(
        {"id": "w", "time": "06:10", "repeat": {"mode": "weekly", "weekdays": [1, 2, 3, 4]}})
    nxt = scheduler_mod.next_run(weekly, now)
    record("调度 每周 次日 06:10", nxt == datetime(2026, 10, 14, 6, 10), str(nxt))

    daily = config_mod.normalize_schedule({"id": "d", "time": "23:00",
                                           "repeat": {"mode": "daily"}})
    nxt = scheduler_mod.next_run(daily, now)
    record("调度 每天 今天 23:00", nxt == datetime(2026, 10, 13, 23, 0), str(nxt))

    once = config_mod.normalize_schedule({"id": "o", "time": "08:00",
                                          "repeat": {"mode": "once", "date": "2026-10-20"}})
    nxt = scheduler_mod.next_run(once, now)
    record("调度 仅一次 2026-10-20 08:00", nxt == datetime(2026, 10, 20, 8, 0), str(nxt))
    record("调度 仅一次 过期返回 None",
           scheduler_mod.next_run(once, datetime(2026, 11, 1, 0, 0)) is None)

    monthly = config_mod.normalize_schedule(
        {"id": "m", "time": "07:00", "repeat": {"mode": "monthly", "days": [31]}})
    nxt = scheduler_mod.next_run(monthly, now)
    record("调度 每月 31 日 07:00（10 月 31）", nxt == datetime(2026, 10, 31, 7, 0), str(nxt))
    record("调度 每月 31 日跳过 11 月",
           scheduler_mod.next_run(monthly, datetime(2026, 11, 1, 0, 0)) == datetime(2026, 12, 31, 7, 0))

    state = {}
    late = config_mod.normalize_schedule(
        {"id": "l", "time": "06:00", "window_minutes": 180, "repeat": {"mode": "daily"}})
    due, reason = scheduler_mod.can_attempt(late, state, datetime(2026, 10, 13, 8, 0))
    record("调度 补执行窗口内可执行", due, reason)
    due2, _ = scheduler_mod.can_attempt(late, state, datetime(2026, 10, 13, 12, 0))
    record("调度 超出补执行窗口不执行", not due2)
    scheduler_mod.bump_attempt(state, "l", datetime(2026, 10, 13, 8, 0))
    scheduler_mod.mark_done(state, "l", datetime(2026, 10, 13, 8, 0))
    due3, _ = scheduler_mod.can_attempt(late, state, datetime(2026, 10, 13, 8, 30))
    record("调度 已执行过当天不再重复", not due3)

    # 4. 插件加载与校验（临时目录写一个最小插件，不污染交付目录）
    import shutil
    tmp_root = paths.temp_dir()
    fixture = os.path.join(tmp_root, "selftest-plugins", "TestWifi")
    os.makedirs(fixture, exist_ok=True)
    try:
        manifest = {
            "spec_version": "1.0",
            "wifi": "TestWifi",
            "name": "自测插件",
            "need_login": True,
            "login": {
                "url": "http://example.invalid/portal",
                "success": {"url_contains": ["success"], "body_contains": ["注销"]},
                "fields": {"account": "#user", "password": "#pass"},
            },
            "options": [{"key": "isp", "type": "select", "label": "运营商",
                         "choices": [{"value": "@unicom", "label": "中国联通"}]}],
        }
        with open(os.path.join(fixture, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(fixture, "login.js"), "w", encoding="utf-8") as f:
            f.write("function fill(ctx){return {ok:true};}\n"
                    "function submit(ctx){return {ok:true};}\n"
                    "function success(ctx){return {ok:false};}\n")
        plugin = plugins_mod.load_plugin(fixture)
        record("插件加载 fixture", plugin.wifi == "TestWifi" and not plugin.errors,
               "；".join(plugin.errors))
        record("插件 JS 契约函数识别",
               plugin.has_js_function("fill") and plugin.has_js_function("submit")
               and plugin.has_js_function("success"))
        record("插件选项解析", len(plugin.options) == 1 and plugin.options[0]["key"] == "isp")
    finally:
        shutil.rmtree(os.path.join(tmp_root, "selftest-plugins"), ignore_errors=True)

    # 交付插件（JOU）校验
    jou_dir = os.path.join(paths.PLUGINS_DIR, "JOU")
    if os.path.isdir(jou_dir):
        jou = plugins_mod.load_plugin(jou_dir)
        record("插件加载 plugins/JOU", not jou.errors, "；".join(jou.errors))
        record("plugins/JOU 声明自定义选项", len(jou.options) > 0)
    else:
        record("插件加载 plugins/JOU", False, "目录不存在")

    # 5. 配置模型
    cfg = config_mod.Config({})
    problems = cfg.validate()
    record("默认配置无硬编码网络", cfg.data["networks"] == {})
    record("默认配置校验无错误", not problems, "；".join(problems))
    record("旧配置迁移可用", bool(config_mod.migrate_from_legacy(
        {"wlan": {"billing_profile": "B", "campus_profile": "C"},
         "portal": {"account": "u", "password": "p", "isp": "@unicom"}})[1]))

    # 6. 状态与互斥锁
    lock = state_mod.ActionLock(timeout=0.2)
    with lock:
        got = lock.acquired
    record("动作互斥锁可用", got and not os.path.exists(lock.path))

    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(json.dumps({"passed": passed, "failed": len(failed), "results": results},
                         ensure_ascii=False, indent=2))
    else:
        for item in results:
            mark = "PASS" if item["ok"] else "FAIL"
            print(f"[{mark}] {item['name']}" + (f" — {item['detail']}" if item["detail"] else ""))
        print(f"\n自测汇总：通过 {passed}/{len(results)}，失败 {len(failed)}")
    return 0 if not failed else 1


def cmd_popup(args) -> int:
    """内部命令：在独立进程里显示弹窗并把结果写入 result-file。

    源码运行时由 ``pythonw cli.py _popup ...`` 调用；冻结运行时由
    ``CampusNet.exe _popup ...``（app.py 转交）调用，保证打包后弹窗仍可用。
    """
    from core import popup as popup_mod  # noqa: PLC0415

    allowed = popup_mod.show_popup_dialog(
        args.title, args.message, args.allow_text, args.deny_text,
        int(args.timeout or 0), args.auto_answer or None,
        result_path=args.result_file)
    return 0 if allowed else 1


def cmd_selftest(args) -> int:
    return run_selftest(args.json)


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="campusnet", description="CampusNet 通用核心引擎 CLI")
    p.add_argument("--config", default="", help="配置文件路径（默认程序目录 config.json）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p.add_argument("--verbose", action="store_true", help="输出 DEBUG 日志")
    sub = p.add_subparsers(dest="command", metavar="<命令>")

    sp = sub.add_parser("status", help="查看整体状态（连接/连通性/流量/插件/计划）")
    sp.add_argument("--profiles", action="store_true", help="附带本机已保存无线配置列表")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("daemon", help="前台运行守护进程（调度+巡检+流量保护）")
    sp.add_argument("--interval", type=float, default=2.0, help="最小轮询间隔（秒）")
    sp.add_argument("--ticks", type=int, default=0, help="只跑 N 轮后退出（自测用）")
    sp.set_defaults(func=cmd_daemon)

    sp = sub.add_parser("connect", help="连接指定网络（按名称/无线配置文件）")
    sp.add_argument("network")
    sp.add_argument("--no-login", action="store_true", help="本次不执行网页登录")
    sp.add_argument("--no-wait", action="store_true", help="只下发连接指令不等待结果")
    sp.add_argument("--timeout", type=float, default=None)
    sp.set_defaults(func=lambda a: cmd_connect(a))

    sp = sub.add_parser("connect-billing", help="连接配置中标记为计费/启用了流量保护的网络")
    sp.add_argument("--no-login", action="store_true")
    sp.add_argument("--no-wait", action="store_true")
    sp.add_argument("--timeout", type=float, default=None)
    sp.set_defaults(func=lambda a: cmd_connect(a, kind="billing"))

    sp = sub.add_parser("connect-campus", help="连接配置中标记为校园/需要登录的网络")
    sp.add_argument("--no-login", action="store_true")
    sp.add_argument("--no-wait", action="store_true")
    sp.add_argument("--timeout", type=float, default=None)
    sp.set_defaults(func=lambda a: cmd_connect(a, kind="campus"))

    sp = sub.add_parser("disconnect", help="断开当前 WLAN")
    sp.set_defaults(func=cmd_disconnect)

    sp = sub.add_parser("login", help="对指定/当前网络执行一次网页登录")
    sp.add_argument("network", nargs="?", default="")
    sp.add_argument("--force", action="store_true", help="即使配置为无需登录也强制登录")
    sp.add_argument("--probe-options", action="store_true", help="登录前按 login.js 规则回读自定义选项")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("health-check", help="连通性检测（可选顺带重启网卡）")
    sp.add_argument("--restart", action="store_true", help="不通时立即重启网卡")
    sp.set_defaults(func=cmd_health_check)

    sp = sub.add_parser("traffic", help="统计一段时间内的上下行流量")
    sp.add_argument("--duration", type=float, default=5.0, help="采样时长（秒）")
    sp.add_argument("--interval", type=float, default=1.0, help="采样间隔（秒）")
    sp.add_argument("--network", default="", help="网络名（默认取当前连接）")
    sp.set_defaults(func=cmd_traffic)

    sp = sub.add_parser("profiles", help="列出本机已保存的无线配置文件（供界面选择）")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_profiles)

    sp = sub.add_parser("networks", help="列出配置的网络及其开关状态")
    sp.set_defaults(func=cmd_networks)

    sp = sub.add_parser("schedules", help="列出计划规则与 next_run")
    sp.set_defaults(func=cmd_schedules)

    sp = sub.add_parser("plugins", help="列出插件与校验结果")
    sp.set_defaults(func=cmd_plugins)

    sp = sub.add_parser("plugin-validate", help="校验插件（可指定 WiFi 名或目录）")
    sp.add_argument("wifi", nargs="?", default="", help="WiFi 名或插件目录")
    sp.add_argument("--plugins-dir", default="")
    sp.set_defaults(func=cmd_plugin_validate)

    sp = sub.add_parser("plugin-make", help="由旧程序匹配自动生成插件（默认 JOU）")
    sp.add_argument("wifi", nargs="?", default="JOU", help="WiFi 名称（插件目录名）")
    sp.add_argument("--output-dir", default="", help="直接指定插件目录")
    sp.add_argument("--plugins-dir", default="", help="插件根目录（默认程序目录 plugins/）")
    sp.add_argument("--force", action="store_true", help="覆盖已存在的插件文件")
    sp.add_argument("--no-config", action="store_true",
                    help="不把迁移出的账号/密码/运营商写入 config.json")
    sp.add_argument("--legacy", default="", help="旧版 config.json 路径（默认自动寻找）")
    sp.add_argument("--portal-type", default="", help="强制指定门户类型（默认自动探测）")
    sp.set_defaults(func=cmd_plugin_make)

    sp = sub.add_parser("migrate", help="把旧程序 config.json 迁移为通用配置")
    sp.add_argument("--source", default="", help="旧配置文件路径")
    sp.add_argument("--force", action="store_true", help="目标已存在时覆盖")
    sp.set_defaults(func=cmd_migrate)

    sp = sub.add_parser("selftest", help="自测：import/单位换算/调度 next_run/插件校验")
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("_popup", help=argparse.SUPPRESS)
    sp.add_argument("--title", default="")
    sp.add_argument("--message", default="")
    sp.add_argument("--allow-text", default="允许继续")
    sp.add_argument("--deny-text", default="拒绝")
    sp.add_argument("--timeout", type=float, default=0.0)
    sp.add_argument("--result-file", default="")
    sp.add_argument("--auto-answer", default="", choices=["", "allow", "deny"],
                    help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_popup)

    return p


def main(argv=None) -> int:
    fix_console_encoding()
    sysutil.ensure_console_streams(paths.log_file())
    paths.bootstrap()          # 冻结运行时释放默认 config.json / plugins（源码运行为空操作）
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as e:  # noqa: BLE001
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "message": f"{type(e).__name__}: {e}"},
                             ensure_ascii=False, indent=2))
        else:
            print(f"执行失败：{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
