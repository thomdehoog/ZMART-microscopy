/**
 * Option C: no sandwich at all. The acquired picture and the operator's own
 * drawing are layers in a *single* canvas, drawn in one pass from one view.
 *
 * The other two options put two drawing surfaces in the page, one exactly on
 * top of the other, and then work hard to keep them in step: the operator's
 * canvas is repainted only from inside the engine's end-of-frame announcement,
 * using the view read at that instant, because anything less lets the two come
 * apart while the view is moved. That discipline was measured holding them
 * together to one screen pixel, which is very good — but it is a thing that has
 * to keep being true.
 *
 * Here there is nothing to keep in step. Viv's image layers and the operator's
 * drawing are handed to deck.gl together, as one list of layers with one view
 * behind them, and deck.gl draws them into one canvas in one pass. A frame
 * cannot show the picture from one moment and the drawing from another, because
 * there is only one moment in it. That is what "exact by construction" means,
 * and it is the whole reason this option is worth building.
 *
 * ## The three things that had to be worked out to make that true
 *
 * **1. The operator's drawing is a rectangle of specimen, not a sheet over the
 * window.** The page draws in two dimensions with a plain drawing context, and
 * deck.gl has no such thing — it draws layers, not strokes. So the page's
 * drawing goes into an ordinary offscreen canvas, and that canvas is handed to
 * deck.gl as an image pinned to the exact rectangle of specimen the window is
 * showing. The picture and the drawing are then two layers over the same ground,
 * placed by the same view in the same pass. The page's drawing code does not
 * change by a character, and is never told which option it is running under —
 * see `drawOver` at the bottom of this file, and the long note there about why
 * this was chosen over the alternatives.
 *
 * The same trick serves the bottom layer of `viz_studio/THE_CANVAS.md`, and here
 * it is at its most natural. `drawUnder(paint)` takes a second offscreen canvas
 * and puts it into the same list of layers *before* the picture rather than
 * after, so the ground, the acquisition and the operator's marks are three
 * layers in one canvas drawn in one pass. There is no question of the bottom
 * layer being covered by an opaque canvas, because there is only one canvas, and
 * no question of it drifting, because all three are placed from the same
 * numbers in the same frame. `viewer.drawsUnder` is `true` here.
 *
 * **2. Ground nobody has imaged had to be made see-through.** Viv paints the
 * whole of a run's declared canvas, and a run declares generously, so most of
 * that canvas is room the microscope has never visited. Viv's colouring ends by
 * setting the transparency to "fully opaque" whatever the brightness, so left
 * alone it would paint every unvisited square black — and in a single canvas
 * that black would cover the operator's own drawing. A dozen lines added to the
 * little program Viv runs on the graphics card — a shader, in the engine's own
 * word, and the thing that decides what colour each spot comes out — fix it:
 * where nothing was recorded, nothing is painted. See
 * `LetTheUnimagedGroundShowThrough` below, including what the fix costs and the
 * measured surprise that where the run kept a coverage record it is not needed
 * at all.
 *
 * **3. Nothing on disk announces a new tile.** A run declares its images at full
 * size before the first tile exists, and their description is identical before
 * and after, so there is nothing for a watcher to notice. Viv has to be handed a
 * freshly opened reader, and only one such read is allowed to be in flight at a
 * time. See `tilesMayHaveLanded` and `openTheStoresAgain`.
 *
 * ## Please keep Viv behind this file
 *
 * This is the only file in the application that knows Viv or deck.gl exist.
 * Everything around it — the page, the two gestures in `../gestures.js`, the
 * carrier outline, the tile rectangles, the measurements — is written against
 * the small interface in `../contract.md`, and works the same whichever of the three options is
 * underneath. That is what makes comparing them fair: a difference somebody
 * feels tomorrow is then a difference in the approach, and not a difference in
 * how somebody happened to wire one of them up.
 */

import { Deck, LayerExtension, OrthographicView } from "@deck.gl/core";
import { BitmapLayer } from "@deck.gl/layers";
import { Matrix4 } from "@math.gl/core";
import { ColorPaletteExtension } from "@vivjs/extensions";
import { MultiscaleImageLayer } from "@vivjs/layers";
import { loadOmeZarr } from "@vivjs/loaders";
// The two gestures, from the one copy every option shares. See `../gestures.js`
// for why there is only one copy and what it costs to have three.
import { onlyPanAndZoom } from "../gestures.js";
// Which plane of a stack to open on, shared for the same reason: three options
// opening on three planes would be three different pictures. See `../planes.js`.
import { theMiddleOfEveryOtherAxis } from "../planes.js";
// And what window to draw it through, from the same plane. The two have to come
// from one place: a window measured on a plane the operator is not being shown
// describes a picture that is not on the screen. See `../brightness.js`.
import { theRangeTheseSourcesHold } from "../brightness.js";
// And where to open looking, which the engines disagree about by a factor of
// twenty if left to themselves. See `../opening-view.js`.
import { theViewThatShowsAllOf } from "../opening-view.js";
// And where the specimen sits inside the declared ground; see that file.
import { whereTheSpecimenIs } from "../where-the-specimen-is.js";

/**
 * How dim a spot may be before it is treated as ground nobody has been to.
 *
 * Two per cent of the brightness window. See
 * `LetTheUnimagedGroundShowThrough` for what this is really asking and what it
 * cannot tell apart.
 */
const AS_GOOD_AS_NOTHING = 0.02;

/**
 * What is handed back for a tile the run has not imaged, when the drawn region
 * is being kept to the coverage record.
 *
 * A picture nought pixels wide, which is Viv's own way of saying "there is
 * nothing to draw here" — its tile handling already discards one, so no request
 * is made and no layer is built. See `onlyWhereTheRunHasImaged`.
 */
const NOTHING_WAS_IMAGED_HERE = Object.freeze({
  data: new Uint16Array(0),
  width: 0,
  height: 0,
});

/**
 * Open a viewer inside `element` and return the handle used to drive it.
 *
 * @param {HTMLElement} element  where the viewer draws; it fills this box
 * @param {object} options
 *   `acquisitions`  `[{ url, name, channels }]`, drawn in order with the first
 *                   at the bottom. Each `url` must be a whole address including
 *                   the scheme and host. `channels` is `[{ name, colour,
 *                   window }]`, where `colour` is three numbers from 0 to 1 and
 *                   `window` is `{low, high}` in the stored numbers' own units.
 *                   It is **optional**: leave it out and the viewer reads the
 *                   run's own description of its colours out of the store it is
 *                   opening anyway. Say it and what you say is used unchanged.
 *   `coverage`      the imaged regions, as `zmart_storage/coverage.py` records
 *                   them, or `null` when the run keeps no record.
 *   `background`    the page colour, as CSS text. Ground nobody has imaged is
 *                   left see-through, so this is the colour an operator sees
 *                   there.
 *   `onViewChanged` called for every frame drawn, with the same record
 *                   `whereThingsAreDrawn()` gives back: the centre and zoom in
 *                   micrometres, the size of the box, and `project`/`unproject`
 *                   for placing ordinary HTML elements in the same coordinates.
 *   `boundToCoverage` whether to refuse to ask for image over ground the run
 *                   has not imaged. On wherever there is a record to go on.
 * @returns {Promise<Viewer>} the handle; see `../contract.md` for what it offers.
 *
 * It refuses an address with no scheme or host in it rather than quietly
 * reading from the wrong place, and it waits until every acquisition has said
 * how large its voxels are before it returns — because until then there is no
 * honest conversion between the operator's micrometres and the screen.
 */
