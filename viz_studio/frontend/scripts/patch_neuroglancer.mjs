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
    // Upgrade: the staged push verifies the state it captured. The
    // beside-the-machine download races the state machine itself: an
    // operator zooming during a storm of announcements moves chunks OUT of
    // the drawn states while their re-downloads are in flight, and a push
    // that then lands with the captured state makes the worker's
    // bookkeeping and the page's holdings disagree -- silently, and for
    // good, which the storm gate measures as a zoom band showing 41% of a
    // fully-landed survey. A push is only delivered if the chunk still has
    // the state it was captured in; one that moved is handed back to the
    // state machine, whose ordinary path repaints it without anything
    // visible to lose.
    // The marker is CODE, not a comment, and that is load-bearing: the
    // build recompiles the flattened worker bundle every run and strips
    // comments doing it, so a comment marker vanishes after one build and
    // the patcher wrongly reports the pinned version changed. Code survives
    // the recompile; the older entries' markers were code by luck, this
    // one is by rule.
    file: join(lib, "chunk_manager", "backend.js"),
    also: workerBundle,
    marker: "group.staged.push([chunk, keptState",
    anchor: `      Promise.resolve(source.download(chunk, abort.signal)).then(() => {
        const staged = {};
        const stagedTransfers = [];
        chunk.serialize(staged, stagedTransfers);
        staged.state = keptState;
        group.staged.push([staged, stagedTransfers]);
        chunk.freeSystemMemory();
        if (--group.remaining <= 0) group.flush();`,
    addition: null,
    replacement: `      Promise.resolve(source.download(chunk, abort.signal)).then(() => {
        // ZMART: a push verifies the state it captured -- see the patch note.
        const staged = {};
        const stagedTransfers = [];
        chunk.serialize(staged, stagedTransfers);
        staged.state = keptState;
        group.staged.push([chunk, keptState, staged, stagedTransfers]);
        chunk.freeSystemMemory();
        if (--group.remaining <= 0) group.flush();`,
  },
  {
    file: join(lib, "chunk_manager", "backend.js"),
    also: workerBundle,
    marker: "if (chunk.state !== keptState)",
    anchor: `    for (const [msg, transfers] of group.staged) {
      queueManager.rpc.invoke("Chunk.update", msg, transfers);
    }`,
    addition: null,
    replacement: `    for (const [chunk, keptState, msg, transfers] of group.staged) {
      if (chunk.state !== keptState) {
        // The chunk moved on while its bytes were in flight; delivering the
        // captured state now would desynchronise the page from the worker.
        // The state machine gets it back and repaints it the ordinary way.
        queueManager.updateChunkState(chunk, ChunkState.QUEUED);
        queueManager.scheduleUpdate();
        continue;
      }
      queueManager.rpc.invoke("Chunk.update", msg, transfers);
    }`,
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
  {
    // Upgrade: the swap keeps a ledger. The delivery chain was measured
    // sound to the worker's doorstep — fresh bytes downloaded, every answer
    // a 200 — while the screen kept the past, so the open question is
    // whether the frontend swap runs at all, and this answers it as counts
    // a test can read: globalThis.zmartSwapLedger.{added,replaced}.
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "globalThis.zmartSwapLedger",
    anchor: `          if (source.chunks.get(key) !== void 0) {
            source.deleteChunk(key);
          }
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
    addition: null,
    replacement: `          if (!globalThis.zmartSwapLedger) {
            globalThis.zmartSwapLedger = { added: 0, replaced: 0 };
          }
          if (source.chunks.get(key) !== void 0) {
            source.deleteChunk(key);
            globalThis.zmartSwapLedger.replaced += 1;
          } else {
            globalThis.zmartSwapLedger.added += 1;
          }
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
  },
  {
    // Upgrade: the ledger keeps a trail — which SOURCE each push landed in
    // and under which KEY — because counts alone said "everything was
    // added, nothing replaced" while five chunks sat on screen, which
    // means the drawn population and the updated population live in
    // different maps, and only their identities can say which two.
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "zmartSwapLedger.trail",
    anchor: `          if (source.chunks.get(key) !== void 0) {
            source.deleteChunk(key);
            globalThis.zmartSwapLedger.replaced += 1;
          } else {
            globalThis.zmartSwapLedger.added += 1;
          }`,
    addition: null,
    replacement: `          if (!globalThis.zmartSwapLedger.trail) {
            globalThis.zmartSwapLedger.trail = [];
          }
          const zmartHad = source.chunks.get(key) !== void 0;
          globalThis.zmartSwapLedger.trail.push(
            { source: update.source, key, had: zmartHad });
          while (globalThis.zmartSwapLedger.trail.length > 64) {
            globalThis.zmartSwapLedger.trail.shift();
          }
          if (zmartHad) {
            source.deleteChunk(key);
            globalThis.zmartSwapLedger.replaced += 1;
          } else {
            globalThis.zmartSwapLedger.added += 1;
          }`,
  },
  {
    // Upgrade: the replacement's bytes must BOARD the GPU. The fresh chunk
    // built from a replace-in-place push is born already claiming the state
    // the old chunk held, so the shared transition below sees newState equal
    // to oldState and SKIPS copyToGPU -- the fresh bytes stay on the CPU and
    // the screen keeps drawing whatever texture the old chunk left, for the
    // rest of the session. That skip is the whole of the storm wedge: an
    // operator navigating during commits keeps chunks hot in GPU memory, so
    // their refreshes all take this path, while an untouched run's chunks
    // arrive through genuine transitions and upload normally -- which is why
    // the wedge needed the operator's hands to appear, and a reload to cure.
    // The upload is driven here, once, exactly for the case the shared block
    // will skip.
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "zmartHad && chunk.state === newState",
    anchor: `          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
        } else {`,
    addition: null,
    replacement: `          chunk = source.getChunk(update);
          source.addChunk(key, chunk);
          if (zmartHad && chunk.state === newState
              && newState === ChunkState.GPU_MEMORY) {
            chunk.copyToGPU(this.gl);
            visibleChunksChanged = true;
          }
        } else {`,
  },
  {
    // Diagnostics for the upload branch: which states the replacement chunk
    // actually carries, and whether the driven upload ever fires.
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "uploadsDriven",
    anchor: `          if (zmartHad && chunk.state === newState
              && newState === ChunkState.GPU_MEMORY) {
            chunk.copyToGPU(this.gl);
            visibleChunksChanged = true;
          }`,
    addition: null,
    replacement: `          globalThis.zmartSwapLedger.lastStates = {
            chunkState: chunk.state, newState,
            gpuIs: ChunkState.GPU_MEMORY,
          };
          if (zmartHad && chunk.state === newState
              && newState === ChunkState.GPU_MEMORY) {
            chunk.copyToGPU(this.gl);
            globalThis.zmartSwapLedger.uploadsDriven =
              (globalThis.zmartSwapLedger.uploadsDriven || 0) + 1;
            visibleChunksChanged = true;
          }`,
  },
  {
    // Upgrade: replace the DATA, keep the OBJECT. Swapping chunk objects
    // orphans every retained reference the render side holds -- the old
    // object keeps drawing its old texture while the new object uploads
    // fresh bytes nobody looks at, measured as a picture stuck in the past
    // with every byte on the CPU provably fresh. So a re-download of a held
    // chunk now pours its decoded fields into the EXISTING object and
    // re-uploads that object's own GPU copy: every reference stays valid,
    // and what the screen draws is what arrived.
    file: join(lib, "chunk_manager", "frontend.js"),
    marker: "zmartPourInto",
    anchor: `          if (zmartHad) {
            source.deleteChunk(key);
            globalThis.zmartSwapLedger.replaced += 1;
          } else {
            globalThis.zmartSwapLedger.added += 1;
          }
          chunk = source.getChunk(update);
          source.addChunk(key, chunk);`,
    addition: null,
    replacement: `          if (zmartHad) {
            globalThis.zmartSwapLedger.replaced += 1;
            const zmartPourInto = source.chunks.get(key);
            const zmartFresh = source.getChunk(update);
            if (zmartPourInto.state === ChunkState.GPU_MEMORY) {
              zmartPourInto.freeGPUMemory(this.gl);
            }
            zmartPourInto.data = zmartFresh.data;
            zmartPourInto.copyToGPU(this.gl);
            visibleChunksChanged = true;
            chunk = zmartPourInto;
          } else {
            globalThis.zmartSwapLedger.added += 1;
            chunk = source.getChunk(update);
            source.addChunk(key, chunk);
          }`,
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
