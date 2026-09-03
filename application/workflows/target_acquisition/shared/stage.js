/**
 * The stage picture: one projection, and layers drawn on it.
 *
 * Everything the operator looks at while a run is being set up is on this
 * canvas — the travel the microscope can reach, the carrier inside it, the
 * fields planned on the carrier, the focus map measured across them, the
 * cells found in them, and the mark where the stage is standing. They are
 * layers of one picture rather than pictures of their own, because they are
 * all statements about the same square millimetre of glass: pan or zoom and
 * every one of them moves together, which is what makes them comparable.
 *
 * The picture is handed the run and asked to draw. It knows what a carrier
 * and a tileset are — it is the target-acquisition run's own picture — but
 * it knows nothing about the window it hangs in: which step is standing,
 * what the channel beside it holds, how the page re-renders. Those arrive as
 * arguments, and what the page may do back to the picture is the handle it
 * returns.
 *
 * Its size is the instrument's: `get_info().canvas` gives the travel, and
 * `get_xyz` the position of the mark. Before a session there is a placeholder
 * travel, so the picture has a frame to draw.
 */

import { putTheCanvasIn } from "../../../parts/canvas/viewer.js";
/* What each step draws on the picture. A step owns its own layers — what they
   are, when the run has anything for them, and what a press on one means — and
   the workflow says only where each sits in the stack. */
import { carrierLayers } from "../steps/define_carrier/layers.js";
import { scanAreaLayers } from "../steps/define_scan_area/layers.js";
import { focusLayers } from "../steps/focus_strategy/layers.js";
import { overviewLayers } from "../steps/scan_the_overview/layers.js";
import { targetLayers } from "../steps/discover_targets/layers.js";
import { acquiredLayers } from "../steps/acquire_targets/layers.js";

/**
 * Open the picture on a canvas.
 *
 * `ctx` carries the page's plumbing (`css`, `sizeCanvas`, `el`), the run and
 * the sample being drawn, the panels that draw their own layers, the focus
 * gestures, the presses other steps own, and what to call when something the
 * rest of the page shows has changed.
 */
