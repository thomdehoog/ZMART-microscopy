import React from "react";

// A small, deliberately limited palette. Green and magenta lead because that is
// the pairing that reads best on a dark background and stays legible to a
// colour-blind viewer, unlike red/green.
export const PALETTE = [
  { name: "green", rgb: [0.0, 1.0, 0.4] },
  { name: "magenta", rgb: [1.0, 0.2, 1.0] },
  { name: "cyan", rgb: [0.2, 0.8, 1.0] },
  { name: "amber", rgb: [1.0, 0.75, 0.1] },
  { name: "blue", rgb: [0.3, 0.45, 1.0] },
  { name: "grey", rgb: null },
];

// A word or two saying what each colour map looks like. The names are the ones
// everybody uses, but they mean nothing until you have seen one, and a biologist
// meeting this panel for the first time should not have to try all four to find
// out.
const LUT_DESCRIPTIONS = {
  viridis: "(blue → green → yellow)",
  magma: "(black → purple → cream)",
  fire: "(black → red → white)",
  ice: "(black → blue → white)",
};

const css = (rgb) =>
  rgb ? `rgb(${rgb.map((v) => Math.round(v * 255)).join(",")})` : "#d8dee6";

// -- the pieces the panel is drawn from ---------------------------------------
//
// A histogram, an eye, and the arithmetic that decides how far the contrast
// handles may travel. They are here rather than inside the panel below so that
// each can be read on its own, and because each of them answers a question a
// microscopist actually asks rather than a question about the interface.

/**
 * How far the black and white handles are allowed to travel.
 *
 * This used to be the full range of the numbers a camera can produce — nought to
 * 65535 — and that made the sliders very nearly unusable on real data. A real
 * acquisition sits in a narrow band of that range, often a few hundred counts of
 * background with the signal just above; across a track a few centimetres wide,
 * the whole useful part was about two pixels of travel, and a single pixel of
 * movement jumped the brightness by hundreds of counts. In practice the only
 * usable control was the Auto button.
 *
 * So the travel is taken from the spread of brightness the server measured — the
 * same measurement the histogram above the sliders is drawn from — with room to
 * spare at each end. The window in use is always included, so pressing "full"
 * widens the track rather than leaving a handle stranded off the end of it.
 */
