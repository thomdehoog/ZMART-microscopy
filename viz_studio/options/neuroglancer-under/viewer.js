/**
 * Option A: neuroglancer draws the acquisition in a canvas of its own, and the
 * operator's drawing sits exactly on top of it with holes cut where the picture
 * should show.
 *
 * This file is the only place in the whole application that knows neuroglancer
 * exists. Everything around it — the page, the two gestures in `../gestures.js`,
 * the carrier outline, the tile rectangles, the measurements — is written
 * against the small interface in
 * `../contract.md` and would work just as well with a different engine
 * underneath. That is deliberate, and it is worth saying why it is worth the
 * trouble.
 *
 * Every import below comes from a folder the neuroglancer package itself calls
 * `unstable`, which is its way of saying "these are our insides and we may move
 * them". Scattered across an application, that promise is frightening: an
 * upgrade moves one file and a dozen places stop compiling, in a dozen different
 * ways, none of which mention neuroglancer. Gathered into one module it is
 * merely a chore: the upgrade breaks this file and the test that exercises it,
 * both of which are about neuroglancer and nothing else, and the rest of the
 * application does not notice.
 *
 * **So please do not import anything from `neuroglancer/unstable/...` anywhere
 * but here.** There is a check that nobody has:
 * `test_the_engine_stays_behind_its_adapter`, in
 * `viz_studio/tests/test_the_options_hold_together.py`.
 *
 * ## What this file does differently from `frontend/src/engine.js`
 *
 * Six things, and each one is fixing something that made the older integration
 * awkward rather than being a matter of taste.
 *
 * 1. **Nothing lives in a module variable.** The older engine module keeps the
 *    addresses it has handed over, the counts it has seen and the queue of
 *    stores still to feed in variables belonging to the file itself, which means
 *    a page can hold exactly one viewer. Here every one of those lives on the
 *    instance, so two viewers can sit side by side — an overview and a detail
 *    scan, or the same run before and after a change — and neither disturbs the
 *    other. It also makes closing one genuinely close it.
 *
 * 2. **Addresses are passed in, never worked out.** The older scene builder puts
 *    `window.location.origin` in front of every store's address. That is right
 *    almost always and wrong exactly when it matters: served from somewhere
 *    else, or measured against a server on a port chosen at run time, it
 *    silently reads from the wrong place. Here the caller says where the data
 *    is, and an address without a scheme is refused outright rather than
 *    quietly never fetched — which is what neuroglancer does with one, with no
 *    error and no request. That was measured on the sandwich probe, whose
 *    write-up is `viz_studio/SANDWICH.md` — a file that is not on this
 *    branch; it lives on `claude/sandwich-probe`, commit `1277e30`, in its
 *    last section.
 *
 * 3. **The operator's drawing is repainted only from inside the engine's
 *    end-of-frame announcement**, using the view read at that instant. This is
 *    the whole discipline that makes the arrangement work: measured, it holds
 *    the two layers together to one screen pixel, where repainting as the mouse
 *    moves lets them drift by twenty-five. It is built in here rather than left
 *    to the page, so a page cannot get it wrong.
 *
 * 4. **Bindings, background colour and layout are each set in exactly one
 *    place**, at the bottom of `start`. The engine's own gesture table is
 *    emptied on purpose: in this arrangement the operator's canvas lies over the
 *    engine and catches every gesture, so the engine's defaults — the plain
 *    wheel stepping through the stack, four different ways to rotate — can never
 *    fire. `CONTROLS.md` explains why each of those had to go.
 *
 * 5. **The picture stays on screen while new tiles are being fetched.** Told
 *    that a tile may have landed, the engine on its own throws away everything
 *    it has already decoded, so the window goes empty and fills back in — every
 *    few seconds, all through a run. That is fixed here, and the section
 *    "Going back to the store for what has arrived since" explains both the
 *    fault and what the engine does and does not give us to fix it with.
 *
 * 6. **The picture is placed where the store says it is.** Our writer says where
 *    an image sits by giving the corner of its first voxel; the engine reads the
 *    same description as giving the middle of it, and so drew every acquisition
 *    half a voxel early — about half a screen pixel at an ordinary
 *    magnification, and four screen pixels when zoomed in to eight times full
 *    resolution. `countFromTheCornerOfTheVoxelRatherThanItsMiddle` puts that
 *    right, and says plainly what part of it a viewer cannot put right.
 *
 * ## The bottom layer, and why this option says no to it
 *
 * `viz_studio/THE_CANVAS.md` describes a canvas of three layers sharing one
 * coordinate system: the application's own drawing beneath the picture, the
 * picture in the middle, and the operator's marks above. The interface offers a
 * slot for each — `drawUnder(paint)` and `drawOver(paint)` — and this option
 * implements both, in the sense that a drawing handed to `drawUnder` really is
 * painted on a surface placed behind the engine's canvas.
 *
 * **An operator will not see it, and this option says so plainly rather than
 * pretending.** `viewer.drawsUnder` is `false` here. Neuroglancer forces the
 * whole of its canvas opaque at the end of every frame, so a surface behind it is
 * never seen at all: measured, with one colour painted behind the engine and
 * another set as the engine's own background, an operator saw 0% of the colour
 * behind and 97% of the engine's background over ground nobody had imaged.
 *
 * The tempting thing to do instead would be to draw the bottom layer *above* the
 * engine with holes cut in it wherever the run has imaged, so that the page looks
 * the same as it does under an engine that can honour the slot. That is not done,
 * and the reason is worth stating: two options that looked identical while doing
 * entirely different things underneath would make the comparison a lie, and a
 * silent difference of exactly that kind is what this whole exercise exists to
 * avoid. An application that needs something beneath the picture on this engine
 * has a different route — put it *inside* the engine as an image or label layer,
 * which does work and is written up in `viz_studio/THE_CANVAS.md`, along with
 * what it costs.
 */

import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import {
  setDefaultInputEventBindings,
} from "neuroglancer/unstable/ui/default_input_event_bindings.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import { makeMinimalViewer } from "neuroglancer/unstable/ui/minimal_viewer.js";
import { makeLayer, deleteLayer } from "neuroglancer/unstable/layer/index.js";
import "neuroglancer/unstable/ui/default_viewer.css";
import "./engine-chrome.css";
// The two gestures, from the one copy every option shares. See `../gestures.js`
// for why there is only one copy and what it costs to have three.
import { onlyPanAndZoom } from "../gestures.js";
import { theRangeAStoreHolds } from "../brightness.js";
// And where to open looking, which the engines disagree about by a factor of
// twenty if left to themselves. See `../opening-view.js`.
import { theViewThatShowsAllOf } from "../opening-view.js";
// And which plane of a stack to open on. This engine's own default is the
// middle of the volume, which is the same answer — but agreeing by coincidence
// is not agreeing. See `../planes.js`.
import { theMiddlePlaneOf } from "../planes.js";
// And where the specimen sits in the ground the run declared. This engine
// keeps the store to itself, so it is read here the way the window is.
import { whereTheSpecimenIsInThisStore } from "../where-the-specimen-is.js";

/**
 * Which of the engine's panel layouts to ask for, and which way round the axes
 * are handed over.
 *
 * These two go together and must be changed together. The engine decides what
 * goes across the window, what goes down it and what goes into the screen from
 * the order of the axis list *and* the named layout, and the two interact.
 * Handing the axes over widest-first and asking for `xy` puts width across the
 * window running to the right, height down it, and depth into the screen — the
 * plane an operator scrolls through, drawn the way round the specimen really is.
 *
 * The other pairing that also looks right — declared order with the layout `yz`
 * — draws every picture as a mirror image, and nothing anywhere reports it. That
 * shipped for months. `CONTROLS.md` §1a tells the story, and
 * `tests/test_the_picture_is_not_mirrored.py` is what stops it coming back.
 */
const FLAT_LAYOUT = "xy";

/* And the arrangement for looking at the whole stack at once.
 *
 * The engine draws a volume by ray-casting through the layers it already holds,
 * so this is a change of layout and a mode on each layer rather than anything
 * being loaded again — which is why the switch is instant and why it costs
 * nothing to offer. The same two names are what the standalone viewer switches
 * between; see `viz_studio/frontend/src/App.jsx`.
 */
const VOLUME_LAYOUT = "3d";

/** How much to lift a volume's brightness over what suits the flat picture. */
const A_VOLUME_NEEDS_LIFTING = 3;

/** Metres to micrometres. The store speaks metres; the operator speaks µm. */
const UM_PER_M = 1e6;

/**
 * How far outside the imaged ground the engine is still allowed to draw, in
 * browser pixels, when the drawn region is bounded to the coverage record.
 *
 * Some slack rather than none, for two reasons. The record counts in whole
 * voxels and the screen in fractional pixels, so an exact fit would leave a
 * hairline of page colour along an edge as the view moved. And a page that draws
 * something around the edge of the picture — a frame, a label — has somewhere to
 * put it. Sixty-four pixels costs a handful of extra requests against the
 * hundreds that bounding saves.
 */
const SLACK_AROUND_THE_IMAGED_GROUND = 64;

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
 *   `coverage`      the imaged regions, as `zmart_storage/coverage.py` records
 *                   them, or `null` when the run keeps no record. Used to decide
 *                   where the picture is allowed to show through.
 *   `background`    the page colour, as CSS text, so the seam between the two
 *                   drawing surfaces never shows.
 *   `onViewChanged` called whenever the view settles, with the same record
 *                   `whereThingsAreDrawn()` gives back: the centre and zoom in
 *                   micrometres, the size of the box, and `project`/`unproject`
 *                   for placing ordinary HTML elements in the same coordinates.
 * @returns {Promise<Viewer>} the handle; see `../contract.md` for what it offers.
 *
 * It can fail in two ways worth knowing about: an address without a scheme is
 * refused straight away, and an acquisition that never says how big its voxels
 * are leaves the promise unresolved until the caller gives up. Both are far
 * better than the alternative, which is a viewer that opens onto nothing and
 * says everything is fine.
 */
