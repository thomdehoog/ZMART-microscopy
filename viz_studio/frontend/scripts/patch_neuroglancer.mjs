/**
 * The one patch this repository maintains against its pinned Neuroglancer.
 *
 * Neuroglancer can only invalidate a chunk source whole: the stock RPC is an
 * unfiltered loop over the source's keyed chunk map, and its companion
 * message tells the page to drop every chunk it holds — the operator watches
 * the picture empty and refill on every live-run commit. A live run changes
 * a handful of chunks per commit, so this adds the filtered variant of the
 * same loop: "ChunkSource.invalidateChunks" re-queues exactly the named
 * chunks, dropping each frontend copy with the same per-chunk message
 * ordinary eviction uses, and never touches anything else on screen.
 * `engine.js` (invalidateTheDirtyPieces) is the caller; the announcement's
 * `dirty` field is where the names come from.
 *
 * Applied to the built worker bundle rather than kept as a diff, because a
 * string patch against a pinned version is readable in review and idempotent
 * to apply, where a line-number diff against a 40,000-line bundle is neither.
 * Runs from `postinstall`, so a fresh `npm install` heals itself; fails loud
 * if the anchor has moved, which is the signal that the pinned version
 * changed and the patch needs re-verifying against its new source.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const bundle = join(
  here, "..", "node_modules", "neuroglancer", "lib", "chunk_worker.bundle.js",
);

const ANCHOR = `registerRPC(CHUNK_SOURCE_INVALIDATE_RPC_ID, function(x) {
  const source = this.get(x.id);
  source.chunkManager.queueManager.invalidateSourceCache(source);
});`;

const ADDITION = `
// ZMART patch: invalidate NAMED chunks of a source instead of all of them.
//
// The stock RPC above re-queues every chunk and tells the frontend to drop
// its whole copy of the source, which empties the screen for as long as the
// refetch takes. A live microscopy run changes a handful of chunks per
// commit, so this filtered variant re-queues exactly those: each named chunk
// held by the frontend is dropped with the same per-chunk EXPIRED message
// ordinary eviction uses, and every other chunk of the source is never
// touched. Keys are chunk grid positions joined with commas, exactly as
// getChunk builds them.
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
      case ChunkState.SYSTEM_MEMORY:
      case ChunkState.GPU_MEMORY:
        queueManager.rpc.invoke("Chunk.update", {
          id: chunk.key,
          state: ChunkState.EXPIRED,
          source: source.rpcId
        });
        break;
    }
    queueManager.updateChunkState(chunk, ChunkState.QUEUED);
  }
  queueManager.scheduleUpdate();
});`;

const held = readFileSync(bundle, "utf8");
if (held.includes('registerRPC("ChunkSource.invalidateChunks"')) {
  console.log("neuroglancer already carries the invalidateChunks patch");
} else if (held.includes(ANCHOR)) {
  writeFileSync(bundle, held.replace(ANCHOR, ANCHOR + ADDITION));
  console.log("neuroglancer patched: ChunkSource.invalidateChunks added");
} else {
  console.error(
    "the neuroglancer worker bundle no longer matches the patch anchor -- "
    + "the pinned version has changed. Re-verify the patch against the new "
    + "source of invalidateSourceCache before building.",
  );
  process.exit(1);
}
