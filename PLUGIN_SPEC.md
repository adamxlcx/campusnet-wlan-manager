# 插件开发规范（PLUGIN_SPEC.md）

版本：`1.0`　适用程序：CampusNet 核心层（`core/plugins.py`）

本规范描述"一个 WiFi 一个登录插件"的目录结构、`manifest.json` 字段与 `login.js` 契约。
**下文所有字段取值均来自前置阶段实际生成的 `plugins/JOU/` 插件（JOU 校园网 / Dr.COM eportal），可直接照抄改造成新插件。**

---

## 1. 设计原则

1. **一个 WiFi 一个插件**：插件目录名 = WiFi 名称（如 `JOU`、`HUAWEI122`），互不干扰，避免不同 WiFi 的登录规则互相污染。
2. **程序零硬编码**：核心引擎不写死 SSID / 账号 / 密码 / 运营商 / 阈值 / 时间。WiFi 名单来自 `core/wlan.py` 读取的本机无线配置文件，账号密码运营商来自 `config.json` 的 `networks[]`，登录页匹配规则来自插件。
3. **插件只描述"怎么登录"，不保存凭据**：`login.js` 通过注入的 `ctx` 取值，不在插件文件里写账号密码。
4. **GUI 表单由插件声明驱动**：`manifest.credentials[]` 与 `manifest.options[]` 决定网络配置页渲染哪些输入项（文本框 / 密码框 / 下拉选择）及其候选项。
5. **两条通道，插件自描述**：浏览器通道（Selenium 注入 `login.js`，主通道）+ HTTP 通道（`manifest.http.attempts`，可选通道）。

---

## 2. 目录结构

```
CampusNet/
├─ core/                       核心引擎（不含 GUI）
├─ cli.py                      命令行形态
├─ tools/
│  └─ make_plugin_from_legacy.py   把旧程序内置匹配规则同步生成为插件
├─ PLUGIN_SPEC.md              本文件
└─ plugins/
   └─ JOU/                     ← 目录名 = WiFi 名称（必须一致）
      ├─ manifest.json         插件清单（必需）
      └─ login.js              登录脚本（必需）
```

新增一个 WiFi 的插件：复制 `plugins/JOU/` 为 `plugins/<新WiFi名称>/`，改 `manifest.json` 的 `wifi`/`id`/`name`/`login.url` 与选择器，改 `login.js` 顶部常量即可。
由旧配置批量生成：`python tools/make_plugin_from_legacy.py --wifi "<新WiFi名称>" --url "<登录页>" --legacy <旧config.json>`。

---

## 3. manifest.json 字段规范

### 3.1 顶层字段

| 字段 | 类型 | 必需 | 说明 | JOU 实际取值 |
|---|---|---|---|---|
| `spec_version` | string | 是 | 规范版本，当前 `"1.0"` | `"1.0"` |
| `id` | string | 是 | 插件唯一标识，建议 `<wifi小写>-<门户类型>` | `"jou-eportal-drcom"` |
| `name` | string | 是 | 展示名 | `"JOU 校园网（Dr.COM / eportal 门户）"` |
| `description` | string | 否 | 描述 | 由迁移工具生成 |
| `wifi` | string | 是 | 该插件服务的 WiFi 名称，**必须与目录名一致** | `"JOU"` |
| `need_login` | bool | 是 | 该 WiFi 是否需要登录（与 `config.json` 同名开关联动） | `true` |
| `generated` | object | 否 | 生成来源信息（迁移工具写入） | `{by, at, legacy_config, portal_type}` |
| `login` | object | 是 | 登录页与提交/判定规则，见 3.2 | — |
| `credentials` | array | 是 | 凭据项声明，见 3.3 | account / password |
| `options` | array | 否 | 自定义选项声明，见 3.4 | isp（运营商） |
| `http` | object | 否 | HTTP 通道声明，见 3.5 | 2 个 eportal 接口 |

### 3.2 `login` 对象

| 字段 | 类型 | 说明 | JOU 实际取值 |
|---|---|---|---|
| `url` | string | 登录页地址（GUI 可改，运行时以 `config.json` 为准） | `"http://210.28.39.250/"` |
| `url_patterns` | string[] | 判定"当前是否在该门户"的通配模式 | `["*eportal*","*drcom*","*dr1003*"]` |
| `driver` | string | `auto` / `browser` / `requests` | `"auto"` |
| `timeout_seconds` | int | 登录超时 | `10` |
| `js_wait_seconds` | int | 注入 JS 前的页面等待 | `2` |
| `form` | object | `{name, selector}` 登录表单 | `{"name":"f1","selector":"form[name='f1']"}` |
| `submit` | object | `{selector, value, page_function, fallback}` | `{"selector":"input[name='0MKKey']","value":"登录","page_function":"ee(1)","fallback":"form.submit()"}` |
| `success` | object | `{url_patterns[], keywords[], failure_keywords[]}` 成功/失败判定 | 见实际文件 |
| `captcha` | object | `{enabled, input_selector, image_selector}`，`enabled=true` 时要求人工处理 | `{"enabled":false,"input_selector":"input[name='captcha']","image_selector":"#captcha_img"}` |