export async function openViewer(element, options = {}) {
  const {
    acquisitions = [],
    coverage = null,
    background = "#000000",
    onViewChanged = null,
    // Whether to give the engine only the part of the window that covers ground
    // the run actually imaged. On by default wherever there is a record to go
    // on, because it is the single largest saving in the whole arrangement:
    // measured on a sparse canvas, a complete redraw went from 256 requests to
    // 25 and from 1.30 seconds to 0.20 on a delay standing in for a network
    // share, and the requests that went away were exactly the ones asking about
    // ground nobody had been to. There is nothing lost by it, because the holes
    // in the operator's drawing are the only place the picture shows anyway.
    //
    // It can be turned off, and one measurement does turn it off, so that the
    // saving can be shown rather than asserted.
    boundToCoverage = true,
  } = options;

  for (const acquisition of acquisitions) {
    if (!/^[a-z]+:\/\//i.test(acquisition.url || "")) {
      throw new Error(
        `the acquisition "${acquisition.name}" was given the address ` +
          `"${acquisition.url}", which has no scheme or host in it. ` +
          "Neuroglancer accepts such an address, builds the layer, raises no " +
          "error and then never fetches anything at all, so this is refused " +
          "here instead. Pass the whole address, including http:// and the host.",
      );
    }
  }

  // Everything the viewer knows lives in this one object, and it goes away when
  // the viewer does. Nothing is kept in a variable belonging to this file.
  const own = {
    element,
    coverage,
    background,
    onViewChanged,
    boundToCoverage: boundToCoverage && Boolean(coverage?.regions?.length),
    // The rectangle within the box the engine is currently drawing in, in
    // browser pixels. The whole box unless the drawn region is being bounded.
    engineRect: null,
    // The view the page last asked for, in micrometres. Kept because the patch
    // the engine is given is worked out from where the view is going rather than
    // from where it has been.
    wanted: null,
    engineHost: null,
    overlay: null,
    context: null,
    // The surface the application's own drawing goes on when it is meant to sit
    // *beneath* the picture, and the drawing function for it. Both stay empty
    // until a page actually asks for a bottom layer, so a page that never uses
    // one costs exactly what it did before there was one.
    beneath: null,
    beneathContext: null,
    paintBeneath: null,
    viewer: null,
    // The two gestures, listening on the box. Put on when the viewer opens and
    // taken off again when it closes, so a page that embeds this canvas gets
    // dragging and the wheel without writing a line and without having to
    // remember to tidy anything up.
    gestures: null,
    // The channels, flattened across all acquisitions in the order they are
    // drawn, each remembering the engine layer that draws it.
    rows: [],
    paint: null,
    stopFollowing: null,
    watchSize: null,
    // How to stop listening for an acquisition's data arriving. Kept so that
    // closing the viewer really lets go of everything; see
    // `countFromTheCornerOfTheVoxelRatherThanItsMiddle` for what the listening
    // is for.
    stopWatchingTheSources: null,
    // The pieces of picture that have been superseded but are still on screen,
    // one set of piece names per source the engine reads from. See
    // `keepShowingThePictureWhileTheNewOneArrives` for what they are for; the
    // short version is that they are the picture an operator is looking at
    // while its replacement is being fetched, and letting go of them is exactly
    // the thing that used to make the window flash empty.
    superseded: new Map(),
    // How to put the engine's own handling of arriving pieces back the way it
    // was. Called when the viewer closes.
    stopHoldingOn: null,
    // How many times the operator's drawing has been repainted, and how many
    // frames the engine has announced. Kept because a measurement has to be
    // able to tell "the drawing never moved" from "the drawing moved to the
    // wrong place", and on screen those look identical.
    counted: {
      overlayPaints: 0, groundPaints: 0, enginePaints: 0, letGoes: 0, lastAsked: 0,
    },
    destroyed: false,
  };

  buildTheTwoSurfaces(own);
  await start(own, acquisitions);
  // The two gestures go on last, once there is something for them to move. The
  // three lines below are word for word the same in every option, because they
  // have to be: if the three wired up dragging even slightly differently, a
  // difference in how they feel would be a difference in the wiring rather than
  // in the engines, and the whole comparison would stop meaning anything.
  own.gestures = onlyPanAndZoom(element, {
    getView: () => readTheView(own),
    setView: (view) => writeTheView(own, view),
  });
  return handleFor(own);
}

// ---------------------------------------------------------------------------
// The two surfaces
// ---------------------------------------------------------------------------
//
// Five of the pieces below — `fitTheSurfaces`, `makeTheSurfaceBeneath`,
// `imagedBounds`, `howThingsArePlaced` and `repaint` — are word for word the
// same in this file and in `../viv-under/viewer.js`.
// That is on purpose and it is not tidy. The two options are the same
// arrangement with a different engine in the middle, so the parts that are
// not about the engine have to be identical or a reader could not tell an
// engine difference from a wiring difference — which is the whole reason
// this comparison exists. Two copies can drift apart, though, so **if you
// change one of those five, change the other file to match in the same
// commit.** Whether they should instead live in one shared module is a real
// question and `../README.md` sets out what it would cost.

/**
 * Put the engine's canvas down and the operator's canvas exactly on top of it.
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
 * the mouse rather than merely covered by something. The two gestures this file
 * puts on the box are the only ones there are, and they reach it because
 * nothing inside the box takes them first.
 */
function buildTheTwoSurfaces(own) {
  const { element } = own;
  // Only set when it has not been decided already, so a page that has laid its
  // own box out is left alone. Absolute positioning inside needs *something*
  // positioned outside it, and `static` is the one value that will not do.
  if (getComputedStyle(element).position === "static") {
    element.style.position = "relative";
  }
  element.style.background = own.background;

  own.engineHost = document.createElement("div");
  own.engineHost.className = "zmart-engine-underneath";
  Object.assign(own.engineHost.style, {
    position: "absolute",
    inset: "0",
    // One above the surface the bottom layer would go on, and one below the
    // operator's own. The three numbers are the three layers of
    // `viz_studio/THE_CANVAS.md`, in order, written down in one place.
    zIndex: "1",
    pointerEvents: "none",
  });

  own.overlay = document.createElement("canvas");
  own.overlay.className = "zmart-operators-drawing";
  Object.assign(own.overlay.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    zIndex: "2",
    // Without this a drag on a touchpad scrolls the page instead of panning the
    // view, and the two gestures stop being the only two.
    touchAction: "none",
  });

  element.appendChild(own.engineHost);
  element.appendChild(own.overlay);
  own.context = own.overlay.getContext("2d");
  fitTheSurfaces(own);

  // The window can be resized, and the engine's drawing area is sized by writing
  // plain pixel numbers onto its element. Written once and never again, a
  // resized window leaves the engine drawing at the old size — and two surfaces
  // that disagree about how large the window is disagree about everything that
  // follows from it.
  own.watchSize = new ResizeObserver(() => {
    if (own.destroyed) return;
    fitTheSurfaces(own);
    // The view is written again as well as the surfaces being resized, because
    // where the engine's patch sits within a differently sized window is a
    // different place, and the offset that follows from it has to be redone.
    if (own.viewer && own.wanted) writeTheView(own, own.wanted);
    // Repainted from the view the engine last drew with rather than anything
    // newer, because that is still the picture on screen.
    repaint(own);
  });
  own.watchSize.observe(element);
}

/**
 * Make both surfaces the size of the box, in real pixels as well as in the
 * browser's own.
 *
 * The operator's canvas is made as many real pixels across as the screen
 * actually has, and then everything is drawn in browser-pixel units, so a screen
 * that packs one and a half real pixels into each browser pixel gets a crisp
 * edge rather than a blurred one. This is invisible at a density of exactly one,
 * which is what makes getting it wrong so easy.
 *
 * The engine takes no account of screen density at all — measured, it draws one
 * canvas pixel per browser pixel and lets the browser scale it up. What that
 * costs is sharpness rather than registration: the geometry still agrees exactly,
 * and the picture is simply drawn at two thirds of the resolution a dense screen
 * could show. It is recorded in `viz_studio/SANDWICH.md` §7 — on the branch
 * `claude/sandwich-probe`, commit `1277e30`, rather than on this one — and it
 * is not this file's to fix.
 */
function fitTheSurfaces(own) {
  const density = window.devicePixelRatio || 1;
  const width = own.element.clientWidth;
  const height = own.element.clientHeight;
  own.overlay.width = Math.max(1, Math.round(width * density));
  own.overlay.height = Math.max(1, Math.round(height * density));
  if (own.beneath) {
    own.beneath.width = own.overlay.width;
    own.beneath.height = own.overlay.height;
  }
  own.size = { width, height, density };
  fitTheEngineToItsPatch(own);
}

/**
 * Lay down the surface the bottom layer is drawn on, the first time a page asks
 * for one.
 *
 * It goes behind the engine's canvas, which is where the bottom layer of
 * `viz_studio/THE_CANVAS.md` belongs. **It will not be seen**, because this
 * engine forces its canvas opaque at the end of every frame — see the note at
 * the top of this file, and `viewer.drawsUnder`, which says so out loud. It is
 * laid down all the same rather than quietly skipped, so that the arrangement is
 * genuinely the one described and the reason an operator sees nothing is the
 * engine rather than a page that decided not to bother.
 *
 * Made only when it is wanted. A page that never draws beneath the picture never
 * gets a third surface, never clears one every frame, and pays nothing for a
 * layer it is not using.
 */
function makeTheSurfaceBeneath(own) {
  if (own.beneath) return;
  own.beneath = document.createElement("canvas");
  own.beneath.className = "zmart-ground-beneath";
  Object.assign(own.beneath.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    zIndex: "0",
    pointerEvents: "none",
  });
  // Put in first, so it is behind both the engine and the operator's drawing
  // however the browser happens to resolve the stacking order.
  own.element.insertBefore(own.beneath, own.element.firstChild);
  own.beneathContext = own.beneath.getContext("2d");
  fitTheSurfaces(own);
}

/**
 * The imaged ground, in micrometres, out of the coverage record.
 *
 * The record counts in voxels of the full-resolution image, because that is what
 * the writer knows. Everything above this file counts in micrometres, so the two
 * are joined here, using the voxel size the record carries.
 */
function imagedBounds(coverage) {
  if (!coverage?.regions?.length) return null;
  const um = coverage.voxel_size_um || { x: 1, y: 1 };
  const xs = coverage.regions.flatMap((r) => [r.x[0] * um.x, r.x[1] * um.x]);
  const ys = coverage.regions.flatMap((r) => [r.y[0] * um.y, r.y[1] * um.y]);
  return {
    x0: Math.min(...xs), x1: Math.max(...xs),
    y0: Math.min(...ys), y1: Math.max(...ys),
  };
}

/**
 * Decide how much of the window the engine is given, and write it onto the
 * element.
 *
 * When the drawn region is bounded to the coverage record, the engine is given
 * only the part of the window that covers ground the run has actually imaged,
 * opened out a little. Everywhere else is ground nobody has been to, and asking
 * about it is where almost the whole cost of a redraw goes: on a sparse canvas
 * 247 requests out of 256 were for pieces nobody has written.
 *
 * This runs on every change of view rather than only when bounding is on, and
 * that is not tidiness. The engine's drawing area is sized by writing plain
 * pixel numbers onto its element; written once and not written again, a resized
 * window leaves the engine drawing at the old size, and two surfaces that
 * disagree about how large the window is disagree about everything that follows.
 */
