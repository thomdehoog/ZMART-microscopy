import React from "react";

// How long to rest on each plane while playing. Slow enough to see what is there,
// fast enough to read movement across a stack.
const PLAY_STEP_MS = 140;

// Read one named axis out of the engine's current coordinate space: where it can
// travel, and where it is now. Returns null when the image has no such axis --
// which is the normal answer for `t` on anything that is not a timelapse, and is
// exactly how the interface decides whether to offer a time slider at all.
function axisInfo(viewer, name) {
  const position = viewer?.navigationState.position;
  const space = position?.coordinateSpace.value;
  if (!space?.valid) return null;
  const index = space.names.indexOf(name);
  if (index < 0) return null;
  // Neuroglancer describes an axis by the real-valued extent the data covers, and
  // separately says whether a whole plane (or frame) sits *on* an integer
  // coordinate or halfway between two. Both conventions occur, and the slider has
  // to land exactly on the planes that exist -- one step too few and the last
  // plane of every stack is unreachable, one too many and the slider runs off the
  // end of the data.
  //
  // When centres are on integers the engine reports the extent shifted by half a
  // voxel (a 48-plane stack comes back as -0.5 to 47.5), so the planes are simply
  // the integers inside that range. When centres fall between integers the extent
  // is unshifted, so the reachable positions are the half-integers inside it.
  const integerCentres = space.bounds.voxelCenterAtIntegerCoordinates[index];
  const lower = space.bounds.lowerBounds[index];
  const upper = space.bounds.upperBounds[index];
  const min = integerCentres ? Math.ceil(lower) : Math.ceil(lower - 0.5) + 0.5;
  const max = integerCentres ? Math.floor(upper) : Math.floor(upper - 0.5) + 0.5;
  if (!Number.isFinite(min) || !Number.isFinite(max) || max < min) return null;
  return { index, min, max, value: position.value[index] };
}

/**
 * One slider that steps the view along a single axis of the image.
 *
 * Used twice: for `z`, to move through the planes of a stack, and for `t`, to
 * move through the frames of a timelapse. Both are the same job -- change one
 * number in the engine's position -- so they are the same control, and a store
 * that has no such axis simply gets no slider.
 */
export default function AxisSlider({
  viewer,
  axis: axisName,
  label,
  limit = null,
  orientation = "horizontal",
}) {
  const [axis, setAxis] = React.useState(null);
  const [playing, onPlay] = usePlayback(viewer, axisName, limit);

  React.useEffect(() => {
    if (!viewer) return undefined;
    const update = () => {
      const next = axisInfo(viewer, axisName);
      setAxis((current) =>
        current?.index === next?.index &&
        current?.min === next?.min &&
        current?.max === next?.max &&
        current?.value === next?.value
          ? current
          : next,
      );
    };
    // Three things can move this slider, and it listens for all three: the view
    // being moved (by the wheel, by dragging, or by this slider itself), the set
    // of axes changing because an image was opened or closed, and the engine
    // settling on where it is going to start. Between them the slider always
    // shows where the view actually is.
    //
    // It is worth saying what is deliberately *not* here. An earlier version also
    // re-read the position sixty times a second, as insurance against the engine
    // swapping the object holding it. Reading Neuroglancer's own source settles
    // that: it makes that object once, when the viewer is created, and never
    // replaces it. So the insurance was paying for nothing, sixty times a second,
    // on the same graphics card that is drawing the specimen.
    const stopWatchingView = viewer.navigationState.changed.add(update);
    const stopWatchingPosition = viewer.navigationState.position.changed.add(update);
    const stopWatchingAxes =
      viewer.navigationState.position.coordinateSpace.changed.add(update);
    update();
    return () => {
      stopWatchingView();
      stopWatchingPosition();
      stopWatchingAxes();
    };
  }, [viewer, axisName]);

  if (!axis) return null;
  // Never offer more steps than there is data for. A store is given its full
  // length in time when it is created, long before the run has produced that many
  // frames, so what the file claims and what exists are not the same thing.
  const reachable =
    limit != null && Number.isFinite(limit)
      ? { ...axis, max: Math.min(axis.max, axis.min + limit - 1) }
      : axis;
  if (reachable.max < reachable.min) return null;
  // The slider steps in halves rather than whole planes, and that is deliberate.
  // The engine opens a view in the *middle* of an axis, which for an even number
  // of planes lands halfway between two of them: a four-frame timelapse starts at
  // 1.5. A control that could only hold whole numbers would be unable to show
  // that, and the browser would quietly round the thumb to 2 while our code still
  // believed 1.5 -- after which dragging it to 2 would change nothing, because as
  // far as the browser was concerned it was already there. The slider would look
  // correct and do nothing at all. Halves can represent every position the engine
  // actually takes, so what is shown and what is meant never come apart.
  const value = Math.max(reachable.min, Math.min(reachable.max, reachable.value));
  const stepNumber = Math.round(value - reachable.min + 1);
  const count = Math.round(reachable.max - reachable.min + 1);
  const moveTo = (next) => {
    const current = viewer.navigationState.position.value;
    const moved = Float32Array.from(current);
    moved[reachable.index] = next;
    viewer.navigationState.position.value = moved;
  };

  // Only one plane or frame to look at is not a choice, so no control is offered.
  // This is how a still image ends up with no time slider and a single plane with
  // no Z slider, without anything having to know which is which.
  if (count < 2) return null;

  // Standing up rather than lying down. The two arrangements hold exactly the same
  // controls in the same order -- play, name, slider, where you are -- so only the
  // direction they run in changes.
  const upright = orientation === "vertical";

  return (
    <label style={upright ? styles.axisControlUpright : styles.axisControl}>
      <button
        type="button"
        onClick={onPlay}
        style={{ ...styles.play, ...(playing ? styles.playOn : null) }}
        aria-label={`play ${axisName}`}
        title={
          playing
            ? "Stop"
            : `Step through ${axisName === "t" ? "the frames" : "the planes"} one after another`
        }
      >
        {playing ? "❙❙" : "▶"}
      </button>
      <span style={styles.axisLabel}>{label}</span>
      <input
        type="range"
        min={reachable.min}
        max={reachable.max}
        step={0.5}
        value={value}
        onChange={(event) => moveTo(Number(event.target.value))}
        aria-label={`${axisName} position`}
        style={upright ? styles.axisRangeUpright : styles.axisRange}
        // Browsers do not agree on how a slider is stood on end. Firefox reads
        // this attribute; the others read the writing direction in the style
        // beside it. Giving both means the control is upright everywhere rather
        // than lying on its side in half of them.
        {...(upright ? { orient: "vertical" } : null)}
      />
      <output aria-label={`${axisName} position value`} style={styles.axisValue}>
        {stepNumber} / {count}
      </output>
    </label>
  );
}

