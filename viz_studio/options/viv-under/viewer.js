/**
 * Option B: Viv and deck.gl draw the acquisition in a canvas of their own, and
 * the operator's drawing sits exactly on top of it with holes cut where the
 * picture should show.
 *
 * This is the same arrangement as option A — the operator's canvas above, the
 * engine's canvas below, the canvas owning every gesture — with a different
 * engine underneath. That is deliberate and it is the whole reason this option exists.
 * If A and B feel different, the difference is the engine, because nothing above
 * the engine differs at all. If they feel the same, the sandwich arrangement is
 * neutral and the choice can be made on everything else, which is a much easier
 * decision to make.
 *
 * So please read `../neuroglancer-under/viewer.js` beside this file. Most of
 * what happens here happens there too, for the same reasons, and where this file
 * says "the same as option A" it means it.
 *
 * ## The four things that genuinely differ, and why
 *
 * 1. **Nothing behind this engine's canvas is painted over.** Neuroglancer forces
 *    its canvas opaque at the end of every frame, so a surface underneath it
 *    cannot be seen at all; that is measured, and it is why the operator's plan
 *    has to be drawn on the surface *above* with holes cut in it. A deck.gl
 *    canvas is cleared to nothing rather than to a colour, so the page's own
 *    background shows through everywhere the picture is not. The engine is
 *    therefore given no background colour of its own here: the box's colour is
 *    the background, and there is no seam to hide because there is only ever one
 *    colour. Measurement 0 in the suite asks exactly this question and reports
 *    the answer for each option side by side.
 *
 *    The sandwich is still built the same way up, with holes cut above. That is
 *    on purpose: an option that quietly rearranged the layers would no longer be
 *    comparable with option A, and the comparison is the point. What the
 *    measurement shows is that this engine *would allow* the simpler
 *    arrangement, which is a real advantage of it and is reported as one.
 *
 *    Since then that advantage has been made usable rather than merely reported.
 *    The interface now has a slot for the bottom layer of
 *    `viz_studio/THE_CANVAS.md` — `drawUnder(paint)`, written exactly like
 *    `drawOver(paint)` — and this option honours it with a third canvas behind
 *    the engine's. `viewer.drawsUnder` is `true` here, and it is a measured
 *    answer rather than a claim: a colour drawn in that slot fills the window
 *    through the engine's canvas, where on option A the same drawing is seen
 *    nowhere at all.
 *
 * 2. **Room the microscope never visited would otherwise be painted black.**
 *    Viv's colouring ends by writing the picture out fully opaque, so a canvas
 *    declared to the reach of the stage arrives as a large black rectangle with
 *    a few bright patches in it. A short addition to the little program that
 *    runs on the graphics card fixes that: where nothing was recorded, nothing
 *    is drawn. See `LetTheUnimagedGroundShowThrough` below, which explains both
 *    what it does and the one thing it cannot tell apart.
 *
 * 3. **The engine is given a patch of its own canvas rather than a smaller
 *    canvas.** Option A bounds the region the engine draws by shrinking the
 *    engine's element to fit the imaged ground, and pays for it: neuroglancer
 *    only re-reads its own size after the browser reports a resize, which is
 *    after it has already drawn a frame at the old size, and that cost 69 screen
 *    pixels of misregistration until it was worked around. deck.gl accepts a
 *    rectangle *within* its canvas as the region to draw in, and re-reads its own
 *    size at the start of every frame in any case, so the canvas here is never
 *    resized and the trap does not arise.
 *
 * 4. **Telling it a tile has landed means handing it a fresh reader.** Nothing on
 *    disk announces a new tile — the images are declared at full size before any
 *    tile exists and their description is identical before and after — so
 *    something has to tell the viewer to look again. Neuroglancer is told by
 *    being asked to let go of the pieces of image it has decoded. Viv has no such
 *    request, so the store is opened afresh and the new reader handed to the
 *    layer, which drops its own store of tiles and fetches again. That is
 *    structurally heavier, and `tilesMayHaveLanded` says so at length.
 *
 * ## What is not here
 *
 * Nothing lives in a variable belonging to this file. Everything belongs to the
 * viewer, so a page can hold two of them — an overview and a detail scan, or the
 * same run before and after a change — and neither disturbs the other. There is
 * a check for it in `viz_studio/tests/test_the_options_hold_together.py`.
 *
 * And no address is worked out here. The caller says where the data is, whole,
 * including the scheme and the host. See the note in option A for why that
 * matters more than it sounds.
 */

// Viv is published both as one package, `@hms-dbmi/viv`, and as the handful of
// smaller packages that make it up. The smaller ones are used here on purpose:
// the single package also carries Viv's ready-made React viewers, and this
// option draws into a canvas of its own with no React anywhere near it. Taking
// only the three pieces that are actually used keeps a page that opens this
// option from carrying an interface it will never show.
import { Deck, LayerExtension, OrthographicView } from "@deck.gl/core";
import { Matrix4 } from "@math.gl/core";
import { ColorPaletteExtension } from "@vivjs/extensions";
import { MultiscaleImageLayer } from "@vivjs/layers";
import { loadOmeZarr } from "@vivjs/loaders";
// The two gestures, from the one copy every option shares. See `../gestures.js`
// for why there is only one copy and what it costs to have three.
import { onlyPanAndZoom } from "../gestures.js";

/**
 * How far outside the imaged ground the engine is still allowed to draw, in
 * browser pixels, when the drawn region is bounded to the coverage record.
 *
 * The same number as option A uses, for the same two reasons. The record counts
 * in whole voxels and the screen in fractional pixels, so an exact fit would
 * leave a hairline of page colour along an edge as the view moved; and a page
 * that draws a frame or a label around the edge of the picture has somewhere to
 * put it. Sixty-four pixels costs a handful of extra requests against the
 * hundreds that bounding saves.
 */
const SLACK_AROUND_THE_IMAGED_GROUND = 64;

