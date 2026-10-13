# -*- coding: utf-8 -*-
"""离屏（offscreen）GUI 冒烟自测。

运行::

    set QT_QPA_PLATFORM=offscreen && python tools/smoke_gui.py
    # 或： python tools/smoke_gui.py --offscreen   （脚本内部自设环境变量）

覆盖：主窗口构建、左侧导航 7 个分页构建与切换、托盘图标与右键菜单、托盘三态配色、
明/暗主题切换、计划编辑对话框（各频率）、插件表单按 options 渲染、设置页开关回滚、
真实事件循环下的线程池异步回调链路（状态 / 无线配置 / 插件 / 计划状态 / 异常回调）、
核心层状态回调驱动界面刷新。

**只读安全**：不启动后台巡检线程、不写配置文件、不注册开机自启动 / 计划任务、
不连接 / 断开网络、不重启网卡。
退出码 0 = 全部通过。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CampusNet GUI 离屏冒烟自测")
    parser.add_argument("--config", default="", help="配置文件路径")
    parser.add_argument("--offscreen", action="store_true", help="强制 offscreen 平台")
    parser.add_argument("--keep-open", action="store_true", help="结束后不退出（调试）")
    args = parser.parse_args(argv)

    if args.offscreen or not os.environ.get("QT_QPA_PLATFORM"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

    from PyQt5.QtCore import QEventLoop, QTimer, Qt
    from PyQt5.QtWidgets import QApplication

    from core import paths
    from core import wlan as wlan_mod
    from gui import config_ops
    from gui import startup as startup_mod
    from gui import theme as theme_mod
    from gui.context import AppContext
    from gui.main_window import MainWindow
    from gui.pages import PAGES
    from gui.pages.plugins import CodeDialog, NewPluginDialog
    from gui.pages.schedule import ScheduleDialog

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    config_path = args.config or paths.CONFIG_FILE

    results: list[tuple[str, str, str]] = []

    def check(name: str, fn):
        try:
            fn()
            results.append((name, "PASS", ""))
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            detail = f"{exc.__class__.__name__}: {exc}"
            results.append((name, "FAIL", detail))
            print(f"[FAIL] {name} -> {detail}")
            traceback.print_exc()

    ctx = AppContext(config_path=config_path, start_service=False, dry_run=True)
    window = MainWindow(ctx, start_minimized=False)

    # ---------------- 主窗口 / 导航 / 分页 ----------------
    check("主窗口构建", lambda: window.windowTitle() or (_ for _ in ()).throw(AssertionError("无标题")))
    check("左侧导航条目数 = 7",
          lambda: (_ for _ in ()).throw(AssertionError(f"实际 {window.nav.count()}")
                                       ) if window.nav.count() != len(PAGES) else None)

    def visit_pages():
        for row in range(window.nav.count()):
            window.nav.setCurrentRow(row)
            page = window.stack.currentWidget()
            assert page is not None, f"第 {row} 页为空"
            assert window.stack.currentIndex() == row
            assert page.sizeHint() is not None

    check("逐页切换（含 on_show 刷新）", visit_pages)

    # ---------------- 托盘 ----------------
    check("托盘图标存在且可见", lambda: (_ for _ in ()).throw(AssertionError("托盘未创建"))
          if window.tray is None else None)
    check("托盘右键菜单含各分页 + 退出",
          lambda: None if all(
              k in window.tray.page_actions for k, *_ in PAGES
          ) and window.tray.quit_action is not None else (_ for _ in ()).throw(
              AssertionError("菜单项缺失")))

    def tray_states():
        for state in ("green", "red", "gray"):
            for theme in ("light", "dark"):
                window.tray.apply_state(state, theme, "自测")
                assert not window.tray.icon().isNull(), f"{state}/{theme} 图标为空"
                assert window.tray.toolTip(), "托盘提示为空"
        # 托盘菜单动作触发（只发出信号，不做副作用）
        seen = []
        window.tray.page_requested.connect(lambda k: seen.append(k))
        window.tray.page_actions["traffic"].trigger()
        window.tray.open_action.trigger()
        assert seen == ["traffic"], f"未收到分页请求：{seen}"

    check("托盘三态配色 + 菜单可触发", tray_states)

    # ---------------- 主题 ----------------
    def switch_theme():
        for theme in ("dark", "light", "dark", "light"):
            window.apply_theme(theme)
            assert window.styleSheet(), "QSS 为空"
        assert theme_mod.normalize("DARK!") == "light"
        assert theme_mod.stylesheet("dark") != theme_mod.stylesheet("light")

    check("明/暗主题切换（不落盘）", switch_theme)

    # ---------------- 状态驱动 ----------------
    def status_driven():
        base = dict(ctx.status)
        for enabled, online, state in ((True, True, "green"), (True, False, "red"),
                                       (False, None, "gray")):
            snapshot = dict(base)
            snapshot["health"] = dict(base.get("health") or {},
                                      enabled=enabled, online=online)
            assert theme_mod.tray_state(snapshot) == state, f"状态推导错误：{state}"
            window.on_status(snapshot)
            assert window.status_text.text(), "状态栏文本为空"
        window.on_status(dict(base))

    check("连通性三态驱动托盘与状态栏", status_driven)

    # ---------------- 计划编辑对话框 ----------------
    def schedule_dialog():
        networks = ctx.network_names() if hasattr(ctx, "network_names") else \
            sorted((ctx.cfg.get("networks") or {}).keys())
        for freq in ("once", "daily", "weekly", "monthly"):
            dialog = ScheduleDialog(networks, {"frequency": freq, "repeat": {"mode": freq},
                                               "time": "08:00", "enabled": True})
            assert dialog.mode() == freq, f"频率未生效：{dialog.mode()} != {freq}"
            rule = dialog.rule()
            assert isinstance(rule, dict) and rule.get("target_network") is not None
            assert dialog.preview.text(), "next_run 预览为空"
            dialog.deleteLater()

    check("计划编辑对话框（4 种频率 + next_run 预览）", schedule_dialog)

    # ---------------- 插件表单 ----------------
    def plugin_form():
        page = window.pages["plugins"]
        names = [str(p.wifi) for p in getattr(page, "plugins", [])]
        assert names, "未发现任何插件目录"
        assert page.list.count() == len(names), "插件列表条目数与插件数不一致"
        for row in range(page.list.count()):
            page.list.setCurrentRow(row)
            assert page.edit_url is not None and page.check_need_login is not None
            assert page.options_holder is not None, "options 表单容器缺失"
            assert page._fields is not None, "options 字段未渲染"
        new_dialog = NewPluginDialog(names)
        assert new_dialog.values().get("name") is not None
        new_dialog.deleteLater()
        page.list.setCurrentRow(0)
        code_dialog = CodeDialog("编辑 login.js", "", "// smoke", None)
        assert code_dialog.text() == "// smoke"
        code_dialog.deleteLater()

    check("插件页、options 表单、新建/编辑对话框", plugin_form)

    # ---------------- 设置页既有开关不误改 ----------------
    def settings_no_side_effect():
        page = window.pages["settings"]
        before = ctx.cfg.get("app", {}).get("ui", {}).get("theme")
        page.combo_theme.setCurrentIndex(page.combo_theme.findData(ctx.theme()))
        after = ctx.cfg.get("app", {}).get("ui", {}).get("theme")
        assert before == after, "自测不应改写主题配置"
        assert page.check_autostart.isChecked() in (True, False)
        assert page.check_task.isChecked() in (True, False)

    check("设置页开关默认态（无副作用）", settings_no_side_effect)

    # ---------------- 页面核心能力可用性（只读） ----------------
    def readonly_caps():
        profiles = wlan_mod.list_profiles()
        assert isinstance(profiles, list) and profiles, "未读到本机无线配置"
        plugins = config_ops.list_plugins(ctx.cfg)
        assert isinstance(plugins, list) and plugins, "未发现插件"
        networks = config_ops.network_names(ctx.cfg)
        assert isinstance(networks, list)
        info = ctx.info()
        assert info.get("config_path")
        schedules = config_ops.schedules(ctx.cfg)
        assert isinstance(schedules, list)
        print(f"       · 本机无线配置 {len(profiles)} 个 / 插件 {len(plugins)} 个 / "
              f"网络 {len(networks)} 个 / 计划 {len(schedules)} 条")

    check("核心层只读能力（wlan 配置/插件/网络/计划/info）", readonly_caps)

    # ---------------- 真实事件循环 + 异步回调（回归 0xC0000409） ----------------
    def async_pipeline():
        """真实跑事件循环，覆盖「线程池任务 → 主线程回调」整条链路。

        回归背景：早期设置页的异步回调按单参数定义，却按 (tag, payload) 两个
        位置参数调用，槽函数抛 TypeError 后 PyQt5 直接 abort 进程（Windows 下
        表现为静默崩溃、退出码 0xC0000409）。旧冒烟测试不进事件循环，因此漏检。
        """
        hits = {"status": 0, "profiles": 0, "plugins": 0, "payload": 0,
                "two_args": 0, "startup": 0, "err_one": 0, "err_two": 0}
        expected = {"status": 1, "profiles": 1, "plugins": 1, "payload": 1,
                    "two_args": 1, "startup": 1, "err_one": 1, "err_two": 1}

        def on_status(payload):             # 单参数写法（refresh_status 约定）
            assert isinstance(payload, dict), "状态回调负载类型错误"
            assert payload.get("wlan") is not None or payload, "状态快照为空"
            hits["status"] += 1

        def on_two(_tag, payload):          # 两参数写法（run_async 旧约定）
            assert _tag == "smoke-two", f"tag 传递错误：{_tag!r}"
            assert payload == "smoke-ok", f"返回值错误：{payload!r}"
            hits["two_args"] += 1

        def on_profiles(payload):           # 单参数写法
            assert isinstance(payload, (list, dict)), "无线配置回调负载类型错误"
            hits["profiles"] += 1

        def on_plugins(_tag, payload):
            hits["plugins"] += 1

        def on_payload(payload):            # 单参数：普通返回值
            assert payload == "smoke-ok", f"返回值错误：{payload!r}"
            hits["payload"] += 1

        def on_startup(state):              # 设置页同款单参数回调（原崩溃点）
            assert isinstance(state, dict), "计划状态回调负载类型错误"
            hits["startup"] += 1

        def on_err_one(message):            # 单参数错误回调
            assert "smoke-error" in str(message), f"错误文本异常：{message!r}"
            hits["err_one"] += 1

        def on_err_two(_tag, message):      # 两参数错误回调
            assert "smoke-error" in str(message), f"错误文本异常：{message!r}"
            hits["err_two"] += 1

        ctx.refresh_status(on_done=on_status)
        ctx.load_profiles(on_done=on_profiles)
        ctx.reload_plugins(on_done=on_plugins)
        ctx.run_async(lambda: "smoke-ok", tag="smoke", on_done=on_payload)
        ctx.run_async(lambda: "smoke-ok", tag="smoke-two", on_done=on_two)
        ctx.run_async(lambda: startup_mod.status(ctx.cfg), tag="smoke-startup",
                      on_done=on_startup, on_error=on_startup)
        ctx.run_async(lambda: (_ for _ in ()).throw(RuntimeError("smoke-error")),
                      tag="smoke-err-one", on_error=on_err_one)
        ctx.run_async(lambda: (_ for _ in ()).throw(RuntimeError("smoke-error")),
                      tag="smoke-err-two", on_error=on_err_two)

        settings_page = window.pages["settings"]
        settings_page.refresh_startup()          # 原始崩溃现场之一
        window.pages["wlan"].reload_profiles()   # 原始崩溃现场之二

        def ready():
            if any(hits[key] < value for key, value in expected.items()):
                return False
            # 设置页的两处状态文本由 1 参数异步回调写入，读到即证明回调跑通
            return ("状态读取中" not in settings_page.autostart_state.text()
                    and "状态读取中" not in settings_page.task_state.text())

        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(100)
        poll.timeout.connect(lambda: loop.quit() if ready() else None)
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        poll.start()
        guard.start(20000)
        loop.exec_()
        poll.stop()

        missing = {k: (hits[k], v) for k, v in expected.items() if hits[k] < v}
        assert not missing, f"异步回调未按预期触发：命中 {hits}，期望 {expected}"
        assert "状态读取中" not in settings_page.autostart_state.text(), "设置页开机自启状态未刷新"
        assert "状态读取中" not in settings_page.task_state.text(), "设置页计划任务状态未刷新"
        assert window.status_text.text(), "异步状态刷新后状态栏为空"
        print(f"       · 异步回调命中：{hits}")

    check("事件循环 + 线程池异步回调链路（回归 0xC0000409）", async_pipeline)

    failed = [item for item in results if item[1] == "FAIL"]
    print("\n================ GUI 冒烟自测汇总 ================")
    print(f"通过 {len(results) - len(failed)}/{len(results)}")
    for name, state, detail in failed:
        print(f"  FAIL  {name}  {detail}")
    print("QT_QPA_PLATFORM =", os.environ.get("QT_QPA_PLATFORM"))

    window.quitting = True
    window.timer.stop()
    ctx.shutdown()
    if not args.keep_open:
        app.quit()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