export function openTheStage(ctx) {
  const {
    css, sizeCanvas, el, run, carrierWidget, scanfieldsWidget,
    activePreset, indexOfStep, sideWidget, step,
    anchorPressed, detectPressed, targetPressed, targetAt,
    renderActionBar, renderRail, liveOverview, thePicture,
  } = ctx;
  const {
    focusPressed, focusCursor, focusDraggedTo, focusGrabbed, focusHovered,
    focusMarqueeTo, focusMarqueeTook, drawFocusLayer, drawFocusPoints,
    /* A gesture already under way belongs to the panel that started it; the
       picture only asks whether one is, and says when it ends. */
    marqueeing, dragging: focusDragging, endDrag: endFocusDrag,
  } = ctx.focus;

/* The picture is handed what it draws on. It reaches for no element of its
   own, because the panel it hangs in is built by the workflow that declared
   it — there is no markup on the page waiting for this file to find. */
const stageBox = ctx.box;
const stageTip = ctx.tip;

/* The canvas itself — the part, not this file. What this file supplies is the
   layers; the view, the buttons, the fade, the lock and the routing of a press
   are the canvas's, and are the same for any workflow that picks it up. */
const theCanvas = putTheCanvasIn({
  box: stageBox,
  layers: ctx.layerBar,
  readout: ctx.readout,
  /* Nothing to draw beneath the layers here, and no engine to choose between:
     the scan that appears under the plan during a run is drawn by the scan
     step, in a surface of its own below this one. */
  acquisitions: [],
  engine: "jpeg-under",
  /* Nothing of its own behind the layers, because the scan the run is writing
     is drawn beneath this canvas by the scan step. A ground of its own would
     cover that scan — and cover it precisely where the plan has been opened up
     to let it show, which is the only place anybody was looking. */
  background: "transparent",
  layersAbove: [],
  /* A press that claimed nothing and went nowhere is the run's own picking, so
     it is answered here. A drag is not: the layers answer for those
     themselves, each in its place in the stack. */
  onPressed: (where) => theRunWasPressed(where),
  /* A press a layer reaches is still the run's to answer: the overview's
     fields say what is under a press and act on nothing, and a press on
     an acquired frame over a field must still choose the target. */
  onTouched: (found) => theRunWasPressed(found),
  /* The travel's micrometres, not the carrier's. The canvas draws in the
     carrier's frame because that is where the run puts things, but what an
     operator reads off the bottom of the picture is where the stage would have
     to go — and the two differ by where the carrier sits in the travel. */
  /* The scan drawn beneath is registered to this picture, so it has to follow
     every move of it. The wheel and the drag belong to the canvas now, and a
     page that only followed its own redraws would let the two come apart the
     first time somebody zoomed. */
  onViewMoved: (where) => { keepItOnScreen(where); thePicture.followTheStage(); },
  readoutSays: ({ at, zoom }) => {
    const [ox, oy] = carrierOriginUm();
    return `x ${(at.x + ox).toFixed(0)} µm · y ${(at.y + oy).toFixed(0)} µm`
      + ` · ${(1000 / zoom).toFixed(1)} px/mm`;
  },
});
const theCanvasIsUp = theCanvas.whenShown();
/* Where the picture is, asked of the canvas rather than kept here. Two numbers
   say it — the middle of what is on screen, in the carrier's own micrometres,
   and how much sample one screen pixel covers — and the canvas is the one that
   moves them, because it owns panning and zooming.

   `scale` is the other way up from `zoom`, because everything drawn here is
   sized in screen pixels per micrometre. One is 1 / the other. */
const theView = () => theCanvas.view ?? { centre: { x: 0, y: 0 }, zoom: 1 / 0.03 };
const view = {
  get scale() { return 1 / theView().zoom; },
  fitted: false,
};

/* The canvas is the stage, so it is what the view frames — not the carrier
   inside it and not the scan inside that. Everything else is drawn in the
   same coordinates and lands where it belongs.

   Its size is the instrument's: `get_info().canvas` gives the travel and
   where the stage is, and connecting takes both. Before a session there
   is the placeholder, so the picture has a frame to draw. */
const TRAVEL_BEFORE_A_SESSION = [120_000, 80_000];
const STAGE_UM = [...TRAVEL_BEFORE_A_SESSION];
/* Where the travel begins. The size alone assumed every instrument's frame
   starts at zero -- true of the mock alone; the Leica's canvas straddles it,
   and discarding the offset laid the plan outside the travel. */
const STAGE_ORIGIN_UM = [0, 0];
let stageReported = null;

function takeTheCanvas(canvas) {
  if (!canvas?.x_um || !canvas?.y_um) {
    console.warn("the instrument reported no canvas; the picture keeps the placeholder travel");
    return;
  }
  STAGE_ORIGIN_UM[0] = canvas.x_um[0];
  STAGE_ORIGIN_UM[1] = canvas.y_um[0];
  STAGE_UM[0] = canvas.x_um[1] - canvas.x_um[0];
  STAGE_UM[1] = canvas.y_um[1] - canvas.y_um[0];
  view.fitted = false;
  drawStage();
}

/** The session is over, and its travel with it: the placeholder comes back,
    so a second instrument never inherits the first one's canvas. */
function forgetTheCanvas() {
  [STAGE_UM[0], STAGE_UM[1]] = TRAVEL_BEFORE_A_SESSION;
  [STAGE_ORIGIN_UM[0], STAGE_ORIGIN_UM[1]] = [0, 0];
  view.fitted = false;
  drawStage();
}

/** The stage mark: where the watch reads the stage, in micrometres. */
function takeThePosition(at) {
  if (!at || Number.isNaN(at.x) || Number.isNaN(at.y)) return;
  stageReported = at;
  drawStage();
}

/* Where the carrier's own zero sits on the stage.
 *
 * Centred in the travel, because that is where a holder puts a plate and it
 * is the only placement that can be worked out rather than measured. It is a
 * default and not a fact: the real offset comes from calibrating against a
 * plate actually on the stage, and this is the one line that answer replaces.
 *
 * Everything the run produces is placed from this point too, so the carrier
 * and what was imaged inside it move together instead of drifting apart the
 * moment either of them moves. */
function carrierOriginUm() {
  /* Measured, once anything has been aligned. Each anchor that has been driven
     to says the same thing — this place on the drawing is that place on the
     stage — and the offset it implies is the difference between the two. Four
     of them are four measurements of one number, so they are averaged: a
     single reading carries whatever slop that one drive had, and the whole
     plate would inherit it. */
  const measured = run.anchors.filter((a) => a.stage);
  if (measured.length) {
    const mean = (f) => measured.reduce((sum, a) => sum + f(a), 0) / measured.length;
    return [mean((a) => a.stage.x - a.x), mean((a) => a.stage.y - a.y)];
  }
  /* Otherwise centred in the travel, because that is where a holder puts a
     plate and it is the only placement that can be worked out rather than
     measured. A default, and the line above is the answer that replaces it. */
  const [w, h] = carrierWidget.extentUm(run.carrier);
  return [
    STAGE_ORIGIN_UM[0] + (STAGE_UM[0] - w) / 2,
    STAGE_ORIGIN_UM[1] + (STAGE_UM[1] - h) / 2,
  ];
}

/* How much clear space the travel is framed with, in screen pixels. */
const FIT_MARGIN = 26;

function fitView() {
  const box = stageBox.getBoundingClientRect();
  const w = box.width || 800, h = box.height || 600;
  /* The stage, always. Framing a small carrier instead was tried, so that an
     EM grid three millimetres across would not be four pixels of it — and it
     put the grid over the whole canvas with the stage mark somewhere off the
     edge, which is a picture of the carrier where what is wanted is a picture
     of the carrier on the stage. A carrier too fine to draw one area at a time
     is drawn as one block instead, which is `drawOn`'s answer and the right
     place for it. */
  const [fw, fh] = STAGE_UM;
  const s = 1 / furthestOut(w, h);
  const [ox, oy] = carrierOriginUm();
  /* Worked back from where the thing being framed should land, in the carrier's
     own micrometres, which is the frame the layers are drawn in.

     Across, it is centred; down, it sits at the top with the margin the sides
     have, rather than floating in the middle of whatever height the window
     happens to give the canvas. */
  theCanvas.lookAt({ zoom: 1 / s, centre: whereFitPutsIt(w, h, 1 / s) });
  view.fitted = true;
}

/**
 * Where Fit stands the picture, at a given zoom.
 *
 * Across, the stage is centred; down, it sits at the top with the same margin
 * the sides have, rather than floating in the middle of whatever height the
 * window happens to give the canvas. Written as a function of the zoom because
 * the limits below need the same answer: zoomed out as far as the picture goes,
 * this is not just where Fit put it, it is the only place it can be.
 */
function whereFitPutsIt(w, h, zoom) {
  const [fw] = STAGE_UM;
  const [ox, oy] = carrierOriginUm();
  return {
    x: STAGE_ORIGIN_UM[0] + fw / 2 - ox,
    y: STAGE_ORIGIN_UM[1] + (h / 2 - FIT_MARGIN) * zoom - oy,
  };
}

/**
 * How far out the picture may be zoomed, and how far it may be pushed about at
 * that zoom: the stage, framed, is the whole of what there is to look at.
 *
 * Zooming out past Fit only makes the one thing on screen smaller in the middle
 * of a growing field of nothing, and panning at that zoom carries it off the
 * edge with no way back but the Fit button. Both are stopped here rather than
 * in the canvas: the canvas draws whatever it is pointed at and has no opinion
 * about how big the stage is, and this is the file that knows.
 *
 * What may be on screen is the stage and the margin Fit frames it with, and no
 * more. Pan while zoomed in and the picture stops with that margin showing —
 * the same air Fit leaves, so the edge of travel always looks the same however
 * you arrived at it. Zoomed all the way out there is no room to move at all,
 * and the picture stays exactly where Fit stands it: an axis with nothing left
 * to show cannot be dragged, only wobbled, and a picture that wobbles under the
 * hand is one nobody can put back without pressing Fit.
 */
function insideTheLimits(where) {
  const box = stageBox.getBoundingClientRect();
  const w = box.width || 800, h = box.height || 600;
  const [fw, fh] = STAGE_UM;
  const [ox, oy] = carrierOriginUm();
  const zoom = Math.min(where.zoom, furthestOut(w, h));
  const air = FIT_MARGIN * zoom;
  const parked = whereFitPutsIt(w, h, zoom);
  const held = (centre, px, lo, hi, home) => {
    const half = (px / 2) * zoom;
    const min = lo - air, max = hi + air;
    return max - min >= 2 * half
      ? Math.min(Math.max(centre, min + half), max - half)
      : home;
  };
  return {
    zoom,
    centre: {
      x: held(where.centre.x, w, STAGE_ORIGIN_UM[0] - ox, STAGE_ORIGIN_UM[0] + fw - ox, parked.x),
      y: held(where.centre.y, h, STAGE_ORIGIN_UM[1] - oy, STAGE_ORIGIN_UM[1] + fh - oy, parked.y),
    },
  };
}

/** The zoom Fit lands on: the stage framed, margin and all. */
function furthestOut(w, h) {
  const [fw, fh] = STAGE_UM;
  return 1 / Math.min((w - 2 * FIT_MARGIN) / fw, (h - 2 * FIT_MARGIN) / fh);
}

/**
 * The canvas has been given a different width — the operator dragged the
 * divider between the picture and the channel.
 *
 * The change is taken out of the right-hand side: whatever was against the
 * left edge of the picture stays there, and the picture is cut, or uncovered,
 * on the right. Sharing the change between both edges walked the carrier out
 * of the window on the left, behind the rail of steps, where there is nothing
 * to drag it back with — the divider only ever gives that width back to the
 * right. In micrometres at the zoom in force, so a narrowing costs the same
 * amount of picture whatever the picture is being viewed at.
 *
 * Then the limits, which is what pulls the picture back into the frame when
 * the new width leaves the stage floating in more space than it can fill.
 */
function theCanvasNarrowed() {
  const where = theCanvas.view;
  const box = stageBox.getBoundingClientRect();
  const w = box.width || 800;
  if (!where?.centre || !lastWidth || Math.abs(w - lastWidth) < 0.5) {
    lastWidth = w;
    return;
  }
  const shift = ((w - lastWidth) / 2) * where.zoom;
  lastWidth = w;
  /* Put where it should be rather than asked whether it has strayed: the shift
     is a move nobody has made yet, so there is nothing for the check in
     `keepItOnScreen` to find. */
  straightening = true;
  theCanvas.lookAt(insideTheLimits({
    ...where, centre: { x: where.centre.x + shift, y: where.centre.y },
  }));
  straightening = false;
}
let lastWidth = 0;

/* Every way the view can move ends here, whichever gesture moved it. Held off
   by a frame so the correction is one more view change and not a call made
   from inside the canvas telling it where to be while it is telling us where
   it went. */
let straightening = false;
function keepItOnScreen(where) {
  if (straightening || !where?.centre) return;
  const should = insideTheLimits(where);
  const off = Math.abs(should.zoom - where.zoom) > 1e-9
    || Math.abs(should.centre.x - where.centre.x) > 1e-6
    || Math.abs(should.centre.y - where.centre.y) > 1e-6;
  if (!off) return;
  straightening = true;
  theCanvas.lookAt(should);
  straightening = false;
}

/* Where the microscope is, in stage micrometres.
 *
 * Worked out rather than stored. It is wherever the run last drove to — the
 * position of the tile the scan has just taken — and the middle of the
 * travel before it has driven anywhere, which is where a stage sits when
 * nothing has asked it to be anywhere else. A stored copy would be a second
 * answer to keep right, and would be wrong the first time a step forgot to
 * write to it.
 */
function whereTheStageIs() {
  /* What the instrument reported is where the stage is, and nothing may
     stand in for it: an invented height handed to the focus map as the
     centre of a stack once drove a real stage millimetres from focus.
     Before the first report there is no position, and the mark and its tip
     simply are not drawn. */
  if (stageReported) {
    return { x: stageReported.x, y: stageReported.y, z: stageReported.z };
  }
  return null;
}

/* Where the microscope is standing, over everything else on the picture.
 *
 * A crosshair rather than a dot, and a crosshair with a hole in the middle:
 * the arms reach out of whatever is under them, and the gap leaves the exact
 * position visible instead of covering the one pixel the mark is about. Its
 * size is in screen pixels and not in micrometres, because it is not a thing
 * on the stage that can be zoomed into — it is a statement about the stage,
 * and it has to stay the same size to keep being read as one.
 *
 * The numbers are beside it because the mark alone answers "where on this
 * picture", and the question is where on the stage. */
/* The mark: a crosshair with a hole in the middle. The gap is the point of
   it — the arms reach out of whatever is behind them and the centre stays
   clear, so the mark shows a position rather than covering it. */
function crosshair(ctx, x, y, arm, gap, dot, ring = 0) {
  ctx.beginPath();
  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    ctx.moveTo(x + dx * gap, y + dy * gap);
    ctx.lineTo(x + dx * arm, y + dy * arm);
  }
  ctx.stroke();
  /* A ring round the open centre, the arms crossing it: the reticle's own
     shape, read as a position at a glance where four bare lines were not. */
  if (ring) {
    ctx.beginPath();
    ctx.arc(x, y, ring, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.arc(x, y, dot, 0, Math.PI * 2);
  ctx.fill();
}

/* Whether the pointer is on the mark. Kept here rather than worked out while
   drawing, because it is the pointer that decides it and the drawing happens
   for many other reasons than the pointer having moved. */
let stageMarkHot = false;

/* How close the pointer has to be to count as on it, in screen pixels. A
   little wider than the mark itself: it is a cross made of thin lines, and
   asking for the exact pixel of one of them is asking for a fight. */
const STAGE_MARK_REACH = 15;

/** Where the mark is on screen, for the pointer to be measured against. */
const stageMarkAt = () => {
  const at = whereTheStageIs();
  return at ? toScreen(at.x, at.y) : null;
};

/* Where the microscope is standing, drawn on the stage.
 *
 * Through the same projection as everything else on the canvas, so it is
 * registered to the stage rather than to the screen: pan the picture and it
 * travels with the carrier, zoom in and it stays over the same micrometre.
 * That is the whole point of it — a mark that sat still while the picture
 * moved would be decoration.
 *
 * Its size is the one thing not in stage units. It is in screen pixels,
 * because the mark is not a thing on the stage that can be zoomed into — it
 * is a statement about the stage, and it has to stay the same size to keep
 * being read as one.
 *
 * It says where and not what. The three numbers behind it are worth having
 * and are not worth having on screen at all times: a permanent readout in
 * the corner is three figures to read past on every step, when the question
 * they answer is only ever asked about this one mark. So they arrive on
 * hover, and the mark thickens to say it is the thing being asked about. */
function drawWhereTheStageIs(ctx, onTheStage) {
  const at = whereTheStageIs();
  if (!at) return;
  const [x, y] = onTheStage(at.x, at.y);
  /* Black on a white halo, and larger than it was: the mark has to be
     found at a glance on tissue and on dark ground alike, and a thin blue
     cross was lost on both. */
  ctx.save();
  const arm = stageMarkHot ? 22 : 18;
  ctx.strokeStyle = "#ffffff";
  ctx.fillStyle = "#ffffff";
  ctx.lineWidth = stageMarkHot ? 7 : 6;
  crosshair(ctx, x, y, arm, 5, stageMarkHot ? 4.5 : 4, 10);
  ctx.strokeStyle = "#000000";
  ctx.fillStyle = "#000000";
  ctx.lineWidth = stageMarkHot ? 3 : 2.5;
  crosshair(ctx, x, y, arm, 5, stageMarkHot ? 2.8 : 2.2, 10);
  ctx.restore();
}

/**
 * Point the tip at the mark, or say that it is not on it.
 *
 * The tip is the page's own hover panel — the one the cells use — so where a
 * hover answer appears is one decision made once, rather than this mark
 * inventing a second place for the same kind of answer to show up in.
 *
 * Millimetres across and micrometres down, because that is what the rest of
 * the page says: a stage is driven in millimetres and focused in micrometres.
 */
function tipTheStageMark(e) {
  const mark = stageMarkAt();
  if (!mark) return false;
  const [mx, my] = mark;
  const hot = Math.hypot(e.offsetX - mx, e.offsetY - my) <= STAGE_MARK_REACH;
  if (hot !== stageMarkHot) { stageMarkHot = hot; drawStage(); }
  if (!hot) return false;
  const at = whereTheStageIs();
  stageTip.classList.add("on");
  stageTip.innerHTML =
    `<b>stage</b><br><b>x</b> ${(at.x / 1000).toFixed(2)} mm`
    + `<br><b>y</b> ${(at.y / 1000).toFixed(2)} mm`
    + `<br><b>z</b> ${at.z.toFixed(0)} µm`;
  stageTip.style.left =
    `${Math.min(e.offsetX + 14, stageBox.getBoundingClientRect().width - 130)}px`;
  stageTip.style.top = `${Math.max(6, e.offsetY - 66)}px`;
  return true;
}

/* Where the stage ends. Drawn first and faintly: it is the edge of what any
   of this can reach, which is context for everything else rather than a
   thing in its own right. */
function drawStageLimits(ctx, onTheStage, scale) {
  const [x, y] = onTheStage(STAGE_ORIGIN_UM[0], STAGE_ORIGIN_UM[1]);
  ctx.save();
  ctx.strokeStyle = css("--line-strong");
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 0.5, y + 0.5, STAGE_UM[0] * scale, STAGE_UM[1] * scale);
  ctx.restore();
}

/* The travel's micrometres, on screen. The canvas projects the carrier's, so
   this is that projection with the carrier's origin taken off — the same two
   frames `drawnIn` names apart, at the one place they have to meet. */
function toScreen(x, y) {
  const [ox, oy] = carrierOriginUm();
  const at = theCanvas.project(x - ox, y - oy);
  return [at.x, at.y];
}

function toWorld(px, py) {
  const [ox, oy] = carrierOriginUm();
  const at = theCanvas.unproject(px, py);
  return [at.x + ox, at.y + oy];
}

/**
 * A place on the carrier as the stage knows it, and back.
 *
 * The workflow lays points and plans on the carrier; the instrument drives in
 * its own frame, and where the carrier sits in it is what alignment measured
 * -- unaligned, it is centred in the travel. Everything handed to the
 * instrument goes through `toStage`, and everything it reports about a place
 * comes back through `toCarrier`. Positions went out unconverted for as long
 * as the mock's picture happened to line up; on an aligned Leica every focus
 * point drove to the wrong place.
 */
function toStage(p) {
  const [ox, oy] = carrierOriginUm();
  return { ...p, x: p.x + ox, y: p.y + oy };
}

function toCarrier(p) {
  const [ox, oy] = carrierOriginUm();
  return { ...p, x: p.x - ox, y: p.y - oy };
}

/* Which layers are off, how solid they are drawn and whether the picture is
   locked are all the canvas's now, kept once where the buttons that change
   them are. This file asks when it needs to know. */
const layersLocked = () => theCanvas.locked;
/* The stack as it was last handed over, so a press can ask what is on the
   picture without building it again to find out. */
let theStack = [];

/**
 * What a layer is handed, in the terms this run draws in.
 *
 * A layer is given a frame by whoever is compositing the stack, and everything
 * it needs is in there: where a place on the sample lands on screen, how
 * magnified the picture is, how big the box is. Taking them from the frame
 * rather than from this file is what lets these layers be drawn by a canvas
 * that is not this one.
 *
 * **Two frames, named apart.** `place` is the carrier's own micrometres — where
 * the plan, the tilesets, the cells and the focus points all live. `onTheStage`
 * is the travel's, which only the stage limits and the stage mark use. They
 * differ by where the carrier sits in the travel, and confusing them draws
 * everything up and to the left of where it belongs. That has happened.
 */
function drawnIn(frame) {
  const [ox, oy] = carrierOriginUm();
  const put = (x, y) => { const at = frame.project(x, y); return [at.x, at.y]; };
  return {
    place: put,
    onTheStage: (x, y) => put(x - ox, y - oy),
    scale: 1 / frame.zoom,
    w: frame.width,
    h: frame.height,
  };
}

/* The order the stack is drawn in, bottom first.
 *
 * The workflow's to state, and stated in one place, because the order is not
 * something any step could know: it interleaves them. The carrier is under the
 * fields it holds, which are under the focus map measured across them, which is
 * under the plan drawn over all of it — steps 2, 5, 4 and 3, in none of their
 * own order. What each layer *is* belongs to its step; where it sits belongs
 * here.
 *
 * A layer that stays solid is drawn after the rest whatever this says, so
 * anything that must sit low in the picture has to accept the fade. See
 * `parts/canvas/layers-above.js`.
 */
const THE_STACK = [
  "ground", "limits", "carrier", "tiles", "segmentation", "cells", "frames", "targets",
  "focus", "plan", "focusFrame", "focusPoints", "detect", "editing", "anchors", "stage", "scale",
];

/**
 * The picture's own furniture, belonging to no step.
 *
 * The page's surface under everything, the travel the stage can reach, where
 * the stage is standing, and how far a stretch of screen is on the sample.
 * They are true of the run from the moment there is a microscope to ask, and
 * they are what every step's own layers are drawn against.
 */
function thePicturesOwnLayers(theRun) {
  const { run, css, drawnIn, drawStageLimits, drawWhereTheStageIs, drawScaleBar } = theRun;
  return {
    ground: {
      key: "ground",
      label: "Background",
      explains: "The page's own surface, under everything else the canvas draws. Turn it "
        + "off and the picture underneath shows through everywhere; leave it on and the "
        + "picture shows only where a window has been opened.",
      /* **This is the layer that decides whether a picture underneath can be
         seen at all**, and it is worth being plain about why it is a layer
         rather than a fill.
      
         The scan itself is drawn on a surface of its own, beneath this one.
         Anything painted here covers it. So if this were painted outside the
         stack — which is how it was written first — a window cut through the
         layers would have nothing to reveal: the drawing above would go, and
         the page's own grey would still be sitting on top of the picture.
      
         As the bottom layer of the stack it is cut by the same window as
         everything above it, by the same rule and in the same pass. Open a
         window over the fields that have landed and the scan appears there,
         through every layer including this one. Turn this off altogether and
         the scan is simply visible everywhere.
      
         It is a flat fill and therefore the one layer that is not sparse, but
         that is exactly its job: it is the ground, and ground is not sparse. */
      shown: true,
      paint: ({ context: ctx, width, height }) => {
        ctx.fillStyle = css("--screen");
        ctx.fillRect(0, 0, width, height);
      },
    },
    limits: {
      key: "limits",
      label: "Stage",
      explains: "The edge of where the stage can travel. Context for everything else "
        + "rather than a thing the run produced, which is why it is drawn faintly.",
      /* With the session, not before: the limits are a readout from the
         connected microscope's configuration, so an unconnected page shows
         nothing it cannot yet know. */
      shown: run.done.has("connect"),
      paint: (frame) => {
        const { onTheStage, scale } = drawnIn(frame);
        drawStageLimits(frame.context, onTheStage, scale);
      },
    },
    stage: {
      key: "stage",
      label: "Where the stage is",
      explains: "A crosshair on the position the stage is standing at. Always solid: it "
        + "is where the microscope actually is, and that should never be the thing that "
        + "went faint.",
      /* With the session: where the stage is standing is a readout from the
         microscope, and there is no microscope until the operator has
         connected. */
      shown: run.done.has("connect"),
      staysSolid: true,
      paint: (frame) => drawWhereTheStageIs(frame.context, drawnIn(frame).onTheStage),
    },
    scale: {
      key: "scale",
      label: "Scale bar",
      explains: "How far a stretch of screen is on the sample. A reading rather than a "
        + "drawing, so it stays solid — a scale bar you can half see through is a scale "
        + "bar you cannot trust.",
      /* A reading about a stage nobody has connected to yet would be a
         reading about nothing. */
      shown: run.done.has("connect"),
      staysSolid: true,
      paint: (frame) => {
        const { scale, w, h } = drawnIn(frame);
        drawScaleBar(frame.context, w, h, scale);
      },
    }
  };
}

/**
 * The whole stack, assembled.
 *
 * Each step says what it draws; this puts the answers in the order the workflow
 * declared. A step that has nothing to draw yet still supplies its layers — a
 * layer says for itself whether the run has anything for it, which is a
 * different question from whether the operator wants to see it.
 */
function theStageLayers({ shown, editing }) {
  const theRun = {
    run, css, drawnIn, carrierWidget, scanfieldsWidget,
    /* Where the stage stands, for a layer that frames the field it would
       take before a scan has taken any. */
    whereTheStageIs,
    activePreset, indexOfStep, step,
    activeMode: step(run.activeIdx).mode,
    editing, shown,
    crosshair,
    drawFocusLayer, drawFocusPoints, drawStageLimits, drawWhereTheStageIs, drawScaleBar,
    /* What a layer needs to answer for a gesture of its own. Handed over rather
       than reached for, so a layer says what a press on it means without
       knowing anything about the page it is drawn on. */
    asAPress, renderRail, renderActionBar, editorTook,
    redraw: drawStage, anchorsChanged: ctx.anchorsChanged,
    pictureShows: ctx.pictureShows,
    focusGrabbed, marqueeing, focusMarqueeTo, focusMarqueeTook,
    focusDragging, focusDraggedTo, endFocusDrag, focusPressed,
    toStage, toCarrier,
  };

  const supplied = {
    ...thePicturesOwnLayers(theRun),
    ...carrierLayers(theRun),
    ...scanAreaLayers(theRun),
    ...focusLayers(theRun),
    ...overviewLayers(theRun),
    ...targetLayers(theRun),
    ...acquiredLayers(theRun),
  };

  return THE_STACK.map((key) => supplied[key]).filter(Boolean);
}

function drawStage() {
  if (!view.fitted) fitView();

  const editing = sideWidget()?.id === "scanfields" ? run.editor : null;
  const stack = theStageLayers({
    shown: Math.max(run.tilesShown, 0),
    /* Which channels are mixed is a question about a picture, and the
       drawing that answers it reads the run's own description -- the two
       booleans that used to ride through here reached nothing at all. */
    editing,
  });

  /* Each layer says what the *run* has for it, and the canvas remembers what
     the operator did about that. They are two questions and must not be run
     together: a layer the operator hid would lose the button that brings it
     back, and a layer the run has nothing for would offer a button that does
     nothing. What each layer works out for itself as `shown` is the first of
     the two, so that is the answer handed over. */
  for (const layer of stack) {
    layer.has = layer.shown !== false;
  }
  theStack = stack;
  theCanvas.setLayersAbove(stack);

  /* Set here rather than on the pointer alone, so a tool armed from the panel
     or a key says so before the mouse is moved to find out. */
  stageBox.style.cursor = editing ? editing.cursor() : focusCursor();

  /* The scan beneath follows the view the plan was just drawn with, so the
     two are never a frame apart. Cheap: it is two divisions and a setView,
     and the engine only redraws if something actually moved. */
  thePicture.followTheStage();
}

/* The row of buttons, the fade and the lock are the canvas's own, built
   from the layers it is handed. This file used to build a second set of
   them into a bar that no markup ever created, so they had never once
   appeared on screen. */

/**
 * Open the ground the scan has already covered, so the picture shows through.
 *
 * Called as fields land. The plan, the tiles and everything else drawn over a
 * field that has been taken is opened up there, which is how an operator
 * watches the scan appear through their own drawing rather than beside it.
 *
 * In micrometres in the carrier's own frame, which is where the fields are,
 * so the window travels with the sample when the view is panned and grows
 * when it is magnified.
 */
function openTheGroundThatHasBeenScanned(howMuch = 1) {
  const shown = Math.max(run.tilesShown, 0);
  const fields = run.plan.slice(0, shown).map((t) => ({
    x: t.x - t.frameUm / 2,
    y: t.y - t.frameUm / 2,
    w: t.frameUm,
    h: t.frameUm,
    letThrough: howMuch,
  }));
  /* The acquired target frames too. A target is imaged where its cell is,
     which can be at the edge of an overview field, so part of its frame lies
     outside every field window; without a window of its own that part of
     the picture stayed hidden under the ground until the operator faded
     the layers by hand. The frame is as wide as the recording says. */
  const half = (run.targetFrameUm ?? 0) / 2;
  const targets = half > 0
    ? (run.acquired ?? []).map((id) => run.cells?.get(id)).filter(Boolean).map((cell) => ({
      x: cell.x - half, y: cell.y - half, w: half * 2, h: half * 2, letThrough: howMuch,
    }))
    : [];
  theCanvas.seeThrough([...fields, ...targets]);
}

/**
 * The discovered targets in the canvas's carrier-local frame.
 *
 * This is a read-only evidence surface, like `plan()` and `project()` below:
 * browser checks can prove that the same physical targets stay at the same
 * canvas positions while the workflow changes their candidate, selected, and
 * acquired presentation. It does not become another coordinate authority;
 * every screen point is read from the canvas's existing projection.
 */
function targetSnapshot() {
  const acquired = new Set(run.acquired);
  return [...run.cells.values()].map((cell) => {
    const at = theCanvas.project(cell.x, cell.y);
    return {
      id: cell.id,
      field: cell.field,
      x: cell.x,
      y: cell.y,
      screen: { x: at.x, y: at.y },
      selected: run.gated.has(cell.id),
      restricted: run.restricted.has(cell.id),
      acquired: acquired.has(cell.id),
    };
  });
}

/**
 * What the canvas will answer to, from outside it.
 *
 * The scan is drawn beneath this canvas, and the run opens the ground over
 * every field it has imaged (`groundFollowsTheScan` on the handle), so the
 * picture appears through the drawing exactly where it was taken. These stay
 * exposed for the browser tests, which drive the same rules by hand.
 */
window.__theStageCanvas = {
  /** Open the ground the scan has covered, so a picture beneath shows there. */
  openScannedGround: openTheGroundThatHasBeenScanned,
  /** Close every window again. */
  closeTheGround() { theCanvas.seeThrough([]); },
  /** Open one named piece of the sample, in micrometres in the carrier's frame. */
  openThisGround(windows) { theCanvas.seeThrough(windows ?? []); },
  /** Where the ground is open right now, in the carrier's micrometres. */
  groundWindows: () => theCanvas.windows(),
  /** Which layers there are, and which are being drawn. */
  layers: () => theCanvas.layersAbove.map(({ key, label, shown, staysSolid }) =>
    ({ key, label, shown, staysSolid: !!staysSolid })),
  /**
   * Draw one of the layers, or stop drawing it.
   *
   * The same thing the controls in the canvas foot did before that strip was
   * taken off the screen. Here rather than only on a button because turning a
   * layer on and off is a thing the canvas can do, and it should not stop
   * being possible because nobody has yet decided where the button for it
   * belongs.
   */
  showLayer(key, on) {
    theCanvas.showLayer(key, on);
    drawStage();
  },
  /** Whether the named layer is being drawn, the picture included. */
  layerShown(key) {
    return theCanvas.layerShown?.(key) ?? true;
  },
  /** How solid the layers are drawn, 0 to 1. */
  fadeTo(howSolid) {
    theCanvas.fadeTo(Math.min(1, Math.max(0, Number(howSolid))));
  },
  /**
   * Where the run means to send the stage, in micrometres in the carrier's
   * own frame.
   *
   * This is the pairing the whole arrangement rests on, and it is worth
   * saying plainly where it shows up: **the files a microscope writes do not
   * say where they were taken.** The run knows, because it is the run that
   * sent the stage there. So making the small pictures for a scan means
   * handing these positions in alongside the files, and this is where a
   * rehearsal gets them from — exactly as the real thing will.
   */
  plan: () => run.plan.map(({ x, y, frameUm, tileset, fieldId }) => ({ x, y, frameUm, tileset: tileset ?? fieldId ?? null })),
  /** Candidate, selected, and acquired target positions on this same canvas. */
  targets: targetSnapshot,
  /**
   * Where a place on the sample lands on screen, as the plan itself works it
   * out.
   *
   * Here so that a test can ask the plan and the scan the same question and
   * compare their answers. That comparison is the one that matters: the two
   * are drawn by different code on different surfaces, and the only thing
   * making them one picture is that they agree about where things are. A
   * difference of a few pixels would look like a slightly blurry scan and be
   * a run pointed at the wrong place.
   */
  project: (x, y) => {
    const [ox, oy] = carrierOriginUm();
    return toScreen(x + ox, y + oy);
  },
};

/* Carrier coordinates for the editor: it places fields inside the carrier,
   so it is handed where the pointer is in that frame rather than where it is
   on the stage. A different question from `toCarrier(point)`, which turns a
   stage point into a carrier point — this turns a screen pixel into one, and
   sharing the name let it shadow the other and corrupt every converted point. */
function pointerInCarrier(px, py) {
  const [wx, wy] = toWorld(px, py);
  const [ox, oy] = carrierOriginUm();
  return { x: wx - ox, y: wy - oy };
}

/* The editor sees the pointer first and says whether it took it. Only what
   it turns down pans or picks, so drawing a region does not drag the stage
   out from under the shape being drawn. */
function editorTook(kind, e) {
  /* Locked, nothing can be drawn or moved by accident. Panning and zooming
     are untouched — the lock is about picking, not about looking. */
  if (layersLocked()) return false;
  if (sideWidget()?.id !== "scanfields" || !run.editor) return false;
  const { x, y } = pointerInCarrier(e.offsetX, e.offsetY);
  const took = run.editor.pointer(kind, { x, y, shift: e.shiftKey, scale: view.scale });
  // the redraw is also what puts the cursor right, and it has to happen after
  // the editor has been told, or the answer is for where the pointer was
  if (took) drawStage();
  /* Only a true means the editor claimed the event. Anything else it answers
     is "the picture changed" — the pointer moved over a field — and the
     canvas still gets to say where the stage is under the cursor. */
  return took === true;
}

/* How big the picture is, said along the bottom of the canvas.
 *
 * Flat: a line and a number, no upstanding ends. The ticks were there to say
 * where the bar stops, which the bar already says, and two little uprights
 * in a picture full of drawn edges read as one more thing the run had put
 * there.
 *
 * It sits in a strip of its own, kept clear of the drawing: the plan is cut
 * off above it rather than running under it, because a rule with a plate
 * showing through it can be read as either. The strip is the page's own
 * surface, the same as the empty stage. */
const SCALE_STRIP = 24;

function drawScaleBar(ctx, w, h, scale) {
  const targetPx = 130;
  const raw = targetPx / scale;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const nice = [1, 2, 5, 10].map((m) => m * pow).reduce((a, b) =>
    Math.abs(b - raw) < Math.abs(a - raw) ? b : a);
  const px = nice * scale;
  const x = w - px - 20, y = h - 9;

  ctx.fillStyle = css("--screen");
  ctx.fillRect(0, h - SCALE_STRIP, w, SCALE_STRIP);

  ctx.strokeStyle = css("--ink-2");
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, y); ctx.lineTo(x + px, y);
  ctx.stroke();
  ctx.fillStyle = css("--ink-2");
  ctx.font = '11.5px ui-monospace, Consolas, monospace';
  ctx.textAlign = "center";
  ctx.fillText(nice >= 1000 ? `${nice / 1000} mm` : `${nice} µm`, x + px / 2, y - 4);
  ctx.textAlign = "left";
}