### 3.3 `credentials[]`（凭据项：账号、密码）

| 字段 | 类型 | 说明 | JOU 示例 |
|---|---|---|---|
| `key` | string | 键名，对应 `config.json` 的 `networks[i].login.credentials[key]` | `"account"` / `"password"` |
| `label` | string | GUI 表单标签 | `"账号"` / `"密码"` |
| `type` | string | `text` / `password` | `"text"` / `"password"` |
| `required` | bool | 是否必填 | `true` |
| `placeholder` | string | 输入提示 | `"上网账号"` / `"上网密码"` |
| `js_selector` | string | 页面上的 DOM 选择器（供 `fill()` 写入） | `"input[name='DDDDD']"` / `"input[name='upass']"` |
| `from_js` | bool | 是否由 `login.js` 负责写入 | `true` |
| `help` | string | 说明 | 指向 config.json 的取值位置 |

### 3.4 `options[]`（自定义选项：由 JS 匹配规则推导）

`options[]` 是"**按 JavaScript 匹配规则生成的自定义选项**"：值来自登录页的真实控件（此处为运营商下拉框 `select[name='ISP_select']`）。

| 字段 | 类型 | 说明 | JOU 示例 |
|---|---|---|---|
| `key` | string | 键名，对应 `networks[i].login.options[key]`，同时是 `login.js` 中 `ctx.options[key]` 的键 | `"isp"` |
| `label` | string | GUI 标签 | `"运营商"` |
| `type` | string | `select` / `text` / `checkbox` | `"select"` |
| `required` | bool | 是否必填 | `false` |
| `js_selector` | string | DOM 选择器 | `"select[name='ISP_select']"` |
| `from_js` | bool | 候选项由 `login.js` 的 `options()` 从页面回读 | `true` |
| `choices` | array | `[{value,label}]` 候选项（页面实测值） | `-1 请选择运营商 / @cmcc 中国移动 / @unicom 中国联通 / @telecom 中国电信 / "" 校园网` |
| `default` | string | 默认值（留空表示由用户配置决定，避免硬编码运营商） | `""` |
| `help` | string | 说明 | `"“校园网”选项仅限访问校内数字资源和学术期刊资源。"` |

> **选项与 GUI 的关系**：网络配置页遍历 `credentials[]` + `options[]` 渲染表单——`type=text/password` 渲染输入框，`type=select` 渲染下拉框且填充其 `choices`；用户填写的值写入 `config.json` 的 `networks[i].login.credentials` / `.options`，登录时再由 `core/portal.py` 组装成 `ctx` 注入 `login.js`。点击「从登录页同步选项」时调用 `login.js` 的 `credentials()` / `options()` 实时回读页面候选项。

### 3.5 `http` 对象（可选通道）

```json
"http": {
  "attempts": [
    {
      "name": "eportal-801-login",
      "method": "GET",
      "url": "http://210.28.39.250:801/eportal/?c=Portal&a=login&callback=dr1003&login_method=1&user_account=,0,{account}&user_password={password}&wlan_user_ip={ip}&...&v={ts}",
      "success": {"contains": ["\"result\":1"], "not_contains": ["\"result\":0"]}
    },
    { "name": "eportal-80-login", "method": "GET", "url": "http://210.28.39.250/eportal/?...", "success": {"contains": ["\"result\":1"], "not_contains": ["\"result\":0"]} }
  ]
}
```

- **占位符**（由 `core/portal.py._render` 渲染）：`{account}` `{password}` `{ip}` `{ts}` `{service}`，并可写 `{options.isp}` / `{credentials.account}`；加后缀 `_q` 做 URL 编码（如 `{password_q}`）、`_j` 做 JSON 转义。
- **`success` 判定规则**：`status`（期望状态码）、`contains`（响应须含关键字）、`not_contains`（不得含关键字）、`regex`（正则）、`json`（JSON 字段等值）。全部为空时该次尝试判为"不可判定"。

---

## 4. login.js 契约

`login.js` 必须定义一个全局对象 **`CampusNetPlugin`**（核心层通过 `driver.execute_script` 注入并按名调用）。`core/plugins.py` 会在加载时校验这些函数是否齐全。

