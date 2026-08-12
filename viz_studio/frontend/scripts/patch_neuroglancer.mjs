/**
 * The one patch this repository maintains against its pinned Neuroglancer.
 *
 * Neuroglancer can only invalidate a chunk source whole: the stock RPC is an
 * unfiltered loop over the source's keyed chunk map, plus a message telling
 * the page to drop every chunk it holds — the operator watches the picture
 * empty and refill on every live-run commit. A live run changes a handful of
 * chunks per commit, so this adds the filtered variant of the same loop,
 * with replace-in-place delivery:
 *
 * - worker side (`lib/chunk_manager/backend.js`): "ChunkSource.invalidateChunks"
 *   re-queues exactly the named chunks and tells the page NOTHING — the stale
 *   pixels keep drawing while the fresh bytes download;
 * - page side (`lib/chunk_manager/frontend.js`): the push that delivers the
 *   fresh bytes arrives marked new, and the stale copy is dropped in the same
 *   JS turn the new one lands, so no rendered frame ever shows a gap.
 *
 * `engine.js` (invalidateTheDirtyPieces) is the caller; the announcement's
 * `dirty` field is where the chunk names come from.
 *
 * **The module files are the target, never the worker bundle**: the build's
 * precompile step regenerates `chunk_worker.bundle.js` from these modules
 * every time, so a patch applied to the bundle quietly evaporates on the
 * next build — which happened once, and cost an evening's confusion.
 *
 * Applied as idempotent string patches against the pinned version (2.41.2).
 * Runs from `postinstall` and before every build, so a fresh `npm install`
 * heals itself; fails loud when an anchor has moved, which is the signal
 * that the pinned version changed and the patch needs re-verifying.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, "..", "node_modules", "neuroglancer", "lib");

const PATCHES = [
  {
    file: join(lib, "chunk_manager", "backend.js"),
    marker: 'registerRPC("ChunkSource.invalidateChunks"',
    anchor: `registerRPC(CHUNK_SOURCE_INVALIDATE_RPC_ID, function(x) {
  const source = this.get(x.id);
  source.chunkManager.queueManager.invalidateSourceCache(source);
});`,
    addition: `
// ZMART patch v2: invalidate NAMED chunks of a source instead of all of them.
//
// The stock RPC above re-queues every chunk and tells the frontend to drop
// its whole copy of the source, which empties the screen for as long as the
// refetch takes. A live microscopy run changes a handful of chunks per
// commit, so this filtered variant re-queues exactly those -- and it sends
// the frontend nothing at all. The stale copy keeps drawing while the fresh
// bytes download; the push that delivers them arrives marked new, and the
// frontend's companion patch swaps old for new inside one JS turn, so no
// rendered frame ever shows the gap. Keys are chunk grid positions joined
// with commas, exactly as getChunk builds them; an unknown key is a
// harmless miss.
registerRPC("ChunkSource.invalidateChunks", function(x) {
  const source = this.get(x.id);
  const queueManager = source.chunkManager.queueManager;
  for (const key of x.keys) {
    const chunk = source.chunks.get(key);
    if (chunk === void 0) continue;
    switch (chunk.state) {
      case ChunkState.DOWNLOADING:
        cancelChunkDownload(chunk);
        break;
      case ChunkState.SYSTEM_MEMORY_WORKER:
        chunk.freeSystemMemory();
        break;
    }
    queueManager.updateChunkState(chunk, ChunkState.QUEUED);
  }
  queueManager.scheduleUpdate();
});`,
  },
  {
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "ZMART patch v2: replace in place",
    anchor: `        if (update.new) {
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
    addition: null, // replacement, not addition -- see apply below
    replacement: `        if (update.new) {
          // ZMART patch v2: replace in place. A re-download of a chunk this
          // page already holds -- the surgical invalidation's delivery --
          // arrives marked new while the stale copy is still drawing. The
          // old copy is dropped in the same JS turn the fresh one is added,
          // so no rendered frame ever shows the gap between them.
          if (source.chunks.get(key) !== void 0) {
            source.deleteChunk(key);
          }
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
  },
];

let failed = false;
for (const patch of PATCHES) {
  const held = readFileSync(patch.file, "utf8");
  if (held.includes(patch.marker)) {
    console.log(`already patched: ${patch.file}`);
    continue;
  }
  if (!held.includes(patch.anchor)) {
    console.error(
      `the anchor no longer matches in ${patch.file} -- the pinned `
      + "neuroglancer version has changed. Re-verify the patch against the "
      + "new source before building.",
    );
    failed = true;
    continue;
  }
  const grafted = patch.replacement
    ? held.replace(patch.anchor, patch.replacement)
    : held.replace(patch.anchor, patch.anchor + patch.addition);
  writeFileSync(patch.file, grafted);
  console.log(`patched: ${patch.file}`);
}
if (failed) process.exit(1);
