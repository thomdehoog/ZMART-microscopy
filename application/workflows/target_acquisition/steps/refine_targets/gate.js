/**
 * Step 7's channel — the scatter the targets are gated on.
 *
 * Discovery finds every cell; this is where the operator says which are worth
 * imaging. A gate is one polygon on one feature pair — laid point by point
 * and closed on its first vertex, the way the scan-area polygon is — and
 * gates accumulate in a list. The selection is the intersection: a cell must
 * fall inside every gate, so adding one only ever narrows. Each plot carries
 * at most its own pair's polygon; choosing a gate from the list brings its
 * plot back, axes and all.
 *
 * The rules live in `gating.js`, where they are pinned without a canvas.
 * The widget owns its markup, its canvas and its gestures; what it reads and
 * what it changes arrive in `ctx`, and it never reaches for the page.
 */

import {
  cellFeature, cellsInAllGates, featureNames, gateForPair,
} from "./gating.js";
import { sideGroup } from "../../../../framework/window/panels.js";

/** Room for the axes, in pixels. */
const PAD = { l: 62, r: 18, t: 18, b: 46 };

/** How near a press must land to take a vertex or an edge, in pixels. */
const REACH = 9;

export default {
  id: "select",
  label: "Refine Targets",

  /**
   * `ctx` carries:
   *   `cells()` `gated()` `acquired()`  what to draw; `gated()` is the
   *                     intersection the run holds
   *   `gates()`         every gate laid, `[{fx, fy, vertices}]`
   *   `setGates(gates, ids)`  the gates changed; the run takes both
   *   `showing()`       whether discovery has run, so there is anything to gate
   *   `sizeCanvas(cv)` `css(name)`  the page's canvas plumbing
   */
  mount(host, ctx) {
    /* Which features the plot spans right now. */
    let fx = "area";
    let fy = "intensity";
    /* The polygon being laid, in feature units, until it closes. */
    let draft = null;
    /* The vertex the hand holds mid-drag, and the one last chosen. */
    let held = null;
    let chosen = -1;
    let xHi = 1;
    let yHi = 1;

    const side = document.createElement("div");
    side.className = "analysis-side";

    /* The same boxed group every earlier step's channel is made of. */
    const boxed = sideGroup("Gates");
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "ghost tiny";
    clear.id = "clear-gate";
    clear.textContent = "Clear gates";

    /* One feature per axis: the gate drawn here is drawn across these. */
    const axes = document.createElement("div");
    axes.className = "gate-axes";
    const pick = (id, label) => {
      const wrap = document.createElement("label");
      wrap.append(label);
      const sel = document.createElement("select");
      sel.id = id;
      wrap.append(sel);
      axes.append(wrap);
      return sel;
    };
    const pickX = pick("gate-fx", "x");
    const pickY = pick("gate-fy", "y");
    axes.append(clear);

    const legend = document.createElement("div");
    legend.className = "legend analysis-legend";
    for (const [ink, what] of [["--mark-context", "all cells"],
      ["--mark-gated", "selected"], ["--mark-acquired", "acquired"]]) {
      const one = document.createElement("span");
      one.innerHTML = `<i class="dot" style="background:var(${ink})"></i> `;
      one.append(what);
      legend.append(one);
    }

    const wrap = document.createElement("div");
    wrap.className = "scatter-wrap";
    const canvasHost = document.createElement("div");
    canvasHost.className = "scatter-host";
    const cv = document.createElement("canvas");
    cv.id = "scatter-canvas";
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.id = "scatter-tip";
    canvasHost.append(cv, tip);
    wrap.append(canvasHost);

    const readout = document.createElement("div");
    readout.className = "side-note";
    readout.id = "gate-readout";

    const list = document.createElement("div");
    list.className = "gate-list";
    list.id = "gate-list";

    boxed.body.append(axes, legend, wrap, readout, list);
    side.append(boxed.group);
    host.append(side);

    const sx = (v, w) => PAD.l + (v / xHi) * (w - PAD.l - PAD.r);
    const sy = (v, h) => (h - PAD.b) - (v / yHi) * (h - PAD.t - PAD.b);
    const invX = (px, w) => ((px - PAD.l) / (w - PAD.l - PAD.r)) * xHi;
    const invY = (py, h) => (((h - PAD.b) - py) / (h - PAD.t - PAD.b)) * yHi;

    const theCells = () => [...ctx.cells()];
    const shownGate = () => gateForPair(ctx.gates(), fx, fy);

    /* Gates changed: the run takes the list and the intersection together. */
    const commit = (gates) => {
      ctx.setGates(gates, cellsInAllGates(theCells(), gates));
      sayIt();
      renderList();
      draw();
    };

    const sayIt = () => {
      const cells = theCells();
      const gates = ctx.gates();
      if (draft) {
        readout.textContent =
          `laying a gate on ${fx} × ${fy} — ${draft.length} point(s), close it on the first`;
        return;
      }
      if (!gates.length) {
        readout.textContent = "click to lay a polygon gate — close it on its first point";
        return;
      }
      readout.textContent =
        `${ctx.gated().size} of ${cells.length} selected · `
        + `${gates.length} gate${gates.length === 1 ? "" : "s"}`;
    };

    /** The gates, each a row that brings its own plot back. */
    function renderList() {
      list.textContent = "";
      const cells = theCells();
      ctx.gates().forEach((gate, at) => {
        const row = document.createElement("div");
        row.className = "gate-row";
        row.setAttribute("aria-current", String(gate === shownGate()));
        const open = document.createElement("button");
        open.type = "button";
        open.className = "gate-open";
        const inside = cellsInAllGates(cells, [gate]).size;
        open.innerHTML = `<span class="idx">${at + 1}</span>`
          + `<span>${gate.fx} × ${gate.fy}</span>`
          + `<span class="gate-n">${inside} in</span>`;
        open.addEventListener("click", () => {
          fx = gate.fx;
          fy = gate.fy;
          draft = null;
          chosen = -1;
          refreshPickers();
          renderList();
          draw();
          sayIt();
        });
        const drop = document.createElement("button");
        drop.type = "button";
        drop.className = "rec-drop";
        drop.textContent = "✕";
        drop.title = "throw this gate away";
        drop.addEventListener("click", () => {
          commit(ctx.gates().filter((g) => g !== gate));
        });
        row.append(open, drop);
        list.append(row);
      });
    }

    /** The pickers offer every feature the cells carry; the pair in use wins. */
    function refreshPickers() {
      const names = featureNames(theCells());
      for (const [sel, current] of [[pickX, fx], [pickY, fy]]) {
        sel.textContent = "";
        for (const name of names) {
          const o = document.createElement("option");
          o.value = name;
          o.textContent = name;
          sel.append(o);
        }
        sel.value = current;
      }
    }
    for (const [sel, take] of [[pickX, (v) => { fx = v; }], [pickY, (v) => { fy = v; }]]) {
      sel.addEventListener("change", () => {
        take(sel.value);
        draft = null;
        chosen = -1;
        renderList();
        draw();
        sayIt();
      });
    }

    function draw() {
      if (!ctx.sizeCanvas(cv)) return;
      const paint = cv.getContext("2d");
      const w = cv.cssW, h = cv.cssH;
      paint.clearRect(0, 0, w, h);
      paint.fillStyle = ctx.css("--screen");
      paint.fillRect(0, 0, w, h);

      const cells = theCells();
      xHi = 1; yHi = 1;
      for (const c of cells) {
        xHi = Math.max(xHi, cellFeature(c, fx));
        yHi = Math.max(yHi, cellFeature(c, fy));
      }

      // recessive grid
      paint.strokeStyle = ctx.css("--line");
      paint.lineWidth = 1;
      paint.fillStyle = ctx.css("--ink-3");
      paint.font = "11.5px ui-monospace, Consolas, monospace";
      paint.textAlign = "right";
      for (let n = 0; n <= 4; n++) {
        const v = (yHi * n) / 4, y = sy(v, h);
        paint.beginPath(); paint.moveTo(PAD.l, y); paint.lineTo(w - PAD.r, y); paint.stroke();
        paint.fillText(v >= 10 ? v.toFixed(0) : v.toFixed(2), PAD.l - 9, y + 4);
      }
      paint.textAlign = "center";
      for (let n = 1; n <= 4; n++) {
        const v = (xHi * n) / 4, x = sx(v, w);
        paint.beginPath(); paint.moveTo(x, PAD.t); paint.lineTo(x, h - PAD.b); paint.stroke();
        paint.fillText(v >= 10 ? v.toFixed(0) : v.toFixed(2), x, h - PAD.b + 18);
      }

      // axis titles are the chosen features, because that is what this plot IS
      paint.fillStyle = ctx.css("--ink-2");
      paint.font = "12.5px system-ui, sans-serif";
      paint.fillText(fx, (PAD.l + w - PAD.r) / 2, h - 12);
      paint.save();
      paint.translate(16, (PAD.t + h - PAD.b) / 2);
      paint.rotate(-Math.PI / 2);
      paint.fillText(fy, 0, 0);
      paint.restore();

      const gated = ctx.gated();

      // every cell, quietly; the survivors of ALL gates, ringed
      paint.fillStyle = ctx.css("--mark-context");
      paint.globalAlpha = 0.5;
      paint.beginPath();
      for (const c of cells) {
        if (gated.has(c.id)) continue;
        const x = sx(cellFeature(c, fx), w), y = sy(cellFeature(c, fy), h);
        paint.moveTo(x + 2, y); paint.arc(x, y, 2, 0, Math.PI * 2);
      }
      paint.fill();
      paint.globalAlpha = 1;

      const acquired = new Set(ctx.acquired());
      for (const c of cells) {
        if (!gated.has(c.id)) continue;
        const x = sx(cellFeature(c, fx), w), y = sy(cellFeature(c, fy), h);
        const taken = acquired.has(c.id);
        paint.beginPath(); paint.arc(x, y, taken ? 4.6 : 3.4, 0, Math.PI * 2);
        paint.fillStyle = taken ? "#16a34a" : "#0284c7";
        paint.fill();
        paint.lineWidth = 2; paint.strokeStyle = ctx.css("--screen"); paint.stroke();
      }

      // this pair's own gate, and only its own — with its handles
      const gate = shownGate();
      if (gate) {
        paint.strokeStyle = "#0284c7"; paint.lineWidth = 1.5;
        paint.setLineDash([5, 4]);
        paint.beginPath();
        gate.vertices.forEach(([gx, gy], i) => {
          const x = sx(gx, w), y = sy(gy, h);
          if (i) paint.lineTo(x, y); else paint.moveTo(x, y);
        });
        paint.closePath();
        paint.stroke();
        paint.setLineDash([]);
        gate.vertices.forEach(([gx, gy], i) => {
          const x = sx(gx, w), y = sy(gy, h);
          paint.fillStyle = i === chosen ? "#0284c7" : ctx.css("--screen");
          paint.strokeStyle = "#0284c7"; paint.lineWidth = 1.5;
          paint.beginPath(); paint.rect(x - 3.5, y - 3.5, 7, 7);
          paint.fill(); paint.stroke();
        });
      }

      // the polygon being laid, open, its first point marked as the way home
      if (draft) {
        paint.strokeStyle = ctx.css("--accent"); paint.lineWidth = 1.5;
        paint.setLineDash([4, 3]);
        paint.beginPath();
        draft.forEach(([gx, gy], i) => {
          const x = sx(gx, w), y = sy(gy, h);
          if (i) paint.lineTo(x, y); else paint.moveTo(x, y);
        });
        paint.stroke();
        paint.setLineDash([]);
        const [hx, hy] = draft[0];
        paint.beginPath(); paint.arc(sx(hx, w), sy(hy, h), 5, 0, Math.PI * 2);
        paint.stroke();
      }
    }

    /* How far a press is from the segment a-b, in pixels. */
    const toSegment = (px, py, ax, ay, bx, by) => {
      const dx = bx - ax, dy = by - ay;
      const t = Math.max(0, Math.min(1,
        ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)));
      return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
    };

    cv.addEventListener("pointerdown", (e) => {
      if (!ctx.showing()) return;
      const w = cv.cssW, h = cv.cssH;
      const gate = shownGate();

      if (gate) {
        /* An existing gate takes the press: a vertex to move, an edge to
           grow through. One polygon per plot means empty space stays empty. */
        for (let i = 0; i < gate.vertices.length; i++) {
          const [gx, gy] = gate.vertices[i];
          if (Math.hypot(sx(gx, w) - e.offsetX, sy(gy, h) - e.offsetY) < REACH) {
            chosen = i;
            held = { gate, at: i };
            cv.setPointerCapture(e.pointerId);
            draw();
            return;
          }
        }
        for (let i = 0; i < gate.vertices.length; i++) {
          const [ax, ay] = gate.vertices[i];
          const [bx, by] = gate.vertices[(i + 1) % gate.vertices.length];
          if (toSegment(e.offsetX, e.offsetY,
            sx(ax, w), sy(ay, h), sx(bx, w), sy(by, h)) < REACH) {
            gate.vertices.splice(i + 1, 0, [invX(e.offsetX, w), invY(e.offsetY, h)]);
            chosen = i + 1;
            held = { gate, at: i + 1 };
            cv.setPointerCapture(e.pointerId);
            draw();
            return;
          }
        }
        return;
      }

      /* No gate on this pair: the press lays the polygon, and landing back on
         the first point closes it. */
      if (draft && draft.length >= 3) {
        const [gx, gy] = draft[0];
        if (Math.hypot(sx(gx, w) - e.offsetX, sy(gy, h) - e.offsetY) < REACH) {
          const vertices = draft;
          draft = null;
          commit([...ctx.gates(), { fx, fy, vertices }]);
          return;
        }
      }
      (draft ??= []).push([invX(e.offsetX, w), invY(e.offsetY, h)]);
      sayIt();
      draw();
    });

    cv.addEventListener("pointermove", (e) => {
      const w = cv.cssW, h = cv.cssH;
      if (held) {
        held.gate.vertices[held.at] = [invX(e.offsetX, w), invY(e.offsetY, h)];
        draw();
        return;
      }
      if (!ctx.showing()) return;
      let hit = null, best = 9;
      for (const c of ctx.cells()) {
        const d = Math.hypot(sx(cellFeature(c, fx), w) - e.offsetX,
          sy(cellFeature(c, fy), h) - e.offsetY);
        if (d < best) { best = d; hit = c; }
      }
      if (!hit) { tip.classList.remove("on"); return; }
      tip.classList.add("on");
      tip.innerHTML =
        `<b>cell</b> ${hit.id}<br><b>${fx}</b> ${cellFeature(hit, fx).toFixed(2)}<br>`
        + `<b>${fy}</b> ${cellFeature(hit, fy).toFixed(2)}<br>`
        + `<b>at</b> ${(hit.x / 1000).toFixed(2)}, ${(hit.y / 1000).toFixed(2)} mm`;
      tip.style.left = `${Math.min(e.offsetX + 14, w - 160)}px`;
      tip.style.top = `${Math.max(6, e.offsetY - 68)}px`;
    });

    cv.addEventListener("pointerup", (e) => {
      if (!held) return;
      held = null;
      cv.releasePointerCapture?.(e.pointerId);
      /* The drag settled: the run re-reads the intersection once, not per frame. */
      commit([...ctx.gates()]);
    });

    cv.addEventListener("pointerleave", () => tip.classList.remove("on"));

    window.addEventListener("keydown", (e) => {
      if (!host.isConnected || !ctx.showing()) return;
      if (e.key === "Escape" && draft) {
        draft = null;
        sayIt(); draw();
        return;
      }
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      const gate = shownGate();
      if (!gate || chosen < 0) return;
      e.preventDefault();
      /* A vertex goes; a polygon that cannot stand on two goes whole. */
      if (gate.vertices.length > 3) {
        gate.vertices.splice(chosen, 1);
        chosen = -1;
        commit([...ctx.gates()]);
      } else {
        chosen = -1;
        commit(ctx.gates().filter((g) => g !== gate));
      }
    });

    clear.addEventListener("click", () => { draft = null; chosen = -1; commit([]); });

    new ResizeObserver(() => draw()).observe(canvasHost);

    refreshPickers();
    renderList();
    sayIt();
    draw();
    return {
      redraw: () => { refreshPickers(); renderList(); sayIt(); draw(); },
    };
  },
};
