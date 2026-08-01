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
 *   `&alsoStore=detail`           a second acquisition to open beside the first,
 *                                 drawn over it. This is the ordinary
 *                                 arrangement of a run — a wide survey with a
 *                                 detailed scan over part of it — and the two
 *                                 can only land in the same place by the
 *                                 position each states in micrometres. Left out,
 *                                 one acquisition is opened and everything
 *                                 behaves exactly as it did before there was a
 *                                 second.
 *   `&draw=carrier`               the operator's real drawing, all on one sheet
 *                                 above the picture with holes cut in it
 *   `&draw=threeLayers`           the same scene taken apart into the three
 *                                 layers of `THE_CANVAS.md`: the carrier beneath
 *                                 the picture, the tiles above it
 *   `&draw=margin`                the measuring instrument: a sheet with a hole
 *                                 cut a little larger than the imaged square
 *   `&data=http://host:port/data` where the acquisitions are served from
 *   `&channels=fromTheStore`      say nothing to the option about the run's
 *                                 colours, so that it reads the run's own
 *                                 description instead. The default,
 *                                 `fromThePage`, states one white channel, which
 *                                 is what every measurement taken before there
 *                                 was a choice was taken with.
 *
 * Press **o** to change engine without losing the view. The centre, the
 * magnification, the plane, the moment and the channel settings are all carried
 * over, so the same view can be looked at through two engines one after the
 * other — which is the only way to see a difference that is small.
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
  drawTheGroundBeneath,
  drawTheMarginProbe,
  drawTheMarginRingBeneath,
  drawTheTilesOnTop,
  fillTheSlot,
  imagedRegions,
} from "./drawings.js";

const asked = new URLSearchParams(window.location.search);
let optionName = asked.get("option") || "neuroglancer-under";
const storeName = asked.get("store") || "square";
// A second acquisition, opened beside the first and drawn over it. Nothing at
// all unless the address asks for one.
const alsoStoreName = asked.get("alsoStore") || null;
const storeNames = alsoStoreName ? [storeName, alsoStoreName] : [storeName];
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
// Whether the page describes the run's channels to the option, or says nothing
// and leaves the option to read the run's own description of them.
//
// The interface allows both, and the difference is worth being able to try. A
// page that already knows what it wants on screen — an operator who has turned a
// channel off, or chosen a colour — says so, and what it says is used. A page
// that has only been handed the address of a run knows nothing about its
// colours, and asking it to find out would mean opening the run twice: once to
// learn what to say and once to draw it. The default here is the page saying its
// piece, because that is what every measurement in `RESULTS.md` was taken with.
const channelsAreSaidBy = asked.get("channels") || "fromThePage";

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
  stores: storeNames,
  margin: MARGIN_CSS_PX,
  // How far the hole is deliberately put in the wrong place, in browser pixels.
  // Nought in every real measurement, and set only to show the check can fail.
  nudge: 0,
  // How much larger than the truth the operator's own drawing is drawn, as a
  // multiple. One in every real measurement. Set to something else only to show
  // that the reading of a disagreement about *size* can go the other way — see
  // `drawTheOperatorsLayerAtTheWrongScale` further down, which explains what
  // this breaks and why the ordinary registration reading cannot see it.
  operatorsLayerScale: 1,
  scene: null,
  coverage: null,
  // One coverage record per acquisition the page opened, kept by name. The
  // single `coverage` above is the first one, which is what the interface takes.
  coverages: null,
  viewer: null,
  gestures: null,
  // What the page is drawing in each of the two slots it is given. The words are
  // the page's own and mean nothing to any option: an option is handed one
  // drawing function per slot and never learns what it will draw.
  //
  //   "nothing"          leave the slot empty. The option is handed no drawing
  //                      function at all for it, so nothing is set up and
  //                      nothing costs anything.
  //   "the scene"        whatever the chosen `draw=` mode puts there
  //   "a colour"         one flat colour over the whole window, for the
  //                      measurement of whether the bottom layer can be seen
  //   "the margin ring"  a rectangle of colour framing the imaged square a
  //                      little way outside it, for the measurement of whether
  //                      the bottom layer stays lined up with the picture
  //
  // The bottom slot is empty unless the three-layer view was asked for, so every
  // measurement that was taken before there was a bottom slot is taken on a page
  // where the bottom slot is doing nothing whatever.
  slots: {
    under: whatToDraw === "threeLayers" ? "the scene" : "nothing",
    over: "the scene",
  },
  // The colour the flat fill uses, when a slot is asked for one.
  slotColour: "#00ff00",
  // How far the ring beneath the picture is deliberately put in the wrong place,
  // in browser pixels. Nought in every real measurement, and set only to show
  // that the reading of the bottom layer's registration can go the other way.
  nudgeBeneath: 0,
  // Whether the option now underneath really draws the bottom slot beneath the
  // picture, and the sentence it gives as the reason. Filled in when a viewer is
  // opened, and read straight off the handle rather than guessed at from the
  // option's name — the page must be able to find this out without knowing which
  // engine it is talking to.
  drawsUnder: null,
  drawsUnderBecause: null,
  // Options that were tried in this page and would not open. See `switchTo`:
  // the one case there is refuses to be reached once a sister option has been
  // loaded, and remembering it here keeps the key that changes engine from
  // offering the same dead end over and over.
  cannotChangeTo: [],
  switchWouldNotWork: null,
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
 * The drawing the page hands over for the **top** slot: everything that belongs
 * over the picture.
 *
 * The same function for every option, and it is never told which one it is
 * drawing for.
 */
