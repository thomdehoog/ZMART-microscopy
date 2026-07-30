/**
 * The probe page: whichever of the two arrangements the address asks for, with
 * the margin test set up on it and a small set of handles for the measuring
 * program to take hold of.
 *
 * The page is opened with a few words in its address, so that one built page can
 * be measured in every arrangement without rebuilding anything:
 *
 *   ``?arrangement=sandwich``    the engine underneath, the operator's sheet on top
 *   ``?arrangement=one-canvas``  both layers in one canvas — the control
 *   ``&follow=pointer``          the sheet is repainted the moment the mouse moves
 *   ``&follow=presented``        the sheet is repainted from the frame the engine just drew
 *   ``&follow=compromise``       the hole follows the engine, the operator's own
 *                                rectangle follows the mouse
 *   ``&store=square``            the small acquisition that was imaged edge to edge
 *   ``&store=sparse``            the large canvas with a small patch imaged in it
 *   ``&bounded=1``               give the engine only the part of the window that
 *                                covers ground the run actually imaged
 *
 * Everything the measuring program needs is hung on ``window.probe``. None of it
 * is the page reporting on its own correctness — the numbers in the report all
 * come from photographs of the screen. What is here is only the means to move
 * the view, to ask what the page believes, and to make things happen at a chosen
 * moment.
 */

import {
  MARGIN_CSS_PX,
  OverlaySheet,
  holeFor,
  toScreen,
} from "./margin_probe.js";
import { onlyPanAndZoom } from "./gestures.js";
import {
  followTheEngine,
  framesDrawn,
  letGoOfDecodedPieces,
  pushView,
  readPresentedView,
  rotateOnPurpose,
  startEngine,
  whereTheImageEdgeIs,
} from "./sandwich.js";
import { startOneCanvas } from "./one_canvas.js";

const asked = new URLSearchParams(window.location.search);
const arrangement = asked.get("arrangement") || "sandwich";
const follow = asked.get("follow") || "presented";
const storeName = asked.get("store") || "square";
const bounded = asked.get("bounded") === "1";
// Which way round the engine is asked to draw the flat view. See FLAT_VIEWS in
// `sandwich.js`: the two choices differ in which way the specimen faces, and
// the difference is invisible on a square.
const flatView = asked.get("axes") || "width running to the right";

// How large the acquired canvas is, in voxels. Passed in rather than read out of
// the image so that where the picture is expected to be and where it actually is
// stay two separate things — if they disagree, the margins go uneven and the
// measurement says so.
const canvasVoxels = Number(asked.get("voxels") || 1024);
// For the sparse acquisition, the patch that was actually imaged. The measuring
// program reads this from the record the writer kept beside the data.
const imagedX0 = Number(asked.get("x0") || 0);
const imagedY0 = Number(asked.get("y0") || 0);
const imagedX1 = Number(asked.get("x1") || canvasVoxels);
const imagedY1 = Number(asked.get("y1") || canvasVoxels);

// The rectangle of specimen the hole is cut around: the ground that holds
// picture. On the square that is the whole image; on the sparse canvas it is the
// patch the run imaged.
const worldRect = { x0: imagedX0, y0: imagedY0, x1: imagedX1, y1: imagedY1 };

// How the numbers in the store are turned into what you see.
//
// The brightness range is the one the writer put its tiles near the top of, so
// the acquisition comes out near white — one of the colours the margin test
// tells apart.
//
// The second line is the one that matters. A run declares far more room than it
// fills, and a piece of that room nobody has imaged reads back as nought —
// which is exactly what a piece of genuinely dark specimen reads back as. Drawn
// plainly, unimaged ground would be a solid black rectangle sitting over the
// operator's own drawing, hiding the plan for a place the microscope has not
// been to yet. Drawn as nothing at all, it lets whatever is underneath show
// through, which is what `LAYERS.md` says should happen.
const SHADER = `#uicontrol invlerp normalized(range=[0, 4095])
void main() {
  float v = normalized();
  emitRGBA(vec4(v, v, v, v > 0.0 ? 1.0 : 0.0));
}`;

