/**
 * The arrangement under test: the drawing engine underneath, the operator's own
 * sheet exactly on top of it, with a hole cut where the image should show.
 *
 * The attraction of this arrangement is real. The engine already treats one
 * enormous, mostly-empty acquisition as its whole reason for existing; it is
 * proven here on this project's own data; nothing has to be injected into
 * anybody's library to make it work; and the three-dimensional view comes almost
 * free, being the same engine asked for a different layout.
 *
 * The doubt is equally real, and it is what this file exists to expose to
 * measurement. Two drawing surfaces cannot be handed to the screen in the same
 * instant. If the sheet on top follows the mouse while the engine underneath
 * draws whenever it is ready, the image slides out from under the outlines and
 * nothing reports that it has.
 *
 * The proposed answer is to stop the sheet following the mouse and have it
 * follow **the view the engine has just drawn** instead. Both are then equally
 * behind, and being equally behind is the same as being lined up. Whether the
 * engine will tell us what it has just drawn is the first thing that had to be
 * found out, and it does: it announces the end of every frame, and it does so
 * while still inside the browser's drawing turn, so a sheet repainted from
 * inside that announcement reaches the screen in the same frame as the image.
 * See ``followTheEngine`` below.
 */

import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import { makeMinimalViewer } from "neuroglancer/unstable/ui/minimal_viewer.js";
import { makeLayer } from "neuroglancer/unstable/layer/index.js";
import "neuroglancer/unstable/ui/default_viewer.css";
// Loaded after the engine's own stylesheet so it wins. It hides the handful of
// controls the engine draws inside the image itself — a cluster of layout
// buttons in one corner, a panel of axis names in another. Here they matter for
// a reason of their own as well as the one given in the file: they are extra
// colours inside the photograph, and the margin test tells its three colours
// apart by colour alone.
import "./engine-chrome.css";

/**
 * Two ways of asking the engine for a flat view of the plate, and why there are
 * two.
 *
 * The engine draws three chosen axes: one across the window, one down it, and
 * one into the screen. Which is which follows from two things together — the
 * *order* the axes are handed over in, and which of the engine's named layouts
 * is asked for — and the two interact in a way that is easy to get wrong and
 * impossible to see afterwards.
 *
 * ``as the viewer does it`` is what `viz_studio/frontend` does today: hand the
 * axes over in the order the image declares them, which for this project's
 * images is depth, height, width, and ask for the layout the engine calls
 * ``yz``. That does put width across the window and height down it, and it
 * looks right.
 *
 * ``width running to the right`` hands the same three axes over in the opposite
 * order — width, height, depth — and asks for the layout called ``xy``.
 *
 * The difference between them is measured rather than argued about; see the
 * report. It matters because it decides which way the specimen faces, and a
 * picture that faces the wrong way still looks like a perfectly good picture.
 */
export const FLAT_VIEWS = {
  "as the viewer does it": { layout: "yz", widthFirst: false, across: 2, down: 1 },
  "width running to the right": { layout: "xy", widthFirst: true, across: 0, down: 1 },
};

/**
 * Start the engine, hand it the acquisition, and leave it drawing.
 *
 * Nothing about the engine's own way of being driven is switched on: no mouse
 * bindings, no keyboard table. The sheet on top catches every gesture before the
 * engine could see one, so leaving its table empty costs nothing and removes a
 * whole class of "the engine and we disagree about what dragging means".
 */
export async function startEngine(container, { source, shader, flatView }) {
  const chosen = FLAT_VIEWS[flatView] || FLAT_VIEWS["as the viewer does it"];
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
  viewer.layout.restoreState(chosen.layout);
  viewer.showDefaultAnnotations.value = false;
  viewer.showAxisLines.value = false;
  viewer.showScaleBar.value = false;
  // The background behind the acquisition. In the finished viewer this is meant
  // to match the page so that the seam between the two surfaces cannot be seen;
  // here it must be a colour of its own, or the margin being measured would be
  // invisible. See the long note at the top of `margin_probe.js`.
  viewer.crossSectionBackgroundColor.restoreState("#0000ff");

  const managed = makeLayer(viewer.layerSpecification, "acquisition", {
    type: "image",
    source,
    shader,
  });
  viewer.layerSpecification.add(managed);

  await whenTheAxesAreKnown(viewer);
  pinTheAxesThatMeasureDistance(viewer, chosen);
  viewer.flatView = chosen;
  return viewer;
}

