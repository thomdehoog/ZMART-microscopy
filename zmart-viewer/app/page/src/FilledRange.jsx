import React from "react";
import "./filled-range.css";

/**
 * A slider whose travelled part is painted blue.
 *
 * Chrome paints the stretch to the left of the handle in the accent colour on
 * its own. The WebKit engine inside the native window (the same one Safari
 * uses) does not: it tints only the handle and leaves the whole groove grey,
 * so the blue bar that says "this much" simply never appears there. The track
 * is therefore drawn by hand — one gradient, blue as far as the value has
 * travelled, grey for the rest — which looks the same in every engine.
 *
 * The painting lives in filled-range.css; this component's only job is to
 * tell the stylesheet how far along the value is (the --fill variable), and
 * to keep telling it as the value moves.
 */
export default function FilledRange({ value, min = 0, max = 100, upright = false, style, ...rest }) {
  const span = Number(max) - Number(min) || 1;
  const fill = Math.min(1, Math.max(0, (Number(value) - Number(min)) / span));
  return (
    <input
      type="range"
      className={upright ? "filled-range filled-range-upright" : "filled-range"}
      value={value}
      min={min}
      max={max}
      style={{ ...style, "--fill": `${fill * 100}%` }}
      {...rest}
    />
  );
}
