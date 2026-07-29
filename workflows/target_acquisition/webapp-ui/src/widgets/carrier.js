/**
 * The carrier configuration panel.
 *
 * Owns one panel and nothing else: it is handed a configuration and a way to
 * report a new one, and it never reaches for run state or for another widget.
 *
 * It draws no picture of its own. The carrier belongs on the canvas beside it,
 * and a second drawing of the same thing is a second thing to keep right — so
 * the controls live here and `drawOn` puts the carrier itself on the stage.
 * Both are in this file because they are one subject: change what a carrier is
 * and there is a single place that has to follow.
 *
 * It redraws itself rather than asking the frame to rebuild the panel. A
 * rebuild on every keystroke would destroy the field being typed into — the
 * defect this page has produced twice — so `sync()` writes new values into the
 * controls that are already there and leaves the focused one alone.
 */

import {
  CARRIER_TYPES, carrierType, fromPreset, matchingPreset, geometry,
  shapeName, maxRadius,
} from "../lib/carriers.js";

const SVG = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
};

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

/* Each type is drawn rather than named twice: the icon says slide or plate
   faster than the word under it does, and the word is there for when it does
   not. */
const ICONS = {
  slide: (g) => {
    g.append(svgEl("rect", { x: 3, y: 8, width: 22, height: 12, rx: 1.5, fill: "none", stroke: "currentColor", "stroke-width": 1.5 }));
    g.append(svgEl("rect", { x: 7, y: 11, width: 14, height: 6, rx: 0.5, fill: "currentColor", "fill-opacity": 0.14, stroke: "currentColor", "stroke-width": 0.8 }));
  },
  dish: (g) => {
    g.append(svgEl("circle", { cx: 14, cy: 14, r: 10, fill: "none", stroke: "currentColor", "stroke-width": 1.5 }));
    g.append(svgEl("circle", { cx: 14, cy: 14, r: 7, fill: "currentColor", "fill-opacity": 0.14, stroke: "currentColor", "stroke-width": 0.8 }));
  },
  wellplate: (g) => {
    g.append(svgEl("rect", { x: 3, y: 6, width: 22, height: 16, rx: 2, fill: "none", stroke: "currentColor", "stroke-width": 1.5 }));
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 6; c++) {
        g.append(svgEl("circle", { cx: 6.5 + c * 3, cy: 9.5 + r * 3, r: 1.1, fill: "currentColor", "fill-opacity": 0.2, stroke: "currentColor", "stroke-width": 0.5 }));
      }
    }
  },
  chamber: (g) => {
    g.append(svgEl("rect", { x: 3, y: 8, width: 22, height: 12, rx: 1.5, fill: "none", stroke: "currentColor", "stroke-width": 1.5 }));
    g.append(svgEl("rect", { x: 5.5, y: 10, width: 7, height: 8, rx: 1, fill: "currentColor", "fill-opacity": 0.14, stroke: "currentColor", "stroke-width": 0.8 }));
    g.append(svgEl("rect", { x: 15.5, y: 10, width: 7, height: 8, rx: 1, fill: "currentColor", "fill-opacity": 0.14, stroke: "currentColor", "stroke-width": 0.8 }));
  },
};

const typeIcon = (id) => {
  const svg = svgEl("svg", { width: 28, height: 28, viewBox: "0 0 28 28", fill: "none" });
  ICONS[id](svg);
  return svg;
};

/* Millimetres are the carrier's unit and micrometres are the stage's. This is
   the only place the two meet. */
const MM_UM = 1000;

