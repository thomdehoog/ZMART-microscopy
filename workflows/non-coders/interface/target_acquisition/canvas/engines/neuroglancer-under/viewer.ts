/**
 * Option A: neuroglancer draws the acquisition in a canvas of its own, and the
 * host places that canvas between its background and annotation layers. Opt-in
 * transparency keeps acquired pixels opaque without background cut-outs.
 *
 * The engine is driven through the ZMART viewer's drawing primitives
 * (`zmart-viewer/drawing/primitives/`), the one way both the viewer's own window
 * and this page steer neuroglancer: making it with its own interface off,
 * keeping its layers in step with a scene, feeding it stores and refreshing
 * them as they are committed, its axes, and its camera in micrometres. A fix
 * there reaches both pages. What stays here is this page's own: how the run's
 * acquisitions become a scene, where the view opens, and the handle the canvas
 * drives (`../../viewer.ts`).
 *
 * Everything around this file — the page, the two gestures in `../gestures.ts`,
 * the carrier outline, the tile rectangles, the measurements — is written
 * against that handle and would work just as well with a different engine
 * underneath. So **please do not import anything from `neuroglancer/unstable/...`
 * anywhere but here and the primitives.** Here it is imported for its types
 * only.
 *
 * Three things this file holds to:
 *
 * 1. **Nothing lives in a module variable.** Everything one viewer knows lives
 *    on its own object, and the engine's own state (its feeding, its memory of
 *    what each layer was told) lives in the primitives' handle, made with the
 *    engine and dropped with it. Two viewers can sit side by side, and closing
 *    one genuinely closes it.
 *
 * 2. **Addresses are passed in, never worked out.** The caller says where the
 *    data is, and an address without a scheme is refused outright rather than
 *    quietly never fetched — which is what neuroglancer does with one, with no
 *    error and no request.
 *
 * 3. **The picture is placed where the store says it is, untouched.** Every
 *    store and published picture says where each level lies by the centre of
 *    its first voxel (OME-NGFF RFC-5), which is what the engine reads, so
 *    nothing is moved here.
 *
 * The host owns the layer stack: application ground, this image, then marks.
 * In transparent 2D mode, authoritative acquired coverage keeps black image
 * pixels opaque while unacquired ground reveals the layer below.
 */

import type { Viewer } from "neuroglancer/unstable/viewer.js";
import type { CoordinateSpace } from "neuroglancer/unstable/coordinate_transform.js";
import type { LayerDataSource } from "neuroglancer/unstable/layer/layer_data_source.js";
import { createViewer, type Engine } from "zmart-viewer/drawing/primitives/viewer.ts";
import { coverageLayerFor, type EngineLayer } from "zmart-viewer/drawing/primitives/description.ts";
import {
  keepSpatialAxes, moveAlong, readTheAxis, startTimeAtTheFirstMoment, type AxisReading,
} from "zmart-viewer/drawing/primitives/axes.ts";
import { captureCamera, restoreCamera, whatIsOnScreen } from "zmart-viewer/drawing/primitives/camera.ts";
import {
  shaderControlsFor as theViewersControls, shaderFor as theViewersProgram,
} from "zmart-viewer/drawing/programs.js";
import { theRangeAStoreHolds } from "../brightness.ts";
// And where to open looking, which the engines disagree about by a factor of
// twenty if left to themselves. See `../opening-view.ts`.
import { theViewThatShowsAllOf, type View } from "../opening-view.ts";
// And which plane of a stack to open on. This engine's own default is the
// middle of the volume, which is the same answer — but agreeing by coincidence
// is not agreeing. See `../planes.ts`.
import { theMiddlePlaneOf } from "../planes.ts";
// And where the specimen sits in the ground the run declared. This engine
// keeps the store to itself, so it is read here the way the window is.
import { whereTheSpecimenIsInThisStore } from "../where-the-specimen-is.ts";

/** A place, in micrometres. */
interface XY {
  x: number;
  y: number;
}

/** A stretch of stored counts. */
interface Span {
  low: number;
  high: number;
}

/** What a published source is a view of: a projection, a stack. */
interface SourceView {
  type?: string;
  method?: string;
  [more: string]: unknown;
}

/** One channel of an acquisition, as the page describes it. */
export interface ChannelSpec {
  name?: string;
  colour?: number[];
  window?: Span | null;
  source?: string;
  sources?: string[];
  coverageSources?: string[];
  sourceDepths?: string[];
  sourceRevisions?: number[];
  sourceGeometryRevisions?: number[];
  view?: SourceView;
  channelIndex?: number;
  localPosition?: number[];
  visible?: boolean;
  weight?: number;
  [more: string]: unknown;
}

/** One acquisition to draw: its address, its name, and, if the page knows them, its channels. */
export interface Acquisition {
  url: string;
  name: string;
  channels?: ChannelSpec[];
  opaque?: boolean;
  [more: string]: unknown;
}

/** One channel as the engine draws it: its stores and its look. */
interface Row {
  url: string;
  sources: string[];
  coverageSources?: string[];
  sourceDepths?: string[];
  sourceRevisions: number[];
  sourceGeometryRevisions?: number[];
  view?: SourceView;
  acquisition: string;
  opaque: boolean;
  name?: string;
  layerName: string;
  logicalName: string;
  colour: number[];
  window: Span;
  channelIndex?: number;
  localPosition?: number[];
  visible: boolean;
  weight: number;
  gamma?: number;
  attenuation?: number;
  depth?: string;
  controlIndex?: number;
}

/** How big the box is, in browser pixels, and how many real pixels go to one. */
interface Size {
  width: number;
  height: number;
  density: number;
}

/** A rectangle in the box, in browser pixels. */
interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** What `openViewer` is told. */
export interface OpenOptions {
  acquisitions?: Acquisition[];
  transparentBackground?: boolean;
  background?: string;
  presentation?: string;
}

/** Everything one viewer knows. */
interface Own {
  element: HTMLElement;
  transparentBackground: boolean;
  background: string;
  presentation: string;
  engineRect: Rect | null;
  engineHost: HTMLDivElement;
  engine: Engine | null;
  rows: Row[];
  watchSize: ResizeObserver | null;
  /** How to stop following the picture's axes as its sources land. */
  stopFollowingTheAxes: (() => void)[];
  stoodOnTheTable: boolean;
  destroyed: boolean;
  /** Measured when the surfaces are built, before anything is drawn. */
  size: Size | null;
  showingPicture: boolean;
}

/**
 * Which of the engine's panel layouts to ask for.
 *
 * Paired with the axis order the primitives hand the engine (width first,
 * depth last; `pinTheAxesThatMeasureDistance`): `xy` puts width across the
 * window running to the right, height down it, and depth into the screen — the
 * plane an operator scrolls through, drawn the way round the specimen really is.
 * The other pairing that also looks right draws every picture as a mirror
 * image, and nothing anywhere reports it; the viewer's
 * `tests/test_the_picture_is_not_mirrored.py` is what stops it coming back.
 */
const FLAT_LAYOUT = "xy";

/** Metres to micrometres. The store speaks metres; the operator speaks µm. */
const UM_PER_M = 1e6;

