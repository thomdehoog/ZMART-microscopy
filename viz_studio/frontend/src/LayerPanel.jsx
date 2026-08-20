import React from "react";

import { restingWindow } from "./scene.js";

// A small, deliberately limited palette. Green and magenta lead because that is
// the pairing that reads best on a dark background and stays legible to a
// colour-blind viewer, unlike red/green.
export const PALETTE = [
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
function contrastRange(layer, window_, shown = null) {
  const measured = layer.histogram;
  const declared = layer.range;
  let min = 0;
  let max = 65535;
  if (measured && Number.isFinite(measured.low) && measured.high > measured.low) {
    min = Math.floor(measured.low);
    max = Math.ceil(measured.high);
  }
  if (shown && Number.isFinite(shown.low) && shown.high > shown.low) {
    if (declared && Number.isFinite(declared.high)) {
      return {
        min: Math.max(shown.low, declared.low ?? 0),
        max: Math.min(shown.high, declared.high),
      };
    }
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
 * The two bars ARE the window, so they drag: take hold near one and pull, and
 * that edge of the window follows — the same window the MIN and MAX sliders
 * move, so the two controls can never disagree. Whichever bar is nearer to
 * where the drag begins is the one taken hold of, which makes the bars easy
 * to grab even when the window is pushed against an edge.
 */
function Histogram({ layer, window_, color, onWindow, scale = "linear", axis = null }) {
  const dragging = React.useRef(null);
  const counts = layer.histogram?.counts;
  if (!counts?.length) return null;
  const peak = Math.max(...counts, 1);
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

  // Where a pointer event sits on the measured brightness scale.
  const valueUnder = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    return low + fraction * span;
  };
  const takeHold = (event) => {
    if (!onWindow) return;
    const value = valueUnder(event);
    dragging.current =
      Math.abs(value - window_.low) <= Math.abs(value - window_.high) ? "low" : "high";
    event.currentTarget.setPointerCapture(event.pointerId);
    follow(event);
  };
  const follow = (event) => {
    if (!dragging.current || !onWindow) return;
    const value = valueUnder(event);
    // The floor may not cross the ceiling: a window at least one count wide
    // always remains, so the picture can never invert.
    if (dragging.current === "low") {
      onWindow({ low: Math.min(value, window_.high - 1), high: window_.high });
    } else {
      onWindow({ low: window_.low, high: Math.max(value, window_.low + 1) });
    }
  };
  const letGo = () => {
    dragging.current = null;
  };

  return (
    <svg
      viewBox={`0 0 ${counts.length} 24`}
      preserveAspectRatio="none"
      style={{ ...styles.histogram, cursor: onWindow ? "ew-resize" : "default" }}
      role="img"
      aria-label={`histogram ${layer.name}`}
      onPointerDown={takeHold}
      onPointerMove={follow}
      onPointerUp={letGo}
      onPointerCancel={letGo}
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
        // may run far past them to the camera's ceiling.
        const bins = measured.high - measured.low || 1;
        const centre = measured.low + ((index + 0.5) * bins) / counts.length;
        const shown = centre >= window_.low && centre <= window_.high;
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
          <rect key={edge} x={x} y="0" width="0.8" height="24" fill="#2f81f7" />
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
function ValueBox({ value, onCommit, label, suffix = "" }) {
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
      style={styles.valueBox}
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
      <input
        type="range" min="-3" max="3" step="0.1" value={gain}
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
      <input
        type="range" min="6" max="16" step="1"
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
      <input
        type="range" min="0" max="8" step="0.1" value={attenuation}
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
 * Choosing what a channel is painted with, showing each choice as it looks.
 *
 * A plain dropdown can only offer words, and the word "magma" tells a
 * microscopist meeting it nothing at all -- which is why the old one had to
 * spell out "(black -> purple -> cream)" beside every map and still left an
 * operator picking by trial. Here every entry carries its own colour beside
 * it, a block for a flat colour and the run of colours for a map, so the
 * choice is made by eye. With that on show the explanations are not needed
 * and are gone.
 *
 * It is a list of buttons rather than a select because a select cannot draw
 * anything but text. That costs the keyboard nothing: each entry is a real
 * button, so tabbing walks them and Enter picks, and Escape closes the list.
 */
function ColormapChooser({ layer, entry, names, onPick }) {
  const [open, setOpen] = React.useState(false);
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
  // A colour picked by hand belongs to no entry in the list, and saying the
  // nearest name would tell the operator they chose something they did not.
  const naming = chosen ? chosen.name : "picked";
  return (
    <span style={styles.chooser}>
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        onBlur={(event) => {
          // Closed when the focus leaves the whole chooser, not merely this
          // button -- otherwise pressing an entry closes the list before the
          // press lands on it.
          if (!event.currentTarget.parentElement.contains(event.relatedTarget)) {
            setOpen(false);
          }
        }}
        aria-label={`colormap ${layer.name}`}
        aria-expanded={open}
        title="What this channel is painted with"
        style={styles.chooserButton}
      >
        <span style={styles.chooserName}>{naming}</span>
        <span aria-hidden="true" style={styles.chooserCaret}>▾</span>
      </button>
      {open && (
        <span role="listbox" style={styles.chooserList}>
          {choices.map((choice) => (
            <button
              key={choice.key}
              type="button"
              role="option"
              aria-selected={chosen?.key === choice.key}
              aria-label={`${choice.name} for ${layer.name}`}
              onBlur={(event) => {
                if (!event.currentTarget.parentElement.parentElement
                  .contains(event.relatedTarget)) {
                  setOpen(false);
                }
              }}
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


function ChannelControls({ layer, index, entry, mode, lookupTables, onWindow, onOpacity,
                          onColor, onLut, displayScales = { x: 1, y: 1, z: 1 } }) {
  // The same resting window the canvas draws with (see scene.js): the run's
  // recorded window, or the measured one when the run said nothing.
  const window_ = entry.window || restingWindow(layer, mode === "volume")
    || { low: 0, high: 65535 };
  // Which part of the brightness axis is drawn. Nothing said means the data's
  // own span; the two boxes under the histogram are where an operator says
  // otherwise, and their answer is kept per channel for as long as the panel
  // is showing it.
  const [shown, setShown] = React.useState(null);
  const { min, max } = contrastRange(layer, window_, shown);
  // The two handles are kept at least one count apart. A window of no width makes
  // every value in the image land on the same shade, so the picture goes flat and
  // it is not obvious why.
  const setLow = (low) =>
    onWindow(index, { low: Math.min(low, window_.high - 1), high: window_.high });
  const setHigh = (high) =>
    onWindow(index, { low: window_.low, high: Math.max(high, window_.low + 1) });

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

  // The Auto light is derived, not stored: it is on exactly while the window
  // equals the measured one, so dragging any handle away turns it off by
  // itself and switching channels always shows the truth.
  const autoWindow = layer.histogram?.autoWindow;
  const following =
    !!autoWindow &&
    Math.abs(window_.low - autoWindow.low) < 0.5 &&
    Math.abs(window_.high - autoWindow.high) < 0.5;
  // What clicking the lit light puts back: the window the run itself
  // declared when that is genuinely a different window, and otherwise the
  // camera's whole range -- everything shown, nothing clipped, the state
  // before anyone chose anything. A run that declared nothing is served the
  // measured window AS its window, so without the difference test the lit
  // button offered a toggle between two equal values and clicking it
  // visibly did nothing (found with a real plate, 2026-08-19; the full-range
  // off state is what the operator asked for the same evening).
  const declared =
    layer.window && autoWindow &&
    (Math.abs(layer.window.low - autoWindow.low) >= 0.5 ||
     Math.abs(layer.window.high - autoWindow.high) >= 0.5)
      ? layer.window
      : null;
  const camera = layer.range && Number.isFinite(layer.range.high)
    ? { low: layer.range.low ?? 0, high: layer.range.high }
    : null;
  const unlit = declared || camera;

  return (
    <div style={styles.controls} aria-label="channel controls">
      <div style={styles.headingRow}>
        <span style={styles.heading}>display settings</span>
      </div>
      <div style={styles.controlsHead}>
        {/* Which channel these settings are about. Without it, the sliders would
            be adjusting something the operator has to remember rather than read. */}
        <span style={styles.controlsName} title={layer.name}>
          {layer.name}
        </span>
        <span style={styles.controlsGroup}>{layer.group}</span>
      </div>
      {isMask ? (
        <div style={styles.maskNote}>objects, each in its own colour</div>
      ) : (
        <>
          <div style={styles.histogramRow}>
            <Histogram
              layer={layer}
              window_={window_}
              color={css(entry.color)}
              onWindow={(next) => onWindow(index, next)}
              scale={scale}
              axis={{ min, max }}
            />
            {/* Auto is a light as much as a button: lit while the window is
                the measured one. Clicking it on applies that measurement;
                clicking it off puts back the window the run itself declared,
                which is what the old Reset button did -- and moving any
                handle by hand turns the light off on its own, because the
                light only ever reports whether window and measurement agree.
                Log warps the brightness axis, histogram and sliders alike. */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <button
                type="button"
                onClick={() =>
                  onWindow(
                    index,
                    following ? unlit : autoWindow || layer.window,
                  )
                }
                disabled={following ? !unlit : !autoWindow && !layer.window}
                aria-label={`auto contrast ${layer.name}`}
                aria-pressed={following}
                title={following
                  ? (declared
                    ? "The window is the measured one; click to put back the window this run was written with"
                    : "The window is the measured one; click to spread it over the camera's whole range")
                  : "Set the window from the brightness measured in this channel"}
                style={{ ...styles.autoButton, ...(following ? styles.autoButtonOn : null) }}
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
            </div>
          </div>
          {/* What part of the brightness axis the histogram above draws, and
              with it how far the handles below can travel. Beneath the
              picture and no wider than it, because the pair belong to the
              picture rather than to the window. */}
          <div style={styles.axisRow}>
            <ValueBox
              value={Math.round(min)}
              onCommit={(asked) => setShown({
                low: asked,
                high: Math.max(asked + 1, shown ? shown.high : max),
              })}
              label={`axis from ${layer.name}`}
            />
            <span style={styles.axisNote} title="The stretch of brightness the histogram draws, and how far the handles below can travel">
              shown
            </span>
            <ValueBox
              value={Math.round(max)}
              onCommit={(asked) => setShown({
                low: Math.min(asked - 1, shown ? shown.low : min),
                high: asked,
              })}
              label={`axis to ${layer.name}`}
            />
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
            <input
              type="range"
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
            <input
              type="range"
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
        <div style={{ ...styles.controlLabel, color: "#d9a441", padding: "0 12px 6px" }}>
          {mode === "volume"
            ? "the axes are stretched differently, so no single scale bar is true in every direction"
            : "x and y are stretched differently, so no single scale bar is true in both directions"}
        </div>
      )}
      <label style={styles.control}>
        <span style={styles.controlLabel} title="How strongly this channel is drawn">
          opacity
        </span>
        <input
          type="range"
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
      {/* How the channel is painted, in one row: what it looks like now, a
          way to choose any colour at all, and the named colours and maps.
          The preview is the choice made visible -- a flat colour as a block,
          a map as its own run of colours -- and it is also the button that
          opens the colour picker, so an operator can see what they have while
          they change it rather than only afterwards. */}
        <label style={styles.control}>
          <span
            style={styles.controlLabel}
            title="How this channel is painted: one flat colour, or a run of colours that shows more detail"
          >
            colormap
          </span>
          <span style={{ ...styles.colourRow, gridColumn: "2 / -1" }}>
            <span
              style={{
                ...styles.preview,
                background: (entry.lut && LUT_GRADIENTS[entry.lut])
                  || css(entry.color),
              }}
              title="What this channel is painted with. Press to choose any colour"
            >
              <input
                type="color"
                value={hexOf(entry.color)}
                onChange={(event) => {
                  // A colour chosen by hand is a flat colour, so whatever map
                  // was on gives way to it -- the preview would otherwise go on
                  // showing a run of colours the channel is no longer painted in.
                  onLut?.(index, null);
                  onColor(index, rgbOf(event.target.value));
                }}
                aria-label={`choose a colour for ${layer.name}`}
                style={styles.hiddenPicker}
              />
            </span>
            <ColormapChooser
              layer={layer}
              entry={entry}
              names={lookupTables}
              onPick={(choice) => {
                if (choice.lut) {
                  onLut?.(index, choice.lut);
                } else {
                  onLut?.(index, null);
                  onColor(index, choice.rgb);
                }
              }}
            />
          </span>
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
    const { visible, color, lut } = state[index];
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
          {/* A read-out, not a control: the colour is chosen in the display
              settings, and this swatch follows the choice. */}
          <span
            style={{ ...styles.swatch,
                     background: (lut && LUT_GRADIENTS[lut]) || css(color) }}
            title="How this channel is painted -- choose it in the display settings"
            aria-label={`colour ${layer.name}`}
            role="img"
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
          lookupTables={lookupTables}
          onWindow={onWindow}
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
  borderTop: "1px solid #2b3440",
  borderBottom: "1px solid #2b3440",
  paddingTop: 8,
  paddingBottom: 8,
  marginBottom: 12,
};

const styles = {
  empty: {
    margin: "0 12px 12px",
    padding: "10px 11px",
    border: "1px dashed #2b3440",
    borderRadius: 5,
    color: "#8b95a3",
    font: "11px/1.5 system-ui, sans-serif",
  },
  emptyLine: { margin: "0 0 6px" },
  orderNote: {
    margin: "0 12px 6px",
    color: "#8b95a3",
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
    color: "#8b95a3",
    font: "10px/1.3 system-ui, sans-serif",
    fontVariantNumeric: "tabular-nums",
  },
  eyeGlyph: { width: 14, height: 14, display: "block" },
  // The card every section sits on. Same blue as the display settings, so the
  // darker panel ground showing between the cards reads as the separation.
  card: { ...BLOCK, paddingBottom: 8, background: "#141922", flexShrink: 0 },
  headingRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    padding: "0 12px 8px",
    minHeight: 22,
  },
  openButton: {
    border: "1px solid #303a46",
    borderRadius: 4,
    background: "#1b222b",
    color: "#9ecbff",
    font: "600 10px/1 system-ui, sans-serif",
    padding: "4px 7px",
    cursor: "pointer",
  },
  notice: {
    margin: "0 12px 8px",
    padding: "6px 8px",
    border: "1px solid #4a2b30",
    borderRadius: 4,
    background: "#251a1d",
    color: "#f0888f",
    font: "11px/1.4 system-ui, sans-serif",
  },
  // Deliberately quiet: closing is easy to reach but should not invite a stray
  // click, since it clears the settings the operator gave those channels.
  close: {
    border: "none",
    background: "none",
    color: "#5f6a78",
    fontSize: 15,
    lineHeight: 1,
    cursor: "pointer",
    padding: "0 2px",
  },
  group: { borderBottom: "1px solid #1d232b" },
  groupHead: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "7px 12px 3px",
  },
  disclose: {
    background: "none",
    border: "none",
    color: "#7f8a98",
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
  maskNote: { padding: "2px 12px 4px 60px", color: "#6b7684", fontSize: 10 },
  select: {
    width: "100%",
    background: "#1b222b",
    color: "#aab4c0",
    border: "1px solid #303a46",
    borderRadius: 3,
    font: "10px system-ui, sans-serif",
    padding: "3px 4px",
  },
  // Channels are indented so it reads as "these belong to that acquisition".
  // marginLeft puts the 2px line exactly under the centre of the disclosure
  // triangle above it (12px head padding + half the 10px button).
  members: { paddingLeft: 8, borderLeft: "2px solid #1f2630", marginLeft: 16 },
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
    background: "#0d1015",
    padding: "12px 0 0",
    font: "13px/1.4 system-ui, -apple-system, 'Segoe UI', sans-serif",
    color: "#c9d1d9",
  },
  heading: {
    font: "600 11px/1 system-ui, sans-serif",
    letterSpacing: ".08em",
    textTransform: "uppercase",
    color: "#6b7684",
  },
  layer: {
    position: "relative",
    padding: "1px 0",
    cursor: "pointer",
    borderLeft: "2px solid transparent",
  },
  // The channel the controls below are acting on. It has to be unmistakable:
  // otherwise a slider appears to do nothing because it is adjusting a different
  // channel from the one being looked at.
  layerChosen: { background: "#1b2431", borderLeftColor: "#2f81f7" },
  // Directly below the list of channels, so the two things that belong
  // together -- the highlighted row naming the channel and the controls
  // adjusting it -- end up next to each other rather than at opposite ends
  // of the bar.
  // The clear space above the block is what separates it from the list at a
  // glance; the section rule alone was too easy to read past.
  controls: { ...BLOCK, marginTop: 16, paddingBottom: 12, background: "#141922", flexShrink: 0 },
  controlsHead: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 8,
    padding: "0 12px 6px",
  },
  controlsName: {
    color: "#e6edf3",
    font: "600 12px/1 system-ui, sans-serif",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  controlsGroup: { color: "#8b95a3", font: "10px/1 system-ui, sans-serif" },
  row: { position: "relative", display: "flex", alignItems: "center", gap: 8, padding: "5px 12px" },
  eye: { background: "none", border: "none", color: "#c9d1d9", cursor: "pointer", fontSize: 13, padding: 0 },
  swatch: { width: 13, height: 13, borderRadius: 3, border: "1px solid #39424e", display: "inline-block", flexShrink: 0 },
  // The colour row: what the channel is painted with, then how to change it.
  colourRow: { display: "flex", alignItems: "center", gap: 5, minWidth: 0 },
  // Under the histogram and no wider: the two ends of what it draws, with a
  // quiet word between them saying what they are.
  axisRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
    marginBottom: 4,
    paddingRight: 62,
  },
  axisNote: {
    font: "9px system-ui, sans-serif",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "#6b7684",
  },
  chooser: { position: "relative", flex: 1, minWidth: 0 },
  chooserButton: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 4,
    background: "#1b222b",
    color: "#aab4c0",
    border: "1px solid #303a46",
    borderRadius: 3,
    font: "10px system-ui, sans-serif",
    padding: "3px 4px",
    cursor: "pointer",
  },
  chooserName: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  chooserCaret: { opacity: 0.7, flexShrink: 0 },
  // Above everything else in the panel, and scrolling once the list is longer
  // than the room beneath it.
  chooserList: {
    position: "absolute",
    top: "calc(100% + 2px)",
    left: 0,
    right: 0,
    zIndex: 40,
    display: "flex",
    flexDirection: "column",
    background: "#141a22",
    border: "1px solid #303a46",
    borderRadius: 3,
    boxShadow: "0 6px 18px rgba(0, 0, 0, 0.5)",
    maxHeight: 220,
    overflowY: "auto",
  },
  chooserEntry: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    background: "transparent",
    color: "#aab4c0",
    border: 0,
    font: "10px system-ui, sans-serif",
    padding: "4px 6px",
    cursor: "pointer",
    textAlign: "left",
  },
  chooserEntryOn: { background: "#243040", color: "#e8edf3" },
  chooserSwatch: {
    width: 22,
    height: 11,
    borderRadius: 2,
    border: "1px solid #39424e",
    flexShrink: 0,
  },
  // Bigger than the row swatch, because this one has to show a whole run of
  // colours legibly rather than just say which one is chosen.
  preview: {
    position: "relative",
    width: 30,
    height: 16,
    borderRadius: 3,
    border: "1px solid #39424e",
    flexShrink: 0,
    cursor: "pointer",
    overflow: "hidden",
  },
  // The picker itself is invisible and fills the preview, so the preview IS
  // the button: the browser's own colour dialog opens on it, which is the one
  // an operator already knows and needs no widget of ours to maintain.
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
  histogramRow: {
    display: "grid",
    // The histogram takes the row's width, starting at the labels' left
    // edge. The button column and gap match the value column of the control
    // rows below exactly, so the histogram's right edge lines up with the
    // end of every slider's track.
    gridTemplateColumns: "1fr 60px",
    alignItems: "end",
    gap: 6,
    padding: "1px 12px 4px",
  },
  histogram: {
    display: "block",
    width: "100%",
    // Sized so the two buttons beside it, stacked with their gap, stand
    // exactly as tall: top and bottom edges line up.
    height: 54,
    // Near-white: the full-light bars between the window's marks must read
    // as "this is what you are seeing", against the dimmed rest.
    color: "#dde5ee",
    background: "#0d1015",
    border: "1px solid #202731",
    borderRadius: 3,
  },
  autoButton: {
    // Full column width with the text centred, so the word keeps even air
    // on both sides however narrow the column. Two of these stacked, with
    // their gap, stand exactly as tall as the histogram beside them.
    width: "100%",
    // Exact height: two of these plus the 4px gap equal the histogram's
    // rendered 56px (54 content + its border), so tops and bottoms meet.
    height: 26,
    padding: 0,
    textAlign: "center",
    border: "1px solid #303a46",
    borderRadius: 4,
    background: "#1b222b",
    color: "#aab4c0",
    font: "600 11px/24px system-ui, sans-serif",
    cursor: "pointer",
  },
  control: {
    display: "grid",
    // The label column is sized to the longest label (BRIGHTNESS); anything
    // narrower lets the text run underneath the slider beside it.
    gridTemplateColumns: "68px 1fr 60px",
    alignItems: "center",
    gap: 6,
    padding: "2px 12px",
    color: "#7f8a98",
    fontSize: 10,
  },
  controlLabel: { textTransform: "uppercase", letterSpacing: ".04em" },
  // A toggle that is on: the same blue the sliders carry, so "lit" reads as
  // "active" without a legend.
  autoButtonOn: { background: "#1f3a5f", borderColor: "#2f81f7", color: "#dbe6f3" },
  range: { width: "100%", accentColor: "#2f81f7", cursor: "pointer" },
  value: { color: "#aab4c0", textAlign: "right", fontVariantNumeric: "tabular-nums" },
  // The typed twin of the value read-out: same column, same right-aligned
  // numerals, with just enough of a border to say "you may type here".
  valueBox: {
    width: "100%",
    // Padding and border inside the width, or the box overflows its column
    // by their sum and stops lining up with the buttons above it.
    boxSizing: "border-box",
    background: "#0d1015",
    border: "1px solid #202731",
    borderRadius: 3,
    color: "#aab4c0",
    font: "inherit",
    fontVariantNumeric: "tabular-nums",
    textAlign: "right",
    padding: "1px 3px",
  },
};
