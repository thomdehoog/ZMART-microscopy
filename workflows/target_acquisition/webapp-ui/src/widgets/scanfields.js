/**
 * The scan fields editor.
 *
 * Owns one channel beside the canvas and the editing that happens on the
 * canvas itself. It never reaches for run state: it is handed the fields, the
 * carrier they sit in and the presets they can be taken with, and reports a
 * new list back.
 *
 * The split inside this file follows what outlives what. `drawOn` is the plan
 * — the fields and their tiles — and stays on the canvas for the rest of the
 * run. Everything the editor adds on top of that (grips, marquee, the shape
 * being drawn) belongs to standing on the step, so it is drawn by the handle
 * `render` returns and disappears with it.
 *
 * Two ways to make fields, because they answer different questions. Geometry
 * is for a sample you are looking at: draw round what is there. Grid is for a
 * carrier you already know: every area gets the same block of positions, taken
 * from the carrier rather than typed, so changing the plate changes the plan.
 */

import { centres, geometry } from "../lib/carriers.js";
import {
  block, bounds, boxesOverlap, centroid, contains, edges, handles, isPointLike,
  normalise, rotatePoint, tiles, topCentre,
} from "../lib/scanfields.js";

const MM_UM = 1000;

/* Distinct hues rather than a ramp: a preset is a name, not a quantity, and
   two fields taken with different presets have to be told apart at a glance. */
const PRESET_INK = ["#0284c7", "#b91c1c", "#16a34a", "#b45309", "#7c3aed", "#0e7490"];

const TOOLS = [
  { id: "pointer", key: "v", glyph: "↖", label: "Select", why: "Select, move, resize and rotate" },
  { id: "point", key: ".", glyph: "+", label: "Point", why: "Place one position" },
  { id: "rectangle", key: "r", glyph: "▭", label: "Rectangle", why: "Drag a rectangular region" },
  { id: "triangle", key: "t", glyph: "△", label: "Triangle", why: "Drag a triangular region" },
  { id: "ellipse", key: "e", glyph: "◯", label: "Ellipse", why: "Drag to draw · Shift for a circle" },
  { id: "polygon", key: "p", glyph: "⬠", label: "Polygon", why: "Click vertices · click the first to close" },
];

const MODES = [
  { id: "geometry", glyph: "▭", label: "DRAW", why: "Draw regions over what is there" },
  { id: "grid", glyph: "⊞", label: "GRID", why: "The same block of positions in every area" },
];

/* How a field is drawn, and how it says it is being talked about. Twice the
   line and no dash: a shape under the pointer or in the selection is the same
   shape, so it should not change into a different kind of drawing — it should
   get heavier. Dashes read as provisional, which is what the marquee and the
   shape being dragged out actually are. */
const FIELD_W = 1.6;
const MARKED_W = FIELD_W * 2;

/* Screen pixels, not micrometres: a grip is as easy to hit zoomed out as in. */
const HIT_PX = 12;
const CLOSE_PX = 18;
const MIN_DRAG_UM = 100;
const NUDGE_UM = 100;
const HISTORY = 60;

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

let uid = 0;
const nextId = () => `f${++uid}`;

export const presetInk = (presets, id) => {
  const i = presets.findIndex((p) => p.id === id);
  return PRESET_INK[(i < 0 ? 0 : i) % PRESET_INK.length];
};

/** Every tile the plan visits, per field, with the preset that takes it. */
export function plan(fields, presets) {
  const out = [];
  for (const f of fields) {
    const preset = presets.find((p) => p.id === f.presetId) ?? presets[0];
    if (!preset) continue;
    for (const t of tiles(f, preset.frameUm, f.overlap ?? 0)) {
      out.push({ ...t, frameUm: preset.frameUm, presetId: preset.id, fieldId: f.id });
    }
  }
  return out;
}

