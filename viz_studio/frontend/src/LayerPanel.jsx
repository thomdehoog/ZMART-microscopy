import React from "react";

import FilledRange from "./FilledRange.jsx";
import { restingWindow } from "./scene.js";

// A small, deliberately limited palette. Green and magenta lead because that is
// the pairing that reads best on a dark background and stays legible to a
// colour-blind viewer, unlike red/green.
export // One block for every small control in the display settings: the boxes an
// operator types into and the buttons beside them. Named rather than repeated
// so the row cannot drift apart the next time one of them is restyled.
const ROW_ITEM = 54;
const ROW_HEIGHT = 24;

const PALETTE = [
  { name: "green", rgb: [0.0, 1.0, 0.4] },
  { name: "magenta", rgb: [1.0, 0.2, 1.0] },
  { name: "cyan", rgb: [0.2, 0.8, 1.0] },
  { name: "amber", rgb: [1.0, 0.75, 0.1] },
  { name: "blue", rgb: [0.3, 0.45, 1.0] },
  { name: "red", rgb: [1.0, 0.15, 0.15] },
  { name: "grey", rgb: null },
];

// A colour as the browser's own picker spells it, and back again. The picker
// hands over "#rrggbb"; everything else here keeps colours as three fractions,
// which is what the shader is given.
const hexOf = (rgb) =>
  rgb
    ? `#${rgb.map((v) => Math.round(Math.min(1, Math.max(0, v)) * 255)
        .toString(16).padStart(2, "0")).join("")}`
    : "#ffffff";
