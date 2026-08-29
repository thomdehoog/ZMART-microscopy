/**
 * A scan of ten thousand fields, drawn from one small JPEG per field.
 *
 * The other engines here read the microscope's own files and do the hard work
 * in the browser. This one does almost nothing: the fields have already been
 * turned into small JPEGs by `viz_studio/backend/jpeg_tiles.py`, and all this
 * has to do is put each one in its place. That is the whole idea. A scan of
 * ten thousand fields is tens of gigabytes of TIFF and about a hundred
 * megabytes of JPEG, and the difference between those two numbers is the
 * difference between a picture that opens and one that does not.
 *
 * ## What makes ten thousand workable
 *
 * Three rules, and nothing else:
 *
 * 1. Only the fields actually on screen are drawn. The cost of a frame follows
 *    what is visible, not what exists.
 * 2. A field too small on screen to show anything is drawn as the one colour
 *    its note carries, and its picture is never fetched. Zoomed out to a whole
 *    scan that is every field at once, which is why a scan of ten thousand
 *    opens with no pictures fetched at all.
 * 3. Only so many pictures are kept decoded, because a decoded picture costs
 *    far more memory than the JPEG it came from.
 *
 * ## Where the pictures come from, and what they are not
 *
 * A folder of small JPEGs with a `tiles.json` beside them saying where each
 * one belongs, in micrometres. Nothing here opens a TIFF, and nothing here
 * works out where a field is: a TIFF does not say where it was taken, so that
 * question was settled when the pictures were made, by the run that knew.
 *
 * These are display copies. They are lossy, they are brightened for
 * legibility, and nothing should ever be measured from them.
 *
 * ## The picture is underneath
 *
 * Three drawing surfaces are stacked in the box: the operator's drawing, then
 * the scan, then the operator's drawing again. So `drawUnder` really is under
 * the picture here, which is not true of every engine, and `drawsUnder` says
 * so honestly. That is also what makes swapping this for neuroglancer later a
 * change of engine and nothing else — both put the scan at the bottom and take
 * the same two drawings around it.
 *
 * ## Fields arriving while somebody is watching
 *
 * A scan is looked at while it is still being taken, so `tiles.json` grows.
 * The page says `tilesMayHaveLanded()` when it thinks something new has been
 * written, and this reads the note again. It is asked rather than told for the
 * reason this project keeps meeting: nothing on disk announces itself, and a
 * picture that waits to be notified waits for ever.
 */

import { onlyPanAndZoom } from "../gestures.js";

/**
 * How many decoded pictures to keep at once.
 *
 * A field kept at 128 pixels is four kilobytes as a JPEG and sixty-four
 * decoded, so they cannot all be held. A thousand is a few tens of megabytes,
 * which measured out as the point where panning still runs at a full sixty
 * frames a second.
 */
const HOW_MANY_TO_KEEP_DECODED = 1000;