/* ---- stage interaction ------------------------------------------------
   One button does everything, and what it does is decided by what is under
   it. The editor is asked first: a field is picked up, a tool draws. Only
   what it turns down moves the stage, so a press on empty canvas pans and a
   press on a shape does not drag the picture out from under it.

   A double-click ends an outline that has no last point of its own — the
   same press that places the final vertex, said twice.

   Alt+drag pans regardless. Without it there is no way to move the stage
   while a drawing tool is armed, since then the editor wants every press on
   empty canvas for the shape it is about to make. */
/* Whose gesture is this?
 *
 * Not this file's business any more. The canvas asks the layers, top of the
 * stack down, and each says whether the press is its own — the editing chrome
 * while a field is being drawn or moved, the focus map while a point is being
 * taken hold of or a set marqueed. Whatever none of them wanted pans the
 * picture.
 *
 * That order used to be written out here, as three lines in a fixed sequence.
 * It now falls out of where the layers sit, which is the same answer and one
 * that a new step cannot get wrong: put a layer in the stack and it is asked in
 * its place, without this file learning it exists.
 */

/* The canvas speaks in micrometres on the sample and in pixels inside its box;
   the presses a layer answers with were written against a DOM event. This is
   the one place the two meet, and it is handed to the layers rather than each
   of them working it out. */
