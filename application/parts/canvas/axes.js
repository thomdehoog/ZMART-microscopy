/**
 * The slider under the picture: along the timelapse (T).
 *
 * A target acquisition can come back as a time series, and then the picture
 * has more than one moment to show. The slider stands only while the picture
 * has such a choice. There is no way through a stack here: the operator's
 * picture is flat, every stack in it drawn as its projection.
 *
 * The row has a play button: pressed, the slider walks by itself, round to
 * the start at the end, until pressed again.
 *
 * The picture engine is what knows the extent: `theMomentsItCanShow()`
 * answers in moments counted from the first (or nothing, for a single
 * moment). The slider reads that and hands back `setMoment(t)`.
 */

/**
 * Wire the slider row to the picture.
 *
 * @param parts the elements: `axes` (the block holding the row), `axisT`,
 *   `moment`, `momentPlay`, `momentReadout`.
 * @param picture a function answering the open picture engine, or null while
 *   there is none. Asked fresh on every refresh, since the picture is
 *   reopened when the run grows a new kind of scan.
 * @returns `{ refresh, stop }`: ask the picture again and show, size and
 *   place the slider accordingly. Call `refresh` whenever the picture opens,
 *   closes or changes what it draws.
 */
export function mountTheAxes(parts, { picture, watchEveryMs = 1000, playEveryMs = 350 }) {
  const { axes, axisT, moment, momentPlay, momentReadout } = parts;
  let moments = null;

  /* A drag asks oftener than a frame is drawn; only the last ask in any
     frame reaches the engine. */
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

  const sayMoment = (t) => {
    if (!moments) return;
    momentReadout.textContent = `moment ${t + 1} of ${moments.many}`;
    fill(moment);
  };
  const goToMoment = (t) => { sayMoment(t); soon(() => picture()?.setMoment?.(t)); };
  moment.addEventListener("input", () => goToMoment(Number(moment.value)));

  /* Play: the slider walks by itself, one step at a time, round to the
     start when it reaches the end, until it is pressed again. */
  let playing = null;
  const say = () => momentPlay?.setAttribute("aria-pressed", String(Boolean(playing)));
  const stopPlaying = () => { if (playing) clearInterval(playing); playing = null; say(); };
  const startPlaying = () => {
    stopPlaying();
    playing = setInterval(() => {
      const next = Number(moment.value) + 1;
      const value = next > Number(moment.max) ? Number(moment.min) : next;
      moment.value = String(value);
      goToMoment(value);
    }, playEveryMs);
    say();
  };
  momentPlay?.addEventListener("click", () => (playing ? stopPlaying() : startPlaying()));

  function refresh() {
    const viewer = picture();
    moments = viewer?.theMomentsItCanShow?.() ?? null;
    const long = Boolean(moments && moments.many > 1);
    if (long) {
      moment.min = "0";
      moment.max = String(moments.many - 1);
      moment.step = "1";
      if (globalThis.document?.activeElement !== moment) moment.value = String(moments.at ?? 0);
      sayMoment(Number(moment.value));
    }
    axisT.hidden = !long;
    if (!long) stopPlaying();
    axes.hidden = !long;
  }

  /* A light watch on the picture. An engine learns how long its picture is
     only once the stores' descriptions have arrived, a moment after the
     picture is opened and after every field that lands, and nothing
     announces that. So the slider looks for itself, now and then: once a
     second, and a redraw only when the answer has changed. */
  let seen = null;
  const look = () => {
    const viewer = picture();
    const now = JSON.stringify([Boolean(viewer), viewer?.theMomentsItCanShow?.() ?? null]);
    if (now === seen) return;
    seen = now;
    refresh();
  };
  const watching = watchEveryMs > 0 ? setInterval(look, watchEveryMs) : null;
  const stop = () => { if (watching) clearInterval(watching); stopPlaying(); };

  return { refresh, stop };
}
