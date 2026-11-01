/**
 * What a target-acquisition run holds: the workflow's half of the run
 * document.
 *
 * The page keeps one plain object for the whole run, `page.run`. The
 * framework's `run-state.ts` writes the keys every workflow has -- which
 * step is active, which are done, what is running -- and asks the workflow
 * for the rest. This file is the answer for target acquisition: everything
 * the operator settles or measures while driving a microscope, from the
 * session and the carrier to the acquired targets, with the value each has
 * before anything has been done and a comment on what it means.
 *
 * The framework never reads these keys. It cannot: a workflow about
 * e-learning or image analysis would hold none of them, and the framework
 * runs that workflow just the same. Everything here is reached through
 * `page.run` by this workflow's own steps.
 */

import type { Backend, FocusSpot, FoundObject, WrittenProtocol } from "../backend/verbs.ts";
import { DEFAULT_SESSION, type Choice, type Session } from "../microscope/instruments.ts";
import { emptySlot } from "../microscope/recordings.ts";
import type { Anchor } from "./alignment.ts";
import { DEFAULT_CARRIER, type Carrier } from "./carriers.ts";
import type { Gate } from "./gating.ts";
import { targetsDress, tilesDress, type MaskLayer } from "./mask-layers.ts";
import type { Field, XY } from "./scanfields.ts";
import type { TaRun } from "../types.ts";

/** A position of the overview's plan: where, how wide a frame, and which field, tileset, compartment and group it is of. */
export interface PlanTile extends XY {
  frameUm: number;
  fieldId?: string | number;
  tileset: string;
  compartment: number;
  group: number;
}

/** The plan as it was scanned, and which plan index each scanned field was. */
export interface Scanned {
  plan: PlanTile[];
  fields: number[];
}

/** A tile laid round chosen targets: where, how wide, which targets it covers, and which overview tileset they came from. */
export interface TargetTile extends XY {
  id: string;
  targetId: string;
  /** Its place among its target's tiles, and the key it is acquired under: `<targetId>#<tileIndex>`. */
  tileIndex: number;
  key: string;
  frameUm: number;
  covers: string[];
  /** The targets the acquisition has whole once this tile is taken, the tiles before it included. */
  completes: string[];
  overviewTileset?: string | number;
  positionIndex?: number;
}

/** What placing the target tiles came to. */
export interface TilePlan {
  placed: TargetTile[];
  uncovered: string[];
  leftOut: string[];
  notes: string[];
}

/** How a target was focussed before its capture: the settings, the map's height, and the peak its stack found, if it found one. */
export interface TargetFocussing {
  settings: unknown;
  z_map_um: number | null;
  z_peak_um: number | null;
  found: boolean;
}

/** A target tile as it was acquired: where, how wide the capture is, its label and its focussing. */
export interface AcquiredTile extends XY {
  frameUm: number | null;
  label?: string;
  taken: unknown;
  focus: TargetFocussing | null;
  positionIndex: number;
  tile: TargetTile;
}

/** One of the connection's checks: what is asked, and the driver's answer once it has one. */
export interface Check {
  label: string;
  result: string | null;
}

/** A protocol as the Protocol box lists it: written on this machine, or read from a file. */
export interface ListedProtocol extends WrittenProtocol {
  written?: number;
  fromFile?: boolean;
}

/** What a walk of Run protocol came to. */
export interface ProtocolSummary {
  ended: string;
  tiles: number;
  objects: number;
  gated: number;
  targets: number;
  seconds: number;
  stoppedAt: string | null;
  endedAt: number;
}

/** How far a walk of Run protocol has got. */
export interface ProtocolWalk {
  at: number;
  of: number;
  within: { done: number; of: number } | null;
  summary: ProtocolSummary | null;
}

/**
 * The surface fitted through a focus map's heights, as the geometry bought it:
 * one height, a least-squares plane about the points' centre, or a smoothing
 * thin-plate spline in coordinates scaled to order one. `affine` is a surface
 * with no points behind it, its tilt `a` and `b` in µm across `width` and `height`.
 */
export type Surface =
  | { kind: "constant"; model: "constant"; c: number }
  | { kind: "plane"; model: "plane"; x0: number; y0: number; c0: number; c1: number; c2: number }
  | {
    kind: "spline"; model: "spline"; x0: number; y0: number; scale: number;
    pts: { u: number; v: number }[]; w: number[]; a0: number; a1: number; a2: number;
  }
  | { kind: "affine"; model: "affine"; a: number; b: number; c: number; width: number; height: number };

