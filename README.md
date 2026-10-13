# CampusNet 校园网 WLAN 自动管理程序（PyQt5 桌面版 + 通用化核心层 + 插件体系）

本程序把原先写死在单文件脚本里的 SSID、账号、密码、运营商、流量阈值、时间规则全部抽到 `config.json` 与插件中，形成「通用化核心引擎 + 每 WiFi 一个插件」的结构，并在其上提供**全功能 PyQt5 桌面 GUI**（系统托盘常驻、明/暗双主题、左侧导航分页、各模块独立开关）。

* GUI 入口：`app.py`（`pythonw` 启动即无控制台窗口；`CampusNet.vbs` / `CampusNet.bat` 双击启动）
* 命令行入口：`cli.py`（守护/连接/巡检/流量/登录/状态/迁移/插件/自测）
* GUI 与 CLI 共用同一套 `core/` 与同一份 `config.json`，两边配置互通。

---

## 一、快速开始

```powershell
cd <本目录>
pip install -r requirements.txt

# 图形界面（推荐：双击 CampusNet.vbs，完全无控制台窗口）
python  app.py                # 直接启动并显示主界面
pythonw app.py --minimized    # 无控制台窗口、直接最小化到任务栏托盘

# 命令行形态
python cli.py status          # 当前网络/配置概览
python cli.py profiles        # 列出本机已保存的无线配置文件（供界面选择）
python cli.py selftest        # 核心层全量自测
```

`app.py` 支持参数：`--minimized`（启动即进托盘）、`--no-service`（只开界面不跑后台服务）、
`--dry-run`（后台服务空跑，不做真实网络动作）、`--config <路径>`（指定配置文件）、`--version`。

命令行里出现中文乱码时无需处理，`cli.py` 启动时会自动切换控制台编码。

---

## 二、目录结构

```
CampusNet/
├─ app.py                GUI 入口（PyQt5，支持 pythonw 隐藏控制台启动）
├─ CampusNet.vbs         双击启动 GUI（完全隐藏控制台窗口，可传 --minimized）
├─ CampusNet.bat         批处理启动 GUI（不保留控制台窗口）
├─ CampusNet_debug.bat   调试启动（保留控制台，便于看异常与日志）
├─ gui/
│  ├─ context.py         AppContext：配置/核心层/后台服务/主题/异步任务的统一入口
│  ├─ main_window.py     主窗口：左侧导航 + 右侧分页 + 状态栏 + 托盘联动
│  ├─ tray.py            QSystemTrayIcon：左键双击开主界面，右键菜单开各分页/退出
│  ├─ theme.py           明/暗两套 QSS 主题 + 托盘配色规则（通绿/不通红/灰中性）
│  ├─ icons.py           托盘与状态图标绘制（绿/红/灰三态）
│  ├─ widgets.py         卡片、表单、开关行、单位输入框等通用控件
│  ├─ startup.py         开机自启动（HKCU Run）与 Windows 计划任务（schtasks）注册/注销
│  ├─ config_ops.py      配置与插件的读写/校验/新建（GUI 侧封装）
│  └─ pages/             概览 / WLAN / 计划 / 插件 / 网络检测 / 流量 / 设置 七个分页
├─ core/
│  ├─ paths.py           程序目录 / 配置与状态文件 / 日志目录 / 临时目录定位
│  ├─ logging_setup.py   滚动文件日志 + 内存环形缓冲（供 GUI 日志查看）
│  ├─ config.py          配置模型：默认值 / 读写 / 校验 / normalize / 旧 config.json 迁移
│  ├─ state.py           运行状态持久化 + 动作互斥锁（防止计划任务与守护进程并发改网络）
│  ├─ wlan.py            基于 netsh 的无线控制：列已存配置 / 连接 / 断开 / 状态 / 重启网卡 / 接口名自动探测
│  ├─ health.py          连通性检测（开关）与重启网卡（开关），两个功能可分别独立启用
│  ├─ traffic.py         单次连接上下行流量统计 + 按 WiFi 的下载保护（网速阈值/持续时长/累计流量）
│  ├─ plugins.py         插件发现 / 校验 / manifest+login.js 解析 / 热加载 + JS 注入与调用片段生成
│  ├─ portal.py          网页登录执行器：浏览器（Selenium，本机 Edge/Chrome）为主通道，requests 为可选通道
│  ├─ scheduler.py       智能闹钟式计划规则（仅一次/每天/每周/每月）+ next_run 计算 + 补执行窗口
│  ├─ popup.py           tkinter 弹窗（逻辑与旧版一致：允许/拒绝，拒绝则保持断开）
│  ├─ sysutil.py         进程/系统小工具（流量排行、管理员权限判断等）
│  └─ service.py         后台主循环（调度 + 连通性巡检 + 下载保护），状态回调与“需要弹窗”回调
├─ plugins/
│  └─ JOU/               由旧程序匹配自动同步生成的插件（目录名 = WiFi 名称）
│     ├─ manifest.json
│     └─ login.js
├─ tools/
│  ├─ make_plugin_from_legacy.py   旧程序内置匹配 → 插件 的迁移工具
│  └─ smoke_gui.py                 离屏（offscreen）GUI 冒烟自测
├─ cli.py                命令行形态（守护/连接/巡检/流量/登录/状态/迁移/插件/自测）
├─ config.json           运行配置（不再含任何硬编码网络参数）
├─ PLUGIN_SPEC.md        插件开发规范（目录结构、manifest 字段、login.js 契约、示例）
└─ requirements.txt      依赖
```