/**
 * Open a viewer inside `element` and return the handle used to drive it.
 *
 * @param {HTMLElement} element  where the viewer draws; it fills this box
 * @param {object} options
 *   `acquisitions`  `[{ url, name, channels }]`, drawn in order with the first
 *                   at the bottom. Each `url` must be a whole address including
 *                   the scheme and host — see the note about addresses above.
 *                   `channels` is `[{ name, colour, window }]`, where `colour`
 *                   is three numbers from 0 to 1 and `window` is `{low, high}`
 *                   in the stored numbers' own units. It is **optional**: leave
 *                   it out and the viewer reads the run's own description of its
 *                   colours out of the store. Say it and what you say is used
 *                   unchanged.
 *   `background`    the page colour, as CSS text, so the seam between the two
 *                   drawing surfaces never shows.
 *   `presentation`  `"2d-overlay"` for sources placed in absolute stage z: the
 *                   picture opens at the lowest plane any stack holds, and a
 *                   flat source is kept in view at every depth. It changes
 *                   navigation and how a flat source's depth is read, never
 *                   where a source is placed.
 * @returns {Promise<Viewer>} the handle.
 *
 * It can fail in two ways worth knowing about: an address without a scheme is
 * refused straight away, and an acquisition that never says how big its voxels
 * are leaves the promise unresolved until the caller gives up. Both are far
 * better than the alternative, which is a viewer that opens onto nothing and
 * says everything is fine.
 */
export async function openViewer(element: HTMLElement, options: OpenOptions = {}): Promise<EngineViewer> {
  const {
    acquisitions = [],
    transparentBackground = false,
    background = "#000000",
    presentation = "source-geometry",
  } = options;

  for (const acquisition of acquisitions) {
    const addresses = [
      acquisition.url,
      ...(acquisition.channels ?? []).flatMap((channel) => channel.sources ?? []),
    ].filter(Boolean);
    for (const address of new Set(addresses)) {
      sourceAddressIsWhole(address, acquisition.name);
    }
  }

  // Everything the viewer knows lives in this one object, and it goes away when
  // the viewer does. Nothing is kept in a variable belonging to this file.
  const own: Own = {
    element,
    transparentBackground,
    background,
    presentation,
    // The rectangle within the box the engine is currently drawing in, in
    // browser pixels: the whole box.
    engineRect: null,
    engineHost: document.createElement("div"),
    engine: null,
    // The channels, flattened across all acquisitions in the order they are
    // drawn.
    rows: [],
    watchSize: null,
    stopFollowingTheAxes: [],
    // Whether the picture has been opened at the bottom of its stacks yet;
    // see `standOnTheTable`.
    stoodOnTheTable: false,
    destroyed: false,
    size: null,
    showingPicture: true,
  };

  buildTheTwoSurfaces(own);
  await start(own, acquisitions);
  return handleFor(own);
}

