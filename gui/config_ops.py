# -*- coding: utf-8 -*-
"""GUI 侧的配置 / 插件文件操作助手。

所有写盘动作都集中在这里，界面层只调用这些函数，便于审计：
    * 配置文件：`config.json`（走 core.config.Config.save）
    * 插件文件：`plugins/<WiFi名称>/manifest.json`、`plugins/<WiFi名称>/login.js`
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from core import config as config_mod
from core import paths
from core import plugins as plugins_mod

OPTION_TYPE_LABELS = [
    ("text", "文本"),
    ("password", "密码"),
    ("number", "数字"),
    ("select", "下拉选择"),
    ("checkbox", "勾选"),
    ("hidden", "隐藏"),
]


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def plugins_dir(cfg: dict | None = None) -> str:
    return plugins_mod.resolve_plugins_dir(cfg or {})


def plugin_dir(cfg: dict | None, wifi: str) -> str:
    return os.path.join(plugins_dir(cfg), str(wifi or "").strip())


def manifest_path(cfg: dict | None, wifi: str) -> str:
    return os.path.join(plugin_dir(cfg, wifi), "manifest.json")


def js_path(cfg: dict | None, wifi: str) -> str:
    return os.path.join(plugin_dir(cfg, wifi), "login.js")


# --------------------------------------------------------------------------- #
# 读写
# --------------------------------------------------------------------------- #
def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def write_json(path: str, data: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def read_js(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_js(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


# --------------------------------------------------------------------------- #
# 插件
# --------------------------------------------------------------------------- #
def list_plugins(cfg: dict | None = None) -> list:
    """列出插件目录下所有插件（含校验失败的，便于界面提示）。"""
    root = plugins_dir(cfg)
    result = []
    for directory in plugins_mod.discover(root):
        result.append(plugins_mod.load_plugin(directory))
    return result


def get_plugin(cfg: dict | None, wifi: str):
    directory = plugin_dir(cfg, wifi)
    if not os.path.isdir(directory):
        return None
    return plugins_mod.load_plugin(directory)


def plugin_report(cfg: dict | None = None) -> list:
    return [p.to_dict() for p in list_plugins(cfg)]


def validate_manifest(manifest: dict, wifi: str, js: str = "") -> list:
    """在不落盘的前提下校验一份 manifest（用于保存前预检）。"""
    plugin = plugins_mod.Plugin(plugin_dir(None, wifi or "unknown"), manifest, js)
    errors = list(plugins_mod.validate(plugin))
    for key in plugins_mod.REQUIRED_MANIFEST_KEYS:
        if key not in (manifest or {}):
            errors.append(f"manifest.json 缺少必填字段：{key}")
    return sorted(set(errors))


def save_manifest(cfg: dict | None, wifi: str, manifest: dict) -> str:
    manifest = dict(manifest or {})
    manifest["wifi"] = wifi  # 目录名 = WiFi 名称，强制一致
    manifest.setdefault("spec_version", "1.0")
    manifest.setdefault("name", wifi)
    return write_json(manifest_path(cfg, wifi), manifest)


def js_skeleton(wifi: str, url: str = "") -> str:
    """新建插件时生成的 login.js 骨架（已满足插件契约，可直接改选择器）。"""
    return f"""/* CampusNet 登录插件：{wifi}
 * 契约见 PLUGIN_SPEC.md：window.CampusNetPlugin = {{
 *     match(ctx), needsCaptcha(ctx),
 *     fill(ctx), submit(ctx), success(ctx),   // 浏览器通道（Selenium）
 *     request(ctx)                            // HTTP 通道（可选）
 * }}
 * ctx = {{network, url, account, password, ip, credentials{{}}, options{{}}}}
 * 登录页 URL：{url or "(请在 manifest.json 的 login.url 中配置)"}
 * 所有函数都返回 {{ok: bool, ...}}，失败时给出 error 文案。
 */
