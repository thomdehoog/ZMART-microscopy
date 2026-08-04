/**
 * The brightness range an acquisition actually holds.
 *
 * Shared by every option, the way `gestures.js` is, and for the same reason: it
 * is not part of what is being compared. How an engine draws a picture is the
 * question; what range of numbers that picture contains is a fact about the file,
 * and two options answering it differently would be a difference in the results
 * table that had nothing to do with the engines.
 *
 * ## Why this exists at all
 *
 * An option is told what colours to draw a run in, or reads them from the run's
 * own description, and only if neither says anything does it have to decide for
 * itself. Deciding has been done badly twice.
 *
 * A fixed nought-to-4095 suits the twelve-bit cameras this project's own runs are
 * acquired on and is a poor guess for anybody else's: a light-sheet transfer sits
 * between about two hundred and fourteen hundred of a possible 65535, so it is
 * drawn in the bottom third of black. And the range of the *data type* — which is
 * what neuroglancer falls back to when it is told nothing — is worse still, since
 * a real acquisition occupies a small corner of what its container could hold.
 * Measured on one mesoSPIM tile, side by side at the same view: the option that
 * read the picture had 46% of its pixels above mid-grey, the one on the fixed
 * guess had 1%.
 *
 * Both of those are guesses about an instrument. The picture can simply be asked.
 *
 * ## Which numbers are asked, and why not the obvious ones
 *
 * One tile out of the middle of a **small** copy — a single chunk, the unit the
 * file is already stored in, so it is one request of the size the store itself
 * chose. Which copy is `theCopyToRead` below, and the reasoning is there: the
 * smallest that still holds enough numbers.
 *
 * **The sharpest copy was tried and is what an operator feels.** It is 1.5 MB for
 * the tile measured here, and read off a shared drive it took 5.65 seconds — paid
 * once per acquisition, every time one is opened, before anything is drawn. On a
 * folder of many acquisitions that is the difference between a viewer that opens
 * and one somebody gives up on.
 *
 * The middle of the image rather than a corner, because a run is imaged outward
 * from where the operator pointed it, so the middle is where the specimen is
 * likeliest to be. A tile that happens to hold nothing has no range and says so.
 *
 * **The middle in every direction, depth included**, which is `planes.js` beside
 * this file and not a decision taken here. Taking the first plane was tried and
 * is wrong in the one way that matters: on the tile measured above the first
 * plane holds 203 to 503 where the middle plane holds 609 to 23103, and a window
 * of 203 to 503 draws that specimen as a white rectangle. The window has to come
 * from the plane the operator is actually shown, which is why that rule is shared
 * with the options rather than kept here.
 *
 * ## Percentiles, not the smallest and the largest
 *
 * The obvious reading of a patch is its smallest and largest value, and it was
 * what this file did first. One saturated pixel is enough to ruin it. The tile
 * measured above holds tissue around 1750 and hot pixels at 65535, which gives a
 * window eleven times wider than the picture needs and a screen median of 12.9 —
 * **dimmer than the fixed guess this was written to replace**, which gives 108.7.
 * The first and ninety-ninth percentiles of the same pixels give 807 to 3921, and
 * a screen median of 76.9.
 *
 * That is the same conclusion the viewer's own backend reached for the same
 * reason; `backend/contrast.py` has it as percentiles over a histogram. The
 * arithmetic here is deliberately the plainer one — a patch is a fraction of the
 * size of the images that code measures, and it is read once while a viewer
 * opens.
 */

import { loadOmeZarr } from "@vivjs/loaders";

import { theMiddleOfEveryOtherAxis } from "./planes.js";

/** How much of each end of the picture is treated as outlying rather than signal. */
const SET_ASIDE_AT_EACH_END = 0.01;

/**
 * How many numbers are enough to describe a picture's range.
 *
 * Percentiles settle long before this: measured across all six copies of a
 * light-sheet tile, from 746 496 numbers down to 11 664, the window moved from
 * 807–3921 to 640–4054 and what reaches the screen moved from a median of 84 to
 * 89 — a difference nobody can see, for a read a sixty-fourth of the size.
 */
const ENOUGH_NUMBERS = 4096;

/**
 * Which copy of the image to read, out of the pyramid the store keeps.
 *
 * The smallest one that still holds enough numbers, because the read is the
 * whole cost: the sharpest copy of the tile above is 1.5 MB off a shared drive
 * and took 5.65 seconds, and every acquisition pays it as it opens.
 *
 * **This file used to say the smallest copy was the wrong answer, and that was
 * right about a different question.** Each coarser copy averages its neighbours,
 * so the extremes are pulled towards the middle — the top of that tile's pyramid
 * runs 199 to 208 where the sharpest runs 203 to 65535. That ruins the smallest
 * and the largest value, which is what this file used to take. It does not ruin a
 * percentile, which is asking where the bulk of the picture sits, and averaging
 * moves that hardly at all. The two changes belong together: taking percentiles
 * is what makes reading a coarse copy safe.
 */