export async function openViewer(element, options = {}) {
  const {
    acquisitions = [],
    coverage = null,
    background = "#000000",
    onViewChanged = null,
    boundToCoverage = true,
  } = options;

  for (const acquisition of acquisitions) {
    if (!/^[a-z]+:\/\//i.test(acquisition.url || "")) {
      throw new Error(
        `the acquisition "${acquisition.name}" was given the address ` +
          `"${acquisition.url}", which has no scheme or host in it. The whole ` +
          "address is passed in by the caller, including http:// and the host, " +
          "so that a viewer served from one place and reading from another " +
          "cannot silently read from the wrong one. See options/contract.md §3.",
      );
    }
  }

  // Everything this viewer knows lives in this one object, and it goes away
  // when the viewer does. Nothing at all is kept in a variable belonging to
  // this file, so a page can hold two viewers side by side — an overview and a
  // detail scan, say — and neither disturbs the other.
  const own = {
    element,
    coverage,
    background,
    onViewChanged,
    boundToCoverage: boundToCoverage && Boolean(coverage?.regions?.length),
    // Who has asked to hear that the picture has moved, and how to stop
    // telling them. See `whenTheViewMoves` on the handle for why anything
    // would want to know.
    watchingTheView: [],
    canvas: null,
    deck: null,
    // The two gestures, listening on the box. Put on when the viewer opens and
    // taken off again when it closes, so a page that embeds this canvas gets
    // dragging and the wheel without writing a line and without having to
    // remember to tidy anything up.
    gestures: null,
    // The offscreen canvas the page draws its carrier and tiles into, the
    // drawing context it draws with, and the texture those pixels are copied
    // into. A texture is simply an image kept in the graphics card's own memory,
    // which is where a picture has to be before the card can draw with it — so
    // this is the bridge between an ordinary two-dimensional drawing and the one
    // canvas everything is composed in.
    drawing: null,
    context: null,
    texture: null,
    // And the same three again for the bottom layer — the application's own
    // drawing that goes *beneath* the picture. They stay empty until a page
    // actually asks for a bottom layer, so a page that never uses one neither
    // allocates a second window-sized image nor carries one to the graphics
    // card every frame.
    drawingBeneath: null,
    contextBeneath: null,
    textureBeneath: null,
    paintBeneath: null,
    size: { width: 1, height: 1, density: 1 },
    // The view, in the operator's own units: a place on the stage in
    // micrometres and a magnification in micrometres to the screen pixel.
    view: null,
    // How large one voxel of the first acquisition is, in micrometres. This is
    // the one number that joins the operator's units to the units the picture
    // is drawn in; see "Micrometres in, micrometres out" below.
    umPerVoxel: { x: 1, y: 1, z: 1 },
    opened: [],
    rows: [],
    // Which plane of the stack and which moment of a timelapse are on screen.
    // Both are settled in `start`, once a store has been read and there is a
    // stack to have a middle; nothing can draw before that, because `openViewer`
    // waits for it.
    plane: null,
    moment: null,
    paint: null,
    counted: {
      overlayPaints: 0, groundPaints: 0, enginePaints: 0, letGoes: 0, lastAsked: 0,
    },
    // Only one fresh read of the store may be in flight at a time; see
    // `openTheStoresAgain` for what that is worth and what it is guarding against.
    readingAgain: false,
    anotherLookIsWanted: false,
    destroyed: false,
  };

  buildTheOneCanvas(own);
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
// The one canvas, and the offscreen one the operator draws into
// ---------------------------------------------------------------------------

/**
 * Put down the single canvas everything is drawn into, and the offscreen canvas
 * the page draws its own shapes on.
 *
 * The canvas on screen is made transparent to the mouse on purpose. Both
 * gestures belong to this viewer and are listened for on the box it was opened
 * inside; letting the events reach the box rather than the canvas means the
 * drawing engine can never quietly catch one for itself. `CONTROLS.md` sets out
 * what each gesture the engine would otherwise bind used to do and why it had
 * to go.
 */
function buildTheOneCanvas(own) {
  const { element } = own;
  // Only set when it has not been decided already, so a page that has laid its
  // own box out is left alone. Placing something exactly over a box needs that
  // box to be positioned, and `static` is the one value that will not do.
  if (getComputedStyle(element).position === "static") {
    element.style.position = "relative";
  }
  // The colour an operator sees over ground nobody has imaged. Nothing is drawn
  // there — that is the point of `LetTheUnimagedGroundShowThrough` below — so
  // what shows is whatever the box is painted, which is the page's own colour.
  element.style.background = own.background;

  own.canvas = document.createElement("canvas");
  own.canvas.className = "zmart-one-canvas";
  Object.assign(own.canvas.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    // The two gestures are listened for on the box, and events reach it
    // because nothing inside the box takes them first.
    pointerEvents: "none",
    // Without this a drag on a touchpad scrolls the page instead of panning the
    // view, and the two gestures stop being the only two.
    touchAction: "none",
  });
  element.appendChild(own.canvas);

  own.drawing = document.createElement("canvas");
  own.context = own.drawing.getContext("2d");
  measureTheBox(own);
}

/**
 * Read how large the box is, and make the offscreen canvas match it.
 *
 * The offscreen canvas is made as many real pixels across as the screen
 * actually has, and then everything is drawn in browser-pixel units, so a
 * screen that packs one and a half real pixels into each browser pixel gets a
 * crisp outline rather than a blurred one. This is invisible at a density of
 * exactly one, which is what makes getting it wrong so easy to miss.
 */
function measureTheBox(own) {
  const density = window.devicePixelRatio || 1;
  const width = Math.max(1, own.element.clientWidth);
  const height = Math.max(1, own.element.clientHeight);
  own.size = { width, height, density };
  own.drawing.width = Math.max(1, Math.round(width * density));
  own.drawing.height = Math.max(1, Math.round(height * density));
  if (own.drawingBeneath) {
    own.drawingBeneath.width = own.drawing.width;
    own.drawingBeneath.height = own.drawing.height;
  }
}

/**
 * Make, or remake, the texture that carries the operator's drawing to the one
 * canvas.
 *
 * It is created here and kept, rather than being handed over as a picture for
 * deck.gl to turn into a texture each time. A new texture every frame would
 * mean the graphics card allocating and throwing away a window-sized image
 * sixty times a second, and the whole point of drawing in one pass is that the
 * frame is cheap.
 */
function makeTheDrawingsTexture(own) {
  if (!own.deck?.device) return;
  own.texture?.destroy?.();
  own.texture = aWindowSizedTexture(own);
  if (own.drawingBeneath) {
    own.textureBeneath?.destroy?.();
    own.textureBeneath = aWindowSizedTexture(own);
  }
}

/** One texture the size of the window, in the graphics card's own memory. */
function aWindowSizedTexture(own) {
  return own.deck.device.createTexture({
    width: own.drawing.width,
    height: own.drawing.height,
    format: "rgba8unorm",
    // Point sampling rather than smoothing. The drawing is made at exactly the
    // size it is shown at, so there is nothing to interpolate, and smoothing
    // would only soften an outline that is meant to be a hairline.
    sampler: {
      minFilter: "nearest",
      magFilter: "nearest",
      addressModeU: "clamp-to-edge",
      addressModeV: "clamp-to-edge",
    },
  });
}

