/**
 * Which drawing engines this page can open the canvas with.
 *
 * The canvas is the picture of a run that the operator pans and zooms. It is
 * being written three times over, once for each of three drawing engines, and
 * all three are kept behind one small interface so that they can be compared
 * fairly. `viz_studio/options/contract.md` sets that interface out in full; the
 * short version is that an engine is a folder holding a `viewer.js` which
 * exports exactly one function, `openViewer`, and the page reaches it through
 * that function and through nothing else.
 *
 * Keeping to that has a purpose worth stating, because it is easy to lose. Three
 * viewers with three different interfaces cannot be compared: any difference you
 * notice might be the engine, or might be the way somebody happened to wire that
 * one up. Three viewers behind an identical interface, opened by the same page
 * on the same run, differ only in the thing being compared.
 *
 * Adding an engine is one line below. Nothing else in this page needs to change:
 * the panel, the two gestures and the little row of buttons that chooses between
 * engines all work by name.
 *
 * ## The third engine, and why it is not here
 *
 * There are three engines in `viz_studio/options/`. Only two of them are in this
 * list, and the reason is a real limitation rather than an oversight.
 *
 * The missing one, `neuroglancer-under`, does part of its work in a background
 * program that the browser has to fetch as a file of its own. This operator page
 * is built into a single self-contained file — one HTML document with everything
 * folded inside it — because the microscope computer has no build tools and no
 * network, and the Python server simply hands that one file out. A background
 * program folded into the page that way has no address of its own, so the
 * requests it makes for pieces of image cannot be resolved: the description of a
 * run loads and the pixels never do, which looks exactly like a slow viewer and
 * is in fact a broken one.
 *
 * So the two engines that draw with Viv and deck.gl are offered here, and the
 * third stays where it can be measured properly, in `viz_studio/options/`. If it
 * is ever wanted inside the operator window, the thing to change is how this
 * page is delivered to the microscope, not this file.
 */

const HOW_TO_OPEN = {
  "viv-under": () => import("../../../../../viz_studio/options/viv-under/viewer.js"),
  "viv-inside": () => import("../../../../../viz_studio/options/viv-inside/viewer.js"),
};

/**
 * A sentence about each engine, shown beside the buttons that choose between
 * them, so that somebody looking at the picture knows what they are looking at.
 */
const WHAT_IT_IS = {
  "viv-under": "the picture underneath, the operator's own drawing on a second surface above it",
  "viv-inside": "one surface, with the picture and the operator's own drawing as layers in it",
};

/** The engines this page was built with, in the order they should be offered. */
export function enginesBuiltIn() {
  return Object.keys(HOW_TO_OPEN);
}

/** One plain sentence saying how the named engine goes about its work. */
export function describeEngine(name) {
  return WHAT_IT_IS[name] ?? "";
}

/**
 * Load one engine by name and hand back its `openViewer`.
 *
 * @param name one of the names {@link enginesBuiltIn} gives back.
 * @returns the function that opens a viewer, which the panel then calls.
 * @throws if there is no engine of that name in this page, or if the file it
 *   points at does not export `openViewer`. Both are said plainly, with the list
 *   of what there is, rather than leaving an empty box on screen. A blank
 *   picture is the most expensive failure this project keeps meeting, because it
 *   looks exactly like a picture that is still loading.
 */
export async function openerFor(name) {
  const load = HOW_TO_OPEN[name];
  if (!load) {
    throw new Error(
      `there is no engine called "${name}" in this page. It was built with: ` +
        `${enginesBuiltIn().join(", ") || "none at all"}. Add it to ` +
        "src/canvas/engines.js and build again.",
    );
  }
  const module = await load();
  if (typeof module.openViewer !== "function") {
    throw new Error(
      `the engine "${name}" does not export openViewer, which is the whole of ` +
        "the interface every engine has to implement. See " +
        "viz_studio/options/contract.md.",
    );
  }
  return module.openViewer;
}