const asAPress = (drag) => ({
  offsetX: drag.screen.x,
  offsetY: drag.screen.y,
  shiftKey: !!drag.shift,
});

/* A press that nothing claimed and that went nowhere: the run's own picking —
   an anchor put down, a focus point placed, the position detection is tuned on.
   Answered when the operator lets go rather than when they press, or the start
   of every pan would put something down. */
function theRunWasPressed({ screen }) {
  if (layersLocked()) return;
  anchorPressed(screen.x, screen.y)
    || focusPressed(screen.x, screen.y)
    || detectPressed(screen.x, screen.y)
    || targetPressed?.(screen.x, screen.y);
}

/* Hovering claims nothing, so it is watched here rather than routed: what is
   under the pointer decides the cursor and whatever the tip has to say. */
stageBox.addEventListener("pointermove", (e) => {
  /* Nothing to say while a gesture is under way: whoever claimed it is being
     told about every move already, and a second opinion about what is under the
     pointer would only fight it. */
  if (theCanvas.gesturing || marqueeing() || focusDragging()) return;

  /* The editor first, and not only for the tip: this is how it learns the
     pointer is over one of its fields, which is what turns the cursor into an
     offer to pick the field up. Hovering is the whole of what it is being told
     here — the drag itself goes through the claims. */
  if (editorTook("move", e)) return;

  /* A focus point answers before anything under it: it is the small thing on
     top, and the press that finds it moves it rather than the picture. */
  if (focusHovered(e)) return;

  /* The mark next: it is drawn over everything else, so it answers for the
     pointer before anything underneath it does. */
  if (tipTheStageMark(e)) return;

  // hover the nearest visible cell
  const world = theCanvas.unproject(e.offsetX, e.offsetY);

  /* A tile under the pointer on the discover step is one press from being
     the test position: the hand and a lit frame both say so. */
  if (step(run.activeIdx).mode === "detect" && !run.running) {
    let overTile = -1;
    for (let i = 0; i < run.plan.length; i++) {
      const t = run.plan[i];
      const half = t.frameUm / 2;
      if (Math.abs(world.x - t.x) <= half
        && Math.abs(world.y - t.y) <= half) { overTile = i; break; }
    }
    if (run.detect.hovered !== overTile) {
      run.detect.hovered = overTile;
      drawStage();
    }
    stageBox.style.cursor = overTile >= 0 ? "pointer" : "";
  } else if (run.detect.hovered !== -1) {
    run.detect.hovered = -1;
    stageBox.style.cursor = "";
    drawStage();
  }

  /* On the acquisition step the frame under the pointer is what a press
     would choose: outlined, and the hand says so. */
  if (step(run.activeIdx).mode === "targets" && !run.running) {
    const over = targetAt?.(world, 8 / view.scale) ?? null;
    if (run.hoveredTarget !== over) {
      run.hoveredTarget = over;
      drawStage();
    }
    stageBox.style.cursor = over !== null ? "pointer" : "";
  } else if (run.hoveredTarget !== null) {
    run.hoveredTarget = null;
    drawStage();
  }

  let hit = null;
  if (run.cellsShown) {
    let best = 12 / view.scale;
    for (const c of run.cells.values()) {
      const d = Math.hypot(c.x - world.x, c.y - world.y);
      if (d < best) { best = d; hit = c; }
    }
  }
  if (hit) {
    stageTip.classList.add("on");
    stageTip.innerHTML =
      `<b>cell</b> ${hit.id}<br><b>area</b> ${hit.area.toFixed(0)} µm²<br><b>int</b> ${hit.intensity.toFixed(2)}`;
    const box = stageBox.getBoundingClientRect();
    stageTip.style.left = `${Math.min(e.offsetX + 14, box.width - 130)}px`;
    stageTip.style.top = `${Math.max(6, e.offsetY - 52)}px`;
  } else {
    stageTip.classList.remove("on");
  }
});

