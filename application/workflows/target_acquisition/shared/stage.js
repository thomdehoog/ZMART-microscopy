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
import { MASK_RAINBOW } from "../steps/discover_targets/mask-dress.js";
import { maskLayersOn } from "./mask-layers.js";
import { mountChannelBox } from "../../../parts/canvas/channel-box.js";
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
  // The lightweight canvas owns navigation and the two application drawings.
  // The acquisition viewer occupies its middle slot.
  acquisitions: [],
  engine: "jpeg-under",
  // Background is an explicit layer in THE_STACK, not a second CSS fill.
  background: "transparent",
  layersAbove: [],
  pictureHost: ctx.pictureHost,
  /* A press that claimed nothing and went nowhere is the run's own picking, so
     it is answered here. A drag is not: the layers answer for those
     themselves, each in its place in the stack. */
  onPressed: (where) => theRunWasPressed(where),
  /* A press a layer reaches is still the run's to answer: the overview's
     fields say what is under a press and act on nothing, and a press on
     an acquired frame over a field must still choose the target. */
  onTouched: (found) => theRunWasPressed(found),
  /* The scan drawn beneath is registered to this picture, so it has to follow
     every move of it. The wheel and the drag belong to the canvas now, and a
     page that only followed its own redraws would let the two come apart the
     first time somebody zoomed. */
  onViewMoved: (where) => {
    /* Use the view carried by the event. Reading it back from the engine in
       the same callback can still return the preceding frame, leaving the
       acquired picture one wheel tick behind the workflow layers. */
    thePicture.followTheStage(keepItOnScreen(where));
    /* Custom workflow layers are retained drawings, not engine imagery.
       Moving only the engine left them painted with the previous projection
       until an unrelated state change happened to redraw the run. */
    /* The engine commits its projection after this callback. Draw on the next
       frame so custom layers use that projection, not the preceding one. */
    redrawViewSoon();
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
/* And above it, the canvas's own presses, which float over the picture:
   it runs under them to the top edge, so Fit lands the travel the margin
   below their lower edge rather than behind them. Measured, not declared,
   so the gap under the presses is the gap beside the travel whatever the
   row's height is. */
function roomAbove() {
  const row = stageBox.closest(".plot-column")?.querySelector(".canvas-toolbar");
  if (!row) return 0;
  /* The row's content edge rather than a press's: the presses are away
     until the microscope is connected, and the row stands either way. */
  const edge = row.getBoundingClientRect().bottom - parseFloat(getComputedStyle(row).paddingBottom);
  return Math.max(0, edge - stageBox.getBoundingClientRect().top);
}

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
    y: STAGE_ORIGIN_UM[1] + (h / 2 - roomAbove() - FIT_MARGIN) * zoom - oy,
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
  return 1 / Math.min((w - 2 * FIT_MARGIN) / fw, (h - roomAbove() - 2 * FIT_MARGIN) / fh);
}

/**
 * The canvas has been given a different width — the operator dragged the
 * divider between the picture and the channel.
 *
 * The sample position at the visual centre stays there. A sidebar is furniture
 * around the picture, not a pan gesture: shifting the centre by half the width
 * change pushed a zoomed tileset sideways whenever the column was folded.
 * The zoom is preserved as well; only an explicit Fit may change it.
 */
function theCanvasNarrowed() {
  const where = theCanvas.view;
  const box = stageBox.getBoundingClientRect();
  const w = box.width || 800;
  if (!where?.centre || !lastWidth || Math.abs(w - lastWidth) < 0.5) {
    lastWidth = w;
    return;
  }
  lastWidth = w;
  straightening = true;
  theCanvas.lookAt(where);
  straightening = false;
  thePicture.followTheStage(where);
}
let lastWidth = 0;

/* View callbacks arrive before the drawing engine has committed the matching
   projection. Coalesce wheel/drag bursts and repaint on the next browser
   frame; an immediate repaint is visibly one zoom or pan behind. */
let viewRedraw = 0;
function redrawViewSoon() {
  if (viewRedraw) return;
  viewRedraw = requestAnimationFrame(() => {
    /* One frame lets the viewer consume the state update; the next observes
       its new projection. This is not a timed delay and coalesces a gesture
       burst into one repaint. */
    viewRedraw = requestAnimationFrame(() => {
      viewRedraw = 0;
      if (view.fitted) drawStage();
    });
  });
}

/* Every way the view can move ends here, whichever gesture moved it. Held off
   by a frame so the correction is one more view change and not a call made
   from inside the canvas telling it where to be while it is telling us where
   it went. */
