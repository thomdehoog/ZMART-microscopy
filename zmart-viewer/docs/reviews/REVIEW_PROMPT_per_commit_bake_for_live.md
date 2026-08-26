# Review prompt: per-commit bake for live runs, as one of two modes

> Written 2026-08-13. You are reviewing a PLAN, not code. Nothing below is
> built. Please attack the design — especially the gate question in §5 —
> before a line of it is implemented. The codebase is the branch
> `agent/server-builds-the-picture-opus-5` of ZMART-microscopy, current
> through `72f0da3f`.

## What the operator decided, verbatim requirements

1. **Live runs get BOTH modes.** Computed-on-demand (today's only mode) and
   baked, as a switch — exactly as finished transfers have `--bake`.
2. **Every kind of change works identically in both modes:** a position
   updated (a replacement today, a new timepoint once the time axis lands),
   a position added (a landing), a position withdrawn (replacement or
   whole-history rollback — the manifest is append-only, so "delete" is one
   of those two).
3. The standing non-negotiables: **zero transients on the frame recorder**
   at every scale rung, fail-closed withholds (withdrawn ground must stop
   being served the moment its commit says so), and the 5D-shaped rule —
   new keys carry (t, c) from the start even while the picture serves
   moment zero of channel zero.

## Context: what exists today

- A **transfer** (finished data) declared with `--bake` holds its coarse
  ground as real chunk files: the composer's pinned levels written as the
  exact wire bytes the composer would produce, then the picture's own
  levels chained upward by 2×2 averaging until one piece holds everything
  (`declare._bake_the_coarse_ground`). Serving answers **file-first**
  (`served.the_bytes_behind`: `baked.is_file()` before anything else), and
  the file door is the *only* door to the extended levels. Cold open is
  file reads — measured "instant" on screen at 12,800 and 115,200
  positions.
- A **governed run** (live) is served through `GovernedRun`: every request
  asks `composer()`, which checks the manifest's fingerprint and derives a
  fresh immutable snapshot when it moved. As of `72f0da3f` the cold derive
  stamps its tiles from one pattern store plus the layout (1.13 s at
  12,769 positions, one disk read). Changed ground is refreshed per piece:
  `_what_changed_dirtied` names exactly which (level, row, column) pieces a
  change reached, from both snapshots' geometry, and the browser refetches
  just those. The coarse ground is NOT baked — it is built on demand
  (~10 s first overview at 12,800, felt on screen today) and kept warm per
  session by a background warmer at idle priority.
- **Windows rule, learned as WinError 5 mid-demo:** the server must not
  hold a chunk file open while the writer replaces it. Composer reads are
  open-read-release; `os.replace` against every read chunk is a regression
  test.
- The 2026-08-12 decision note (`docs/measured/NOTE_live_updates_seen_on_screen.md`,
  memory-recorded): in-place refresh and generation swap COMPOSE, and for
  swaps "the bake patched per commit, never rebuilt."

## The plan

### 0. Instrument first (the flicker hunt's law)

Extend `measure_a_governed_run_at_scale.py` with a bake column: cold open
time, landing-to-visible latency, per-commit patch cost, recorder
transients, in both modes at 1,024 / 6,400 / 12,769. Every claim below is
measured before and after, on the same fixture.

### 1. The switch

`declare_a_governed_picture(..., bake: bool = False)` mirroring the
transfer door. `bake=True` writes the initial baked ground from the current
snapshot — for a young run most pieces are fill, and fill is expressed by
ABSENCE, so an empty run's bake writes nothing and costs nothing — and
records the baked level list under the picture's `zmart` attributes.
Declaring again without `--bake` removes the baked ground (the transfer
rule: the switch works both ways).

### 2. The patcher

When `GovernedRun.composer()` derives a fresh snapshot, it already computes
the dirtied pieces per level. On a baked picture, those pieces — and only
those — are rebuilt and their files atomically replaced (write sidecar,
`os.replace`); a piece that became all-fill has its file DELETED
(absent-means-fill, as everywhere). Then the change is carried up the
picture's own extended levels **regionally**: each level up halves the
footprint, so the touched region of level L+1 is recomputed from the
just-patched region of level L read back from files — never the whole
array, unlike the transfer bake, which may hold a whole level in memory
because it runs once at declare time. Cost per commit: O(change) pieces at
the pinned levels plus a geometrically shrinking tail up the extended
chain.

### 3. Rollbacks and swaps patch the same way

A replacement, a withhold and a recovery all move the fingerprint, and
`_what_changed_dirtied` already collects the footprint from BOTH snapshots
— the ground a removal used to cover rebuilds just as surely as the ground
an arrival now covers. The patcher therefore needs no case analysis: it
patches whatever was dirtied, deleting files that became empty. A
generation swap (fresh picture at a fresh address) inherits the previous
generation's baked files minus the change's footprint rather than
re-baking the world — the "patched per commit, never rebuilt" decision.
HOW that inheritance is expressed (hard-link the unchanged files? copy?
serve-through with a fallback chain?) is deliberately left open for
review — see question Q4.

### 4. Both modes stay honest to the same bytes

The baked answer and the built answer must be byte-identical by
construction (the bake writes the composer's own wire bytes; the patcher
uses the same encoder). The central test is therefore: after an arbitrary
churn — landings, replacements, a rollback, in any order — every piece of
a baked picture equals the same piece of an unbaked picture of the same
run, byte for byte, at every level including the extended ones. Plus: zero
recorder transients with bake ON at the 12,769 rung; the WinError 5
regression against baked pieces while serving; the switch removing and
re-creating baked ground; and the 5D key shape asserted from day one.

### 5. THE question for reviewers: the gate under the file door

`the_bytes_behind` answers from a baked file BEFORE consulting the
manifest — today safe (only transfers have baked files; a transfer never
changes). With live bake, between a commit landing and the patcher
finishing, the file door would serve the PREVIOUS state's bytes. For an
arrival that is merely "old for a moment"; for a WITHHOLD it is
fail-closed ground still being served — not acceptable by the gate's own
words ("this record means everything").

Two candidate cures, review please:

- **(a) Patch synchronously inside the derive**, before the fresh snapshot
  is handed out and before the refresh is announced. Truth stays simple —
  files are always current once anyone can know about the new state — but
  the patch cost lands inside landing-to-visible latency (estimated tens
  of ms for one position's footprint; measured before accepting).
- **(b) A dirty-set override**: the derive records dirtied addresses; for a
  governed store the request path asks the GovernedRun FIRST, and any
  address in the dirty set is answered by the composer (same bytes,
  computed) while the patcher catches up in the background; the file door
  serves only clean addresses. No added latency, more machinery, and the
  file-first door needs restructuring for governed stores either way,
  because today it never reaches the GovernedRun at all.

The plan's lean is (a) for its simpler truth, with (b)'s restructuring
(governed stores consult the run before the file door) adopted regardless,
because a governed picture answering ANY address without consulting its
run is the same hole the gate was built to close.

### 6. What stands down, what stays

With bake on: the session warmer stands down (already the transfer rule —
`served._the_serving_behind` skips warming baked pictures). With bake off:
nothing changes, today's behavior exactly. The unbaked mode is not a
degraded mode — it is the zero-setup mode, and the measurement harnesses
keep building composers cold to measure what they exist to measure.

## Questions for reviewers, collected

- **Q1 (gate):** §5 — is (a), (b), or both the right cure? Is there a hole
  neither closes?
- **Q2 (edges):** the extended-level regional patch does read-modify-write
  up a chain whose odd-sized edges the transfer bake handles by padding
  with `mode="edge"`. Same rule regionally — any corner case that breaks
  byte-identity with a from-scratch bake?
- **Q3 (concurrency):** two threads may derive the same snapshot (by
  design, either wins). May two patchers race on the same files? Does the
  patcher need the derive's guard, its own, or idle-priority stepping-aside
  like the warmer?
- **Q4 (swap inheritance):** hard links, copies, or fallback-chain serving
  for the unchanged baked files of a generation swap? Windows junctions
  and hard links behaved well for fixtures; is either acceptable for a
  serving path the operator trusts?
- **Q5 (crash honesty):** the patcher dies mid-change (power, kill). Files
  are then a mix of two states with no marker. Does the next derive need a
  bake epoch / manifest revision stamp beside the baked levels to detect
  and re-patch, and is that stamp the same thing as the dirty-set made
  durable?

## Addendum, same day: what got built, and the writer question that remains

The plan above was implemented before external review at the operator's
direction; §5's lean was taken (synchronous patch, governed stores consult
the run before any file door — including the BACKEND's, which had its own
static-file door in front of everything and served baked pieces past the
manifest until an HTTP-level test pinned it). Five defects were found by
the scale harness and screen-watching, none by inspection: the backend
door; a patch-per-racing-thread pile-up (cure: the stamp is the
idempotence, forward-only); a second manifest reader racing the writer's
appends (cure: the bake stamps the fold's own count — one reader per
derive); announces not covering the picture's extended levels (the engine
displays them at overview zoom and refetched nothing); and extended-level
patches written in place through zarr, whose truncate-writes tore under
concurrent refetches and left growing black regions (cure: staging array +
atomic per-chunk replace). Ladder complete, zero transients at every rung;
baked cold open 0.3 s against 81.5 s unbaked at 12,769.