const rgbOf = (hex) => {
  const value = parseInt(hex.replace("#", ""), 16);
  return [(value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255];
};

// What each colour map roughly looks like, as a little gradient. Drawn beside
// its name in the chooser and on the channel's row, so a map is chosen and
// recognised by eye. It used to be explained in words instead -- "magma"
// means nothing until you have seen one -- and showing the thing itself says
// it better than a sentence could.
const LUT_GRADIENTS = {
  viridis: "linear-gradient(90deg, #440154, #21918c, #fde725)",
  magma: "linear-gradient(90deg, #000004, #b73779, #fcfdbf)",
  fire: "linear-gradient(90deg, #000000, #e63b1f, #fff3c4)",
  ice: "linear-gradient(90deg, #000000, #3a6fd8, #ffffff)",
};

// The palette entry a stored rgb corresponds to: which flat colour the
// colormap chooser currently holds, or nothing at all when
// a colour was picked by hand and matches no named entry.
const paletteNameOf = (rgb) =>
  (PALETTE.find((entry) => css(entry.rgb) === css(rgb)) || { name: null }).name;

const css = (rgb) =>
  rgb ? `rgb(${rgb.map((v) => Math.round(v * 255)).join(",")})` : "#d8dee6";

// Log used to warp the brightness axis itself, which moved every bar and
// every handle sideways; it lifts the histogram's counts now instead, and the
// arithmetic for a warped axis went with it.

// -- the pieces the panel is drawn from ---------------------------------------
//
// A histogram, an eye, and the arithmetic that decides how far the contrast
// handles may travel. They are here rather than inside the panel below so that
// each can be read on its own, and because each of them answers a question a
// microscopist actually asks rather than a question about the interface.

/**
 * How far the black and white handles are allowed to travel.
 *
 * From the dimmest pixel in the channel to the brightest, and no further. An
 * axis drawn to what the camera COULD have written instead puts a real
 * specimen in the first few per cent of the track -- a few hundred counts of
 * background inside sixty-five thousand -- and leaves the rest as headroom
 * nothing occupies, so a whole slider becomes two pixels of useful travel.
 * That was tried both ways within a day: measured-span, then the camera's
 * range with a logarithmic axis to make it usable, and now the data again
 * with the axis SAID rather than guessed. Which part of it is drawn is the
 * operator's to set, in the two boxes beneath the histogram, and ``shown``
 * carries their answer when they have given one.
 *
 * The window in use is always included, so a window wider than the pixels --
 * one the run itself declared, say -- widens the track rather than leaving a
 * handle stranded off the end of it.
 *
 * And where a run declares the range its numbers live in, that is as far as
 * the boxes may be pushed: a twelve-bit camera cannot produce 5000, so an
 * axis drawn to it would be room that can never hold anything.
 */
// Where the window's two edges sit along the histogram, as fractions of its
// width. The stretch of brightness being shown takes the middle of the
// picture and leaves a seventh of it beyond each edge -- enough to see what
// is being clipped at both ends, and enough of a reference to adjust
// against. The operator asked for exactly this (2026-08-22): "the blue bars
// should be at fifteen and eighty five per cent along the histogram, so
// that's important to know for how to adjust the values."
const WINDOW_SITS_FROM = 0.15;

/**
 * The stretch of brightness to draw so that a window sits across the middle.
 *
 * Given the window a channel was handed -- the one its file declared when it
 * opened, or the one Auto just measured -- this says how far the picture
 * beneath it should reach on either side. The answer is only ever taken when
 * a window is GIVEN, never while a handle is being dragged: an axis that
 * moved with the handle would mean the operator could never see what their
 * drag had done.
 *
 * The bars land at fifteen and eighty five per cent exactly, whatever the
 * window's numbers are. For a window sitting close to zero that means the
 * axis starts below zero — room no pixel can occupy, kept anyway because a
 * pair of bars that always sits in the same two places is worth more than a
 * left edge that never goes negative. The axis was clamped at zero for a
 * day, which pinned the min bar to the left edge for exactly the dim
 * channels Auto is most used on; the operator asked for the exact framing
 * instead (2026-08-23).
 */
function frameTheWindow(window_) {
  if (!window_ || !(window_.high > window_.low)) return null;
  const across = (window_.high - window_.low) / (1 - 2 * WINDOW_SITS_FROM);
  const beyond = across * WINDOW_SITS_FROM;
  return {
    low: window_.low - beyond,
    high: window_.high + beyond,
  };
}

function contrastRange(layer, window_, shown = null) {
  const measured = layer.histogram;
  let min = 0;
  let max = 65535;
  if (measured && Number.isFinite(measured.low) && measured.high > measured.low) {
    min = Math.floor(measured.low);
    max = Math.ceil(measured.high);
  }
  if (shown && Number.isFinite(shown.low) && shown.high > shown.low) {
    // Taken as given, even where it runs past what the run declared or below
    // zero: the framing promises the window's bars a fixed pair of places on
    // the picture, and an axis trimmed back to the declared range would move
    // them (see frameTheWindow).
    return { min: shown.low, max: shown.high };
  }
  return {
    min: Math.min(min, Math.floor(window_.low)),
    max: Math.max(max, Math.ceil(window_.high), min + 1),
  };
}

/**
 * The spread of brightness in a channel, with the chosen window marked on it.
 *
 * This is the one picture in the panel that answers a question a microscopist
 * actually asks: is this channel saturating, or is it sitting on background?
 * The bars between the window's two marks are drawn at full light — that is
 * the brightness the display ramp is spent on — and the bars outside them are
 * dimmed: everything to the left saturates to black, everything to the right
 * to white.
 *
 * The two bars ARE the window, and only they move it: take hold of one — the
 * pointer has to be over it, a few pixels of grace either side — and pull,
 * and that edge of the window follows, the same window the MIN and MAX
 * sliders move, so the two controls can never disagree. A bar can never be
 * pulled past the image's own range: there are no pixels out there for a
 * black or white point to say anything about.
 *
 * Everywhere that is not a bar, the pointer works the AXIS instead — the
 * stretch of brightness being drawn, never the picture itself. Dragging pans
 * it; the wheel zooms it toward the pointer, out as far as the whole range
 * framed the usual way and no further. Auto puts the default framing back.
 * (All of this is the operator's design, 2026-08-23.)
 */
function Histogram({ layer, window_, color, onWindow, onAxis = null,
                     range = null, scale = "linear", axis = null,
                     steady = null }) {
  const dragging = React.useRef(null);
  const [overBar, setOverBar] = React.useState(false);
  const box = React.useRef(null);
  // The freshest zoom arithmetic, held where the listener below can reach
  // it. The listener itself is attached once per mount; the maths it calls
  // is replaced on every render, so it always reads today's axis.
  const zooming = React.useRef(null);
  const counts = layer.histogram?.counts;
  // The wheel zooms the axis, so the page must not scroll with it. React's
  // own wheel listener is registered as "passive" — one that has promised
  // never to stop the scroll — so the listener is attached by hand instead,
  // with that promise withheld.
  React.useEffect(() => {
    const target = box.current;
    if (!target) return undefined;
    const wheel = (event) => zooming.current?.(event);
    target.addEventListener("wheel", wheel, { passive: false });
    return () => target.removeEventListener("wheel", wheel);
  }, [Boolean(counts?.length)]);
  if (!counts?.length) return null;
  const measured = layer.histogram;
  // The box spans the AXIS -- the camera's whole range when the store's
  // numbers have one -- and the bars sit at the brightness they were
  // measured at inside it, so the empty stretch up to saturation is honest
  // headroom on show. Marks, bars and the pointer all share one mapping, or
  // they would sit under the wrong values; on the log axis it warps them
  // together.
  const low = axis ? axis.min : measured.low;
  const span = (axis ? axis.max - axis.min : measured.high - measured.low) || 1;
  // Brightness runs along the box evenly, always. It once ran logarithmically
  // when Log was on, which moved every bar sideways and dragged the handles
  // with them, so a window an operator had set stopped sitting where they put
  // it. Log now lifts the bars instead (see their height below), which is the
  // thing that actually needs it: fluorescence piles almost every pixel into
  // the dim bins and leaves the interesting tail one pixel high.
  const at = (value) =>
    Math.min(Math.max((value - low) / span, 0), 1) * counts.length;
  const left = at(window_.low);
  const right = at(window_.high);

  // Which bin each count belongs to, in the brightness the server counted.
  const bins = measured.high - measured.low || 1;
  const brightnessOf = (index) =>
    measured.low + ((index + 0.5) * bins) / counts.length;
  // The tallest bar is measured over the bins inside the RESTING frame --
  // the one Auto or a fresh window lays out -- not over every bin the
  // server counted, and not over whatever stretch a pan or zoom happens to
  // be showing. The first would let a background peak outside the frame
  // squash the specimen to a line one pixel high; the second made the bars
  // breathe up and down while the operator panned, a scale that changed
  // under the eye measuring against it (2026-08-23). Anchored to the
  // frame, the heights hold still until the framing itself is asked to
  // change.
  const anchor = steady || { min: low, max: low + span };
  const drawn = counts.filter(
    (_count, index) => brightnessOf(index) >= anchor.min
      && brightnessOf(index) <= anchor.max);
  const peak = Math.max(...(drawn.length ? drawn : counts), 1);

  // The image's own range of values, which the window may never leave: a
  // black or white point beyond the pixels would say something about
  // brightness that does not exist. The axis is allowed further — that is
  // what keeps the bars at their fifteen and eighty-five per cent — but
  // only as far as the whole range framed the usual way.
  const bounds = range && Number.isFinite(range.high)
    ? { low: range.low ?? 0, high: range.high }
    : { low: Math.min(0, measured.low), high: Math.max(65535, measured.high) };
  const widest = frameTheWindow(bounds);
  const withinImage = (value) =>
    Math.min(Math.max(value, bounds.low), bounds.high);
  const holdTheAxis = (next) => {
    const width = Math.min(
      Math.max(next.high - next.low, (bounds.high - bounds.low) / 256),
      widest.high - widest.low,
    );
    const from = Math.min(Math.max(next.low, widest.low), widest.high - width);
    return { low: from, high: from + width };
  };

  // Where a pointer event sits on the brightness axis.
  const valueUnder = (event) => {
    const face = event.currentTarget.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - face.left) / face.width));
    return low + fraction * span;
  };
  // Which bar the pointer is over, if either: within a few screen pixels,
  // so the target is the drawn line and not "the nearer half of the box".
  const barUnder = (event) => {
    const face = event.currentTarget.getBoundingClientRect();
    const grace = (6 / face.width) * span;
    if (Math.abs(valueUnder(event) - window_.low) <= grace) return "low";
    if (Math.abs(valueUnder(event) - window_.high) <= grace) return "high";
    return null;
  };
  const takeHold = (event) => {
    const bar = onWindow ? barUnder(event) : null;
    if (bar) {
      dragging.current = { bar };
    } else if (onAxis) {
      // Not a bar: the drag pans the axis. Everything is measured from
      // where the drag began, so the ground cannot creep under a held
      // pointer as the axis it is measured against moves.
      dragging.current = { panFrom: event.clientX, axisWas: { low, span } };
    } else {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    follow(event);
  };
  const follow = (event) => {
    const held = dragging.current;
    if (!held) {
      // A resting pointer only updates what the cursor face says it would
      // grab, so the bars read as handles before they are ever touched.
      const bar = onWindow ? barUnder(event) : null;
      if (Boolean(bar) !== overBar) setOverBar(Boolean(bar));
      return;
    }
    if (held.bar) {
      const value = withinImage(valueUnder(event));
      // The floor may not cross the ceiling: a window at least one count
      // wide always remains, so the picture can never invert.
      if (held.bar === "low") {
        onWindow({ low: Math.min(value, window_.high - 1), high: window_.high });
      } else {
        onWindow({ low: window_.low, high: Math.max(value, window_.low + 1) });
      }
      return;
    }
    const face = event.currentTarget.getBoundingClientRect();
    const moved = ((held.panFrom - event.clientX) / face.width) * held.axisWas.span;
    onAxis(holdTheAxis({
      low: held.axisWas.low + moved,
      high: held.axisWas.low + held.axisWas.span + moved,
    }));
  };
  const letGo = () => {
    dragging.current = null;
  };
  // The wheel zooms the axis toward the pointer: the brightness under the
  // cursor stays under the cursor, everything else breathes in or out
  // around it. The picture itself is untouched — this moves only what
  // stretch of brightness is DRAWN.
  zooming.current = onAxis
    ? (event) => {
      event.preventDefault();
      const face = box.current.getBoundingClientRect();
      const fraction = Math.min(1, Math.max(0, (event.clientX - face.left) / face.width));
      const anchor = low + fraction * span;
      const factor = Math.exp(event.deltaY * 0.002);
      onAxis(holdTheAxis({
        low: anchor - (anchor - low) * factor,
        high: anchor + (low + span - anchor) * factor,
      }));
    }
    : null;

  return (
    <svg
      ref={box}
      viewBox={`0 0 ${counts.length} 24`}
      preserveAspectRatio="none"
      style={{ ...styles.histogram,
               cursor: overBar ? "ew-resize" : onAxis ? "grab" : "default" }}
      role="img"
      aria-label={`histogram ${layer.name}`}
      onPointerDown={takeHold}
      onPointerMove={follow}
      onPointerUp={letGo}
      onPointerCancel={letGo}
      onPointerLeave={() => overBar && setOverBar(false)}
      // A double click puts the default framing back after a pan or a zoom
      // — the same resting layout the panel opened with. It does NOT press
      // Auto: nothing is measured and the window does not move (the
      // operator's ask, 2026-08-23).
      onDoubleClick={() => onAxis?.(null)}
    >
      {/* Bars inside the window at full light -- near-white, so the stretch
          the display ramp is spent on is unmistakable -- and bars outside it
          dimmed to a quarter: that brightness saturates to black or white.
          One glance says which pixels are being looked at. */}
      {counts.map((count, index) => {
        // How many pixels this bin holds, against the fullest bin. On the
        // plain scale that is the honest proportion; on the log scale the
        // quiet bins are lifted until they can be seen at all, which is the
        // whole reason a microscopist asks for it.
        const share = scale === "log"
          ? Math.log1p(count) / Math.log1p(peak)
          : count / peak;
        const height = share * 22;
        // The bins live in MEASURED brightness -- that is what the server
        // counted -- and only their places are mapped through the axis, which
        // may run past them, or stop short of them.
        const shown = brightnessOf(index) >= window_.low
          && brightnessOf(index) <= window_.high;
        const starts = at(measured.low + (index * bins) / counts.length);
        const ends = at(measured.low + ((index + 1) * bins) / counts.length);
        return (
          <rect
            key={index}
            x={starts}
            y={24 - height}
            width={ends - starts}
            height={height}
            fill="currentColor"
            opacity={shown ? 1 : 0.25}
          />
        );
      })}
      {[left, right].map((x, edge) =>
        x > 0 && x < counts.length ? (
          <rect key={edge} x={x} y="0" width="0.8" height="24" fill="var(--accent)" />
        ) : null,
      )}
    </svg>
  );
}

