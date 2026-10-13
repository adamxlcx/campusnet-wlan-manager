# -*- coding: utf-8 -*-
"""把旧版单体程序内置的登录匹配规则，自动同步生成为插件。

用法（在 CampusNet 目录下）：
    python tools/make_plugin_from_legacy.py                 # 自动寻找旧 config.json 并生成
    python tools/make_plugin_from_legacy.py --json          # 额外以 JSON 输出生成结果
    python tools/make_plugin_from_legacy.py --dry-run       # 只打印将要写入的内容，不落盘
    python tools/make_plugin_from_legacy.py --force         # 覆盖已存在的插件文件

生成物：
    plugins/<WiFi名称>/manifest.json   插件清单
    plugins/<WiFi名称>/login.js        登录脚本（fill/submit/success 或 request）

设计原则（与 PLUGIN_SPEC.md 第 1 节一致）：
    * 程序内**不硬编码**任何 SSID / 账号 / 密码 / 运营商 / 阈值 / 时间；
      WiFi 名称、登录页 URL、账号、密码、运营商全部来自旧配置或命令行参数，
      并输出成 config.json 的 networks 片段交用户确认。
    * 只有“登录页 DOM 匹配规则”（表单名、字段名、按钮、成功特征）属于门户站点自身
      的既有事实，作为插件数据（LEGACY_PORTALS 绑定表）随插件一起生成，
      便于后续照抄到其它门户。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_HERE)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

try:  # 优先复用程序内的路径定义（脱离程序目录也能独立运行）
    from core import paths as _paths  # noqa: E402

    DEFAULT_PLUGINS_DIR = _paths.PLUGINS_DIR
    LEGACY_CANDIDATES = list(_paths.LEGACY_CONFIG_CANDIDATES)
except Exception:  # noqa: BLE001
    DEFAULT_PLUGINS_DIR = os.path.join(_PROJECT_DIR, "plugins")
    LEGACY_CANDIDATES = [
        os.path.join(os.path.dirname(_PROJECT_DIR), "config.json"),
        os.path.join(_PROJECT_DIR, "config.legacy.json"),
    ]

SPEC_VERSION = "1.0"
GENERATOR = "tools/make_plugin_from_legacy.py"


# --------------------------------------------------------------------------- #
# 旧程序内置的门户匹配绑定表（按门户类型索引）
# --------------------------------------------------------------------------- #
# 说明：这里的键值与《登录窗口元素代码》一致——
#   表单  form[name='f1']          提交  input[name='0MKKey'] / 页面函数 ee(1)
#   账号  input[name='DDDDD']      密码  input[name='upass']
#   运营商 select[name='ISP_select']（-1 请选择运营商 / @cmcc 中国移动 /
#                                   @unicom 中国联通 / @telecom 中国电信 / "" 校园网）
#   验证码 input[name='captcha'] + #captcha_img（默认隐藏，预留开关）
#   登录成功判定：URL 回到门户首页或出现成功关键字；失败：出现错误关键字
LEGACY_PORTALS = {
    "eportal-drcom": {
        "id": "eportal-drcom",
        "name": "Dr.COM / eportal 门户",
        "description": "Dr.COM eportal（含 Dr1003 回调）网页认证门户",
        "url_hints": ("eportal", "drcom", "dr1003", "portal"),
        "form": {"name": "f1", "selector": "form[name='f1']"},
        "credentials": [
            {"key": "account", "label": "账号", "type": "text", "required": True,
             "selector": "input[name='DDDDD']", "placeholder": "上网账号"},
            {"key": "password", "label": "密码", "type": "password", "required": True,
             "selector": "input[name='upass']", "placeholder": "上网密码"},
        ],
        "options": [
            {"key": "isp", "label": "运营商", "type": "select", "required": False,
             "selector": "select[name='ISP_select']",
             "choices": [
                 {"value": "-1", "label": "请选择运营商"},
                 {"value": "@cmcc", "label": "中国移动"},
                 {"value": "@unicom", "label": "中国联通"},
                 {"value": "@telecom", "label": "中国电信"},
                 {"value": "", "label": "校园网"},
             ],
             "help": "“校园网”选项仅限访问校内数字资源和学术期刊资源。"},
        ],
        "submit": {"selector": "input[name='0MKKey']", "value": "登录",
                   "page_function": "ee(1)", "fallback": "form.submit()"},
        "captcha": {"enabled": False, "input_selector": "input[name='captcha']",
                    "image_selector": "#captcha_img"},
        "success": {
            "url_patterns": ["eportal", "index", "portal", "210.28.39.250"],
            "keywords": ["注销", "退出", "已登录", "登录成功", "logout", "success"],
            "failure_keywords": ["密码错误", "账号或密码", "用户不存在", "已欠费",
                                 "认证失败", "登录失败", "error"],
        },
        "http_attempts": [
            {
                "name": "eportal-801-login",
                "method": "GET",
                "url": "{portal_origin}:801/eportal/?c=Portal&a=login&callback=dr1003"
                       "&login_method=1&user_account=,0,{account}&user_password={password}"
                       "&wlan_user_ip={ip}&wlan_user_ipv6=&wlan_user_mac=000000000000"
                       "&wlan_user_vlan=&wlan_ac_ip=&wlan_ac_name=&jsVersion=3.3.3&v={ts}",
                "success": {"contains": ["\"result\":1"], "not_contains": ["\"result\":0"]},
            },
            {
                "name": "eportal-80-login",
                "method": "GET",
                "url": "{portal_origin}/eportal/?c=Portal&a=login&callback=dr1003"
                       "&login_method=1&user_account=,0,{account}&user_password={password}"
                       "&wlan_user_ip={ip}&wlan_user_ipv6=&wlan_user_mac=000000000000"
                       "&wlan_user_vlan=&wlan_ac_ip=&wlan_ac_name=&jsVersion=3.3.3&v={ts}",
                "success": {"contains": ["\"result\":1"], "not_contains": ["\"result\":0"]},
            },
        ],
    },
}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _first(mapping, *keys, default=""):
    for key in keys:
        value = (mapping or {}).get(key)
        if value not in (None, ""):
            return value
    return default


def find_legacy_config(explicit: str = "") -> str:
    if explicit:
        return explicit if os.path.isfile(explicit) else ""
    for candidate in LEGACY_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return ""


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def detect_portal_type(legacy: dict, forced: str = "") -> str:
    """按旧配置的登录页/接口特征判断门户类型。"""
    if forced:
        if forced not in LEGACY_PORTALS:
            raise SystemExit(f"未知的门户类型：{forced}（可选：{', '.join(LEGACY_PORTALS)}）")
        return forced
    portal = legacy.get("portal") or {}
    haystack = " ".join([
        str(_first(portal, "url", "login_url")),
        " ".join(str(x) for x in (portal.get("eportal_endpoints") or [])),
        str(_first(portal, "method")),
    ]).lower()
    for key, spec in LEGACY_PORTALS.items():
        if any(hint.lower() in haystack for hint in spec["url_hints"]):
            return key
    return "eportal-drcom"


def portal_origin(url: str) -> str:
    """从登录页 URL 取出 origin（scheme://host[:port]），用于拼 HTTP 接口。"""
    from urllib.parse import urlsplit
    parts = urlsplit(url or "")
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


