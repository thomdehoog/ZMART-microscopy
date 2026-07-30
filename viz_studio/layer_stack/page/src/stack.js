/**
 * Several acquisitions stacked inside one flat view, and the handful of controls
 * needed to take them apart again.
 *
 * `LAYERS.md` describes a stack with the plate layout at the bottom, the tiles
 * the operator planned above it, and the acquisition on top with unimaged room
 * drawn see-through so the two below show through it. This file builds exactly
 * that, as several image layers inside one engine, so that it can be
 * photographed and measured rather than argued about.
 *
 * The whole arrangement rests on one assumption: that a layer with see-through
 * parts, drawn above another layer, really does let the lower one show through.
 * The engine's own code reads as though it should — it turns blending off only
 * for whichever layer is drawn first and leaves it on for every layer after
 * that — but an obvious reading of code is not a measurement, so nothing here
 * takes it on trust.
 */

import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import { makeMinimalViewer } from "neuroglancer/unstable/ui/minimal_viewer.js";
import { makeLayer } from "neuroglancer/unstable/layer/index.js";
import "neuroglancer/unstable/ui/default_viewer.css";
// Loaded after the engine's own stylesheet so that it wins. It hides the few
// controls the engine draws inside the picture itself. Here they would be extra
// colours inside a photograph, and several of these measurements tell one layer
// from another by colour alone.
import "./engine-chrome.css";

/**
 * How the numbers in a store are turned into what you see.
 *
 * Each of these is a complete shader for one image layer. They are written out
 * in full rather than assembled from pieces because a shader is the one place
 * where a small change quietly alters what a photograph means, and a reader
 * checking a measurement should be able to see exactly what was drawn.
 *
 * Two families matter.
 *
 * The **see-through** ones end with `v > 0.0 ? 1.0 : 0.0`. That is the whole
 * trick behind the stack: a voxel of nought is drawn as nothing at all, so
 * whatever lies underneath shows through. Room a run declared but never imaged
 * reads back as nought, so this is what makes unimaged ground see-through.
 *
 * The **opaque** ones always emit an alpha of one. They exist so that a
 * measurement can be shown the truth beside the appearance: drawn opaque, a
 * layer shows exactly where it has been written, including the parts that the
 * see-through shader makes vanish. Question 6 leans on that pair entirely.
 *
 * The saturated colours — pure red, pure green — are not decoration. Several of
 * these measurements have to tell three things apart in a photograph: the lower
 * layer, the upper layer, and the engine's own background. Giving each a colour
 * that nothing else could produce means the reading needs no threshold and no
 * judgement.
 */
const SHADERS = {
  // Saturated colours, see-through wherever nothing was written.
  green: colour(0.0, 1.0, 0.0, false),
  red: colour(1.0, 0.0, 0.0, false),
  blue: colour(0.2, 0.4, 1.0, false),
  yellow: colour(1.0, 1.0, 0.0, false),
  magenta: colour(1.0, 0.0, 1.0, false),
  // The same colours, drawn solid everywhere the image reaches — including the
  // parts nobody imaged. Used to reveal what the see-through version hides.
  greenopaque: colour(0.0, 1.0, 0.0, true),
  redopaque: colour(1.0, 0.0, 0.0, true),
  // Ordinary greyscale picture, see-through where nothing was written. This is
  // what an acquisition layer would really be drawn with.
  grey: `#uicontrol invlerp normalized(range=[0, 4095])
void main() {
  float v = normalized();
  emitRGBA(vec4(v, v, v, v > 0.0 ? 1.0 : 0.0));
}`,
  // Greyscale drawn solid everywhere, so that the edge of an imaged tile can be
  // seen even where the picture inside it is black.
  greyopaque: `#uicontrol invlerp normalized(range=[0, 4095])
void main() {
  float v = normalized();
  emitRGBA(vec4(v, v, v, 1.0));
}`,
};

