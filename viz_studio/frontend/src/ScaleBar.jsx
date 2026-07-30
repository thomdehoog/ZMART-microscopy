import React from "react";
import { pickSiPrefix } from "neuroglancer/unstable/util/si_units.js";

/**
 * How long a bar is allowed to be, and the lengths it is allowed to read.
 *
 * A scale bar is only useful if the number on it is one you can reason with. So
 * rather than whatever length happens to fit, the bar is drawn at the nearest of
 * these — 1, 1.5, 2, 3, 5, 7.5 or 10 times a power of ten — which is how every
 * microscope's own scale bar behaves and why "2 µm" appears rather than "1.87 µm".
 */
const NICE_LENGTHS = [1.5, 2, 3, 5, 7.5, 10];
const TARGET_PIXELS = 120;

/**
 * Work out the bar to draw: how many pixels long, and what to call that length.
 *
 * ``perPixel`` is how much of the specimen one screen pixel covers, in whatever
 * unit the image declares. The returned length is the nearest sensible round
 * number to roughly ``TARGET_PIXELS`` across, with the unit scaled to suit — so
 * zooming in walks the bar down from millimetres to micrometres to nanometres
 * rather than showing an ever-smaller fraction.
 */
export function barFor(perPixel, unit) {
  if (!Number.isFinite(perPixel) || perPixel <= 0) return null;
  const wanted = TARGET_PIXELS * perPixel;
  const exponent = Math.floor(Math.log10(wanted));
  const power = 10 ** exponent;
  const significandWanted = wanted / power;
  let significand = 1;
  for (const allowed of NICE_LENGTHS) {
    if (Math.abs(allowed - significandWanted) < Math.abs(significand - significandWanted)) {
      significand = allowed;
    } else {
      break;
    }
  }
  const physical = significand * power;
  const prefix = pickSiPrefix(physical);
  return {
    pixels: Math.round(physical / perPixel),
    length: Number((significand * 10 ** (exponent - prefix.exponent)).toPrecision(3)),
    unit: `${prefix.prefix}${unit}`,
  };
}

/**
 * The volume panel currently on screen, if that is what is being shown.
 *
 * The flat view and the volume view are magnified by two entirely separate
 * zooms, so which panel is in front of the operator decides which of them the
 * bar has to read. Returns nothing when the flat view is showing, which is the
 * ordinary case.
 */
function volumePanelOnScreen(viewer) {
  for (const panel of viewer?.display?.panels || []) {
    // Told apart by what the panel holds rather than by its class name, because
    // the built page has those names shortened to a couple of letters and they
    // change from one build to the next.
    //
    // A flat panel *is* one slice through the specimen, and holds a single
    // `sliceView`. A volume panel draws the specimen in depth and can show
    // slices inside it, so it holds a collection — `sliceViews` — along with the
    // projection it is drawn through. That difference is a real one about what
    // each panel is, so it is a fair thing to recognise them by.
    if (!("sliceViews" in panel) || "sliceView" in panel) continue;
    // The zoom is taken from the viewer rather than from the panel, even though
    // the panel has one too. The panel's is a copy kept in step with the viewer's
    // a moment afterwards, so reading it here — while responding to the very
    // change that has not reached it yet — gives the previous value, and the bar
    // then states the size the specimen was before the operator zoomed. Only the
    // height is the panel's own to give.
    const zoom = viewer?.perspectiveNavigationState?.zoomFactor?.value;
    const height = panel.renderViewport?.logicalHeight;
    if (typeof zoom !== "number" || !Number.isFinite(height) || height <= 0) continue;
    return { zoom, height };
  }
  return null;
}

/**
 * Read how much of the specimen one screen pixel covers, right now.
 *
 * This follows Neuroglancer's own reasoning: each axis on screen has a scale (how
 * much of the specimen one voxel covers), the view has a zoom, and the two
 * together give the size of a pixel. Only axes measured in a length are of
 * interest — an image with a time axis has a scale for time too, and a bar
 * reading "100 s" says nothing about how big the specimen is.
 *
 * **The volume view counts its zoom differently, and getting that wrong states
 * the wrong size of specimen.** In the flat view the zoom is how much of the
 * specimen one screen pixel covers. In the volume view the same number counts
 * across the whole *height of the panel* instead, so it has to be divided by that
 * height before it means anything per pixel. Reading the flat view's zoom while
 * the volume was on screen made the bar over-state the specimen by about three
 * quarters on the demo volume — it read 50 µm where the truth was 28.5 — by a
 * factor that changed with the height of the window, and it did not move at all
 * when the operator magnified the volume. A scale bar that is quietly wrong is
 * worse than none, because a measurement gets read off it and written down.
 */
