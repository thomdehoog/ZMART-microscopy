# Review prompt: the plan for building change zero

> Hand this whole file to an independent reviewer (it is self-contained).
> The question being asked: **will this build order produce a composer that
> is safe to serve a live run, and where will it go wrong?** Criticise the
> plan, not the prose.

## Context, in five sentences

A ZMART run writes each position as its own OME-Zarr and publishes it
through a manifest ("files existing means nothing; this record means
everything"). The viewer shows all positions as ONE seamless picture, built
piece by piece on request by a composer that today assumes everything on
disk is showable and remembers every answer forever — fine for finished
transfers, disqualifying for live runs. An independent review
(`docs/reviews/REVIEW_the_composer_meets_the_live_role.md`, findings 1–10) catalogued
what breaks; a measured demonstration (2026-08-12,
`docs/measured/NOTE_live_updates_seen_on_screen.md`) showed the browser side works today
and the server side is the whole problem: with forget-everything standing in
for invalidation, updates ceiling at ~2 changes/s and unchanged ground
blinks. "Change zero" is the plan's name for teaching the composer the gate
before any accelerator touches live data. The reference implementation of
every rule is `zmart_live/gateway.py`, which already does gate-then-serve
for the per-store path.

## The bar the result is held to

Simple, efficient, professional, maintainable — in that order of tension.
The smallest clean design that enforces the two invariants below wins;
anything in this plan that can be deleted without weakening an invariant
should be, and the reviewer is asked to name such deletions explicitly.
Mechanism count is the enemy: prefer one rule applied everywhere (the
counter in the key) over many special cases policed separately. No
workaround survives the build — if a step only works with a caveat, the
step is not done. And every piece of cleverness on the hot path must pay
for itself in a measured number, or it goes.

## The two invariants everything serves

1. **Nothing uncommitted, rolled back, or superseded is ever encoded into a
   piece** — withheld ground renders as if never written; absent chunks of
   committed ground are a 404, never plausible zeros (fail closed).
2. **A cached answer is valid exactly as long as the manifest state it was
   built under** — the change counter lives in every key, so staleness is
   unreachable-by-key rather than policed.

## Proposed build order (TDD: each step's tests watched failing first)

**Step 0 — the governed-run fixture.** A test fixture that creates a real
manifest-governed run (via `zmart_live`'s own writer machinery, not mocks)
holding: committed positions, a written-but-uncommitted position, a
rolled-back position, a replaced position (two generations), and a
half-written arrival. Every later step's tests run against this one
fixture. Also: an independent order-oracle for `check.py`, because today's
harness iterates tiles in the same order as the composer and cannot see
wrong overlap order (review finding 2's closing trap).

**Step 1 — sources from the manifest, never glob (finding 1).** The
composer gains a second way to learn its tiles: from manifest + layout
(position id, generation, published moments), used whenever the source is a
governed run; `glob` remains for imported transfers only. Geometry (origin,
extent, dtype, voxel size) comes from the run's profile/layout — a fixed
world frame — so an empty run is a valid empty picture and growth neither
blanks nor shifts anything (finding 5 travels with this step).

**Step 2 — commit order (finding 2).** Each piece's tile list is sorted by
manifest commit revision, later on top. The replaced-generation inversion
(`generation-2` sorting before its original) is the named regression test.

**Step 3 — fail closed (finding 3, plus 9).** Reads of committed ground
verify chunk presence; an absent committed chunk fails the piece as 404
with a logged reason — never fill zeros over published pixels. Exceptions
per-request → 404 + brief negative cache keyed by fingerprint (so one bad
store stops being a standing DoS and recovery is noticed).

**Step 4 — the counter in every key (findings 4 and 6).** Per request:
check `manifest.fingerprint()`; on change, swap in a freshly derived
immutable snapshot (tiles, placements, piece index) — never mutate in
place. Slab and block cache keys carry the per-store revision
(`CommittedState.by_store`); a build stamps the counter at its *start* and
discards on insert if it moved (closing the torn-picture window). Eviction
is therefore automatic: stale entries become unreachable and age out of the
LRU. This step is what lifts the measured 2/s ceiling — only touched
pieces rebuild.

**Step 5 — the composer releases committed tiles at the commit boundary.**
Open zarr handles for a position being replaced/rolled back are closed when
the snapshot swaps (Windows refuses to replace a file the server holds
open — reproduced 2026-08-12, WinError 5). All other handles stay open;
reopening everything was 86% of view-building cost.

**Step 6 — routing and the address space (findings 7 and 8).** A built
picture whose `built_from` lies inside a governed run must route every tile
decision through the manifest (no gate bypass); `built_from` restricted to
an allow-listed root. The piece address space grows the moment axis — keys
carry (t, c, z, y, x) from the start even while only t=0 is served — so the
per-(position, moment) gate has somewhere to stand and change zero is
5D-shaped rather than retrofitted.

**Acceptance, beyond the unit tests:** the sabotage campaigns gain composer
faults (lay in arrival order; ignore the manifest; serve a cached piece
across a commit that touched it) — each watched failing first; the
parallel-fire storm runs against built answers (a commit mid-storm must
never surface withheld pixels, blank published ground, or hand back a torn
mixture); and the 2026-08-12 churn demonstration rerun end-to-end: **100
positions appearing/disappearing at 8 changes/s, achieving 8/s, with no
blink on unchanged ground** — watched by the operator, not only asserted.

## Deliberately NOT in scope

- Every accelerator (slab finish, cache sizing, warmer changes, bake
  patching) — they land after correctness, per the plan.
- The writer's L0–L5 default flip — decided, and gated on this work
  landing (`docs/open/PLAN_responsiveness.md` change-zero section).
- Browser-side changes — the demonstration showed none are needed; the
  page's announce path stays as is.
- Forking or patching Neuroglancer.

## Questions for the reviewer

1. Is the step order right — specifically, is deferring the moment axis to
   step 6 (while shaping keys 5D from step 4) safe, or does it retrofit the
   exact thing finding 8 warns about?
2. Step 4's discard-on-insert closes the torn-picture window per slab — is
   there a cross-piece tear it misses (two pieces of one screenful built
   astride one commit)? Should a whole *request generation* pin one
   fingerprint?
3. Is the per-store revision the right cache-key ingredient, or must the
   key carry the whole-run fingerprint (coarse pieces meet many stores)?
4. The fixture uses real `zmart_live` machinery — name the ways that
   fixture could be *less* adversarial than a real microscope (timing,
   partial writes, filesystem reordering) and which of those deserve a
   sabotage campaign of their own.
5. What in this plan quietly assumes Windows semantics (file locks, mtime
   granularity) and will behave differently on the Linux boxes?
6. Against the bar above: which steps carry mechanism that could be deleted
   or merged? In particular — do the negative cache (step 3) and the
   discard-on-insert (step 4) earn their complexity, or does one simpler
   rule (snapshot pinned per request generation) subsume both?