function colour(r, g, b, opaque) {
  // The brightness is read but deliberately not used for the colour, only for
  // the decision about transparency. A flat saturated colour is far easier to
  // measure in a photograph than a colour that varies with what was written.
  return `#uicontrol invlerp normalized(range=[0, 4095])
void main() {
  float v = normalized();
  emitRGBA(vec4(${r.toFixed(1)}, ${g.toFixed(1)}, ${b.toFixed(1)}, ${
    opaque ? "1.0" : "v > 0.0 ? 1.0 : 0.0"
  }));
}`;
}

export function shaderNamed(name) {
  const found = SHADERS[name];
  if (!found) throw new Error(`no shader called ${name}`);
  return found;
}

/**
 * Start the engine and give it the layers, bottom of the stack first.
 *
 * ``layers`` is a list of ``{ store, shader, opacity }``. The order is the order
 * they are added in, and the engine draws them in that order — the first one
 * added is drawn first and therefore ends up underneath. Whether that really is
 * what happens is not assumed anywhere; it is what the photographs show.
 *
 * **One thing here is easy to miss and changes every result.** An image layer in
 * this engine opens at an opacity of one half, not one. Two layers stacked at
 * the default would blend into a mixture rather than one covering the other, and
 * a measurement of transparency taken without noticing would be measuring the
 * opacity control instead. So every layer is given an explicit opacity, and the
 * measurements that care state what they set it to.
 */
export async function startStack(container, { layers, background, flatView }) {
  const viewer = makeMinimalViewer({
    target: container,
    showUIControls: false,
    showTopBar: false,
    showLayerPanel: false,
    showLocation: false,
    showPanelBorders: false,
    showLayerDialog: false,
    resetStateWhenEmpty: false,
  });
  viewer.layout.restoreState(flatView.layout);
  viewer.showDefaultAnnotations.value = false;
  viewer.showAxisLines.value = false;
  viewer.showScaleBar.value = false;
  // The colour behind everything. In the finished viewer this would match the
  // page so the operator never sees a seam; here it is a colour of its own so
  // that "nothing was drawn here at all" can be told apart from "something was
  // drawn here in a dark colour", which is a distinction several of these
  // measurements depend on.
  viewer.crossSectionBackgroundColor.restoreState(background);

  const added = [];
  for (const wanted of layers) {
    const managed = makeLayer(viewer.layerSpecification, wanted.store, {
      type: "image",
      source: wanted.source,
      shader: shaderNamed(wanted.shader),
    });
    viewer.layerSpecification.add(managed);
    added.push({ managed, wanted });
  }

  await whenTheAxesAreKnown(viewer);
  // The opacity has to be set after the layer has finished being built, because
  // until then there is no rendered layer to set it on.
  for (const { managed, wanted } of added) {
    setOpacity(managed, wanted.opacity ?? 1.0);
  }
  pinTheAxesThatMeasureDistance(viewer, flatView);
  viewer.flatView = flatView;
  viewer.stackLayers = added;
  return viewer;
}

/** Set one layer's opacity, which the engine multiplies into the emitted alpha. */
export function setOpacity(managed, value) {
  const layer = managed.layer;
  if (layer && layer.opacity) layer.opacity.value = value;
}

/**
 * Show or hide one layer.
 *
 * Hiding a layer takes it out of the list the engine draws, which is exactly
 * what makes this worth measuring: if the layer above depended on there being
 * something underneath it, hiding the plate would change how the acquisition
 * itself is drawn — and an operator who simply wanted the plate out of the way
 * would have no reason to connect the two.
 */
export function setVisible(managed, shown) {
  managed.setVisible(shown);
}

/**
 * Wait until the images have said how big a voxel is.
 *
 * Until they have, the engine is working in a space with no axes at all, and
 * every conversion between micrometres and the screen would be nonsense. This is
 * the same wait the viewer itself does before choosing a magnification.
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
 * Which way round the flat view is drawn.
 *
 * The engine draws three chosen axes: one across the window, one down it, one
 * into the screen. Which is which follows from the order the axes are handed
 * over together with which named layout is asked for. `SANDWICH.md` measured
 * that the order this project's viewer uses today runs width to the *left*,
 * which draws the specimen mirrored. Everything here is drawn with width running
 * to the right, because a measurement of where something lands is worthless if
 * the picture is flipped.
 */
