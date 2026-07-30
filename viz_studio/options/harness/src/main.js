/**
 * The page that drives any of the three options, chosen by a word in its address.
 *
 * Its whole job is to be *the same page* whichever option is underneath it. It
 * owns the two gestures, it owns the operator's drawing, it owns where the view
 * is, and it reaches the option through the small interface in
 * `viz_studio/options/contract.md` and through nothing else. It never asks which
 * option it got. That is what makes the comparison about the engines rather than
 * about how somebody happened to wire each one up.
 *
 * The address says what to open:
 *
 *   `?option=neuroglancer-under`  which of the three draws the picture
 *   `&store=square`               which acquisition to read
 *   `&draw=carrier`               the operator's real drawing: a carrier
 *                                 outline and tile rectangles
 *   `&draw=margin`                the measuring instrument: a sheet with a hole
 *                                 cut a little larger than the imaged square
 *   `&data=http://host:port/data` where the acquisitions are served from
 *
 * Everything a measurement needs to take hold of is hung on `window.harness`.
 * None of it is the page reporting on its own correctness: every number in the
 * results comes from a photograph of the screen. What is here is only the means
 * to move the view, to ask what the page believes, and to make something happen
 * at a chosen moment.
 */

import { openerFor, optionsBuiltIn } from "./options.js";
import { onlyPanAndZoom } from "./gestures.js";
import {
  MARGIN_CSS_PX,
  drawTheCarrier,
  drawTheMarginProbe,
  imagedRegions,
} from "./drawings.js";

const asked = new URLSearchParams(window.location.search);
const optionName = asked.get("option") || "neuroglancer-under";
const storeName = asked.get("store") || "square";
const whatToDraw = asked.get("draw") || "margin";
// Where the acquisitions are served from. Passed in rather than worked out from
// the page's own address, because the option is forbidden to work it out and the
// page should not quietly do it on the option's behalf. The default is the
// server that handed over this page, which is the ordinary case and is stated
// here, in the open, rather than buried in the adapter.
const dataBase = asked.get("data") || `${window.location.origin}/data`;
// The page's own colour. The option is told it, so that the seam between two
// drawing surfaces cannot be seen. During the margin measurement it must differ
// from the sheet on top or there would be no band to measure; see `drawings.js`.
const background = asked.get("background") || (whatToDraw === "margin" ? "#0000ff" : "#101014");
// A colour painted on the box *behind* whatever surfaces the option puts in it.
// Used by one measurement only, and it is worth saying which: the whole
// arrangement assumes that a drawing surface with nothing on it lets what is
// behind it show through, and that assumption had never been tested. Give the
// box one colour, give the engine's own background another, and a photograph
// says plainly which one an operator would see over ground nobody imaged.
const under = asked.get("under") || null;

const box = document.getElementById("viewer");
const note = document.getElementById("note");

/** What the page believes, kept where a measurement can read it. */
const harness = {
  ready: false,
  failed: null,
  option: optionName,
  built: optionsBuiltIn(),
  draw: whatToDraw,
  store: storeName,
  margin: MARGIN_CSS_PX,
  // How far the hole is deliberately put in the wrong place, in browser pixels.
  // Nought in every real measurement, and set only to show the check can fail.
  nudge: 0,
  scene: null,
  coverage: null,
  viewer: null,
  gestures: null,
};
window.harness = harness;

function sizeOfBox() {
  return { width: box.clientWidth, height: box.clientHeight };
}

/**
 * A carrier and a plausible set of tiles laid over whatever the run imaged.
 *
 * Built from the coverage record so that the operator's plan lines up with the
 * picture, which is the property the whole front end rests on: the application's
 * coordinate system and the store's are the same one, with no conversion at
 * drawing time.
 *
 * The tiles are given three different states because that is what a run in
 * progress looks like, and because a tile changing from planned to acquiring to
 * done every few seconds is the thing that must never touch the disk.
 */
