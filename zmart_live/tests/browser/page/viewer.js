/**
 * The smallest page that opens a real Neuroglancer on one growing run.
 *
 * This exists for one test, and it is worth saying plainly what that test is
 * asking, because everything here is shaped by it.
 *
 * While a microscope is running, image files appear on disk continuously, and a
 * half-written position looks exactly like a finished one. The rule this project
 * works to is that a position becomes visible only once it has been *committed*
 * to the run's publication record — the bookkeeping described at the top of
 * `zmart_live/manifest.py`. Files existing means nothing; the commit means
 * everything.
 *
 * A rule like that is only worth having if it is true of the picture an operator
 * actually sees. So the test drives this page, which is a genuine Neuroglancer
 * reading a genuine OME-Zarr over HTTP, and photographs the screen. Nothing here
 * stands in for the drawing engine.
 *
 * ## What this page deliberately does not do
 *
 * It opens **one** image source, not one per position. The two positions of the
 * run are two halves of a single image, exactly as an acquisition writes them,
 * so "position B is not drawn" cannot be satisfied by a layer simply being
 * absent — the layer is there either way, and what changes is whether the pieces
 * of image behind its right-hand half can be fetched at all.
 *
 * It has no controls, no labels and no chrome. Anything drawn on the page would
 * be counted as light by the measurement the test makes, and that measurement is
 * the only evidence the test has.
 *
 * ## Where the picture lands on the screen
 *
 * The box the viewer draws into is 1024 by 512 browser pixels, and the run is
 * 1024 by 512 voxels. The view is set to one voxel per screen pixel, centred on
 * the middle of the run, so the run exactly fills the box: the left half of the
 * box is position A's ground and the right half is position B's, in every
 * photograph and at every point in the test. That is what lets the test measure
 * "how much of A is lit" against a rectangle that never moves. A rectangle
 * worked out from wherever the picture happens to be would move as soon as a
 * second position appeared, which is precisely the moment the measurement has to
 * be trustworthy.
 */

import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import { makeMinimalViewer } from "neuroglancer/unstable/ui/minimal_viewer.js";
import { makeLayer } from "neuroglancer/unstable/layer/index.js";
import "neuroglancer/unstable/ui/default_viewer.css";

/**
 * Which panels the engine puts on screen, and which way round the axes go.
 *
 * These two belong together. The engine decides what runs across the window and
 * what runs down it from the order the axes are handed over *and* from the named
 * layout. Handing the distance axes over widest-first and asking for `xy` puts
 * width across the window and height down it, which is the specimen drawn the
 * way round it really is. The other pairing that also looks right draws every
 * picture mirrored, and nothing reports it — see the note on `FLAT_LAYOUT` in
 * `viz_studio/options/neuroglancer-under/viewer.js`, where that cost months.
 */
const FLAT_LAYOUT = "xy";

/** Metres to micrometres. The store speaks metres; this page counts in µm. */
const UM_PER_M = 1e6;

/** The brightness range the picture is drawn with, in the stored numbers' units. */
const WINDOW = { low: 0, high: 4095 };

/**
 * How large one voxel is meant to be on screen, in micrometres per browser
 * pixel. The run is written with one-micrometre voxels, so a value of one puts
 * one voxel in one pixel and makes the box on the page and the run the same size.
 */
const UM_PER_SCREEN_PIXEL = 1;

/** Where to look: the middle of the run, in micrometres. */
const LOOK_AT = { x: 512, y: 256 };

/**
 * A little program for the graphics card that draws the picture in white.
 *
 * The transparency carries only "was this spot imaged", so ground nothing has
 * been written to stays clear rather than being painted black. The brightness
 * lives in the colour. This is the flat-picture form of the shader in
 * `viz_studio/options/neuroglancer-under/viewer.js`; the note there explains why
 * a volume needs the opposite arrangement.
 */
const SHADER =
  "#uicontrol invlerp normalized\n" +
  "void main() { float v = normalized();" +
  " emitRGBA(vec4(vec3(1.0, 1.0, 1.0) * v, v > 0.0 ? 1.0 : 0.0)); }";

/**
 * Wait until the image has said how big a voxel is.
 *
 * Until it has, the engine is working in a space with no axes in it at all, and
 * anything this page said about where to look would be meaningless.
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
 * Put the axes that measure distance on the screen, and leave the others alone.
 *
 * An OME-Zarr image has five axes: which moment, which colour of light, and then
 * the three that say where in the specimen something is. Only the last three
 * belong on screen. The engine cannot know that on its own — left alone it takes
 * the first three in the order they were written, which draws time against depth
 * and puts the specimen nowhere. Metres are the only unit that measures distance
 * across a specimen, so that is what is looked for.
 */
function pinTheAxesThatMeasureDistance(viewer) {
  const space = viewer.navigationState.position.coordinateSpace.value;
  if (!space?.names) return;
  const distances = space.names.filter((_, at) => space.units?.[at] === "m");
  if (distances.length < 2) return;
  // Width first, depth last: an OME-Zarr image lists its distance axes
  // slowest-changing first, so reversing them puts width across the window.
  viewer.navigationState.pose.displayDimensions.restoreState(
    distances.slice(0, 3).reverse(),
  );
}

