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
 * and refresh, and receives positions.
 *
 * ## A read that never comes back
 *
 * The pretend instrument answers the moment it is asked. A real one does not
 * always answer at all: reading the stage through the CAM API can hang, which
 * is the whole reason this driver has log-reading alternatives. A watch built
 * on the pretend instrument's manners waits for that answer forever — the
 * clock is only wound again when a read finishes — and the mark on the canvas
 * silently stops following the stage, with nothing on the page to say why.
 *
 * So a read is given only so long to answer. Past that it is abandoned, said
 * to be a failure, and the clock is wound anyway. The pretend backend never
 * comes near the limit, which is the point: the page behaves the same on both,
 * rather than working on one and freezing on the other.
 */

/** How often the stage is asked where it is, while the session is open. */
export const EVERY_MS = 5000;

/**
 * How long a single reading is given to answer.
 *
 * Comfortably longer than a healthy read and comfortably shorter than the
 * clock, so a slow instrument is waited for and a hung one does not cost the
 * next reading its turn.
 */
export const PATIENCE_MS = 2500;

/**
 * Start watching. `backend.get_xyz()` answers `{x: {value}, y: {value}, z: {value}}`
 * in micrometres; `onPosition({x, y, z})` receives each reading. Returns the
 * handle: `refresh()` reads now (after a move the page made), `stop()` ends
 * the watch — after which no more positions arrive, even from a read that was
 * still in flight.
 */
export function watchStagePosition(backend, onPosition, {
  every = EVERY_MS, patience = PATIENCE_MS, onError,
} = {}) {
  let stopped = false;
  let timer = null;
  let inFlight = null;

  /** One reading, abandoned if it takes longer than the instrument should. */
  const ask = () => {
    let waiting = null;
    const tooLong = new Promise((_, giveUp) => {
      waiting = setTimeout(
        () => giveUp(new Error(`the stage did not say where it is within ${patience} ms`)),
        patience,
      );
    });
    return Promise.race([backend.get_xyz(), tooLong])
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
      .finally(() => clearTimeout(waiting));
  };

  /**
   * The reading the clock takes. One at a time: a second turn of the clock
   * while the first is still out waits for it rather than asking again.
   */
  const read = () => {
    if (stopped) return Promise.resolve(null);
    inFlight ??= ask().finally(() => { inFlight = null; });
    return inFlight;
  };

  const schedule = () => {
    if (stopped) return;
    timer = setTimeout(() => { read().then(schedule); }, every);
  };

  read().then(schedule);

  return {
    /**
     * Where the stage is *now*, asked now.
     *
     * A reading of its own rather than whichever one the clock happens to have
     * out. This is what the page calls the moment it has moved the stage, or
     * when an operator ties an alignment point to where they have just driven
     * to; handed a reading that was already in flight, the point would be tied
     * to where the stage was up to five seconds before the drive ended — and,
     * if that reading were one of the hanging ones, to nothing at all.
     */
    refresh: () => (stopped ? Promise.resolve(null) : ask()),
    stop: () => {
      stopped = true;
      clearTimeout(timer);
      timer = null;
    },
  };
}