let straightening = false;
function keepItOnScreen(where) {
  if (straightening || !where?.centre) return where;
  const should = insideTheLimits(where);
  const off = Math.abs(should.zoom - where.zoom) > 1e-9
    || Math.abs(should.centre.x - where.centre.x) > 1e-6
    || Math.abs(should.centre.y - where.centre.y) > 1e-6;
  if (!off) return where;
  straightening = true;
  theCanvas.lookAt(should);
  straightening = false;
  return should;
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
  /* A red hairline down the middle of the black: the mark is found by its
     halo and read by its colour. */
  ctx.strokeStyle = "#dc2626";
  ctx.fillStyle = "#dc2626";
  ctx.lineWidth = 1;
  crosshair(ctx, x, y, arm, 5, stageMarkHot ? 1.4 : 1.1, 10);
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
 * something any step could know: it interleaves them. Carrier, focus heatmap
 * and overview plan sit below the acquisition picture; markers sit above it.
 * What each layer draws belongs to its step; where it sits belongs here.
 *
 * Within each drawing slot, layers that stay solid are drawn last. See
 * `parts/canvas/layers-above.js`.
 */
const THE_STACK = [
  "ground", "limits", "carrier", "focus", "plan",
  "picture",
  "tiles", "segmentation", "frames", "cells", "targets",
  "focusFrame", "focusPoints", "detect", "editing", "anchors", "stage", "scale",
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
      explains: "The opaque background beneath the plan and acquired images.",
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
    showLegend,
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
    picture: { key: "picture", has: false },
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
  if (ctx.tilesetButton) ctx.tilesetButton.disabled = !run.plan.length;
  legendSettles();

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
    if (layer.has === undefined) layer.has = layer.shown !== false;
  }
  theStack = stack;
  theCanvas.setLayersAbove(stack);
  if (ctx.tileButton) ctx.tileButton.disabled = !theFramedField();
  sayWhatThePressesDo();

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
 * The discovered targets in the canvas's carrier-local frame.
 *
 * This is a read-only evidence surface, like `plan()` and `project()` below:
 * browser checks can prove that the same physical targets stay at the same
 * canvas positions while the workflow changes their candidate, selected, and
 * acquired presentation. It does not become another coordinate authority;
 * every screen point is read from the canvas's existing projection.
 */
function targetSnapshot() {
  const acquired = new Set((run.acquired ?? []).flatMap((key) =>
    run.acquiredTiles?.[key]?.tile?.completes
      ?? run.acquiredTiles?.[key]?.tile?.covers ?? []));
  return [...run.cells.values()].map((cell) => {
    const at = theCanvas.project(cell.x, cell.y);
    return {
      id: cell.id,
      field: cell.field,
      x: cell.x,
      y: cell.y,
      screen: { x: at.x, y: at.y },
      selected: (run.done?.has("select") ? run.restricted : run.gated).has(cell.id),
      restricted: run.restricted.has(cell.id),
      acquired: acquired.has(cell.id),
    };
  });
}

/**
 * What the canvas will answer to, from outside it.
 *
 * Read-only geometry and layer controls used by the browser tests.
 */
window.__theStageCanvas = {
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
 * On the picture, not in a strip of its own: the white band it once cleared
 * along the bottom read as a margin under the picture, on Thom's word. */

function drawScaleBar(ctx, w, h, scale) {
  const targetPx = 130;
  const raw = targetPx / scale;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const nice = [1, 2, 5, 10].map((m) => m * pow).reduce((a, b) =>
    Math.abs(b - raw) < Math.abs(a - raw) ? b : a);
  const px = nice * scale;
  const x = w - px - 20, y = h - 9;

  ctx.strokeStyle = css("--ink-2");
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(x, y); ctx.lineTo(x + px, y);
  ctx.stroke();
  ctx.fillStyle = css("--ink-2");
  ctx.font = '600 13px ui-monospace, Consolas, monospace';
  ctx.textAlign = "center";
  ctx.fillText(nice >= 1000 ? `${nice / 1000} mm` : `${nice} µm`, x + px / 2, y - 6);
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

  /* No tip over a cell: the picture says what a cell is, and a box that
     followed the pointer over every one of them was in the way. */
  stageTip.classList.remove("on");
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


/* Carrier frames whichever picture is on show. While the acquired overview
   is covering the plan, it is the thing being looked at, so it is the thing
   that gets framed. */
ctx.carrierButton.addEventListener("click", () => {
  if (liveOverview.showing) { liveOverview.fit(); return; }
  fitView(); drawStage();
});

/**
 * The tilesets the plan holds, each as the box its fields cover, in the
 * carrier's micrometres. The plan lists fields; a tileset is the group of
 * them one drawn area or one well gave, and it is what an operator wants
 * to look at as one thing.
 */
function theTilesets() {
  const boxes = new Map();
  for (const t of run.plan) {
    const key = t.tileset ?? t.fieldId ?? "plan";
    const half = t.frameUm / 2;
    const box = boxes.get(key) ?? { key, xMin: Infinity, yMin: Infinity, xMax: -Infinity, yMax: -Infinity };
    box.xMin = Math.min(box.xMin, t.x - half); box.xMax = Math.max(box.xMax, t.x + half);
    box.yMin = Math.min(box.yMin, t.y - half); box.yMax = Math.max(box.yMax, t.y + half);
    boxes.set(key, box);
  }
  /* Reading order: top row first, left to right, so pressing again walks the
     plate the way a person reads it. */
  return [...boxes.values()].sort((a, b) => (a.yMin - b.yMin) || (a.xMin - b.xMin));
}

/* Which tileset the last press framed, so the next press can go on to the
   next one; forgotten when the view has been moved off it by hand. */
let framedTileset = null;

/**
 * Tile set: frame one tileset, filling the canvas with it. The first press
 * takes the one nearest the middle of what is on screen; a press while that
 * one is still in the middle goes on to the next in reading order, and round
 * again, so the button is also a tour of the plate.
 */
function frameTileset() {
  const sets = theTilesets();
  if (!sets.length) return;
  const here = theView().centre;
  const middle = (b) => ({ x: (b.xMin + b.xMax) / 2, y: (b.yMin + b.yMax) / 2 });
  const inside = (b) => here.x >= b.xMin && here.x <= b.xMax && here.y >= b.yMin && here.y <= b.yMax;
  let index = sets.findIndex((b) => b.key === framedTileset);
  if (index >= 0 && inside(sets[index])) {
    index = (index + 1) % sets.length;
  } else {
    let best = Infinity;
    sets.forEach((b, i) => {
      const m = middle(b);
      const d = Math.hypot(m.x - here.x, m.y - here.y);
      if (d < best) { best = d; index = i; }
    });
  }
  const box = sets[index];
  framedTileset = box.key;
  const rect = stageBox.getBoundingClientRect();
  const w = rect.width || 800, h = rect.height || 600;
  /* With some ground round it, as Tile keeps: filling the canvas edge to
     edge read as the whole picture rather than as one tileset of it. */
  const room = 1 + 2 * ROOM_AROUND_A_TILESET;
  const zoom = Math.max(
    (box.xMax - box.xMin) * room / Math.max(1, w - 2 * FIT_MARGIN),
    (box.yMax - box.yMin) * room / Math.max(1, h - 2 * FIT_MARGIN),
  );
  theCanvas.lookAt({ zoom, centre: middle(box) });
  thePicture.followTheStage({ zoom, centre: middle(box) });
  drawStage();
}
ctx.tilesetButton.addEventListener("click", frameTileset);

/* The one field the frame is on: the position detection is tuned on, or
   before the scan the field under the stage. The layer that draws the
   frame says where it stands. */
function theFramedField() {
  const layer = theStack.find((one) => one.key === "detect" && one.has);
  return layer?.field?.() ?? null;
}

/* How much ground a framed field keeps around it, as a fraction of its
   width each side. A sixth of a field: the field stands in the middle of
   the canvas at three quarters of its shorter side, with a rim of its
   neighbours round it. Half a field each side was tried and read as too
   far out; the operator asked for the field a bit bigger than that. */
const ROOM_AROUND_A_TILE = 1 / 6;

/* And round a framed tileset, as a fraction of its width each side: less
   than a tile keeps, since a tileset is the thing being looked at whole. */
const ROOM_AROUND_A_TILESET = 0.1;

/** The zoom that frames a field of `frameUm` with a little ground around it. */
function zoomForATile(frameUm) {
  const rect = stageBox.getBoundingClientRect();
  const w = rect.width || 800, h = rect.height || 600;
  return frameUm * (1 + 2 * ROOM_AROUND_A_TILE) / Math.max(1, Math.min(w, h) - 2 * FIT_MARGIN);
}

/** Tile: frame the current field, with a little ground around it. Pressed
    while that field is already framed -- in the middle, at a tile's zoom --
    it goes on to the next field in reading order, and round again, so the
    press is also a tour of the plan, the way Tile set tours the tilesets. */
function frameTile() {
  const layer = theStack.find((one) => one.key === "detect" && one.has);
  let t = layer?.field?.() ?? null;
  if (!t) return;
  const here = theView();
  const inTheMiddle = Math.abs(here.centre.x - t.x) <= t.frameUm / 2
    && Math.abs(here.centre.y - t.y) <= t.frameUm / 2;
  const atATilesZoom = Math.abs(here.zoom - zoomForATile(t.frameUm)) <= 0.1 * zoomForATile(t.frameUm);
  if (inTheMiddle && atATilesZoom && layer.next) {
    layer.next();
    t = layer.field?.() ?? t;
  }
  const zoom = zoomForATile(t.frameUm);
  const centre = { x: t.x, y: t.y };
  theCanvas.lookAt({ zoom, centre });
  thePicture.followTheStage({ zoom, centre });
  drawStage();
}
ctx.tileButton?.addEventListener("click", frameTile);

/* ---- the picture's half of the canvas row -------------------------------
   Which acquisition the row is about, its channels as chips, and beside it the masks as
   one of them, and Grayscale. The chips read the picture's own panel and
   act through it, so the row and Display settings never disagree. */

/* The acquisition the row shows: the operator's choice, else the one the
   step is about -- the focus stacks on the focus step, the targets while
   acquiring, the overview otherwise -- else the first there is. */
let chosenAcquisition = null;
function theRowsAcquisition(names) {
  if (chosenAcquisition && names.includes(chosenAcquisition)) return chosenAcquisition;
  const mode = step(run.activeIdx)?.mode;
  const wanted = mode === "focus" ? "focussing" : mode === "targets" ? "targets" : "overview";
  return names.includes(wanted) ? wanted : names[0] ?? null;
}

/* Every card in the row closes the way a menu does: a press anywhere else,
   or Escape. */
const cards = [];
/* The press that opened the card on show, so that the same press closes it:
   a triangle that only ever opened left no way back but a click elsewhere. */
let openedBy = null;
function openOnly(card, button, open) {
  for (const [c, b] of cards) {
    const on = open && c === card;
    c.hidden = !on;
    b?.setAttribute("aria-expanded", String(on));
  }
  openedBy?.setAttribute("aria-expanded", "false");
  openedBy = open ? button : null;
  openedBy?.setAttribute("aria-expanded", "true");
}
function closeTheCards() { openOnly(null, null, false); }
/** Open the card from this press, or close it if this press opened it.
    The presses are drawn afresh after every press, so the one that opened
    the card is known by its label rather than by identity. */
function toggleFrom(card, button, open) {
  const same = openedBy && openedBy.getAttribute("aria-label") === button.getAttribute("aria-label");
  if (same && !card.hidden) { closeTheCards(); return false; }
  open();
  openOnly(card, button, true);
  return true;
}
document.addEventListener("click", (e) => {
  if (cards.some(([c]) => !c.hidden) && !e.target.closest?.(".canvas-toolbar-right")) closeTheCards();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeTheCards(); });

/* Masks: a bar of their own at the right end of the row, one cell per mask
   layer lying on the acquisition the row shows. A press on a cell shows or
   hides that layer; the triangle beside it opens the layer's card, where
   the eye, the colour, the look and the opacity are that layer's own. The
   card is one card for whichever layer was last opened. */
let chosenMask = null;
if (ctx.maskPop) cards.push([ctx.maskPop, null]);
const theMaskKind = () => theAcquisitionOnShow() ?? "overview";
/* The masks on the picture: those of every acquisition shown in it, not
   only of the one the row names. On the acquisition step the row names the
   targets, whose pictures have no masks, while the overview's masks are
   still drawn under them -- and a mask on the picture with no chip in the
   strip cannot be dressed or put away. */
const theMaskLayers = () => {
  const shown = new Set((window.__viewerPanel?.acquisitions?.() ?? [])
    .filter((one) => one.shown).map((one) => one.name));
  const masks = shown.size
    ? (run.masks ?? []).filter((one) => shown.has(one.kind))
    : maskLayersOn(run.masks ?? [], theMaskKind());
  return [...masks, theTilesLayer(), theTargetsLayer()].filter(Boolean);
};
/* The target tiles, as a layer of the strip: between the masks and the
   targets, as they lie in the picture. Their cell is a square, since that
   is what they are on the picture; colour null is the page's accent. */
const theTilesLayer = () => {
  const frames = theCanvas.layersAbove.find((one) => one.key === "frames" && one.has);
  if (!frames) return null;
  return {
    id: "tiles", name: "target tiles", how: "placed", objects: run.targetTiles?.length ?? 0,
    get shown() { return theCanvas.layerShown?.("frames") ?? true; },
    set shown(on) { theCanvas.showLayer("frames", on); },
    dress: run.tilesDress,
    ownColour: css("--accent"),
    glyph: "square",
  };
};
/* The chosen targets, as a layer of the strip: after the masks they were
   chosen from, in a mask layer's shape so the one card dresses them. Shown
   is the canvas's own switch for the cells layer, read and set through it;
   the dress is the run's. Colour null is each target's own ink, the
   selected green, and the cell in the strip wears that. */
const theTargetsLayer = () => {
  const cells = theCanvas.layersAbove.find((one) => one.key === "cells" && one.has);
  if (!cells) return null;
  const lit = run.restricted?.size ? run.restricted : run.gated?.size ? run.gated : run.cells;
  return {
    id: "targets", name: "targets", how: "selected", objects: lit?.size ?? 0,
    get shown() { return theCanvas.layerShown?.("cells") ?? true; },
    set shown(on) { theCanvas.showLayer("cells", on); },
    dress: run.targetsDress,
    ownColour: css("--mark-selected"),
  };
};
const theChosenMask = () => {
  const layers = theMaskLayers();
  return layers.find((one) => one.id === chosenMask) ?? layers[0] ?? null;
};
/* A change to the chosen layer: made, drawn, and said in the bar and the card. */
const dressTheChosen = (change) => {
  const layer = theChosenMask();
  if (!layer) return;
  change(layer);
  drawStage();
  sayWhatThePressesDo();
};
ctx.maskEye?.addEventListener("click", () => dressTheChosen((layer) => { layer.shown = !layer.shown; }));
if (ctx.channelPop) cards.push([ctx.channelPop, null]);
let channelBox = null;

/* What a colour channel's box needs of the panel: its numbers as they
   stand, and where a change goes. The panel keeps the truth; the column's
   own box and this one both read it. */
const aColourChannel = (panel, index, label) => ({
  kind: "colour", label, unit: "",
  state: () => panel.channelBox?.(index) ?? null,
  setWindow: (window_) => panel.channelAct?.(index, { window: window_ }),
  setAxis: (axis) => panel.channelAct?.(index, { axis }),
  setWeight: (weight) => panel.channelAct?.(index, { weight }),
  setGamma: (gamma) => panel.channelAct?.(index, { gamma }),
  setSaturate: (saturate) => panel.channelAct?.(index, { saturate }),
  setLog: (log) => panel.channelAct?.(index, { log }),
  setVisible: (on) => panel.setChannelVisible?.(index, on),
  setColour: (hex) => panel.channelAct?.(index, { colour: hex }),
  auto: () => panel.autoChannel?.(index),
  changed: () => sayWhatThePressesDo(),
});

/* The grey channel's box speaks in percent of the summed window: the
   composite's shares are its numbers, and the axis on view is its own. */
const theGreyChannel = (panel, acquisition) => {
  let view = null;
  return {
    kind: "grey", label: `the grey ${acquisition}`, unit: "%",
    state: () => {
      const c = panel.composite?.(acquisition);
      if (!c) return null;
      return {
        title: acquisition,
        counts: c.counts, range: { low: 0, high: 100 },
        window: { low: c.a * 100, high: c.b * 100 },
        axis: view ?? { low: 0, high: 100 },
        weight: c.s, log: Boolean(c.log), measured: c.measured,
        gamma: panel.gammaOf?.(acquisition) ?? 1,
      };
    },
    setGamma: (gamma) => panel.setGammaOf?.(acquisition, gamma),
    setWindow: ({ low, high }) => {
      const a = Math.max(0, Math.min(low, 98)) / 100;
      const b = Math.max(a + 0.02, Math.min(high, 100) / 100);
      panel.setComposite?.(acquisition, { a, b });
    },
    setAxis: (axis) => {
      if (!axis) { view = null; return; }
      const low = Math.max(0, Math.min(axis.low, 99));
      view = { low, high: Math.min(100, Math.max(axis.high, low + 1)) };
    },
    setWeight: (s) => panel.setComposite?.(acquisition, { s }),
    setLog: (log) => panel.setComposite?.(acquisition, { log }),
    auto: () => panel.autoComposite?.(acquisition),
    changed: () => sayWhatThePressesDo(),
  };
};

/* The grey channel's chip: while the picture is grey it stands in for the
   dots, and a press opens the one box for the sum. */
let greyBox = null;
if (ctx.greyPop) cards.push([ctx.greyPop, ctx.greyChipMore]);
const openTheGreyBox = (e) => {
  e.stopPropagation();
  const panel = window.__viewerPanel;
  const names = panel?.acquisitions?.().map((one) => one.name) ?? [];
  const shown = theRowsAcquisition(names);
  if (!panel || !shown) return;
  if (ctx.greyPop.hidden) {
    greyBox = mountChannelBox(ctx.greyPop, theGreyChannel(panel, shown));
    openOnly(ctx.greyPop, ctx.greyChipMore, true);
  } else {
    openOnly(ctx.greyPop, ctx.greyChipMore, false);
  }
};
ctx.greyChipMore?.addEventListener("click", openTheGreyBox);
/* A mask layer's colour: a rainbow dot for each object its own colour, a
   few swatches -- five colours and a grey -- and at the end a swatch that
   opens the browser's own colour picker for any other. */
const MASK_SWATCHES = ["#ffd400", "#ff5a5f", "#3ddc84", "#4f8dff", "#c04bff", "#9aa3ad"];
let maskPicker = null;
if (ctx.maskColours) {
  const rainbow = document.createElement("button");
  rainbow.type = "button";
  rainbow.className = "mask-colour";
  rainbow.dataset.colour = "";
  rainbow.style.background = MASK_RAINBOW;
  rainbow.title = "Each object its own colour";
  rainbow.addEventListener("click", () => dressTheChosen((layer) => { layer.dress.colour = null; }));
  ctx.maskColours.append(rainbow);
  for (const hex of MASK_SWATCHES) {
    const one = document.createElement("button");
    one.type = "button";
    one.className = "mask-colour";
    one.dataset.colour = hex;
    one.style.background = hex;
    one.title = "Every object in this colour";
    one.addEventListener("click", () => dressTheChosen((layer) => { layer.dress.colour = hex; }));
    ctx.maskColours.append(one);
  }
  const swatch = document.createElement("label");
  swatch.className = "mask-colour mask-pick";
  swatch.title = "Every object in one colour: choose it";
  maskPicker = document.createElement("input");
  maskPicker.type = "color";
  maskPicker.id = "mask-picker";
  maskPicker.value = "#ffd400";
  maskPicker.setAttribute("aria-label", "choose a colour for the masks");
  maskPicker.addEventListener("input", () => dressTheChosen((layer) => { layer.dress.colour = maskPicker.value; }));
  swatch.append(maskPicker);
  ctx.maskColours.append(swatch);
}
ctx.maskFill?.addEventListener("click", () => dressTheChosen((layer) => { layer.dress.show = "fill"; }));
ctx.maskLine?.addEventListener("click", () => dressTheChosen((layer) => { layer.dress.show = "line"; }));
ctx.maskOpacity?.addEventListener("input", () => {
  dressTheChosen((layer) => { layer.dress.alpha = Number(ctx.maskOpacity.value) / 100; });
});

/* A cell with six uneven bumps, no two sides alike, the way a real cell
   lies: the glyph a mask layer wears in the bar, in its own dress. */
const MASK_CELL = "M16.70 14.15 C16.96 14.81 18.88 16.79 19.07 17.57 C19.25 18.36 18.58 19.05 17.79 18.89 C16.99 18.73 15.05 17.03 14.30 16.63 C13.55 16.23 13.45 16.24 13.28 16.50 C13.11 16.76 13.42 17.79 13.26 18.20 C13.10 18.62 12.63 18.86 12.32 18.99 C12.01 19.12 11.70 19.12 11.40 18.97 C11.10 18.83 10.91 18.46 10.50 18.15 C10.08 17.83 9.52 17.66 8.93 17.08 C8.33 16.51 7.79 15.26 6.93 14.70 C6.07 14.14 4.34 14.24 3.78 13.74 C3.23 13.25 3.15 12.32 3.60 11.74 C4.06 11.16 5.92 10.57 6.53 10.24 C7.14 9.92 7.10 10.17 7.27 9.80 C7.43 9.43 7.52 8.66 7.52 8.03 C7.53 7.40 7.19 6.46 7.32 6.01 C7.45 5.57 7.84 5.30 8.31 5.36 C8.77 5.41 9.53 6.12 10.09 6.33 C10.65 6.54 11.44 6.47 11.67 6.61 C11.89 6.75 11.25 7.82 11.46 7.16 C11.67 6.50 12.40 3.35 12.92 2.65 C13.44 1.95 14.35 2.12 14.58 2.96 C14.81 3.80 14.22 6.76 14.28 7.70 C14.34 8.64 14.33 8.33 14.94 8.59 C15.55 8.85 17.33 9.03 17.93 9.27 C18.53 9.51 18.38 9.78 18.51 10.04 C18.64 10.31 18.70 10.55 18.70 10.84 C18.70 11.13 18.72 11.32 18.52 11.79 C18.33 12.26 17.82 13.26 17.52 13.66 C17.21 14.05 16.44 13.50 16.70 14.15Z";
/* A tile's cell: a square of the cell glyph's size. */
const MASK_SQUARE = "M4.5 4.5 H19.5 V19.5 H4.5 Z";

/* The masks bar: one cell per mask layer on the acquisition the row shows,
   rebuilt only when a layer, its dress or the chosen one changes. */
/* The discovered targets on the picture, as the mask strip sees them: a
   layer of the stage's, present on the steps that choose targets, hidden
   or shown by the operator's hand like any layer. In the strip because they
   look like a mask -- green shapes over the tissue -- and a mask the strip
   did not list, with the detection's mask switched off, read as a mask
   that had appeared from nowhere. */
function drawTheMasks(layers) {
  const host = ctx.maskCells;
  if (!host) return;
  const chosen = theChosenMask()?.id ?? null;
  const stamp = JSON.stringify([layers, chosen]);
  if (host.dataset.stamp === stamp) return;
  host.dataset.stamp = stamp;
  host.replaceChildren();
  for (const layer of layers) {
    const chip = document.createElement("span");
    chip.className = `chip mask-cell${layer.shown ? " on" : " off"}${layer.id === chosen ? " chosen" : ""}`;
    chip.dataset.mask = layer.id;
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "mask-dot";
    dot.title = layer.shown ? `Hide ${layer.name}` : `Show ${layer.name}`;
    dot.setAttribute("aria-pressed", String(layer.shown));
    dot.setAttribute("aria-label", `show or hide ${layer.name}`);
    /* The cell wears the layer's dress: its colour, or its own -- the
       rainbow of a mask, the green of the targets -- filled, or a thick
       outline round a white middle when the layer is outlines. */
    const paint = layer.dress.colour ?? layer.ownColour ?? "url(#mask-rainbow)";
    const line = layer.dress.show === "line";
    const shape = layer.glyph === "square" ? MASK_SQUARE : MASK_CELL;
    dot.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="${shape}" fill="${line ? "#ffffff" : paint}" stroke="${line ? paint : "rgba(15, 23, 42, 0.35)"}" stroke-width="${line ? "2.2" : "0.8"}" stroke-linejoin="round"/></svg>`;
    dot.addEventListener("click", (e) => {
      e.stopPropagation();
      layer.shown = !layer.shown;
      drawStage();
      sayWhatThePressesDo();
    });
    const more = chipMore(`settings for ${layer.name}`);
    more.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFrom(ctx.maskPop, more, () => { chosenMask = layer.id; });
      sayWhatThePressesDo();
    });
    chip.append(dot, more);
    host.append(chip);
  }
}

/* The acquisition picker: the layers pictogram, the ramp chip, the
   acquisition's name, and a menu of every acquisition with an eye and a
   chip of its own. Choosing one puts its channels in the row; its eye shows
   or hides the whole acquisition; its chip draws it in grey or in colour.
   The press is a span with a button inside it, so it answers the keyboard
   the way a button would. */
const pickButton = ctx.acquisitionPick?.querySelector("#acquisition-btn");
if (ctx.acquisitionMenu) cards.push([ctx.acquisitionMenu, pickButton]);
const openThePicker = (e) => {
  e.stopPropagation();
  openOnly(ctx.acquisitionMenu, pickButton, ctx.acquisitionMenu.hidden);
};
pickButton?.addEventListener("click", openThePicker);
pickButton?.addEventListener("keydown", (e) => {
  if (e.target !== pickButton || (e.key !== "Enter" && e.key !== " ")) return;
  e.preventDefault();
  openThePicker(e);
});

/* Colour or grey is the acquisition's own: the picture's panel keeps the
   colours and does the drawing, and the chip on the acquisition's name --
   in the press and on its line in the menu -- is the one switch, shown
   twice. */
const theAcquisitionOnShow = () =>
  theRowsAcquisition((window.__viewerPanel?.acquisitions?.() ?? []).map((one) => one.name));
const drawTheAcquisitionIn = (name, grey) => {
  window.__viewerPanel?.drawInGrey?.(name, grey);
  sayWhatThePressesDo();
};
ctx.rampChip?.addEventListener("click", (e) => {
  e.stopPropagation();
  const shown = theAcquisitionOnShow();
  if (shown) drawTheAcquisitionIn(shown, ctx.rampChip.getAttribute("aria-pressed") !== "true");
});
/* The eye in the press is the shown acquisition's own switch, the same
   one its line in the menu carries; it hides or shows without opening the
   menu, and the menu follows through the panel. */
ctx.acquisitionEye?.addEventListener("click", (e) => {
  e.stopPropagation();
  const shown = theAcquisitionOnShow();
  if (shown) window.__viewerPanel?.showAcquisition?.(shown, ctx.acquisitionEye.getAttribute("aria-pressed") !== "true");
  sayWhatThePressesDo();
});

/* The panel is remade when the picture's sources change, so the hook is
   put on whichever panel stands now, once. */
let hookedPanel = null;
function followThePanel() {
  const panel = window.__viewerPanel;
  if (!panel || panel === hookedPanel) return;
  hookedPanel = panel;
  panel.onChanged?.(() => sayWhatThePressesDo());
}

/* The chip's glyph: both ramps, and the chip's pressed state says which one
   shows. The gradients are defined once, on the chip in the press. */
const RAMP = '<svg width="14" height="8" viewBox="0 0 14 8" aria-hidden="true"><rect class="ramp colours" width="14" height="8" rx="1.5"/><rect class="ramp greys" width="14" height="8" rx="1.5"/></svg>';
/* One chip, in the press or on a menu line, told what it stands for. */
function dressTheChip(chip, name, grey) {
  chip.setAttribute("aria-pressed", String(grey));
  chip.setAttribute("aria-label", `show ${name} in colour or in grey`);
  chip.title = grey ? "Show this layer in colour" : "Show this layer in grey";
}
/* One eye, in the press or on a menu line, told whose it is and whether
   that acquisition is on show. */
function dressTheEye(eye, name, shown) {
  eye.setAttribute("aria-pressed", String(shown));
  eye.setAttribute("aria-label", `show or hide ${name}`);
  eye.title = shown ? `Hide ${name}` : `Show ${name}`;
}
const EYE = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/><path class="acquisition-eye-slash" d="M3 13L13 3"/></svg>';

/* One chip per channel of the acquisition the row shows: a dot in the
   channel's colour and its name, or its number in the dot when the row is
   short of room. The dot shows or hides the channel -- hidden, the chip
   fades and a line crosses the dot. The name chooses the channel and opens
   Display settings, where its histogram, window and opacity are. */
/**
 * The small triangle beside a chip's dot or cell: the press that opens the
 * thing's card, where the dot itself shows or hides it. One shape for the
 * channels' chips and the masks' cells, so the row has one rule.
 */
function chipMore(label) {
  const more = document.createElement("button");
  more.type = "button";
  more.className = "chip-more";
  more.setAttribute("aria-label", label);
  more.setAttribute("aria-haspopup", "true");
  more.title = "Open its box";
  more.innerHTML = '<svg width="8" height="8" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>';
  return more;
}

function drawTheChips(panel, acquisition) {
  const host = ctx.chips;
  if (!host) return;
  const channels = acquisition ? panel.channelsOf(acquisition) : [];
  const stamp = JSON.stringify(channels);
  if (host.dataset.stamp !== stamp) {
    host.dataset.stamp = stamp;
    host.replaceChildren();
    channels.forEach((channel, n) => {
      const chip = document.createElement("span");
      chip.className = `chip${channel.visible ? " on" : " off"}${channel.chosen ? " chosen" : ""}`;
      chip.dataset.channel = channel.name;
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "chip-dot";
      dot.style.background = channel.color;
      dot.textContent = String(n + 1);
      dot.title = channel.visible ? `Hide ${channel.name}` : `Show ${channel.name}`;
      dot.setAttribute("aria-pressed", String(channel.visible));
      dot.setAttribute("aria-label", `show or hide ${channel.name}`);
      /* A press on the dot shows or hides the channel, at once and with no
         box in the way: switching a channel off is the frequent act. The
         dot's number in its colour says which channel it is. */
      dot.addEventListener("click", (e) => {
        e.stopPropagation();
        panel.setChannelVisible?.(channel.index, !channel.visible);
        sayWhatThePressesDo();
      });
      /* The triangle beside it opens the channel's box under the row: an
         eye, its colour and its name at the head, then its histogram and
         sliders, on the same numbers the column's own box shows. The box's
         eye and the dot are one state, read from the panel. */
      const more = chipMore(`settings for ${channel.name}`);
      more.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleFrom(ctx.channelPop, more, () => {
          panel.chooseRow(channel.index);
          channelBox = mountChannelBox(ctx.channelPop, aColourChannel(panel, channel.index, channel.name));
        });
        sayWhatThePressesDo();
      });
      chip.append(dot, more);
      host.append(chip);
    });
  }
}

