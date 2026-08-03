/**
 * The overview as it is being acquired, drawn from the run's own images.
 *
 * The scan step used to report a count — "12 / 40 tiles" — and nothing else. A
 * count tells you the stage is moving; it does not tell you whether the sample
 * is where you thought it was, whether the focus held, or whether half the plate
 * is empty. This draws the picture instead, reading the same OME-Zarr images the
 * microscope is writing, so the operator can see the overview appear tile by
 * tile and stop a run that has gone wrong in the first minute rather than the
 * twentieth.
 *
 * How the picture is drawn
 * ------------------------
 *
 * By Viv, which is the library the project's viewer already uses to draw
 * OME-Zarr, and by deck.gl underneath it. Viv also ships ready-made viewers
 * written as React components, and those are deliberately not used here: they
 * take over the whole drawing surface and the whole of the page's layout, and
 * this page is plain JavaScript with a layout of its own. Viv's *layers* have no
 * such opinion — a layer is a description of something to draw — so a layer is
 * what this asks for, and it hands that to deck.gl directly.
 *
 * How the picture learns that a tile has landed
 * ---------------------------------------------
 *
 * This is the part worth reading, because it is where a live picture usually
 * goes wrong.
 *
 * Nothing on disk announces a new tile. The run declares its images at the very
 * start, at their full final size, and the tiles are written into room that was
 * already reserved for them — so the description of the images is exactly the
 * same before and after a tile arrives. That is a deliberate property of the
 * writer and a good one, because it is what lets a viewer open a run that is
 * still going. But it does mean that asking "has the image changed?" has no
 * useful answer: the image, as described, never changes. Only its contents do.
 *
 * So the picture has to go and look. It looks whenever the scan step says
 * another tile has been saved, which is the moment there is something new to
 * see, and that is all the coordination there is. For an overview of a few
 * dozen tiles this is cheap and completely reliable.
 *
 * Looking again is not as simple as redrawing, and this is the trap the project
 * has met more than once: a drawing engine remembers the pieces of image it has
 * already fetched, so a piece it read while it was still empty stays empty on
 * screen forever, however many times you redraw. What clears that memory is
 * handing deck.gl a *different* set of loaders than the one it was given last
 * time; it then treats every piece as unread and fetches them all again, while
 * keeping the old picture on screen until the new one has arrived, so nothing
 * flickers. That is what `lookAgain()` below does, and it is why it makes new
 * arrays rather than reusing the ones it has.
 */

import { COORDINATE_SYSTEM, Deck, LayerExtension, OrthographicView } from "@deck.gl/core";
import { SolidPolygonLayer } from "@deck.gl/layers";
import { ColorPaletteExtension } from "@vivjs/extensions";
import { loadOmeZarr } from "@vivjs/loaders";
import { ImageLayer, MultiscaleImageLayer } from "@vivjs/layers";
import { getDefaultInitialViewState } from "@vivjs/views";

/** The colour a channel is drawn in when the run did not record one. */
const WHITE = [255, 255, 255];

/**
 * Let the darkest parts of the image be see-through, so what is under it shows.
 *
 * Why this has to exist at all is worth spelling out, because it is a limitation
 * of the drawing library rather than a choice.
 *
 * Viv draws an image as a rectangle covering everything the run declared room
 * for, and it gives every one of those pixels an opacity of one — its shader
 * ends with `rgba = vec4(rgb, 1.)`. So a run that declared a canvas the size of
 * the whole carrier and imaged five places in it paints a solid black rectangle
 * over the entire carrier, and anything the page had drawn underneath — the
 * plate, the wells, the positions the operator laid out — disappears behind it.
 *
 * This is a small piece of shader code slipped into the last step of Viv's
 * drawing, where deck.gl leaves a hook open for exactly that purpose. It sets
 * how solid each pixel is from how bright it is, so black contributes nothing
 * and the picture appears to float over whatever is beneath it. It is the same
 * idea the project's other viewer uses in `viz_studio/frontend/src/scene.js`,
 * where brightness becomes colour and coverage becomes transparency.
 *
 * **What it cannot do**, and this matters: it makes a place that was imaged and
 * came back black just as see-through as a place nobody has visited, because by
 * the time the shader sees them they are both the same colour. Telling those two
 * apart would mean carrying "was anything written here" alongside the picture,
 * which neither Viv nor the format offers today. So this is offered rather than
 * assumed — a run being watched for what has been covered wants it off, and a
 * picture that has to sit over the operator's own drawing wants it on.
 */
