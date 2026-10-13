# -*- coding: utf-8 -*-
"""CampusNet 修复后回归验证：核心采样 / 主循环 / GUI 显示三层全链路。

只做只读验证：dry_run 打开，不切换网络、不重启网卡、不改配置。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(PROJ, "config.json")
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  |  {detail}" if detail else ""), flush=True)


from core import service as service_mod  # noqa: E402
from core import wlan  # noqa: E402
from core import traffic as traffic_mod  # noqa: E402

# ---------------------------------------------------------------- 下载负载
stop = threading.Event()
counter = {"n": 0}
URLS = [
    "https://mirrors.aliyun.com/ubuntu-releases/22.04/SHA256SUMS",
    "https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/22.04/SHA256SUMS",
    "http://mirrors.aliyun.com/ubuntu/ls-lR.gz",
]


def downloader():
    import urllib.request
    while not stop.is_set():
        for url in URLS:
            if stop.is_set():
                return
            try:
                with urllib.request.urlopen(url, timeout=8) as resp:
                    while not stop.is_set():
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        counter["n"] += len(chunk)
            except Exception:
                time.sleep(0.3)


threading.Thread(target=downloader, daemon=True).start()
time.sleep(1.0)

print("=" * 70)
print("【第一层】核心层：网速 / 流量采样")
print("=" * 70)
svc = service_mod.build_service(CFG)
svc.dry_run = True
check("wlan.detect_interface()", bool(wlan.detect_interface()), wlan.detect_interface())
check("当前网络识别", bool(svc.current_network), svc.current_network)
print("guard_config(JOU) =", json.dumps(traffic_mod.guard_summary(svc.guard_config("JOU")),
                                       ensure_ascii=False))

samples = []
for _ in range(6):
    samples.append(svc.traffic_tick())
    time.sleep(1.0)
print("采样序列（down_speed）:", [s.get("down_speed") for s in samples])

st = svc.status()
tr = st["traffic"]
check("sampling=True", tr.get("sampling") is True, f"message={tr.get('message')!r}")
check("down_bps > 0", (tr.get("down_bps") or 0) > 0, tr.get("down_speed"))
check("session_recv > 0", (tr.get("session_recv") or 0) > 0, tr.get("session_recv_human"))
check("session_total_human", tr.get("session_total_human") not in (None, "0 B"),
      tr.get("session_total_human"))
check("峰值速率非空", tr.get("peak_down_speed") not in (None, "", "0 B/s"),
      tr.get("peak_down_speed"))
check("触发次数非 None", tr.get("trip_count") is not None, tr.get("trip_count"))
check("guard 配置贯通界面", bool(tr.get("guard")), json.dumps(tr.get("guard"), ensure_ascii=False))
check("下载进程启发式可用", isinstance(tr.get("top_processes"), list),
      len(tr.get("top_processes") or []))

print("=" * 70)
print("【第二层】连通性检测 + 守护主循环")
print("=" * 70)
h = svc.health_tick(allow_restart=False)
st = svc.status()
import gui.theme as theme_mod  # noqa: E402

check("连通性检测 ok", h.get("online") is True,
      f"method={h.get('method')} latency={h.get('latency_ms')}ms online={h.get('online')}")
check("托盘状态 green", theme_mod.tray_state(st) == "green", theme_mod.tray_state(st))

# 回归：插件空闲巡检不得反复重载（修复 manifest/js mtime 比较后应稳定返回 False）
from core import plugins as plugins_mod  # noqa: E402

pm = plugins_mod.PluginManager(svc.cfg)
pm.maybe_reload(min_interval=0.0)
idle = [pm.maybe_reload(min_interval=0.0) for _ in range(4)]
check("插件空闲时不重复重载", not any(idle), f"reload 结果序列={idle}")

due = svc.scheduler.due_rules(datetime.now())
check("无到期计划（避免误切网）", len(due) == 0, [r.get("id") for r in due])

hb0 = svc.state.get("heartbeat")
loop_err = []


def run_loop():
    try:
        svc.run_forever(interval=1.0, max_ticks=8)
    except Exception as exc:  # noqa: BLE001
        loop_err.append(repr(exc))


loop = threading.Thread(target=run_loop, daemon=True)
loop.start()
time.sleep(4.0)
mid = svc.status()
loop.join(timeout=30)
hb1 = svc.state.get("heartbeat")
check("主循环完整跑完无异常", (not loop.is_alive()) and not loop_err, loop_err or "ok")
check("heartbeat 每轮刷新", (hb1 or 0) > (hb0 or 0), f"{hb0} -> {hb1}")
check("循环运行中状态可读", bool(mid.get("service", {}).get("heartbeat")),
      str(mid.get("service", {}).get("started_at")))
tr2 = mid.get("traffic") or {}
check("主循环内采样持续有效", (tr2.get("session_recv") or 0) > 0, tr2.get("session_recv_human"))

print("=" * 70)
print("【第三层】GUI 实际渲染（离屏）")
print("=" * 70)
from PyQt5.QtWidgets import QApplication  # noqa: E402

from gui.context import AppContext  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.pages.health import HealthPage  # noqa: E402
from gui.pages.traffic import TrafficPage  # noqa: E402

app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)
ctx = AppContext(config_path=CFG, start_service=False)
ctx.service.dry_run = True
win = MainWindow(ctx)

for _ in range(3):
    ctx.service.traffic_tick()
    time.sleep(1.0)
ctx.service.health_tick(allow_restart=False)
ctx._on_status(ctx.service.status())

tp = [p for p in win.pages.values() if isinstance(p, TrafficPage)][0]
hp = [p for p in win.pages.values() if isinstance(p, HealthPage)][0]

rate = tp.rate_label.value_label.text()
total = tp.total_label.value_label.text()
peak = tp.peak_label.value_label.text()
trip = tp.trip_label.value_label.text()
netname = tp.net_label.value_label.text()
check("GUI 实时下载速率非零", rate not in ("0 B/s", "—", ""), rate)
check("GUI 会话累计接收非零", total not in ("0 B", "—", ""), total)
check("GUI 峰值速率", peak not in ("—", ""), peak)
check("GUI 触发次数", trip != "", trip)
check("GUI 当前 WiFi", netname not in ("—", ""), netname)
check("GUI 保护提示含阈值", "网速" in tp.guard_hint.text(), tp.guard_hint.text()[:80])
check("GUI 网络检测状态行", "在线：True" in hp.state_label.text(), hp.state_label.text()[:100])

stop.set()
svc.close()
win.close()
ctx.shutdown()

print("=" * 70)
print("【第四层】冻结态日志不重复（模拟 sys.stdout 被重定向到日志文件）")
print("=" * 70)
import io  # noqa: E402
import logging as logging_mod  # noqa: E402

from core import logging_setup as ls  # noqa: E402

sink = io.StringIO()
sink._campusnet_redirect = os.path.join(PROJ, "logs", "campusnet.log")
_old_stdout = sys.stdout
sys.stdout = sink
root_log = logging_mod.getLogger(ls.ROOT_LOGGER_NAME)
for _h in list(root_log.handlers):
    root_log.removeHandler(_h)
ls._configured = False
ls.setup_logging(svc.cfg, console=True)
_handlers = [type(_h).__name__ for _h in root_log.handlers]
_stream_added = any(isinstance(_h, logging_mod.StreamHandler)
                    and not isinstance(_h, logging_mod.FileHandler)
                    for _h in root_log.handlers)
check("冻结态不再重复挂 stdout handler", not _stream_added, _handlers)
sys.stdout = _old_stdout

failed = [r for r in RESULTS if not r[1]]
print("=" * 70)
print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
for name, _ok, detail in failed:
    print("  FAIL:", name, detail)
print("RESULT:", "ALL-PASS" if not failed else "HAS-FAILURE")