/**
 * The same frame, with the operator's drawing deliberately drawn at the wrong
 * magnification.
 *
 * This exists to break one thing on purpose, and it is worth saying exactly
 * which. The usual registration reading is the *unevenness* of the band around
 * the picture — how much wider one side is than the side opposite — and that
 * catches the two layers sitting in different places. It cannot catch them
 * agreeing about where the middle is and disagreeing about how big things are,
 * because then all four sides of the band grow or shrink together and the
 * unevenness stays at nought while the operator's outline is visibly the wrong
 * size around its tile.
 *
 * So this scales everything the page draws about the middle of the window, by a
 * small factor, leaving the picture exactly where it is. It is a real shape of
 * fault: an option whose conversion from micrometres to screen pixels was
 * slightly wrong would look precisely like this. `harness.operatorsLayerScale`
 * is one for every measurement that is not showing the check can fail.
 */
function asTheOperatorsLayerIsScaled(frame) {
  const wrong = harness.operatorsLayerScale;
  if (!(wrong > 0) || wrong === 1) return frame;
  const middleX = frame.width / 2;
  const middleY = frame.height / 2;
  return {
    ...frame,
    project: (x, y) => {
      const at = frame.project(x, y);
      return {
        x: middleX + (at.x - middleX) * wrong,
        y: middleY + (at.y - middleY) * wrong,
      };
    },
  };
}

function paint(given) {
  const frame = asTheOperatorsLayerIsScaled(given);
  harness.painted = (harness.painted || 0) + 1;
  harness.lastView = { centre: frame.centre, zoom: frame.zoom };
  if (harness.slots.over === "nothing") {
    // Nothing at all. The option has already cleared the slot before calling
    // this, so what a photograph then shows is purely whatever the option drew
    // and whatever is behind it — which is exactly what the measurements of
    // showing-through and of the bottom layer need to see.
    return;
  }
  if (harness.slots.over === "a colour") {
    fillTheSlot(frame, harness.slotColour);
    return;
  }
  if (whatToDraw === "none") return;
  if (whatToDraw === "margin") {
    harness.lastHole = drawTheMarginProbe(frame, {
      square: harness.square,
      nudge: harness.nudge,
      alsoDrawTheTileEdge: asked.get("tileEdge") === "1",
    });
  } else if (whatToDraw === "threeLayers") {
    drawTheTilesOnTop(frame, harness.scene);
  } else {
    drawTheCarrier(frame, harness.scene);
  }
}

/**
 * The drawing the page hands over for the **bottom** slot: everything that
 * belongs beneath the picture.
 *
 * This is the same shape of function as `paint` above, receives the same frame,
 * and is written in exactly the same way — which is the point of having a bottom
 * slot at all. An application should be able to put its carrier under the picture
 * without learning anything about the engine drawing the picture.
 *
 * Whether it can actually be *seen* is a different question, and the page asks
 * the viewer rather than assuming: `viewer.drawsUnder`. An engine that cannot
 * honour the bottom slot says so, and the page then shows nothing there rather
 * than quietly drawing the same thing on top with holes cut in it. Faking it
 * would make two options look alike while doing entirely different things
 * underneath, which is the kind of silent difference this whole comparison
 * exists to avoid.
 */
function paintBeneath(frame) {
  harness.paintedBeneath = (harness.paintedBeneath || 0) + 1;
  if (harness.slots.under === "nothing") return;
  if (harness.slots.under === "a colour") {
    fillTheSlot(frame, harness.slotColour);
    return;
  }
  if (harness.slots.under === "the margin ring") {
    drawTheMarginRingBeneath(frame, {
      square: harness.square,
      nudge: harness.nudgeBeneath,
    });
    return;
  }
  if (whatToDraw === "threeLayers") drawTheGroundBeneath(frame, harness.scene);
}

