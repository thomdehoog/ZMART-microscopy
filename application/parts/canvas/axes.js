/**
 * The two sliders under the picture: through the stack (Z) and along the
 * timelapse (T).
 *
 * A target acquisition can come back as a z-stack, as a time series, or as
 * both, and then the picture has more than one plane, or more than one
 * moment, to show. Each slider stands only while the picture has such a
 * choice: a flat, single-moment picture shows neither, so the canvas is
 * never asked to find room for a control that does nothing.
 *
 * Each row also has a play button: pressed, the slider walks by itself,
 * round to the start at the end, until pressed again. Z and T play
 * independently.
 *
 * The picture engine is what knows the extent: `theDepthItCanShow()` answers
 * in micrometres (or nothing, for a single plane), `theMomentsItCanShow()`
 * in moments counted from the first (or nothing, for a single moment). The
 * sliders read those and hand back `setPlane(um)` and `setMoment(t)`.
 */

/**
 * Wire the two slider rows to the picture.
 *
 * @param parts the elements: `axes` (the block holding both rows), `axisZ`,
 *   `plane`, `planeReadout`, `axisT`, `moment`, `momentReadout`.
 * @param picture a function answering the open picture engine, or null while
 *   there is none. Asked fresh on every refresh, since the picture is
 *   reopened when the run grows a new kind of scan.
 * @returns `{ refresh }`: ask the picture again and show, size and place the
 *   sliders accordingly. Call it whenever the picture opens, closes or
 *   changes what it draws.
 */
export function mountTheAxes(parts, { picture, watchEveryMs = 1000, playEveryMs = { plane: 120, moment: 350 } }) {
  const { axes, axisZ, plane, planePlay, planeReadout, axisT, moment, momentPlay, momentReadout } = parts;
  let depth = null;
  let moments = null;

  /* A drag asks oftener than a frame is drawn; only the last ask in any
     frame reaches the engine, the way the canvas's own plane control does. */
  const frame = globalThis.requestAnimationFrame ?? ((tick) => setTimeout(tick, 16));
  let wanted = null;
  let pending = false;
  const soon = (go) => {
    wanted = go;
    if (pending) return;
    pending = true;
    frame(() => {
      pending = false;
      const now = wanted;
      wanted = null;
      now?.();
    });
  };

  const fill = (slider) => {
    const low = Number(slider.min), high = Number(slider.max);
    slider.style?.setProperty?.("--fill", `${((Number(slider.value) - low) / (high - low || 1)) * 100}%`);
  };

  const sayPlane = (um) => {
    if (!depth) return;
    const step = depth.stepUm || 1;
    const which = Math.round((um - depth.lowUm) / step);
    const many = Math.round((depth.highUm - depth.lowUm) / step) + 1;
    planeReadout.textContent = `${Math.round(um)} µm · plane ${which + 1} of ${many}`;
    fill(plane);
  };
  const sayMoment = (t) => {
    if (!moments) return;
    momentReadout.textContent = `moment ${t + 1} of ${moments.many}`;
    fill(moment);
  };

  const goToPlane = (um) => { sayPlane(um); soon(() => picture()?.setPlane?.(um)); };
  const goToMoment = (t) => { sayMoment(t); soon(() => picture()?.setMoment?.(t)); };
  plane.addEventListener("input", () => goToPlane(Number(plane.value)));
  moment.addEventListener("input", () => goToMoment(Number(moment.value)));

  /* Play: the slider walks by itself, one step at a time, round to the
     start when it reaches the end, until it is pressed again. Z and T each
     have their own, so a stack can play while the moment stands still and
     the other way round. */
  const playing = { plane: null, moment: null };
  const player = (key, button, slider, go) => {
    const say = () => button?.setAttribute("aria-pressed", String(Boolean(playing[key])));
    const stop = () => { if (playing[key]) clearInterval(playing[key]); playing[key] = null; say(); };
    const start = () => {
      stop();
      playing[key] = setInterval(() => {
        const step = Number(slider.step) || 1;
        const next = Number(slider.value) + step;
        const value = next > Number(slider.max) + 1e-9 ? Number(slider.min) : next;
        slider.value = String(value);
        go(value);
      }, playEveryMs[key]);
      say();
    };
    button?.addEventListener("click", () => (playing[key] ? stop() : start()));
    return { stop };
  };
  const planePlayer = player("plane", planePlay, plane, goToPlane);
  const momentPlayer = player("moment", momentPlay, moment, goToMoment);

  function refresh() {
    const viewer = picture();
    depth = viewer?.theDepthItCanShow?.() ?? null;
    moments = viewer?.theMomentsItCanShow?.() ?? null;
    const deep = Boolean(depth && depth.highUm > depth.lowUm);
    if (deep) {
      plane.min = String(depth.lowUm);
      plane.max = String(depth.highUm);
      plane.step = String(depth.stepUm || 1);
      /* Where the picture already is, unless a hand is on the slider. */
      if (globalThis.document?.activeElement !== plane) plane.value = String(depth.atUm ?? depth.lowUm);
      sayPlane(Number(plane.value));
    }
    axisZ.hidden = !deep;
    if (!deep) planePlayer.stop();
    const long = Boolean(moments && moments.many > 1);
    if (long) {
      moment.min = "0";
      moment.max = String(moments.many - 1);
      moment.step = "1";
      if (globalThis.document?.activeElement !== moment) moment.value = String(moments.at ?? 0);
      sayMoment(Number(moment.value));
    }
    axisT.hidden = !long;
    if (!long) momentPlayer.stop();
    axes.hidden = !deep && !long;
  }

  /* A light watch on the picture. An engine learns how deep and how long
     its picture is only once the stores' descriptions have arrived, a
     moment after the picture is opened and after every field that lands,
     and nothing announces that. So the sliders look for themselves, now
     and then: once a second, and a redraw only when the answer
     has changed. */
  let seen = null;
  const look = () => {
    const viewer = picture();
    const now = JSON.stringify([
      Boolean(viewer), viewer?.theDepthItCanShow?.() ?? null, viewer?.theMomentsItCanShow?.() ?? null,
    ]);
    if (now === seen) return;
    seen = now;
    refresh();
  };
  const watching = watchEveryMs > 0 ? setInterval(look, watchEveryMs) : null;
  const stop = () => { if (watching) clearInterval(watching); planePlayer.stop(); momentPlayer.stop(); };

  return { refresh, stop };
}