/* The picker's menu: every acquisition, with an eye, its ramp chip and its
   name; the one the row shows is marked. */
function drawTheMenu(panel, acquisitions, shown) {
  const menu = ctx.acquisitionMenu;
  if (!menu) return;
  const greys = acquisitions.map((one) => Boolean(panel.acquisitionGrey?.(one.name)));
  const stamp = JSON.stringify([acquisitions, shown, greys]);
  if (menu.dataset.stamp === stamp) return;
  menu.dataset.stamp = stamp;
  menu.replaceChildren();
  for (const one of acquisitions) {
    const line = document.createElement("div");
    line.className = `acquisition-line${one.name === shown ? " chosen" : ""}${one.shown ? "" : " off"}`;
    const eye = document.createElement("button");
    eye.type = "button";
    eye.className = "acquisition-eye";
    eye.innerHTML = EYE;
    dressTheEye(eye, one.name, one.shown);
    eye.addEventListener("click", (e) => { e.stopPropagation(); panel.showAcquisition(one.name, !one.shown); });
    /* The line's chip switches this acquisition without choosing it, and
       the menu stays open: the operator is looking at the layers, not
       leaving them. */
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "ramp-chip";
    chip.innerHTML = RAMP;
    const grey = greys[acquisitions.indexOf(one)];
    dressTheChip(chip, one.name, grey);
    chip.addEventListener("click", (e) => { e.stopPropagation(); drawTheAcquisitionIn(one.name, !grey); });
    const name = document.createElement("button");
    name.type = "button";
    name.className = "acquisition-choose";
    name.textContent = one.name;
    name.addEventListener("click", () => { chosenAcquisition = one.name; closeTheCards(); sayWhatThePressesDo(); });
    line.append(eye, chip, name);
    menu.append(line);
  }
}

