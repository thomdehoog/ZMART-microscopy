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

import carrierWidget from "../../shared/carrier-panel.ts";
import { METRICS, METRIC_KEYS, MIN_TISSUE_WIDTH_UM, findCandidates, pickPeak }
  from "../../shared/focus-curves.ts";
import {
  fitSurface, residualsUm, surfaceZ,
} from "./surface.ts";
import { sharePoints } from "../../shared/scanfields.ts";
import { visitOrder } from "./visit-order.ts";
import { zColourScale } from "./z-domain.ts";
import { status } from "zmart-interface/api";
import { progressBox } from "../../shared/progress.ts";
import { activeRecording } from "../../microscope/recordings.ts";
import type { Backend } from "../../backend/verbs.ts";
import type { FocusMap, MapPoint, PlanTile, Surface } from "../../shared/run-document.ts";
import type { XY } from "../../shared/scanfields.ts";
import type { StageAt } from "../../shared/stage-position.ts";
import type { TaRun, TaStep } from "../../types.ts";
/* The step's controls, as markup: read in as text by the build tool. */
import focusControlsMarkup from "./focus-controls.html?raw";

declare global {
  interface Window {
    /** The slice the focus preview shows, by name, for a browser test. */
    __theSliceShown?: () => string | null;
  }
}

/** The stage picture, as the focus map draws on it and drives through it. */
interface FocusStage {
  /** Screen pixels per micrometre, right now. */
  view: { scale: number };
  draw(): void;
  cursor(shape: string): void;
  toWorld(px: number, py: number): [number, number];
  carrierOriginUm(): [number, number];
  whereTheStageIs(): StageAt | null;
  toStage<P extends XY>(p: P): P;
  toCarrier<P extends XY>(p: P): P;
  /** Where the stage mark goes: a place, and the height last reported. */
  takeThePosition(at: StageAt | null | undefined): void;
}

/** What opening the focus map is handed: the run, the backend, the stage picture, and the page's plumbing. */
interface FocusMapContext {
  run: TaRun;
  backend: {
    measureFocus: Backend["measureFocus"];
    /** Where a focus stack's slice pictures are fetched from, or null when none are served. */
    slicesAt?: () => string | null;
    /** The run's own loop told to stop before its next point; the microscope is not asked. */
    stopFocusMeasure: Backend["stopFocusMeasure"];
  };
  stage: FocusStage;
  el: (id: string) => HTMLElement | null;
  css: (name: string) => string;
  sizeCanvas: (cv: HTMLCanvasElement & { cssW?: number; cssH?: number }) => boolean;
  step: (index: number) => TaStep;
  focusControls: HTMLElement;
  renderActionBar: () => void;
  tileChosen?: () => void;
  edited?: () => void;
  /** The step run again, through the runner, doing `measure` as its run. */
  runTheMap: (measure: () => Promise<void>) => unknown;
}

/** The plan position under a place: the tile, its index in the plan, and how far its centre is. */
interface Nearest {
  t: PlanTile;
  i: number;
  d: number;
}

/** What a legend row is told: its title, the two ends, and the ramp between them as a CSS gradient. */
interface Legend {
  title: string;
  lo: string;
  hi: string;
  ramp: string;
}

/**
 * The focus map, open: what the picture and the page may ask of it. Written
 * out rather than read off the function that makes it, because the page's
 * own type is built from it.
 */
export interface FocusMapHandle {
  /** The surface and the positions, drawn early; what its colours mean, or null while there is no surface. */
  drawFocusLayer(ctx: CanvasRenderingContext2D, toScreen: (x: number, y: number) => [number, number],
    scale: number, w: number, h: number): Legend | null;
  /** The points alone, drawn above the plan. */
  drawFocusPoints(ctx: CanvasRenderingContext2D, toScreen: (x: number, y: number) => [number, number]): void;
  focusPressed(px: number, py: number): boolean;
  focusCursor(): string;
  focusDraggedTo(px: number, py: number): void;
  focusGrabbed(e: { offsetX: number; offsetY: number; shiftKey: boolean }): boolean;
  focusHovered(e: { offsetX: number; offsetY: number }): boolean;
  focusMarqueeTo(px: number, py: number): void;
  focusMarqueeTook(shift: boolean): void;
  marqueeing(): boolean;
  dragging(): boolean;
  /** Lets go of the point being dragged: which it was and whether it moved, or nothing. */
  endDrag(): Partial<FocusDrag>;
  anchorPressed(px: number, py: number): boolean;
  detectPressed(px: number, py: number): boolean;
  surfaceZAt(x: number, y: number): number | null;
  nearestPosition(x: number, y: number): Nearest | null;
  renderFocusBar(): void;
  renderPointList(): void;
  drawTrace(): void;
  refitSurface(): void;
  /** Measures every point; says whether the operator's hand stopped it, or nothing when there were none. */
  remeasure(how?: { from?: "stage" | "map" | null }): Promise<{ stopped: boolean } | undefined>;
  interruptTheRun(): void;
  mounted(): boolean;
}

/** A box, in micrometres. */
interface Bounds {
  xMin: number;
  yMin: number;
  xMax: number;
  yMax: number;
}

/** A point being dragged: which, whether the pointer has moved, and where every point stood when it was taken hold of. */
interface FocusDrag {
  at: number;
  moved: boolean;
  held: XY[];
}

/** The rectangle being drawn: where it started and where the pointer is, in the carrier's micrometres. */
interface Marquee {
  sx: number;
  sy: number;
  cx: number;
  cy: number;
}

/** One slice of a focus stack, as the backend names its copy. */
interface Slice {
  name: string;
  z_um: number;
}

/** A slice picture being fetched, whoever is waiting for it, and whether it failed. */
interface Fetched {
  img: HTMLImageElement;
  waiting: ((img: HTMLImageElement | null) => void)[];
  failed?: boolean;
}

