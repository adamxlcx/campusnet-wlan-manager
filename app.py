# -*- coding: utf-8 -*-
"""CampusNet GUI 入口（PyQt5）。

用法::

    python  app.py                 # 正常启动（显示主界面）
    python  app.py --minimized     # 直接最小化到任务栏托盘（开机自启动用）
    python  app.py --no-service    # 只开界面，不启动后台巡检（调试用）
    python  app.py --dry-run       # 干跑模式：不做任何真实网络/系统改动
    python  app.py --config <path> # 指定配置文件
    python  app.py --version       # 打印版本后退出
    python  app.py --selftest      # 无界面自检：跑核心层自测，结果写入日志后退出

隐藏控制台启动：双击 `CampusNet.vbs`（推荐，完全无窗口），或双击 `CampusNet.bat`；
调试时用 `CampusNet_debug.bat`（保留控制台）。详见 README「GUI 使用说明」。

打包版（CampusNet.exe）额外说明：`CampusNet.exe --selftest` 用于无界面自检，
结果同时写入数据目录 `logs\\campusnet.log` 与 `logs\\selftest-result.json`，退出码 0/1；
冻结运行时 `_popup` 参数会被转交给核心层 CLI（后台弹窗子进程用）。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import logging_setup  # noqa: E402
from core import paths  # noqa: E402
from core import sysutil  # noqa: E402
from gui.context import AppContext  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CampusNet 校园网 WLAN 自动管理（GUI）")
    parser.add_argument("--config", default="", help="配置文件路径（默认 config.json）")
    parser.add_argument("--minimized", action="store_true", help="启动后直接最小化到托盘")
    parser.add_argument("--no-service", action="store_true", help="不启动后台巡检线程")
    parser.add_argument("--dry-run", action="store_true", help="干跑模式，不做真实改动")
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    parser.add_argument("--selftest", action="store_true",
                        help="无界面自检：跑核心层自测，写入日志与 selftest-result.json 后退出")
    return parser


def _set_app_user_model_id() -> None:
    """Windows 任务栏图标分组需要显式设置 AppUserModelID。"""
    if os.name != "nt":
        return
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CampusNet.GUI")
    except Exception:  # noqa: BLE001
        pass


def _acquire_single_instance(name: str):
    """返回 (server, existing_socket)：已有实例时返回 (None, socket)。"""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(400):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(400)
        return None, socket
    server = QLocalServer()
    QLocalServer.removeServer(name)
    server.listen(name)
    return server, None


def _install_excepthook() -> None:
    """安装异常兜底钩子。

    PyQt5 在槽函数里出现未捕获异常时会直接 abort 进程（Windows 下表现为
    静默崩溃、退出码 0xC0000409）。装一个自定义 `sys.excepthook` 后，PyQt5
    改为调用它并把异常交给我们记录，界面继续存活，日志里能查到现场。
    """
    logger = logging_setup.get_logger()

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip()
        logger.error("未捕获异常（界面继续运行）：%s", detail)

    sys.excepthook = _hook


def _run_selftest() -> int:
    """无界面自检（供打包后验证）：跑核心层自测，结果写入日志与 JSON 文件后退出。

    退出码：0 = 全部通过，1 = 有失败项或执行异常。
    """
    import contextlib
    import io
    import json
    import logging
    import time

    started = time.time()
    logger = logging_setup.get_logger()
    code = 1

    released = paths.bootstrap()
    logger.info("自检开始：冻结运行=%s，数据目录=%s，资源目录=%s",
                paths.is_frozen(), paths.app_root(), paths.resource_dir())
    for item in released:
        logger.info("首次运行已释放：%s", item)

    buffer = io.StringIO()
    try:
        from cli import run_selftest  # noqa: PLC0415
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = int(run_selftest(as_json=True))
    except Exception:  # noqa: BLE001
        logger.exception("自检执行异常")
        code = 1

    raw = buffer.getvalue()
    payload = {}
    if "{" in raw:
        try:
            payload = json.loads(raw[raw.index("{"):])
        except ValueError:
            payload = {}
    results = payload.get("results") or []
    for item in results:
        logger.info("[%s] %s%s", "PASS" if item.get("ok") else "FAIL",
                    item.get("name"), f" — {item['detail']}" if item.get("detail") else "")
    passed = int(payload.get("passed") or 0)
    failed = int(payload.get("failed") or 0)
    logger.info("自测汇总：通过 %s/%s，失败 %s", passed, passed + failed, failed)

    record = {
        "ok": code == 0,
        "exit_code": code,
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "frozen": paths.is_frozen(),
        "app_root": paths.app_root(),
        "resource_dir": paths.resource_dir(),
        "config_file": paths.CONFIG_FILE,
        "plugins_dir": paths.PLUGINS_DIR,
        "log_file": paths.log_file(),
        "version": _version_text(),
        "released": released,
        "duration_seconds": round(time.time() - started, 3),
        "results": results,
    }
    try:
        target = paths.selftest_result_file()
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        logger.info("自检结果已写入：%s", target)
    except OSError as exc:
        logger.error("自检结果写入失败：%s", exc)

    logger.info("=== 自检结束（退出码 %s）===", code)
    for handler in logging.getLogger(logging_setup.ROOT_LOGGER_NAME).handlers:
        try:
            handler.flush()
        except Exception:  # noqa: BLE001
            pass
    logging.shutdown()
    return code


def _version_text() -> str:
    from core import config as config_mod  # noqa: PLC0415
    data = config_mod.ensure_config(paths.CONFIG_FILE)[0].data
    return f"{data['app']['name']} {data['app']['version']} (GUI)"


def main(argv=None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)

    # 冻结运行时没有控制台：先把 stdout/stderr 兜底到日志文件，避免 print 抛异常
    sysutil.ensure_console_streams(paths.log_file())

    # 冻结运行时 `_popup` 由本 exe 自身承担（后台需要弹窗时以子进程方式调用）
    if paths.is_frozen() and cli_args[:1] == ["_popup"]:
        from cli import main as cli_main  # noqa: PLC0415
        return int(cli_main(cli_args))

    args = build_parser().parse_args(argv)

    if args.version:
        text = _version_text()
        print(text)
        logging_setup.get_logger().info("版本：%s", text)
        return 0

    if args.selftest:
        paths.ensure_dirs()
        logging_setup.setup_logging(None, console=not paths.is_frozen())
        return _run_selftest()

    paths.bootstrap()

    _install_excepthook()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    _set_app_user_model_id()

    app = QApplication(sys.argv[:1])
    app.setApplicationName("CampusNet")
    app.setApplicationDisplayName("CampusNet")
    app.setOrganizationName("CampusNet")
    app.setQuitOnLastWindowClosed(False)   # 关掉主界面只是隐藏到托盘

    config_path = args.config or paths.CONFIG_FILE
    instance_key = "CampusNetGUI-" + str(abs(hash(os.path.abspath(config_path))) % 10 ** 10)
    server, existing = _acquire_single_instance(instance_key)
    if existing is not None:
        print("CampusNet 已在运行，已唤起已有窗口。")
        return 0

    try:
        ctx = AppContext(config_path=config_path, start_service=not args.no_service,
                         dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "CampusNet 启动失败",
                             f"初始化核心层失败：\n{exc}")
        return 2

    window = MainWindow(ctx, start_minimized=bool(args.minimized))
    app.setWindowIcon(window.windowIcon())
    if server is not None:
        def _on_new_connection():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.readyRead.connect(lambda: window.show_main())
                conn.disconnected.connect(conn.deleteLater)

        server.newConnection.connect(_on_new_connection)

    if not args.minimized:
        window.show_main()
    if not args.no_service:
        ctx.start_service()

    code = app.exec_()
    try:
        ctx.shutdown()
    except Exception:  # noqa: BLE001
        pass
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