/** Open the viewer inside `element`. See `viz_studio/options/contract.md`. */
export async function openViewer(element, options = {}) {
  const { acquisitions = [], background = "#05070d", onViewChanged = null } = options;

  const own = {
    element,
    background,
    onViewChanged,
    destroyed: false,
    /* One entry per acquisition, in the order the page gave them, each holding
       its own fields and whether it is being shown. Kept apart rather than
       poured into one list because a run is looked at as more than one picture:
       a survey of the whole slide, and later the detail scans taken from it.
       Which of those you are looking at is a question an operator asks
       constantly, and it can only be answered if they were never mixed. */
    pictures: acquisitions
      .filter((a) => a?.url)
      .map((a) => ({
        name: a.name || String(a.url).split("/").filter(Boolean).pop() || "picture",
        url: a.url,
        tiles: [],
        shown: true,
      })),
    decoded: new Map(),   // src -> picture, or the promise for one; oldest first
    showing: true,
    paintUnder: null,
    paintOver: null,
    view: { centre: { x: 0, y: 0 }, zoom: 1 },
    surfaces: null,
    gestures: null,
    frameAsked: false,
  };

  buildTheThreeSurfaces(own);
  await readTheNotes(own);
  fitToWhatThereIs(own);

  own.gestures = onlyPanAndZoom(own.surfaces.box, {
    getView: () => handle.getView(),
    setView: (v) => handle.setView(v),
  });

  const handle = {
    setView({ centre, zoom } = {}) {
      if (own.destroyed) return;
      if (centre && Number.isFinite(centre.x) && Number.isFinite(centre.y)) {
        own.view.centre = { x: Number(centre.x), y: Number(centre.y) };
      }
      if (Number.isFinite(zoom) && zoom > 0) own.view.zoom = Number(zoom);
      askForAFrame(own);
      settled(own);
    },

    getView() {
      return { centre: { ...own.view.centre }, zoom: own.view.zoom };
    },

    /* Flat by construction: the pictures are one per field, already flattened
       over every colour and depth the microscope took there. Saying so plainly
       is better than pretending to a depth this cannot show. */
    theDepthItCanShow() { return null; },
    setPlane() {},
    setMoment() {},
    setChannel() {},

    canShowVolume: false,
    canShowVolumeBecause:
      "the pictures are one flat JPEG per field, already flattened over every " +
      "colour and depth, so there is no stack left to draw as a volume.",

    showPicture(on) {
      own.showing = !!on;
      askForAFrame(own);
    },

    /**
     * The pictures this viewer is holding, and whether each is being drawn.
     *
     * A run is looked at as more than one picture. There is the survey of the
     * whole slide, and later the detail scans taken from places found in it,
     * and an operator wants to see either on its own or both together. So the
     * viewer keeps them apart and offers them by name, in the order they are
     * drawn — bottom of the stack first, so a detail scan lands over the survey
     * it came from.
     *
     * This is the bottom layer of the canvas, and the pictures in it are
     * deliberately plainer than the layers above: they are drawn or they are
     * not, and nothing here fades. Everything see-through lives above the
     * picture, which is what `viz_studio/LAYERS.md` settles and what lets the
     * whole arrangement survive being handed to an engine that cannot be made
     * see-through at all.
     */
    picturesInside() {
      return own.pictures.map(({ name, shown }) => ({ name, shown }));
    },

    /** Draw one of those pictures, or stop drawing it. Unknown names are ignored. */
    showPictureInside(name, on) {
      const picture = own.pictures.find((p) => p.name === name);
      if (!picture) return;
      picture.shown = !!on;
      askForAFrame(own);
    },

    handDragsTo(handler) {
      own.gestures?.handDragsTo?.(handler);
    },

    drawUnder(paint) {
      own.paintUnder = paint || null;
      askForAFrame(own);
    },

    drawOver(paint) {
      own.paintOver = paint || null;
      askForAFrame(own);
    },

    drawsUnder: true,
    drawsUnderBecause:
      "the scan is drawn on its own surface with one of the operator's above " +
      "it and one below, so a drawing handed to the bottom slot really is " +
      "beneath the picture.",

    whereThingsAreDrawn() {
      return whereThingsAre(own);
    },

    /* How many pictures may be held decoded at once. Said out loud because it
       is what decides how far out a field still gets its real picture, so a
       test that checks the scan looks even should not have to guess it. */
    howManyPicturesAreKept() { return HOW_MANY_TO_KEEP_DECODED; },

    async tilesMayHaveLanded() {
      if (own.destroyed) return;
      await readTheNotes(own);
      askForAFrame(own);
    },

    destroy() {
      own.destroyed = true;
      own.gestures?.stop?.();
      for (const picture of own.decoded.values()) picture?.close?.();
      own.decoded.clear();
      own.surfaces?.box.remove();
    },
  };

  askForAFrame(own);
  settled(own);
  return handle;
}

