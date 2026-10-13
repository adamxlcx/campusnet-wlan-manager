# -*- coding: utf-8 -*-
"""插件加载器：发现 / 校验 / manifest + login.js 解析 / 热加载。

插件目录约定（每个 WiFi 一个插件，目录以 WiFi 名称命名）
    plugins/<WiFi名称>/manifest.json    插件清单（声明是否需要登录、登录页 URL、选项）
    plugins/<WiFi名称>/login.js         登录脚本（fill/submit/success 或 request）

完整规范见 PLUGIN_SPEC.md。
"""
from __future__ import annotations

import json
import os
import re
import time

from . import paths
from .logging_setup import get_logger

REQUIRED_MANIFEST_KEYS = ("spec_version", "name", "wifi", "need_login")
REQUIRED_JS_SYMBOL = "CampusNetPlugin"
OPTION_TYPES = ("text", "password", "select", "checkbox", "number", "hidden")
# 插件契约函数（既支持 CampusNetPlugin.xxx 形式，也支持顶层独立函数形式）
CONTRACT_FUNCTIONS = ("match", "needsCaptcha", "fill", "submit", "success",
                      "credentials", "options", "request")


class Plugin:
    """一个已加载的插件。"""

    def __init__(self, directory: str, manifest: dict | None = None, js: str = ""):
        self.directory = os.path.abspath(directory)
        self.wifi = os.path.basename(self.directory)
        self.manifest = manifest if isinstance(manifest, dict) else {}
        self.js = js or ""
        self.errors: list = []
        self.warnings: list = []
        self.loaded_at = 0.0
        self.manifest_mtime = 0.0
        self.js_mtime = 0.0

    # ---- 常用字段 ----
    @property
    def plugin_id(self) -> str:
        return str(self.manifest.get("id") or self.wifi)

    @property
    def name(self) -> str:
        return str(self.manifest.get("name") or self.wifi)

    @property
    def description(self) -> str:
        return str(self.manifest.get("description") or "")

    @property
    def spec_version(self) -> str:
        return str(self.manifest.get("spec_version") or "")

    @property
    def need_login(self) -> bool:
        return bool(self.manifest.get("need_login", True))

    @property
    def login_block(self) -> dict:
        block = self.manifest.get("login")
        return block if isinstance(block, dict) else {}

    @property
    def url(self) -> str:
        return str(self.login_block.get("url") or self.manifest.get("url") or "")

    @property
    def url_patterns(self) -> list:
        pats = self.login_block.get("url_patterns") or []
        return [str(p) for p in pats] if isinstance(pats, list) else []

    @property
    def driver(self) -> str:
        return str(self.login_block.get("driver") or "auto").lower()

    @property
    def timeout_seconds(self) -> int:
        try:
            return int(self.login_block.get("timeout_seconds") or 30)
        except (TypeError, ValueError):
            return 30

    @property
    def captcha(self) -> dict:
        block = self.login_block.get("captcha")
        return block if isinstance(block, dict) else {"enabled": False}

    @property
    def credentials(self) -> list:
        items = self.manifest.get("credentials") or []
        return [i for i in items if isinstance(i, dict) and i.get("key")]

    @property
    def options(self) -> list:
        items = self.manifest.get("options") or []
        return [i for i in items if isinstance(i, dict) and i.get("key")]

    @property
    def http_attempts(self) -> list:
        block = self.manifest.get("http")
        if isinstance(block, dict) and isinstance(block.get("attempts"), list):
            return [a for a in block["attempts"] if isinstance(a, dict)]
        return []

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "wifi": self.wifi,
            "plugin_id": self.plugin_id,
            "name": self.name,
            "spec_version": self.spec_version,
            "directory": self.directory,
            "need_login": self.need_login,
            "url": self.url,
            "driver": self.driver,
            "credentials": [{"key": c.get("key"), "label": c.get("label"),
                             "type": c.get("type", "text")} for c in self.credentials],
            "options": [{"key": o.get("key"), "label": o.get("label"),
                         "type": o.get("type", "text"),
                         "choices": o.get("choices") or []} for o in self.options],
            "http_attempts": [a.get("name") or a.get("url") for a in self.http_attempts],
            "js_functions": [fn for fn in ("fill", "submit", "success", "request")
                             if self.has_js_function(fn)],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }

    # ---- JS 契约 ----
    def has_js_function(self, fn_name: str) -> bool:
        if not self.js:
            return False
        pattern = rf"(?:^|[\s,{{]){re.escape(fn_name)}\s*[:=(]"
        return bool(re.search(pattern, self.js))

    def js_snippet(self, fn_name: str, ctx_arg: str = "ctx") -> str:
        """生成在浏览器中调用插件函数的 JS 片段（返回 {ok, value/error}）。

        以 `return` 开头并显式调用，可直接交给 Selenium 的 execute_script 使用；
        插件对象以方法形式调用，保证 JS 内部的 `this` 指向插件本身。
        """
        return (
            "return (function(ctx){\n"
            f"  var win = (typeof window !== 'undefined') ? window : {{}};\n"
            f"  if (typeof win.{REQUIRED_JS_SYMBOL} === 'undefined' || !win.{REQUIRED_JS_SYMBOL}) "
            f"{{ return {{ok:false, error:'插件未注入或未定义 {REQUIRED_JS_SYMBOL}'}}; }}\n"
            f"  var P = win.{REQUIRED_JS_SYMBOL};\n"
            f"  if (typeof P.{fn_name} !== 'function') "
            f"{{ return {{ok:false, error:'插件缺少函数 {fn_name}()'}}; }}\n"
            f"  try {{ return {{ok:true, value: P.{fn_name}(ctx)}}; }}\n"
            "  catch (e) { return {ok:false, error: String(e)}; }\n"
            "})(arguments[0] || {});"
        )