/* The row's right half, from what the picture shows now. Asked on every
   draw, on every change the panel reports, and after a press. */
function sayWhatThePressesDo() {
  followThePanel();
  const panel = window.__viewerPanel;
  const acquisitions = panel?.acquisitions?.() ?? [];
  const names = acquisitions.map((one) => one.name);
  const shown = theRowsAcquisition(names);
  const modes = document.getElementById("view-modes");
  if (modes) {
    const available = panel?.viewModes?.(shown) ?? [];
    modes.hidden = !available.length;
    for (const option of modes.options) option.disabled = !available.includes(option.value);
    modes.value = panel?.viewMode?.(shown) ?? "top";
    modes.onchange = () => panel.setViewMode(shown, modes.value).catch(console.error);
  }

  if (ctx.acquisitionPick) {
    ctx.acquisitionPick.hidden = !acquisitions.length;
    if (ctx.acquisitionName && shown) ctx.acquisitionName.textContent = shown;
    if (ctx.rampChip && shown) dressTheChip(ctx.rampChip, shown, Boolean(panel?.acquisitionGrey?.(shown)));
    if (ctx.acquisitionEye && shown) {
      dressTheEye(ctx.acquisitionEye, shown, acquisitions.find((one) => one.name === shown)?.shown !== false);
    }
    if (panel) drawTheMenu(panel, acquisitions, shown);
  }
  if (panel) drawTheChips(panel, shown);
  else if (ctx.chips) { ctx.chips.replaceChildren(); ctx.chips.dataset.stamp = ""; }
  /* Grey: the acquisition is one channel, so the dots give way to one chip. */
  const greyNow = Boolean(shown && panel?.acquisitionGrey?.(shown));
  if (ctx.greyChip) ctx.greyChip.hidden = !greyNow;
  if (ctx.chips) ctx.chips.hidden = greyNow;
  if (!greyNow && ctx.greyPop && !ctx.greyPop.hidden) closeTheCards();
  if (greyNow && ctx.greyPop && !ctx.greyPop.hidden) greyBox?.refresh();
  if (ctx.channelPop && !ctx.channelPop.hidden) channelBox?.refresh();

  if (ctx.masksBar) {
    const layers = theMaskLayers();
    ctx.masksBar.hidden = !layers.length;
    if (!layers.length && ctx.maskPop && !ctx.maskPop.hidden) closeTheCards();
    drawTheMasks(layers);
    const layer = theChosenMask();
    if (layer) {
      ctx.maskEye?.setAttribute("aria-pressed", String(layer.shown));
      if (ctx.maskName) ctx.maskName.textContent = layer.name;
      if (ctx.maskHow) {
        ctx.maskHow.textContent = `${layer.how} · ${layer.objects} object${layer.objects === 1 ? "" : "s"}`;
      }
      const dress = layer.dress;
      for (const swatch of ctx.maskColours?.querySelectorAll(".mask-colour[data-colour]") ?? []) {
        swatch.setAttribute("aria-pressed", String((dress.colour ?? "") === swatch.dataset.colour));
      }
      if (maskPicker) {
        const swatch = maskPicker.parentElement;
        const free = Boolean(dress.colour) && !MASK_SWATCHES.includes(dress.colour);
        swatch.setAttribute("aria-pressed", String(free));
        if (free && document.activeElement !== maskPicker) maskPicker.value = dress.colour;
        swatch.style.background = maskPicker.value;
      }
      const line = dress.show === "line";
      ctx.maskFill?.setAttribute("aria-pressed", String(!line));
      ctx.maskLine?.setAttribute("aria-pressed", String(line));
      const percent = Math.round(dress.alpha * 100);
      if (ctx.maskOpacity && document.activeElement !== ctx.maskOpacity) ctx.maskOpacity.value = String(percent);
      if (ctx.maskOpacity) ctx.maskOpacity.style.setProperty("--fill", `${((percent - 10) / 90) * 100}%`);
      if (ctx.maskOpacityValue) ctx.maskOpacityValue.textContent = `${percent}%`;
    }
  }
  /* The channels' box stands only when it holds something; without it the
     acquisition's press ends the strip on its own. */
  if (ctx.channelsBox) {
    const channelsThere = (Boolean(ctx.chips?.childElementCount) && !ctx.chips.hidden)
      || (ctx.greyChip && !ctx.greyChip.hidden);
    ctx.channelsBox.hidden = !channelsThere;
    pickButton?.classList.toggle("strip-last", !channelsThere);
  }
}