stageBox.addEventListener("pointerleave", (e) => {
  editorTook("leave", e);
  stageTip.classList.remove("on");
  if (run.detect.hovered !== -1) { run.detect.hovered = -1; drawStage(); }
  if (run.hoveredTarget !== null) { run.hoveredTarget = null; drawStage(); }
  stageBox.style.cursor = "";
  // the pointer is off the canvas, so it is off the mark whatever it was on
  if (stageMarkHot) { stageMarkHot = false; drawStage(); }
});

/* On the discover step a single press on the tile under the pointer makes
   it the test position -- the one step where a plain click has no other
   meaning. Ignored while a run is out, like the hover that leads to it. */
stageBox.addEventListener("click", (e) => {
  void e;
  if (step(run.activeIdx).mode !== "detect" || run.running) return;
  if (run.detect.hovered < 0) return;
  if (run.detect.tile !== run.detect.hovered) {
    run.detect.tile = run.detect.hovered;
    run.detect.tested = false;
    ctx.tileChosen?.();
  }
  drawStage();
});

/* An outline with no last point of its own is ended by saying the same press
   twice. Not a drag, so it does not go through the claims. */
stageBox.addEventListener("dblclick", (e) => {
  if (editorTook("finish", e)) return;
  driveTheStageTo(e);
});