# --------------------------------------------------------------------------- #
# 加载与校验
# --------------------------------------------------------------------------- #
def default_plugins_dir() -> str:
    return paths.PLUGINS_DIR


def resolve_plugins_dir(cfg: dict | None = None) -> str:
    custom = str(((cfg or {}).get("portal") or {}).get("plugins_dir") or "").strip()
    return custom or paths.PLUGINS_DIR


def load_plugin(directory: str, strict: bool = False) -> Plugin:
    directory = os.path.abspath(directory)
    manifest_path = os.path.join(directory, "manifest.json")
    js_path = os.path.join(directory, "login.js")

    manifest, errors, warnings = {}, [], []
    if not os.path.isfile(manifest_path):
        errors.append(f"缺少 manifest.json：{manifest_path}")
    else:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if not isinstance(manifest, dict):
                errors.append("manifest.json 顶层必须是 JSON 对象")
                manifest = {}
        except Exception as e:  # noqa: BLE001
            errors.append(f"manifest.json 解析失败：{e}")

    js = ""
    if not os.path.isfile(js_path):
        errors.append(f"缺少 login.js：{js_path}")
    else:
        try:
            with open(js_path, "r", encoding="utf-8") as f:
                js = f.read()
        except Exception as e:  # noqa: BLE001
            errors.append(f"login.js 读取失败：{e}")

    plugin = Plugin(directory, manifest, js)
    plugin.errors = errors
    plugin.warnings = warnings
    plugin.loaded_at = time.time()
    try:
        plugin.manifest_mtime = os.path.getmtime(manifest_path)
        plugin.js_mtime = os.path.getmtime(js_path)
    except OSError:
        pass
    plugin.errors.extend(validate(plugin))
    if strict and plugin.errors:
        raise ValueError("插件校验失败：" + "；".join(plugin.errors))
    return plugin