/**
 * The number beside a slider, as a box that can be typed into.
 *
 * While untouched it simply shows the slider's value. Start typing and it
 * holds your draft until Enter or leaving the box commits it; a draft that
 * is not a number is quietly dropped and the real value comes back. So box
 * and slider always describe the same setting, whichever one moved last.
 */
function ValueBox({ value, onCommit, label, suffix = "", align = "right" }) {
  const [draft, setDraft] = React.useState(null);
  const commit = () => {
    if (draft !== null) {
      const asked = Number(draft.replace(suffix, ""));
      if (Number.isFinite(asked)) onCommit(asked);
    }
    setDraft(null);
  };
  return (
    <input
      type="text"
      inputMode="numeric"
      value={draft ?? `${value}${suffix}`}
      onChange={(event) => setDraft(event.target.value)}
      onFocus={(event) => event.target.select()}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
      }}
      aria-label={label}
      style={{ ...styles.valueBox, textAlign: align }}
    />
  );
}

/** A drawn eye, open or crossed out — the show/hide idea every biologist knows. */
function Eye({ open }) {
  return (
    <svg viewBox="0 0 16 16" style={styles.eyeGlyph} aria-hidden="true">
      <path
        d="M1 8s2.6-4.2 7-4.2S15 8 15 8s-2.6 4.2-7 4.2S1 8 1 8z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <circle cx="8" cy="8" r="1.9" fill="currentColor" />
      {!open && <path d="M2.5 13.5L13.5 2.5" stroke="currentColor" strokeWidth="1.3" />}
    </svg>
  );
}


// -- the controls, and the list they act on -----------------------------------

/**
 * The one block of controls, acting on whichever channel is picked out in the list.
 *
 * There is a single copy of this rather than one per channel. That is partly for
 * room — with sliders on every row, three channels filled a tall screen — and
 * partly because it matches how the work goes: you look at one channel, set it up,
 * then move to the next. It is the arrangement napari uses, and anyone who has
 * used napari will already know where to look.
 */
/**
 * How a ray through the volume becomes a colour.
 *
 * Only shown in the volume view, because it means nothing in a flat one. The
 * default is a projection rather than accumulation: on sparse specimen -- which
 * is what a fluorescence run is -- accumulating every voxel a ray passes gives a
 * milky picture with almost no contrast, and a projection needs no transparency
 * tuned before anything can be seen.
 */
function VolumeMode({ volumeMode, onVolumeMode, gain, onGain,
                     attenuation, onAttenuation,
                     depthSamples, onDepthSamples,
                     displayScales, onDisplayScales }) {
  const accumulating = volumeMode === "on";
  return (
    <>
    <label style={styles.control}>
      <span
        style={styles.controlLabel}
        title="How the voxels along each line of sight are combined into one pixel"
      >
        projection
      </span>
      <select
        value={volumeMode}
        onChange={(event) => onVolumeMode?.(event.target.value)}
        aria-label="volume projection"
        title="Brightest keeps the brightest voxel along each ray -- a maximum-intensity projection (MIP), which is how most fluorescence is looked at. Accumulated adds every voxel up instead."
        // The row has no value readout, so the dropdown may take the value
        // column too -- its option names are long.
        style={{ ...styles.select, gridColumn: "2 / -1" }}
      >
        <option value="max">brightest along the ray</option>
        <option value="on">accumulated along the ray</option>
        <option value="min">darkest along the ray</option>
      </select>
    </label>
    {/* Gain belongs to accumulation and to nothing else. The engine swaps the
        whole colour-emitting function out for a projection and the replacement
        never mentions its gain, so the slider would sit here looking alive and
        do nothing -- which is the fault this viewer has now produced three
        times in one day. Shown disabled rather than hidden, so that somebody
        looking for it finds it and is told why. */}
    <label style={{ ...styles.control, opacity: accumulating ? 1 : 0.45 }}>
      <span
        style={styles.controlLabel}
        title={accumulating
          ? "Brighten a picture that piles up along the ray and washes out"
          : "Only for the accumulated projection; there is nothing to accumulate in a brightest or darkest one"}
      >
        gain
      </span>
      <FilledRange
        min="-3" max="3" step="0.1" value={gain}
        disabled={!accumulating}
        onChange={(event) => onGain?.(Number(event.target.value))}
        aria-label="volume gain"
        title={accumulating
          ? "Accumulating along a ray washes a picture out; this brightens it back"
          : "Only for the accumulated projection"}
        style={styles.range}
      />
      <output style={styles.value}>{accumulating ? gain.toFixed(1) : "n/a"}</output>
    </label>
    {/* Doubling steps along the ray, because the engine compares a level's
        voxel against the cube of one step -- so the useful settings are spread
        over orders of magnitude, not evenly. The readout is the real number,
        since that is what the launch flag takes. */}
    <label style={styles.control}>
      <span style={styles.controlLabel} title="How many steps a ray takes through the volume. More is sharper and slower">
        detail
      </span>
      <FilledRange
        min="6" max="16" step="1"
        value={Math.round(Math.log2(depthSamples))}
        onChange={(event) => onDepthSamples?.(2 ** Number(event.target.value))}
        aria-label="volume detail"
        title="Too few steps and the volume stays on its coarsest copy however far you zoom in; too many and it will not keep up"
        style={styles.range}
      />
      <output style={styles.value}>{depthSamples}</output>
    </label>
    <label style={styles.control}>
      <span style={styles.controlLabel} title="Fade the far side of the specimen, so front reads in front of back">
        depth fade
      </span>
      <FilledRange
        min="0" max="8" step="0.1" value={attenuation}
        onChange={(event) => onAttenuation?.(Number(event.target.value))}
        aria-label="volume depth fade"
        title="Weighs each voxel by how far along the line of sight it is. Nought is no fading"
        style={styles.range}
      />
      <output style={styles.value}>{attenuation.toFixed(1)}</output>
    </label>
    {/* Stretching the picture along an axis. It lives here because squashing
        or exaggerating depth on anisotropic data is what it is for, and depth
        is seen in this view. The factors change how the specimen is DRAWN and
        nothing about what it claims to be, and they keep acting in the flat
        view too -- the warning beside the display settings says so whenever
        the axes on screen disagree. */}
    <div style={styles.control}>
      <span style={styles.controlLabel} title="Draw the specimen stretched along an axis. Does not change the data">
        stretch
      </span>
      {/* The three inputs take the slider column AND the value column, so
          their right edge lines up with the numbers above them. */}
      <div style={{ display: "flex", gap: 6, gridColumn: "2 / -1" }}>
        {["x", "y", "z"].map((axis) => (
          <label key={axis} style={{ display: "flex", alignItems: "center", gap: 3, flex: 1 }}>
            <span style={{ ...styles.controlLabel, minWidth: 0 }}>{axis}</span>
            <input
              type="number" min="0.05" max="20" step="0.05"
              value={displayScales[axis]}
              onChange={(event) => {
                const asked = Number(event.target.value);
                if (asked > 0) onDisplayScales?.({ ...displayScales, [axis]: asked });
              }}
              aria-label={`stretch ${axis}`}
              title={`How many times to stretch the picture along ${axis}. 1 is as the run declared it`}
              style={{ ...styles.select, width: "100%", minWidth: 34 }}
            />
          </label>
        ))}
      </div>
    </div>
    </>
  );
}


/**
 * The axes the operator can actually see, which is what decides whether one
 * scale bar can be true.
 *
 * A bar states one distance per screen pixel, so it stays honest only while every
 * axis on screen is drawn at the same stretch. Which axes those are is a property
 * of the *view* rather than of the data, and that is the whole reason this cannot
 * be decided from the stretch factors alone.
 *
 * A single plane shows x and y and leaves depth off screen entirely, so
 * stretching z there — the ordinary thing to do with anisotropic data — cannot
 * make the bar wrong, and warning about it would cry wolf on the common case.
 * Turning the volume on puts z on screen beside them and the same stretch now
 * does make it wrong: measured on the demo volume with z quadrupled, ten
 * micrometres covers about 201 screen pixels along z against 50 along x, so a bar
 * reading either one is off by four for the other. The operator changed nothing
 * but what they were looking at.
 */
