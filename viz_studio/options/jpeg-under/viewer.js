/**
 * The scan drawn from small JPEGs, one per field, with the operator's drawing
 * above and below it.
 *
 * The other engines read the microscope's own files and do the hard work in
 * the browser. This one does not: the fields have already been turned into
 * small JPEGs by `viz_studio/backend/jpeg_tiles.py`, and all this has to do is
 * put them in the right places. That is the whole idea. A scan of ten thousand
 * fields is tens of gigabytes of TIFF and a few tens of megabytes of JPEG, and
 * the difference between those two numbers is the difference between a picture
 * that opens and one that does not.
 *
 * It is deliberately the plainest engine here. No WebGL, no image pyramid, no
 * chunk fetching — a canvas, some pictures, and a rectangle each. What makes it
 * work at ten thousand is not cleverness but leaving things out: only the
 * fields actually on screen are ever drawn, and only those are ever decoded.
 *
 * ## Where the pictures come from, and what they are not
 *
 * A folder of small JPEGs and a `tiles.json` beside them saying where each
 * belongs, in micrometres. Nothing here opens a TIFF, and nothing here works
 * out where a field is: a TIFF does not say where it was taken, so that
 * question was settled when the pictures were made, by the run that knew.
 *
 * These are display copies. They are lossy, they are stretched for legibility,
 * and nothing should ever be measured from them.
 *
 * ## The picture is underneath
 *
 * This engine keeps three drawing surfaces stacked in the box it was given:
 * the operator's drawing, then the scan, then the operator's drawing again. So
 * `drawUnder` really is under the picture here, which is not true of every
 * engine, and `drawsUnder` says so honestly.
 *
 * That is also why swapping this for neuroglancer later is a change of engine
 * and nothing else. Both put the scan at the bottom and take the same two
 * drawings around it; the page hands over the same run, the same view and the
 * same two paint functions either way.
 *
 * ## Fields arriving while somebody is watching
 *
 * A scan is drawn while it is still being taken, so `tiles.json` grows. The
 * page says `tilesMayHaveLanded()` when it thinks something new has been
 * written and this reads the note again. It is asked rather than told for the
 * reason the whole project keeps meeting: nothing on disk announces itself,
 * and a picture that waits to be notified waits for ever.
 */

import { onlyPanAndZoom } from "../gestures.js";

/**
 * How many decoded pictures to keep.
 *
 * A decoded picture costs far more memory than the JPEG it came from, so they
 * cannot all be kept — that would give back exactly the problem this engine
 * exists to avoid. Only what is on screen is decoded, and this many are kept
 * afterwards so that panning back and forth does not decode the same field
 * over and over. A screenful is a few dozen fields; this is generous next to
 * that and still bounded far below ten thousand.
 */
const HOW_MANY_TO_KEEP_DECODED = 400;