/** Where each axis on screen sits in the image's own list, and how big it is. */
function axesOnScreen(viewer) {
  const info = viewer.navigationState.displayDimensionRenderInfo.value;
  const space = viewer.navigationState.position.coordinateSpace.value;
  const across = info.displayDimensionIndices[0];
  const down = info.displayDimensionIndices[1];
  return {
    across,
    down,
    umAcross: (space?.scales?.[across] ?? 0) * UM_PER_M,
    umDown: (space?.scales?.[down] ?? 0) * UM_PER_M,
    umPerCanonicalVoxel: info.canonicalVoxelPhysicalSize * UM_PER_M,
  };
}

/**
 * Tell the engine exactly where to look, in micrometres.
 *
 * The engine's own idea of zoom is "how many of the smallest voxel on screen
 * fall in one browser pixel", which is a number whose meaning changes with the
 * image. The conversion to micrometres per pixel is the one line below, and it
 * is worth checking rather than trusting: the engine works out voxels per pixel
 * for an axis as `zoomFactor / canonicalVoxelFactors[axis]`, and that factor is
 * the axis's voxel size divided by the canonical one, so the axis cancels and
 * micrometres per pixel is simply `zoomFactor × umPerCanonicalVoxel`.
 */
function look(viewer, centre, umPerPixel) {
  const axes = axesOnScreen(viewer);
  const navigation = viewer.navigationState;
  if (axes.umAcross > 0 && axes.umDown > 0) {
    const position = Float32Array.from(navigation.position.value);
    position[axes.across] = centre.x / axes.umAcross;
    position[axes.down] = centre.y / axes.umDown;
    navigation.position.value = position;
  }
  if (axes.umPerCanonicalVoxel > 0) {
    navigation.zoomFactor.value = umPerPixel / axes.umPerCanonicalVoxel;
  }
}

/**
 * Send every one of the engine's readers back to the store.
 *
 * Nothing on disk announces that a position has been committed, and the engine
 * has no reason of its own to ask again for something it has already fetched.
 * This is the instruction that makes it ask: it tells each reader to let go of
 * what it decoded, so the next frame fetches afresh.
 *
 * The count it hands back matters to the test. "The engine was asked and nothing
 * came back" and "the engine was never asked" look identical on screen and mean
 * completely different things, and a test that cannot tell them apart is not
 * measuring what it thinks it is.
 */
function goBackToTheStore(viewer) {
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
 * Open the viewer on the store named in the page's address.
 *
 * The address is passed in rather than worked out, because the run under test is
 * served on a port chosen when the test starts. An address without a scheme and
 * host is fetched from nowhere at all by this engine, with no error reported, so
 * it is refused here instead of turning into a blank screen with no explanation.
 */
async function open() {
  const asked = new URLSearchParams(window.location.search).get("store") || "";
  if (!/^[a-z]+:\/\//i.test(asked)) {
    throw new Error(
      `The page was opened without a whole address for the run: "${asked}". ` +
      "It needs one including the scheme and host, such as " +
      "http://127.0.0.1:8000/live.ome.zarr/|zarr2:",
    );
  }

  const viewer = makeMinimalViewer({
    target: document.getElementById("picture"),
    showUIControls: false,
    showTopBar: false,
    showLayerPanel: false,
    showLocation: false,
    showPanelBorders: false,
    showLayerDialog: false,
    resetStateWhenEmpty: false,
  });
  viewer.layout.restoreState(FLAT_LAYOUT);
  // The engine's own furniture — layout buttons, axis names, axis lines and a
  // scale bar — is all light on the screen, and this test counts light.
  viewer.showDefaultAnnotations.value = false;
  viewer.showAxisLines.value = false;
  viewer.showScaleBar.value = false;
  viewer.crossSectionBackgroundColor.restoreState("#000000");

  const managed = makeLayer(viewer.layerSpecification, "run", {
    type: "image",
    source: asked,
    shader: SHADER,
    shaderControls: { normalized: { range: [WINDOW.low, WINDOW.high] } },
    // Full strength. The engine's default for an image layer is a half, which is
    // right for looking through one layer at another and wrong here, where there
    // is one picture and it should be drawn as bright as it is.
    opacity: 1,
  });
  viewer.layerSpecification.add(managed, 0);

  await whenTheAxesAreKnown(viewer);
  pinTheAxesThatMeasureDistance(viewer);
  // The engine chooses a magnification the first moment it believes it knows
  // what space the picture lives in, and for a moment that is an empty space in
  // which one voxel is one metre. Clearing it makes it choose again; then the
  // line below chooses for it.
  viewer.navigationState.zoomFactor.reset();
  look(viewer, LOOK_AT, UM_PER_SCREEN_PIXEL);

  return viewer;
}

/* Everything the test needs to drive the page, and nothing else. Failures are
   kept rather than thrown away, so that a page which never opened can say why
   instead of merely staying black. */
const probe = {
  viewer: null,
  failed: null,
  ready: false,
  refresh: () => 0,
  /** Where the engine ended up looking, so a test can say so in its output. */
  view: () => null,
};
window.probe = probe;

open().then(
  (viewer) => {
    probe.viewer = viewer;
    probe.refresh = () => goBackToTheStore(viewer);
    probe.view = () => {
      const axes = axesOnScreen(viewer);
      const position = viewer.navigationState.position.value;
      return {
        centre: {
          x: position[axes.across] * axes.umAcross,
          y: position[axes.down] * axes.umDown,
        },
        umPerPixel: viewer.navigationState.zoomFactor.value * axes.umPerCanonicalVoxel,
      };
    };
    probe.ready = true;
  },
  (trouble) => {
    probe.failed = String(trouble?.stack || trouble);
  },
);