const engineHost = document.getElementById("engine");
const sheetCanvas = document.getElementById("sheet");
const oneCanvas = document.getElementById("one-canvas");

// Taken from the element that holds the whole stack rather than from either
// surface, because in the control arrangement the operator's sheet is not on
// screen at all and a hidden element measures zero. Both arrangements then agree
// about how large the window is, which they must if their numbers are to be
// compared.
const stack = document.getElementById("stack");
const sizeOfWindow = () => ({
  width: stack.clientWidth,
  height: stack.clientHeight,
});

/** Where the engine is allowed to draw, in browser pixels within the window. */
function engineRectNow() {
  const size = sizeOfWindow();
  if (!bounded) return { left: 0, top: 0, width: size.width, height: size.height };
  // Bounded to the ground the run imaged. The hole in the sheet is where the
  // picture shows, so there is nothing to be gained by having the engine draw
  // anywhere else — and everywhere else is where it spends its requests asking
  // about pieces nobody has written. Clamped to the window because the imaged
  // patch can easily be larger than the screen.
  const square = toScreen(view, size, worldRect);
  const left = Math.max(0, Math.floor(square.left - MARGIN_CSS_PX));
  const top = Math.max(0, Math.floor(square.top - MARGIN_CSS_PX));
  const right = Math.min(size.width, Math.ceil(square.right + MARGIN_CSS_PX));
  const bottom = Math.min(size.height, Math.ceil(square.bottom + MARGIN_CSS_PX));
  return {
    left,
    top,
    width: Math.max(1, right - left),
    height: Math.max(1, bottom - top),
  };
}

// The view the operator is driving: the middle of the window in voxels, and how
// many voxels one browser pixel covers.
//
// It opens with the imaged square in the middle, taking up a little over half
// the window. That is not a matter of taste: the margin test has to be able to
// see the band of background all the way round the square as well as the sheet
// framing it, so the square must sit comfortably inside the window with room to
// spare, and it must stay there while the view is moved about.
let view = {
  cx: (imagedX0 + imagedX1) / 2,
  cy: (imagedY0 + imagedY1) / 2,
  scale: 1,
};
function fitTheSquareInTheWindow() {
  const size = sizeOfWindow();
  // A third of the window rather than most of it. The square has to stay wholly
  // inside the window with its band and its frame visible all the way round
  // *while the view is being moved about*, or the measurement stops being able
  // to see the very frames it most wants to see. There is then room to pan a
  // couple of hundred pixels and to zoom in a factor of two without any edge
  // leaving the window.
  const across = Math.min(size.width, size.height) * 0.35;
  view = {
    cx: (imagedX0 + imagedX1) / 2,
    cy: (imagedY0 + imagedY1) / 2,
    scale: Math.max(imagedX1 - imagedX0, imagedY1 - imagedY0) / across,
  };
}

const sheet = new OverlaySheet(sheetCanvas);
let viewer = null;
let control = null;
// How many times the sheet has been repainted, and what the sheet's own idea of
// the view was the last time it was. Both are here so that a measurement can
// tell "the sheet never moved" from "the sheet moved to the wrong place".
const counted = { sheetPaints: 0, enginePaints: 0, lastPresented: null };
// A note, kept only while a measurement asks for it, of what each of the
// engine's frames was asked to show, what it said it was showing, and what it
// really had on its surface. See `whereTheImageEdgeIs` for why all three are
// needed to answer the question this project is asking.
let watchingFrames = false;
const frameLog = [];

// How far the hole is deliberately put in the wrong place, in browser pixels.
// Nought in every real measurement; set only to show that the margin test can
// fail. See `window.probe.nudgeTheHole`.
let nudge = 0;