/**
 * Double-click a place on the picture and the microscope goes there.
 *
 * The one gesture on this canvas that moves the instrument rather than the
 * view, which is why it is a double-click: a single press already means
 * something on nearly every step — placing a point, starting an outline,
 * picking a mark — and a stage that drove on any of them would be a stage
 * that drove by accident.
 *
 * **The mark follows the answer, never the request.** `set_xyz` is confirmed:
 * the driver moves, checks, and raises if it could not, and it hands back the
 * position it commanded. That is what the mark is put at. Drawing it where
 * the press was would show where the stage was *asked* to go — which is the
 * one thing a mark saying "the stage is here" must never do. Until the answer
 * comes back, nothing moves.
 *
 * Only inside the travel. A press out in the margin is somewhere the stage
 * cannot reach, and asking is either refused by the driver or quietly clamped
 * into somewhere nobody pointed at.
 */
async function driveTheStageTo(e) {
  if (run.running || layersLocked() || !ctx.driveTo) return;
  /* `toWorld` answers in the stage's own frame, so the travel's bounds are
     compared in it directly. Subtracting the carrier origin here treated the
     press as a carrier coordinate and shifted the accepted region by half
     the travel-minus-carrier -- the top of the travel drove and the bottom
     third refused, silently. */
  const [x, y] = toWorld(e.offsetX, e.offsetY);
  const [fw, fh] = STAGE_UM;
  if (x < STAGE_ORIGIN_UM[0] || y < STAGE_ORIGIN_UM[1]
    || x > STAGE_ORIGIN_UM[0] + fw || y > STAGE_ORIGIN_UM[1] + fh) return;
  const at = await ctx.driveTo({ x, y });
  if (at) takeThePosition(at);
}
// the canvas has no menu of its own, and a borrowed one over the plan is noise
stageBox.addEventListener("contextmenu", (e) => e.preventDefault());


