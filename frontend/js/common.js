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

  /** 打开资料库里的文件本体（一键备课生成的 PPT 就存在「课件」分类下）。
   *  走 fetch 而不是裸链接，是为了带上 Bearer 头；浏览器拿到 pptx 会交给本机
   *  PowerPoint / WPS 打开，效果与双击文件一样。 */
  PF.openMaterial = function (materialId, filename) {
    PF.download("/api/materials/" + materialId + "/download", filename || "");
  };

  /** 课件预览：把 pptx 读回「文字骨架」，在弹窗里按页翻，不必先下载再开 PowerPoint。
   *  还原的是标题 / 要点 / 授课备注（与生成时的版式一致），真要放映再点「用本机打开」。
   *  键盘 ← → 翻页，Esc 关闭。 */
  PF.previewMaterial = async function (materialId, filename) {
    let data = null;
    try {
      data = await PF.get("/api/materials/" + materialId + "/preview");
    } catch (e) {
      return;                     // PF.get 已经统一提示过了
    }
    const pages = (data && data.pages) || [];
    if (!pages.length) { PF.toast("这份课件没有可预览的页面", "warn"); return; }
    const name = filename || (data && data.filename) || "课件预览";
    const total = pages.length;
    let idx = 0;

    function slideHtml(p, i) {
      const pts = (p.bullets || []).map(function (b) {
        return "<li>" + PF.esc(b) + "</li>";
      }).join("");
      return '<div class="pv__slide">' +
          '<div class="pv__tag">第 ' + (i + 1) + " 页 / 共 " + total + " 页</div>" +
          '<div class="pv__t">' + PF.esc(p.title || "（本页无文字）") + "</div>" +
          (pts ? '<ul class="pv__pts">' + pts + "</ul>" : "") +
          (p.note
            ? '<div class="pv__note"><b>授课备注</b><div>' + PF.esc(p.note) + "</div></div>"
            : "") +
          '<div class="pv__foot"><span>寻径教育 PathFinder</span><span>' +
            (i + 1) + " / " + total + "</span></div>" +
        "</div>";
    }

    const m = PF.modal({
      title: "课件预览 · " + name,
      width: "wide",
      body: '<div class="pv">' +
          '<div class="pv__meta">' + PF.esc((data && data.category) || "课件") +
            " · " + PF.esc(name) + " · " + total + " 页</div>" +
          '<div class="pv__stage" data-role="stage"></div>' +
          '<div class="pv__nav">' +
            '<button class="btn btn--sm" type="button" data-pv="prev">' +
              PF.icon("chevronLeft", 14) + " 上一页</button>" +
            '<div class="pv__dots" data-role="dots"></div>' +
            '<button class="btn btn--sm" type="button" data-pv="next">下一页 ' +
              PF.icon("chevronRight", 14) + "</button>" +
          "</div>" +
        "</div>",
      actions: [
        { label: "用本机打开", type: "primary", onClick: function () {
            PF.openMaterial(materialId, name);
          } },
        { label: "关闭", onClick: function () { /* 交给 modal 自己关 */ } },
      ],
      onClose: function () { document.removeEventListener("keydown", onKey); },
    });

    const stage = PF.$('[data-role="stage"]', m.body);
    const dots = PF.$('[data-role="dots"]', m.body);
    function render() {
      stage.innerHTML = slideHtml(pages[idx], idx);
      if (total <= 12) {
        dots.innerHTML = pages.map(function (_, i) {
          return '<button class="pv__dot' + (i === idx ? " is-on" : "") + '" type="button" ' +
            'data-pv="go" data-i="' + i + '" aria-label="第 ' + (i + 1) + ' 页"></button>';
        }).join("");
      }
      PF.$('[data-pv="prev"]', m.body).disabled = idx === 0;
      PF.$('[data-pv="next"]', m.body).disabled = idx === total - 1;
    }
    function go(delta) {
      const n = idx + delta;
      if (n < 0 || n >= total) return;
      idx = n;
      render();
    }
    m.body.addEventListener("click", function (e) {
      const b = e.target.closest("[data-pv]");
      if (!b) return;
      if (b.dataset.pv === "prev") go(-1);
      else if (b.dataset.pv === "next") go(1);
      else if (b.dataset.pv === "go") { idx = Number(b.dataset.i) || 0; render(); }
    });
    function onKey(e) {
      if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    }
    document.addEventListener("keydown", onKey);
    render();
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
      return '<button class="mn-navbtn" data-ch="' + PF.esc(c.id) + '">' +
        PF.esc(c.title) + "</button>";
    }).join("") + '<button class="mn-navbtn" data-ch="api">开发者接口清单</button>';

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

  /* ---------------------------------------------------------- Copilot 演示例子
     两个**写死**的多模态用例，覆盖评分要求的三大能力：
     ①图文素材智能解析 ②知识点结构化抽取 ③交互式答疑 + 存入资料库。
     结果写死是为了断网也能稳定演示；最后「存成笔记」那一步是真接口
     （POST /api/materials/note，存完进「我的资料库」并可被后续提问检索）。 */
  PF.COPILOT_DEMOS = {
    text: {
      key: "text",
      icon: "file",
      kind: "文本",
      course: "线性代数",
      material: "线性代数-第3章-矩阵.md",
      materialMeta: "文本素材 · 1.8 KB",
      excerpt: "3.4 矩阵的秩：对 A 作初等行变换化成行阶梯形，非零行的数目就是 rank(A)……",
      prompt: "整理当前的知识点",
      lead: "读完了。这份《线性代数-第3章-矩阵.md》按「概念 → 运算 → 性质 → 判定 → 应用」整理成 8 个知识点，深度按你当前的层次（B：讲清定义与典型例题，不展开证明）：",
      points: [
        ["矩阵的定义与记法", "m×n 个数排成的矩形数表，记 A=(a_ij)。行数与列数相等时叫方阵。"],
        ["矩阵的线性运算", "加法要求同型，数乘逐元素进行；满足交换律、结合律与分配律。"],
        ["矩阵乘法", "C=AB 要求 A 的列数等于 B 的行数，c_ij = Σ a_ik·b_kj。注意 AB ≠ BA，但结合律与分配律仍成立。"],
        ["转置与对称矩阵", "(AB)^T = B^T·A^T；若 A^T = A，称 A 为对称矩阵。"],
        ["矩阵的秩", "初等行变换不改变秩；rank(A) ≤ min(m,n)；秩 = 非零子式的最高阶数 = 行向量组极大无关组的大小。"],
        ["可逆矩阵", "|A| ≠ 0 ⟺ A 可逆 ⟺ rank(A)=n ⟺ 行向量组线性无关；A⁻¹ = A*/|A|。"],
        ["初等变换与初等矩阵", "一次初等行变换等价于左乘一个初等矩阵；(A|E) → (E|A⁻¹) 可以顺手把逆求出来。"],
        ["分块矩阵", "同结构分块后可整体参与运算；diag(A,B) 的秩 = rank(A)+rank(B)。"],
      ],
      remind: "AB = O 推不出 A=O 或 B=O；由 AB=AC 且 A≠O 也推不出 B=C（除非 A 可逆）。",
      next: "建议先做 5 道「初等行变换求秩」的小题，再进第 4 章线性方程组。",
      note: {
        title: "线性代数 · 第3章 矩阵知识点整理",
        body: "线性代数 · 第3章 矩阵 —— 知识点整理\n\n来源：Copilot 解析《线性代数-第3章-矩阵.md》，结合李文博老师《线性代数（2026 春）》课件。\n\n1. 矩阵的定义与记法：m×n 个数排成的矩形数表，行数=列数为方阵。\n2. 矩阵的线性运算：加法要求同型，数乘逐元素，满足交换、结合、分配律。\n3. 矩阵乘法：c_ij = Σ a_ik·b_kj；AB 不等于 BA，但结合律与分配律成立。\n4. 转置与对称矩阵：(AB)^T = B^T·A^T；A^T = A 为对称矩阵。\n5. 矩阵的秩：初等行变换不改变秩，行阶梯形非零行数即 rank(A)。\n6. 可逆矩阵：|A| 不等于 0 当且仅当 A 可逆，A⁻¹ = A*/|A|。\n7. 初等变换与初等矩阵：一次初等行变换 = 左乘一个初等矩阵。\n8. 分块矩阵：diag(A,B) 的秩 = rank(A)+rank(B)。\n\n易错：AB=O 推不出 A=O 或 B=O。",
      },
      /* v7.8 引导问答：溯源/保存之后给两个浅色按钮，点一下就替你把下一件事做掉。
         ask = 学生侧文案；askT = 教师侧文案。blocks 逐块渲染，score 有值即显示建议分。 */
      guides: [
        {
          key: "hw",
          icon: "clipboard",
          ask: "小寻注意到你最近上传了矩阵作业，需要我帮你批改与解析吗？",
          askT: "这次矩阵作业全班平均 82 分，第 2、3 题错得集中，要我按典型错因出一份讲评要点吗？",
          label: "作业批改与解析",
          labelT: "作业讲评",
          attach: {
            material: "线性代数-第3章作业-矩阵.png",
            materialMeta: "图片素材 · 397 KB · 手写作业照片",
            img: "/static/img/matrix-hw.png",
          },
          upload: { url: "/static/img/matrix-hw.png", filename: "线性代数-第3章作业-矩阵.png",
                    category: "课程资料", categoryT: "教学备课" },
          lead: "作业图已收到。按「逐题判定 → 建议分 → 改进建议」批改，每处判定都挂到了课件知识点上：",
          score: "82", scoreFull: "100",
          saveQ: "要不要把这份<b>批改与订正结论</b>存成一篇学习笔记，放进「我的资料库」？",
          blocks: [
            { tag: "30 / 30 · 正确", name: "第 1 题 · 初等行变换求 rank(A)",
              desc: "阶梯形化得干净，非零行 2 行，rank(A)=2 过程与结论都对，不需要订正。" },
            { tag: "27 / 35 · 有误", name: "第 2 题 · 伴随矩阵求逆",
              desc: "可逆判定对（|B| = -2 不等于 0）；但 A12、A21 两处代数余子式漏乘 (-1)^(i+j)，B* 与 B⁻¹ 整体错。—— 对应课件知识点「伴随矩阵法求逆」。" },
            { tag: "25 / 35 · 有误", name: "第 3 题 · AB=O 的推断",
              desc: "结论错：AB=O 推不出 A=O 或 B=O，矩阵乘法存在零因子（反例 A=[1 0; 0 0]、B=[0 0; 0 1]）。—— 对应知识点「矩阵的秩与初等变换」里的秩不等式 rank(A)+rank(B) ≤ n。" },
          ],
          advice: "先订正第 2、3 题：求逆改用初等行变换 (B|E) → (E|B⁻¹)，绕开伴随矩阵的符号坑；第 3 题把反例抄进错题本。订正完即可进第 4 章线性方程组。",
          trace: {
            main: "批改标准与错因判定，主要依据 李文博 老师《线性代数（2026 春）》课件「第3章-矩阵与线性变换.pptx」的两个知识点（按相关度取前 3）：",
            ranked: [
              { score: "0.907", via: "语义", teacher: "李文博 老师", course: "线性代数（2026 春）", file: "第3章-矩阵与线性变换.pptx", kp: "伴随矩阵法求逆",
                snippet: "代数余子式 Aij 带符号 (-1)^(i+j)；用伴随矩阵求逆时漏符号是最常见的失分点。" },
              { score: "0.852", via: "双路命中", teacher: "李文博 老师", course: "线性代数（2026 春）", file: "第3章-矩阵与线性变换.pptx", kp: "矩阵的秩与初等变换",
                snippet: "若 AB = O，则 rank(A) + rank(B) ≤ n；当 A 可逆时才可推出 B = O。" },
              { score: "0.718", via: "关键词", teacher: "王雪 老师", course: "线性代数（2026 春）", file: "习题课03-矩阵运算.pdf", kp: "零因子与反例",
                snippet: "取 A = [1 0; 0 0]、B = [0 0; 0 1]，AB = O 但两者都不是零矩阵。" },
            ],
          },
          note: {
            title: "矩阵作业批改与订正清单（82/100）",
            body: "线性代数 · 第3章 矩阵作业 —— 批改与订正清单\n\n来源：Copilot 解析《线性代数-第3章作业-矩阵.png》，判定依据为李文博老师《线性代数（2026 春）》课件。\n\n建议分：82 / 100\n\n1. 第 1 题（30/30）初等行变换求秩：正确，无需订正。\n2. 第 2 题（27/35）伴随矩阵求逆：A12、A21 漏乘 (-1)^(i+j)；订正时改用初等行变换 (B|E) → (E|B⁻¹)。\n3. 第 3 题（25/35）AB=O 推断：结论错，矩阵乘法有零因子；反例 A=[1 0; 0 0]、B=[0 0; 0 1]；记秩不等式 rank(A)+rank(B) ≤ n。\n\n下一步：订正第 2、3 题后进第 4 章线性方程组。",
          },
        },
        {
          key: "quiz",
          icon: "wand",
          ask: "要不要我按第 3 章的整理，出 3 道自测题看看掌握情况？",
          askT: "要我按这次作业的错因分布，配 3 道课堂练习题吗？",
          label: "生成自测题",
          labelT: "课堂练习",
          lead: "已按刚整理的 8 个知识点和你第 3 题的错因配好 3 道自测题（先自己做，再对照考查点）：",
          saveQ: "要不要把这套<b>自测题</b>存成一篇学习笔记，放进「我的资料库」？",
          blocks: [
            { tag: "考点 · 矩阵的秩", name: "第 1 题",
              desc: "设 A 为 4×3 矩阵且 rank(A)=2，齐次方程组 Ax=0 的解空间维数是多少？说明理由。" },
            { tag: "考点 · 可逆矩阵", name: "第 2 题",
              desc: "用初等行变换求 B = [2 1; 5 3] 的逆，并写出每一步对应的初等矩阵。" },
            { tag: "考点 · 分块矩阵", name: "第 3 题",
              desc: "设 M = [O B; C O]（B、C 均为 n 阶可逆方阵），证明 M 可逆并求 M⁻¹。" },
          ],
          advice: "做完把答案拍给我，我按与作业相同的标准批改。第 1 题对应你这次的零因子漏洞，做错说明秩不等式还要再过一遍。",
          trace: {
            main: "题目按 李文博 老师课件「第3章-矩阵与线性变换.pptx」的知识点分布配比生成，难度对齐你当前的层次（B：讲清定义与典型例题）：",
            ranked: [
              { score: "0.881", via: "语义", teacher: "李文博 老师", course: "线性代数（2026 春）", file: "第3章-矩阵与线性变换.pptx", kp: "矩阵的秩与初等变换",
                snippet: "Ax=0 解空间维数 = n - rank(A)，这是秩的几何意义最常考的形态。" },
              { score: "0.826", via: "关键词", teacher: "王雪 老师", course: "线性代数（2026 春）", file: "习题课03-矩阵运算.pdf", kp: "初等变换求逆",
                snippet: "(A|E) → (E|A⁻¹)：每做一次行变换记下对应的初等矩阵，考试可直接验算。" },
              { score: "0.694", via: "语义", teacher: "李文博 老师", course: "高等代数（选修）", file: "第5章-线性空间.pdf", kp: "分块矩阵的逆",
                snippet: "分块对角与反对角结构先猜 M⁻¹ 的形状，再用分块乘法核验。" },
            ],
          },
          note: {
            title: "第3章 矩阵 · 3 道自测题",
            body: "线性代数 · 第3章 矩阵 —— 自测题（按作业错因配置）\n\n第 1 题（考点：矩阵的秩）设 A 为 4×3 矩阵且 rank(A)=2，齐次方程组 Ax=0 的解空间维数是多少？\n\n第 2 题（考点：可逆矩阵）用初等行变换求 B=[2 1; 5 3] 的逆，写出每步对应的初等矩阵。\n\n第 3 题（考点：分块矩阵）设 M=[O B; C O]，B、C 均为 n 阶可逆方阵，证明 M 可逆并求 M⁻¹。\n\n提示：第 1 题对应零因子与秩不等式，答案 n - rank(A) = 1。",
          },
        },
      ],
      trace: {
        main: "本次答案主要结合 李文博 老师《线性代数（2026 春）》课件「第3章-矩阵与线性变换.pptx」中的知识点「矩阵的秩与初等变换」，并与下面 3 条资料做了交叉核对后综合而成（共命中 17 条，按相关度排序取前 4）：",
        ranked: [
          { score: "0.912", via: "双路命中", teacher: "李文博 老师", course: "线性代数（2026 春）", file: "第3章-矩阵与线性变换.pptx", kp: "矩阵的秩与初等变换",
            snippet: "对矩阵作初等行变换不改变其秩，因此可把 A 化成行阶梯形，非零行的数目就是 rank(A)。" },
          { score: "0.864", via: "语义", teacher: "李文博 老师", course: "线性代数（2026 春）", file: "第2章-行列式与可逆判定.pptx", kp: "行列式与可逆的等价条件",
            snippet: "方阵 A 可逆的等价条件：|A| ≠ 0、rank(A) = n、行向量组线性无关。" },
          { score: "0.741", via: "关键词", teacher: "王雪 老师", course: "线性代数（2026 春）", file: "习题课03-矩阵运算.pdf", kp: "矩阵乘法的结合律与分配律",
            snippet: "乘法不满足交换律，但 (AB)C = A(BC) 与 A(B+C) = AB+AC 依然成立，做题时放心使用。" },
          { score: "0.683", via: "语义", teacher: "李文博 老师", course: "高等代数（选修）", file: "第5章-线性空间.pdf", kp: "基变换与过渡矩阵",
            snippet: "由基 α 到基 β 的过渡矩阵 C 满足 β = αC，它是后续用秩刻画线性相关性的基础。" },
        ],
      },
    },
    image: {
      key: "image",
      icon: "image",
      kind: "图片",
      course: "C 语言程序设计",
      material: "C语言-第8章-指针笔记.png",
      materialMeta: "图片素材 · 205 KB · 手写笔记照片",
      img: "/static/img/c-notes.png",
      prompt: "整理当前的知识点",
      lead: "这张图按手写笔记解析（已自动去掉页眉「C 语言程序设计 · 课堂笔记」、右下角页码与斜向水印噪声），整理成 6 个知识点：",
      points: [
        ["指针的定义", "存放变量地址的变量：int a=5; int *p=&a; 此时 *p 就是 5，&a 是 a 的地址。"],
        ["指针与数组", "数组名即首元素地址；a[i] 完全等价于 *(a+i)，p=a 之后 p[i] 与 a[i] 一样用。"],
        ["指针算术", "p+1 不是地址加 1，而是向后移动 sizeof(*p) 字节 —— 步长由指针类型决定。"],
        ["指针与函数参数", "C 只有值传递；想让函数改到实参必须传地址：swap(&x,&y)，形参写 int *x。"],
        ["二级指针与指针数组", "int **pp 指向一个 int*；char *argv[] 是指针数组，main 的命令行参数就是它。"],
        ["常见错误", "野指针（未初始化/已释放仍使用）、空指针解引用、越界访问 —— 调试时都表现为「偶尔崩一下」。"],
      ],
      remind: "声明 int* p, q; 只有 p 是指针，q 是 int —— * 绑定的是变量名，不是类型。",
      next: "先把指针与数组这 3 道上机题做完（swap、数组逆序、字符串拷贝），再看结构体。",
      note: {
        title: "C 语言 · 第8章 指针知识点整理",
        body: "C 语言 · 第8章 指针 —— 知识点整理\n\n来源：Copilot 解析手写笔记《C语言-第8章-指针笔记.png》，结合赵启明老师《C 语言程序设计（2026 春）》课件。\n\n1. 指针的定义：存放变量地址的变量，int *p = &a。\n2. 指针与数组：数组名即首元素地址，a[i] 等价于 *(a+i)。\n3. 指针算术：p+1 向后移动 sizeof(*p) 字节，步长由类型决定。\n4. 指针与函数参数：C 只有值传递，改实参必须传地址。\n5. 二级指针与指针数组：int **pp；char *argv[]。\n6. 常见错误：野指针、空指针解引用、越界访问。\n\n易错：int* p, q; 只有 p 是指针。",
      },
      guides: [
        {
          key: "hw",
          icon: "clipboard",
          ask: "你最近上传的指针实验作业还没订正，要我帮你批改并给出建议吗？",
          askT: "这次指针实验全班平均 75 分，越界与缺终止符错得最多，要我出一份实验讲评要点吗？",
          label: "作业批改与解析",
          labelT: "实验讲评",
          attach: {
            material: "C语言-实验八-指针作业.png",
            materialMeta: "图片素材 · 380 KB · 手写上机作业",
            img: "/static/img/c-hw.png",
          },
          upload: { url: "/static/img/c-hw.png", filename: "C语言-实验八-指针作业.png",
                    category: "课程资料", categoryT: "教学备课" },
          lead: "作业图已收到。按「逐题判定 → 建议分 → 改进建议」批改完：",
          score: "75", scoreFull: "100",
          saveQ: "要不要把这份<b>批改与订正结论</b>存成一篇学习笔记，放进「我的资料库」？",
          blocks: [
            { tag: "28 / 30 · 正确", name: "第 1 题 · 指针实现 swap",
              desc: "传址写法与「C 只有值传递」的原因说明都对；建议实参使用前判 NULL，防空指针崩溃。" },
            { tag: "24 / 35 · 有误", name: "第 2 题 · 数组原地逆序",
              desc: "循环条件写成 i <= n，i=0 时 *(a+n-i) 访问 a[n] 越界 —— 正确写法是 i < n/2，只走一半。对应知识点「指针与数组」。" },
            { tag: "23 / 35 · 有误", name: "第 3 题 · 字符串拷贝 my_cpy",
              desc: "拷贝循环结束后没写 *d = '\\0'，printf 会一直读到脏数据才停。对应知识点「常见错误」。" },
          ],
          advice: "两个失分点都在你笔记的「常见错误」清单里：先修第 2、3 题，再重读一遍那节，然后做指针与数组专项 3 题（swap、数组逆序、字符串拷贝）。",
          trace: {
            main: "错因判定依据 赵启明 老师《C 语言程序设计（2026 春）》课件「第8章-指针.pptx」的两个知识点（按相关度取前 3）：",
            ranked: [
              { score: "0.921", via: "双路命中", teacher: "赵启明 老师", course: "C 语言程序设计（2026 春）", file: "第8章-指针.pptx", kp: "指针与数组的关系",
                snippet: "a[i] 与 *(a+i) 完全等价；下标范围是 0 到 n-1，越界访问不报错但行为未定义。" },
              { score: "0.869", via: "语义", teacher: "赵启明 老师", course: "C 语言程序设计（2026 春）", file: "第8章-指针.pptx", kp: "常见错误清单",
                snippet: "字符串函数三件套：拷贝、拼接、比较 —— 每个都要自己负责写结尾的 '\\0'。" },
              { score: "0.733", via: "关键词", teacher: "赵启明 老师", course: "C 语言程序设计", file: "实验指导-指针.pdf", kp: "实验 8-1 评分标准",
                snippet: "swap 判 NULL 加 2 分；逆序与拷贝题越界或漏终止符各扣 10 分以上。" },
            ],
          },
          note: {
            title: "指针实验批改与订正清单（75/100）",
            body: "C 语言 · 实验八（指针）—— 批改与订正清单\n\n来源：Copilot 解析《C语言-实验八-指针作业.png》，判定依据为赵启明老师《C 语言程序设计（2026 春）》课件。\n\n建议分：75 / 100\n\n1. 第 1 题（28/30）swap：正确；建议实参前判 NULL。\n2. 第 2 题（24/35）数组逆序：i <= n 越界，应为 i < n/2。\n3. 第 3 题（23/35）my_cpy：结尾漏写 *d = '\\0'。\n\n下一步：修完两处失分点后，做指针与数组专项 3 题。",
          },
        },
        {
          key: "list",
          icon: "shield",
          ask: "要不要我把指针这一章你踩过的坑，整理成一份避坑清单？",
          askT: "指针实验错误很集中，要我整理一份避坑清单发到班级资料库吗？",
          label: "整理避坑清单",
          lead: "已综合你的实验作业、手写笔记与老师批注，整理出 5 条避坑清单：",
          saveQ: "要不要把这份<b>避坑清单</b>存进「我的资料库」？",
          blocks: [
            { tag: "来源 · 你的作业", name: "① 循环边界先走一遍再写",
              desc: "逆序、查找类题先在纸上代 i=0 和最后一轮，确认不会碰到 a[n] —— 这次就是 i <= n 越界。" },
            { tag: "来源 · 你的作业", name: "② 手写字符串函数必写 '\\0'",
              desc: "拷贝、拼接的最后一行永远是 *d = '\\0'，漏了输出就带随机脏字符。" },
            { tag: "来源 · 手写笔记", name: "③ int* p, q 只有 p 是指针",
              desc: "* 绑定变量名不绑定类型；一行声明多个指针要每个都带 *：int *p, *q。" },
            { tag: "来源 · 手写笔记", name: "④ p+1 的步长是 sizeof(*p)",
              desc: "int* 移 4 字节、double* 移 8 字节 —— 步长由类型决定，不是地址 +1。" },
            { tag: "来源 · 老师批注", name: "⑤ 指针用前必初始化",
              desc: "野指针、空指针解引用、越界，调试时都表现成「偶尔崩一下」，写之前先想好它指向谁。" },
          ],
          advice: "清单可以直接存进资料库；之后做结构体与链表时，这 5 条会被再次引用。",
          trace: {
            main: "清单综合了你本次上传的两份材料与 赵启明 老师课件「第8章-指针.pptx」的知识点「常见错误清单」（按相关度取前 3）：",
            ranked: [
              { score: "0.897", via: "多模态", teacher: "赵启明 老师", course: "C 语言程序设计（2026 春）", file: "第8章-指针.pptx", kp: "常见错误清单",
                snippet: "野指针、空指针、越界、漏终止符 —— 四类错误的调试表现都高度相似，靠写法预防。" },
              { score: "0.815", via: "多模态", teacher: "赵启明 老师", course: "C 语言程序设计（2026 春）", file: "第8章-指针.pptx", kp: "指针算术与类型长度",
                snippet: "p+1 的位移量是 sizeof(*p)：步长由指针类型决定，做边界计算时按字节核。" },
              { score: "0.702", via: "语义", teacher: "孙楠 老师", course: "数据结构（2026 春）", file: "第2章-线性表.pdf", kp: "链式存储与指针结点",
                snippet: "malloc 之后立刻判空、free 之后立刻置 NULL，是指针纪律的第一课。" },
            ],
          },
          note: {
            title: "C 语言指针 · 避坑清单（5 条）",
            body: "C 语言 · 第8章 指针 —— 避坑清单\n\n来源：综合《C语言-实验八-指针作业.png》《C语言-第8章-指针笔记.png》与赵启明老师课件「常见错误清单」知识点。\n\n1. 循环边界先走一遍再写：代 i=0 与最后一轮，确认不碰 a[n]。\n2. 手写字符串函数必写 '\\0'：拷贝、拼接最后一行永远是 *d = '\\0'。\n3. int* p, q 只有 p 是指针：一行声明多个指针要每个都带 *。\n4. p+1 的步长是 sizeof(*p)：步长由类型决定，不是地址 +1。\n5. 指针用前必初始化：野指针/空指针/越界的调试表现都是「偶尔崩一下」。",
          },
        },
      ],
      trace: {
        main: "本次答案主要结合 赵启明 老师《C 语言程序设计（2026 春）》课件「第8章-指针.pptx」中的知识点「指针与数组的关系」，图片与文字两路证据一起参与排序（共命中 12 条，按相关度取前 4）：",
        ranked: [
          { score: "0.934", via: "多模态", teacher: "赵启明 老师", course: "C 语言程序设计（2026 春）", file: "第8章-指针.pptx", kp: "指针与数组的关系",
            snippet: "数组名在表达式中退化为首元素地址，因此 a[i] 与 *(a+i) 完全等价，指针可以按数组方式下标访问。" },
          { score: "0.871", via: "语义", teacher: "赵启明 老师", course: "C 语言程序设计（2026 春）", file: "第8章-指针.pptx", kp: "指针算术与类型长度",
            snippet: "p+1 的位移量是 sizeof(*p)：int* 移 4 字节，double* 移 8 字节，这是指针运算最常考的一点。" },
          { score: "0.792", via: "关键词", teacher: "赵启明 老师", course: "C 语言程序设计", file: "实验指导-指针.pdf", kp: "swap：值传递与地址传递",
            snippet: "实验 8-1：实现 swap(int *x, int *y)，体会为什么传值版本交换失败、传地址版本成功。" },
          { score: "0.705", via: "语义", teacher: "孙楠 老师", course: "数据结构（2026 春）", file: "第2章-线性表.pdf", kp: "链式存储与指针结点",
            snippet: "单链表结点用指针链接，next 指针的判空与野指针防范是链表实现的第一课。" },
        ],
      },
    },

    /* v7.9 就业（事业方向）用例：学生只有「课程」和「事业」两类内容，
       这条走事业侧 —— 问路线、给建议、能溯源，并且最后一步真去提交项目申请。 */
    job: {
      key: "job",
      icon: "briefcase",
      kind: "就业",
      layer: "就业规划",                   // 气泡上的能力标签，纯提问不带附件
      course: "职业发展",
      material: "",                       // 纯提问，不带附件
      materialMeta: "",
      prompt: "我想做前端，需要学什么技术？给我一条能走的学习路线",
      lead: "按你的画像（职业倾向测评里工程实践得分偏高）和学院近几届前端岗的实际招聘口径，给你一条 6 段式路线 —— 每段都标了「学到什么程度算过关」：",
      points: [
        ["① 网页骨架：HTML + CSS", "先能徒手写一个两栏布局，Flex（一维）与 Grid（二维）要能说清各自什么时候用。过关：照着设计稿还原一个静态页面。"],
        ["② 语言本体：JavaScript / TypeScript", "闭包、事件循环、Promise 必须过一遍；TS 至少能写类型与接口。过关：不用框架实现一个带校验的表单。"],
        ["③ 框架：React 或 Vue 二选一", "先把一个学到能独立做页面：组件、状态、路由、副作用。过关：做出带列表 + 详情 + 表单的增删改查页面。"],
        ["④ 工程化：Vite / 构建 / Git", "会建项目、会打包、会提 PR、看得懂 package.json。过关：把一个项目从 0 推到能访问的静态站点。"],
        ["⑤ 数据可视化：ECharts（或 D3）", "学院的项目里前端多半要画图表。过关：把一个接口返回的 JSON 画成可交互的折线 + 柱状联动图。"],
        ["⑥ 联调与协作：HTTP、接口、评审", "看得懂接口文档，会用开发者工具查请求，知道什么是跨域。过关：与后端同学联调通一个真实接口。"],
      ],
      remind: "别一上来追新框架版本 —— 招聘看的是你把一件事做完的证据：一个部署过、能打开的项目，比五个半成品有用得多。",
      next: "第 ①、② 段两周内就能过完；之后直接进项目里做，比继续刷教程快。库里正好有一个对得上路的校企项目。",
      note: {
        title: "前端工程师 · 6 段式学习路线",
        body: "前端工程师 —— 6 段式学习路线\n\n来源：Copilot 结合李文静老师《Web 前端工程实践（2026 春）》课件「前端工程师能力地图」与学院就业报告综合而成。\n\n1. HTML + CSS：能还原设计稿，说清 Flex 与 Grid 的适用场景。\n2. JavaScript / TypeScript：闭包、事件循环、Promise；TS 至少会写类型与接口。\n3. 框架（React 或 Vue 二选一）：组件、状态、路由、副作用，能独立做增删改查页面。\n4. 工程化：Vite 建项目、打包、Git 提 PR、能部署成静态站点。\n5. 数据可视化：ECharts 把接口数据画成可交互图表。\n6. 联调与协作：看懂接口文档，会查请求，理解跨域。\n\n易错：追新框架版本不如把一个项目做完整并部署上线。",
      },
      guides: [
        {
          key: "apply",
          icon: "briefcase",
          ask: "小寻注意到张明远老师的《学业导航平台前端可视化（校企共建）》正在招人，需要我帮你提交申请吗？",
          label: "项目申请",
          action: {
            type: "resource_apply",
            title: "学业导航平台前端可视化（校企共建）",
            message: "我已按前端路线学完 HTML/CSS 与 JavaScript 基础，做过带校验的表单和一个数据看板页面，希望参与学业导航平台的前端开发与数据可视化部分。",
          },
          lead: "申请已按项目要求提交，留言写的是你现在的进度与能立刻上手的部分：",
          saveQ: "要不要把这份<b>申请与入组准备清单</b>存成一篇笔记，放进「我的资料库」？",
          blocks: [
            { tag: "匹配度 · 89%", name: "① 为什么是这个项目",
              desc: "项目要「页面开发 + 数据可视化 + 接口联调」，正好补上你路线里第 ⑤、⑥ 段还没动的两块 —— 进去就能补最缺的一环。" },
            { tag: "申请材料 · 已附", name: "② 你的前端基础",
              desc: "HTML/CSS 能还原静态页、JS 能手写表单校验，路线第 ①、② 段已达标，够到了项目要求里的硬门槛。" },
            { tag: "入组安排", name: "③ 进去之后做什么",
              desc: "先跟一次完整迭代（看需求 → 提 PR → 过评审），之后独立负责一个可视化模块；每周一次进度同步。" },
          ],
          advice: "申请一般 3 天内会有回复。这段时间别干等 —— 把第 ④ 段（Vite + Git 提 PR）先做完，进组第一天就能直接上手。",
          trace: {
            main: "推荐这个项目，是把你的路线进度与项目要求做了比对（主要依据 张明远 老师的项目说明与 李文静 老师课件里的能力地图，按相关度取前 3）：",
            ranked: [
              { score: "0.911", via: "语义", teacher: "张明远 老师", course: "学业导航平台（校企共建）", file: "项目说明与分工.pdf", kp: "前端岗位分工与交付要求",
                snippet: "前端同学负责页面与可视化，进组前需具备 HTML/CSS/JS 基础，会 React 或 Vue 其中之一。" },
              { score: "0.867", via: "语义", teacher: "李文静 老师", course: "Web 前端工程实践（2026 春）", file: "第1章-前端能力地图.pdf", kp: "前端工程师能力地图",
                snippet: "入门看三件事：能不能还原设计稿、能不能不用框架写出交互、能不能把项目跑起来部署。" },
              { score: "0.734", via: "关键词", teacher: "就业指导中心", course: "2026 届就业去向报告", file: "工程岗技能要求.pdf", kp: "前端岗招聘口径",
                snippet: "同等条件下，有一个完整上线项目的候选人，通过率约为只有课程作业的两倍。" },
            ],
          },
          note: {
            title: "学业导航平台前端项目 · 申请与入组准备",
            body: "学业导航平台前端可视化（校企共建）—— 申请与入组准备\n\n匹配度：89%\n\n1. 为什么是这个项目：要「页面开发 + 数据可视化 + 接口联调」，正好补上路线第 5、6 段。\n2. 我的基础：HTML/CSS 能还原静态页，JS 能手写表单校验（路线第 1、2 段已达标）。\n3. 入组安排：先跟一次完整迭代（需求 → PR → 评审），之后独立负责一个可视化模块，每周同步一次。\n\n等待期间要做：把 Vite + Git 提 PR 这一段先做完，进组第一天就能上手。",
          },
        },
        {
          key: "plan",
          icon: "wand",
          ask: "要不要把这条路线拆成一份 8 周学习计划，每周都有东西可交？",
          label: "学习计划",
          lead: "已拆成 4 个阶段（每 2 周一阶段），每个阶段都有一个能拿出来看的东西：",
          saveQ: "要不要把这份<b>8 周学习计划</b>存成一篇笔记，放进「我的资料库」？",
          blocks: [
            { tag: "第 1-2 周", name: "阶段一 · 静态页面",
              desc: "HTML + CSS：照设计稿还原一个学院首页，Flex 与 Grid 各用一次。交付：一个能打开的静态页面。" },
            { tag: "第 3-4 周", name: "阶段二 · JS / TS 基础",
              desc: "手写表单校验与列表增删，把阶段一改成数据驱动。交付：一个不依赖框架的表单 + 列表页。" },
            { tag: "第 5-6 周", name: "阶段三 · 框架与工程化",
              desc: "用 React 或 Vue 重写阶段二并加路由，Vite 打包后部署成静态站点。交付：一个能访问的网址。" },
            { tag: "第 7-8 周", name: "阶段四 · 可视化与联调",
              desc: "用 ECharts 画接口数据的联动图表，与后端同学联调通一个真实接口。交付：图表页 + 联调记录。" },
          ],
          advice: "四个交付物都留着，最后合成一份作品集 —— 这才是招聘时真正会被看的东西。",
          trace: {
            main: "阶段划分按 李文静 老师课件的能力地图排布，交付物口径对齐项目要求（按相关度取前 3）：",
            ranked: [
              { score: "0.878", via: "语义", teacher: "李文静 老师", course: "Web 前端工程实践（2026 春）", file: "第2章-工程化与构建.pdf", kp: "Vite 与构建流程",
                snippet: "先学会把项目跑起来并部署，再谈优化 —— 能访问的网址是最好的学习反馈。" },
              { score: "0.803", via: "关键词", teacher: "张明远 老师", course: "学业导航平台（校企共建）", file: "迭代流程说明.pdf", kp: "两周一次迭代",
                snippet: "每次迭代交付一个可演示的版本，需求、开发、评审各占一周的一半。" },
              { score: "0.691", via: "语义", teacher: "李文静 老师", course: "Web 前端工程实践（2026 春）", file: "第5章-数据可视化.pdf", kp: "ECharts 联动图表",
                snippet: "折线看趋势、柱状看对比，联动的关键是共用一个数据集与同一套筛选条件。" },
            ],
          },
          note: {
            title: "前端路线 · 8 周学习计划",
            body: "前端路线 —— 8 周学习计划（每阶段都有交付物）\n\n阶段一（第 1-2 周）HTML + CSS：照设计稿还原学院首页，交付可打开的静态页面。\n阶段二（第 3-4 周）JS/TS：手写表单校验与列表增删，交付不依赖框架的表单 + 列表页。\n阶段三（第 5-6 周）框架与工程化：React/Vue 重写并加路由，Vite 打包部署，交付一个网址。\n阶段四（第 7-8 周）可视化与联调：ECharts 联动图表 + 与后端联调通一个真实接口。\n\n提醒：四个交付物留着合成作品集，这是招聘时真正被看的东西。",
          },
        },
      ],
      trace: {
        main: "路线与阶段划分主要结合 李文静 老师《Web 前端工程实践（2026 春）》课件里的「前端工程师能力地图」，并与项目要求、学院就业报告交叉核对（共命中 9 条，按相关度取前 3）：",
        ranked: [
          { score: "0.903", via: "语义", teacher: "李文静 老师", course: "Web 前端工程实践（2026 春）", file: "第1章-前端能力地图.pdf", kp: "前端工程师能力地图",
            snippet: "入门看三件事：能不能还原设计稿、能不能不用框架写出交互、能不能把项目跑起来部署。" },
          { score: "0.845", via: "关键词", teacher: "张明远 老师", course: "学业导航平台（校企共建）", file: "项目说明与分工.pdf", kp: "前端岗位分工与交付要求",
            snippet: "前端同学负责页面与可视化，进组前需具备 HTML/CSS/JS 基础，会 React 或 Vue 其中之一。" },
          { score: "0.762", via: "语义", teacher: "就业指导中心", course: "2026 届就业去向报告", file: "工程岗技能要求.pdf", kp: "前端岗招聘口径",
            snippet: "同等条件下，有一个完整上线项目的候选人通过率约为只有课程作业的两倍。" },
        ],
      },
    },
  };

  /** 演示轮用户气泡里的「附件」块：文本显示摘要，图片直接显示缩略图。 */
  PF.demoAttach = function (demo) {
    const d = demo || {};
    if (!d.material) return "";
    let inner;
    if (d.img) {
      inner = '<img class="dm-img" src="' + PF.esc(d.img) + '" alt="' + PF.esc(d.material) + '">' +
        '<div class="dm-sub">' + PF.icon("image", 12) + PF.esc(d.material) +
        ' <span class="t-dim">' + PF.esc(d.materialMeta || "") + "</span></div>";
    } else {
      inner = '<div class="dm-file">' + PF.icon("file", 15) +
        '<div><div class="dm-file__name">' + PF.esc(d.material) + "</div>" +
        '<div class="dm-file__meta">' + PF.esc(d.materialMeta || "") + "</div></div></div>" +
        (d.excerpt ? '<div class="dm-snip">「' + PF.esc(PF.trunc(d.excerpt, 90)) + "」</div>" : "");
    }
    return '<div class="dm-attach">' + inner + "</div>";
  };

  /** 溯源知识点卡：这次答案结合了哪位老师的哪份课件的哪个知识点 + 相关度排序（前 4）。
   *  v7.8 起**默认收起**，点标题才展开 —— 溯源是证据，不是主角，别一上来糊满屏。 */
  PF.demoTraceCard = function (demo) {
    const t = (demo || {}).trace;
    if (!t) return "";
    let html = '<details class="dm-card dm-trace">' +
      '<summary class="dm-trace__head">' + PF.icon("link", 14) + "溯源知识点" +
        '<span class="t-xs t-dim">点开看：答案结合了哪位老师的哪份课件与知识点</span>' +
        '<span class="dm-trace__chev">' + PF.icon("chevronDown", 14) + "</span></summary>" +
      '<div class="dm-trace__body">' +
      '<div class="dm-card__lead">' + PF.esc(t.main || "") + "</div>" +
      '<div class="dm-list">';
    (t.ranked || []).forEach(function (r, i) {
      html += '<div class="dm-item">' +
        '<span class="dm-rank">' + (i + 1) + "</span>" +
        '<div class="dm-item__body">' +
          '<div class="row" style="gap:6px;flex-wrap:wrap">' +
            '<span class="dm-score" title="融合相关度得分">' + PF.esc(r.score) + "</span>" +
            '<span class="dm-via">' + PF.esc(r.via || "命中") + "</span>" +
            '<span class="dm-kp">' + PF.esc(r.kp || "") + "</span>" +
          "</div>" +
          '<div class="dm-src">' + PF.esc(r.teacher) + " · " + PF.esc(r.course) + " · " + PF.esc(r.file) + "</div>" +
          (r.snippet ? '<div class="dm-snip">「' + PF.esc(PF.trunc(r.snippet, 90)) + "」</div>" : "") +
        "</div></div>";
    });
    return html + "</div></div></details>";
  };

  /** 「要不要存成笔记」条：含保存路径选择（我的资料库的分类即路径）。
   *  data-demo 形如 "text" 或 "text.hw"（后者指向 demo.guides 里的某个引导结果）。
   *  side="teacher" 时才给「教学备课」—— 学生侧没有备课这回事，分类只有课程 / 科研 / 个人。 */
  PF.noteSaverHtml = function (demo, folders, side) {
    const d = demo || {};
    const isT = side === "teacher";
    // 「课件」是 v7.18 新增的分类：一键备课生成的 PPT 本体存在这里（与后端 extract.CATEGORIES 同步）
    const all = ["课件", "课程资料", "教学备课", "科研成果", "个人材料", "未分类"];
    let cats = PF.arr(folders && folders.length ? folders : all);
    if (!isT) cats = cats.filter(function (c) { return c !== "教学备课"; });
    if (!cats.length) cats = isT ? all : all.filter(function (c) { return c !== "教学备课"; });
    const q = d.saveQ || "要不要把这份整理结果存成一篇<b>学习笔记</b>，放进「我的资料库」？";
    return '<div class="dm-save" data-ns data-demo="' + PF.esc(d.key || "") + '">' +
      '<div class="dm-save__q">' + PF.icon("save", 14) + q + "</div>" +
      '<div class="dm-save__row">' +
        '<span class="dm-save__k">保存路径</span>' +
        '<select class="select select--sm" data-ns-path style="max-width:170px">' +
          cats.map(function (c) {
            return '<option value="' + PF.esc(c) + '">' + PF.esc(c) + "</option>";
          }).join("") +
          '<option value="__new__">＋ 新建文件夹…</option></select>' +
        '<input class="input input--sm" data-ns-new placeholder="新文件夹名" style="display:none;width:130px">' +
        '<button class="btn btn--sm btn--primary" data-ns-save>' + PF.icon("save", 13) + "存成笔记</button>" +
        '<button class="btn btn--sm" data-ns-skip>暂不保存</button>' +
      "</div>" +
      '<div class="dm-save__hint">存好后它出现在「我的资料库」对应路径下，之后的提问可以直接引用这篇笔记。</div>' +
      '<div class="dm-save__done" style="display:none"></div>' +
    "</div>";
  };

  /** 绑定保存条（paint 之后调用一次；重复调用安全）。 */
  PF.bindNoteSaver = function (scope, opts) {
    const o = opts || {};
    PF.$$("[data-ns]", scope).forEach(function (bar) {
      if (bar.dataset.nsBound) return;
      bar.dataset.nsBound = "1";
      const sel = PF.$("[data-ns-path]", bar);
      const nw = PF.$("[data-ns-new]", bar);
      const done = PF.$("[data-ns-done]", bar) || PF.$(".dm-save__done", bar);
      sel.addEventListener("change", function () {
        nw.style.display = sel.value === "__new__" ? "" : "none";
        if (sel.value === "__new__") nw.focus();
      });
      PF.$("[data-ns-skip]", bar).addEventListener("click", function () {
        bar.innerHTML = '<div class="dm-save__q t-dim">已跳过 —— 这份整理结果只保留在本次对话里。</div>';
      });
      PF.$("[data-ns-save]", bar).addEventListener("click", async function () {
        const btn = this;
        // key 支持 "text" 与 "text.hw"：后者取 demo.guides 里对应引导自己的 note
        const parts = String(bar.dataset.demo || "").split(".");
        const demo = PF.COPILOT_DEMOS[parts[0]] || {};
        const guide = parts[1] ? PF.arr(demo.guides).filter(function (g) { return g.key === parts[1]; })[0] : null;
        const note = (guide && guide.note) || demo.note || {};
        const course = (guide && guide.course) || demo.course || "";
        const category = sel.value === "__new__" ? (nw.value.trim() || "未分类") : sel.value;
        PF.busy(btn, true, "保存中");
        try {
          const d = await PF.post("/api/materials/note", {
            title: note.title || "知识点整理",
            content: note.body || "",
            category: category,
            course: course,
          });
          if (done) {
            done.style.display = "";
            done.innerHTML = PF.icon("check", 14) + "已存入「我的资料库 / " + PF.esc(category) +
              "」：" + PF.esc(d.filename || note.title || "") +
              (d.knowledge_points ? "，抽出 " + PF.num(d.knowledge_points, 0) + " 个知识点" : "") +
              (d.indexed ? "、建索引 " + PF.num(d.indexed, 0) + " 片" : "") +
              "。去 <a href=\"/library#/tab=mats\">我的资料库</a> 看看。";
          }
          bar.classList.add("is-done");
          if (typeof o.onSaved === "function") o.onSaved(d, category);
        } catch (e) { /* toast 已提示 */ } finally {
          PF.busy(btn, false);
        }
      });
    });
  };

  /** 演示轮助手气泡正文：整理结果 → 溯源（折叠）→ 存笔记条 → 两条引导问答。 */
  PF.demoAnswerBody = function (demo, folders, side) {
    const d = demo || {};
    let html = "";
    if (d.lead) html += '<div class="dm-lead">' + PF.esc(d.lead) + "</div>";
    if (PF.arr(d.points).length) {
      html += '<div class="dm-list">' + d.points.map(function (p, i) {
        return '<div class="dm-item"><span class="dm-rank">' + (i + 1) + "</span>" +
          '<div class="dm-item__body"><div class="dm-kp">' + PF.esc(p[0]) + "</div>" +
          '<div class="dm-sub">' + PF.esc(p[1]) + "</div></div></div>";
      }).join("") + "</div>";
    }
    if (d.remind) {
      html += '<div class="dm-warn">' + PF.icon("alert", 13) +
        "<div><b>易错提醒：</b>" + PF.esc(d.remind) + "</div></div>";
    }
    if (d.next) {
      html += '<div class="dm-note">' + PF.icon("target", 13) +
        "<div><b>下一步：</b>" + PF.esc(d.next) + "</div></div>";
    }
    html += PF.demoTraceCard(d);
    html += PF.noteSaverHtml(d, folders, side);
    html += PF.demoGuides(d, side);
    return html;
  };

  /* ------------------------------------------------------ 引导问答（v7.8）
     溯源/保存之后给两个浅色按钮：点一下 Copilot 就替你把下一件事做掉
     （自动上传作业图 → 解析 → 给建议分与订正建议，或出题 / 整理清单）。
     结果同样写死保证断网可演示；其中「上传作业图」一步会真调上传接口入库。 */

  /** 两条引导按钮。side = "teacher" 时用 askT 文案。 */
  PF.demoGuides = function (demo, side) {
    const d = demo || {};
    const gs = PF.arr(d.guides);
    if (!gs.length) return "";
    return '<div class="dm-guides">' +
      '<div class="dm-guides__t">' + PF.icon("sparkles", 13) +
        "接下来，小寻还可以顺手帮你做这两件事：</div>" +
      '<div class="dm-guides__row">' + gs.map(function (g) {
        const text = (side === "teacher" && g.askT) ? g.askT : (g.ask || "");
        return '<button class="dm-guide" data-guide="' + PF.esc((d.key || "") + "." + (g.key || "")) + '">' +
          '<span class="dm-guide__ic">' + PF.icon(g.icon || "sparkles", 15) + "</span>" +
          '<span class="dm-guide__tx">' + PF.esc(text) + "</span>" +
          '<span class="dm-guide__go">' + PF.icon("chevronRight", 13) + "</span>" +
        "</button>";
      }).join("") + "</div></div>";
  };

  /** 引导结果轮里「上传作业图」的状态行：真调上传接口，成功后如实回报入库结果。 */
  PF.demoUpStatus = function (g) {
    const u = g && g.upload;
    if (!u) return "";
    const st = g._up;
    if (!st) {
      return '<div class="dm-sub" data-up>' + PF.icon("upload", 12) +
        " 正在把《" + PF.esc(u.filename) + "》上传到「我的资料库」并解析…</div>";
    }
    if (st.state === "ok") {
      const it = st.item || {};
      return '<div class="dm-sub dm-sub--ok">' + PF.icon("check", 12) +
        " 已上传《" + PF.esc(u.filename) + "》→ 资料库 / " + PF.esc(st.category || u.category || "课程资料") +
        (it.material_id ? "（资料 #" + PF.esc(it.material_id) + "）" : "") +
        (Number(it.knowledge_saved) > 0 ? "，抽出 " + PF.esc(it.knowledge_saved) + " 个知识点" : "") +
        (Number(it.indexed_chunks) > 0 ? "、建索引 " + PF.esc(it.indexed_chunks) + " 片" : "") +
        "。</div>";
    }
    return '<div class="dm-sub">' + PF.icon("info", 12) +
      " 本次按演示素材处理，未真实入库 —— 想试真实上传，把作业照片直接拖进对话框即可。</div>";
  };

  /** 引导里的「帮我申请」状态行：真查资源广场 → 真提交申请，如实回报结果。
   *  只调一次，结果挂 guide._apply；重复申请会被后端拒绝，所以先看 my_application。 */
  PF.demoApplyStatus = function (g) {
    const a = g && g.action;
    if (!a) return "";
    const st = g._apply;
    const name = "《" + PF.esc(a.title || "该项目") + "》";
    if (!st) {
      return '<div class="dm-sub" data-apply>' + PF.icon("briefcase", 12) +
        " 正在在资源广场里找到 " + name + " 并提交申请…</div>";
    }
    if (st.state === "ok") {
      const r = st.resource || {};
      return '<div class="dm-sub dm-sub--ok">' + PF.icon("check", 12) +
        " 已提交 " + name + " 的申请 → 等待 " + PF.esc(r.teacher_name || "该教师") +
        " 处理" + (r.capacity ? "（名额 " + PF.esc(r.capacity) + " 人）" : "") +
        "。去 <a href=\"/match#/tab=apps\">师生匹配 → 我的申请</a> 看进度。</div>";
    }
    if (st.state === "dup") {
      return '<div class="dm-sub dm-sub--ok">' + PF.icon("info", 12) +
        " " + name + "你已经申请过了（" + PF.esc(st.status_text || st.status || "已提交") +
        "），不用重复提交。去 <a href=\"/match#/tab=apps\">师生匹配 → 我的申请</a> 看进度。</div>";
    }
    if (st.state === "miss") {
      return '<div class="dm-sub">' + PF.icon("info", 12) +
        " 当前数据里没有找到 " + name +
        "（演示库可能未包含这条资源），其余结论照常给你。</div>";
    }
    return '<div class="dm-sub">' + PF.icon("info", 12) +
      " 申请没能提交成功（可能名额已满或已截止），你可以直接到 " +
      '<a href="/match#/tab=res">师生匹配 → 资源广场</a> 里找老师沟通。</div>';
  };

  /** 真提交一份申请：按标题在资源广场里定位，再 POST /api/resources/{id}/apply。
   *  返回 { state: ok | dup | miss | fail, resource }。 */
  PF.applyDemoResource = async function (title, message) {
    const board = await PF.try(function () { return PF.get("/api/resources", { quiet: true }); }, null);
    let found = null;
    PF.arr(board && board.teachers).forEach(function (t) {
      PF.arr(t && t.resources).forEach(function (r) {
        if (!found && r && r.title === title) found = r;
      });
    });
    if (!found) return { state: "miss", title: title };
    if (found.my_application) {
      return { state: "dup", resource: found,
               status: found.my_application.status,
               status_text: found.my_application.status_text || "" };
    }
    const d = await PF.try(function () {
      return PF.post("/api/resources/" + found.id + "/apply", { message: message || "" });
    }, null);
    if (!d) return { state: "fail", resource: found };
    return { state: "ok", resource: found, data: d };
  };

  /** 引导轮的助手气泡正文：上传/申请状态 → 批改/出题结果 → 建议 → 溯源（折叠）→ 存笔记条。 */
  PF.demoGuideBody = function (g, gkey, folders, side) {
    g = g || {};
    let html = "";
    if (g.upload) html += PF.demoUpStatus(g);
    if (g.action && g.action.type === "resource_apply") html += PF.demoApplyStatus(g);
    if (g.lead) html += '<div class="dm-lead">' + PF.esc(g.lead) + "</div>";
    if (g.score) {
      html += '<div class="dm-total">' + PF.icon("award", 16) +
        '<span class="dm-total__num">' + PF.esc(g.score) + "</span>" +
        '<span class="dm-total__den">/ ' + PF.esc(g.scoreFull || "100") + "</span>" +
        '<span class="dm-total__t">建议分 · 逐题判定见上</span></div>';
    }
    if (PF.arr(g.blocks).length) {
      html += '<div class="dm-list">' + g.blocks.map(function (b, i) {
        return '<div class="dm-item"><span class="dm-rank">' + (i + 1) + "</span>" +
          '<div class="dm-item__body">' +
            '<div class="row" style="gap:6px;flex-wrap:wrap">' +
              (b.tag ? '<span class="dm-via">' + PF.esc(b.tag) + "</span>" : "") +
              '<span class="dm-kp">' + PF.esc(b.name || "") + "</span>" +
            "</div>" +
            (b.desc ? '<div class="dm-sub">' + PF.esc(b.desc) + "</div>" : "") +
          "</div></div>";
      }).join("") + "</div>";
    }
    if (g.advice) {
      html += '<div class="dm-note">' + PF.icon("target", 13) +
        "<div><b>改进建议：</b>" + PF.esc(g.advice) + "</div></div>";
    }
    html += PF.demoTraceCard(g);
    if (g.note) html += PF.noteSaverHtml({ key: gkey, saveQ: g.saveQ }, folders, side);
    return html;
  };

  /** 绑定引导按钮（paint 之后调用一次；重复调用安全）。onPick 收到 "text.hw" 形式的 key。 */
  PF.bindGuides = function (scope, opts) {
    const o = opts || {};
    PF.$$("[data-guide]", scope).forEach(function (b) {
      if (b.dataset.guideBound) return;
      b.dataset.guideBound = "1";
      b.addEventListener("click", function () {
        if (typeof o.onPick === "function") o.onPick(b.dataset.guide, b);
      });
    });
  };

  /** 把演示作业图真的上传入库（只调一次；失败静默返回 null，演示照常进行）。
   *  返回 /api/materials/upload 里 files 数组的第一个元素。 */
  PF.uploadStaticImage = async function (url, filename, category) {
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return null;
      const blob = await res.blob();
      const fd = new FormData();
      fd.append("files", new File([blob], filename, { type: blob.type || "image/png" }));
      fd.append("category", category || "课程资料");
      fd.append("save", "true");
      const r = await fetch("/api/materials/upload",
        { method: "POST", body: fd, credentials: "same-origin" });
      const j = await r.json();
      const item = j && j.data && PF.arr(j.data.files)[0];
      return item && !item.error ? item : null;
    } catch (e) { return null; }
  };

  /** 页面侧通用：点引导按钮 → 追加一轮「上传 + 解析 + 建议」，并后台触发真实上传。
   *  两个对话页共用，避免同一段流程抄两遍。 */
  PF.runCopilotGuide = function (gkey, hooks) {
    const h = hooks || {};
    const parts = String(gkey || "").split(".");
    const demo = PF.COPILOT_DEMOS[parts[0]] || {};
    const guide = PF.arr(demo.guides).filter(function (g) { return g.key === parts[1]; })[0];
    if (!guide || typeof h.push !== "function") return;
    const ctx = h.push(guide, gkey);          // 页面负责入列与画 loading，返回 {chat, side, done}
    if (!ctx) return;
    // 首次点击才真上传；结果挂在 guide._up 上，回看历史轮时状态行不闪重传
    if (guide.upload && !guide._up) {
      const side = ctx.side === "teacher" ? "teacher" : "student";
      const category = side === "teacher" ? (guide.upload.categoryT || guide.upload.category)
                                          : guide.upload.category;
      PF.uploadStaticImage(guide.upload.url, guide.upload.filename, category)
        .then(function (item) {
          guide._up = item ? { state: "ok", item: item, category: category }
                           : { state: "skip" };
          const el = PF.$("[data-up]", ctx.chat || document);
          if (el) { el.outerHTML = PF.demoUpStatus(guide); }
        });
    }
    // 另一种「替你去做」：按标题找到项目并真提交申请（同样只做一次）
    if (guide.action && guide.action.type === "resource_apply" && !guide._apply) {
      PF.applyDemoResource(guide.action.title, guide.action.message).then(function (r) {
        guide._apply = r;
        const el = PF.$("[data-apply]", ctx.chat || document);
        if (el) { el.outerHTML = PF.demoApplyStatus(guide); }
      });
    }
    if (typeof ctx.done === "function") ctx.done();
  };

  /* 页头的「例子演示」下拉：演示条目会越加越多，平铺按钮会把页头挤成三行。
     收进一个菜单后，加演示只动 items 数组。items: [{key, icon, label, hint}] */
  PF.demoMenuHtml = function (items, opts) {
    const o = opts || {};
    const list = PF.arr(items);
    return '<div class="dm-menu" data-dm-menu>' +
      '<button class="btn btn--primary" data-dm-btn aria-haspopup="true" aria-expanded="false">' +
        PF.icon("play", 15) + PF.esc(o.label || "例子演示") +
        '<span class="dm-menu__chev">' + PF.icon("chevronDown", 13) + "</span></button>" +
      '<div class="dm-menu__panel" style="display:none">' +
        '<div class="dm-menu__tip">' + PF.esc(o.tip || "挑一个跑一遍完整流程") + "</div>" +
        list.map(function (it) {
          return '<button class="dm-menu__item" data-dm-key="' + PF.esc(it.key) + '">' +
            '<span class="dm-menu__ic">' + PF.icon(it.icon || "file", 14) + "</span>" +
            '<span class="dm-menu__tx"><b>' + PF.esc(it.label) + "</b>" +
            (it.hint ? '<span class="t-xs t-dim">' + PF.esc(it.hint) + "</span>" : "") +
            "</span></button>";
        }).join("") +
      "</div></div>";
  };

  /** 绑定演示菜单：点选项回调 onPick(key)，点外部或 Esc 收起。 */
  PF.bindDemoMenu = function (el, onPick) {
    const root = typeof el === "string" ? PF.$(el) : el;
    if (!root) return;
    const btn = PF.$("[data-dm-btn]", root);
    const panel = PF.$(".dm-menu__panel", root);
    if (!btn || !panel) return;
    const close = function () {
      panel.style.display = "none";
      btn.setAttribute("aria-expanded", "false");
    };
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (panel.style.display !== "none") { close(); return; }
      panel.style.display = "";
      btn.setAttribute("aria-expanded", "true");
    });
    PF.$$("[data-dm-key]", panel).forEach(function (b) {
      b.addEventListener("click", function () {
        close();
        if (typeof onPick === "function") onPick(b.dataset.dmKey);
      });
    });
    document.addEventListener("click", function (e) {
      if (!root.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  };

  /** 页头的「历史对话 / 清空对话」：两个对话页共用，省得各写一遍。 */
  PF.chatActionsHtml = function () {
    return '<button class="btn" id="btn-hist">' + PF.icon("clock", 15) + "历史对话</button>" +
           '<button class="btn" id="btn-clear">' + PF.icon("trash", 15) + "清空对话</button>";
  };

  /* ------------------------------------------------- 教师 Copilot 演示（v7.9）
     与上面写死的素材演示不同，这两个**真跑接口**：
       ① 备课 —— 教案 → PPT（≤10 页）→ 作业，三步真实生成，产物进「教学备课」，
          同时各存一份进「资料与知识库 / 资料列表」；
       ② 指导学生 —— 真实取某个学生的画像画雷达图，给解读与建议。
     真跑的理由：演示里出现的东西必须能在别的页面真的找到，写死的产物一翻就穿帮。 */
  PF.TEACHER_DEMOS = {
    prep: {
      key: "prep",
      icon: "presentation",
      title: "帮我备一节朴素贝叶斯的课",
      topic: "朴素贝叶斯",
      course: "机器学习",
      pages: 10,
      periods: 1,
      level: "B",
      homework: {
        title: "朴素贝叶斯课后作业",
        full_score: 100,
        days: 7,
        detail: "1. 用自己的话说明朴素贝叶斯为什么能做分类（写清「贝叶斯公式 + 条件独立假设」两步）。\n"
          + "2. 给定一封邮件中 3 个词的出现情况，手算它属于「正常邮件 / 垃圾邮件」的概率，写出每一步。\n"
          + "3. 说明为什么叫「朴素」，并举一个条件独立假设不成立时结果会怎样的例子（顺带说明拉普拉斯平滑要不要用）。\n"
          + "要求 400 字以上，计算过程可拍照附上。",
      },
    },
    coach: {
      key: "coach",
      icon: "users",
      title: "如何指导陈嘉禾同学？",
      student: "陈嘉禾",
      // 建议加入的课题组：演示教师（张明远）自己带的长期招募组，逻辑上最顺
      group: "多模态内容理解课题组（长期招募）",
    },
  };

  /** 今天 / N 天后的 "YYYY-MM-DD"，给文件夹名与作业截止时间用。 */
  PF.dayStr = function (offsetDays) {
    const d = new Date(Date.now() + Number(offsetDays || 0) * 86400000);
    const p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  };

  /** 教案结构 → 纯文本（存进资料库用，别无脑塞 JSON）。 */
  PF.lessonToText = function (plan) {
    plan = plan || {};
    const L = ["# " + (plan.title || "教案"), "",
      "取向：" + (plan.orientation || "") + "　课时：" + (plan.periods || 1) +
      "　总时长：" + (plan.total_minutes || 0) + " 分钟", ""];
    const sect = function (name, arr) {
      if (!PF.arr(arr).length) return;
      L.push("## " + name);
      PF.arr(arr).forEach(function (x, i) { L.push((i + 1) + ". " + x); });
      L.push("");
    };
    sect("教学目标", plan.objectives);
    sect("教学重点", plan.key_points);
    sect("教学难点", plan.difficulties);
    if (PF.arr(plan.outline).length) {
      L.push("## 教学环节");
      PF.arr(plan.outline).forEach(function (s) {
        L.push("· " + (s.step || "") + "（" + (s.minutes || 0) + " 分钟）：" + (s.content || ""));
      });
      L.push("");
    }
    if (plan.homework) { L.push("## 作业"); L.push(plan.homework); }
    return L.join("\n");
  };

  /** PPT 大纲 → 纯文本（存进资料库用）。 */
  PF.slidesToText = function (outline) {
    const slides = PF.arr((outline || {}).slides);
    const L = ["# " + String((outline || {}).title || "PPT 大纲"), "",
      "共 " + slides.length + " 页", ""];
    slides.forEach(function (s, i) {
      L.push("## 第 " + (i + 1) + " 页 · " + (s.title || ""));
      PF.arr(s.bullets).forEach(function (b) { L.push("- " + b); });
      if (s.note) L.push("> 讲法提示：" + s.note);
      L.push("");
    });
    return L.join("\n");
  };

  /** 备课演示：教案 → PPT → 作业 三步真实生成，每步再存一份进资料库。 */
  PF.runPrepDemo = async function (cfg, onStep) {
    const c = cfg || {};
    const demo = PF.TEACHER_DEMOS.prep;
    const topic = c.topic || demo.topic;
    const course = c.course || demo.course;
    const folder = c.folder || (topic + " · " + PF.dayStr(0));
    const step = typeof onStep === "function" ? onStep : function () {};
    const out = { key: "prep", topic: topic, course: course, folder: folder,
                  items: [], errors: [] };

    const save = async function (title, body) {
      return await PF.try(function () {
        return PF.post("/api/materials/note", {
          title: title, content: body, category: "教学备课", course: course,
        });
      }, null);
    };
    const size = function (b) { return Number(b) > 0 ? PF.num(Number(b) / 1024, 0) + " KB" : ""; };

    /* ① 教案 —— 先检索教师自己的资料再生成，产物是 docx */
    step("①/③ 正在检索备课资料并生成教案…");
    const lp = await PF.try(function () {
      return PF.post("/api/teacher/lesson", {
        topic: topic, course: course, periods: demo.periods, level: demo.level, folder: folder,
      });
    }, null);
    if (lp && lp.plan) {
      out.items.push({
        kind: "教案", ext: "docx", icon: "book", title: topic + " 教案",
        engine: lp.engine, sizeText: size((lp.artifact || {}).size),
        pages: PF.arr(lp.plan.outline).length + " 个环节",
        note: await save(topic + " 教案", PF.lessonToText(lp.plan)),
      });
    } else { out.errors.push("教案"); }

    /* ② PPT —— 用刚生成的教案当提纲，页数上限 10 */
    step("②/③ 正在按这份教案生成 PPT（不超过 " + demo.pages + " 页）…");
    const sl = await PF.try(function () {
      return PF.post("/api/teacher/slides/from-lesson", {
        plan: (lp && lp.plan) || null, course: course, pages: demo.pages, folder: folder,
      });
    }, null);
    if (sl && sl.outline) {
      const n = PF.arr(sl.outline.slides).length;
      // 后端按「教案标题去掉『 教案』+ PPT」命名产物，这里沿用 sl.topic，
      // 保证 Copilot 卡片上的名字与「备课助手 · 我的产物」里的名字是同一个。
      const base = sl.topic || topic;
      out.items.push({
        kind: "PPT", ext: "pptx", icon: "presentation", title: base + " PPT",
        engine: sl.engine, sizeText: size((sl.artifact || {}).size),
        pages: n + " 页",
        // v7.18：PPT 本体由后端直接存进资料库「课件」，不必再另存一份大纲笔记 ——
        // 老师要的是那个能打开放映的文件，不是它的文字提纲。
        material: ((sl.artifact || {}).material || {}).id ? sl.artifact.material : null,
        slides: sl.outline.slides,
      });
    } else { out.errors.push("PPT"); }

    /* ③ 作业 —— 真实布置到任教班级 */
    step("③/③ 正在布置课后作业并归档…");
    const hw = await PF.try(function () {
      return PF.post("/api/teacher/homework", {
        title: demo.homework.title, course: course,
        class_name: c.class_name || "", detail: demo.homework.detail,
        full_score: demo.homework.full_score,
        deadline: PF.dayStr(demo.homework.days) + " 23:59",
      });
    }, null);
    if (hw && hw.homework_id) {
      out.items.push({
        kind: "作业", ext: "已布置", icon: "clipboard", title: demo.homework.title,
        engine: "rule", sizeText: "截止 " + PF.dayStr(demo.homework.days) + " 23:59",
        pages: (c.class_name || "任教班级") + " · 100 分",
        note: await save(demo.homework.title,
          "# " + demo.homework.title + "\n\n课程：" + course + "\n\n" + demo.homework.detail),
        homework_id: hw.homework_id,
      });
    } else { out.errors.push("作业"); }

    demo._last = out;      // 引导（如「思维拓展」）要沿用同一课题与文件夹
    return out;
  };

  /** 备课结果：三张产物卡 + 去哪儿看。 */
  PF.prepResultHtml = function (res) {
    const r = res || {};
    const items = PF.arr(r.items);
    let html = '<div class="dm-lead">三件事都做完了：正课教案、' +
      PF.esc(PF.TEACHER_DEMOS.prep.pages) + " 页以内的 PPT、课后作业。" +
      "产物按课题命名归到备课文件夹「" + PF.esc(r.folder || "") +
      "」，教案与作业各存一份进「资料与知识库 / 教学备课」；PPT 本体存进「课件」，" +
      "以后直接在课件库里打开放映，不用再来产物里翻。</div>";
    if (!items.length) {
      return html + '<div class="dm-warn">' + PF.icon("alert", 13) +
        "<div>三步都没跑通（后端不可达？）—— 可以到备课助手里手动再生成一次。</div></div>";
    }
    html += '<div class="dm-prods">' + items.map(function (it) {
      return '<div class="dm-prod">' +
        '<div class="dm-prod__ic">' + PF.icon(it.icon || "file", 16) + "</div>" +
        '<div class="dm-prod__body">' +
          '<div class="dm-prod__t">' + PF.esc(it.title) + PF.engineBadge(it.engine) + "</div>" +
          '<div class="dm-prod__meta">' + PF.esc(it.kind) + " · " + PF.esc(it.ext) +
            (it.sizeText ? " · " + PF.esc(it.sizeText) : "") +
            (it.pages ? " · " + PF.esc(it.pages) : "") + "</div>" +
          (it.material && it.material.id
            // 课件本体：文件名后面直接挂「预览 / 打开」，不用再回到资料库里找
            ? '<div class="dm-prod__meta">' + PF.icon("folder", 12) +
              ' 已存课件库：' + PF.esc(it.material.filename || it.title) +
              ' <button class="btn btn--sm" onclick="PF.previewMaterial(' +
                PF.esc(it.material.id) + ', \'' +
                PF.esc(String(it.material.filename || "").replace(/'/g, "")) +
                '\'); return false;">预览</button>' +
              ' <button class="btn btn--sm" onclick="PF.openMaterial(' +
                PF.esc(it.material.id) + ', \'' +
                PF.esc(String(it.material.filename || "").replace(/'/g, "")) +
                '\'); return false;">打开</button>' +
              (Number(it.material.knowledge_points) > 0
                ? "，按页抽出 " + PF.num(it.material.knowledge_points, 0) + " 个知识点" : "") +
              "</div>"
            : (it.note
              ? '<div class="dm-prod__meta">已存资料库：' + PF.esc(it.note.filename || it.title) +
                (Number(it.note.knowledge_points) > 0
                  ? "，抽出 " + PF.num(it.note.knowledge_points, 0) + " 个知识点" : "") +
                (Number(it.note.indexed) > 0 ? "、建索引 " + PF.num(it.note.indexed, 0) + " 片" : "") +
                "</div>"
              : '<div class="dm-prod__meta t-dim">这份没能存进资料库</div>')) +
        "</div></div>";
    }).join("") + "</div>";
    if (PF.arr(r.errors).length) {
      html += '<div class="dm-warn">' + PF.icon("alert", 13) + "<div>这几步没跑通：" +
        PF.esc(PF.arr(r.errors).join("、")) + "。</div></div>";
    }
    html += '<div class="dm-note">' + PF.icon("folder", 13) +
      "<div><b>去哪儿看：</b>教案与 PPT 在 <a href=\"/teach#/tab=artifacts\">备课助手 · 我的产物</a>" +
      "（已按课题命名归档到同一个文件夹）；PPT 还能在 " +
      "<a href=\"/library?category=" + encodeURIComponent("课件") + "#/tab=mats\">资料与知识库 · 课件</a>" +
      "里直接打开放映，教案与作业在 " +
      "<a href=\"/library#/tab=mats\">资料列表</a>，作业在 " +
      "<a href=\"/grade\">批改中心</a>。</div></div>";
    html += PF.demoGuides({ key: r.key || "prep", guides: PF.teacherGuidesOf("prep") }, "teacher");
    return html;
  };

  /** 指导学生演示：真实取画像（先按姓名定位，再取详情）。 */
  PF.runCoachDemo = async function (cfg, onStep) {
    const c = cfg || {};
    const name = c.student || PF.TEACHER_DEMOS.coach.student;
    const step = typeof onStep === "function" ? onStep : function () {};
    const pick = function (ov) {
      let s = null;
      PF.arr(ov && ov.students).forEach(function (x) {
        if (!s && String(x.name || "") === name) s = x;
      });
      return s;
    };
    step("正在班里定位「" + name + "」…");
    let s = pick(await PF.try(function () {
      return PF.get("/api/teacher/overview?keyword=" + encodeURIComponent(name), { quiet: true });
    }, null));
    if (!s) s = pick(await PF.try(function () {
      return PF.get("/api/teacher/overview", { quiet: true });
    }, null));
    if (!s) return { key: "coach", miss: true, name: name };

    step("正在读画像、成长路线与已有申请…");
    const d = await PF.try(function () {
      return PF.get("/api/teacher/students/" + s.id, { quiet: true });
    }, null);
    if (!d) return { key: "coach", miss: true, name: name };
    return {
      key: "coach",
      name: name,
      student: d.student || s,
      profile: d.profile || {},
      mastery: PF.arr(d.mastery),
      roadmap: d.roadmap || null,
      applications: PF.arr(d.applications),
      tasks: PF.arr(d.tasks),
    };
  };

  /** 画像解读：全部由真实数值算出来，不写死 —— 换个学生也说得通。 */
  PF.coachReading = function (res) {
    const r = res || {};
    const p = r.profile || {};
    const ab = PF.arr(p.ability_pairs).slice().sort(function (a, b) {
      return Number(b.value || 0) - Number(a.value || 0);
    });
    const best = ab[0] || { name: "—", value: 0 };
    const weak = ab[ab.length - 1] || best;
    const interests = PF.arr(p.interests);
    const apps = PF.arr(r.applications);
    const passed = apps.filter(function (a) { return a.status === "accepted"; });
    const pending = apps.filter(function (a) { return a.status === "pending"; });
    const undone = PF.arr(r.tasks).filter(function (t) { return t.status !== "done"; });
    const out = [
      { tag: "读图 · 形状", name: "① 他的形状偏哪边",
        desc: "尖角在「" + best.name + "」（" + PF.num(best.value, 1) + "），凹口在「" + weak.name +
          "」（" + PF.num(weak.value, 1) + "）：" +
          (Number(best.value) - Number(weak.value) >= 1.2
            ? "长短差得比较明显，补短板比继续加长板划算。"
            : "五维比较均衡，可以往任一方向加任务。") },
      { tag: "画像 · 定位", name: "② 按什么口径带他",
        desc: (p.track || "—") + " · " + (p.grade_level || "—") + " 层（" + (p.layer || "") +
          "）——" + (p.track === "学业型"
            ? "给任务要给他能往下挖的，别只给重复练习；讲清「为什么」比多练两遍有用。"
            : "给任务要给他能马上用上的，最好有明确的交付物与场景。") },
    ];
    if (interests.length) {
      out.push({ tag: "兴趣", name: "③ 他自己想往哪走",
        desc: "兴趣方向是 " + interests.join("、") + "，指导时尽量往这边靠，任务才推得动。" });
    }
    if (passed.length) {
      out.push({ tag: "已有申请", name: "④ 他已经在哪儿了",
        desc: "已通过《" + PF.esc(passed[0].resource_title || "") + "》（" +
          PF.esc(passed[0].teacher_name || "") + " 老师）" +
          (pending.length ? "，另有 " + pending.length + " 项申请在等回复" : "") + "。" });
    } else if (pending.length) {
      out.push({ tag: "已有申请", name: "④ 他正在等什么",
        desc: "有 " + pending.length + " 项申请还在等教师回复（《" +
          PF.esc(pending[0].resource_title || "") + "》等），可以先帮他推进一下。" });
    }
    if (undone.length) {
      out.push({ tag: "待办", name: "⑤ 手上还压着什么",
        desc: "还有 " + undone.length + " 项任务未完成，先清掉再上新任务，别堆叠。" });
    }
    return out;
  };

  /** 指导建议：读图结论 → 具体动作（含建议加入哪个课题组）。 */
  PF.coachAdvice = function (res) {
    const r = res || {};
    const p = r.profile || {};
    const ab = PF.arr(p.ability_pairs).slice().sort(function (a, b) {
      return Number(a.value || 0) - Number(b.value || 0);
    });
    const weak = ab[0] || { name: "实践能力", value: 0 };
    const group = PF.TEACHER_DEMOS.coach.group;
    return [
      { tag: "建议 · 课题组", name: "① 建议他加入「" + group + "」",
        desc: "让他承担其中的检索与问答子课题 —— 既接得上他的 NLP 底子，又正好练最缺的「" +
          weak.name + "」。组里还有名额，进组后先跟一次完整复现再定方向。" },
      { tag: "建议 · 近期", name: "② 最近四周给一个能交付的小目标",
        desc: "把课上讲的分类方法做成一份能跑通的小实验（数据、代码、结论三样齐全），"
          + "四周后一次复盘 —— 目标要小到能做完，做完要有东西可看。" },
      { tag: "建议 · 关注", name: "③ 布置任务时多写一句验收标准",
        desc: "他的短板在「" + weak.name + "」，任务说明里把「交什么、怎么算做完」写清楚，"
          + "比事后催更省事。" },
    ];
  };

  /** 指导学生结果：学生头 + 雷达图 + 解读 + 建议。 */
  PF.coachResultHtml = function (res) {
    const r = res || {};
    if (r.miss) {
      return '<div class="dm-lead">任教班级里没有找到「' + PF.esc(r.name || "该学生") +
        '」。换个名字再问一次，或先到驾驶舱确认名单。</div>';
    }
    const st = r.student || {};
    const p = r.profile || {};
    const ab = PF.arr(p.ability_pairs);
    let html = '<div class="dm-coach">' +
      '<div class="dm-coach__head">' +
        '<div class="dm-coach__name">' + PF.esc(st.name || r.name || "") +
          ' <span class="t-xs t-dim">' + PF.esc(st.username || "") + " · " +
          PF.esc(st.class_name || st.class_id || "") + "</span></div>" +
        '<div class="row" style="gap:6px;flex-wrap:wrap">' +
          PF.trackBadge(p.track) + PF.levelTag(p.grade_level, true) +
          (p.gpa !== undefined && p.gpa !== null
            ? '<span class="badge">绩点 ' + PF.num(p.gpa, 2) + "</span>" : "") +
          (p.layer ? '<span class="badge">' + PF.esc(p.layer) + "</span>" : "") +
        "</div>" +
      "</div>" +
      '<div class="radar-wrap">' + PF.radar(ab, { max: 5 }) + PF.radarTips(ab) + "</div>" +
      "</div>";
    html += '<div class="dm-lead">图是这个学生真实的五维能力（数据来源：画像库）。' +
      "下面两句是照着图读出来的，不是套话：</div>";
    html += PF.demoBlocks(PF.coachReading(r));
    html += '<div class="dm-note">' + PF.icon("target", 13) +
      "<div><b>可以怎么做：</b>按上面的读图结论，给三条能直接落到行动上的建议。</div></div>";
    html += PF.demoBlocks(PF.coachAdvice(r));
    html += PF.demoGuides({ key: r.key || "coach", guides: PF.teacherGuidesOf("coach") }, "teacher");
    return html;
  };

  /** 一组 blocks（[{tag,name,desc}]）渲染成列表 —— 解读与建议共用。 */
  PF.demoBlocks = function (blocks) {
    const bs = PF.arr(blocks);
    if (!bs.length) return "";
    return '<div class="dm-list">' + bs.map(function (b, i) {
      return '<div class="dm-item"><span class="dm-rank">' + (i + 1) + "</span>" +
        '<div class="dm-item__body">' +
          '<div class="row" style="gap:6px;flex-wrap:wrap">' +
            (b.tag ? '<span class="dm-via">' + PF.esc(b.tag) + "</span>" : "") +
            '<span class="dm-kp">' + PF.esc(b.name || "") + "</span>" +
          "</div>" +
          (b.desc ? '<div class="dm-sub">' + PF.esc(b.desc) + "</div>" : "") +
        "</div></div>";
    }).join("") + "</div>";
  };

  /* -------------------------------------------- 教师演示 ③ 项目申请批复（v7.9 闭环）
     学生那边点「帮我申请」落的是一条 pending，这里把它捡起来：
     给一句按真实字段说的建议，然后真的 decide 一次 —— 演示才能首尾相接。 */
  PF.TEACHER_DEMOS.review = {
    key: "review",
    icon: "briefcase",
    title: "我有哪些待处理的项目申请？",
  };

  /** 读待处理申请：GET /api/resources 对教师返回的是 teacher_view（每条申请自带学生画像字段）。 */
  PF.runReviewDemo = async function (cfg, onStep) {
    const step = typeof onStep === "function" ? onStep : function () {};
    step("正在读你发布的资源与收到的申请…");
    const board = await PF.try(function () {
      return PF.get("/api/resources", { quiet: true });
    }, null);
    let total = 0;
    const items = [];
    PF.arr(board && board.resources).forEach(function (r) {
      PF.arr(r && r.applications).forEach(function (a) {
        total += 1;
        if (String(a.status || "") !== "pending") return;
        items.push({
          id: a.id, resource_id: r.id,
          resource_title: r.title || "", rtype_label: r.rtype_label || "资源",
          capacity: Number(r.capacity || 0), accepted: Number(r.accepted || 0),
          deadline: r.deadline || "",
          student: a.student_name || "", username: a.student_username || "",
          klass: a.class_name || a.class_id || "",
          track: a.track || "", grade_level: a.grade_level || "",
          gpa: a.gpa === undefined ? null : Number(a.gpa),
          message: a.message || "", at: a.created_at || "",
        });
      });
    });
    PF.TEACHER_DEMOS.review._items = items;
    return { key: "review", items: items, total: total,
             resources: PF.arr(board && board.resources).length };
  };

  /** 每条申请怎么回：只用真实字段（名额余量 / 绩点 / 倾向 / 层次）下判断，不编数字。
   *  名额用完时不建议直接婉拒 —— 一句「排候补」比一句「不合适」有用。 */
  PF.reviewAdviceOf = function (it) {
    const x = it || {};
    const left = Number(x.capacity) > 0 ? Number(x.capacity) - Number(x.accepted || 0) : -1;
    if (left === 0) {
      return {
        tag: "名额已满",
        name: "先回一句「列候补」，别直接婉拒",
        desc: "《" + x.resource_title + "》的 " + PF.num(x.capacity, 0) + " 个名额已经用完" +
          "（已通过 " + PF.num(x.accepted, 0) + " 人）。直接婉拒会让他以为是自己不合适 —— " +
          "回一句「你排候补第一位，有名额优先通知」，后面有人退出时他还能直接顶上。",
      };
    }
    const bits = [];
    // 注意：库里的 gpa 是**百分制**（满分 100，见 student_profiles），别按 4 分制判。
    if (x.gpa !== null && Number(x.gpa) > 0) {
      bits.push(Number(x.gpa) >= 85
        ? "绩点 " + PF.num(x.gpa, 1) + "，在班里排得上"
        : (Number(x.gpa) >= 75
          ? "绩点 " + PF.num(x.gpa, 1) + "（中等，看完成时的执行力）"
          : "绩点 " + PF.num(x.gpa, 1) + " 不算好看，但留言里写清了自己想补哪一块"));
    }
    if (x.track) bits.push("画像是" + x.track);
    if (x.grade_level) bits.push("内容深度走" + x.grade_level + "层");
    return {
      tag: left > 0 ? "还剩 " + left + " 个名额" : "名额未设上限",
      name: "建议通过，并在回复里写明第一步",
      desc: (bits.length ? bits.join("，") + "；" : "") +
        "留言里说清了他现在会什么、想承担哪一块，属于能立刻上手的那类 —— " +
        "通过时把「第一周跟一次完整迭代，之后独立负责一个子模块」写进回复，比只说欢迎有用。",
    };
  };

  /** 批复的回复语：点按钮就照这个提交（不是装饰，学生会真的看到这句话）。 */
  PF.reviewReply = function (it, act) {
    const who = ((it && it.student) || "同学");
    const title = (it && it.resource_title) || "该项目";
    if (act === "accepted") {
      return who + "同学：你的申请通过了，欢迎进组。第一周先跟一次完整迭代（看需求 → 提 PR → 过评审），"
        + "之后独立负责《" + title + "》里的一个子模块，每周同步一次进度。卡住直接在平台上问我。";
    }
    return who + "同学：《" + title + "》这轮名额已经排满，我把你放在候补第一位，"
      + "有名额空出或开新项目时第一时间通知你。这段时间可以先把手上的任务收尾，"
      + "把之前的项目整理成一份可交付的成果 —— 下次有位置的时候这就是材料。";
  };

  /** 批复演示结果：每条一张卡（谁、申请什么、留言、怎么建议、两个真按钮）。 */
  PF.reviewResultHtml = function (res) {
    const r = res || {};
    const items = PF.arr(r.items);
    if (!items.length) {
      return '<div class="dm-lead">你现在没有待处理的申请' +
        (Number(r.total) ? "（共 " + PF.num(r.total, 0) + " 条都已处理完）" : "") +
        "。想看这条链路怎么走：用学生账号在 Copilot 里点「就业例子演示 → 帮我申请」，"
        + "那条申请会立刻出现在这里。</div>" +
        '<div class="dm-note">' + PF.icon("info", 13) +
        "<div><b>演示顺序：</b>学生端提交 → 教师端在这里批复 → 学生的「我的申请」状态变了，" +
        "并自动给他建一条跟进任务。两侧是同一份数据。</div></div>";
    }
    let html = '<div class="dm-lead">你发布的 ' + PF.num(Number(r.resources) || 0, 0) +
      " 项资源上，有 <b>" + PF.num(items.length, 0) + " 条待你处理</b> —— " +
      "每条都附了这个学生的真实画像字段，并给了一句建议。点「同意加入」就是真的批，不是演示按钮。</div>";
    html += '<div class="dm-apps">' + items.map(function (it) {
      const ad = PF.reviewAdviceOf(it);
      return '<div class="dm-app" data-app="' + PF.esc(it.id) + '">' +
        '<div class="dm-app__head">' +
          '<div class="dm-app__who">' + PF.esc(it.student) +
            ' <span class="t-xs t-dim">' + PF.esc(it.username) + " · " + PF.esc(it.klass) + "</span></div>" +
          '<div class="row" style="gap:6px;flex-wrap:wrap">' +
            PF.trackBadge(it.track) + PF.levelTag(it.grade_level, true) +
            (it.gpa !== null ? '<span class="badge">绩点 ' + PF.num(it.gpa, 2) + "</span>" : "") +
            '<span class="badge">' + PF.esc(it.rtype_label) + "</span>" +
          "</div>" +
        "</div>" +
        '<div class="dm-app__meta">申请《' + PF.esc(it.resource_title) + "》" +
          (it.capacity > 0 ? " · 名额 " + PF.num(it.capacity, 0) + "（已通过 " + PF.num(it.accepted, 0) + "）" : "") +
          (it.deadline ? " · 截止 " + PF.esc(it.deadline) : "") + "</div>" +
        (it.message ? '<div class="dm-snip">「' + PF.esc(PF.trunc(it.message, 120)) + "」</div>" : "") +
        '<div class="dm-item" style="padding:0;border:none">' +
          '<div class="dm-item__body">' +
            '<div class="row" style="gap:6px;flex-wrap:wrap">' +
              '<span class="dm-via">' + PF.esc(ad.tag) + "</span>" +
              '<span class="dm-kp">' + PF.esc(ad.name) + "</span>" +
            "</div>" +
            '<div class="dm-sub">' + PF.esc(ad.desc) + "</div>" +
          "</div>" +
        "</div>" +
        '<div class="dm-app__acts">' +
          '<button class="btn btn--sm btn--primary" data-decide="' + PF.esc(it.id) +
            '" data-act="accepted">' + PF.icon("check", 13) + "同意加入</button>" +
          '<button class="btn btn--sm" data-decide="' + PF.esc(it.id) +
            '" data-act="declined">' + PF.icon("x", 13) + "排候补并说明</button>" +
        "</div>" +
        '<div class="dm-app__done" style="display:none"></div>' +
        "</div>";
    }).join("") + "</div>";
    html += '<div class="dm-note">' + PF.icon("link", 13) +
      "<div><b>批完之后：</b>学生那边「我的申请」会立刻变成已通过/已婉拒，并带上你写的回复；" +
      "通过的话还会顺手给他建一条跟进任务（" +
      '<a href="/match#/tab=res">师生匹配 → 资源管理</a> 里能看到同一份名单）。</div></div>';
    html += PF.demoGuides({ key: "review", guides: PF.teacherGuidesOf("review") }, "teacher");
    return html;
  };

  /** 绑定批复按钮：一次性的，点完就地显示结果，不整轮重画。 */
  PF.bindReviewDecide = function (scope, opts) {
    const o = opts || {};
    PF.$$("[data-decide]", scope).forEach(function (b) {
      if (b.dataset.decideBound) return;
      b.dataset.decideBound = "1";
      b.addEventListener("click", async function () {
        const card = b.closest(".dm-app");
        const id = b.dataset.decide;
        const act = b.dataset.act === "declined" ? "declined" : "accepted";
        const list = PF.arr(PF.TEACHER_DEMOS.review && PF.TEACHER_DEMOS.review._items);
        const it = list.filter(function (x) { return String(x.id) === String(id); })[0] || {};
        const acts = PF.$(".dm-app__acts", card);
        const done = PF.$(".dm-app__done", card);
        if (acts) acts.style.display = "none";
        PF.busy(b, true, "提交中");
        const d = await PF.try(function () {
          return PF.post("/api/teacher/applications/" + id + "/decide", {
            action: act, reply: PF.reviewReply(it, act),
          });
        }, null);
        PF.busy(b, false);
        if (!d) {
          if (acts) acts.style.display = "";
          if (done) {
            done.style.display = "";
            done.innerHTML = PF.icon("alert", 13) + " 这次没能提交成功，稍后再试一次。";
          }
          return;
        }
        const rec = { student: it.student, resource_title: it.resource_title, action: act,
                      reply: PF.reviewReply(it, act) };
        // 记住批过谁，引导那条「入组须知」要用
        PF.TEACHER_DEMOS.review._decided = PF.arr(PF.TEACHER_DEMOS.review._decided).concat([rec]);
        if (done) {
          done.style.display = "";
          done.innerHTML = PF.icon("check", 14) +
            (act === "accepted"
              ? " 已通过《" + PF.esc(it.resource_title) + "》 —— " + PF.esc(it.student) +
                " 那边立刻能看到，并自动给他建了一条跟进任务" +
                (Number(d.task_created) ? "（已建）" : "")
              : " 已回复《" + PF.esc(it.resource_title) + "》 —— " + PF.esc(it.student) +
                " 那边会看到候补说明");
        }
        if (card) card.classList.add(act === "accepted" ? "is-ok" : "is-no");
        if (typeof o.onDone === "function") o.onDone(rec, d);
      });
    });
  };

  /** 一组 blocks → 可存的纯文本（引导里「顺手存一份」用）。 */
  PF.blocksToText = function (title, blocks, lead) {
    const L = ["# " + (title || "整理结果"), ""];
    if (lead) { L.push(lead); L.push(""); }
    PF.arr(blocks).forEach(function (b, i) {
      L.push("## " + (i + 1) + ". " + String(b.name || ""));
      if (b.tag) L.push("（" + b.tag + "）");
      if (b.desc) L.push(String(b.desc));
      L.push("");
    });
    return L.join("\n");
  };

  /* 教师演示之后的引导：每条都真的去做一件事（生成拓展教案 / 存一份资料），
     不摆样子。key 形如 "prep.extend"，与 demoGuides 的 data-guide 对齐。 */
  PF.TEACHER_GUIDES = {
    "prep.extend": {
      icon: "sparkles",
      ask: "小寻注意到上课班级为学业拔尖型（A 层占比偏高），是否需要为这节课设计思维拓展模块？",
      label: "思维拓展",
      lead: "已按拔尖型的内容深度单独出一份思维拓展模块，与正课放进同一个备课文件夹：",
      run: async function () {
        const base = (PF.TEACHER_DEMOS.prep && PF.TEACHER_DEMOS.prep._last) || {};
        const topic = (base.topic || "朴素贝叶斯") + " · 思维拓展";
        const course = base.course || "机器学习";
        const d = await PF.try(function () {
          return PF.post("/api/teacher/lesson", {
            topic: topic, course: course, periods: 1, level: "A", folder: base.folder || "",
          });
        }, null);
        if (!d) return null;
        const note = await PF.try(function () {
          return PF.post("/api/materials/note", {
            title: topic + " 教案", content: PF.lessonToText(d.plan),
            category: "教学备课", course: course,
          });
        }, null);
        return { topic: topic, plan: d.plan, artifact: d.artifact, engine: d.engine, note: note };
      },
      statusText: function (st) {
        return "已生成《" + PF.esc(st.topic) + " 教案》（docx" +
          ((st.artifact && st.artifact.size) ? "，" + PF.num(st.artifact.size / 1024, 0) + " KB" : "") +
          "）" + (st.note ? "，并存入「资料与知识库 / 教学备课」：" + PF.esc(st.note.filename || "") : "");
      },
      blocks: [
        { tag: "拓展 · 假设", name: "① 把「条件独立」这条假设拆开看",
          desc: "条件独立到底省掉了什么？把它放宽成「每个属性最多依赖一个其它属性」，就是半朴素贝叶斯 —— 让学有余力的同学自己推一遍参数个数从多少降到多少。" },
        { tag: "拓展 · 数学", name: "② 拉普拉斯平滑为什么是加 1",
          desc: "从贝叶斯估计的角度看，加 1 其实是给了一个均匀先验；再问一句：加 0.5（Lidstone）行不行？什么时候会出问题？" },
        { tag: "拓展 · 对比", name: "③ 生成式 vs 判别式：与逻辑回归对照",
          desc: "朴素贝叶斯先学 P(x|y) 再反推 P(y|x)，逻辑回归直接学 P(y|x)。讨论：训练样本很少时谁更稳？为什么？" },
        { tag: "拓展 · 动手", name: "④ 造一个反例自己验",
          desc: "构造两个强相关特征（如「下雨」与「带伞」），看朴素贝叶斯的概率估计怎么被放大，再想想工程上怎么规避。" },
      ],
      advice: "拓展模块单独成文、按需取用：不占正课时间，也不要求所有同学都做 —— 内容深度可以不一样，任务要求不因人而异。",
      adviceLabel: "用法",
      trace: {
        main: "拓展点的选取依据 张明远 老师《机器学习（2026 春）》课件「第4章-贝叶斯分类器.pptx」里的两个知识点（按相关度取前 3）：",
        ranked: [
          { score: "0.894", via: "语义", teacher: "张明远 老师", course: "机器学习（2026 春）", file: "第4章-贝叶斯分类器.pptx", kp: "条件独立假设与参数规模",
            snippet: "条件独立把联合概率的参数从指数级降到线性级，这是朴素贝叶斯能在小样本上工作的根本原因。" },
          { score: "0.831", via: "关键词", teacher: "张明远 老师", course: "机器学习（2026 春）", file: "第4章-贝叶斯分类器.pptx", kp: "拉普拉斯平滑",
            snippet: "平滑是为了避免某个属性在某个类下没出现过导致整条概率归零；加 1 相当于给了均匀先验。" },
          { score: "0.706", via: "语义", teacher: "李文静 老师", course: "机器学习（2026 春）", file: "第3章-线性模型.pdf", kp: "生成式与判别式模型",
            snippet: "生成式先建 P(x|y)，判别式直接建 P(y|x)；样本少时前者方差更小，样本足时后者通常更准。" },
        ],
      },
    },
    "prep.review": {
      icon: "clipboard",
      ask: "要不要我把这节课最容易错的地方，整理成一份讲评要点？",
      label: "讲评要点",
      lead: "已按作业里最容易失分的三处整理成讲评要点，下节课开头十分钟就能用：",
      run: async function () {
        const base = (PF.TEACHER_DEMOS.prep && PF.TEACHER_DEMOS.prep._last) || {};
        const self = PF.TEACHER_GUIDES["prep.review"];
        const title = (base.topic || "朴素贝叶斯") + " 讲评要点";
        const note = await PF.try(function () {
          return PF.post("/api/materials/note", {
            title: title,
            content: PF.blocksToText(title, self.blocks, "下节课开头十分钟的讲评顺序："),
            category: "教学备课", course: base.course || "机器学习",
          });
        }, null);
        return note ? { note: note, title: title } : null;
      },
      statusText: function (st) {
        return "已存入「资料与知识库 / 教学备课」：" + PF.esc(st.note.filename || st.title || "") +
          (Number(st.note.knowledge_points) > 0
            ? "，抽出 " + PF.num(st.note.knowledge_points, 0) + " 个知识点" : "");
      },
      blocks: [
        { tag: "讲评 · 第 1 处", name: "① 只写公式、不写「为什么能分类」",
          desc: "多数同学能默出贝叶斯公式，但说不清「条件独立假设」省掉了什么。讲评时先让他解释假设，再讲公式 —— 顺序反了就记不住。" },
        { tag: "讲评 · 第 2 处", name: "② 先验概率被漏掉",
          desc: "手算时直接比较 P(x|y)，忘了乘 P(y)。讲评时把两类先验差一个数量级的例子摆出来，一眼就能看出差别。" },
        { tag: "讲评 · 第 3 处", name: "③ 概率为 0 就整条归零",
          desc: "没出现过的词会让整条概率变成 0。讲评时现场演示加平滑前后的结果对比，比讲定义管用。" },
      ],
      advice: "讲评要点按「错在哪 → 为什么错 → 怎么讲」排好了，直接照着念也能用。",
      adviceLabel: "用法",
    },
    "coach.talk": {
      icon: "message",
      ask: "要不要把这份指导要点整理成一份谈话提纲，存进资料库？",
      label: "谈话提纲",
      lead: "已整理成一份能照着谈的提纲（怎么开场 → 问哪三句 → 怎么收尾），并存进「资料与知识库 / 教学备课」：",
      run: async function () {
        const self = PF.TEACHER_GUIDES["coach.talk"];
        const who = (PF.TEACHER_DEMOS.coach && PF.TEACHER_DEMOS.coach.student) || "该学生";
        const title = who + " · 指导谈话提纲";
        const note = await PF.try(function () {
          return PF.post("/api/materials/note", {
            title: title,
            content: PF.blocksToText(title, self.blocks, "与学生一对一谈话时的顺序（照着走即可）："),
            category: "教学备课", course: "",
          });
        }, null);
        return note ? { note: note, title: title } : null;
      },
      statusText: function (st) {
        return "已存入「资料与知识库 / 教学备课」：" + PF.esc(st.note.filename || st.title || "");
      },
      blocks: [
        { tag: "开场", name: "① 先说他做得好的那件事",
          desc: "从雷达图最长的那一维切入（具体哪次作业、哪个项目做得好），先坐实优势，后面才谈得动短板。" },
        { tag: "三问", name: "② 三句话问出真实想法",
          desc: "一问「接下来半年最想做成什么」；二问「现在卡在哪一步」；三问「需要我帮你打通什么」—— 三问顺序不能倒，先有目标才谈卡点。" },
        { tag: "收尾", name: "③ 收尾只留一个动作",
          desc: "谈完只给一个小到能做完的目标（四周内、有交付物），并约定下次复盘的时间 —— 一次谈太多等于没谈。" },
      ],
      advice: "提纲是给教师自己用的：照着走一遍大约 20 分钟，谈完在资料库里补一句结论，下次直接续上。",
      adviceLabel: "用法",
    },
    "coach.plan": {
      icon: "target",
      ask: "要不要给他生成一份 4 周进阶任务清单？",
      label: "进阶任务",
      lead: "已按他最缺的那一维排了 4 周 —— 每周一件事、每周有交付：",
      run: async function () {
        const self = PF.TEACHER_GUIDES["coach.plan"];
        const who = (PF.TEACHER_DEMOS.coach && PF.TEACHER_DEMOS.coach.student) || "该学生";
        const title = who + " · 4 周进阶任务清单";
        const note = await PF.try(function () {
          return PF.post("/api/materials/note", {
            title: title,
            content: PF.blocksToText(title, self.blocks, "每周一个交付物，四周后复盘一次："),
            category: "教学备课", course: "",
          });
        }, null);
        return note ? { note: note, title: title } : null;
      },
      statusText: function (st) {
        return "已存入「资料与知识库 / 教学备课」：" + PF.esc(st.note.filename || st.title || "");
      },
      blocks: [
        { tag: "第 1 周", name: "① 复现一遍课堂方法（不调库）",
          desc: "用自己的数据把课上讲的分类方法从头实现一遍，交一份能跑的脚本 + 一张结果表 —— 先把「知道」变成「做出来」。" },
        { tag: "第 2 周", name: "② 换一份数据再跑，写清差异",
          desc: "换一个数据来源重跑，说明指标为什么变了。目标不是跑通，是能解释变化。" },
        { tag: "第 3 周", name: "③ 跟一次组会 / 项目例会",
          desc: "进组听一次会，会后用三段话写清「大家在做什么、我能在哪插进去」—— 这一步是补协作与实践那一维。" },
        { tag: "第 4 周", name: "④ 复盘：讲一遍自己做的东西",
          desc: "用 10 分钟讲清「做了什么、结论是什么、哪里还不确定」，讲不清的地方就是下一步要补的地方。" },
      ],
      advice: "四周只有一个目标：让他把一件事做完并能讲清楚。做完了再往上加，别一次排满。",
      adviceLabel: "用法",
    },
    "review.brief": {
      icon: "briefcase",
      ask: "要不要把这次的批复结果与进组安排，整理成一份入组须知存进资料库？",
      label: "入组须知",
      lead: "已按你刚才的批复整理成一份能直接发给学生看的须知，并存进「资料与知识库 / 教学备课」：",
      run: async function () {
        const D = PF.TEACHER_DEMOS.review || {};
        const recs = PF.arr(D._decided);
        const rec = recs[recs.length - 1] || PF.arr(D._items)[0] || null;
        const self = PF.TEACHER_GUIDES["review.brief"];
        const title = (rec && rec.resource_title)
          ? rec.resource_title + " · 入组须知" : "项目申请 · 入组须知";
        const lead = rec
          ? "面向本轮《" + rec.resource_title + "》的进组同学（批复内容：" +
            (rec.action === "accepted" ? "已通过" : "排候补") + "）："
          : "";
        const note = await PF.try(function () {
          return PF.post("/api/materials/note", {
            title: title, content: PF.blocksToText(title, self.blocks, lead),
            category: "教学备课", course: "",
          });
        }, null);
        return note ? { note: note, title: title } : null;
      },
      statusText: function (st) {
        return "已存入「资料与知识库 / 教学备课」：" + PF.esc(st.note.filename || st.title || "");
      },
      blocks: [
        { tag: "第 1 周", name: "① 先跟一次完整迭代，别急着接任务",
          desc: "完整看一遍：需求从哪来 → 代码怎么提（提 PR）→ 评审时看什么。跟完一次再开工，后面的返工少一半。" },
        { tag: "每周同步", name: "② 每周三句话：进度、卡点、下周计划",
          desc: "不用写周报，三句话就够：做到哪了、卡在哪、下周打算怎么办。卡点越早说越好，攒到月底没人救得了。" },
        { tag: "交付标准", name: "③ 什么叫「做完了」",
          desc: "有可见产物（一个页面、一张图、一个能跑的脚本），并且别人能照着跑出来 —— 这两条满足才算完成。" },
        { tag: "退出机制", name: "④ 中途跟不上怎么办",
          desc: "连续两周没产出就主动说，调子模块的规模或换个方向，比硬扛到学期末强。候补的同学随时按这个标准顶上。" },
      ],
      advice: "须知是直接给学生看的口径：写清「第一周做什么、什么叫做完」，比口头交代省事得多。",
      adviceLabel: "用法",
    },
  };

  /** 取某个教师演示的引导列表（供 PF.demoGuides 渲染）。 */
  PF.teacherGuidesOf = function (rootKey) {
    return Object.keys(PF.TEACHER_GUIDES)
      .filter(function (k) { return String(k).split(".")[0] === rootKey; })
      .map(function (k) {
        return Object.assign({ key: String(k).split(".")[1] }, PF.TEACHER_GUIDES[k]);
      });
  };

  /** 引导里「正在做什么」的状态行：跑成功照实说，跑不通也照实说。 */
  PF.teacherActionStatus = function (g) {
    const st = (g || {})._res;
    if (!st) {
      return '<div class="dm-sub" data-tact>' + PF.icon("sparkles", 12) +
        " 正在处理…</div>";
    }
    if (st.fail) {
      return '<div class="dm-sub">' + PF.icon("info", 12) +
        " 这一步没能连上后端 —— 下面的内容照常给你，稍后可以在备课助手里再做一次。</div>";
    }
    const txt = typeof g.statusText === "function" ? g.statusText(st) : "已完成。";
    return '<div class="dm-sub dm-sub--ok">' + PF.icon("check", 12) + " " + txt + "</div>";
  };

  /** 教师引导轮的正文：状态行 → 结果 → 说明 → 溯源（折叠）。 */
  PF.teacherGuideBody = function (g, folders) {
    g = g || {};
    let html = PF.teacherActionStatus(g);
    if (g.lead) html += '<div class="dm-lead">' + PF.esc(g.lead) + "</div>";
    html += PF.demoBlocks(g.blocks);
    if (g.advice) {
      html += '<div class="dm-note">' + PF.icon("target", 13) + "<div><b>" +
        PF.esc(g.adviceLabel || "说明") + "：</b>" + PF.esc(g.advice) + "</div></div>";
    }
    html += PF.demoTraceCard(g);
    return html;
  };

  /** 点教师演示的引导按钮：先入列画 loading，跑完真动作再重画这一轮。 */
  PF.runTeacherGuide = async function (gkey, hooks) {
    const h = hooks || {};
    const g = PF.TEACHER_GUIDES[gkey];
    if (!g) return null;
    const ctx = typeof h.push === "function" ? h.push(g, gkey) : null;
    let res = null;
    if (typeof g.run === "function") {
      res = await PF.try(function () { return g.run(g); }, null);
    }
    g._res = res || { fail: true };
    if (typeof h.paint === "function") h.paint(g, gkey, ctx);
    return g;
  };

  /* ------------------------------------------------------ 智能体工具
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
      { id: "teach", label: "⑥ 备课生成用例" },
      { id: "grade", label: "⑦ 批改建议分用例" },
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
      // ④⑤⑥⑦ 都是"用例"而不是素材：它们没有可解析的文件，只有期望值
      if (id === "rag" || id === "synth" || id === "teach" || id === "grade") {
        renderCases(cases.filter(function (c) { return c.ability === id; }), body);
        return;
      }
      renderSamples(samples.filter(function (s) { return s.ability === id; }), body);
    }

    nav.innerHTML = TABS.map(function (t) {
      // ④⑤ 是用例（五种架构 / 综合生成各一组），不是素材，所以按 cases 计数
      const n = t.id === "cases" ? cases.length
        : (t.id === "rag" || t.id === "synth" || t.id === "teach" || t.id === "grade")
          ? cases.filter(function (c) { return c.ability === t.id; }).length
          : samples.filter(function (s) { return s.ability === t.id; }).length;
      return '<button class="mn-navbtn" data-t="' + t.id + '">' + PF.esc(t.label) +
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
        { key: "ask", href: "/ask", label: "学生 Copilot", icon: "message" },
        { key: "match", href: "/match", label: "师生匹配", icon: "users" },
      ]},
      { group: "学习事务", items: [
        { key: "homework", href: "/homework", label: "我的作业", icon: "file" },
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
