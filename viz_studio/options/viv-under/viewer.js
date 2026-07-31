/**
 * Option B: Viv and deck.gl draw the acquisition in a canvas of their own, and
 * the operator's drawing sits exactly on top of it with holes cut where the
 * picture should show.
 *
 * This is the same arrangement as option A — the operator's canvas above, the
 * engine's canvas below, the page owning every gesture — with a different engine
 * underneath. That is deliberate and it is the whole reason this option exists.
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
 * 2. **Room the microscope never visited would otherwise be painted black.**
 *    Viv's colouring ends by writing the picture out fully opaque, so a canvas
 *    declared to the reach of the stage arrives as a large black rectangle with
 *    a few bright patches in it. A short addition to the little program that
 *    runs on the graphics card fixes that: where nothing was recorded, nothing
 *    is drawn. See `ShowWhatIsBehindUnimagedGround` below, which explains both
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
 *                   `{low, high}` in the stored numbers' own units.
 *   `coverage`      the imaged regions, as `zmart_storage/coverage.py` records
 *                   them, or `null` when the run keeps no record. Used to decide
 *                   where the picture is allowed to show through, and how much
 *                   of the window is worth asking the engine to draw.
 *   `background`    the page colour, as CSS text. Painted on the box itself; the
 *                   engine paints no background of its own, so there is no seam.
 *   `onViewChanged` called with `{ centre, zoom }` whenever the view settles.
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
    deck: null,
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
    refreshing: null,
    askedAgainWhileRefreshing: false,
    // How much drawing has actually happened. Kept because a measurement has to
    // be able to tell "the drawing never moved" from "the drawing moved to the
    // wrong place", and on screen those look identical.
    counted: { overlayPaints: 0, enginePaints: 0, letGoes: 0, lastAsked: 0 },
    destroyed: false,
  };

  buildTheTwoSurfaces(own);
  await start(own, acquisitions);
  return handleFor(own);
}

// ---------------------------------------------------------------------------
// The two surfaces
// ---------------------------------------------------------------------------

/**
 * Put the engine's canvas down and the operator's canvas exactly on top of it.
 *
 * The same arrangement as option A, and the same two pieces of styling that were
 * learned the hard way there. The engine's box is given a stacking order of its
 * own so that nothing the engine creates inside it can escape and end up above
 * the operator's drawing; and it is made transparent to the mouse, so the page's
 * two gestures are the only ones there are and they arrive at the operator's
 * canvas.
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
    zIndex: "0",
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
    zIndex: "1",
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
      // The engine handles no gesture at all. The page owns both of them and
      // they arrive at the operator's canvas, which lies over this one.
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
  const channels = acquisition.channels && acquisition.channels.length
    ? acquisition.channels
    : [{ name: acquisition.name, colour: [1, 1, 1], window: { low: 0, high: 4095 } }];
  return {
    name: acquisition.name,
    url: acquisition.url,
    address,
    sources: opened.data,
    metadata: opened.metadata,
    um,
    // Which plane of the stack and which moment of a timelapse are being shown.
    // Both are counted in the image's own whole numbers here; the handle takes
    // micrometres and moments and converts.
    plane: 0,
    moment: 0,
    channels: channels.map((channel, within) => ({
      name: channel.name,
      within,
      colour: channel.colour || [1, 1, 1],
      window: channel.window || { low: 0, high: 4095 },
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
    // The engine handles no gesture. Both of the page's gestures arrive at the
    // operator's canvas, which lies over this one, and the engine's box is
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
      if (own.onViewChanged) own.onViewChanged(readTheView(own));
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
    centre: { x: wideUm / 2, y: tallUm / 2 },
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
class ShowWhatIsBehindUnimagedGround extends LayerExtension {
  getShaders() {
    return {
      inject: {
        "fs:DECKGL_FILTER_COLOR": `
          float brightestOfTheThree = max(max(color.r, color.g), color.b);
          color.a *= smoothstep(0.0, 0.02, brightestOfTheThree);
        `,
      },
    };
  }
}
ShowWhatIsBehindUnimagedGround.extensionName = "ShowWhatIsBehindUnimagedGround";

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
    return new MultiscaleImageLayer({
      id: `zmart-acquisition-${at}`,
      loader: image.sources,
      // Which plane, which moment, and which channel each colour comes from.
      selections: shown.map((channel) => ({
        t: image.moment,
        c: channel.within,
        z: image.plane,
      })),
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
        new ShowWhatIsBehindUnimagedGround(),
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
 * Where one acquisition sits relative to the first, as a placement the engine
 * understands.
 *
 * The engine counts in voxels of the first acquisition, because that is the
 * space its layers naturally live in. An overview scan and a detail scan of the
 * same specimen do not have voxels of the same size, so the second has to be
 * stretched to match the first or the two would be drawn at different
 * magnifications on top of one another. Nought is the ordinary case — one
 * acquisition, or several written at the same voxel size — and then this is the
 * identity and costs nothing.
 */
function placementOf(own, image) {
  const first = own.images[0];
  if (!first || image === first) return undefined;
  const across = image.um.x / first.um.x;
  const down = image.um.y / first.um.y;
  if (Math.abs(across - 1) < 1e-9 && Math.abs(down - 1) < 1e-9) return undefined;
  return new Matrix4().scale([across, down, 1]);
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
  let viewport = null;
  try {
    viewport = own.deck.getViewports?.()[0] || null;
  } catch {
    return null;
  }
  if (!viewport || !(viewport.width > 0) || !Array.isArray(viewport.target)) {
    return null;
  }
  return viewport;
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
  const viewport = theFrameTheEngineDrew(own);
  if (!viewport) {
    return own.wanted || { centre: { x: 0, y: 0 }, zoom: 1 };
  }
  const zoomAcross = viewport.zoomX ?? viewport.zoom;
  const zoom = um.x / Math.pow(2, zoomAcross);
  const off = howFarThePatchIsOffCentre(own);
  return {
    centre: {
      x: viewport.target[0] * um.x - off.x * zoom,
      y: viewport.target[1] * um.y - off.y * zoom,
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
  if (own.refreshing) {
    own.askedAgainWhileRefreshing = true;
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
  own.refreshing = doIt;
  let handedOver = 0;
  try {
    handedOver = await doIt;
  } finally {
    own.refreshing = null;
  }
  own.counted.letGoes += 1;
  own.counted.lastAsked = handedOver;
  if (own.askedAgainWhileRefreshing && !own.destroyed) {
    own.askedAgainWhileRefreshing = false;
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
      own.watchSize?.disconnect();
      own.paint = null;
      own.deck?.finalize();
      own.deck = null;
      own.images = [];
      own.rows = [];
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