# --------------------------------------------------------------------------- #
# 生成 manifest.json
# --------------------------------------------------------------------------- #
def build_manifest(wifi: str, url: str, portal: dict, legacy_path: str,
                   legacy: dict) -> dict:
    login_cfg = legacy.get("portal") or {}
    return {
        "spec_version": SPEC_VERSION,
        "id": f"{wifi.lower()}-{portal['id']}",
        "name": f"{wifi} 校园网（{portal['name']}）",
        "description": (f"由 {GENERATOR} 从旧程序内置匹配规则自动生成："
                        f"{portal['description']}。目录名 = WiFi 名称 = {wifi}。"),
        "wifi": wifi,
        "need_login": True,
        "generated": {
            "by": GENERATOR,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "legacy_config": legacy_path or "",
            "portal_type": portal["id"],
        },
        "login": {
            "url": url,
            "url_patterns": [f"*{hint}*" for hint in portal["url_hints"] if hint != "portal"]
                            or ["*"],
            "driver": "auto",
            "timeout_seconds": int(_first(login_cfg, "timeout", default=30) or 30),
            "js_wait_seconds": 2,
            "form": dict(portal["form"]),
            "submit": dict(portal["submit"]),
            "success": dict(portal["success"]),
            "captcha": dict(portal["captcha"]),
        },
        "credentials": [
            {
                "key": item["key"],
                "label": item["label"],
                "type": item["type"],
                "required": bool(item.get("required")),
                "placeholder": item.get("placeholder", ""),
                "js_selector": item["selector"],
                "from_js": True,
                "help": "由 login.js 的 fill() 按 js_selector 写入；值来自 config.json 的 "
                        "networks[%s].login.credentials" % wifi,
            }
            for item in portal["credentials"]
        ],
        "options": [
            {
                "key": item["key"],
                "label": item["label"],
                "type": item["type"],
                "required": bool(item.get("required")),
                "js_selector": item["selector"],
                "from_js": True,
                "choices": [dict(c) for c in item.get("choices", [])],
                "default": item.get("default", ""),
                "help": item.get("help", ""),
            }
            for item in portal["options"]
        ],
        "http": {
            "attempts": [
                {
                    "name": attempt["name"],
                    "method": attempt["method"],
                    "url": attempt["url"].replace("{portal_origin}", portal_origin(url)),
                    "success": dict(attempt["success"]),
                }
                for attempt in portal.get("http_attempts", [])
            ]
        },
    }


