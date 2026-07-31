/**
 * Option A: neuroglancer draws the acquisition in a canvas of its own, and the
 * operator's drawing sits exactly on top of it with holes cut where the picture
 * should show.
 *
 * This file is the only place in the whole application that knows neuroglancer
 * exists. Everything above it — the page, the gestures, the carrier outline, the
 * tile rectangles, the measurements — is written against the small interface in
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
 *    error and no request (see `SANDWICH.md`, last section).
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
 *    "Keeping the picture on screen while it is being fetched again" explains
 *    both the fault and what the engine does and does not give us to fix it
 *    with.
 *
 * 6. **The picture is placed where the store says it is.** Our writer says where
 *    an image sits by giving the corner of its first voxel; the engine reads the
 *    same description as giving the middle of it, and so drew every acquisition
 *    half a voxel early — about half a screen pixel at an ordinary
 *    magnification, and four screen pixels when zoomed in to eight times full
 *    resolution. `countFromTheCornerOfTheVoxelRatherThanItsMiddle` puts that
 *    right, and says plainly what part of it a viewer cannot put right.
 */

import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import { makeMinimalViewer } from "neuroglancer/unstable/ui/minimal_viewer.js";
import { makeLayer, deleteLayer } from "neuroglancer/unstable/layer/index.js";
import "neuroglancer/unstable/ui/default_viewer.css";
import "./engine-chrome.css";

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
 *                   in the stored numbers' own units.
 *   `coverage`      the imaged regions, as `zmart_storage/coverage.py` records
 *                   them, or `null` when the run keeps no record. Used to decide
 *                   where the picture is allowed to show through.
 *   `background`    the page colour, as CSS text, so the seam between the two
 *                   drawing surfaces never shows.
 *   `onViewChanged` called with `{ centre, zoom }` whenever the view settles.
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
    viewer: null,
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
    counted: { overlayPaints: 0, enginePaints: 0, letGoes: 0, lastAsked: 0 },
    destroyed: false,
  };

  buildTheTwoSurfaces(own);
  await start(own, acquisitions);
  return handleFor(own);
}

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
 * the mouse rather than merely covered by something. The page's own two gestures
 * are the only ones there are, and they arrive at the operator's canvas.
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
    zIndex: "0",
    pointerEvents: "none",
  });

  own.overlay = document.createElement("canvas");
  own.overlay.className = "zmart-operators-drawing";
  Object.assign(own.overlay.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    zIndex: "1",
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
 * could show. It is recorded in `SANDWICH.md` §7 and it is not this file's to fix.
 */
function fitTheSurfaces(own) {
  const density = window.devicePixelRatio || 1;
  const width = own.element.clientWidth;
  const height = own.element.clientHeight;
  own.overlay.width = Math.max(1, Math.round(width * density));
  own.overlay.height = Math.max(1, Math.round(height * density));
  own.size = { width, height, density };
  fitTheEngineToItsPatch(own);
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
 * operator sees is drawn at the size it is displayed at. With this, the same
 * measurement comes back to a single pixel.
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

  own.rows = rowsFor(acquisitions);
  for (const [at, row] of own.rows.entries()) {
    const managed = makeLayer(own.viewer.layerSpecification, row.layerName, {
      type: "image",
      source: row.url,
      shader: shaderFor(row.colour),
      shaderControls: { normalized: { range: [row.window.low, row.window.high] } },
    });
    // Where a store keeps its channels inside one array, this is what picks the
    // channel out: the engine offers it as a dimension belonging to the layer,
    // and each row pins it to its own index. Nothing splits the data — one store
    // feeds every row that reads from it.
    if (row.channelIndex != null) managed.layer.localPosition.value =
      Float32Array.from([row.channelIndex]);
    own.viewer.layerSpecification.add(managed, at);
    row.managed = managed;
  }

  await whenTheAxesAreKnown(own.viewer);
  pinTheAxesThatMeasureDistance(own.viewer);
  startTimeAtTheFirstMoment(own.viewer);
  countFromTheCornerOfTheVoxelRatherThanItsMiddle(own);
  // A page may open several acquisitions at once, and they do not all arrive
  // together — the axes become known as soon as the first of them is read, so a
  // second one may still be on its way. Each layer is therefore looked at again
  // whenever its source changes. Looking twice costs nothing: the second look
  // finds the engine already counting from the corner of a voxel and leaves it
  // alone, which is why this cannot creep half a voxel further with each pass.
  own.stopWatchingTheSources = own.rows
    .map((row) => row.managed?.layer?.dataSourcesChanged?.add(
      () => countFromTheCornerOfTheVoxelRatherThanItsMiddle(own),
    ))
    .filter(Boolean);
  // The engine chooses a starting magnification the first moment it believes it
  // knows what space the picture lives in, and for a moment that is an empty
  // space in which one voxel is one metre. Clearing it now makes it choose
  // again, this time knowing how big a voxel really is. Without this the viewer
  // opens on an empty rectangle with every piece of data present and correct.
  own.viewer.navigationState.zoomFactor.reset();
  own.viewer.perspectiveNavigationState.zoomFactor.reset();

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
    if (own.onViewChanged) own.onViewChanged(readTheView(own));
  });

  // -- and the rule that keeps the picture on screen during a refresh -------
  keepShowingThePictureWhileTheNewOneArrives(own);
}