def validate(plugin: Plugin) -> list:
    """校验插件，返回错误列表（空列表 = 通过）。"""
    problems = []
    m = plugin.manifest

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in m:
            problems.append(f"manifest.json 缺少必填字段：{key}")
    if str(m.get("spec_version") or "") and str(m["spec_version"]).split(".")[0] != "1":
        problems.append(f"不支持的 spec_version：{m.get('spec_version')}（当前支持 1.x）")
    wifi = str(m.get("wifi") or "")
    if wifi and wifi != plugin.wifi:
        problems.append(f"manifest.wifi（{wifi}）与所在目录名（{plugin.wifi}）不一致；"
                        f"插件目录必须以 WiFi 名称命名")

    if plugin.js and REQUIRED_JS_SYMBOL not in plugin.js:
        has_contract = ((plugin.has_js_function("fill") and plugin.has_js_function("submit"))
                        or plugin.has_js_function("request"))
        if not has_contract:
            problems.append(f"login.js 未定义 {REQUIRED_JS_SYMBOL} 对象，"
                            f"也未实现 fill()/submit() 或 request() 契约函数")

    if plugin.need_login:
        if not plugin.url and not plugin.http_attempts:
            problems.append("need_login=true 时，必须在 login.url 或 http.attempts 中提供入口")
        if plugin.js:
            has_browser = (plugin.has_js_function("fill") and plugin.has_js_function("submit"))
            has_http = plugin.has_js_function("request") or bool(plugin.http_attempts)
            if not (has_browser or has_http):
                problems.append("login.js 必须实现 fill()/submit()（浏览器通道）"
                                "或 request()（HTTP 通道）中的至少一种")

    for item in plugin.credentials:
        if item.get("type", "text") not in OPTION_TYPES:
            problems.append(f"credentials[{item.get('key')}] 的 type 非法：{item.get('type')}")
    for item in plugin.options:
        otype = item.get("type", "text")
        if otype not in OPTION_TYPES:
            problems.append(f"options[{item.get('key')}] 的 type 非法：{otype}")
        if otype == "select" and not item.get("choices"):
            problems.append(f"options[{item.get('key')}] 为 select 但缺少 choices")

    for i, attempt in enumerate(plugin.http_attempts):
        if not attempt.get("url"):
            problems.append(f"http.attempts[{i}] 缺少 url")
        method = str(attempt.get("method") or "GET").upper()
        if method not in ("GET", "POST", "PUT", "HEAD"):
            problems.append(f"http.attempts[{i}] 的 method 非法：{method}")
        if not isinstance(attempt.get("success"), dict):
            problems.append(f"http.attempts[{i}] 缺少 success 判定规则")
    return problems


def discover(plugins_dir: str | None = None) -> list:
    """列出所有插件目录（必须含 manifest.json 或 login.js）。"""
    root = plugins_dir or default_plugins_dir()
    if not os.path.isdir(root):
        return []
    found = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if not os.path.isdir(path) or entry.startswith(".") or entry == "__pycache__":
            continue
        if os.path.isfile(os.path.join(path, "manifest.json")) \
                or os.path.isfile(os.path.join(path, "login.js")):
            found.append(path)
    return found


def load_all(plugins_dir: str | None = None) -> dict:
    """加载全部插件，返回 {wifi 名称: Plugin}（含校验失败的插件，便于界面提示）。"""
    result = {}
    for path in discover(plugins_dir):
        plugin = load_plugin(path)
        result[plugin.wifi] = plugin
        if plugin.errors:
            get_logger().warning("插件 %s 校验未通过：%s", plugin.wifi, "；".join(plugin.errors))
        else:
            get_logger().info("插件 %s 加载成功（%s）", plugin.wifi, plugin.name)
    return result


def find_for_network(network: str, plugins: dict | None = None) -> Plugin | None:
    """按“网络配置的 plugin 名 → 目录名”查找插件。"""
    plugins = plugins if plugins is not None else load_all()
    if not network:
        return None
    if network in plugins:
        return plugins[network]
    target = str(network).strip().lower()
    for wifi, plugin in plugins.items():
        if wifi.lower() == target or plugin.plugin_id.lower() == target:
            return plugin
    return None