# --------------------------------------------------------------------------- #
# 生成 login.js
# --------------------------------------------------------------------------- #
JS_TEMPLATE = r"""/* eslint-disable */
/**
 * __PLUGIN_NAME__ —— 校园网登录插件（由 __GENERATOR__ 自动生成）
 *
 * WiFi 名称：__WIFI__
 * 登录页：__URL__
 * 门户类型：__PORTAL_ID__（__PORTAL_NAME__）
 * 生成时间：__GENERATED_AT__
 *
 * 契约（详见 PLUGIN_SPEC.md）：
 *   CampusNetPlugin.match(ctx)        -> boolean   当前页面是否为该门户的登录页
 *   CampusNetPlugin.fill(ctx)         -> {ok, filled[], error}   填表
 *   CampusNetPlugin.submit(ctx)       -> {ok, error}             提交
 *   CampusNetPlugin.success(ctx)      -> boolean   是否登录成功
 *   CampusNetPlugin.needsCaptcha(ctx) -> boolean   是否需要人工完成验证码
 *   CampusNetPlugin.credentials(ctx)  -> [{key,label,type,value}] 回读页面凭据项（可选）
 *   CampusNetPlugin.options(ctx)      -> [{key,label,type,value,choices[]}] 回读页面选项（可选）
 *   CampusNetPlugin.request(ctx)      -> {url,method,data} HTTP 通道参考请求（可选）
 *
 * ctx（由 core/portal.py 注入）：{network, url, account, password, credentials{}, options{}, ip}
 */
var CampusNetPlugin = {
  specVersion: "__SPEC_VERSION__",
  id: "__PLUGIN_ID__",
  wifi: "__WIFI__",
  name: "__PLUGIN_NAME__",
  pageUrl: "__URL__",
  urlPatterns: __URL_PATTERNS__,

  selectors: {
    form: "__SEL_FORM__",
    account: "__SEL_ACCOUNT__",
    password: "__SEL_PASSWORD__",
    isp: "__SEL_ISP__",
    submit: "__SEL_SUBMIT__",
    captchaInput: "__SEL_CAPTCHA_INPUT__",
    captchaImage: "__SEL_CAPTCHA_IMAGE__"
  },
  submitPageFunction: "__SUBMIT_PAGE_FN__",
  successKeywords: __SUCCESS_KEYWORDS__,
  failureKeywords: __FAILURE_KEYWORDS__,
  successUrlPatterns: __SUCCESS_URL_PATTERNS__,

  // ---------------- 内部工具 ----------------
  _q: function (selector, root) {
    if (!selector) { return null; }
    try { return (root || document).querySelector(selector); } catch (e) { return null; }
  },
  _all: function (selector, root) {
    try { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }
    catch (e) { return []; }
  },
  _visible: function (el) {
    if (!el) { return false; }
    if (el.type === "hidden") { return false; }
    var style = window.getComputedStyle ? window.getComputedStyle(el) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) { return false; }
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  },
  /** 写入输入框：同时触发 input/change，兼容受框架监听的页面。 */
  _setValue: function (el, value) {
    if (!el) { return false; }
    el.focus();
    el.value = (value === undefined || value === null) ? "" : String(value);
    try {
      el.dispatchEvent(new Event("input", {bubbles: true}));
      el.dispatchEvent(new Event("change", {bubbles: true}));
      el.dispatchEvent(new Event("blur", {bubbles: true}));
    } catch (e) { /* 老浏览器忽略 */ }
    return true;
  },
  /** 选择下拉框：优先按 value 命中，其次按显示文本命中。 */
  _setSelect: function (el, value) {
    if (!el || !el.options) { return false; }
    var target = String(value === undefined || value === null ? "" : value);
    var hit = null;
    for (var i = 0; i < el.options.length; i++) {
      var opt = el.options[i];
      if (String(opt.value) === target) { hit = opt; break; }
    }
    if (!hit) {
      for (var j = 0; j < el.options.length; j++) {
        if (String(el.options[j].text).trim() === target) { hit = el.options[j]; break; }
      }
    }
    if (!hit) { return false; }
    el.value = hit.value;
    try {
      el.dispatchEvent(new Event("change", {bubbles: true}));
    } catch (e) { /* ignore */ }
    return true;
  },
  _text: function () {
    return (document.body ? (document.body.innerText || document.body.textContent || "") : "");
  },

  // ---------------- 契约实现 ----------------
  /** 当前页面是否为该门户登录页（表单与账号框都在）。 */
  match: function (ctx) {
    var form = this._q(this.selectors.form);
    var account = this._q(this.selectors.account);
    if (!form && !account) { return false; }
    if (this.selectors.account && !account) { return false; }
    return true;
  },

  /** 是否需要人工输入图形验证码（默认关闭，验证码可见时才要求人工）。 */
  needsCaptcha: function (ctx) {
    var input = this._q(this.selectors.captchaInput);
    return !!(input && this._visible(input));
  },

  /** 填表：账号 / 密码 / 运营商等全部取自 ctx，插件不保存任何账号信息。 */
  fill: function (ctx) {
    ctx = ctx || {};
    var options = ctx.options || {};
    var credentials = ctx.credentials || {};
    var filled = [];
    var missing = [];

    var accountEl = this._q(this.selectors.account);
    var accountValue = ctx.account || credentials.account || "";
    if (accountEl) {
      if (this._setValue(accountEl, accountValue)) { filled.push("account"); }
    } else { missing.push("account"); }

    var passwordEl = this._q(this.selectors.password);
    var passwordValue = ctx.password || credentials.password || "";
    if (passwordEl) {
      if (this._setValue(passwordEl, passwordValue)) { filled.push("password"); }
    } else { missing.push("password"); }

    // 运营商是“自定义选项”，键名与 manifest.options[].key 一致（此处为 isp）
    var ispEl = this._q(this.selectors.isp);
    var ispValue = (options.isp !== undefined && options.isp !== null)
      ? options.isp
      : (credentials.isp || "");
    if (ispEl && String(ispValue) !== "") {
      if (this._setSelect(ispEl, ispValue) || this._setValue(ispEl, ispValue)) {
        filled.push("isp");
      }
    }

    if (missing.length) {
      return {ok: false, filled: filled, error: "未找到字段：" + missing.join("、")};
    }
    return {ok: true, filled: filled, error: ""};
  },

  /** 提交：优先调用门户自带提交函数，失败再退回表单 submit()。 */
  submit: function (ctx) {
    var button = this._q(this.selectors.submit);
    if (button) {
      button.click();
      return {ok: true, error: "", via: "button-click"};
    }
    var fnName = String(this.submitPageFunction || "").trim();
    if (fnName) {
      var name = fnName.replace(/\(.*$/, "");
      if (name && typeof window[name] === "function") {
        try { window[name](1); return {ok: true, error: "", via: "page-function"}; }
        catch (e) { /* 继续尝试 form.submit */ }
      }
    }
    var form = this._q(this.selectors.form);
    if (form && typeof form.submit === "function") {
      form.submit();
      return {ok: true, error: "", via: "form-submit"};
    }
    return {ok: false, error: "找不到提交按钮，也无法提交表单"};
  },

  /** 成功判定：URL 命中门户特征或出现成功关键字，且不含失败关键字。 */
  success: function (ctx) {
    var text = this._text();
    var url = String(window.location.href || "");
    for (var i = 0; i < this.failureKeywords.length; i++) {
      if (text.indexOf(this.failureKeywords[i]) >= 0) { return false; }
    }
    for (var j = 0; j < this.successKeywords.length; j++) {
      if (text.indexOf(this.successKeywords[j]) >= 0) { return true; }
    }
    for (var k = 0; k < this.successUrlPatterns.length; k++) {
      var pat = String(this.successUrlPatterns[k]);
      if (pat && url.indexOf(pat) >= 0 && url.indexOf("eportal/?c=Portal&a=login") < 0) {
        return true;
      }
    }
    return false;
  },

  /** 回读页面凭据项（GUI「从登录页同步」用）。 */
  credentials: function (ctx) {
    var out = [];
    var specs = [
      {key: "account", label: "账号", type: "text", selector: this.selectors.account},
      {key: "password", label: "密码", type: "password", selector: this.selectors.password}
    ];
    for (var i = 0; i < specs.length; i++) {
      var el = this._q(specs[i].selector);
      if (!el) { continue; }
      out.push({
        key: specs[i].key, label: specs[i].label, type: specs[i].type,
        value: el.value || "", placeholder: el.placeholder || ""
      });
    }
    return out;
  },

  /** 回读自定义选项（运营商下拉的真实候选项）。 */
  options: function (ctx) {
    var el = this._q(this.selectors.isp);
    if (!el || !el.options) { return []; }
    var choices = [];
    for (var i = 0; i < el.options.length; i++) {
      choices.push({value: String(el.options[i].value), label: String(el.options[i].text).trim()});
    }
    return [{
      key: "isp", label: "运营商", type: "select",
      value: el.value || "", choices: choices
    }];
  },

  /** HTTP 通道参考请求（实际请求由 manifest.http.attempts 声明，供 GUI 展示）。 */
  request: function (ctx) {
    ctx = ctx || {};
    return {
      url: (ctx.url || this.pageUrl || "").replace(/\/+$/, "") + "/eportal/",
      method: "GET",
      data: {user_account: ",0," + (ctx.account || ""), user_password: ctx.password || ""}
    };
  }
};
"""


