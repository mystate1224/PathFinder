/* ==========================================================================
   tabs.js —— 极简标签页组件
   --------------------------------------------------------------------------
   依赖 common.js（先引）。用法：

     const view = PF.tabs(document.getElementById('tabs'), [
       { key: 'a', label: '标签A', count: 3, render: (box) => { box.innerHTML = '...' } },
       { key: 'b', label: '标签B', render: (box, ctx) => { ... } },
     ], { base: '#/tab' });

   特性：
   - 懒加载：标签首次激活才调用 render（避免一进页面打十几个请求）
   - 强制刷新：ctx.reload() 让当前标签重跑 render，ctx.go(key) 切到别的标签
   - 数量角标：item.count 变化后可调用 ctx.refreshCount(key, n)
   - 滑动指示条：切页时下划线平滑滑过去，而不是硬跳
   - 键盘可达：←/→/Home/End 切换，符合 WAI-ARIA tabs 模式
   - 支持 #/tab=key 形式的锚点，刷新后停留在同一标签
   ========================================================================== */
(function () {
  "use strict";
  const PF = window.PF;
  if (!PF) { console.error("tabs.js 需要先引入 common.js"); return; }

  /**
   * 渲染一组标签页。
   * @param {HTMLElement} host   容器（组件会自己往里面塞 tab 条 + 面板）
   * @param {Array} items        [{ key, label, count, icon, render(box, ctx) }]
   * @param {object} [opts]      { base: 锚点前缀, initial: 初始 key, onChange(key) }
   * @returns {object} ctx       { go, reload, current, box, refreshCount }
   */
  PF.tabs = function (host, items, opts) {
    const o = opts || {};
    const tabs = PF.arr(items).filter((t) => t && t.key);
    if (!host || !tabs.length) return null;

    const rendered = Object.create(null);   // key -> true 表示已渲染过
    let current = "";

    host.innerHTML =
      '<div class="tabs" role="tablist"></div>' +
      '<div class="tab-panels mt-5"></div>';
    const bar = PF.$(".tabs", host);
    const panels = PF.$(".tab-panels", host);

    // 滑动指示条：跟随当前标签。定位失败（如容器隐藏）时自动隐藏，由 .tab 自带的下边框兜底。
    // 在按钮之后 append，保证它画在标签之上（标签的透明下边框不会挡住它）。
    const ink = document.createElement("div");
    ink.className = "tabs__ink";
    ink.setAttribute("aria-hidden", "true");

    // 每个标签一个面板容器，切走时隐藏而不销毁（保留滚动位置与表单内容）
    tabs.forEach((t) => {
      const panel = document.createElement("div");
      panel.className = "tab-panel";
      panel.id = "tabpanel-" + t.key;
      panel.dataset.key = t.key;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", "tab-" + t.key);
      panel.hidden = true;
      panels.appendChild(panel);
      t._panel = panel;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tab";
      btn.id = "tab-" + t.key;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-controls", panel.id);
      btn.tabIndex = -1;                      // 由 activate() 做 roving tabindex
      btn.dataset.key = t.key;
      btn.innerHTML =
        (t.icon ? PF.icon(t.icon, 15) : "") +
        "<span>" + PF.esc(t.label) + "</span>" +
        '<span class="tab__count"' + (t.count === undefined ? ' style="display:none"' : "") + ">" +
          PF.esc(t.count === undefined ? 0 : t.count) + "</span>";
      btn.addEventListener("click", () => activate(t.key));
      btn.addEventListener("keydown", onBarKey);
      bar.appendChild(btn);
      t._btn = btn;
    });

    bar.appendChild(ink);

    /** ←/→/Home/End 在标签条内移动并立即激活（ARIA tabs 手册推荐的做法） */
    function onBarKey(e) {
      const keys = { ArrowLeft: -1, ArrowRight: 1 };
      let idx = tabs.map((t) => t.key).indexOf(current);
      if (idx < 0) idx = 0;
      if (e.key in keys) {
        idx = (idx + keys[e.key] + tabs.length) % tabs.length;
      } else if (e.key === "Home") {
        idx = 0;
      } else if (e.key === "End") {
        idx = tabs.length - 1;
      } else {
        return;
      }
      e.preventDefault();
      const next = tabs[idx];
      activate(next.key);
      next._btn.focus();
    }

    /** 把指示条对齐到当前标签；容器不可见时（宽度为 0）先藏起来 */
    function moveInk() {
      const t = tabs.filter((x) => x.key === current)[0];
      if (!t || !t._btn) return;
      if (t._panel.hidden || !bar.getClientRects().length) { ink.style.opacity = "0"; return; }
      const left = t._btn.offsetLeft;
      const w = t._btn.offsetWidth;
      if (!w) { ink.style.opacity = "0"; return; }
      ink.style.opacity = "1";
      ink.style.width = w + "px";
      ink.style.transform = "translateX(" + left + "px)";
    }
    const reposition = PF.debounce(moveInk, 120);
    window.addEventListener("resize", reposition);

    const ctx = {
      get current() { return current; },
      box: null,
      go: activate,
      reload() { rendered[current] = false; return activate(current, true); },
      refreshCount(key, n) {
        const t = tabs.filter((x) => x.key === key)[0];
        if (!t) return;
        t.count = n;
        const badge = PF.$(".tab__count", t._btn);
        badge.textContent = n;
        badge.style.display = "";
        reposition();
      },
    };

    function hashKey() {
      const raw = (location.hash || "").replace(/^#\/?/, "");
      const m = /(?:^|&)tab=([^&]+)/.exec(raw);
      return m ? decodeURIComponent(m[1]) : "";
    }

    function activate(key, force) {
      const target = tabs.filter((t) => t.key === key)[0] || tabs[0];
      if (!target) return null;

      const changed = target.key !== current;
      current = target.key;

      tabs.forEach((t) => {
        const on = t.key === current;
        t._btn.classList.toggle("is-active", on);
        t._btn.setAttribute("aria-selected", on ? "true" : "false");
        t._btn.tabIndex = on ? 0 : -1;
        t._panel.hidden = !on;
      });
      moveInk();

      if (o.base) {
        const next = o.base + (o.base.indexOf("?") >= 0 ? "&" : "") + "tab=" + encodeURIComponent(current);
        if (location.hash !== next) history.replaceState(null, "", next);
      }
      if (typeof o.onChange === "function" && changed) o.onChange(current);

      if (force || !rendered[current]) {
        rendered[current] = true;
        ctx.box = target._panel;
        // 面板淡入：先摘掉 class 再下一帧加回，动画才会重新播
        if (!PF.reduced()) {
          target._panel.classList.remove("is-entering");
          requestAnimationFrame(() => {
            if (!target._panel.hidden) target._panel.classList.add("is-entering");
          });
        }
        // render 允许返回 Promise；抛错时降级为空态而不是让整页白屏
        try {
          const ret = target.render ? target.render(target._panel, ctx) : null;
          if (ret && typeof ret.catch === "function") {
            ret.catch((err) => {
              target._panel.innerHTML = PF.empty({
                icon: "alert",
                title: "「" + target.label + "」加载失败",
                desc: (err && err.message) || String(err),
              });
            });
          }
        } catch (err) {
          target._panel.innerHTML = PF.empty({
            icon: "alert",
            title: "「" + target.label + "」渲染出错",
            desc: (err && err.message) || String(err),
          });
        }
      }
      ctx.box = target._panel;
      return target._panel;
    }

    const start = o.initial || hashKey() || tabs[0].key;
    activate(start);
    // 字体或异步内容会让标签宽度变化，布局稳定后再校一次位置
    requestAnimationFrame(moveInk);
    window.addEventListener("load", moveInk);
    return ctx;
  };

  /** 侧边栏同级页面内跳转到某个标签（供跨页链接使用） */
  PF.tabs.go = function (key) {
    location.hash = "#/tab=" + encodeURIComponent(key);
  };
})();