/** A focus point on a map: placed, then measured, and how far the fitted surface misses it. */
export type MapPoint = FocusSpot & {
  residual?: number | null;
  /** Which tileset's leg of the route it marches with; none for a point outside every tileset. */
  tileset?: number;
  /** Whether the peak chosen for it is too narrow to be tissue. */
  onNarrow?: boolean;
  /** What was read for it before it was moved, so the move can be taken back. */
  wasRead?: WasRead;
};

/** A moved point's last reading: where it stood, and what was read there. */
interface WasRead {
  x: number;
  y: number;
  z: number;
  zAuto?: number | null;
  traces?: FocusSpot["traces"];
  manual: boolean;
  onNarrow: boolean;
  lost: boolean;
  speck: unknown;
}

/* The focus strategy is its own little document: which approach, that
   approach's parameters, and whatever it has produced so far.

   Only "plane" can be reached at the moment — the bar that chose between the
   four went, and comes back carrying whichever of them turns out to be
   wanted. The rest are parked rather than deleted: the model is what the step
   is about, and the readiness rules, the drawing and the trace all still ask
   which strategy this is. One row of markup arms them again. */
/* The focus maps a run holds, and which of them is being worked on.
   A map is a named thing the operator makes: where to measure, what was
   measured, and the surface fitted to it. Named on the way in, because a run
   may carry several — one per plate region, one measured before a long
   acquisition and reused after — and a list of unnamed ones is a list
   nobody can choose from. */
export function newFocus() {
  return {
    strategy: "plane",
    metric: "brenner",   // which sharpness score the sweep is scored with
    points: [] as MapPoint[], // picked positions, plane strategy only
    perField: 1,         // how many Place lays in each tileset
    perCarrier: 4,       // and how many it lays over the whole carrier
    selected: 0,         // which point's trace is charted
    picked: new Set<number>(), // which are held, for moving or taking away together
    hovered: -1,         // which one the pointer has found, if any
    placing: false,      // whether the crosshair is armed for a press
    applied: false,
    surface: null as Surface | null, // constant | plane | spline, chosen by geometry
    residual: null as number | null,
    worst: -1,
  };
}

// detection settings live next to the focus strategy: chosen, tried on one
// tile, then applied to the rest
function newDetect() {
  return {
    algo: "fast",  // how objects are found: fast (watershed) | robust (Cellpose)
    channel: 0,      // which colour of the overview is segmented, by its place; the others are measured
    diameter: 30,
    cellprob: 0,
    threshold: 100,  // fast only: a nucleus's mean above background, in counts
    border: 0,       // µm from the field's edge inside which a cell is dropped
    binning: 1,      // segment on a copy this many times smaller each side
    maskShow: "fill", // how the test view wears the masks: fill | line | off
    maskColour: null as string | null, // one colour for every object, or null for each its own
    maskAlpha: 0.65,  // how strongly the masks sit on the image (0..1)
    tile: 0,         // the current field of the plan: framed by Tile, tested
    targetTile: 0,   // the current target tile, on the steps about the targets
    hovered: -1,     // the tile under the pointer, a press from being tested
    tested: false,
    tried: [] as FoundObject[],
  };
}

/** A focus map: where to measure, what was measured, and the surface fitted to it. */
export type FocusMap = ReturnType<typeof newFocus>;

/** The placing levers: the margin, the ceiling per tileset and the stitching overlap, each null when its switch is off, and whether to look for the fewest tiles. */
export interface Placing {
  margin: number | null;
  objectsMax: number | null;
  minimise: boolean;
  overlapMin: number | null;
}

/** The placing levers as a run starts, as `scan-areas.ts` reads them. */
const newPlacing = (): Placing => ({ margin: 1, objectsMax: 50, minimise: true, overlapMin: 0.2 });

/**
 * The workflow's keys of a fresh run, for the backend it will speak to.
 *
 * Every key a step of this workflow ever reads is here, with the value it
 * has before the operator has done anything. The framework lays these beside
 * its own keys when it makes a fresh run (`freshRun` in
 * `framework/window/run-state.ts`), so a step finds both on `page.run`.
 */