function axesOnScreen(mode) {
  return mode === "volume" ? ["x", "y", "z"] : ["x", "y"];
}

/**
 * Whether the axes on screen are drawn at stretches that disagree.
 *
 * Compared against each other rather than against 1, because stretching every
 * axis alike is a zoom: it changes how large the specimen is drawn and not its
 * proportions, so one bar still describes it perfectly. Only a difference between
 * two axes that are both on screen shears the picture, and then it is 20 µm wide
 * and 30 µm tall per the same bar. Fiji and napari avoid this by not offering the
 * control at all. We offer it and say so.
 *
 * The bar itself follows a stretch rather than ignoring one — it divides by the
 * engine's `canonicalVoxelFactors`, which are computed from these very factors —
 * so this is a warning that no single number can be right, not that the bar has
 * been left stale.
 */
function stretchedUnevenly(displayScales, mode) {
  const onScreen = axesOnScreen(mode).map((axis) => displayScales[axis]);
  return onScreen.some((factor) => factor !== onScreen[0]);
}

/**
 * The square a channel is painted in, which is also how the colour is chosen.
 *
 * Press it and a list opens showing every choice as it actually looks: a
 * block for a flat colour, and the whole run of colours for a map. That is
 * the point of drawing them. A plain dropdown can only offer words, and the
 * word "magma" tells a microscopist meeting it nothing at all -- the version
 * before this one had to spell out "(black -> purple -> cream)" beside every
 * map and still left an operator picking by trial.
 *
 * "Custom" heads the list and opens the browser's own colour picker, because
 * an operator who wants a particular colour is not going to find it among
 * the named ones.
 *
 * It is a list of buttons rather than a select because a select cannot draw
 * anything but text. That costs the keyboard nothing: each entry is a real
 * button, so tabbing walks them and Enter picks, and Escape closes the list.
 */
function ColourChooser({ layer, entry, names, onPick, named = null }) {
  // Where the list is drawn, in window coordinates rather than inside the
  // square. The channel list it may be opened from scrolls, and anything
  // drawn inside a box that scrolls is cut off at that box's edge -- opened
  // from a row, the list showed two of its twelve entries (seen 2026-08-22).
  // Placed against the window instead, it escapes that box entirely.
  const [openAt, setOpenAt] = React.useState(null);
  const open = openAt !== null;
  const setOpen = (want) => setOpenAt(want ? openAt : null);
  const openBeside = (square) => {
    const box = square.getBoundingClientRect();
    // Above the square where there is no room beneath it, so the list is
    // never half off the bottom of the screen.
    const room = window.innerHeight - box.bottom;
    setOpenAt(room < LIST_TALL_AT_MOST + 8
      ? { left: box.left, bottom: window.innerHeight - box.top + 2 }
      : { left: box.left, top: box.bottom + 2 });
  };
  const choices = [
    ...PALETTE.map((one) => ({
      key: `flat:${one.name}`,
      name: one.name,
      rgb: one.rgb,
      lut: null,
      look: css(one.rgb),
    })),
    ...names.map((name) => ({
      key: name,
      name,
      lut: name,
      look: LUT_GRADIENTS[name] || "#d8dee6",
    })),
  ];
  const chosen = entry.lut
    ? choices.find((one) => one.lut === entry.lut)
    : choices.find((one) => !one.lut && css(one.rgb) === css(entry.color));
  const painted = (entry.lut && LUT_GRADIENTS[entry.lut]) || css(entry.color);
  // A colour picked by hand belongs to no entry in the list, and saying the
  // nearest name would tell the operator they chose something they did not.
  const naming = chosen ? chosen.name : "picked";
  // What to call the channel in the labels a screen reader reads out.
  // The row says its own name; the settings block says "the chosen
  // channel", because the name is written beside it already -- and
  // because a label that CONTAINS another label makes the two
  // impossible to tell apart (found by a browser gate, 2026-08-22).
  const about = named || layer.name;
  // Closed as soon as the focus leaves the whole chooser. Asking about the
  // chooser rather than about the button pressed means pressing an entry does
  // not close the list out from under the press.
  const closeOnLeaving = (event) => {
    if (!event.currentTarget.closest("[data-chooser]")
      ?.contains(event.relatedTarget)) {
      setOpen(false);
    }
  };
  return (
    <span style={styles.chooser} data-chooser="">
      {/* The colour itself is the control: press the square a channel is
          painted in and the list of everything it could be painted in opens
          under it. There was a row of its own for this, labelled COLORMAP,
          with the square beside a named dropdown; one thing to press, where
          the operator is already looking, says the same in less room. */}
      <button
        type="button"
        onClick={(event) => (open ? setOpenAt(null) : openBeside(event.currentTarget))}
        onBlur={closeOnLeaving}
        aria-label={`colour ${about}`}
        aria-expanded={open}
        title={`Painted ${naming}. Press to choose another colour`}
        style={{ ...styles.swatch, ...styles.swatchButton, background: painted }}
      />
      {open && (
        <span role="listbox" style={{ ...styles.chooserList, ...openAt }}>
          {/* Any colour at all, first in the list, because an operator who
              wants one is not looking for it among the named ones. The
              browser's own picker opens on it -- the one they already know. */}
          <label
            style={{ ...styles.chooserEntry, ...styles.chooserCustom }}
            title="Choose any colour"
          >
            {/* Left empty on purpose: this entry stands for a colour not
                chosen yet, so showing the current one would say the channel
                is already painted it. An empty well is the invitation. */}
            <span style={{ ...styles.chooserSwatch, background: "transparent" }} />
            custom
            <input
              type="color"
              value={hexOf(entry.color)}
              onBlur={closeOnLeaving}
              onChange={(event) => {
                onPick({ rgb: rgbOf(event.target.value), lut: null });
                setOpen(false);
              }}
              aria-label={`choose a colour for ${about}`}
              style={styles.hiddenPicker}
            />
          </label>
          {choices.map((choice) => (
            <button
              key={choice.key}
              type="button"
              role="option"
              aria-selected={chosen?.key === choice.key}
              aria-label={`${choice.name} for ${about}`}
              onBlur={closeOnLeaving}
              onClick={() => {
                onPick(choice);
                setOpen(false);
              }}
              style={{
                ...styles.chooserEntry,
                ...(chosen?.key === choice.key ? styles.chooserEntryOn : null),
              }}
            >
              <span style={{ ...styles.chooserSwatch, background: choice.look }} />
              {choice.name}
            </button>
          ))}
        </span>
      )}
    </span>
  );
}


