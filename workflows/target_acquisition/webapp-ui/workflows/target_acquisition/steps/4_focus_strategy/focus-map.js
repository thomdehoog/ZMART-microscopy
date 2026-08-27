/**
 * Step 4 — the focus map: where to measure the sample's height, and what was
 * measured there.
 *
 * A focus point is a **place**, not a position: somewhere the stage is driven
 * to and a height is read. That is a different question from where the run
 * will image, so nothing about the plan's grid has a say in where a point may
 * sit — points are laid so many to a tileset and settled against each other
 * until each sits in the middle of the ground it stands for.
 *
 * The map is drawn on the stage rather than in a picture of its own, with the
 * stage's own projection, because it is a statement about the same glass the
 * plan is drawn on. Two projections would be two answers to where a well is,
 * and the operator holding both.
 *
 * Everything here is one subject — the points, the sweeps that measured them,
 * the surface fitted through them, and the controls in the channel — so it is
 * one file. The gestures live here too: a press on the canvas over a point is
 * about this step, whoever owns the canvas.
 */

import carrierWidget from "../2_define_carrier/carrier-panel.js";
import { makeRng } from "../../microscope/pretend-sample/rng.js";
import { METRICS, METRIC_KEYS, scoreAt } from "../../microscope/pretend-sample/sweep.js";
import {
  affineSurface, fitSurface, residualsUm, surfaceZ,
} from "../../microscope/pretend-sample/surface.js";
import { sharePoints } from "../../shared/scanfields.js";


/**
 * Open the focus map on the page.
 *
 * `ctx` carries the run and the sample it is measuring, the stage picture it
 * draws on, the backend that does the measuring, and the page's plumbing.
 */