def scan_options(plugin: Plugin) -> dict:
    """把插件声明的凭据/选项整理成 GUI 表单可渲染的结构。

    返回 {"credentials":[{key,label,type,required,choices,default}], "options":[...]}
    这是“按 JavaScript 匹配规则生成自定义选项”的静态侧：manifest 中每一项都记录了
    它在页面上的 JS 选择器（js_selector / js_source），因此 GUI 可以据此渲染表单。
    """
    def pick(item, default_type="text"):
        entry = {
            "key": item.get("key"),
            "label": item.get("label") or item.get("key"),
            "type": item.get("type") or default_type,
            "required": bool(item.get("required")),
            "default": item.get("default", ""),
            "choices": list(item.get("choices") or []),
            "placeholder": item.get("placeholder") or "",
            "help": item.get("help") or "",
            "js_selector": item.get("js_selector") or item.get("selector") or "",
            "from_js": bool(item.get("from_js")),
        }
        if entry["type"] == "checkbox":
            entry["default"] = bool(item.get("default", False))
        return entry

    return {
        "plugin": plugin.plugin_id,
        "wifi": plugin.wifi,
        "credentials": [pick(c) for c in plugin.credentials],
        "options": [pick(o) for o in plugin.options],
    }


def js_inject_source(plugin: Plugin) -> str:
    """返回可直接交给浏览器执行的脚本（幂等，可重复注入）。

    Selenium 的 execute_script 会把脚本包进函数作用域，`var CampusNetPlugin`
    不会自动成为全局变量，因此这里在作用域内定义后再显式发布到 window，
    使后续每次调用的 JS 片段都能取到插件对象。
    同时兼容“只声明独立函数（fill/submit/...）”的简化写法。
    """
    js = plugin.js or ""
    publishes = "\n".join(
        f"  if (typeof __P['{fn}'] !== 'function' && typeof {fn} === 'function') "
        f"{{ __P['{fn}'] = {fn}; }}"
        for fn in CONTRACT_FUNCTIONS
    )
    return (
        "(function(){\n"
        "  if (typeof window !== 'undefined' && window.__campusnet_plugin_loaded__) { return; }\n"
        + js + "\n"
        f"  var __P = (typeof {REQUIRED_JS_SYMBOL} !== 'undefined' && {REQUIRED_JS_SYMBOL})"
        f" ? {REQUIRED_JS_SYMBOL} : {{}};\n"
        + publishes + "\n"
        f"  window.{REQUIRED_JS_SYMBOL} = __P;\n"
        "  window.__campusnet_plugin_loaded__ = true;\n"
        "})();"
    )


class PluginManager:
    """带热加载的插件管理器（GUI 保存插件后调用 reload 即可，无需重启程序）。"""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.plugins: dict = {}
        self.dir = resolve_plugins_dir(self.cfg)
        self.last_scan = 0.0
        self.reload()

    def reload(self, force: bool = False) -> dict:
        self.dir = resolve_plugins_dir(self.cfg)
        self.plugins = load_all(self.dir)
        self.last_scan = time.time()
        return self.plugins

    def maybe_reload(self, min_interval: float = 2.0) -> bool:
        """检测目录/文件时间戳变化，变化则热加载。返回是否发生了重载。"""
        if time.time() - self.last_scan < min_interval:
            return False
        changed = False
        seen = set()
        for path in discover(self.dir):
            seen.add(path)
            manifest = os.path.join(path, "manifest.json")
            js = os.path.join(path, "login.js")
            try:
                newest = max(os.path.getmtime(manifest), os.path.getmtime(js))
            except OSError:
                newest = 0.0
            wifi = os.path.basename(path)
            old = self.plugins.get(wifi)
            # 注意：必须比较 manifest.json 与 login.js 里**较新**的那个时间戳。
            # 只用 manifest_mtime 比较时，只要 login.js 比 manifest.json 新（生成/释放
            # 插件时很常见），就会永远判定为“已变化”，导致每次巡检（每 15 秒）都重载插件。
            if old is None or max(old.manifest_mtime, old.js_mtime) < newest:
                changed = True
                break
        if not changed and set(self.plugins.keys()) != {os.path.basename(p) for p in seen}:
            changed = True
        if changed:
            self.reload()
        self.last_scan = time.time()
        return changed

    def get(self, wifi: str) -> Plugin | None:
        return find_for_network(wifi, self.plugins)

    def all(self) -> list:
        return list(self.plugins.values())

    def validated(self) -> list:
        return [p for p in self.plugins.values() if p.ok]

    def report(self) -> list:
        return [p.to_dict() for p in self.plugins.values()]