/* The legend at the foot of the picture, for whichever layer asks for one. A
   layer that paints hands over what its colours mean; when no layer has
   done so by the next frame, the row shows none. */
let legendAsked = false;
function showLegend(spec) {
  legendAsked = true;
  const el = ctx.legend;
  if (!el) return;
  el.hidden = false;
  el.querySelector(".canvas-legend-title").textContent = spec.title;
  el.querySelector(".canvas-legend-lo").textContent = spec.lo;
  el.querySelector(".canvas-legend-hi").textContent = spec.hi;
  el.querySelector(".canvas-legend-ramp").style.background = spec.ramp;
}
function legendSettles() {
  legendAsked = false;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (!legendAsked && ctx.legend) ctx.legend.hidden = true;
  }));
}

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
    /** Which acquisition the row's chips belong to right now. */
    acquisitionOnShow: () => theAcquisitionOnShow(),
    /* Restore an exact carrier-local view without depending on the global
       debug handle: the live picture beneath has a second canvas and may be
       the last one that registered itself there. */
    lookAt(where) {
      theCanvas.lookAt(where);
      /* Programmatic view changes do not emit the pointer/wheel callback.
         Keep the acquired picture beneath the workflow layers registered in
         exactly the same way those gestures do. */
      thePicture.followTheStage(where);
      redrawViewSoon();
    },
    fit: fitView,
    /* The canvas is the picture's; the page says when its box has changed
       shape, and what the pointer should look like over it. */
    /* The canvas measures itself; this only asks for the layers again, since
       what they draw depends on how big the box is. */
    resize() { theCanvasNarrowed(); redrawViewSoon(); },
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
    layers: () => theCanvas.layersAbove.map(({ key, label, shown, staysSolid }) =>
      ({ key, label, shown, staysSolid: !!staysSolid })),
    showLayer(key, on) { theCanvas.showLayer(key, on); drawStage(); },
    layerShown: (key) => theCanvas.layerShown?.(key) ?? true,
    fadeTo(value) { theCanvas.fadeTo(value); },
  };
}
