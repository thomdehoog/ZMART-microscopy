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
 * Read how much of the specimen one screen pixel covers, right now.
 *
 * This follows Neuroglancer's own reasoning: each axis on screen has a scale (how
 * much of the specimen one voxel covers), the view has a zoom, and the two
 * together give the size of a pixel. Only axes measured in a length are of
 * interest — an image with a time axis has a scale for time too, and a bar
 * reading "100 s" says nothing about how big the specimen is.
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
  const zoom = navigation.zoomFactor?.value ?? navigation.relativeDisplayScales?.value;
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
    const stopNavigation = viewer.navigationState.changed.add(update);
    const stopZoom = viewer.navigationState.zoomFactor?.changed?.add(update);
    update();
    return () => {
      stopNavigation();
      if (stopZoom) stopZoom();
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
