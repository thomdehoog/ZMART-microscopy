/**
 * What in a store's own description will stop a strict reader opening it.
 *
 * Shared by every option, the way `planes.js` is, and for the same reason: it is
 * a fact about the file rather than about a drawing engine.
 *
 * ## Why an application needs this at all
 *
 * The engines disagree about how much they will forgive, and the strict one does
 * not say what it objected to. Neuroglancer, handed a store it will not accept,
 * simply never finishes opening — no error, no rejected promise, nothing on the
 * console. All an application can do is wait, give up, and report a silence. An
 * operator then reads "not ready after twenty-five seconds", which tells them
 * their data is broken in some unspecified way, or that this software is.
 *
 * Both of the faults below were met on one real acquisition from another
 * laboratory: a 75 GB skin biopsy that Viv drew perfectly and neuroglancer would
 * not open at all. Each was enough on its own, and finding them meant building
 * stores that differed in exactly one thing and seeing which opened — an hour for
 * something the store could have said in a sentence.
 *
 * So this is that sentence. It does not decide anything and it does not repair
 * anything: it reads a description an application already has and says what a
 * strict reader will refuse, so the message on screen can name the cause.
 *
 * ## What is deliberately not here
 *
 * Anything only *suspected*. Big-endian data, an empty `filters` list, bare
 * `zstd`, nested chunk keys, five axes and unknown extra keys were all measured
 * and are all fine, so none of them is reported. A checker that guesses is worse
 * than no checker, because it sends whoever reads it to the wrong place.
 */

/** The one name the format asks for, and the spellings met instead. */
const THE_STANDARD_UNIT = "micrometer";
const WAYS_OF_WRITING_MICROMETRE = new Set(["um", "µm", "μm", "micron", "microns"]);

/**
 * @param {object} described a store's `.zattrs`, as it was read.
 * @returns {string[]} one sentence per thing a strict reader will refuse, each
 *   naming what was found and what the format asks for instead. Empty when
 *   nothing known is wrong — which does not promise the store will open, only
 *   that it is not failing for a reason anybody here has met before.
 */
export function whyAReaderMayRefuse(described) {
  const refusals = [];
  const named = new Set();
  for (const multiscale of described?.multiscales ?? []) {
    for (const axis of multiscale?.axes ?? []) {
      if (!WAYS_OF_WRITING_MICROMETRE.has(axis?.unit) || named.has(axis.unit)) continue;
      named.add(axis.unit);
      refusals.push(
        `its axes are measured in "${axis.unit}", and the format asks for ` +
        `"${THE_STANDARD_UNIT}"`,
      );
    }
  }
  const channels = described?.omero?.channels;
  if (Array.isArray(channels)
      && channels.some((channel) => channel && "window" in channel
                       && (channel.window === null || typeof channel.window !== "object"))) {
    refusals.push(
      "it describes a channel whose display window is empty; a window written as "
      + "nothing at all is refused where leaving it out would have been accepted",
    );
  }
  return refusals;
}