class SeeThroughWhereDark extends LayerExtension {
  /* deck.gl wants a name it can use for this in its own bookkeeping, and it
     cannot take one from the class once the page has been built and shortened,
     so it is said here. Without it deck writes a warning to the console on every
     load, which is noise the browser tests then have to ignore. */
  static componentName = "SeeThroughWhereDark";

  getShaders() {
    return {
      // Named, because deck.gl says so in the console otherwise.
      name: "see-through-where-dark",
      inject: {
        "fs:DECKGL_FILTER_COLOR": `
          float brightest = max(max(color.r, color.g), color.b);
          color.a *= smoothstep(0.0, 0.02, brightest);
        `,
      },
    };
  }
}

/** Six hex digits, as OME-Zarr writes them, turned into the three numbers deck.gl wants. */
function channelColour(hex) {
  if (typeof hex !== "string" || !/^[0-9a-f]{6}$/i.test(hex)) return WHITE;
  return [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16));
}

/**
 * The brightness range a channel should first be shown with.
 *
 * A run records this in its `omero` block as `start` and `end`, and using it is
 * what makes the overview open looking like the sample rather than like a black
 * rectangle: an acquisition sits in the bottom few per cent of what the camera
 * can count, so showing the camera's whole range shows almost nothing. When the
 * run did not say, the camera's range is all there is to go on.
 */
function brightnessWindow(channel) {
  const window = channel?.window ?? {};
  const low = window.start ?? window.min ?? 0;
  const high = window.end ?? window.max ?? 65535;
  return [low, high];
}

/**
 * Draw a run's overview into a canvas, and keep drawing it as the run goes on.
 *
 * @param canvas the `<canvas>` element to draw into. It is drawn at whatever
 *   size the element currently has, and follows it if that changes.
 * @param store the address of the run's OME-Zarr image, as a URL. This is what
 *   the acquisition is writing into; it is read over HTTP, so whatever serves
 *   it has to answer range requests and allow the page to read it.
 * @param onStatus called with a short line about how the picture is getting on,
 *   which the page shows beside the canvas. Optional.
 * @param ground a colour to paint the declared canvas with, underneath the
 *   image, as `[red, green, blue]`. Left out, nothing is drawn underneath.
 *   Anything drawn here only shows through where the image lets it, which makes
 *   this both a way to see the shape of the room a run declared and the way the
 *   tests ask whether an unimaged part of that room is see-through at all.
 *
 * @returns a handle on the picture:
 *   `lookAgain()` reads the run again, which is how a tile written after the
 *   picture was first drawn appears; `fit()` frames the whole overview;
 *   `destroy()` releases the drawing surface. Every one of them is safe to call
 *   after the picture has been destroyed, so a page tearing itself down does not
 *   have to keep track of the order.
 *
 * @throws if the run cannot be read at all — a wrong address, a server that
 *   will not let the page read it, or a folder that is not an OME-Zarr image.
 *   Everything after that first read is reported through `onStatus` instead,
 *   because a scan in progress is not a reason to take the picture away.
 */