**The remaining question for reviewers is the WRITER.** Profiled at 12,769
committed: 48.3 s per publish, of which ~33 s was re-reading every
position's array description (152,300 zarr.json opens) and ~6 s linear
placement scans — both now remembered (48.3 → 37.3 s, commit 33897d70).
What remains is architecture: ``route_the_view`` runs twelve times per
publish, each pass validating ALL positions' geometry to admit one change.
The proposed cure is validating the CHANGE — the new or replaced
position's records against the settled survey's remembered validation —
which alters what a publish re-checks and therefore what it guarantees.
Q6: is per-change validation over a remembered survey-wide baseline
acceptable to the gate's philosophy, and what must invalidate the
baseline (layout revision? profile change? recovery?)? Q7: within one
publish, the same state is routed for the link map, the inspection and
the view check — may these share one routing, and which of them is
entitled to refuse independently?

## How to look for yourself

- The serving door: `zmart-viewer/app/picture/served.py` (`the_bytes_behind`,
  `_the_serving_behind`); the live snapshot: `zmart-viewer/app/picture/governed.py`
  (`composer`, `_compose_the_snapshot`, `_what_changed_dirtied`); the
  transfer bake: `zmart-viewer/app/picture/declare.py`
  (`_bake_the_coarse_ground`); refresh contracts:
  `zmart-viewer/tests/test_the_composer_obeys_the_manifest.py`,
  `zmart-viewer/tests/test_frontend_live_refresh_contract.py`.
- Suites: `python -m pytest zmart-viewer/tests zmart_live/tests zmart_storage`
  from the repo root (browser tests need the built frontend and free
  ports — do not run demo viewers beside them; 24 photograph/port tests
  fail under a squatted port and it looks exactly like a real regression).
- The scale harness: `zmart-viewer/app/picture/measure_a_governed_run_at_scale.py`
  against `D:\zmart-scale-runs\gov113x113`.
