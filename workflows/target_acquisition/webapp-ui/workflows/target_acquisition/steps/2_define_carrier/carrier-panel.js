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
 * It redraws itself rather than asking the framework to rebuild the panel. A
 * rebuild on every keystroke would destroy the field being typed into — the
 * defect this page has produced twice — so `sync()` writes new values into the
 * controls that are already there and leaves the focused one alone.
 */

import { sideGroup } from "../../../../framework/window/panels.js";
import {
  CARRIER_TYPES, carrierType, fromPreset, matchingPreset, geometry, maxRadius,
  centres, depthMm,
} from "../../shared/carriers.js";

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

/**
 * Which way a millimetre of depth runs across the stage view, and how far.
 *
 * The canvas looks straight down at the stage, so depth has no direction of
 * its own there and has to be borrowed. This is the cabinet projection, which
 * draughtsmen use for exactly this situation: the third axis runs off at an
 * angle at a fraction of its true length, because a full-length oblique axis
 * reads as longer than it is.
 *
 * A third of the length rather than the usual half, and thirty degrees rather
 * than the usual forty-five. The vessels here are deep — a cuvette is four and
 * a half times deeper than it is wide — and at the usual figures the box
 * climbs so far up the picture that it reads as the subject of it rather than
 * as one carrier standing on a stage. Flatter and shorter, it says the same
 * thing more quietly, and what it says is still true: the face the depth is
 * measured *from* is untouched by either number, which matters because that
 * face is the footprint every position in the run is placed inside.
 */
const DEPTH_RUNS = 1 / 3;
const DEPTH_ANGLE = Math.PI / 6;
const DEPTH_ACROSS = DEPTH_RUNS * Math.cos(DEPTH_ANGLE);
const DEPTH_UP = DEPTH_RUNS * Math.sin(DEPTH_ANGLE);

/**
 * The two faces of a box a viewer standing over the stage would see besides
 * its top, drawn behind the footprint so that the footprint itself is left
 * exactly where it is.
 *
 * Two rather than three: the far face is behind the sample and an opaque box
 * hides it, so drawing it would only put lines through the sample. The top
 * face is drawn a shade stronger than the side, which is the whole of the
 * shading — enough for the eye to read a solid, and nothing that pretends to
 * know where the light is.
 */
function drawTheDepthBehind(ctx, x, y, w, h, dx, dy, fill) {
  const faces = [
    [0.55, [[x, y], [x + w, y], [x + w + dx, y - dy], [x + dx, y - dy]]],
    [0.35, [[x + w, y], [x + w, y + h], [x + w + dx, y + h - dy], [x + w + dx, y - dy]]],
  ];
  const was = ctx.globalAlpha;
  for (const [shade, corners] of faces) {
    ctx.beginPath();
    for (const [px, py] of corners) ctx.lineTo(px, py);
    ctx.closePath();
    if (fill) {
      ctx.globalAlpha = was * shade;
      ctx.fill();
      ctx.globalAlpha = was;
    }
    ctx.stroke();
  }
}

/**
 * The four places a carrier is registered from, in its own micrometres.
 *
 * The middle of each border rather than the corners, because a corner is the
 * one part of a carrier an objective can rarely see: a slide's are cut back, a
 * plate's are under the skirt, and a dish has none at all. The middle of a
 * border is on the glass whatever the vessel is — and on a dish, whose rim
 * touches its own bounding box at exactly those four places, they land on the
 * rim itself.
 *
 * Left, right, top and bottom: two pairs facing each other across the carrier,
 * so the registration is measured over the longest run in each direction
 * rather than out of one corner of it. The same four for every carrier on
 * offer, including a chamber slide with one chamber in it — where a carrier is
 * registered from is a property of its outline, not of what is inside it.
 */
export function anchorsUm(config) {
  const g = geometry(config);
  const w = g.width * MM_UM, h = g.height * MM_UM;
  return [
    { at: "left", x: 0, y: h / 2 },
    { at: "right", x: w, y: h / 2 },
    { at: "top", x: w / 2, y: 0 },
    { at: "bottom", x: w / 2, y: h },
  ];
}