/**
 * Hand both drawings over to whichever viewer is in the box.
 *
 * A slot the page has nothing for is handed `null` rather than a function that
 * paints nothing. The difference is not tidiness: told there is nothing beneath,
 * an option need not lay down a surface for it, clear it every frame or carry it
 * to the graphics card, so a page that never uses the bottom layer costs exactly
 * what it did before there was one.
 */
function handOverTheDrawings(viewer) {
  viewer.drawUnder(harness.slots.under === "nothing" ? null : paintBeneath);
  viewer.drawOver(paint);
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

/** The coverage record of every acquisition the page opened, kept by name. */
async function readTheCoverageRecords() {
  const found = {};
  for (const name of storeNames) {
    found[name] = await fetch(
      `/api/coverage?image=${encodeURIComponent(name)}`,
    ).then((answer) => answer.json());
  }
  return found;
}

/**
 * Every imaged rectangle of every acquisition on the page, in micrometres.
 *
 * Micrometres, because that is the only thing two runs written at different
 * voxel sizes have in common — and it is what makes a survey and a detail scan
 * over part of it a single scene rather than two.
 */
function everythingImaged(coverages) {
  return storeNames.flatMap((name) => imagedRegions(coverages[name]));
}

async function boot() {
  const coverages = await readTheCoverageRecords();
  const coverage = coverages[storeName];
  harness.coverages = coverages;
  harness.coverage = coverage;
  const regions = everythingImaged(coverages);
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

  // Kept where a test can reach them, so that a second viewer can be opened on
  // exactly the same acquisitions as the first. That is the check that catches
  // an option keeping its state in a variable belonging to its file rather than
  // to the viewer — which is what stops a page holding two.
  //
  // One entry per acquisition the address asked for, in the order they should be
  // drawn: the survey first and the detail scan over it, which is the order the
  // interface takes them in.
  harness.acquisitionsAsked = storeNames.map((name) => ({
    url: `${dataBase}/${name}.ome.zarr/|zarr2:`,
    name,
    // Left out altogether when the page has been asked to say nothing about
    // the colours. Left out means left out: the option is handed an
    // acquisition with no `channels` at all, exactly as a page that has only
    // been given the address of a run would hand it over.
    ...(channelsAreSaidBy === "fromTheStore"
      ? {}
      : {
          channels: [
            { name: "probe", colour: [1, 1, 1], window: { low: 0, high: 4095 } },
          ],
        }),
  }));
  harness.loadTheOption = async () => ({ openViewer: await openerFor(optionName) });

  await putAViewerInTheBox(fitTheImagedGround());

  harness.gestures = onlyPanAndZoom(box, {
    // Read through `harness.viewer` rather than through a viewer captured here,
    // because the engine underneath can be changed while the page is open and
    // the gestures must go on reaching whichever one is there now.
    getView: () => harness.viewer.getView(),
    setView: (view) => harness.viewer.setView(view),
    sizeOf: sizeOfBox,
  });

  // -- the handles a measurement takes hold of ---------------------------
  harness.view = () => harness.viewer.getView();
  harness.setView = (view) => harness.viewer.setView(view);
  harness.size = sizeOfBox;
  harness.density = () => window.devicePixelRatio || 1;
  // Put the imaged ground back in the middle at the magnification the page
  // opened with. Every measurement starts from here, so that the numbers from
  // one are comparable with the numbers from another.
  harness.reset = () => harness.viewer.setView(fitTheImagedGround());
  // "Go and look, a tile may have arrived." The coverage record is fetched again
  // first, because a run that has acquired new ground has changed where the
  // picture is allowed to show — and a viewer told to look again while still
  // holding last hour's idea of where the run had been would go and look in the
  // wrong place.
  harness.tilesMayHaveLanded = async () => {
    const records = await readTheCoverageRecords();
    harness.coverages = records;
    harness.coverage = records[storeName];
    harness.scene = sceneFor(harness.coverage);
    return harness.viewer.tilesMayHaveLanded({ coverage: harness.coverage });
  };
  harness.counts = () => harness.viewer.countsForMeasurement?.() ?? null;
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
    harness.viewer.drawOver(paint);
  };
  // Draw everything the operator's layer holds at the wrong magnification, and
  // leave the picture exactly where it is. One puts it back.
  //
  // This is a different fault from moving the hole, and the difference is the
  // whole reason it is here. Moving the hole makes one side of the band thicker
  // and the side opposite thinner, which the usual reading — the unevenness —
  // sees at once. Drawing the operator's layer a little too large grows all four
  // sides of the band together, so the unevenness stays at nought and only a
  // reading that compares the band with the width it was *cut* at can notice.
  harness.drawTheOperatorsLayerAtTheWrongScale = (factor) => {
    harness.operatorsLayerScale = factor;
    harness.viewer.drawOver(paint);
  };
  // The same deliberate breakage for the bottom layer: move the ring drawn
  // beneath the picture away from where it belongs, and watch the reading of the
  // bottom layer's registration go uneven by twice as much.
  harness.nudgeTheGroundBeneath = (pixels) => {
    harness.nudgeBeneath = pixels;
    handOverTheDrawings(harness.viewer);
  };
  // Which plane, which moment and which channel settings the page has asked for.
  // They are remembered as well as passed on, so that changing engine can put
  // the new one into the same state as the old — see `switchTo`.
  harness.setPlane = (z) => {
    harness.plane = z;
    harness.viewer.setPlane(z);
  };
  harness.setMoment = (t) => {
    harness.moment = t;
    harness.viewer.setMoment(t);
  };
  harness.setChannel = (index, settings) => {
    harness.channels = harness.channels || {};
    harness.channels[index] = { ...(harness.channels[index] || {}), ...settings };
    harness.viewer.setChannel(index, settings);
  };
  // What the page draws in each slot. The words are explained beside
  // `harness.slots` at the top of this file; the measurement of the bottom layer
  // uses them to put the same flat colour first in one slot and then in the
  // other, which is what makes its reading mean "which slot" rather than "which
  // colour".
  harness.drawInTheSlots = ({ under: below, over: above, colour }) => {
    if (colour) harness.slotColour = colour;
    if (below) harness.slots.under = below;
    if (above) harness.slots.over = above;
    handOverTheDrawings(harness.viewer);
  };
  // Change the engine underneath without losing the view. See `switchTo`.
  harness.switchTo = switchTo;
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

  window.addEventListener("resize", () =>
    harness.viewer.setView(harness.viewer.getView()),
  );
  // One key, so that two engines can be compared on the same view by pressing it
  // and looking again. It is deliberately not one of the keys the flat view used
  // to answer to — those are all refused and counted, and `CONTROLS.md` says why.
  window.addEventListener("keydown", (event) => {
    if (event.key !== "o" && event.key !== "O") return;
    const next = nextOption();
    if (next) switchTo(next);
  });
  harness.ready = true;
  sayWhichEngineIsUnderneath();
}