function fitTheEngineToItsPatch(own) {
  const { width, height } = own.size || { width: 0, height: 0 };
  let rect = { left: 0, top: 0, width, height };
  const bounds = own.boundToCoverage ? imagedBounds(own.coverage) : null;
  const view = own.wanted;
  if (bounds && view && view.zoom > 0) {
    const toScreen = (x, y) => ({
      x: width / 2 + (x - view.centre.x) / view.zoom,
      y: height / 2 + (y - view.centre.y) / view.zoom,
    });
    const low = toScreen(bounds.x0, bounds.y0);
    const high = toScreen(bounds.x1, bounds.y1);
    const slack = SLACK_AROUND_THE_IMAGED_GROUND;
    const left = Math.max(0, Math.floor(Math.min(low.x, high.x) - slack));
    const top = Math.max(0, Math.floor(Math.min(low.y, high.y) - slack));
    const right = Math.min(width, Math.ceil(Math.max(low.x, high.x) + slack));
    const bottom = Math.min(height, Math.ceil(Math.max(low.y, high.y) + slack));
    rect = {
      left, top,
      width: Math.max(1, right - left),
      height: Math.max(1, bottom - top),
    };
  }
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
 *
 * It reaches into a field rather than calling something, because there is
 * nothing to call. If a later version of the engine renames it, this file is
 * where it breaks, and the registration measurement is what says so.
 */
function tellTheEngineItHasBeenResized(own) {
  const display = own.viewer?.display;
  if (!display) return;
  display.resizeGeneration += 1;
  display.scheduleRedraw?.();
}

// ---------------------------------------------------------------------------
// Opening the acquisitions
// ---------------------------------------------------------------------------

/**
 * Start the engine, hand it the acquisitions, and settle everything that is set
 * once.
 */
async function start(own, acquisitions) {
  own.viewer = makeMinimalViewer({
    target: own.engineHost,
    showUIControls: false,
    showTopBar: false,
    showLayerPanel: false,
    showLocation: false,
    showPanelBorders: false,
    showLayerDialog: false,
    resetStateWhenEmpty: false,
  });

  // -- the three things that are set in exactly one place, here ------------

  // Which panels are on screen. Paired with the axis order below; see FLAT_LAYOUT.
  own.viewer.layout.restoreState(FLAT_LAYOUT);

  // The engine's own furniture is off. It draws a cluster of layout buttons in
  // one corner, a panel of axis names in another, axis lines through the middle
  // and a scale bar per axis along the bottom — including one for time, which
  // looks like a distance and is not one. The page draws whichever of those it
  // wants, where it wants them, so none of this is a loss.
  own.viewer.showDefaultAnnotations.value = false;
  own.viewer.showAxisLines.value = false;
  own.viewer.showScaleBar.value = false;

  // The colour behind the picture, which is the page's own colour so that the
  // seam between the two drawing surfaces cannot be seen. This is the whole
  // point of the arrangement, and it is why the measurements deliberately use a
  // different colour: a margin you cannot see is a margin you cannot measure.
  own.viewer.crossSectionBackgroundColor.restoreState(own.background);

  // The engine's gesture table, emptied. In this arrangement the operator's
  // canvas lies over the engine and catches every gesture before the engine
  // could see one, so this is belt as well as braces — but an unbound gesture
  // and a gesture nobody tried look exactly alike, and a stacking order is one
  // stylesheet edit away from being wrong. `CONTROLS.md` sets out what each of
  // these used to do and why it had to go.
  emptyTheEnginesOwnBindings(own.viewer);

  // -- the acquisitions ---------------------------------------------------

  own.rows = await rowsFor(acquisitions);
  for (const [at, row] of own.rows.entries()) {
    const managed = makeLayer(own.viewer.layerSpecification, row.layerName, {
      type: "image",
      source: row.url,
      shader: shaderFor(row.colour),
      shaderControls: controlsFor(row),
      // How solid this layer is. The engine's own default for an image layer is
      // a half, which is right for looking through one layer at another and
      // wrong for the channels of one acquisition, because those are separate
      // colours of the same specimen rather than one picture seen through
      // another. Measured on a run recorded in two colours: with the default
      // left alone the second channel reached the screen at 118 of a possible
      // 255 where the first reached 237 — the colour the run names, drawn at
      // half strength for no reason an operator could see.
      //
      // Nothing is lost by drawing each at its full strength, because what
      // decides where a layer is see-through here is the little program the
      // engine runs on the graphics card. It emits nothing at all where the
      // stored number is nought, so ground a channel never imaged still lets the
      // layers beneath it show through.
      opacity: 1,
      /* Channels are added to one another, not painted over one another.
       *
       * They are separate colours of one specimen: a place that recorded both
       * green and red is yellow, and nothing about it is "green seen through
       * red". Stacked the ordinary way it is exactly that, because the shader
       * below is opaque wherever the stored number clears the window's floor —
       * so the channel drawn last covers every other one everywhere it has any
       * signal at all. Measured on a two-colour skin biopsy: 0.011% of the
       * window showed green against Viv's 0.029% on the same view, and Viv is
       * doing the arithmetic this asks the engine for.
       */
      blend: "additive",
      // Where a store keeps its channels inside one array, this is what picks
      // the channel out: the engine offers it as a dimension belonging to the
      // layer, and each row pins it to its own index. Nothing splits the data —
      // one store feeds every row that reads from it.
      //
      // It is said here, in the description the layer is built from, rather than
      // written onto the layer afterwards. That is not tidiness. A layer built a
      // moment ago does not yet know what dimensions its data has, so writing a
      // position into it at that point writes into a space with no room in it
      // and is simply lost. Measured before it was moved here: a run with two
      // channels drew both of its layers from the same channel, so one colour
      // was missing and the other was drawn twice.
      localPosition: [row.channelIndex],
    });
    own.viewer.layerSpecification.add(managed, at);
    row.managed = managed;
  }

  await whenTheAxesAreKnown(own.viewer);
  pinTheAxesThatMeasureDistance(own.viewer);
  startTimeAtTheFirstMoment(own.viewer);
  countFromTheCornerOfTheVoxelRatherThanItsMiddle(own);
  /* Kept on a clock until every row has settled, because a slow store (a
     linked scene takes seconds to load) has no transform to rewrite yet at
     this moment, and no signal announces the moment it does. Idempotent,
     cheap, and it puts itself down. */
  if (!everyHeightBeginsAtNought(own)) {
    own.heightsBecomeNought = setInterval(() => {
      if (everyHeightBeginsAtNought(own) && own.heightsBecomeNought) {
        clearInterval(own.heightsBecomeNought);
        own.heightsBecomeNought = null;
      }
    }, 500);
  }
  // A page may open several acquisitions at once, and they do not all arrive
  // together — the axes become known as soon as the first of them is read, so a
  // second one may still be on its way. Each layer is therefore looked at again
  // whenever its source changes. Looking twice costs nothing: the second look
  // finds the engine already counting from the corner of a voxel and leaves it
  // alone, which is why this cannot creep half a voxel further with each pass.
  own.stopWatchingTheSources = own.rows
    .map((row) => row.managed?.layer?.dataSourcesChanged?.add(
      () => {
        countFromTheCornerOfTheVoxelRatherThanItsMiddle(own);
        everyHeightBeginsAtNought(own);
      },
    ))
    .filter(Boolean);
  // The engine chooses a starting magnification the first moment it believes it
  // knows what space the picture lives in, and for a moment that is an empty
  // space in which one voxel is one metre. Clearing it now makes it choose
  // again, this time knowing how big a voxel really is. Without this the viewer
  // opens on an empty rectangle with every piece of data present and correct.
  own.viewer.navigationState.zoomFactor.reset();
  own.viewer.perspectiveNavigationState.zoomFactor.reset();

  /* Having let the engine choose again, choose for it. Left alone it opens at one
     voxel to one screen pixel, which on a 1.1 µm store drops the operator inside
     the specimen at full magnification with nothing on screen to say where they
     are. Where a run opens is not a property of an engine — `../opening-view.js`
     holds the rule, and the Viv options obey the same one. Skipped where the box
     has not been measured yet, since fitting to a box of no size would be worse
     than the engine's own guess. */
  /* Where the specimen is, so the view opens on it rather than on the middle of
     the ground the run declared — and so a volume turns about the specimen
     instead of swinging around a point outside it. One small read; nothing else
     waits on it. */
  const specimen = acquisitions.length
    ? await whereTheSpecimenIsInThisStore(acquisitions[0].url)
    : null;
  if (own.size?.width > 0 && own.size?.height > 0) {
    const ground = theGroundTheRunCovers(own);
    const showingAllOfIt = theViewThatShowsAllOf(
      ground && specimen
        ? { ...ground, specimenUm: theSpecimenInMicrometres(own, ground, specimen) }
        : ground,
      own.size,
    );
    if (showingAllOfIt) writeTheView(own, showingAllOfIt);
  }
  openOnThePlaneWhereTheSpecimenIs(own, specimen);

  // -- the repaint discipline ---------------------------------------------
  //
  // The engine announces the end of every frame, and it does so from inside its
  // own drawing function, which the browser is running as part of a single
  // animation frame. So anything painted from inside the announcement reaches
  // the screen in the same frame as the picture, rather than one frame later.
  // And the engine reads the view at the moment it draws, so the view read from
  // inside the announcement is the view it just drew with.
  //
  // That is the whole of the discipline, and it is not decoration: measured, it
  // holds the two surfaces together to one screen pixel while the view is thrown
  // about. Following the pointer instead gives twenty-five.
  own.stopFollowing = own.viewer.display.updateFinished.add(() => {
    if (own.destroyed) return;
    own.counted.enginePaints += 1;
    repaint(own);
    // The whole placement rather than only the centre and the zoom, so that a
    // page keeping ordinary HTML elements over or under the canvas can move them
    // in the same instant the picture moved. See `whereThingsAreDrawn` on the
    // handle for what it is for.
    if (own.onViewChanged) own.onViewChanged(howThingsArePlaced(own));
  });

  // -- and the rule that keeps the picture on screen during a refresh -------
  keepShowingThePictureWhileTheNewOneArrives(own);
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
//
// The four pieces below are word for word the same in all three options, on
// purpose. The three are meant to be comparable, and a difference in how they
// read the same description would show up in the results as a difference
// between the engines, which it is not. Two copies can drift apart, so **if you
// change one of these four, change the other two files to match in the same
// commit.**

/** The colour a channel is drawn in when nobody has named one. */
const WHITE = [1, 1, 1];

/**
 * The brightness range to open a channel at when neither the page nor the run
 * asked for one. It is the same range this viewer has always used in that case,
 * and it suits the twelve-bit cameras these runs are acquired on.
 */
const AN_ORDINARY_WINDOW = { low: 0, high: 4095 };

/**
 * Six hex digits, the way a run writes a colour, as the three numbers from 0 to
 * 1 the drawing works in.
 *
 * Anything that is not six hex digits is drawn white rather than refused. A
 * misspelt colour is a small blemish; refusing to open somebody's acquisition
 * over one would be a great deal worse.
 */
function colourFromTheStore(hex) {
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
function windowFromTheStore(described) {
  const range = described?.window ?? {};
  if (Number.isFinite(range.start) && Number.isFinite(range.end)) {
    return { low: range.start, high: range.end };
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
 * the picture's own channels instead would mean a second reading of the image
 * for one of the three options and none for the other two, which is exactly the
 * kind of difference between them this comparison is trying not to introduce.
 */
function channelsTheStoreDescribes(attributes) {
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
 * This is the one place where this option has to work harder than the other two,
 * and the difference is worth knowing rather than hiding. Viv hands a store's
 * whole description back alongside the picture, so the two Viv options already
 * have it in their hands and reading the channels out of it costs them nothing.
 * Neuroglancer reads the same description — it has to, in order to build a layer
 * at all — but it keeps it to itself: what it gives back is a layer, not the
 * text the layer was built from. So the only honest way for this option to learn
 * what a run calls its colours is to go and ask for the description itself. That
 * is one small request per acquisition, made once while the viewer is opening.
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
async function theRunsOwnDescription(url) {
  const bar = url.indexOf("|");
  const address = (bar < 0 ? url : url.slice(0, bar)).replace(/\/+$/, "");
  // The two versions of the format keep the description in different places.
  // Version 2 writes a small `.zattrs` file beside the picture; version 3 folds
  // the same thing into `zarr.json`, under `attributes`. Both are tried, so that
  // a run written either way opens the same.
  for (const [file, unwrap] of [
    [".zattrs", (doc) => doc],
    // Version 3 folds the description into `zarr.json` under `attributes`,
    // and OME-Zarr 0.5 folds the OME half one level further, under an `ome`
    // key that holds `multiscales` and `omero` alike — so a 0.5 store read
    // only at `attributes` answered with neither, and a run written 0.5
    // opened as a single white channel however many colours it named.
    ["zarr.json", (doc) => doc?.attributes?.ome ?? doc?.attributes ?? doc],
  ]) {
    try {
      // Never from the browser's own copy. These runs are written into while
      // somebody is watching them, and a viewer answering from a moment ago is
      // exactly what live viewing exists to avoid.
      const answer = await fetch(`${address}/${file}`, { cache: "no-store" });
      if (answer.ok) return unwrap(await answer.json());
    } catch (why) {
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
async function rowsFor(acquisitions) {
  const rows = [];
  for (const acquisition of acquisitions) {
    const itsOwnDescription = await theRunsOwnDescription(acquisition.url);
    // What the page said, where it said anything; otherwise what the run says
    // about itself; and only if the run says nothing either, one white channel.
    const described = acquisition.channels && acquisition.channels.length
      ? acquisition.channels
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
    const channels = [];
    for (const [within, channel] of described.entries()) {
      channels.push(channel.window ? channel : {
        ...channel,
        window: (await theRangeAStoreHolds(acquisition.url, { channel: within }))
          || { ...AN_ORDINARY_WINDOW },
      });
    }
    channels.forEach((channel, within) => {
      rows.push({
        url: acquisition.url,
        acquisition: acquisition.name,
        name: channel.name,
        // The engine keeps one flat list of layers and needs their names to be
        // different from one another, and two acquisitions can easily hold a
        // channel of the same name — an overview and a detail scan both
        // recording green. So the name carries both halves.
        layerName: `${acquisition.name}/${channel.name}`,
        colour: channel.colour || [...WHITE],
        window: channel.window || { ...AN_ORDINARY_WINDOW },
        // Which position along the store's channel axis this row reads from.
        // Said for every row, including a lone one, and that is worth a sentence
        // because it used not to be. Left unsaid, the engine picks a channel for
        // itself — the middle of however many the store holds — so a page that
        // named one channel of a two-channel run was shown the *second* one,
        // drawn in the colour it had asked for the first. Nothing on screen
        // could have told an operator that. The other two options have always
        // said which channel they mean, and now all three do.
        channelIndex: within,
        visible: channel.visible !== false,
        managed: null,
      });
    });
  }
  return rows;
}

/**
 * Every store's height re-based to nought, so the map can show them all.
 *
 * The canvas is a two-dimensional map of the specimen, and the engine keeps
 * one z for the whole space — so an overview captured at one height and a
 * focus stack spanning another could never be on screen together: each store
 * drew only when the shared z sat exactly on one of its own planes, and "the
 * overview is not showing up" was a focus stack holding the z somewhere
 * else. On the instrument the heights genuinely differ — the focus map is
 * micrometres of real slope — and a slice a single voxel thick forgives
 * none of it.
 *
 * So the height is taken out of the placement: each layer's z translation is
 * set to nought, the way the half-voxel corner shift above rewrites the same
 * matrix, and every acquisition then begins at the same plane. The recorded
 * heights are untouched in the stores — this bends the drawing, not the
 * data. A stack still spans its planes (from nought), and browsing them
 * walks above the flat captures; the map's own plane is the first one.
 * Idempotent, because nought written twice is nought.
 */
function everyHeightBeginsAtNought(own) {
  let settled = true;
  for (const row of own.rows) {
    const placing = row.managed?.layer?.dataSources?.[0]?.loadState?.transform;
    if (!placing?.value?.outputSpace) {
      // Not loaded yet: a slow store (a linked scene takes seconds) has no
      // transform to rewrite at the moment the axes become known, and no
      // later signal announces it — which is why the caller keeps a clock
      // on this until every row has settled.
      settled = false;
      continue;
    }
    const placed = placing.value;
    const { rank, outputSpace } = placed;
    const heightAxis = outputSpace?.names?.indexOf?.("z");
    if (heightAxis === undefined || heightAxis < 0) continue;
    const moved = Float64Array.from(placed.transform);
    const at = rank * (rank + 1) + heightAxis;
    if (moved[at] !== 0) {
      moved[at] = 0;
      placing.value = { ...placed, transform: moved };
    }
  }
  // And the map opens on that first plane, rather than wherever the engine's
  // own centring left the height standing.
  const space = own.viewer.navigationState.position.coordinateSpace.value;
  const heightAxis = space?.names?.indexOf?.("z") ?? -1;
  if (heightAxis >= 0) {
    const standing = Float32Array.from(own.viewer.navigationState.position.value);
    if (Number.isFinite(standing[heightAxis]) && standing[heightAxis] !== 0.5) {
      standing[heightAxis] = 0.5;
      own.viewer.navigationState.position.value = standing;
    }
  }
  return settled;
}

/**
 * Take away every gesture the engine binds for itself.
 *
 * The engine keeps a plain table mapping a gesture to an action, and it is ours
 * to write to. Emptying it is the one-line version of the long list in
 * `CONTROLS.md`: rotation bound four different ways, the plain wheel stepping
 * through the stack, ctrl and the wheel zooming, the right button recentring,
 * and a page-wide keyboard table whose space bar split the image into four
 * panels with no way back.
 *
 * The named tables are cleared rather than replaced, because replacing one with
 * an empty table of our own would leave whatever the engine adds in a later
 * version bound again.
 */
function emptyTheEnginesOwnBindings(viewer) {
  const tables = viewer.inputEventBindings;
  if (!tables) return;
  for (const name of Object.keys(tables)) {
    const table = tables[name];
    if (table && typeof table.clear === "function") table.clear();
    // Some of the tables are stacks of tables, and the parents are where the
    // engine's own defaults actually live.
    for (const parent of table?.parents ?? []) {
      if (parent && typeof parent.clear === "function") parent.clear();
    }
  }
}

/**
 * Wait until the images have said how big a voxel is.
 *
 * Until they have, the engine is working in a space with no axes at all, and
 * every conversion between the operator's micrometres and the screen would be
 * nonsense.
 */
function whenTheAxesAreKnown(viewer) {
  const { position } = viewer.navigationState;
  return new Promise((done) => {
    const look = () => {
      if ((position.coordinateSpace.value?.rank ?? 0) === 0) return;
      stop();
      done();
    };
    const stop = position.coordinateSpace.changed.add(look);
    look();
  });
}

/**
 * Draw the axes that measure distance, and leave the rest to the page's sliders.
 *
 * An image says what each of its axes measures. Some are places in the specimen —
 * depth, height, width — and some are not: which moment this is, or which colour
 * of light was recorded. Only the first kind belongs on screen, and the engine
 * does not know that on its own: left alone it takes the first three axes in the
 * order they were written, which for a timelapse means drawing time against
 * depth and pinning width, so the specimen is nowhere on screen and nothing
 * reports a fault.
 *
 * Which axes measure distance is not guessed at. Metres are the only unit that
 * measures distance across a specimen; seconds do not, and an axis with no unit
 * does not.
 *
 * The order matters as much as the choice, and it is paired with `FLAT_LAYOUT`
 * at the top of this file. See the note there.
 */
function pinTheAxesThatMeasureDistance(viewer) {
  const space = viewer.navigationState.position.coordinateSpace.value;
  if (!space?.names) return;
  const distances = space.names.filter((_, at) => space.units?.[at] === "m");
  if (distances.length < 2) return;
  // Width first, depth last. An OME-Zarr image lists its distance axes
  // slowest-changing first — depth, height, width — so reversing them is what
  // puts width across the window and depth into the screen.
  const facing = distances.slice(0, 3).reverse();
  try {
    viewer.navigationState.pose.displayDimensions.restoreState(facing);
  } catch {
    // An engine that will not take them leaves the view as it was rather than
    // leaving the page broken. This runs while an operator is waiting for their
    // acquisition to appear, so it must not be the thing that stops it.
  }
}

/**
 * Open a timelapse at its first moment rather than half way through it.
 *
 * The engine opens every axis in the middle, which is right for the axes that
 * measure the specimen and wrong for time: a recording is watched from the
 * beginning. It also shows on screen, because a run declares room for all the
 * moments it might record and fills them in as it goes — so the middle of a run
 * in progress is a black screen with the data sitting at the start, unseen.
 */
function startTimeAtTheFirstMoment(viewer) {
  const { position } = viewer.navigationState;
  const space = position.coordinateSpace.value;
  if (!space?.names || !space.units) return;
  const at = Array.from(space.units).indexOf("s");
  if (at < 0) return;
  // Both conventions occur — a moment sitting on a whole number, or half way
  // between two — and the first moment has to be worked out for the one in use
  // or the view lands between two frames.
  const onWholeNumbers = space.bounds.voxelCenterAtIntegerCoordinates[at];
  const lower = space.bounds.lowerBounds[at];
  const first = onWholeNumbers ? Math.ceil(lower) : Math.ceil(lower - 0.5) + 0.5;
  if (!Number.isFinite(first) || position.value[at] === first) return;
  const moved = Float32Array.from(position.value);
  moved[at] = first;
  position.value = moved;
}

/**
 * Put the picture where the store says it is, rather than half a voxel before it.
 *
 * An image has to say where in the specimen its first voxel sits, and there are
 * two ways of saying it. The writer in this project gives the **corner** of that
 * voxel: an image of one-micrometre voxels beginning at nought has its first
 * voxel covering the ground from 0 µm to 1 µm, and the coverage record beside it
 * counts the same way. The description the writer leaves in the store is read by
 * neuroglancer under the other convention, in which the number given is the
 * **middle** of the first voxel — so the engine places the whole image half a
 * voxel earlier than the writer meant. That is not carelessness on the engine's
 * part. The file format's own text says middles, and our writer says corners
 * without ever writing it down, so each is being reasonable about a description
 * that does not say.
 *
 * Half a voxel sounds like nothing, and at the magnification the engine chooses
 * for itself it very nearly is: it comes to about half a screen pixel, because
 * the engine picks whichever stored resolution puts roughly one voxel in one
 * pixel. Zoom in past the finest resolution, though, and half a voxel keeps its
 * size in the specimen while a screen pixel shrinks. Measured on this page at
 * eight times full resolution, the edge of the picture sat four screen pixels
 * away from where the operator's drawing put it — which is exactly the moment an
 * operator is asking whether a tile's picture really landed inside the square
 * they laid out.
 *
 * So the layer is moved back by half a voxel, and two things make that a
 * conversion between two stated conventions rather than a fudge. It is half a
 * voxel *of the image*, not a number of screen pixels tuned on one machine, so
 * it holds at every magnification and on a screen of any density. And it is
 * applied only where the engine has said, in `voxelCenterAtIntegerCoordinates`,
 * that it is counting from the middle of a voxel; an image it has read the other
 * way round is left exactly as it is, which also means running this twice can do
 * no harm.
 *
 * Only the two axes drawn on the window are moved. Depth and time choose which
 * plane and which moment an operator is looking at rather than where anything is
 * drawn, and shifting those by half a step would change which plane `setPlane`
 * hands back without lining anything up.
 *
 * **What this does not cure.** The engine takes its half a voxel off every
 * stored resolution separately, so a coarse level of the pyramid is placed half
 * of *its own* voxel early — one and a half micrometres for a four-micrometre
 * level built from one-micrometre data. Only the finest level can be corrected
 * from here: the coarser ones are placed once, while the description is being
 * read, and are out of reach afterwards. So a view zoomed a long way out is
 * still up to half a screen pixel out, and a view zoomed in is exact. The
 * complete cure is for the writer to say which convention it means, by giving
 * each resolution in `zmart_storage/canvas.py` a translation of half its own
 * voxel; that would also line the resolutions up with one another, which they
 * are not today.
 */
function countFromTheCornerOfTheVoxelRatherThanItsMiddle(own) {
  const space = own.viewer.navigationState.position.coordinateSpace.value;
  const shown = axesOnScreen(own.viewer);
  const drawnAcrossTheWindow = new Set(
    [space?.names?.[shown.across], space?.names?.[shown.down]].filter(Boolean),
  );
  if (!drawnAcrossTheWindow.size) return;
  for (const row of own.rows) {
    const placing = row.managed?.layer?.dataSources?.[0]?.loadState?.transform;
    if (!placing) continue;
    const placed = placing.value;
    const { rank, outputSpace } = placed;
    const moved = Float64Array.from(placed.transform);
    let anythingMoved = false;
    for (let axis = 0; axis < rank; axis += 1) {
      if (!drawnAcrossTheWindow.has(outputSpace?.names?.[axis])) continue;
      if (!outputSpace.bounds?.voxelCenterAtIntegerCoordinates?.[axis]) continue;
      // Where the image sits is the last column of the matrix, and one unit
      // along an axis is one voxel of the finest stored resolution — so half a
      // voxel is simply a half.
      moved[rank * (rank + 1) + axis] += 0.5;
      anythingMoved = true;
    }
    if (anythingMoved) placing.value = { ...placed, transform: moved };
  }
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
 */
function shaderFor(colour, { asAVolume = false } = {}) {
  void colour; // kept in the signature for the call sites; the colour travels
  //             as a control now, so a colour change never recompiles.
  /* The ZMART viewer's own programs, ported verbatim from its
     `app/page/src/scene.js` (`shaderFor`), because that is the look the
     microscope's operators have tested and know. Three things distinguish
     them from what stood here before:

     - the colour is a `color` uicontrol, not a number baked into the text,
       so changing it is a control write instead of a recompile;
     - `weight` is the channel's own opacity, multiplying the value;
     - alpha in the flat program comes from `imaged()` — an invlerp over the
       RAW value — not from the windowed one. That difference is load-bearing:
       alpha from the windowed value punched holes wherever a pixel sat below
       the window's floor, so raising MIN made the specimen see-through. */
  if (asAVolume) {
    return (
      "#uicontrol invlerp normalized\n" +
      "#uicontrol float weight slider(min=0, max=1, default=1)\n" +
      "#uicontrol invlerp imaged(range=[0, 1], clamp=false)\n" +
      '#uicontrol vec3 color color(default="white")\n' +
      "#uicontrol float attenuation slider(min=0, max=8, default=0)\n" +
      "void main() {\n" +
      "  float v = normalized();\n" +
      "  vec3 shown = color * (v * weight);\n" +
      "  float faded = exp(-attenuation * depthAtRayPosition);\n" +
      "  emitIntensity(v * weight * faded);\n" +
      "  emitRGBA(vec4(shown * faded, v * weight * faded));\n" +
      "}\n"
    );
  }
  return (
    "#uicontrol invlerp normalized\n" +
    "#uicontrol float weight slider(min=0, max=1, default=1)\n" +
    "#uicontrol invlerp imaged(range=[0, 1], clamp=false)\n" +
    '#uicontrol vec3 color color(default="white")\n' +
    "void main() {\n" +
    "  float v = normalized();\n" +
    "  vec3 shown = color * (v * weight);\n" +
    "  emitRGBA(vec4(shown, imaged() > 0.0 ? 1.0 : 0.0));\n" +
    "}\n"
  );
}

/** A colour as the engine's `color` control wants it: six hex digits. */
function hexColourFor(colour) {
  return `#${(colour ?? WHITE)
    .map((part) => Math.round(Math.min(1, Math.max(0, part)) * 255)
      .toString(16).padStart(2, "0"))
    .join("")}`;
}

/**
 * Every shader control of one row, as one whole object.
 *
 * Always restored whole, never piecewise: a partial restore is how one
 * control quietly resets another to its default. This mirrors the viewer's
 * own `shaderControlsFor` in `app/page/src/scene.js`.
 */
function controlsFor(row, { asAVolume = false } = {}) {
  const controls = {
    normalized: { range: [row.window.low, row.window.high] },
    weight: row.weight ?? 1,
    color: hexColourFor(row.colour),
  };
  if (asAVolume) controls.attenuation = row.attenuation ?? 0;
  return controls;
}


// ---------------------------------------------------------------------------
// Micrometres in, micrometres out
// ---------------------------------------------------------------------------
//
// The engine has a notion of zoom of its own, and it is not one the operator
// should ever meet. It counts in "canonical voxels per screen pixel", where a
// canonical voxel is the smallest voxel among the axes on screen — a number that
// changes meaning when a different acquisition is opened. The store and the
// stage both speak micrometres, so that is what crosses this boundary, and the
// conversion lives here and nowhere else.
//
// The arithmetic, so it can be checked rather than trusted. The engine works out
// how many voxels of an axis fall in one screen pixel as
// `zoomFactor / canonicalVoxelFactors[i]`, and `canonicalVoxelFactors[i]` is the
// size of that axis's voxel divided by the canonical one. Multiply those and the
// axis drops out: metres per screen pixel is simply
// `zoomFactor × canonicalVoxelPhysicalSize`, whichever axis you ask about.

/** Where each axis on screen sits in the image's own list, and how big it is. */
function axesOnScreen(viewer) {
  const info = viewer.navigationState.displayDimensionRenderInfo.value;
  const space = viewer.navigationState.position.coordinateSpace.value;
  const across = info.displayDimensionIndices[0];
  const down = info.displayDimensionIndices[1];
  return {
    across,
    down,
    // Micrometres per voxel along each axis on screen.
    umAcross: (space?.scales?.[across] ?? 0) * UM_PER_M,
    umDown: (space?.scales?.[down] ?? 0) * UM_PER_M,
    umPerCanonicalVoxel: info.canonicalVoxelPhysicalSize * UM_PER_M,
  };
}

/**
 * How far the middle of the engine's patch is from the middle of the window, in
 * browser pixels.
 *
 * Nought unless the drawn region is being bounded to the imaged ground. When it
 * is, the engine's patch is somewhere else in the window and its idea of "the
 * centre" is the centre of the patch — so this difference has to be added on the
 * way in and taken off on the way out, or a given point of specimen would land
 * in a different place on the window depending on whether bounding happened to
 * be on. The page must never be able to tell.
 */
function howFarThePatchIsOffCentre(own) {
  const rect = own.engineRect;
  const { width, height } = own.size || { width: 0, height: 0 };
  if (!rect) return { x: 0, y: 0 };
  return {
    x: rect.left + rect.width / 2 - width / 2,
    y: rect.top + rect.height / 2 - height / 2,
  };
}

/**
 * Whose gestures are in charge, which depends on what is being looked at.
 *
 * **Flat: ours, and only two of them.** Dragging pans, the wheel zooms, nothing
 * rotates. That is decided in `viz_studio/CONTROLS.md` and it is not a
 * preference: the operator's carrier outline and tile positions are drawn in
 * stage coordinates over the picture, and a rotated flat view breaks that
 * correspondence silently — nothing errors, the drawing simply stops lining up.
 * So the engine's own bindings are cleared when a viewer opens.
 *
 * **A volume: the engine's own.** That same document says rotation is removed
 * *from the flat view*, and that a rotated view "comes back as a deliberate
 * control" when somebody needs it. A volume is that moment. There is no flat
 * drawing to line up with, turning the specimen over is the whole point of
 * looking at one, and neuroglancer already does it properly: drag rotates,
 * shift and drag moves the centre, and the wheel is left to us so that zooming
 * needs no modifier.
 *
 * Restored and cleared rather than merged, because a half-bound engine is the
 * state nobody can reason about — every gesture then belongs to whichever of the
 * two got to it first.
 */
function handTheEngineItsOwnGestures(own) {
  if (own.showingVolume) {
    /* Ours come off entirely, and that is the part that was missing.
       
       Installing the engine's bindings is not enough on its own: our handler
       takes the pointer on `pointerdown` and calls `preventDefault`, which
       suppresses the compatibility `mousedown` the engine's bindings are written
       against. So the engine never saw a drag, our pan won, and the measurement
       said so plainly — a drag moved the flat view's centre by 900 µm and turned
       nothing. Two sets of handlers over one surface is not a thing to arbitrate;
       one of them has to go. */
    own.gestures?.stop();
    own.gestures = null;
    theTwoGesturesAVolumeNeeds(own, true);
    theWheelZoomsTheCamera(own);
    return;
  }
  own.stopTheWheel?.();
  own.stopTheWheel = null;
  theTwoGesturesAVolumeNeeds(own, false);
  emptyTheEnginesOwnBindings(own.viewer);
  own.gestures = own.gestures || onlyPanAndZoom(own.element, {
    getView: () => readTheView(own),
    setView: (view) => writeTheView(own, view),
  });
}

/**
 * Turning and moving a volume, bound by name rather than by restoring defaults.
 *
 * `setDefaultInputEventBindings` was the obvious way and does not work here, for
 * a reason worth writing down: the engine's defaults live in tables shared by the
 * whole page, and `emptyTheEnginesOwnBindings` empties those tables rather than
 * detaching them. Once emptied they stay empty, so re-adding them as parents adds
 * nothing — measured, a drag then did nothing at all rather than rotating.
 *
 * So the two gestures a volume needs are named here. It is also the smaller
 * claim: a volume gets turning and moving, and not the twenty-odd other bindings
 * the engine ships, several of which `viz_studio/CONTROLS.md` removed on purpose.
 */
function theTwoGesturesAVolumeNeeds(own, wanted) {
  const table = own.viewer.inputEventBindings?.perspectiveView;
  if (!table?.set) return;
  const turning = "at:mousedown0";
  const moving = "at:shift+mousedown0";
  if (!wanted) {
    table.delete(turning);
    table.delete(moving);
    return;
  }
  // Plain drag turns it; shift and drag moves it. That is the engine's own
  // arrangement for a three-dimensional view and what an operator asked for.
  table.set(turning, { action: "rotate-via-mouse-drag", stopPropagation: true });
  table.set(moving, { action: "translate-via-mouse-drag", stopPropagation: true });
}

/**
 * The plain wheel zooms the camera, without a modifier.
 *
 * The engine binds zoom to *control* and the wheel, and leaves the plain wheel
 * for stepping through slices — which a volume has none of. An operator turning
 * a specimen over expects the wheel to bring it closer, so the plain wheel is
 * bound here, to the camera the perspective view actually draws with.
 *
 * That is a different number from the flat view's magnification, and mixing them
 * up is what made zooming feel broken: the wheel moved `µm per pixel` from 6.45
 * to 1.07 while the specimen on screen did not change size by a single pixel,
 * because the flat view's zoom is not what a perspective camera draws with.
 */
function theWheelZoomsTheCamera(own) {
  if (own.stopTheWheel) return;
  const zoom = own.viewer.perspectiveNavigationState.zoomFactor;
  const wheel = (event) => {
    event.preventDefault();
    // The same feel as the flat view's wheel, which is one shared constant away
    // from being literally the same line; see `../gestures.js`.
    zoom.value *= Math.exp(event.deltaY * 0.0015);
  };
  own.element.addEventListener("wheel", wheel, { passive: false });
  own.stopTheWheel = () => own.element.removeEventListener("wheel", wheel);
}

/**
 * Put the view on the plane a stack should open on.
 *
 * Said rather than inherited. Left alone this engine opens in the middle of its
 * volume, which is the answer `planes.js` gives — so the three options agreed
 * because two of them were told and the third happened to. A default that changed
 * on a version bump would have shown one engine a different slice of tissue from
 * the other, and nothing in the comparison would have said so.
 */
/**
 * The specimen's position turned from voxels of the store into micrometres of
 * stage, which is what every option speaks.
 */
function theSpecimenInMicrometres(own, ground, specimen) {
  const axes = axesOnScreen(own.viewer);
  if (!(axes.umAcross > 0) || !(axes.umDown > 0)) return null;
  if (specimen.x === undefined || specimen.y === undefined) return null;
  return {
    x: ground.atUm.x + specimen.x * axes.umAcross,
    y: ground.atUm.y + specimen.y * axes.umDown,
  };
}

function openOnThePlaneWhereTheSpecimenIs(own, specimen) {
  const info = own.viewer.navigationState.displayDimensionRenderInfo.value;
  const space = own.viewer.navigationState.position.coordinateSpace.value;
  const depth = info?.displayDimensionIndices?.[2] ?? -1;
  if (depth < 0 || !space?.bounds) return;
  const planes = Math.round(
    space.bounds.upperBounds[depth] - space.bounds.lowerBounds[depth],
  );
  if (!(planes > 1)) return;
  const moved = Float32Array.from(own.viewer.navigationState.position.value);
  // Where the specimen is, where it could be found; the middle of the declared
  // stack otherwise, which is what this did before and is right when a run fills
  // the room it asked for.
  const plane = specimen?.z ?? theMiddlePlaneOf(planes);
  moved[depth] = space.bounds.lowerBounds[depth] + plane + 0.5;
  own.viewer.navigationState.position.value = moved;
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
function theGroundTheRunCovers(own) {
  const axes = axesOnScreen(own.viewer);
  const space = own.viewer.navigationState.position.coordinateSpace.value;
  const bounds = space?.bounds;
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

/** The view the engine is showing now, in micrometres. */
function readTheView(own) {
  const axes = axesOnScreen(own.viewer);
  const position = own.viewer.navigationState.position.value;
  const zoom =
    own.viewer.navigationState.zoomFactor.value * axes.umPerCanonicalVoxel;
  const off = howFarThePatchIsOffCentre(own);
  return {
    centre: {
      x: position[axes.across] * axes.umAcross - off.x * zoom,
      y: position[axes.down] * axes.umDown - off.y * zoom,
    },
    zoom,
  };
}

/** Tell the engine where to look, in micrometres. */
function writeTheView(own, asked) {
  const axes = axesOnScreen(own.viewer);
  const navigation = own.viewer.navigationState;
  const now = readTheView(own);
  const centre = asked.centre || now.centre;
  const zoom = asked.zoom > 0 ? asked.zoom : now.zoom;
  // Remembered before the patch is worked out, because the patch is worked out
  // from where the view is about to be rather than from where it was.
  own.wanted = { centre, zoom };
  fitTheEngineToItsPatch(own);
  const off = howFarThePatchIsOffCentre(own);
  if (axes.umAcross > 0 && axes.umDown > 0) {
    const position = Float32Array.from(navigation.position.value);
    position[axes.across] = (centre.x + off.x * zoom) / axes.umAcross;
    position[axes.down] = (centre.y + off.y * zoom) / axes.umDown;
    navigation.position.value = position;
  }
  if (zoom > 0 && axes.umPerCanonicalVoxel > 0) {
    navigation.zoomFactor.value = zoom / axes.umPerCanonicalVoxel;
  }
}

// ---------------------------------------------------------------------------
// The operator's own drawing
// ---------------------------------------------------------------------------

/**
 * How the canvas is placed on the screen at this instant.
 *
 * One record, worked out in one place, and used for three things: the frame each
 * of the page's two drawings is handed, the announcement when the view settles,
 * and the answer to `whereThingsAreDrawn()`. Keeping them the same object is what
 * makes an ordinary HTML element positioned from `project` land in exactly the
 * same place as a shape drawn with it.
 *
 * `project` turns micrometres into browser pixels from the top-left of the box;
 * `unproject` goes the other way, which is what a click or a drag needs.
 */
function howThingsArePlaced(own) {
  const { width, height, density } = own.size;
  const view = readTheView(own);
  return {
    centre: view.centre,
    zoom: view.zoom,
    width,
    height,
    density,
    project: (x, y) => ({
      x: width / 2 + (x - view.centre.x) / view.zoom,
      y: height / 2 + (y - view.centre.y) / view.zoom,
    }),
    unproject: (x, y) => ({
      x: view.centre.x + (x - width / 2) * view.zoom,
      y: view.centre.y + (y - height / 2) * view.zoom,
    }),
  };
}

/**
 * Repaint the page's own drawings from the view the engine has just drawn with.
 *
 * Both slots are painted from the same instant: the ground beneath the picture
 * first and the operator's marks above it second, each with the same view, the
 * same size and the same conversion from micrometres to screen pixels. That is
 * what makes all three layers move together.
 *
 * Each drawing function is handed everything it needs to place a shape in
 * micrometres and nothing that would let it ask the engine a question, which is
 * what keeps one piece of drawing code working over every option.
 */
function repaint(own) {
  if (own.destroyed) return;
  const { width, height, density } = own.size;
  const placed = howThingsArePlaced(own);
  const frameFor = (context) => ({ ...placed, context, coverage: own.coverage });
  if (own.paintBeneath && own.beneathContext) {
    const context = own.beneathContext;
    context.setTransform(density, 0, 0, density, 0, 0);
    context.clearRect(0, 0, width, height);
    own.paintBeneath(frameFor(context));
    own.counted.groundPaints += 1;
  }
  if (own.paint && own.context) {
    const context = own.context;
    context.setTransform(density, 0, 0, density, 0, 0);
    context.clearRect(0, 0, width, height);
    own.paint(frameFor(context));
    own.counted.overlayPaints += 1;
  }
}

// ---------------------------------------------------------------------------
// Going back to the store for what has arrived since
// ---------------------------------------------------------------------------
//
// **Keeping the picture on screen while it is being fetched again.** This
// section exists because of one thing an operator sees, so it is worth
// describing that first and the machinery second.
//
// While a run is going, the viewer is told every few seconds that a tile may
// have landed. Each time, it has to make the engine go back to the store,
// because nothing on disk announces a new tile — see `tilesMayHaveLanded` below
// for why. Left to itself, the engine handles that by throwing away every piece
// of picture it had already decoded and starting again from nothing, so the
// window went completely empty for about a sixth of a second and then filled
// back in. Measured: the share of the window holding picture read
// 0.2726 → 0.0000 → 0.1839 across a single refresh. On a real acquisition that
// is a flash of empty screen every few seconds, at exactly the moment the
// operator is watching most closely, and it reads as the viewer breaking rather
// than as the viewer working.
//
// **What the engine does and does not offer.** The only instruction the engine's
// background worker accepts on this subject is "let go of everything you decoded
// from this source", and a source here is one whole resolution level of one
// acquisition — there is nothing finer. So the newly imaged ground cannot be
// singled out: the refetching really is all-or-nothing, and that part is not
// ours to change.
//
// What *is* ours to change is the picture on screen while the refetching
// happens. The pieces the operator is looking at live in two places at once: the
// worker's copy, which is what the instruction above throws away, and the
// browser's own copy already uploaded to the graphics card, which is what is
// actually drawn. The engine throws both away together, and only the first of
// those two is necessary. So this keeps the second: the picture already on the
// screen stays on the screen, and each piece of it is exchanged for its
// replacement at the moment that replacement finishes downloading. Nothing is
// ever drawn from two generations of the data at once, because the exchange
// happens one piece at a time and each piece is whole.

/**
 * Keep every piece of picture already on screen until its replacement arrives.
 *
 * The engine's worker and the page talk to each other in short messages, one per
 * piece of picture: "here is a fresh piece", "that piece has gone". Among them
 * is one message with no piece named at all, which means "let go of everything
 * you decoded from this source" — and that single message is the whole of the
 * blank. This intercepts exactly that one message and answers it by remembering
 * what was on screen instead of clearing it.
 *
 * Two things then have to be tidied up, and both are done here rather than left
 * to chance.
 *
 * A piece that is kept has to be let go of at the moment its replacement lands,
 * or the graphics card would quietly hold two copies of the same picture for
 * ever. A replacement announces itself by arriving under a name that is already
 * in use, which is what the second half of this function watches for.
 *
 * And a piece that is kept but never asked for again — ground the operator has
 * scrolled away from, which the engine has no reason to fetch a second time —
 * is let go of when the *next* refresh comes round, in `tilesMayHaveLanded`.
 * That bounds what is being held to a single refresh's worth of scenery.
 *
 * **That bound is per source, and it is worth knowing what happens when there
 * are many of them.** A picture built from one store holds one store's worth,
 * which is what this was written for and is comfortably within what a graphics
 * card will keep. A picture built from a hundred stores, each handed over as a
 * source of its own, holds a hundred stores' worth at once — against the same
 * fixed budget on the card.
 *
 * Nobody has measured what that costs, and until somebody does it is only an
 * observation about how the bound is drawn, not a known fault. It is written
 * down because it is the kind of thing that would be hard to find later: if a
 * picture ever looks starved of detail on a large run, the engine's own counts
 * of what it is holding are the first place to point.
 *
 * It was briefly offered here as the explanation for a picture built from a
 * hundred separate sources coming out wrong. **That was wrong, and the real
 * cause has since been found and had nothing to do with this function.** The
 * script preparing those hundred stores deleted the placement each one carried,
 * so every tile collapsed toward the origin and piled on the others. This is
 * left as a note about a bound worth knowing, and no longer as a suspect for
 * anything.
 */
function keepShowingThePictureWhileTheNewOneArrives(own) {
  const queue = own.viewer?.chunkManager?.chunkQueueManager;
  if (!queue || typeof queue.applyChunkUpdate !== "function") return;
  const asTheEngineWouldHave = queue.applyChunkUpdate.bind(queue);

  queue.applyChunkUpdate = (message) => {
    const source = queue.rpc.get(message.source);
    if (source === undefined) return asTheEngineWouldHave(message);

    // "Let go of everything you decoded from this source." It is the only
    // message that names no piece, and `message.promise` tells it apart from the
    // one other message that names none — a direct request for a piece's
    // contents, which is a question rather than an instruction.
    if (message.promise === undefined && message.id === undefined) {
      let holding = own.superseded.get(source);
      if (holding === undefined) {
        holding = new Set();
        own.superseded.set(source, holding);
      }
      for (const piece of source.chunks.keys()) holding.add(piece);
      // Nothing on screen changed, and saying so is not a white lie: every piece
      // the engine was drawing a moment ago is still there to be drawn.
      return false;
    }

    // A replacement for a piece that is still on screen. Letting go of the old
    // one here, rather than leaving it to be overwritten, is what returns its
    // room on the graphics card.
    if (message.new && source.chunks.has(message.id)) {
      source.deleteChunk(message.id);
      own.superseded.get(source)?.delete(message.id);
    }
    return asTheEngineWouldHave(message);
  };

  own.stopHoldingOn = () => {
    delete queue.applyChunkUpdate;
    own.superseded.clear();
  };
}

/**
 * Let go of the pieces kept through the last refresh that were never replaced.
 *
 * A piece is replaced during a refresh if the engine wants to draw it, which
 * means everything the operator is actually looking at is exchanged within that
 * one refresh. What is left over is scenery: ground that was on screen at some
 * point and is not now. Holding it costs room on the graphics card that the
 * engine no longer knows about, so it is let go of when the next refresh comes
 * round, and the picture on screen does not change when it goes.
 */
function letGoOfWhatWasAlreadyReplaced(own) {
  for (const [source, holding] of own.superseded) {
    for (const piece of holding) {
      if (source.chunks.has(piece)) source.deleteChunk(piece);
    }
  }
  own.superseded.clear();
}

// ---------------------------------------------------------------------------
// The handle
// ---------------------------------------------------------------------------

function handleFor(own) {
  return {
    /** Move the view. `centre` is in micrometres, `zoom` in µm per screen pixel. */
    setView(view) {
      writeTheView(own, view);
    },

    /** The view now on screen, in the same units. */
    getView() {
      return readTheView(own);
    },

    /**
     * Which plane of the stack to show, in micrometres along the depth axis.
     *
     * Moving through the stack lives on a slider rather than on a gesture,
     * where it is visible and labelled — see `CONTROLS.md`.
     */
    /**
     * How deep the stack is, so a page can offer a way through it.
     *
     * Read out of the engine's own coordinate space, which spans every
     * acquisition it has been given, and in the same micrometres `setPlane`
     * counts in — the two are useless apart. Nothing when there is no depth to
     * speak of: a single plane is not a stack.
     */
    theDepthItCanShow() {
      const info = own.viewer.navigationState.displayDimensionRenderInfo.value;
      const space = own.viewer.navigationState.position.coordinateSpace.value;
      const depth = info?.displayDimensionIndices?.[2] ?? -1;
      if (depth < 0 || !space?.bounds) return null;
      const umPerVoxel = space.scales[depth] * UM_PER_M;
      const planes = Math.round(
        space.bounds.upperBounds[depth] - space.bounds.lowerBounds[depth],
      );
      if (!(umPerVoxel > 0) || !(planes > 1)) return null;
      /* Counted from the first plane, not from the engine's own lower bound.
         Those differ by half a voxel — this engine puts its bounds at voxel
         *edges*, so a 833-plane stack at 5 µm reports itself as starting at
         −2.5 µm — and a depth control that opens at minus two and a half
         micrometres is describing the engine's arithmetic rather than the
         specimen. It also has to match what `setPlane` below consumes, which
         counts plane k at k voxels from the store's origin, and it has to match
         what the other options answer, or the same stack is two different
         depths depending on which engine happens to be drawing. */
      const now = own.viewer.navigationState.position.value[depth];
      return {
        lowUm: 0,
        highUm: (planes - 1) * umPerVoxel,
        stepUm: umPerVoxel,
        // Where the picture is now, counted from the first plane like the rest.
        atUm: Math.max(now - space.bounds.lowerBounds[depth] - 0.5, 0) * umPerVoxel,
      };
    },

    setPlane(z) {
      const info = own.viewer.navigationState.displayDimensionRenderInfo.value;
      const space = own.viewer.navigationState.position.coordinateSpace.value;
      const depth = info.displayDimensionIndices[2];
      if (depth < 0 || !space) return;
      const umPerVoxel = space.scales[depth] * UM_PER_M;
      if (!(umPerVoxel > 0)) return;
      const moved = Float32Array.from(own.viewer.navigationState.position.value);
      moved[depth] = z / umPerVoxel;
      own.viewer.navigationState.position.value = moved;
    },

    /** Which moment of a timelapse to show, counted from the first. */
    setMoment(t) {
      const space = own.viewer.navigationState.position.coordinateSpace.value;
      if (!space?.units) return;
      const at = Array.from(space.units).indexOf("s");
      if (at < 0) return;
      const onWholeNumbers = space.bounds.voxelCenterAtIntegerCoordinates[at];
      const lower = space.bounds.lowerBounds[at];
      const first = onWholeNumbers ? Math.ceil(lower) : Math.ceil(lower - 0.5) + 0.5;
      const moved = Float32Array.from(own.viewer.navigationState.position.value);
      moved[at] = first + t;
      own.viewer.navigationState.position.value = moved;
    },

    /**
     * Change one channel: whether it shows, what colour it is drawn in, and the
     * brightness window applied to it.
     *
     * `index` counts across all the acquisitions in the order they are drawn,
     * which is the order they appear in a list on screen.
     */
    /** Whether this engine can draw the stack as a volume. */
    canShowVolume: true,

    canShowVolumeBecause:
      "neuroglancer ray-casts through the layers it already holds, so the whole "
      + "stack is drawn from what is open rather than fetched again",

    /**
     * Draw the whole stack rather than one plane of it.
     *
     * Two things at once, and both are needed: the engine is asked for its
     * three-dimensional arrangement, and every image layer is told to render as
     * a volume. Either alone gives a picture that looks like a mistake — the
     * layout without the mode shows one flat plane floating in a rotatable space,
     * and the mode without the layout changes nothing anybody can see.
     *
     * Nothing is fetched. The volume is drawn out of the pieces already decoded,
     * which is what makes this a switch rather than an operation.
     */
    showVolume(on) {
      own.showingVolume = on !== false;
      own.viewer.layout.restoreState(own.showingVolume ? VOLUME_LAYOUT : FLAT_LAYOUT);
      handTheEngineItsOwnGestures(own);
      for (const row of own.rows) {
        const layer = row.managed?.layer;
        if (!layer?.volumeRenderingMode) continue;
        layer.volumeRenderingMode.restoreState(own.showingVolume ? "on" : "off");
        /* How brightly a volume is drawn, which is a separate number from the
           window and starts at nought — so a volume drawn through a window that
           suits the flat picture comes out barely visible. Measured on a skin
           biopsy: 1.3% of the window lit as a volume against 15.7% flat, with
           this untouched. It is a logarithmic gain, so a few counts is a large
           change; this is a starting point an operator should be able to move,
           and a control for it is the obvious next thing this panel wants. */
        if (layer.volumeRenderingGain) {
          layer.volumeRenderingGain.value = own.showingVolume ? A_VOLUME_NEEDS_LIFTING : 0;
        }
        // And the little program, because how a sample contributes is the whole
        // difference between a volume and a fog. See `shaderFor`. A fresh
        // program starts on its controls' defaults, so the row's own values
        // are restored right after it — whole, never piecewise.
        if (layer.fragmentMain) {
          layer.fragmentMain.value = shaderFor(row.colour, { asAVolume: own.showingVolume });
          layer.shaderControlState.restoreState(
            controlsFor(row, { asAVolume: own.showingVolume }),
          );
        }
      }
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
    showPicture(on) {
      own.showingPicture = on !== false;
      for (const row of own.rows) {
        if (!row.managed) continue;
        row.managed.setVisible(own.showingPicture && row.visible !== false);
      }
    },

    setChannel(index, { visible, colour, window: brightness, weight } = {}) {
      const row = own.rows[index];
      if (!row || !row.managed) return;
      if (visible !== undefined) row.visible = visible;
      /* A channel switched on while the whole picture is off stays off on
         screen, and comes on with the picture. Without this the page could
         contradict itself: one channel drawn over a picture that is meant not to
         be there. */
      const shouldShow = own.showingPicture !== false && row.visible !== false;
      if (row.managed.visible !== shouldShow) {
        row.managed.setVisible(shouldShow);
      }
      const layer = row.managed.layer;
      if (!layer) return;
      if (colour) row.colour = colour;
      if (brightness) row.window = brightness;
      /* `weight` is the channel's own opacity, an extension the viewer's
         panel uses; an option without it simply ignores the key. */
      if (weight !== undefined) row.weight = weight;
      if (colour || brightness || weight !== undefined) {
        // Everything travels as values for controls the compiled program
        // declares — the colour included, so no change here recompiles.
        // Restored whole, never piecewise: a partial restore is how one
        // control quietly resets another to its default.
        layer.shaderControlState.restoreState(
          controlsFor(row, { asAVolume: own.showingVolume }),
        );
      }
    },

    /**
     * Say what a drag means now.
     *
     * The canvas owns the mechanics of every gesture; the application owns what
     * a drag currently *means*. Hand over a function and dragging stops panning:
     * each drag is given to that function instead — once as it begins, once for
     * every movement of the hand, and once when the operator lets go. Hand over
     * nothing, or `null`, and dragging pans again, which is what it does until
     * somebody says otherwise.
     *
     * The function is called with `{ phase, at, screen }`: `phase` is
     * `"started"`, `"moved"` or `"finished"`, `at` is where the pointer is on
     * the stage in micrometres, and `screen` is where it is in the box in
     * browser pixels. Micrometres are what a mark on the specimen has to be
     * recorded in — a mark kept in screen pixels would slide off the sample the
     * moment the operator panned or zoomed.
     *
     * This is the whole of the mechanism, and it is deliberately no more than
     * that. Nothing here draws anything, and this option never learns *why* the
     * meaning changed. In the operator's window that is decided by the panel on
     * the right, which is where choosing a tool belongs.
     */
    handDragsTo(handler) {
      own.gestures?.handDragsTo(handler);
    },

    /**
     * Every row's standing, for a measurement — like `gesturesSoFar`, not
     * part of the interface an application would use. What a test needs when
     * a layer is invisible and nothing on screen says why: whether the
     * engine holds it, what space it landed in, and where the view stands.
     */
    layersForMeasurement() {
      const space = own.viewer.navigationState.position.coordinateSpace.value;
      return own.rows.map((row) => {
        const source = row.managed?.layer?.dataSources?.[0];
        const landed = source?.loadState?.transform?.outputSpace?.value;
        return {
          name: row.layerName,
          visible: row.managed?.visible,
          window: row.window,
          weight: row.weight ?? 1,
          matrix: source?.loadState?.transform?.value?.transform
            ? Array.from(source.loadState.transform.value.transform)
            : null,
          error: source?.loadState?.error?.message ?? null,
          dims: landed ? Array.from(landed.names) : null,
          lower: landed?.bounds ? Array.from(landed.bounds.lowerBounds) : null,
          upper: landed?.bounds ? Array.from(landed.bounds.upperBounds) : null,
          navDims: Array.from(space?.names ?? []),
          nav: Array.from(own.viewer.navigationState.position.value ?? []),
        };
      });
    },

    /**
     * The operator's own drawing.
     *
     * Hand over one function. It is called at the moment this option considers
     * correct — here, from inside the engine's end-of-frame announcement — with
     * the view that frame was drawn from. The page never knows which option is
     * underneath it, which is what makes comparing them fair.
     */
    drawOver(paint) {
      own.paint = paint;
      repaint(own);
    },

    /**
     * The application's own drawing, beneath the picture.
     *
     * The same shape of function as `drawOver`, called at the same moments with
     * the same frame, so a page writes the two the same way. Hand over `null` to
     * say there is nothing beneath, and no surface is laid down at all.
     *
     * **On this engine an operator will not see it.** Neuroglancer forces its
     * canvas opaque at the end of every frame, so the surface this paints on is
     * covered completely wherever the engine is drawing. The drawing is made all
     * the same, on a surface genuinely behind the engine's, because pretending
     * otherwise — by drawing it on top with holes cut in it — would make this
     * option look like the others while doing something quite different. Ask
     * `drawsUnder` before relying on it; it is `false` here and says why.
     */
    drawUnder(paint) {
      own.paintBeneath = paint;
      if (paint) makeTheSurfaceBeneath(own);
      repaint(own);
    },

    /**
     * Whether a drawing handed to `drawUnder` really ends up beneath the
     * picture, where an operator can see it.
     *
     * `false` here, and measured rather than assumed: with one colour painted
     * behind this engine's canvas and another set as the engine's own
     * background, an operator saw none of the colour behind and 97% of the
     * engine's background over ground nobody had imaged.
     */
    drawsUnder: false,

    /** Why, in a sentence a page can show to whoever is looking at it. */
    drawsUnderBecause:
      "neuroglancer forces the whole of its canvas opaque at the end of every " +
      "frame, so nothing placed behind it is ever seen. Anything that has to " +
      "sit beneath the picture on this engine has to go inside the engine as a " +
      "layer of its own, which means it must be written to the store first and " +
      "cannot change while somebody is watching.",

    /**
     * Where the canvas is looking, in a form good enough to place an ordinary
     * HTML element in micrometres.
     *
     * The two drawing slots take a function and give back a flat picture, which
     * is right for shapes that must stay locked to the specimen — and it is why
     * they stay locked as well as they do. But a drawing context cannot hold an
     * HTML element, so a label pinned to a tile, a menu, a handle with its own
     * event listeners, anything with a life of its own, has to be an ordinary
     * element positioned over or under the canvas.
     *
     * This is what lets an application do that in the canvas's own coordinate
     * system. `project(x, y)` turns micrometres into browser pixels measured
     * from the top-left of the box the viewer was opened inside, which is
     * exactly what `left` and `top` want; `unproject` goes back, which is what a
     * click needs. The same record is handed to `onViewChanged` every time the
     * view settles, so an element can be moved in the same instant the picture
     * moved rather than a frame later.
     *
     * Which side of the canvas such an element may go on is not a free choice,
     * and it is the same question `drawsUnder` answers: above the canvas works
     * on every option, below it only where the engine's canvas lets what is
     * behind it show through.
     */
    whereThingsAreDrawn() {
      return howThingsArePlaced(own);
    },

    /**
     * "Go and look, a tile may have arrived."
     *
     * Nothing on disk announces a new tile. The images are declared at full size
     * before any tile exists and their description is identical before and
     * after, so there is nothing for a watcher to notice. Worse, the engine
     * remembers every piece of image it has decoded **including the pieces it
     * found to be empty**, with no time limit — so a tile written into ground it
     * has already looked at is not "slow to appear", it is never fetched again
     * at all.
     *
     * The decoded pieces live in a background worker, and this sends word to
     * that worker to read them again. **The picture on screen is not disturbed
     * while that happens**: every piece the operator can see stays exactly where
     * it is and is exchanged for its replacement at the moment that replacement
     * finishes downloading. The section above
     * `keepShowingThePictureWhileTheNewOneArrives` says how, and why it had to be
     * done that way rather than by asking the engine for something finer: the
     * engine's worker has no instruction narrower than "read this whole
     * resolution level again", so the newly imaged ground cannot be singled out.
     *
     * What it costs: only the pieces actually on screen are asked for again,
     * because the engine fetches what it needs to draw and nothing else. That
     * number follows the size of the window rather than the size of the
     * specimen, so it is the same on forty terabytes as on forty megabytes.
     * Anything the operator had scrolled past is fetched again if they scroll
     * back to it, which is the price and it is a fair one.
     *
     * Returns how many of the engine's readers were sent back to the store, so
     * that a measurement can tell "it was asked and nothing happened" from "it
     * was never asked" — two failures that look identical on screen and have
     * quite different causes.
     */
    tilesMayHaveLanded({ coverage } = {}) {
      // A newer coverage record, when the caller has one.
      //
      // This is not decoration and it is not optional in practice. The record
      // says where the run has imaged, and while a run is going that answer
      // changes — that is the whole point of it. Two things are worked out from
      // it: where the operator's drawing cuts its holes, and how much of the
      // window the engine is given. Both were settled when the viewer opened,
      // so without this a tile written outside the ground the run had reached at
      // that moment is drawn nowhere and shows through nothing.
      //
      // Measured before this was here: a tile written into fresh ground never
      // appeared at all, while tiles written inside the old bounds appeared
      // straight away — which looks exactly like an engine failing to notice new
      // data and is nothing of the sort.
      if (coverage) {
        own.coverage = coverage;
        own.boundToCoverage = own.boundToCoverage
          && Boolean(coverage.regions?.length);
        if (own.wanted) writeTheView(own, own.wanted);
      }
      // Anything still being held from the last refresh is scenery the operator
      // has moved away from, so this is the moment to let it go. It happens
      // before the readers are sent back to the store rather than after, so that
      // the pieces about to be kept are not swept away along with it.
      letGoOfWhatWasAlreadyReplaced(own);
      const shared = own.viewer.chunkManager?.rpc?.objects;
      if (!shared) return 0;
      let asked = 0;
      for (const [, held] of shared) {
        if (!held || typeof held.invalidateCache !== "function") continue;
        held.invalidateCache();
        asked += 1;
      }
      own.counted.letGoes += 1;
      own.counted.lastAsked = asked;
      return asked;
    },

    /** Close the viewer and let go of everything it was holding. */
    destroy() {
      if (own.destroyed) return;
      own.destroyed = true;
      if (own.heightsBecomeNought) {
        clearInterval(own.heightsBecomeNought);
        own.heightsBecomeNought = null;
      }
      // The gestures come off first. Listeners left behind on a box that is
      // still in the page would go on answering the operator's hand after the
      // viewer they belonged to had gone. The little record of what they saw is
      // kept rather than thrown away, so that a check can still ask a closed
      // viewer whether anything reached it after it shut.
      own.gestures?.stop();
      own.watchSize?.disconnect();
      own.stopFollowing?.();
      own.stopHoldingOn?.();
      for (const stop of own.stopWatchingTheSources || []) stop();
      own.stopWatchingTheSources = null;
      own.paint = null;
      own.paintBeneath = null;
      for (const row of own.rows) {
        if (row.managed) deleteLayer(row.managed);
      }
      own.rows = [];
      own.viewer?.dispose?.();
      own.viewer = null;
      own.engineHost?.remove();
      own.overlay?.remove();
      own.beneath?.remove();
      own.beneath = null;
    },

    /**
     * How much drawing has actually happened.
     *
     * Not part of the interface an application would use, and deliberately named
     * so that it reads as what it is. The measurements need it for one narrow
     * purpose: on screen, "the drawing never moved" and "the drawing moved to
     * the wrong place" look identical when the right answer is that nothing
     * should have happened. Every number the measurements *report* still comes
     * from a photograph.
     */
    countsForMeasurement() {
      return { ...own.counted };
    },

    /**
     * What the two gestures have accepted, and what they have turned away.
     *
     * Not part of the interface an application would use, and deliberately
     * named so that it reads as what it is. The measurements need it for one
     * narrow reason: on screen, a gesture that was refused and a gesture nobody
     * made look exactly alike, so without a count a canvas that had quietly
     * stopped listening altogether would pass a check that nothing moved.
     */
    gesturesSoFar() {
      return {
        refused: { ...(own.gestures?.refused || {}) },
        accepted: { ...(own.gestures?.accepted || {}) },
      };
    },
  };
}