function ChannelControls({ layer, index, entry, mode, lookupTables, onWindow, onOpacity, onToggle,
                          onColor, onLut, onMeasureHere = null,
                          displayScales = { x: 1, y: 1, z: 1 } }) {
  // The brightness of the part of the picture on screen, once Auto has asked
  // for it. Kept here rather than pushed into the layer because it describes
  // where the operator was looking at one moment, not the channel: pan away
  // and the old reading is no longer about anything.
  const [here, setHere] = React.useState(null);
  // The same resting window the canvas draws with (see scene.js): the run's
  // recorded window, or the measured one when the run said nothing.
  const window_ = entry.window || restingWindow(layer, mode === "volume")
    || { low: 0, high: 65535 };
  // Which part of the brightness axis is drawn. Nothing said means the data's
  // own span; the two boxes under the histogram are where an operator says
  // otherwise, and their answer is kept per channel for as long as the panel
  // is showing it.
  const [shown, setShown] = React.useState(null);
  // The stretch of brightness the picture draws when the operator has not
  // said otherwise: settled from the window this channel was handed, and
  // settled again whenever Auto hands it another. Held in between, so that
  // dragging a handle moves the handle rather than the ground under it.
  const [framed, setFramed] = React.useState(() => frameTheWindow(window_));
  const frameAround = (given) => {
    const around = frameTheWindow(given);
    if (!around) return;
    setShown(null);
    setFramed(around);
  };
  // The channel as measured: the same layer, but wearing the reading Auto
  // last took where the operator was looking. Substituted whole so that the
  // axis, the bars and the Auto light all describe one measurement instead
  // of disagreeing about which picture they are talking about.
  const seen = here ? { ...layer, histogram: here } : layer;
  const { min, max } = contrastRange(seen, window_, shown || framed);
  // The two handles are kept at least one count apart. A window of no width makes
  // every value in the image land on the same shade, so the picture goes flat and
  // it is not obvious why. And neither handle may leave the image's own range
  // of values — a black or white point beyond the pixels would describe
  // brightness that does not exist (the operator's rule, 2026-08-23). This is
  // the one gate every mover of the window passes: the sliders, the typed
  // boxes and the histogram's bars all land here.
  const imageRange = layer.range && Number.isFinite(layer.range.high)
    ? { low: layer.range.low ?? 0, high: layer.range.high }
    : { low: 0, high: 65535 };
  const withinImage = (value) =>
    Math.min(Math.max(value, imageRange.low), imageRange.high);
  const setLow = (low) =>
    onWindow(index, { low: Math.min(withinImage(low), window_.high - 1),
                      high: window_.high });
  const setHigh = (high) =>
    onWindow(index, { low: window_.low,
                      high: Math.max(withinImage(high), window_.low + 1) });

  // There used to be BRIGHTNESS and CONTRAST sliders below MIN and MAX --
  // the same window re-described, the way Fiji presents it. They were removed
  // (2026-08-18) once the window became directly grabbable in the histogram:
  // MIN and MAX are the two saturation points, everything below the first is
  // black and everything above the second is white, and a second pair of
  // handles moving the very same window read as controls that do something
  // else when they do not.
  const isMask = layer.kind === "segmentation";

  // Whether the histogram's counts are drawn plainly or lifted. It starts
  // plain: with the brightness axis now the data's own span, the picture is
  // readable as it stands, and Log is there for the channel whose dim bins
  // dwarf everything else. It was briefly turned on by itself for such
  // channels, back when the axis ran to the camera's whole range and needed
  // the help.
  const [scale, setScale] = React.useState("linear");

  // The measurement Auto falls back on: the whole picture's, taken once when
  // the run was opened. It is what the button can still offer in the moment
  // before the view can be asked -- an unlaid-out panel, a volume turned in
  // three dimensions -- and nothing more than that.
  const autoWindow = seen.histogram?.autoWindow;

  return (
    <div style={styles.controls} aria-label="channel controls">
      <div style={styles.headingRow}>
        <span style={styles.heading}>channel settings</span>
      </div>
      {/* Which channel these settings are about, said the same way the list
          above says it: the acquisition it belongs to, and under that the
          channel's own row -- eye, colour, name. Reading the same shape in
          both places is what makes the pairing obvious, and without it the
          sliders adjust something the operator has to remember rather than
          read. */}
      <div style={styles.controlsHead}>
        <span style={styles.controlsGroup} title={layer.group}>{layer.group}</span>
        <div style={styles.controlsChannel}>
          <button
            onClick={() => onToggle?.(index)}
            style={{ ...styles.eye, opacity: entry.visible ? 1 : 0.4 }}
            title={entry.visible ? "Hide this channel" : "Show this channel"}
            aria-label="toggle the chosen channel"
          >
            <Eye open={entry.visible} />
          </button>
          <ColourChooser
            layer={layer}
            entry={entry}
            names={lookupTables}
            named="the chosen channel"
            onPick={(choice) => {
              if (choice.lut) {
                onLut?.(index, choice.lut);
              } else {
                // A flat colour replaces whatever map was on, or the square
                // would go on showing a run of colours the channel is no
                // longer painted in.
                onLut?.(index, null);
                onColor(index, choice.rgb);
              }
            }}
          />
          <span style={styles.controlsName} title={layer.name}>
            {layer.name}
          </span>
        </div>
      </div>
      {isMask ? (
        <div style={styles.maskNote}>objects, each in its own colour</div>
      ) : (
        <>
          {/* The brightness of this channel, drawn across the panel. It
              takes the whole width now: the two buttons that used to sit
              beside it stole a sixth of the picture to say four letters
              each, and they read just as well under it. */}
          <div style={styles.histogramRow}>
            <Histogram
              layer={seen}
              window_={window_}
              color={css(entry.color)}
              onWindow={(next) => onWindow(index, next)}
              onAxis={(next) => setShown(next)}
              range={imageRange}
              scale={scale}
              axis={{ min, max }}
              // The bars' height scale is anchored to the resting frame, so
              // panning or zooming the axis never moves it — only Auto or a
              // fresh window does, by laying a new frame.
              steady={(() => {
                const resting = contrastRange(seen, window_, framed);
                return { min: resting.min, max: resting.max };
              })()}
            />
          </div>
          {/* Under the picture, in one row: what stretch of brightness it
              draws -- the two boxes, at its two ends, where they label the
              ends they set -- and between them the two things one can ask
              of it.

              Auto is a plain press, not a state: it reads the brightness of
              what is on screen and sets the window to it, and that is all.
              It was briefly a light that stayed on while the window matched
              its reading, with a second press that undid it -- but nobody
              presses Auto to undo it, and a button that means one thing on
              the way in and another on the way out is a button an operator
              has to remember rather than read (2026-08-20). Every handle,
              box and slider below stays free afterwards.

              Log is the one thing in this row that IS a state: it lifts the
              quiet bins and stays lifted until pressed again. */}
          <div style={styles.axisRow}>
            <span style={styles.axisBox}>
              <ValueBox
                value={Math.round(min)}
                onCommit={(asked) => setShown({
                  low: asked,
                  high: Math.max(asked + 1, shown ? shown.high : max),
                })}
                label={`axis from ${layer.name}`}
                align="left"
              />
            </span>
            <span style={styles.axisButtons}>
              <button
                type="button"
                onClick={async () => {
                  // What Auto is for: the brightness of what is in front of
                  // the operator, read afresh on every press -- on a plate,
                  // the whole picture's reading and one well's are worlds
                  // apart. The whole picture's is the fallback for the moment
                  // the view cannot be asked.
                  const answer = onMeasureHere ? await onMeasureHere(index) : null;
                  if (answer?.histogram) {
                    setHere(answer.histogram);
                    // A fresh reading is a fresh picture, so the axis is laid
                    // out again around the window it produced -- the bars land
                    // at fifteen and eighty five per cent of the width, exactly
                    // as they do when a channel first opens.
                    frameAround(answer.window);
                    return;
                  }
                  const fallingBackOn = autoWindow || layer.window;
                  onWindow(index, fallingBackOn);
                  frameAround(fallingBackOn);
                }}
                disabled={!onMeasureHere && !autoWindow && !layer.window}
                aria-label={`auto contrast ${layer.name}`}
                title="Set the window from the brightness of what is on screen, leaving out the ground nobody imaged"
                style={styles.autoButton}
              >
                Auto
              </button>
              <button
                type="button"
                onClick={() => setScale(scale === "log" ? "linear" : "log")}
                aria-label={scale === "log" ? "plain counts" : "logarithmic counts"}
                aria-pressed={scale === "log"}
                title="Lift the quiet bins of the histogram into view. Fluorescence piles almost every pixel into the dim bins, which leaves the interesting tail one pixel high"
                style={{ ...styles.autoButton, ...(scale === "log" ? styles.autoButtonOn : null) }}
              >
                Log
              </button>
            </span>
            <span style={styles.axisBox}>
              <ValueBox
                value={Math.round(max)}
                onCommit={(asked) => setShown({
                  low: Math.min(asked - 1, shown ? shown.low : min),
                  high: asked,
                })}
                label={`axis to ${layer.name}`}
              />
            </span>
          </div>
          <label style={styles.control}>
            <span style={styles.controlLabel} title="Anything dimmer than this is shown as black">
              min
            </span>
            {/* The handle travels over brightness itself, evenly, and over
                exactly the stretch the histogram above it draws -- so a mark
                on the picture and a handle beneath it always mean the same
                number. It used to count steps along a warped scale whenever
                Log was on, which moved the two apart. */}
            <FilledRange
              min={min}
              max={max}
              step="1"
              value={window_.low}
              onChange={(event) => setLow(Number(event.target.value))}
              aria-label={`min ${layer.name}`}
              title="Anything dimmer than this is shown as black"
              style={styles.range}
            />
            <ValueBox
              value={Math.round(window_.low)}
              onCommit={setLow}
              label={`min value ${layer.name}`}
            />
          </label>
          <label style={styles.control}>
            <span style={styles.controlLabel} title="Anything brighter than this is shown as white">
              max
            </span>
            <FilledRange
              min={min}
              max={max}
              step="1"
              value={window_.high}
              onChange={(event) => setHigh(Number(event.target.value))}
              aria-label={`max ${layer.name}`}
              title="Anything brighter than this is shown as white"
              style={styles.range}
            />
            <ValueBox
              value={Math.round(window_.high)}
              onCommit={setHigh}
              label={`max value ${layer.name}`}
            />
          </label>
        </>
      )}
      {/* The stretch inputs themselves live in the 3D viewer section below --
          squashing or exaggerating depth is what stretching is for, and that
          is seen in the volume. The warning stays HERE, in both views: a
          stretch set in the volume still distorts the flat picture after
          switching back, and a stretched picture with a quiet scale bar is a
          way to measure wrongly and never find out. */}
      {stretchedUnevenly(displayScales, mode) && (
        <div style={{ ...styles.controlLabel, color: "var(--warning-text)", padding: "0 12px 6px" }}>
          {mode === "volume"
            ? "the axes are stretched differently, so no single scale bar is true in every direction"
            : "x and y are stretched differently, so no single scale bar is true in both directions"}
        </div>
      )}
      <label style={styles.control}>
        <span style={styles.controlLabel} title="How strongly this channel is drawn">
          opacity
        </span>
        <FilledRange
          min="0"
          max="1"
          step="0.01"
          value={entry.opacity}
          onChange={(event) => onOpacity(index, Number(event.target.value))}
          aria-label={`opacity ${layer.name}`}
          style={styles.range}
        />
        <ValueBox
          value={Math.round(entry.opacity * 100)}
          suffix="%"
          onCommit={(asked) => onOpacity(index, Math.min(1, Math.max(0, asked / 100)))}
          label={`opacity value ${layer.name}`}
        />
      </label>
    </div>
  );
}

