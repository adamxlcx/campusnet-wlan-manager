/* eslint-disable */
/**
 * JOU 校园网（Dr.COM / eportal 门户） —— 校园网登录插件（由 tools/make_plugin_from_legacy.py 自动生成）
 *
 * WiFi 名称：JOU
 * 登录页：http://210.28.39.250/
 * 门户类型：eportal-drcom（Dr.COM / eportal 门户）
 * 生成时间：2026-10-13 06:29:36
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
  specVersion: "1.0",
  id: "jou-eportal-drcom",
  wifi: "JOU",
  name: "JOU 校园网（Dr.COM / eportal 门户）",
  pageUrl: "http://210.28.39.250/",
  urlPatterns: ["*eportal*", "*drcom*", "*dr1003*"],

  selectors: {
    form: "form[name='f1']",
    account: "input[name='DDDDD']",
    password: "input[name='upass']",
    isp: "select[name='ISP_select']",
    submit: "input[name='0MKKey']",
    captchaInput: "input[name='captcha']",
    captchaImage: "#captcha_img"
  },
  submitPageFunction: "ee(1)",
  successKeywords: ["注销", "退出", "已登录", "登录成功", "logout", "success"],
  failureKeywords: ["密码错误", "账号或密码", "用户不存在", "已欠费", "认证失败", "登录失败", "error"],
  successUrlPatterns: ["eportal", "index", "portal", "210.28.39.250"],

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

    // 运营商是“自定义选项”（manifest.options[].key = isp），键名与 manifest.options[].key 一致（此处为 isp）
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