export async function showOverview(canvas, {
  store, stores, onStatus = () => {}, ground = null, seeThrough = false,
}) {
  const addresses = stores ?? [store];
  onStatus(addresses.length > 1 ? "opening the run…" : "opening the acquisition…");

  /** Everything one acquisition needs to be drawn: its images and its channels. */
  async function openOne(address, order) {
    const { data, metadata } = await loadOmeZarr(address, {
      type: "multiscales",
      // The whole point of this picture is that a file which was empty a moment
      // ago now has a tile in it, so the browser must never answer from what it
      // kept the first time.
      fetchOptions: { overrides: { cache: "no-store" } },
    });
    const base = data[0];
    const channelAxis = base.labels.indexOf("c");
    const count = channelAxis >= 0 ? base.shape[channelAxis] : 1;
    const described = metadata?.omero?.channels ?? [];
    const depthAxis = base.labels.indexOf("z");
    return {
      order,
      data,
      base,
      /* How deep it is. An acquisition taken one plane at a time has a depth of
         one and nothing to step through; one that takes a small stack at each
         position has more, and then which plane is on screen is a real choice. */
      depth: depthAxis >= 0 ? base.shape[depthAxis] : 1,
      // One entry per channel it recorded, in the order the image keeps them.
      channels: Array.from({ length: count }, (_, c) => ({
        index: c,
        label: described[c]?.label ?? `channel ${c + 1}`,
        colour: channelColour(described[c]?.color),
        window: brightnessWindow(described[c]),
      })),
    };
  }

  /* Several acquisitions can be drawn at once, and this is how a run is actually
     shaped: the writer keeps one image per acquisition type, so a low-power
     overview of the whole carrier is one image and the high-power scan of the
     targets picked out of it is another. They share a coordinate space, so they
     can simply be stacked — the overview underneath, the target scan over it —
     and the operator sees one picture of the run rather than two views to
     compare by eye. They are given in the order they should be drawn, from the
     bottom up. */
  const opened = await Promise.all(addresses.map(openOne));

  // The first one is what the view is framed on, being the wider of them.
  const base = opened[0].base;
  const data = opened[0].data;
  const channels = opened[0].channels;
  const depth = Math.max(...opened.map((one) => one.depth));

  const view = new OrthographicView({ id: "overview", controller: true });
  let generation = 0;
  let plane = 0;
  let destroyed = false;
  let deck = null;

  /* Whether a read of the run is still in flight, and whether something asked
     for another one while it was.

     This matters more than it sounds. Reading the run again throws away every
     piece of image the engine had fetched and asks for all of them afresh, and
     asking again before that has finished cancels what was in flight. Do that
     often enough and pieces of the picture never finish arriving at all: the
     screen ends up a patchwork of whatever each piece managed to fetch, which
     after a change of plane means parts of two different planes on screen at
     once. So one read runs at a time, and anything that arrives meanwhile is
     remembered and done when it finishes. */
  let reading = false;
  let asked = false;
  let settled = null;

  /* How long one read is given before the next may start. Long enough that a
     read of a small overview finishes in it, short enough that a tile which has
     just landed appears while the operator is still looking at the stage. */
  const SETTLE = 2500;

  /* The declared canvas, painted under the image. What a run declares is the
     room it might image, which is usually a great deal more than it does image;
     drawing that room says where the picture is going to appear, and it is the
     one honest way to see how much of it is still empty. */
  function groundLayer() {
    if (!ground) return null;
    const width = base.shape.at(-1);
    const height = base.shape.at(-2);
    /* Drawn a little larger than the canvas the run declared, so that a border
       of it stands outside the picture. That border is what makes the ground
       readable as ground: it shows where the declared room ends, and it says
       plainly that the ground is there at all even when the picture covers every
       part of it that matters. */
    const margin = 0.04;
    const squares = 8;
    const across = (width * (1 + 2 * margin)) / squares;
    const down = (height * (1 + 2 * margin)) / squares;
    const data = [];
    for (let row = 0; row < squares; row++) {
      for (let col = 0; col < squares; col++) {
        const x = col * across - width * margin;
        const y = row * down - height * margin;
        data.push({
          polygon: [[x, y], [x + across, y], [x + across, y + down], [x, y + down]],
          // A chequer rather than a flat wash, so that what is underneath can be
          // recognised as itself wherever a gap in the image lets it through.
          colour: (row + col) % 2 ? ground : ground.map((c) => Math.round(c * 0.55)),
        });
      }
    }
    return new SolidPolygonLayer({
      id: "declared-canvas",
      data,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => d.colour,
    });
  }

  /** One acquisition, as something deck.gl can draw. */
  function imageLayer(one) {
    /* Fresh arrays every time, and that is the whole mechanism: deck.gl decides
       whether it can reuse the pieces of image it already fetched by asking
       whether it was handed the same loaders and the same choice of channels as
       last time. Different arrays mean "read the run again", which is exactly
       what is wanted once another tile has been written into it. */
    const loader = one.data.slice();
    /* Which plane of which moment to draw. Each plane is stored separately, so
       asking for one reads only that plane rather than the whole stack. An
       acquisition shallower than the deepest one shows its last plane rather
       than nothing at all. */
    const which = Math.min(plane, one.depth - 1);
    const selections = one.channels.map((channel) => ({ t: 0, c: channel.index, z: which }));
    const shared = {
      id: `live-overview-${one.order}`,
      loader: loader.length > 1 ? loader : loader[0],
      selections,
      contrastLimits: one.channels.map((c) => c.window),
      colors: one.channels.map((c) => c.colour),
      channelsVisible: one.channels.map(() => true),
      /* Viv's own extension is what turns the numbers in the image into colours,
         so it has to stay; naming any extension at all replaces the list Viv
         would otherwise use. Ours is added after it, because it works on the
         colour that one produced.

         Every acquisition gets it or none does. It is what stops the one on top
         from hiding the ones below wherever it has imaged nothing — which, for a
         scan of a few scattered targets, is almost everywhere. */
      extensions: seeThrough
        ? [new ColorPaletteExtension(), new SeeThroughWhereDark()]
        : [new ColorPaletteExtension()],
    };
    // An acquisition with several progressively smaller copies is drawn piece by
    // piece, which is what keeps a large one light. One with a single copy has no
    // pieces to choose between, so the whole of it is drawn at once.
    return loader.length > 1 ? new MultiscaleImageLayer(shared) : new ImageLayer(shared);
  }

  function layers() {
    /* In the order they are drawn, which is the order they were given: the
       ground first because it is underneath everything, then each acquisition
       over the one before it. */
    return [groundLayer(), ...opened.map(imageLayer)].filter(Boolean);
  }

  function finishedReading() {
    clearTimeout(settled);
    reading = false;
    if (!asked || destroyed) return;
    asked = false;
    handle.lookAgain();
  }

  function size() {
    const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 800;
    const height = canvas.clientHeight || canvas.parentElement?.clientHeight || 600;
    return { width, height };
  }

  /* Where the camera has to stand for the whole overview to be on screen. The
     small step back — the third argument — leaves a margin around it, so the
     edge of the declared canvas reads as an edge rather than running off the
     side of the panel. */
  const framed = () => ({ ...getDefaultInitialViewState(data, size(), 0.15), id: "overview" });

  /* The view is held here rather than inside deck.gl, which is what makes "fit"
     possible: the operator's panning and zooming comes back through
     `onViewStateChange`, so this always knows where the camera is and can put it
     back where it started. */
  let viewState = framed();

  deck = new Deck({
    canvas,
    views: [view],
    viewState,
    onViewStateChange: ({ viewState: moved }) => {
      viewState = moved;
      if (!destroyed) deck.setProps({ viewState });
    },
    controller: true,
    ...size(),
    /* Headless browsers draw WebGL in software, and the test that photographs
       this canvas needs what was drawn to still be there when the photograph is
       taken rather than having been thrown away after the frame. It costs
       nothing worth measuring on a real machine. */
    glOptions: { preserveDrawingBuffer: true },
    layers: layers(),
    onError: (error) => onStatus(`the picture could not be drawn: ${error.message}`),
  });

  /* What is on screen, said once it is: how many acquisitions are being drawn
     and which colours of light they recorded. */
  onStatus(
    `overview open · ${opened.map((one) => one.channels.map((c) => c.label).join(", ")).join(" + ")}`,
  );

  /* The canvas shares its space with the rest of the panel, so it changes size
     when the window does. deck.gl is told rather than left to guess, because a
     drawing surface whose size disagrees with the element it lives in draws the
     picture at the wrong scale — which is the failure that once opened this
     project's viewer on a specimen a ten-thousandth of a pixel wide. */
  const watchSize = new ResizeObserver(() => {
    if (destroyed) return;
    const now = size();
    // A panel that is not on show measures zero, and telling deck.gl to draw
    // into nothing leaves it with a camera it cannot recover from.
    if (now.width > 0 && now.height > 0) deck.setProps(now);
  });
  watchSize.observe(canvas.parentElement ?? canvas);

  /* How often the run is worth reading.
   *
   * Reading it means fetching every piece of image the view covers, so doing it
   * on every progress report from a scan — which can arrive sixty times a second
   * — would spend the whole browser on requests. Worse, starting another read
   * before the last one has finished leaves the picture showing a patchwork of
   * the two for longer, so being eager makes it look *less* finished, not more.
   * Once a second is quicker than anybody can watch a tile appear. */
  const CALM = 1000;
  let lookedAt = 0;
  let due = null;

  const handle = {
    /** Read the run again, so tiles written since the last look appear. */
    lookAgain() {
      if (destroyed) return;
      lookedAt = performance.now();
      generation += 1;
      reading = true;
      /* A read counts as finished once it has had a fair while to arrive, and
         the clock is used rather than an announcement from the drawing engine on
         purpose. deck.gl can say when everything in view has loaded, but
         measured here it says so after the first read of a run and then stays
         quiet however many more are done — and a picture waiting for an
         announcement that never comes simply stops refreshing, which is the very
         failure this whole thing exists to avoid. */
      clearTimeout(settled);
      settled = setTimeout(finishedReading, SETTLE);
      deck.setProps({ layers: layers() });
    },

    /**
     * Say that a tile may have been saved, and let the picture decide when to look.
     *
     * This is what a running scan calls. It looks straight away if it has not
     * looked recently and is not already in the middle of a read; otherwise it
     * arranges one for as soon as it can. Either way a scan reporting every
     * position, however fast they arrive, ends with the picture having read what
     * was written last.
     */
    tileMayHaveLanded() {
      if (destroyed || due) return;
      if (reading) { asked = true; return; }
      const since = performance.now() - lookedAt;
      if (since >= CALM) { handle.lookAgain(); return; }
      due = setTimeout(() => { due = null; handle.tileMayHaveLanded(); }, CALM - since);
    },

    /** How many planes deep the run is, and which one is on screen. */
    get depth() { return depth; },
    get plane() { return plane; },

    /**
     * Show a different plane of the stack.
     *
     * Only that plane is read: a piece of stored image holds one plane, so
     * stepping through depth costs the same as looking at the first one rather
     * than fetching the whole stack. Out-of-range numbers are pulled back to the
     * ends, so a control that runs off the end does no harm.
     */
    showPlane(which) {
      if (destroyed) return;
      const wanted = Math.max(0, Math.min(depth - 1, Math.round(which)));
      if (wanted === plane) return;
      plane = wanted;
      handle.lookAgain();
    },

    /** Frame the whole overview, however the operator has panned and zoomed. */
    fit() {
      if (destroyed) return;
      viewState = framed();
      deck.setProps({ viewState, ...size() });
    },

    /** How many times the run has been read, which the test and the readout use. */
    get generation() { return generation; },

    /** The channels the run recorded, for anything that wants to name them. */
    channels,

    destroy() {
      if (destroyed) return;
      destroyed = true;
      if (due) clearTimeout(due);
      clearTimeout(settled);
      watchSize.disconnect();
      deck.finalize();
    },
  };

  return handle;
}