/** Refuse a source address that Neuroglancer would otherwise fail on silently. */
function sourceAddressIsWhole(address: string, acquisition: string) {
  if (/^[a-z]+:\/\//i.test(address)) return;
  throw new Error(
    `the acquisition "${acquisition}" was given the address ` +
      `"${address}", which has no scheme or host in it. ` +
      "Neuroglancer accepts such an address, builds the layer, raises no " +
      "error and then never fetches anything at all, so this is refused " +
      "here instead. Pass the whole address, including http:// and the host.",
  );
}

/** The engine's viewer, while the page's viewer is open. */
function viewerOf(own: Own): Viewer | null {
  return own.engine?.viewer ?? null;
}

// ---------------------------------------------------------------------------
// The two surfaces
// ---------------------------------------------------------------------------

/**
 * Put the engine's canvas down in the box. The operator's drawing goes over it
 * from the canvas's own surface (`../../surface.ts`), not from here.
 *
 * Two lines of styling here were each learned the hard way and neither is
 * optional.
 *
 * The engine builds a small tree of elements of its own with a stacking order
 * inside it. Left alone those escape into the page's own order and end up
 * *above* anything placed after them, so the operator's drawing appears to be on
 * top while every click and drag is quietly caught by the engine's panel
 * underneath. Giving the engine's box a stacking order of its own keeps its
 * insides inside it.
 *
 * And the engine must not receive gestures at all, so it is made transparent to
 * the mouse rather than merely covered by something. The two gestures the
 * canvas's surface listens for are the only ones there are.
 */
function buildTheTwoSurfaces(own: Own) {
  const { element } = own;
  // Only set when it has not been decided already, so a page that has laid its
  // own box out is left alone. Absolute positioning inside needs *something*
  // positioned outside it, and `static` is the one value that will not do.
  if (getComputedStyle(element).position === "static") {
    element.style.position = "relative";
  }
  element.style.background = own.transparentBackground ? "transparent" : own.background;

  own.engineHost.className = "zmart-engine-underneath";
  Object.assign(own.engineHost.style, {
    position: "absolute",
    inset: "0",
    // One above the surface the bottom layer would go on, and one below the
    // operator's own: the three layers of the canvas, in order.
    zIndex: "1",
    pointerEvents: "none",
  });

  element.appendChild(own.engineHost);
  fitTheSurfaces(own);

  // The window can be resized, and the engine's drawing area is sized by writing
  // plain pixel numbers onto its element. Written once and never again, a
  // resized window leaves the engine drawing at the old size — and two surfaces
  // that disagree about how large the window is disagree about everything that
  // follows from it.
  own.watchSize = new ResizeObserver(() => {
    if (own.destroyed) return;
    fitTheSurfaces(own);
  });
  own.watchSize.observe(element);
}

/**
 * Measure the box, and make the engine's drawing area its size.
 *
 * The engine takes no account of screen density at all — measured, it draws one
 * canvas pixel per browser pixel and lets the browser scale it up. What that
 * costs is sharpness rather than registration: the geometry still agrees exactly,
 * and the picture is simply drawn at two thirds of the resolution a dense screen
 * could show. It is not this file's to fix.
 */
function fitTheSurfaces(own: Own) {
  const density = window.devicePixelRatio || 1;
  const width = own.element.clientWidth;
  const height = own.element.clientHeight;
  own.size = { width, height, density };
  fitTheEngineToItsPatch(own);
}

/**
 * Write the box's size onto the engine's element.
 *
 * The engine's drawing area is sized by writing plain pixel numbers onto its
 * element; written once and not written again, a resized window leaves the
 * engine drawing at the old size, and two surfaces that disagree about how
 * large the window is disagree about everything that follows.
 */
function fitTheEngineToItsPatch(own: Own): Rect {
  const { width, height } = own.size || { width: 0, height: 0 };
  const rect: Rect = { left: 0, top: 0, width, height };
  const same = own.engineRect
    && own.engineRect.left === rect.left && own.engineRect.top === rect.top
    && own.engineRect.width === rect.width && own.engineRect.height === rect.height;
  own.engineRect = rect;
  if (same) return rect;
  own.engineHost.style.left = `${rect.left}px`;
  own.engineHost.style.top = `${rect.top}px`;
  own.engineHost.style.width = `${rect.width}px`;
  own.engineHost.style.height = `${rect.height}px`;
  tellTheEngineItHasBeenResized(own);
  return rect;
}

/**
 * Tell the engine at once that its drawing area has changed size.
 *
 * This is the one place that reaches past the engine's own arrangements, and it
 * earns its place, so it is worth explaining what it does and what happens
 * without it.
 *
 * The engine only re-reads how large it is when it notices a resize, and it
 * notices through the browser's own resize watcher — which reports *after* the
 * page has been laid out, and therefore after the engine has already drawn at
 * least one more frame at the old size. That one frame is drawn at one size and
 * stretched to fill another, so the picture in it is very slightly the wrong
 * scale and in the wrong place. Measured, that showed up as the two layers
 * coming apart by seventy screen pixels while the view was panned — not because
 * the operator's drawing was following the wrong thing, but because the engine's
 * own frame did not yet know how big it was.
 *
 * Nudging the engine's own count of resizes makes it re-read its size at the
 * start of the very next frame, before it draws anything, so the frame the
 * operator sees is drawn at the size it is displayed at. Asking for a redraw is
 * what makes that next frame happen at once rather than whenever something else
 * causes one. With this, the same measurement comes back to a single pixel.
 *
 * Both halves earn their place, and which fault each one prevents was measured
 * rather than assumed. With the whole of this taken out, the two layers came
 * apart by 69 screen pixels while panning and 71 while thrown about. With only
 * the count left out and the redraw kept, panning came back to 1 and zooming
 * stayed at 2 rather than 1 — so the redraw is what saves panning and the count
 * is what saves zooming.
 */
function tellTheEngineItHasBeenResized(own: Own) {
  const display = viewerOf(own)?.display;
  if (!display) return;
  display.resizeGeneration += 1;
  display.scheduleRedraw();
}

// ---------------------------------------------------------------------------
// Opening the acquisitions
// ---------------------------------------------------------------------------

/**
 * Start the engine, hand it the acquisitions, and settle everything that is set
 * once.
 *
 * The engine's own gestures are emptied (`"none"`): in this arrangement the
 * operator's canvas lies over the engine and catches every gesture before the
 * engine could see one. The ground behind the picture is the page's own colour,
 * so that the seam between the two drawing surfaces cannot be seen — which is
 * why the measurements deliberately use a different colour: a margin you cannot
 * see is a margin you cannot measure. The engine's own furniture (axis lines,
 * the annotations it draws by default) is off; the page draws whatever of that
 * it wants, where it wants it.
 */
async function start(own: Own, acquisitions: Acquisition[]) {
  own.engine = createViewer(own.engineHost, { gestures: "none", ground: own.background });
  own.engine.setView({
    layout: FLAT_LAYOUT, chrome: false, transparentBackground: own.transparentBackground,
  });
  followTheAxes(own, own.engine.viewer);
  await loadAcquisitions(own, acquisitions);
}

/**
 * Keep the axes that measure distance on screen, and open the picture at the
 * bottom of its stacks, as the picture's sources land.
 *
 * The picture's axes come from its sources, and they arrive as each source
 * is read: a depth that lands after the first source has to be taken into the
 * screen too (`keepSpatialAxes`), and the picture opened at the bottom of it.
 */
function followTheAxes(own: Own, viewer: Viewer) {
  own.stopFollowingTheAxes.push(
    keepSpatialAxes(viewer),
    viewer.navigationState.position.coordinateSpace.changed.add(() => standOnTheTable(own)),
  );
}

async function loadAcquisitions(own: Own, acquisitions: Acquisition[]) {
  own.rows = await rowsFor(acquisitions);
  const viewer = viewerOf(own);
  if (own.destroyed || !viewer || !own.rows.length) return;
  drawTheRows(own);
  await whenTheAxesAreKnown(viewer);
  if (own.destroyed) return;
  startTimeAtTheFirstMoment(viewer);
  standOnTheTable(own);
  await finishOpeningAcquisitions(own, viewer, acquisitions);
}

/**
 * Hand the engine the scene: every row, in draw order, as the primitives keep
 * layers in step with it. Only what changed is changed — a slider's value, a
 * store that arrived, a revision committed into a store already drawn.
 */
function drawTheRows(own: Own) {
  own.engine?.syncLayers(sceneOf(own));
}

/**
 * The rows as the layers the engine draws, first at the bottom.
 *
 * The channels of one acquisition add together, and an acquisition drawn over
 * another covers it rather than mixing with it -- a target frame over the
 * overview is a picture of its own, not the sum of two. So the first channel of
 * an acquisition drawn over another keeps the covering blend, and the program is
 * opaque wherever it has data; its other channels add onto it alone. Where an
 * acquisition's rows know which ground was acquired, that ground is laid first,
 * black and opaque, so acquired black pixels stay opaque while unacquired ground
 * stays clear; then every channel of it adds.
 */
function sceneOf(own: Own): EngineLayer[] {
  const groupOf = (row: Row) => `${row.acquisition}/${row.depth ?? ""}`;
  const bottom = own.rows.length ? groupOf(own.rows[0]) : "";
  const opened = new Set<string>();
  const scene: EngineLayer[] = [];
  for (const row of own.rows) {
    const group = groupOf(row);
    const opens = !opened.has(group);
    if (opens) {
      opened.add(group);
      for (const member of own.rows.filter(one => groupOf(one) === group)) {
        if (member.coverageSources?.length) {
          scene.push(coverageLayerFor(layerFor(own, member, "additive"), member.coverageSources, "default"));
        }
      }
    }
    const coversWhatIsBelow = opens && group !== bottom && !row.coverageSources?.length;
    scene.push(layerFor(own, row, coversWhatIsBelow ? "default" : "additive"));
  }
  return scene;
}

/**
 * One row as the engine is told to draw it.
 *
 * Every position store of one channel is a source of the SAME layer, placed by
 * the transform in its own OME-Zarr metadata; flattening it into one
 * acquisition per address is what once produced 27 controls for a 3-channel,
 * 3-by-3 overview.
 *
 * Each layer is drawn at its full strength (`opacity: 1`). The engine's own
 * default for an image layer is a half, which is right for looking through one
 * layer at another and wrong for the channels of one acquisition: measured on a
 * run recorded in two colours, the second channel reached the screen at 118 of a
 * possible 255 where the first reached 237. Nothing is lost by it, because what
 * decides where a layer is see-through is the program, which emits nothing
 * where the stored number is nought.
 *
 * Where a store keeps its channels inside one array, the row's own index picks
 * the channel out, as a dimension belonging to the layer, said in the
 * description the layer is built from: written onto a layer built a moment ago
 * it would land in a space with no room in it yet, and a two-channel run drew
 * both of its layers from the same channel that way.
 *
 * A flat picture -- a published projection, or the flat stores of a channel --
 * keeps its depth to itself, so it is drawn at whatever plane the picture
 * stands at instead of on one plane of the shared depth.
 */
function layerFor(own: Own, row: Row, blend: "additive" | "default"): EngineLayer {
  const localPosition = row.localPosition ?? (row.channelIndex != null ? [row.channelIndex] : undefined);
  return {
    type: "image",
    name: row.layerName,
    source: [...row.sources],
    visible: own.showingPicture && row.visible,
    shader: programFor(row),
    shaderControls: controlsFor(row),
    opacity: 1,
    blend,
    ...(localPosition ? { localPosition } : {}),
    persistentFlat: row.depth === "flat" || row.view?.type === "projection",
    sourceRevisions: row.sourceRevisions,
    ...(row.sourceGeometryRevisions ? { sourceGeometryRevisions: row.sourceGeometryRevisions } : {}),
  };
}

async function finishOpeningAcquisitions(own: Own, viewer: Viewer, acquisitions: Acquisition[]) {
  // The engine chooses a starting magnification the first moment it believes it
  // knows what space the picture lives in, and for a moment that is an empty
  // space in which one voxel is one metre. Clearing it now makes it choose
  // again, this time knowing how big a voxel really is. Without this the viewer
  // opens on an empty rectangle with every piece of data present and correct.
  viewer.navigationState.zoomFactor.reset();
  viewer.perspectiveNavigationState.zoomFactor.reset();

  /* Having let the engine choose again, choose for it. Left alone it opens at one
     voxel to one screen pixel, which on a 1.1 µm store drops the operator inside
     the specimen at full magnification with nothing on screen to say where they
     are. Where a run opens is not a property of an engine — `../opening-view.ts`
     holds the rule. Skipped where the box has not been measured yet, since
     fitting to a box of no size would be worse than the engine's own guess. */
  /* Where the specimen is, so the view opens on it rather than on the middle of
     the ground the run declared. One small read; nothing else waits on it. */
  const specimen = own.presentation !== "2d-overlay" && acquisitions.length
    ? await whereTheSpecimenIsInThisStore(acquisitions[0].url)
    : null;
  if (own.destroyed) return;
  if (own.size && own.size.width > 0 && own.size.height > 0) {
    const ground = theGroundTheRunCovers(viewer);
    const showingAllOfIt = theViewThatShowsAllOf(
      ground && specimen
        ? { ...ground, specimenUm: theSpecimenInMicrometres(viewer, ground, specimen) }
        : ground,
      own.size,
    );
    if (showingAllOfIt) writeTheView(viewer, showingAllOfIt);
  }
  openOnThePlaneWhereTheSpecimenIs(own, viewer, specimen);
}


// ---------------------------------------------------------------------------
// What the run says about its own colours
// ---------------------------------------------------------------------------
//
// The page may describe an acquisition's channels — what each one is called,
// what colour to draw it in, and how bright to open it — and where it does, what
// it says is used exactly as given. But a page usually has no way of knowing any
// of that, because the description lives inside the store, which is the very
// thing it is asking this viewer to open. Making the page find out would mean
// opening the run twice: once by the page, to learn what to say, and once by the
// viewer, to draw it.
//
// So where the page says nothing, the description is read here instead, out of
// the `omero` block that every image this project writes carries.
// `zmart_storage/canvas.py` is where it is written, and it holds one entry per
// channel: a label, a colour as six hex digits, and a brightness window.
//
// Leaving this out has a plain and visible cost. With nothing to go on a viewer
// falls back to a single white channel, so **a run recorded in two colours shows
// only its first one**, in white, and nothing on screen says that the rest of
// the acquisition is missing.

/** The colour a channel is drawn in when nobody has named one. */
const WHITE = [1, 1, 1];

/**
 * The brightness range to open a channel at when neither the page nor the run
 * asked for one. It is the same range this viewer has always used in that case,
 * and it suits the twelve-bit cameras these runs are acquired on.
 */
const AN_ORDINARY_WINDOW = { low: 0, high: 4095 };

/** One channel as a run's own description names it (`omero.channels`). */
interface DescribedChannel {
  label?: string;
  color?: unknown;
  window?: { start?: unknown; end?: unknown } | null;
}

/** What this reads of a run's own description: its channels. */
interface RunDescription {
  omero?: { channels?: DescribedChannel[] };
}

/** A description file, as either version of the format writes it. */
interface DescriptionFile extends RunDescription {
  attributes?: RunDescription & { ome?: RunDescription };
}

/**
 * Six hex digits, the way a run writes a colour, as the three numbers from 0 to
 * 1 the drawing works in.
 *
 * Anything that is not six hex digits is drawn white rather than refused. A
 * misspelt colour is a small blemish; refusing to open somebody's acquisition
 * over one would be a great deal worse.
 */
function colourFromTheStore(hex: unknown): number[] {
  if (typeof hex !== "string" || !/^[0-9a-f]{6}$/i.test(hex)) return [...WHITE];
  return [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
}

/**
 * The brightness range a channel should first be shown with, out of the run's
 * own description of it.
 *
 * A description holds two different ranges and telling them apart is the whole
 * of this function. `min` and `max` are the numbers the camera can produce at
 * all — nought to 65535 for a sixteen-bit camera — which is a fact about the
 * instrument and true of every acquisition it ever takes. `start` and `end` are
 * the range the picture should be *displayed* with, and they are written only
 * when the run actually asked for one.
 *
 * Only `start` and `end` are used here, and that is deliberate. A real
 * acquisition sits in the bottom few per cent of what the camera can count — a
 * few hundred counts of background with the signal not far above — so opening it
 * with the camera's whole range shows a picture that is very nearly black, and
 * it stays that way until somebody thinks to drag a contrast slider. This
 * project has already had that fault once and fixed it, which is why it is
 * spelled out here rather than left to whoever reads the description next.
 *
 * When the run asked for nothing, the ordinary window above is used — the same
 * one this viewer would have used had there been no description at all.
 */
function windowFromTheStore(described: DescribedChannel | undefined): Span | null {
  const { start, end } = described?.window ?? {};
  if (typeof start === "number" && typeof end === "number"
      && Number.isFinite(start) && Number.isFinite(end)) {
    return { low: start, high: end };
  }
  /* Nothing, rather than the ordinary window. A run that names a colour and says
     nothing about how to display it is not the same as a run that asked for the
     ordinary window, and answering as though it were is what put a real skin
     biopsy on a milky grey field. The caller reads the picture instead; only if
     that cannot be read does the guess come back. */
  return null;
}

/**
 * The channels a store describes, in the form this viewer keeps them in.
 *
 * `attributes` is the store's own description, as it was read from the image.
 * Nothing at all is returned when the store describes no channels, so that the
 * caller can fall back to whatever it did before rather than being handed an
 * empty list and drawing nothing.
 *
 * One limit, said plainly. What comes back is one entry per channel the
 * description *names*, not one per channel the picture holds. Everything this
 * project writes keeps the two in step, so for our own runs they are the same
 * list. A foreign image that stored four colours and described only two would
 * have two of them drawn here, and the operator would have to notice. Counting
 * the picture's own channels instead would mean a second reading of every image.
 */
function channelsTheStoreDescribes(attributes: RunDescription | null): ChannelSpec[] | null {
  const described = attributes?.omero?.channels;
  if (!Array.isArray(described) || !described.length) return null;
  return described.map((channel, at) => ({
    name: channel?.label || `channel ${at + 1}`,
    colour: colourFromTheStore(channel?.color),
    window: windowFromTheStore(channel),
  }));
}

/**
 * The run's own description of an acquisition, fetched from the store.
 *
 * Neuroglancer reads the same description — it has to, in order to build a layer
 * at all — but it keeps it to itself: what it gives back is a layer, not the
 * text the layer was built from. So this asks for the description itself: one
 * small request per acquisition, made once while the viewer is opening.
 *
 * The address the page passes carries a short suffix telling the engine which
 * shape of store to expect, written after a vertical bar as in
 * `…/run.ome.zarr/|zarr2:`. It is taken off here so that the description can be
 * asked for by name.
 *
 * A store that will not answer is not a reason to refuse the acquisition, so
 * nothing at all is returned and the caller carries on with what it already has.
 *
 * @param {string} url the address the page gave for this acquisition.
 * @returns {Promise<object|null>} the store's description, or nothing.
 */
async function theRunsOwnDescription(url: string): Promise<RunDescription | null> {
  const bar = url.indexOf("|");
  const address = (bar < 0 ? url : url.slice(0, bar)).replace(/\/+$/, "");
  // The two versions of the format keep the description in different places.
  // Version 2 writes a small `.zattrs` file beside the picture; version 3 folds
  // the same thing into `zarr.json`, under `attributes`. Both are tried, so that
  // a run written either way opens the same.
  const spellings: [string, (doc: DescriptionFile) => RunDescription][] = [
    [".zattrs", (doc) => doc],
    // Version 3 folds the description into `zarr.json` under `attributes`,
    // and OME-Zarr 0.5 folds the OME half one level further, under an `ome`
    // key that holds `multiscales` and `omero` alike — so a 0.5 store read
    // only at `attributes` answered with neither, and a run written 0.5
    // opened as a single white channel however many colours it named.
    ["zarr.json", (doc) => doc?.attributes?.ome ?? doc?.attributes ?? doc],
  ];
  for (const [file, unwrap] of spellings) {
    try {
      // Never from the browser's own copy. These runs are written into while
      // somebody is watching them, and a viewer answering from a moment ago is
      // exactly what live viewing exists to avoid.
      const answer = await fetch(`${address}/${file}`, { cache: "no-store" });
      if (answer.ok) return unwrap(await answer.json() as DescriptionFile);
    } catch {
      // One of the two spellings is expected to be missing, so a failure here is
      // ordinary. It is only worth saying something if both of them fail, which
      // is what happens below.
    }
  }
  console.warn(
    `the description of "${address}" could not be read, so nothing is known ` +
      "about the colours this run recorded. It will be drawn as a single white " +
      "channel, which is all there is to go on.",
  );
  return null;
}

/**
 * Turn the acquisitions into the flat list of rows the engine draws.
 *
 * One row per channel, in the order they should be drawn, the first at the
 * bottom. Numbering them across all the acquisitions rather than within each one
 * is what makes `setChannel(index, …)` a single sensible number for the page to
 * hold, and it matches how an operator reads the list on screen: one line per
 * thing that can be switched on and off.
 */
async function rowsFor(acquisitions: Acquisition[]): Promise<Row[]> {
  const rows: Row[] = [];
  for (const acquisition of acquisitions) {
    const explicitlyDescribed = acquisition.channels && acquisition.channels.length;
    const itsOwnDescription = explicitlyDescribed
      ? null
      : await theRunsOwnDescription(acquisition.url);
    // What the page said, where it said anything; otherwise what the run says
    // about itself; and only if the run says nothing either, one white channel.
    const described: ChannelSpec[] = explicitlyDescribed
      ? acquisition.channels!
      : channelsTheStoreDescribes(itsOwnDescription)
        || [{ name: acquisition.name, colour: [...WHITE], window: null }];
    /* Whatever is still without a window is read out of the picture, one channel
       at a time.

       Not only the run that describes nothing. A run may name its colours and
       still say nothing about how to display them — a skin biopsy met here does
       exactly that, `omero` present with `"window": null` on both channels — and
       filling that gap with a guess about a camera puts a specimen whose
       background sits at 1990 counts on a milky grey field. Per channel, because
       two channels of one acquisition are routinely far apart: on that biopsy one
       reaches 4573 counts and the other 8859, and one window across the pair
       flattens whichever is fainter. That fault is already fixed once, in the
       viewer's own backend; this is the same fault in the canvas. */
    const channels: ChannelSpec[] = [];
    for (const [within, channel] of described.entries()) {
      const sources = channel.sources?.length
        ? [...channel.sources]
        : [channel.source ?? acquisition.url];
      channels.push(channel.window ? channel : {
        ...channel,
        sources,
        window: (await theRangeAStoreHolds(sources[0], {
          channel: channel.channelIndex ?? within,
        }))
          || { ...AN_ORDINARY_WINDOW },
      });
    }
    channels.forEach((channel, within) => {
      const sources = channel.sources?.length
        ? [...channel.sources]
        : [channel.source ?? acquisition.url];
      rows.push({
        url: sources[0],
        sources,
        coverageSources: channel.coverageSources,
        sourceDepths: channel.sourceDepths,
        sourceGeometryRevisions: channel.sourceGeometryRevisions,
        view: channel.view,
        sourceRevisions: [...(channel.sourceRevisions ?? sources.map(() => 0))],
        acquisition: acquisition.name,
        /* Whether every store of this acquisition is one imaged position and
           nothing else, so a layer may be opaque across its whole extent. */
        opaque: acquisition.opaque === true,
        name: channel.name,
        // The engine keeps one flat list of layers and needs their names to be
        // different from one another, and two acquisitions can easily hold a
        // channel of the same name — an overview and a detail scan both
        // recording green. So the name carries both halves.
        layerName: `${acquisition.name}/${channel.name}${channel.view ? "/" + (channel.view.method ?? channel.view.type) : ""}`,
        logicalName: `${acquisition.name}/${channel.name}`,
        colour: channel.colour || [...WHITE],
        window: channel.window || { ...AN_ORDINARY_WINDOW },
        // Which position along the store's channel axis this row reads from.
        // Said for every row, including a lone one, and that is worth a sentence
        // because it used not to be. Left unsaid, the engine picks a channel for
        // itself — the middle of however many the store holds — so a page that
        // named one channel of a two-channel run was shown the *second* one,
        // drawn in the colour it had asked for the first. Nothing on screen
        // could have told an operator that.
        channelIndex: channel.channelIndex === undefined ? within : channel.channelIndex,
        localPosition: channel.localPosition,
        visible: channel.visible !== false,
        weight: channel.weight ?? 1,
      });
    });
  }
  const expanded = rows.flatMap((row, controlIndex): Row[] => {
    const depths = row.sourceDepths;
    if (row.view || !depths) return [{ ...row, controlIndex }];
    return ["flat", "stack"].flatMap(depth => {
      const indices = depths.flatMap((kind, i) => kind === depth ? [i] : []);
      if (!indices.length) return [];
      const part: Row = { ...row, depth, controlIndex, layerName: `${row.layerName}/${depth}` };
      part.sources = indices.map(i => row.sources[i]);
      const covering = row.coverageSources;
      if (covering) part.coverageSources = indices.map(i => covering[i]);
      part.sourceRevisions = indices.map(i => row.sourceRevisions[i]);
      const geometry = row.sourceGeometryRevisions;
      if (geometry) part.sourceGeometryRevisions = indices.map(i => geometry[i]);
      part.url = part.sources[0];
      return [part];
    });
  });
  return acquisitions.flatMap(acquisition => [undefined, "flat", "stack"].flatMap(depth =>
    expanded.filter(row => row.acquisition === acquisition.name && row.depth === depth)));
}

/**
 * Grow the open rows in place, and draw the acquisitions and depths that join.
 *
 * The viewer publishes stable aggregate addresses with committed revisions.
 * Another acquisition or depth kind can join an open picture without a reason
 * to destroy it: destroying revokes the old `/data/N/` endpoint while its
 * chunks are still in flight, and it also throws away navigation and operator
 * choices. This accepts only the shape the viewer promises here — additional
 * acquisition/channel rows, and each old source list as an exact prefix of its
 * next — and returns false for anything else: removing or replacing a source is
 * a genuinely different scene, which the caller opens afresh.
 *
 * A row already open keeps what the operator chose for it (whether it shows,
 * its colour, window, weight and gamma); a row that joins takes those of the
 * same channel of its acquisition, where one is open. The primitives then feed
 * the new stores in, a group at a time, and refresh the ones whose revision
 * moved.
 */
async function addSourcesToTheOpenRows(own: Own, acquisitions: Acquisition[]): Promise<boolean> {
  if (own.destroyed) return false;
  if (!own.rows.length) {
    await loadAcquisitions(own, acquisitions);
    return true;
  }
  const wanted = await rowsFor(acquisitions);
  const viewer = viewerOf(own);
  if (own.destroyed || !viewer) return false;
  const nextByName = new Map(wanted.map(row => [row.layerName, row]));
  for (const held of own.rows) {
    const next = nextByName.get(held.layerName);
    if (!next || !viewer.layerManager.getLayerByName(held.layerName)?.layer) return false;
    if (next.sources.length < held.sources.length) return false;
    if (held.sources.some((source, at) => next.sources[at] !== source)) return false;
  }
  for (const row of wanted) {
    for (const address of row.sources) sourceAddressIsWhole(address, row.acquisition);
  }
  const heldByName = new Map(own.rows.map(row => [row.layerName, row]));
  own.rows = wanted.map(row => {
    const chosen = heldByName.get(row.layerName)
      ?? own.rows.find(one => one.acquisition === row.acquisition && one.name === row.name);
    if (!chosen) return row;
    return {
      ...row,
      visible: chosen.visible, colour: chosen.colour, window: chosen.window,
      weight: chosen.weight, gamma: chosen.gamma, attenuation: chosen.attenuation,
    };
  });
  drawTheRows(own);
  return true;
}

/**
 * Wait until the images have said how big a voxel is.
 *
 * Until they have, the engine is working in a space with no axes at all, and
 * every conversion between the operator's micrometres and the screen would be
 * nonsense.
 */
function whenTheAxesAreKnown(viewer: Viewer): Promise<void> {
  const { position } = viewer.navigationState;
  return new Promise<void>((done) => {
    const look = () => {
      if ((position.coordinateSpace.value?.rank ?? 0) === 0) return;
      stop();
      done();
    };
    const stop = position.coordinateSpace.changed.add(look);
    viewer.registerDisposer(() => { stop(); done(); });
    look();
  });
}

/**
 * Open the picture at the bottom of the stacks, once, when it first has a
 * depth to open at.
 *
 * Every stack is written in absolute stage z, lowest plane first, so the
 * bottom of the shared depth axis is the lowest plane there is, and the Z
 * slider under the picture reads "plane 1" there. The engine on its own
 * would open a depth that lands after the first source in the middle of
 * it. Only once: after that the depth is the operator's to choose, and a
 * stack landing later must not pull the view back down.
 */
function standOnTheTable(own: Own) {
  const viewer = viewerOf(own);
  if (!viewer || own.presentation !== "2d-overlay" || own.stoodOnTheTable) return;
  const depth = theDepthOnScreen(viewer);
  if (depth < 0) return;
  const bottom = theLowestPlaneOf(viewer, depth);
  if (bottom === null) return;
  own.stoodOnTheTable = true;
  moveAlong(viewer, depth, bottom);
}

/** Which of the picture's axes goes into the screen, or -1 while none does. */
function theDepthOnScreen(viewer: Viewer): number {
  return viewer.navigationState.displayDimensionRenderInfo.value?.displayDimensionIndices?.[2] ?? -1;
}

/**
 * The centre of the lowest plane on the shared depth axis, in the engine's
 * own coordinates, or null while no stack has declared a depth.
 *
 * Stores are written in absolute stage z (`zarr_positions.py`), so the
 * shared axis's lower bound is the lowest plane any stack holds; flat
 * aggregates keep their depth local and do not pull the bound about. Where
 * integer coordinates are voxel centres on this axis, the first plane's centre
 * is half a voxel in from the bound.
 */
function theLowestPlaneOf(viewer: Viewer, depth: number): number | null {
  const space = viewer.navigationState.position.coordinateSpace.value;
  const lower = space?.bounds?.lowerBounds?.[depth];
  if (lower === undefined || !Number.isFinite(lower)) return null;
  return space.bounds.voxelCenterAtIntegerCoordinates?.[depth] ? lower + 0.5 : lower;
}

/**
 * The axis of the picture that counts time, read as the primitives read every
 * axis, or null for a picture of one moment. Time is the axis measured in
 * seconds.
 */
function theTimeAxis(viewer: Viewer | null): AxisReading | null {
  const space = viewer?.navigationState.position.coordinateSpace.value;
  const at = space?.units ? Array.from(space.units).indexOf("s") : -1;
  return space && at >= 0 ? readTheAxis(viewer, space.names[at]) : null;
}

// ---------------------------------------------------------------------------
// The little program that runs on the graphics card
// ---------------------------------------------------------------------------

/**
 * The little program that turns stored numbers into what you see.
 *
 * It has two things to get right at once and they pull in opposite directions,
 * so both are worth stating.
 *
 * **The brightness has to reach the screen**, because turning the contrast
 * handles is how a microscopist finds their specimen. So the colour carries the
 * brightness: colour × value.
 *
 * **Ground nobody has imaged has to come out as nothing rather than as black.**
 * Most of a canvas is usually empty — the room is declared to the reach of the
 * stage and filled in as the run goes — so a row drawn opaque everywhere blacks
 * out every row below it. That means the transparency answers one question only:
 * was this spot imaged at all?
 *
 * Getting these the other way round is a real mistake with a confusing symptom.
 * For the bottom-most picture on screen the engine switches blending off
 * altogether and writes the colour straight out, using the transparency only as
 * a yes-or-no test — so brightness put into the transparency simply never
 * arrives, and every contrast window draws the same flat shape.
 *
 * The numbers for the window are sent separately, as values for a control the
 * program declares, so that dragging a contrast handle reaches a program that is
 * already compiled instead of causing a fresh one to be built several times a
 * second.
 *
 * **The programs are the ZMART viewer's.** The viewer's own window draws with
 * exactly these, and operators have learned to read their specimens by that
 * look, so there is one copy, in the viewer (`programs.js` in its `drawing`
 * folder), and this page's build takes it from the installed viewer. This page
 * asks for one thing the viewer's window does not offer yet: gamma, which bends
 * the curve between the window's ends.
 */
function programFor(row: Row): string {
  return theViewersProgram(false, null, row.opaque, { gamma: true });
}

/**
 * Every shader control of one row, as one whole object.
 *
 * Always restored whole, never piecewise: a partial restore is how one
 * control quietly resets another to its default.
 */
function controlsFor(row: Row) {
  const [red, green, blue] = row.colour;
  return theViewersControls(row.window, false, row.weight ?? 1, [red, green, blue], null,
    row.attenuation ?? 0, row.gamma ?? 1);
}


// ---------------------------------------------------------------------------
// Micrometres in, micrometres out
// ---------------------------------------------------------------------------
//
// The engine has a notion of zoom of its own, and it is not one the operator
// should ever meet. It counts in "canonical voxels per screen pixel", where a
// canonical voxel is the smallest voxel among the axes on screen — a number that
// changes meaning when a different acquisition is opened. The store and the
// stage both speak micrometres, so that is what crosses this boundary: the
// primitives' camera (`captureCamera`, `restoreCamera`) does the exchange, and
// this page names which two axes are across and down the window.

/** Where each axis on screen sits in the image's own list, its name, and how big it is. */
function axesOnScreen(viewer: Viewer) {
  const info = viewer.navigationState.displayDimensionRenderInfo.value;
  const space: CoordinateSpace = viewer.navigationState.position.coordinateSpace.value;
  const across = info.displayDimensionIndices[0];
  const down = info.displayDimensionIndices[1];
  return {
    across,
    down,
    acrossName: space.names[across],
    downName: space.names[down],
    // Micrometres per voxel along each axis on screen.
    umAcross: (space.scales?.[across] ?? 0) * UM_PER_M,
    umDown: (space.scales?.[down] ?? 0) * UM_PER_M,
  };
}

/**
 * The specimen's position turned from voxels of the store into micrometres of
 * stage, which is what the page speaks.
 */
function theSpecimenInMicrometres(viewer: Viewer, ground: { atUm: XY }, specimen: Record<string, number>): XY | null {
  const axes = axesOnScreen(viewer);
  if (!(axes.umAcross > 0) || !(axes.umDown > 0)) return null;
  if (specimen.x === undefined || specimen.y === undefined) return null;
  return {
    x: ground.atUm.x + specimen.x * axes.umAcross,
    y: ground.atUm.y + specimen.y * axes.umDown,
  };
}

/**
 * Put the view on the plane a stack should open on.
 *
 * Said rather than inherited. Left alone this engine opens in the middle of its
 * volume, which is the answer `planes.ts` gives — but agreeing by coincidence is
 * not agreeing, and a default that changed on a version bump would show another
 * slice of tissue with nothing to say so.
 */
function openOnThePlaneWhereTheSpecimenIs(own: Own, viewer: Viewer, specimen: Record<string, number> | null) {
  const space = viewer.navigationState.position.coordinateSpace.value;
  const depth = theDepthOnScreen(viewer);
  if (depth < 0 || !space?.bounds) return;
  if (own.presentation === "2d-overlay") {
    /* The picture opens at the lowest plane any stack holds -- absolute
       stage z, as the writer places it. Navigation only selects that plane;
       it never rewrites a placement or infers one from whichever source
       loaded first. */
    const bottom = theLowestPlaneOf(viewer, depth);
    if (bottom === null) return;
    moveAlong(viewer, depth, bottom);
    own.stoodOnTheTable = true;
    return;
  }
  const planes = Math.round(
    space.bounds.upperBounds[depth] - space.bounds.lowerBounds[depth],
  );
  if (!(planes > 1)) return;
  // Where the specimen is, where it could be found; the middle of the declared
  // stack otherwise, which is right when a run fills the room it asked for.
  const plane = specimen?.z ?? theMiddlePlaneOf(planes);
  moveAlong(viewer, depth, space.bounds.lowerBounds[depth] + plane + 0.5);
}

/**
 * How much ground the open acquisitions cover, in micrometres.
 *
 * Read out of the engine's own coordinate space rather than from the stores,
 * because by this point the engine has read every store it was given and its
 * space spans all of them — so a page opening a wide survey and a detailed scan
 * over it gets the pair, without this having to know there were two.
 *
 * The bounds are in voxels of each axis, so each is turned into micrometres by
 * that axis's own scale; the two axes of a light-sheet store are rarely the same
 * size.
 */
function theGroundTheRunCovers(viewer: Viewer) {
  const axes = axesOnScreen(viewer);
  const bounds = viewer.navigationState.position.coordinateSpace.value?.bounds;
  if (!bounds || !(axes.umAcross > 0) || !(axes.umDown > 0)) return null;
  const low = { x: bounds.lowerBounds[axes.across], y: bounds.lowerBounds[axes.down] };
  const high = { x: bounds.upperBounds[axes.across], y: bounds.upperBounds[axes.down] };
  if (![low.x, low.y, high.x, high.y].every(Number.isFinite)) return null;
  return {
    atUm: { x: low.x * axes.umAcross, y: low.y * axes.umDown },
    wideUm: (high.x - low.x) * axes.umAcross,
    tallUm: (high.y - low.y) * axes.umDown,
  };
}

/** The view the engine is showing now, in micrometres; nothing to say while it has no axes. */
function readTheView(viewer: Viewer | null): View {
  const camera = viewer ? captureCamera(viewer) : null;
  if (!viewer || !camera) return { centre: { x: 0, y: 0 }, zoom: 0 };
  const axes = axesOnScreen(viewer);
  return {
    centre: { x: camera.positionUm[axes.acrossName], y: camera.positionUm[axes.downName] },
    zoom: camera.zoomUm,
  };
}

/**
 * Tell the engine where to look, in micrometres. Only the two axes across and
 * down the window are named, so every other axis -- the plane, the moment --
 * stays exactly where it stands.
 */
function writeTheView(viewer: Viewer, asked: { centre?: XY; zoom?: number }) {
  const camera = captureCamera(viewer);
  if (!camera) return;
  const axes = axesOnScreen(viewer);
  const positionUm: Record<string, number> = {};
  if (asked.centre) {
    positionUm[axes.acrossName] = asked.centre.x;
    positionUm[axes.downName] = asked.centre.y;
  }
  const zoomUm = asked.zoom !== undefined && asked.zoom > 0 ? asked.zoom : camera.zoomUm;
  restoreCamera(viewer, { ...camera, positionUm, zoomUm });
}

// ---------------------------------------------------------------------------
// The handle
// ---------------------------------------------------------------------------

/** What `layersForMeasurement` reports of one store of a channel. */
interface StoreStanding {
  url: string | null;
  matrix: number[] | null;
  error: string | null;
  dims: string[] | null;
  scales: number[] | null;
  units: string[] | null;
  lower: number[] | null;
  upper: number[] | null;
  voxelCenterAtIntegerCoordinates: boolean[] | null;
}

/**
 * What `layersForMeasurement` reports of one channel: its standing, and where
 * the view stands. A type rather than an interface, so a reader that knows only
 * some of its fields (the panel's `EngineRow`) can take it as it is.
 */
type ChannelStanding = {
  name: string;
  visible: boolean | undefined;
  window: Span;
  weight: number;
  matrix: number[] | null;
  error: string | null;
  dims: string[] | null;
  scales: number[] | null;
  units: string[] | null;
  lower: number[] | null;
  upper: number[] | null;
  sources: StoreStanding[];
  navDims: string[];
  nav: number[];
};

/** Where one store landed in the engine, as far as it has been read. */
function standingOf(source: LayerDataSource, url: string | null): StoreStanding {
  const state = source.loadState;
  const loaded = state && "transform" in state ? state : null;
  const landed = loaded?.transform.outputSpace.value;
  return {
    url,
    matrix: loaded ? Array.from(loaded.transform.value.transform) : null,
    error: state?.error?.message ?? null,
    dims: landed ? Array.from(landed.names) : null,
    scales: landed ? Array.from(landed.scales) : null,
    units: landed ? Array.from(landed.units) : null,
    lower: landed?.bounds ? Array.from(landed.bounds.lowerBounds) : null,
    upper: landed?.bounds ? Array.from(landed.bounds.upperBounds) : null,
    // Which convention the engine says this source counts in, per axis: true
    // means integer coordinates fall on voxel centres. Kept for measurements only.
    voxelCenterAtIntegerCoordinates: landed?.bounds
      ? Array.from(landed.bounds.voxelCenterAtIntegerCoordinates)
      : null,
  };
}

/** The handle the canvas drives this engine with. */
export type EngineViewer = ReturnType<typeof handleFor>;

function handleFor(own: Own) {
  return {
    /**
     * Grow stable acquisition rows in place. Returns false when their shape
     * changed and the caller therefore needs to open a different scene.
     */
    addSources(acquisitions: Acquisition[]) {
      return addSourcesToTheOpenRows(own, acquisitions);
    },

    /** Move the view. `centre` is in micrometres, `zoom` in µm per screen pixel. */
    setView(view: { centre?: XY; zoom?: number }) {
      const viewer = viewerOf(own);
      if (viewer) writeTheView(viewer, view);
    },

    /** The view now on screen, in the same units. */
    getView() {
      return readTheView(viewerOf(own));
    },

    /** The visible flat rectangle, normalized for the viewer's measure API. */
    measurementBox() {
      const viewer = viewerOf(own);
      return viewer ? whatIsOnScreen(viewer) : null;
    },

    /**
     * Which plane of the stack to show, in micrometres along the depth axis.
     *
     * Moving through the stack lives on a slider rather than on a gesture,
     * where it is visible and labelled — see `CONTROLS.md`.
     */
    setPlane(z: number) {
      const viewer = viewerOf(own);
      if (!viewer) return;
      const depth = theDepthOnScreen(viewer);
      const space = viewer.navigationState.position.coordinateSpace.value;
      if (depth < 0 || !space) return;
      const umPerVoxel = space.scales[depth] * UM_PER_M;
      if (!(umPerVoxel > 0)) return;
      moveAlong(viewer, depth, z / umPerVoxel);
    },

    /**
     * How long the timelapse is, so a page can offer a way along it: how many
     * moments, and which one is on screen, counted from the first. Nothing
     * when there is only one moment: a single frame is not a timelapse.
     */
    theMomentsItCanShow() {
      const time = theTimeAxis(viewerOf(own));
      if (!time) return null;
      const many = time.max - time.min + 1;
      if (!(many > 1)) return null;
      return { many, at: Math.min(Math.max(Math.round(time.value - time.min), 0), many - 1) };
    },

    /** Which moment of a timelapse to show, counted from the first. */
    setMoment(t: number) {
      const viewer = viewerOf(own);
      const time = theTimeAxis(viewer);
      if (viewer && time) moveAlong(viewer, time.index, time.min + t);
    },

    /**
     * Draw the acquisitions, or do not — the viewer stays open either way.
     *
     * Turning the picture off used to mean opening the canvas again with no
     * acquisitions at all, and on this engine that does not work: neuroglancer
     * takes its axes from its image layers, so with no images there is nothing
     * to take them from and opening never finishes. Measured from the page, both
     * presses of the button cost 26.7 seconds and the picture never went off —
     * the wait ran out, the page gave up and put the picture back.
     *
     * Hiding the layers instead costs one frame, in both directions, and keeps
     * everything the engine has decoded, so the picture comes back without a
     * single request. What is deliberately *not* changed is which channels the
     * operator had switched off: they stay off when the picture comes back, so
     * this is a switch over the whole picture rather than a way of losing what
     * was set.
     */
    showPicture(on?: boolean) {
      own.showingPicture = on !== false;
      drawTheRows(own);
    },

    /**
     * Change one channel: whether it shows, what colour it is drawn in, and the
     * brightness window applied to it.
     *
     * `index` counts across all the acquisitions in the order they are drawn,
     * which is the order they appear in a list on screen. A channel switched on
     * while the whole picture is off stays off on screen, and comes on with the
     * picture. Everything travels as values for controls the compiled program
     * declares — the colour included — so no change here recompiles it.
     */
    setChannel(index: number, { visible, colour, window: brightness, weight, gamma }: {
      visible?: boolean; colour?: number[]; window?: Span; weight?: number; gamma?: number;
    } = {}) {
      for (const row of own.rows.filter(one => one.controlIndex === index)) {
        if (visible !== undefined) row.visible = visible;
        if (colour) row.colour = colour;
        if (brightness) row.window = brightness;
        /* `weight` is the channel's own opacity, an extension the viewer's
           panel uses. */
        if (weight !== undefined) row.weight = weight;
        if (gamma !== undefined) row.gamma = gamma;
      }
      drawTheRows(own);
    },

    /**
     * Every row's standing, for a measurement. What a test needs when
     * a layer is invisible and nothing on screen says why: whether the
     * engine holds it, what space it landed in, and where the view stands.
     */
    layersForMeasurement() {
      const viewer = viewerOf(own);
      const space = viewer?.navigationState.position.coordinateSpace.value;
      const channels = new Map<number | undefined, ChannelStanding>();
      for (const row of own.rows) {
        const managed = viewer?.layerManager.getLayerByName(row.layerName);
        const sources = (managed?.layer?.dataSources ?? [])
          .map((source, at) => standingOf(source, row.sources[at] ?? null));
        const held = channels.get(row.controlIndex);
        if (held) {
          held.sources.push(...sources);
          continue;
        }
        const first = sources[0];
        channels.set(row.controlIndex, {
          name: row.logicalName,
          visible: managed?.visible,
          window: row.window,
          weight: row.weight ?? 1,
          matrix: first?.matrix ?? null,
          error: first?.error ?? null,
          dims: first?.dims ?? null,
          scales: first?.scales ?? null,
          units: first?.units ?? null,
          lower: first?.lower ?? null,
          upper: first?.upper ?? null,
          sources,
          navDims: Array.from(space?.names ?? []),
          nav: Array.from(viewer?.navigationState.position.value ?? []),
        });
      }
      return [...channels].sort(([a], [b]) => (a ?? 0) - (b ?? 0)).map(([, row]) => row);
    },

    /** Close the viewer and let go of everything it was holding. */
    destroy() {
      if (own.destroyed) return;
      own.destroyed = true;
      own.watchSize?.disconnect();
      for (const stop of own.stopFollowingTheAxes) stop();
      own.stopFollowingTheAxes = [];
      own.rows = [];
      own.engine?.dispose();
      own.engine = null;
      own.engineHost.remove();
    },
  };
}