def build_login_js(wifi: str, url: str, portal: dict, manifest: dict) -> str:
    creds = {item["key"]: item["selector"] for item in portal["credentials"]}
    isp_key = portal["options"][0]["key"] if portal.get("options") else ""
    js = JS_TEMPLATE
    replacements = {
        "__GENERATOR__": GENERATOR,
        "__SPEC_VERSION__": SPEC_VERSION,
        "__PLUGIN_ID__": manifest["id"],
        "__PLUGIN_NAME__": manifest["name"],
        "__WIFI__": wifi,
        "__URL__": url,
        "__PORTAL_ID__": portal["id"],
        "__PORTAL_NAME__": portal["name"],
        "__GENERATED_AT__": manifest["generated"]["at"],
        "__SEL_FORM__": portal["form"]["selector"],
        "__SEL_ACCOUNT__": creds.get("account", ""),
        "__SEL_PASSWORD__": creds.get("password", ""),
        "__SEL_ISP__": (portal["options"][0]["selector"] if portal.get("options") else ""),
        "__SEL_SUBMIT__": portal["submit"]["selector"],
        "__SEL_CAPTCHA_INPUT__": portal["captcha"]["input_selector"],
        "__SEL_CAPTCHA_IMAGE__": portal["captcha"]["image_selector"],
        "__SUBMIT_PAGE_FN__": portal["submit"].get("page_function", ""),
        "__URL_PATTERNS__": json.dumps(manifest["login"]["url_patterns"], ensure_ascii=False),
        "__SUCCESS_KEYWORDS__": json.dumps(portal["success"]["keywords"], ensure_ascii=False),
        "__FAILURE_KEYWORDS__": json.dumps(portal["success"]["failure_keywords"], ensure_ascii=False),
        "__SUCCESS_URL_PATTERNS__": json.dumps(portal["success"]["url_patterns"], ensure_ascii=False),
    }
    for token, value in replacements.items():
        js = js.replace(token, value)
    # ISP 选项键名提示（便于人工核对 manifest.options[].key 与 fill() 中的读取键名一致）
    js = js.replace("// 运营商是“自定义选项”",
                    f"// 运营商是“自定义选项”（manifest.options[].key = {isp_key}）")
    return js