---

## 三、通用化约定

* **核心层不含任何具体网络参数**：SSID、账号、密码、运营商、登录页 URL、流量阈值、时间规则一律来自 `config.json` 与插件；代码中不存在 `HUAWEI122` / `JOU` / 账号密码等字面量。
* **每个 WiFi 一个条目**：`config.json → networks.<WiFi名称>`，包含是否登录、登录页、所属插件、下载保护阈值。
* **每个 WiFi 一个插件**：`plugins/<WiFi名称>/`，目录名即 WiFi 名称；`need_login=false` 的 WiFi 只需配置条目、无需插件。
* **单位可换**：网速支持 `KB/s / MB/s / GB/s`，流量支持 `KB / MB / GB`，由 `traffic.py` 统一换算为字节后比较。

---

## 四、配置结构（config.json）

| 区块 | 作用 |
|---|---|
| `app` | 名称/版本、界面主题（`light` / `dark`）、启动最小化、关闭到托盘、托盘显示网络状态 |
| `app.startup` | 开机自启动开关、延迟秒数、计划任务开关、任务名前缀 |
| `wlan` | 网卡接口名（空则自动探测）、连接超时、连接后校验 |
| `networks.<WiFi>` | 该 WiFi 的 `profile` / `label` / **`need_login`** / `plugin` / `login`（url、driver、credentials、options）/ `guard`（enabled、speed、sustained_seconds、volume、采样与进程排查） |
| `health` | 连通性检测开关与间隔、ping 目标、失败阈值；`health.restart` 为**重启网卡独立开关**、冷却时间、是否优先禁用-启用、重启后是否重连 |
| `traffic` | 全局采样参数与 `traffic.defaults`（未单独配置的 WiFi 使用的默认阈值） |
| `schedules[]` | 智能闹钟式规则：`repeat.mode`（once/daily/weekly/monthly）、月份、星期、日期、时间、`window_minutes` 补执行窗口、目标网络、是否需要登录、重试策略 |
| `portal` | 浏览器驱动（auto/edge/chrome）、是否无头、超时、是否允许 requests 兜底、插件目录 |
| `popup` | 弹窗开关、标题、超时、拒绝后是否保持断开（**行为与原程序一致**） |
| `logging` | 日志级别、轮转大小、备份数、内存保留条数 |

### 阈值单位换算示例

```jsonc
"guard": {
  "speed":  { "value": 2.0,   "unit": "MB/s" },   // 网速阈值，可写 2048 KB/s、0.002 GB/s
  "sustained_seconds": 10,                         // 持续多久才判定
  "volume": { "value": 50.0,  "unit": "MB" }       // 累计流量阈值，可写 51200 KB、0.05 GB
}
```

三条同时满足（持续超速 + 累计超量）即触发下载保护：断开连接并按 `popup` 配置弹窗询问是否保留；与原程序逻辑一致。

---

## 五、调度模型（智能闹钟式）