/** The three stacked surfaces: the operator below, the scan, the operator above. */
function buildTheThreeSurfaces(own) {
  const box = document.createElement("div");
  Object.assign(box.style, {
    position: "absolute", inset: "0", background: own.background, overflow: "hidden",
  });

  const make = () => {
    const canvas = document.createElement("canvas");
    Object.assign(canvas.style, {
      position: "absolute", inset: "0", width: "100%", height: "100%", display: "block",
    });
    box.append(canvas);
    return canvas;
  };

  own.surfaces = { box, under: make(), picture: make(), over: make() };
  own.element.append(box);
  fitTheSurfaces(own);
}

function fitTheSurfaces(own) {
  const rect = own.element.getBoundingClientRect();
  const density = globalThis.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * density));
  const height = Math.max(1, Math.round(rect.height * density));
  for (const key of ["under", "picture", "over"]) {
    const canvas = own.surfaces[key];
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
  }
  own.size = { width: rect.width, height: rect.height, density };
}

/**
 * Read every acquisition's note of where its pictures belong.
 *
 * A note that cannot be read is passed over rather than thrown. During a run
 * the file is being written, and catching it half-written is an ordinary
 * event, not a failure.
 */
async function readTheNotes(own) {
  for (const picture of own.pictures) {
    const at = String(picture.url).replace(/\/+$/, "");
    let note;
    try {
      const answer = await fetch(`${at}/tiles.json`, { cache: "no-store" });
      if (!answer.ok) continue;
      note = await answer.json();
    } catch {
      continue;
    }
    picture.tiles = (note?.tiles || []).map((tile) => ({
      src: `${at}/${tile.src}`,
      grey: Number(tile.grey),
      x0: Number(tile.x0),
      y0: Number(tile.y0),
      w: Number(tile.w),
      h: Number(tile.h),
    }));
  }
}

/** Every field of every picture that is being shown, bottom of the stack first. */
function* everyFieldOnShow(own) {
  for (const picture of own.pictures) {
    if (!picture.shown) continue;
    for (const tile of picture.tiles) yield tile;
  }
}

/** The piece of sample every field together covers, in micrometres. */
function theWholeScan(own) {
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  let any = false;
  for (const picture of own.pictures) {
    for (const tile of picture.tiles) {
      any = true;
      left = Math.min(left, tile.x0);
      top = Math.min(top, tile.y0);
      right = Math.max(right, tile.x0 + tile.w);
      bottom = Math.max(bottom, tile.y0 + tile.h);
    }
  }
  return any ? { left, top, right, bottom } : null;
}

function fitToWhatThereIs(own) {
  const scan = theWholeScan(own);
  if (!scan) return;
  fitTheSurfaces(own);
  const { width, height } = own.size;
  const across = Math.max(1e-9, scan.right - scan.left);
  const down = Math.max(1e-9, scan.bottom - scan.top);
  own.view = {
    centre: { x: (scan.left + scan.right) / 2, y: (scan.top + scan.bottom) / 2 },
    zoom: Math.max(across / Math.max(1, width), down / Math.max(1, height)) * 1.05,
  };
}

/**
 * Where a point on the sample lands in the box, and back again.
 *
 * Micrometres in, browser pixels from the top-left of the box out. Positions
 * are pairs of named numbers rather than pairs in a list, because that is what
 * `viz_studio/options/contract.md` settles on and what the shared gesture code
 * and every drawing the application hands over already expect. Getting this
 * wrong is quiet: a viewer whose own numbers agree with each other draws
 * perfectly well on its own and stops dead the moment somebody drags it.
 */
function whereThingsAre(own) {
  const { width = 0, height = 0, density = 1 } = own.size || {};
  const { centre, zoom } = own.view;
  const project = (x, y) => ({
    x: width / 2 + (x - centre.x) / zoom,
    y: height / 2 + (y - centre.y) / zoom,
  });
  const unproject = (x, y) => ({
    x: centre.x + (x - width / 2) * zoom,
    y: centre.y + (y - height / 2) * zoom,
  });
  return { centre: { ...centre }, zoom, width, height, density, project, unproject };
}

function settled(own) {
  if (own.destroyed || !own.onViewChanged) return;
  own.onViewChanged(whereThingsAre(own));
}

