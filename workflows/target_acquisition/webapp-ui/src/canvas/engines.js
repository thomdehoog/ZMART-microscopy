/**
 * Which drawing engines this page can open the canvas with.
 *
 * The canvas is the picture of a run that the operator pans and zooms. It is
 * written more than once, one folder per drawing engine, and every one of them is
 * kept behind one small interface so that they can be compared fairly.
 * `zmart-viewer/parked/contract.md` sets that interface out in full; the short
 * version is that an engine is a folder holding a `viewer.js` which exports
 * exactly one function, `openViewer`, and the page reaches it through that
 * function and through nothing else.
 *
 * Keeping to that has a purpose worth stating, because it is easy to lose.
 * Viewers with different interfaces cannot be compared: any difference you notice
 * might be the engine, or might be the way somebody happened to wire that one up.
 * Viewers behind an identical interface, opened by the same page on the same run,
 * differ only in the thing being compared.
 *
 * Adding an engine is one line below **and one column of markup in
 * `index.html`**, which is one place more than this file used to promise. The
 * page now shows every engine at once rather than offering a chooser, so the
 * columns are written out rather than generated; whether to generate them from
 * `enginesOnOffer()` instead is an open question. The two gestures still need no
 * thought — a canvas arrives with dragging and the wheel already attached, every
 * engine sharing one piece of code for them.
 *
 * `zmart-viewer/parked/` also holds `viv-inside`, which this page no longer
 * offers: it drew the operator's layer inside the engine as a texture, so every
 * change to that layer cost an engine frame. It is still in the comparison there.
 *
 * ## Neuroglancer, and what it costs to have it here
 *
 * `viv-under` is ordinary JavaScript and lives entirely inside the page.
 * Neuroglancer does not: it hands the fetching and the unpacking of image pieces
 * to background programs, and a browser will only start one of those from a file
 * of its own.
 *
 * That matters here because this page is otherwise built into a single
 * self-contained file — one HTML document with everything folded inside it —
 * since the microscope computer has no build tools and no network, and one file
 * is what can simply be copied to it. The two cannot both hold, and the way it
 * was settled is that **what gets copied to the microscope is one small folder
 * rather than one file**: the page, and neuroglancer's two background programs
 * beside it.
 *
 * It was settled that way after trying the alternative properly. Folding the
 * background programs into the page was attempted and measured, and it fails in
 * two separate ways, the second of them silently — which is the kind of failure
 * this project keeps being caught by. `README.md` records what was tried and
 * what each attempt did, and `vite.config.js` is where the build makes the
 * chosen arrangement happen.
 *
 * ## Where the page is open from decides what it can offer
 *
 * There is a second consequence of neuroglancer needing background programs, and
 * it is the reason this file has two lists rather than one. A browser will not
 * start a background program for a page that was opened straight off the disk —
 * a `file:///…` address rather than an `http://…` one — because such a page has
 * no address for the program to belong to. It refuses outright, and the picture
 * would simply never appear.
 *
 * So {@link enginesBuiltIn} says what was built into this page, and
 * {@link enginesOnOffer} says which of those can actually work here and now.
 * Only the second is put in front of an operator, and {@link whyOneIsMissing}
 * gives the sentence that says what is absent and what to do about it. Offering
 * a button that cannot draw would be worse than offering nothing at all: a
 * picture that never arrives looks exactly like one that is still loading, and
 * that confusion has cost this project real days.
 *
 * The short version, for anyone about to look at the page: **open the built page
 * over HTTP if you want neuroglancer.** `python dev_window.py --build` does that
 * for you.
 *
 * One thing this file cannot check is whether the two background programs were
 * copied along with the page. If neuroglancer is chosen and they are missing,
 * {@link openerFor} still hands back a viewer and the box stays black, because
 * the failure happens out of reach inside the engine. What catches that is a
 * photograph of the built page, in `tests/viewer-built.spec.js`.
 */

/* The order matters in one small way: the page opens on the first of them unless
   the address says otherwise, so this list decides what an operator sees first.
   It is left as it was, with a Viv engine leading, because which engine should
   greet an operator is a decision about the product and not something to change
   quietly while adding one. */
const HOW_TO_OPEN = {
  "viv-under": () => import("../../../../../zmart-viewer/parked/viv-under/viewer.js"),
  "neuroglancer-under": () =>
    import("../../../../../zmart-viewer/parked/neuroglancer-under/viewer.js"),
};

/**
 * A sentence about each engine, shown beside the buttons that choose between
 * them, so that somebody looking at the picture knows what they are looking at.
 */
const WHAT_IT_IS = {
  "viv-under": "the picture underneath, the operator's own drawing on a second surface above it",
  "neuroglancer-under":
    "neuroglancer draws the picture underneath, the operator's own drawing on a " +
    "second surface above it",
};

/**
 * Which engines need a background program, and are therefore fussy about how the
 * page was opened. See the note at the top of this file.
 */
const NEEDS_A_BACKGROUND_PROGRAM = new Set(["neuroglancer-under"]);

/**
 * Was this page opened straight off the disk rather than served over HTTP?
 *
 * A page opened that way has an address beginning `file://`, and a browser gives
 * it no origin — which is what stops a background program from starting. The
 * check is deliberately about the address and nothing else: it needs no network,
 * no guessing and no waiting, and it is right before anything has been drawn.
 *
 * Written to survive being asked outside a browser, because the unit tests call
 * the functions below without one.
 */
function openedStraightOffTheDisk() {
  return globalThis.location?.protocol === "file:";
}

/** The engines this page was built with, in the order they should be offered. */
export function enginesBuiltIn() {
  return Object.keys(HOW_TO_OPEN);
}

/**
 * The engines that can actually draw, given how this page was opened.
 *
 * This is what the row of buttons is built from. It is the same list as
 * {@link enginesBuiltIn} whenever the page is served over HTTP, which is how an
 * operator will meet it; it is shorter when the page has been opened straight
 * off the disk.
 */
export function enginesOnOffer() {
  if (!openedStraightOffTheDisk()) return enginesBuiltIn();
  return enginesBuiltIn().filter((name) => !NEEDS_A_BACKGROUND_PROGRAM.has(name));
}

/**
 * One sentence saying which engines are not being offered and why, or `null`
 * when all of them are.
 *
 * Shown on the page beside the buttons. Somebody who came looking for an engine
 * and cannot find it deserves to be told where it went in the same glance.
 */
export function whyOneIsMissing() {
  const missing = enginesBuiltIn().filter((name) => !enginesOnOffer().includes(name));
  if (!missing.length) return null;
  return (
    `${missing.join(" and ")} cannot draw in a page opened straight off the ` +
    "disk, because a browser will not start the background program it needs " +
    "for one. Serve this folder over HTTP and it will be here — " +
    "`python dev_window.py --build` does that."
  );
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
        "zmart-viewer/parked/contract.md.",
    );
  }
  return module.openViewer;
}