* `repeat.mode`：`once`（仅一次，配 `date`）、`daily`、`weekly`（配 `weekdays`）、`monthly`（配 `days`）。
* `time` 为本地时间；`window_minutes` 为**补执行窗口**：错过整点后在窗口内仍会补执行，超出窗口当次作废。
* 每条规则独立记录执行状态（`state.py`），当天已执行过不会重复触发；`cli.py schedules` 可查看规则与下次执行时间。
* `scheduler.next_run()` 计算下一次触发时刻，`selftest` 已覆盖跨星期/跨月/窗口边界等场景。

---

## 六、插件体系

* 规范见 **[PLUGIN_SPEC.md](PLUGIN_SPEC.md)**：目录结构、`manifest.json` 字段、`login.js` 契约（`fill(ctx)` / `submit(ctx)` / `success(ctx)`，或 HTTP 通道 `request(ctx)`）、`options` 与 GUI 表单渲染的对应关系、可直接照抄的示例。
* `ctx` 携带 `network / url / account / password / credentials / options / ip`，由 `portal.py` 组装后注入。
* `core/plugins.py` 负责发现、校验（manifest 必填字段、WiFi 名与目录名一致、`need_login` 与 JS 契约匹配）与热加载；`cli.py plugin-validate` 可单独校验。

### 由旧程序同步生成插件

```powershell
python cli.py plugin-make JOU --force     # 生成 plugins/JOU/{manifest.json,login.js}
python cli.py plugin-validate JOU         # 校验
```

`tools/make_plugin_from_legacy.py` 读取旧 `config.json`，自动探测门户类型（当前支持 `Dr.COM/eportal`，Key 值与《登录窗口元素代码》完全一致：`form[name='f1']`、账号 `input[name='DDDDD']`、密码 `input[name='upass']`、运营商 `select[name='ISP_select']`（`@cmcc/@unicom/@telecom/""`）、提交 `input[name='0MKKey']` / 页面函数 `ee(1)`），生成插件并把账号/密码/运营商/登录页合并进 `config.json → networks.JOU`。

---

## 七、命令行一览

| 子命令 | 作用 |
|---|---|
| `status` | 配置、当前连接、健康与流量保护开关概览 |
| `daemon` | 后台主循环（GUI 未启动时由计划任务/开机自启拉起） |
| `connect <WiFi>` / `connect-billing` / `connect-campus` | 连接无线，可选随后登录 |
| `disconnect` | 断开当前无线 |
| `login [WiFi] [--force] [--probe-options]` | 按插件完成网页登录；通道由 `portal.driver`（auto/browser/requests）决定，`--probe-options` 登录前按 login.js 规则回读自定义选项 |
| `health-check [--restart]` | 连通性检测，必要时重启网卡（受两个独立开关控制） |
| `traffic [--duration N] [--interval N] [--network 名称]` | 单次连接上下行流量统计与阈值判定 |
| `profiles` | 列出本机已保存的无线配置文件 |
| `networks` / `schedules` | 列出网络条目 / 计划规则与下次执行时间 |
| `plugins` / `plugin-validate [WiFi]` | 列出插件 / 校验插件 |
| `plugin-make [WiFi]` | 由旧程序匹配生成插件 |
| `migrate` | 旧 `config.json` → 通用配置的一次性迁移 |
| `selftest` | import、单位换算、调度 next_run、插件校验自测 |

多数子命令支持 `--json` 输出，便于 GUI 或脚本消费。

---

## 八、GUI 使用说明

### 8.1 启动方式

| 方式 | 命令 | 说明 |
|---|---|---|
| 双击启动（推荐） | 双击 `CampusNet.vbs` | 完全隐藏控制台窗口，桌面无黑框 |
| 双击启动（最小化） | `wscript CampusNet.vbs --minimized` | 不弹主界面，直接进任务栏托盘 |
| 批处理 | 双击 `CampusNet.bat` | 不保留控制台窗口（仍有一瞬间的黑框） |
| 调试 | 双击 `CampusNet_debug.bat` | 保留控制台，能看到异常与日志输出 |
| 直接运行 | `python app.py` / `pythonw app.py --minimized` | 开发调试用 |

### 8.2 托盘（任务栏图标）

* **左键双击** 打开/还原主界面；主界面点关闭按钮只收起到托盘，不退出程序。
* **右键菜单** 可直接跳转到任意分页（概览 / WLAN / 计划 / 插件 / 网络检测 / 流量 / 设置）或**退出**。
* **图标颜色表示网络状态**：连通 = **绿**；不通 = **红**；连通性检测功能关闭时 = **中性灰**（此时颜色不再变化，界面「网络检测」页有说明）。
* 需要弹窗的时机（下载保护触发）沿用核心层弹窗逻辑，行为与旧版完全一致。