/**
 * Step an axis along on its own, the way a film is played.
 *
 * Looking through a stack or a timelapse by hand is a poor way to see movement,
 * and movement is often the whole point — a specimen drifting, a marker
 * brightening. This walks one step at a time and wraps round at the end, so it
 * loops rather than stopping at the last frame.
 *
 * It moves the engine's position and nothing else, so everything already
 * following the position — the slider, the image — comes along without being
 * told. The step rate is a compromise: fast enough to read as motion, slow
 * enough that the engine has a chance to fetch each plane as it arrives.
 */
function usePlayback(viewer, axisName, limit) {
  const [playing, setPlaying] = React.useState(false);

  React.useEffect(() => {
    if (!playing || !viewer) return undefined;
    const step = () => {
      const axis = axisInfo(viewer, axisName);
      if (!axis) return;
      const top =
        limit != null && Number.isFinite(limit)
          ? Math.min(axis.max, axis.min + limit - 1)
          : axis.max;
      const next = axis.value + 1 > top ? axis.min : axis.value + 1;
      const position = viewer.navigationState.position;
      const moved = Float32Array.from(position.value);
      moved[axis.index] = next;
      position.value = moved;
    };
    const timer = setInterval(step, PLAY_STEP_MS);
    return () => clearInterval(timer);
  }, [playing, viewer, axisName, limit]);

  // Playing an axis the image no longer has would be a control quietly doing
  // nothing, so it stops itself if the axis goes away with the image.
  React.useEffect(() => {
    if (playing && viewer && !axisInfo(viewer, axisName)) setPlaying(false);
  }, [playing, viewer, axisName]);

  return [playing, () => setPlaying((on) => !on)];
}

const styles = {
  axisControl: {
    display: "grid",
    gridTemplateColumns: "22px 16px 1fr 74px",
    alignItems: "center",
    gap: 8,
    padding: "8px 12px",
    border: "1px solid #2c333d",
    borderRadius: 7,
    background: "rgba(12, 15, 19, .82)",
    boxShadow: "0 2px 10px rgba(0,0,0,.6)",
    color: "#f2f5f8",
    font: "600 11px/1 system-ui, sans-serif",
  },
  // The same control stood on end. It is laid out as rows rather than columns and
  // fills the height it is given, so the slider itself is as long as there is room
  // for -- which is what makes a deep stack comfortable to move through.
  axisControlUpright: {
    display: "grid",
    gridTemplateRows: "22px 16px 1fr auto",
    justifyItems: "center",
    alignItems: "center",
    gap: 8,
    padding: "12px 8px",
    height: "100%",
    // Counting the border and the padding as part of that height, rather than as
    // extra on top of it. Without this the control is taller than the room it was
    // given and the reading at the foot of it falls outside the panel.
    boxSizing: "border-box",
    border: "1px solid #2c333d",
    borderRadius: 7,
    background: "rgba(12, 15, 19, .82)",
    boxShadow: "0 2px 10px rgba(0,0,0,.6)",
    color: "#f2f5f8",
    font: "600 11px/1 system-ui, sans-serif",
  },
  axisLabel: { color: "#f2f5f8" },
  axisRange: { width: "100%", accentColor: "#2f81f7", cursor: "pointer" },
  axisRangeUpright: {
    // Running the control's text down the page rather than across is what turns a
    // slider on its end in browsers built on Chromium and WebKit. Reversing the
    // direction as well puts the first plane at the bottom, so moving the handle
    // up moves up through the stack, which is the way round it reads at the
    // microscope.
    writingMode: "vertical-lr",
    direction: "rtl",
    height: "100%",
    width: 22,
    accentColor: "#2f81f7",
    cursor: "pointer",
  },
  axisValue: {
    textAlign: "right",
    color: "#e6edf3",
    fontVariantNumeric: "tabular-nums",
  },
  play: {
    width: 22,
    border: "1px solid #3a444f",
    borderRadius: 4,
    background: "rgba(255,255,255,.06)",
    color: "#e6edf3",
    font: "9px/1 system-ui, sans-serif",
    padding: "3px 0",
    cursor: "pointer",
  },
  playOn: { background: "#2f81f7", color: "#fff", borderColor: "#2f81f7" },
};