/** Open the viewer inside `element`. See `viz_studio/options/contract.md`. */
export async function openViewer(element, options = {}) {
  const {
    acquisitions = [],
    background = "#05070d",
    onViewChanged = null,
  } = options;

  const own = {
    element,
    background,
    onViewChanged,
    destroyed: false,
    tiles: [],
    sources: [],
    decoded: new Map(),      // src -> ImageBitmap or the promise for one
    order: [],               // which was decoded least recently
    showing: true,
    paintUnder: null,
    paintOver: null,
    view: { centre: [0, 0], zoom: 1 },
    surfaces: null,
    gestures: null,
    frameAsked: false,
  };

  buildTheThreeSurfaces(own);
  own.sources = acquisitions.map((a) => a.url).filter(Boolean);
  await readTheNotes(own);
  fitToWhatThereIs(own);

  own.gestures = onlyPanAndZoom(own.surfaces.box, {
    getView: () => handle.getView(),
    setView: (v) => handle.setView(v),
  });

  const handle = {
    setView({ centre, zoom } = {}) {
      if (own.destroyed) return;
      if (Array.isArray(centre)) own.view.centre = [Number(centre[0]), Number(centre[1])];
      if (Number.isFinite(zoom) && zoom > 0) own.view.zoom = Number(zoom);
      askForAFrame(own);
      settled(own);
    },

    getView() {
      return { centre: [...own.view.centre], zoom: own.view.zoom };
    },

    /* Flat by construction: the pictures are one per field, already flattened
       over every colour and depth the microscope took there. Saying so plainly
       is better than pretending to a depth this cannot show. */
    theDepthItCanShow() { return null; },
    setPlane() {},
    setMoment() {},

    showPicture(on) {
      own.showing = !!on;
      askForAFrame(own);
    },

    canShowVolume: false,
    canShowVolumeBecause:
      "the pictures are one flat JPEG per field, already flattened over every " +
      "colour and depth, so there is no stack left to draw as a volume.",

    /* The colours were decided when the pictures were made, and a JPEG has no
       channels left to set. A page asking for one is told, rather than being
       silently ignored. */
    setChannel() {},

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
    position: "absolute",
    inset: "0",
    background: own.background,
    overflow: "hidden",
  });

  const make = () => {
    const canvas = document.createElement("canvas");
    Object.assign(canvas.style, {
      position: "absolute",
      inset: "0",
      width: "100%",
      height: "100%",
      display: "block",
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
 * Called again whenever the page thinks fields may have landed, so a scan
 * being watched grows. A note that cannot be read is skipped rather than
 * thrown: during a run the file is being written, and half a file read at the
 * wrong moment is an ordinary event, not a failure.
 */
async function readTheNotes(own) {
  const tiles = [];
  for (const source of own.sources) {
    const at = String(source).replace(/\/+$/, "");
    let note;
    try {
      const answer = await fetch(`${at}/tiles.json`, { cache: "no-store" });
      if (!answer.ok) continue;
      note = await answer.json();
    } catch {
      continue;
    }
    for (const tile of note?.tiles || []) {
      tiles.push({
        src: `${at}/${tile.src}`,
        x0: Number(tile.x0),
        y0: Number(tile.y0),
        w: Number(tile.w),
        h: Number(tile.h),
      });
    }
  }
  own.tiles = tiles;
}

/** The piece of sample every field together covers, in micrometres. */
function theWholeScan(own) {
  if (!own.tiles.length) return null;
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const tile of own.tiles) {
    left = Math.min(left, tile.x0);
    top = Math.min(top, tile.y0);
    right = Math.max(right, tile.x0 + tile.w);
    bottom = Math.max(bottom, tile.y0 + tile.h);
  }
  return { left, top, right, bottom };
}

function fitToWhatThereIs(own) {
  const scan = theWholeScan(own);
  if (!scan) return;
  fitTheSurfaces(own);
  const { width, height } = own.size;
  const across = Math.max(1e-9, scan.right - scan.left);
  const down = Math.max(1e-9, scan.bottom - scan.top);
  own.view = {
    centre: [(scan.left + scan.right) / 2, (scan.top + scan.bottom) / 2],
    zoom: Math.max(across / Math.max(1, width), down / Math.max(1, height)) * 1.05,
  };
}

/** Where a point on the sample lands in the box, and back again. */
function whereThingsAre(own) {
  const { width = 0, height = 0, density = 1 } = own.size || {};
  const { centre, zoom } = own.view;
  const project = (x, y) => [
    width / 2 + (x - centre[0]) / zoom,
    height / 2 + (y - centre[1]) / zoom,
  ];
  const unproject = (px, py) => [
    centre[0] + (px - width / 2) * zoom,
    centre[1] + (py - height / 2) * zoom,
  ];
  return { centre: [...centre], zoom, width, height, density, project, unproject };
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
 * Decode one picture, keeping only so many decoded at a time.
 *
 * A decoded picture is far larger than its JPEG, so keeping all of them would
 * hand back the very problem this engine exists to avoid. The least recently
 * wanted are let go once there are too many.
 */
function pictureFor(own, src) {
  const already = own.decoded.get(src);
  if (already) {
    const at = own.order.indexOf(src);
    if (at >= 0) own.order.splice(at, 1);
    own.order.push(src);
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
  own.order.push(src);
  while (own.order.length > HOW_MANY_TO_KEEP_DECODED) {
    const oldest = own.order.shift();
    const picture = own.decoded.get(oldest);
    if (picture && typeof picture.close === "function") picture.close();
    own.decoded.delete(oldest);
  }
  return coming;
}

/**
 * Draw the three surfaces.
 *
 * **Only the fields on screen are drawn, and only those are decoded.** That
 * one sentence is what makes ten thousand of them workable: the cost of a
 * frame follows what is visible, not what exists, so a scan of ten thousand
 * costs the same to look at as a scan of fifty once you are close enough to
 * see either.
 */
function drawEverything(own) {
  fitTheSurfaces(own);
  const where = whereThingsAre(own);
  const { density } = own.size;

  const clear = (canvas) => {
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.scale(density, density);
    return ctx;
  };

  const under = clear(own.surfaces.under);
  own.paintUnder?.(under, where);

  const picture = clear(own.surfaces.picture);
  if (own.showing) {
    const { width, height } = own.size;
    for (const tile of own.tiles) {
      const [left, top] = where.project(tile.x0, tile.y0);
      const across = tile.w / where.zoom;
      const down = tile.h / where.zoom;
      // Off screen: not drawn, and never decoded.
      if (left + across < 0 || top + down < 0 || left > width || top > height) continue;
      const ready = own.decoded.get(tile.src);
      const drawable = ready && typeof ready.width === "number" ? ready : pictureFor(own, tile.src);
      if (drawable && typeof drawable.width === "number") {
        picture.imageSmoothingEnabled = across > 2 * drawable.width;
        picture.drawImage(drawable, left, top, across, down);
      }
    }
  }

  const over = clear(own.surfaces.over);
  own.paintOver?.(over, where);
}
