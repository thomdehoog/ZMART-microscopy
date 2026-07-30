/**
 * The three options, listed in one place, chosen by a word in the address.
 *
 * The rule this file exists to keep is short: **somebody comparing three viewers
 * must be able to flip between them on the same data in the same second.** A
 * difference you can only see by rebuilding is a difference you will not see at
 * all, because nobody rebuilds between two glances at a picture.
 *
 * So every option is built into the one page and chosen at the moment it is
 * opened, with `?option=…`. Each is loaded only when it is asked for, so a page
 * opened on one option never pays for the other two — but all three are there,
 * and switching costs a page reload and nothing else.
 *
 * ## Adding the option you are here to add
 *
 * Add one line below. That is genuinely all: the page, the gestures, the
 * drawing, the measurements and the results table all work by name and need no
 * changes at all.
 *
 *     "viv-under": () => import("../../viv-under/viewer.js"),
 *
 * The module it points at must export exactly one thing, `openViewer`, with the
 * shape set out in `viz_studio/options/contract.md`. Nothing else may be public.
 * If your option needs a library that speaks in its own units, that conversion
 * belongs inside your module and must not appear in its interface — units are
 * micrometres everywhere above this line.
 */

const HOW_TO_OPEN = {
  "neuroglancer-under": () => import("../../neuroglancer-under/viewer.js"),
  // "viv-under": () => import("../../viv-under/viewer.js"),
  // "viv-inside": () => import("../../viv-inside/viewer.js"),
};

/** The options this page was built with, in the order they should be tried. */
export function optionsBuiltIn() {
  return Object.keys(HOW_TO_OPEN);
}

/**
 * Load one option by name and hand back its `openViewer`.
 *
 * An option that has not been built yet fails here with a message that says so
 * plainly and lists what there is, rather than leaving a blank page. A blank
 * page is the single most expensive failure this project keeps meeting, because
 * it looks exactly like a viewer that is still loading.
 */
export async function openerFor(name) {
  const load = HOW_TO_OPEN[name];
  if (!load) {
    throw new Error(
      `there is no option called "${name}" in this page. ` +
        `It was built with: ${optionsBuiltIn().join(", ") || "none at all"}. ` +
        "Add it to viz_studio/options/harness/src/options.js and build again.",
    );
  }
  const module = await load();
  if (typeof module.openViewer !== "function") {
    throw new Error(
      `the option "${name}" does not export openViewer, which is the whole of ` +
        "the interface every option has to implement. See " +
        "viz_studio/options/contract.md.",
    );
  }
  return module.openViewer;
}