/**
 * Wait until the image has said how big a voxel is.
 *
 * Until it has, the engine is working in a space with no axes at all and every
 * conversion between the operator's coordinates and the screen would be
 * nonsense. This is the same wait the viewer itself does before choosing a
 * starting magnification, and for the same reason.
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
 * Put the axes that measure distance on screen, and no others.
 *
 * An image written by this project declares five axes: the moment, the colour,
 * and then depth, height and width. Left alone the engine draws the first three
 * of them, which means drawing time against colour and showing nothing at all.
 * Only the axes whose unit is a length belong on screen, and the image says
 * which those are, so nothing has to be guessed from a name.
 */
function pinTheAxesThatMeasureDistance(viewer, chosen) {
  const space = viewer.navigationState.position.coordinateSpace.value;
  const distances = space.names.filter((_, at) => space.units?.[at] === "m");
  if (distances.length < 2) return;
  const wanted = chosen.widthFirst
    ? distances.slice(0, 3).reverse()
    : distances.slice(0, 3);
  viewer.navigationState.pose.displayDimensions.restoreState(wanted);
}

/** Where each axis on screen sits in the image's own list of axes. */
function axesOnScreen(viewer) {
  const info = viewer.navigationState.displayDimensionRenderInfo.value;
  const chosen = viewer.flatView || FLAT_VIEWS["as the viewer does it"];
  return {
    across: info.displayDimensionIndices[chosen.across],
    down: info.displayDimensionIndices[chosen.down],
    // How many of the image's own voxels the engine counts as one "canonical"
    // voxel on each axis. It is what turns the engine's single magnification
    // number into a number of voxels to a screen pixel, and it is 1 on an image
    // whose voxels are square, which these are.
    factorAcross: info.canonicalVoxelFactors[chosen.across],
    factorDown: info.canonicalVoxelFactors[chosen.down],
  };
}

/**
 * Tell the engine where to look.
 *
 * ``view`` is in the operator's own terms: the middle of the *window* in voxels,
 * and how many voxels one browser pixel covers. When the engine has been given
 * only part of the window to draw in — which is what bounding the drawn region
 * to the ground a run actually imaged comes to — the middle of its patch is not
 * the middle of the window, and the difference is added here so that a given
 * point of specimen still lands on the same point of the window either way.
 */
export function pushView(viewer, view, { engineRect, windowSize }) {
  const axes = axesOnScreen(viewer);
  const position = Float32Array.from(viewer.navigationState.position.value);
  const engineCentreX = engineRect.left + engineRect.width / 2;
  const engineCentreY = engineRect.top + engineRect.height / 2;
  position[axes.across] =
    view.cx + (engineCentreX - windowSize.width / 2) * view.scale;
  position[axes.down] =
    view.cy + (engineCentreY - windowSize.height / 2) * view.scale;
  viewer.navigationState.position.value = position;
  viewer.navigationState.zoomFactor.value = view.scale * axes.factorAcross;
}

/**
 * The view the engine has just drawn with, in the operator's own terms.
 *
 * Read back rather than remembered, because the point of the whole exercise is
 * that what the engine drew and what we *asked* it to draw are not necessarily
 * the same thing at the same moment.
 */
export function readPresentedView(viewer, { engineRect, windowSize }) {
  const axes = axesOnScreen(viewer);
  const position = viewer.navigationState.position.value;
  const scale = viewer.navigationState.zoomFactor.value / axes.factorAcross;
  const engineCentreX = engineRect.left + engineRect.width / 2;
  const engineCentreY = engineRect.top + engineRect.height / 2;
  return {
    scale,
    cx: position[axes.across] - (engineCentreX - windowSize.width / 2) * scale,
    cy: position[axes.down] - (engineCentreY - windowSize.height / 2) * scale,
  };
}

/**
 * Do something at the end of every frame the engine draws.
 *
 * This is the hook the whole proposal rests on, so it is worth saying exactly
 * what it is. The engine announces the end of each frame with a signal called
 * ``updateFinished``, and — this is the part that matters — it dispatches that
 * signal from inside its own drawing function, which the browser is running as
 * part of a single animation frame. Anything painted from inside the
 * announcement is therefore painted before the browser composites the page, so
 * the two surfaces reach the screen together rather than one frame apart.
 *
 * What the engine does *not* offer is a snapshot of the view it drew with. There
 * is no "here is the state of frame 412". What there is instead is the plain
 * fact that the engine reads the current view at the moment it draws, so the
 * current view read from inside this announcement *is* the view it just drew
 * with. That is enough, and it is what ``readPresentedView`` above relies on.
 */