/**
 * Open the chosen option inside the box and wire the page's two drawings to it.
 *
 * Split out from `boot` because the engine underneath can be changed while the
 * page is open, and everything here has to happen again when it is.
 */
async function putAViewerInTheBox(view) {
  const openViewer = await openerFor(optionName);
  const viewer = await openViewer(box, {
    acquisitions: harness.acquisitionsAsked,
    coverage: harness.coverage,
    background,
    // Bounding what the engine draws to the ground the run imaged is on by
    // default, because it is the arrangement that would ship. One measurement
    // turns it off, so that the saving can be shown rather than asserted.
    boundToCoverage: asked.get("bounded") !== "0",
    onViewChanged: (settled) => {
      harness.viewNow = settled;
    },
  });
  harness.viewer = viewer;
  harness.option = optionName;
  // Read off the handle rather than worked out from the option's name. The page
  // must be able to find out whether the bottom slot is really beneath the
  // picture without knowing which engine it is talking to, because that is the
  // whole point of there being one interface.
  harness.drawsUnder = viewer.drawsUnder ?? null;
  harness.drawsUnderBecause = viewer.drawsUnderBecause ?? null;
  // Painted after the option has laid its surfaces down, so it really is behind
  // them rather than merely declared first.
  if (under) box.style.background = under;
  // Both slots, in the order they sit in: the ground first, the operator's marks
  // second. The same two functions go to every option, and neither of them knows
  // which one it reached.
  handOverTheDrawings(viewer);
  viewer.setView(view);
  if (harness.plane != null) viewer.setPlane(harness.plane);
  if (harness.moment != null) viewer.setMoment(harness.moment);
  for (const [index, settings] of Object.entries(harness.channels || {})) {
    viewer.setChannel(Number(index), settings);
  }
  return viewer;
}

