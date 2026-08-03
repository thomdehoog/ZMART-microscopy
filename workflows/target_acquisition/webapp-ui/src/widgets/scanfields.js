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
  normalise, rotatePoint, tiles, topCentre, withoutTrailingDuplicate,
} from "../lib/scanfields.js";

const MM_UM = 1000;

/* Distinct hues rather than a ramp: a preset is a name, not a quantity, and
   two fields taken with different presets have to be told apart at a glance. */
const PRESET_INK = ["#0284c7", "#b91c1c", "#16a34a", "#b45309", "#7c3aed", "#0e7490"];

/* A regular pentagon is the one polygon nobody draws round a sample. The glyph
   is an irregular closed shape for the same reason the tool exists: the point
   of it is that the outline follows something, so it is drawn rather than
   borrowed from the character set. */
const POLYGON_GLYPH = "M 3.5 8.5 L 9 2.5 L 18.5 5 L 19.5 14 L 9.5 19.5 Z";

const TOOLS = [
  { id: "pointer", key: "v", glyph: "↖", label: "Select", why: "Select, move, resize and rotate" },
  { id: "point", key: ".", glyph: "+", label: "Point", why: "Place positions · press again to stop" },
  { id: "rectangle", key: "r", glyph: "▭", label: "Rectangle", why: "Drag a rectangular region" },
  { id: "triangle", key: "t", glyph: "△", label: "Triangle", why: "Drag a triangular region" },
  { id: "ellipse", key: "e", glyph: "◯", label: "Ellipse", why: "Drag to draw · Shift for a circle" },
  { id: "polygon", key: "p", path: POLYGON_GLYPH, label: "Polygon", why: "Click to add points · double-click to finish" },
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

/* Marked, a field lights up: the same hue at more chroma, not a deeper one.
   Colour is the one signal every kind of field can carry — a region has an
   outline to thicken, a position has only its tile, and a tile cannot grow
   without saying something false about how much of the sample it takes in — so
   it is the same rule everywhere rather than one per shape.

   Brighter rather than darker because a plan is mostly tiles, and darkening
   drags the marked ones toward the greys the carrier is drawn in. Away from
   grey is the direction nothing else on the canvas is using. */
const REST_INK = 0.5;
const VIVID = 1.5;
const REST_FILL = 0.05;
const MARKED_FILL = 0.11;
const TILE_FILL = 0.12;
const MARKED_TILE_FILL = 0.2;
/* The tile's own outline carries some of it too, so the fill does not have to
   go so deep that lighting a field up reads as shading it in. */
const TILE_W = 0.8;
const MARKED_TILE_W = 1.6;

/* A region is an area of a sample, not a pixel boundary. Micrometres, so the
   softening is a property of the shape rather than of how far it is zoomed. */
const CORNER_UM = 50;

/* A hand-placed position is drawn against the frame it will image — the same
   fraction of it at every zoom — so a crosshair says how much of the sample
   that one press actually takes in. */
const CROSS_FRAC = 0.3;
const DOT_FRAC = 0.18;

/* Below this a frame is smaller than the line that would draw it, so the mark
   that stands in for it takes over — see the tile loop for why. */
const MIN_TILE_PX = 1.6;
const SPECK_R = 1.5;

/* Screen pixels, not micrometres: a grip is as easy to hit zoomed out as in. */
const HIT_PX = 12;
/* A marquee under this never changes the selection. Reaching for empty canvas
   with Shift still down is a twitch, not a request to deselect everything. */
const MARQUEE_MIN_PX = 50;
/* Two polygon vertices closer together than this were one press as far as
   anybody was concerned. */
const DUPLICATE_PX = 4;
const MIN_DRAG_UM = 100;
const NUDGE_UM = 100;
/* Far enough that a pasted copy is visibly its own field rather than a second
   outline hiding under the first, and small enough to drag where it belongs. */
const PASTE_UM = 1000;
const HISTORY = 60;

/* An edge grip moves one side and a corner grip moves two. Different jobs, so
   different shapes — the hand knows which it has before it reads the position. */
const EDGE_GRIPS = new Set(["t", "b", "l", "r"]);
const GRIP_R = 4.5;
const ROTATE_R = 7;

/* The tools whose gesture is a drag rather than a press. It is the difference
   between saying how big and saying where, and the two want opposite things
   from a shape that is already under the pointer. */
const DRAG_TOOLS = new Set(["rectangle", "triangle", "ellipse"]);

const GREY = "#9ca3af";
const BLUE = "#0284c7";

const rgb = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

const withAlpha = (hex, a) => `rgba(${rgb(hex).join(", ")}, ${a})`;

/**
 * The same hue with the grey taken out of it. What marked looks like.
 *
 * Pushing each channel away from their mean raises chroma while leaving
 * lightness roughly where it was, so the colour reads as more itself rather
 * than as a lighter or heavier version of itself.
 */
const vivid = (hex) => {
  const c = rgb(hex);
  const grey = (c[0] + c[1] + c[2]) / 3;
  const lift = (v) => Math.max(0, Math.min(255, Math.round(grey + (v - grey) * VIVID)));
  return `rgb(${c.map(lift).join(", ")})`;
};

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const SVG_NS = "http://www.w3.org/2000/svg";

/** A tool's mark: a character where one says it, a drawn outline where none does. */
const glyphOf = (tool) => {
  if (!tool.path) return el("span", "sf-glyph", tool.glyph);
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 22 22");
  svg.setAttribute("class", "sf-glyph sf-glyph-drawn");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", tool.path);
  svg.append(path);
  return svg;
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
   *
   * `marked` is which of it is being talked about — selected or under the
   * pointer, which read the same because they are the same claim. It is passed
   * in rather than drawn over the top afterwards so that one place decides how
   * a field looks; two would disagree about a fill the moment either changed.
   */
  drawOn(ctx, { fields, presets, toScreen, scale, marked = null, dim = false }) {
    if (!fields?.length) return;
    const on = (id) => !!marked?.has(id);
    const base = dim ? 0.45 : 1;
    ctx.save();
    ctx.globalAlpha = base;

    /* The tiles carry the marking too, and for a grid position they are all of
       it — its own drawing is nothing, because the tile already says where it
       is and how much it takes in. */
    for (const t of plan(fields, presets)) {
      const [x, y] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      const s = t.frameUm * scale;
      const ink = presetInk(presets, t.presetId);
      const hot = on(t.fieldId);
      /* A frame smaller than a pixel is not a square any more. Drawing it as
         one would be a lie about how much it covers, and drawing nothing loses
         the position altogether — which is what a high-magnification preset
         over a whole plate did: hundreds of positions, an empty canvas, and a
         readout insisting they were there. So a mark stands in until the view
         is close enough for the frame itself to say something. */
      if (s < MIN_TILE_PX) {
        ctx.beginPath();
        ctx.arc(x + s / 2, y + s / 2, hot ? SPECK_R * 1.8 : SPECK_R, 0, Math.PI * 2);
        ctx.fillStyle = hot ? vivid(ink) : ink;
        ctx.fill();
        continue;
      }
      ctx.fillStyle = hot ? vivid(ink) : ink;
      ctx.globalAlpha = base * (hot ? MARKED_TILE_FILL : TILE_FILL);
      ctx.fillRect(x, y, s, s);
      ctx.globalAlpha = base;
      ctx.strokeStyle = hot ? vivid(ink) : ink;
      ctx.lineWidth = hot ? MARKED_TILE_W : TILE_W;
      ctx.strokeRect(x, y, s, s);
    }

    for (const f of fields) {
      const ink = presetInk(presets, f.presetId);
      const hot = on(f.id);
      if (isPointLike(f.type)) {
        drawPoint(ctx, f, {
          ink, toScreen, scale, marked: hot,
          frameUm: presets.find((p) => p.id === f.presetId)?.frameUm ?? 0,
        });
        continue;
      }
      traceField(ctx, f, toScreen, scale);
      ctx.fillStyle = withAlpha(hot ? vivid(ink) : ink, hot ? MARKED_FILL : REST_FILL);
      ctx.fill();
      ctx.strokeStyle = hot ? vivid(ink) : withAlpha(ink, REST_INK);
      ctx.lineWidth = hot ? MARKED_W : FIELD_W;
      ctx.stroke();
    }
    ctx.restore();
  },

  /**
   * Mount the channel. Returns the handle the frame keeps while the step is
   * selected: what to draw on top of the plan, and where the pointer went.
   */
  render(host, { fields, carrier, presets, locked, onChange, redraw }) {
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
      hoverGrip: null,
      cursor: null,
      shift: false,
      past: [],
      future: [],
      presetId: presets[0]?.id ?? null,
      rows: 3,
      cols: 3,
      spacingX: 0,
      spacingY: 0,
    };

    /* Held by the step, not by the system: these are fields in carrier
       micrometres, and nothing outside this page would know what to do with
       them. It empties when the step is left, which is the same thing the
       operator means by leaving it. */
    let clipboard = [];

    const preset = () => presets.find((p) => p.id === ed.presetId) ?? presets[0];
    const frameUm = () => preset()?.frameUm ?? 1000;
    // spacing is a floor, not a free number: positions may be spread apart,
    // never overlapped, so the frame is what it cannot go below
    const pitch = () => [
      Math.max(ed.spacingX || 0, frameUm()),
      Math.max(ed.spacingY || 0, frameUm()),
    ];

    /* The carrier is the edge of what can be imaged, so it is the edge of what
       can be drawn. A field outside it is a position the stage will not reach,
       and nothing downstream would notice: the plan would simply contain tiles
       that never arrive. */
    const extentUm = () => {
      const g = geometry(carrier);
      return [g.width * MM_UM, g.height * MM_UM];
    };
    const inside = (x, y) => {
      const [w, h] = extentUm();
      return { x: Math.min(Math.max(x, 0), w), y: Math.min(Math.max(y, 0), h) };
    };
    /* Pushed back whole rather than trimmed. The shape somebody drew is the
       statement; clipping it would quietly change what gets imaged, where
       sliding it says plainly that it does not fit where it was put. */
    const clamped = (f) => {
      const [w, h] = extentUm();
      const b = bounds(f);
      let dx = 0, dy = 0;
      if (b.xMin < 0) dx = -b.xMin;
      else if (b.xMax > w) dx = w - b.xMax;
      if (b.yMin < 0) dy = -b.yMin;
      else if (b.yMax > h) dy = h - b.yMax;
      return dx || dy ? move(f, dx, dy) : f;
    };

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

    /* Select is one of them. It is where the panel returns after every shape,
       which is exactly why it needs showing: without it the row goes blank
       between shapes and there is nothing on screen saying what the next press
       will do. Armed is a state, and a state wants somewhere to live. */
    const geomGroup = group("Geometries");
    const toolRow = el("div", "sf-tools");
    for (const t of TOOLS) {
      const b = el("button", "sf-tool");
      b.type = "button";
      b.dataset.tool = t.id;
      b.title = `${t.label} (${t.key}) — ${t.why}`;
      b.append(glyphOf(t));
      /* Pressing the armed tool disarms it. Point is the one that stays armed
         after it is used — placing positions is something done several times
         in a row — so it is also the one that needs a way back out that is not
         a keystroke. The rest disarm themselves after a shape and never reach
         this, which is why it is a plain toggle rather than a special case. */
      b.addEventListener("click", () => {
        ed.tool = ed.tool === t.id && t.id !== "pointer" ? "pointer" : t.id;
        ed.poly = [];
        sync();
        redraw();
      });
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
          made.push({
            id: nextId(), type: "point", presetId: ed.presetId, source: "grid",
            ...inside(p.x, p.y),
          });
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
      ["Double-click", "finish the polygon"],
      ["Alt+drag", "pan, even over a field"],
      ["Shift+drag", "circle or square — marquee on empty"],
      ["Shift+move", "keep to one axis"],
      ["Shift+click", "add to selection"],
      ["Shift+rotate", "45° snap"],
      ["Wheel", "zoom"],
      ["Arrows", "nudge — Shift coarse"],
      ["Ctrl+Z / Y", "undo, redo"],
      ["Ctrl+C / V", "copy, paste"],
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

    /* A copy is hand-made whatever it was taken from, so it sheds the grid tag
       on the way out. Otherwise the next Apply — which replaces everything the
       grid put down — would sweep away a field nobody asked it to touch.
       Copying a grid position is, in fact, how one is kept. */
    function copy() {
      clipboard = ed.fields
        .filter((f) => ed.selected.has(f.id))
        .map(({ id, source, ...rest }) => rest);
    }

    function paste() {
      if (locked || !clipboard.length) return;
      const made = clipboard.map((f) =>
        clamped(move({ ...f, id: nextId() }, PASTE_UM, PASTE_UM)));
      ed.selected = new Set(made.map((f) => f.id));
      commit([...ed.fields, ...made]);
      // what was pasted becomes what is held, so a second paste lands clear of
      // the first rather than back on top of the original
      clipboard = made.map(({ id, ...rest }) => rest);
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
      /* Selection is drawn on the canvas, so changing it from the keyboard has
         to say so. A pointer gesture gets a redraw for free — the frame draws
         whatever the editor answers to — and these do not go through it. */
      if ((e.ctrlKey || e.metaKey) && k === "a") {
        e.preventDefault();
        ed.selected = new Set(ed.fields.map((f) => f.id));
        sync();
        redraw();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && k === "c") { e.preventDefault(); copy(); return; }
      if ((e.ctrlKey || e.metaKey) && k === "v") { e.preventDefault(); paste(); return; }
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeSelected(); return; }
      if (e.key === "Escape") {
        ed.poly = []; ed.drawing = null; ed.tool = "pointer"; ed.selected = new Set();
        sync();
        redraw();
        return;
      }
      if (ed.mode === "geometry" && !e.ctrlKey && !e.metaKey) {
        const t = TOOLS.find((x) => x.key === (e.key === "." ? "." : k));
        if (t) { ed.tool = t.id; ed.poly = []; sync(); redraw(); return; }
      }
      const nudge = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (nudge && ed.selected.size) {
        e.preventDefault();
        const d = NUDGE_UM * (e.shiftKey ? 5 : 1);
        commit(ed.fields.map((f) =>
          (ed.selected.has(f.id) && movable(f) ? clamped(move(f, nudge[0] * d, nudge[1] * d)) : f)));
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

      /* Which of the fields are being talked about, for whoever draws them.
         Selected or under the pointer — the same claim, so the same answer —
         and nothing while a drag is under way, when whether a shape was
         pickable has stopped being the question. */
      marked() {
        const m = new Set(ed.selected);
        if (ed.hover && !ed.drag && !ed.drawing && !ed.marquee) m.add(ed.hover);
        return m;
      },

      /** What the next press will do, as one word the canvas hands to CSS. */
      cursor: cursorNow,

      /** Grips, marquee and the shape being drawn — the editing, not the plan. */
      drawChrome(ctx, { toScreen, scale }) {
        ctx.save();

        const only = single();
        if (only && !isPointLike(only.type)) {
          /* The grips wear the field's own colour rather than one editor blue,
             so which shape they belong to survives two overlapping regions. */
          const ink = presetInk(presets, only.presetId);
          const rot = only.rotation || 0, c = centroid(only);
          /* Hollow at rest, filled under the pointer. Which grip has been
             found is worth saying outright, because grips are small, several
             are within reach of one another, and being wrong about it costs a
             resize that has to be undone. */
          for (const h of handles(only)) {
            const w = rotatePoint(h.x, h.y, c.x, c.y, rot);
            const [x, y] = toScreen(w.x, w.y);
            const hot = ed.hoverGrip === h.id;
            ctx.beginPath();
            if (EDGE_GRIPS.has(h.id)) {
              const s = hot ? GRIP_R + 1.5 : GRIP_R;
              ctx.rect(x - s, y - s, s * 2, s * 2);
            } else ctx.arc(x, y, hot ? GRIP_R + 1.5 : GRIP_R, 0, Math.PI * 2);
            ctx.fillStyle = hot ? ink : "#ffffff"; ctx.fill();
            ctx.lineWidth = 1.5; ctx.strokeStyle = ink; ctx.stroke();
          }
          /* On a stem, and dashed, because the stem is not part of the shape —
             it is only saying where the grip belongs. */
          const grip = rotationGrip(only, scale);
          const [gx, gy] = toScreen(grip.x, grip.y);
          const top = rotatePoint(topCentre(only).x, topCentre(only).y, c.x, c.y, rot);
          const [tx, ty] = toScreen(top.x, top.y);
          ctx.beginPath();
          ctx.moveTo(tx, ty); ctx.lineTo(gx, gy);
          ctx.strokeStyle = ink; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
          ctx.stroke();
          ctx.setLineDash([]);
          const spinning = ed.hoverGrip === "rotate";
          ctx.beginPath(); ctx.arc(gx, gy, spinning ? ROTATE_R + 1.5 : ROTATE_R, 0, Math.PI * 2);
          ctx.fillStyle = spinning ? ink : "#ffffff"; ctx.fill();
          ctx.lineWidth = 1.5; ctx.strokeStyle = ink; ctx.stroke();
          // the arc keeps its contrast by swapping to the surface colour
          ctx.beginPath(); ctx.arc(gx, gy, spinning ? 4 : 3.2, Math.PI * 0.7, Math.PI * 2);
          ctx.lineWidth = 1; ctx.strokeStyle = spinning ? "#ffffff" : ink; ctx.stroke();
        }

        /* One box round the whole selection, so a group reads as a group and
           its extent is visible before it is dragged anywhere. */
        if (ed.selected.size > 1) {
          const b = ed.fields.filter((f) => ed.selected.has(f.id)).map(bounds)
            .reduce((a, n) => (a ? {
              xMin: Math.min(a.xMin, n.xMin), yMin: Math.min(a.yMin, n.yMin),
              xMax: Math.max(a.xMax, n.xMax), yMax: Math.max(a.yMax, n.yMax),
            } : n), null);
          if (b) {
            const pad = 800;
            const [x0, y0] = toScreen(b.xMin - pad, b.yMin - pad);
            const [x1, y1] = toScreen(b.xMax + pad, b.yMax + pad);
            ctx.strokeStyle = GREY; ctx.lineWidth = 2; ctx.setLineDash([12, 6]);
            ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
            ctx.setLineDash([]);
          }
        }

        if (ed.drawing) {
          const g = previewOf(ed.drawing, armed(), ed.shift);
          if (g) {
            ctx.strokeStyle = BLUE; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
            traceField(ctx, g, toScreen, scale);
            ctx.fillStyle = withAlpha(BLUE, 0.04); ctx.fill();
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }

        /* Closed from the first two points on, with the cursor standing in for
           the vertex about to be placed. A polygon being drawn as an open
           chain asks the operator to hold the finished shape in their head;
           closing it means what is on screen is always the region they would
           get, and each press only changes it rather than completing it. */
        if (ed.poly.length) {
          const ring = ed.cursor ? [...ed.poly, ed.cursor] : ed.poly;
          ctx.beginPath();
          ring.forEach((p, i) => {
            const [x, y] = toScreen(p.x, p.y);
            i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
          });
          ctx.closePath();
          ctx.fillStyle = withAlpha(BLUE, 0.05); ctx.fill();
          ctx.strokeStyle = BLUE; ctx.lineWidth = 1.5; ctx.stroke();
          for (const p of ed.poly) {
            const [x, y] = toScreen(p.x, p.y);
            ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fillStyle = "#ffffff"; ctx.fill();
            ctx.lineWidth = 1.5; ctx.strokeStyle = BLUE; ctx.stroke();
          }
        }

        if (ed.marquee) {
          const [x0, y0] = toScreen(Math.min(ed.marquee.sx, ed.marquee.cx), Math.min(ed.marquee.sy, ed.marquee.cy));
          const [x1, y1] = toScreen(Math.max(ed.marquee.sx, ed.marquee.cx), Math.max(ed.marquee.sy, ed.marquee.cy));
          /* Grey and filled, not the preset blue: the marquee is a question
             about which fields, not a field. */
          ctx.fillStyle = "rgba(107, 114, 128, 0.06)";
          ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
          ctx.strokeStyle = GREY; ctx.lineWidth = 1.5; ctx.setLineDash([8, 4]);
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
        if (kind === "up") return up(scale);
        if (kind === "finish") return finish(scale);
        if (kind === "leave") {
          const had = ed.hover || ed.hoverGrip || ed.cursor;
          ed.hover = null;
          ed.hoverGrip = null;
          ed.cursor = null;
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

    /* The nearest grip within reach, not the first one found.
     *
     * Zoomed out, or on a field only a little bigger than the grips it
     * carries, several are inside the same twelve pixels. Taking whichever
     * came first in the list means the one that answers is not the one being
     * pointed at, and since exactly one is highlighted, the highlight would be
     * on the wrong grip — which is worse than none, because it is a claim. */
    function hitHandle(x, y, scale) {
      const f = single();
      if (!f || armed() !== "pointer" || isPointLike(f.type)) return null;
      const near = HIT_PX / scale;
      const c = centroid(f), rot = f.rotation || 0;
      let best = null;
      const consider = (p, grip) => {
        const d = Math.hypot(x - p.x, y - p.y);
        if (d < near && (!best || d < best.d)) best = { d, ...grip };
      };
      consider(rotationGrip(f, scale), { kind: "rotate", id: "rotate", field: f });
      for (const h of handles(f)) {
        consider(rotatePoint(h.x, h.y, c.x, c.y, rot),
          { kind: "resize", id: h.id, field: f, handle: h.id, index: h.index });
      }
      return best;
    }

    /* Which tool is armed. Only the drawing mode arms one — the other mode
       hides the tools rather than disabling the canvas, so selecting, moving,
       resizing and the marquee go on working on whatever the grid just put
       down. A mode is about what can be made, not about whether what is
       already there can be touched. */
    /* Everything below the return is a function declaration on purpose. The
       handle has already been returned by the time control would reach here,
       so a `const` never gets initialised and the first press throws on the
       dead zone — twice now. Declarations hoist; nothing else here does. */
    function armed() {
      return ed.mode === "geometry" ? ed.tool : "pointer";
    }

    /* The cursor answers what the next press does, and nothing else. Over a
       field: it can be picked up. With a tool armed: it draws — which is why
       there is a crosshair rather than a grabbing hand, since a press on empty
       canvas is going to start a shape, not take hold of one. */
    function cursorNow() {
      if (locked) return "default";
      if (ed.drawing || ed.marquee) return "crosshair";
      if (ed.drag) return "default";
      if (ed.hover || ed.hoverGrip) return "pointer";
      return armed() === "pointer" ? "default" : "crosshair";
    }

    /* A grid position is not where somebody put it — it is where the carrier
       and the grid settings say it is. Dragging one by hand would leave a
       position claiming to be part of a block it is no longer in, and the next
       Apply would throw the change away without saying so. So it can be
       picked, given a different preset and deleted, and it cannot be moved:
       change the grid, or take it out of the grid by deleting it. */
    function movable(f) {
      return f.source !== "grid";
    }

    function pushHistory() {
      ed.past = [...ed.past.slice(-(HISTORY - 1)), ed.fields];
      ed.future = [];
    }

    /* The anchor is where the press landed and stays there for the whole drag;
       dx/dy are how far the fields have been carried from it so far. */
    function startMove(x, y) {
      ed.drag = { kind: "move", ox: x, oy: y, dx: 0, dy: 0 };
      pushHistory();
    }

    /* A double-click says the outline is done.
     *
     * A polygon is the one shape with no gesture that ends itself: a rectangle
     * is finished by letting go, but there is no vertex that announces it was
     * the last one — only the operator knows. Hunting for the first point to
     * click again is a second, smaller drawing problem on top of the first.
     * Fewer than three points is not a region, so it is thrown away instead. */
    function finish(scale) {
      if (!ed.poly.length) return false;
      const points = withoutTrailingDuplicate(ed.poly, DUPLICATE_PX / scale);
      ed.poly = [];
      ed.tool = "pointer";
      if (points.length < 3) { sync(); return true; }
      const f = { id: nextId(), type: "polygon", presetId: ed.presetId, points, rotation: 0 };
      commit([...ed.fields, f]);
      ed.selected = new Set([f.id]);
      sync();
      return true;
    }

    function down(x, y, scale) {
      const tool = armed();

      /* A region already on the canvas answers before a tool that would drag a
         new one out on top of it: reaching for something that is there is a
         request to pick it up.

         Only the drag tools defer, and only to regions. Point and polygon put
         something exactly where the press was, and inside an existing region
         is a perfectly ordinary place to want it — while a plate carrying a
         grid is covered in positions, so deferring to those would leave
         nowhere on the carrier a new field could start. */
      if (DRAG_TOOLS.has(tool)) {
        const over = hitField(x, y, scale);
        if (over && !isPointLike(over.type)) {
          ed.tool = "pointer";
          ed.selected = new Set([over.id]);
          startMove(x, y);
          sync();
          return true;
        }
      }

      // every press is another point; the right button is what says that is enough
      if (tool === "polygon") {
        ed.poly = [...ed.poly, inside(x, y)];
        sync();
        return true;
      }

      if (tool === "point") {
        // stays armed: placing positions is something done several times over
        const f = { id: nextId(), type: "point", presetId: ed.presetId, ...inside(x, y) };
        commit([...ed.fields, f]);
        ed.selected = new Set([f.id]);
        return true;
      }

      if (tool !== "pointer") {
        const s = inside(x, y);
        ed.drawing = { sx: s.x, sy: s.y, cx: s.x, cy: s.y };
        return true;
      }

      const grip = hitHandle(x, y, scale);
      if (grip) {
        const c = centroid(grip.field);
        ed.drag = grip.kind === "rotate"
          ? { kind: "rotate", id: grip.field.id, cx: c.x, cy: c.y, from: Math.atan2(y - c.y, x - c.x), start: grip.field.rotation || 0 }
          : { kind: "resize", id: grip.field.id, handle: grip.handle, index: grip.index, start: grip.field };
        pushHistory();
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
        // picked either way; only what the grid did not place can be dragged
        if ([...ed.selected].some((id) => movable(ed.fields.find((f) => f.id === id)))) {
          startMove(x, y);
        }
        sync();
        return true;
      }
      if (ed.shift) { ed.marquee = { sx: x, sy: y, cx: x, cy: y }; return true; }
      /* A press on empty canvas lets go of everything. It does not claim the
         event — the same press goes on to pan — but it does change what is
         drawn, and saying so is the whole of it: clearing the selection while
         the canvas kept the old outlines on screen is what made deselecting
         look broken. */
      const had = ed.selected.size;
      ed.selected = new Set();
      sync();
      return had ? "redraw" : false;
    }

    function moveTo(x, y, scale) {
      ed.cursor = { x, y };
      if (ed.marquee) { ed.marquee = { ...ed.marquee, cx: x, cy: y }; return true; }
      if (ed.drawing) {
        const s = inside(x, y);
        ed.drawing = { ...ed.drawing, cx: s.x, cy: s.y };
        return true;
      }
      if (!ed.drag) {
        /* Nothing is being dragged, so this is only the pointer passing over.
           Say the picture changed without claiming the event: the canvas still
           wants to report where the stage is under the cursor. */
        /* One thing at a time. A grip sitting on its own field's outline is
           two answers to the same question, and the field behind a grip is a
           third — so the grip wins outright and the field is not looked for.
           Highlighting both would say the press could do either. */
        const grip = hitHandle(x, y, scale);
        const over = grip ? null : (hitField(x, y, scale)?.id ?? null);
        const same = over === ed.hover && (grip?.id ?? null) === ed.hoverGrip;
        ed.hover = over;
        ed.hoverGrip = grip?.id ?? null;
        // a half-drawn outline follows the cursor, so it always wants the redraw
        return same && !ed.poly.length ? false : "redraw";
      }

      if (ed.drag.kind === "move") {
        /* Measured from where the drag started rather than from the last
           event. A per-event delta is a pixel or two, so asking which axis is
           the major one would answer differently on every frame and Shift
           would jitter between them instead of holding one. */
        let dx = x - ed.drag.ox, dy = y - ed.drag.oy;
        if (ed.shift) (Math.abs(dx) > Math.abs(dy) ? (dy = 0) : (dx = 0));
        const stepX = dx - ed.drag.dx, stepY = dy - ed.drag.dy;
        ed.drag = { ...ed.drag, dx, dy };
        if (!stepX && !stepY) return true;
        commit(ed.fields.map((f) =>
          (ed.selected.has(f.id) && movable(f) ? clamped(move(f, stepX, stepY)) : f)),
        { history: false });
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
        /* The pointer is clamped rather than the result: an edge dragged past
           the carrier simply stops there, where clamping afterwards would slide
           the whole field sideways and move the edge nobody was holding. */
        const s = inside(x, y);
        commit(ed.fields.map((f) => (f.id === ed.drag.id ? resize(f, ed.drag, s.x, s.y, ed.shift) : f)), { history: false });
        return true;
      }
      return false;
    }

    function up(scale) {
      if (ed.marquee) {
        const m = ed.marquee;
        ed.marquee = null;
        const box = {
          xMin: Math.min(m.sx, m.cx), yMin: Math.min(m.sy, m.cy),
          xMax: Math.max(m.sx, m.cx), yMax: Math.max(m.sy, m.cy),
        };
        /* Too small to be a rectangle anybody meant to draw: a press with
           Shift still held from the last one, which should not empty the
           selection it was about to add to. */
        const spans = Math.max(box.xMax - box.xMin, box.yMax - box.yMin) * scale;
        if (spans < MARQUEE_MIN_PX) { sync(); return true; }
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

/**
 * A position, drawn against the frame it will image.
 *
 * A grid position is left entirely to its tile: the tile is where it is and
 * how much of the sample it takes, a crosshair on every one of a hundred says
 * nothing the block has not already said, and marking it is the tile lighting
 * up. A crosshair marks the ones placed by hand, which are few and are meant
 * to be found again.
 */
function drawPoint(ctx, f, { ink, toScreen, scale, marked, frameUm }) {
  if (f.source === "grid") return;
  const [x, y] = toScreen(f.x, f.y);
  const lit = marked ? vivid(ink) : ink;
  const arm = frameUm * CROSS_FRAC * scale;
  ctx.beginPath();
  ctx.arc(x, y, Math.max(1.5, frameUm * DOT_FRAC * scale), 0, Math.PI * 2);
  ctx.fillStyle = marked ? lit : withAlpha(ink, 0.25);
  ctx.fill();
  if (arm < 2) return;
  ctx.beginPath();
  ctx.moveTo(x - arm, y); ctx.lineTo(x + arm, y);
  ctx.moveTo(x, y - arm); ctx.lineTo(x, y + arm);
  ctx.strokeStyle = marked ? lit : withAlpha(ink, REST_INK);
  ctx.lineWidth = marked ? MARKED_W : FIELD_W;
  ctx.stroke();
}

function traceField(ctx, f, toScreen, scale) {
  ctx.beginPath();
  if (f.type === "ellipse") {
    const c = centroid(f);
    const [cx, cy] = toScreen(c.x, c.y);
    const [ex] = toScreen(c.x + f.rx, c.y);
    const [, ey] = toScreen(c.x, c.y + f.ry);
    ctx.ellipse(cx, cy, Math.abs(ex - cx), Math.abs(ey - cy), f.rotation || 0, 0, Math.PI * 2);
    return;
  }
  if (f.type === "rectangle") {
    /* Built under a rotation rather than from rotated corners, because a
       rounded corner is an arc and there is no rotated-arc primitive. The path
       is baked in screen space as it is laid down, so the stroke that follows
       is still measured in pixels. */
    const c = centroid(f);
    const [cx, cy] = toScreen(c.x, c.y);
    const w = f.w * scale, h = f.h * scale;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(f.rotation || 0);
    ctx.roundRect(-w / 2, -h / 2, w, h, Math.min(CORNER_UM * scale, w / 2, h / 2));
    ctx.restore();
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