### 8.3 各分页能做什么

| 分页 | 功能 |
|---|---|
| **概览** | 当前 WiFi、无线网卡、连通状态、托盘配色、下次计划执行时间、实时速率与会话累计流量 |
| **WLAN** | 读取本机已保存的无线配置列表供选择；设主/备网络；连接 / 断开 / 重启网卡；每个网络一个「是否需要登录」开关（与插件联动） |
| **计划** | 智能闹钟式规则列表 + 编辑对话框：频率（仅一次 / 每天 / 每周 / 每月）、月份、星期、时间、目标网络、是否需要登录、补执行窗口、启用开关；实时显示下次执行时间 |
| **插件** | 按 WiFi 名称列出插件；可视化编辑登录页 URL、是否需要登录等字段；按插件 `options` 自动渲染表单（密码掩码）；打开/编辑 `login.js`；校验插件；一键新建插件 |
| **网络检测** | 连通性检测开关（间隔 / 目标地址 / 超时 / 失败阈值）与重启网卡开关（触发冷却 / 回收等待 / 重启后重连）**互相独立**；含托盘配色含义说明与「立即检测」 |
| **流量** | 按每个 WiFi 分别配置下载保护：启用开关、网速阈值 + 单位、持续秒数、累计流量阈值 + 单位（KB / MB / GB）；显示实时速率与本会话累计 |
| **设置** | 明/暗主题切换（持久化）、开机自启动开关、Windows 计划任务开关（两个开关各自独立注册/注销，含权限说明与降级方案）、日志查看、关于 |

### 8.4 界面主题与配置持久化

主题（`light` / `dark`）、各页开关与阈值全部写入 `config.json`，重启后保持；GUI 与 `cli.py` 读取同一份配置，界面改完命令行立即生效。

### 8.5 开机自启动 / 计划任务的权限说明

* **开机自启动**：写当前用户的注册表 `HKCU\...\Run`，普通用户即可，无需管理员。
* **Windows 计划任务**：`schtasks /Create /SC ONLOGON`，普通用户可创建「以当前用户身份运行」的任务；若需最高权限（`/RL HIGHEST`）则必须以管理员身份运行本程序，程序会自动先试最高权限、失败后降级为普通权限。
* **降级方案**：计划任务不可用时改用「开机自启动」开关，或按界面显示的命令行手动在「任务计划程序」中创建，或以管理员身份重启本程序。设置页会把完整 `schtasks` 命令显示出来。

---

## 九、插件开发速查

> 完整规范见 **[PLUGIN_SPEC.md](PLUGIN_SPEC.md)**，下面是最小可用速查。

```
plugins/<WiFi名称>/
├─ manifest.json     # 目录名必须等于 WiFi 名称（SSID）
└─ login.js          # 匹配与登录逻辑
```

**manifest.json 关键字段**

```jsonc
{
  "wifi": "JOU",                    // 必填，等于目录名
  "name": "JOU 校园网",              // 展示名
  "need_login": true,               // 该 WiFi 是否需要网页登录
  "url": "http://210.28.39.250/",   // 登录页地址（可自定义）
  "driver": "auto",                 // auto | edge | chrome | requests
  "credentials": {                  // 按 login.js 规则生成的账号/密码
    "account": "YOUR_STUDENT_ID",
    "password": "******"
  },
  "options": [                      // 自定义选项 → GUI 自动渲染成表单
    { "key": "isp", "label": "运营商", "type": "select",
      "choices": [ {"label": "联通", "value": "@unicom"},
                   {"label": "移动", "value": "@cmcc"},
                   {"label": "电信", "value": "@telecom"} ] }
  ]
}
```

**login.js 契约**（浏览器通道：注入执行；HTTP 通道：`request`）

| 函数 | 作用 |
|---|---|
| `fill(ctx)` | 向登录表单填值，`ctx` 含 `network / url / account / password / credentials / options / ip` |
| `submit(ctx)` | 提交表单（或返回请求描述） |
| `success(ctx)` | 判定是否登录成功 |
| `request(ctx)` | 可选，纯 HTTP 通道的请求构造（不装浏览器时兜底） |

