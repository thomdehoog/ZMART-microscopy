# Prompt: fix the bake that cannot catch up, and audit the night that found it

You are picking up a diagnosed but unfixed bug, plus a set of patches of
uncertain value made while diagnosing it. The full investigation record
is the last three sections of `docs/measured/MEASURED_the_ladder_of_surveys.md` in
this folder; read them first and believe their corrections over their
first drafts — the night walked through one measurement mirage and
several exonerated suspects before reaching the bottom.

## The bug, as proven

At twenty commits a second (the demo regime, ~40× a real microscope),
the per-commit bake falls behind the storm and **its catch-up never
repairs the ground it missed**: 7.5% of every baked level stayed
unpatched forever on `D:\zmart-demo-spiral15` (kept as evidence — read
the baked levels of `gov40x40/shown/live.ome.zarr` and see). The
picture is then permanently behind its manifest, and the fail-closed
gate does what it was built to do: a cold client against a brand-new
server process over that folder sees 0.0% lit. Blank is the gate shut;
the earlier "black stripes cured by F5" era was the gate open over a
picture partially behind. Slower runs never outran the bake: an
untouched hour at one commit per two seconds soaked clean, machine-
judged.

## The fix's address

Either the derive's catch-up must actually re-patch the footprints a
storm made it skip (the stamp's prefix rule claims workers only bake
NEWER ground than the stamp says — find where a skipped patch still
lets the stamp advance), or the stamp must refuse to advance past
unpatched ground so the next derive knows to return. Start from
``declare.py``'s stamp handling and ``governed.py::_keep_the_bake_true``,
and reproduce first: `show_a_run_growing.py --across 40 --spiral
--core 32 --every 0.05 --quick-page --no-pop` into a FRESH fixtures
folder breaks the serving within seconds of the storm's start — then
read the baked levels on disk and watch the holes never close. The fix
is done when: the storm run's baked levels reach 0% dark after the run
quiets, a cold client sees the full survey, and the whole guard suite
plus `test_a_commit_storm_under_zooming.py` and
`test_dirty_pieces_reach_their_level.py` stay green.

## First, the audit: the night may have done harm as well as good

Four behaviour changes shipped while diagnosing, and only some are
verified. The operator's standing worry is that the night did more harm
than good — treat that as a hypothesis to test, not an insult:

1. **Invalidation routing by identity** (`engine.js`,
   `invalidateTheDirtyPieces`): gate-verified
   (`test_dirty_pieces_reach_their_level.py` reproduces the misrouting
   deterministically and pins the fix). Keep.
2. **ETag revalidation for live pieces** (`server.py`,
   `test_server.py`): unit-verified, exonerated for the storm bug by a
   cache-disabled reproduction. Keep, but know it shipped the same day
   the stripes were first seen.
3. **The delivery push verifies its captured state**
   (`patch_neuroglancer.mjs`, worker side): never proven load-bearing
   against any red test. Plausibly correct; audit or revert.
4. **Replace-in-place pours data into the held chunk instead of
   swapping objects** (`patch_neuroglancer.mjs`, frontend side): built
   on a hypothesis the mirage later dissolved, never proven, changed
   the most delicate path in the viewer. Audit first — build a red test
   that distinguishes object-swap from data-pour (the render side's
   retained references are the question), or revert to the committed
   object-swap and let a red test earn any change back.

Diagnostic instruments the night left for you, all committed: the swap
ledger and its trail (`globalThis.zmartSwapLedger`), the delivery
counters (`window.zmartChunkInvalidation.delivered`), the worker probe
(`ChunkSource.zmartProbe`), the storm gate's env-guarded debug blocks
(`ZMART_STORM_DEBUG`, `ZMART_STORM_HEAL`, `ZMART_STORM_NO_HTTP_CACHE`),
and `show_a_run_growing.py` for watched reproductions. The patcher rule
that cost hours twice: **worker-bundle patch markers must be CODE
strings, never comments** — the build recompiles the bundle and strips
comments.

## Also open, smaller

- The synthetic storm gate drives zoom by teleporting the zoom factor;
  the operator's real wheel (zoom-toward-cursor through the engine's
  own handlers) broke things the gate missed. Upgrade the gate to real
  `mouse.wheel` and drags over the canvas mid-storm.
- The pywebview window has no reachable reload (the engine's input
  system eats Ctrl+R and F5); an UNCOMMITTED fix sits in
  `zmart-viewer/app/server/launcher.py` (a native View → "Reload the
  picture" menu) awaiting behavioural verification.
- A transient-flicker rate ceiling between 10 and 20 commits/s,
  untouched viewer — measured, unexplained, benign at real rates. The
  operator's hypothesis, worth testing first: ordinary engine memory
  pressure. The chunk queue runs a fixed budget (1 GB GPU / 2 GB
  system, whatever the card holds), and storm-plus-zoom eviction going
  dark until refetch would look exactly like the transient half of the
  night's symptoms — self-healing holes, never the persistent stripes
  and never the server-side refusal. Raise the capacities and watch
  whether the transients move; if they do, that whole symptom layer
  files under "designed behaviour under a budget", not under the bug.
- The campaign's other threads (bake worker count on 24 cores, the
  prefill flicker, the publish path's metadata round-trips) still
  stand in the doc's open-threads list.