export function openTheFocusMap(ctx) {
  const {
    run, backend, stage, el, css, sizeCanvas, step,
    focusControls, renderActionBar, renderSide,
  } = ctx;
  const theSample = ctx.sample;

const carrierSpan = () => carrierWidget.extentUm(run.carrier);
const trueZ = (x, y) => {
  const [w, h] = carrierSpan();
  return -412 + 96 * (x / w - 0.5) + 61 * (y / h - 0.5);
};

function focusSurface() {
  const f = run.focus;
  const [w, h] = carrierSpan();
  if (f.strategy === "fixed") return affineSurface({ c: f.zFixed, width: w, height: h });
  if (f.strategy === "reuse") {
    return affineSurface({ ...PREVIOUS_SURFACES[f.reuse].plane, width: w, height: h });
  }
  return f.surface;
}

/* Fitting the focus surface — which model the geometry buys, the fit, the
   height it predicts anywhere, and the residuals — lives in
   `microscope/pretend-sample/surface.js`, imported above, mirroring the
   Python `workflow/_focus_surface.py`. */

// viridis — multi-hue but monotone in lightness, which is the property that
// matters: it stays readable in greyscale and for every kind of colour vision
const VIRIDIS = [
  [68, 1, 84], [72, 36, 117], [65, 68, 135], [53, 95, 141], [42, 120, 142],
  [33, 145, 140], [34, 168, 132], [68, 190, 112], [122, 209, 81], [189, 223, 38], [253, 231, 37],
];

function viridis(t) {
  const u = Math.max(0, Math.min(0.99999, t)) * (VIRIDIS.length - 1);
  const i = Math.floor(u), f = u - i;
  const a = VIRIDIS[i], b = VIRIDIS[i + 1];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

const zColor = (t) => { const c = viridis(t); return `rgb(${c[0]},${c[1]},${c[2]})`; };

/* The surface is continuous, so it is painted as a continuous field: one
   small offscreen buffer sampled across the sample bounds, then scaled up
   with smoothing. Nothing about z is per-tile — only the positions are. */
/* Its own camera. Sharing one with the canvas was tempting, but the two
   panels are different sizes, so a fit computed against one of them puts
   the sample off the edge of the other and clicks land nowhere. */

/** The plate, in the frame the plan is written in. */
function carrierBox() {
  const [w, h] = carrierSpan();
  return { xMin: 0, yMin: 0, xMax: w, yMax: h };
}

/* How far the positions themselves reach — the plate while there are none. */
function planBox() {
  return theSample().bounds ?? carrierBox();
}

/* Every position inside one compartment, by where it is rather than by any
   tag it carries: the plan is a flat list of tiles and a tile does not know
   which well it fell in, but the carrier says where every well is. */

/**
 * Where to measure the focus: so many points in every scan field, or by hand.
 *
 * A scan field is the unit because it is the unit of the plan: the operator
 * drew it, or the grid laid it, around something worth imaging, and a field
 * is small enough that a height measured in it is true of the rest of it.
 * There used to be four patterns to choose between — first, centre, every
 * nth, n at random — which was four answers to a question that only ever
 * had one: how many.
 *
 * A point sits on a scan position, never beside one: focus is measured where
 * the run will image, and a height read off the gap between positions is a
 * real number and a worthless one. Which positions is `sharePoints` in
 * `shared/scanfields.js`: the field is cut into as many equal blocks as points
 * were asked for, and the position nearest the middle of each is taken.
 */
const inScanOrder = (tiles) => [...tiles].sort((a, b) => (a.y - b.y) || (a.x - b.x));

/** The positions of each scan field, in scan order, fields with any tiles. */
/* The plan, in tilesets. Which positions make a tileset is the plan's own
   answer — a drawn one is a tileset, and the positions a grid laid in one
   area are that area's — because counting per field would be counting per
   frame, and a point asked for per tileset would land in every frame of the
   plate. */
function tilesByField() {
  const byTileset = new Map();
  for (const t of run.plan) {
    const key = t.tileset ?? t.fieldId;
    if (!byTileset.has(key)) byTileset.set(key, []);
    byTileset.get(key).push(t);
  }
  return [...byTileset.values()].map(inScanOrder);
}

const perField = (f) => Math.max(1, Math.round(f.perField) || 1);
const perCarrier = (f) => Math.max(1, Math.round(f.perCarrier) || 1);

/**
 * A set of points, shared out over the positions the run will visit.
 *
 * `over` says what they are shared out over: each tileset separately, so that
 * every drawn thing is measured in its own right; or the carrier as a whole,
 * one set of them over everything there is. The second is the answer for a
 * sample that sits flat — the height across a slide is one surface, and
 * measuring it once is cheaper than measuring it in every tileset that happens
 * to be on it.
 *
 * The two know different amounts. In each tileset knows only the tileset it is
 * working on, and gives the same answer for it whatever else the plan holds.
 * Across the carrier is the one that has been asked about the carrier, and is
 * the only one that looks at how the rest of it is laid out.
 *
 * Either way the ground is shared out by `sharePoints`, which settles the
 * points against the sample rather than against the frames that will image it,
 * and leaves each of them inside a frame.
 */
function patternFocusPoints(over = "tileset") {
  if (!run.plan.length) return [];
  const f = run.focus;
  /* Each way of laying them has its own number: so many inside every tileset,
     or so many over the carrier as a whole. */
  const n = over === "carrier" ? perCarrier(f) : perField(f);
  const drawn = tilesByField();
  /* Only the carrier-wide press knows there is a carrier. In each tileset is a
     question about that tileset and nothing outside it: so many points, spread
     as evenly over this drawn thing as they can be, and the same answer whether
     it is alone on a slide or one of ninety-six. Across the carrier is the
     press that has been asked about the whole of it, and there the wells being
     laid out identically is a fact about the thing being measured — points
     settled against it come to rest at the same spot in every one, so each is
     let off the middle of its share. */
  const vary = over === "carrier" && drawn.length > 1;
  const groups = over === "carrier" ? [inScanOrder(run.plan)] : drawn;
  return groups
    .flatMap((held) => sharePoints(held, n, { vary }))
    .map((t) => ({ x: t.x, y: t.y, z: null }));
}

/* The position under the pointer, if it is over one. A list of positions has
   no rows and columns to index into, so it is asked by distance. */
function nearestPosition(x, y) {
  let best = null;
  run.plan.forEach((t, i) => {
    const half = t.frameUm / 2;
    if (x < t.x - half || x > t.x + half || y < t.y - half || y > t.y + half) return;
    const d = Math.hypot(t.x - x, t.y - y);
    if (!best || d < best.d) best = { t, i, d };
  });
  return best;
}

const FIELD_W = 148, FIELD_H = 108;
const fieldCv = document.createElement("canvas");
fieldCv.width = FIELD_W; fieldCv.height = FIELD_H;

function paintSurface(surf, zLo, zHi, box) {
  const fctx = fieldCv.getContext("2d");
  const img = fctx.createImageData(FIELD_W, FIELD_H);
  const span = zHi - zLo || 1;
  let k = 0;
  for (let j = 0; j < FIELD_H; j++) {
    const y = box.yMin + ((j + 0.5) / FIELD_H) * (box.yMax - box.yMin);
    for (let i = 0; i < FIELD_W; i++) {
      const x = box.xMin + ((i + 0.5) / FIELD_W) * (box.xMax - box.xMin);
      const c = viridis((surfaceZ(surf, x, y) - zLo) / span);
      img.data[k++] = c[0]; img.data[k++] = c[1]; img.data[k++] = c[2]; img.data[k++] = 255;
    }
  }
  fctx.putImageData(img, 0, 0);
}

/**
 * The focus map, drawn onto the canvas rather than onto a map of its own.
 *
 * It is the same plate the rest of the run is looking at, so it is drawn in
 * the same place with the same projection: the carrier, the positions and
 * where the surface says each of them sits. A second map with a second
 * camera meant two answers to where a well is, and the operator holding both.
 */
function drawFocusLayer(ctx, toScreen, scale, w, h) {
  const f = run.focus;
  const surf = focusSurface();
  const showSurface = surf && (f.strategy !== "plane" || f.applied);

  // predicted z range across the sample, for the ramp and its legend
  /* How many of the plan's positions have an image in them by now. */
  const imaged = Math.max(run.tilesShown, 0);

  const box = planBox();
  let zLo = 0, zHi = 1;
  if (showSurface) {
    // a spline can bulge between its points, so sample the field rather than
    // trusting the corners the way a plane would let you
    zLo = Infinity; zHi = -Infinity;
    for (let j = 0; j <= 12; j++) {
      for (let i = 0; i <= 16; i++) {
        const z = surfaceZ(surf,
          box.xMin + (i / 16) * (box.xMax - box.xMin),
          box.yMin + (j / 12) * (box.yMax - box.yMin));
        if (z < zLo) zLo = z;
        if (z > zHi) zHi = z;
      }
    }
    if (zHi - zLo < 1) { zLo -= 0.5; zHi += 0.5; }
  }

  /* ---- the surface: fitted everywhere, shown only where it is used.
     The fit is global on purpose — every measured point informs it, and the
     ramp and its legend keep the range across the whole sample, so a tile's
     colour means the same thing wherever it sits. What gets painted is
     clipped to the positions, because the z it predicts between them is
     never going to be driven to: colouring the gaps states a focus for
     places this run does not visit. */
  /* **The prediction gets out of the picture's way.** A field that has been
     imaged has the answer in it, and a predicted height painted over that
     answer is the question drawn on top of it — no amount of fading fixes
     that, because fading it to see the image also fades the thing being read.
     So the fill stops at the fields nobody has been to yet, and an imaged
     field carries the same colour on its edge instead. The colour still means
     what it meant: the ramp is fitted across the whole sample either way. */
  if (showSurface && run.plan.length) {
    const [sx0, sy0] = toScreen(box.xMin, box.yMin);
    const sw = (box.xMax - box.xMin) * scale, sh = (box.yMax - box.yMin) * scale;
    paintSurface(surf, zLo, zHi, planBox());
    ctx.save();
    ctx.beginPath();
    run.plan.forEach((t, i) => {
      if (i < imaged) return;
      const [tx, ty] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      const sz = t.frameUm * scale;
      ctx.rect(tx, ty, sz, sz);
    });
    ctx.clip();
    ctx.globalAlpha = 0.82;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(fieldCv, sx0, sy0, sw, sh);
    ctx.restore();
  }

  // ---- the positions, exactly as the software reports them
  /* The positions themselves, as the scan fields laid them out. This panel
     works on the list the run is going to drive, not on a grid of its own. */
  run.plan.forEach((t, i) => {
    const [tx, ty] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
    const sz = t.frameUm * scale;
    /* An imaged field says its predicted height on its own edge, where it
       cannot cover what was taken there. Drawn heavier than the hairline that
       merely outlines a field, because here the line is carrying a reading
       rather than saying where a boundary is. */
    const carriesTheReading = showSurface && i < imaged;
    ctx.strokeStyle = carriesTheReading
      ? zColor((surfaceZ(surf, t.x, t.y) - zLo) / (zHi - zLo || 1))
      : (showSurface ? "rgba(255,255,255,0.30)" : css("--line-strong"));
    ctx.lineWidth = carriesTheReading ? 2 : 1;
    if (sz < 2) { ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(tx, ty, 2, 2); return; }
    ctx.strokeRect(tx + 0.5, ty + 0.5, sz - 1, sz - 1);
  });

  if (f.strategy === "auto") {
    ctx.fillStyle = css("--ink-3");
    ctx.font = '11px ui-monospace, Consolas, monospace';
    ctx.textAlign = "center";
    for (const t of run.plan) {
      const [tx, ty] = toScreen(t.x, t.y);
      if (t.frameUm * scale > 34) ctx.fillText("AF", tx, ty + 4);
    }
    ctx.textAlign = "left";
  }

  /* ---- focus points, as a reticle rather than a dot.
     Open in the middle, because the middle is the thing being pointed at:
     a filled marker hides the one pixel of the map it is about. The height
     is not written beside it either — the map says it in colour and the list
     says it in numbers, and a label per point tiles over the field it is
     annotating once there are more than a handful. */
  if (f.strategy === "plane") {
    const R = 4.5, ARM_IN = 6.5, ARM_OUT = 11;
    const reticle = (x, y) => {
      ctx.beginPath();
      ctx.arc(x, y, R, 0, Math.PI * 2);
      ctx.moveTo(x - ARM_OUT, y); ctx.lineTo(x - ARM_IN, y);
      ctx.moveTo(x + ARM_IN, y); ctx.lineTo(x + ARM_OUT, y);
      ctx.moveTo(x, y - ARM_OUT); ctx.lineTo(x, y - ARM_IN);
      ctx.moveTo(x, y + ARM_IN); ctx.lineTo(x, y + ARM_OUT);
    };
    /* The rectangle being drawn, if one is: grey and dashed, because it is a
       question about what it covers rather than a thing on the plate. */
    if (focusMarquee) {
      const [mx0, my0] = toScreen(
        Math.min(focusMarquee.sx, focusMarquee.cx), Math.min(focusMarquee.sy, focusMarquee.cy),
      );
      const [mx1, my1] = toScreen(
        Math.max(focusMarquee.sx, focusMarquee.cx), Math.max(focusMarquee.sy, focusMarquee.cy),
      );
      ctx.save();
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = css("--ink-3");
      ctx.fillStyle = "rgba(100, 116, 139, 0.12)";
      ctx.fillRect(mx0, my0, mx1 - mx0, my1 - my0);
      ctx.strokeRect(mx0, my0, mx1 - mx0, my1 - my0);
      ctx.restore();
    }

    f.points.forEach((p, i) => {
      const [x, y] = toScreen(p.x, p.y);
      /* Held, found by the pointer, or charted: all three are the same claim
         — this is one the next thing you do will happen to — so all three are
         said the same way, by drawing the mark heavier and ringing it. */
      const lit = picked().has(i) || i === f.hovered
        || (!picked().size && i === f.selected);
      /* One colour, whether the height has been read or not: the mark says
         where focus is measured, and the heat under it says what came back.
         Drawn over a dark halo, because viridis runs dark to bright and a
         mark that carried no contrast of its own disappeared into one end of
         it or the other. */
      reticle(x, y);
      ctx.lineWidth = lit ? 6 : 3.6; ctx.lineCap = "round";
      // a pale halo, because the mark itself is ink and the picture under
      // it can run dark
      ctx.strokeStyle = "rgba(255, 255, 255, 0.75)";
      ctx.stroke();
      reticle(x, y);
      ctx.lineWidth = lit ? 4 : 1.9;
      ctx.strokeStyle = css(lit ? "--mark-focus-lit" : "--mark-focus");
      ctx.stroke();
      ctx.lineCap = "butt";
    });
  }

  // ---- ramp legend
  if (showSurface) {
    // the legend sits ON the field, so it carries its own plate
    const bw = 132, bh = 9, bx = 20, by = h - 26;
    const padL = 8, top = by - 36;
    ctx.fillStyle = css("--screen");
    ctx.globalAlpha = 0.88;
    ctx.fillRect(bx - padL, top, bw + padL * 2, (by + bh + 7) - top);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = css("--line");
    ctx.lineWidth = 1;
    ctx.strokeRect(bx - padL + 0.5, top + 0.5, bw + padL * 2 - 1, (by + bh + 7) - top - 1);

    for (let i = 0; i < bw; i++) {
      ctx.fillStyle = zColor(i / bw);
      ctx.fillRect(bx + i, by, 1.4, bh);
    }
    ctx.strokeStyle = css("--line-strong");
    ctx.strokeRect(bx - 0.5, by - 0.5, bw + 1, bh + 1);

    ctx.fillStyle = css("--ink-3");
    ctx.font = '11.5px system-ui, sans-serif';
    ctx.fillText("predicted focus height", bx, top + 14);
    ctx.font = '11px ui-monospace, Consolas, monospace';
    ctx.fillStyle = css("--ink-2");
    ctx.fillText(`${zLo.toFixed(0)}`, bx, by - 5);
    ctx.textAlign = "right";
    ctx.fillText(`${zHi.toFixed(0)} µm`, bx + bw, by - 5);
    ctx.textAlign = "left";
  }

}

/* A focus point being dragged: which one, and whether the pointer has
   actually moved since it was taken hold of. A press that never moves is
   still a press, and means the other thing — take this point away. */
let focusDrag = null;

/* Shift and drag over the map picks out the points the rectangle covers, the
   same gesture that picks tilesets a step earlier. Held in screen pixels
   while it is being drawn, because that is where the rectangle is. */
let focusMarquee = null;

/** How small a rectangle is too small to have been meant — a shifted press. */
const MARQUEE_MIN_PX = 4;

/** Which points the picked set holds, kept as a set of places, not indexes. */
const picked = () => run.focus.picked ?? (run.focus.picked = new Set());

/** Where the pointer is, in the carrier's own coordinates. */
function pointerInCarrier(px, py) {
  const [wx, wy] = stage.toWorld(px, py);
  const [ox, oy] = stage.carrierOriginUm();
  return [wx - ox, wy - oy];
}

/* How near a press has to be to take hold of a point: a few pixels, measured
   in what the picture is showing rather than in micrometres, so it is the
   same reach whatever the zoom. */
const POINT_REACH_PX = 10;

/** The focus point under the pointer, if the map is open to being changed. */
function focusPointAt(px, py) {
  const f = run.focus;
  if (step(run.activeIdx).mode !== "focus") return -1;
  if (f.strategy !== "plane" || run.running) return -1;
  const [x, y] = pointerInCarrier(px, py);
  const reach = POINT_REACH_PX / stage.view.scale;
  let at = -1, bestD = reach;
  f.points.forEach((p, i) => {
    const d = Math.hypot(p.x - x, p.y - y);
    if (d <= bestD) { at = i; bestD = d; }
  });
  return at;
}

/**
 * Taking hold of a point on the canvas, so it can be moved to another
 * position — dragged rather than deleted and placed again, because moving one
 * is what an operator means by "not there, there", and two gestures to say
 * one thing is one gesture too many.
 */
function focusGrabbed(e) {
  const f = run.focus;
  if (step(run.activeIdx).mode !== "focus") return false;
  if (f.strategy !== "plane" || run.running) return false;

  const at = focusPointAt(e.offsetX, e.offsetY);
  if (at < 0) {
    /* Shift on empty ground draws the rectangle; a plain press there lets go
       of whatever was picked and falls through to the pan. */
    if (e.shiftKey) {
      const [x, y] = pointerInCarrier(e.offsetX, e.offsetY);
      focusMarquee = { sx: x, sy: y, cx: x, cy: y };
      return true;
    }
    if (picked().size) { picked().clear(); renderPointList(); stage.draw(); }
    return false;
  }

  /* Shift on a point adds it to what is held, or takes it back out. Without
     shift, a press on a point that is not held picks that one alone — and a
     press on one that is held keeps the whole set, so a group can be dragged
     by any of its members. */
  if (e.shiftKey) {
    if (picked().has(at)) picked().delete(at); else picked().add(at);
  } else if (!picked().has(at)) {
    picked().clear();
    picked().add(at);
  }
  focusDrag = { at, moved: false, held: f.points.map((p) => ({ x: p.x, y: p.y })) };
  f.selected = at;
  renderPointList(); drawTrace(); stage.draw();
  return true;
}

/** The rectangle being drawn, in the carrier's own coordinates. */
function focusMarqueeTo(px, py) {
  const [x, y] = pointerInCarrier(px, py);
  focusMarquee = { ...focusMarquee, cx: x, cy: y };
  stage.draw();
}

/* What the rectangle covered. A rectangle too small to have been meant is a
   shifted press that was about to add to what is held, so it leaves the set
   alone rather than emptying it. */
function focusMarqueeTook(shift) {
  const m = focusMarquee;
  focusMarquee = null;
  if (!m) return;
  const box = {
    xMin: Math.min(m.sx, m.cx), yMin: Math.min(m.sy, m.cy),
    xMax: Math.max(m.sx, m.cx), yMax: Math.max(m.sy, m.cy),
  };
  if (Math.max(box.xMax - box.xMin, box.yMax - box.yMin) * stage.view.scale < MARQUEE_MIN_PX) {
    stage.draw();
    return;
  }
  const f = run.focus;
  if (!shift) picked().clear();
  f.points.forEach((p, i) => {
    if (p.x >= box.xMin && p.x <= box.xMax && p.y >= box.yMin && p.y <= box.yMax) {
      picked().add(i);
    }
  });
  if (picked().size) f.selected = Math.min(...picked());
  renderPointList(); drawTrace(); stage.draw();
}

/* A point goes wherever the pointer goes: it is a place the stage is driven
   to, not a frame the run images, so nothing about the plan's grid has a
   say in where it may sit. */
function focusDraggedTo(px, py) {
  if (!focusDrag) return;
  focusDrag.moved = true;
  const f = run.focus;
  const was = focusDrag.held[focusDrag.at];
  if (!was) return;
  const [x, y] = pointerInCarrier(px, py);
  /* Measured from where the points were when they were taken hold of, not
     from where they are now: a drag that added its own last step every time
     would run away from the pointer. Everything held moves together. */
  const dx = x - was.x, dy = y - was.y;
  const moving = picked().size ? picked() : new Set([focusDrag.at]);
  for (const i of moving) {
    const p = f.points[i], from = focusDrag.held[i];
    if (!p || !from) continue;
    /* Moved off what was read for it: the height belonged to where it was.
       A point that had one is kept in the list and greyed — the reading is
       stale, not missing — where one that never had a reading is not listed
       at all until the map is measured again. */
    f.points[i] = {
      ...p, x: from.x + dx, y: from.y + dy,
      z: null, residual: null, stale: p.z !== null || !!p.stale,
    };
  }
  refitSurface();
  stage.draw(); renderPointList();
}

/**
 * What the pointer says on the focus step. Answered here rather than at the
 * moment of the press, so a crosshair armed from the panel says so before the
 * mouse is moved to find out — and so the one place that sets the canvas
 * cursor keeps setting it. The drawing calls this; nothing else assigns it.
 */
function focusCursor() {
  if (step(run.activeIdx).mode !== "focus") return "";
  const f = run.focus;
  if (f.strategy !== "plane" || run.running) return "";
  if (f.hovered >= 0) return "grab";
  return f.placing ? "crosshair" : "";
}

/**
 * The pointer passing over the map: whether it has found a focus point, and
 * saying so on the canvas. Answered true when it has, so whatever else the
 * pointer would have reported is not asked.
 */
function focusHovered(e) {
  const f = run.focus;
  if (step(run.activeIdx).mode !== "focus") return false;
  const at = focusPointAt(e.offsetX, e.offsetY);
  if (at === f.hovered) return at >= 0;
  f.hovered = at;
  stage.draw();
  return at >= 0;
}

/* Placing a point is a press on the canvas with the crosshair armed. Armed
   rather than always live, because the same press pans the picture and a
   step where every press moves the plan is a step nobody can look around in.

   The point lands where the press landed, on ground that has none. */
function focusPressed(px, py) {
  const f = run.focus;
  if (step(run.activeIdx).mode !== "focus") return false;
  if (!f.placing || f.strategy !== "plane" || run.running) return false;
  /* A press that landed on a point has already done its work: the press
     picked it, and picking is what a press on a thing means. It used to take
     the point away instead — the armed tool's other half — which made every
     point one careless press from gone and made choosing one on the map
     impossible while the tool was armed. Taking one away is the cross in the
     list, or Delete. */
  if (focusPointAt(px, py) >= 0) return true;

  const [x, y] = pointerInCarrier(px, py);
  f.points.push({ x, y, z: null });
  /* The one just put down is the one being worked on: it is what the hand is
     pointing at, and the next thing said — a drag, Delete — is about it
     rather than about whatever was picked before. */
  picked().clear();
  picked().add(f.points.length - 1);
  f.selected = f.points.length - 1;
  drawTrace();
  stage.draw(); renderPointList(); renderActionBar();
  return true;
}

/* An anchor point lands where the press landed, once the button has armed
   it. Armed rather than always live, for the reason the focus crosshair is:
   the same press pans the picture. */
function anchorPressed(px, py) {
  if (step(run.activeIdx).mode !== "carrier" || !run.anchoring) return false;
  const [x, y] = pointerInCarrier(px, py);
  run.anchors = [...run.anchors, { x, y }];
  run.anchoring = false;
  renderSide(true);
  stage.draw();
  return true;
}

/* The same press during detection picks the test position: the channel's
   preview is one tile, and pointing at a position on the canvas is how it
   is chosen — the pager beside the preview is the other way. */
function detectPressed(px, py) {
  if (step(run.activeIdx).mode !== "detect" || run.running) return false;
  const [wx, wy] = stage.toWorld(px, py);
  const [ox, oy] = stage.carrierOriginUm();
  const hit = nearestPosition(wx - ox, wy - oy);
  if (!hit) return false;
  const d = run.detect;
  if (d.tile !== hit.i) {
    d.tile = hit.i;
    d.tested = false;
  }
  detectionShown?.redraw(); stage.draw(); renderActionBar();
  return true;
}

/* The rehearsed autofocus sweep — the two sharpness metrics, the debris a
   position may carry, every candidate peak and the one worth trusting —
   lives in `microscope/pretend-sample/sweep.js`, imported above. The trace
   below draws exactly the curve the unit tests measure. */

/* The bar that makes the points and the list of the ones there are: one
   section, so they are drawn together and cannot disagree about how many. */
function renderFocusBar() {
  if (!focusMounted()) return;
  const f = run.focus;
  /* Running freezes the box, a finished test does not: measuring a map is a
     reading of it, not a lock on it. Points can be added, moved and taken
     away afterwards, and the map measured again — what has no reading yet
     says so in the list until it does. */
  const frozen = !!run.running || f.strategy !== "plane";

  /* One number, always asked: how many points to lay in each scan field. */
  const count = el("fp-count");
  // never while it is being typed into, or a 1 on its way to 12 is corrected
  if (document.activeElement !== count) count.value = String(perField(f));
  const countAll = el("fp-count-all");
  if (document.activeElement !== countAll) countAll.value = String(perCarrier(f));
  countAll.disabled = frozen || !run.plan.length;
  count.disabled = frozen;

  el("fp-place").disabled = frozen || !run.plan.length;
  el("fp-place-all").disabled = frozen || !run.plan.length;
  el("fp-clear").disabled = frozen || !f.points.length;
  /* Only once there is a map to act on. Rerun and Refine both measure points
     that are already down; Reset throws away what a run produced. */
  const ran = f.strategy === "plane" && f.applied && f.points.length > 0;
  el("fp-again").hidden = !ran;
  /* And the step's own press goes when they arrive. Once a map exists the bar
     offers "Run again", which is what Rerun does and says less about how — two
     presses a hand's width apart, both meaning measure it again, one of them
     silent about where the search starts. Before there is a map it is the only
     way to make one, so it stays until there is. */
  document.querySelector(".fp-run").hidden = ran;
  for (const id of ["fp-rerun", "fp-refine", "fp-reset"]) {
    el(id).disabled = !ran || !!run.running;
  }
  /* The traces are what the run came back with, so the box that reads them
     is not there until it has. What the map came to is in the rows: a height
     for every point and how far each sits from the surface. */
  el("focus-traces").hidden = !f.applied;

  const pick = el("fp-pick");
  pick.disabled = frozen || !run.plan.length;
  pick.classList.toggle("on", !!f.placing && !frozen);
  /* One of the two is always on, so a press on the map is never a question:
     the crosshair puts a point down, and the arrow picks one that is. */
  const select = el("fp-select");
  select.disabled = frozen || !run.plan.length;
  select.classList.toggle("on", !f.placing && !frozen);
  // the cursor says what the next press will do, the way it does when a
  // scan field is being drawn — worked out in one place, and set there
  stage.cursor(focusCursor());
}

/* The focus controls are in the document only while their step is standing —
   the channel takes them in and gives them back. Anything that writes into
   them has to ask first, or a redraw from somewhere else reaches for an
   element that is not there. */
const focusMounted = () => focusControls.isConnected;

function renderPointList() {
  if (!focusMounted()) return;
  const f = run.focus;
  const host = el("point-list");
  host.textContent = "";
  renderFocusBar();

  if (f.strategy !== "plane") {
    const d = document.createElement("div");
    d.className = "none";
    d.textContent = f.strategy === "auto"
      ? "Per-tile autofocus measures every position — no points to place."
      : f.strategy === "fixed"
        ? "A fixed height needs no measured points."
        : "The stored surface already carries its points.";
    host.append(d);
    return;
  }
  if (!f.points.length) {
    const d = document.createElement("div");
    d.className = "none";
    d.textContent = "Click the position map to place focus points. Three or more spread-out points make a plane.";
    host.append(d);
    return;
  }

  f.points.forEach((p, i) => {
    /* Only what has a trace to inspect, or had one: a point put down after
       the map was measured has nothing to show and waits on the map until
       the next test gives it a reading. */
    if (p.z === null && !p.stale) return;

    /* A row, not a button: it holds one — the row itself picks the point —
       and a cross of its own for throwing it away. A button inside a button
       is not a thing a browser will draw. */
    const row = document.createElement("div");
    row.className = p.stale ? "point-row stale" : "point-row";
    /* Held, or the one whose trace is charted: the list marks what the
       canvas marks, so a rectangle drawn over the map is answered here. */
    row.setAttribute("aria-current",
      String(picked().has(i) || (!picked().size && i === f.selected)));
    const suspect = p.onNarrow || (f.worst === i && Math.abs(p.residual || 0) > 3);
    const pick = document.createElement("button");
    pick.className = "point-pick"; pick.type = "button";
    pick.innerHTML =
      `<span class="idx">${i + 1}</span>` +
      `<span>${(p.x / 1000).toFixed(2)}, ${(p.y / 1000).toFixed(2)} mm</span>` +
      (p.residual === undefined || p.residual === null ? ""
        : `<span class="res"${suspect ? ' style="color:var(--bad)"' : ""}>` +
          `${p.residual >= 0 ? "+" : ""}${p.residual.toFixed(1)}</span>`) +
      `<span class="z${p.z === null ? " pending" : ""}"` +
      `${suspect && !p.manual ? ' style="color:var(--bad)"' : ""}>` +
      `${p.z === null ? "—" : (p.manual ? "✎ " : suspect ? "⚠ " : "") + p.z.toFixed(1) + " µm"}</span>`;
    /* A moved point has no trace to show — what was read was read of where it
       used to be — so its row says so by being unpressable until the map is
       measured again. */
    pick.disabled = !!p.stale;
    pick.addEventListener("click", () => {
      f.selected = i;
      renderPointList(); drawTrace(); stage.draw();
    });

    const drop = document.createElement("button");
    drop.className = "rec-drop point-drop"; drop.type = "button";
    drop.textContent = "✕";
    drop.title = "stop measuring here";
    drop.disabled = !!run.running;
    drop.addEventListener("click", () => {
      f.points.splice(i, 1);
      f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
      refitSurface();
      renderPointList(); drawTrace(); stage.draw(); renderActionBar();
    });

    row.append(pick, drop);
    host.append(row);
  });
}

const traceCv = el("trace-canvas");

function drawTrace() {
  if (!focusMounted()) return;
  const f = run.focus;
  /* A point put down after the map was measured has no reading yet, and a
     trace is the reading: there is nothing to draw for it until the map is
     measured again. */
  const has = f.strategy === "plane" && f.applied
    && f.points.length > f.selected && f.points[f.selected]?.z !== null;
  el("trace-empty").classList.toggle("hidden", has);
  /* Which point is being read is said by the list, where the row is marked,
     and by the map, where the mark is drawn heavier. The heading says what
     the box is, once. */
  if (!has || !sizeCanvas(traceCv)) return;

  const ctx = traceCv.getContext("2d");
  const w = traceCv.cssW, h = traceCv.cssH;
  ctx.clearRect(0, 0, w, h);
  // the plot stands on the same white the box does: a tinted panel inside a
  // white card read as a second surface for one of the three parts
  ctx.fillStyle = css("--screen");
  ctx.fillRect(0, 0, w, h);

  /* Both metrics on one plot. They score the same stack on different
     scales, so each is normalised to its own maximum — the shapes are the
     comparison, not the absolute numbers. */
  const traces = f.points[f.selected]?.traces;
  if (!traces) return;
  const curves = METRIC_KEYS.map((key) => {
    const sw = traces[key];
    const peak = Math.max(...sw.samples.map((q) => q.s)) || 1;
    return { key, sw, norm: sw.samples.map((q) => ({ z: q.z, s: q.s / peak })) };
  });
  const deciding = curves.find((c) => c.key === f.metric) || curves[0];
  const t = deciding.sw;

  const P = { l: 40, r: 14, t: 16, b: 30 };
  const zs = t.samples.map((p) => p.z);
  const zLo = Math.min(...zs), zHi = Math.max(...zs);
  const sHi = 1.16;
  const X = (z) => P.l + ((z - zLo) / (zHi - zLo)) * (w - P.l - P.r);
  const Y = (s) => (h - P.b) - (s / sHi) * (h - P.t - P.b);
  const decidingPeak = Math.max(...t.samples.map((q) => q.s)) || 1;

  // recessive frame
  ctx.strokeStyle = css("--line");
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(P.l, P.t); ctx.lineTo(P.l, h - P.b); ctx.lineTo(w - P.r, h - P.b);
  ctx.stroke();

  ctx.fillStyle = css("--ink-3");
  ctx.font = '10.5px ui-monospace, Consolas, monospace';
  ctx.textAlign = "center";
  ctx.fillText(`${zLo.toFixed(0)}`, X(zLo) + 10, h - P.b + 15);
  ctx.fillText(`${zHi.toFixed(0)} µm`, X(zHi) - 16, h - P.b + 15);
  ctx.save();
  ctx.translate(13, (P.t + h - P.b) / 2); ctx.rotate(-Math.PI / 2);
  ctx.font = '11px system-ui, sans-serif';
  ctx.fillText("sharpness", 0, 0);
  ctx.restore();
  ctx.textAlign = "left";

  // the comparison curve first, so the deciding one reads on top
  legendHits = [];
  let lx = P.l + 8;
  for (const c of curves) {
    const isDeciding = c === deciding;
    ctx.save();
    ctx.strokeStyle = css(METRICS[c.key].token);
    ctx.lineWidth = isDeciding ? 2 : 1.5;
    ctx.globalAlpha = isDeciding ? 1 : 0.55;
    if (!isDeciding) ctx.setLineDash([4, 3]);
    ctx.beginPath();
    c.norm.forEach((q, i) => { const x = X(q.z), y = Y(q.s); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.restore();

    // legend doubles as the control: click a metric to let it decide
    ctx.save();
    ctx.strokeStyle = css(METRICS[c.key].token);
    ctx.lineWidth = isDeciding ? 2.5 : 1.5;
    if (!isDeciding) ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(lx, P.t + 3); ctx.lineTo(lx + 16, P.t + 3); ctx.stroke();
    ctx.restore();
    ctx.font = `${isDeciding ? "600 " : ""}11px system-ui, sans-serif`;
    ctx.fillStyle = isDeciding ? css("--ink") : css("--ink-3");
    const label = METRICS[c.key].short + (isDeciding ? " · deciding" : "");
    ctx.fillText(label, lx + 22, P.t + 7);
    const wLab = 22 + ctx.measureText(label).width;
    legendHits.push({ key: c.key, x0: lx - 4, x1: lx + wLab + 4, y0: P.t - 6, y1: P.t + 13 });
    lx += wLab + 18;
  }

  // everything below is drawn against the deciding curve, so its raw scores
  // are normalised the same way the curve was
  const N = (s) => s / decidingPeak;
  const p = f.points[f.selected];
  // sweep() is deterministic, so the recomputed candidate at the recorded
  // height is the same peak the rule picked when the strategy ran
  const chosen = t.candidates.find((c) => Math.abs(c.z - p.zAuto) < 1e-6) || t.candidates[0];

  // every measured z
  for (const q of t.samples) {
    ctx.beginPath();
    ctx.arc(X(q.z), Y(N(q.s)), 2.2, 0, Math.PI * 2);
    ctx.fillStyle = css("--mark-context");
    ctx.fill();
  }

  // candidate peaks the rule turned down — a narrow one is almost always a
  // speck of debris, and this is where it becomes visible instead of silent
  for (const c of t.candidates) {
    if (c === chosen || Math.abs(c.z - chosen.z) < 1e-6) continue;
    ctx.beginPath();
    ctx.arc(X(c.z), Y(N(c.s)), 4, 0, Math.PI * 2);
    ctx.strokeStyle = c.narrow ? css("--bad") : css("--ink-3");
    ctx.lineWidth = 1.6;
    ctx.stroke();
    if (c.narrow) {
      ctx.fillStyle = css("--bad");
      ctx.font = '10px ui-monospace, Consolas, monospace';
      const lbl = `${c.width.toFixed(1)} µm wide`;
      const lw = ctx.measureText(lbl).width;
      ctx.fillText(lbl, Math.max(P.l, Math.min(X(c.z) - lw / 2, w - P.r - lw)), Y(N(c.s)) - 8);
    }
  }

  // the parabola through the chosen peak's three samples
  if (chosen.used && chosen.used.length === 3 && chosen.used[0] !== chosen.used[1]) {
    ctx.save();
    ctx.strokeStyle = "#16a34a";
    ctx.lineWidth = 1.6;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    const [q0, q1, q2] = chosen.used;
    for (let i = 0; i <= 40; i++) {
      const z = q0.z + ((q2.z - q0.z) * i) / 40;
      const l0 = ((z - q1.z) * (z - q2.z)) / ((q0.z - q1.z) * (q0.z - q2.z));
      const l1 = ((z - q0.z) * (z - q2.z)) / ((q1.z - q0.z) * (q1.z - q2.z));
      const l2 = ((z - q0.z) * (z - q1.z)) / ((q2.z - q0.z) * (q2.z - q1.z));
      const s = q0.s * l0 + q1.s * l1 + q2.s * l2;
      const x = X(z), y = Y(N(s));
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
    for (const q of chosen.used) {
      ctx.beginPath(); ctx.arc(X(q.z), Y(N(q.s)), 3.6, 0, Math.PI * 2);
      ctx.fillStyle = "#0284c7"; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = css("--surface-2"); ctx.stroke();
    }
  }

  // where the metric put the peak — kept visible as a reference once the
  // operator has dragged the chosen height somewhere else
  if (p.manual) {
    ctx.save();
    ctx.globalAlpha = 0.45;
    ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 1.5;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(X(p.zAuto), P.t); ctx.lineTo(X(p.zAuto), h - P.b);
    ctx.stroke();
    ctx.restore();
  }

  // the draggable height
  const zSel = p.z;
  const sSel = N(scoreAt(t.samples, zSel));
  const xSel = X(zSel);
  // a peak too narrow to be tissue never gets to look like a confident answer
  const pickColour = p.manual ? css("--accent") : (p.onNarrow ? css("--bad") : "#16a34a");
  ctx.strokeStyle = pickColour;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(xSel, P.t); ctx.lineTo(xSel, h - P.b);
  ctx.stroke();

  // a grab handle, so it reads as draggable
  ctx.fillStyle = pickColour;
  ctx.beginPath();
  ctx.moveTo(xSel - 5, P.t); ctx.lineTo(xSel + 5, P.t); ctx.lineTo(xSel, P.t + 7);
  ctx.closePath(); ctx.fill();

  ctx.beginPath(); ctx.arc(xSel, Y(sSel), 4.4, 0, Math.PI * 2);
  ctx.fill();
  ctx.lineWidth = 1.8; ctx.strokeStyle = css("--surface-2"); ctx.stroke();

  const lab = p.onNarrow && !p.manual
    ? `${zSel.toFixed(1)} µm · ${chosen.width.toFixed(1)} µm wide`
    : `${zSel.toFixed(1)} µm`;
  ctx.font = '11px ui-monospace, Consolas, monospace';
  const tw = ctx.measureText(lab).width;
  ctx.fillStyle = p.manual ? css("--accent-deep") : pickColour;
  ctx.fillText(lab, Math.min(xSel + 7, w - P.r - tw), Y(sSel) - 7);

  traceGeom = { zLo, zHi, P, w, h, samples: t.samples };
}

let traceGeom = null;
let legendHits = [];


/* The image at the chosen height is parked. It was a second thing to read
   beside the plot and the plot is what says whether a height is the right
   one; the drawing comes back with the box that shows it. */
/* ---- drag the height, and watch the image follow -----------------------
   The whole reason the preview is here: a peak the metric loved can be a
   speck, and the operator decides by looking rather than by trusting. */
let scrubbing = false;

function scrubTo(clientOffsetX) {
  const f = run.focus;
  if (!traceGeom || f.strategy !== "plane" || !f.applied) return;
  const p = f.points[f.selected];
  const { zLo, zHi, P, w } = traceGeom;
  const t = Math.max(0, Math.min(1, (clientOffsetX - P.l) / (w - P.l - P.r)));
  p.z = zLo + t * (zHi - zLo);
  p.manual = Math.abs(p.z - p.zAuto) > 0.05;
  refitSurface();
  drawTrace(); renderPointList(); stage.draw();
}

traceCv.addEventListener("pointerdown", (e) => {
  const f = run.focus;
  if (f.strategy !== "plane" || !f.applied) return;
  // the legend is the metric control — no separate row of buttons for it
  const hit = legendHits.find((g) =>
    e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
  if (hit) {
    if (hit.key !== f.metric) {
      f.metric = hit.key;
      remeasure().then(() => {
        drawTrace(); renderPointList(); stage.draw(); renderActionBar();
      });
    }
    return;
  }
  scrubbing = true;
  traceCv.setPointerCapture(e.pointerId);
  scrubTo(e.offsetX);
});

traceCv.addEventListener("pointermove", (e) => {
  if (scrubbing) return;
  const over = legendHits.some((g) =>
    e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
  traceCv.style.cursor = over ? "pointer" : "ew-resize";
});
traceCv.addEventListener("pointermove", (e) => { if (scrubbing) scrubTo(e.offsetX); });
traceCv.addEventListener("pointerup", (e) => {
  scrubbing = false;
  traceCv.releasePointerCapture?.(e.pointerId);
});
traceCv.addEventListener("pointercancel", () => { scrubbing = false; });

// keyboard equivalent, because a drag-only control is not operable by everyone
traceCv.tabIndex = 0;
traceCv.setAttribute("role", "slider");
traceCv.setAttribute("aria-label", "focus height for the selected point");
traceCv.addEventListener("keydown", (e) => {
  const f = run.focus;
  if (f.strategy !== "plane" || !f.applied) return;
  const nudge = { ArrowLeft: -0.5, ArrowRight: 0.5, PageDown: -3, PageUp: 3 }[e.key];
  if (nudge === undefined) return;
  e.preventDefault();
  const p = f.points[f.selected];
  p.z += nudge * (e.shiftKey ? 4 : 1);
  p.manual = Math.abs(p.z - p.zAuto) > 0.05;
  refitSurface();
  drawTrace(); renderPointList(); stage.draw();
});

// ---- laying points by the number, rather than clicking positions one by one
el("fp-count-all").addEventListener("input", () => {
  const v = parseInt(el("fp-count-all").value, 10);
  if (Number.isNaN(v)) return;
  run.focus.perCarrier = Math.min(99, Math.max(1, v));
});
el("fp-count-all").addEventListener("blur", () => { renderFocusBar(); });
el("fp-count").addEventListener("input", () => {
  const v = parseInt(el("fp-count").value, 10);
  if (Number.isNaN(v)) return;
  run.focus.perField = Math.min(99, Math.max(1, v));
  renderFocusBar();
});
el("fp-count").addEventListener("blur", () => { renderFocusBar(); });
el("fp-pick").addEventListener("click", () => {
  const f = run.focus;
  f.placing = !f.placing;
  renderPointList();
});
/* Disarming, said as a thing to press rather than as pressing the armed tool
   again — the step before names it the same way, and a row where nothing is on
   leaves an operator wondering what a press on the map will do. */
el("fp-select").addEventListener("click", () => {
  run.focus.placing = false;
  renderPointList();
});
/* A fresh set, not more on top: the points are settled against each other —
   every one stands for its own share of the group — so laying a second set
   through the first would leave neither arrangement true. What is kept by hand
   is kept by not pressing either of these. */
const layPoints = (over) => {
  const f = run.focus;
  f.points = patternFocusPoints(over);
  picked().clear();
  f.selected = 0;
  stage.draw(); renderPointList(); drawTrace(); renderActionBar();
};
el("fp-place").addEventListener("click", () => layPoints("tileset"));
el("fp-place-all").addEventListener("click", () => layPoints("carrier"));
/* Delete takes away whichever point is chosen — the one the canvas is
   drawing heavier and the list has highlighted. The same key does the same
   thing to a scan field one step earlier, and a map is edited the way a plan
   is. */
window.addEventListener("keydown", (e) => {
  if (step(run.activeIdx).mode !== "focus" || run.running) return;
  if (e.key !== "Delete" && e.key !== "Backspace") return;
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const f = run.focus;
  if (f.strategy !== "plane" || !f.points.length) return;
  e.preventDefault();
  /* Everything held, or the charted one when nothing is: the same key, and
     the same meaning, whether one point was picked or a rectangle full. */
  const going = picked().size ? picked() : new Set([f.selected]);
  f.points = f.points.filter((_, i) => !going.has(i));
  picked().clear();
  f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
  f.hovered = -1;
  refitSurface();
  stage.draw(); renderPointList(); drawTrace(); renderActionBar();
});

el("fp-clear").addEventListener("click", () => {
  run.focus.points = [];
  picked().clear();
  stage.draw(); renderPointList(); drawTrace(); renderActionBar();
});

/* Measuring an existing map again. Both presses re-run every point that is
   down; they differ only in where each search begins, which is what `from`
   carries into the backend.

   The map is put away while the objective is out, because what is on screen
   during the run is the old answer and the picture would go on drawing a
   surface the run is in the middle of replacing. */
const runAgain = async (from, button) => {
  const f = run.focus;
  if (run.running || !f.applied || !f.points.length) return;
  run.running = true;
  button.classList.add("on");
  renderFocusBar(); renderActionBar();
  try {
    await remeasure({ from });
  } finally {
    run.running = false;
    button.classList.remove("on");
  }
  f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
  stage.draw(); renderPointList(); drawTrace(); renderFocusBar(); renderActionBar(); renderSide();
};
el("fp-rerun").addEventListener("click", (e) => runAgain("stage", e.currentTarget));
el("fp-refine").addEventListener("click", (e) => runAgain("map", e.currentTarget));

/* Everything the step has to show for itself, thrown away together: the map,
   the points it was fitted through, and the fact that it was ever run. What is
   left is the step as it stood before anybody pressed anything, which is what
   an operator wants when the answer is wrong in a way no rerun will mend. */
el("fp-reset").addEventListener("click", () => {
  if (run.running) return;
  const f = run.focus;
  f.points = [];
  f.surface = null;
  f.residual = 0;
  f.worst = -1;
  f.selected = 0;
  f.applied = false;
  picked().clear();
  /* The step is not done any more either — it has nothing to have finished. */
  run.done.delete(step(run.activeIdx).id);
  stage.draw(); renderPointList(); drawTrace(); renderFocusBar(); renderActionBar(); renderSide();
});

/* Measure every placed point with the current metric, then fit the plane.
   The backend drives to each point and focuses there; what comes back is
   the height, the traces the chart draws, and the speck the preview shows.
   A height the operator dragged by hand survives a change of metric. */
/**
 * Measure every placed point, and say where each search should begin.
 *
 * `from` is the difference between the three presses:
 *
 *   - nothing, for the first run: the objective arrives near the tissue by
 *     luck, which is all a run with nothing behind it can claim.
 *   - `"stage"`, for running it again: every search starts from the height the
 *     objective is standing at now. That is what an operator has after focusing
 *     by eye somewhere on the plate — one good height, and a map to rebuild
 *     around it.
 *   - `"map"`, for refining: every search starts from what the map already
 *     predicts at that point, so each begins a micrometre or two from the
 *     tissue instead of somewhere near the middle of the plate.
 *
 * A search that sweeps its whole range without reaching the tissue comes back
 * with no height, which is why refining from a map that is already close finds
 * points a rerun from one height cannot.
 */
async function remeasure({ from = null } = {}) {
  const f = run.focus;
  const stageZ = () => stage.whereTheStageIs().z;
  const beginsAt = (p) => {
    if (from === "stage") return stageZ();
    if (from === "map") return f.surface ? surfaceZ(f.surface, p.x, p.y) : stageZ();
    return undefined;
  };
  const asked = f.points.map((p) => {
    const startZ = beginsAt(p);
    return Number.isFinite(startZ) ? { ...p, startZ } : p;
  });
  const { points } = await backend.measureFocus(asked, {
    metric: f.metric,
    extent: carrierSpan(),
  });
  f.points = points;
  refitSurface();
}

function refitSurface() {
  const f = run.focus;
  /* Only the points that came back with a height. A search that swept its
     whole range without ever reaching the tissue has nothing to say about
     where the surface is, and letting it say the height it stopped at would
     tilt the whole map towards a place nobody measured. */
  const found = f.points.filter((p) => Number.isFinite(p.z));
  f.surface = found.length ? fitSurface(found) : null;
  if (!f.surface) {
    f.points.forEach((p) => { p.residual = null; });
    f.residual = 0;
    f.worst = -1;
    return;
  }
  const errs = residualsUm(f.surface, found);
  found.forEach((p, i) => { p.residual = errs[i]; });
  f.points.forEach((p) => { if (!Number.isFinite(p.z)) p.residual = null; });
  f.residual = Math.sqrt(errs.reduce((a, e) => a + e * e, 0) / Math.max(1, errs.length));
  /* The worst is an index into the points as the list draws them, not into the
     ones that were found — the list is what an operator presses. */
  let worst = -1;
  f.points.forEach((p, i) => {
    if (!Number.isFinite(p.residual)) return;
    if (worst < 0 || Math.abs(p.residual) > Math.abs(f.points[worst].residual)) worst = i;
  });
  f.worst = worst;
}

  /* What the picture and the page may ask of the focus map. The gestures are
     here because the points are here: a press on the canvas over a point is
     about this step, whoever owns the canvas. */
  return {
    // the layer it draws on the stage
    drawFocusLayer,
    // the gestures it owns, and whether one is under way
    focusPressed, focusCursor, focusDraggedTo, focusGrabbed, focusHovered,
    focusMarqueeTo, focusMarqueeTook,
    marqueeing: () => focusMarquee,
    dragging: () => focusDrag,
    endDrag: () => { const held = focusDrag; focusDrag = null; return held ?? {}; },
    /* Two presses that belong to other steps and live here because the
       geometry they need does: placing a carrier anchor, and picking the
       position detection is tried on. They move when that geometry does. */
    anchorPressed, detectPressed,
    // what the sample's surface is said to be, and where a position is
    trueZ, nearestPosition,
    // the channel
    renderFocusBar, renderPointList, drawTrace, refitSurface, remeasure,
    mounted: focusMounted,
  };
}