/**
 * The next option along the list, wrapping round at the end.
 *
 * Anything already found not to open in this page is stepped over rather than
 * offered again, so that one option that cannot be reached does not stop the key
 * reaching the others. `switchTo` explains what makes an option unreachable and
 * why it is a fact about the page rather than about the option. Nothing at all is
 * returned when there is nowhere left to go.
 */
function nextOption() {
  const all = optionsBuiltIn();
  const at = all.indexOf(optionName);
  for (let step = 1; step <= all.length; step += 1) {
    const name = all[(at + step) % all.length];
    if (name !== optionName && !harness.cannotChangeTo.includes(name)) return name;
  }
  return null;
}

/**
 * Change the engine underneath, keeping the view exactly where it is.
 *
 * Comparing two ways of drawing the same thing is very hard if looking at the
 * second one means opening a fresh page and finding your way back to where you
 * were. Small differences — half a pixel of registration, a slightly different
 * edge — are only visible when the two pictures are of the same view moments
 * apart. So the old viewer is closed, the new one is opened in the same box, and
 * the centre, the magnification, the plane, the moment and the channel settings
 * are carried across.
 *
 * The gestures are untouched by this. They listen on the box, which does not go
 * away, and they reach whichever viewer is in it through `harness.viewer` rather
 * than through one they were handed when the page opened.
 *
 * **One pair of options cannot be swapped this way, and it is worth knowing
 * why.** The two options that draw with Viv are installed from two different
 * lists of packages — one borrows the viewer's own, the other keeps a list beside
 * itself — and the versions of deck.gl underneath them are not the same. deck.gl
 * refuses outright to have two versions of itself alive in one page and says so:
 * "multiple versions detected". So changing from one Viv option straight to the
 * other fails, the engine that was working is put back on the same view, and the
 * reason is written in the corner rather than swallowed. Every other change
 * works, including from either Viv option to neuroglancer and back, so a fresh
 * page is all that is needed to reach the third. Making all three swappable would
 * mean the two Viv options sharing one version of deck.gl, which would change
 * which version of the engine the measurements describe — a real decision, and
 * not one to take by accident while adding a keystroke.
 */
async function switchTo(name) {
  if (harness.switching || name === optionName) return harness.option;
  harness.switching = true;
  const wasShowing = optionName;
  const carriedOver = harness.viewer.getView();
  harness.switchWouldNotWork = null;
  try {
    harness.viewer.destroy();
    optionName = name;
    await putAViewerInTheBox(carriedOver);
  } catch (why) {
    // Put the engine that was working back, on the same view, rather than
    // leaving an empty box. A page that has quietly become blank is the single
    // most expensive failure this project keeps meeting, and one that has become
    // blank because somebody pressed a key would be worse still.
    harness.switchWouldNotWork = {
      wanted: name,
      why: String(why && why.message ? why.message : why),
    };
    if (!harness.cannotChangeTo.includes(name)) harness.cannotChangeTo.push(name);
    optionName = wasShowing;
    try {
      await putAViewerInTheBox(carriedOver);
    } catch (alsoWhy) {
      harness.failed = String(alsoWhy && alsoWhy.stack ? alsoWhy.stack : alsoWhy);
      note.textContent = harness.failed;
      harness.switching = false;
      return harness.option;
    }
  }
  sayWhichEngineIsUnderneath();
  harness.switching = false;
  return harness.option;
}

/**
 * Say in the corner which engine is drawing and whether it can honour the bottom
 * layer.
 *
 * Only in the three-layer view, and deliberately so. Every other view is
 * photographed by a measurement that counts colours, and a line of text in the
 * corner would be another colour in the photograph. This one is for a person
 * flipping between engines with the **o** key, where knowing which one you are
 * looking at is the whole point.
 */
function sayWhichEngineIsUnderneath() {
  if (whatToDraw !== "threeLayers") {
    note.textContent = "";
    return;
  }
  note.textContent =
    `${harness.option} — press o for the next engine\n` +
    (harness.drawsUnder
      ? "the bottom layer is drawn beneath the picture"
      : `no bottom layer: ${harness.drawsUnderBecause || "this engine cannot"}`) +
    (harness.switchWouldNotWork
      ? `\ncould not change to ${harness.switchWouldNotWork.wanted}, so this one ` +
        `was put back: ${harness.switchWouldNotWork.why}`
      : "");
}

note.textContent = `opening "${optionName}"…`;
boot().catch((why) => {
  harness.failed = String(why && why.stack ? why.stack : why);
  // Said on the page as well as recorded, because a blank page that is broken
  // and a blank page that is still loading look exactly alike, and this project
  // has lost days to the difference.
  note.textContent = harness.failed;
});