/**
 * Make the offscreen canvas the bottom layer is drawn into, the first time a
 * page asks for one.
 *
 * Made only when it is wanted, because it is a window-sized image and the
 * texture that carries it to the graphics card is another. A page that never
 * draws beneath the picture pays for neither. The texture the operator's own
 * drawing already uses is deliberately left alone here: it is in use by a layer
 * on screen, and replacing it would throw away the picture that layer is holding
 * for no reason.
 */
function makeTheGroundBeneath(own) {
  if (own.drawingBeneath) return;
  own.drawingBeneath = document.createElement("canvas");
  own.drawingBeneath.width = own.drawing.width;
  own.drawingBeneath.height = own.drawing.height;
  own.contextBeneath = own.drawingBeneath.getContext("2d");
  if (own.deck?.device) own.textureBeneath = aWindowSizedTexture(own);
}

// ---------------------------------------------------------------------------
// Opening the acquisitions
// ---------------------------------------------------------------------------

/**
 * The address of the store itself, with any reader hint taken off the end.
 *
 * One of the three options names the reader it wants by writing it after a
 * vertical bar — `…/run.ome.zarr/|zarr2:` — because the engine it drives asks
 * for that. It is a hint about how to read the store rather than part of where
 * the store is, so it is taken off here. Nothing is added: the address the
 * caller gave is the address that is read.
 */
function addressOfTheStore(url) {
  const withoutTheHint = url.split("|")[0];
  return withoutTheHint.endsWith("/")
    ? withoutTheHint.slice(0, -1)
    : withoutTheHint;
}

/**
 * How large one voxel is, in micrometres, out of the store's own description.
 *
 * The store says how large its voxels are and in what unit, and both spellings
 * of "micrometre" occur in the wild — written out in full by this project's own
 * writer, abbreviated by some instruments. Metres appear too, because that is
 * what one of the drawing engines prefers, so they are converted.
 *
 * An axis that says nothing about its unit is taken to be in micrometres. That
 * is the honest reading for the stores this project writes, and stating it here
 * is better than a silent factor of a thousand somewhere further along.
 */
