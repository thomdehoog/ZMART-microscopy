/**
 * Which brightness window a channel opens with, and where it came from.
 *
 * Shared by every option, the way `brightness.js` and `gestures.js` are, and
 * for the same reason: which window a channel is *drawn through* is not part of
 * what the three engines are being compared on, and three copies of the rule
 * would drift.
 *
 * ## The rule, in order
 *
 * 1. **What the page said.** The operator's page may hand an engine a window
 *    for a channel — the run's declared window, or a measurement the panel
 *    made — and what it says is used exactly as given.
 * 2. **What the run declared.** A store's own description may carry a display
 *    window (`omero` → `window.start`/`end`), written only when the acquisition
 *    actually decided one.
 * 3. **What the pixels ask for.** Failing both, a small patch of the picture is
 *    read and a window taken from its percentiles (`brightness.js`). This is a
 *    measurement and is labelled as one.
 * 4. **Nothing.** A channel with no window is not drawn through a made-up one.
 *
 * ## What is deliberately gone
 *
 * There used to be a fifth step: a fixed nought-to-4095, "the range this viewer
 * has always used", which suited the twelve-bit cameras this project's own runs
 * came from. It is gone because it could not be told apart from a decision.
 * On the operator's canvas it drew every unresolved acquisition through a
 * window nobody chose, while the panel beside it — which had measured a
 * different window — showed its own numbers and never applied them: two
 * authorities, and the picture followed the wrong one. Now a channel that
 * nobody has given a window has none: the engine does not draw it, says so
 * through `layersForMeasurement` (`window: null`, `windowFrom: null`), and
 * draws it the moment the page hands one over through `setChannel`. On the
 * operator's page that moment is when the panel's measurement arrives.
 */

/**
 * The window to open a channel with, and its provenance.
 *
 * @param {{page?: {low:number, high:number}|null,
 *          store?: {low:number, high:number}|null,
 *          pixels?: () => Promise<{low:number, high:number}|null>}} offered
 *   what the page said, what the run declared, and how to read the pixels.
 *   Any of them may be missing.
 * @returns {Promise<{window: {low:number, high:number}|null,
 *                    from: "page"|"store"|"pixels"|null}>}
 */
export async function theWindowToOpenWith({ page = null, store = null, pixels = null } = {}) {
  if (isAWindow(page)) return { window: { low: page.low, high: page.high }, from: "page" };
  if (isAWindow(store)) return { window: { low: store.low, high: store.high }, from: "store" };
  if (typeof pixels === "function") {
    const read = await pixels();
    if (isAWindow(read)) return { window: { low: read.low, high: read.high }, from: "pixels" };
  }
  return { window: null, from: null };
}

/** A window is two finite numbers, the second above the first. */
export function isAWindow(candidate) {
  return Boolean(candidate)
    && Number.isFinite(candidate.low)
    && Number.isFinite(candidate.high)
    && candidate.high > candidate.low;
}