function sceneFor(coverage) {
  const regions = imagedRegions(coverage);
  if (!regions.length) {
    return { background, carrier: null, wells: [], tiles: [], selected: null };
  }
  const x0 = Math.min(...regions.map((r) => r.x0));
  const x1 = Math.max(...regions.map((r) => r.x1));
  const y0 = Math.min(...regions.map((r) => r.y0));
  const y1 = Math.max(...regions.map((r) => r.y1));
  const wide = x1 - x0;
  const tall = y1 - y0;
  // A carrier comfortably larger than the imaged ground, because that is the
  // shape of a real run: the room is declared to the reach of the stage and the
  // specimen occupies a small part of it.
  const carrier = {
    x0: x0 - wide * 0.6,
    y0: y0 - tall * 0.6,
    x1: x1 + wide * 0.6,
    y1: y1 + tall * 0.6,
  };
  const wells = [];
  for (let row = 0; row < 2; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      wells.push({
        x: carrier.x0 + ((column + 0.5) / 3) * (carrier.x1 - carrier.x0),
        y: carrier.y0 + ((row + 0.5) / 2) * (carrier.y1 - carrier.y0),
        r: Math.min(wide, tall) * 0.28,
      });
    }
  }
  const tiles = [];
  // How many tile rectangles the operator laid out. The measurement of drawing
  // rate runs the same page at twenty and at two hundred, because the fault
  // being looked for is a cost that grows with the number of positions.
  const wanted = Number(asked.get("positions") || 36);
  const across = Math.max(1, Math.round(Math.sqrt(wanted)));
  const downCount = Math.max(1, Math.ceil(wanted / across));
  for (let row = 0; row < downCount; row += 1) {
    for (let column = 0; column < across; column += 1) {
      if (tiles.length >= wanted) break;
      const left = carrier.x0 + (column / across) * (carrier.x1 - carrier.x0);
      const top = carrier.y0 + (row / downCount) * (carrier.y1 - carrier.y0);
      // A third done, one being acquired, the rest still planned — which is what
      // a run in progress looks like, and the state of a tile is the thing that
      // changes every few seconds and must never touch the disk.
      const at = tiles.length;
      tiles.push({
        x0: left,
        y0: top,
        x1: left + (carrier.x1 - carrier.x0) / across,
        y1: top + (carrier.y1 - carrier.y0) / downCount,
        state: at < wanted / 3 ? "done"
          : at === Math.floor(wanted / 3) ? "acquiring" : "planned",
      });
    }
  }
  return {
    background, carrier, wells, tiles,
    selected: Math.min(tiles.length - 1, Math.floor(wanted / 3) + 2),
  };
}

/**
 * The drawing the page hands over. The same function for every option, and it is
 * never told which one it is drawing for.
 */
function paint(frame) {
  if (whatToDraw === "none") {
    // Nothing at all. The option has already cleared the operator's surface
    // before calling this, so what a photograph then shows is purely whatever
    // the option drew and whatever is behind it — which is exactly what the
    // measurement of showing-through needs to see.
    harness.painted = (harness.painted || 0) + 1;
    return;
  }
  if (whatToDraw === "margin") {
    harness.lastHole = drawTheMarginProbe(frame, {
      square: harness.square,
      nudge: harness.nudge,
      alsoDrawTheTileEdge: asked.get("tileEdge") === "1",
    });
  } else {
    drawTheCarrier(frame, harness.scene);
  }
  harness.lastView = { centre: frame.centre, zoom: frame.zoom };
  harness.painted = (harness.painted || 0) + 1;
}

/**
 * Put the imaged ground in the middle of the window at a magnification that
 * leaves room all round it.
 *
 * A third of the window rather than most of it, for a reason that is easy to
 * miss: the margin measurement has to see the band of background and the sheet
 * framing it all the way round the square *while the view is being moved about*.
 * Filling the window would mean the very frames the measurement most wants to
 * look at are the ones where an edge has left the picture.
 */
function fitTheImagedGround() {
  const size = sizeOfBox();
  const square = harness.square;
  const across = Math.min(size.width, size.height) * 0.35;
  return {
    centre: { x: (square.x0 + square.x1) / 2, y: (square.y0 + square.y1) / 2 },
    zoom: Math.max(square.x1 - square.x0, square.y1 - square.y0) / across,
  };
}