/** Where a metric's name is written under the plot, to be pressed. */
interface LegendHit {
  key: string;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** The plot as last drawn, for the drag that reads a height off it. */
interface TraceGeom {
  zLo: number;
  zHi: number;
  P: { l: number; r: number; t: number; b: number };
  w: number;
  h: number;
  samples: { z: number; s: number }[];
}

/* The controls go into the page the moment this module loads, hidden, so
   that `openTheFocusMap` below finds every element by its id when the page
   starts and the step's channel can move them into the column later. The
   page's template knows no step, which is why the markup arrives from here
   rather than being written in it. Guarded, because the unit tests load
   this module in Node, where there is no document to put anything into. */
if (typeof document !== "undefined" && !document.getElementById("focus-controls")) {
  document.body.insertAdjacentHTML("beforeend", focusControlsMarkup);
}


/**
 * Open the focus map on the page.
 *
 * `ctx` carries the run and the sample it is measuring, the stage picture it
 * draws on, the backend that does the measuring, and the page's plumbing.
 */
export function openTheFocusMap(ctx: FocusMapContext): FocusMapHandle {
  const {
    run, backend, stage, el, css, sizeCanvas, step,
    focusControls, renderActionBar, tileChosen, edited, runTheMap,
  } = ctx;

/* The controls' markup is put into the page as this module loads, so every
   id asked for below is there; these say what kind of element each one is. */
const theElement = (id: string) => el(id)!;
const theInput = (id: string) => el(id) as HTMLInputElement;
const theButton = (id: string) => el(id) as HTMLButtonElement;
const theCanvas = (id: string) => el(id) as HTMLCanvasElement & { cssW?: number; cssH?: number };

const carrierSpan = () => carrierWidget.extentUm(run.carrier);

/* The surface the stage is driven to: the one fitted through the points
   measured in this session, and nothing else. The parked strategies (see
   `newFocus` in the run document) once answered here with a demonstration
   height and two invented earlier runs, and a protocol naming one of them
   sent the stage there; they give no surface now, so a step that drives
   to the map's height stands where the objective is instead. */
function focusSurface(): Surface | null {
  const f = run.focus;
  return f.strategy === "plane" ? f.surface : null;
}

/* Fitting the focus surface — which model the geometry buys, the fit, the
   height it predicts anywhere, and the residuals — lives in `surface.ts`
   beside this file, imported above. */

// viridis — multi-hue but monotone in lightness, which is the property that
// matters: it stays readable in greyscale and for every kind of colour vision
const VIRIDIS = [
  [68, 1, 84], [72, 36, 117], [65, 68, 135], [53, 95, 141], [42, 120, 142],
  [33, 145, 140], [34, 168, 132], [68, 190, 112], [122, 209, 81], [189, 223, 38], [253, 231, 37],
];

function viridis(t: number): [number, number, number] {
  const u = Math.max(0, Math.min(0.99999, t)) * (VIRIDIS.length - 1);
  const i = Math.floor(u), f = u - i;
  const a = VIRIDIS[i], b = VIRIDIS[i + 1];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

const zColor = (t: number) => { const c = viridis(t); return `rgb(${c[0]},${c[1]},${c[2]})`; };

/* The surface is continuous, so it is painted as a continuous field: one
   small offscreen buffer sampled across the sample bounds, then scaled up
   with smoothing. Nothing about z is per-tile — only the positions are. */
/* Its own camera. Sharing one with the canvas was tempting, but the two
   panels are different sizes, so a fit computed against one of them puts
   the sample off the edge of the other and clicks land nowhere. */

/** The plate, in the frame the plan is written in. */
function carrierBox(): Bounds {
  const [w, h] = carrierSpan();
  return { xMin: 0, yMin: 0, xMax: w, yMax: h };
}

/** The measured surface's z at a place — in the frame the stage drives in —
    or null while there is no surface to read. What the scan and the targets
    drive each position to. Named for z rather than "height", which on a
    screen reads as y. */
function surfaceZAt(x: number, y: number): number | null {
  const surf = focusSurface();
  return surf ? surfaceZ(surf, x, y) : null;
}

/* How far the positions themselves reach — the plate while there are none. */
function planBox(): Bounds {
  if (!run.plan.length) return carrierBox();
  let xMin = Infinity, yMin = Infinity, xMax = -Infinity, yMax = -Infinity;
  for (const t of run.plan) {
    const half = t.frameUm / 2;
    xMin = Math.min(xMin, t.x - half); xMax = Math.max(xMax, t.x + half);
    yMin = Math.min(yMin, t.y - half); yMax = Math.max(yMax, t.y + half);
  }
  return { xMin, yMin, xMax, yMax };
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
 * `shared/scanfields.ts`: the field is cut into as many equal blocks as points
 * were asked for, and the position nearest the middle of each is taken.
 */
const inScanOrder = (tiles: PlanTile[]) => [...tiles].sort((a, b) => (a.y - b.y) || (a.x - b.x));

/** The positions of each scan field, in scan order, fields with any tiles. */
/* The plan, in tilesets. Which positions make a tileset is the plan's own
   answer — a drawn one is a tileset, and the positions a grid laid in one
   area are that area's — because counting per field would be counting per
   frame, and a point asked for per tileset would land in every frame of the
   plate. */
function tilesByField() {
  const byTileset = new Map<string | number | undefined, PlanTile[]>();
  for (const t of run.plan) {
    const key = t.tileset ?? t.fieldId;
    if (!byTileset.has(key)) byTileset.set(key, []);
    byTileset.get(key)!.push(t); // set just above when it was missing
  }
  return [...byTileset.values()].map(inScanOrder);
}

const perField = (f: FocusMap) => Math.max(1, Math.round(f.perField) || 1);
const perCarrier = (f: FocusMap) => Math.max(1, Math.round(f.perCarrier) || 1);

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
function patternFocusPoints(over: "tileset" | "carrier" = "tileset") {
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
  return groups.flatMap((held, order) =>
    sharePoints(held, n, { vary })
      /* Which tileset laid a point rides along: the visiting order drains
         one tileset before the next, and this is how it knows them. */
      .map((t) => ({ x: t.x, y: t.y, z: null, tileset: order })));
}

/* The position under the pointer, if it is over one. A list of positions has
   no rows and columns to index into, so it is asked by distance. */
function nearestPosition(x: number, y: number): Nearest | null {
  let best: Nearest | null = null;
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

function paintSurface(surf: Surface, scale: ReturnType<typeof zColourScale>, box: Bounds) {
  const fctx = fieldCv.getContext("2d")!;
  const img = fctx.createImageData(FIELD_W, FIELD_H);
  let k = 0;
  for (let j = 0; j < FIELD_H; j++) {
    const y = box.yMin + ((j + 0.5) / FIELD_H) * (box.yMax - box.yMin);
    for (let i = 0; i < FIELD_W; i++) {
      const x = box.xMin + ((i + 0.5) / FIELD_W) * (box.xMax - box.xMin);
      const c = viridis(scale.t(surfaceZ(surf, x, y)));
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
function drawFocusLayer(
  ctx: CanvasRenderingContext2D, toScreen: (x: number, y: number) => [number, number],
  scale: number, w: number, h: number,
) {
  const f = run.focus;
  const surf = focusSurface();
  const showSurface = surf && (f.strategy !== "plane" || f.applied);

  // predicted z range across the sample, for the ramp and its legend
  /* How many of the plan's positions have an image in them by now. */
  const imaged = Math.max(run.tilesShown, 0);

  const box = planBox();
  let colours: ReturnType<typeof zColourScale> | null = null;
  if (showSurface) {
    // a spline can bulge between its points, so sample the field rather than
    // trusting the corners the way a plane would let you
    const sampled: number[] = [];
    for (let j = 0; j <= 12; j++) {
      for (let i = 0; i <= 16; i++) {
        sampled.push(surfaceZ(surf,
          box.xMin + (i / 16) * (box.xMax - box.xMin),
          box.yMin + (j / 12) * (box.yMax - box.yMin)));
      }
    }
    colours = zColourScale(sampled, run.focus.points.map((p) => p.z));
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
    paintSurface(surf, colours!, planBox()); // measured whenever the surface is shown
    ctx.save();
    ctx.beginPath();
    run.plan.forEach((t, i) => {
      if (i < imaged) return;
      const [tx, ty] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      const sz = t.frameUm * scale;
      ctx.rect(tx, ty, sz, sz);
    });
    ctx.clip();
    /* Translucent so the focus stacks under it show through. */
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
      ? zColor(colours!.t(surfaceZ(surf, t.x, t.y))) // measured whenever the surface is shown
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

  // ---- ramp legend
  /* Not painted here any more: the canvas keeps a row of its own for a
     legend, at the top right, so the map hands over what its colours mean
     and the row shows it in the page's own type. */
  if (!showSurface) return null;
  /* Measured above whenever the surface is shown. */
  const shownColours = colours!;
  return {
    title: "relative z-depth",
    lo: `${shownColours.min.toFixed(1)}`,
    hi: `${shownColours.max.toFixed(1)} µm`,
    ramp: zRampCss(shownColours.t(shownColours.min), shownColours.t(shownColours.max)),
  };
}

/** The slice of the colour ramp between two places on it, as a CSS
    gradient for the legend: the colours the map actually reaches. */
function zRampCss(from = 0, to = 1) {
  const stops = [];
  for (let i = 0; i <= 16; i++) {
    stops.push(`${zColor(from + (to - from) * (i / 16))} ${(i / 16 * 100).toFixed(1)}%`);
  }
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

/**
 * The focus points alone, drawn above the plan.
 *
 * Split from the map on the note the map itself carried: drawn as one
 * layer, being early enough to keep the scan fields readable also meant
 * the plan's grid painted over the very reticles the operator was
 * placing. The map stays early and fades with the drawing it colours;
 * these stand above the plan and stay solid through the shared fade.
 */
function drawFocusPoints(ctx: CanvasRenderingContext2D, toScreen: (x: number, y: number) => [number, number]) {
  const f = run.focus;
  /* ---- focus points, as a reticle rather than a dot.
     Open in the middle, because the middle is the thing being pointed at:
     a filled marker hides the one pixel of the map it is about. The height
     is not written beside it either — the map says it in colour and the list
     says it in numbers, and a label per point tiles over the field it is
     annotating once there are more than a handful. */
  if (f.strategy === "plane") {
    const R = 4.5, ARM_IN = 6.5, ARM_OUT = 11;
    const reticle = (x: number, y: number) => {
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
      if (lit) {
        /* A thin black rim between halo and red, so the chosen point is
           picked out by an edge as well as by weight. */
        reticle(x, y);
        ctx.lineWidth = 5;
        ctx.strokeStyle = "rgba(15, 23, 42, 0.9)";
        ctx.stroke();
      }
      reticle(x, y);
      ctx.lineWidth = lit ? 4 : 1.9;
      ctx.strokeStyle = css(lit ? "--mark-focus-lit" : "--mark-focus");
      ctx.stroke();
      ctx.lineCap = "butt";
    });
  }
}

/* A focus point being dragged: which one, and whether the pointer has
   actually moved since it was taken hold of. A press that never moves is
   still a press, and means the other thing — take this point away. */
let focusDrag: FocusDrag | null = null;

/* Shift and drag over the map picks out the points the rectangle covers, the
   same gesture that picks tilesets a step earlier. Held in screen pixels
   while it is being drawn, because that is where the rectangle is. */
let focusMarquee: Marquee | null = null;

/** How small a rectangle is too small to have been meant — a shifted press. */
const MARQUEE_MIN_PX = 4;

/** Which points the picked set holds, kept as a set of places, not indexes. */
const picked = () => run.focus.picked ?? (run.focus.picked = new Set());

/** Where the pointer is, in the carrier's own coordinates. */
function pointerInCarrier(px: number, py: number): [number, number] {
  const [wx, wy] = stage.toWorld(px, py);
  const [ox, oy] = stage.carrierOriginUm();
  return [wx - ox, wy - oy];
}

/* How near a press has to be to take hold of a point: a few pixels, measured
   in what the picture is showing rather than in micrometres, so it is the
   same reach whatever the zoom. */
const POINT_REACH_PX = 10;

/** The focus point under the pointer, if the map is open to being changed. */
function focusPointAt(px: number, py: number): number {
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
function focusGrabbed(e: { offsetX: number; offsetY: number; shiftKey: boolean }): boolean {
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
function focusMarqueeTo(px: number, py: number): void {
  const [x, y] = pointerInCarrier(px, py);
  // asked only while a rectangle is being drawn
  focusMarquee = { ...focusMarquee!, cx: x, cy: y };
  stage.draw();
}

/* What the rectangle covered. A rectangle too small to have been meant is a
   shifted press that was about to add to what is held, so it leaves the set
   alone rather than emptying it. */
function focusMarqueeTook(shift: boolean): void {
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
function focusDraggedTo(px: number, py: number): void {
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
       at all until the map is measured again.

       What it was is kept with it, so the move can be taken back: Rerun reads
       the point where it now stands, and Reset puts it where its reading was.
       Kept from the first move only — dragging a point about three times
       still undoes to the place it was measured, not to the last place it
       was dropped. */
    f.points[i] = {
      ...p, x: from.x + dx, y: from.y + dy,
      z: null, residual: null, stale: p.z !== null || !!p.stale,
      wasRead: p.wasRead ?? (p.z !== null ? {
        x: p.x, y: p.y, z: p.z, zAuto: p.zAuto, traces: p.traces,
        manual: !!p.manual, onNarrow: !!p.onNarrow,
        lost: !!p.lost, speck: p.speck,
      } : undefined),
    };
  }
  refitSurface();
  /* The plot too. A moved point has no curve -- what was read for it was
     read where it used to be -- and the row said so while the plot went on
     showing the old one. */
  stage.draw(); renderPointList(); drawTrace();
}

/**
 * What the pointer says on the focus step. Answered here rather than at the
 * moment of the press, so a crosshair armed from the panel says so before the
 * mouse is moved to find out — and so the one place that sets the canvas
 * cursor keeps setting it. The drawing calls this; nothing else assigns it.
 */
function focusCursor(): string {
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
function focusHovered(e: { offsetX: number; offsetY: number }): boolean {
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
/* Which tileset's leg of the route a place belongs to: the one whose
   frames it sits inside. Geometry answers, not how the point came to be --
   a point put down by hand inside a tileset marches with that tileset, and
   one dragged into another changes legs. Outside every tileset, it joins
   the tail the route walks last. */
function tilesetAt(x: number, y: number): number | undefined {
  const drawn = tilesByField();
  for (let order = 0; order < drawn.length; order++) {
    for (const t of drawn[order]) {
      const half = t.frameUm / 2;
      if (x >= t.x - half && x <= t.x + half
        && y >= t.y - half && y <= t.y + half) return order;
    }
  }
  return undefined;
}

/* The route is settled the moment the map changes: a point added or moved
   slots into its place in the itinerary at once, so the number a row shows
   is always the point's place on the route the stage will take -- a corner
   that is the sixth stop says 6, however few of the six are measured yet.
   Selection and holds follow their points through the shuffle. */
function settleTheRoute() {
  const f = run.focus;
  const chosen = f.points[f.selected];
  const holding = [...picked()].map((i) => f.points[i]);
  for (const point of f.points) point.tileset = tilesetAt(point.x, point.y);
  f.points = visitOrder(f.points);
  f.selected = Math.max(0, f.points.indexOf(chosen));
  picked().clear();
  for (const point of holding) {
    const at = f.points.indexOf(point);
    if (at >= 0) picked().add(at);
  }
}

function focusPressed(px: number, py: number): boolean {
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
  edited?.();
  /* The one just put down is the one being worked on: it is what the hand is
     pointing at, and the next thing said — a drag, Delete — is about it
     rather than about whatever was picked before. */
  picked().clear();
  picked().add(f.points.length - 1);
  f.selected = f.points.length - 1;
  settleTheRoute();
  drawTrace();
  stage.draw(); renderPointList(); renderActionBar();
  return true;
}

/* An anchor point lands where the press landed, once the button has armed
   it. Armed rather than always live, for the reason the focus crosshair is:
   the same press pans the picture. */
function anchorPressed(px: number, py: number): boolean {
  if (step(run.activeIdx).mode !== "carrier" || !run.anchoring) return false;
  const [x, y] = pointerInCarrier(px, py);
  run.anchors = [...run.anchors, { x, y }];
  run.anchoring = false;
  stage.draw();
  return true;
}

/* The same press during detection picks the test position: the channel's
   preview is one tile, and pointing at a position on the canvas is how it
   is chosen — the pager beside the preview is the other way. */
function detectPressed(px: number, py: number): boolean {
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
  /* The preview follows the chosen field through the page's own hook: this
     module has no hand on the detection panel. Reaching for it by name
     threw, and the press was lost with the field already changed. */
  tileChosen?.(); stage.draw(); renderActionBar();
  return true;
}

/* Every word written on the plot — what the axis carries, what each curve
   measures — is the same kind of thing said about the same picture, so it is
   one font and one weight rather than a hierarchy invented per label. */
const LEGEND_FONT = "600 11px system-ui, sans-serif";

/* What the box the plot sits in insets its own text by, so the axis title can
   start on the same line the heading above it starts on. */
const BOX_PAD = 14;

/* The two sharpness metrics, every candidate peak in a curve and the one
   worth trusting live in `shared/focus-curves.ts`, imported above. The trace
   below draws exactly the curve the unit tests measure. */

/** How tall another peak has to stand, against the tallest in the sweep,
 *  before it counts as one the rule had to choose between. */
const RIVAL_SHARE = 0.5;

/**
 * What is doubtful about a measured point, said the way an operator would say
 * it. Empty means nothing is.
 *
 * These are the four ways a height can be worth a second look, and they are
 * gathered in one place because the row shows one mark for all of them and
 * has to be able to say which it means. A sweep that found more than one peak
 * is the interesting case: the rule picked the tallest wide one and may well
 * be right, but the operator is the one who gets to decide that, and until
 * they have looked nothing on the row would have told them there was a choice.
 */
function doubtsAbout(point: MapPoint, i: number): string[] {
  const f = run.focus;
  /* A point that has moved since the map was run is not doubtful, it is
     unmeasured: the grey row and the empty plot say so already, and a warning
     on top of them would have the count at the head of the list promising
     something to look at that nobody can look at yet. */
  if (point.stale) return [];
  /* A height the operator set by hand stands: the warnings are about the
     automatic pick, and dragging past it is the look they asked for. */
  if (point.manual) return [];
  const out: string[] = [];
  if (point.lost && point.refused) {
    out.push(`The microscope did not measure this point: ${point.refused}`);
  } else if (point.lost) {
    out.push("The search swept its whole range without finding a peak — no height was measured here.");
  }
  if (point.onNarrow) {
    out.push("The peak it chose is too narrow to be tissue, which is almost always a speck of debris.");
  }
  /* Rivals, not peaks. Every sweep of a noisy signal has small local maxima
     in it, and a shoulder beside the main one is the same tissue seen from
     slightly off; counting those marked every point on the map, which is the
     same as marking none. A rival is a peak that stood high enough to have
     been taken instead and far enough away to be a different thing — which is
     what a speck of debris looks like, and what an operator is being asked to
     look at. */
  const cands = sweepShown(point)?.[f.metric]?.candidates ?? [];
  const tallest = cands.reduce((a, c) => Math.max(a, c.s), 0);
  const rivals = cands.filter((c) =>
    c.s >= RIVAL_SHARE * tallest
    && Math.abs(c.z - (point.zAuto as number)) > MIN_TISSUE_WIDTH_UM).length;
  if (rivals) {
    out.push(rivals === 1
      ? "Another peak in the sweep stood nearly as high, at a different height. The tallest wide one was taken; the plot shows the other."
      : `${rivals} other peaks in the sweep stood nearly as high, at other heights. The tallest wide one was taken; the plot shows them.`);
  }
  if (f.worst === i && Math.abs(point.residual || 0) > 3) {
    // past three µm above, so there is a residual
    out.push(`This height sits ${point.residual!.toFixed(1)} µm off the surface fitted through the others.`);
  }
  return out;
}

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
  const count = theInput("fp-count");
  // never while it is being typed into, or a 1 on its way to 12 is corrected
  if (document.activeElement !== count) count.value = String(perField(f));
  const countAll = theInput("fp-count-all");
  if (document.activeElement !== countAll) countAll.value = String(perCarrier(f));
  count.disabled = frozen;

  /* Only once there is a map to act on. Rerun measures points that are
     already down; Reset throws away what a run produced. */
  const ran = f.strategy === "plane" && f.applied && f.points.length > 0;
  /* And nothing lays a fresh set over a map that has been measured. The points
     and the surface fitted through them are one answer: laying new ones would
     leave the traces below describing points that are no longer there, and the
     box quietly offering a sweep for each of them. Reset is the way back, and
     it is the press beside them. */
  for (const id of ["fp-place", "fp-place-all", "fp-count", "fp-count-all"]) {
    (el(id) as HTMLButtonElement | HTMLInputElement).disabled = frozen || !run.plan.length || ran;
  }
  /* Never greyed while a hand could mean it -- the presses under the plot
     follow the same rule. With nothing to clear it simply clears nothing. */
  theButton("fp-clear").disabled = frozen || !!run.running;
  /* One slot for the one act: the step's own press makes the map, and
     Rerun takes the cell once there is one to measure again — the two were
     briefly on screen together, both meaning measure it. */
  focusControls.querySelector<HTMLElement>(".focus-action")!.hidden = ran;
  theElement("fp-rerun").hidden = !ran;
  /* While a run is out, the Rerun cell is the brake — one press, one place,
     whichever press started the run. The backend stops between two points,
     and what was measured stands. */
  theElement("fp-rerun").textContent = run.running ? "Interrupt" : "Rerun";
  theButton("fp-rerun").disabled = run.running ? false : !ran;
  theButton("fp-runnew").disabled = frozen || !ran || !!run.running;
  /* The traces are what the run came back with, so the box that reads them
     is not there until it has. What the map came to is in the rows: a height
     for every point and how far each sits from the surface. */
  theElement("focus-traces").hidden = !f.applied;

  const pick = theButton("fp-pick");
  pick.disabled = frozen || !run.plan.length;
  pick.classList.toggle("on", !!f.placing && !frozen);
  /* One of the two is always on, so a press on the map is never a question:
     the crosshair puts a point down, and the arrow picks one that is. */
  const select = theButton("fp-select");
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
  const host = theElement("point-list");
  host.textContent = "";
  /* Cleared before anything is drawn, so a count never outlives the list it
     was counted from — every way out of this function below leaves it as it
     is found here. */
  const warned = theElement("fp-warned");
  warned.textContent = "";
  renderFocusBar();

  if (f.strategy !== "plane") {
    const d = document.createElement("div");
    d.className = "none";
    d.textContent = f.strategy === "auto"
      ? "Per-tile autofocus measures every position — no points to place."
      : "This strategy is not available yet; only a measured focus map is.";
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

  let doubtful = 0;
  let listed = 0;
  f.points.forEach((p, i) => {
    /* The list is the run's own account, and it grows with the acquisitions:
       a row appears the moment the stage sets off to measure its point, and
       fills in when the reading lands. A point laid and never visited lives
       on the canvas -- placed, dragged and thrown away there -- and has
       nothing to report here yet. */
    const visited = p.z !== null || p.lost === true || !!p.traces || p.stale;
    if (!visited && !(run.running && i === f.selected)) return;
    listed++;

    /* A row, not a button: it holds one — the row itself picks the point —
       and a cross of its own for throwing it away. A button inside a button
       is not a thing a browser will draw. */
    const row = document.createElement("div");
    row.className = p.stale ? "point-row stale" : "point-row";
    /* Held, or the one whose trace is charted: the list marks what the
       canvas marks, so a rectangle drawn over the map is answered here. */
    row.setAttribute("aria-current",
      String(picked().has(i) || (!picked().size && i === f.selected)));
    const doubts = doubtsAbout(p, i);
    const suspect = doubts.length > 0;
    if (suspect) doubtful++;
    const pick = document.createElement("button");
    pick.className = "point-pick"; pick.type = "button";
    pick.innerHTML =
      `<span class="idx">${i + 1}</span>` +
      `<span>${(p.x / 1000).toFixed(2)}, ${(p.y / 1000).toFixed(2)} mm</span>` +
      (suspect ? `<span class="warn" title="${doubts.join("&#10;")}">⚠</span>` : "") +
      `<span class="z${p.z === null ? " pending" : ""}"` +
      `${suspect && !p.manual ? ' style="color:var(--warn-ink)"' : ""}>` +
      `${p.z === null ? "—" : p.z.toFixed(1) + " µm"}</span>`;
    /* A moved point can still be picked. What was read for it was read of
       where it used to be, so there is no sweep to show and the plot below
       says exactly that — but which point the map is marking is the row's
       other job, and an unpressable row cannot do it. */
    pick.addEventListener("click", () => {
      /* Picking a row picks the point, on the map as well as in the list.
         Charting it and selecting it were two different things, so a row
         pressed while something else was held on the canvas charted one point
         and left the other one lit. One press, one selection. */
      f.selected = i;
      picked().clear();
      picked().add(i);
      renderPointList(); drawTrace(); stage.draw(); renderActionBar();
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
      edited?.();
      renderPointList(); drawTrace(); stage.draw(); renderActionBar();
    });

    row.append(pick, drop);
    host.append(row);
  });

  if (!listed) {
    const d = document.createElement("div");
    d.className = "none";
    d.textContent = "Rows appear here as the run measures its points.";
    host.append(d);
  }

  /* Said once at the top, because the list scrolls: four rows are on screen
     and a mark on the fifth is a mark nobody sees. The number is how many
     rows carry a warning, not how many things are wrong with them. */
  warned.textContent = doubtful
    ? `${doubtful} warning${doubtful === 1 ? "" : "s"}`
    : "";
}

/**
 * The point the plot is showing, when it has a reading to act on.
 *
 * Not the same thing as `f.points[f.selected]`: a point that has moved since
 * the map was measured is selected, and drawn as selected, with no height and
 * no curve. Rerun and Reset take
 * the selected point itself, because giving a moved point a reading back is
 * exactly what those two are for.
 */
function pointOnShow() {
  const f = run.focus;
  if (f.strategy !== "plane" || !f.applied) return null;
  const p = f.points[f.selected];
  return p && !p.stale && p.z !== null ? p : null;
}

/** The selected point, read or not: what Rerun measures and what Reset
 *  puts back. */
function pointToRerun() {
  const f = run.focus;
  if (f.strategy !== "plane" || !f.applied) return null;
  return f.points[f.selected] ?? null;
}

/* The three presses under the plot are never greyed. Working out which of
   them has something to do meant working out, on every redraw, what each of
   them would do — and a press that goes grey the moment the height is dragged
   back to where it started is a press that argues with the hand on the
   slider. Each does nothing when there is nothing to do, which is what a
   press for one point should do anyway. */

/* One point put back. Two things to undo, and the point says which one it
   is. Carried somewhere else on the map, it goes back to where its reading
   was taken and the reading comes back with it — position, height, and the
   sweep the plot draws. Standing where it was measured, only the height
   moved, so only the height goes back: to what the instrument answered, and
   no longer answered for, since a point put back is a point nobody has
   looked at yet. */
function putBack(point: MapPoint) {
  const f = run.focus;
  if (point.stale && point.wasRead) {
    const { wasRead, ...rest } = point;
    f.points[f.points.indexOf(point)] = { ...rest, ...wasRead, stale: false };
    return;
  }
  if (point.zAuto === undefined) return;
  point.z = point.zAuto;
  point.manual = false;
}

const afterPuttingBack = () => {
  refitSurface();
  renderPointList(); drawTrace(); stage.draw();
};

theElement("ft-reset").addEventListener("click", () => {
  if (run.running) return;
  const p = pointToRerun() ?? pointOnShow();
  if (!p) return;
  putBack(p);
  afterPuttingBack();
});

/* Every point at once: the whole map back to what the instrument
   answered, for an operator who dragged a few heights to see and wants the
   measured map back without finding each one. */
theElement("ft-reset-all").addEventListener("click", () => {
  if (run.running) return;
  for (const p of [...run.focus.points]) putBack(p);
  afterPuttingBack();
});

theElement("ft-rerun").addEventListener("click", (e) => {
  const f = run.focus;
  const p = pointToRerun();
  if (!p || run.running) return;
  const at = f.points.indexOf(p);
  const button = e.currentTarget as HTMLElement;
  /* The step run again on one point: the runner holds the page while the
     stage is out, so the press shows it is doing something and cannot be
     pressed again under a run of its own. It did neither once: a rerun of
     one point looked, for its whole length, like a button nobody pressed. */
  runTheMap(async () => {
    button.classList.add("on");
    try {
      await rerunOne(f, at, p);
    } finally {
      button.classList.remove("on");
    }
    refitSurface();
    renderPointList(); drawTrace(); stage.draw(); renderActionBar();
  });
});

async function rerunOne(f: FocusMap, at: number, p: MapPoint): Promise<void> {
  const startZ = stage.whereTheStageIs()?.z;
  /* Asked as a point nobody has touched. A backend keeps a height the operator
     moved by hand — that is what makes a hand-set height survive a change of
     metric — and here that would have the rerun hand back the very height it
     was asked to go and measure again. */
  const asked = { ...p, manual: false };
  if (Number.isFinite(startZ)) asked.startZ = startZ;
  /* One point measured on its own, through the same verb the whole map goes
     through — a backend that drives to a list of positions is given a list of
     one. What comes back replaces that point and nothing else, and it comes
     back unanswered: a fresh reading is not one anybody has looked at. */
  const { points } = await backend.measureFocus([stage.toStage(asked)], {
    metric: f.metric,
    extent: carrierSpan(),
    state: activeRecording(run.focusPreset)?.changeable ?? null,
  });
  const [got] = points;
  if (got) {
    /* And no longer moved-since-measured: what was just read was read where
       the point is standing now, which is the whole of what `stale` meant. */
    const { wasRead, ...came } = stage.toCarrier(got);
    f.points[at] = settled({ ...came, stale: false, manual: false });
  }
}

/* The run's progress, straight under the focussing configuration while a
   run is on: the same box the scan and the acquisition have, but put away
   when the run ends -- the map and its results are the whole answer, and a
   finished bar between the configuration and the presses was a thing to
   read past every time. */
const focusProgress = progressBox("Focus progress");
focusProgress.doing.id = "focus-doing";
focusProgress.count.id = "focus-count";
theElement("focus-controls").prepend(focusProgress.group);

const traceCv = theCanvas("trace-canvas");

/* ---- the slice at whatever height the line is sitting on ---------------
   The real captured plane nearest the black line, so a peak the metric
   loved can be seen to be a speck rather than trusted not to be. The
   backend serves the copies and the point names them; a backend that
   names none simply keeps the box hidden. */
const sliceBox = theElement("zpreview");
const sliceFailure = document.createElement("p");
sliceFailure.setAttribute("role", "status");
sliceFailure.textContent = "Focus preview unavailable.";
sliceFailure.hidden = true;
sliceBox.before(sliceFailure);
const sliceCv = theCanvas("zpreview-canvas");
const orthoCv = theCanvas("zortho-canvas");
const sliceImages = new Map<string, Fetched>();
let sliceShown: string | null = null;
window.__theSliceShown = () => sliceShown;

/* One fetch per slice, whoever asks: the picture wants the slice on show,
   the side view wants every slice once. `crossOrigin` because the side view
   is read back by the tests, and a canvas that drew a cross-origin picture
   without it refuses to be read at all. */
function sliceImage(src: string, ready: (img: HTMLImageElement | null) => void) {
  let held = sliceImages.get(src);
  if (!held) {
    const fresh: Fetched = { img: new Image(), waiting: [] };
    held = fresh;
    fresh.img.crossOrigin = "anonymous";
    fresh.img.onload = () => {
      const call = fresh.waiting;
      fresh.waiting = [];
      for (const tell of call) tell(fresh.img);
    };
    fresh.img.onerror = () => {
      fresh.failed = true;
      const call = fresh.waiting;
      fresh.waiting = [];
      for (const tell of call) tell(null);
    };
    fresh.img.src = src;
    sliceImages.set(src, fresh);
  }
  if (held.failed) ready(null);
  else if (held.img.complete && held.img.naturalWidth) ready(held.img);
  else held.waiting.push(ready);
}

/* ---- the stack seen from the side --------------------------------------
   One column per height: the middle column of each slice, left to right up
   the stack, the same direction the plot's axis runs. Built once per stack
   as its slices arrive, and repainted with the marker on every scrub. */
let orthoOf: Slice[] | null = null;      // the slices array the buffer was built from
let orthoBuffer: HTMLCanvasElement | null = null;  // one column per slice, at the slices' own pixels
let orthoAt = -1;        // which column the black line stands on
let orthoFrom: { at: string; slices: Slice[] } | null = null;    // where the columns come from, so a moved cut can re-cut

function buildOrtho(at: string, slices: Slice[]) {
  orthoOf = slices;
  orthoFrom = { at, slices };
  orthoBuffer = null;
  const cut = orthoCut;
  slices.forEach((entry, index) => sliceImage(`${at}/${entry.name}`, (img) => {
    if (!img) return;
    if (orthoOf !== slices || cut !== orthoCut) return;
    if (!orthoBuffer) {
      orthoBuffer = document.createElement("canvas");
      orthoBuffer.width = img.naturalWidth;
      orthoBuffer.height = slices.length;
    }
    const g = orthoBuffer.getContext("2d")!;
    const row = Math.min(img.naturalHeight - 1, Math.floor(img.naturalHeight * orthoCut));
    /* Side-on, zx: the cut row of each slice becomes one row here, highest
       height at the top, so up in the picture is up on the instrument and
       left stays left. */
    g.drawImage(img, 0, row, img.naturalWidth, 1,
      0, slices.length - 1 - index, orthoBuffer.width, 1);
    drawOrtho();
  }));
}

function drawOrtho() {
  if (!orthoBuffer) return;
  const g = orthoCv.getContext("2d")!;
  g.clearRect(0, 0, orthoCv.width, orthoCv.height);
  g.imageSmoothingEnabled = true;
  g.imageSmoothingQuality = "high";
  g.drawImage(orthoBuffer, 0, 0, orthoCv.width, orthoCv.height);
  if (orthoAt < 0) return;
  /* The chosen height, horizontal: heights run down the picture, so the
     bar rides up and down with the black line in the plot. */
  const y = ((orthoBuffer.height - 1 - orthoAt + 0.5) / orthoBuffer.height) * orthoCv.height;
  g.strokeStyle = css("--bad");
  g.lineWidth = 3;
  g.beginPath();
  g.moveTo(0, y);
  g.lineTo(orthoCv.width, y);
  g.stroke();
}

/* Where the side view cuts through the slice, as a fraction of its height.
   The operator's to drag; it holds across scrubs and stacks, because the
   place worth looking along rarely changes with the height. */
let orthoCut = 0.5;
let sliceOn: HTMLImageElement | null = null;   // the slice image on show, so the cut can repaint it

function paintSlice(img: HTMLImageElement) {
  sliceOn = img;
  const g = sliceCv.getContext("2d")!;
  g.clearRect(0, 0, sliceCv.width, sliceCv.height);
  g.imageSmoothingEnabled = true;
  g.imageSmoothingQuality = "high";
  g.drawImage(img, 0, 0, sliceCv.width, sliceCv.height);
  /* While the slider is held, the cut shows itself: a wide dashed black
     line at the height being chosen, gone when the hand lets go. */
  if (cutting) {
    /* Black and white alternating, so the line reads on bright ground and
       dark alike. */
    const y = orthoCut * sliceCv.height;
    g.save();
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(0, y); g.lineTo(sliceCv.width, y);
    g.setLineDash([10, 10]);
    g.strokeStyle = "#000000";
    g.stroke();
    g.lineDashOffset = 10;
    g.strokeStyle = "#ffffff";
    g.stroke();
    g.restore();
  }
}

/* The slider between the pictures is the cut: slide it and the side view
   is re-cut along that height, live -- the rows come off pictures already
   decoded, so rebuilding is a repaint, not a fetch. */
let cutting = false;
theInput("zcut-slider").addEventListener("input", (e) => {
  orthoCut = Math.max(0, Math.min(1, Number((e.currentTarget as HTMLInputElement).value) / 1000));
  if (sliceOn) paintSlice(sliceOn);
  if (orthoFrom) buildOrtho(orthoFrom.at, orthoFrom.slices);
});
theInput("zcut-slider").addEventListener("pointerdown", () => {
  cutting = true;
  if (sliceOn) paintSlice(sliceOn);
});
for (const done of ["pointerup", "pointercancel"]) {
  theInput("zcut-slider").addEventListener(done, () => {
    cutting = false;
    if (sliceOn) paintSlice(sliceOn);
  });
}

/* The bar on the side view is the same height by another handle. Top of the
   picture is the highest slice, so up on the bar is up on the instrument. */
let barHeld = false;

function barTo(e: PointerEvent) {
  const slices = orthoFrom?.slices;
  if (!slices?.length) return;
  const t = Math.max(0, Math.min(1, e.offsetY / orthoCv.clientHeight));
  const top = slices[slices.length - 1].z_um;
  const bottom = slices[0].z_um;
  chooseHeight(top + t * (bottom - top));
}

orthoCv.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  barHeld = true;
  orthoCv.setPointerCapture(e.pointerId);
  barTo(e);
});
orthoCv.addEventListener("pointermove", (e) => { if (barHeld) barTo(e); });
orthoCv.addEventListener("pointerup", () => { barHeld = false; });

function drawZSlice(point: MapPoint | null) {
  const at = ctx.backend.slicesAt?.();
  /* The slice copies the backend named, as the point carries them. */
  const slices = (point?.slices ?? []) as Slice[];
  // slices are there only when there is a point carrying them
  const show = !!at && slices.length > 0 && point!.z !== null && !point!.stale;
  sliceFailure.hidden = !(at && point?.z != null && !point.stale && !slices.length);
  sliceBox.hidden = !show;
  if (!show) { sliceShown = null; return; }
  /* Shown only for a point with a height. */
  const z = point!.z!;

  let nearest = slices[0];
  for (const s of slices) {
    if (Math.abs(s.z_um - z) < Math.abs(nearest.z_um - z)) nearest = s;
  }
  sliceShown = nearest.name;

  /* Painted when it lands, but only if the line still stands on it: a slow
     fetch must not paint a slice the operator has already scrubbed past. */
  sliceImage(`${at}/${nearest.name}`, (img) => {
    if (sliceShown !== nearest.name) return;
    sliceFailure.hidden = !!img;
    if (img) paintSlice(img);
    else {
      sliceOn = null;
      sliceCv.getContext("2d")!.clearRect(0, 0, sliceCv.width, sliceCv.height);
    }
  });

  if (orthoOf !== slices) buildOrtho(at!, slices); // show, above, holds only when there is one
  orthoAt = slices.indexOf(nearest);
  drawOrtho();
}

/**
 * The curve on screen for a point: what was measured there, or nothing.
 *
 * There used to be a stand-in here — a curve generated from the pretend
 * sample, drawn about the height that had been reported, for backends that
 * gave a height and no curve. Every backend gives a curve now, and a
 * generated one is a picture of the settings rather than a measurement: it
 * cannot show that a peak was a speck of dust, and it looks exactly as
 * convincing when it shows nothing at all. A point with no measurement gets
 * no plot.
 */
function sweepShown(point: MapPoint | null | undefined) {
  const traces = point?.traces ?? null;
  if (!traces) return traces;
  /* The peaks are found here, from the curve, whoever measured it. A backend
     that named its own would be answering a question the operator's rule
     decides -- how wide a peak has to be to be tissue -- and only one backend
     ever did, so the plot worked against the pretend one and crashed on the
     real one. */
  return Object.fromEntries(Object.entries(traces).map(([key, trace]) => [
    key, { ...trace, candidates: findCandidates(trace.samples) },
  ]));
}


function drawTrace() {
  if (!focusMounted()) return;
  const f = run.focus;
  /* Whether there is a sweep to show for the point being read. A point put
     down since the map was run has no reading yet; a point that has moved
     since has one, but of somewhere else. Neither draws: the notice covers
     the plot, so no curve and no marker from the point read before it is
     left standing under an explanation of why there is nothing there. */
  const point = f.points[f.selected];
  const has = f.strategy === "plane" && f.applied
    && f.points.length > f.selected && point?.z !== null && !point?.stale;
  theElement("trace-empty").textContent = point?.stale
    ? "This point has moved since the map was measured. What was read for it was read where it used to be — run the map again to see its sweep."
    : "Run the strategy to measure each point, then its sweep appears here.";
  theElement("trace-empty").classList.toggle("hidden", has);
  /* Which point is being read is said by the list, where the row is marked,
     and by the map, where the mark is drawn heavier. The heading says what
     the box is, once. */
  if (!sizeCanvas(traceCv)) return;
  const ctx = traceCv.getContext("2d")!;
  /* Sized just above, which is what sets them. */
  const w = traceCv.cssW!, h = traceCv.cssH!;
  /* Wiped before deciding whether there is anything to draw. A point that has
     moved has no curve -- what was read for it was read where it used to be
     -- and the message says so; but the curve it had stayed painted under
     the message, because the wipe came after the bail. */
  ctx.clearRect(0, 0, w, h);
  if (!has) { drawZSlice(null); return; }

  // the plot stands on the same white the box does: a tinted panel inside a
  // white card read as a second surface for one of the three parts
  ctx.fillStyle = css("--screen");
  ctx.fillRect(0, 0, w, h);

  /* Both metrics on one plot. They score the same stack on different
     scales, so each is normalised to its own maximum — the shapes are the
     comparison, not the absolute numbers. */
  /* A point measured through the bridge comes back with a height and nothing
     else: the instrument's autofocus reports where it landed, not the curve it
     walked to get there. Rather than leave the box empty, the plot draws a
     stand-in sweep about the height that was reported — the shape a sweep of
     this stack and step would have. It is a picture of the settings and never
     a measurement, and it goes the moment a backend reports a real sweep.

     Nothing on the plot says which it is looking at, by choice: the curve is
     the same either way, and the mark that said so was in the way. Anyone
     reading a screenshot of this has to be told. */
  const traces = sweepShown(f.points[f.selected]);
  if (!traces) return;
  const curves = METRIC_KEYS.map((key) => {
    const sw = traces[key];
    const peak = Math.max(...sw.samples.map((q) => q.s)) || 1;
    return { key, sw, norm: sw.samples.map((q) => ({ z: q.z, s: q.s / peak })) };
  });
  const deciding = curves.find((c) => c.key === f.metric) || curves[0];
  const t = deciding.sw;

  /* The legend is under the plot, on one line, and the foot is deep enough to
     hold it below the heights. Inside the frame it competed with the curve for
     the same space: the metric names at one end, the height of the chosen peak
     at the other, and the peak itself wherever the point happened to sit. */
  /* How far the frame stands off the titles, left and bottom alike. The
     bottom is fixed by where the heights are written and how tall their
     letters are; the left is then whatever puts the same air between the
     turned title and the frame. Measured rather than typed in, because both
     numbers move with the font. */
  ctx.font = LEGEND_FONT;
  const yTitle = ctx.measureText("Focus score");
  const zTitle = ctx.measureText("z-position");
  const titleAscent = yTitle.actualBoundingBoxAscent;
  const titleThick = titleAscent + yTitle.actualBoundingBoxDescent;
  const AXIS_TEXT_DROP = 15;   // baseline of the row of heights, under the frame
  const axisGap = AXIS_TEXT_DROP - zTitle.actualBoundingBoxAscent;
  const P = { l: BOX_PAD + titleThick + axisGap, r: 14, t: 12, b: 48 };
  const legendY = h - 12;
  const zs = t.samples.map((p) => p.z);
  const zLo = Math.min(...zs), zHi = Math.max(...zs);
  const sHi = 1.16;
  /* Inverted on purpose: + stands on the left and - on the right. */
  const X = (z: number) => P.l + ((zHi - z) / (zHi - zLo)) * (w - P.l - P.r);
  const Y = (s: number) => (h - P.b) - (s / sHi) * (h - P.t - P.b);
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
  ctx.fillText(`${zHi.toFixed(0)}`, X(zHi) + 10, h - P.b + AXIS_TEXT_DROP);
  ctx.fillText(`${zLo.toFixed(0)} µm`, X(zLo) - 16, h - P.b + AXIS_TEXT_DROP);
  /* Both titles in the same grey as the heights they label: they say what the
     axis is, which is the quietest thing on the plot, and the curves are what
     is being read. The fill is the one set for the numbers above. */
  /* The axis title starts where the box's column starts, level with the
     heading above the plot: turned, its letters run rightwards from their own
     baseline, so the baseline goes one ascent in from that line. */
  ctx.save();
  ctx.translate(BOX_PAD + titleAscent, (P.t + h - P.b) / 2); ctx.rotate(-Math.PI / 2);
  ctx.font = LEGEND_FONT;
  ctx.fillText("Focus score", 0, 0);
  ctx.restore();

  /* And what the numbers at either end of it are, between them. The axis is
     the one thing on the plot an operator has to be told the units of; the
     heights themselves say µm. */
  ctx.font = LEGEND_FONT;
  ctx.fillText("z-position", (P.l + w - P.r) / 2, h - P.b + AXIS_TEXT_DROP);
  ctx.textAlign = "left";

  // the comparison curve first, so the deciding one reads on top
  legendHits = [];
  let lx = P.l;
  for (const c of curves) {
    const isDeciding = c === deciding;
    ctx.save();
    /* Both curves are drawn solid and at full strength: each is a measurement
       that was actually taken, and fading or dashing one says it is less real
       when all it is is not the one in charge. Which is in charge is said by
       weight, here and in the legend swatch below. */
    ctx.strokeStyle = css(METRICS[c.key].token);
    ctx.lineWidth = isDeciding ? 2.4 : 1.5;
    ctx.beginPath();
    c.norm.forEach((q, i) => { const x = X(q.z), y = Y(q.s); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.restore();

    /* The legend doubles as the control: press a metric to let it decide.
       Both names are written the same — same font, same weight, same ink —
       because they name two measurements of equal standing; which one is
       deciding is said by the weight of its line, here and in the plot. */
    ctx.save();
    ctx.strokeStyle = css(METRICS[c.key].token);
    ctx.lineWidth = isDeciding ? 2.4 : 1.5;
    ctx.beginPath(); ctx.moveTo(lx, legendY - 4); ctx.lineTo(lx + 16, legendY - 4); ctx.stroke();
    ctx.restore();
    /* Both names carry the same weight: which one is deciding is said by its
       line and its ink, and a lighter name reads as a lesser measurement
       rather than as the one not currently in charge. */
    ctx.font = LEGEND_FONT;
    ctx.fillStyle = css("--ink");
    const label = METRICS[c.key].short;
    ctx.fillText(label, lx + 22, legendY);
    const wLab = 22 + ctx.measureText(label).width;
    legendHits.push({ key: c.key, x0: lx - 4, x1: lx + wLab + 4, y0: legendY - 13, y1: legendY + 6 });
    lx += wLab + 18;
  }


  // everything below is drawn against the deciding curve, so its raw scores
  // are normalised the same way the curve was
  const N = (s: number) => s / decidingPeak;
  const p = f.points[f.selected];
  // candidates are recomputed from the recorded curve, so the one at the
  // recorded height is the same peak the rule picked when the strategy ran
  const chosen = t.candidates.find((c) => Math.abs(c.z - (p.zAuto as number)) < 1e-6) || t.candidates[0];

  /* The peaks the rule turned down are not ringed. Every bump in the curve is
     drawn already, and a narrow one — almost always a speck of debris — is
     what the warning on the point's row above is about. The plot is the
     shape; the list is the verdict on it. */

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
  }

  // the draggable height
  const zSel = p.z!; // has, above, holds only for a point with a height
  const xSel = X(zSel);
  /* The height that will be used, and the thing dragged left and right to
     change it. Red, on Thom's word: since the automatic-focus dashes went,
     red is the colour of the operator's own handles -- this line, and the
     cut's triangle on the picture above. */
  ctx.strokeStyle = css("--bad");
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(xSel, P.t); ctx.lineTo(xSel, h - P.b);
  ctx.stroke();

  // a grab handle, so it reads as draggable
  ctx.fillStyle = css("--bad");
  ctx.beginPath();
  ctx.moveTo(xSel - 5, P.t); ctx.lineTo(xSel + 5, P.t); ctx.lineTo(xSel, P.t + 7);
  ctx.closePath(); ctx.fill();

  /* No bead where the marker crosses the curve. The line already runs through
     that point over the whole plot, so the dot marked a place that was marked;
     what it added was a second thing changing colour under the pointer. */

  /* No number written beside the marker. The height it is standing at is in
     the list above, in the row for this point, where it is read against every
     other point's — printed on the curve as well it moved under the pointer
     while the eye was on the shape. */

  traceGeom = { zLo, zHi, P, w, h, samples: t.samples };
  drawZSlice(p);
}

let traceGeom: TraceGeom | null = null;
let legendHits: LegendHit[] = [];


/* The image at the chosen height is parked. It was a second thing to read
   beside the plot and the plot is what says whether a height is the right
   one; the drawing comes back with the box that shows it. */
/* ---- drag the height, and watch the image follow -----------------------
   The whole reason the preview is here: a peak the metric loved can be a
   speck, and the operator decides by looking rather than by trusting. */
let scrubbing = false;

/* One height, two handles: the plot's line drags it left and right, the
   side view's bar drags it up and down, and both land here. */
function chooseHeight(z: number) {
  const f = run.focus;
  if (f.strategy !== "plane" || !f.applied) return;
  const p = f.points[f.selected];
  /* Nothing is drawn for a moved point, and the geometry left behind belongs
     to whichever point was read before it: a press on the covered plot would
     otherwise set this one's height from another one's axis. */
  if (!p || p.stale) return;
  p.z = z;
  p.manual = Math.abs(p.z - (p.zAuto as number)) > 0.05;
  refitSurface();
  drawTrace(); renderPointList(); stage.draw();
}

function scrubTo(clientOffsetX: number) {
  if (!traceGeom) return;
  const { zLo, zHi, P, w } = traceGeom;
  const t = Math.max(0, Math.min(1, (clientOffsetX - P.l) / (w - P.l - P.r)));
  chooseHeight(zHi - t * (zHi - zLo));
}

traceCv.addEventListener("pointerdown", (e) => {
  const f = run.focus;
  if (f.strategy !== "plane" || !f.applied) return;
  if (f.points[f.selected]?.stale) return;
  /* A press here drags a height; it does not need to take focus to do it, and
     taking it drew a ring around the whole plot for the length of the drag.
     Reaching the plot by keyboard still focuses it, and still shows the ring,
     which is who the ring is for. */
  e.preventDefault();
  // the legend is the metric control — no separate row of buttons for it
  const hit = legendHits.find((g) =>
    e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
  if (hit) {
    if (hit.key !== f.metric) {
      /* The curves for every metric are already in hand -- the backend sends
         them all -- so choosing one is a re-reading, never a re-drive: a
         legend click used to send the stage through the whole map again. */
      f.metric = hit.key;
      f.points = f.points.map((p) => settled(p));
      refitSurface();
      edited?.();
      drawTrace(); renderPointList(); stage.draw(); renderActionBar();
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
  // left is + now, so the arrows follow the eye rather than the number
  const nudge = ({ ArrowLeft: 0.5, ArrowRight: -0.5, PageDown: -3, PageUp: 3 } as Record<string, number | undefined>)[e.key];
  if (nudge === undefined) return;
  const p = f.points[f.selected];
  if (!p || p.stale) return;
  e.preventDefault();
  p.z = (p.z as number) + nudge * (e.shiftKey ? 4 : 1);
  p.manual = Math.abs(p.z - (p.zAuto as number)) > 0.05;
  refitSurface();
  drawTrace(); renderPointList(); stage.draw();
});

// ---- laying points by the number, rather than clicking positions one by one
theInput("fp-count-all").addEventListener("input", () => {
  const v = parseInt(theInput("fp-count-all").value, 10);
  if (Number.isNaN(v)) return;
  run.focus.perCarrier = Math.min(99, Math.max(1, v));
  edited?.();
});
theInput("fp-count-all").addEventListener("blur", () => { renderFocusBar(); });
theInput("fp-count").addEventListener("input", () => {
  const v = parseInt(theInput("fp-count").value, 10);
  if (Number.isNaN(v)) return;
  run.focus.perField = Math.min(99, Math.max(1, v));
  edited?.();
  renderFocusBar();
});
theInput("fp-count").addEventListener("blur", () => { renderFocusBar(); });
theButton("fp-pick").addEventListener("click", () => {
  const f = run.focus;
  f.placing = !f.placing;
  renderPointList();
});
theButton("fp-select").addEventListener("click", () => {
  run.focus.placing = false;
  renderPointList();
});
/* A fresh set, not more on top: the points are settled against each other —
   every one stands for its own share of the group — so laying a second set
   through the first would leave neither arrangement true. What is kept by hand
   is kept by not pressing either of these. */
const layPoints = (over: "tileset" | "carrier") => {
  const f = run.focus;
  f.points = visitOrder(patternFocusPoints(over));
  picked().clear();
  f.selected = 0;
  edited?.();
  stage.draw(); renderPointList(); drawTrace(); renderActionBar();
};
theButton("fp-place").addEventListener("click", () => layPoints("tileset"));
theButton("fp-place-all").addEventListener("click", () => layPoints("carrier"));
/* Delete takes away whichever point is chosen — the one the canvas is
   drawing heavier and the list has highlighted. The same key does the same
   thing to a scan field one step earlier, and a map is edited the way a plan
   is. */
window.addEventListener("keydown", (e) => {
  if (step(run.activeIdx).mode !== "focus" || run.running) return;
  if (e.key !== "Delete" && e.key !== "Backspace") return;
  const target = e.target as HTMLElement;
  if (target.tagName === "INPUT" || target.tagName === "SELECT") return;
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
  edited?.();
  stage.draw(); renderPointList(); drawTrace(); renderActionBar();
});

/* One press for the whole way back: the points, and the map measured from
   them if one exists -- Reset said the second half and read as a second
   subject. */
theButton("fp-clear").addEventListener("click", () => {
  if (run.running) return;
  const f = run.focus;
  f.points = [];
  f.surface = null;
  f.residual = 0;
  f.worst = -1;
  f.selected = 0;
  f.applied = false;
  picked().clear();
  edited?.();
  /* The step is not done any more either: with the map thrown away, the
     press at the foot of the panel makes one for the first time again. */
  run.done.delete(step(run.activeIdx).id);
  run.ran.delete(step(run.activeIdx).id);
  stage.draw(); renderPointList(); drawTrace(); renderFocusBar(); renderActionBar();
});

/* Measuring an existing map again. Both presses re-run every point that is
   down; they differ only in where each search begins, which is what `from`
   carries into the backend.

   The map is put away while the objective is out, because what is on screen
   during the run is the old answer and the picture would go on drawing a
   surface the run is in the middle of replacing. */
const runAgain = (from: "stage" | "map", button: HTMLElement) => {
  const f = run.focus;
  if (run.running || !f.applied || !f.points.length) return;
  /* The step run again, through the runner: green when it lands, and the
     steps after it orange, as the step's own press leaves them. */
  runTheMap(async () => {
    interruptAsked = false;
    button.classList.add("on");
    renderFocusBar(); renderActionBar();
    try {
      await remeasure({ from });
    } finally {
      button.classList.remove("on");
      status.quiet();
    }
    f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
    stage.draw(); renderPointList(); drawTrace(); renderFocusBar(); renderActionBar();
  });
};

/* The operator's hand on the brake. One flag, two readers: the backend stops
   its run between two points, and the Run-new-points loop below reads the
   same flag between its own. Whichever press started the run, the Rerun cell
   is where the brake stands while it is out. */
let interruptAsked = false;
const interruptTheRun = () => {
  interruptAsked = true;
  backend.stopFocusMeasure();
  theButton("fp-rerun").disabled = true;
  theButton("fp-rerun").textContent = "stopping…";
};
theButton("fp-rerun").addEventListener("click", (e) => {
  if (run.running) return interruptTheRun();
  runAgain("stage", e.currentTarget as HTMLElement);
});

/* Only the points with no reading: placed since the last run, or moved since
   they were read. The measured ones keep their heights -- this is how a map
   grows without being rebuilt. With nothing new it measures nothing. */
theButton("fp-runnew").addEventListener("click", (e) => {
  const f = run.focus;
  if (run.running) return interruptTheRun();
  if (!f.applied) return;
  /* The batch marches the same way a full run does -- tilesets whole,
     shortest path inside each -- not in the order the points happened to
     be added. The route orders the points; each keeps its own row. */
  const route = new Map(f.points
    .map((point, at): [MapPoint, number] => [point, at])
    .filter(([point]) => point.z === null || point.stale));
  const fresh = visitOrder([...route.keys()])
    .map((point) => ({ point, at: route.get(point)! })); // every point routed is a key
  if (!fresh.length) return;
  const button = e.currentTarget as HTMLElement;
  /* The step run again on the new points, through the runner. */
  runTheMap(async () => {
    interruptAsked = false;
    button.classList.add("on");
    renderFocusBar(); renderActionBar();
    try {
      for (const { point, at } of fresh) {
        /* Between two points, on the operator's say-so: the ones measured
           stand, and the rest are still rows that say they have no reading. */
        if (interruptAsked) break;
        /* The mark and the row lead here too: this is the point being
           measured, so it is the one lit and marked while the stage works. */
        f.selected = at;
        leadTheMarkTo(point);
        stage.draw(); renderPointList(); drawTrace();
        await rerunOne(f, at, point);
        stage.draw(); renderPointList(); drawTrace();
      }
    } finally {
      button.classList.remove("on");
      status.quiet();
    }
    refitSurface();
    f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
    stage.draw(); renderPointList(); drawTrace(); renderFocusBar(); renderActionBar();
  });
});

/* Everything the step has to show for itself, thrown away together: the map,
   the points it was fitted through, and the fact that it was ever run. What is
   left is the step as it stood before anybody pressed anything, which is what
   an operator wants when the answer is wrong in a way no rerun will mend. */
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
/**
 * A measured point as the map keeps it: the height the operator's rule chooses.
 *
 * The backend reports the curves and the tallest peak. The rule -- the tallest
 * peak wide enough to be tissue -- is applied here, to every curve, whoever
 * measured it. Taken from the backend instead, a speck of dust won the point
 * and nothing said so; and the one-point rerun, which had its own copy of the
 * reading, kept doing exactly that after the map had stopped.
 */
/**
 * Put the stage mark on the point the run is driving to, before the stage
 * reports it is there: the mark and the lit row lead the stage rather than
 * trail it.
 *
 * Only the place leads. The height stays the one the instrument last
 * reported, until its next reading replaces the whole mark: a height made
 * up for a place the stage has not reached is the kind that once centred a
 * stack millimetres from focus. Before any reading there is no mark to move.
 */
function leadTheMarkTo(point: XY) {
  const here = stage.whereTheStageIs();
  if (!here) return;
  const going = stage.toStage(point);
  stage.takeThePosition({ x: going.x, y: going.y, z: here.z });
}

function settled(p: MapPoint): MapPoint {
  const curve = p.traces?.[run.focus.metric];
  if (curve?.samples?.length) {
    const chosen = pickPeak(findCandidates(curve.samples));
    if (chosen) return { ...p, z: chosen.z, zAuto: chosen.z, onNarrow: chosen.narrow, lost: false };
    return { ...p, z: null, zAuto: null, lost: true };
  }
  return Number.isFinite(p.zAuto) || !Number.isFinite(p.z) ? p : { ...p, zAuto: p.z };
}

async function remeasure({ from = null }: { from?: "stage" | "map" | null } = {}) {
  const f = run.focus;
  if (!f.points.length) return;
  /* The itinerary is settled before the stage moves: tilesets whole, a
     cheap shortest path over their centres and again inside each -- and the
     list grows in this same order, so reading it top to bottom replays the
     run. The mark and the first row lead the stage from the first drive. */
  settleTheRoute();
  f.selected = 0;
  leadTheMarkTo(f.points[0]);
  renderPointList(); drawTrace(); stage.draw();
  const stageZ = () => stage.whereTheStageIs()?.z;
  const beginsAt = (p: MapPoint) => {
    if (from === "stage") return stageZ();
    if (from === "map") return f.surface ? surfaceZ(f.surface, p.x, p.y) : stageZ();
    return undefined;
  };
  const asked = f.points.map((p) => {
    const startZ = beginsAt(p);
    return Number.isFinite(startZ) ? { ...p, startZ } : p;
  });
  /* Each search begins at the height just found at the point before it, so
     the stack follows the tissue as it tilts across the plate instead of
     every point being taken around one height. Refining is the exception:
     there the map's own prediction at each point is the better guess. A
     point that found nothing hands on the last height that was found. */
  const lastFoundBefore = (index: number) => {
    for (let j = index - 1; j >= 0; j -= 1) {
      const p = f.points[j];
      if (!p.lost && Number.isFinite(p.z)) return p.z;
    }
    return undefined;
  };
  /* A backend that reports a height and nothing else is reporting its
     autofocus's answer, which is what `zAuto` means: the height the instrument
     chose, fixed, against which a height the operator moved is a departure.
     Filled in here so every backend's points have the one shape, rather than
     each reader of them learning to cope with a missing field. */
  /* Points are laid on the carrier; the instrument is driven in its own
     frame. Out through `toStage`, back through `toCarrier` -- see stage.ts. */
  focusProgress.say({ start: true, of: asked.length, doing: "starting the focus run…" });
  const { points, stopped } = await backend.measureFocus(asked.map(stage.toStage), {
    metric: f.metric,
    extent: carrierSpan(),
    beginAt: from === "map" ? undefined : lastFoundBefore,
    /* The status bar and the box read the bridge's own sentence about the run. */
    onDoing: (sentence) => { status.say(sentence); if (sentence) focusProgress.say({ doing: sentence }); },
    /* The recorded focussing configuration, applied once before the run: the
       stack a point captures is whatever this recording says it is. */
    state: activeRecording(run.focusPreset)?.changeable ?? null,
    /* Each point goes onto the map the moment it is measured, and the surface
       is fitted through what is there so far: the operator watches the map
       fill in rather than a spinner, and sees a bad point while the stage is
       still working through the rest. */
    onPoint: (measured, index) => {
      /* A fresh reading is not one anybody has moved: the echo of the
         asked point carries `manual`, and keeping it silenced the dust
         warning on a brand-new height. */
      f.points[index] = settled(stage.toCarrier(
        { ...measured, manual: false, stale: false }));
      /* There is a map from the first point on. `applied` is what opens the
         traces box, draws the surface and puts the heights in the rows; held
         until the run ended, every point that landed stayed hidden and the
         whole map appeared at once. */
      f.applied = true;
      /* The mark and the lit row lead the stage rather than trail it: when
         a measurement lands the run is already off to the next point, so
         the mark jumps there and that row appears -- the last point keeps
         both, and the run ends where the stage ends. */
      const heading = f.points[index + 1];
      if (heading) {
        leadTheMarkTo(heading);
        f.selected = index + 1;
      } else {
        leadTheMarkTo(f.points[index]);
        f.selected = index;
      }
      focusProgress.say({ done: index + 1, of: asked.length });
      refitSurface();
      renderPointList(); renderFocusBar(); drawTrace(); stage.draw();
    },
  });
  focusProgress.say({
    ended: true,
    note: stopped ? "stopped by hand" : `${points.filter((p) => Number.isFinite(p.z_um ?? p.z)).length} of ${asked.length} points measured`,
  });
  focusProgress.group.style.display = "none";
  /* A stopped run keeps the map as it stands: the points that landed are
     already in it, and the ones never reached are still places to measure —
     replacing the list with the short answer dropped them. */
  if (!stopped) {
    f.points = points.map((p) => settled(stage.toCarrier(
      { ...p, accepted: false, manual: false, stale: false })));
  }
  refitSurface();
  return { stopped: !!stopped };
}

function refitSurface() {
  const f = run.focus;
  /* Only the points that came back with a height. A search that swept its
     whole range without ever reaching the tissue has nothing to say about
     where the surface is, and letting it say the height it stopped at would
     tilt the whole map towards a place nobody measured. */
  const found = f.points.filter((p): p is MapPoint & { z: number } => Number.isFinite(p.z));
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
    // both finite: the one just asked, and the worst so far
    if (worst < 0 || Math.abs(p.residual as number) > Math.abs(f.points[worst].residual as number)) worst = i;
  });
  f.worst = worst;
}

  /* What the picture and the page may ask of the focus map. The gestures are
     here because the points are here: a press on the canvas over a point is
     about this step, whoever owns the canvas. */
  return {
    // the layers it draws on the stage: the map early, the points above the plan
    drawFocusLayer, drawFocusPoints,
    // the gestures it owns, and whether one is under way
    focusPressed, focusCursor, focusDraggedTo, focusGrabbed, focusHovered,
    focusMarqueeTo, focusMarqueeTook,
    marqueeing: () => focusMarquee !== null,
    dragging: () => focusDrag !== null,
    endDrag: (): Partial<FocusDrag> => {
      const held = focusDrag;
      focusDrag = null;
      /* A moved point slots into its new place on the route the moment the
         hand lets go, and the rows renumber to match. */
      if (held?.moved) {
        settleTheRoute();
        edited?.();
        stage.draw(); renderPointList(); drawTrace(); renderActionBar();
      }
      return held ?? {};
    },
    /* Two presses that belong to other steps and live here because the
       geometry they need does: placing a carrier anchor, and picking the
       position detection is tried on. They move when that geometry does. */
    anchorPressed, detectPressed,
    // the surface's z at a place, and where a position is
    surfaceZAt, nearestPosition,
    // the channel
    renderFocusBar, renderPointList, drawTrace, refitSurface, remeasure, interruptTheRun,
    mounted: focusMounted,
  };
}
