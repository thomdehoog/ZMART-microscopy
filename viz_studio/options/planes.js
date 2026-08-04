/**
 * Which plane of a stack to look at when nobody has said which.
 *
 * Shared by every option, the way `gestures.js` is, and for the same reason: it
 * is not part of what is being compared. Which engine draws a picture is the
 * question; which plane of the stack that picture is *of* is not, and two
 * options answering it differently do not compare — they draw different
 * pictures of the same store and every reading taken from them, brightness and
 * sharpness alike, is a reading of two different things.
 *
 * That is not a hypothetical. It was found on screen: `viv-under` opened every
 * acquisition at plane 0 while neuroglancer opened in the middle, and the two
 * columns of the operator page were photographed showing plainly different
 * pictures of one light-sheet tile.
 *
 * ## The fact this file holds
 *
 * **A stack's middle plane is where the specimen is; its first plane is its
 * edge.** Measured on `mesoSPIM_transfer_20260626_1700/…/Mag5_Tile0_Ch488…`, the
 * first plane holds 203 to 503 with a median of 317 — background and a little
 * flare — where the middle plane holds 609 to 23103 with a median of 1835 and
 * the structure an operator came to look at. Opened at the first plane, a
 * perfectly good acquisition looks empty and out of focus, which is exactly what
 * a failed one looks like.
 *
 * ## Two things ask it, and they have to agree
 *
 * Which plane an option opens on, and which plane `brightness.js` reads a
 * display window out of. A window measured on one plane and applied to another
 * describes a picture that is not on the screen, so both come from here.
 *
 * ## Time and colour are the exception, and take the first of each
 *
 * A run declares its whole length in time before it has recorded it, so the
 * middle moment of a timelapse is routinely one that nothing has been written
 * into yet — the same trap that makes a declared canvas measure as empty. And
 * the first colour is the one an option draws when it has been told nothing, so
 * any other would describe a picture that is not being shown.
 */

/** The axes whose middle is asked for; every other axis is asked for its first. */
const READ_THE_MIDDLE_OF = new Set(["z"]);

/**
 * Which index of each axis that is not on screen should be looked at.
 *
 * The two axes being drawn are left out, so that what comes back is exactly what
 * a reader wants for `selection` and what an option wants for the plane and the
 * moment it opens on.
 *
 * @param {string[]} labels the image's axis names, in order.
 * @param {number[]} shape how long the image is along each of them.
 * @returns {Object<string, number>} an index per axis that is not `x` or `y`.
 */
export function theMiddleOfEveryOtherAxis(labels, shape) {
  const selection = {};
  (labels || []).forEach((name, at) => {
    if (name === "x" || name === "y") return;
    const along = shape?.[at] ?? 1;
    selection[name] = READ_THE_MIDDLE_OF.has(name) ? Math.floor(along / 2) : 0;
  });
  return selection;
}