export function freshState({ backend }: { backend: Pick<Backend, "viewOf"> }) {
  return {
    session: { ...DEFAULT_SESSION } as Session,
    /* What can be connected to, as the interface lists it (`/api/instruments`),
       grouped for the card: microscopes, each with its drivers. Loaded once
       the backend is known; empty until then. */
    instruments: [] as Choice[],
    overviewPreset: emptySlot("acquisition"),
    focusPreset: emptySlot("autofocus"),
    /* Read from further along the instrument's list than the overview: what
       the targets are taken with is a different setting from what found them,
       and a mock that answered with the same one twice would let a plan that
       never switched objectives look right. */
    targetType: emptySlot("acquisition", 1),
    /* Focussing before each target: off unless the operator asks, and then
       a focussing job of its own, read at the targets' magnification. */
    targetFocusOn: false,
    targetFocus: emptySlot("autofocus", 1),
    /* Added to every target's height on top of where it would be taken. */
    targetZOffsetUm: 0,
    /* How wide each acquired frame is on the sample, from the target
       recording; known once one has been taken or placed. */
    targetFrameUm: null as number | null,
    carrier: { ...DEFAULT_CARRIER } as Carrier,
    /* Points put on the carrier drawing, in the carrier's own coordinates, to
       be driven to on the microscope. Placed the way focus points are: the
       button arms, and the next press on the canvas puts one down. Which one
       is pressed, and which one the pointer rests on in the list. */
    anchors: [] as Anchor[],
    anchoring: false,
    anchorPicked: -1,
    anchorLit: -1,
    /* The anchor being dragged on the picture, or -1 while none is held. */
    anchorHeld: -1,
    /* The scan fields the operator drew, and the plan -- the positions the
       stage will visit -- worked out from them and the active preset. */
    fields: [] as Field[],
    plan: [] as PlanTile[],
    /* The connection checks, one row per question the driver answers. */
    checks: [] as Check[],
    /* The tiles the overview is rehearsed on: plan indices pressed green in
       Step 5. Empty means the whole plan. And how many the box offers to
       pick per tileset, and over the whole carrier. */
    testTiles: new Set<number>(),
    testN: 3,
    testNCarrier: 3,
    /* The plan index under the pointer on the scan step, a press from
       being a test tile; -1 when it is over none. */
    testHovered: -1,
    /* The rectangle a Shift-drag on the scan step is drawing over the plan, in the carrier's frame, with where it started on screen; null while none is. */
    testMarquee: null as { sx: number; sy: number; cx: number; cy: number; screen: { x: number; y: number } } | null,
    /* The protocols this machine has written, listed after connecting; the
       one this run was opened on, or null for a run from scratch; the
       sentence the Protocol box shows about it; and whether the steps after
       the focus map are still waiting to appear from the file. */
    protocols: [] as ListedProtocol[],
    /* How far a walk of Run protocol has got -- which step of how many, and
       that step's own progress -- and what it came to. Whether one is
       walking is the framework's (`run.walk`). */
    protocol: { at: 0, of: 0, within: null, summary: null } as ProtocolWalk,
    protocolChosen: null as string | null,
    protocolNote: "",
    protocolPending: false,
    /* The plan as it was scanned -- the tiles sent, in the order sent -- and
       which plan index each was. Every result is read through this and not
       through `plan`, so a field's picture stays where it was taken when the
       plan is edited afterwards, and a scan of a few tiles numbers its
       fields the way the bridge does: by their place in what was sent. */
    scanned: null as Scanned | null,
    tilesShown: 0,
    focus: newFocus(),
    /* A focus map apiece: the points measured under one focussing preset are
       not the points measured under another, and switching between them is
       switching between two maps rather than editing one. Kept by the
       recording's id, with `focusFor` saying whose map `focus` currently is. */
    focusMaps: {} as Record<string, FocusMap>,
    focusFor: null as string | null,
    detect: newDetect(),
    /* What discovery found, by id, and the label of the field each came
       from, which is where its picture is. */
    cells: new Map<string, FoundObject>(),
    fieldLabels: {} as Record<number, string>,
    /* The fields the run's own discovery has examined: the masks the canvas
       shows are theirs alone, never a tile test's left on disk. */
    examined: new Set<number>(),
    /* The mask layers detection has laid, one per picture it ran on: what
       the masks bar draws and whose dress the canvas wears. */
    masks: [] as MaskLayer[],
    /* Where this backend serves the overview's and the targets' pictures,
       if anywhere. */
    overviewPictures: backend.viewOf?.("overview") ?? null,
    targetPictures: backend.viewOf?.("targets") ?? null,
    cellsShown: false,
    targetsDress: targetsDress(),
    gates: [] as Gate[], // [{fx, fy, vertices: [[x, y], ...]}] — see gating.ts
    /* The selection as it stands: what the gates let through, and once
       Restrict has been pressed, that held under the ceiling. The canvas
       rings it and the targets scan images it. */
    gated: new Set<string>(),
    /* What Restrict kept of it under the ceiling, and the tiles laid round
       those -- the plan the acquisition images. */
    restricted: new Set<string>(),
    targetTiles: [] as TargetTile[],
    tilesDress: tilesDress(),
    /* The placing levers, as scan-areas.js reads them, and what the last
       placing came to. */
    placing: newPlacing(),
    tilePlan: null as TilePlan | null,
    acquired: [] as string[],
    /* The acquired target whose pair the gallery shows, chosen there or on
       the canvas; null until one is acquired. Whether that choice was the
       gallery's own quiet follow rather than the operator's. */
    selectedTarget: null as string | null,
    selectedQuietly: false,
    /* The acquired target under the pointer on the acquisition step: what a
       press would choose, outlined so the hand knows before it presses. */
    hoveredTarget: null as string | null,
    acquiredLabels: {} as Record<string, string | undefined>,
    acquiredTiles: {} as Record<string, AcquiredTile>,
  };
}