function theCopyToRead(sources) {
  for (let level = sources.length - 1; level >= 0; level -= 1) {
    const source = sources[level];
    const across = source?.labels?.indexOf("x") ?? -1;
    const down = source?.labels?.indexOf("y") ?? -1;
    if (across < 0 || down < 0) continue;
    const tile = source.tileSize;
    const held = Math.min(tile, source.shape[across]) * Math.min(tile, source.shape[down]);
    if (held >= ENOUGH_NUMBERS) return source;
  }
  // Nothing in the pyramid holds enough, so the picture is a small one and its
  // sharpest copy is both the best answer and a cheap read.
  return sources[0];
}

/**
 * The window these pixels ask to be drawn through.
 *
 * @param {ArrayLike<number>} values one patch of the picture, in stored counts.
 * @returns {{low: number, high: number}|null} the window, or nothing when the
 *   patch holds a single value and there is no window to be had.
 */
export function theWindowThesePixelsAskFor(values) {
  const sorted = Float64Array.from(values ?? []).sort();
  if (!sorted.length) return null;
  const at = (share) => sorted[Math.round(share * (sorted.length - 1))];
  const low = at(SET_ASIDE_AT_EACH_END);
  const high = at(1 - SET_ASIDE_AT_EACH_END);
  if (high > low) return { low, high };
  /* Nearly every pixel being the same value is not the same as the picture
     holding one: a mostly empty tile with a small specimen in it lands here, and
     it is exactly the picture an operator most wants drawn. The percentiles have
     nothing left to say about it, so the whole of what was read is used, which is
     what this function did before percentiles and is still better than a guess
     about the camera. */
  const ends = { low: sorted[0], high: sorted[sorted.length - 1] };
  return ends.high > ends.low ? ends : null;
}

/**
 * The window an image asks for, from resolutions somebody has already opened.
 *
 * This is the one an option should call when it has the image in its hands
 * already, which the two Viv options do — Viv hands a store's resolutions back
 * when it opens it, so asking for the store a second time would be a second load
 * of the same thing.
 *
 * @param {Array<object>} sources the image's resolutions, sharpest first.
 * @returns {Promise<{low: number, high: number}|null>} what the picture holds,
 *   or nothing when it cannot be read or holds a single value — in which case
 *   the caller keeps whatever it would have used.
 */
export async function theRangeTheseSourcesHold(sources) {
  if (!sources?.length) return null;
  const reading = theCopyToRead(sources);
  if (!reading) return null;
  try {
    const selection = theMiddleOfEveryOtherAxis(reading.labels, reading.shape);

    // The tile in the middle, counted in tiles rather than in pixels, because
    // that is the unit the reader fetches in and the file is stored in.
    const across = reading.labels.indexOf("x");
    const down = reading.labels.indexOf("y");
    const tile = reading.tileSize;
    const middle = {
      x: Math.floor(reading.shape[across] / tile / 2),
      y: Math.floor(reading.shape[down] / tile / 2),
    };
    const patch = await reading.getTile({ x: middle.x, y: middle.y, selection });

    /* Nothing is invented when the picture is one flat value. The type it is
       stored in would give a range — nought to 65535 for a sixteen-bit image —
       but that is not a fact about the picture: cameras put eleven, twelve and
       fourteen-bit data into a sixteen-bit container all the time, so the
       container says almost nothing about what is in it. Guessing from the type
       is the same mistake as guessing from the camera, one step further back.
       The caller keeps whatever it had, and says nothing it cannot support. */
    return theWindowThesePixelsAskFor(patch?.data);
  } catch (whyNot) {
    /* An image that will not give up a piece of itself is not a reason to refuse
       to draw it — the caller keeps what it had and the picture still appears.
       But it is said out loud, because a silent fallback here looks exactly like
       a working one: the picture is drawn either way, only wrongly exposed, and
       nobody looking at a dim picture would think to suspect this. */
    console.warn("could not read the brightness range of an opened image", whyNot);
    return null;
  }
}

/**
 * The same, for an option that has only the address.
 *
 * Neuroglancer is that option: it reads a store's description in order to build
 * a layer and then keeps it to itself, so the only honest way for its adapter to
 * learn what the picture holds is to ask for the image itself.
 *
 * @param {string} url  the store's address; anything after a `|` is a reader's
 *   own suffix and is taken off, so an address written for one engine can be
 *   handed here unchanged.
 * @returns {Promise<{low: number, high: number}|null>} what the picture holds,
 *   or nothing, as above.
 */
export async function theRangeAStoreHolds(url) {
  const bar = url.indexOf("|");
  const address = (bar < 0 ? url : url.slice(0, bar)).replace(/\/+$/, "");
  try {
    const opened = await loadOmeZarr(address, { type: "multiscales" });
    return theRangeTheseSourcesHold(opened?.data);
  } catch (whyNot) {
    console.warn(`could not read the brightness range of ${address}`, whyNot);
    return null;
  }
}
