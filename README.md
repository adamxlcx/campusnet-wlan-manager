---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f0c75eeee44aadb9ea76f29ff93749a3_2666e27bc6d711f1820a525400638852
    ReservedCode1: EeKrvoamTp0vDwIJSeAQ7u79/LP2W4OlOSCMXG5ghg8kXzwqzU+eY22bLgS/I6Pn1ppwqF5u33c+ni8K3/pOL1mBJs/+e8kVHC2OQB0XX77hniYgwxE5/x+cq7Db1OxK1+feuL1b6U3pH6xYHY41QudO+E3cz9gKz1e6/MA+75s6uw0jW7KoDJF754I=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f0c75eeee44aadb9ea76f29ff93749a3_2666e27bc6d711f1820a525400638852
    ReservedCode2: EeKrvoamTp0vDwIJSeAQ7u79/LP2W4OlOSCMXG5ghg8kXzwqzU+eY22bLgS/I6Pn1ppwqF5u33c+ni8K3/pOL1mBJs/+e8kVHC2OQB0XX77hniYgwxE5/x+cq7Db1OxK1+feuL1b6U3pH6xYHY41QudO+E3cz9gKz1e6/MA+75s6uw0jW7KoDJF754I=
---

# CampusNet

> **A general-purpose WLAN manager for campus networks on Windows — scheduled network switching, portal auto-login, download traffic guard and connectivity watchdog, with a PyQt5 tray GUI.**
>
> **面向 Windows 的通用化校园网 WLAN 管理程序：定时切换网络、门户网页自动登录、下载流量保护、连通性看门狗，带 PyQt5 托盘界面。**

