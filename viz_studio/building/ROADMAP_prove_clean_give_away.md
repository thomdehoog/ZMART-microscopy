# The road from here: prove it, clean it, give it away

> Written 2026-08-13, at the close of the night change zero was built and
> the flicker was killed (`bb047577..f5af6698`). The live pipeline works at
> demonstration scale: real manifest commits landing in a governed picture,
> served warm through the gate, refreshed chunk-by-chunk with zero
> transients on the recorder and by the operator's own eyes. What remains
> is one arc in three steps, in order.

## 1. Prove it

**Scale.** The churn ladder at 100, 1,600 and 12,800 positions, with the
frame recorder keeping everyone honest — zero transients at every rung, or
the rung fails. The known risk to attack first: deriving a fresh snapshot
re-reads every committed tile's description per commit, which is linear
and becomes seconds at ten thousand positions; the incremental tile-list
is owed before big surveys. The writer's own ~500-900 ms per `publish()`
is a separate investigation with a separate owner.

**5D.** Z-depth, channels and time through the governed picture. Today it
serves three axes reading moment zero of channel zero; a multi-channel run
is refused loudly at the declare door, and depth beyond one plane has
never been in a demonstration. The groundwork is deliberately 5D-shaped
already — the copies' outer indices, the block-cache keys, the
per-(position, moment) gate — so the growth is the declared description,
the served addresses, the dirty protocol, and the refresh keys. First
move, per this night's hardest lesson: probe the frontend chunk map for
the real 5D key spelling rather than assuming it.

## 2. Clean it

The neuroglancer patch reimplemented as a real TypeScript change in the
engine's source — refresh named chunks without touching their state,
grouped atomic delivery, the frontend replace-in-place — with the dead
first-generation block shed by a fresh install, and string-patching of
built bundles retired.

## 3. Give it away

A pull request to google/neuroglancer for the primitive the engine
genuinely lacks: **refresh named chunks of a source without dropping the
rest.** It is not a ZMART quirk — it is what any live or streaming data
source needs, their own Python integration included — and the PR arrives
with measured evidence: whole-source invalidation empties the screen;
per-chunk refresh runs at commit cadence with zero transients. The
recorder scripts produce the numbers.

And the closure the whole design has been pointing at: once the feature is
merged and released upstream, `frontend/scripts/patch_neuroglancer.mjs` is
deleted — the no-workaround-survives rule, applied in the end to our own
patch.