export default {
  id: "scanfields",
  label: "Initial scanfields",

  plan,

  /**
   * The plan on the stage: every field's outline and every tile it visits,
   * drawn from the carrier's own zero. This is what the run is going to do, so
   * it outlives the step that drew it.
   */
  drawOn(ctx, { fields, presets, toScreen, scale, dim = false }) {
    if (!fields?.length) return;
    ctx.save();
    ctx.globalAlpha = dim ? 0.45 : 1;

    for (const t of plan(fields, presets)) {
      const [x, y] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      const s = t.frameUm * scale;
      if (s < 1.2) continue;
      ctx.fillStyle = presetInk(presets, t.presetId);
      ctx.globalAlpha = (dim ? 0.45 : 1) * 0.12;
      ctx.fillRect(x, y, s, s);
      ctx.globalAlpha = dim ? 0.45 : 1;
      ctx.strokeStyle = presetInk(presets, t.presetId);
      ctx.lineWidth = 0.8;
      ctx.strokeRect(x, y, s, s);
    }

    for (const f of fields) {
      const ink = presetInk(presets, f.presetId);
      if (isPointLike(f.type)) {
        const [x, y] = toScreen(f.x, f.y);
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = ink;
        ctx.fill();
        continue;
      }
      ctx.strokeStyle = ink;
      ctx.lineWidth = FIELD_W;
      traceField(ctx, f, toScreen);
      ctx.stroke();
    }
    ctx.restore();
  },

  /**
   * Mount the channel. Returns the handle the frame keeps while the step is
   * selected: what to draw on top of the plan, and where the pointer went.
   */
  render(host, { fields, carrier, presets, locked, onChange }) {
    const ed = {
      tool: "pointer",
      mode: "geometry",
      fields: fields.map(normalise),
      selected: new Set(),
      drag: null,
      drawing: null,
      poly: [],
      marquee: null,
      hover: null,
      shift: false,
      past: [],
      future: [],
      presetId: presets[0]?.id ?? null,
      rows: 3,
      cols: 3,
      spacingX: 0,
      spacingY: 0,
    };

    const preset = () => presets.find((p) => p.id === ed.presetId) ?? presets[0];
    const frameUm = () => preset()?.frameUm ?? 1000;
    // spacing is a floor, not a free number: positions may be spread apart,
    // never overlapped, so the frame is what it cannot go below
    const pitch = () => [
      Math.max(ed.spacingX || 0, frameUm()),
      Math.max(ed.spacingY || 0, frameUm()),
    ];

    const commit = (next, { history = true } = {}) => {
      if (history) {
        ed.past = [...ed.past.slice(-(HISTORY - 1)), ed.fields];
        ed.future = [];
      }
      ed.fields = next;
      onChange(ed.fields);
      sync();
    };

    const card = el("div", "sf-card");
    const controls = el("div", "sf-controls");
    card.append(controls);
    host.append(card);

    /* Which of the two ways to say it, before anything else, because it
       decides what the rest of the column is for. */
    const modeRow = el("div", "sf-modes");
    for (const m of MODES) {
      const b = el("button", "sf-mode");
      b.type = "button";
      b.dataset.mode = m.id;
      b.title = m.why;
      b.append(el("span", "sf-mode-icon", m.glyph), el("span", "sf-mode-label", m.label));
      b.addEventListener("click", () => {
        ed.mode = m.id;
        if (m.id !== "geometry") { ed.tool = "pointer"; ed.poly = []; ed.drawing = null; }
        sync();
      });
      modeRow.append(b);
    }
    controls.append(modeRow);

    const group = (title) => {
      const g = el("div", "sf-group");
      g.append(el("div", "sf-group-title", title));
      controls.append(g);
      return g;
    };

    /* Select is not among them. It is where the panel returns after every
       shape, so a button for it would be a button for the state you are
       already in — Esc says it too. */
    const geomGroup = group("Geometries");
    const toolRow = el("div", "sf-tools");
    for (const t of TOOLS.filter((x) => x.id !== "pointer")) {
      const b = el("button", "sf-tool");
      b.type = "button";
      b.dataset.tool = t.id;
      b.title = `${t.label} (${t.key}) — ${t.why}`;
      b.append(el("span", "sf-glyph", t.glyph));
      b.addEventListener("click", () => { ed.tool = t.id; ed.poly = []; sync(); });
      toolRow.append(b);
    }
    geomGroup.append(toolRow);

    const gridGroup = group("Positions per compartment");
    const gridPair = el("div", "sf-pair");
    gridGroup.append(gridPair);
    const num = (label, get, set, min) => {
      const wrap = el("div", "sf-num");
      wrap.append(el("span", "sf-num-label", label));
      const i = document.createElement("input");
      i.type = "number";
      i.addEventListener("input", () => {
        const v = parseFloat(i.value);
        if (i.value === "" || Number.isNaN(v)) return;
        set(v);
        sync({ keep: i });
      });
      /* Clamped when the field is left, not while it is being typed in: a 1 on
         its way to a 1600 is below the floor and would be corrected out from
         under the operator. */
      i.addEventListener("blur", () => { set(Math.max(min(), parseFloat(i.value) || min())); sync(); });
      wrap.append(i);
      gridPair.append(wrap);
      return { i, get, min };
    };
    const gridInputs = [
      num("ROWS", () => ed.rows, (v) => { ed.rows = Math.max(1, Math.round(v)); }, () => 1),
      num("COLUMNS", () => ed.cols, (v) => { ed.cols = Math.max(1, Math.round(v)); }, () => 1),
      num("SPACING X (µm)", () => pitch()[0], (v) => { ed.spacingX = v; }, frameUm),
      num("SPACING Y (µm)", () => pitch()[1], (v) => { ed.spacingY = v; }, frameUm),
    ];
    const applyGrid = el("button", "sf-flat sf-apply-grid", "Apply");
    applyGrid.type = "button";
    applyGrid.addEventListener("click", () => {
      const [px, py] = pitch();
      const made = [];
      for (const area of centres(carrier)) {
        for (const p of block({ x: area.x * MM_UM, y: area.y * MM_UM }, ed.rows, ed.cols, px, py)) {
          made.push({ id: nextId(), type: "point", presetId: ed.presetId, source: "grid", ...p });
        }
      }
      /* Applying replaces what the last Apply made rather than stacking on it.
         Anything drawn or placed by hand is left alone — it was not the grid's
         to remove. */
      commit([...ed.fields.filter((f) => f.source !== "grid"), ...made]);
      ed.selected = new Set();
    });
    gridGroup.append(el("div", "sf-row").appendChild(applyGrid).parentElement);

    /* Every preset the run recorded, as the list it is — one press says what
       the next field is taken with, and the dot is the colour it will be drawn
       in, so the canvas and this column agree without a legend. */
    const presetGroup = group("Acquisition preset");
    const presetList = el("div", "sf-presets");
    presetGroup.append(presetList);
    const presetRows = presets.map((p) => {
      const b = el("button", "sf-preset");
      b.type = "button";
      b.dataset.preset = p.id;
      const dot = el("span", "sf-dot");
      dot.style.background = presetInk(presets, p.id);
      b.append(dot, el("span", "sf-preset-name", p.name),
        el("span", "sf-preset-frame", `${p.frameUm} µm`));
      b.addEventListener("click", () => { ed.presetId = p.id; sync(); });
      presetList.append(b);
      return b;
    });
    const applyRow = el("div", "sf-row");
    const applyTo = (which) => {
      const ids = which === "all" ? new Set(ed.fields.map((f) => f.id)) : ed.selected;
      if (!ids.size) return;
      commit(ed.fields.map((f) => (ids.has(f.id) ? { ...f, presetId: ed.presetId } : f)));
    };
    const applySel = el("button", "sf-flat", "Apply to selected");
    applySel.type = "button";
    applySel.addEventListener("click", () => applyTo("selection"));
    const applyAll = el("button", "sf-flat", "Apply to all");
    applyAll.type = "button";
    applyAll.addEventListener("click", () => applyTo("all"));
    applyRow.append(applySel, applyAll);
    presetGroup.append(applyRow);

    /* Folded away, because the shortcuts are reference rather than workflow —
       and where a control has no button, this is the only place it is said. */
    const keysBox = el("div", "sf-keys");
    const keysHead = el("button", "sf-keys-head");
    keysHead.type = "button";
    keysHead.append(el("span", null, "Show controls"), el("span", "sf-chev", "⌄"));
    const keysBody = el("div", "sf-keys-body");
    keysBody.hidden = true;
    for (const [key, what] of [
      ["Drag", "move — pan on empty"],
      ["Shift+drag", "circle or square — marquee on empty"],
      ["Shift+click", "add to selection"],
      ["Shift+rotate", "45° snap"],
      ["Wheel", "zoom"],
      ["Arrows", "nudge — Shift coarse"],
      ["Ctrl+Z / Y", "undo, redo"],
      ["Ctrl+A", "select all"],
      ["Delete", "remove"],
      ["Esc", "deselect"],
    ]) {
      const row = el("div", "sf-key");
      row.append(el("span", "sf-key-name", key), el("span", "sf-key-what", what));
      keysBody.append(row);
    }
    keysHead.addEventListener("click", () => {
      keysBody.hidden = !keysBody.hidden;
      keysBox.classList.toggle("open", !keysBody.hidden);
    });
    keysBox.append(keysHead, keysBody);
    controls.append(keysBox);

    const readout = el("div", "sf-readout");
    card.append(readout);

    function undo() {
      if (locked || !ed.past.length) return;
      ed.future = [...ed.future, ed.fields];
      ed.fields = ed.past[ed.past.length - 1];
      ed.past = ed.past.slice(0, -1);
      onChange(ed.fields);
      sync();
    }

    function redo() {
      if (locked || !ed.future.length) return;
      ed.past = [...ed.past, ed.fields];
      ed.fields = ed.future[ed.future.length - 1];
      ed.future = ed.future.slice(0, -1);
      onChange(ed.fields);
      sync();
    }

    function removeSelected() {
      if (locked || !ed.selected.size) return;
      commit(ed.fields.filter((f) => !ed.selected.has(f.id)));
      ed.selected = new Set();
    }

    function sync({ keep = null } = {}) {
      for (const b of modeRow.children) b.classList.toggle("on", b.dataset.mode === ed.mode);
      for (const b of toolRow.children) b.classList.toggle("on", b.dataset.tool === ed.tool);
      geomGroup.hidden = ed.mode !== "geometry";
      gridGroup.hidden = ed.mode !== "grid";
      for (const b of presetRows) b.classList.toggle("on", b.dataset.preset === ed.presetId);
      for (const { i, get } of gridInputs) {
        if (i !== keep && document.activeElement !== i) i.value = String(Math.round(get()));
      }
      applySel.disabled = locked || !ed.selected.size;
      applyAll.disabled = locked || !ed.fields.length;
      applyGrid.disabled = locked;
      for (const c of card.querySelectorAll("button, select, input")) {
        if (locked) c.disabled = true;
      }

      const positions = plan(ed.fields, presets).length;
      const regions = ed.fields.filter((f) => !isPointLike(f.type)).length;
      const points = ed.fields.length - regions;
      readout.textContent = ed.fields.length
        ? `${positions} position${positions === 1 ? "" : "s"} · ${regions} region${regions === 1 ? "" : "s"} · ${points} point${points === 1 ? "" : "s"}`
        : "nothing to scan yet";
    }

    const keydown = (e) => {
      if (locked) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (e.key === "Shift") ed.shift = true;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === "z") {
        e.preventDefault();
        (e.shiftKey ? redo : undo)();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && k === "y") { e.preventDefault(); redo(); return; }
      if ((e.ctrlKey || e.metaKey) && k === "a") {
        e.preventDefault();
        ed.selected = new Set(ed.fields.map((f) => f.id));
        sync();
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeSelected(); return; }
      if (e.key === "Escape") { ed.poly = []; ed.drawing = null; ed.tool = "pointer"; ed.selected = new Set(); sync(); return; }
      if (ed.mode === "geometry" && !e.ctrlKey && !e.metaKey) {
        const t = TOOLS.find((x) => x.key === (e.key === "." ? "." : k));
        if (t) { ed.tool = t.id; ed.poly = []; sync(); return; }
      }
      const nudge = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (nudge && ed.selected.size) {
        e.preventDefault();
        const d = NUDGE_UM * (e.shiftKey ? 5 : 1);
        commit(ed.fields.map((f) =>
          (ed.selected.has(f.id) ? move(f, nudge[0] * d, nudge[1] * d) : f)));
      }
    };
    const keyup = (e) => { if (e.key === "Shift") ed.shift = false; };
    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);

    sync();

    return {
      destroy() {
        window.removeEventListener("keydown", keydown);
        window.removeEventListener("keyup", keyup);
      },

      /* Is the pointer over something it could pick? Only true while nothing
         is being dragged: once a field is held, whether it was pickable is no
         longer the question. */
      overField() {
        return !!ed.hover && !ed.drag && !ed.drawing && !ed.marquee;
      },

      /** Grips, marquee and the shape being drawn — the editing, not the plan. */
      drawChrome(ctx, { toScreen, scale }) {
        ctx.save();
        /* Marked means selected or under the pointer, and both look the same:
           pointing at a shape and having picked it are the same claim about
           which one is being talked about, so clicking should not change how
           it reads — only what happens next. */
        for (const f of ed.fields) {
          if (!ed.selected.has(f.id) && ed.hover !== f.id) continue;
          ctx.strokeStyle = presetInk(presets, f.presetId);
          ctx.lineWidth = MARKED_W;
          if (isPointLike(f.type)) {
            const [x, y] = toScreen(f.x, f.y);
            ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.stroke();
          } else {
            traceField(ctx, f, toScreen);
            ctx.stroke();
          }
        }

        const only = single();
        if (only && !isPointLike(only.type)) {
          const rot = only.rotation || 0, c = centroid(only);
          for (const h of handles(only)) {
            const w = rotatePoint(h.x, h.y, c.x, c.y, rot);
            const [x, y] = toScreen(w.x, w.y);
            ctx.beginPath();
            ctx.rect(x - 4, y - 4, 8, 8);
            ctx.fillStyle = "#ffffff"; ctx.fill();
            ctx.lineWidth = 1.5; ctx.strokeStyle = "#0284c7"; ctx.stroke();
          }
          const grip = rotationGrip(only, scale);
          const [gx, gy] = toScreen(grip.x, grip.y);
          const top = rotatePoint(topCentre(only).x, topCentre(only).y, c.x, c.y, rot);
          const [tx, ty] = toScreen(top.x, top.y);
          ctx.beginPath();
          ctx.moveTo(tx, ty); ctx.lineTo(gx, gy);
          ctx.strokeStyle = "#0284c7"; ctx.lineWidth = 1; ctx.stroke();
          ctx.beginPath(); ctx.arc(gx, gy, 5, 0, Math.PI * 2);
          ctx.fillStyle = "#0284c7"; ctx.fill();
        }

        if (ed.drawing) {
          const g = previewOf(ed.drawing, armed(), ed.shift);
          if (g) {
            ctx.strokeStyle = "#0284c7"; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
            traceField(ctx, g, toScreen);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }

        if (ed.poly.length) {
          ctx.strokeStyle = "#0284c7"; ctx.lineWidth = 1.5;
          ctx.beginPath();
          ed.poly.forEach((p, i) => {
            const [x, y] = toScreen(p.x, p.y);
            i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
          });
          ctx.stroke();
          for (const p of ed.poly) {
            const [x, y] = toScreen(p.x, p.y);
            ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2);
            ctx.fillStyle = "#0284c7"; ctx.fill();
          }
        }

        if (ed.marquee) {
          const [x0, y0] = toScreen(Math.min(ed.marquee.sx, ed.marquee.cx), Math.min(ed.marquee.sy, ed.marquee.cy));
          const [x1, y1] = toScreen(Math.max(ed.marquee.sx, ed.marquee.cx), Math.max(ed.marquee.sy, ed.marquee.cy));
          ctx.strokeStyle = "#0284c7"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
          ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
          ctx.setLineDash([]);
        }
        ctx.restore();
      },

      /**
       * Where the pointer went, in carrier coordinates. Answers true when the
       * editor took it, so the canvas only pans when nothing here wanted it.
       */
      pointer(kind, { x, y, shift, scale }) {
        if (locked) return false;
        ed.shift = shift;
        if (kind === "down") return down(x, y, scale);
        if (kind === "move") return moveTo(x, y, scale);
        if (kind === "up") return up();
        if (kind === "leave") {
          const had = ed.hover;
          ed.hover = null;
          return had ? "redraw" : false;
        }
        return false;
      },
    };

    function single() {
      if (ed.selected.size !== 1) return null;
      const id = [...ed.selected][0];
      return ed.fields.find((f) => f.id === id) ?? null;
    }

    function rotationGrip(f, scale) {
      const c = centroid(f), rot = f.rotation || 0;
      const t = topCentre(f);
      return rotatePoint(t.x, t.y - 26 / scale, c.x, c.y, rot);
    }

    function hitField(x, y, scale) {
      const near = HIT_PX / scale;
      for (let i = ed.fields.length - 1; i >= 0; i--) {
        const f = ed.fields[i];
        if (isPointLike(f.type)) {
          if (Math.hypot(x - f.x, y - f.y) < Math.max(near, 200)) return f;
        } else if (contains(x, y, f)) return f;
      }
      return null;
    }

    function hitHandle(x, y, scale) {
      const f = single();
      if (!f || armed() !== "pointer" || isPointLike(f.type)) return null;
      const near = HIT_PX / scale;
      const grip = rotationGrip(f, scale);
      if (Math.hypot(x - grip.x, y - grip.y) < near) return { kind: "rotate", field: f };
      const c = centroid(f), rot = f.rotation || 0;
      for (const h of handles(f)) {
        const w = rotatePoint(h.x, h.y, c.x, c.y, rot);
        if (Math.hypot(x - w.x, y - w.y) < near) {
          return { kind: "resize", field: f, handle: h.id, index: h.index };
        }
      }
      return null;
    }

    /* Which tool is armed. Only the drawing mode arms one — the other mode
       hides the tools rather than disabling the canvas, so selecting, moving,
       resizing and the marquee go on working on whatever the grid just put
       down. A mode is about what can be made, not about whether what is
       already there can be touched. */
    function armed() {
      return ed.mode === "geometry" ? ed.tool : "pointer";
    }

    function down(x, y, scale) {
      const tool = armed();
      if (tool === "polygon") {
        if (ed.poly.length >= 3) {
          const d = Math.hypot(x - ed.poly[0].x, y - ed.poly[0].y) * scale;
          if (d < CLOSE_PX) {
            const f = { id: nextId(), type: "polygon", presetId: ed.presetId, points: [...ed.poly], rotation: 0 };
            ed.poly = [];
            commit([...ed.fields, f]);
            ed.selected = new Set([f.id]);
            sync();
            return true;
          }
        }
        ed.poly = [...ed.poly, { x, y }];
        sync();
        return true;
      }

      if (tool === "point") {
        const f = { id: nextId(), type: "point", presetId: ed.presetId, x, y };
        commit([...ed.fields, f]);
        ed.selected = new Set([f.id]);
        return true;
      }

      if (tool !== "pointer") {
        ed.drawing = { sx: x, sy: y, cx: x, cy: y };
        return true;
      }

      const grip = hitHandle(x, y, scale);
      if (grip) {
        const c = centroid(grip.field);
        ed.drag = grip.kind === "rotate"
          ? { kind: "rotate", id: grip.field.id, cx: c.x, cy: c.y, from: Math.atan2(y - c.y, x - c.x), start: grip.field.rotation || 0 }
          : { kind: "resize", id: grip.field.id, handle: grip.handle, index: grip.index, start: grip.field };
        ed.past = [...ed.past.slice(-(HISTORY - 1)), ed.fields];
        ed.future = [];
        return true;
      }

      const hit = hitField(x, y, scale);
      if (hit && ed.shift) {
        const next = new Set(ed.selected);
        next.has(hit.id) ? next.delete(hit.id) : next.add(hit.id);
        ed.selected = next;
        sync();
        return true;
      }
      if (hit) {
        if (!ed.selected.has(hit.id)) ed.selected = new Set([hit.id]);
        ed.drag = { kind: "move", ox: x, oy: y };
        ed.past = [...ed.past.slice(-(HISTORY - 1)), ed.fields];
        ed.future = [];
        sync();
        return true;
      }
      if (ed.shift) { ed.marquee = { sx: x, sy: y, cx: x, cy: y }; return true; }
      ed.selected = new Set();
      sync();
      return false;
    }

    function moveTo(x, y, scale) {
      if (ed.marquee) { ed.marquee = { ...ed.marquee, cx: x, cy: y }; return true; }
      if (ed.drawing) {
        ed.drawing = { ...ed.drawing, cx: x, cy: y };
        return true;
      }
      if (!ed.drag) {
        /* Nothing is being dragged, so this is only the pointer passing over.
           Say the picture changed without claiming the event: the canvas still
           wants to report where the stage is under the cursor. */
        const over = hitField(x, y, scale)?.id ?? null;
        if (over === ed.hover) return false;
        ed.hover = over;
        return "redraw";
      }

      if (ed.drag.kind === "move") {
        const dx = x - ed.drag.ox, dy = y - ed.drag.oy;
        ed.drag = { ...ed.drag, ox: x, oy: y };
        commit(ed.fields.map((f) => (ed.selected.has(f.id) ? move(f, dx, dy) : f)), { history: false });
        return true;
      }
      if (ed.drag.kind === "rotate") {
        const a = Math.atan2(y - ed.drag.cy, x - ed.drag.cx);
        let rot = ed.drag.start + a - ed.drag.from;
        // eight orientations is what a scan field is ever squared up to
        if (ed.shift) rot = (Math.round((rot * 180) / Math.PI / 45) * 45 * Math.PI) / 180;
        commit(ed.fields.map((f) => (f.id === ed.drag.id ? { ...f, rotation: rot } : f)), { history: false });
        return true;
      }
      if (ed.drag.kind === "resize") {
        commit(ed.fields.map((f) => (f.id === ed.drag.id ? resize(f, ed.drag, x, y, ed.shift) : f)), { history: false });
        return true;
      }
      return false;
    }

    function up() {
      if (ed.marquee) {
        const m = ed.marquee;
        ed.marquee = null;
        const box = {
          xMin: Math.min(m.sx, m.cx), yMin: Math.min(m.sy, m.cy),
          xMax: Math.max(m.sx, m.cx), yMax: Math.max(m.sy, m.cy),
        };
        ed.selected = new Set(ed.fields.filter((f) => boxesOverlap(box, bounds(f))).map((f) => f.id));
        sync();
        return true;
      }
      if (ed.drawing) {
        const g = previewOf(ed.drawing, armed(), ed.shift);
        ed.drawing = null;
        if (g) {
          const f = { ...g, id: nextId(), presetId: ed.presetId };
          commit([...ed.fields, f]);
          ed.selected = new Set([f.id]);
          ed.tool = "pointer";
        }
        sync();
        return true;
      }
      if (ed.drag) { ed.drag = null; sync(); return true; }
      return false;
    }
  },
};