/**
 * How dim a spot may be before it is treated as ground nobody has been to.
 *
 * Two per cent of the brightness window. The same number and the same meaning as
 * in `../viv-inside/viewer.js`; see `LetTheUnimagedGroundShowThrough` below for
 * what this is really asking and what it cannot tell apart.
 */
const AS_GOOD_AS_NOTHING = 0.02;

/**
 * How the store's own description spells the size of a voxel, and what that is
 * in micrometres.
 *
 * A store says how large its voxels are and in what unit, and both spellings of
 * every unit occur in the wild — an instrument that writes "um" and one that
 * writes "micrometer" are describing the same thing. Anything not listed here is
 * treated as micrometres and noted on the browser's console, because refusing to
 * open an acquisition over a spelling would be a much worse outcome than drawing
 * it and saying so.
 */
const UM_PER_UNIT = {
  meter: 1e6, metre: 1e6, m: 1e6,
  millimeter: 1e3, millimetre: 1e3, mm: 1e3,
  micrometer: 1, micrometre: 1, micron: 1, um: 1, "µm": 1,
  nanometer: 1e-3, nanometre: 1e-3, nm: 1e-3,
};

/**
 * Open a viewer inside `element` and return the handle used to drive it.
 *
 * @param {HTMLElement} element  where the viewer draws; it fills this box
 * @param {object} options
 *   `acquisitions`  `[{ url, name, channels }]`, drawn in order with the first
 *                   at the bottom. Each `url` must be a whole address including
 *                   the scheme and host. `channels` is `[{ name, colour, window }]`,
 *                   where `colour` is three numbers from 0 to 1 and `window` is
 *                   `{low, high}` in the stored numbers' own units. It is
 *                   **optional**: leave it out and the viewer reads the run's own
 *                   description of its colours out of the store it is opening
 *                   anyway. Say it and what you say is used unchanged.
 *   `coverage`      the imaged regions, as `zmart_storage/coverage.py` records
 *                   them, or `null` when the run keeps no record. Used to decide
 *                   where the picture is allowed to show through, and how much
 *                   of the window is worth asking the engine to draw.
 *   `background`    the page colour, as CSS text. Painted on the box itself; the
 *                   engine paints no background of its own, so there is no seam.
 *   `onViewChanged` called whenever the view settles, with the same record
 *                   `whereThingsAreDrawn()` gives back: the centre and zoom in
 *                   micrometres, the size of the box, and `project`/`unproject`
 *                   for placing ordinary HTML elements in the same coordinates.
 * @returns {Promise<Viewer>} the handle; see `../contract.md` for what it offers.
 *
 * It can fail in two ways worth knowing about. An address without a scheme is
 * refused straight away rather than quietly read from the wrong place. And an
 * acquisition whose description cannot be read at all is refused with the
 * reason, rather than opening onto an empty window that looks like a slow one.
 */
export async function openViewer(element, options = {}) {
  const {
    acquisitions = [],
    coverage = null,
    background = "#000000",
    onViewChanged = null,
    // Whether to give the engine only the part of the window that covers ground
    // the run actually imaged. On by default wherever there is a record to go
    // on, because asking about ground nobody has been to is where most of the
    // cost of a redraw goes. One measurement turns it off, so that the saving
    // can be shown rather than asserted.
    boundToCoverage = true,
  } = options;

  for (const acquisition of acquisitions) {
    if (!/^[a-z]+:\/\//i.test(acquisition.url || "")) {
      throw new Error(
        `the acquisition "${acquisition.name}" was given the address ` +
          `"${acquisition.url}", which has no scheme or host in it. An option ` +
          "may not work an address out from the page's own address, because " +
          "that is right almost always and wrong exactly when it matters — " +
          "served from somewhere else, or measured against a server on a port " +
          "chosen at run time. Pass the whole address, including http:// and " +
          "the host.",
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
    // the engine is given is worked out from where the view is going rather
    // than from where it has been, and because it is the honest answer to
    // "where are we" before the engine has drawn its first frame.
    wanted: null,
    size: { width: 0, height: 0, density: 1 },
    engineHost: null,
    engineCanvas: null,
    overlay: null,
    context: null,
    // The surface the application's own drawing goes on when it is meant to sit
    // *beneath* the picture, and the drawing function for it. Both stay empty
    // until a page actually asks for a bottom layer, so a page that never uses
    // one costs exactly what it did before there was one.
    beneath: null,
    beneathContext: null,
    paintBeneath: null,
    deck: null,
    // The two gestures, listening on the box. Put on when the viewer opens and
    // taken off again when it closes, so a page that embeds this canvas gets
    // dragging and the wheel without writing a line and without having to
    // remember to tidy anything up.
    gestures: null,
    view: null,
    // One entry per acquisition, each holding the pyramid of readers, how large
    // its voxels are, and where it sits relative to the first acquisition.
    images: [],
    // The channels flattened across all acquisitions in the order they are
    // drawn, so that `setChannel(index, …)` is a single sensible number for the
    // page to hold — one line per thing that can be switched on and off.
    rows: [],
    paint: null,
    watchSize: null,
    // A refresh already under way, and whether another was asked for while it
    // ran. Only one read of the store at a time: two overlapping reads leave
    // parts of two different generations of the data on screen at once, which
    // the live-tiles work in this repository has already met once.
    readingAgain: null,
    anotherLookIsWanted: false,
    // How much drawing has actually happened. Kept because a measurement has to
    // be able to tell "the drawing never moved" from "the drawing moved to the
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
// same in this file and in `../neuroglancer-under/viewer.js`.
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
 * The same arrangement as option A, and the same two pieces of styling that were
 * learned the hard way there. The engine's box is given a stacking order of its
 * own so that nothing the engine creates inside it can escape and end up above
 * the operator's drawing; and it is made transparent to the mouse, so the two
 * gestures this file puts on the box are the only ones there are and nothing
 * inside the box takes them first.
 *
 * The one difference is the background. Option A gives the engine a background
 * colour of its own that matches the page, so that the seam between the two
 * surfaces cannot be seen. Here the engine paints no background at all — a
 * deck.gl canvas is cleared to nothing rather than to a colour — so the box's
 * own colour is what an operator sees wherever there is no picture, and there is
 * no seam to hide.
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
    // One above the surface the bottom layer goes on, and one below the
    // operator's own. The three numbers are the three layers of
    // `viz_studio/THE_CANVAS.md`, in order, written down in one place.
    zIndex: "1",
    pointerEvents: "none",
  });

  own.engineCanvas = document.createElement("canvas");
  own.engineCanvas.className = "zmart-engine-canvas";
  Object.assign(own.engineCanvas.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    display: "block",
  });
  own.engineHost.appendChild(own.engineCanvas);

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

  // The window can be resized, and both surfaces have to follow it. The
  // engine's canvas needs no help here — deck.gl re-reads how large its canvas
  // is at the start of every frame it draws, so a frame is never drawn at one
  // size and shown at another. That is worth saying because the same thing is
  // not true of option A's engine, where it cost 69 screen pixels of
  // misregistration until it was worked around.
  own.watchSize = new ResizeObserver(() => {
    if (own.destroyed) return;
    fitTheSurfaces(own);
    // The view is written again as well as the surfaces being resized, because
    // where the engine's patch sits within a differently sized window is a
    // different place, and the offset that follows from it has to be redone.
    if (own.wanted) writeTheView(own, own.wanted);
    // Repainted from the view the engine last drew with rather than anything
    // newer, because that is still the picture on screen.
    repaint(own);
  });
  own.watchSize.observe(element);
}