**新增一个 WiFi 的完整流程**

1. 界面「插件」页 → 一键新建（以 WiFi 名称命名）→ 填登录页 URL 与是否需要登录 → 保存；
2. 编辑 `login.js`（可用「插件」页内置编辑器），按上表实现 4 个钩子；
3. 点「校验插件」确认通过；
4. 「WLAN」页连接该 WiFi（或「计划」页加一条规则），需要登录时会自动调用该 WiFi 专属插件。

> 每个 WiFi 独享一个插件目录，互不影响；旧程序里写死的匹配规则已由 `cli.py plugin-make` 自动同步生成为插件（当前 `plugins/JOU`）。

---

## 十、自测与验证结论

| 自测项 | 命令 | 结果 |
|---|---|---|
| 核心层自测 | `python cli.py selftest` | **43/43 通过，0 失败**（import、KB/MB/GB 换算、调度 next_run、插件校验、配置迁移、动作互斥锁） |
| GUI 离屏冒烟 | `set QT_QPA_PLATFORM=offscreen && python tools\smoke_gui.py` | **13/13 通过**（主窗口、7 个分页切换、托盘三态与右键菜单、明暗主题切换、连通性三态驱动、计划编辑对话框 4 种频率、插件表单与新建/编辑对话框、设置页开关默认态、核心层只读能力） |
| 网速 / 流量 / 连通性回归 | `python tools\verify_campusnet.py` | **26/26 通过**：流量采样速率与累计非零、下载保护阈值贯通界面、下载进程启发式可用、连通性检测与托盘配色、插件空闲不重复重载、GUI「流量」「网络检测」两页真实渲染（只读验证：`dry_run`，不切网、不重启网卡、不改配置） |
| 打包后程序自测 | `CampusNet.exe --selftest` | **43/43 通过，退出码 0**（`frozen=true`，app_root=`G:\CampusNet`，config / plugins / logs 全部落在 exe 同级目录） |
| 打包后实机采样 | 运行 `CampusNet.exe --minimized` 并制造下载流量 | **采样有效**：`state.json → guard.JOU.down_bps ≈ 622 KB/s`、`total_recv ≈ 19.5 MB`、`traffic_live.sampling = true` |

冒烟测试在无桌面环境下运行（`QT_QPA_PLATFORM=offscreen`），不产生真实网络动作、不落盘修改配置。

### 10.1 网速 / 流量检测不可用的修复（2026-10-13）

旧打包版存在「网速检测、网络流量检测完全不可用」的问题，定位到两处缺陷并已修复：

| 问题 | 现象 | 修复 |
|---|---|---|
| 插件热加载比较逻辑有误 | `core/plugins.py` 仅比较 `manifest.json` 的 mtime，`login.js` 更新后 mtime 永远「更新」→ 后台每轮巡检都重新加载插件，日志刷屏、采样线程构造被反复打断 | 改为比较 `max(manifest_mtime, js_mtime)` 与已记录值，插件空闲时不再重复重载 |
| 窗口态日志重复写 | 冻结运行时 `stdout` 已被重定向到日志文件，日志系统又挂了一个 `StreamHandler`，同一行写两遍；海量刷屏挤占采样线程时间片，界面速率长期为 0 | `core/logging_setup.py` 检测到 `stdout` 带重定向标记（由 `core/sysutil.py` 打标）时不再重复挂控制台 handler |

修复后重新打包（`PyInstaller --onefile --windowed`），实测结论：

* 「流量」页的实时下载速率、本会话累计接收、峰值速率、触发次数均正常刷新；
* 「网络检测」页的连通判定（连通/绿）、在线状态、延迟、连续失败次数正常刷新；
* 后台日志每行只出现一次、插件只加载一次，不再刷屏；
* 数据仍在便携目录：`G:\CampusNet\state.json`（运行状态）、`G:\CampusNet\logs\campusnet.log`（日志）、`G:\CampusNet\logs\selftest-result.json`（自检结果）。

排查建议：若界面速率仍为 0，先看 `logs\campusnet.log` 是否出现 `[<WiFi名>] 流量统计会话开始` 并持续有采样记录，再确认「流量」页该 WiFi 的下载保护条目与阈值；更换 WiFi 后需在「流量」页为新 WiFi 建条目。