/* What survives a disconnect or a change of workflow, of this workflow's
   own keys: who the operator was talking to. Everything else was read off
   the session or made against it, and goes with it. The framework adds the
   keys of its own that survive (`startOver` in `run-state.ts`). */
export const keptAcrossSessions = ["session", "instruments"];

/* The settings a protocol carries, and the results that stand on them. A
   run opened on a protocol starts from these afresh and then fills them from
   the file; what the connection established stays. */
const THE_SETTINGS = [
  "overviewPreset", "focusPreset", "targetType", "targetFocusOn", "targetFocus", "targetZOffsetUm",
  "carrier", "anchors", "fields", "plan", "focus", "focusMaps", "focusFor", "detect",
  "gates", "gated", "placing", "testTiles", "stale", "protocolPending",
];

/**
 * Put the settings back to a fresh session's, before a protocol fills them
 * in or after the operator chose "new" again. The connection and what it
 * settled -- the connect step done, its note -- stay as they are.
 *
 * `stale` is the framework's key, not this workflow's, and is the one
 * exception in the list: the steps settled from a protocol are orange until
 * confirmed, so a fresh start empties it.
 */
export function freshSettings(state: TaRun, backend: Backend): void {
  const fresh: Record<string, unknown> = { ...freshState({ backend }), stale: new Set<string>() };
  const settled = state as unknown as Record<string, unknown>;
  for (const key of THE_SETTINGS) settled[key] = fresh[key];
  state.notes = { connect: state.notes.connect };
  state.done = new Set(state.done.has("connect") ? ["connect"] : []);
  state.ran = new Set(state.ran.has("connect") ? ["connect"] : []);
}

/**
 * This workflow's part of the run as a browser test reads it, through
 * `window.__theRunState()`: a plain copy of the fields a test needs to say
 * why a step did nothing rather than only that it did. The framework adds
 * its own fields (which step is active, which are done, what is running).
 */
export function forTests(state: TaRun) {
  return {
    testTiles: [...state.testTiles], scannedFields: state.scanned?.fields ?? null,
    focus: { strategy: state.focus.strategy, applied: state.focus.applied,
             points: state.focus.points.length, selected: state.focus.selected },
    /* How wide each acquired frame is, so a test can check the ground is
       opened over exactly the frame the recording describes. */
    targetFrameUm: state.targetFrameUm ?? null,
    targetFocusOn: state.targetFocusOn,
    /* What each acquired tile's record said about its focussing, keyed by
       tile, so a test can read which height a target was imaged at and why. */
    acquiredFocus: Object.fromEntries(Object.entries(state.acquiredTiles).map(
      ([key, one]) => [key, one.focus ?? null])),
    /* The chosen acquired tile key, so a test can press on the picture and
       see the choice land. */
    selectedTarget: state.selectedTarget ?? null,
    /* Whether that choice was the gallery's own, following the newest frame
       as a run grows, rather than the operator's. */
    selectedQuietly: state.selectedQuietly === true,
    acquiredTileKeys: [...state.acquired],
    restricted: [...state.restricted],
    targetTiles: state.targetTiles.length,
    targetTilePositions: state.targetTiles.map((tile) => ({
      x: tile.x, y: tile.y, frameUm: tile.frameUm,
      key: tile.key,
      overviewTileset: tile.overviewTileset,
      targetId: tile.targetId ?? tile.id,
      covers: tile.covers ?? [],
    })),
  };
}