// ---------------------------------------------------------------------------
// Keeping the picture on screen while it is being fetched again
// ---------------------------------------------------------------------------
//
// This section exists because of one thing an operator sees, so it is worth
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

/**
 * Turn the acquisitions into the flat list of rows the engine draws.
 *
 * One row per channel, in the order they should be drawn, the first at the
 * bottom. Numbering them across all the acquisitions rather than within each one
 * is what makes `setChannel(index, …)` a single sensible number for the page to
 * hold, and it matches how an operator reads the list on screen: one line per
 * thing that can be switched on and off.
 */
function rowsFor(acquisitions) {
  const rows = [];
  acquisitions.forEach((acquisition) => {
    const channels = acquisition.channels && acquisition.channels.length
      ? acquisition.channels
      : [{ name: acquisition.name, colour: [1, 1, 1], window: { low: 0, high: 4095 } }];
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
        colour: channel.colour || [1, 1, 1],
        window: channel.window || { low: 0, high: 4095 },
        channelIndex: channels.length > 1 ? within : null,
        visible: channel.visible !== false,
        managed: null,
      });
    });
  });
  return rows;
}

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
function shaderFor(colour) {
  const [r, g, b] = colour;
  return (
    "#uicontrol invlerp normalized\n" +
    "void main() { float v = normalized();" +
    ` emitRGBA(vec4(vec3(${r}, ${g}, ${b}) * v, v > 0.0 ? 1.0 : 0.0)); }`
  );
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
 * Repaint the operator's canvas from the view the engine has just drawn with.
 *
 * The page's own drawing function is handed everything it needs to place a shape
 * in micrometres and nothing that would let it ask the engine a question, which
 * is what keeps the same drawing code working over every option.
 */
function repaint(own) {
  if (!own.paint || !own.context || own.destroyed) return;
  const { width, height, density } = own.size;
  const view = readTheView(own);
  const context = own.context;
  context.setTransform(density, 0, 0, density, 0, 0);
  context.clearRect(0, 0, width, height);
  own.paint({
    centre: view.centre,
    zoom: view.zoom,
    width,
    height,
    context,
    coverage: own.coverage,
    // Micrometres to screen pixels, for this frame. Everything the page draws
    // goes through this one function, so there is exactly one place where the
    // conversion between the operator's coordinates and the screen can be wrong.
    project: (x, y) => ({
      x: width / 2 + (x - view.centre.x) / view.zoom,
      y: height / 2 + (y - view.centre.y) / view.zoom,
    }),
  });
  own.counted.overlayPaints += 1;
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
    setChannel(index, { visible, colour, window: brightness } = {}) {
      const row = own.rows[index];
      if (!row || !row.managed) return;
      if (visible !== undefined && row.managed.visible !== visible) {
        row.managed.setVisible(visible);
        row.visible = visible;
      }
      const layer = row.managed.layer;
      if (!layer) return;
      if (colour) {
        row.colour = colour;
        // Setting the shader to the text it already holds is ignored by the
        // engine, so this costs nothing when the colour has not changed.
        layer.fragmentMain.value = shaderFor(colour);
      }
      if (brightness) {
        row.window = brightness;
        // The window travels separately, as a value for a control the program
        // declares, so it reaches a program that is already compiled. That is
        // what makes dragging a contrast handle smooth however much is open.
        layer.shaderControlState.restoreState({
          normalized: { range: [brightness.low, brightness.high] },
        });
      }
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
      own.watchSize?.disconnect();
      own.stopFollowing?.();
      own.stopHoldingOn?.();
      for (const stop of own.stopWatchingTheSources || []) stop();
      own.stopWatchingTheSources = null;
      own.paint = null;
      for (const row of own.rows) {
        if (row.managed) deleteLayer(row.managed);
      }
      own.rows = [];
      own.viewer?.dispose?.();
      own.viewer = null;
      own.engineHost?.remove();
      own.overlay?.remove();
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
  };
}
