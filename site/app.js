// Project site interactions: chart tabs, market-view toggle, the note-vs-bill explorer, copy buttons
// and section highlighting. All numbers come from the JSON the Python build embeds in the page.
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const dataEl = $("#site-data");
  const D = dataEl ? JSON.parse(dataEl.textContent) : {};
  const fix = (v, d = 2) => v.toFixed(d);
  const sgn = (v, d = 2) => (v < 0 ? "−" : "+") + Math.abs(v).toFixed(d);
  let view = "hyp";
  const listeners = [];

  // ---------- tabs ----------
  $$("[data-tabs]").forEach((group) => {
    const tabs = $$('[role="tab"]', group);
    const show = (id, focus) => {
      tabs.forEach((t) => {
        const on = t.dataset.target === id;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        const panel = document.getElementById(t.dataset.target);
        if (panel) panel.hidden = !on;
        if (on && focus) t.focus();
      });
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => show(t.dataset.target));
      t.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const j = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
        show(tabs[j].dataset.target, true);
      });
    });
    if (tabs.length) show(tabs[0].dataset.target);
  });

  // ---------- market view toggle (shared by the explorer and the scenario table) ----------
  const setView = (v) => {
    view = v;
    $$("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
    $$("[data-view-panel]").forEach((p) => { p.hidden = p.dataset.viewPanel !== v; });
    listeners.forEach((f) => f());
  };
  $$("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  // ---------- explorer ----------
  const X = D.explorer;
  const svg = $("#explorer-chart");
  if (X && svg) {
    const NS = "http://www.w3.org/2000/svg";
    const P = X.points;
    const slider = $("#explorer-slider");
    const tip = $("#explorer-tip");
    const chips = $("#explorer-chips");
    const box = svg.parentElement;
    const css = getComputedStyle(document.documentElement);
    const col = (n) => css.getPropertyValue(`--${n}`).trim();
    const scenColor = { falling: col("falling"), stable: col("stable"), rising: col("rising") };
    const order = ["rolldown", "below_eia", "falling", "stable", "rising"];
    const keyOf = (s) => (s === "rolldown" ? "rolldown" : `${view}:${s}`);
    const indexOf = (key) => P.findIndex((p) => p.keys.includes(key));
    let sel = Math.max(0, indexOf("rolldown"));
    let geo = null;

    slider.max = String(P.length - 1);

    const mk = (tag, attrs, parent, text) => {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      if (text !== undefined) e.textContent = text;
      if (parent) parent.appendChild(e);
      return e;
    };

    function draw() {
      const W = Math.max(300, Math.round(box.clientWidth));
      const narrow = W < 560;
      const H = narrow ? 300 : 380;
      const m = { l: narrow ? 46 : 56, r: 14, t: 30, b: 46 };
      const x0 = P[0].y, x1 = P[P.length - 1].y;
      const vals = P.flatMap((p) => [p.note, p.bill]);
      const y0 = Math.floor(Math.min(...vals) * 2) / 2, y1 = Math.ceil(Math.max(...vals) * 2) / 2;
      const sx = (v) => m.l + ((v - x0) / (x1 - x0)) * (W - m.l - m.r);
      const sy = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);
      geo = { W, H, m, sx, sy };
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.setAttribute("width", W);
      svg.setAttribute("height", H);
      svg.textContent = "";

      // regions: note wins left of breakeven, bill wins right of it
      const bx = sx(X.breakeven);
      mk("rect", { x: m.l, y: m.t, width: bx - m.l, height: H - m.t - m.b, fill: col("note"), opacity: 0.06 }, svg);
      mk("rect", { x: bx, y: m.t, width: W - m.r - bx, height: H - m.t - m.b, fill: col("bill"), opacity: 0.06 }, svg);
      mk("text", { x: m.l + 8, y: m.t + 16, fill: col("note"), "font-size": 12, "font-weight": 700 }, svg, "← Note wins");
      mk("text", { x: W - m.r - 8, y: m.t + 16, fill: col("bill"), "font-size": 12, "font-weight": 700, "text-anchor": "end" }, svg, "Bill wins →");

      // grid and axes
      const g = mk("g", {}, svg);
      for (let v = y0; v <= y1 + 1e-9; v += 0.5) {
        mk("line", { x1: m.l, x2: W - m.r, y1: sy(v), y2: sy(v), stroke: col("rule"), "stroke-width": 1 }, g);
        mk("text", { x: m.l - 8, y: sy(v) + 4, "text-anchor": "end", "font-size": 12, fill: col("muted") }, g, `${fix(v, 1)}%`);
      }
      const step = narrow ? 0.5 : 0.25;
      for (let v = Math.ceil(x0 / step) * step; v <= x1 + 1e-9; v += step) {
        mk("line", { x1: sx(v), x2: sx(v), y1: H - m.b, y2: H - m.b + 5, stroke: col("muted") }, g);
        mk("text", { x: sx(v), y: H - m.b + 19, "text-anchor": "middle", "font-size": 12, fill: col("muted") }, g, `${fix(v, 2)}%`);
      }
      mk("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: col("muted") }, g);
      mk("text", { x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle", "font-size": 12.5, fill: col("ink-2") }, g,
        `1.5-year yield on ${X.horizon}`);
      if (!narrow) {
        mk("text", { x: 12, y: (m.t + H - m.b) / 2, "text-anchor": "middle", "font-size": 12.5, fill: col("ink-2"),
          transform: `rotate(-90 12 ${(m.t + H - m.b) / 2})` }, g, "Return over the hold");
      }

      // breakeven
      mk("line", { x1: bx, x2: bx, y1: m.t, y2: H - m.b, stroke: col("ink-2"), "stroke-width": 1.5, "stroke-dasharray": "5 4" }, svg);
      mk("text", { x: bx, y: m.t - 10, "text-anchor": "middle", "font-size": 12, "font-weight": 700, fill: col("ink") }, svg,
        `Breakeven ${fix(X.breakeven)}%`);

      // lines
      mk("line", { x1: m.l, x2: W - m.r, y1: sy(X.bill), y2: sy(X.bill), stroke: col("bill"), "stroke-width": 2.5, "stroke-linecap": "round" }, svg);
      const d = P.map((p, i) => `${i ? "L" : "M"}${sx(p.y).toFixed(1)},${sy(p.note).toFixed(1)}`).join("");
      mk("path", { d, fill: "none", stroke: col("note"), "stroke-width": 2.5, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);

      // scenario dots for the current view
      order.forEach((s) => {
        const i = indexOf(keyOf(s));
        if (i < 0) return;
        const p = P[i], cx = sx(p.y), cy = sy(p.note);
        const hollow = s === "below_eia" || s === "rolldown";
        mk("circle", { cx, cy, r: 6, fill: hollow ? col("surface") : scenColor[s], stroke: hollow ? col("ref") : col("surface"),
          "stroke-width": hollow ? 2 : 2.5 }, svg);
        if (!narrow) {
          const below = s === "rolldown";
          mk("text", { x: cx + (below ? -10 : 10), y: cy + (below ? 20 : -10), "text-anchor": below ? "end" : "start",
            "font-size": 12, fill: col("ink-2") }, svg, X.short[s]);
        }
      });

      // selection and hover layers
      geo.sel = mk("g", {}, svg);
      geo.hover = mk("line", { y1: m.t, y2: H - m.b, stroke: col("muted"), "stroke-width": 1, visibility: "hidden" }, svg);
      const overlay = mk("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent", style: "cursor:crosshair" }, svg);
      overlay.addEventListener("pointermove", hover);
      overlay.addEventListener("pointerleave", () => { tip.hidden = true; geo.hover.setAttribute("visibility", "hidden"); });
      overlay.addEventListener("click", (e) => select(nearest(e)));
      drawSel();
    }

    function nearest(e) {
      const r = svg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * geo.W;
      let best = 0, bd = Infinity;
      P.forEach((p, i) => { const dd = Math.abs(geo.sx(p.y) - x); if (dd < bd) { bd = dd; best = i; } });
      return best;
    }

    function hover(e) {
      const i = nearest(e), p = P[i];
      const x = geo.sx(p.y);
      geo.hover.setAttribute("x1", x); geo.hover.setAttribute("x2", x); geo.hover.setAttribute("visibility", "visible");
      const r = svg.getBoundingClientRect(), scale = r.width / geo.W;
      tip.innerHTML = `Yield <b>${fix(p.y)}%</b><br>Note <b>${fix(p.note)}%</b> &middot; Bill <b>${fix(p.bill)}%</b><br>Edge <b>${sgn(p.edge)}%</b>`;
      tip.hidden = false;
      const left = Math.min(Math.max(x * scale, 70), r.width - 70);
      tip.style.left = `${left}px`;
      tip.style.top = `${Math.max(geo.sy(Math.max(p.note, p.bill)) * scale - 12, 60)}px`;
    }

    function drawSel() {
      if (!geo) return;
      const p = P[sel], { sx, sy, m, H } = geo;
      geo.sel.textContent = "";
      mk("line", { x1: sx(p.y), x2: sx(p.y), y1: m.t, y2: H - m.b, stroke: col("navy"), "stroke-width": 1.5 }, geo.sel);
      mk("circle", { cx: sx(p.y), cy: sy(p.bill), r: 5, fill: col("bill"), stroke: col("surface"), "stroke-width": 2 }, geo.sel);
      mk("circle", { cx: sx(p.y), cy: sy(p.note), r: 7.5, fill: col("navy"), stroke: col("surface"), "stroke-width": 2.5 }, geo.sel);
    }

    function scenarioName(p) {
      const k = p.keys.find((key) => key === "rolldown" || key.startsWith(`${view}:`));
      if (!k) return "";
      if (k === "rolldown") return "This is where the yield ends up if the curve does not move at all.";
      return `This is the “${X.labels[k.split(":")[1]]}” scenario when the ${X.views[view].replace("Market", "market")}.`;
    }

    function select(i) {
      sel = i;
      const p = P[i];
      slider.value = String(i);
      slider.setAttribute("aria-valuetext", `${fix(p.y)} percent`);
      $("#explorer-yield").textContent = `${fix(p.y)}%`;
      $("#ro-note").textContent = `${fix(p.note)}%`;
      $("#ro-bill").textContent = `${fix(p.bill)}%`;
      $("#ro-edge").textContent = `${sgn(p.edge)}%`;
      let v;
      if (Math.abs(p.edge) < 0.005) v = `At ${fix(p.y)}% the note and the bill tie: this is the breakeven.`;
      else if (p.edge > 0) v = `At ${fix(p.y)}% the note beats the bill by ${fix(p.edge)}% over the ${X.days} days.`;
      else v = `At ${fix(p.y)}% the bill beats the note by ${fix(-p.edge)}% over the ${X.days} days.`;
      const sn = scenarioName(p);
      $("#ro-verdict").textContent = sn ? `${v} ${sn}` : v;
      $$(".chip-btn", chips).forEach((b) => b.setAttribute("aria-pressed", String(P[sel].keys.includes(b.dataset.key))));
      drawSel();
    }

    function buildChips() {
      chips.textContent = "";
      order.forEach((s) => {
        const key = keyOf(s);
        if (indexOf(key) < 0) return;
        const b = document.createElement("button");
        b.type = "button";
        b.className = "chip-btn";
        b.dataset.key = key;
        b.innerHTML = `<i class="dot dot--${s}" aria-hidden="true"></i>${X.labels[s]}`;
        b.addEventListener("click", () => select(indexOf(key)));
        chips.appendChild(b);
      });
    }

    slider.addEventListener("input", () => select(Number(slider.value)));
    listeners.push(() => { buildChips(); draw(); select(sel); });
    if ("ResizeObserver" in window) {
      let last = 0;
      new ResizeObserver(() => { const w = box.clientWidth; if (Math.abs(w - last) > 2) { last = w; draw(); } }).observe(box);
    } else {
      window.addEventListener("resize", draw);
    }
  }
  setView("hyp");

  // ---------- copy buttons ----------
  $$("pre[data-copy]").forEach((pre) => {
    const wrap = document.createElement("div");
    wrap.className = "code";
    const bar = document.createElement("div");
    bar.className = "code-bar";
    bar.textContent = "Terminal";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.append(bar, pre);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "copy-btn";
    b.textContent = "Copy";
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(pre.querySelector("code").innerText.trim()); b.textContent = "Copied"; }
      catch (e) { b.textContent = "Select and copy"; }
      setTimeout(() => { b.textContent = "Copy"; }, 1600);
    });
    bar.appendChild(b);
  });

  // ---------- highlight the section in view ----------
  const nav = $(".nav");
  const links = new Map($$(".nav a").map((a) => [a.getAttribute("href").slice(1), a]));
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        links.forEach((a) => a.classList.remove("active"));
        const a = links.get(en.target.id);
        if (a) {
          a.classList.add("active");
          nav.scrollTo({ left: a.offsetLeft - nav.clientWidth / 2 + a.clientWidth / 2, behavior: "smooth" });
        }
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    links.forEach((_, id) => { const s = document.getElementById(id); if (s) io.observe(s); });
  }
})();