/**
 * Make the operator's canvas the size of the box, in real pixels as well as in
 * the browser's own.
 *
 * The canvas is made as many real pixels across as the screen actually has, and
 * then everything is drawn in browser-pixel units, so a screen that packs one
 * and a half real pixels into each browser pixel gets a crisp edge rather than a
 * blurred one. This is invisible at a density of exactly one, which is what
 * makes getting it wrong so easy.
 *
 * The engine's canvas is not touched. It is styled to fill its box and deck.gl
 * sizes the drawing surface behind it, taking the screen's density into account
 * on its own.
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
 * `viz_studio/THE_CANVAS.md` belongs, and here it is genuinely seen: a deck.gl
 * canvas is cleared to nothing rather than to a colour, so wherever the picture
 * has not been drawn, what is behind shows through. That is the one place this
 * engine differs from neuroglancer in a way that decides what can be built
 * rather than how well it performs.
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
 * Decide how much of the window the engine is given, as a rectangle inside its
 * own canvas.
 *
 * When the drawn region is bounded to the coverage record, the engine is asked
 * to draw only in the part of the window that covers ground the run has actually
 * imaged, opened out a little. Everywhere else is ground nobody has been to, and
 * asking about it is where almost the whole cost of a redraw goes.
 *
 * This is the one place where the two sandwich options are built differently,
 * and the difference is worth knowing. Option A shrinks the engine's *element*,
 * which means resizing the drawing surface every time the view moves — and an
 * engine that has not yet noticed it was resized draws one frame at the old size
 * and has it stretched to the new one, which is the wrong scale in the wrong
 * place. deck.gl instead accepts a rectangle within its canvas as the region to
 * draw in, so the canvas here keeps the size of the window from beginning to end
 * and there is nothing to fall behind.
 */
function fitTheEngineToItsPatch(own) {
  const { width, height } = own.size;
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
  // The description of the region is rebuilt only when it has really changed,
  // because handing the engine a new one asks it to work out afresh which
  // pieces of image it needs, and that is not free.
  if (!same || !own.view) {
    own.view = new OrthographicView({
      id: "the-flat-view",
      x: rect.left,
      y: rect.top,
      width: rect.width,
      height: rect.height,
      // Height runs down the window, the way a stage and an image both count it.
      flipY: true,
      // The engine handles no gesture at all. Both of them belong to this
      // canvas, which listens for them on the box the viewer was opened inside.
      controller: false,
    });
    own.deck?.setProps({ views: own.view });
  }
  return rect;
}

// ---------------------------------------------------------------------------
// Opening the acquisitions
// ---------------------------------------------------------------------------

/**
 * The address of the store itself, with any engine's private decoration removed.
 *
 * The page passes one address to every option, and it carries a small suffix
 * that tells neuroglancer which shape of store to expect — written after a
 * vertical bar, as in `…/run.ome.zarr/|zarr2:`. Viv works out that much from the
 * store's own description, so the suffix is taken off here rather than the page
 * being asked to know which option it is talking to. That is the whole point of
 * one interface: the page says where the data is, and each option makes of that
 * whatever its own engine needs.
 */
function addressOfTheStore(url) {
  const bar = url.indexOf("|");
  return bar < 0 ? url : url.slice(0, bar);
}

/**
 * How large one voxel is, in micrometres, out of the store's own description.
 *
 * Viv does not fill this in for a store read as OME-Zarr — its plumbing for
 * physical sizes is only complete for OME-TIFF — but the numbers are there in
 * the description it hands back, so they are taken from it here. This matters
 * more than a scale bar: it is the conversion between the operator's
 * micrometres and everything the engine counts in, and it is the only place that
 * conversion happens.
 *
 * A description that never says how large a voxel is leaves us with no honest
 * answer, so one micrometre is assumed and a note is written to the browser's
 * console. A viewer that refused to open would be worse; a viewer that said
 * nothing would be worse still.
 */