# --------------------------------------------------------------------------- #
# 网络配置片段
# --------------------------------------------------------------------------- #
def build_network_snippet(wifi: str, url: str, legacy: dict) -> dict:
    portal = legacy.get("portal") or {}
    return {
        "profile": str(_first((legacy.get("wlan") or {}), "campus_profile",
                              default=wifi) or wifi),
        "label": "校园网络",
        "need_login": True,
        "plugin": wifi,
        "login": {
            "url": url,
            "driver": "",
            "credentials": {
                "account": str(_first(portal, "account", "username", default="")),
                "password": str(_first(portal, "password", default="")),
            },
            "options": {"isp": str(_first(portal, "isp", default=""))},
        },
        "guard": {"enabled": False},
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def generate(legacy_path: str = "", plugins_dir: str = "", wifi: str = "",
             url: str = "", portal_type: str = "", force: bool = False,
             dry_run: bool = False) -> dict:
    legacy_path = find_legacy_config(legacy_path)
    legacy = load_json(legacy_path) if legacy_path else {}
    wlan_cfg = legacy.get("wlan") or {}
    portal_cfg = legacy.get("portal") or {}

    wifi = (wifi or _first(wlan_cfg, "campus_profile", "campus_ssid",
                           default="") or "").strip()
    if not wifi:
        raise SystemExit("无法确定 WiFi 名称：旧配置里没有 wlan.campus_profile，"
                         "请用 --wifi 指定（插件目录必须以 WiFi 名称命名）")

    portal_key = detect_portal_type(legacy, portal_type)
    portal = LEGACY_PORTALS[portal_key]

    url = (url or _first(portal_cfg, "url", "login_url", default="") or "").strip()

    manifest = build_manifest(wifi, url, portal, legacy_path, legacy)
    js_text = build_login_js(wifi, url, portal, manifest)
    target_dir = os.path.join(plugins_dir or DEFAULT_PLUGINS_DIR, wifi)
    manifest_path = os.path.join(target_dir, "manifest.json")
    js_path = os.path.join(target_dir, "login.js")

    written = []
    skipped = []
    if dry_run:
        skipped.append({"path": manifest_path, "reason": "dry-run 未写入"})
        skipped.append({"path": js_path, "reason": "dry-run 未写入"})
    else:
        os.makedirs(target_dir, exist_ok=True)
        for path, content in ((manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2)),
                              (js_path, js_text)):
            if os.path.isfile(path) and not force:
                skipped.append({"path": path, "reason": "已存在（加 --force 覆盖）"})
                continue
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.replace(tmp, path)
            written.append(path)

    return {
        "ok": True,
        "wifi": wifi,
        "portal_type": portal_key,
        "legacy_config": legacy_path,
        "plugins_dir": os.path.dirname(target_dir),
        "plugin_dir": target_dir,
        "written": written,
        "skipped": skipped,
        "manifest": manifest,
        "login_js": js_text,
        "network_snippet": build_network_snippet(wifi, url, legacy),
        "next_steps": [
            "把 network_snippet 合并进 config.json 的 networks[%s]" % wifi,
            "运行 python cli.py plugin-validate 确认插件校验通过",
            "GUI 阶段：网络配置页直接渲染 manifest 的 credentials/options 生成表单",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="把旧程序内置的登录匹配规则同步生成为插件（plugins/<WiFi名称>/）")
    parser.add_argument("--legacy", default="", help="旧版 config.json 路径（默认自动寻找）")
    parser.add_argument("--plugins-dir", default="", help="插件根目录（默认程序内 plugins/）")
    parser.add_argument("--wifi", default="", help="WiFi 名称（默认取旧配置 wlan.campus_profile）")
    parser.add_argument("--url", default="", help="登录页 URL（默认取旧配置 portal.url）")
    parser.add_argument("--portal-type", default="", help="门户类型：%s" % ", ".join(LEGACY_PORTALS))
    parser.add_argument("--force", action="store_true", help="覆盖已存在的插件文件")
    parser.add_argument("--dry-run", action="store_true", help="只计算不落盘")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    parser.add_argument("--full", action="store_true", help="与 --json 同用时附带文件全文")
    args = parser.parse_args(argv)

    result = generate(legacy_path=args.legacy, plugins_dir=args.plugins_dir, wifi=args.wifi,
                      url=args.url, portal_type=args.portal_type, force=args.force,
                      dry_run=args.dry_run)

    if args.json:
        payload = dict(result)
        if not args.full:
            payload.pop("login_js", None)
            payload.pop("manifest", None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("WiFi 名称：%s（插件目录名）" % result["wifi"])
        print("门户类型：%s" % result["portal_type"])
        print("旧配置：%s" % (result["legacy_config"] or "（未找到）"))
        print("插件目录：%s" % result["plugin_dir"])
        for path in result["written"]:
            print("  已写入：%s" % path)
        for item in result["skipped"]:
            print("  已跳过：%s（%s）" % (item["path"], item["reason"]))
        print("待合并进 config.json 的网络片段：")
        print(json.dumps(result["network_snippet"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
