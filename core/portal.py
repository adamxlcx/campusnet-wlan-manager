# -*- coding: utf-8 -*-
"""网页登录：调用插件完成认证。

通道：
    browser  —— Selenium（本机 Edge/Chrome）为主通道：把插件 login.js 注入登录页，
                用 JS 完成 match / fill / submit / success 判定（因此匹配规则 100% 由插件定义）
    requests —— 可选通道：按插件 manifest 的 http.attempts 声明式发送请求

返回统一结构：{"ok", "method", "message", "steps"[], "needs_user"(可选)}
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

from . import health as health_mod
from . import plugins as plugins_mod
from . import sysutil
from .logging_setup import get_logger


# --------------------------------------------------------------------------- #
# 上下文
# --------------------------------------------------------------------------- #
def build_ctx(network_cfg: dict, plugin=None, extra: dict | None = None) -> dict:
    """构造传给 login.js 的 ctx：{account, password, options, url, network, ip}。"""
    net = network_cfg or {}
    login = net.get("login") or {}
    credentials = {str(k): ("" if v is None else str(v))
                   for k, v in (login.get("credentials") or {}).items()}
    options = dict(login.get("options") or {})
    ctx = {
        "network": net.get("name") or "",
        "url": (login.get("url") or (plugin.url if plugin else "") or ""),
        "account": credentials.get("account", ""),
        "password": credentials.get("password", ""),
        "credentials": credentials,
        "options": options,
        "ip": health_mod.get_local_ip(),
    }
    if extra:
        ctx.update(extra)
    return ctx


def _render(template: str, ctx: dict) -> str:
    """渲染 {key} / {key_q}（URL 编码）/ {key_j}（JSON 字符串）占位符。"""
    if not isinstance(template, str):
        return template

    def repl(match):
        key = match.group(1)
        quoted = False
        json_mode = False
        if key.endswith("_q"):
            key, quoted = key[:-2], True
        elif key.endswith("_j"):
            key, json_mode = key[:-2], True
        value = _lookup(ctx, key)
        if value is None:
            return ""
        text = str(value)
        if quoted:
            return urllib.parse.quote(text, safe="")
        if json_mode:
            return json.dumps(text)[1:-1]
        return text

    return re.sub(r"\{([A-Za-z0-9_.]+)\}", repl, template)


def _lookup(ctx: dict, key: str):
    if key in ctx:
        return ctx[key]
    if key.startswith("options."):
        return (ctx.get("options") or {}).get(key.split(".", 1)[1])
    if key.startswith("credentials."):
        return (ctx.get("credentials") or {}).get(key.split(".", 1)[1])
    # 允许直接使用选项名，如 {isp}
    if isinstance(ctx.get("options"), dict) and key in ctx["options"]:
        return ctx["options"][key]
    if isinstance(ctx.get("credentials"), dict) and key in ctx["credentials"]:
        return ctx["credentials"][key]
    if key == "ts":
        return int(time.time() * 1000)
    if key == "service":
        return "default"
    return None


def _render_map(mapping: dict, ctx: dict) -> dict:
    return {k: _render(str(v), ctx) for k, v in (mapping or {}).items()}


# --------------------------------------------------------------------------- #
# 浏览器通道（主）
# --------------------------------------------------------------------------- #
def _make_driver(browser: str = "edge", headless: bool = False):
    from selenium import webdriver  # 延迟导入：未安装 selenium 时不影响其它功能

    browser = (browser or "edge").lower()
    if browser == "chrome":
        opts = webdriver.ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_experimental_option("excludeSwitches", ["enable-logging"])
        return webdriver.Chrome(options=opts)

    opts = webdriver.EdgeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    return webdriver.Edge(options=opts)


def login_browser(network_cfg: dict, plugin, portal_cfg: dict | None = None,
                  ctx_extra: dict | None = None) -> dict:
    portal_cfg = portal_cfg or {}
    steps = []
    driver = None
    try:
        driver = _make_driver(portal_cfg.get("browser", "edge"), portal_cfg.get("headless", False))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "method": "browser", "steps": steps,
                "message": f"浏览器驱动启动失败：{e}"}

    try:
        url = (network_cfg.get("login") or {}).get("url") or plugin.url
        if not url:
            return {"ok": False, "method": "browser", "steps": steps, "message": "未配置登录页 URL"}
        try:
            driver.set_page_load_timeout(plugin.timeout_seconds or 30)
        except Exception:  # noqa: BLE001
            pass
        driver.get(url)
        steps.append({"step": "open", "url": url})

        wait = float(portal_cfg.get("js_wait_seconds") or 2)
        _wait_ready(driver, wait)

        if not _inject(driver, plugin):
            return {"ok": False, "method": "browser", "steps": steps,
                    "message": "login.js 注入失败"}
        steps.append({"step": "inject"})

        ctx = build_ctx(network_cfg, plugin, ctx_extra)
        matched = _call(driver, plugin, "match", ctx)
        steps.append({"step": "match", "result": matched})
        if matched.get("ok") and matched.get("value") is False:
            get_logger().info("[%s] 当前页面未匹配登录表单（可能已登录）", plugin.wifi)

        captcha = plugin.captcha or {}
        if captcha.get("enabled"):
            need = _call(driver, plugin, "needsCaptcha", ctx)
            if need.get("ok") and need.get("value"):
                return {"ok": False, "method": "browser", "steps": steps, "needs_user": True,
                        "message": "登录页要求图形验证码，请手动完成登录后重试"}

        filled = _call(driver, plugin, "fill", ctx)
        steps.append({"step": "fill", "result": filled})
        if not filled.get("ok") or (isinstance(filled.get("value"), dict)
                                    and filled["value"].get("ok") is False):
            return {"ok": False, "method": "browser", "steps": steps,
                    "message": f"填表失败：{_err_text(filled)}"}

        submitted = _call(driver, plugin, "submit", ctx)
        steps.append({"step": "submit", "result": submitted})
        if not submitted.get("ok"):
            return {"ok": False, "method": "browser", "steps": steps,
                    "message": f"提交失败：{_err_text(submitted)}"}

        deadline = time.time() + float(portal_cfg.get("timeout_seconds") or 30)
        last = {}
        while time.time() < deadline:
            sysutil.sleep(1.0)
            _wait_ready(driver, 0.8)
            last = _call(driver, plugin, "success", ctx)
            steps.append({"step": "success", "result": last})
            if last.get("ok") and last.get("value") is True:
                return {"ok": True, "method": "browser", "steps": steps,
                        "message": "浏览器通道登录成功", "page": _current_url(driver)}
            if isinstance(last.get("value"), dict) and last["value"].get("ok"):
                return {"ok": True, "method": "browser", "steps": steps,
                        "message": last["value"].get("reason") or "浏览器通道登录成功",
                        "page": _current_url(driver)}
        return {"ok": False, "method": "browser", "steps": steps,
                "message": f"登录结果判定超时：{_err_text(last) or '未见成功特征'}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "method": "browser", "steps": steps, "message": f"浏览器通道异常：{e}"}
    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:  # noqa: BLE001
            pass


def _wait_ready(driver, seconds: float = 1.0) -> None:
    try:
        driver.execute_script(
            "return document.readyState === 'complete' || document.readyState === 'interactive';")
    except Exception:  # noqa: BLE001
        pass
    if seconds:
        sysutil.sleep(seconds)


def _inject(driver, plugin) -> bool:
    try:
        driver.execute_script(plugins_mod.js_inject_source(plugin))
        check = driver.execute_script(
            "return typeof CampusNetPlugin !== 'undefined';")
        return bool(check)
    except Exception as e:  # noqa: BLE001
        get_logger().error("[%s] 注入 login.js 失败：%s", plugin.wifi, e)
        return False


def _call(driver, plugin, fn_name: str, ctx: dict) -> dict:
    try:
        result = driver.execute_script(plugin.js_snippet(fn_name), ctx)
        if isinstance(result, dict):
            return result
        return {"ok": True, "value": result}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _err_text(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)
    if result.get("error"):
        return str(result["error"])
    value = result.get("value")
    if isinstance(value, dict):
        return str(value.get("error") or value.get("reason") or "")
    return ""


def _current_url(driver) -> str:
    try:
        return driver.current_url
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------- #
# requests 通道（可选）
# --------------------------------------------------------------------------- #
def login_requests(network_cfg: dict, plugin, portal_cfg: dict | None = None,
                   ctx_extra: dict | None = None) -> dict:
    portal_cfg = portal_cfg or {}
    steps = []
    attempts = plugin.http_attempts
    if not attempts:
        return {"ok": False, "method": "requests", "steps": steps,
                "message": "插件未声明 http.attempts，无法使用 requests 通道"}
    try:
        import requests
    except ImportError:
        return {"ok": False, "method": "requests", "steps": steps,
                "message": "未安装 requests"}

    ctx = build_ctx(network_cfg, plugin, ctx_extra)
    verify = bool(portal_cfg.get("verify_tls", False))
    timeout = float(portal_cfg.get("timeout_seconds") or 30)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CampusNet/2.0"}

    session = requests.Session()
    for index, attempt in enumerate(attempts):
        name = attempt.get("name") or f"attempt-{index + 1}"
        method = str(attempt.get("method") or "GET").upper()
        url = _render(str(attempt.get("url") or ""), ctx)
        data = _render_map(attempt.get("data") or {}, ctx)
        params = _render_map(attempt.get("params") or {}, ctx)
        merged_headers = dict(headers)
        merged_headers.update(_render_map(attempt.get("headers") or {}, ctx))
        try:
            if method == "POST":
                resp = session.post(url, data=data, params=params or None,
                                    headers=merged_headers, timeout=timeout, verify=verify)
            else:
                resp = session.get(url, params=params or None, data=data or None,
                                   headers=merged_headers, timeout=timeout, verify=verify)
        except Exception as e:  # noqa: BLE001
            steps.append({"step": name, "ok": False, "error": str(e)})
            continue

        ok, reason = _judge(resp, attempt.get("success") or {})
        steps.append({"step": name, "ok": ok, "status": resp.status_code,
                      "url": resp.url, "reason": reason,
                      "body": resp.text[:300]})
        if ok:
            return {"ok": True, "method": "requests", "steps": steps,
                    "message": f"{name} 登录成功（{reason}）"}
    return {"ok": False, "method": "requests", "steps": steps,
            "message": "所有 HTTP 尝试均未判定为成功"}


def _judge(resp, success: dict) -> tuple:
    """按插件的 success 规则判定响应是否表示登录成功。"""
    text = resp.text or ""
    status = resp.status_code
    expect_status = success.get("status")
    if expect_status:
        codes = expect_status if isinstance(expect_status, list) else [expect_status]
        if status not in [int(c) for c in codes]:
            return False, f"HTTP {status} 不在期望状态码内"

    contains = success.get("contains") or []
    if isinstance(contains, str):
        contains = [contains]
    if contains and not any(str(c) in text for c in contains):
        return False, "响应文本未包含成功关键字"

    not_contains = success.get("not_contains") or []
    if isinstance(not_contains, str):
        not_contains = [not_contains]
    if not_contains and any(str(c) in text for c in not_contains):
        return False, "响应文本包含失败关键字"

    regex = success.get("regex")
    if regex and not re.search(regex, text):
        return False, "响应未匹配正则"

    json_path = success.get("json")
    if isinstance(json_path, dict):
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            return False, "响应不是合法 JSON"
        for key, expected in json_path.items():
            if isinstance(payload, dict) and str(payload.get(key)) != str(expected):
                return False, f"JSON 字段 {key} 不匹配"
    if not (expect_status or contains or regex or isinstance(json_path, dict)):
        return False, "插件未给出可判定的 success 规则"
    return True, "命中 success 规则"


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def login(network_cfg: dict, plugin=None, portal_cfg: dict | None = None,
          ctx_extra: dict | None = None, plugins_map: dict | None = None) -> dict:
    """按配置与插件完成一次登录。"""
    net = network_cfg or {}
    portal_cfg = portal_cfg or {}
    name = net.get("name") or ""

    need_login = net.get("need_login", False)
    login_block = net.get("login") or {}
    if login_block.get("enabled") is not None:
        need_login = bool(login_block.get("enabled"))
    if not need_login:
        return {"ok": True, "method": "skip", "skipped": True, "steps": [],
                "message": f"{name} 配置为无需登录，跳过"}

    if plugin is None:
        plugin = plugins_mod.find_for_network(net.get("plugin") or name, plugins_map)
    if plugin is None:
        return {"ok": False, "method": "none", "steps": [],
                "message": f"未找到网络 {name} 对应的登录插件"}
    if plugin.errors:
        return {"ok": False, "method": "none", "steps": [],
                "message": f"插件 {plugin.wifi} 校验未通过：{'；'.join(plugin.errors)}"}

    driver_choice = (login_block.get("driver") or portal_cfg.get("driver") or "auto").lower()
    if driver_choice in ("selenium",):
        driver_choice = "browser"
    order = []
    if driver_choice == "requests":
        order = ["requests"]
    elif driver_choice == "browser":
        order = ["browser"]
    else:  # auto
        order = ["browser", "requests"] if plugin.js else ["requests"]

    if driver_choice == "browser" and portal_cfg.get("allow_requests_fallback", True) \
            and plugin.http_attempts:
        pass
    elif driver_choice == "browser":
        order = ["browser"]

    results = []
    for channel in order:
        if channel == "browser":
            if not plugin.js:
                continue
            get_logger().info("[%s] 使用浏览器通道登录", plugin.wifi)
            result = login_browser(net, plugin, portal_cfg, ctx_extra)
        else:
            get_logger().info("[%s] 使用 requests 通道登录", plugin.wifi)
            result = login_requests(net, plugin, portal_cfg, ctx_extra)
        results.append(result)
        if result.get("ok"):
            return result
        if result.get("needs_user"):
            return result

    if not results:
        return {"ok": False, "method": "none", "steps": results,
                "message": "插件既无可用 JS，也无 http.attempts"}
    return {"ok": False, "method": order[-1], "steps": results,
            "message": results[-1].get("message", "登录失败")}


# --------------------------------------------------------------------------- #
# 按 JS 规则回读自定义选项（GUI「从登录页同步选项」按钮用）
# --------------------------------------------------------------------------- #
def probe_options(plugin, url: str = "", portal_cfg: dict | None = None) -> dict:
    """用浏览器打开登录页，注入 login.js，读取 credentials()/options() 声明的实时选项。"""
    portal_cfg = portal_cfg or {}
    result = {"ok": False, "credentials": [], "options": [], "message": ""}
    if not plugin or not plugin.js:
        result["message"] = "插件缺少 login.js"
        return result
    target = url or plugin.url
    if not target:
        result["message"] = "未提供登录页 URL"
        return result

    driver = None
    try:
        driver = _make_driver(portal_cfg.get("browser", "edge"), portal_cfg.get("headless", False))
        driver.get(target)
        _wait_ready(driver, float(portal_cfg.get("js_wait_seconds") or 2))
        if not _inject(driver, plugin):
            result["message"] = "login.js 注入失败"
            return result
        ctx = build_ctx({"name": plugin.wifi}, plugin)
        for fn, key in (("credentials", "credentials"), ("options", "options")):
            if plugin.has_js_function(fn):
                out = _call(driver, plugin, fn, ctx)
                if out.get("ok") and isinstance(out.get("value"), list):
                    result[key] = out["value"]
        result["ok"] = bool(result["credentials"] or result["options"])
        result["message"] = "已按 login.js 规则回读登录页选项" if result["ok"] \
            else "登录页未返回任何选项"
    except Exception as e:  # noqa: BLE001
        result["message"] = f"回读失败：{e}"
    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:  # noqa: BLE001
            pass
    return result


def selenium_available() -> bool:
    try:
        import selenium  # noqa: F401
        return True
    except ImportError:
        return False