export default {
  id: "carrier",
  label: "Carrier configuration",

  /** How much stage the carrier covers, for whatever has to frame it. */
  extentUm(config) {
    const g = geometry(config);
    return [g.width * MM_UM, g.height * MM_UM];
  },

  /**
   * Every imageable area the carrier declares, drawn in stage coordinates.
   * Under everything else: it is the frame the run happens inside, not a layer
   * of the run. Handed the projection rather than reaching for it, so this
   * knows nothing about how the canvas is panned.
   */
  drawOn(ctx, { config, toScreen, scale, colour }) {
    const g = geometry(config);
    const aw = config.w * MM_UM * scale;
    const ah = config.h * MM_UM * scale;
    if (aw < 1.5 || ah < 1.5) return;
    const rad = Math.min(g.corner * MM_UM * scale, aw / 2, ah / 2);
    ctx.save();
    ctx.strokeStyle = colour;
    ctx.globalAlpha = 0.8;
    ctx.lineWidth = Math.min(1.2, Math.max(0.4, aw * 0.02));
    for (let r = 0; r < config.rows; r++) {
      for (let c = 0; c < config.cols; c++) {
        const [x, y] = toScreen(c * g.pitchX * MM_UM, r * g.pitchY * MM_UM);
        ctx.beginPath();
        ctx.roundRect(x, y, aw, ah, rad);
        ctx.stroke();
      }
    }
    ctx.restore();
  },

  render(host, { config, locked, onChange }) {
    let cfg = { ...config };
    /* Whether the two halves of a pair move together is the operator's choice
       about this session, not part of the carrier — a saved configuration that
       remembered it would be describing the panel rather than the vessel. */
    let link = {
      grid: cfg.rows === cfg.cols,
      size: cfg.w === cfg.h,
      gap: cfg.gapX === cfg.gapY,
    };

    const card = el("div", "carrier-card");
    const controls = el("div", "carrier-controls");
    card.append(controls);
    host.append(card);

    const inputs = [];
    const commit = (patch) => {
      cfg = { ...cfg, ...patch };
      onChange(cfg);
      sync();
    };

    const types = el("div", "carrier-types");
    for (const t of CARRIER_TYPES) {
      const b = el("button", "carrier-type");
      b.type = "button";
      b.dataset.type = t.id;
      b.disabled = locked;
      b.append(typeIcon(t.id), el("span", null, t.label));
      b.addEventListener("click", () => {
        const next = fromPreset(t.id, carrierType(t.id).presets[0]);
        link = { grid: next.rows === next.cols, size: next.w === next.h, gap: true };
        commit(next);
        presets.replaceChildren(...presetOptions(t.id));
      });
      types.append(b);
    }
    controls.append(types);

    const presetOptions = (typeId) => [
      ...carrierType(typeId).presets.map((p, i) => new Option(p.label, String(i))),
      new Option("Custom", "-1"),
    ];

    const presetGroup = el("div", "carrier-group");
    const presets = el("select", "carrier-preset");
    presets.replaceChildren(...presetOptions(cfg.type));
    presets.addEventListener("change", () => {
      const i = Number(presets.value);
      if (i < 0) return;
      const next = fromPreset(cfg.type, carrierType(cfg.type).presets[i]);
      link = { grid: next.rows === next.cols, size: next.w === next.h, gap: true };
      commit(next);
    });
    const reset = el("button", "carrier-reset", "Reset");
    reset.type = "button";
    reset.addEventListener("click", () => {
      const next = fromPreset(cfg.type, carrierType(cfg.type).presets[0]);
      link = { grid: next.rows === next.cols, size: next.w === next.h, gap: true };
      commit(next);
    });
    presetGroup.append(presets, reset);
    controls.append(presetGroup);

    /* Three pairs, one shape: two numbers that may be tied together. Written
       once because a row of boxes that behaved slightly differently in each
       group would be three things to learn instead of one. */
    function pair({ label1, label2, get1, get2, set1, set2, min1, min2, max, step, decimals, key }) {
      const group = el("div", "carrier-group");
      const grid = el("div", "carrier-pair");
      grid.append(el("span", "carrier-label", label1), el("span", "carrier-label", label2), el("span"));

      const mk = (get, set, min) => {
        const i = document.createElement("input");
        i.type = "number";
        i.className = "carrier-num";
        i.step = String(step);
        if (max != null) i.max = String(max);
        i.addEventListener("input", () => {
          const v = parseFloat(i.value);
          if (i.value === "" || Number.isNaN(v)) return;
          set(v);
        });
        /* Clamping while typing fights the operator — "1" on its way to "12"
           is below a minimum of 6 and would be corrected out from under them.
           So the floor is applied when the field is left, not as it is used. */
        i.addEventListener("blur", () => {
          const v = parseFloat(i.value);
          set(Number.isNaN(v) ? min() : Math.max(min(), v));
          sync();
        });
        inputs.push({ i, get, decimals });
        return i;
      };

      const a = mk(get1, set1, min1);
      const b = mk(get2, set2, min2);
      const tie = el("button", "carrier-link");
      tie.type = "button";
      tie.dataset.key = key;
      tie.title = "Move both together";
      tie.addEventListener("click", () => {
        link[key] = !link[key];
        if (link[key]) set2(get1());
        commit({});
      });
      grid.append(a, b, tie);
      group.append(grid);
      controls.append(group);
      return { tie };
    }

    const ties = {};
    ties.grid = pair({
      label1: "ROWS", label2: "COLUMNS", key: "grid", step: 1, max: 50, decimals: 0,
      get1: () => cfg.rows, get2: () => cfg.cols, min1: () => 1, min2: () => 1,
      set1: (v) => commit(link.grid ? { rows: Math.round(v), cols: Math.round(v) } : { rows: Math.round(v) }),
      set2: (v) => commit(link.grid ? { rows: Math.round(v), cols: Math.round(v) } : { cols: Math.round(v) }),
    }).tie;

    ties.size = pair({
      label1: "WIDTH (mm)", label2: "HEIGHT (mm)", key: "size", step: 0.1, decimals: 2,
      get1: () => cfg.w, get2: () => cfg.h, min1: () => 0.1, min2: () => 0.1,
      set1: (v) => commit(link.size ? { w: v, h: v } : { w: v }),
      set2: (v) => commit(link.size ? { w: v, h: v } : { h: v }),
    }).tie;

    /* Pitch is centre to centre, which is what a plate's datasheet quotes and
       what the stage will be told. The gap is what is stored, because it is
       what stays meaningful when the area is resized. */
    ties.gap = pair({
      label1: "COLUMN PITCH (mm)", label2: "ROW PITCH (mm)", key: "gap", step: 0.1, decimals: 2,
      get1: () => cfg.w + cfg.gapX, get2: () => cfg.h + cfg.gapY,
      min1: () => cfg.w, min2: () => cfg.h,
      set1: (v) => {
        const g = Math.max(0, v - cfg.w);
        commit(link.gap ? { gapX: g, gapY: g } : { gapX: g });
      },
      set2: (v) => {
        const g = Math.max(0, v - cfg.h);
        commit(link.gap ? { gapX: g, gapY: g } : { gapY: g });
      },
    }).tie;

    const shapeGroup = el("div", "carrier-group");
    const shapeGrid = el("div", "carrier-pair");
    shapeGrid.append(
      el("span", "carrier-label", "CORNER RADIUS (mm)"),
      el("span", "carrier-label", "AREA (mm²)"),
      el("span"),
    );
    const cornerIn = document.createElement("input");
    cornerIn.type = "number";
    cornerIn.className = "carrier-num";
    cornerIn.step = "0.01";
    cornerIn.min = "0";
    cornerIn.addEventListener("input", () => {
      const v = parseFloat(cornerIn.value);
      if (cornerIn.value === "" || Number.isNaN(v)) return;
      const maxR = maxRadius(cfg);
      commit({ cornerRatio: maxR > 0 ? Math.min(Math.max(v, 0), maxR) / maxR : 0 });
    });
    const areaIn = document.createElement("input");
    areaIn.type = "number";
    areaIn.className = "carrier-num";
    areaIn.step = "0.01";
    areaIn.addEventListener("input", () => {
      const v = parseFloat(areaIn.value);
      if (areaIn.value === "" || Number.isNaN(v)) return;
      /* Area runs the other way through the same relation: the shortfall from
         a full rectangle is r²(4 − π), so the corner it implies is its root. */
      const lost = cfg.w * cfg.h - v;
      const r = lost > 0 ? Math.sqrt(lost / (4 - Math.PI)) : 0;
      const maxR = maxRadius(cfg);
      commit({ cornerRatio: maxR > 0 ? Math.min(Math.max(r / maxR, 0), 1) : 0 });
    });
    inputs.push({ i: cornerIn, get: () => geometry(cfg).corner, decimals: 2 });
    inputs.push({ i: areaIn, get: () => geometry(cfg).areaMm2, decimals: 2 });

    const shapeBtn = el("button", "carrier-shape");
    shapeBtn.type = "button";
    shapeBtn.title = "Square off, or round completely";
    shapeBtn.addEventListener("click", () => commit({ cornerRatio: cfg.cornerRatio >= 0.99 ? 0 : 1 }));
    shapeGrid.append(cornerIn, areaIn, shapeBtn);
    shapeGroup.append(shapeGrid);
    controls.append(shapeGroup);

    /* Where the run's own button goes: after the numbers that decide it and
       before the summary of what they came to, so applying reads as the end of
       the editing rather than a footnote under the result. */
    card.append(el("div", "carrier-action"));

    const stats = el("div", "carrier-stats");
    card.append(stats);

    function stat(label, value) {
      const d = el("div", "carrier-stat");
      d.append(el("span", "carrier-stat-label", label), el("span", "carrier-stat-value", value));
      return d;
    }

    function sync() {
      const g = geometry(cfg);
      for (const { i, get, decimals } of inputs) {
        if (document.activeElement === i) continue;
        const v = get();
        i.value = decimals ? v.toFixed(decimals) : String(v);
      }
      cornerIn.max = String(maxRadius(cfg));
      for (const b of types.querySelectorAll(".carrier-type")) {
        b.classList.toggle("on", b.dataset.type === cfg.type);
      }
      for (const [key, b] of Object.entries(ties)) b.classList.toggle("on", link[key]);
      presets.value = String(matchingPreset(cfg));
      shapeBtn.classList.toggle("round", cfg.cornerRatio >= 0.99);
      for (const i of card.querySelectorAll("input, select, button")) i.disabled = locked;
      stats.replaceChildren(
        stat("Carrier", `${g.width.toFixed(1)} × ${g.height.toFixed(1)} mm`),
        stat("Areas", String(g.areas)),
        stat("Layout", `${cfg.rows}×${cfg.cols}`),
        stat("Shape", shapeName(cfg)),
      );
    }

    sync();
  },
};