export const FLAT_VIEW = { layout: "xy", widthFirst: true, across: 0, down: 1 };

function pinTheAxesThatMeasureDistance(viewer, chosen) {
  const space = viewer.navigationState.position.coordinateSpace.value;
  const distances = space.names.filter((_, at) => space.units?.[at] === "m");
  if (distances.length < 2) return;
  const wanted = chosen.widthFirst
    ? distances.slice(0, 3).reverse()
    : distances.slice(0, 3);
  viewer.navigationState.pose.displayDimensions.restoreState(wanted);
}

/**
 * How the engine's own numbers relate to micrometres on the specimen.
 *
 * Everything the operator and the store speak is micrometres, and none of the
 * engine's own quantities are. This is the one place the two are joined, so it
 * is worth being explicit about what each piece is.
 *
 * ``scales`` says how large one step along a global axis is, in metres. So a
 * position in micrometres divided by that scale gives the engine's own number.
 *
 * ``canonicalVoxelPhysicalSize`` is how large the engine's own unit of
 * magnification is, in metres. The engine's ``zoomFactor`` counts those per
 * screen pixel, so multiplying the two gives metres per screen pixel.
 *
 * None of this is trusted on its own. Question 2 draws a feature of known
 * physical size at a known physical place and measures it in a photograph, which
 * is what actually establishes that these conversions are right.
 */
function frame(viewer) {
  const info = viewer.navigationState.displayDimensionRenderInfo.value;
  const space = viewer.navigationState.position.coordinateSpace.value;
  const chosen = viewer.flatView || FLAT_VIEW;
  return {
    across: info.displayDimensionIndices[chosen.across],
    down: info.displayDimensionIndices[chosen.down],
    scales: space.scales,
    metresPerZoomUnit: info.canonicalVoxelPhysicalSize,
  };
}

/** Tell the engine where to look, in micrometres on the specimen. */
export function pushView(viewer, view) {
  const f = frame(viewer);
  const position = Float32Array.from(viewer.navigationState.position.value);
  position[f.across] = (view.cx * 1e-6) / f.scales[f.across];
  position[f.down] = (view.cy * 1e-6) / f.scales[f.down];
  viewer.navigationState.position.value = position;
  viewer.navigationState.zoomFactor.value =
    (view.umPerPixel * 1e-6) / f.metresPerZoomUnit;
}

/** The view the engine has just drawn with, in micrometres on the specimen. */
export function readView(viewer) {
  const f = frame(viewer);
  const position = viewer.navigationState.position.value;
  return {
    cx: (position[f.across] * f.scales[f.across]) / 1e-6,
    cy: (position[f.down] * f.scales[f.down]) / 1e-6,
    umPerPixel:
      (viewer.navigationState.zoomFactor.value * f.metresPerZoomUnit) / 1e-6,
  };
}

/** Do something at the end of every frame the engine draws. */
export function followTheEngine(viewer, paint) {
  return viewer.display.updateFinished.add(paint);
}

/**
 * Ask the engine to forget the pieces of image it has already decoded.
 *
 * Without this, a tile written into ground the engine has already looked at and
 * found empty is never noticed at all — not slow to appear, but never. Question
 * 3 photographs a run part-acquired and then fully acquired, so it needs this
 * between the two.
 */
export function letGoOfDecodedPieces(viewer) {
  const shared = viewer.chunkManager?.rpc?.objects;
  if (!shared) return 0;
  let asked = 0;
  for (const [, held] of shared) {
    if (!held || typeof held.invalidateCache !== "function") continue;
    held.invalidateCache();
    asked += 1;
  }
  return asked;
}

/**
 * The order the engine is really drawing the layers in, and how many there are.
 *
 * This is the engine reporting on itself, so no verdict in the write-up rests on
 * it. It is kept because when a photograph shows something unexpected, knowing
 * whether the engine thought it had two layers or one is the difference between
 * a diagnosis and a guess.
 */
export function drawnLayerCount(viewer) {
  let count = 0;
  for (const panel of viewer.display.panels) {
    if (!panel.sliceView) continue;
    count = Math.max(count, panel.sliceView.visibleLayerList.length);
  }
  return count;
}