export function followTheEngine(viewer, paint) {
  return viewer.display.updateFinished.add(paint);
}

/**
 * Turn the flat view on purpose, so that a check for it can be shown to fail.
 *
 * Rotation is removed from the flat view, and a check that it has been removed
 * is worth nothing unless it can be shown to notice a rotation that really
 * happened — an unbound gesture and a gesture nobody tried look exactly alike.
 * So this reaches past the gestures and turns the view directly, which is the
 * one thing an operator can no longer do.
 *
 * It is also the clearest demonstration of *why* rotation was removed. A
 * rotated picture is still a perfectly good picture; it simply no longer lines
 * up with the carrier outline and the tile rectangles drawn over it, and
 * nothing anywhere reports that it has stopped lining up. The margins go to
 * pieces immediately, which is exactly what they are for.
 */
export function rotateOnPurpose(viewer, degrees) {
  const pose = viewer.navigationState.pose;
  const turn = (degrees * Math.PI) / 180;
  const half = Math.sin(turn / 2);
  const spin = [0, 0, half, Math.cos(turn / 2)];
  const held = pose.orientation.orientation;
  // Multiply the view's own turn by this one, in place, and say it has changed.
  const [x, y, z, w] = held;
  const [ax, ay, az, aw] = spin;
  held[0] = w * ax + x * aw + y * az - z * ay;
  held[1] = w * ay - x * az + y * aw + z * ax;
  held[2] = w * az + x * ay - y * ax + z * aw;
  held[3] = w * aw - x * ax - y * ay - z * az;
  pose.orientation.changed.dispatch();
}

/** How many frames the engine has drawn since the page opened. */
export function framesDrawn(viewer) {
  return viewer.display.frameNumber;
}

/**
 * Where the edge of the acquisition really is in the frame the engine has just
 * drawn, read out of the engine's own drawing surface.
 *
 * This exists to settle a question that nothing else can settle. The engine
 * announces the end of a frame, and the view read at that moment is the view it
 * was asked to draw with — but "was asked to draw with" and "what is now on the
 * surface" are not the same claim, and the whole doubt about this arrangement
 * lives in the gap between them. So rather than believe either, this looks at
 * the pixels the engine has just produced and finds the first bright one along
 * the middle row. Comparing that with where the view says the edge should be
 * says plainly whether the engine's frame is the frame the view describes.
 *
 * It has to be called from inside the end-of-frame announcement. A drawing
 * surface is only readable until the browser takes it away to put on screen, so
 * a moment later there is nothing there to read.
 */
export function whereTheImageEdgeIs(viewer) {
  const gl = viewer.display.gl;
  const width = gl.drawingBufferWidth;
  const height = gl.drawingBufferHeight;
  if (!width || !height) return null;
  const row = new Uint8Array(width * 4);
  gl.readPixels(
    0, Math.floor(height / 2), width, 1, gl.RGBA, gl.UNSIGNED_BYTE, row,
  );
  // The acquisition is near white and the background behind it is blue, so the
  // edge is the first place all three colours are bright at once.
  for (let at = 0; at < width; at += 1) {
    if (row[at * 4] > 150 && row[at * 4 + 1] > 150 && row[at * 4 + 2] > 150) {
      return { at, width };
    }
  }
  return { at: null, width };
}

/**
 * Ask the engine to forget the pieces of image it has already decoded.
 *
 * This is what makes it possible to watch a run that writes into one large
 * image. The engine remembers every piece it has decoded, including the pieces
 * it found to be empty, and there is no time limit on that memory — so a tile
 * written into a place it has already looked at is simply never noticed. Not
 * "slow to appear": no request at all, ever.
 *
 * The pieces live in a background worker, and this sends word to that worker to
 * let them go. The viewer's own live path does exactly this, in
 * `frontend/src/engine.js`, and the note there explains what it costs: only the
 * pieces actually on screen are fetched again, which follows the size of the
 * window rather than the size of the specimen.
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