| 函数 | 必需 | 入参 | 返回 | 说明 |
|---|---|---|---|---|
| `match(ctx)` | 是 | ctx | `boolean` | 当前页面是否为本门户登录页 |
| `fill(ctx)` | 是 | ctx | `{ok:boolean, filled:string[], error:string}` | 按 `ctx` 填写账号/密码/选项 |
| `submit(ctx)` | 是 | ctx | `{ok:boolean, error:string}` | 点击提交按钮或调用页面提交函数 |
| `success(ctx)` | 是 | ctx | `boolean` | 是否登录成功 |
| `needsCaptcha(ctx)` | 否 | ctx | `boolean` | 是否需人工完成验证码（返回 `true` 时核心层终止自动流程并提示用户） |
| `credentials(ctx)` | 否 | ctx | `[{key,label,type,value,placeholder}]` | 从页面回读凭据项（GUI「同步」用） |
| `options(ctx)` | 否 | ctx | `[{key,label,type,value,choices[]}]` | 从页面回读选项候选项（GUI「同步」用） |
| `request(ctx)` | 否 | ctx | `{url,method,data}` | HTTP 通道参考请求（供 GUI 展示） |

### 4.1 `ctx` 结构（由 `core/portal.py.build_ctx` 注入）

```js
{
  network: "JOU",                 // WiFi 名称
  url: "http://210.28.39.250/",   // 登录页 URL
  account: "YOUR_STUDENT_ID",          // = credentials.account
  password: "******",             // = credentials.password
  credentials: {account: "...", password: "..."},   // 来自 config.json
  options: {isp: "@unicom"},      // 自定义选项，键名与 manifest.options[].key 一致
  ip: "10.x.x.x"                  // 本机局域网 IP（HTTP 通道常用）
}
```

### 4.2 编写要求

- **不在插件内保存凭据**：一律从 `ctx.credentials` / `ctx.options` 取值。
- **选择器集中在 `selectors` 对象**，便于新门户只改一处。
- 写值后应派发 `input` / `change` 事件（JOU 插件已用 `_setValue()` 统一处理），兼容由前端框架监听的页面。
- 下拉框优先按 `value` 匹配，失败再按显示文本匹配（JOU 插件 `_setSelect()`）。
- 全文件使用 ES5 语法（`var` + `function`），避免 `execute_script` 在老内核上报错。

---

## 5. 开发新插件步骤

1. **拿到登录页**：打开该 WiFi 的认证页，用浏览器开发者工具查看表单结构（`form` 名、账号/密码输入框 `name`、提交按钮、运营商下拉、验证码）。
2. **建目录**：`mkdir plugins/<WiFi名称>`（目录名必须等于 WiFi 名称）。
3. **写 `manifest.json`**：照抄 `plugins/JOU/manifest.json`，逐项修改 `id` / `name` / `wifi` / `login.*` / `credentials[].js_selector` / `options[].choices`。
4. **写 `login.js`**：照抄 `plugins/JOU/login.js`，改顶部 `selectors`、`successKeywords` 等常量即可，逻辑无需重写。
5. **在 `config.json` 登记**：
   ```json
   "networks": [
     {
       "profile": "JOU",
       "label": "校园网络",
       "need_login": true,
       "plugin": "JOU",
       "login": {
         "url": "http://210.28.39.250/",
         "credentials": {"account": "你的账号", "password": "你的密码"},
         "options": {"isp": "@unicom"}
       },
       "guard": {"enabled": false}
     }
   ]
   ```
6. **校验**：`python cli.py plugin-validate`（应输出 `ok=true`、`errors=[]`）。
7. **试登录**：`python cli.py login --network JOU --channel browser`（需要 selenium；HTTP 通道用 `--channel requests`）。
8. **自动同步旧规则**：若已有可用的旧单体程序，直接 `python tools/make_plugin_from_legacy.py --force` 由工具生成，无需手写。

---

## 6. 加载与校验行为（`core/plugins.py`）

- **发现**：扫描 `plugins/` 下每个子目录，读 `manifest.json` + `login.js`。
- **校验**（`plugin-validate` / `load_all()`）：
  - `manifest.json` 可解析且为对象；`spec_version` / `wifi` / `name` / `login` 必备；
  - **目录名与 `manifest.wifi` 必须一致**，否则 `errors` 记录并拒绝用于登录；
  - `login.url` 非空（缺失仅告警）；
  - `credentials[].key` 唯一且非空；`options[].key` 唯一；
  - `login.js` 存在且定义 `CampusNetPlugin`，必备函数 `match` / `fill` / `submit` / `success` 齐全，缺失即为错误；
  - `http.attempts` 每条须有 `url` 与可判定的 `success` 规则。
- **热加载**：`load_all(force_reload=True)` 重新读取磁盘，GUI 保存插件后可即时生效，无需重启程序。
- **入口**：`find_for_network(name)` 按 WiFi 名称或 `config.json` 里的 `plugin` 字段定位插件。