function contrastRange(layer, window_) {
  const measured = layer.histogram;
  let min = 0;
  let max = 65535;
  if (measured && Number.isFinite(measured.low) && measured.high > measured.low) {
    const room = (measured.high - measured.low) * 0.2;
    min = Math.max(0, Math.floor(measured.low - room));
    max = Math.ceil(measured.high + room);
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
 * actually asks: is this channel saturating, or is it sitting on background? The
 * shaded band shows which part of the spread is being stretched across the
 * screen, so it can be read at a glance — anything to the left of the band comes
 * out black, anything to the right comes out white.
 */
function Histogram({ layer, window_, color }) {
  const counts = layer.histogram?.counts;
  if (!counts?.length) return null;
  const peak = Math.max(...counts, 1);
  const measured = layer.histogram;
  // The bars are drawn across the range the server measured; the band has to be
  // placed on that same scale, or it would sit under the wrong bars.
  const span = measured.high - measured.low || 1;
  const at = (value) => ((value - measured.low) / span) * counts.length;
  const left = Math.max(0, at(window_.low));
  const right = Math.min(counts.length, at(window_.high));
  return (
    <svg
      viewBox={`0 0 ${counts.length} 24`}
      preserveAspectRatio="none"
      style={styles.histogram}
      role="img"
      aria-label={`histogram ${layer.name}`}
    >
      {right > left && (
        <rect
          x={left}
          y="0"
          width={right - left}
          height="24"
          fill={color}
          opacity="0.16"
        />
      )}
      {counts.map((count, index) => {
        const height = (Math.log1p(count) / Math.log1p(peak)) * 22;
        return (
          <rect
            key={index}
            x={index}
            y={24 - height}
            width="1"
            height={height}
            fill="currentColor"
          />
        );
      })}
      {[left, right].map((x, edge) =>
        x > 0 && x < counts.length ? (
          <rect key={edge} x={x} y="0" width="0.6" height="24" fill={color} opacity="0.9" />
        ) : null,
      )}
    </svg>
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
                     depthSamples, onDepthSamples }) {
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
        title="Brightest keeps the brightest voxel along each ray, which is what most fluorescence is looked at with. Accumulated adds them all up."
        style={styles.select}
      >
        <option value="max">brightest along the ray (mip)</option>
        <option value="on">accumulated through the volume</option>
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
        style={styles.slider}
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
        style={styles.slider}
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
        style={styles.slider}
      />
      <output style={styles.value}>{attenuation.toFixed(1)}</output>
    </label>
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

function ChannelControls({ layer, index, entry, mode, lookupTables, onWindow, onOpacity, onLut,
                          displayScales = { x: 1, y: 1, z: 1 }, onDisplayScales }) {
  const measuredWindow = mode === "volume" ? layer.volumeWindow || layer.window : layer.window;
  const window_ = entry.window || measuredWindow || { low: 0, high: 65535 };
  const { min, max } = contrastRange(layer, window_);
  // The two handles are kept at least one count apart. A window of no width makes
  // every value in the image land on the same shade, so the picture goes flat and
  // it is not obvious why.
  const setLow = (low) =>
    onWindow(index, { low: Math.min(low, window_.high - 1), high: window_.high });
  const setHigh = (high) =>
    onWindow(index, { low: window_.low, high: Math.max(high, window_.low + 1) });

  // Brightness and contrast are not a second setting; they are the same window
  // described the way a microscopist is used to describing it, which is how Fiji
  // has always presented it. The two handles say *where* the window is; these two
  // say how bright the middle of it is and how tightly it is drawn around that
  // middle. Moving either pair moves the other, because underneath there is only
  // ever one window.
  //
  // Brightness runs backwards on purpose: pulling the window down towards the
  // dark end makes the picture brighter, since more of the image lands above it.
  const track = Math.max(1, max - min);
  const middle = (window_.low + window_.high) / 2;
  const width = Math.max(1, window_.high - window_.low);
  const brightness = Math.round((1 - (middle - min) / track) * 100);
  const contrast = Math.round((1 - width / track) * 100);
  const windowAround = (centre, spread) => {
    const half = Math.max(0.5, spread / 2);
    return onWindow(index, { low: centre - half, high: centre + half });
  };
  const setBrightness = (value) =>
    windowAround(min + (1 - value / 100) * track, width);
  const setContrast = (value) =>
    windowAround(middle, Math.max(1, (1 - value / 100) * track));
  const isMask = layer.kind === "segmentation";

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
            <Histogram layer={layer} window_={window_} color={css(entry.color)} />
            <button
              type="button"
              onClick={() => onWindow(index, layer.histogram?.autoWindow || layer.window)}
              disabled={!layer.histogram?.autoWindow && !layer.window}
              aria-label={`auto contrast ${layer.name}`}
              title="Set the window from the brightness measured in this channel"
              style={styles.autoButton}
            >
              Auto
            </button>
            {/* Auto and Reset answer different questions and neither replaces the
                other. Auto reads the brightness actually present in this channel;
                Reset puts back the window the run itself declared, which is what
                the operator saw when the images were opened. Somebody who has
                pulled the handles about wants the second far more often than a
                fresh measurement. */}
            <button
              type="button"
              onClick={() => onWindow(index, layer.window || layer.histogram?.autoWindow)}
              disabled={!layer.window && !layer.histogram?.autoWindow}
              aria-label={`reset contrast ${layer.name}`}
              title="Put back the window this run was written with"
              style={styles.autoButton}
            >
              Reset
            </button>
          </div>
          <label style={styles.control}>
            <span style={styles.controlLabel} title="Anything dimmer than this is shown as black">
              min
            </span>
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
            <output style={styles.value}>{Math.round(window_.low)}</output>
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
            <output style={styles.value}>{Math.round(window_.high)}</output>
          </label>
          <label style={styles.control}>
            <span style={styles.controlLabel} title="Move the whole window up or down the range at once">
              brightness
            </span>
            <input
              type="range" min="0" max="100" step="1" value={brightness}
              onChange={(event) => setBrightness(Number(event.target.value))}
              aria-label={`brightness ${layer.name}`}
              title="Slides the window along without changing how wide it is"
              style={styles.range}
            />
            <output style={styles.value}>{brightness}</output>
          </label>
          <label style={styles.control}>
            <span style={styles.controlLabel} title="Draw the window tighter around its middle">
              contrast
            </span>
            <input
              type="range" min="0" max="99" step="1" value={contrast}
              onChange={(event) => setContrast(Number(event.target.value))}
              aria-label={`contrast ${layer.name}`}
              title="Narrows the window around its middle, so a smaller range of brightness fills the screen"
              style={styles.range}
            />
            <output style={styles.value}>{contrast}</output>
          </label>
        </>
      )}
      {/* Stretching the picture along an axis, which is a property of the view
          rather than of a channel -- so it sits here once, not once per colour.
          Anything other than 1 means the picture is no longer drawn at the
          proportions the run declared, and the note below says so, because a
          stretched picture with a quiet scale bar is a way to measure wrongly
          and never find out. */}
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
        <output style={styles.value}>{Math.round(entry.opacity * 100)}%</output>
      </label>
          {lookupTables.length > 0 && (
        <label style={styles.control}>
          <span
            style={styles.controlLabel}
            title="Paint this channel in a run of colours instead of one flat colour"
          >
            colour
          </span>
          <select
            value={entry.lut || ""}
            onChange={(event) => onLut?.(index, event.target.value || null)}
            aria-label={`colour map ${layer.name}`}
            title="A colour map shows more detail in a single channel than a plain brightness ramp"
            style={styles.select}
          >
            <option value="">flat colour</option>
            {lookupTables.map((name) => (
              <option key={name} value={name}>
                {name} {LUT_DESCRIPTIONS[name] || ""}
              </option>
            ))}
          </select>
          <output style={styles.value} />
        </label>
      )}
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
  onGroupOpacity,
  onGroupMove,
  onOpenStore,
  onCloseGroup,
  busy = false,
  notice = null,
}) {
  const [openSwatch, setOpenSwatch] = React.useState(null);
  const [collapsed, setCollapsed] = React.useState({});
  const [dragging, setDragging] = React.useState(null);

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
    const { visible, color } = state[index];
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
          <button
            onClick={() => setOpenSwatch(openSwatch === index ? null : index)}
            style={{ ...styles.swatch, background: css(color) }}
            title="The colour this channel is drawn in"
            aria-label={`colour ${layer.name}`}
          />
          <span style={styles.name} title={layer.name}>
            {layer.name}
          </span>
          {openSwatch === index && (
            <div style={styles.palette}>
              {PALETTE.map((entry) => (
                <button
                  key={entry.name}
                  onClick={() => {
                    onColor(index, entry.rgb);
                    setOpenSwatch(null);
                  }}
                  style={{ ...styles.paletteDot, background: css(entry.rgb) }}
                  title={entry.name}
                  aria-label={`${entry.name} for ${layer.name}`}
                />
              ))}
            </div>
          )}
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
        <div style={styles.loadBox}>
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
      {mode === "volume" && (
        <div style={styles.loadBox}>
          <VolumeMode
            volumeMode={volumeMode}
            onVolumeMode={onVolumeMode}
            gain={volumeGain}
            onGain={onVolumeGain}
            attenuation={volumeAttenuation}
            onAttenuation={onVolumeAttenuation}
            depthSamples={depthSamples}
            onDepthSamples={onDepthSamples}
          />
        </div>
      )}
      {layers[selected] && state[selected] && (
        <ChannelControls
          layer={layers[selected]}
          index={selected}
          entry={state[selected]}
          mode={mode}
          lookupTables={lookupTables}
          onWindow={onWindow}
          onOpacity={onOpacity}
          onLut={onLut}
          displayScales={displayScales}
          onDisplayScales={onDisplayScales}
        />
      )}
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
        const settings = groupState[group] || { visible: true, opacity: 1 };
        const isCollapsed = collapsed[group];
        // A group with no name is a store that carried no acquisition type in its
        // filename. It still needs to appear, so its rows are shown plainly with
        // no header rather than hidden under an empty heading.
        if (!group) return <div key="ungrouped">{members.map(renderRow)}</div>;
        return (
          <div
            key={group}
            style={{
              ...styles.group,
              ...(dragging === position ? styles.groupDragging : null),
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              onGroupMove?.(dragging, position);
              setDragging(null);
            }}
          >
            <div style={styles.groupHead}>
              {/* Dragging a group up or down changes which acquisition type is
                  drawn on top of which, so this is a real control. */}
              {/* Only the grip starts a drag. With the whole group draggable,
                  taking hold of a slider inside it began dragging the group
                  instead of moving the handle -- so the sliders could not be
                  used at all in some browsers. */}
              <span
                style={styles.grip}
                title="Drag to change what is drawn on top"
                draggable
                onDragStart={() => setDragging(position)}
                onDragEnd={() => setDragging(null)}
              >
                ⠿
              </span>
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
              <span style={styles.groupCount}>{members.length}</span>
              {onCloseGroup && (
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
            <label style={styles.control}>
              <span
                style={styles.controlLabel}
                title="Dim this whole acquisition at once, keeping the channels in balance"
              >
                group
              </span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={settings.opacity}
                onChange={(event) => onGroupOpacity?.(group, Number(event.target.value))}
                aria-label={`opacity group ${group}`}
                style={styles.range}
              />
              <output style={styles.value}>{Math.round(settings.opacity * 100)}%</output>
            </label>
            {!isCollapsed && <div style={styles.members}>{members.map(renderRow)}</div>}
          </div>
        );
      })}
      </div>
    </section>
  );
}

