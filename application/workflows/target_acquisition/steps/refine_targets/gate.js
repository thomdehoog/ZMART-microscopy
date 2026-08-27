/**
 * Step 7's channel — the scatter the targets are gated on.
 *
 * Discovery finds every cell; this is where the operator says which of them
 * are worth imaging. Each detected cell is a point — area across, mean
 * intensity up — and dragging a rectangle over them takes those inside as the
 * targets. The gated ones light up here and on the canvas at the same time,
 * because they are the same cells seen two ways.
 *
 * The widget owns its markup, its canvas and its gestures. What it reads and
 * what it changes arrive in `ctx`; it never reaches for the page around it.
 */

/** Room for the axes, in pixels. */
const PAD = { l: 62, r: 18, t: 18, b: 46 };

/** A drag shorter than this in either direction is a press, not a gate. */
const A_DRAG_AT_LEAST = 6;

/**
 * Which cells a gate takes: the detected ones inside it, area and intensity
 * both. The one rule of this step, so it is said once and can be tested
 * without a canvas.
 */
export function cellsInGate(cells, detected, gate) {
  if (!gate) return new Set();
  return new Set(cells
    .filter((c) => detected.has(c.id)
      && c.area >= gate.aLo && c.area <= gate.aHi
      && c.intensity >= gate.iLo && c.intensity <= gate.iHi)
    .map((c) => c.id));
}

/** What the readout under the scatter says. */
export function gateReadout(gate, gatedCount, detectedCount) {
  if (!gate) return "drag a rectangle to gate";
  return `${gatedCount} of ${detectedCount} detected gated`
    + ` · area ${gate.aLo.toFixed(0)}–${gate.aHi.toFixed(0)} µm²`
    + ` · int ${gate.iLo.toFixed(2)}–${gate.iHi.toFixed(2)}`;
}