/** Repaint the sheet, using whichever view this arrangement says to use. */
function repaintSheet(holeView, operatorView) {
  const size = sizeOfWindow();
  const hole = holeFor(holeView, size, worldRect);
  if (nudge) {
    hole.left += nudge;
    hole.right += nudge;
  }
  // The operator's own rectangle: a tile outline, drawn exactly on the edge of
  // the imaged square because that is where a tile rectangle belongs. It is
  // given separately from the hole so that one of them can follow the engine
  // while the other follows the mouse — which is the compromise being weighed.
  const operatorRect = operatorView
    ? toScreen(operatorView, size, worldRect)
    : null;
  sheet.paint(hole, operatorRect);
  counted.sheetPaints += 1;
}

function fitTheEngineToItsPatch() {
  const rect = engineRectNow();
  engineHost.style.left = `${rect.left}px`;
  engineHost.style.top = `${rect.top}px`;
  engineHost.style.width = `${rect.width}px`;
  engineHost.style.height = `${rect.height}px`;
  return rect;
}

/**
 * What happens when the operator moves the view.
 *
 * The three arrangements differ *only* here, which is the point: the drawing,
 * the gestures and the measurement are all shared, so a difference in the
 * numbers is a difference in this decision and nothing else.
 */
function viewChanged(next) {
  view = next;
  if (arrangement === "one-canvas") {
    // One canvas: there is nothing to keep in step. The single redraw lays out
    // the image and the sheet from this one reading of the view.
    control.draw(view, sizeOfWindow());
    counted.sheetPaints += 1;
    return;
  }
  // The patch the engine is given is fitted on every change, not only when the
  // drawn region is being bounded. It has to be: the size is written onto the
  // element in plain pixels, so a window that has been resized leaves the
  // engine drawing at the old size until it is written again — and two surfaces
  // that disagree about how large the window is disagree about everything else
  // that follows from it.
  const rect = fitTheEngineToItsPatch();
  pushView(viewer, view, { engineRect: rect, windowSize: sizeOfWindow() });
  if (follow === "pointer") {
    // The naive arrangement: repaint the sheet straight away, from where the
    // mouse now is. The engine will catch up when it is ready, and the gap
    // between the two is what the margins measure.
    repaintSheet(view, null);
  } else if (follow === "compromise") {
    // The operator's own rectangle keeps up with the mouse; the hole waits for
    // the engine. Painted here as well as in the engine's own announcement, so
    // the rectangle really does move at the rate of the pointer.
    repaintSheet(counted.lastPresented || view, view);
  }
  // Under `presented` nothing is painted here at all. The sheet is repainted
  // only when the engine says it has finished a frame.
}

