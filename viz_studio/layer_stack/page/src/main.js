/**
 * The probe page: a stack of image layers inside one flat view, and a small set
 * of handles for the measuring program to take hold of.
 *
 * The page is told what to build by its address, so that one built page serves
 * every measurement without anything being rebuilt. The important one is
 * ``layers``, which carries a short description of the whole stack:
 *
 *   ``?layers=[{"store":"under","shader":"green"},{"store":"over","shader":"red"}]``
 *
 * written out bottom of the stack first. Each entry may also carry an
 * ``opacity``, and a ``source`` if a measurement needs to hand the engine
 * something other than the plain address of a store — which is how the question
 * about showing only part of a store is put to it.
 *
 * Everything the measuring program needs is hung on ``window.probe``. None of it
 * is the page reporting on whether it is correct. Every verdict in the write-up
 * comes from a photograph; what is here is only the means to build a stack, to
 * move the view, and to make things happen at a chosen moment.
 */

import {
  FLAT_VIEW,
  drawnLayerCount,
  followTheEngine,
  letGoOfDecodedPieces,
  pushView,
  readView,
  setOpacity,
  setVisible,
  startStack,
} from "./stack.js";

const asked = new URLSearchParams(window.location.search);

// The stack, bottom first. Written as a small piece of JSON rather than as a
// string of colons and commas because several measurements need to hand the
// engine a source specification of their own, and those are themselves JSON.
const wantedLayers = JSON.parse(asked.get("layers") || "[]");

// The colour behind everything. A colour of its own rather than the page's own
// colour, so that "nothing at all was drawn here" can be told apart from "a
// layer was drawn here in a dark colour" — a distinction most of these
// measurements turn on. In the finished viewer this would match the page so the
// operator never sees a seam.
const background = asked.get("bg") || "#3060a0";

// Where to look, in micrometres on the specimen, and how much specimen one
// screen pixel covers. Micrometres everywhere, because that is what the
// operator's stage and the store's own description both speak.
const startingView = {
  cx: Number(asked.get("cx") || 512),
  cy: Number(asked.get("cy") || 512),
  umPerPixel: Number(asked.get("umpp") || 1),
};

const engineHost = document.getElementById("engine");

/**
 * Give the engine's element a size in plain pixel numbers.
 *
 * This has to be done in so many words rather than left to the stylesheet. The
 * engine builds a tree of elements of its own inside this one and sizes its
 * drawing surface from what it measures here, and left to fill its parent the
 * element measured nine hundred pixels wide and *nought* high — so the engine
 * drew a canvas nine hundred by nought and the window stayed black, with no
 * error anywhere and the engine perfectly satisfied that it had drawn three
 * hundred frames.
 *
 * It also has to be done again whenever the window changes size, for the same
 * reason: numbers written once and not written again leave the engine drawing at
 * the old size.
 */
function sizeTheEngine() {
  engineHost.style.width = `${window.innerWidth}px`;
  engineHost.style.height = `${window.innerHeight}px`;
}

let viewer = null;
let view = { ...startingView };
const counted = { enginePaints: 0, lastPresented: null };

function sourceFor(wanted) {
  // A layer may be given a source specification outright — that is how the
  // question "can one store be shown as several bounded pieces" is put to the
  // engine. Otherwise it is the plain address of a store.
  //
  // The address has to be a whole one, with the site's own name at the front.
  // The engine's readers resolve what they are given against nothing in
  // particular, so a path beginning with a slash is quietly never fetched: the
  // layer is built, no error is raised, no request is ever made, and the page
  // simply waits for ever.
  if (wanted.source) return wanted.source;
  return `${window.location.origin}/data/${wanted.store}.ome.zarr/|zarr2:`;
}

async function boot() {
  sizeTheEngine();
  window.addEventListener("resize", sizeTheEngine);
  viewer = await startStack(engineHost, {
    layers: wantedLayers.map((wanted) => ({ ...wanted, source: sourceFor(wanted) })),
    background,
    flatView: FLAT_VIEW,
  });

  followTheEngine(viewer, () => {
    counted.enginePaints += 1;
    counted.lastPresented = readView(viewer);
  });

  pushView(viewer, view);

  const byName = new Map(
    viewer.stackLayers.map(({ managed, wanted }) => [wanted.store, managed]),
  );

  Object.assign(window.probe, {
    setView: (next) => {
      view = { ...view, ...next };
      pushView(viewer, view);
      return view;
    },
    view: () => ({ ...view }),
    // What the engine has just drawn with, read back rather than remembered.
    presented: () => counted.lastPresented,
    // Hide or show one layer by the name of its store. Hiding takes it out of
    // the list the engine draws, which is the thing worth measuring: whether a
    // layer above it is drawn differently once it is gone.
    setVisible: (store, shown) => {
      const managed = byName.get(store);
      if (!managed) throw new Error(`no layer called ${store}`);
      setVisible(managed, shown);
      return drawnLayerCount(viewer);
    },
    // Change one layer's opacity. The engine multiplies this into the alpha the
    // shader emits, so an opacity of nought draws nothing at all — while, the
    // measurement asks, possibly still holding its place in the stack.
    setOpacity: (store, value) => {
      const managed = byName.get(store);
      if (!managed) throw new Error(`no layer called ${store}`);
      setOpacity(managed, value);
      return value;
    },
    // How many layers the engine believes it is drawing. This is the engine
    // reporting on itself, so no verdict rests on it; it is kept because when a
    // photograph is surprising, knowing whether the engine thought it had two
    // layers or one turns a guess into a diagnosis.
    drawnLayers: () => drawnLayerCount(viewer),
    letGo: () => letGoOfDecodedPieces(viewer),
    frames: () => viewer.display.frameNumber,
    paints: () => counted.enginePaints,
  });

  window.probe.ready = true;
}

window.probe = {
  ready: false,
  layers: wantedLayers,
  background,
};

boot().catch((why) => {
  window.probe.failed = String(why && why.stack ? why.stack : why);
});
