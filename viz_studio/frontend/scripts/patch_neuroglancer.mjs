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
 * **Worker patches target the module AND the compiled bundle, and the build
 * runs this AFTER precompiling.** The precompile step flattens the worker's
 * import stub into a self-contained bundle ON ITS FIRST RUN and thereafter
 * recompiles that flattened bundle — module changes never enter the worker
 * again. That cost a night: three patch generations ran only in the module
 * files while the worker executed the first-ever compile, and every
 * measurement of them was a measurement of nothing. On a fresh install the
 * postinstall patches the modules, the first precompile carries them into
 * the bundle, and the bundle entries here find their markers already
 * present; on a tree whose stub is long flattened, the bundle entries are
 * what actually lands. Frontend patches live in modules only — vite bundles
 * the page from modules every build.
 *
 * Applied as idempotent string patches against the pinned version (2.41.2).
 * Fails loud when an anchor has moved, which is the signal that the pinned
 * version changed and the patch needs re-verifying.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, "..", "node_modules", "neuroglancer", "lib");
const workerBundle = join(lib, "chunk_worker.bundle.js");

const PATCHES = [
  {
    file: join(lib, "chunk_manager", "backend.js"),
    also: workerBundle,
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
    file: join(lib, "chunk_manager", "backend.js"),
    also: workerBundle,
    marker: "ChunkSource.refreshChunks",
    anchor: `registerRPC(CHUNK_SOURCE_INVALIDATE_RPC_ID, function(x) {
  const source = this.get(x.id);
  source.chunkManager.queueManager.invalidateSourceCache(source);
});`,
    addition: `
// ZMART: refresh NAMED chunks beside the state machine, delivered as one.
//
// The predecessor above ("invalidateChunks") re-queued the named chunks, and
// the queue's own consistency sweep did exactly what it exists to do: a
// QUEUED chunk is not entitled to keep owning frontend memory, so each was
// reclaimed with a per-chunk EXPIRED -- measured as the drawn chunk deleted
// and its region black until the fresh bytes arrived. So here a chunk the
// page is drawing keeps its state untouched: the fresh bytes are downloaded
// beside the machinery, and one data-bearing push replaces the old copy in
// a single frontend turn (the frontend's replace-in-place patch). Chunks
// the page does not hold are plainly re-queued, where nothing visible can
// be lost -- that is also how a chunk that 404'd before its ground was
// committed comes to exist at all.
//
// The named chunks are one change -- one commit's footprint -- so their
// pushes are staged until the last is in hand and sent back-to-back: the
// change appears in ONE frame. The group's timeout flushes whatever is
// staged if a download stalls, so no chunk holds its neighbours' fresh
// pixels hostage. Keys are chunk grid positions joined with commas, x
// fastest and z last, exactly as getChunk builds them.
registerRPC("ChunkSource.refreshChunks", function(x) {
  const source = this.get(x.id);
  const queueManager = source.chunkManager.queueManager;
  const group = { open: true, remaining: 0, staged: [] };
  group.flush = () => {
    if (!group.open) return;
    group.open = false;
    for (const [msg, transfers] of group.staged) {
      queueManager.rpc.invoke("Chunk.update", msg, transfers);
    }
    group.staged.length = 0;
  };
  for (const key of x.keys) {
    const chunk = source.chunks.get(key);
    if (chunk === void 0) continue;
    if (chunk.state === ChunkState.GPU_MEMORY
        || chunk.state === ChunkState.SYSTEM_MEMORY) {
      group.remaining += 1;
      const keptState = chunk.state;
      const abort = new AbortController();
      Promise.resolve(source.download(chunk, abort.signal)).then(() => {
        const staged = {};
        const stagedTransfers = [];
        chunk.serialize(staged, stagedTransfers);
        staged.state = keptState;
        group.staged.push([staged, stagedTransfers]);
        chunk.freeSystemMemory();
        if (--group.remaining <= 0) group.flush();
      }, () => {
        if (--group.remaining <= 0) group.flush();
      });
    } else {
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
  }
  queueManager.scheduleUpdate();
  if (group.remaining === 0) {
    group.open = false;
    return;
  }
  setTimeout(group.flush, 2000);
});`,
  },
  {
    file: join(lib, "chunk_manager", "backend.js"),
    also: workerBundle,
    marker: "ChunkSource.zmartProbe",
    anchor: `registerRPC(CHUNK_SOURCE_INVALIDATE_RPC_ID, function(x) {
  const source = this.get(x.id);
  source.chunkManager.queueManager.invalidateSourceCache(source);
});`,
    addition: `
// ZMART diagnostics: what one source actually holds, read-only. The flicker
// investigation needed ground truth about chunk keys and states inside the
// worker, and a question that can be asked is worth keeping.
registerPromiseRPC("ChunkSource.zmartProbe", function(x) {
  const source = this.get(x.id);
  const keys = [...source.chunks.keys()];
  const byState = {};
  for (const chunk of source.chunks.values()) {
    const name = ChunkState[chunk.state];
    byState[name] = (byState[name] || 0) + 1;
  }
  return Promise.resolve({ value: {
    held: keys.length, sample: keys.slice(0, 8), byState,
  } });
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
  for (const file of [patch.file, patch.also].filter(Boolean)) {
    const held = readFileSync(file, "utf8");
    if (held.includes(patch.marker)) {
      console.log(`already patched: ${file}`);
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
    const grafted = patch.replacement
      ? held.replace(patch.anchor, patch.replacement)
      : held.replace(patch.anchor, patch.anchor + patch.addition);
    writeFileSync(file, grafted);
    console.log(`patched: ${file}`);
  }
}
if (failed) process.exit(1);