export default {
  id: "select",
  label: "Refine Targets",

  /**
   * Build the channel and draw the run into it.
   *
   * `ctx` carries:
   *   `cells()` `detected()` `gated()` `acquired()` `gate()`  what to draw
   *   `showing()`      whether discovery has run, so there is anything to gate
   *   `areaRange`      the axis across, as the sample defines it
   *   `setGate(gate, ids)`  the operator has gated; the run takes both
   *   `sizeCanvas(cv)` `css(name)`  the page's canvas plumbing
   *
   * Returns a handle whose `redraw()` draws it again — for a theme change, or
   * when the run has moved on and the same points mean something new.
   */
  mount(host, ctx) {
    const [AREA_LO, AREA_HI] = ctx.areaRange;

    const side = document.createElement("div");
    side.className = "analysis-side";

    const head = document.createElement("div");
    head.className = "side-head";
    head.append("Gate");
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "ghost tiny";
    clear.id = "clear-gate";
    clear.textContent = "Clear gate";
    head.append(clear);

    const legend = document.createElement("div");
    legend.className = "legend analysis-legend";
    for (const [ink, what] of [["--mark-context", "all cells"],
      ["--mark-gated", "gated"], ["--mark-acquired", "acquired"]]) {
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

    side.append(head, legend, wrap, readout);
    host.append(side);

    /* Where a cell sits on the scatter, and back again for a gate drawn on
       it. Four lines rather than a projection object: this picture is two
       axes and never pans or zooms. */
    const sx = (area, w) => PAD.l + ((area - AREA_LO) / (AREA_HI - AREA_LO)) * (w - PAD.l - PAD.r);
    const sy = (inten, h) => (h - PAD.b) - inten * (h - PAD.t - PAD.b);
    const invX = (px, w) => AREA_LO + ((px - PAD.l) / (w - PAD.l - PAD.r)) * (AREA_HI - AREA_LO);
    const invY = (py, h) => ((h - PAD.b) - py) / (h - PAD.t - PAD.b);

    const drag = { active: false, x0: 0, y0: 0, x1: 0, y1: 0 };

    const sayTheGate = () => {
      readout.textContent = gateReadout(ctx.gate(), ctx.gated().size, ctx.detected().size);
    };

    function draw() {
      if (!ctx.sizeCanvas(cv)) return;
      const paint = cv.getContext("2d");
      const w = cv.cssW, h = cv.cssH;
      paint.clearRect(0, 0, w, h);
      paint.fillStyle = ctx.css("--screen");
      paint.fillRect(0, 0, w, h);

      // recessive grid
      paint.strokeStyle = ctx.css("--line");
      paint.lineWidth = 1;
      paint.fillStyle = ctx.css("--ink-3");
      paint.font = "11.5px ui-monospace, Consolas, monospace";
      paint.textAlign = "right";
      for (let v = 0; v <= 1.0001; v += 0.25) {
        const y = sy(v, h);
        paint.beginPath(); paint.moveTo(PAD.l, y); paint.lineTo(w - PAD.r, y); paint.stroke();
        paint.fillText(v.toFixed(2), PAD.l - 9, y + 4);
      }
      paint.textAlign = "center";
      for (let a = 100; a <= AREA_HI; a += 100) {
        const x = sx(a, w);
        paint.beginPath(); paint.moveTo(x, PAD.t); paint.lineTo(x, h - PAD.b); paint.stroke();
        paint.fillText(String(a), x, h - PAD.b + 18);
      }

      // axis titles
      paint.fillStyle = ctx.css("--ink-2");
      paint.font = "12.5px system-ui, sans-serif";
      paint.fillText("cell area (µm²)", (PAD.l + w - PAD.r) / 2, h - 12);
      paint.save();
      paint.translate(16, (PAD.t + h - PAD.b) / 2);
      paint.rotate(-Math.PI / 2);
      paint.fillText("mean intensity · ch2", 0, 0);
      paint.restore();

      const cells = ctx.cells(), detected = ctx.detected(), gated = ctx.gated();

      // the cells that were found but not taken, quietly
      paint.fillStyle = ctx.css("--mark-context");
      paint.globalAlpha = 0.5;
      paint.beginPath();
      for (const c of cells) {
        if (!detected.has(c.id) || gated.has(c.id)) continue;
        const x = sx(c.area, w), y = sy(c.intensity, h);
        paint.moveTo(x + 2, y); paint.arc(x, y, 2, 0, Math.PI * 2);
      }
      paint.fill();
      paint.globalAlpha = 1;

      // the gated ones — larger and ringed as well as coloured
      const acquired = new Set(ctx.acquired());
      for (const c of cells) {
        if (!gated.has(c.id)) continue;
        const x = sx(c.area, w), y = sy(c.intensity, h);
        const taken = acquired.has(c.id);
        paint.beginPath(); paint.arc(x, y, taken ? 4.6 : 3.4, 0, Math.PI * 2);
        paint.fillStyle = taken ? "#16a34a" : "#0284c7";
        paint.fill();
        paint.lineWidth = 2; paint.strokeStyle = ctx.css("--screen"); paint.stroke();
      }

      // the gate itself, and the rectangle being drawn
      const gate = ctx.gate();
      if (gate) {
        const x0 = sx(gate.aLo, w), x1 = sx(gate.aHi, w);
        const y0 = sy(gate.iHi, h), y1 = sy(gate.iLo, h);
        paint.strokeStyle = "#0284c7"; paint.lineWidth = 1.5;
        paint.setLineDash([5, 4]);
        paint.strokeRect(x0, y0, x1 - x0, y1 - y0);
        paint.setLineDash([]);
      }
      if (drag.active) {
        paint.strokeStyle = ctx.css("--accent"); paint.lineWidth = 1.5;
        paint.setLineDash([4, 3]);
        paint.strokeRect(Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1),
          Math.abs(drag.x1 - drag.x0), Math.abs(drag.y1 - drag.y0));
        paint.setLineDash([]);
      }
    }

    const gateTo = (g) => {
      ctx.setGate(g, cellsInGate(ctx.cells(), ctx.detected(), g));
      sayTheGate();
      draw();
    };

    cv.addEventListener("pointerdown", (e) => {
      if (!ctx.showing()) return;
      drag.active = true;
      drag.x0 = drag.x1 = e.offsetX; drag.y0 = drag.y1 = e.offsetY;
      cv.setPointerCapture(e.pointerId);
    });

    cv.addEventListener("pointermove", (e) => {
      const w = cv.cssW, h = cv.cssH;
      if (drag.active) {
        drag.x1 = e.offsetX; drag.y1 = e.offsetY;
        draw();
        return;
      }
      if (!ctx.showing()) return;
      // the nearest detected cell, if the pointer is near one at all
      let hit = null, best = 9;
      for (const c of ctx.cells()) {
        if (!ctx.detected().has(c.id)) continue;
        const d = Math.hypot(sx(c.area, w) - e.offsetX, sy(c.intensity, h) - e.offsetY);
        if (d < best) { best = d; hit = c; }
      }
      if (!hit) { tip.classList.remove("on"); return; }
      tip.classList.add("on");
      tip.innerHTML =
        `<b>cell</b> ${hit.id}<br><b>area</b> ${hit.area.toFixed(0)} µm²<br>`
        + `<b>int</b> ${hit.intensity.toFixed(2)}<br>`
        + `<b>at</b> ${(hit.x / 1000).toFixed(2)}, ${(hit.y / 1000).toFixed(2)} mm`;
      tip.style.left = `${Math.min(e.offsetX + 14, w - 160)}px`;
      tip.style.top = `${Math.max(6, e.offsetY - 68)}px`;
    });

    cv.addEventListener("pointerup", (e) => {
      if (!drag.active) return;
      drag.active = false;
      cv.releasePointerCapture?.(e.pointerId);
      const w = cv.cssW, h = cv.cssH;
      /* A press is not a gate: dragging is how a gate is drawn, and a stray
         click should leave the one already there alone. */
      if (Math.abs(drag.x1 - drag.x0) < A_DRAG_AT_LEAST
        || Math.abs(drag.y1 - drag.y0) < A_DRAG_AT_LEAST) { draw(); return; }
      gateTo({
        aLo: invX(Math.min(drag.x0, drag.x1), w), aHi: invX(Math.max(drag.x0, drag.x1), w),
        iLo: invY(Math.max(drag.y0, drag.y1), h), iHi: invY(Math.min(drag.y0, drag.y1), h),
      });
    });

    cv.addEventListener("pointerleave", () => tip.classList.remove("on"));
    clear.addEventListener("click", () => gateTo(null));

    /* Its own size is its own business: the channel is dragged wider and
       narrower by the operator, and a canvas has to be told. */
    new ResizeObserver(() => draw()).observe(canvasHost);

    sayTheGate();
    draw();
    return { redraw: () => { sayTheGate(); draw(); } };
  },
};