/**
 * The layer list, in napari's shape: one row per layer, an eye to hide it, a
 * swatch to recolour it.
 *
 * Deliberately the only chrome on screen. Everything the engine would otherwise
 * put up -- its own layer panel, top bar and dialogs -- is off, so this is the
 * single place layers are controlled and there is no second owner to fight.
 */
export default function LayerPanel({
  layers,
  state,
  mode,
  groupOrder = [],
  groupState = {},
  onToggle,
  onColor,
  onOpacity,
  onWindow,
  onMeasureHere,
  onLut,
  volumeMode = "max",
  onVolumeMode,
  volumeGain = 0,
  onVolumeGain,
  volumeAttenuation = 0,
  onVolumeAttenuation,
  depthSamples = 256,
  onDepthSamples,
  displayScales = { x: 1, y: 1, z: 1 },
  onDisplayScales,
  selected = 0,
  onSelect,
  canOpen = true,
  lookupTables = [],
  onGroupToggle,
  onOpenStore,
  onCloseGroup,
  busy = false,
  notice = null,
}) {
  const [collapsed, setCollapsed] = React.useState({});

  // Every row, paired with the position it holds in the panel's own state, so a
  // row can still be controlled after being gathered under its group.
  const rows = layers.map((layer, index) => ({ layer, index }));
  const groups = groupOrder.length
    ? groupOrder
    : [...new Set(layers.map((layer) => layer.group || ""))];

  // One line per channel: whether it is showing, what colour it is, what it is
  // called. Everything adjustable lives in the single block of controls below the
  // list, and applies to whichever line is picked out — the way napari does it.
  // The reason is simply that there is not room otherwise: with every slider on
  // every row, three channels filled a tall screen and six could not be seen at
  // all. Adjusting one channel at a time is also how the work actually goes.
  const renderRow = ({ layer, index }) => {
    const { visible } = state[index];
    const chosen = index === selected;
    return (
      <div
        key={layer.name}
        style={{ ...styles.layer, ...(chosen ? styles.layerChosen : null) }}
        onClick={() => onSelect?.(index)}
        aria-current={chosen ? "true" : undefined}
      >
        <div style={styles.row}>
          <button
            onClick={() => onToggle(index)}
            style={{ ...styles.eye, opacity: visible ? 1 : 0.4 }}
            title={visible ? "Hide this channel" : "Show this channel"}
            aria-label={`toggle ${layer.name}`}
          >
            <Eye open={visible} />
          </button>
          {/* The colour, and the way to change it: press the square and the
              list of everything this channel could be painted in opens. */}
          <ColourChooser
            layer={layer}
            entry={state[index]}
            names={lookupTables}
            onPick={(choice) => {
              if (choice.lut) {
                onLut?.(index, choice.lut);
              } else {
                onLut?.(index, null);
                onColor?.(index, choice.rgb);
              }
            }}
          />
          <span style={styles.name} title={layer.name}>
            {layer.name}
          </span>
        </div>
      </div>
    );
  };

  return (
    <section style={styles.panel} aria-label="layer panel">
      {/* Choosing folders by hand is for using the viewer on its own. During a
          run the workflow decides what is shown, so this whole box is absent —
          see `allow_open` in the server. */}
      {canOpen && onOpenStore && (
        <div style={styles.card}>
          <div style={styles.headingRow}>
            <span style={styles.heading}>load data</span>
            <button
              type="button"
              onClick={onOpenStore}
              disabled={busy}
              style={styles.openButton}
              aria-label="open images"
              title="Choose a folder of images to show"
            >
              {busy ? "…" : "choose folder"}
            </button>
          </div>
        </div>
      )}
      {/* Each section sits on the same lighter card, so the darker panel
          ground showing between them is what separates one from the next. */}
      <div style={styles.card}>
      <div style={styles.headingRow}>
        <span style={styles.heading}>image data</span>
      </div>
      {notice && (
        <div style={styles.notice} role="alert">
          {notice}
        </div>
      )}
      {!layers.length && (
        <div style={styles.empty}>Open the folder your run is writing into.</div>
      )}
      <div style={styles.list}>
      {groups.map((group, position) => {
        const members = rows.filter(({ layer }) => (layer.group || "") === group);
        if (!members.length) return null;
        const settings = groupState[group] || { visible: true };
        const isCollapsed = collapsed[group];
        // A group with no name is a store that carried no acquisition type in its
        // filename. It still needs to appear, so its rows are shown plainly with
        // no header rather than hidden under an empty heading.
        if (!group) return <div key="ungrouped">{members.map(renderRow)}</div>;
        return (
          <div key={group} style={styles.group}>
            <div style={styles.groupHead}>
              <button
                onClick={() => setCollapsed((c) => ({ ...c, [group]: !c[group] }))}
                style={styles.disclose}
                aria-label={`${isCollapsed ? "expand" : "collapse"} ${group}`}
                aria-expanded={!isCollapsed}
              >
                {isCollapsed ? "▸" : "▾"}
              </button>
              <button
                onClick={() => onGroupToggle?.(group)}
                style={{ ...styles.eye, opacity: settings.visible ? 1 : 0.4 }}
                aria-label={`toggle group ${group}`}
                title={settings.visible ? "Hide this acquisition" : "Show this acquisition"}
              >
                <Eye open={settings.visible} />
              </button>
              <span style={styles.groupName} title={group}>
                {group}
              </span>
              {/* Closing an acquisition by hand belongs to the browse-your-own
                  workflow; during a run the workflow decides what is shown, so
                  the button is absent then -- same rule as the folder chooser. */}
              {canOpen && onCloseGroup && (
                <button
                  type="button"
                  onClick={() => onCloseGroup(group)}
                  disabled={busy}
                  style={styles.close}
                  aria-label={`close ${group}`}
                  title="Stop showing this acquisition (the files are not touched)"
                >
                  ×
                </button>
              )}
            </div>
            {!isCollapsed && <div style={styles.members}>{members.map(renderRow)}</div>}
          </div>
        );
      })}
      </div>
      </div>
      {/* The settings sit directly under the list they act on: pick a channel
          above, adjust it here. The block names the channel it is adjusting,
          so the pairing can be read rather than remembered. */}
      {layers[selected] && state[selected] && (
        <ChannelControls
          layer={layers[selected]}
          index={selected}
          entry={state[selected]}
          mode={mode}
          onToggle={onToggle}
          lookupTables={lookupTables}
          onWindow={onWindow}
          onMeasureHere={onMeasureHere}
          onOpacity={onOpacity}
          onColor={onColor}
          onLut={onLut}
          displayScales={displayScales}
        />
      )}
      {/* How the volume is drawn. These act on the whole view rather than on
          one channel, so they live in their own section, shown only while the
          3-D view is. */}
      {mode === "volume" && (
        // marginTop matches the gap above the settings block: the display
        // settings carry marginBottom 12 of their own, so 4 more makes the
        // same clear 16 pixels of separation.
        <div style={{ ...styles.card, marginTop: 4 }}>
          <div style={styles.headingRow}>
            <span style={styles.heading}>3d viewer</span>
          </div>
          <VolumeMode
            volumeMode={volumeMode}
            onVolumeMode={onVolumeMode}
            gain={volumeGain}
            onGain={onVolumeGain}
            attenuation={volumeAttenuation}
            onAttenuation={onVolumeAttenuation}
            depthSamples={depthSamples}
            onDepthSamples={onDepthSamples}
            displayScales={displayScales}
            onDisplayScales={onDisplayScales}
          />
        </div>
      )}
    </section>
  );
}