function voxelSizeUm(metadata, name) {
  const multiscale = metadata?.multiscales?.[0];
  const found = { x: 1, y: 1, z: 1 };
  if (!multiscale) return found;
  const axes = multiscale.axes || [];
  const names = axes.map((axis) => (typeof axis === "string" ? axis : axis.name));
  const units = axes.map((axis) => (typeof axis === "string" ? "" : axis.unit || ""));
  let scale = null;
  for (const step of multiscale.datasets?.[0]?.coordinateTransformations || []) {
    if (step.type === "scale") scale = step.scale;
  }
  if (!scale) return found;
  let anySaid = false;
  names.forEach((axisName, at) => {
    if (!(axisName in found)) return;
    const spelled = String(units[at] || "").toLowerCase();
    const perUnit = UM_PER_UNIT[spelled];
    if (perUnit === undefined) return;
    found[axisName] = scale[at] * perUnit;
    anySaid = true;
  });
  if (!anySaid) {
    console.warn(
      `the acquisition "${name}" does not say what unit its voxels are ` +
        "measured in, so one micrometre to the voxel has been assumed. " +
        "Distances shown for it may be wrong by a factor.",
    );
  }
  return found;
}

/**
 * Where the low corner of this acquisition sits on the stage, in micrometres.
 *
 * **Why a viewer needs this at all.** An image says how large its voxels are and
 * how many of them there are, and between them those two say how *big* it is —
 * but neither says where on the specimen it begins. A run written from the
 * stage's zero begins at nought and the question never comes up, which is why it
 * can go unanswered for a long time without anybody noticing. Open a wide survey
 * and a detailed scan of one part of it together, though, and the position is
 * the only thing there is: the two runs have different voxels and share nothing
 * else, so a viewer that ignores where each of them says it is draws the detail
 * scan at the same corner as the survey — a perfectly sharp picture of the
 * wrong part of the slide.
 *
 * That is not a hypothetical. Measured before this function existed, the detail
 * scan of `viz_studio/options/RESULTS.md` measurement 8 landed 898 micrometres
 * from where its store says it is.
 *
 * The number is written as a translation, in the same units as the axes. Viv's
 * own reading of a store does not carry it, so it is taken from the description
 * here, exactly as the size of a voxel is.
 *
 * **It can be written in two places, and both have to be read.** OME-Zarr lets
 * an image state a transformation beside each resolution and another beside the
 * multiscale block that holds them, and the second is applied to the result of
 * the first. This project's own writer uses the outer one
 * (`zmart_storage/canvas.py`); the images other instruments send arrive with the
 * inner one and no outer block at all. Reading only the outer place is therefore
 * right for our runs and silently wrong for everybody else's — every foreign
 * image reports itself as beginning at the stage's zero, and a run of many tiles
 * draws all of them on top of one another.
 *
 * That is the same fault as the 898 micrometres above, in the one form the first
 * fix did not cover: the readers were taught this project's convention rather
 * than the format's. So the two are composed the way the format says and the way
 * neuroglancer's own reader does it — the outer scale applies to the inner
 * translation, and the outer translation is added to it. Where either is absent
 * the arithmetic collapses to the other, which is why one expression serves both
 * conventions rather than a test for which kind of store this is.
 */