// -- how it all looks ---------------------------------------------------------

// What separates one block of the bar from the next: a rule, and enough room on
// either side of it that the eye reads two sections rather than one long list.
const BLOCK = {
  borderBottom: "1px solid #2b3440",
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
  loadBox: { ...BLOCK, flexShrink: 0 },
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
  groupDragging: { opacity: 0.5, background: "#1a2029" },
  groupHead: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "7px 12px 3px",
    cursor: "grab",
  },
  grip: { color: "#4c5764", cursor: "grab", fontSize: 12, userSelect: "none" },
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
  groupCount: { color: "#5c6673", fontSize: 10, fontVariantNumeric: "tabular-nums" },
  // Channels are indented so it reads as "these belong to that acquisition".
  members: { paddingLeft: 8, borderLeft: "2px solid #1f2630", marginLeft: 14 },
  // The list of images has the bar's leftover height and scrolls inside it, so a
  // run with many acquisitions never pushes the targets off the bottom.
  list: { flex: 1, minHeight: 90, overflowY: "auto" },
  panel: {
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    // Inside the single right-hand bar now, so it takes the bar's width and
    // shares the height with the targets list below it.
    flex: 1,
    background: "#12161c",
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
  // Above the list of channels, which is where napari puts the controls for the
  // selected layer. Anyone arriving from napari looks there first, and the two
  // things that belong together -- the name of the channel being adjusted and the
  // controls adjusting it -- end up next to each other rather than at opposite
  // ends of the bar.
  controls: { ...BLOCK, paddingBottom: 12, background: "#141922", flexShrink: 0 },
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
  swatch: { width: 13, height: 13, borderRadius: 3, border: "1px solid #39424e", cursor: "pointer", padding: 0 },
  name: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  palette: {
    position: "absolute",
    left: 34,
    top: 26,
    zIndex: 20,
    display: "flex",
    gap: 4,
    padding: 5,
    background: "#1b212a",
    border: "1px solid #2f3843",
    borderRadius: 5,
    boxShadow: "0 2px 8px rgba(0,0,0,.6)",
  },
  paletteDot: { width: 15, height: 15, borderRadius: 3, border: "1px solid #39424e", cursor: "pointer", padding: 0 },
  histogramRow: {
    display: "grid",
    gridTemplateColumns: "1fr 42px",
    alignItems: "end",
    gap: 7,
    padding: "1px 12px 4px 60px",
  },
  histogram: {
    display: "block",
    width: "100%",
    height: 28,
    color: "#53657a",
    background: "#0d1015",
    border: "1px solid #202731",
    borderRadius: 3,
  },
  autoButton: {
    padding: "4px 5px",
    border: "1px solid #303a46",
    borderRadius: 4,
    background: "#1b222b",
    color: "#aab4c0",
    font: "600 10px/1 system-ui, sans-serif",
    cursor: "pointer",
  },
  control: {
    display: "grid",
    // The label column is sized to the longest label (BRIGHTNESS); anything
    // narrower lets the text run underneath the slider beside it.
    gridTemplateColumns: "68px 1fr 42px",
    alignItems: "center",
    gap: 6,
    padding: "2px 12px",
    color: "#7f8a98",
    fontSize: 10,
  },
  controlLabel: { textTransform: "uppercase", letterSpacing: ".04em" },
  range: { width: "100%", accentColor: "#2f81f7", cursor: "pointer" },
  value: { color: "#aab4c0", textAlign: "right", fontVariantNumeric: "tabular-nums" },
};
