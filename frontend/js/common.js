/* ==========================================================================
   common.js —— 寻径教育 PathFinder 前端运行时
   --------------------------------------------------------------------------
   零依赖、零构建。每个页面只引这一份 + tabs.js，页面逻辑写在各 HTML 内联脚本里。
   对外只暴露一个全局：window.PF

   设计原则：
   1. 任何一次请求失败都必须让人看见 —— 不吞异常、不静默降级。
   2. 所有来自后端或用户的内容都先 escapeHtml 再拼进 innerHTML。
   3. 引擎来源（AI 生成 / 规则生成）永远显式标注，不把模拟结果冒充模型输出。
   ========================================================================== */
(function () {
  "use strict";

  const PF = (window.PF = {});

  /* ============================================================ 图标库 */
  /* 全部为 24×24 描边图标，stroke 继承 currentColor，避免任何图标字体依赖 */
  const ICONS = {
    compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    message: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/>',
    sparkles: '<path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z"/><path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z"/>',
    presentation: '<path d="M3 4h18"/><rect x="4" y="4" width="16" height="11" rx="2"/><path d="M12 15v4"/><path d="M8.5 22l3.5-3 3.5 3"/>',
    clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 11l1.8 1.8L14.5 9"/>',
    users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5.2a3.2 3.2 0 0 1 0 6"/><path d="M18 20a6 6 0 0 0-2.2-4.6"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    file: '<path d="M14 3v5h5"/><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M9 13h6M9 17h4"/>',
    upload: '<path d="M12 16V4"/><path d="M8 8l4-4 4 4"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    download: '<path d="M12 4v12"/><path d="M8 12l4 4 4-4"/><path d="M4 18v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="M4.5 12.5l5 5 10-11"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    edit: '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="M14 6l4 4"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.5h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.5h.01"/>',
    chevronRight: '<path d="M9 5l7 7-7 7"/>',
    chevronDown: '<path d="M6 9l6 6 6-6"/>',
    chevronLeft: '<path d="M15 5l-7 7 7 7"/>',
    logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 16l-4-4 4-4"/><path d="M6 12h11"/>',
    user: '<path d="M20 21v-1.5a4.5 4.5 0 0 0-4.5-4.5h-7A4.5 4.5 0 0 0 4 19.5V21"/><circle cx="12" cy="7.5" r="3.8"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-13.7-5.2L4 8"/><path d="M4 5v3.5h3.5"/><path d="M4 13a8 8 0 0 0 13.7 5.2L20 16"/><path d="M20 19v-3.5h-3.5"/>',
    send: '<path d="M4 12l16-8-6 16-2.5-6.5z"/>',
    target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
    award: '<circle cx="12" cy="9" r="5.5"/><path d="M8.5 13.8L7 21l5-2.5L17 21l-1.5-7.2"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M3 12h18"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3.5 2"/>',
    play: '<path d="M7 4.5l12 7.5-12 7.5z"/>',
    save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h8V3"/><path d="M8 21v-6h8v6"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 1 0-5.7-5.7L11.5 7"/><path d="M14 10a4 4 0 0 0-5.7 0L5.5 12.8a4 4 0 1 0 5.7 5.7l1.3-1.5"/>',
    book: '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20"/>',
    shield: '<path d="M12 3l8 3v6c0 4.5-3.2 8.3-8 9.5C7.2 20.3 4 16.5 4 12V6z"/><path d="M9 12l2 2 4-4"/>',
    scale: '<path d="M12 4v16"/><path d="M6 8h12"/><path d="M6 8l-3 6h6z"/><path d="M18 8l-3 6h6z"/><path d="M9 20h6"/>',
    wand: '<path d="M5 19L17 7"/><path d="M15 5l4 4"/><path d="M18 13l.7 1.8L20.5 15l-1.8.7L18 17.5l-.7-1.8L15.5 15l1.8-.7z"/><path d="M7 5l.5 1.3L8.8 6.8 7.5 7.3 7 8.6 6.5 7.3 5.2 6.8 6.5 6.3z"/>',
    filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    star: '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 16.9l-5.3 2.8 1.1-5.9-4.3-4.1 5.9-.8z"/>',
    bell: '<path d="M18 8a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7"/><path d="M10.5 20a2 2 0 0 0 3 0"/>',
    activity: '<path d="M3 12h4l2.5-7 4 14 2.5-7h4"/>',
    crop: '<path d="M6 2v16h16"/><path d="M2 6h16v16"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.8"/><path d="M21 16.5L15.5 11 6 20"/>',
    home: '<path d="M4 11l8-7 8 7"/><path d="M6 10v10h12V10"/>',
    sun: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.2v2.3M12 19.5v2.3M2.2 12h2.3M19.5 12h2.3M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M19.1 4.9l-1.7 1.7M6.6 17.4l-1.7 1.7"/>',
    moon: '<path d="M20.5 14.2A8.6 8.6 0 0 1 9.8 3.5a8.6 8.6 0 1 0 10.7 10.7z"/>',
  };

  /**
   * 生成一个图标 SVG 字符串。
   * @param {string} name  ICONS 中的键
   * @param {number} size  像素尺寸（默认 16）
   */
  PF.icon = function (name, size) {
    const body = ICONS[name] || ICONS.info;
    const s = size || 16;
    return (
      '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true">' + body + "</svg>"
    );
  };

  /* ============================================================ 基础工具 */
  const HTML_ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  /** 转义 HTML —— 凡是拼接来自后端/用户的文本，必须先过这一层。 */
  PF.esc = function (v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/[&<>"']/g, (c) => HTML_ESC[c]);
  };
  PF.escapeHtml = PF.esc;

  /** 取元素（支持选择器或元素本身） */
  PF.$ = function (sel, root) { return (root || document).querySelector(sel); };
  PF.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /** 尽力把任意值转成数组，避免后端返回 null 时前端崩 */
  PF.arr = function (v) { return Array.isArray(v) ? v : []; };

  /** 数字格式化：保留 sign + 最多 n 位小数 */
  PF.num = function (v, digits) {
    const n = Number(v);
    if (!isFinite(n)) return "—";
    return n.toFixed(digits === undefined ? 1 : digits).replace(/\.0+$/, "");
  };

  /** 百分比（入参为 0~1 或 0~100，由 total 决定） */
  PF.pct = function (part, total) {
    const t = Number(total) || 0;
    if (t <= 0) return 0;
    return Math.round((Number(part) || 0) / t * 100);
  };

  /** 截断文本 */
  PF.trunc = function (text, n) {
    const s = String(text === null || text === undefined ? "" : text);
    return s.length > n ? s.slice(0, n) + "…" : s;
  };

  /** 友好时间：刚刚 / N 分钟前 / 今天 HH:MM / MM-DD HH:MM */
  PF.when = function (value) {
    if (!value) return "—";
    let iso = String(value).trim();
    // 后端存的是 "YYYY-MM-DD HH:MM:SS"，Safari 不认，替换空格为 T
    if (/^\d{4}-\d{2}-\d{2} /.test(iso)) iso = iso.replace(" ", "T");
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(value);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff >= 0 && diff < 60) return "刚刚";
    if (diff >= 0 && diff < 3600) return Math.floor(diff / 60) + " 分钟前";
    const pad = (x) => String(x).padStart(2, "0");
    const hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    if (d.toDateString() === now.toDateString()) return "今天 " + hm;
    return pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + hm;
  };

  /** 只取日期部分 */
  PF.date = function (value) {
    if (!value) return "—";
    const s = String(value).trim();
    return s.length >= 10 ? s.slice(0, 10) : s;
  };

  /** 是否已过期（与后端 now() 同口径的字符串比较即可） */
  PF.isPast = function (value) {
    if (!value) return false;
    const s = String(value).replace("T", " ").trim();
    const d = new Date(s.replace(" ", "T"));
    return !isNaN(d.getTime()) && d.getTime() < Date.now();
  };

  /** 取姓名首字用于头像 */
  PF.initial = function (name) {
    const s = String(name || "?").trim();
    return s ? s.slice(0, 1) : "?";
  };

  /* ============================================================ 网络层 */
  /** 模块级状态：当前用户、轻量缓存 */
  PF.state = { me: null, meta: null };

  function authHeaders() {
    const t = localStorage.getItem("pf_token");
    return t ? { Authorization: "Bearer " + t } : {};
  }

  /**
   * 统一请求封装。失败一定抛 Error，调用方用 try/catch 或 PF.try 处理。
   * @param {string} path        以 /api 开头的路径
   * @param {object} [opts]
   * @param {string} [opts.method]
   * @param {object} [opts.body] 会被 JSON 序列化
   * @param {FormData} [opts.form] multipart 上传（与 body 二选一）
   * @param {boolean} [opts.quiet] true 时不弹 toast（由调用方自己处理）
   */
  PF.api = async function (path, opts) {
    const o = opts || {};
    const init = { method: o.method || "GET", headers: Object.assign({}, authHeaders()) };
    if (o.form) {
      init.body = o.form;
    } else if (o.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(o.body);
    }
    let res;
    try {
      res = await fetch(path, init);
    } catch (e) {
      const err = new Error("网络请求失败，请确认后端服务已启动（" + path + "）");
      if (!o.quiet) PF.toast(err.message, "err");
      throw err;
    }
    let payload = null;
    const text = await res.text();
    if (text) {
      try { payload = JSON.parse(text); } catch (e) { payload = null; }
    }
    if (res.status === 401) {
      const err = new Error((payload && payload.error) || "登录已过期，请重新登录");
      err.status = 401;
      if (!o.quiet) { PF.toast(err.message, "err"); }
      // 只有明确是"登录态失效"才跳转，登录接口本身的 400 不跳。
      // 另外：**已经在登录页时绝不能跳转** —— 登录页自身要靠 /api/auth/me 的 401
      // 判断"当前未登录"，若无条件跳 /login，页面会自我重定向成无限刷新循环。
      const onLoginPage = /^\/login\b/.test(window.location.pathname) || /\/auth\/login$/.test(path);
      if (!onLoginPage && !/账号或密码/.test(err.message)) {
        setTimeout(() => { window.location.href = "/login"; }, 700);
      }
      throw err;
    }
    if (!res.ok || !payload || payload.ok !== true) {
      const msg = (payload && payload.error) || ("请求失败（HTTP " + res.status + "）");
      const err = new Error(msg);
      err.status = res.status;
      if (!o.quiet) PF.toast(msg, "err");
      throw err;
    }
    return payload.data;
  };

  PF.get = function (path, opts) { return PF.api(path, Object.assign({ method: "GET" }, opts)); };
  PF.post = function (path, body, opts) { return PF.api(path, Object.assign({ method: "POST", body: body || {} }, opts)); };
  PF.del = function (path, opts) { return PF.api(path, Object.assign({ method: "DELETE" }, opts)); };

  /** 包一层：失败返回 fallback 而不抛出，用于非关键路径（如元数据） */
  PF.try = async function (fn, fallback) {
    try { return await fn(); } catch (e) { return fallback; }
  };

  /** 用 fetch + Blob 下载（保留中文文件名，且能带 Bearer 头） */
  PF.download = async function (path, fallbackName) {
    let res;
    try {
      res = await fetch(path, { headers: authHeaders() });
    } catch (e) {
      PF.toast("下载失败：网络不可达", "err");
      return;
    }
    if (!res.ok) {
      PF.toast("下载失败（HTTP " + res.status + "）", "err");
      return;
    }
    const cd = res.headers.get("Content-Disposition") || "";
    let name = fallbackName || "download";
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const plain = /filename="?([^";]+)"?/i.exec(cd);
    if (star) { try { name = decodeURIComponent(star[1]); } catch (e) { /* 保持兜底名 */ } }
    else if (plain && plain[1]) { name = plain[1]; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  /* ============================================================ 提示与弹窗 */
  function toastHost() {
    let host = PF.$(".toast-host");
    if (!host) {
      host = document.createElement("div");
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    return host;
  }

  /**
   * 轻提示。
   * @param {string} message
   * @param {"ok"|"err"|"warn"|""} [type]
   */
  PF.toast = function (message, type) {
    const ico = type === "ok" ? "check" : type === "err" ? "alert" : type === "warn" ? "alert" : "info";
    const el = document.createElement("div");
    el.className = "toast" + (type ? " toast--" + type : "");
    el.innerHTML = PF.icon(ico, 16) + "<span>" + PF.esc(message) + "</span>";
    const host = toastHost();
    host.appendChild(el);
    const life = type === "err" ? 5200 : 3000;
    setTimeout(() => {
      el.classList.add("is-out");
      setTimeout(() => el.remove(), 220);
    }, life);
  };

  /**
   * 打开一个对话框，返回 { el, close, body, foot }。
   * @param {object} cfg  { title, body(HTML 或 Node), actions:[{label,type,onClick,close}], width:"narrow"|"wide" }
   */
  PF.modal = function (cfg) {
    const c = cfg || {};
    const opener = document.activeElement;      // 关掉之后要把焦点还回去
    const host = document.createElement("div");
    host.className = "modal-host";
    const sizeCls = c.width === "wide" ? " modal--wide" : c.width === "narrow" ? " modal--narrow" : "";
    const title = c.title || "对话框";
    host.innerHTML =
      '<div class="modal' + sizeCls + '" role="dialog" aria-modal="true" aria-label="' + PF.esc(title) + '">' +
        '<div class="modal__head">' +
          '<div class="modal__title">' + PF.esc(title) + "</div>" +
          '<button class="modal__close" type="button" aria-label="关闭">' + PF.icon("x", 16) + "</button>" +
        "</div>" +
        '<div class="modal__body"></div>' +
        '<div class="modal__foot"></div>' +
      "</div>";
    const bodyEl = PF.$(".modal__body", host);
    const footEl = PF.$(".modal__foot", host);

    let closed = false;
    function close() {
      if (closed) return;
      closed = true;
      document.removeEventListener("keydown", onKey, true);
      // 退场动画只在"会动"的环境里播；播完再摘掉节点，否则动画会被打断
      if (PF.reduced()) {
        host.remove();
      } else {
        host.classList.add("is-out");
        setTimeout(function () { host.remove(); }, 200);
      }
      if (opener && typeof opener.focus === "function" && opener.isConnected) {
        try { opener.focus(); } catch (e) { /* 原元素已不可聚焦，忽略 */ }
      }
      if (typeof c.onClose === "function") c.onClose();
    }

    /** 当前可聚焦的控件，用于把 Tab 圈在弹窗里 */
    function focusables() {
      return PF.$$(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])', host
      ).filter(function (el) { return el.getClientRects().length > 0; });
    }

    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); close(); return; }
      if (e.key !== "Tab") return;
      const list = focusables();
      if (!list.length) return;
      const first = list[0];
      const last = list[list.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !host.contains(active))) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault(); first.focus();
      }
    }

    document.addEventListener("keydown", onKey, true);
    PF.$(".modal__close", host).addEventListener("click", close);
    host.addEventListener("mousedown", function (e) { if (e.target === host) close(); });

    if (typeof c.body === "string") bodyEl.innerHTML = c.body;
    else if (c.body) bodyEl.appendChild(c.body);

    const actions = c.actions || [];
    if (!actions.length) {
      footEl.innerHTML = '<button class="btn" type="button" data-role="close">关闭</button>';
      PF.$('[data-role="close"]', footEl).addEventListener("click", close);
    } else {
      actions.forEach(function (a, i) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn " + (a.type === "primary" ? "btn--primary" : a.type === "danger" ? "btn--danger" : a.type === "ok" ? "btn--ok" : "");
        btn.textContent = a.label;
        btn.addEventListener("click", async function () {
          if (typeof a.onClick !== "function") { close(); return; }
          btn.classList.add("is-loading");
          const original = btn.textContent;
          btn.innerHTML = '<span class="spin"></span>' + PF.esc(original);
          try {
            const keep = await a.onClick({ close: close, body: bodyEl, foot: footEl, button: btn });
            if (keep !== true) close();
          } catch (e) {
            btn.classList.remove("is-loading");
            btn.textContent = original;
          }
        });
        footEl.appendChild(btn);
        if (i === actions.length - 1 && a.type === "primary") btn.focus();
      });
    }
    document.body.appendChild(host);
    // 弹窗内容是动态塞进去的，新内容也要享受错峰入场（观察器会接管，这里只保证首屏）
    if (!PF.reduced()) PF.reveal(bodyEl);
    return { el: host, body: bodyEl, foot: footEl, close: close };
  };

  /** 二次确认（危险操作统一走这里，避免误点） */
  PF.confirm = function (opts) {
    const o = opts || {};
    return new Promise((resolve) => {
      let settled = false;
      const m = PF.modal({
        title: o.title || "请确认",
        width: "narrow",
        body: '<p class="t-body">' + PF.esc(o.text || "") + "</p>" +
              (o.detail ? '<div class="note note--warn mt-4">' + PF.icon("alert", 15) + "<div>" + PF.esc(o.detail) + "</div></div>" : ""),
        actions: [
          { label: o.cancelText || "取消", onClick: () => { settled = true; resolve(false); } },
          { label: o.okText || "确定", type: o.danger ? "danger" : "primary",
            onClick: () => { settled = true; resolve(true); } },
        ],
        onClose: () => { if (!settled) resolve(false); },
      });
      if (o.danger) {
        const btn = m.foot.lastElementChild;
        if (btn) btn.classList.add("btn--danger");
      }
    });
  };

  /* ============================================================ 徽标构件 */
  /** 引擎徽标：llm → "AI 生成"，rule → "规则生成" */
  PF.engineBadge = function (engine) {
    const isLlm = engine === "llm" || engine === "api";
    return '<span class="engine engine--' + (isLlm ? "llm" : "rule") + '">' +
      (isLlm ? "AI 生成" : "规则生成") + "</span>";
  };

  /** 双轨标签 */
  PF.trackBadge = function (track) {
    const t = String(track || "");
    const career = t.indexOf("事业") >= 0;
    return '<span class="track track--' + (career ? "career" : "academic") + '">' +
      (career ? "事业型" : "学业型") + "</span>";
  };

  /** 层次标签（A/B/C，只表示推荐内容深度） */
  PF.levelTag = function (level, large) {
    const lv = String(level || "B").toUpperCase().slice(0, 1);
    const safe = ["A", "B", "C"].indexOf(lv) >= 0 ? lv : "B";
    const text = { A: "优秀", B: "良好", C: "需改进" }[safe];
    return '<span class="level level--' + safe + (large ? " level--lg" : "") + '" title="' +
      text + '">' + safe + "</span>";
  };

  /* ---------------------------------------------------------- 能力说明手册
     三项能力的口径**不写在页面里**，而是从 /api/manual 读。
     那份数据由 services/manual.py 从代码中的规则表生成 —— 改规则即改手册，
     不会出现「文档写着一套、代码跑着另一套」。 */
  function manualChapter(ch) {
    return (PF.arr(ch.sections) || []).map(function (s) {
      let html = '<h4 class="mn-h4">' + PF.esc(s.title || "") + "</h4>";
      if (s.type === "text") {
        html += '<p class="mn-p">' + PF.esc(s.body || "") + "</p>";
      } else if (s.type === "list") {
        html += '<ul class="mn-ul">' + PF.arr(s.items).map(function (x) {
          return "<li>" + PF.esc(x) + "</li>";
        }).join("") + "</ul>";
      } else if (s.type === "table") {
        html += '<div class="mn-tbl" style="--mn-cols:' + (PF.arr(s.columns).length || 2) + '">' +
          '<div class="mn-tr mn-tr--head">' + PF.arr(s.columns).map(function (c) {
            return '<div class="mn-td">' + PF.esc(c) + "</div>";
          }).join("") + "</div>" +
          PF.arr(s.rows).map(function (row) {
            return '<div class="mn-tr">' + PF.arr(row).map(function (c) {
              return '<div class="mn-td">' + PF.esc(String(c)) + "</div>";
            }).join("") + "</div>";
          }).join("") + "</div>";
      }
      return html;
    }).join("");
  }

  PF.manual = async function (chapterId) {
    let data;
    try {
      data = await PF.get("/api/manual", { quiet: true });
    } catch (e) {
      PF.toast("手册加载失败：" + e.message, "err");
      return null;
    }
    const chapters = PF.arr(data.chapters);
    const m = PF.modal({
      title: "能力说明手册 " + PF.esc(data.version || ""),
      width: "wide",
      body: '<div class="manual"><div class="manual__nav" id="mn-nav"></div>' +
            '<div class="manual__body" id="mn-body"></div></div>',
      actions: [{ label: "关闭", type: "primary" }],
    });
    const nav = PF.$("#mn-nav", m.body);
    const body = PF.$("#mn-body", m.body);

    function apiTable() {
      return '<p class="mn-sum">' + PF.esc(data.api_note ||
        "这一页是给要接手代码的人看的，使用者可以忽略。") + "</p>" +
        '<h4 class="mn-h4">接口在哪、用来做什么</h4>' +
        '<div class="mn-tbl" style="--mn-cols:3"><div class="mn-tr mn-tr--head">' +
        '<div class="mn-td">模块</div><div class="mn-td">符号</div><div class="mn-td">用途</div></div>' +
        PF.arr(data.api).map(function (a) {
          return '<div class="mn-tr"><div class="mn-td t-mono">' + PF.esc(a.module) + "</div>" +
            '<div class="mn-td t-mono">' + PF.esc(a.symbol) + "</div>" +
            '<div class="mn-td">' + PF.esc(a.purpose) + "</div></div>";
        }).join("") + "</div>";
    }

    function pick(id) {
      PF.$$("button", nav).forEach(function (b) {
        b.classList.toggle("is-on", b.dataset.ch === id);
      });
      if (id === "api") { body.innerHTML = apiTable(); return; }
      const ch = chapters.filter(function (c) { return c.id === id; })[0];
      if (!ch) { body.innerHTML = PF.empty({ title: "章节不存在" }); return; }
      body.innerHTML = '<p class="mn-sum">' + PF.esc(ch.summary || "") + "</p>" + manualChapter(ch);
    }

    nav.innerHTML = chapters.map(function (c) {
      return '<button class="btn btn--sm mn-navbtn" data-ch="' + PF.esc(c.id) + '">' +
        PF.esc(c.title) + "</button>";
    }).join("") + '<button class="btn btn--sm mn-navbtn" data-ch="api">给开发者的接口清单</button>';

    PF.$$("[data-ch]", nav).forEach(function (b) {
      b.addEventListener("click", function () { pick(b.dataset.ch); });
    });
    pick(chapterId || (chapters[0] && chapters[0].id) || "api");
    if (!PF.reduced()) PF.reveal(body);
    return m;
  };

  /** 智能体简介卡（放在智能体页面右侧，紧凑、不抢正文排版）。 */
  PF.agentCard = function (cfg) {
    const c = cfg || {};
    return '<div class="agent-card">' +
      '<div class="agent-card__name">' + PF.esc(c.name || "智能体") + "</div>" +
      '<div class="agent-card__one">' + PF.esc(c.one_line || "") + "</div>" +
      '<div class="agent-card__row"><span class="agent-card__k">能答</span>' +
        '<span class="agent-card__v">' + PF.arr(c.answers).slice(0, 7).map(function (x) {
          return '<span class="chiplet">' + PF.esc(x) + "</span>";
        }).join("") + "</span></div>" +
      '<div class="agent-card__row"><span class="agent-card__k">怎么答</span>' +
        '<span class="agent-card__v">' + PF.esc(c.how || "") + "</span></div>" +
      '<div class="agent-card__row"><span class="agent-card__k">依据</span>' +
        '<span class="agent-card__v">' + PF.esc(c.ground || "") + "</span></div>" +
      (c.can ? '<div class="agent-card__row"><span class="agent-card__k">还能做</span>' +
        '<span class="agent-card__v">' + PF.esc(c.can) + "</span></div>" : "") +
      '<div class="agent-card__foot">' +
        '<button class="btn btn--sm btn--primary" id="' + PF.esc(c.btnId || "btn-manual") + '">' +
          PF.icon("book", 12) + "查看说明手册</button>" +
      "</div>" +
      '<div class="agent-card__note">' + PF.esc(c.caveat || "") + "</div>" +
    "</div>";
  };

  /** 答疑协议附加块：答疑类型 / 协议阶段 / 澄清 / 追问建议 / 下一步动作。 */
  PF.qaBlock = function (d) {
    if (!d) return "";
    const intent = d.intent || {};
    const proto = d.protocol || {};
    let html = '<div class="qa-extra">';
    if (intent.label) {
      html += '<span class="badge badge--brand">答疑类型 · ' + PF.esc(intent.label) + "</span>";
    }
    if (proto.stage_label) {
      html += '<span class="badge">协议 · ' + PF.esc(proto.stage_label) + "</span>";
    }
    html += "</div>";
    if (proto.need_clarify && proto.clarify_question) {
      html += '<div class="qa-clarify">' + PF.icon("info", 13) +
        "<div><b>先确认一下：</b>" + PF.esc(proto.clarify_question) + "</div></div>";
    }
    const fu = PF.arr(d.followups);
    if (fu.length) {
      html += '<div class="qa-k">可以继续问</div><div class="qa-chips">' +
        fu.map(function (q) {
          return '<button class="btn btn--sm q-chip" data-fu="' + PF.esc(q) + '">' +
            PF.esc(PF.trunc(q, 26)) + "</button>";
        }).join("") + "</div>";
    }
    const acts = PF.arr(d.actions);
    if (acts.length) {
      html += '<div class="qa-k">下一步</div><div class="qa-chips">' +
        acts.map(function (a) {
          return '<span class="qa-act" title="' + PF.esc(a.hint || "") + '">' +
            PF.icon("target", 12) + PF.esc(a.label) + "</span>";
        }).join("") + "</div>";
    }
    return html;
  };

  /* ---------------------------------------------------------- RAG 路由
     五种架构共用一张策略表。数据与后端 ragroute.STRATEGIES 对齐，
     接口没返回时用它兜底，保证断网也能演示。 */
  PF.RAG_STRATEGIES = [
    { id: "auto", name: "自动选择", when: "按问题自己挑一种" },
    { id: "hybrid", name: "混合式 RAG", when: "概念、原理这类文字解释" },
    { id: "graph", name: "图谱 RAG", when: "问关系、前置、知识链路" },
    { id: "agentic", name: "智能体式 RAG", when: "要结合我的情况、要计划" },
    { id: "corrective", name: "纠错型 RAG", when: "口语、指代、说得含糊" },
    { id: "multimodal", name: "多模态 RAG", when: "问图、表、扫描件、版面" },
  ];

  /** 策略下拉框。``picked`` 为当前值，默认 auto。 */
  PF.ragSelect = function (id, picked, width) {
    const cur = picked || "auto";
    return '<select class="select select--sm" id="' + PF.esc(id) + '" title="检索策略：不同问题走不同架构" ' +
      'style="width:' + (width || 128) + 'px">' +
      PF.RAG_STRATEGIES.map(function (s) {
        return '<option value="' + PF.esc(s.id) + '"' + (s.id === cur ? " selected" : "") + '>' +
          PF.esc(s.name) + "</option>";
      }).join("") + "</select>";
  };

  /** 本次走了哪种 RAG：徽标 + 理由 + 该架构自己的证据（子图 / 计划 / 改写 / 图片）。 */
  PF.ragCard = function (rag) {
    const r = rag || {};
    if (!r.strategy) return "";
    const extra = r.extra || {};
    let html = '<div class="rag-card">' +
      '<div class="rag-card__head">' +
        '<span class="badge badge--brand">' + PF.esc(r.strategy_name || r.strategy) + "</span>" +
        (r.auto === false ? '<span class="badge">手动指定</span>' : '<span class="badge">自动路由</span>') +
        '<div class="spacer"></div>' +
        '<span class="t-xs t-dim">' + PF.esc(r.reason || "") + "</span>" +
      "</div>";

    // 图谱：把召回到的子图读出来
    const g = extra.graph;
    if (g) {
      html += '<div class="rag-card__sec"><span class="rag-card__k">子图</span>' +
        '<span class="rag-card__v">' +
        (PF.arr(g.nodes).length
          ? PF.arr(g.nodes).slice(0, 8).map(function (n) {
              return '<span class="chiplet">' + PF.esc(n) + "</span>";
            }).join("")
          : '<span class="t-dim">问题没命中知识点，未展开子图</span>') +
        "</span></div>" +
        '<div class="rag-card__sec"><span class="rag-card__k">关系</span>' +
        '<span class="rag-card__v">' +
        (PF.arr(g.edges).length
          ? PF.arr(g.edges).slice(0, 6).map(function (e) {
              return '<span class="chiplet">' + PF.esc(e.source) + " — " + PF.esc(e.target) +
                '<span class="t-dim">（' + PF.esc(e.reason || "") + "）</span></span>";
            }).join("")
          : '<span class="t-dim">暂未建立关联边</span>') +
        "</span></div>";
    }
    // 智能体式：规划了哪几步、每步拿到什么
    if (PF.arr(extra.plan).length) {
      html += '<div class="rag-card__sec"><span class="rag-card__k">规划执行</span>' +
        '<span class="rag-card__v">' + extra.plan.map(function (p) {
          return '<span class="chiplet">' + PF.esc(p.tool) + " · 取到 " + PF.num(p.found, 0) +
            '<span class="t-dim">（' + PF.esc(p.note || "") + "）</span></span>";
        }).join("") + "</span></div>";
    }
    // 纠错式：改写了什么
    if (extra.rewrite) {
      html += '<div class="rag-card__sec"><span class="rag-card__k">改写</span>' +
        '<span class="rag-card__v t-sm">「' + PF.esc(extra.rewrite.from) + "」→「" +
        PF.esc(extra.rewrite.to) + "」</span></div>";
    }
    if (extra.rounds) {
      html += '<div class="rag-card__sec"><span class="rag-card__k">检索</span>' +
        '<span class="rag-card__v t-sm">' + PF.num(extra.rounds, 0) + " 轮，首查质量 " +
        PF.esc(extra.quality || "—") + "</span></div>";
    }
    // 多模态：一起召回了哪些图片素材
    if (PF.arr(extra.images).length) {
      html += '<div class="rag-card__sec"><span class="rag-card__k">图片素材</span>' +
        '<span class="rag-card__v">' + extra.images.slice(0, 4).map(function (im) {
          return '<span class="chiplet">' + PF.icon("image", 11) + PF.esc(PF.trunc(im.title, 16)) + "</span>";
        }).join("") + "</span></div>";
    }
    if (extra.note) {
      html += '<div class="rag-card__note">' + PF.esc(extra.note) + "</div>";
    }
    return html + "</div>";
  };

  /** 综合生成卡：回答不是检索片段的拼接，而是"证据 + 推理"综合出来的。
      默认折叠，点开看它这次走了哪几步、依据了哪几句原文。 */
  PF.synthCard = function (s) {
    const d = s || {};
    const steps = PF.arr(d.steps);
    const ev = PF.arr(d.evidence);
    if (!steps.length && !ev.length) return "";
    let html = '<details class="synth-card">' +
      "<summary>" +
        '<span class="badge badge--brand">' + PF.esc(d.mode || "综合生成") + "</span>" +
        '<span class="t-xs t-dim">' + PF.esc("综合 " + PF.num(d.evidence_count || ev.length, 0) +
          " 条证据" + (d.hit_count ? "（命中 " + PF.num(d.hit_count, 0) + " 条）" : "") +
          "，不是原文拼接") + "</span>" +
        '<div class="spacer"></div>' +
        '<span class="t-xs t-dim">看它怎么想出来的</span>' +
      "</summary>";
    if (d.conclusion) {
      html += '<div class="synth-card__lead">' + PF.esc(d.conclusion) + "</div>";
    }
    html += '<div class="synth-card__steps">' + steps.map(function (st) {
      return '<div class="synth-step">' +
        '<span class="synth-step__i">' + PF.esc(st.name || "") + "</span>" +
        '<span class="synth-step__t">' + PF.esc(PF.trunc(st.text || st.desc || "", 90)) + "</span>" +
      "</div>";
    }).join("") + "</div>";
    if (ev.length) {
      html += '<div class="synth-card__k">用到的证据原文</div>' +
        ev.map(function (e) {
          return '<div class="synth-ev">' +
            '<span class="chiplet">' + PF.esc(e.ref || "资料") + "</span>" +
            '<span class="synth-ev__t">' + PF.esc(PF.trunc(e.sentence || "", 80)) + "</span>" +
          "</div>";
        }).join("");
    }
    if (d.remind) {
      html += '<div class="rag-card__note">' + PF.icon("info", 12) +
        "易错提醒：" + PF.esc(d.remind) + "</div>";
    }
    return html + "</details>";
  };

  /* ---------------------------------------------------------- 智能体工具
     两个对话页共用：从 /api/agent/tools 拿清单渲染按钮，点开弹窗填参数，
     跑完把结果（含引用来源）就地展示。新增工具不需要改前端。 */
  PF.agentTools = function (cfg) {
    const c = cfg || {};
    const box = c.el;
    const apiBase = c.apiBase || "/api/agent/tools";
    if (!box) return { refresh: function () {} };

    function btnHtml(t) {
      return '<button class="btn btn--sm tool-btn" data-tool="' + PF.esc(t.id) + '">' +
        PF.icon(t.id === "upload_material" ? "upload" : "sparkles", 13) +
        "<span>" + PF.esc(t.name) + "</span></button>";
    }

    async function refresh() {
      const d = await PF.try(function () { return PF.get(apiBase, { quiet: true }); }, null);
      const tools = PF.arr(d && d.tools);
      if (!tools.length) {
        box.innerHTML = '<span class="t-xs t-dim">工具暂不可用</span>';
        return tools;
      }
      box.innerHTML = '<div class="tool-list">' + tools.map(btnHtml).join("") + "</div>" +
        '<div class="t-xs t-dim mt-2">' + PF.esc(tools[0].desc || "") + "</div>";
      PF.$$("[data-tool]", box).forEach(function (b) {
        b.addEventListener("click", function () {
          const t = tools.filter(function (x) { return x.id === b.dataset.tool; })[0];
          if (t) open(t);
        });
      });
      return tools;
    }

    function open(tool) {
      PF.modal({
        title: tool.name,
        body:
          '<p class="t-sm t-dim mb-3">' + PF.esc(tool.desc || "") + "</p>" +
          PF.arr(tool.args).map(function (a) {
            const lab = '<label class="t-xs t-strong" for="ta-' + PF.esc(a.key) + '">' +
              PF.esc(a.label) + (a.required ? ' <span class="t-danger">*</span>' : "") + "</label>";
            if (a.type === "textarea") {
              return '<div class="field">' + lab +
                '<textarea class="input" id="ta-' + PF.esc(a.key) + '" rows="6" placeholder="' +
                PF.esc(a.placeholder || "") + '"></textarea></div>';
            }
            if (a.type === "select") {
              return '<div class="field">' + lab +
                '<select class="select" id="ta-' + PF.esc(a.key) + '">' +
                PF.arr(a.options).map(function (o) {
                  return '<option value="' + PF.esc(o) + '">' + PF.esc(o) + "</option>";
                }).join("") + "</select></div>";
            }
            if (a.type === "switch") {
              return '<label class="switch-row"><input type="checkbox" id="ta-' + PF.esc(a.key) + '">' +
                "<span>" + PF.esc(a.label) + "</span></label>";
            }
            return '<div class="field">' + lab +
              '<input class="input" id="ta-' + PF.esc(a.key) + '" placeholder="' +
              PF.esc(a.placeholder || "") + '"></div>';
          }).join(""),
        actions: [
          { label: "取消" },
          { label: "执行", type: "primary", onClick: async function (m) {
              const args = {};
              for (const a of PF.arr(tool.args)) {
                const el = PF.$("#ta-" + a.key, m.body);
                if (!el) continue;
                args[a.key] = a.type === "switch" ? !!el.checked : el.value;
              }
              const miss = PF.arr(tool.args).filter(function (a) {
                return a.required && !String(args[a.key] || "").trim();
              });
              if (miss.length) { PF.toast("请填写：" + miss.map(function (a) { return a.label; }).join("、"), "warn"); return true; }
              m.body.innerHTML = PF.loading("正在执行…");
              const r = await PF.try(function () {
                return PF.post(apiBase + "/" + tool.id + "/run", args);
              }, null);
              if (!r) { m.body.innerHTML = '<p class="t-sm t-danger">执行失败，请稍后重试。</p>'; return true; }
              m.body.innerHTML = PF.toolResult(tool, r, {
                onInsert: c.onInsert,
                onRerun: function (patch) {
                  return PF.post(apiBase + "/" + tool.id + "/run", Object.assign({}, args, patch));
                },
                refreshDone: function () { refresh(); if (c.onDone) c.onDone(r); },
              });
              return true;   // 留在弹窗里看结果
            } },
        ],
      });
    }

    refresh();
    return { refresh: refresh };
  };

  /** 工具执行结果：统一展示"做了什么 + 依据什么 + 接下来能干嘛"。 */
  PF.toolResult = function (tool, r, opts) {
    const o = opts || {};
    const d = r || {};
    if (d.ok === false) return '<p class="t-sm t-danger">' + PF.esc(d.error || "执行失败") + "</p>";

    let html = '<div class="tool-result">' +
      '<div class="row" style="gap:6px;flex-wrap:wrap">' +
        '<span class="badge badge--ok">已完成</span>' + PF.engineBadge(d.engine) +
        (d.material_id ? '<span class="badge">资料 #' + PF.esc(d.material_id) + "</span>" : "") +
      "</div>" +
      '<p class="t-sm mt-3">' + PF.esc(d.message || "") + "</p>";

    if (tool.id === "upload_material") {
      const pr = d.parse || {};
      html += '<div class="stat-row mt-3">' +
        '<div class="stat"><div class="stat__num">' + PF.num(d.indexed_chunks, 0) + "</div>" +
          '<div class="stat__label">索引片段</div></div>' +
        '<div class="stat"><div class="stat__num">' + PF.num(d.knowledge_saved, 0) + "</div>" +
          '<div class="stat__label">知识点</div></div>' +
        '<div class="stat"><div class="stat__num">' + PF.num(pr.blocks || 0, 0) + "</div>" +
          '<div class="stat__label">解析块</div></div>' +
      "</div>";
      const items = PF.arr(d.kp_rule && d.kp_rule.items);
      if (items.length) {
        html += '<div class="t-xs t-dim mt-3">抽出知识点（' + PF.esc(d.kp_rule.rule_set || "") + "）：" +
          items.map(function (i) { return '<span class="chiplet">' + PF.esc(i.name) + "</span>"; }).join("") +
          "</div>";
      }
    }

    if (d.markdown) {
      html += '<div class="md-box mt-3">' + PF.esc(d.markdown) + "</div>";
      if (PF.arr(d.refs).length) {
        html += '<div class="t-xs t-dim mt-2">依据：' + PF.arr(d.refs).slice(0, 6).map(function (x) {
          return '<span class="chiplet">' + PF.esc(x) + "</span>";
        }).join("") + "</div>";
      }
      html += '<div class="row mt-3" style="gap:8px;flex-wrap:wrap">' +
        (typeof o.onInsert === "function"
          ? '<button class="btn btn--sm" data-act="insert">' + PF.icon("send", 12) + "填入提问框</button>" : "") +
        (!d.material_id && typeof o.onRerun === "function"
          ? '<button class="btn btn--sm btn--primary" data-act="save">' + PF.icon("upload", 12) + "保存到资料库</button>" : "") +
        "</div>";
    }
    html += "</div>";

    // 结果里的按钮要在这里绑定：这一段 HTML 是后来塞进弹窗的
    setTimeout(function () {
      const scope = document.querySelector(".tool-result");
      if (!scope) return;
      const bi = scope.querySelector('[data-act="insert"]');
      if (bi && typeof o.onInsert === "function") {
        bi.addEventListener("click", function () { o.onInsert(d.markdown || "", d); PF.toast("已填入提问框", "ok"); });
      }
      const bs = scope.querySelector('[data-act="save"]');
      if (bs && typeof o.onRerun === "function") {
        bs.addEventListener("click", async function () {
          PF.busy(bs, true, "保存中");
          const again = await PF.try(function () { return o.onRerun({ save: true }); }, null);
          PF.busy(bs, false);
          if (!again) { PF.toast("保存失败", "warn"); return; }
          PF.toast(again.message || "已保存", "ok");
          if (typeof o.refreshDone === "function") o.refreshDone();
          const host = scope.parentElement;
          if (host) host.innerHTML = PF.toolResult(tool, again, { onInsert: o.onInsert });
        });
      }
    }, 0);
    return html;
  };

  /* ---------------------------------------------------------- 会话管理
     「新开对话」与「回到某一次对话」。学生与教师两个场景只差 api 前缀。 */
  PF.sessionList = function (cfg) {
    const c = cfg || {};
    const box = c.el;
    const api = c.api || "/api/tutor";
    let items = [];
    let current = "";

    function paint() {
      if (!box) return;
      box.innerHTML = PF.arr(items).length
        ? items.map(function (s) {
            return '<button class="qa-dock__item' + (s.session_id === current ? " is-on" : "") +
              '" data-sid="' + PF.esc(s.session_id) + '">' +
              '<div class="qa-dock__q">' + PF.esc(PF.trunc(s.title || "（空会话）", 30)) + "</div>" +
              '<div class="qa-dock__t">' + PF.num(s.turns, 0) + " 条 · " +
              PF.esc(PF.when(s.last_at)) + "</div></button>";
          }).join("")
        : '<div class="t-xs t-dim">还没有对话，点上面的「新开对话」开始。</div>';
      PF.$$("[data-sid]", box).forEach(function (b) {
        b.addEventListener("click", function () { pick(b.dataset.sid); });
      });
    }

    function pick(sid) {
      current = sid || "";
      paint();
      if (typeof c.onPick === "function") c.onPick(current);
    }

    async function refresh() {
      const d = await PF.try(function () { return PF.get(api + "/sessions", { quiet: true }); }, null);
      items = PF.arr(d && d.sessions);
      if (typeof c.onStrategies === "function" && d) c.onStrategies(PF.arr(d.strategies));
      if (!current && items.length) current = items[0].session_id || "";
      paint();
      return items;
    }

    async function create() {
      const d = await PF.try(function () { return PF.post(api + "/new", {}, { quiet: true }); }, null);
      current = (d && d.session_id) || "";
      await refresh();
      if (typeof c.onPick === "function") c.onPick(current);
      return current;
    }

    return {
      refresh: refresh, create: create, pick: pick, paint: paint,
      get current() { return current; },
      set current(v) { current = v || ""; paint(); },
      get items() { return items; },
    };
  };

  /** 把容器撑到视口底部，让左右两栏各自滚动（页面整体不再滚）。返回解绑函数。 */
  PF.fitHeight = function (el, pad) {
    if (!el) return function () {};
    const p = typeof pad === "number" ? pad : 20;
    function fit() {
      const top = el.getBoundingClientRect().top;
      const h = Math.max(320, window.innerHeight - top - p);
      el.style.height = Math.round(h) + "px";
    }
    fit();
    window.addEventListener("resize", fit);
    return function () { window.removeEventListener("resize", fit); };
  };

  /** 可拖拽宽度的历史侧栏。cfg: {shell, dock, grip, open} */
  PF.bindDock = function (cfg) {
    const shell = cfg && cfg.shell, grip = cfg && cfg.grip;
    const noop = { toggle: function () {}, isOpen: function () { return false; } };
    if (!shell || !grip) return noop;
    const MIN = 180, MAX = 460, DEFAULT = 280;
    let open = !!(cfg && cfg.open);
    function set(w) {
      shell.style.setProperty("--qa-dock", Math.max(0, Math.round(w)) + "px");
    }
    function toggle(force) {
      open = (typeof force === "boolean") ? force : !open;
      set(open ? DEFAULT : 0);
      grip.setAttribute("aria-expanded", open ? "true" : "false");
    }
    toggle(open);
    grip.title = "拖动调整宽度，双击折叠 / 展开";
    grip.addEventListener("dblclick", function () { toggle(); });
    grip.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      const dock = shell.querySelector(".qa-dock");
      const startX = e.clientX;
      const startW = dock ? dock.getBoundingClientRect().width : 0;
      function move(ev) {
        const w = Math.min(MAX, Math.max(MIN, startW + ev.clientX - startX));
        set(w);
        open = true;
        grip.setAttribute("aria-expanded", "true");
      }
      function up() {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      }
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
    return { toggle: toggle, isOpen: function () { return open; } };
  };

  /* ---------------------------------------------------------- 数字滚动
     只用在"统计数字"这类一眼扫过的信息上。600ms 内结束，ease-out-cubic，
     尊重 prefers-reduced-motion；配合 .num-roll 的等宽数字，递增时不会左右跳。 */
  PF.countUp = function (el, to, opts) {
    if (!el) return;
    const o = opts || {};
    const target = Number(to) || 0;
    const decimals = Math.max(0, Math.min(3, o.decimals || 0));
    const duration = Math.max(180, Math.min(900, o.duration || 620));
    el.classList.add("num-roll");
    if (PF.reduced()) { el.textContent = PF.num(target, decimals); return; }
    const start = performance.now();
    function frame(now) {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = PF.num(target * eased, decimals);
      if (p < 1) requestAnimationFrame(frame);
      else el.textContent = PF.num(target, decimals);
    }
    requestAnimationFrame(frame);
  };

  /** 把容器里**新出现**的统计数字（.stat__num）首位数字改成递增。
      自动挂载，页面不需要为此改一行代码。 */
  PF.countUpIn = function (scope) {
    const root = scope || document;
    PF.$$(".stat__num", root).forEach(function (el) {
      if (el.getAttribute("data-counted")) return;
      const html = el.innerHTML;
      const m = html.match(/^\s*([-+]?\d[\d,]*(?:\.\d+)?)/);
      if (!m) return;
      const to = parseFloat(m[1].replace(/,/g, ""));
      if (!isFinite(to) || to === 0) return;
      el.setAttribute("data-counted", "1");
      const rest = html.slice(m[0].length);
      el.innerHTML = '<span class="num-roll">' + PF.esc(m[1]) + "</span>" + rest;
      PF.countUp(el.firstElementChild, to, { decimals: 0 });
    });
  };

  /* 统计卡是各页面自己渲染的，与其改十几个调用点，不如一次性观察 DOM：
     新插入的 .stat__num 才会被接管，且只处理一次（data-counted 标记）。
     变更用 rAF 合并，避免聊天流式输出时高频触发。 */
  (function autoCountUp() {
    let queued = false;
    function run() { queued = false; PF.countUpIn(document); }
    new MutationObserver(function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(run);
    }).observe(document.body, { childList: true, subtree: true });
    requestAnimationFrame(run);
  })();

  /* ---------------------------------------------------------- 演示例子与测试用例
     例子（samples）= 跑给观众看的完整链路；用例（cases）= 期望写死、可切 live 真跑。
     两份数据都由后端 /api/demo/* 提供，前端只负责呈现与触发。 */
  function demoNoise(res) {
    const rules = ((res.parse || {}).noise || {}).rules || [];
    const hits = rules.filter(function (r) { return r.hits > 0; });
    if (!hits.length) return '<div class="t-xs t-dim">本次没有命中去杂规则。</div>';
    return '<div class="t-xs">命中去杂规则：' + hits.map(function (r) {
      return PF.esc(r.name) + " ×" + r.hits;
    }).join("；") + "</div>";
  }

  function demoKpTable(items) {
    const rows = PF.arr(items);
    if (!rows.length) return '<div class="t-xs t-dim">未抽到知识点。</div>';
    return '<div class="mn-tbl" style="--mn-cols:4"><div class="mn-tr mn-tr--head">' +
      '<div class="mn-td">知识点</div><div class="mn-td">类型</div>' +
      '<div class="mn-td">认知层级</div><div class="mn-td">锚点</div></div>' +
      rows.map(function (i) {
        return '<div class="mn-tr"><div class="mn-td">' + PF.esc(i.name) + "</div>" +
          '<div class="mn-td">' + PF.esc(i.kp_type) + "</div>" +
          '<div class="mn-td">' + PF.esc(i.bloom) + "</div>" +
          '<div class="mn-td">' + PF.esc(i.anchor) + "</div></div>";
      }).join("") + "</div>";
  }

  PF.demo = async function (ability, opts) {
    const o = opts || {};
    let cases = [], samples = [], ov = {};
    try {
      const r = await PF.get("/api/demo/cases", { quiet: true });
      cases = PF.arr(r && r.cases);
      ov = (r && r.overview) || {};
      samples = PF.arr(await PF.get("/api/demo/samples", { quiet: true }));
    } catch (e) {
      PF.toast("演示数据加载失败：" + e.message, "err");
      return null;
    }

    const m = PF.modal({
      title: "演示例子与测试用例",
      width: "wide",
      body: '<div class="manual"><div class="manual__nav" id="dm-nav"></div>' +
            '<div class="manual__body" id="dm-body"></div></div>',
      actions: [{ label: "关闭", type: "primary" }],
    });
    const nav = PF.$("#dm-nav", m.body), body = PF.$("#dm-body", m.body);
    const TABS = [
      { id: "parse", label: "① 图文解析示例" },
      { id: "kp", label: "② 知识点抽取示例" },
      { id: "qa", label: "③ 交互式答疑示例" },
      { id: "rag", label: "④ RAG 路由用例" },
      { id: "synth", label: "⑤ 综合生成用例" },
      { id: "cases", label: "测试用例" },
    ];

    function runSample(s, box) {
      box.innerHTML = PF.loading("正在运行示例");
      PF.post("/api/demo/samples/" + s.id + "/run", {}).then(function (res) {
        if (res.error) { box.innerHTML = PF.empty({ title: "运行失败", desc: res.error }); return; }
        // 内置示例的预置解析结果不能标成"AI 生成"或"规则生成"，会误导；
        // 单独一个徽标说清楚它是仓库自带的预置结果。
        const engineHtml = res.engine === "fixture"
          ? '<span class="badge badge--brand">内置示例 · 预置解析</span>'
          : PF.engineBadge(res.engine);
        let html = '<div class="row" style="gap:6px;flex-wrap:wrap;margin-bottom:8px">' + engineHtml + "</div>";
        if (res.type === "image") {
          const p = res.parsed || {};
          html += '<div class="row" style="gap:6px;flex-wrap:wrap;margin-bottom:8px">' +
            '<span class="badge badge--brand">' + PF.esc(p.title || "—") + "</span>" +
            (p.directions || []).map(function (d) { return '<span class="chip">' + PF.esc(d) + "</span>"; }).join("") +
            (res.expected_rule_set ? '<span class="chip">' + PF.esc(res.expected_rule_set) + "</span>" : "") +
            "</div>" +
            (p.summary ? '<p class="mn-p">' + PF.esc(p.summary) + "</p>" : "") +
            (p.knowledge_points ? demoKpTable((p.knowledge_points || []).map(function (k) {
              return { name: k.name, kp_type: k.difficulty ? "难度 " + k.difficulty : "—",
                       bloom: "—", anchor: res.source === "vision" ? "视觉读图" : "预置" };
            })) : "") +
            (PF.arr(res.detected_noise).length
              ? '<h4 class="mn-h4">应被清掉的噪声</h4><div class="t-xs">' +
                PF.arr(res.detected_noise).map(function (n) { return "· " + PF.esc(n); }).join("<br>") + "</div>"
              : "") +
            (res.vision_note ? '<div class="qa-clarify">' + PF.icon("info", 13) + "<div>" +
              PF.esc(res.vision_note) + "</div></div>" : "");
        } else if (res.type === "qa") {
          // 问答集：不跑解析，直接给可一键填入的问题清单与验收点
          html += '<p class="mn-sum">共 ' + PF.arr(res.pairs).length +
            " 条。点「填入」把问题放进输入框，按「期望」逐条验收。</p>" +
            PF.arr(res.pairs).map(function (p, i) {
              return '<div class="demo-row">' +
                '<div class="demo-row__main">' +
                  '<div class="t-sm"><b>' + (i + 1) + ".</b> " + PF.esc(p.question) +
                    (p.section ? ' <span class="chip">' + PF.esc(p.section) + "</span>" : "") + "</div>" +
                  (p.expect ? '<div class="t-xs t-dim mt-2">期望：' + PF.esc(p.expect) + "</div>" : "") +
                  (p.source ? '<div class="t-xs t-dim">依据：' + PF.esc(p.source) + "</div>" : "") +
                "</div>" +
                '<div class="demo-row__act"><button class="btn btn--sm" data-ask="' +
                  PF.esc(p.question) + '">填入</button></div>' +
              "</div>";
            }).join("");
        } else {
          const doc = (res.parse || {}).doc || {};
          html += '<div class="row" style="gap:6px;flex-wrap:wrap;margin-bottom:8px">' +
            '<span class="badge badge--info">原文 ' + PF.num(doc.chars_before, 0) + " → 清洗后 " +
              PF.num(doc.chars_after, 0) + " 字</span>" +
            '<span class="badge">' + PF.num(doc.blocks, 0) + " 块 / " + PF.num(doc.chunks, 0) + " 片</span>" +
            '<span class="badge">' + PF.num(doc.assets, 0) + " 项素材</span></div>" +
            demoNoise(res.parse || {}) +
            '<h4 class="mn-h4">知识点（' + PF.esc(((res.kp || {}).rule_set || {}).name || "—") + "）</h4>" +
            demoKpTable((res.kp || {}).items);
        }
        box.innerHTML = html;
        PF.$$("[data-ask]", box).forEach(function (b) {
          b.addEventListener("click", function () {
            if (typeof o.onAsk === "function") { o.onAsk(b.dataset.ask); m.close(); return; }
            const input = PF.$("#c-input");
            if (input) { input.value = b.dataset.ask; input.focus(); m.close(); }
          });
        });
      }).catch(function (e) {
        box.innerHTML = PF.empty({ title: "运行失败", desc: e.message });
      });
    }

    function renderSamples(list, box) {
      if (!list.length) { box.innerHTML = PF.empty({ title: "该能力暂无示例" }); return; }
      box.innerHTML = list.map(function (s) {
        return '<div class="demo-row">' +
          '<div class="demo-row__main">' +
            '<div class="t-sm t-strong">' + PF.esc(s.title) +
              ' <span class="chip">' + (s.type === "image" ? "图片" : "文本") + "</span>" +
              (s.available ? "" : ' <span class="badge badge--danger">文件缺失</span>') + "</div>" +
            '<div class="t-xs t-dim mt-2">' + PF.esc(s.points || "") + "</div>" +
            '<div class="demo-res" data-res></div>' +
          "</div>" +
          '<div class="demo-row__act"><button class="btn btn--sm btn--primary" data-run="' + PF.esc(s.id) + '"' +
            (s.available ? "" : " disabled") + ">运行示例</button></div>" +
        "</div>";
      }).join("");
      PF.$$("[data-run]", box).forEach(function (b) {
        b.addEventListener("click", function () {
          const s = list.filter(function (x) { return x.id === b.dataset.run; })[0];
          const box2 = b.closest(".demo-row").querySelector("[data-res]");
          runSample(s, box2);
        });
      });
    }

    function renderCases(list, box) {
      if (!list.length) { box.innerHTML = PF.empty({ title: "暂无用例" }); return; }
      box.innerHTML =
        '<p class="mn-sum">期望结果写死在代码里（稳定、断网可复现）；每个用例都带真实实现的入口，' +
        "点「真实跑一遍」就会执行并与期望比对，给出 PASS / FAIL 和差异明细。</p>" +
        list.map(function (c) {
          return '<div class="demo-row">' +
            '<div class="demo-row__main">' +
              '<div class="t-sm t-strong">' + PF.esc(c.title) +
                ' <span class="chip">' + PF.esc(c.ability) + "</span></div>" +
              '<div class="t-xs t-mono mt-2">' + PF.esc(c.runner) + "</div>" +
              (c.note ? '<div class="t-xs t-dim mt-2">' + PF.esc(c.note) + "</div>" : "") +
              '<div class="demo-res" data-res></div>' +
            "</div>" +
            '<div class="demo-row__act stack-sm">' +
              '<button class="btn btn--sm" data-fixture="' + PF.esc(c.id) + '">按约定（Fixture）</button>' +
              '<button class="btn btn--sm btn--primary" data-live="' + PF.esc(c.id) + '">真实跑一遍（Live）</button>' +
              (c.ability === "qa" || c.ability === "rag"
                ? '<button class="btn btn--sm" data-ask="' + PF.esc(c.input.question || "") +
                '">填入对话框</button>' : "") +
            "</div>" +
          "</div>";
        }).join("");

      function run(cid, live, box2) {
        box2.innerHTML = PF.loading(live ? "真实执行中" : "读取约定");
        PF.post("/api/demo/cases/" + cid + "/run", { live: live }).then(function (r) {
          const ok = r.status === "PASS" || r.status === "约定";
          let html = '<div class="row" style="gap:6px;flex-wrap:wrap">' +
            '<span class="badge ' + (ok ? "badge--ok" : "badge--danger") + '">' + PF.esc(r.status) + "</span>" +
            '<span class="chip">' + (r.mode === "live" ? "Live 真实执行" : "Fixture 写死期望") + "</span></div>";
          if (r.checks) {
            html += '<div class="mn-tbl mt-3" style="--mn-cols:3"><div class="mn-tr mn-tr--head">' +
              '<div class="mn-td">检查项</div><div class="mn-td">期望</div><div class="mn-td">实际</div></div>' +
              r.checks.map(function (k) {
                return '<div class="mn-tr"><div class="mn-td">' + (k.pass ? "✓ " : "✗ ") + PF.esc(k.name) + "</div>" +
                  '<div class="mn-td">' + PF.esc(String(k.name.split("=").pop() || "").trim()) + "</div>" +
                  '<div class="mn-td">' + PF.esc(String(k.actual)) + "</div></div>";
              }).join("") + "</div>";
          }
          box2.innerHTML = html;
        }).catch(function (e) {
          box2.innerHTML = PF.empty({ title: "执行失败", desc: e.message });
        });
      }

      PF.$$("[data-fixture]", box).forEach(function (b) {
        b.addEventListener("click", function () {
          run(b.dataset.fixture, false, b.closest(".demo-row").querySelector("[data-res]"));
        });
      });
      PF.$$("[data-live]", box).forEach(function (b) {
        b.addEventListener("click", function () {
          run(b.dataset.live, true, b.closest(".demo-row").querySelector("[data-res]"));
        });
      });
      PF.$$("[data-ask]", box).forEach(function (b) {
        b.addEventListener("click", function () {
          if (typeof o.onAsk === "function") { o.onAsk(b.dataset.ask); m.close(); return; }
          const input = PF.$("#c-input");
          if (input) { input.value = b.dataset.ask; const send = PF.$("#btn-send"); if (send) send.click(); m.close(); }
        });
      });
    }

    function pick(id) {
      PF.$$("button", nav).forEach(function (b) { b.classList.toggle("is-on", b.dataset.t === id); });
      if (id === "cases") { renderCases(cases, body); return; }
      if (id === "rag") {
        renderCases(cases.filter(function (c) { return c.ability === "rag"; }), body);
        return;
      }
      if (id === "synth") {
        renderCases(cases.filter(function (c) { return c.ability === "synth"; }), body);
        return;
      }
      renderSamples(samples.filter(function (s) { return s.ability === id; }), body);
    }

    nav.innerHTML = TABS.map(function (t) {
      // ④⑤ 是用例（五种架构 / 综合生成各一组），不是素材，所以按 cases 计数
      const n = t.id === "cases" ? cases.length
        : (t.id === "rag" || t.id === "synth")
          ? cases.filter(function (c) { return c.ability === t.id; }).length
          : samples.filter(function (s) { return s.ability === t.id; }).length;
      return '<button class="btn btn--sm mn-navbtn" data-t="' + t.id + '">' + PF.esc(t.label) +
        " <span class='t-xs t-dim'>" + n + "</span></button>";
    }).join("");
    PF.$$("[data-t]", nav).forEach(function (b) {
      b.addEventListener("click", function () { pick(b.dataset.t); });
    });
    pick(TABS.some(function (t) { return t.id === ability; }) ? ability : "cases");
    if (!PF.reduced()) PF.reveal(body);
    return m;
  };

  /* ---------------------------------------------------------- 团队类型
     老师带的不只是科研课题组，还有横向项目、竞赛团队、实习团队，
     所以「我的团队」用一组类型做分类展示。类型**不参与匹配打分**，
     打分只看方向与名额，避免给非科研团队引入额外门槛。 */
  PF.GROUP_KINDS = ["科研课题组", "横向项目", "竞赛团队", "实习实践", "其他"];

  const KIND_TONE = {
    "科研课题组": "badge--brand",
    "横向项目": "badge--info",
    "竞赛团队": "badge--warn",
    "实习实践": "badge--ok",
    "其他": "badge--outline",
  };

  /** 团队类型徽标：空值按「科研课题组」兜底（历史数据没有类型字段） */
  PF.kindBadge = function (kind) {
    const k = String(kind || "").trim() || "科研课题组";
    return '<span class="badge ' + (KIND_TONE[k] || "badge--outline") + '">' + PF.esc(k) + "</span>";
  };

  /** 状态徽标：把任意中文状态映射到配色 */
  PF.statusBadge = function (text) {
    const t = String(text || "");
    let cls = "";
    if (/通过|已录取|已接受|已完成|已批改|已发放|已确认|开放|进行中/.test(t)) cls = "badge--ok";
    else if (/待|申请中|审核|未|缺/.test(t)) cls = "badge--warn";
    else if (/拒绝|驳回|关闭|过期|取消/.test(t)) cls = "badge--danger";
    else if (/草稿|规划/.test(t)) cls = "badge--info";
    return '<span class="badge ' + cls + '">' + PF.esc(t || "—") + "</span>";
  };

  /** 空白占位 */
  PF.empty = function (opts) {
    const o = opts || {};
    return '<div class="empty">' +
      '<div class="empty__ico">' + PF.icon(o.icon || "info", 26) + "</div>" +
      '<div class="empty__title">' + PF.esc(o.title || "暂无数据") + "</div>" +
      (o.desc ? '<div class="empty__desc">' + PF.esc(o.desc) + "</div>" : "") +
      (o.action ? '<div class="empty__actions">' + o.action + "</div>" : "") +
      "</div>";
  };

  /** 加载骨架 */
  PF.skeleton = function (lines) {
    const n = lines || 3;
    let html = '<div style="padding:24px"><div class="skeleton skeleton--title"></div>';
    for (let i = 0; i < n; i++) html += '<div class="skeleton skeleton--line"></div>';
    return html + "</div>";
  };

  PF.loading = function (text) {
    return '<div class="loading-row"><span class="spin"></span>' + PF.esc(text || "加载中") + "</div>";
  };

  /** 通用表格渲染 */
  PF.table = function (cols, rows, opts) {
    const o = opts || {};
    if (!rows || !rows.length) return PF.empty(o.empty || {});
    const head = cols.map((c) => '<th class="' + (c.cls || "") + '">' + PF.esc(c.label) + "</th>").join("");
    const body = rows.map((row) => {
      const tds = cols.map((c) => {
        const raw = typeof c.render === "function" ? c.render(row) : row[c.key];
        return '<td class="' + (c.cls || "") + '">' + (raw === null || raw === undefined ? "—" : raw) + "</td>";
      }).join("");
      const trCls = typeof o.rowClass === "function" ? ' class="' + o.rowClass(row) + '"' : "";
      const trAttr = typeof o.rowAttr === "function" ? o.rowAttr(row) : "";
      return "<tr" + trCls + " " + trAttr + ">" + tds + "</tr>";
    }).join("");
    return '<div class="table-wrap"><table class="table' + (o.fixed ? " table--fixed" : "") + '"><thead><tr>' +
      head + "</tr></thead><tbody>" + body + "</tbody></table></div>";
  };

  /** 进度条 */
  PF.progress = function (value, opts) {
    const o = opts || {};
    const v = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
    const tone = o.tone ? " progress__bar--" + o.tone : "";
    return '<div class="progress' + (o.large ? " progress--lg" : "") + '"><div class="progress__bar' +
      tone + '" style="width:' + v + '%"></div></div>';
  };

  /** 分数环（作业得分等） */
  PF.ring = function (value, total, label) {
    const t = Number(total) || 100;
    const v = Math.max(0, Math.min(t, Number(value) || 0));
    const r = 40, c = 2 * Math.PI * r;
    const off = c * (1 - v / t);
    const tone = v / t >= 0.85 ? "#2e9c6a" : v / t >= 0.7 ? "#3d7ba8" : "#c98a35";
    return '<div class="ring">' +
      '<svg width="96" height="96" viewBox="0 0 96 96">' +
        '<circle class="ring__track" cx="48" cy="48" r="' + r + '"/>' +
        '<circle class="ring__fill" cx="48" cy="48" r="' + r + '" stroke="' + tone + '" ' +
          'stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '"/>' +
      "</svg>" +
      '<div class="ring__val">' + PF.num(v, 0) +
        '<span class="t-xs" style="font-weight:500">/' + PF.num(t, 0) + "</span></div>" +
      (label ? '<div class="t-xs t-center" style="margin-top:2px">' + PF.esc(label) + "</div>" : "") +
      "</div>";
  };

  /**
   * 雷达图（能力画像）：零依赖，纯 SVG。
   * items: [{ name, value }]（至少 3 项）；opts: { max, r, levels, label, emptyText }
   */
  var _radarSeq = 0;
  PF.radar = function (items, opts) {
    const o = opts || {};
    const max = Number(o.max) || 5;
    const list = PF.arr(items).map(function (a) {
      const v = Number(a && a.value);
      return { name: String((a && a.name) || "").trim(), value: isFinite(v) && v > 0 ? v : 0 };
    }).filter(function (a) { return a.name; });
    if (list.length < 3) {
      return '<div class="t-sm t-dim t-center">' +
        PF.esc(o.emptyText || "维度不足，暂无法绘制雷达图") + "</div>";
    }
    const n = list.length;
    const levels = o.levels || 4;
    const W = 300, H = 250, cx = 150, cy = 118, R = Number(o.r) || 78;
    const uid = "pfradar" + (++_radarSeq);
    const ang = function (i) { return -Math.PI / 2 + (Math.PI * 2 * i) / n; };
    const px = function (i, k) { return cx + Math.cos(ang(i)) * R * k; };
    const py = function (i, k) { return cy + Math.sin(ang(i)) * R * k; };
    const clamp = function (v) { return Math.max(0.02, Math.min(1, v / max)); };
    const poly = function (k) {
      const pts = [];
      for (let i = 0; i < n; i++) pts.push(px(i, k).toFixed(1) + "," + py(i, k).toFixed(1));
      return pts.join(" ");
    };

    let rings = "";
    for (let L = levels; L >= 1; L--) {
      const k = L / levels;
      rings += '<polygon class="radar__ring' + (L === levels ? " radar__ring--outer" : "") +
        '" points="' + poly(k) + '"/>';
    }
    let spokes = "", dots = "", labels = "", area = [];
    for (let i = 0; i < n; i++) {
      spokes += '<line class="radar__spoke" x1="' + cx + '" y1="' + cy +
        '" x2="' + px(i, 1).toFixed(1) + '" y2="' + py(i, 1).toFixed(1) + '"/>';
      const k = clamp(list[i].value);
      dots += '<circle class="radar__dot" cx="' + px(i, k).toFixed(1) + '" cy="' + py(i, k).toFixed(1) +
        '" r="3.6"><title>' + PF.esc(list[i].name + " " + PF.num(list[i].value, 1) +
        " / " + PF.num(max, 0)) + "</title></circle>";
      area.push(px(i, k).toFixed(1) + "," + py(i, k).toFixed(1));

      const cos = Math.cos(ang(i)), sin = Math.sin(ang(i));
      const anchor = Math.abs(cos) < 0.25 ? "middle" : cos > 0 ? "start" : "end";
      const lx = cx + cos * (R + 14), ly = cy + sin * (R + 14);
      const shift = sin < -0.6 ? -4 : sin > 0.6 ? 8 : 0;
      labels += '<text class="radar__label" x="' + lx.toFixed(1) + '" y="' + (ly + shift).toFixed(1) +
        '" text-anchor="' + anchor + '">' + PF.esc(list[i].name) + "</text>" +
        '<text class="radar__val" x="' + lx.toFixed(1) + '" y="' + (ly + shift + 13).toFixed(1) +
        '" text-anchor="' + anchor + '">' + PF.num(list[i].value, 1) + "</text>";
    }

    return '<div class="radar-wrap">' +
      '<svg class="radar" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' +
        PF.esc(o.label || "能力雷达图") + '">' +
        "<defs><linearGradient id=\"" + uid + '" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0" style="stop-color:var(--brand-400);stop-opacity:.58"/>' +
          '<stop offset="1" style="stop-color:var(--brand-600);stop-opacity:.16"/>' +
        "</linearGradient></defs>" +
        '<g class="radar__rings">' + rings + "</g>" +
        '<g class="radar__spokes">' + spokes + "</g>" +
        '<polygon class="radar__area" points="' + area.join(" ") + '" style="fill:url(#' + uid + ')"/>' +
        '<g class="radar__dots">' + dots + "</g>" +
        '<g class="radar__labels">' + labels + "</g>" +
      "</svg></div>";
  };

  /** 雷达图旁的「优势 / 待提升」小结 */
  PF.radarTips = function (items) {
    const list = PF.arr(items).filter(function (a) { return a && a.name; })
      .map(function (a) { return { name: String(a.name), value: Number(a.value) || 0 }; });
    if (list.length < 2) return "";
    const sorted = list.slice().sort(function (a, b) { return b.value - a.value; });
    const best = sorted[0], weak = sorted[sorted.length - 1];
    return '<div class="radar-tips">' +
      '<span class="chip chip--ok">' + PF.icon("award", 11) +
        "优势 " + PF.esc(best.name) + " " + PF.num(best.value, 1) + "</span>" +
      (weak.name !== best.name
        ? '<span class="chip chip--warn">' + PF.icon("target", 11) +
          "待提升 " + PF.esc(weak.name) + " " + PF.num(weak.value, 1) + "</span>"
        : "") +
      "</div>";
  };

  /** 表单取值助手 */
  PF.form = function (root) {
    const out = {};
    PF.$$("[name]", root).forEach((el) => {
      const k = el.getAttribute("name");
      if (!k) return;
      if (el.type === "checkbox") {
        if (el.dataset.multi !== undefined) {
          out[k] = out[k] || [];
          if (el.checked) out[k].push(el.value);
        } else {
          out[k] = el.checked;
        }
      } else if (el.type === "radio") {
        if (el.checked) out[k] = el.value;
      } else if (el.type === "number" || el.type === "range") {
        out[k] = el.value === "" ? null : Number(el.value);
      } else {
        out[k] = el.value;
      }
    });
    return out;
  };

  /** 按钮加载态开关 */
  PF.busy = function (btn, on, labelWhenBusy) {
    if (!btn) return;
    if (on) {
      if (!btn.dataset.origin) btn.dataset.origin = btn.innerHTML;
      btn.classList.add("is-loading");
      btn.innerHTML = '<span class="spin"></span>' + PF.esc(labelWhenBusy || "处理中");
    } else {
      btn.classList.remove("is-loading");
      if (btn.dataset.origin) { btn.innerHTML = btn.dataset.origin; delete btn.dataset.origin; }
    }
  };

  /** 防抖 */
  PF.debounce = function (fn, wait) {
    let timer = null;
    return function () {
      const args = arguments, self = this;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(self, args), wait || 260);
    };
  };

  /* ============================================================ 动效层
     设计约束（写在最前面，改这里之前先读）：
       1. 只动 opacity 与 transform，不碰 width/height/margin 等布局属性；
       2. 时长封顶 400ms，缓动一律 ease-out（快起慢收）；
       3. 尊重 prefers-reduced-motion —— 命中时整个动效层直接不启动，
          元素保持样式表里的最终状态，功能一个不少；
       4. 元素默认是"可见"的，动画只是在 JS 参与时额外加的入场效果。
          也就是说 JS 挂了页面照样能看，不会白屏。
     ============================================================ */

  /** 是否处于"减少动效"偏好。为 true 时全站不做任何入场/增长动画。 */
  PF.reduced = function () {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  };

  /* 会被错峰淡入的元素。宁可少列几种，也不要让满屏都在动。 */
  const REVEAL_SEL = [
    ".card", ".stat", ".list__item", ".empty", ".note", ".suggest-box",
    ".kp", ".hit", ".slide-card", ".seg", ".matrix__cell", ".check-item",
    ".mk-card", ".res-card", ".hub-card", ".hw-card", ".hw-item", ".pick",
    ".ref", ".ref-item", ".msg", ".file-pill", ".demo-card", ".mini-student",
    ".timeline__item", ".thumb",
  ].join(",");

  /* 需要"从 0 长出来"的进度类元素 */
  const GROW_W = ".progress__bar, .dist-bar > span, .bar-mini > span";
  const GROW_H = ".bars__fill";
  const GROW_RING = ".ring__fill";
  /* 需要数字滚动的元素 */
  const COUNT_SEL = ".stat__num, .mk-score__n, .ring__val, .res-stat b";

  /** 一个元素上最多排到第几号（后面的不再增加延迟，避免总时长失控） */
  const MAX_STAGGER = 30;

  /**
   * 数字平滑递增。只改文本节点的值、不动 DOM 结构，因此不触发重排。
   * 能安全处理 "12 人"（数字 + 后置元素）、"3.52"、"86%" 这类结构。
   */
  function countUp(el) {
    if (el.dataset.pfCounted) return;
    const node = el.firstChild;
    if (!node || node.nodeType !== 3) return;
    const raw = node.nodeValue;
    const m = /^(\s*)(\d+(?:\.\d+)?)/.exec(raw);
    if (!m) return;
    const target = parseFloat(m[2]);
    if (!isFinite(target) || target <= 0) return;
    const digits = (m[2].split(".")[1] || "").length;
    const head = m[1];
    const tail = raw.slice(m[0].length);
    el.dataset.pfCounted = "1";
    el.classList.add("is-counting");

    const dur = 620;
    const t0 = performance.now();
    requestAnimationFrame(function frame(now) {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      node.nodeValue = head + (target * eased).toFixed(digits) + tail;
      if (p < 1) { requestAnimationFrame(frame); return; }
      node.nodeValue = raw;              // 收尾一定回到原值，不留浮点残差
      el.classList.remove("is-counting");
    });
  }

  /**
   * 进度条 / 柱状图 / 分数环从 0 长到目标值。
   * 用"写起始值 → 连等两帧 → 写目标值"的顺序触发 CSS transition：
   * 只等一帧的话，起始值还没来得及被浏览器采信就又被覆盖，transition 不会触发。
   * 刻意不用 offsetWidth 强制同步布局 —— 那个写法在几十个条同时渲染时会明显掉帧。
   */
  function growBars(scope) {
    PF.$$(GROW_W, scope).forEach(function (el) {
      if (el.dataset.pfGrown || !el.style.width) return;
      el.dataset.pfGrown = "1";
      const target = el.style.width;
      el.style.width = "0%";
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { el.style.width = target; });
      });
    });

    PF.$$(GROW_H, scope).forEach(function (el) {
      if (el.dataset.pfGrown || !el.style.height) return;
      el.dataset.pfGrown = "1";
      const target = el.style.height;
      el.style.height = "0%";
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { el.style.height = target; });
      });
    });

    PF.$$(GROW_RING, scope).forEach(function (el) {
      const off = el.getAttribute("stroke-dashoffset");
      if (el.dataset.pfGrown || off === null) return;
      el.dataset.pfGrown = "1";
      // 属性优先级低于行内样式，所以先摘掉属性、改走 style，transition 才生效
      const total = parseFloat(el.getAttribute("stroke-dasharray")) || 0;
      el.removeAttribute("stroke-dashoffset");
      el.style.strokeDashoffset = total + "px";
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { el.style.strokeDashoffset = off + "px"; });
      });
    });
  }

  /**
   * 扫描一个子树，给其中新出现的元素挂上入场动画并启动进度/数字动效。
   * @param {Element} node 新增的节点（它自身也可能是候选）
   * @param {number}  seq  已排到的错峰序号，返回推进后的值
   */
  function scan(node, seq) {
    if (!node || node.nodeType !== 1 || !node.isConnected) return seq;

    const all = [];
    if (node.matches && node.matches(REVEAL_SEL)) all.push(node);
    PF.$$(REVEAL_SEL, node).forEach(function (el) { all.push(el); });

    // 先读后写：可见性判定全部做完再改 class，避免读写交替触发多次同步布局
    const todo = all.filter(function (el) { return !el.dataset.pfIn; });
    const shown = todo.filter(function (el) { return el.getClientRects().length > 0; });
    const stagger = shown.length > 24 ? "10ms" : "34ms";
    let n = seq;
    shown.forEach(function (el) {
      el.dataset.pfIn = "1";
      el.style.setProperty("--i", Math.min(n, MAX_STAGGER));
      el.style.setProperty("--stagger", stagger);
      el.classList.add("anim-in");
      n++;
    });

    growBars(node);
    PF.$$(COUNT_SEL, node).forEach(countUp);
    if (node.matches && node.matches(COUNT_SEL)) countUp(node);
    return n;
  }

  /* 把 MutationObserver 的多次回调合并到一帧里处理 */
  let pendingNodes = [];
  let pendingFrame = 0;
  function flushPending() {
    pendingFrame = 0;
    const batch = pendingNodes;
    pendingNodes = [];
    let seq = 0;
    batch.forEach(function (node) { seq = scan(node, seq); });
  }
  function collect(node) {
    if (!node || node.nodeType !== 1) return;
    pendingNodes.push(node);
    if (!pendingFrame) pendingFrame = requestAnimationFrame(flushPending);
  }

  let mo = null;
  function installObserver() {
    if (mo || !document.body || PF.reduced()) return;
    if (typeof MutationObserver !== "function") return;
    mo = new MutationObserver(function (records) {
      for (let i = 0; i < records.length; i++) {
        const added = records[i].addedNodes;
        for (let j = 0; j < added.length; j++) collect(added[j]);
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  /**
   * 手动触发一次动效扫描（一般不用调 —— 观察器会自动处理动态渲染的内容）。
   * @param {Element} [scope] 默认整页
   */
  PF.reveal = function (scope) {
    const root = scope || document.body;
    if (!root || PF.reduced()) return;
    scan(root, 0);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installObserver);
  } else {
    installObserver();
  }

  /* ============================================================ 主题
     明暗主题的唯一切换入口。CSS 那边只有一个开关 html[data-theme="dark"]，
     这里负责三件事：读初值、写回 localStorage、跟随系统偏好。

     为什么初值不在这里定：本文件在各页 <body> 顶部加载，而登录页在它之前就有
     静态 DOM，等到这里再定性会先亮一帧白。所以各页 <head> 里有一小段引导脚本
     抢在首帧前把 data-theme 写好，这里只做兜底与后续交互。 */
  PF.theme = (function () {
    const KEY = "pf_theme";
    const root = document.documentElement;
    const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

    function stored() {
      try {
        const v = localStorage.getItem(KEY);
        return v === "dark" || v === "light" ? v : null;
      } catch (e) { return null; }
    }
    function system() { return mq && mq.matches ? "dark" : "light"; }
    function current() { return root.getAttribute("data-theme") === "dark" ? "dark" : "light"; }

    /** 把当前主题同步到顶栏按钮（图标 / aria / title）。按钮可能还没渲染，允许空跑。 */
    function sync() {
      const btn = document.getElementById("pf-theme");
      if (!btn) return;
      const dark = current() === "dark";
      btn.innerHTML = PF.icon(dark ? "sun" : "moon", 17);
      const label = dark ? "切换到浅色模式" : "切换到深色模式";
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
    }

    function apply(t, persist) {
      root.setAttribute("data-theme", t);
      if (persist) { try { localStorage.setItem(KEY, t); } catch (e) { /* 隐私模式下写不进去，忽略 */ } }
      sync();
    }

    function toggle() { apply(current() === "dark" ? "light" : "dark", true); }

    function init() {
      // 兜底：引导脚本被 CSP 拦掉、或 localStorage 不可用时，至少别缺主题属性
      if (root.getAttribute("data-theme") !== "dark" && root.getAttribute("data-theme") !== "light") {
        apply(stored() || system(), false);
      }
      if (mq) {
        // 只有"用户从没手动选过"才跟随系统变化，否则手动选择会被系统偏好顶掉
        const onChange = function () { if (!stored()) apply(system(), false); };
        if (mq.addEventListener) mq.addEventListener("change", onChange);
        else if (mq.addListener) mq.addListener(onChange);
      }
      sync();
    }

    return {
      KEY: KEY,
      init: init,
      sync: sync,
      toggle: toggle,
      current: current,
      system: system,
      set: function (t) { apply(t, true); },
      reset: function () {
        try { localStorage.removeItem(KEY); } catch (e) { /* 同上 */ }
        apply(system(), false);
      },
      icon: function () { return PF.icon(current() === "dark" ? "sun" : "moon", 17); },
    };
  })();
  PF.theme.init();

  /* ============================================================ 导航外壳 */
  const NAV = {
    teacher: [
      { group: "教学", items: [
        { key: "teacher", href: "/teacher", label: "驾驶舱", icon: "grid" },
        { key: "teach", href: "/teach", label: "备课助手", icon: "presentation" },
        { key: "grade", href: "/grade", label: "批改中心", icon: "clipboard" },
        { key: "tutor", href: "/tutor", label: "教师 Copilot", icon: "sparkles" },
      ]},
      { group: "事务", items: [
        { key: "homework", href: "/homework", label: "作业管理", icon: "file" },
        { key: "resources", href: "/resources", label: "资源管理", icon: "folder" },
        { key: "match", href: "/match", label: "师生匹配", icon: "users" },
        { key: "library", href: "/library", label: "资料与知识库", icon: "layers" },
      ]},
      { group: "账号", items: [
        { key: "profile", href: "/profile", label: "个人中心", icon: "user" },
      ]},
    ],
    student: [
      { group: "我的成长", items: [
        { key: "student", href: "/student", label: "我的画像", icon: "compass" },
        { key: "ask", href: "/ask", label: "分层答疑", icon: "message" },
        { key: "match", href: "/match", label: "团队匹配", icon: "users" },
      ]},
      { group: "学习事务", items: [
        { key: "homework", href: "/homework", label: "我的作业", icon: "file" },
        { key: "hub", href: "/hub", label: "资源广场", icon: "briefcase" },
        { key: "library", href: "/library", label: "我的资料库", icon: "layers" },
      ]},
      { group: "账号", items: [
        { key: "profile", href: "/profile", label: "个人中心", icon: "user" },
      ]},
    ],
  };

  function navHtml(role, active) {
    const groups = NAV[role] || NAV.student;
    return groups.map((g) => {
      const items = g.items.map((it) => {
        const on = it.key === active;
        return '<a class="nav-item' + (on ? " is-active" : "") + '" href="' + it.href + '"' +
          (on ? ' aria-current="page"' : "") + ">" +
          PF.icon(it.icon, 17) + "<span>" + PF.esc(it.label) + "</span>" +
          (it.tag ? '<span class="nav-item__tag">' + PF.esc(it.tag) + "</span>" : "") +
          "</a>";
      }).join("");
      return '<div class="nav-group"><div class="nav-group__title">' + PF.esc(g.group) + "</div>" + items + "</div>";
    }).join("");
  }

  /**
   * 构建整站外壳（侧边栏 + 顶栏 + 内容区），返回内容挂载点。
   * @param {object} cfg { active, title, desc, actions, narrow, wide, me }
   * @returns {HTMLElement} 内容挂载点 #view
   */
  PF.shell = function (cfg) {
    const c = cfg || {};
    const me = c.me || PF.state.me || {};
    const role = me.role || "student";
    const roleName = role === "teacher" ? "教师" : "学生";
    const root = PF.$("#app") || document.body;
    const widthCls = c.narrow ? " content--narrow" : c.wide ? " content--wide" : "";

    root.innerHTML =
      '<a class="skip-link" href="#pf-main">跳到主要内容</a>' +
      '<div class="shell">' +
        '<aside class="sidebar">' +
          '<div class="sidebar__brand">' +
            '<div class="sidebar__mark">' + PF.icon("compass", 18) + "</div>" +
            "<div><div class=\"sidebar__name\">寻径教育</div>" +
            '<div class="sidebar__sub">PathFinder</div></div>' +
          "</div>" +
          '<nav class="sidebar__scroll" aria-label="主导航">' + navHtml(role, c.active) + "</nav>" +
          '<div class="sidebar__foot">' +
          '<div class="sidebar__user">' +
            '<a class="sidebar__user-main" href="/profile" title="个人中心">' +
              '<div class="sidebar__avatar" aria-hidden="true">' + PF.esc(PF.initial(me.name)) + "</div>" +
              '<div class="flex-1"><div class="sidebar__uname">' + PF.esc(me.name || me.username || "未登录") + "</div>" +
              '<div class="sidebar__urole">' + roleName + " · " + PF.esc(me.username || "") + "</div></div>" +
            "</a>" +
            '<button class="btn--ghost" type="button" id="pf-logout" title="退出登录" aria-label="退出登录" ' +
                'style="color:var(--ink-400);padding:6px;border-radius:6px">' + PF.icon("logout", 15) + "</button>" +
            "</div>" +
          "</div>" +
        "</aside>" +
        '<div class="main">' +
          '<header class="topbar">' +
            '<button class="btn--ghost nav-toggle" type="button" id="pf-nav-toggle" ' +
              'aria-label="展开导航" aria-controls="pf-main" aria-expanded="false">' + PF.icon("menu", 18) + "</button>" +
            // 页面标题只保留 page-head 一处：顶栏再放一遍就是两个相同的标题。
            '<div class="topbar__spacer"></div>' +
            '<button class="theme-toggle" type="button" id="pf-theme"></button>' +
            '<button class="topbar__user" type="button" id="pf-user" title="个人中心" aria-label="个人中心">' +
              PF.icon("user", 17) + "</button>" +
            '<span class="badge badge--brand">' + PF.icon(role === "teacher" ? "book" : "compass", 11) + roleName + "端</span>" +
            '<span id="pf-engine"></span>' +
          "</header>" +
          '<main class="content' + widthCls + '" id="pf-main" tabindex="-1">' +
            (c.title ? '<div class="page-head">' +
              '<div class="page-head__main">' +
                '<h1 class="page-head__title">' + PF.esc(c.title) + "</h1>" +
                (c.desc ? '<p class="page-head__desc">' + PF.esc(c.desc) + "</p>" : "") +
              "</div>" +
              (c.actions ? '<div class="page-head__actions">' + c.actions + "</div>" : "") +
            "</div>" : "") +
            '<div id="view"></div>' +
          "</main>" +
        "</div>" +
      "</div>";

    // 页面标题区淡入：外壳是静态的，只有这块每次加载都是"新内容"
    if (!PF.reduced()) {
      const ph = PF.$(".page-head", root);
      if (ph) ph.classList.add("anim-in");
    }

    /* 导航滑块（v2.2）：把本页选中项的位置记进 sessionStorage；
       若上一页选中项在同一角色的菜单里且位置不同，就创建一块
       .nav-glider 底光，从旧位置滑到当前项 —— 多页应用里最接近
       单页应用"滑动指示器"的做法。滑完即删，落点样式与
       .is-active 常态一致，不会有二次跳变。 */
    if (!PF.reduced()) {
      const navScroll = PF.$(".sidebar__scroll", root);
      const cur = navScroll ? navScroll.querySelector(".nav-item.is-active") : null;
      if (cur) {
        let prev = null;
        try { prev = JSON.parse(sessionStorage.getItem("pf.nav") || "null"); } catch (e) { prev = null; }
        try { sessionStorage.setItem("pf.nav", JSON.stringify({ role: role, top: cur.offsetTop })); } catch (e) {}
        if (prev && prev.role === role && typeof prev.top === "number" &&
            Math.abs(prev.top - cur.offsetTop) > 1) {
          const sidebar = PF.$(".sidebar", root);
          const glider = document.createElement("div");
          glider.className = "nav-glider";
          glider.style.top = prev.top + "px";
          glider.style.left = cur.offsetLeft + "px";
          glider.style.width = cur.offsetWidth + "px";
          glider.style.height = cur.offsetHeight + "px";
          navScroll.appendChild(glider);
          sidebar.classList.add("has-glider");
          // 双 rAF 确保起始位置先提交渲染，再改 top 触发过渡
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              glider.style.top = cur.offsetTop + "px";
            });
          });
          const glideClean = function () {
            if (!glider.parentNode) return;
            glider.remove();
            sidebar.classList.remove("has-glider");
          };
          glider.addEventListener("transitionend", function (e) {
            if (e.target === glider && e.propertyName === "top") glideClean();
          });
          // 兜底：transitionend 偶发不触发（切后台等），超时强制复位
          setTimeout(glideClean, 1200);
        }
      }
    }

    PF.$("#pf-logout").addEventListener("click", async () => {
      const yes = await PF.confirm({ title: "退出登录", text: "确定要退出当前账号吗？", okText: "退出" });
      if (!yes) return;
      await PF.try(() => PF.post("/api/auth/logout"));
      localStorage.removeItem("pf_token");
      window.location.href = "/login";
    });

    // 主题切换：图标与 aria 由 PF.theme.sync 统一维护，这里只负责把点击接上去
    PF.theme.sync();
    const themeBtn = PF.$("#pf-theme");
    if (themeBtn) themeBtn.addEventListener("click", PF.theme.toggle);

    // 顶栏头像 → 个人中心（侧栏底部用户块也是同一个入口）
    const userBtn = PF.$("#pf-user", root);
    if (userBtn) userBtn.addEventListener("click", () => { window.location.href = "/profile"; });

    /* 移动端贴底操作条（拇指可达性）
       只有显式声明 dock:true 的页面才把页头主操作搬到屏幕底部。
       之所以按视口开关 class 而不是纯 CSS 媒体查询：挂载点就是 .page-head__actions
       本身，桌面端它必须留在页头流内，两套定位没法用同一条媒体查询切换。 */
    const actionsEl = PF.$(".page-head__actions", root);
    if (c.dock && actionsEl && window.matchMedia) {
      const mq = window.matchMedia("(max-width: 620px)");
      const syncDock = function () {
        actionsEl.classList.toggle("fab-bar", mq.matches);
        document.body.classList.toggle("has-dock", mq.matches);
      };
      syncDock();
      if (mq.addEventListener) mq.addEventListener("change", syncDock);
      else if (mq.addListener) mq.addListener(syncDock);
    }

    const toggle = PF.$("#pf-nav-toggle");
    function setNav(open) {
      document.body.classList.toggle("nav-open", open);
      if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    if (toggle) toggle.addEventListener("click", () => setNav(!document.body.classList.contains("nav-open")));
    PF.$$(".nav-item").forEach((a) => a.addEventListener("click", () => setNav(false)));

    // 点空白处或按 Esc 关掉移动端抽屉 —— 只点按钮关不了会很难用
    document.addEventListener("click", (e) => {
      if (!document.body.classList.contains("nav-open")) return;
      if (toggle && toggle.contains(e.target)) return;
      const bar = PF.$(".sidebar");
      if (bar && bar.contains(e.target)) return;
      setNav(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && document.body.classList.contains("nav-open")) setNav(false);
    });

    // 顶栏引擎状态：让"现在是 AI 还是规则"始终可见
    const engineSlot = PF.$("#pf-engine");
    if (engineSlot) {
      PF.try(() => PF.get("/api/health", { quiet: true })).then((health) => {
        if (!health) { engineSlot.innerHTML = ""; return; }
        const llm = health.llm || {};
        const mode = llm.api_ready ? "真实模型" : "规则版";
        const cls = llm.api_ready ? "badge--ok" : "badge--info";
        engineSlot.innerHTML = '<span class="badge ' + cls + '" title="' +
          PF.esc(llm.api_ready ? ("模型：" + llm.model) : "未配置 API Key，全程规则生成（断网可完整演示）") +
          '">' + PF.icon("activity", 11) + PF.esc(mode) + "</span>";
      });
    }
    return PF.$("#view");
  };

  /** 拉取当前用户；未登录返回 null */
  PF.me = async function (force) {
    if (PF.state.me && !force) return PF.state.me;
    try {
      const me = await PF.get("/api/auth/me", { quiet: true });
      PF.state.me = me;
      return me;
    } catch (e) {
      return null;
    }
  };

  /**
   * 页面守卫：未登录跳登录页；角色不符跳自己的首页。
   * @param {"teacher"|"student"|""} role 需要的角色，空串表示登录即可
   */
  PF.requireAuth = async function (role) {
    const me = await PF.me();
    if (!me) {
      const next = encodeURIComponent(location.pathname + location.search);
      window.location.replace("/login?next=" + next);
      return null;
    }
    if (role && me.role !== role) {
      PF.toast("当前账号无权访问该页面，已跳转到你的首页", "warn");
      setTimeout(() => { window.location.replace(me.role === "teacher" ? "/teacher" : "/student"); }, 800);
      return null;
    }
    return me;
  };

  /** 站点元数据（学科方向、资源类型、口径说明等），进程内缓存 */
  PF.meta = async function () {
    if (PF.state.meta) return PF.state.meta;
    const meta = await PF.try(() => PF.get("/api/meta", { quiet: true }), null);
    if (meta) PF.state.meta = meta;
    return meta;
  };

  /** 把 select 填充为 options（value/label 由 pick 指定） */
  PF.fillSelect = function (el, items, opts) {
    const o = opts || {};
    const list = PF.arr(items);
    el.innerHTML = (o.placeholder ? '<option value="">' + PF.esc(o.placeholder) + "</option>" : "") +
      list.map((it) => {
        const v = typeof it === "string" ? it : (it[o.valueKey || "value"] !== undefined ? it[o.valueKey || "value"] : it.value);
        const l = typeof it === "string" ? it : (it[o.labelKey || "label"] !== undefined ? it[o.labelKey || "label"] : it.label);
        return '<option value="' + PF.esc(v) + '">' + PF.esc(l) + "</option>";
      }).join("");
    if (o.selected !== undefined) el.value = o.selected;
    return el;
  };

  /** 口径提示条：分层免责说明等，全站统一文案入口 */
  PF.caveat = function (text, tone) {
    return '<div class="note' + (tone ? " note--" + tone : "") + '">' + PF.icon(tone === "warn" ? "alert" : "info", 15) +
      "<div>" + PF.esc(text) + "</div></div>";
  };

  /** 从检索命中里高亮查询词 */
  PF.highlight = function (text, terms) {
    let html = PF.esc(text);
    PF.arr(terms).filter(Boolean).slice(0, 6).forEach((t) => {
      const safe = PF.esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (!safe) return;
      html = html.replace(new RegExp(safe, "g"), (m) => "<mark>" + m + "</mark>");
    });
    return html;
  };

  /** 折线/条形迷你图：把 [{label,value}] 渲染成 .bars */
  PF.bars = function (items, opts) {
    const o = opts || {};
    const list = PF.arr(items);
    const max = Math.max.apply(null, list.map((d) => Number(d.value) || 0).concat([1]));
    return '<div class="bars">' + list.map((d) => {
      const h = Math.max(3, Math.round((Number(d.value) || 0) / max * 100));
      const color = o.color ? "background:" + o.color + ";" : "";
      return '<div class="bars__item" title="' + PF.esc(d.label + "：" + d.value) + '">' +
        '<div class="bars__fill" style="height:' + h + "%;" + color + '"></div></div>';
    }).join("") + "</div>";
  };

  window.PF = PF;
})();