async function boot() {
  fitTheSquareInTheWindow();
  if (arrangement === "one-canvas") {
    control = startOneCanvas(oneCanvas, {
      worldRect,
      imageUrl: `/api/square.png?store=${storeName}`,
    });
    oneCanvas.style.display = "block";
    engineHost.style.display = "none";
    sheetCanvas.style.display = "none";
    window.probe.gestures = onlyPanAndZoom(oneCanvas, {
      getView: () => view,
      setView: viewChanged,
      sizeOf: sizeOfWindow,
    });
    control.draw(view, sizeOfWindow());
    window.probe.holeNow = () => control.holeNow();
  } else {
    oneCanvas.style.display = "none";
    fitTheEngineToItsPatch();
    viewer = await startEngine(engineHost, {
      // The address has to be a whole one, with the site's own name at the
      // front. The engine's readers resolve what they are given against nothing
      // in particular, so a path beginning with a slash is quietly never
      // fetched — the layer is built, no error is raised, and no request is ever
      // made. The viewer's own scene builder does the same thing for the same
      // reason.
      source: `${window.location.origin}/data/${storeName}.ome.zarr/|zarr2:`,
      shader: SHADER,
      flatView,
    });
    followTheEngine(viewer, () => {
      counted.enginePaints += 1;
      const presented = readPresentedView(viewer, {
        engineRect: engineRectNow(),
        windowSize: sizeOfWindow(),
      });
      counted.lastPresented = presented;
      if (watchingFrames) {
        // Where the view says the edge of the acquisition should be, and where
        // it really is on the surface the engine has just drawn. Kept together
        // so a measurement can see whether the two ever part company.
        const size = sizeOfWindow();
        const rect = engineRectNow();
        const said = toScreen(presented, size, worldRect).left - rect.left;
        const drawn = whereTheImageEdgeIs(viewer);
        frameLog.push({
          frame: counted.enginePaints,
          asked: toScreen(view, size, worldRect).left - rect.left,
          said,
          drawn: drawn ? drawn.at : null,
          density: window.devicePixelRatio || 1,
        });
      }
      if (follow === "presented") repaintSheet(presented, null);
      else if (follow === "compromise") repaintSheet(presented, view);
      // Under `pointer` the sheet is never repainted from here. That is the
      // arrangement being doubted, and leaving it alone is what exposes it.
    });
    window.probe.gestures = onlyPanAndZoom(sheetCanvas, {
      getView: () => view,
      setView: viewChanged,
      sizeOf: sizeOfWindow,
    });
    viewChanged(view);
    repaintSheet(view, follow === "compromise" ? view : null);
    window.probe.watchFrames = (on) => {
      watchingFrames = Boolean(on);
      if (on) frameLog.length = 0;
      return frameLog.length;
    };
    window.probe.frameLog = () => frameLog.slice();
    window.probe.holeNow = () => sheet.lastHole;
    window.probe.letGo = () => letGoOfDecodedPieces(viewer);
    // Two deliberate breakages, so that the checks can be shown to fail.
    window.probe.rotateOnPurpose = (degrees) => {
      rotateOnPurpose(viewer, degrees);
      viewChanged(view);
    };
    window.probe.nudgeTheHole = (pixels) => {
      // Move the hole a few pixels away from where it belongs. Nothing else
      // changes, so anything the margin test then reports is the test noticing
      // a disagreement that really is there — which is the only way to know it
      // would notice a real one.
      nudge = pixels;
      // Repainted here outright rather than by nudging the view, because in the
      // arrangement being tested the sheet is repainted only when the engine
      // finishes a frame — and a view that has not changed gives the engine no
      // reason to draw one.
      repaintSheet(counted.lastPresented || view, null);
    };
    window.probe.framesDrawn = () => framesDrawn(viewer);
    window.probe.presented = () => counted.lastPresented;
  }

  window.addEventListener("resize", () => {
    sheet.resize();
    if (arrangement === "one-canvas") control.draw(view, sizeOfWindow());
    else viewChanged(view);
  });

  window.probe.ready = true;
}

window.probe = {
  ready: false,
  arrangement,
  follow,
  bounded,
  flatView,
  margin: MARGIN_CSS_PX,
  worldRect,
  counted,
  view: () => ({ ...view }),
  setView: (next) => viewChanged({ ...view, ...next }),
  // Put the square back in the middle of the window at the magnification the
  // page opened with. Every measurement starts from here, so that the numbers
  // from one are comparable with the numbers from another.
  reset: () => {
    fitTheSquareInTheWindow();
    viewChanged(view);
  },
  size: sizeOfWindow,
  density: () => window.devicePixelRatio || 1,
  // What size the two surfaces really are, in real pixels. Two canvases have to
  // agree about how large a screen pixel is, and this is where a disagreement
  // would show.
  canvasSizes: () => ({
    sheet: { width: sheetCanvas.width, height: sheetCanvas.height,
             css: sheetCanvas.clientWidth },
    engine: (() => {
      const c = engineHost.querySelector("canvas");
      return c ? { width: c.width, height: c.height, css: c.clientWidth } : null;
    })(),
  }),
};

boot().catch((why) => {
  window.probe.failed = String(why && why.stack ? why.stack : why);
});