/* ---- geometry helpers shared by drawing and editing ---------------------- */

function traceField(ctx, f, toScreen) {
  ctx.beginPath();
  if (f.type === "ellipse") {
    const c = centroid(f);
    const [cx, cy] = toScreen(c.x, c.y);
    const [ex] = toScreen(c.x + f.rx, c.y);
    const [, ey] = toScreen(c.x, c.y + f.ry);
    ctx.ellipse(cx, cy, Math.abs(ex - cx), Math.abs(ey - cy), f.rotation || 0, 0, Math.PI * 2);
    return;
  }
  const ring = edges(f);
  if (!ring.length) return;
  ring.forEach((e, i) => {
    const [x, y] = toScreen(e[0], e[1]);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.closePath();
}

function previewOf(d, tool, shift) {
  let { sx, sy, cx, cy } = d;
  if (shift) {
    const span = Math.max(Math.abs(cx - sx), Math.abs(cy - sy));
    cx = sx + Math.sign(cx - sx) * span;
    cy = sy + Math.sign(cy - sy) * span;
  }
  const x = Math.min(sx, cx), y = Math.min(sy, cy);
  const w = Math.abs(cx - sx), h = Math.abs(cy - sy);
  if (w < MIN_DRAG_UM || h < MIN_DRAG_UM) return null;
  if (tool === "rectangle") return { type: "rectangle", x, y, w, h, rotation: 0 };
  if (tool === "triangle") {
    return {
      type: "triangle", rotation: 0,
      points: [{ x: x + w / 2, y }, { x: x + w, y: y + h }, { x, y: y + h }],
    };
  }
  if (tool === "ellipse") {
    return { type: "ellipse", cx: x + w / 2, cy: y + h / 2, rx: w / 2, ry: h / 2, rotation: 0 };
  }
  return null;
}

function move(f, dx, dy) {
  if (f.points) return { ...f, points: f.points.map((p) => ({ x: p.x + dx, y: p.y + dy })) };
  if (f.type === "ellipse") return { ...f, cx: f.cx + dx, cy: f.cy + dy };
  return { ...f, x: f.x + dx, y: f.y + dy };
}

function resize(f, drag, x, y, shift) {
  const start = drag.start;

  if (drag.index !== undefined && f.points) {
    const rot = f.rotation || 0;
    if (!rot) {
      const points = [...f.points];
      points[drag.index] = { x, y };
      return { ...f, points };
    }
    /* Rotation pivots on the centroid, and moving one vertex moves the
       centroid — so every other vertex would drift. Go out to world space,
       set the dragged vertex there, and come back around the new centroid. */
    const c = centroid(f);
    const world = f.points.map((p) => rotatePoint(p.x, p.y, c.x, c.y, rot));
    world[drag.index] = { x, y };
    const nc = {
      x: world.reduce((s, p) => s + p.x, 0) / world.length,
      y: world.reduce((s, p) => s + p.y, 0) / world.length,
    };
    return { ...f, points: world.map((p) => rotatePoint(p.x, p.y, nc.x, nc.y, -rot)) };
  }

  if (f.type === "ellipse") {
    const local = rotatePoint(x, y, f.cx, f.cy, -(f.rotation || 0));
    let rx = f.rx, ry = f.ry;
    if (drag.handle === "l" || drag.handle === "r") rx = Math.abs(local.x - f.cx);
    if (drag.handle === "t" || drag.handle === "b") ry = Math.abs(local.y - f.cy);
    if (shift) { const r = Math.max(rx, ry); rx = r; ry = r; }
    return { ...f, rx: Math.max(MIN_DRAG_UM / 2, rx), ry: Math.max(MIN_DRAG_UM / 2, ry) };
  }

  if (f.type === "rectangle") {
    const rot = f.rotation || 0;
    const c0 = { x: start.x + start.w / 2, y: start.y + start.h / 2 };
    const local = rotatePoint(x, y, c0.x, c0.y, -rot);
    let { x: nx, y: ny, w, h } = start;
    const id = drag.handle;

    /* The corner opposite the grip must not move. Its world position is taken
       before the resize and put back after, or a rotated rectangle walks away
       from under the pointer. */
    const anchorLocal = anchorFor(id, start);
    const anchorWorld = rotatePoint(anchorLocal.x, anchorLocal.y, c0.x, c0.y, rot);

    if (id.includes("r")) w = local.x - nx;
    if (id.includes("l")) { const e = nx + w; nx = local.x; w = e - nx; }
    if (id.includes("b")) h = local.y - ny;
    if (id.includes("t")) { const e = ny + h; ny = local.y; h = e - ny; }
    if (shift && id.length === 2) {
      const s = Math.max(Math.abs(w), Math.abs(h));
      if (id.includes("l")) nx = start.x + start.w - Math.sign(w) * s;
      if (id.includes("t")) ny = start.y + start.h - Math.sign(h) * s;
      w = Math.sign(w) * s; h = Math.sign(h) * s;
    }
    if (w < 0) { nx += w; w = -w; }
    if (h < 0) { ny += h; h = -h; }
    w = Math.max(MIN_DRAG_UM, w); h = Math.max(MIN_DRAG_UM, h);

    if (rot) {
      const c1 = { x: nx + w / 2, y: ny + h / 2 };
      const a1 = anchorFor(id, { x: nx, y: ny, w, h });
      const now = rotatePoint(a1.x, a1.y, c1.x, c1.y, rot);
      nx += anchorWorld.x - now.x;
      ny += anchorWorld.y - now.y;
    }
    return { ...f, x: nx, y: ny, w, h };
  }
  return f;
}

/** The point a resize pivots on: the corner or edge opposite the grip. */
function anchorFor(id, r) {
  let ax = r.x + r.w / 2, ay = r.y + r.h / 2;
  if (id.includes("l")) ax = r.x + r.w;
  else if (id.includes("r")) ax = r.x;
  if (id.includes("t")) ay = r.y + r.h;
  else if (id.includes("b")) ay = r.y;
  return { x: ax, y: ay };
}