function originUm(metadata) {
  const multiscale = metadata?.multiscales?.[0];
  const found = { x: 0, y: 0, z: 0 };
  if (!multiscale) return found;
  const axes = multiscale.axes || [];
  const names = axes.map((axis) => (typeof axis === "string" ? axis : axis.name));
  const units = axes.map((axis) => (typeof axis === "string" ? "" : axis.unit || ""));
  const saying = (transformations, kind) => {
    for (const step of transformations || []) {
      if (step.type === kind) return step[kind];
    }
    return null;
  };
  // The full-resolution copy: every level states the same position, and this is
  // the one whose voxels the rest of the file counts in.
  const beside = saying(multiscale.datasets?.[0]?.coordinateTransformations, "translation");
  const around = saying(multiscale.coordinateTransformations, "translation");
  const stretch = saying(multiscale.coordinateTransformations, "scale");
  names.forEach((axisName, at) => {
    if (!(axisName in found)) return;
    const perUnit = UM_PER_UNIT[String(units[at] || "").toLowerCase()];
    if (perUnit === undefined) return;
    const inner = Number(beside?.[at]);
    const outer = Number(around?.[at]);
    const factor = Number(stretch?.[at]);
    found[axisName] = (
      (Number.isFinite(inner) ? inner : 0) * (Number.isFinite(factor) ? factor : 1)
      + (Number.isFinite(outer) ? outer : 0)
    ) * perUnit;
  });
  return found;
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
  return { ...AN_ORDINARY_WINDOW };
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
 * Turn one acquisition into the pyramid of readers and the description of it
 * that the drawing needs.
 *
 * The pyramid is the list of ever-smaller copies of the image the writer made,
 * biggest first. Viv chooses which of them to read from according to how far out
 * the view is, which is the whole of what makes a large acquisition affordable —
 * zoomed out, the full-resolution copy is not touched at all.
 */
async function openOneAcquisition(acquisition) {
  const address = addressOfTheStore(acquisition.url);
  let opened;
  try {
    opened = await loadOmeZarr(address, {
      type: "multiscales",
      // Nothing may be kept between one look and the next. These runs are
      // written into while somebody is watching them, so a copy held in the
      // browser would answer from a moment ago — and a viewer showing a moment
      // ago is exactly the failure live viewing exists to avoid.
      fetchOptions: { cache: "no-store" },
    });
  } catch (why) {
    throw new Error(
      `the acquisition "${acquisition.name}" could not be read from ` +
        `${address}: ${why && why.message ? why.message : why}. This is said ` +
        "here rather than left as an empty window, because a viewer that opens " +
        "onto nothing and reports itself content is the most expensive failure " +
        "this project keeps meeting.",
    );
  }
  const um = voxelSizeUm(opened.metadata, acquisition.name);
  const at = originUm(opened.metadata);
  // What the page said, where it said anything; otherwise what the run says
  // about itself; and only if the run says nothing either, one white channel.
  // Viv hands back the store's whole description alongside the picture, so
  // reading it here costs no extra request at all.
  const channels = acquisition.channels && acquisition.channels.length
    ? acquisition.channels
    : channelsTheStoreDescribes(opened.metadata)
      || [{ name: acquisition.name, colour: [...WHITE], window: { ...AN_ORDINARY_WINDOW } }];
  return {
    name: acquisition.name,
    url: acquisition.url,
    address,
    sources: opened.data,
    metadata: opened.metadata,
    um,
    // Where this acquisition's low corner sits on the stage, in micrometres.
    // Nought for a run written from the stage's zero, which is most of them, and
    // the only thing that puts two runs of different voxel sizes in the same
    // place when it is not.
    at,
    // Which plane of the stack and which moment of a timelapse are being shown.
    // Both are counted in the image's own whole numbers here; the handle takes
    // micrometres and moments and converts.
    plane: 0,
    moment: 0,
    channels: channels.map((channel, within) => ({
      name: channel.name,
      within,
      colour: channel.colour || [...WHITE],
      window: channel.window || { ...AN_ORDINARY_WINDOW },
      visible: channel.visible !== false,
    })),
  };
}

/**
 * Start the engine, open the acquisitions, and settle everything that is set
 * once.
 */
async function start(own, acquisitions) {
  own.images = [];
  for (const acquisition of acquisitions) {
    own.images.push(await openOneAcquisition(acquisition));
  }
  own.rows = own.images.flatMap((image, at) =>
    image.channels.map((channel) => ({ image, imageAt: at, channel })),
  );

  // Where a view is to start from, before the page has said. The middle of the
  // first acquisition at a magnification that puts the whole of it in the
  // window, so that a viewer opened and left alone shows something rather than
  // an empty rectangle somewhere off to one side.
  own.wanted = own.wanted || openingViewFor(own);
  fitTheEngineToItsPatch(own);

  own.deck = new Deck({
    canvas: own.engineCanvas,
    // The canvas is styled to fill its box and deck.gl reads how large that is
    // at the start of every frame, so no size is stated here and none can go
    // stale.
    views: own.view,
    viewState: engineViewFor(own),
    // The engine handles no gesture. Both of them belong to this canvas, which
    // listens on the box the viewer was opened inside, and the engine's box is
    // transparent to the mouse besides.
    controller: false,
    // Nothing here is clicked on, and asking the engine to work out what is
    // under the pointer costs it a second drawing of the whole scene every time
    // the mouse moves.
    _pickable: false,
    layers: layersFor(own),
    onAfterRender: () => {
      if (own.destroyed) return;
      own.counted.enginePaints += 1;
      // The operator's drawing is repainted from inside the engine's own
      // end-of-frame, using the view read at that instant. This is the whole
      // discipline that holds a sandwich together: anything painted from here
      // reaches the screen in the same frame as the picture rather than one
      // frame later, and the view read here is the view the engine just drew
      // with. It is built in rather than left to the page, so a page cannot get
      // it wrong.
      repaint(own);
      // The whole placement rather than only the centre and the zoom, so that a
      // page keeping ordinary HTML elements over or under the canvas can move
      // them in the same instant the picture moved. See `whereThingsAreDrawn` on
      // the handle for what it is for.
      if (own.onViewChanged) own.onViewChanged(howThingsArePlaced(own));
    },
    onError: (why) => {
      // Said out loud rather than swallowed. A drawing engine that has quietly
      // given up looks exactly like one that is still loading.
      console.error("the drawing engine reported a problem", why);
    },
  });
}

/** A view showing the whole of the first acquisition, for a viewer left alone. */
function openingViewFor(own) {
  const first = own.images[0];
  const { width, height } = own.size;
  if (!first) return { centre: { x: 0, y: 0 }, zoom: 1 };
  const across = widthAndHeightInVoxels(first);
  const wideUm = across.width * first.um.x;
  const tallUm = across.height * first.um.y;
  return {
    // The middle of the first acquisition, counted from where that acquisition
    // says it begins rather than from the stage's zero — otherwise a run written
    // some way along the stage opens looking at empty room beside it.
    centre: { x: first.at.x + wideUm / 2, y: first.at.y + tallUm / 2 },
    zoom: Math.max(
      wideUm / Math.max(1, width),
      tallUm / Math.max(1, height),
      1e-6,
    ),
  };
}

/** How many voxels across and down the full-resolution image is. */
function widthAndHeightInVoxels(image) {
  const source = image.sources[0];
  const labels = source.labels || [];
  const shape = source.shape || [];
  const at = (name) => labels.indexOf(name);
  return {
    width: shape[at("x")] ?? 0,
    height: shape[at("y")] ?? 0,
  };
}

// ---------------------------------------------------------------------------
// The little program that runs on the graphics card
// ---------------------------------------------------------------------------

/**
 * Let what is behind show through wherever nothing was recorded.
 *
 * **Why this is needed.** A run declares room to the reach of the stage and
 * fills it in as it goes, so most of a canvas is usually ground nobody has been
 * to. Viv finishes its colouring by writing the picture out fully opaque, which
 * means all that empty room arrives as a large black rectangle: it hides the
 * page behind it, and where two acquisitions are drawn one over the other, the
 * upper one blacks out the lower. So the transparency has to answer one question
 * and one only — *was this spot imaged at all?*
 *
 * **What it does.** After the colour for a spot has been worked out, it looks at
 * how bright that colour is. Nothing there at all means nothing is drawn, and
 * what is behind shows through. The change is gradual over a very small range
 * rather than a hard yes-or-no, which keeps the edge of an imaged region smooth
 * instead of speckled where the brightness is hovering around nothing.
 *
 * **The one thing it cannot tell apart**, and it is important. A place that
 * genuinely *was* imaged and came back black looks exactly like a place nobody
 * visited, so it disappears too — and a viewer that hides a dark specimen is
 * worse than one that never hid anything. `viz_studio/OPTIONS.md` sets out the
 * fix, which is one line in the writer rather than anything here: write nothing
 * below one, and nought then means "nobody has been here" exactly and always.
 * Until that is done this remains a good guess rather than a true statement, and
 * it is worth knowing which.
 */
class LetTheUnimagedGroundShowThrough extends LayerExtension {
  getShaders() {
    return {
      inject: {
        "fs:DECKGL_FILTER_COLOR": `
          float brightestHere = max(color.r, max(color.g, color.b));
          color.a *= smoothstep(0.0, ${AS_GOOD_AS_NOTHING.toFixed(3)}, brightestHere);
        `,
      },
    };
  }
}
LetTheUnimagedGroundShowThrough.extensionName = "LetTheUnimagedGroundShowThrough";

// ---------------------------------------------------------------------------
// What the engine is asked to draw
// ---------------------------------------------------------------------------

/**
 * One drawing layer per acquisition, in the order they should be drawn, the
 * first at the bottom.
 *
 * A note on why this is one layer per acquisition rather than one per channel,
 * which is how option A does it. Viv draws all of an acquisition's channels in a
 * single pass, mixing their colours as it goes, which is both faster and how the
 * engine is meant to be used. So the flat list of channels the page holds — one
 * line per thing that can be switched on and off — is mapped onto layers here,
 * and the page never has to know that the two engines arrange it differently.
 */
function layersFor(own) {
  return own.images.map((image, at) => {
    const shown = image.channels;
    // Viv gives every resolution of an image the same list of axis names, so
    // the first is as good as any and is the one already read elsewhere here.
    const labels = image.sources?.[0]?.labels || [];
    return new MultiscaleImageLayer({
      id: `zmart-acquisition-${at}`,
      loader: image.sources,
      // Which plane, which moment, and which channel each colour comes from —
      // naming only the axes this image actually has.
      //
      // Asking for all three regardless looks harmless and is not. Every image
      // this project writes declares five axes whether or not the run had a
      // moment or a colour to put in them, so a fixed `{t, c, z}` is right on
      // every acquisition of our own and cannot be wrong on any of them. A
      // light-sheet transfer declares `z, y, x` and nothing else, and asking
      // such an image for its `t` is refused rather than ignored: every piece
      // of it fails to load, one quiet rejection at a time, and what is left is
      // a viewer reporting itself perfectly well over an empty window.
      //
      // The same reasoning as `originUm` above, one layer up: what the store
      // says about itself is the only thing worth trusting, and a constant that
      // happens to match our own writer is not a substitute for reading it.
      // `viv-inside` asks the same question of its own store; the two are
      // written separately on purpose, so change both together.
      selections: shown.map((channel) => {
        const asked = {};
        if (labels.includes("t")) asked.t = image.moment;
        if (labels.includes("c")) asked.c = channel.within;
        if (labels.includes("z")) asked.z = image.plane;
        return asked;
      }),
      contrastLimits: shown.map((channel) => [
        channel.window.low,
        channel.window.high,
      ]),
      channelsVisible: shown.map((channel) => channel.visible),
      // The page speaks in fractions of full brightness, as option A's does;
      // this engine counts colour from 0 to 255.
      colors: shown.map((channel) =>
        channel.colour.map((part) => Math.round(part * 255)),
      ),
      // Where this acquisition sits relative to the first one. See
      // `placementOf` for why this is needed at all.
      modelMatrix: placementOf(own, image),
      // Nothing here is clicked on, and working out what is under the pointer
      // costs a whole second drawing of the scene.
      pickable: false,
      // Viv can draw a single low-resolution copy of the whole image behind the
      // tiles, so that something appears while the detailed pieces are still
      // arriving. It is left out here, and the reason is the shape of a real
      // run: the canvas is declared to the reach of the stage, so even the
      // smallest copy of it is large, and reading the whole of it costs
      // hundreds of requests for ground nobody has imaged. That is exactly the
      // cost this arrangement exists to avoid.
      excludeBackground: true,
      extensions: [
        new ColorPaletteExtension(),
        new LetTheUnimagedGroundShowThrough(),
      ],
      onTileError: (why) => {
        // A piece nobody has written is the ordinary case on a sparse run
        // rather than a fault, and it arrives here as a piece that could not be
        // read. Anything else is worth saying out loud.
        if (why && why.name !== "AbortError") {
          console.warn("a piece of image could not be read", why);
        }
      },
    });
  });
}

/**
 * Where one acquisition sits on the specimen, as a placement the engine
 * understands.
 *
 * The engine counts in **voxels of the first acquisition, from the stage's
 * zero**. That is worth stating in full because it is two decisions and both
 * matter. The unit is the first acquisition's voxel because that is the space
 * its layers naturally live in and it keeps the conversion from micrometres to a
 * single line. The zero is the stage's zero rather than the first acquisition's
 * corner, so that the page's micrometres mean the same thing however the first
 * run happens to have been placed.
 *
 * Two things therefore have to be said about every acquisition, and leaving out
 * either one is a fault an operator can see:
 *
 * - **How big its voxels are.** A survey and a detail scan of the same specimen
 *   have voxels of different sizes, so the second is stretched to match the
 *   first; without this the two are drawn at different magnifications on top of
 *   one another.
 * - **Where it begins.** An image says how large it is and says nothing about
 *   where it sits unless it is asked. Without this a detail scan is drawn at the
 *   same corner as the survey rather than over the part of the specimen it was
 *   taken from — measured, before this was put right, at 898 micrometres from
 *   where its store says it is.
 *
 * Nothing at all is handed back for the ordinary case — one acquisition, or
 * several written at the same voxel size from the stage's zero — where the
 * placement is the identity and costs nothing.
 */
function placementOf(own, image) {
  const first = own.images[0];
  if (!first) return undefined;
  const across = image.um.x / first.um.x;
  const down = image.um.y / first.um.y;
  // The corner, in the same voxels the engine counts in.
  const from = { x: image.at.x / first.um.x, y: image.at.y / first.um.y };
  const sameSize = Math.abs(across - 1) < 1e-9 && Math.abs(down - 1) < 1e-9;
  if (sameSize && from.x === 0 && from.y === 0) return undefined;
  return new Matrix4().translate([from.x, from.y, 0]).scale([across, down, 1]);
}

// ---------------------------------------------------------------------------
// Micrometres in, micrometres out
// ---------------------------------------------------------------------------
//
// The engine has a notion of zoom of its own, and it is not one the operator
// should ever meet. deck.gl counts in doublings: a zoom of nought means one
// voxel of the first acquisition covers one screen pixel, a zoom of one means it
// covers two, and so on. The store and the stage both speak micrometres, so that
// is what crosses this boundary, and the conversion lives here and nowhere else.
//
// The arithmetic, so it can be checked rather than trusted. Screen pixels per
// voxel is 2 raised to the engine's zoom. Micrometres per screen pixel is
// therefore the size of a voxel divided by that, so
//
//     zoom (the engine's)  =  log2( micrometres per voxel / micrometres per pixel )
//
// and the two axes are converted separately, because an acquisition whose voxels
// are taller than they are wide would otherwise be drawn squashed.

/**
 * How far the middle of the engine's patch is from the middle of the window, in
 * browser pixels.
 *
 * Nought unless the drawn region is being bounded to the imaged ground. When it
 * is, the engine is drawing in a rectangle somewhere else in the window and its
 * idea of "the centre" is the centre of that rectangle — so this difference has
 * to be added on the way in and taken off on the way out, or a given point of
 * specimen would land in a different place on the window depending on whether
 * bounding happened to be on. The page must never be able to tell.
 */
function howFarThePatchIsOffCentre(own) {
  const rect = own.engineRect;
  const { width, height } = own.size;
  if (!rect) return { x: 0, y: 0 };
  return {
    x: rect.left + rect.width / 2 - width / 2,
    y: rect.top + rect.height / 2 - height / 2,
  };
}

/** How large a voxel of the space the engine counts in is, in micrometres. */
function voxelOfTheEngine(own) {
  return own.images[0]?.um || { x: 1, y: 1, z: 1 };
}

/** The view to hand the engine, worked out from the view the page asked for. */
function engineViewFor(own) {
  const um = voxelOfTheEngine(own);
  const { centre, zoom } = own.wanted;
  const off = howFarThePatchIsOffCentre(own);
  return {
    target: [
      (centre.x + off.x * zoom) / um.x,
      (centre.y + off.y * zoom) / um.y,
      0,
    ],
    zoom: [Math.log2(um.x / zoom), Math.log2(um.y / zoom)],
  };
}

/**
 * The engine's own description of the frame it last drew, or nothing at all.
 *
 * There is a moment, between a viewer being asked for and its first frame
 * reaching the screen, when the engine has not yet been told how large its
 * canvas is and has therefore drawn nothing. Asked about the view during that
 * moment it does not answer politely — it stops with an assertion — so the
 * question is only put once there is a frame to ask about, and the answer before
 * then comes from what the page asked for, which is the only honest thing to say
 * at that point.
 */
function theFrameTheEngineDrew(own) {
  if (!own.deck || own.destroyed) return null;
  const { width, height } = own.size;
  if (!(width > 0) || !(height > 0)) return null;
  let frame = null;
  try {
    frame = own.deck.getViewports?.()[0] || null;
  } catch {
    return null;
  }
  if (!frame || !(frame.width > 0) || !Array.isArray(frame.target)) {
    return null;
  }
  return frame;
}

/**
 * The view the engine is showing now, in micrometres.
 *
 * Read out of the engine's own description of the frame it drew rather than out
 * of what we last asked for, so that a request the engine did not honour shows
 * up as a difference rather than being papered over. Before the engine has drawn
 * anything there is no frame to read, and then the answer is what was asked for,
 * which is the only honest thing to say at that moment.
 */
function readTheView(own) {
  const um = voxelOfTheEngine(own);
  const frame = theFrameTheEngineDrew(own);
  if (!frame) {
    return own.wanted || { centre: { x: 0, y: 0 }, zoom: 1 };
  }
  const zoomAcross = frame.zoomX ?? frame.zoom;
  const zoom = um.x / Math.pow(2, zoomAcross);
  const off = howFarThePatchIsOffCentre(own);
  return {
    centre: {
      x: frame.target[0] * um.x - off.x * zoom,
      y: frame.target[1] * um.y - off.y * zoom,
    },
    zoom,
  };
}

/** Tell the engine where to look, in micrometres. */
function writeTheView(own, asked) {
  const now = readTheView(own);
  const centre = asked?.centre || now.centre;
  const zoom = asked?.zoom > 0 ? asked.zoom : now.zoom;
  // Remembered before the patch is worked out, because the patch is worked out
  // from where the view is about to be rather than from where it was.
  own.wanted = { centre, zoom };
  fitTheEngineToItsPatch(own);
  own.deck?.setProps({ viewState: engineViewFor(own) });
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

/**
 * Open every acquisition again and hand the fresh readers to the drawing.
 *
 * This is what "a tile may have arrived" comes to for this engine, and it is
 * worth setting out plainly because it is heavier than option A's answer.
 *
 * Nothing on disk announces a new tile. A run declares its images at full size
 * before a single tile exists, and their description is identical before and
 * after, so there is nothing for a watcher to notice. Neuroglancer can be asked
 * to let go of the pieces of image it has already decoded, and it then fetches
 * what it needs again. Viv has no such request: the reader it was given is the
 * only thing it will ever read through, and it keeps a store of decoded tiles
 * keyed to that reader. So the store is opened afresh — which re-reads the small
 * files describing it — and the new reader handed over. The drawing then drops
 * its store of tiles and fetches the ones on screen again.
 *
 * **One read at a time.** If a second read is started while the first is still
 * going, the drawing can end up holding pieces from two different generations of
 * the data and shows a patchwork of both. So a request that arrives while one is
 * running is remembered and honoured once, afterwards, rather than run alongside.
 */
async function openTheStoresAgain(own) {
  if (own.destroyed) return 0;
  if (own.readingAgain) {
    own.anotherLookIsWanted = true;
    return own.counted.lastAsked;
  }
  const doIt = (async () => {
    let handedOver = 0;
    for (const image of own.images) {
      try {
        const opened = await loadOmeZarr(image.address, {
          type: "multiscales",
          fetchOptions: { cache: "no-store" },
        });
        if (own.destroyed) return handedOver;
        image.sources = opened.data;
        image.metadata = opened.metadata;
        handedOver += opened.data.length;
      } catch (why) {
        // A run that is mid-write can briefly hand back a description that
        // cannot be read. That is not a reason to lose the picture already on
        // screen, so the old reader is kept and we try again next time.
        console.warn(
          `the acquisition "${image.name}" could not be read again, so the ` +
            "picture already on screen has been kept",
          why,
        );
      }
    }
    if (!own.destroyed) own.deck?.setProps({ layers: layersFor(own) });
    return handedOver;
  })();
  own.readingAgain = doIt;
  let handedOver = 0;
  try {
    handedOver = await doIt;
  } finally {
    own.readingAgain = null;
  }
  own.counted.letGoes += 1;
  own.counted.lastAsked = handedOver;
  if (own.anotherLookIsWanted && !own.destroyed) {
    own.anotherLookIsWanted = false;
    return openTheStoresAgain(own);
  }
  return handedOver;
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
     * Moving through the stack lives on a slider rather than on a gesture, where
     * it is visible and labelled — see `CONTROLS.md`.
     */
    setPlane(z) {
      let changed = false;
      for (const image of own.images) {
        const umPerVoxel = image.um.z;
        if (!(umPerVoxel > 0)) continue;
        const plane = Math.max(0, Math.round(z / umPerVoxel));
        if (plane !== image.plane) {
          image.plane = plane;
          changed = true;
        }
      }
      if (changed) own.deck?.setProps({ layers: layersFor(own) });
    },

    /** Which moment of a timelapse to show, counted from the first. */
    setMoment(t) {
      let changed = false;
      for (const image of own.images) {
        const moment = Math.max(0, Math.round(t));
        if (moment !== image.moment) {
          image.moment = moment;
          changed = true;
        }
      }
      if (changed) own.deck?.setProps({ layers: layersFor(own) });
    },

    /**
     * Change one channel: whether it shows, what colour it is drawn in, and the
     * brightness window applied to it.
     *
     * `index` counts across all the acquisitions in the order they are drawn,
     * which is the order they appear in a list on screen.
     */
    setChannel(index, { visible, colour, window: brightness } = {}) {
      const row = own.rows[index];
      if (!row) return;
      if (visible !== undefined) row.channel.visible = visible;
      if (colour) row.channel.colour = colour;
      if (brightness) row.channel.window = brightness;
      own.deck?.setProps({ layers: layersFor(own) });
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
     * The operator's own drawing.
     *
     * Hand over one function. It is called at the moment this option considers
     * correct — here, from inside the engine's own end-of-frame — with the view
     * that frame was drawn from. The page never knows which option is underneath
     * it, which is what makes comparing them fair.
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
     * On this engine it is genuinely seen. A deck.gl canvas is cleared to
     * nothing rather than to a colour, so wherever the picture has not been
     * drawn — which on a run in progress is most of the window — what is behind
     * shows through. `drawsUnder` is `true` here.
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
     * `true` here, and measured rather than assumed: with one colour painted
     * behind this engine's canvas and another set as the engine's own
     * background, an operator saw 96.95% of the colour behind and none of the
     * engine's background over ground nobody had imaged.
     */
    drawsUnder: true,

    /** Why, in a sentence a page can show to whoever is looking at it. */
    drawsUnderBecause:
      "a deck.gl canvas is cleared to nothing rather than to a colour, so " +
      "wherever the picture has not been drawn, whatever is behind the canvas " +
      "shows through it.",

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
     * behind it show through, as this one does.
     */
    whereThingsAreDrawn() {
      return howThingsArePlaced(own);
    },

    /**
     * "Go and look, a tile may have arrived."
     *
     * Returns how many copies of the image, across the whole pyramid and every
     * acquisition, were handed over fresh — so that a measurement can tell "it
     * was asked and nothing happened" from "it was never asked", two failures
     * that look identical on screen and have quite different causes.
     *
     * Unlike option A's, this one has to wait: opening the store again means
     * reading the small files that describe it, which is a round trip. The
     * promise settles once the drawing has been given the fresh readers, not
     * once the new tiles are on screen.
     */
    async tilesMayHaveLanded({ coverage } = {}) {
      // A newer coverage record, when the caller has one.
      //
      // This is not decoration and it is not optional in practice. The record
      // says where the run has imaged, and while a run is going that answer
      // changes — that is the whole point of it. Two things are worked out from
      // it: where the operator's drawing cuts its holes, and how much of the
      // window the engine is asked to draw in. Both were settled when the viewer
      // opened, so without this a tile written outside the ground the run had
      // reached at that moment is drawn nowhere and shows through nothing — on
      // screen, indistinguishable from an engine that failed to notice it.
      if (coverage) {
        own.coverage = coverage;
        own.boundToCoverage = own.boundToCoverage
          && Boolean(coverage.regions?.length);
        if (own.wanted) writeTheView(own, own.wanted);
      }
      try {
        return await openTheStoresAgain(own);
      } catch (why) {
        console.warn("going back to the store for new tiles did not work", why);
        return 0;
      }
    },

    /** Close the viewer and let go of everything it was holding. */
    destroy() {
      if (own.destroyed) return;
      own.destroyed = true;
      // The gestures come off first. Listeners left behind on a box that is
      // still in the page would go on answering the operator's hand after the
      // viewer they belonged to had gone. The little record of what they saw is
      // kept rather than thrown away, so that a check can still ask a closed
      // viewer whether anything reached it after it shut.
      own.gestures?.stop();
      own.watchSize?.disconnect();
      own.paint = null;
      own.paintBeneath = null;
      own.deck?.finalize();
      own.deck = null;
      own.images = [];
      own.rows = [];
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