function pixelSize(viewer) {
  const navigation = viewer?.navigationState;
  const render = navigation?.displayDimensionRenderInfo?.value;
  if (!render) return null;
  const {
    displayRank,
    displayDimensionUnits,
    displayDimensionScales,
    canonicalVoxelFactors,
  } = render;
  // The same arithmetic the engine does for its own bar in a volume panel:
  // the perspective zoom divided by the panel's height. See
  // perspective_view/panel.js, which draws its bar from exactly this.
  const volume = volumePanelOnScreen(viewer);
  const zoom = volume
    ? volume.zoom / volume.height
    : navigation.zoomFactor?.value ?? navigation.relativeDisplayScales?.value;
  const effective = typeof zoom === "number" ? zoom : null;
  if (effective === null) return null;
  for (let i = 0; i < displayRank; i += 1) {
    // "m" is the only unit that measures distance across a specimen. Anything
    // else on screen (seconds, or an axis with no unit at all) is skipped.
    if (displayDimensionUnits[i] !== "m") continue;
    const perPixel = (displayDimensionScales[i] * effective) / canonicalVoxelFactors[i];
    if (Number.isFinite(perPixel) && perPixel > 0) return { perPixel, unit: "m" };
  }
  return null;
}

/**
 * A scale bar in the corner of the image, kept in step with the zoom.
 *
 * Neuroglancer draws its own along the bottom-left, one per axis — including one
 * for time, which reads as a length and is not one. This replaces them with a
 * single bar for distance, in the top-right corner, out of the way of the
 * specimen and of the sliders along the bottom.
 *
 * It has to follow the zoom, because a bar that does not is worse than none at
 * all: it would quietly state the wrong size. So it listens to the same
 * navigation signals the sliders do and recomputes whenever the view moves.
 */
export default function ScaleBar({ viewer }) {
  const [bar, setBar] = React.useState(null);

  React.useEffect(() => {
    if (!viewer) return undefined;
    const update = () => {
      const size = pixelSize(viewer);
      const next = size ? barFor(size.perPixel, size.unit) : null;
      setBar((current) =>
        current?.pixels === next?.pixels &&
        current?.length === next?.length &&
        current?.unit === next?.unit
          ? current
          : next,
      );
    };
    // Both views' movements are listened to, because either can be the one on
    // screen and the bar has to follow whichever it is. Magnifying the volume
    // moves only the perspective zoom, so without that one the bar would sit
    // unchanged while the specimen grew — stating a size that was true a moment
    // ago and is not any more.
    const stops = [
      viewer.navigationState.changed.add(update),
      viewer.navigationState.zoomFactor?.changed?.add(update),
      viewer.perspectiveNavigationState?.changed?.add(update),
      viewer.perspectiveNavigationState?.zoomFactor?.changed?.add(update),
      // Switching between the flat view and the volume swaps which zoom counts,
      // and changes no navigation state at all.
      viewer.layout?.changed?.add(update),
      // And once more whenever the engine draws. This is what catches the things
      // no single signal announces: switching to the volume builds a new panel,
      // and the panel's height is only known once it has been laid out and drawn,
      // so an answer worked out the instant the layout changed is worked out
      // before there is anything to measure. Recomputing is a few multiplications
      // and the bar is left alone when the answer has not moved, so this costs
      // nothing worth counting. It is also how the engine keeps its own bar
      // truthful.
      viewer.display?.updateStarted?.add(update),
    ];
    // The panel's height is part of the answer in the volume view, so a resized
    // window changes the bar even when nothing has been navigated.
    const onResize = () => update();
    window.addEventListener("resize", onResize);
    update();
    return () => {
      for (const stop of stops) if (stop) stop();
      window.removeEventListener("resize", onResize);
    };
  }, [viewer]);

  if (!bar) return null;
  return (
    <div style={styles.wrap} aria-label="scale bar">
      <span style={styles.text}>
        {bar.length} {bar.unit}
      </span>
      <div style={{ ...styles.bar, width: bar.pixels }} />
    </div>
  );
}

const styles = {
  wrap: {
    position: "absolute",
    top: 12,
    right: 14,
    zIndex: 10,
    display: "grid",
    justifyItems: "center",
    gap: 3,
    pointerEvents: "none",
  },
  text: {
    color: "#fff",
    font: "600 11px/1 system-ui, sans-serif",
    textShadow: "0 1px 3px rgba(0,0,0,.9)",
    fontVariantNumeric: "tabular-nums",
  },
  bar: {
    height: 3,
    background: "#fff",
    borderRadius: 1,
    boxShadow: "0 1px 3px rgba(0,0,0,.9)",
  },
};