export default {
  id: "carrier",
  label: "Define Carrier",

  /** The four places this carrier is registered from. See `anchorsUm`. */
  anchorsUm,

  /** How much stage the carrier covers, for whatever has to frame it. */
  extentUm(config) {
    const g = geometry(config);
    return [g.width * MM_UM, g.height * MM_UM];
  },

  /**
   * Every imageable area the carrier declares, drawn from the carrier's own
   * zero. Under everything else: it is the frame the run happens inside, not a
   * layer of the run. Handed the projection rather than reaching for it, so
   * this knows neither how the canvas is panned nor where on the stage the
   * carrier has been placed — both are the caller's to decide.
   *
   * Filled as well as outlined, because an area is somewhere a sample can be
   * rather than a line around nothing — the stage around it is empty travel,
   * and the difference between the two is worth seeing at a glance.
   */
  drawOn(ctx, { config, toScreen, scale, colour, fill }) {
    const g = geometry(config);
    const aw = config.w * MM_UM * scale;
    const ah = config.h * MM_UM * scale;
    if (aw < 1.5 || ah < 1.5) return;
    const rad = Math.min(g.corner * MM_UM * scale, aw / 2, ah / 2);
    const depth = depthMm(config) * MM_UM * scale;
    ctx.save();
    ctx.fillStyle = fill;
    ctx.strokeStyle = colour;
    ctx.globalAlpha = 0.8;
    ctx.lineWidth = Math.min(1.2, Math.max(0.4, aw * 0.02));
    // from the same centres anything placing positions inside an area reads,
    // so the drawing and the positions cannot land in different places
    for (const a of centres(config)) {
      const [x, y] = toScreen((a.x - config.w / 2) * MM_UM, (a.y - config.h / 2) * MM_UM);
      /* A carrier with depth drawn flat is an area with a number attached:
         the one thing that makes it deep is the one thing the picture leaves
         out. So the depth is put on the stage as a box behind the footprint —
         no carrier on offer declares one at the moment, and this is what will
         draw the next one that does. */
      if (depth > 0) {
        drawTheDepthBehind(ctx, x, y, aw, ah,
          depth * DEPTH_ACROSS, depth * DEPTH_UP, fill);
      }
      ctx.beginPath();
      ctx.roundRect(x, y, aw, ah, rad);
      if (fill) ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  },

  render(host, { config, locked, onChange, anchors }) {
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

    /* The type is chosen in a box of its own, headed by the choosing: it is
       the first question the step asks, and everything under it is about the
       answer. */
    const { group: typeBox, body: typeCard } = sideGroup("Select carrier type");
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
    typeCard.append(types);
    controls.append(typeBox);

    /* One body under the type row: every carrier is designed in the same
       panel, and what differs between them is which groups of it are on
       screen. */
    const designer = el("div", "carrier-designer");
    controls.append(designer);

    /* Which groups a type is about, filled as the groups are built and read
       by sync(). A group and the rule for showing it are written in the same
       breath here, which is the only arrangement in which the two cannot
       drift apart. */
    const groups = [];
    const showWhen = (node, when) => { groups.push([node, when]); return node; };

    /* How each row of numbers narrows itself to the carrier on screen. Kept
       beside the list of groups because the two answer the same question at
       different sizes: which groups this carrier is about, and which boxes
       within them. */
    const fits = [];

    const presetOptions = (typeId) => [
      ...carrierType(typeId).presets.map((p, i) => new Option(p.label, String(i))),
      new Option("Custom", "-1"),
    ];

    /* The catalogue and the three things done with a whole carrier go straight
       under the type they belong to: picking a wellplate and picking the
       96-well one out of the catalogue are the same question asked twice over,
       so neither a box nor a word of their own. The numbers below are the other
       thing — one measurement of the carrier these name. */
    const templateCard = el("div", "carrier-templates");
    const presets = el("select", "carrier-preset");
    presets.replaceChildren(...presetOptions(cfg.type));
    presets.addEventListener("change", () => {
      const i = Number(presets.value);
      if (i < 0) return;
      take(fromPreset(cfg.type, carrierType(cfg.type).presets[i]));
    });
    const take = (next) => {
      link = { grid: next.rows === next.cols, size: next.w === next.h, gap: true };
      commit(next);
    };

    /* Three things to do with a whole carrier, under the catalogue it is
       chosen from, because all three are about the configuration rather than
       about any one number in it.

       Save and load are a file and not a list kept somewhere. A carrier that
       is not in the catalogue is one this lab made up, and what is wanted for
       one of those is to hand it to the next person and to the machine in the
       next room — which a list living in this browser cannot do. */
    const fileRow = el("div", "carrier-files");

    const load = el("button", "carrier-reset", "Load");
    load.type = "button";
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = "application/json,.json";
    picker.hidden = true;
    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      picker.value = "";
      if (!file) return;
      try {
        const read = JSON.parse(await file.text());
        /* Read as a carrier and not as whatever the file happened to hold: a
           configuration is the fields this panel edits, and anything else in
           there is somebody else's. An unreadable file leaves the carrier
           alone rather than half-replacing it. */
        if (!carrierType(read.type)) return;
        take({
          type: read.type,
          rows: Math.max(1, Math.round(read.rows ?? 1)),
          cols: Math.max(1, Math.round(read.cols ?? 1)),
          w: read.w, h: read.h, d: read.d ?? 0,
          gapX: read.gapX ?? 0, gapY: read.gapY ?? 0,
          cornerRatio: read.cornerRatio ?? 0,
        });
      } catch { /* not a carrier; the one on screen stands */ }
    });
    load.addEventListener("click", () => picker.click());

    const save = el("button", "carrier-reset", "Save");
    save.type = "button";
    save.addEventListener("click", () => {
      const file = new Blob([`${JSON.stringify(cfg, null, 2)}\n`],
        { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(file);
      a.download = `carrier-${cfg.type}-${cfg.cols}x${cfg.rows}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    });

    const reset = el("button", "carrier-reset", "Reset");
    reset.type = "button";
    reset.addEventListener("click", () =>
      take(fromPreset(cfg.type, carrierType(cfg.type).presets[0])));

    fileRow.append(load, save, reset, picker);
    /* Straight into the box, with no second frame around them: the box is
       already the object these belong to, and an edge inside an edge says the
       same thing twice. */
    templateCard.append(presets, fileRow);
    typeCard.append(templateCard);

    /* Every number the carrier is made of goes in one box: rows and columns,
       the size of an area, the pitch between them, the corner. They are one
       description of one thing, and a box apiece made a plate look like four
       decisions when it is one. */
    const { group: sizeBox, body: sizeCard } =
      sideGroup("Configure layout", "carrier-sizes");
    designer.append(sizeBox);

    /* Where the carrier is on the stage, as against what it is made of. A
       point is put on the drawing here and driven to on the microscope; what
       is done with the pair is the next thing to build. */
    const { group: anchorBox, body: anchorCard } = sideGroup("Align carrier");
    designer.append(anchorBox);

    const anchorAdd = el("button", "sf-flat", "Add alignment points");
    anchorAdd.type = "button";
    /* Put all four down at once. Where a carrier is registered from is a
       property of its shape, not something an operator should have to find by
       eye four times — what they do is drive to each one and say "here". */
    /* `cfg`, not `config`: this panel redraws itself in place rather than being
       rebuilt, so the argument it was first rendered with is the carrier the
       operator started on. Reading it here put a slide's four points on a
       dish. */
    anchorAdd.addEventListener("click", () => anchors.suggest(anchorsUm(cfg)));

    const anchorList = el("div", "point-list anchor-list");
    /* The points first, the button under them — the same way a recorded
       configuration reads. What the box is about is where the carrier has been
       aligned to; putting the button above that offered to lay a fresh set
       before the eye had reached the set already there. */
    anchorCard.append(anchorList, anchorAdd);

    /** The points put on the carrier so far, in the order they were placed. */
    const drawAnchors = () => {
      /* The set is complete or it is not there — where a carrier is aligned
         from is a property of its shape. So once the four are down the button
         stops offering to add and offers to lay them again, which is what an
         operator wants after dragging three of them somewhere unhelpful. */
      anchorAdd.textContent = anchors.list().length
        ? "Reset alignment"
        : "Add alignment points";
      anchorAdd.classList.toggle("on", anchors.arming());
      anchorList.textContent = "";
      anchors.list().forEach((a, i) => {
        const row = el("div", "point-row");
        const pick = el("div", "point-pick");
        /* Named by the border it sits on rather than numbered, because that is
           how it is found on the picture: an operator reading "left" knows
           which of the four green marks to drive to without counting. */
        /* Numbers alone. Four rows of coordinates each carrying "mm" is the
           unit written four times in a column where it never changes, and it
           was the width that pushed the pairs onto two lines. */
        /* Numbered, and nothing else but what was read. Where each point sits
           is drawn on the picture, and the row is for the reading taken there;
           saying the place again as a number filled it with the half an
           operator already knows and crowded out the half they came for. */
        pick.innerHTML = `<span class="idx">Point ${i + 1}</span>`
          /* What was read is not shown. The stage position is kept on the point
             — the alignment is worked out from it, and the drawing moves when
             it changes — but an operator reading this list wants to know which
             of the four are done, and "Snap again" says that already. Three
             numbers per row said it a second time and filled the column. */
          ;
        /* Drive the microscope to this place, then say so here: the point on
           the drawing and the place on the stage become one statement. */
        /* Short, because the row already has three numbers and a name in it and
           the channel is only so wide: "Snap to stage position" pushed the
           button off the edge as soon as a reading appeared beside it. What it
           snaps to is on the button when the pointer rests there, and said in
           full there rather than crowded onto the face. */
        /* The button carries the state of its own point: waiting, or done. Four
           rows that differ only in a word are four rows an operator has to
           read; four that differ in colour are four they can count. */
        const snap = el("button",
          a.stage ? "sf-flat anchor-snap done" : "sf-flat anchor-snap waiting",
          a.stage ? "Snap again" : "Snap");
        snap.type = "button";
        snap.title = "Snap to stage position — tie this point to where the stage is standing now";
        snap.addEventListener("click", () => anchors.snap(i));
        pick.append(snap);
        /* No way to forget one. The four are what this carrier is aligned by
           and they come from its shape, so throwing one away leaves a carrier
           aligned by three points and no way to get the fourth back short of
           laying the set again. Moving one is the answer to a mark in an
           awkward place. */
        /* Pointing at a row lights its mark on the picture. On hover because
           that is the gesture for "which one is this?", and it costs nothing
           to undo — the operator is looking, not choosing. */
        row.addEventListener("pointerenter", () => anchors.light(i));
        row.addEventListener("pointerleave", () => anchors.light(-1));
        row.append(pick);
        anchorList.append(row);
      });
    };
    anchors.onChange(drawAnchors);
    drawAnchors();

    /**
     * A row of numbers, with the button that ties two of them at the end.
     *
     * One builder for every row of fields in this panel, because a row of
     * boxes that behaved slightly differently in each group would be several
     * things to learn instead of one. How many boxes is the carrier's
     * business and not the row's: a deep carrier's size is three numbers, an
     * area's is two and a dish's is one, so the row is told how many to show
     * rather than being written out three times over.
     *
     * A row with nothing to tie has no tie column either, and its boxes run
     * the full width of the group. That is the alignment that reads: a dish
     * has no other row of numbers to line up with, so a box stopping thirty
     * pixels short of the edge lines up with nothing and merely looks short
     * of the buttons above it.
     */
    function numbers({ fields, key, step, decimals, max }) {
      const group = el("div", "carrier-group");
      const grid = el("div", "carrier-nums");
      const cells = fields.map((f) => {
        const i = document.createElement("input");
        i.type = "number";
        i.className = "carrier-num";
        /* What the box is of, said on the box. The row it is in and the order
           it stands in are layout and change with the carrier; what it edits
           does not, so that is what anything looking for it should go by. */
        i.dataset.field = f.name;
        i.step = String(step);
        if (max != null) i.max = String(max);
        i.addEventListener("input", () => {
          const v = parseFloat(i.value);
          if (i.value === "" || Number.isNaN(v)) return;
          f.set(v);
        });
        /* Clamping while typing fights the operator — "1" on its way to "12"
           is below a minimum of 6 and would be corrected out from under them.
           So the floor is applied when the field is left, not as it is used. */
        i.addEventListener("blur", () => {
          const v = parseFloat(i.value);
          f.set(Number.isNaN(v) ? f.min() : Math.max(f.min(), v));
          sync();
        });
        inputs.push({ i, get: f.get, decimals });
        return { ...f, label: el("span", "carrier-label", f.label), i };
      });

      let tie = null;
      if (key) {
        tie = el("button", "carrier-link");
        tie.type = "button";
        tie.dataset.key = key;
        tie.title = "Move both together";
        tie.addEventListener("click", () => {
          link[key] = !link[key];
          if (link[key]) cells[1].set(cells[0].get());
          commit({});
        });
      }

      // labels on the first line, boxes on the second, one column each
      if (!tie) grid.classList.add("no-tie");
      grid.append(...cells.map((c) => c.label));
      if (tie) grid.append(el("span"));
      grid.append(...cells.map((c) => c.i));
      if (tie) grid.append(tie);
      group.append(grid);
      sizeCard.append(group);

      /* How many columns the row is drawn in follows what is in it, so a
         field that is not this carrier's business takes its column with it
         rather than leaving a gap where it used to be. */
      const fit = () => {
        let shown = 0;
        for (const c of cells) {
          const on = !c.when || c.when(carrierType(cfg.type));
          c.label.hidden = c.i.hidden = !on;
          if (on) shown += 1;
        }
        grid.style.setProperty("--cols", String(shown));
      };
      fits.push(fit);
      return { group, tie };
    }

    const ties = {};
    const gridRow = numbers({
      key: "grid", step: 1, max: 50, decimals: 0,
      fields: [
        {
          name: "rows", label: "ROWS", get: () => cfg.rows, min: () => 1,
          set: (v) => commit(link.grid ? { rows: Math.round(v), cols: Math.round(v) } : { rows: Math.round(v) }),
        },
        {
          name: "cols", label: "COLUMNS", get: () => cfg.cols, min: () => 1,
          set: (v) => commit(link.grid ? { rows: Math.round(v), cols: Math.round(v) } : { cols: Math.round(v) }),
        },
      ],
    });
    // an area and a dish are one area; a row of ones says nothing
    showWhen(gridRow.group, (t) => t.grid);
    ties.grid = gridRow.tie;

    /* The size, which is two numbers or three. Depth is in this row rather
       than in one of its own because it is the same kind of statement as the
       other two — how big the thing is — and a carrier's size read across one
       line is one fact rather than a fact and a footnote. The tie stays about
       the width and the height: a cuvette is square across and deep, and
       tying its depth to its width would describe a different vessel. */
    const sizeRow = numbers({
      key: "size", step: 0.1, decimals: 2,
      fields: [
        {
          name: "w", label: "WIDTH (mm)", get: () => cfg.w, min: () => 0.1,
          set: (v) => commit(link.size ? { w: v, h: v } : { w: v }),
        },
        {
          name: "h", label: "HEIGHT (mm)", get: () => cfg.h, min: () => 0.1,
          set: (v) => commit(link.size ? { w: v, h: v } : { h: v }),
        },
        {
          name: "d", label: "DEPTH (mm)", get: () => cfg.d, min: () => 0.1,
          when: (t) => t.deep, set: (v) => commit({ d: v }),
        },
      ],
    });
    showWhen(sizeRow.group, (t) => !t.round);
    ties.size = sizeRow.tie;

    /* A round area has one measurement, and offering a width beside a height
       invites the operator to make it an ellipse it cannot be. */
    showWhen(numbers({
      step: 0.1, decimals: 2,
      fields: [{
        name: "diameter", label: "DIAMETER (mm)", get: () => cfg.w, min: () => 0.1,
        set: (v) => commit({ w: v, h: v }),
      }],
    }).group, (t) => t.round);

    /* Pitch is centre to centre, which is what a plate's datasheet quotes and
       what the stage will be told. The gap is what is stored, because it is
       what stays meaningful when the area is resized. */
    const pitchRow = numbers({
      key: "gap", step: 0.1, decimals: 2,
      fields: [
        {
          name: "columnPitch", label: "COLUMN PITCH (mm)", get: () => cfg.w + cfg.gapX, min: () => cfg.w,
          set: (v) => {
            const g = Math.max(0, v - cfg.w);
            commit(link.gap ? { gapX: g, gapY: g } : { gapX: g });
          },
        },
        {
          name: "rowPitch", label: "ROW PITCH (mm)", get: () => cfg.h + cfg.gapY, min: () => cfg.h,
          set: (v) => {
            const g = Math.max(0, v - cfg.h);
            commit(link.gap ? { gapX: g, gapY: g } : { gapY: g });
          },
        },
      ],
    });
    showWhen(pitchRow.group, (t) => t.grid);
    ties.gap = pitchRow.tie;

    const shapeGroup = el("div", "carrier-group");
    const shapeGrid = el("div", "carrier-nums");
    shapeGrid.append(
      el("span", "carrier-label", "CORNER RADIUS (mm)"),
      el("span", "carrier-label", "AREA (mm²)"),
      el("span"),
    );
    const cornerIn = document.createElement("input");
    cornerIn.type = "number";
    cornerIn.className = "carrier-num";
    cornerIn.dataset.field = "corner";
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
    areaIn.dataset.field = "area";
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
    sizeCard.append(shapeGroup);
    /* A corner belongs to a carrier whose areas are compartments — a well is
       round, a chamber's corners are moulded, and both are worth saying. A
       single free-standing area is a rectangle of the size just given, and a
       corner and an area restated from that size are two more numbers that
       only say it again. */
    showWhen(shapeGroup, (t) => t.grid);

    /* Where the run's own button goes: at the end of the numbers that decide
       it, so applying reads as the end of the editing.

       Nothing follows it. A panel of totals used to — carrier size, areas,
       layout, shape — and every one of them was already on screen: the layout
       is the two boxes above, the shape is the corner control and the drawing
       beside it, the areas are those two multiplied, and the size is in the
       rail. Restating the controls under the controls is the panel talking
       about itself. */
    card.append(el("div", "carrier-action"));

    function sync() {
      const type = carrierType(cfg.type);
      for (const [node, when] of groups) node.hidden = !when(type);
      for (const fit of fits) fit();
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
    }

    sync();
  },
};