(function () {{
  var PLUGIN = {{
    match: function (ctx) {{
      return true;  // 本插件只服务 WiFi：{wifi}
    }},

    needsCaptcha: function (ctx) {{
      return false;  // 有验证码时返回 true（需人工处理）
    }},

    fill: function (ctx) {{
      var q = function (sel) {{ return document.querySelector(sel); }};
      var account = q("input[name='username'], #username");
      if (account) {{
        account.value = ctx.account || "";
        account.dispatchEvent(new Event("input", {{bubbles: true}}));
      }}
      var password = q("input[name='password'], #password");
      if (password) {{
        password.value = ctx.password || "";
        password.dispatchEvent(new Event("input", {{bubbles: true}}));
      }}
      return {{ok: true, filled: ["account", "password"]}};
    }},

    submit: function (ctx) {{
      var btn = document.querySelector("input[type='submit'], button[type='submit'], #login");
      if (!btn) {{
        return {{ok: false, error: "未找到登录按钮，请按实际登录页修改 submit()"}};
      }}
      btn.click();
      return {{ok: true}};
    }},

    success: function (ctx) {{
      var text = (document.body && document.body.innerText) || "";
      if (/注销|退出|已登录|登录成功|logout|success/i.test(text)) {{
        return {{ok: true}};
      }}
      return {{ok: false, error: "未检测到登录成功标志"}};
    }},

    request: function (ctx) {{
      return {{ok: false, error: "未实现 HTTP 通道（如需可在 manifest.http.attempts 配置）"}};
    }}
  }};

  window.CampusNetPlugin = PLUGIN;
}})();
"""


def manifest_template(wifi: str, name: str = "", url: str = "", need_login: bool = True,
                      driver: str = "auto", description: str = "",
                      credentials: list | None = None, options: list | None = None) -> dict:
    return {
        "spec_version": "1.0",
        "id": f"{wifi}-portal",
        "name": name or f"{wifi} 登录插件",
        "description": description or "由 GUI 新建：请按实际登录页补全 login.js 的选择器。",
        "wifi": wifi,
        "need_login": bool(need_login),
        "generated": {
            "by": "gui/plugin_page",
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "login": {
            "url": url,
            "driver": driver,
            "timeout_seconds": 10,
            "js_wait_seconds": 2,
            "success": {
                "keywords": ["注销", "退出", "已登录", "登录成功", "logout", "success"],
                "failure_keywords": ["密码错误", "认证失败", "登录失败", "error"],
            },
            "captcha": {"enabled": False, "input_selector": "", "image_selector": ""},
        },
        "credentials": credentials or [
            {"key": "account", "label": "账号", "type": "text", "required": True,
             "js_selector": "input[name='username']", "from_js": True},
            {"key": "password", "label": "密码", "type": "password", "required": True,
             "js_selector": "input[name='password']", "from_js": True},
        ],
        "options": options or [],
        "http": {"attempts": []},
    }


def create_plugin(cfg: dict | None, wifi: str, name: str = "", url: str = "",
                  need_login: bool = True, driver: str = "auto",
                  with_js: bool = True, register_network: bool = True) -> dict:
    """一键新建插件：plugins/<WiFi 名称>/manifest.json (+ login.js)。"""
    wifi = str(wifi or "").strip()
    if not wifi:
        return {"ok": False, "message": "WiFi 名称不能为空"}
    directory = plugin_dir(cfg, wifi)
    manifest_file = manifest_path(cfg, wifi)
    if os.path.isfile(manifest_file):
        return {"ok": False, "message": f"插件已存在：{manifest_file}"}

    manifest = manifest_template(wifi, name=name, url=url, need_login=need_login,
                                 driver=driver)
    os.makedirs(directory, exist_ok=True)
    save_manifest(cfg, wifi, manifest)
    if with_js:
        js_file = js_path(cfg, wifi)
        if not os.path.isfile(js_file):
            write_js(js_file, js_skeleton(wifi, url))

    plugin = plugins_mod.load_plugin(directory)
    return {
        "ok": not plugin.errors,
        "message": "插件已创建" if not plugin.errors
        else "插件已创建，但校验未通过：" + "；".join(plugin.errors),
        "directory": directory,
        "manifest": plugin.manifest,
        "errors": plugin.errors,
    }


# --------------------------------------------------------------------------- #
# 网络 / 计划
# --------------------------------------------------------------------------- #
def network_names(cfg: dict) -> list:
    return list((cfg.get("networks") or {}).keys())


def ensure_network(cfg: dict, name: str) -> dict:
    """确保 cfg["networks"] 中存在该网络（按默认结构补全）。"""
    name = str(name or "").strip()
    if not name:
        return {}
    networks = cfg.setdefault("networks", {})
    if name not in networks:
        networks[name] = config_mod.normalize_network(name, {}, None)
    else:
        networks[name] = config_mod.normalize_network(name, networks[name],
                                                      cfg.get("traffic", {}).get("defaults"))
    return networks[name]


def remove_network(cfg: dict, name: str) -> bool:
    networks = cfg.get("networks") or {}
    if name in networks:
        networks.pop(name)
        return True
    return False


def networks_view(cfg: dict) -> list:
    """网络列表（供 WLAN 页表格）。"""
    plugins = {p.wifi: p for p in list_plugins(cfg)}
    rows = []
    for name, net in (cfg.get("networks") or {}).items():
        plugin = plugins.get(str(net.get("plugin") or name)) or plugins.get(name)
        rows.append({
            "name": name,
            "label": net.get("label") or name,
            "profile": net.get("profile") or name,
            "primary": bool(net.get("primary")),
            "need_login": bool(net.get("need_login")),
            "plugin": net.get("plugin") or name,
            "plugin_exists": plugin is not None,
            "plugin_ok": bool(plugin and not plugin.errors),
            "plugin_errors": list(plugin.errors) if plugin else [],
            "guard_enabled": bool((net.get("guard") or {}).get("enabled")),
            "login_url": ((net.get("login") or {}).get("url") or ""),
        })
    return rows


def schedules(cfg: dict) -> list:
    rules = cfg.get("schedules")
    return rules if isinstance(rules, list) else []


def save_schedules(cfg: dict, rules: list) -> list:
    cfg["schedules"] = [config_mod.normalize_schedule(r, i) for i, r in enumerate(rules)]
    return cfg["schedules"]


def save_config(config_obj) -> dict:
    """规范化后写盘。返回写入后的配置。"""
    config_obj.data = config_mod.normalize(config_obj.data)
    config_obj.save()
    return config_obj.data


def config_backup_path() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(paths.STATE_DIR if hasattr(paths, "STATE_DIR") else paths.PROJECT_DIR,
                        f"config.backup-{stamp}.json")


__all__ = [
    "plugins_dir", "plugin_dir", "manifest_path", "js_path",
    "read_json", "write_json", "read_js", "write_js",
    "list_plugins", "get_plugin", "plugin_report", "validate_manifest",
    "save_manifest", "manifest_template", "js_skeleton", "create_plugin",
    "network_names", "ensure_network", "remove_network", "networks_view",
    "schedules", "save_schedules", "save_config", "OPTION_TYPE_LABELS",
]
