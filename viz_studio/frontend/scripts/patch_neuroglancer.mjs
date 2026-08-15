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
 * - page side (`lib/chunk_manager/frontend.js`): the push that delivers fresh
 *   bytes updates the held chunk object, preserving the renderer's reference
 *   while the ordinary state transition uploads its new texture.
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
    marker: "zmartPumpRefreshesWithoutDeadline",
    legacyStart: "async function zmartPumpRefreshes(source) {",
    legacyEnd: `  void zmartPumpRefreshes(source);
});`,
    anchor: `registerRPC(CHUNK_SOURCE_INVALIDATE_RPC_ID, function(x) {
  const source = this.get(x.id);
  source.chunkManager.queueManager.invalidateSourceCache(source);
});`,
    addition: `
// ZMART: refresh NAMED chunks beside the state machine.
//
// A live storm can name the same visible chunk again before its previous
// refresh finishes. Downloading both into the same mutable Chunk races their
// callbacks: one callback can serialize bytes written by another and detach
// the buffer before its owner reaches serialize. One source therefore has one
// refresh pump. Announcements received while it runs are coalesced into the
// next batch, so quiet always produces a final batch begun after the last
// announcement. The old frontend chunks keep drawing until each replacement
// succeeds. A slow response is not a failure: aborting useful composition at
// an arbitrary deadline makes the server repeat the same expensive work and
// can keep it behind forever. Completed chunks are therefore delivered as
// soon as they arrive. The HTTP reader already retries 429/503/504 with
// bounded backoff, so this pump must not start a competing retry policy.
//

async function zmartPumpRefreshesWithoutDeadline(source) {
  if (source.zmartRefreshRunning) return;
  source.zmartRefreshRunning = true;
  const queueManager = source.chunkManager.queueManager;
  try {
    while (source.zmartPendingRefresh.size !== 0) {
      const keys = [...source.zmartPendingRefresh];
      source.zmartPendingRefresh.clear();
      source.zmartRefreshBatches = (source.zmartRefreshBatches || 0) + 1;
      const jobs = [];
      for (const key of keys) {
        const chunk = source.chunks.get(key);
        source.zmartRefreshOffered = (source.zmartRefreshOffered || 0) + 1;
        if (chunk === void 0) {
          source.zmartRefreshAbsent = (source.zmartRefreshAbsent || 0) + 1;
          continue;
        }
        const stateName = ChunkState[chunk.state];
        const states = source.zmartRefreshStates ||= {};
        states[stateName] = (states[stateName] || 0) + 1;
        if (chunk.state === ChunkState.GPU_MEMORY
            || chunk.state === ChunkState.SYSTEM_MEMORY) {
          const keptState = chunk.state;
          const abort = new AbortController();
          jobs.push(Promise.resolve(source.download(chunk, abort.signal)).then(
            () => {
              const msg = {};
              const transfers = [];
              chunk.serialize(msg, transfers);
              msg.state = keptState;
              queueManager.rpc.invoke("Chunk.update", msg, transfers);
              chunk.freeSystemMemory();
            },
            () => {
              source.zmartRefreshFailures =
                (source.zmartRefreshFailures || 0) + 1;
            },
          ));
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
      await Promise.allSettled(jobs);
    }
  } finally {
    source.zmartRefreshRunning = false;
    if (source.zmartPendingRefresh.size !== 0) {
      void zmartPumpRefreshesWithoutDeadline(source);
    }
  }
}

registerRPC("ChunkSource.refreshChunks", function(x) {
  const source = this.get(x.id);
  const pending = source.zmartPendingRefresh ||= new Set();
  for (const key of x.keys) pending.add(key);
  void zmartPumpRefreshesWithoutDeadline(source);
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
  const source = this.get(x.source);
  const keys = [...source.chunks.keys()];
  const byState = {};
  for (const chunk of source.chunks.values()) {
    const name = ChunkState[chunk.state];
    byState[name] = (byState[name] || 0) + 1;
  }
  return Promise.resolve({ value: {
    held: keys.length, sample: keys.slice(0, 8), byState,
    refresh: {
      offered: source.zmartRefreshOffered || 0,
      absent: source.zmartRefreshAbsent || 0,
      overlaps: source.zmartRefreshOverlaps || 0,
      maxOverlap: source.zmartMaxRefreshOverlap || 0,
      overlapKeys: [...(source.zmartRefreshOverlapKeys || [])].slice(0, 8),
      batches: source.zmartRefreshBatches || 0,
      failures: source.zmartRefreshFailures || 0,
      superseded: source.zmartRefreshSuperseded || 0,
      pending: source.zmartPendingRefresh?.size || 0,
      running: source.zmartRefreshRunning || false,
      byState: source.zmartRefreshStates || {},
    },
  } });
});`,
  },
  {
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "Object.assign(chunk, source.getChunk(update))",
    anchor: `        if (update.new) {
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
    addition: null,
    replacement: `        if (update.new) {
          // ZMART: refresh data without replacing the chunk object retained
          // by render layers. Replacing it passed the short no-blink gate but
          // reproducibly left the 20/s storm at 72% where F5 showed 100%.
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
  for (const file of [patch.file, patch.also].filter(Boolean)) {
    const held = readFileSync(file, "utf8");
    if (held.includes(patch.marker)) {
      console.log(`already patched: ${file}`);
      continue;
    }
    let grafted;
    const legacyAt = patch.legacyStart
      ? held.indexOf(patch.legacyStart)
      : -1;
    const legacyThrough = legacyAt === -1
      ? -1
      : held.indexOf(patch.legacyEnd, legacyAt);
    if (legacyAt !== -1 && legacyThrough !== -1) {
      const afterLegacy = legacyThrough + patch.legacyEnd.length;
      grafted = held.slice(0, legacyAt) + patch.addition
        + held.slice(afterLegacy);
      console.log(`migrated legacy patch: ${file}`);
    } else if (!held.includes(patch.anchor)) {
      console.error(
        `the anchor no longer matches in ${file} -- the pinned `
        + "neuroglancer version has changed. Re-verify the patch against the "
        + "new source before building.",
      );
      failed = true;
      continue;
    } else {
      grafted = patch.replacement
        ? held.replace(patch.anchor, patch.replacement)
        : held.replace(patch.anchor, patch.anchor + patch.addition);
      console.log(`patched: ${file}`);
    }
    writeFileSync(file, grafted);
  }
}
if (failed) process.exit(1);
