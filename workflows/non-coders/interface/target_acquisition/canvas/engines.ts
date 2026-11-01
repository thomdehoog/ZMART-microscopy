/**
 * The drawing engines the canvas opens, by name.
 *
 * An engine is a folder holding a `viewer.ts` that exports one function,
 * `openViewer`, and the page reaches it through that function and nothing else
 * (`docs/viewer-slot.md`). Each is loaded only when it is first asked for: an
 * engine is a large thing to fetch, and a page with nothing to draw has no use
 * for one.
 *
 * ## Neuroglancer, and what it costs to have it here
 *
 * Neuroglancer hands the fetching and the unpacking of image pieces to
 * background programs, and a browser will only start one of those from a file
 * of its own, never from something folded into the page. So what is copied to
 * the microscope is one small folder rather than one file: the page, and
 * neuroglancer's two background programs beside it. `docs/building-the-page.md`
 * records what was tried and why, and `vite.config.js` is where the build makes
 * it happen.
 *
 * Two things follow. A page opened straight off the disk — a `file:///…`
 * address — cannot start a background program, so neuroglancer draws only in a
 * page served over HTTP; the `zmart-interface` window serves it. And whether the
 * two programs were copied along with the page cannot be checked here: if they
 * are missing the box stays black, and what catches that is a photograph of the
 * built page, in `workflows/target_acquisition/the-built-page.spec.ts`.
 */

/** An engine's one export. */
type OpenViewer = typeof import("./engines/neuroglancer-under/viewer.ts")["openViewer"];

const HOW_TO_OPEN: Record<string, () => Promise<{ openViewer?: OpenViewer }>> = {
  "neuroglancer-under": () => import("./engines/neuroglancer-under/viewer.ts"),
};

/**
 * Load one engine by name and hand back its `openViewer`.
 *
 * @throws if there is no engine of that name, or its file does not export
 *   `openViewer` — said plainly, with the list of what there is, rather than
 *   leaving an empty box on screen.
 */
export async function openerFor(name: string): Promise<OpenViewer> {
  const load = HOW_TO_OPEN[name];
  if (!load) {
    throw new Error(
      `there is no engine called "${name}" in this page. It was built with: ` +
        `${Object.keys(HOW_TO_OPEN).join(", ")}.`,
    );
  }
  const module = await load();
  if (typeof module.openViewer !== "function") {
    throw new Error(
      `the engine "${name}" does not export openViewer, which is the whole of ` +
        "the interface every engine has to implement. See docs/viewer-slot.md.",
    );
  }
  return module.openViewer;
}