// -- how it all looks ---------------------------------------------------------

// What separates one block of the bar from the next: a rule, and enough room on
// either side of it that the eye reads two sections rather than one long list.
const BLOCK = {
  // Ruled top and bottom, so a section reads as a card whichever side the
  // eye arrives from.
  borderTop: "1px solid var(--panel-border)",
  borderBottom: "1px solid var(--panel-border)",
  paddingTop: 8,
  paddingBottom: 8,
  marginBottom: 12,
};

// The ground under the channel being adjusted, in both the places it is
// named: its row in the list, and its row above the histogram. One value, so
// the two cannot drift apart.
const CHOSEN_GROUND = "var(--selected-row-bg)";

// How tall the colour list may grow before it scrolls. Named, because the
// list also asks "is there room for me below the square?", and the two have
// to be the same number.
const LIST_TALL_AT_MOST = 220;

const styles = {
  empty: {
    margin: "0 12px 12px",
    padding: "10px 11px",
    border: "1px dashed var(--panel-border)",
    borderRadius: 5,
    color: "var(--text-muted)",
    font: "11px/1.5 system-ui, sans-serif",
  },
  emptyLine: { margin: "0 0 6px" },
  orderNote: {
    margin: "0 12px 6px",
    color: "var(--text-muted)",
    font: "10px/1.4 system-ui, sans-serif",
  },
  // The two numbers under the histogram are the window in use, so the picture
  // above can be read as "this part of the spread is what you are seeing".
  histogramCaption: {
    display: "grid",
    gridTemplateColumns: "1fr auto 1fr",
    alignItems: "baseline",
    gap: 6,
    padding: "0 12px 3px 60px",
    color: "var(--text-muted)",
    font: "10px/1.3 system-ui, sans-serif",
    fontVariantNumeric: "tabular-nums",
  },
  eyeGlyph: { width: 14, height: 14, display: "block" },
  // The card every section sits on. Same blue as the display settings, so the
  // darker panel ground showing between the cards reads as the separation.
  // One spacing rhythm for every section, so the bar reads as one design:
  // a heading sits 10 of room above its content (5 from the heading row, 5
  // from the content's own top), and every card ends with 12 of room after
  // its last row (the operator asked for both, 2026-08-23).
  card: { ...BLOCK, paddingBottom: 12, background: "var(--card-bg)", flexShrink: 0 },
  headingRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    padding: "0 12px 5px",
    minHeight: 22,
  },
  openButton: {
    border: "1px solid var(--control-border)",
    borderRadius: 4,
    background: "var(--control-bg)",
    color: "var(--accent-text)",
    font: "600 10px/1 system-ui, sans-serif",
    padding: "4px 7px",
    cursor: "pointer",
  },
  notice: {
    margin: "0 12px 8px",
    padding: "6px 8px",
    border: "1px solid var(--danger-border)",
    borderRadius: 4,
    background: "var(--danger-bg)",
    color: "var(--danger-text)",
    font: "11px/1.4 system-ui, sans-serif",
  },
  // Deliberately quiet: closing is easy to reach but should not invite a stray
  // click, since it clears the settings the operator gave those channels.
  close: {
    border: "none",
    background: "none",
    color: "var(--text-faint)",
    fontSize: 15,
    lineHeight: 1,
    cursor: "pointer",
    padding: "0 2px",
  },
  group: { borderBottom: "1px solid var(--subtle-border)" },
  groupHead: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    // The 5 of top padding is half the heading rhythm; see the card note.
    padding: "5px 12px 3px",
  },
  disclose: {
    background: "none",
    border: "none",
    color: "var(--text-muted)",
    cursor: "pointer",
    fontSize: 10,
    padding: 0,
    width: 10,
  },
  groupName: {
    flex: 1,
    font: "600 12px/1 system-ui, sans-serif",
    letterSpacing: ".02em",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  maskNote: { padding: "2px 12px 4px 60px", color: "var(--text-faint)", fontSize: 10 },
  select: {
    width: "100%",
    background: "var(--control-bg)",
    color: "var(--text-secondary)",
    border: "1px solid var(--control-border)",
    borderRadius: 3,
    font: "10px system-ui, sans-serif",
    padding: "3px 4px",
  },
  // Channels are indented so it reads as "these belong to that acquisition".
  // marginLeft puts the 2px line exactly under the centre of the disclosure
  // triangle above it (12px head padding + half the 10px button).
  members: { paddingLeft: 8, borderLeft: "2px solid var(--subtle-border)", marginLeft: 16 },
  // The list keeps its natural height so the settings sit directly beneath
  // it, but a run with many acquisitions is capped and scrolls inside the
  // cap rather than pushing the settings off the bottom of the bar.
  list: { flex: "0 1 auto", minHeight: 90, maxHeight: "42vh", overflowY: "auto" },
  panel: {
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    // Inside the single right-hand bar now, so it takes the bar's width and
    // shares the height with the targets list below it. If everything
    // together still outgrows the bar, the whole panel scrolls.
    flex: 1,
    overflowY: "auto",
    // Noticeably darker than the section cards (#141922), so the ground
    // showing between them separates the sections at a glance.
    background: "var(--panel-bg)",
    padding: "12px 0 0",
    font: "13px/1.4 system-ui, -apple-system, 'Segoe UI', sans-serif",
    color: "var(--text-primary)",
  },
  heading: {
    font: "600 11px/1 system-ui, sans-serif",
    letterSpacing: ".08em",
    textTransform: "uppercase",
    color: "var(--text-faint)",
  },
  layer: {
    position: "relative",
    padding: "1px 0",
    cursor: "pointer",
    // The highlight below stops where the histogram does, so the row picked
    // out and the picture it belongs to share a right-hand edge.
    marginRight: 12,
    borderRadius: 3,
  },
  // The channel the controls below are acting on. It has to be unmistakable:
  // otherwise a slider appears to do nothing because it is adjusting a
  // different channel from the one being looked at. A tinted ground says that
  // on its own; there was a blue bar down the left of it as well, which said
  // the same thing twice and drew the eye to the panel's edge rather than to
  // the row.
  layerChosen: { background: CHOSEN_GROUND },
  // Directly below the list of channels, so the two things that belong
  // together -- the highlighted row naming the channel and the controls
  // adjusting it -- end up next to each other rather than at opposite ends
  // of the bar.
  // The clear space above the block is what separates it from the list at a
  // glance; the section rule alone was too easy to read past.
  // Every section is separated from the next by the darker panel ground
  // showing between the cards, and by the same amount: what set this one
  // apart with extra room above was making the settings look like a
  // different kind of thing from the list they belong to.
  controls: { ...BLOCK, paddingBottom: 12, background: "var(--card-bg)", flexShrink: 0 },
  controlsHead: {
    display: "flex",
    flexDirection: "column",
    gap: 3,
    // The 5 of top padding is half the heading rhythm; see the card note.
    padding: "5px 12px 6px",
  },
  // The channel's own row, built like the rows in the list above so the two
  // read as the same thing said twice: eye, colour, name -- on the same
  // tinted ground the chosen row carries up there, which is what ties the
  // two together at a glance.
  controlsChannel: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    minWidth: 0,
    background: CHOSEN_GROUND,
    borderRadius: 3,
    padding: "4px 6px",
  },
  controlsName: {
    color: "var(--text-bright)",
    font: "600 12px/1 system-ui, sans-serif",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  // The acquisition, written exactly as the list above writes it, so the two
  // read as one name in two places rather than two labels.
  controlsGroup: {
    font: "600 12px/1 system-ui, sans-serif",
    letterSpacing: ".02em",
    color: "var(--text-primary)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  row: { position: "relative", display: "flex", alignItems: "center", gap: 8, padding: "5px 12px" },
  eye: { background: "none", border: "none", color: "var(--text-primary)", cursor: "pointer", fontSize: 13, padding: 0 },
  swatch: { width: 13, height: 13, borderRadius: 3, border: "1px solid var(--control-border)", display: "inline-block", flexShrink: 0 },
  // The square is a button now, so it needs a button's manners taken off it:
  // no browser chrome, no text metrics, just the colour.
  swatchButton: { padding: 0, cursor: "pointer", appearance: "none" },
  // Under the histogram and exactly as wide: the same grid as the row above,
  // so the ends of the axis sit under the ends of the picture they describe.
  // Written as the same template rather than as a padding that happens to
  // come out near it, because the two would drift the moment either changed.
  // The same side padding the histogram carries, so the row's two ends sit
  // exactly under the two ends of the picture they describe. The generous
  // space beneath is deliberate: it closes the group -- picture, its two
  // ends, and what one can ask of it -- and separates it from the window
  // controls below, which are a different subject. Four pixels left the two
  // groups reading as one long list.
  axisRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
    padding: "0 12px 14px",
  },
  // Between the two ends, side by side and close: Auto and Log are a pair,
  // and the four pixels between them against the nineteen on either side of
  // the pair is what says so. Equal gaps would read as four unrelated
  // controls in a line.
  axisButtons: {
    display: "flex",
    alignItems: "center",
    gap: 4,
  },
  // One width for all four things in the row under the histogram -- these two
  // boxes and the two buttons between them -- and the same width again for
  // the value boxes in the slider rows, so the right-hand box stands in
  // their column. An edge that does not quite line up reads as a mistake
  // even when nobody can say which pixel is wrong (2026-08-20).
  axisBox: { width: ROW_ITEM, flexShrink: 0 },
  // Only as wide as the square it holds, since the square is now the whole
  // control; the list beneath it is free to be wider.
  chooser: { position: "relative", flexShrink: 0, lineHeight: 0 },
  // Above everything else in the panel, and scrolling once the list is longer
  // than the room beneath it.
  chooserList: {
    position: "fixed",
    minWidth: 116,
    zIndex: 40,
    display: "flex",
    flexDirection: "column",
    background: "var(--card-bg)",
    border: "1px solid var(--control-border)",
    borderRadius: 3,
    boxShadow: "0 6px 18px var(--shadow-color)",
    maxHeight: LIST_TALL_AT_MOST,
    overflowY: "auto",
  },
  chooserEntry: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    background: "transparent",
    color: "var(--text-secondary)",
    border: 0,
    font: "10px system-ui, sans-serif",
    padding: "4px 6px",
    cursor: "pointer",
    textAlign: "left",
  },
  chooserEntryOn: { background: "var(--selected-row-bg)", color: "var(--text-bright)" },
  // The custom entry holds the browser's own picker, invisible and filling
  // it, so pressing the entry opens the picker rather than a control of ours.
  chooserCustom: { position: "relative", cursor: "pointer" },
  chooserSwatch: {
    width: 22,
    height: 11,
    borderRadius: 2,
    border: "1px solid var(--control-border)",
    flexShrink: 0,
  },
  // The picker itself is invisible and fills the entry that holds it, so
  // that entry IS the button: the browser's own colour dialog opens on it,
  // which is the one an operator already knows and needs no widget of ours
  // to maintain.
  hiddenPicker: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    opacity: 0,
    padding: 0,
    border: 0,
    cursor: "pointer",
  },
  name: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  // The histogram spans the panel: left edge with the control labels, right
  // edge with the end of every slider's track below it.
  histogramRow: {
    padding: "1px 12px 4px",
  },
  histogram: {
    display: "block",
    width: "100%",
    // Tall enough to read a distribution in, now that nothing stands beside
    // it setting the height. It used to be sized to two stacked buttons.
    height: 60,
    // The loudest ink of the theme: the full-light bars between the window's
    // marks must read as "this is what you are seeing", against the dimmed
    // rest -- near-white on the dark theme, near-black on the light one.
    color: "var(--text-bright)",
    background: "var(--input-bg)",
    border: "1px solid var(--subtle-border)",
    borderRadius: 3,
  },
  autoButton: {
    width: ROW_ITEM,
    flexShrink: 0,
    // Built to the same block as the two value boxes it sits between: same
    // width, same height, same corner, same border thickness, so the four
    // read as one row of equals rather than four sizes in a line.
    height: ROW_HEIGHT,
    boxSizing: "border-box",
    padding: 0,
    textAlign: "center",
    border: "1px solid var(--control-border)",
    borderRadius: 3,
    background: "var(--control-bg)",
    color: "var(--text-secondary)",
    font: "600 11px/22px system-ui, sans-serif",
    cursor: "pointer",
  },
  control: {
    display: "grid",
    // The label column is sized to the longest label now in it (COLORMAP,
    // measured at 56px); anything narrower lets the text run underneath the
    // control beside it. It was 68 to hold BRIGHTNESS, a slider that no
    // longer exists, and those twelve pixels were costing every slider,
    // the colour well and the colormap list their left-hand reach.
    // 58 either side. The right-hand column is four pixels wider than the box
    // that sits in it, on purpose: that is what makes the slider track start
    // and stop exactly where Auto and Log do in the row above, so the middle
    // of the panel reads as one column rather than two that nearly agree.
    gridTemplateColumns: "58px 1fr 58px",
    alignItems: "center",
    gap: 6,
    padding: "2px 12px",
    color: "var(--text-muted)",
    fontSize: 10,
  },
  controlLabel: { textTransform: "uppercase", letterSpacing: ".04em" },
  // A toggle that is on: the same blue the sliders carry, so "lit" reads as
  // "active" without a legend.
  autoButtonOn: {
    background: "var(--accent-selection)",
    borderColor: "var(--accent)",
    color: "var(--accent-selection-text)",
  },
  // margin: 0 because the browser gives a range input two pixels of its own,
  // which pushed every track two to the right of the column it lives in --
  // and so two off the buttons above it that share that column.
  range: {
    width: "100%",
    margin: 0,
    cursor: "pointer",
  },
  value: { color: "var(--text-secondary)", textAlign: "right", fontVariantNumeric: "tabular-nums" },
  // The typed twin of the value read-out: same column, same right-aligned
  // numerals, with just enough of a border to say "you may type here".
  valueBox: {
    // The same block as everything else in this panel, held to the right of
    // its slightly wider column so its edge stays in the column the boxes
    // above it make.
    width: ROW_ITEM,
    justifySelf: "end",
    height: ROW_HEIGHT,
    // Padding and border inside the width, or the box overflows its column
    // by their sum and stops lining up with the buttons above it.
    boxSizing: "border-box",
    background: "var(--input-bg)",
    border: "1px solid var(--subtle-border)",
    borderRadius: 3,
    color: "var(--text-secondary)",
    font: "inherit",
    fontVariantNumeric: "tabular-nums",
    textAlign: "right",
    padding: "1px 3px",
  },
};