/* Fit frames whichever picture is on show. While the acquired overview is
   covering the plan, it is the thing being looked at, so it is the thing that
   gets framed. */
ctx.fitButton.addEventListener("click", () => {
  if (liveOverview.showing) { liveOverview.fit(); return; }
  fitView(); drawStage();
});

  /* What the page around it may do to the picture. Everything else — how a
     layer is drawn, where the mark goes, what a press means — is in here. */
  return {
    draw: drawStage,
    /* Where the picture is, in the canvas's own terms — the middle of what is
       on screen in the carrier's micrometres, and how much sample a screen
       pixel covers. Handed out so the scan drawn beneath can be put in exactly
       the same place, rather than working it out a second time from numbers
       that would then have to agree. */
    pictureView: () => theCanvas.view,
    /* The ground opens over what the scan has imaged, so the picture beneath
       shows through the drawing exactly where it was taken. Called as tiles
       land, and again when a run is reset and there is nothing to show. */
    groundFollowsTheScan: openTheGroundThatHasBeenScanned,
    fit: fitView,
    /* The canvas is the picture's; the page says when its box has changed
       shape, and what the pointer should look like over it. */
    /* The canvas measures itself; this only asks for the layers again, since
       what they draw depends on how big the box is. */
    resize() { theCanvasNarrowed(); drawStage(); },
    cursor(shape) { stageBox.style.cursor = shape; },
    view,
    travelUm: STAGE_UM,
    travelOriginUm: STAGE_ORIGIN_UM,
    toScreen,
    toWorld,
    /* Lent to a panel that draws its own small picture and wants the page's
       one way of saying how big a micrometre is. */
    drawScaleBar,
    carrierOriginUm,
    whereTheStageIs,
    /* What the plan laid, and where a place on the sample lands on screen —
       so a test can ask this picture and the scan beneath it the same
       question and compare the answers. That comparison is the one that
       matters: the two are drawn by different code on different surfaces,
       and the only thing making them one picture is that they agree. */
    plan: () => run.plan.map(({ x, y, frameUm, tileset, fieldId }) => ({ x, y, frameUm, tileset: tileset ?? fieldId ?? null })),
    targets: targetSnapshot,
    toStage, toCarrier,
    project: (x, y) => {
      const [ox, oy] = carrierOriginUm();
      return toScreen(x + ox, y + oy);
    },
    /* The place on the sample under a screen point, in the frame the cells
       and the plan are kept in -- the same answer the hover reads. */
    unproject: (px, py) => theCanvas.unproject(px, py),
    /** How much sample one screen pixel covers right now. */
    umPerPixel: () => 1 / view.scale,
    takeTheCanvas,
    forgetTheCanvas,
    takeThePosition,
    openScannedGround: openTheGroundThatHasBeenScanned,
    closeTheGround() { theCanvas.seeThrough([]); },
    openThisGround(windows) { theCanvas.seeThrough(windows ?? []); },
    groundWindows: () => theCanvas.windows(),
    layers: () => theCanvas.layersAbove.map(({ key, label, shown, staysSolid }) =>
      ({ key, label, shown, staysSolid: !!staysSolid })),
    showLayer(key, on) { theCanvas.showLayer(key, on); drawStage(); },
    layerShown: (key) => theCanvas.layerShown?.(key) ?? true,
    fadeTo(value) { theCanvas.fadeTo(value); },
  };
}
