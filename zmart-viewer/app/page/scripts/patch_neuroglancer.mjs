/**
 * The one patch this repository maintains against its pinned Neuroglancer.
 *
 * It says one thing: **a refresh should replace pixels, not remove them.**
 *
 * Neuroglancer refreshes a chunk source by re-queueing its chunks and then
 * telling the page to drop every chunk it holds. Between the drop and the
 * refetch there is nothing left to draw, so the picture empties and refills.
 * On a static dataset that never happens; on a live acquisition it happens on
 * every commit, and the operator watches the specimen flash.
 *
 * Two edits, both to stock functions, both a few lines:
 *
 * - **worker** (`lib/chunk_manager/backend.js`) — `invalidateSourceCache`
 *   keeps its re-queue loop exactly as it is and no longer sends the page the
 *   key-less "drop your whole copy of this source" message. The stale pixels
 *   keep drawing while the fresh bytes download.
 * - **page** (`lib/chunk_manager/frontend.js`) — when those fresh bytes
 *   arrive for a chunk the page already holds, they are written INTO the held
 *   object rather than replacing it, so the render layer's reference stays
 *   valid and the ordinary state transition uploads the new texture.
 *
 * Nothing is added: no new RPC, no parallel refresh machinery, no per-chunk
 * bookkeeping. Both edits are inside functions Neuroglancer already has, and
 * both are improvements to it rather than accommodations of us — which is the
 * point, because this is meant to be sendable upstream and read in a minute.
 *
 * The gate that holds it is `tests/test_the_screen_never_goes_black.py`,
 * which measured the fault it cures: one whole frame at 0% lit, about 17 ms,
 * invisible to a screenshot and plain to the eye.
 *
 * **Worker patches target the module AND the compiled bundle, and the build
 * runs this AFTER precompiling.** The precompile step flattens the worker's
 * import stub into a self-contained bundle ON ITS FIRST RUN and thereafter
 * recompiles that flattened bundle — module changes never enter the worker
 * again. That cost a night once: patch generations that ran only in the
 * module files while the worker executed the first-ever compile, and every
 * measurement of them was a measurement of nothing. On a fresh install the
 * postinstall patches the modules, the first precompile carries them into the
 * bundle, and the bundle entries here find their markers already present.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, "..", "node_modules", "neuroglancer", "lib");
const workerBundle = join(lib, "chunk_worker.bundle.js");

// On a fresh install the worker bundle is still Neuroglancer's un-flattened
// import stub: the compiled bundle only comes into being when the build's
// precompile step runs. Demanding the bundle's anchors at postinstall time
// therefore failed every clean `npm ci` -- the anchors cannot exist yet.
// So postinstall runs with --modules-only and patches just the module files,
// which the first precompile then carries into the bundle it creates; the
// full pass, bundle checks included, runs during `npm run build` where the
// bundle really exists and a missing anchor really is a version change.
const modulesOnly = process.argv.includes("--modules-only");

// An older generation of this patch added parallel refresh machinery beside
// the stock function instead of correcting it: a named-chunk RPC, a per-key
// pump, a probe, and an override that took the whole-source refresh away from
// `invalidateSourceCache` altogether. A tree still carrying that would end up
// with both, and the override would win, so this refuses rather than pretends.
const SUPERSEDED = "zmartPumpRefreshesWithoutDeadline";

const PATCHES = [
  {
    file: join(lib, "chunk_manager", "backend.js"),
    also: workerBundle,
    // This edit REMOVES a line, so there is nothing new to look for -- and a
    // comment could not do the job anyway: esbuild strips comments when it
    // flattens the worker bundle, so a comment marker is present in the module
    // and absent in the bundle built from it. The line's absence is the mark.
    gone: `this.rpc.invoke("Chunk.update", { source: source.rpcId });`,
    // The line is unique in both the module and the compiled worker bundle,
    // so it is its own anchor. Anchoring on the whole function instead made
    // the patch look far larger than it is, and would drift the day anything
    // unrelated inside that function changed.
    anchor: `    this.rpc.invoke("Chunk.update", { source: source.rpcId });
`,
    replacement: `    // A refresh replaces pixels; it must not remove them.
    //
    // Removed here: a key-less Chunk.update naming only the source, which
    // told the page to drop its whole copy. The page dropped it at once and
    // the fresh bytes arrived milliseconds later, so between the two there
    // was nothing to draw and the picture flashed -- on a static dataset
    // never, on a live acquisition once per commit. Each chunk's own update
    // still arrives as it downloads, which is what makes the page's copy
    // fresh; the whole-copy drop only ever made it briefly absent.
`,
  },
  {
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "Object.assign(chunk, source.getChunk(update))",
    anchor: `        if (update.new) {
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
    replacement: `        if (update.new) {
          // Fresh bytes for a chunk this page already holds are written INTO
          // the held object rather than replacing it, so the render layer's
          // reference stays valid and the ordinary state transition uploads
          // the new texture. Replacing the object instead passed the short
          // no-blink gate and still left a 20-per-second commit storm drawing
          // 72% of what a reload drew: the layers went on pointing at objects
          // the source had already forgotten.
          chunk = source.chunks.get(key);
          if (chunk !== void 0) {
            if (chunk.state === ChunkState.GPU_MEMORY) {
              chunk.freeGPUMemory(this.gl);
            }
            Object.assign(chunk, source.getChunk(update));
          } else {
            chunk = source.getChunk(update);
            source.addChunk(key, chunk);
          }
        } else {`,
  },
];

let failed = false;
for (const patch of PATCHES) {
  const targets = modulesOnly ? [patch.file] : [patch.file, patch.also];
  for (const file of targets.filter(Boolean)) {
    const held = readFileSync(file, "utf8");
    const done = patch.gone
      ? !held.includes(patch.gone)
      : held.includes(patch.marker);
    if (done) {
      console.log(`already patched: ${file}`);
      continue;
    }
    if (held.includes(SUPERSEDED)) {
      console.error(
        `${file} still carries the superseded patch generation. Reinstall the `
        + "package so this one applies to stock sources:\\n\\n"
        + "    rm -rf app/page/node_modules/neuroglancer && npm --prefix app/page install\\n",
      );
      failed = true;
      continue;
    }
    if (!held.includes(patch.anchor)) {
      console.error(
        `the anchor no longer matches in ${file} -- the pinned `
        + "neuroglancer version has changed. Re-verify the patch against the "
        + "new source before building.",
      );
      failed = true;
      continue;
    }
    writeFileSync(file, held.replace(patch.anchor, patch.replacement));
    console.log(`patched: ${file}`);
  }
}
if (failed) process.exit(1);