function voxelSizeUm(metadata, labels) {
  const found = { x: 1, y: 1, z: 1 };
  const multiscale = metadata?.multiscales?.[0];
  if (!multiscale) return found;
  const axes = multiscale.axes || labels;
  const scale = (multiscale.datasets?.[0]?.coordinateTransformations || []).find(
    (step) => step.type === "scale",
  )?.scale;
  if (!scale) return found;
  axes.forEach((axis, at) => {
    const name = typeof axis === "string" ? axis : axis.name;
    const unit = typeof axis === "string" ? "" : axis.unit || "";
    if (!(name in found)) return;
    const size = Number(scale[at]);
    if (!Number.isFinite(size) || size <= 0) return;
    const toMicrometres =
      unit === "meter" || unit === "m" ? 1e6
      : unit === "millimeter" || unit === "mm" ? 1e3
      : unit === "nanometer" || unit === "nm" ? 1e-3
      : 1;
    found[name] = size * toMicrometres;
  });
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
function originUm(metadata, labels) {
  const found = { x: 0, y: 0, z: 0 };
  const multiscale = metadata?.multiscales?.[0];
  if (!multiscale) return found;
  const axes = multiscale.axes || labels;
  const saying = (transformations, kind) => {
    for (const step of transformations || []) {
      if (step.type === kind) return step[kind];
    }
    return null;
  };
  // The full-resolution copy: every level states the same position, and this is
  // the one whose voxels the rest of this file counts in.
  const beside = saying(multiscale.datasets?.[0]?.coordinateTransformations, "translation");
  const around = saying(multiscale.coordinateTransformations, "translation");
  const stretch = saying(multiscale.coordinateTransformations, "scale");
  axes.forEach((axis, at) => {
    const name = typeof axis === "string" ? axis : axis.name;
    const unit = typeof axis === "string" ? "" : axis.unit || "";
    if (!(name in found)) return;
    const inner = Number(beside?.[at]);
    const outer = Number(around?.[at]);
    const factor = Number(stretch?.[at]);
    const toMicrometres =
      unit === "meter" || unit === "m" ? 1e6
      : unit === "millimeter" || unit === "mm" ? 1e3
      : unit === "nanometer" || unit === "nm" ? 1e-3
      : 1;
    found[name] = (
      (Number.isFinite(inner) ? inner : 0) * (Number.isFinite(factor) ? factor : 1)
      + (Number.isFinite(outer) ? outer : 0)
    ) * toMicrometres;
  });
  return found;
}

/**
 * Read one acquisition's pyramid of smaller copies, freshly.
 *
 * "Freshly" is not a figure of speech and it is the whole of how new tiles
 * appear. Everything the reader has already fetched it remembers, including the
 * pieces it found empty, so a tile written into ground it has already looked at
 * would never be fetched again. Opening the store afresh gives a reader that
 * remembers nothing.
 *
 * A store that cannot be read at all is refused with the reason and the address,
 * in the same words option B uses, rather than being left to whatever the reading
 * library happens to say. A viewer that opens onto nothing and reports itself
 * content is the most expensive failure this project keeps meeting.
 */
async function readTheStore(url, name = "this acquisition") {
  const address = addressOfTheStore(url);
  try {
    return await loadOmeZarr(address, { type: "multiscales" });
  } catch (why) {
    throw new Error(
      `the acquisition "${name}" could not be read from ${address}: ` +
        `${why && why.message ? why.message : why}. This is said here rather ` +
        "than left as an empty window, because a viewer that opens onto " +
        "nothing and reports itself content is the most expensive failure " +
        "this project keeps meeting.",
    );
  }
}

/**
 * Start deck.gl, read every acquisition, and settle everything set once.
 */
async function start(own, acquisitions) {
  own.opened = await Promise.all(
    acquisitions.map(async (acquisition) => {
      const { data, metadata } = await readTheStore(
        acquisition.url, acquisition.name,
      );
      return {
        asked: acquisition,
        name: acquisition.name,
        pyramid: data,
        metadata,
        umPerVoxel: voxelSizeUm(metadata, data[0].labels),
        // Where this acquisition's low corner sits on the stage, in
        // micrometres. Nought for a run written from the stage's zero, which is
        // most of them, and the only thing that puts two runs of different voxel
        // sizes in the same place when it is not.
        originUm: originUm(metadata, data[0].labels),
        // Read here rather than where the rows are built, because that is not a
        // place that can wait for anything. Only wanted when the run describes
        // no colours of its own, and cheap enough to take either way.
        heldRanges: await everyChannelsRange(data, metadata),
        specimen: await whereTheSpecimenIs(data),
      };
    }),
  );
  if (own.opened.length) own.umPerVoxel = own.opened[0].umPerVoxel;
  /* Which plane to open on cannot be settled before a store has been read, since
     where the middle of a stack is depends on how deep it is — and it is not this
     option's to decide in any case, or the options draw different pictures and
     stop comparing. See `../planes.js`. In micrometres here, because that is what
     this viewer counts its plane in; `selectionFor` turns it back into an index
     per store. With nothing open there is no stack and no plane, which comes out
     as nought without a special case. */
  const sharpest = own.opened[0]?.pyramid?.[0];
  const looking = theMiddleOfEveryOtherAxis(sharpest?.labels, sharpest?.shape);
  // Where the specimen is, in micrometres, where that could be found.
  const specimen = own.opened[0]?.specimen;
  own.plane = (specimen?.z ?? looking.z ?? 0) * (own.umPerVoxel.z || 1);
  own.moment = looking.t ?? 0;
  own.rows = rowsFor(own.opened);

  // Somewhere sensible to be looking before the page says where it wants to be,
  // so that the very first frame shows the specimen rather than a corner of
  // empty room. The page moves the view immediately afterwards.
  own.view = openingViewFor(own);

  own.deck = new Deck({
    canvas: own.canvas,
    // A flat view, and this file owns every gesture. `controller: false` empties
    // the engine's own gesture table before it can bind anything: dragging with
    // a modifier, the wheel with a modifier, double-click to zoom. `CONTROLS.md`
    // explains why each of those had to go.
    views: [new OrthographicView({ id: "flat", controller: false })],
    controller: false,
    viewState: theViewStateFor(own),
    layers: [],
    // Nothing is clicked on in this viewer, and turning picking off means the
    // engine does not draw a second, hidden copy of every frame in order to
    // answer a question nobody asked.
    _pickable: false,
    // Left transparent on purpose, rather than cleared to the page's colour.
    // Ground nobody has imaged then has nothing drawn over it at all, and what
    // an operator sees there is the box's own colour showing through the canvas.
    // It is worth knowing that this works, because it is exactly what a canvas
    // in the other arrangement was measured *not* to do.
    parameters: { clearColor: [0, 0, 0, 0] },
    useDevicePixels: true,
    onResize: () => {
      if (own.destroyed) return;
      measureTheBox(own);
      makeTheDrawingsTexture(own);
      showTheView(own);
    },
    // Counted rather than reported. A measurement has to be able to tell "the
    // drawing never moved" from "the drawing moved to the wrong place", and on
    // screen those two look identical when the right answer is that nothing
    // should have happened. Every number the measurements *report* still comes
    // from a photograph of the screen.
    onError: (why) => {
      // Said out loud rather than swallowed, in the same words option B uses. A
      // drawing engine that has quietly given up looks exactly like one that is
      // still loading, and telling those two apart has cost this project days.
      console.error("the drawing engine reported a problem", why);
    },
    onAfterRender: () => {
      if (own.destroyed) return;
      own.counted.enginePaints += 1;
      // The whole placement rather than only the centre and the zoom, so that a
      // page keeping ordinary HTML elements over or under the canvas can move
      // them in the same instant the picture moved. See `whereThingsAreDrawn` on
      // the handle for what it is for.
      if (own.onViewChanged) own.onViewChanged(howThingsArePlaced(own));
    },
  });
  makeTheDrawingsTexture(own);
  showTheView(own);
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
 * Turn the acquisitions into the flat list of rows that can be switched on and
 * off.
 *
 * One row per channel, in the order they are drawn with the first at the
 * bottom. Numbering them across all the acquisitions rather than within each
 * one is what makes `setChannel(index, …)` a single sensible number for the
 * page to hold, and it matches how an operator reads the list on screen: one
 * line per thing that can be switched on and off.
 */
function rowsFor(opened) {
  const rows = [];
  opened.forEach((store, atStore) => {
    const asked = store.asked;
    // What the page said, where it said anything; otherwise what the run says
    // about itself; and only if the run says nothing either, one white channel.
    // Viv hands back the store's whole description alongside the picture, so
    // reading it here costs no extra request at all.
    const channels =
      asked.channels && asked.channels.length
        ? asked.channels
        : channelsTheStoreDescribes(store.metadata)
          || [{
            name: asked.name,
            colour: [...WHITE],
            window: store.heldRanges?.[0] || { ...AN_ORDINARY_WINDOW },
          }];
    channels.forEach((channel, within) => {
      rows.push({
        atStore,
        name: channel.name,
        colour: channel.colour || [...WHITE],
        /* What the run asked for; failing that what this channel's own pixels
           ask for; and only failing both, a guess about a camera. The middle one
           is what a run that names its colours without saying how to display
           them needs, which is commoner than it sounds. */
        window: channel.window
          || store.heldRanges?.[within]
          || { ...AN_ORDINARY_WINDOW },
        // Which position along the store's channel axis this row reads from.
        // Nothing splits the data — one store feeds every row that reads from it.
        channelIndex: within,
        visible: channel.visible !== false,
      });
    });
  });
  return rows;
}

/**
 * A view showing the whole of the first acquisition, used only until the page
 * says where it would rather be.
 */
function openingViewFor(own) {
  const first = own.opened[0];
  if (!first) return NOWHERE_IN_PARTICULAR;
  const across = widthAndHeightInVoxels(first.pyramid[0]);
  const um = first.umPerVoxel;
  return theViewThatShowsAllOf({
    atUm: first.originUm,
    wideUm: across.width * um.x,
    tallUm: across.height * um.y,
    specimenUm: first.specimen ? {
      x: first.originUm.x + first.specimen.x * um.x,
      y: first.originUm.y + first.specimen.y * um.y,
    } : null,
  }, own.size) || NOWHERE_IN_PARTICULAR;
}

/** Where to look when there is no acquisition to look at. */
const NOWHERE_IN_PARTICULAR = { centre: { x: 0, y: 0 }, zoom: 1 };

/** How many voxels across and down the full-resolution image is. */
function widthAndHeightInVoxels(source) {
  const across = source.labels.indexOf("x");
  const down = source.labels.indexOf("y");
  return { width: source.shape[across], height: source.shape[down] };
}

// ---------------------------------------------------------------------------
// The little program that runs on the graphics card
// ---------------------------------------------------------------------------

/**
 * Let ground nobody has imaged show what is beneath it, instead of painting it
 * black.
 *
 * **What it is fixing.** A run declares room to the reach of the stage before it
 * images anything, because room nobody writes into costs nothing, and then
 * fills a small part of it in. Viv draws that whole declared canvas, and the
 * last thing its colouring does is set the transparency to "fully opaque"
 * regardless of how bright the spot is. In its own viewer that is right — there
 * is nothing underneath to reveal. Here there is: the operator's carrier, their
 * wells and their planned tiles are all drawn under the picture, and left alone
 * the picture would paint black rectangles over every part of the plan the
 * microscope has not yet visited.
 *
 * **What it does.** After the colour has been worked out, it takes the
 * brightest of the three colour channels and fades the transparency to nothing
 * as that approaches zero. Nothing recorded means nothing painted. Measured
 * with a colour painted behind the canvas and nothing of the operator's own
 * drawn over it, this takes what an operator sees over ground nobody imaged
 * from 90.5% that colour and 6.5% black to 96.9% that colour and no black at
 * all. On a canvas eight thousand voxels across with a small patch imaged in
 * it, the difference is starker still: without this, the band of page colour
 * around the patch is painted over entirely and the registration measurement
 * cannot find it, reporting only that the band had closed.
 *
 * **The surprise, which is worth more than the fix.** Where the run kept a
 * coverage record, none of this is needed. `onlyWhereTheRunHasImaged` below
 * refuses to ask for a piece of image over ground the run has not imaged, so
 * Viv is given nothing to draw there and draws nothing — transparency stops
 * being computed from brightness and becomes structural. Taking this shader out
 * altogether changed no measurement taken with the coverage record in use.
 * That is the arrangement `viz_studio/OPTIONS.md` describes under "Nothing is
 * drawn until something is there", arrived at here by a different route, and it
 * is the arrangement that ships. This shader is what keeps a run that kept *no*
 * record from blacking out the operator's plan.
 *
 * **What it costs, so that it is chosen rather than discovered.** It asks the
 * pixels how bright they are, and a place that genuinely *was* imaged and came
 * back black looks exactly like a place nobody has visited — so a truly dark
 * specimen would disappear along with the empty room. That is a real cost and
 * it is not this file's to fix: `viz_studio/OPTIONS.md` sets out the two ways to
 * take the ambiguity away for good, under "Telling imaged-and-dark from
 * never-visited", and records that the decision has not been taken.
 *
 * The fade is soft rather than a sharp cut, over the first two per cent of the
 * brightness window, because a sharp cut leaves a hard jagged edge wherever the
 * specimen fades out into background.
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
// Not asking about ground nobody has imaged
// ---------------------------------------------------------------------------

/**
 * The imaged rectangles, as ranges of full-resolution voxels.
 *
 * The coverage record already counts in voxels of the full-resolution image,
 * because that is what the writer knows, so nothing is converted here.
 */
function imagedVoxelRanges(coverage) {
  if (!coverage?.regions?.length) return [];
  return coverage.regions.map((region) => ({
    x0: region.x[0], x1: region.x[1],
    y0: region.y[0], y1: region.y[1],
  }));
}

/**
 * The same pyramid of smaller copies, but refusing to fetch a piece of image
 * over ground the run has not imaged.
 *
 * This is the single largest saving available on the shape of run this viewer
 * is for: a large canvas declared up front with a small patch imaged in it, so
 * that most of what an engine would ask for is a piece nobody has written.
 * Every one of those still costs a round trip to wherever the store lives, and
 * on a network share that is the difference between comfortable and painful.
 *
 * It is done by wrapping the reader rather than by shrinking anything on
 * screen, which is worth noticing: because the picture and the operator's
 * drawing are in one canvas here, there is no engine surface to make smaller,
 * and there does not need to be. The reader simply says "nothing was imaged
 * here" without asking, and Viv draws nothing for that tile.
 *
 * Measured on a canvas eight thousand voxels across with a small patch imaged
 * in the middle of it, this took one redraw from 720 requests, 675 of them for
 * ground nobody had been to, down to 36 requests and none wasted — and from
 * 2.52 seconds to 0.14.
 *
 * @param source one copy of the image, as Viv's reader hands it over
 * @param level  which copy: 0 is full resolution, 1 is half, and so on
 * @param regions the imaged rectangles, in full-resolution voxels
 */
function onlyWhereTheRunHasImaged(source, level, regions) {
  // How many full-resolution voxels one voxel of this copy stands for. Viv's
  // pyramids halve at each step, which is what this writer produces.
  const stands = 2 ** level;
  const tile = source.tileSize;
  const bounded = Object.create(source);
  bounded.getTile = (props) => {
    const x0 = props.x * tile * stands;
    const x1 = x0 + tile * stands;
    const y0 = props.y * tile * stands;
    const y1 = y0 + tile * stands;
    const touchesImagedGround = regions.some(
      (region) =>
        region.x0 < x1 && x0 < region.x1 && region.y0 < y1 && y0 < region.y1,
    );
    if (!touchesImagedGround) return Promise.resolve(NOTHING_WAS_IMAGED_HERE);
    return source.getTile(props);
  };
  return bounded;
}

// ---------------------------------------------------------------------------
// What the engine is asked to draw
// ---------------------------------------------------------------------------

/**
 * Everything drawn this frame, bottom first: the application's own ground, then
 * the picture, then the application's own marks over it.
 *
 * These are the three layers of `viz_studio/THE_CANVAS.md`, in one canvas, drawn
 * in one pass. The first and the last are both the application's — the page
 * hands over one drawing function for each and never learns which engine
 * received them — and the picture sits between them. Because all three are
 * placed from the same view in the same frame, they cannot come apart even in
 * principle, which is the property this option exists to demonstrate.
 *
 * The bottom layer is left out entirely when the page has nothing to put there,
 * which is the ordinary case for the measurements taken before there was a
 * bottom layer at all.
 *
 * A page may also, as the harness does by default, keep everything of its own on
 * the top layer as one sheet with holes cut in it wherever the run has imaged.
 * That looks upside down and is not: laid over the picture, the holes are
 * exactly where the picture shows and everything else is the operator's plan. It
 * is the arrangement an engine that cannot draw beneath its own canvas obliges
 * an application into, and it is kept working here so that all three options can
 * be compared drawing exactly the same thing.
 */
function layersFor(own) {
  const layers = [];
  if (own.paintBeneath && own.textureBeneath) layers.push(theGroundBeneathLayer(own));
  layers.push(...imageLayersFor(own));
  layers.push(theOperatorsDrawingLayer(own));
  return layers;
}

/**
 * What each of a store's channels asks to be drawn through.
 *
 * Read here rather than where the rows are built, because that is not a place
 * that can wait for anything, and read per channel because two channels of one
 * acquisition are routinely far apart — measured on a skin biopsy, one reaches
 * 4573 counts and the other 8859, so one window across the pair flattens
 * whichever is fainter. Only wanted where the run gave no window of its own; the
 * read is a single small chunk per channel and costs little either way.
 */
async function everyChannelsRange(sources, metadata) {
  const described = metadata?.omero?.channels;
  const many = Array.isArray(described) && described.length ? described.length : 1;
  const ranges = [];
  for (let channel = 0; channel < many; channel += 1) {
    ranges.push(await theRangeTheseSourcesHold(sources, { channel }));
  }
  return ranges;
}

/** One layer per acquisition, drawn in the order they were given. */
function imageLayersFor(own) {
  /* The picture switched off is no image layers in the next frame; the
     operator's own layers are added around this and are unaffected. Hiding them
     with deck.gl's own `visible: false` instead was tried and measured worse —
     see the note in `viv-under`, where the numbers are. */
  if (own.showingPicture === false) return [];
  const regions = own.boundToCoverage ? imagedVoxelRanges(own.coverage) : [];
  return own.opened.map((store, atStore) => {
    const rows = own.rows.filter((row) => row.atStore === atStore);
    const visible = rows.filter((row) => row.visible);
    if (!visible.length) return null;
    const pyramid = own.boundToCoverage && regions.length
      ? store.pyramid.map((source, level) =>
          onlyWhereTheRunHasImaged(source, level, regions))
      : store.pyramid;
    return new MultiscaleImageLayer({
      id: `picture-${atStore}-${store.name}`,
      loader: pyramid,
      selections: visible.map((row) => selectionFor(own, store, row)),
      contrastLimits: visible.map((row) => [row.window.low, row.window.high]),
      channelsVisible: visible.map(() => true),
      colors: visible.map((row) => row.colour.map((part) => Math.round(part * 255))),
      // Where a second acquisition was written at a different voxel size, it is
      // stretched onto the world the first one defines. The width is left alone
      // wherever it can be, because Viv chooses which copy of the pyramid to
      // fetch from the width of this matrix and rounds that choice — so a
      // matrix that only stretches the height costs nothing at all.
      modelMatrix: stretchOntoTheSameWorld(own, store),
      // Nothing here is clicked on, and answering "what is under the pointer"
      // costs a second, hidden drawing of the frame.
      pickable: false,
      extensions: [
        new ColorPaletteExtension(),
        new LetTheUnimagedGroundShowThrough(),
      ],
      // Ground nobody has imaged is drawn nowhere at all when the coverage
      // record says where the run has been. The coarse copy Viv would otherwise
      // paint underneath everything covers the whole declared canvas by
      // definition, so it is exactly the thing that must not be fetched.
      excludeBackground: own.boundToCoverage && regions.length > 0,
      onTileError: () => {},
      updateTriggers: {
        // Handing over a freshly opened reader is how a tile that has just
        // landed reaches the screen. Saying so here is what makes Viv let go of
        // the tiles it has already decoded and fetch them again.
        getTileData: [store.pyramid, own.plane, own.moment],
      },
    });
  }).filter(Boolean);
}

/**
 * Which plane, which moment and which channel this row reads.
 *
 * Only the axes the store actually has are named, because naming one it has not
 * got is an error rather than something to be ignored.
 */
function selectionFor(own, store, row) {
  const labels = store.pyramid[0].labels;
  const asked = {};
  if (labels.includes("c")) asked.c = row.channelIndex;
  if (labels.includes("z")) {
    const um = store.umPerVoxel.z || 1;
    asked.z = Math.max(0, Math.round(own.plane / um));
  }
  if (labels.includes("t")) asked.t = Math.max(0, Math.round(own.moment));
  return asked;
}

/**
 * An acquisition put where it belongs in the world the first one defines:
 * stretched to the same voxel size, and moved to where it says it begins.
 *
 * The world here is **voxels of the first acquisition, counted from the stage's
 * zero**, and both halves of that matter. The unit is the first acquisition's
 * voxel because that is the space deck.gl's layers naturally live in. The zero
 * is the stage's zero rather than the first acquisition's corner, so that the
 * page's micrometres mean the same thing however the first run happens to have
 * been placed.
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
function stretchOntoTheSameWorld(own, store) {
  const reference = own.umPerVoxel;
  const mine = store.umPerVoxel;
  const across = mine.x / reference.x;
  const down = mine.y / reference.y;
  // The corner, in the same voxels the engine counts in.
  const from = {
    x: store.originUm.x / reference.x,
    y: store.originUm.y / reference.y,
  };
  if (across === 1 && down === 1 && from.x === 0 && from.y === 0) return undefined;
  return new Matrix4().translate([from.x, from.y, 0]).scale([across, down, 1]);
}

// ---------------------------------------------------------------------------
// Micrometres in, micrometres out
// ---------------------------------------------------------------------------
//
// deck.gl has a notion of magnification of its own, and it is not one the
// operator should ever meet: it counts in powers of two, where zero means one
// unit of its own world to the screen pixel, and its world is whatever the
// layers were placed in. The store and the microscope stage both speak
// micrometres, so that is what crosses the interface, and the conversion lives
// here and nowhere else.
//
// The world the layers are placed in is **voxels of the first acquisition's
// full-resolution image**. That choice is worth stating, because it is the one
// place a unit could go wrong. Viv places an image one world unit to the voxel
// unless it is told otherwise, and telling it otherwise changes which copy of
// the pyramid it chooses as well as where it draws — two things at once, one of
// them rounded. Leaving its own placement alone and converting here instead
// keeps the conversion in a single line that can be read and checked.
//
// The arithmetic, so it can be checked rather than trusted:
//
//     world units per screen pixel  =  µm per screen pixel ÷ µm per voxel
//     deck.gl's magnification       =  −log₂(world units per screen pixel)
//
// A second acquisition written at a different voxel size is scaled onto the
// same world with a matrix, in `imageLayersFor`.

/** Where deck.gl should be looking, worked out from the view in micrometres. */
function theViewStateFor(own) {
  const { centre, zoom } = own.view;
  const um = own.umPerVoxel;
  return {
    target: [centre.x / um.x, centre.y / um.y, 0],
    zoom: -Math.log2(zoom / um.x),
  };
}

/** The rectangle of specimen the window is showing, in world units. */
function theWindowInWorld(own) {
  const { centre, zoom } = own.view;
  const { width, height } = own.size;
  const um = own.umPerVoxel;
  const acrossPerPixel = zoom / um.x;
  const downPerPixel = zoom / um.y;
  const middleX = centre.x / um.x;
  const middleY = centre.y / um.y;
  return {
    left: middleX - (width / 2) * acrossPerPixel,
    right: middleX + (width / 2) * acrossPerPixel,
    top: middleY - (height / 2) * downPerPixel,
    bottom: middleY + (height / 2) * downPerPixel,
  };
}

/** The view now on screen, in micrometres. */
function readTheView(own) {
  return {
    centre: { x: own.view.centre.x, y: own.view.centre.y },
    zoom: own.view.zoom,
  };
}

/**
 * Move the view, in micrometres, and draw the frame that follows from it.
 *
 * The view and the layers are handed over together, in one call, and this is
 * the heart of why this option needs no discipline about repainting. deck.gl
 * takes both and draws them in one pass, so the picture and the operator's
 * drawing in any frame were placed from the same numbers. There is no follower
 * and nothing to lag.
 */

/**
 * Tell whoever asked that the picture has moved.
 *
 * One listener failing must not stop the next from hearing, and must not take
 * down the movement that caused it: the picture has already moved by the time
 * this runs, and a panel that fails to redraw its slider is a smaller fault
 * than a viewer that stops answering the operator's hand.
 */
function sayTheViewMoved(own) {
  if (own.destroyed) return;
  for (const tell of own.watchingTheView) {
    try {
      tell();
    } catch (why) {
      console.warn("something listening for the view moving failed", why);
    }
  }
}

function writeTheView(own, asked) {
  const now = own.view;
  own.view = {
    centre: asked.centre || now.centre,
    zoom: asked.zoom > 0 ? asked.zoom : now.zoom,
  };
  showTheView(own);
}

/** Hand deck.gl the view and the layers that go with it, together. */
function showTheView(own) {
  if (!own.deck || own.destroyed) return;
  own.deck.setProps({
    viewState: theViewStateFor(own),
    layers: layersFor(own),
  });
  // Every way the picture can move ends here — the gestures, `setView`,
  // `setPlane`, `setMoment` — so this is the one place that has to say so.
  sayTheViewMoved(own);
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
  const view = own.view;
  return {
    centre: { x: view.centre.x, y: view.centre.y },
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
 * The operator's drawing, as one layer glued to the rectangle of specimen the
 * window is showing.
 *
 * Everything drawn in the offscreen canvas is therefore fixed to the specimen
 * rather than to the window, exactly as the picture is, and deck.gl places both
 * with the same view in the same pass. That is what makes the two impossible to
 * separate: it is not that the drawing follows the picture accurately, it is
 * that there is nothing for it to follow.
 *
 * The four numbers are given in the order deck.gl reads them for an image —
 * left, bottom, right, top — and here the bottom of the screen is the larger
 * value, because a microscope's coordinates run down the screen as the rows of
 * a camera do.
 */
function theOperatorsDrawingLayer(own) {
  const showing = theWindowInWorld(own);
  return new TheOperatorsDrawing({
    id: "the-operators-drawing",
    image: own.texture,
    bounds: [showing.left, showing.bottom, showing.right, showing.top],
    pickable: false,
    repaintFromTheFrameBeingDrawn: () => repaint(own),
    updateTriggers: { repaintFromTheFrameBeingDrawn: [] },
  });
}

/**
 * The application's ground, as one layer glued to the same rectangle of specimen
 * and drawn before the picture.
 *
 * Exactly the same construction as the operator's drawing above, differing in
 * two things only: which offscreen canvas it carries, and where it sits in the
 * list of layers. That is the whole of what a bottom layer costs in this option,
 * and it is worth noticing how little it is — the arrangement was already three
 * layers over the same ground, and this simply puts one of them underneath.
 */
function theGroundBeneathLayer(own) {
  const showing = theWindowInWorld(own);
  return new TheOperatorsDrawing({
    id: "the-ground-beneath",
    image: own.textureBeneath,
    bounds: [showing.left, showing.bottom, showing.right, showing.top],
    pickable: false,
    repaintFromTheFrameBeingDrawn: () => repaintTheGroundBeneath(own),
    updateTriggers: { repaintFromTheFrameBeingDrawn: [] },
  });
}

/**
 * An image layer that redraws its own picture as part of the frame.
 *
 * This is where the page's drawing function is called, and it is called from
 * inside deck.gl's own drawing of the frame — which is what `contract.md` asks
 * of a single-canvas option. The page hands over one function and never learns
 * when it is called or what is underneath it.
 */
class TheOperatorsDrawing extends BitmapLayer {
  draw(opts) {
    this.props.repaintFromTheFrameBeingDrawn?.();
    super.draw(opts);
  }
}
TheOperatorsDrawing.layerName = "TheOperatorsDrawing";
TheOperatorsDrawing.defaultProps = {
  ...BitmapLayer.defaultProps,
  // Compared as a plain value rather than by what it does, so that handing over
  // the same job written a second time does not rebuild the layer.
  repaintFromTheFrameBeingDrawn: { type: "function", value: null, compare: false },
};

/**
 * Draw the operator's own shapes into the offscreen canvas, and put the result
 * where the graphics card can see it.
 *
 * The page's drawing function is handed everything it needs to place a shape in
 * micrometres and nothing that would let it ask the engine a question, which is
 * what keeps one piece of drawing code working over all three options.
 */
function repaint(own) {
  if (own.destroyed || !own.context || !own.texture) return;
  const { width, height, density } = own.size;
  const context = own.context;
  context.setTransform(density, 0, 0, density, 0, 0);
  context.clearRect(0, 0, width, height);
  if (own.paint) {
    own.paint({ ...howThingsArePlaced(own), context, coverage: own.coverage });
  }
  own.texture.copyExternalImage({
    image: own.drawing,
    width: own.drawing.width,
    height: own.drawing.height,
  });
  own.counted.overlayPaints += 1;
}

/**
 * The same again for the bottom layer, drawn from the same view in the same
 * frame.
 *
 * Called from inside that layer's own drawing, which deck.gl runs before the
 * picture's, so the ground is up to date at the moment it is composited. There
 * is no possibility of the two being a frame apart: the whole list of layers is
 * drawn in one pass from one view.
 */
function repaintTheGroundBeneath(own) {
  if (own.destroyed || !own.contextBeneath || !own.textureBeneath) return;
  const { width, height, density } = own.size;
  const context = own.contextBeneath;
  context.setTransform(density, 0, 0, density, 0, 0);
  context.clearRect(0, 0, width, height);
  if (own.paintBeneath) {
    own.paintBeneath({
      ...howThingsArePlaced(own), context, coverage: own.coverage,
    });
  }
  own.textureBeneath.copyExternalImage({
    image: own.drawingBeneath,
    width: own.drawingBeneath.width,
    height: own.drawingBeneath.height,
  });
  own.counted.groundPaints += 1;
}

// ---------------------------------------------------------------------------
// Going back to the store for what has arrived since
// ---------------------------------------------------------------------------

/**
 * Open every acquisition again and hand deck.gl the fresh readers.
 *
 * Only one such read is allowed to be in flight at a time. If somebody asks
 * again while a read is going on, the asking is remembered and one more read
 * happens when this one finishes — which is what a run writing steadily
 * produces, and it settles rather than piling up.
 *
 * There are two reasons for that, and it is worth being plain about which of
 * them has actually been seen. The first is waste, and it was measured: told
 * ten times in quick succession that a tile might have landed, this opens the
 * store three times and asks the server for twelve pieces of image, where
 * without the guard it opens it ten times and asks for twenty. The second is
 * the patchwork the live-tiles work met earlier in this project, where a second
 * read started too early left parts of two different generations on screen at
 * once. That one was *not* reproduced here, on these small acquisitions, even
 * with every piece of image deliberately slowed by 150 ms — the picture went
 * from the old amount to the new one with nothing in between. So the guard is
 * kept for a measured saving and a remembered fault, not for a fault seen here.
 */
async function openTheStoresAgain(own) {
  own.anotherLookIsWanted = true;
  if (own.readingAgain) return own.counted.lastAsked;
  own.readingAgain = true;
  try {
    while (own.anotherLookIsWanted && !own.destroyed) {
      own.anotherLookIsWanted = false;
      let asked = 0;
      for (const store of own.opened) {
        const fresh = await readTheStore(store.asked.url, store.name);
        if (own.destroyed) return own.counted.lastAsked;
        store.pyramid = fresh.data;
        store.metadata = fresh.metadata;
        asked += fresh.data.length;
      }
      own.counted.letGoes += 1;
      own.counted.lastAsked = asked;
      showTheView(own);
    }
  } finally {
    own.readingAgain = false;
  }
  return own.counted.lastAsked;
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
    /** How deep the stack is, in micrometres; see `viv-under` for why. */
    theDepthItCanShow() {
      const first = own.opened[0];
      const source = first?.pyramid?.[0];
      const at = source?.labels?.indexOf("z") ?? -1;
      const deep = at >= 0 ? source.shape[at] : 0;
      const um = first?.umPerVoxel?.z;
      if (!(deep > 1) || !(um > 0)) return null;
      return { lowUm: 0, highUm: (deep - 1) * um, stepUm: um,
               atUm: own.plane ?? 0 };
    },

    setPlane(z) {
      own.plane = z;
      showTheView(own);
    },

    /** Which moment of a timelapse to show, counted from the first. */
    setMoment(t) {
      own.moment = t;
      showTheView(own);
    },

    /**
     * Be told whenever the picture has moved.
     *
     * The view moves for reasons a panel knows nothing about — the scroll
     * wheel, a step of the workflow driving the stage, a plane chosen from
     * somewhere other than the control that shows it. A control that is only
     * ever written to goes on showing where it last put the operator, which
     * after any of those is not where the picture is. So anything drawing a
     * control for the depth, the moment or the view asks to hear about a
     * movement it did not make itself, and reads the answer back out of
     * `theDepthItCanShow()` rather than remembering its own.
     *
     * Hand over a function; hand back what stops it being called. It reports
     * *that* the picture moved rather than where to, because the one honest
     * answer to "where is it now" is the one this viewer gives when asked.
     */
    whenTheViewMoves(tell) {
      if (typeof tell !== "function") return () => {};
      own.watchingTheView.push(tell);
      return () => {
        own.watchingTheView = own.watchingTheView.filter((one) => one !== tell);
      };
    },

    /**
     * Change one channel: whether it shows, what colour it is drawn in, and the
     * brightness window applied to it.
     *
     * `index` counts across all the acquisitions in the order they are drawn,
     * which is the order they appear in a list on screen.
     */
    /** Whether this engine can draw the stack as a volume. */
    canShowVolume: false,

    canShowVolumeBecause: "this option draws one plane through an orthographic view; Viv has a volume view, and wiring it up is work rather than a setting",

    /* Says no rather than doing nothing quietly. A page asks `canShowVolume`
       first and does not offer what cannot be done, so this is only reached by
       an application that asked anyway — and an application that asked anyway is
       better told than ignored. */
    showVolume() {},

    /**
     * Draw the acquisitions, or do not — the viewer stays open either way.
     *
     * Leaving the image layers out of the next frame, rather than opening the
     * canvas again with no acquisitions, which is how this used to be done: a
     * reopen costs the picture being fetched and decoded from nothing on the way
     * back, and on one of the three engines it never finishes at all.
     */
    showPicture(on) {
      own.showingPicture = on !== false;
      showTheView(own);
    },

    setChannel(index, { visible, colour, window: brightness } = {}) {
      const row = own.rows[index];
      if (!row) return;
      if (visible !== undefined) row.visible = visible;
      if (colour) row.colour = colour;
      if (brightness) row.window = brightness;
      showTheView(own);
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
     * correct — here, from inside deck.gl's own drawing of a frame, with the
     * view that frame is being drawn from. The page never knows which option is
     * underneath it, which is what makes comparing the three fair.
     *
     * ## Why an offscreen canvas, and what was considered instead
     *
     * deck.gl has no two-dimensional drawing context to offer: it draws layers,
     * not strokes. So something had to give, and `contract.md` is explicit about
     * what must not: **the page's drawing code**. A viewer that needed its own
     * version of the operator's drawing would make the comparison meaningless,
     * because a difference somebody felt might then be the drawing rather than
     * the approach.
     *
     * What is done here is what `contract.md` suggests, with one change worth
     * explaining. The page draws into an ordinary offscreen canvas, and that
     * canvas is composited inside the single pass. The change is *how* it is
     * composited: rather than being stretched over the window, it is handed to
     * deck.gl as an image occupying the exact rectangle of specimen the window
     * is showing. It is therefore placed by the same view, in the same pass, as
     * the picture — so the two cannot come apart even in principle, which is the
     * property this whole option exists to demonstrate.
     *
     * Two other ways were considered and set aside. Drawing the operator's
     * shapes as deck.gl layers of their own — a path layer for the carrier, a
     * polygon layer for the tiles — would be the natural deck.gl way, and it is
     * ruled out for exactly the reason above: it would mean this option drawing
     * something different from the other two. Compositing the canvas over the
     * top afterwards, outside deck.gl's pass, would reintroduce the second
     * surface and everything that goes with keeping two surfaces in step, which
     * is the thing this option is here to do without.
     */
    drawOver(paint) {
      own.paint = paint;
      // Drawn again at once rather than at the next frame, because the page
      // hands its drawing over between frames and would otherwise show the
      // previous one until something else moved.
      own.deck?.redraw("the operator's drawing was handed over");
    },

    /**
     * The application's own drawing, beneath the picture.
     *
     * The same shape of function as `drawOver`, called at the same moment with
     * the same frame, so a page writes the two the same way. Hand over `null` to
     * say there is nothing beneath, and no second offscreen canvas is made at
     * all.
     *
     * Here the bottom layer is simply another layer in the same list, placed
     * before the picture instead of after it. All three are drawn in one pass
     * from one view, so the ground beneath, the acquisition and the operator's
     * marks share a coordinate system by construction and there is nothing that
     * could fall behind. `drawsUnder` is `true`.
     */
    drawUnder(paint) {
      own.paintBeneath = paint;
      if (paint) makeTheGroundBeneath(own);
      showTheView(own);
      own.deck?.redraw("the ground beneath was handed over");
    },

    /**
     * Whether a drawing handed to `drawUnder` really ends up beneath the
     * picture, where an operator can see it.
     *
     * `true` here, and it is the strongest form of yes among the three options:
     * there is no second canvas that could cover it, because there is only one
     * canvas.
     */
    drawsUnder: true,

    /** Why, in a sentence a page can show to whoever is looking at it. */
    drawsUnderBecause:
      "the ground beneath, the picture and the operator's marks are three " +
      "layers in one canvas, drawn in one pass from one view, so the bottom " +
      "one is simply the first thing drawn.",

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
     * click needs. The same record is handed to `onViewChanged` for every frame
     * drawn, so an element can be moved in the same instant the picture moved
     * rather than a frame later.
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
     * Nothing on disk announces a new tile. A run declares its images at full
     * size before the first tile exists, and their description is identical
     * before and after, so there is nothing for a watcher to notice. Worse, the
     * reader remembers every piece of image it has fetched **including the
     * pieces it found empty** — so a tile written into ground it has already
     * looked at is not "slow to appear", it is never fetched again at all.
     *
     * What is needed is a freshly opened reader, which remembers nothing, and
     * that is what this does.
     *
     * A newer coverage record can be handed over at the same time, and in
     * practice it must be. The record says where the run has imaged, and while a
     * run is going that answer changes — which is the whole point of it. Two
     * things are worked out from it: where the operator's drawing cuts its
     * holes, and which pieces of image are worth asking for at all. Both were
     * settled when the viewer opened, so without a newer record a tile written
     * outside the ground the run had reached at that moment shows through
     * nothing and is never fetched.
     *
     * Returns how many copies of the image were opened afresh, so that a
     * measurement can tell "it was asked and nothing happened" from "it was
     * never asked" — two failures that look identical on screen and have quite
     * different causes.
     */
    tilesMayHaveLanded({ coverage } = {}) {
      if (coverage) {
        own.coverage = coverage;
        own.boundToCoverage =
          own.boundToCoverage && Boolean(coverage.regions?.length);
      }
      return openTheStoresAgain(own);
    },

    /** Close the viewer and let go of everything it was holding. */
    destroy() {
      if (own.destroyed) return;
      own.destroyed = true;
      /* Anything that asked to hear the view move is let go of here too, so a
         panel taken down without unsubscribing cannot keep a listener alive on
         a viewer that has closed. */
      own.watchingTheView = [];
      // The gestures come off first. Listeners left behind on a box that is
      // still in the page would go on answering the operator's hand after the
      // viewer they belonged to had gone. The little record of what they saw is
      // kept rather than thrown away, so that a check can still ask a closed
      // viewer whether anything reached it after it shut.
      own.gestures?.stop();
      own.paint = null;
      own.paintBeneath = null;
      own.deck?.finalize();
      own.deck = null;
      own.texture?.destroy?.();
      own.texture = null;
      own.textureBeneath?.destroy?.();
      own.textureBeneath = null;
      own.drawingBeneath = null;
      own.contextBeneath = null;
      own.canvas?.remove();
      own.canvas = null;
      own.opened = [];
      own.rows = [];
    },

    /**
     * How much drawing has actually happened.
     *
     * Not part of the interface an application would use, and deliberately
     * named so that it reads as what it is. The measurements need it for one
     * narrow purpose: on screen, "the drawing never moved" and "the drawing
     * moved to the wrong place" look identical when the right answer is that
     * nothing should have happened. Every number the measurements *report*
     * still comes from a photograph.
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