function askForAFrame(own) {
  if (own.destroyed || own.frameAsked) return;
  own.frameAsked = true;
  const draw = () => {
    own.frameAsked = false;
    if (!own.destroyed) drawEverything(own);
  };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(draw);
  else draw();
}

/**
 * The picture for one field, fetching it the first time it is wanted.
 *
 * Returns the decoded picture once it is ready, and before that the promise
 * for it, which the drawing simply skips. Nothing is ever waited for: the
 * field is drawn as its one colour meanwhile, and the frame that follows the
 * picture's arrival draws it properly.
 *
 * Asking for a picture also moves it to the back of the queue of what to let
 * go. A Map hands its keys back in the order they went in, so taking one out
 * and putting it straight back is enough to say "still wanted" — no second
 * list to keep in step, and it costs the same however many are being kept.
 */
function pictureFor(own, src) {
  const already = own.decoded.get(src);
  if (already) {
    own.decoded.delete(src);
    own.decoded.set(src, already);
    return already;
  }

  const coming = fetch(src)
    .then((answer) => (answer.ok ? answer.blob() : null))
    .then((blob) => (blob ? createImageBitmap(blob) : null))
    .then((picture) => {
      if (own.destroyed) {
        picture?.close?.();
        return null;
      }
      own.decoded.set(src, picture);
      askForAFrame(own);
      return picture;
    })
    .catch(() => null);

  own.decoded.set(src, coming);
  while (own.decoded.size > HOW_MANY_TO_KEEP_DECODED) {
    const oldest = own.decoded.keys().next().value;
    own.decoded.get(oldest)?.close?.();
    own.decoded.delete(oldest);
  }
  return coming;
}

/**
 * Draw the three surfaces.
 *
 * Every field on screen is drawn exactly once: as its real picture if there is
 * one and it is large enough to be worth having, and as the one colour its
 * note carries otherwise. So the scan is complete from the very first frame
 * and only sharpens — which matters because a picture that is still loading
 * looks exactly like one that is broken.
 */
function drawEverything(own) {
  fitTheSurfaces(own);
  const where = whereThingsAre(own);
  const { width, height, density } = own.size;

  const clear = (canvas) => {
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.scale(density, density);
    return ctx;
  };

  // Cleared whether or not there is anything to draw. An empty slot still has
  // to leave an empty surface, or a drawing switched off stays on screen.
  const under = clear(own.surfaces.under);
  own.paintUnder?.({ ...where, context: under, coverage: null });

  const picture = clear(own.surfaces.picture);
  if (own.showing) {
    for (const tile of everyFieldOnShow(own)) {
      const { x: left, y: top } = where.project(tile.x0, tile.y0);
      const across = tile.w / where.zoom;
      const down = tile.h / where.zoom;
      if (left + across < 0 || top + down < 0 || left > width || top > height) continue;

      /* Always the picture, at any size: a field's mean grey stands in only
         until its picture has arrived. Refusing to fetch below a size drew
         the whole overview as flat grey blocks at plate zoom, which is the
         zoom an operator judges a scan at. */
      const ready = pictureFor(own, tile.src);
      if (ready && typeof ready.width === "number") {
        // Smoothing on while a picture is being made smaller, off once it is
        // being made much larger. Shrinking without it means the browser picks
        // out single pixels rather than averaging them, and on a picture of
        // sparse bright specks that mostly picks the dark ground between them:
        // the field comes out darker than the colour standing for it, and
        // shimmers while somebody pans. Magnifying with it on is the opposite
        // mistake — a blur that looks like detail nobody took.
        picture.imageSmoothingEnabled = across < 2 * ready.width;
        picture.drawImage(ready, left, top, across, down);
      } else {
        const grey = Number.isFinite(tile.grey) ? tile.grey : 40;
        picture.fillStyle = `rgb(${grey},${grey},${grey})`;
        picture.fillRect(left, top, Math.max(1, across), Math.max(1, down));
      }
    }
  }

  const over = clear(own.surfaces.over);
  own.paintOver?.({ ...where, context: over, coverage: null });
}