[English](#english-documentation) | [简体中文](#简体中文文档)

---

## English Documentation

CampusNet is a Windows WLAN manager built on a **config-driven core engine plus one plugin per WiFi network**. Every parameter that used to be hard-coded inside a single script — SSID, account, password, ISP, portal URL, traffic thresholds and time rules — is externalized into `config.json` and per-WiFi plugin directories. The same `core/` engine drives both the **PyQt5 tray GUI** (`app.py`) and the **command-line interface** (`cli.py`); both read the same `config.json`, so a change made in the GUI takes effect in the CLI immediately.

A typical deployment: connect to a metered network at night, switch back to the campus network before the morning lecture with automatic portal login, and disconnect automatically when a download exceeds the configured traffic threshold.

### Table of Contents

1. [Introduction](#1-introduction)
2. [Features](#2-features)
3. [Architecture](#3-architecture)
4. [Requirements and Installation](#4-requirements-and-installation)
5. [Quick Start](#5-quick-start)
6. [Configuration Reference](#6-configuration-reference)
7. [Plugin Development Guide](#7-plugin-development-guide)
8. [Packaging as a Standalone EXE](#8-packaging-as-a-standalone-exe)
9. [FAQ](#9-faq)
10. [Disclaimer](#10-disclaimer)
11. [License](#11-license)
12. [Acknowledgements](#12-acknowledgements)

### 1. Introduction

Campus networks usually require two things that Windows does not do by itself: switching between several wireless networks on a timetable, and completing a web portal (captive portal) login after each switch. CampusNet automates both and adds two safety features — a per-network download traffic guard and a connectivity watchdog.

The program is **generic**: it contains no network-specific values. You declare your networks in `config.json`, and if a network needs a portal login you drop in a plugin directory that knows how to fill and submit that page.

### 2. Features

| Area | Capability |
|---|---|
| Scheduled switching | Smart-alarm style rules: `once` / `daily` / `weekly` (by weekday) / `monthly` (by day), local time, per-rule catch-up window (`window_minutes`) so a run missed by a few minutes still executes inside the window, per-rule execution state so a rule never fires twice on the same day, retry interval and maximum attempts per day |
| Portal auto-login | Per-WiFi plugin (`login.js`) injected via Selenium into the locally installed Edge or Chrome; optional pure-HTTP channel declared by the plugin (`http.attempts`); captcha detected → the automatic flow stops and asks the user to handle it; custom fields such as ISP are written by the plugin |
| Download traffic guard | Per-WiFi thresholds: speed threshold with unit (`KB/s` `MB/s` `GB/s`) sustained for N seconds **and** accumulated volume threshold (`KB` `MB` `GB`); when both are met CampusNet disconnects and shows a popup asking whether to keep the download — answering "deny" leaves the adapter disconnected; optional process inspection ranks the top traffic consumers |
| Connectivity watchdog | Periodic ping checks (interval, target, timeout, consecutive-failure threshold) plus an **independent** adapter-restart switch (cooldown, prefer disable/enable recycle, optional reconnect after restart) |
| Tray GUI | PyQt5 tray icon: double-click restores the main window, right-click jumps to any page; icon colour follows connectivity — green = reachable, red = unreachable, neutral grey = watchdog disabled; 7 pages: Overview, WLAN, Schedules, Plugins, Health, Traffic, Settings |
| Light / dark theme | Two QSS themes, persisted in `config.json` together with every page switch and threshold |
| CLI parity | `status` `daemon` `connect` `connect-billing` `connect-campus` `disconnect` `login` `health-check` `traffic` `profiles` `networks` `schedules` `plugins` `plugin-validate` `plugin-make` `migrate` `selftest` — most accept `--json` |
| Plugin hot reload | Plugins are re-read from disk when their files change; saving a plugin in the GUI takes effect without restarting the program |
| Legacy migration | `cli.py migrate` converts an old single-script `config.json`; `cli.py plugin-make` / `tools/make_plugin_from_legacy.py` generate a plugin from the old built-in match rules |
| Autostart & task scheduler | Per-user autostart (`HKCU\...\Run`) and Windows Task Scheduler registration (`schtasks /SC ONLOGON`), each with its own switch; highest privileges are attempted first and automatically degraded to normal privileges |
| Logging | Rotating file log plus an in-memory ring buffer that feeds the GUI log viewer |

### 3. Architecture

**Two layers, one engine.**

| Layer | Path | Responsibility |
|---|---|---|
| Core engine | `core/` | GUI-free Windows logic: paths, configuration model, runtime state, WLAN control, health checks, traffic accounting, plugin loading, portal execution, scheduling and the background service loop |
| Per-WiFi plugin | `plugins/<WiFi name>/` | Describes *how to log in* for exactly one network: `manifest.json` (metadata, selectors, declared credentials and options) and `login.js` (page hooks) |

Design rules:

* **The core engine contains no network-specific values.** SSID, account, password, ISP, portal URL, traffic thresholds and time rules all come from `config.json` and the plugins.
* **One entry per WiFi**: `config.json → networks.<WiFi name>` holds whether login is required, the portal URL, the plugin name and the download-guard thresholds.
* **One plugin per WiFi**: `plugins/<WiFi name>/`, where the directory name must equal the WiFi name. A network with `need_login=false` needs a config entry only, no plugin.
* **Units are converted centrally**: `core/traffic.py` normalises `KB/s` `MB/s` `GB/s` and `KB` `MB` `GB` to bytes before comparing.

```
CampusNet/
├─ app.py                GUI entry point (PyQt5; runnable with pythonw to hide the console)
├─ CampusNet.vbs         Double-click launcher for the GUI (no console window; accepts --minimized)
├─ CampusNet.bat         Batch launcher for the GUI
├─ CampusNet_debug.bat   Debug launcher (keeps the console so exceptions and logs are visible)
├─ gui/
│  ├─ context.py         AppContext: single entry point for config / core / service / theme / async tasks
│  ├─ main_window.py     Main window: left navigation + right pages + status bar + tray integration
│  ├─ tray.py            QSystemTrayIcon: double-click opens the window, right-click menu opens any page or exits
│  ├─ theme.py           Light / dark QSS themes and tray colour rules (green / red / neutral)
│  ├─ icons.py           Tray and status icon rendering (three states)
│  ├─ widgets.py         Reusable controls: cards, forms, switch rows, unit inputs
│  ├─ startup.py         Autostart (HKCU Run) and Windows scheduled task (schtasks) registration
│  ├─ config_ops.py      Config and plugin read / validate / create helpers for the GUI
│  └─ pages/             Overview / WLAN / Schedules / Plugins / Health / Traffic / Settings
├─ core/
│  ├─ paths.py           Program directory, config and state files, log and temp directories
│  ├─ logging_setup.py   Rotating file log + in-memory ring buffer for the GUI log viewer
│  ├─ config.py          Config model: defaults, read/write, validation, normalisation, legacy migration
│  ├─ state.py           Runtime state persistence + action mutex (keeps scheduler and daemon from racing)
│  ├─ wlan.py            netsh-based WLAN control: list/connect/disconnect/status/adapter restart/interface probing
│  ├─ health.py          Connectivity check (switch) and adapter restart (independent switch)
│  ├─ traffic.py         Per-session up/down accounting + per-WiFi download guard
│  ├─ plugins.py         Plugin discovery, validation, manifest + login.js parsing, hot reload, JS snippets
│  ├─ portal.py          Portal login executor: browser channel (Selenium, local Edge/Chrome) with optional requests fallback
│  ├─ scheduler.py       Smart-alarm rules (once/daily/weekly/monthly) + next_run computation + catch-up window
│  ├─ popup.py           tkinter popup (allow / deny, deny keeps the connection down)
│  ├─ sysutil.py         Process and system helpers (traffic ranking, administrator check)
│  └─ service.py         Background loop: scheduling + health polling + download guard
├─ plugins/
│  └─ JOU/               Sample plugin generated from the legacy match rules (Dr.COM / eportal portal)
│     ├─ manifest.json
│     └─ login.js
├─ tools/
│  ├─ make_plugin_from_legacy.py   Legacy built-in rules → plugin migration tool
│  └─ smoke_gui.py                 Offscreen GUI smoke test
├─ cli.py                Command-line interface
├─ config.json           Runtime configuration (no hard-coded network parameters)
├─ PLUGIN_SPEC.md        Plugin specification (layout, manifest fields, login.js contract, examples)
└─ requirements.txt      Dependencies
```

**Where files live at runtime**

| Run mode | Configuration & plugins | User data (state, logs, temp) |
|---|---|---|
| Source (`python app.py`) | The project directory | `%LOCALAPPDATA%\CampusNet` (override with the `CAMPUSNET_HOME` environment variable) |
| Frozen (`CampusNet.exe`) | The directory containing `CampusNet.exe` when writable, otherwise `%LOCALAPPDATA%\CampusNet` | Same directory as above |

The frozen build is portable: copy the EXE to a writable folder and `config.json`, `plugins/`, `state.json` and `logs/` are created next to it.

### 4. Requirements and Installation

| Item | Requirement |
|---|---|
| OS | Windows 10 / 11 (the program uses `netsh wlan`, the `HKCU` Run key and `schtasks`) |
| Python | Python 3 (the development and self-test environment uses Python 3.11 and 3.14; no minimum version is declared in the repository) |
| Browser | Edge or Chrome installed locally (needed by the Selenium browser channel, which is the primary login channel) |
| Node.js | **Not required** — plugins are plain `.js` files executed by the browser engine, never by Node |

```powershell
pip install -r requirements.txt
```

| Dependency | Used by |
|---|---|
| `psutil>=5.9.0` | Adapter counters and per-process traffic ranking |
| `requests>=2.28.0` | Optional HTTP fallback channel for portal login |
| `selenium>=4.15.0` | Browser channel (primary): injects the plugin `login.js` |
| `PyQt5>=5.15.0` | GUI only — the core layer and `cli.py` do not depend on it |

`tkinter` (the popup) is part of the Python standard library, so no extra package is needed.

### 5. Quick Start

```powershell
cd <project directory>
pip install -r requirements.txt

# Graphical interface (recommended: double-click CampusNet.vbs for a console-free start)
python  app.py                # start and show the main window
pythonw app.py --minimized    # no console window, start minimised in the tray

# Command line
python cli.py status          # current network / configuration overview
python cli.py profiles        # wireless profiles saved on this machine (for the GUI picker)
python cli.py selftest        # full core-layer self test
```

`app.py` options:

| Option | Effect |
|---|---|
| `--minimized` | Start directly in the tray |
| `--no-service` | Start the GUI without the background service thread |
| `--dry-run` | Background service runs without performing real network actions |
| `--config <path>` | Use a specific configuration file |
| `--version` | Print the version and exit |
| `--selftest` | Headless core-layer self test; the result is written to the log, then the program exits |

GUI launchers:

| Launcher | Effect |
|---|---|
| `CampusNet.vbs` (double-click) | Console-free start |
| `wscript CampusNet.vbs --minimized` | Start straight to the tray |
| `CampusNet.bat` | Batch start (a console window may flash briefly) |
| `CampusNet_debug.bat` | Keeps the console so exceptions and log output are visible |

The tray icon offers every page in its right-click menu; the window close button hides the window to the tray instead of exiting.

Garbled Chinese characters in the console need no action — `cli.py` switches the console code page on start-up.

### 6. Configuration Reference

`config.json` is the single source of truth and is read again on every daemon loop, so edits apply immediately. All examples below use placeholders — never commit real credentials.

| Block | Purpose |
|---|---|
| `app` | Name / version, UI theme (`light` / `dark`), start minimised, close to tray, tray shows network status |
| `app.startup` | Autostart switch, delay in seconds, scheduled-task switch, task name prefix |
| `wlan` | Adapter interface name (auto-detected when empty), connect timeout, verify after connect |
| `networks.<WiFi>` | Per-network `profile` / `label` / **`need_login`** / `plugin` / `login` (url, driver, credentials, options) / `guard` (enabled, speed, sustained_seconds, volume, sampling, process inspection) |
| `health` | Connectivity check switch and interval, ping target, failure threshold |
| `health.restart` | **Independent adapter-restart switch**, cooldown, prefer disable/enable recycle, reconnect after restart |
| `traffic` | Global sampling parameters and `traffic.defaults` (thresholds used by networks without their own entry) |
| `schedules[]` | Smart-alarm rules: `repeat.mode` (`once` / `daily` / `weekly` / `monthly`), months, weekdays, days, time, `window_minutes` catch-up window, target network, login requirement, retry policy |
| `portal` | Browser driver (`auto` / `edge` / `chrome`), headless flag, timeouts, whether the `requests` fallback is allowed, plugins directory |
| `popup` | Popup switch, title, timeout, whether "deny" keeps the adapter disconnected |
| `logging` | Log level, rotation size, backup count, number of in-memory records |

Minimal example:

```jsonc
{
  "wlan": { "interface": "", "connect_timeout": 25, "verify_after_connect": true },
  "networks": {
    "CAMPUS_WIFI": {
      "profile": "CAMPUS_WIFI",
      "label": "Campus network",
      "need_login": true,
      "plugin": "CAMPUS_WIFI",
      "login": {
        "url": "http://portal.example.edu/",
        "driver": "",
        "credentials": { "account": "YOUR_STUDENT_ID", "password": "YOUR_PASSWORD" },
        "options": { "isp": "@unicom" }
      },
      "guard": { "enabled": false }
    },
    "BILLING_WIFI": {
      "profile": "BILLING_WIFI",
      "label": "Metered network",
      "need_login": false,
      "guard": {
        "enabled": true,
        "speed":  { "value": 2.0,  "unit": "MB/s" },
        "sustained_seconds": 10,
        "volume": { "value": 50.0, "unit": "MB" }
      }
    }
  }
}
```

Threshold units accept any of the supported units, so `{ "value": 2048, "unit": "KB/s" }` and `{ "value": 0.002, "unit": "GB/s" }` are equivalent to `2.0 MB/s`:

```jsonc
"guard": {
  "speed":  { "value": 2.0,   "unit": "MB/s" },   // 2048 KB/s or 0.002 GB/s also work
  "sustained_seconds": 10,                        // how long the speed must stay above the threshold
  "volume": { "value": 50.0,  "unit": "MB" }      // 51200 KB or 0.05 GB also work
}
```

The download guard fires when **both** conditions hold (speed above the threshold for the sustained period **and** accumulated volume above the threshold): CampusNet disconnects and asks via the popup whether to keep downloading; "deny" keeps the adapter disconnected.

Scheduling model:

* `repeat.mode`: `once` (uses `date`), `daily`, `weekly` (uses `weekdays`), `monthly` (uses `days`).
* `time` is local time; `window_minutes` is the catch-up window — if the exact moment is missed, the rule still runs inside the window, and expires beyond it.
* Every rule keeps its own execution state (`core/state.py`), so a rule already executed today does not fire again. `python cli.py schedules` prints each rule and its next run time.

### 7. Plugin Development Guide

> The complete specification — directory layout, every `manifest.json` field with a real example, the full `login.js` contract — is in **[PLUGIN_SPEC.md](PLUGIN_SPEC.md)**. The summary below is the minimum you need to get started.

Layout (the directory name must equal the WiFi name):

```
plugins/CAMPUS_WIFI/
├─ manifest.json     # plugin manifest
└─ login.js          # matching and login logic
```

Key `manifest.json` fields:

```jsonc
{
  "spec_version": "1.0",
  "id": "campus-eportal-drcom",
  "name": "Campus network (Dr.COM / eportal portal)",
  "wifi": "CAMPUS_WIFI",                 // must equal the directory name
  "need_login": true,
  "login": {
    "url": "http://portal.example.edu/",
    "driver": "auto",
    "timeout_seconds": 10
  },
  "credentials": [
    { "key": "account", "label": "Account", "type": "text",
      "js_selector": "input[name='DDDDD']", "from_js": true },
    { "key": "password", "label": "Password", "type": "password",
      "js_selector": "input[name='upass']", "from_js": true }
  ],
  "options": [
    { "key": "isp", "label": "ISP", "type": "select",
      "choices": [ { "label": "Unicom", "value": "@unicom" },
                   { "label": "Mobile", "value": "@cmcc" },
                   { "label": "Telecom", "value": "@telecom" } ] }
  ]
}
```

`manifest.json` declares the form fields; the GUI renders them automatically (`text` / `password` → input, `select` → dropdown with `choices`), and the values the user enters are written to `config.json → networks.<WiFi>.login.credentials` / `.options`.

`login.js` must define a global object `CampusNetPlugin`; `core/plugins.py` validates the required hooks on load:

| Hook | Required | Purpose |
|---|---|---|
| `match(ctx)` | yes | Is the current page this portal's login page? |
| `fill(ctx)` | yes | Write account / password / options into the form |
| `submit(ctx)` | yes | Click the submit button or call the page submit function |
| `success(ctx)` | yes | Decide whether the login succeeded |
| `needsCaptcha(ctx)` | no | Returning `true` stops the automatic flow and asks the user |
| `credentials(ctx)` | no | Read credential fields back from the page (GUI "sync") |
| `options(ctx)` | no | Read option candidates back from the page (GUI "sync") |
| `request(ctx)` | no | Build the HTTP-channel request (used when no browser is available) |

`ctx` is assembled by `core/portal.py` and carries `network`, `url`, `account`, `password`, `credentials`, `options` and `ip`. **Plugins never store credentials** — always read them from `ctx`.

Adding a new WiFi network:

1. In the GUI open the **Plugins** page and create a plugin named after the WiFi (its directory name must match exactly).
2. Fill in the portal URL and whether login is required, then edit `login.js` and implement the four required hooks.
3. Click **Validate plugin** (or run `python cli.py plugin-validate CAMPUS_WIFI`) and confirm it reports `ok=true, errors=[]`.
4. Connect that WiFi from the **WLAN** page, or add a rule on the **Schedules** page; when login is required the network's own plugin is invoked automatically.

Migrating the legacy built-in match rules into a plugin:

```powershell
python cli.py plugin-make CAMPUS_WIFI --force    # generates plugins/CAMPUS_WIFI/{manifest.json,login.js}
python cli.py plugin-validate CAMPUS_WIFI        # validates the generated plugin
```

The migration tool reads the legacy `config.json`, detects the portal type (currently `Dr.COM` / `eportal`) and also merges the account, password, ISP and portal URL into `config.json → networks.<WiFi>`.

### 8. Packaging as a Standalone EXE

The frozen build is a single windowed executable produced with PyInstaller. Run the following from the project directory after installing the dependencies plus PyInstaller:

```powershell
pip install pyinstaller

pyinstaller --noconfirm --clean --onefile --windowed --name CampusNet `
  --collect-all selenium `
  --icon <your-icon>.ico `
  app.py
```

Notes:

* `--windowed` removes the console window; `--onefile` produces a single EXE.
* `--collect-all selenium` bundles Selenium and the drivers it needs — omitting it is the usual cause of a driver error in the packaged program.
* `--icon` is optional; generate an `.ico` (e.g. with Pillow) or use your own artwork.
* If a module is reported missing at runtime, add `--hidden-import <module>`.
* The EXE keeps its data portable: `config.json`, `plugins/`, `state.json` and `logs/` live next to the executable when that directory is writable, otherwise they fall back to `%LOCALAPPDATA%\CampusNet`.

Verify the build without opening the GUI:

```powershell
.\dist\CampusNet.exe --version
.\dist\CampusNet.exe --selftest    # writes logs\selftest-result.json and exits
```

### 9. FAQ

**Where are my configuration, logs and state stored?**
Source runs keep `config.json` and `plugins/` in the project directory and user data in `%LOCALAPPDATA%\CampusNet` (overridable with `CAMPUSNET_HOME`). Frozen runs keep everything next to `CampusNet.exe` when that directory is writable, otherwise in `%LOCALAPPDATA%\CampusNet`. The log file is `logs\campusnet.log`.

**The CLI prints garbled Chinese characters.**
Nothing to fix — `cli.py` switches the console code page on start-up. If you still see mojibake, run the command in Windows Terminal or PowerShell rather than a legacy console host.

**The live speed and session totals stay at 0 on the Traffic page.**
Check `logs\campusnet.log` for a `[<WiFi name>] 流量统计会话开始` line followed by continuous samples; if the session never starts, confirm that the Traffic page has a guard entry for the currently connected WiFi (after switching networks, add an entry for the new one). A guard entry is per WiFi, and the global `traffic.enabled` switch must also be on.

**The tray icon stays grey.**
Grey means the connectivity watchdog is disabled, so the colour is intentionally static. Enable it on the **Health** page (interval, ping target, timeout, failure threshold) — this is independent from the adapter-restart switch.

**Creating the Windows scheduled task fails.**
`schtasks /SC ONLOGON` can be created by a normal user for the current user account; requesting highest privileges (`/RL HIGHEST`) requires running CampusNet as administrator. The program tries highest privileges first and degrades to normal automatically. The Settings page shows the full `schtasks` command so you can create the task manually, and the autostart switch is an alternative for most cases.

**Portal login fails.**
Check the portal URL and the selectors in `login.js` (`python cli.py login --probe-options` re-reads the page's custom options before logging in), make sure the entered account/password/ISP values are correct, and confirm a browser channel is usable (`portal.driver` = `auto` / `browser` vs `requests`). If the portal shows a captcha, automatic login stops by design and asks you to complete it manually.

**Do I need Node.js?**
No. Plugins are plain JavaScript executed by the browser via Selenium.

**Are my credentials sent anywhere?**
No. Credentials live only in your local `config.json`, plugins never store them, and nothing is uploaded. Keep the file out of version control once you fill in real values — the repository ships placeholders only.

**Can I manage more than one campus network?**
Yes. Add one entry under `networks` per WiFi; only the networks with `need_login=true` need a plugin.

### 10. Disclaimer

* This project is provided for personal and educational use. Use it only on networks you are authorised to access.
* Automatically logging in to a campus portal may conflict with your institution's network policy. **Check your school's rules first** — you are responsible for how you use this program.
* The software is provided "as is", without warranty of any kind. The authors are not liable for account penalties, network charges, data loss or any other damage arising from its use.

### 11. License

Released under the [MIT License](LICENSE). Copyright (c) 2026 CampusNet contributors.

### 12. Acknowledgements

* [PyQt5](https://pypi.org/project/PyQt5/) — tray GUI, themes and page framework.
* [Selenium](https://www.selenium.dev/) — browser channel that injects the plugin login scripts.
* [psutil](https://pypi.org/project/psutil/) — adapter counters and per-process traffic ranking.
* [requests](https://requests.readthedocs.io/) — optional HTTP login channel.
* [PyInstaller](https://pyinstaller.org/) — single-file windowed packaging.
* Dr.COM / eportal portal pages, whose form structure is documented in the bundled `plugins/JOU` sample plugin.

---

## 简体中文文档

CampusNet 是一个基于**「通用化核心引擎 + 每 WiFi 一个插件」**结构的 Windows 无线网络管理程序。原先写死在单文件脚本里的 SSID、账号、密码、运营商、门户地址、流量阈值与时间规则，全部抽到 `config.json` 与按 WiFi 划分的插件目录中；同一套 `core/` 引擎同时驱动 **PyQt5 托盘界面**（`app.py`）与**命令行形态**（`cli.py`），两者读取同一份 `config.json`，界面改完命令行立即生效。

典型用法：夜间连接计费网络，清晨切回校园网并自动完成门户登录；下载流量超过阈值时自动断开并询问是否保留。

### 目录导航

1. [项目简介](#一项目简介)
2. [功能特性](#二功能特性)
3. [架构说明](#三架构说明)
4. [环境要求与安装](#四环境要求与安装)
5. [快速开始](#五快速开始)
6. [配置说明](#六配置说明)
7. [插件开发指引](#七插件开发指引)
8. [打包为 EXE](#八打包为-exe)
9. [常见问题](#九常见问题)
10. [免责声明](#十免责声明)
11. [开源许可](#十一开源许可)
12. [致谢](#十二致谢)

### 一、项目简介

校园网通常需要 Windows 自身不做两件事：按时间表在多张无线网络之间切换、每次切换后完成网页门户（captive portal）认证。CampusNet 把这两件事自动化，并额外提供两项保护能力——按网络配置的下载流量保护与连通性看门狗。

程序本身是**通用**的：代码中不含任何具体网络参数。你在 `config.json` 中登记自己的网络；需要网页登录的网络，再放一个了解该登录页结构的插件目录即可。

### 二、功能特性

| 能力 | 说明 |
|---|---|
| 定时切换 | 智能闹钟式规则：`once`（仅一次）/ `daily`（每天）/ `weekly`（按星期）/ `monthly`（按日期），本地时间；每条规则带 `window_minutes` 补执行窗口，错过整点后在窗口内仍会补执行；每条规则独立记录执行状态，当天已执行不会重复触发；支持重试间隔与每日最大尝试次数 |
| 门户自动登录 | 按 WiFi 使用插件（`login.js`），通过 Selenium 注入本机 Edge 或 Chrome 执行；可选用插件声明的纯 HTTP 通道（`http.attempts`）；识别到验证码时自动流程中止并提示人工处理；运营商等自定义选项由插件写入 |
| 下载流量保护 | 按 WiFi 配置阈值：网速阈值 + 单位（`KB/s` `MB/s` `GB/s`）持续 N 秒，**且**累计流量阈值（`KB` `MB` `GB`）；两个条件同时满足即断开连接并弹窗询问是否保留下载——选择拒绝则保持断开；可选进程排查，列出流量占用最高的进程 |
| 连通性看门狗 | 周期性 ping 检测（间隔、目标地址、超时、连续失败阈值），并带**独立**的重启网卡开关（触发冷却、优先禁用-启用回收、重启后是否重连） |
| 托盘界面 | PyQt5 系统托盘：左键双击打开主界面，右键菜单直达任意分页；图标颜色跟随连通状态——绿=连通，红=不通，中性灰=连通性检测已关闭；共 7 个分页：概览、WLAN、计划、插件、网络检测、流量、设置 |
| 明暗主题 | 两套 QSS 主题，与各分页开关、阈值一并持久化到 `config.json` |
| 命令行同能力 | `status` `daemon` `connect` `connect-billing` `connect-campus` `disconnect` `login` `health-check` `traffic` `profiles` `networks` `schedules` `plugins` `plugin-validate` `plugin-make` `migrate` `selftest`，多数子命令支持 `--json` |
| 插件热加载 | 插件文件变化后从磁盘重新读取；在界面保存插件后无需重启程序即时生效 |
| 旧配置迁移 | `cli.py migrate` 将旧版单文件 `config.json` 迁移为通用配置；`cli.py plugin-make` / `tools/make_plugin_from_legacy.py` 由旧程序内置匹配规则生成插件 |
| 开机自启与计划任务 | 当前用户开机自启动（`HKCU\...\Run`）与 Windows 计划任务（`schtasks /SC ONLOGON`）两个独立开关；优先尝试最高权限，失败自动降级为普通权限 |
| 日志 | 滚动文件日志，另有内存环形缓冲供界面日志查看 |

### 三、架构说明

**两层结构，一套引擎。**

| 层次 | 路径 | 职责 |
|---|---|---|
| 核心引擎 | `core/` | 与界面无关的 Windows 逻辑：路径、配置模型、运行状态、无线控制、连通性检测、流量统计、插件加载、门户执行、调度与后台主循环 |
| 每 WiFi 一个插件 | `plugins/<WiFi名称>/` | 只描述某一个网络「怎么登录」：`manifest.json`（元信息、选择器、凭据与选项声明）与 `login.js`（页面钩子） |

设计约定：

* **核心引擎不含任何具体网络参数**：SSID、账号、密码、运营商、登录页 URL、流量阈值与时间规则全部来自 `config.json` 与插件。
* **每个 WiFi 一个条目**：`config.json → networks.<WiFi名称>`，记录是否需要登录、登录页地址、所属插件与下载保护阈值。
* **每个 WiFi 一个插件**：`plugins/<WiFi名称>/`，目录名必须等于 WiFi 名称；`need_login=false` 的网络只需配置条目，无需插件。
* **单位统一换算**：`core/traffic.py` 把 `KB/s` `MB/s` `GB/s` 与 `KB` `MB` `GB` 统一换算为字节后比较。

```
CampusNet/
├─ app.py                界面入口（PyQt5，可用 pythonw 隐藏控制台启动）
├─ CampusNet.vbs         双击启动界面（无控制台窗口，可传 --minimized）
├─ CampusNet.bat         批处理启动界面
├─ CampusNet_debug.bat   调试启动（保留控制台，便于查看异常与日志）
├─ gui/
│  ├─ context.py         AppContext：配置 / 核心层 / 后台服务 / 主题 / 异步任务的统一入口
│  ├─ main_window.py     主窗口：左侧导航 + 右侧分页 + 状态栏 + 托盘联动
│  ├─ tray.py            QSystemTrayIcon：双击开主界面，右键菜单开各分页或退出
│  ├─ theme.py           明/暗两套 QSS 主题与托盘配色规则（通绿 / 不通红 / 灰中性）
│  ├─ icons.py           托盘与状态图标绘制（三种状态）
│  ├─ widgets.py         卡片、表单、开关行、单位输入框等通用控件
│  ├─ startup.py         开机自启动（HKCU Run）与计划任务（schtasks）注册 / 注销
│  ├─ config_ops.py      界面侧的配置与插件读写 / 校验 / 新建封装
│  └─ pages/             概览 / WLAN / 计划 / 插件 / 网络检测 / 流量 / 设置 七个分页
├─ core/
│  ├─ paths.py           程序目录、配置与状态文件、日志目录、临时目录定位
│  ├─ logging_setup.py   滚动文件日志 + 内存环形缓冲（供界面日志查看）
│  ├─ config.py          配置模型：默认值、读写、校验、归一化、旧配置迁移
│  ├─ state.py           运行状态持久化 + 动作互斥锁（避免计划任务与守护进程并发改网络）
│  ├─ wlan.py            基于 netsh 的无线控制：列已存配置 / 连接 / 断开 / 状态 / 重启网卡 / 接口探测
│  ├─ health.py          连通性检测（开关）与重启网卡（独立开关）
│  ├─ traffic.py         单次连接上下行统计 + 按 WiFi 的下载保护
│  ├─ plugins.py         插件发现、校验、manifest 与 login.js 解析、热加载、JS 片段生成
│  ├─ portal.py          门户登录执行器：浏览器通道（Selenium，本机 Edge/Chrome）为主，requests 为可选兜底
│  ├─ scheduler.py       智能闹钟式规则（仅一次 / 每天 / 每周 / 每月）+ next_run 计算 + 补执行窗口
│  ├─ popup.py           tkinter 弹窗（允许 / 拒绝，拒绝则保持断开）
│  ├─ sysutil.py         进程与系统小工具（流量排行、管理员权限判断）
│  └─ service.py         后台主循环：调度 + 连通性巡检 + 下载保护
├─ plugins/
│  └─ JOU/               由旧程序匹配规则生成的示例插件（Dr.COM / eportal 门户）
│     ├─ manifest.json
│     └─ login.js
├─ tools/
│  ├─ make_plugin_from_legacy.py   旧程序内置匹配 → 插件的迁移工具
│  └─ smoke_gui.py                 离屏（offscreen）界面冒烟自测
├─ cli.py                命令行形态
├─ config.json           运行配置（不含任何硬编码网络参数）
├─ PLUGIN_SPEC.md        插件开发规范（目录结构、manifest 字段、login.js 契约、示例）
└─ requirements.txt      依赖
```

**运行时文件位置**

| 运行方式 | 配置与插件 | 用户数据（状态、日志、临时文件） |
|---|---|---|
| 源码运行（`python app.py`） | 项目目录 | `%LOCALAPPDATA%\CampusNet`（可用环境变量 `CAMPUSNET_HOME` 覆盖） |
| 打包运行（`CampusNet.exe`） | `CampusNet.exe` 所在目录（可写时），否则 `%LOCALAPPDATA%\CampusNet` | 同上 |

打包版是便携的：把 EXE 放到可写目录即可，`config.json`、`plugins/`、`state.json` 与 `logs/` 会在其同级目录生成。

### 四、环境要求与安装

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11（程序依赖 `netsh wlan`、`HKCU` Run 注册表项与 `schtasks`） |
| Python | Python 3（开发与自测环境为 Python 3.11 与 3.14，仓库未声明最低版本） |
| 浏览器 | 本机已安装 Edge 或 Chrome（Selenium 浏览器通道使用，浏览器是主要登录通道） |
| Node.js | **不需要**——插件是纯 `.js` 文件，由浏览器执行，不经 Node 运行 |

```powershell
pip install -r requirements.txt
```

| 依赖 | 用途 |
|---|---|
| `psutil>=5.9.0` | 网卡计数器读取、进程流量排行 |
| `requests>=2.28.0` | 网页登录的可选 HTTP 兜底通道 |
| `selenium>=4.15.0` | 浏览器通道（主通道）：注入插件 `login.js` |
| `PyQt5>=5.15.0` | 仅界面需要——核心层与 `cli.py` 不依赖 PyQt5 |

弹窗使用的 `tkinter` 属 Python 标准库，无需额外安装。

### 五、快速开始

```powershell
cd <项目目录>
pip install -r requirements.txt

# 图形界面（推荐：双击 CampusNet.vbs，完全无控制台窗口）
python  app.py                # 直接启动并显示主界面
pythonw app.py --minimized    # 无控制台窗口，直接最小化到托盘

# 命令行形态
python cli.py status          # 当前网络与配置概览
python cli.py profiles        # 列出本机已保存的无线配置文件（供界面选择）
python cli.py selftest        # 核心层全量自测
```

`app.py` 支持的参数：

| 参数 | 作用 |
|---|---|
| `--minimized` | 启动后直接进托盘 |
| `--no-service` | 只开界面，不启动后台服务线程 |
| `--dry-run` | 后台服务空跑，不做真实网络动作 |
| `--config <路径>` | 指定配置文件 |
| `--version` | 打印版本后退出 |
| `--selftest` | 无界面核心层自测，结果写入日志后退出 |

界面启动器：

| 启动器 | 效果 |
|---|---|
| `CampusNet.vbs`（双击） | 完全隐藏控制台窗口启动 |
| `wscript CampusNet.vbs --minimized` | 不弹主界面，直接进托盘 |
| `CampusNet.bat` | 批处理启动（可能有一瞬间的黑框） |
| `CampusNet_debug.bat` | 保留控制台，可查看异常与日志输出 |

托盘图标右键菜单可直接跳转任意分页；主界面点关闭按钮只收起到托盘，不退出程序。

命令行里出现中文乱码无需处理，`cli.py` 启动时会自动切换控制台编码。

### 六、配置说明

`config.json` 是唯一配置源，守护进程每轮循环重新读取，改完即生效。以下示例一律使用占位符，请勿提交真实凭据。

| 区块 | 作用 |
|---|---|
| `app` | 名称 / 版本、界面主题（`light` / `dark`）、启动最小化、关闭到托盘、托盘显示网络状态 |
| `app.startup` | 开机自启动开关、延迟秒数、计划任务开关、任务名前缀 |
| `wlan` | 网卡接口名（留空则自动探测）、连接超时、连接后校验 |
| `networks.<WiFi>` | 每个网络：`profile` / `label` / **`need_login`** / `plugin` / `login`（url、driver、credentials、options）/ `guard`（enabled、speed、sustained_seconds、volume、采样与进程排查） |
| `health` | 连通性检测开关与间隔、ping 目标、失败阈值 |
| `health.restart` | **独立的重启网卡开关**、冷却时间、是否优先禁用-启用、重启后是否重连 |
| `traffic` | 全局采样参数与 `traffic.defaults`（未单独配置的 WiFi 使用的默认阈值） |
| `schedules[]` | 智能闹钟式规则：`repeat.mode`（`once` / `daily` / `weekly` / `monthly`）、月份、星期、日期、时间、`window_minutes` 补执行窗口、目标网络、是否需要登录、重试策略 |
| `portal` | 浏览器驱动（`auto` / `edge` / `chrome`）、是否无头、超时、是否允许 `requests` 兜底、插件目录 |
| `popup` | 弹窗开关、标题、超时、拒绝后是否保持断开 |
| `logging` | 日志级别、轮转大小、备份数、内存保留条数 |

最小示例：

```jsonc
{
  "wlan": { "interface": "", "connect_timeout": 25, "verify_after_connect": true },
  "networks": {
    "CAMPUS_WIFI": {
      "profile": "CAMPUS_WIFI",
      "label": "校园网络",
      "need_login": true,
      "plugin": "CAMPUS_WIFI",
      "login": {
        "url": "http://portal.example.edu/",
        "driver": "",
        "credentials": { "account": "YOUR_STUDENT_ID", "password": "YOUR_PASSWORD" },
        "options": { "isp": "@unicom" }
      },
      "guard": { "enabled": false }
    },
    "BILLING_WIFI": {
      "profile": "BILLING_WIFI",
      "label": "计费网络",
      "need_login": false,
      "guard": {
        "enabled": true,
        "speed":  { "value": 2.0,  "unit": "MB/s" },
        "sustained_seconds": 10,
        "volume": { "value": 50.0, "unit": "MB" }
      }
    }
  }
}
```

阈值单位可自由换算，`{ "value": 2048, "unit": "KB/s" }`、`{ "value": 0.002, "unit": "GB/s" }` 与 `2.0 MB/s` 等价：

```jsonc
"guard": {
  "speed":  { "value": 2.0,   "unit": "MB/s" },   // 也可写 2048 KB/s、0.002 GB/s
  "sustained_seconds": 10,                        // 网速需要持续超过阈值多久
  "volume": { "value": 50.0,  "unit": "MB" }      // 也可写 51200 KB、0.05 GB
}
```

**两个条件同时满足**（持续超速 **且** 累计超量）即触发下载保护：断开连接并按 `popup` 配置弹窗询问是否保留；选择拒绝则保持断开。

调度模型：

* `repeat.mode`：`once`（配 `date`）、`daily`、`weekly`（配 `weekdays`）、`monthly`（配 `days`）。
* `time` 为本地时间；`window_minutes` 为补执行窗口——错过整点后在窗口内仍会补执行，超出窗口当次作废。
* 每条规则独立记录执行状态（`core/state.py`），当天已执行过不会重复触发；`python cli.py schedules` 可查看规则与下次执行时间。

### 七、插件开发指引

> 完整规范——目录结构、每个 `manifest.json` 字段（含真实示例）、完整 `login.js` 契约——见 **[PLUGIN_SPEC.md](PLUGIN_SPEC.md)**。下面是上手所需的最小速查。

目录结构（目录名必须等于 WiFi 名称）：

```
plugins/CAMPUS_WIFI/
├─ manifest.json     # 插件清单
└─ login.js          # 匹配与登录逻辑
```

`manifest.json` 关键字段：

```jsonc
{
  "spec_version": "1.0",
  "id": "campus-eportal-drcom",
  "name": "校园网（Dr.COM / eportal 门户）",
  "wifi": "CAMPUS_WIFI",                 // 必须与目录名一致
  "need_login": true,
  "login": {
    "url": "http://portal.example.edu/",
    "driver": "auto",
    "timeout_seconds": 10
  },
  "credentials": [
    { "key": "account", "label": "账号", "type": "text",
      "js_selector": "input[name='DDDDD']", "from_js": true },
    { "key": "password", "label": "密码", "type": "password",
      "js_selector": "input[name='upass']", "from_js": true }
  ],
  "options": [
    { "key": "isp", "label": "运营商", "type": "select",
      "choices": [ { "label": "联通", "value": "@unicom" },
                   { "label": "移动", "value": "@cmcc" },
                   { "label": "电信", "value": "@telecom" } ] }
  ]
}
```

`manifest.json` 声明表单字段后，界面会自动渲染（`text` / `password` 渲染输入框，`select` 渲染下拉框并填充 `choices`）；用户填写的值写入 `config.json → networks.<WiFi>.login.credentials` / `.options`。

`login.js` 必须定义全局对象 `CampusNetPlugin`，`core/plugins.py` 加载时会校验必备钩子：

| 钩子 | 必需 | 作用 |
|---|---|---|
| `match(ctx)` | 是 | 当前页面是否为本门户登录页 |
| `fill(ctx)` | 是 | 填写账号 / 密码 / 选项 |
| `submit(ctx)` | 是 | 点击提交按钮或调用页面提交函数 |
| `success(ctx)` | 是 | 判定是否登录成功 |
| `needsCaptcha(ctx)` | 否 | 返回 `true` 时中止自动流程并提示人工处理 |
| `credentials(ctx)` | 否 | 从页面回读凭据项（界面「同步」用） |
| `options(ctx)` | 否 | 从页面回读选项候选项（界面「同步」用） |
| `request(ctx)` | 否 | 构造 HTTP 通道请求（无浏览器时使用） |

`ctx` 由 `core/portal.py` 组装，携带 `network`、`url`、`account`、`password`、`credentials`、`options`、`ip`。**插件内不保存凭据**，一律从 `ctx` 取值。

新增一个 WiFi 的流程：

1. 界面「插件」页按 WiFi 名称新建插件（目录名必须完全一致）。
2. 填写登录页 URL 与是否需要登录，然后编辑 `login.js`，实现四个必需钩子。
3. 点「校验插件」确认通过（或执行 `python cli.py plugin-validate CAMPUS_WIFI`，应输出 `ok=true`、`errors=[]`）。
4. 在「WLAN」页连接该 WiFi，或在「计划」页加一条规则；需要登录时会自动调用该网络专属插件。

由旧程序内置匹配规则生成插件：

```powershell
python cli.py plugin-make CAMPUS_WIFI --force    # 生成 plugins/CAMPUS_WIFI/{manifest.json,login.js}
python cli.py plugin-validate CAMPUS_WIFI        # 校验生成的插件
```

迁移工具会读取旧 `config.json`、自动探测门户类型（当前支持 `Dr.COM` / `eportal`），并把账号、密码、运营商与登录页地址合并进 `config.json → networks.<WiFi>`。

### 八、打包为 EXE

打包产物为 PyInstaller 生成的单文件窗口化程序。安装依赖与 PyInstaller 后，在项目目录执行：

```powershell
pip install pyinstaller

pyinstaller --noconfirm --clean --onefile --windowed --name CampusNet `
  --collect-all selenium `
  --icon <你的图标>.ico `
  app.py
```

要点：

* `--windowed` 去掉控制台窗口，`--onefile` 产出单个 EXE。
* `--collect-all selenium` 打包 Selenium 及其驱动资源，缺失是打包后驱动报错的常见原因。
* `--icon` 可选；图标可用 Pillow 生成 `.ico`，或使用你自己的图片。
* 若运行时报缺少模块，追加 `--hidden-import <模块名>`。
* 打包版的数据是便携的：`config.json`、`plugins/`、`state.json` 与 `logs/` 位于 EXE 同级目录（该目录可写时），否则回退到 `%LOCALAPPDATA%\CampusNet`。

无需打开界面即可校验打包结果：

```powershell
.\dist\CampusNet.exe --version
.\dist\CampusNet.exe --selftest    # 写入 logs\selftest-result.json 后退出
```

### 九、常见问题

**配置、日志与状态文件在哪里？**
源码运行时 `config.json` 与 `plugins/` 在项目目录，用户数据在 `%LOCALAPPDATA%\CampusNet`（可用 `CAMPUSNET_HOME` 覆盖）；打包运行时若 EXE 所在目录可写则全部在其同级目录，否则回退到 `%LOCALAPPDATA%\CampusNet`。日志文件为 `logs\campusnet.log`。

**命令行中文乱码。**
无需处理，`cli.py` 启动时会切换控制台编码。若仍有乱码，请在 Windows Terminal 或 PowerShell 中执行，而不是旧式控制台宿主。

**「流量」页的实时速率与本会话累计一直为 0。**
先看 `logs\campusnet.log` 是否出现 `[<WiFi名>] 流量统计会话开始` 并持续有采样记录；若会话未开始，请确认「流量」页为当前连接的 WiFi 建了下载保护条目（更换 WiFi 后需为新 WiFi 新建条目）。条目按 WiFi 配置，且全局 `traffic.enabled` 开关需为开。

**托盘图标一直是灰色。**
灰色表示连通性检测已关闭，此时颜色固定不变属预期行为。请在「网络检测」页开启连通性检测（间隔、目标地址、超时、失败阈值）；该开关与「重启网卡」开关互相独立。

**创建 Windows 计划任务失败。**
`schtasks /SC ONLOGON` 可由普通用户以当前用户身份创建；若要求最高权限（`/RL HIGHEST`）则必须以管理员身份运行 CampusNet。程序会先尝试最高权限，失败自动降级为普通权限。设置页会显示完整 `schtasks` 命令供手动创建，「开机自启动」开关也是多数场景下的替代方案。

**门户登录失败。**
检查登录页地址与 `login.js` 中的选择器（`python cli.py login --probe-options` 会在登录前按规则回读页面自定义选项），确认填写的账号 / 密码 / 运营商取值正确，并确认浏览器通道可用（`portal.driver` 取 `auto` / `browser` 或 `requests`）。若门户出现验证码，自动流程会按设计中止并提示人工完成。

**需要安装 Node.js 吗？**
不需要。插件是纯 JavaScript 文件，由浏览器经 Selenium 执行。

**账号密码会被上传吗？**
不会。凭据只保存在本地 `config.json`，插件不保存凭据，程序不上传任何数据。填入真实凭据后请将该文件排除在版本控制之外——仓库内提供的是占位符。

**可以管理多个校园网吗？**
可以。在 `networks` 下为每个 WiFi 建一个条目；只有 `need_login=true` 的网络需要配套插件。

### 十、免责声明

* 本项目供个人学习与研究使用，请仅在你有权访问的网络环境中使用。
* 自动登录校园门户可能与所在院校的网络管理规定冲突，**请先了解你所在学校的规定**，使用本程序产生的后果由使用者自行承担。
* 软件按「现状」提供，不附带任何形式的担保；因使用本程序造成的账号处罚、网络费用、数据丢失或其他损失，作者不承担任何责任。

### 十一、开源许可

本项目基于 [MIT License](LICENSE) 发布。Copyright (c) 2026 CampusNet contributors。

### 十二、致谢

* [PyQt5](https://pypi.org/project/PyQt5/) —— 托盘界面、主题与分页框架。
* [Selenium](https://www.selenium.dev/) —— 注入插件登录脚本的浏览器通道。
* [psutil](https://pypi.org/project/psutil/) —— 网卡计数器与进程流量排行。
* [requests](https://requests.readthedocs.io/) —— 可选的 HTTP 登录通道。
* [PyInstaller](https://pyinstaller.org/) —— 单文件窗口化打包。
* Dr.COM / eportal 门户页面，其表单结构记录在随仓库提供的 `plugins/JOU` 示例插件中。
*（内容由AI生成，仅供参考）*