async function boot() {
  const coverage = await fetch(
    `/api/coverage?image=${encodeURIComponent(storeName)}`,
  ).then((answer) => answer.json());
  harness.coverage = coverage;
  const regions = imagedRegions(coverage);
  if (!regions.length) {
    throw new Error(
      `the run "${storeName}" has no coverage record, so there is nowhere the ` +
        "picture is allowed to show through and the page would draw an opaque " +
        "sheet over everything. Write one, or point at a run that kept one.",
    );
  }
  // The rectangle the hole is cut around: the ground that holds picture.
  harness.square = {
    x0: Math.min(...regions.map((r) => r.x0)),
    y0: Math.min(...regions.map((r) => r.y0)),
    x1: Math.max(...regions.map((r) => r.x1)),
    y1: Math.max(...regions.map((r) => r.y1)),
  };
  harness.scene = sceneFor(coverage);

  const openViewer = await openerFor(optionName);
  // Kept where a test can reach them, so that a second viewer can be opened on
  // exactly the same acquisitions as the first. That is the check that catches
  // an option keeping its state in a variable belonging to its file rather than
  // to the viewer — which is what stops a page holding two.
  harness.acquisitionsAsked = [
    {
      url: `${dataBase}/${storeName}.ome.zarr/|zarr2:`,
      name: storeName,
      channels: [
        { name: "probe", colour: [1, 1, 1], window: { low: 0, high: 4095 } },
      ],
    },
  ];
  harness.loadTheOption = async () => ({ openViewer: await openerFor(optionName) });
  const viewer = await openViewer(box, {
    acquisitions: harness.acquisitionsAsked,
    coverage,
    background,
    // Bounding what the engine draws to the ground the run imaged is on by
    // default, because it is the arrangement that would ship. One measurement
    // turns it off, so that the saving can be shown rather than asserted.
    boundToCoverage: asked.get("bounded") !== "0",
    onViewChanged: (view) => {
      harness.viewNow = view;
    },
  });
  harness.viewer = viewer;
  // Painted after the option has laid its surfaces down, so it really is behind
  // them rather than merely declared first.
  if (under) box.style.background = under;
  viewer.drawOver(paint);
  viewer.setView(fitTheImagedGround());

  harness.gestures = onlyPanAndZoom(box, {
    getView: () => viewer.getView(),
    setView: (view) => viewer.setView(view),
    sizeOf: sizeOfBox,
  });

  // -- the handles a measurement takes hold of ---------------------------
  harness.view = () => viewer.getView();
  harness.setView = (view) => viewer.setView(view);
  harness.size = sizeOfBox;
  harness.density = () => window.devicePixelRatio || 1;
  // Put the imaged ground back in the middle at the magnification the page
  // opened with. Every measurement starts from here, so that the numbers from
  // one are comparable with the numbers from another.
  harness.reset = () => viewer.setView(fitTheImagedGround());
  // "Go and look, a tile may have arrived." The coverage record is fetched again
  // first, because a run that has acquired new ground has changed where the
  // picture is allowed to show — and a viewer told to look again while still
  // holding last hour's idea of where the run had been would go and look in the
  // wrong place.
  harness.tilesMayHaveLanded = async () => {
    const coverage = await fetch(
      `/api/coverage?image=${encodeURIComponent(storeName)}`,
    ).then((answer) => answer.json());
    harness.coverage = coverage;
    harness.scene = sceneFor(coverage);
    return viewer.tilesMayHaveLanded({ coverage });
  };
  harness.counts = () => viewer.countsForMeasurement?.() ?? null;
  harness.gesturesSoFar = () => ({
    refused: { ...harness.gestures.refused },
    accepted: { ...harness.gestures.accepted },
  });
  // Move the hole a few pixels away from where it belongs. Nothing else changes,
  // so whatever the margin check then reports is the check noticing a
  // disagreement that really is there — which is the only way to know it would
  // notice a real one.
  harness.nudgeTheHole = (pixels) => {
    harness.nudge = pixels;
    viewer.drawOver(paint);
  };
  // What size the surfaces really are, in real pixels. Two canvases have to
  // agree about how large a screen pixel is, and this is where a disagreement
  // would show.
  harness.canvasSizes = () =>
    Array.from(box.querySelectorAll("canvas")).map((canvas) => ({
      className: canvas.className,
      width: canvas.width,
      height: canvas.height,
      css: canvas.clientWidth,
    }));

  window.addEventListener("resize", () => viewer.setView(viewer.getView()));
  harness.ready = true;
  note.textContent = "";
}

note.textContent = `opening "${optionName}"…`;
boot().catch((why) => {
  harness.failed = String(why && why.stack ? why.stack : why);
  // Said on the page as well as recorded, because a blank page that is broken
  // and a blank page that is still loading look exactly alike, and this project
  // has lost days to the difference.
  note.textContent = harness.failed;
});
