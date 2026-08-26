/**
 * Where the stage is — a process of its own, running for as long as the
 * session is open.
 *
 * The red cross on the canvas is not a stored fact the page keeps right; it
 * is read from the instrument (`get_xyz` through the backend) and placed
 * where the reading says. This does that on a clock, every five seconds,
 * and again at once whenever the page has moved the stage itself, so the
 * mark never shows where the stage was told to go but where it is.
 *
 * It is kept apart from the rest of the page on purpose: one place owns
 * "ask the instrument where the stage is", the page only says start, stop
 * and refresh, and receives positions. Two watchers can never run at once;
 * a refresh while a read is in flight simply waits for that read.
 */

/** How often the stage is asked where it is, while the session is open. */
export const EVERY_MS = 5000;

/**
 * Start watching. `backend.xyz()` answers `{x: {value}, y: {value}, z: {value}}`
 * in micrometres; `onPosition({x, y, z})` receives each reading. Returns the
 * handle: `refresh()` reads now (after a move the page made), `stop()` ends
 * the watch — after which no more positions arrive, even from a read that was
 * still in flight.
 */
export function watchStagePosition(backend, onPosition, { every = EVERY_MS, onError } = {}) {
  let stopped = false;
  let timer = null;
  let inFlight = null;

  const read = () => {
    if (stopped) return Promise.resolve(null);
    inFlight ??= backend.xyz()
      .then((xyz) => {
        if (stopped || !xyz?.x || !xyz?.y) return null;
        const at = { x: Number(xyz.x.value), y: Number(xyz.y.value), z: Number(xyz.z?.value ?? 0) };
        onPosition(at);
        return at;
      })
      .catch((why) => {
        if (!stopped) onError?.(why);
        return null;
      })
      .finally(() => { inFlight = null; });
    return inFlight;
  };

  const schedule = () => {
    if (stopped) return;
    timer = setTimeout(() => { read().then(schedule); }, every);
  };

  read().then(schedule);

  return {
    refresh: () => read(),
    stop: () => {
      stopped = true;
      clearTimeout(timer);
      timer = null;
    },
  };
}
