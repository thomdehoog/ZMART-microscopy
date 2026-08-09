# Independent review: live position and timepoint publication

**Branch reviewed** `agent/live-position-timepoint-publication`
**Head** `a8254418e1673482f332d27d409ed43160a61026`
**Reviewed against** `claude/omezarr-neuroglancer-structure-srnwu6` (`2027f911`), not `main`
**Pull request** draft #8
**Assignment** `docs/design/claude-review-prompt.md`
**Reviewed on** 9 August 2026, Linux, Python 3.11.15, zarr 3.1.6, numpy 2.4.6

---

## Release verdict

**Safe reference implementation.** Not yet suitable for controlled prototype use
on runs that matter, and some distance from live scientific decisions.

This is the lowest of the four categories the assignment offered, and it is worth
saying why, because the branch is in several respects better engineering than the
category suggests. The publication machinery genuinely earns its readiness rather
than asserting it: every commit decodes 1.76 million stored pieces, resolves and
byte-compares 93 virtual ranges, rebuilds 64 coarse pieces and compares 1.33
million raw-overlap pixels before it will move the record. Five independent fault
campaigns re-run here caught every one of their seeded faults. Three browser tests
driving a real Neuroglancer pass, and their sabotage harness proves they can fail.

The verdict is what it is for two reasons.

First, the review found a class of silently wrong pixels and silently wrong counts
that nobody had reported: **any mosaic that is not a complete rectangle**. This is
not an exotic shape. It is a tissue-shaped region of interest, a skipped position,
a run stopped early. On such a run the code double-owns specimen, double-counts it
for analysis, and silently rewrites pixels it has already published and verified.
The project's own acceptance criterion 10 forbids precisely this.

Second, the gap between what the branch's documents claim and what the production
path does is wider in one place than the response documents admit. Canonical
positions are described throughout as "conforming canonical OME-Zarr 0.5 position
images". A position written by `LivePublisher` — the production writer, the one the
browser tests use — is not an OME-Zarr image at all. It has no group metadata
whatsoever, and an independent reader refuses to open it.

The already-disclosed gaps (quadratic view copying, no view pyramids, `ViewRoute`
not wired into `viz_studio/backend`, no analysis reader) are all confirmed present
and are correctly described in `codex-review-2-blocking-findings-response.md`. That
document is unusually honest and this review did not find it overstating anything
except on the OME-Zarr point above.

---

## Findings, ranked

Ranked by the assignment's order: silently wrong pixels and counts first, then
exposure of incomplete data, then loss and irreproducibility, then scale, then
interoperability, then documentation.

---

### 1. A mosaic that is not a complete rectangle double-owns specimen

**Severity: critical — silently wrong analysis counts.**
**Verified by running.**

**Where** `zmart_live/ownership.py:174-211` (`plan_one_tile`), and
`zmart_live/coordinator.py:300` where the completeness result is discarded.

**What happens.** `plan_one_tile` decides a tile's analysis core by asking whether
a 4-connected neighbour exists on each axis. Where there is no neighbour it hands
the tile its whole frame on that axis, on the reasoning that an outer edge has
nobody to share with. It cannot tell an outer edge from an internal hole. When the
diagonal neighbour is the missing one, two tiles each extend towards the gap on
different axes, and their extensions intersect.

**Smallest reproducer.** A 3×3 mosaic with the centre tile absent — a shape
`check_the_grid_holds_together` accepts, and which `test_a_hole_in_the_middle_
leaves_the_mosaic_incomplete` asserts is accepted.

```python
from zmart_live.model import AcquisitionProfile, GridCell, LevelGeometry
from zmart_live.ownership import place_the_tiles

cells = {GridCell(r, c): f"pos{r}{c}"
         for r in range(3) for c in range(3) if not (r == 1 and c == 1)}
placements = place_the_tiles(profile, cells)
# then sweep core_roi_in_run().contains_point over the mosaic extent
```

**Expected** every point of specimen owned by exactly one tile.
**Observed** at frame 1152 with 128 overlap — the shipped `overview` geometry —
four 64×64 squares are owned by two tiles at once:

| frame | overlap | doubly-owned pixels | region |
| --- | --- | --- | --- |
| 18 | 2 | 4 | 1×1 per corner |
| 90 | 10 | 100 | 5×5 |
| 1152 | 128 | 16 384 | 64×64 |
| 2304 | 256 | 65 536 | 128×128 |

A 64×64 patch at 0.35 µm holds several nuclei comfortably. Every object in it is
counted twice, with nothing anywhere to say so.

The same sweep on complete rectangles — 1×2, 2×2, 3×3, 2×4 — finds zero doubly
owned pixels, which is exactly the set of shapes
`test_no_gaps_and_no_duplicates_anywhere_in_the_mosaic` parametrises over. The
invariant is real; it is simply never checked on any shape that could break it.

L-shaped and ragged mosaics fail the same way (1 doubly-owned pixel at the test
scale, 16 384 at production scale).

**Root cause.** Ownership is derived from grid adjacency rather than from actual
frame overlap between placed tiles. `check_the_grid_holds_together` already
computes `complete=False` for these shapes, but `LivePublisher.__post_init__` calls
it for its exception only and throws the result away; `MosaicComponent.complete` is
serialised to JSON and never read by any non-test code.

**Against the project's own criteria.** `live-position-timepoint-publication-
decisions.md:517`, acceptance criterion 10: *"A declared outer boundary keeps its
complete edge, while an unexpected internal hole leaves the component incomplete
rather than being silently reclassified as a boundary."* That is the defect,
stated in advance, and it is unimplemented.

**Minimum credible fix.** Decide `half_before` / `half_beyond` from whether another
*placed* tile's frame actually covers the strip, not from grid adjacency; or refuse
to publish a component whose `complete` is `False` until an explicit boundary
declaration says which edges are real. The second is smaller and matches the
decision record's language.

**Regression test that should remain.** Extend the existing exactly-once sweep to
parametrise over a holed 3×3, a ragged 3×3, an L, and two disconnected diagonal
tiles, asserting zero doubly-owned and zero unowned points inside the imaged union.

---

### 2. A later commit silently rewrites pixels already published and verified

**Severity: critical — a committed image changes without a new revision.**
**Verified by running.**

**Where** `zmart_live/coordinator.py:642-654` (`write_the_seamless_view`) together
with `:656-679` (`_what_this_tile_fills_in`).

The visual rule has the same blind spot as finding 1. On the holed 3×3, `pos01` and
`pos10` both write run region y[1024,1152) × x[1024,1152) — 16 384 pixels — and the
loop order decides who wins.

**Observed, end to end through the real publisher:**

```
published pos01: validated=True
   collision region right after pos01 was published: [1100]   <- pos01's own value
...
collision region after the whole run: [1300]                  <- pos10's value
pixels changed since pos01 was published and verified: 16384

re-inspect pos01: everything_checks_out=False
    complaint: The zoomed-out picture does not show 'pos01's own pixels over the
    ground it covers at moment 0. ...
re-inspect pos10: everything_checks_out=True
```

The system's own inspector confirms the violation after the fact. It is not caught
at commit time because `_check_the_zoomed_out_picture` only ever compares the
position being published, never the ones already committed.

This answers one of the assignment's questions directly: **yes, a committed image
can later change without a new revision.**

**Minimum credible fix.** Same as finding 1 — the collision disappears once the
fill region is derived from real coverage. Additionally, `inspect` could re-check
the committed neighbours whose regions this commit touched; that is cheap because
the neighbour set is small and bounded by geometry.

---

### 3. An uncommitted timepoint becomes visible in both views

**Severity: critical — unpublished data on the operator's screen.**
**Verified by running.**

**Where** `zmart_live/coordinator.py:652-654` and `:737-742`. Both view writers copy
`source[:, :, :, …]` — every moment the position's store holds — while the
publication unit is one position at one moment.

**Reproducer.** Commit `posA` moment 0. Write `posA` moment 1 to disk without
committing it. Commit `posB`, an unrelated position, which rebuilds the shared
pictures.

```
posA moment 0 committed (value 700)
posA moment 1 written to disk but NOT committed (value 4242)
  view at moment 1 over posA: [0]            <- correct so far
posB moment 0 committed -- shared pictures rebuilt
  view at moment 1 over posA: [4242]         <- the uncommitted moment
  manifest says committed: [('posA', None), ('posB', None)]
  raw overlap view at moment 1 over posA: [4242]
```

The manifest never records `posA` moment 1. Both view stores now contain it.

**Why the browser tests do not catch this.** They do catch it — but only because
the gate is enforced in `zmart_live/tests/browser/production/production_run.py`, a
server written inside the test folder, which refuses pieces whose
`(position, moment)` is not in the manifest. That refusal is real and correct, and
`production_run.py:73-97` explains it well. It is also the only thing standing
between the operator and this data, and it does not exist in `viz_studio/backend`,
which serves files out of a folder with no manifest awareness at all. Point the
real backend at a live run and the uncommitted moment is served.

A partially written moment — the microscope interrupted mid-frame — reaches the
store by the same path and would be drawn as plausible specimen.

**Minimum credible fix.** Write only the committed moments into the views: pass the
committed `(position, moment)` set, not just the position set, and slice per moment.

**Regression test.** Commit moment 0 of A, write moment 1 of A, commit B, then
assert the view at moment 1 over A is still empty ground.

---

### 4. A writer restart silently undoes a published replacement

**Severity: high — retracted pixels shown under a revision that says they were replaced.**
**Verified by running.**

**Where** `zmart_live/coordinator.py:293` — `generations: dict[str, int] =
field(init=False, default_factory=dict)` — never written to disk, never recovered
in `__post_init__`.

`replace_a_position` writes a new generation, rebuilds both views from it, and
publishes revision 2 as `position_replaced`. All correct, in memory.

```
replaced posA with 4200: revision 2, type position_replaced
  current store              : posA.generation-1.ome.zarr
  seamless shows             : {4200}

--- writer restarted over the same run folder ---
  generations after restart  : {}
  current store              : posA.ome.zarr
  manifest still records     : [('posA','position_committed',1),
                                ('posA','position_replaced',2)]
  seamless after a rebuild   : {700}      <- the superseded pixels are back
  inspect posA now           : everything_checks_out=False
```

The run's own history says those pixels were replaced because they were wrong. The
next rebuild after any restart puts them back on screen. The manifest is durable;
the pointer that says which bytes it refers to is not.

**Minimum credible fix.** Record the current generation in the commit event (or
beside the layout) and rebuild `generations` from the manifest in `__post_init__`.

**Regression test.** Publish, replace, construct a second `LivePublisher` over the
same folder, and assert `position_store` and a rebuilt view both still resolve to
the replacement.

---

### 5. Nothing the production writer produces is an OME-Zarr image

**Severity: high — the central interoperability claim does not hold on the production path.**
**Verified by running, with an independent reader and the published schema.**

**Where** `zmart_live/coordinator.py:524-605`. `_write_the_pixels` creates the level
arrays and nothing else. `describe_the_position` — the whole of `zmart_live/
omezarr.py`, 626 careful lines — is called from its own docstring example and from
`test_omezarr.py`, and **from nowhere else in the repository**. `coordinator.py`
does not import it.

**Observed after a real `write_and_publish`:**

```
--- canonical position as the run left it: posA.ome.zarr
  zarr.json at the image root: ABSENT
  level folders (with their own zarr.json): ['0','1','2','3']
  level 0: shape=[1,1,1,1152,1152] dimension_names=None
  ngff-zarr REFUSED it: ValueError: No valid Zarr group found at ...
  published 0.5 schema: cannot check, no root zarr.json

--- seamless view store: overview-seamless.ome.zarr
  THIS STORE IS A SINGLE ARRAY, not a multiscale image
  ngff-zarr REFUSED it
  published 0.5 schema: FAILED ValidationError: 'ome' is a required property

--- raw overlap view store: overview-raw.ome.zarr
  (identical result; shape [4,1,1,1,1152,2176])
```

All three folders are named `*.ome.zarr`. None of them is one. A collaborator
handed `positions/posA.ome.zarr` gets a refusal from the reader that
multiview-stitcher uses.

**What is genuinely fixed.** `omezarr.py` itself is good work and its 28 tests are
thorough — axes, units, per-level scale and translation, `dimension_names`, the
independent reader, and the published 0.5 schema. Every one of those tests operates
on a store that the test itself described first. `test_a_position_a_live_run_
actually_wrote_can_be_opened` is the only test that starts from `LivePublisher`, and
it calls `describe_the_position` by hand before checking anything.

So finding 7 of the previous review is fixed **in the module and not on the path**.
The response document's "Fixed. `zarr.open_group()` now succeeds" is true only of
positions somebody has separately described.

**Minimum credible fix.** Call `describe_the_position` at the end of
`_write_the_pixels`, before the readiness inspection, so that a position is
described by the time anything can publish it. Then add the independent-reader and
schema checks to the live-run test rather than only to the hand-built fixture.

---

### 6. The whole run's view cost is quadratic, and the break point is low

**Severity: high — cannot operate at the intended scale.**
**Verified by running.** Already disclosed by the branch; measured here.

Every commit rebuilds both full-resolution views from all committed positions
(`coordinator.py:1583-1586`). Measured on 1152×1152 uint16, one plane, one channel,
a single row:

| commit | position reads | seconds |
| --- | --- | --- |
| 1 | 20 | 0.99 |
| 4 | 26 | 1.80 |
| 8 | 34 | 2.98 |
| 12 | 42 | 4.20 |
| 16 | 50 | 5.19 |

Reads grow as `2N + 18`; time fits `0.28 N + 0.71` seconds per commit. Extrapolating
that fit:

- one commit costs 10 s at about **35 positions**, 60 s at about **210**;
- a 1 000-position run costs roughly **39 hours** of view rebuilding;
- a 10 000-position run costs roughly **160 days**, with the last commit alone
  taking about 47 minutes.

The stated target is 10 000 positions and multi-terabyte runs. More planes and
channels make it worse proportionally. The practical break point — where the writer
stops keeping up with an acquisition producing a position every few seconds — is a
few hundred positions.

This is correctly identified in the response document as a design change rather
than a repair, and as the thing that should probably come first.

---

### 7. Declared Python 3.10 support is broken

**Severity: medium — the package cannot be installed and used on its declared floor.**
**Verified by running.** Already disclosed; extent measured here.

`pyproject.toml:11` declares `requires-python = ">=3.10,<3.13"`.
`zmart_storage/canvas.py:1478` uses a starred expression inside a subscript:

```python
picture.arrays[0][
    *at, z0:z0 + depth, y0:y0 + height, x0:x0 + width
] = image
```

which is syntax valid only from 3.11. Checked with each interpreter's own parser:

```
py3.10: SyntaxError line 1478: invalid syntax
py3.11: parses OK
py3.12: parses OK
```

It is the only file in the repository that fails, but `zmart_live/omezarr.py:103`
imports `from zmart_storage.canvas import Channel`, so the OME-Zarr layer — and the
whole `viz_studio` test suite — is unimportable on 3.10.

**Minimum credible fix.** Either rewrite the subscript (`picture.arrays[0][(*at,
slice(z0, z0 + depth), …)]` works on 3.10) or raise the declared floor to 3.11.

---

### 8. The operator-facing viewer path is not connected to any of this

**Severity: medium — the production guarantee is unproven where it matters.**
**Established by reading, with an exhaustive search.** Already disclosed.

`viz_studio/backend/` contains **no reference** to `zmart_live`, `ViewRoute`,
`LivePublisher`, or the publication manifest. It still serves whole-file pointers
via `zmart_storage.linked` (`backend/linking.py`, `backend/server.py`). There are
two parallel linking systems, and the operator runs the older one.

The three production browser tests are honest about this — `browser/production/
README.md` says so in its second heading — and they do prove something real: every
pixel on screen was written, inspected and committed by the production writer, and
a real drawing engine was watched. They do not prove the application serves the same
way, because the application's serving path is not exercised.

Combined with finding 3, this is the sharpest practical risk in the branch: the
commit gate exists only in test code.

---

### 9. Neither view has zoomed-out copies

**Severity: medium.** **Verified by running.** Already disclosed.

Both view stores are single full-resolution arrays. `_check_the_zoomed_out_picture`
loops `for level_number in (0,)` and its `rebuilt` counter is bookkeeping only.
`coarse.py` plans the work; nothing writes those pixels. Zooming out in either view
has nothing prepared to fall back on.

---

### 10. There is no executable analysis consumer

**Severity: medium.** **Established by reading.** Already disclosed.

`analysis_core_roi` is computed, serialised, and read by nothing outside
`zmart_live/model.py` and the tests. There is no code that segments, counts,
deduplicates or publishes an analysis result against a layout-revisioned core. The
exactly-once ownership contract exists as a geometric predicate
(`contains_point`) and a stored field, not as an enforced path.

Note that finding 1 means the predicate itself is wrong on non-rectangular mosaics,
so the first consumer written against it would inherit the defect.

---

### 11. The decision record still states the opposite overlap rule

**Severity: low — documentation contradiction, acknowledged and unfixed.**
**Established by reading.**

`live-position-timepoint-publication-decisions.md:270-276`, Decision 7, says
top/left predecessor wins: *"the first tile keeps its complete image; a tile with a
real left neighbour omits the complete overlap on its left"*. Line 428 repeats it.

The executable rule is the opposite: every tile contributes `[0, step)` from its own
corner and gives up its lower and right strip
(`ownership.py:193-199`). `live-writer-and-linked-views-plan.md:77-82` records the
change and says *"The decision record should be amended to say lower/right"* — and
the decision record was not amended.

The trap is that both documents call the rule `one_sided`, and
`AcquisitionProfile.seamless_ownership` defaults to the string `"one_sided"`. A
reader reconciling the two gets the seam wrong by exactly one overlap width.

---

### 12. The documented install command cannot run the interoperability checks

**Severity: low — the headline test count is not the one that matters.**
**Verified by running.**

The assignment and the PR both quote `458 passed, 3 skipped` from
`pip install -e '.[dev]'`. That reproduces exactly. The three skips are not
incidental — they are the only checks that ask whether these images travel:

```
SKIPPED test_omezarr.py:804  ngff-zarr is an optional check that our images travel
SKIPPED test_omezarr.py:834  an optional outside reader
SKIPPED test_omezarr.py:863  an optional outside reader
```

`ngff-zarr` is listed in `requirements-dev.txt` but **not** in the `[project.
optional-dependencies] dev` extra in `pyproject.toml`, so the documented command
can never enable them. Installing it, and then `ngff-zarr[validate]` for the
published schema, gives:

```
461 passed in 65.54s
```

So the suite is stronger than advertised — and the number everyone quotes is the one
where the impartial checks did not run.

**Minimum credible fix.** Add `ngff-zarr[validate]>=0.41` to the `dev` extra.

---

## Claims that survived attack

These were genuinely attacked, not merely accepted.

**Readiness is earned, not asserted.** One publish of a single 1152² position
decodes 1 762 560 stored pieces, resolves and byte-compares 93 virtual ranges,
rebuilds 64 coarse pieces and compares 1 327 104 raw-overlap pixels. There is no
API by which a caller can supply a readiness flag. The counters are real.

**The fault campaigns are honest and they work.** All five Python campaigns were
re-run on a clean baseline; every seeded fault was caught. `_fault_check.py` is
careful in the ways that matter: it proves the baseline green before mutating,
accepts only pytest's exit status 1 as a catch, treats collection and usage errors
as errors rather than catches, reports a mutation whose target string has moved as
`STALE` rather than silently skipping it, reads every write back, and discards the
compiled copy after each rewrite. I attacked this and could not make it report a
false success; the failure modes I could construct all fall on the conservative side
(an ineffective mutation reads as "not caught", never as "caught").

One robustness gap, and it is mine as much as theirs: I killed a campaign with
SIGTERM mid-mutation and it left `if False:` in `coordinator.py`. The next run
correctly refused to proceed — `require_green_baseline` did exactly its job — but
the worktree was left with mutated product code. A `finally:` does not survive
SIGTERM. Worth a note in the campaign docstrings; not worth engineering around.

**The virtual routing layer is solid.** Hostile and nonsense chunk addresses are all
refused with clear errors rather than answered with somebody else's bytes:

```
in range              : offset=0 length=20
past the end          : refused -> ZmartLiveError
negative              : refused -> ZmartLiveError
too few axes          : refused -> ZmartLiveError
too many axes         : refused -> ZmartLiveError
moment nobody wrote   : refused -> ZmartLiveError
```

Rewriting a shard underneath the cache is caught by CRC32C rather than served
stale:

> The shard index's CRC32C checksum is 0x00000000, but its contents calculate to
> 0xbda3f87f. The table has changed or been damaged, so none of its byte ranges can
> be trusted.

The cache key includes device, inode, size, mtime and ctime in nanoseconds plus the
storage settings, and is LRU-bounded by both entry count and table size.

**The `tile` selector is described honestly.** `SceneImage.selector_axis` is kept out
of the declared axes and `scene.py:464-468` refuses an image that uses one name for
both. Neuroglancer is not told the tile slider is an OME-Zarr axis.

**Single-writer locking works.** A second publisher on the same run is refused
immediately with a clear message and succeeds on retry once the lock is released.
On POSIX only — see below.

**Committed pixels cannot be rewritten in place.** `write_a_position` refuses a
`(position, moment)` that has been published, and directs the caller to
`replace_a_position`.

**Complete rectangular mosaics are correct.** The exactly-once sweep on 1×2, 2×2,
3×3 and 2×4 finds no gaps and no duplicates, including at the four-tile corner and
with odd overlaps. Outer edges are covered.

**The production browser tests pass against a real Neuroglancer**, and their
sabotage harness makes them go red when it should. Chromium was available and all
three ran; this is not a "blocked".

---

## Verified by running

Environment: Linux, Python 3.11.15, zarr 3.1.6, numpy 2.4.6, ngff-zarr 0.41.1,
jsonschema 4.26.0, Node 22.22.2, Chromium 1194 (swiftshader).

| what | command | result |
| --- | --- | --- |
| Baseline | `.venv/bin/python -m pytest zmart_live/tests -q` | `458 passed, 3 skipped` |
| With the outside reader | same, after `pip install ngff-zarr[validate]` | `461 passed` |
| Lint | `.venv/bin/ruff check zmart_live` | clean |
| Whitespace | `git diff --check` | clean |
| Fault campaigns ×5 | `python -m zmart_live.tests.check_the_*_can_fail` | every fault caught |
| Production browser | `npx playwright test --config .../production/playwright.config.mjs` | 3 passed (1.9 m) |
| Browser sabotage | `node .../check-the-production-test-can-fail.mjs` | every fault caught |
| Ownership sweep | probe, holed / ragged / L mosaics | finding 1 |
| Silent overwrite | probe, real publisher, holed 3×3 | finding 2 |
| Uncommitted moment | probe, real publisher | finding 3 |
| Generation restart | probe, real publisher | finding 4 |
| OME-Zarr reality | probe + ngff-zarr + published schema | finding 5 |
| Commit cost | probe, 16 commits, instrumented reads | finding 6 |
| Python 3.10 | `/usr/bin/python3.10 -c "ast.parse(...)"` over every file | finding 7 |
| Routing attacks | probe, hostile keys + shard rewrite | survived |
| Two writers | probe, real lock file | survived |

Running the browser tests needs two things the configuration does not supply on a
machine like this one: `PYTHON` must be set (the spec defaults to `python`, which
does not exist where only `python3` is installed), and the page needs
`workflows/target_acquisition/webapp-ui` to have been `npm install`ed. Both are
environment facts rather than defects, but they cost time to discover and are worth
a line in the browser README.

All probe scripts are reproduced in the appendix below.

---

## Established by reading only

- **Finding 8**, the disconnection of `viz_studio/backend`, is a proof by exhaustive
  search rather than execution: no reference to `zmart_live`, `ViewRoute`,
  `LivePublisher` or the manifest exists in that folder. Executing it would mean
  standing up the real backend against a live run, which is precisely the
  integration that does not exist yet.
- **Finding 10**, the absent analysis consumer, is the same kind of search.
- **Finding 11** is a documentary comparison.
- The **manifest's durability machinery** — `os.replace`, `fsync` on both file and
  containing directory, the append-only history, the crash-tail recovery — was read
  and looks correct, and the fault campaign exercises it. I did not attempt real
  power-loss or short-write testing.

---

## Blocked or untested

Stated plainly, because none of these should be read as passing.

- **Windows and SMB.** Nothing here ran on either. The writer lock branches on
  `os.name == "nt"` and that branch is marked `pragma: no cover`. `fcntl.flock` is
  unreliable over SMB and NFS in ways that matter for a lock whose whole job is to
  stop two writers. Every conclusion in this review is a Linux conclusion.
- **Power loss and short writes.** Not simulated.
- **Multi-terabyte scale.** Finding 6 is a measurement over 16 positions and a
  linear fit; the extrapolation is arithmetic, not observation.
- **A mosaic several rows deep, watched on a screen.** Still not done. The browser
  runs here were one row, as before.
- **Non-square frames.** The OME-Zarr conformance fixture is square (512×512, t=2,
  c=2, z=2). Multiple moments, colours and planes are covered; a rectangular frame
  is not.
- **Concurrent readers racing the atomic replace.** Not tested.

---

## Answers to the questions asked

**Are canonical positions genuinely interoperable OME-Zarr images?**
No. Not as the production writer leaves them — they have no group metadata and an
independent reader refuses them. They become conforming images only when
`describe_the_position` is called separately, which nothing outside the tests does.

**Are virtual raw and seamless views described honestly?**
The `tile` selector is described honestly, and the response document is candid that
the views are bare arrays. The `.ome.zarr` file extension on all three stores is
not honest, because none of them is one.

**Can any uncommitted or partially complete timepoint become visible?**
Yes — finding 3. It reaches both view stores. In the browser it is hidden by a
refusal implemented in test-only code, which the real backend does not have.

**Can a committed image later change without a new revision?**
Yes, twice over: finding 2 on non-rectangular mosaics, and finding 4 after any
writer restart following a replacement.

**Do all axes, outer edges and overlaps produce correct pixels?**
On complete rectangular mosaics, yes, including outer edges, four-tile corners, odd
overlaps, and t, c and z together. On any other shape, no.

**Does analysis have an executable exactly-once ownership path?**
No. It has a stored region and a geometric predicate, and no consumer. The predicate
is also wrong on the shapes in finding 1.

**Is the real operator-facing Neuroglancer path connected?**
No. `viz_studio/backend` knows nothing about this layer.

**At what run size does the current implementation become impractical?**
A few hundred positions for a live acquisition, on the measured fit — 60 s per
commit at about 210 positions. A 1 000-position run costs about 39 hours of view
rebuilding; the 10 000-position target is roughly 160 days.

**What must be completed before this can guide live scientific decisions?**
Findings 1 to 5, then 6, then 8. Nothing below that changes whether the numbers
coming out are right.

---

## Recommended next slice

The smallest vertical piece that most increases confidence, in dependency order.

1. **Make ownership come from real coverage, not grid adjacency** (findings 1 and 2).
   One change in `plan_one_tile` fixes both the double-counted analysis region and
   the silent visual overwrite. Ship it with the exactly-once sweep extended to
   holed, ragged, L-shaped and disconnected mosaics. This is the only item on the
   list that is currently producing wrong science, and it is a small change.

2. **Gate the view writers per moment, not per position** (finding 3). Pass the
   committed `(position, moment)` set into both view writers. This moves the commit
   gate out of test-only code and into the store, which is where the design says it
   lives.

3. **Persist the current generation** (finding 4). Record it in the commit event and
   rebuild it in `__post_init__`.

4. **Call `describe_the_position` from the writer** (finding 5), and move the
   independent-reader and published-schema checks onto a store the publisher wrote.
   Add `ngff-zarr[validate]` to the `dev` extra so those checks run for everybody
   (finding 12). Raise the Python floor to 3.11 or fix the subscript (finding 7)
   while in the neighbourhood.

Steps 1 to 4 are all small, all testable without new infrastructure, and together
they close every correctness defect this review found. Only then is the quadratic
view copying (finding 6) worth attacking, and it should be attacked before, not
alongside, wiring `ViewRoute` into `viz_studio/backend` — because the zero-copy
design is what makes that wiring worth doing.

---

## A note on tone

The assignment asked for an adversarial review and the findings above are
adversarial. It would be a poor summary of this branch to leave it there.

The publication machinery does something unusual and right: it refuses to let a
caller assert readiness, and goes and looks instead. The fault campaigns are the
most serious attempt at testing the tests I have seen in a repository this size,
and they hold up under attack. The response documents disclose their own gaps
accurately, including the ones that are embarrassing. The docstrings genuinely
explain to a biologist why a thing is done, which is rare and is worth protecting.

The defects found here are concentrated in one place: the code decides what a tile
owns by looking at the grid it was planned on, rather than at the tiles that were
actually placed. That single assumption produces findings 1 and 2, and it is
holding up an otherwise careful design.

---

## Appendix: probes

Every probe below was run from the repository root with `.venv/bin/python`. All were
removed afterwards and the worktree left clean.

### A. Exactly-once ownership on non-rectangular mosaics (findings 1)

```python
from zmart_live.model import AcquisitionProfile, GridCell, LevelGeometry
from zmart_live.ownership import check_the_grid_holds_together, place_the_tiles

def a_plan(frame=18, overlap=2, chunk=2):
    return AcquisitionProfile(
        profile_id="probe", acquisition_type="overview",
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": 1, "y": frame, "x": frame}, dtype="uint16",
        overlap_pixels={"y": overlap, "x": overlap}, topology="grid",
        levels=(LevelGeometry(level=0, downsampling={"y": 1, "x": 1},
                              inner_chunk={"y": chunk, "x": chunk},
                              linkable=(frame - overlap) % chunk == 0),))

def sweep(name, cells):
    profile = a_plan()
    step, frame = profile.grid_step("x"), profile.frame_shape["x"]
    placements = place_the_tiles(profile, cells)
    reach_y = max(c.row for c in cells) * step + frame
    reach_x = max(c.column for c in cells) * step + frame
    doubled, nobody = [], []
    for y in range(reach_y):
        for x in range(reach_x):
            owning = [p.position_id for p in placements
                      if p.core_roi_in_run().contains_point({"y": y, "x": x, "z": 0})]
            (doubled if len(owning) > 1 else nobody if not owning else []).append((y, x))
    print(name, "doubled:", len(doubled), "unowned:", len(nobody))

square = lambda r, c: {GridCell(i, j): f"pos{i}{j}"
                       for i in range(r) for j in range(c)}
sweep("3x3 complete", square(3, 3))
holed = square(3, 3); del holed[GridCell(1, 1)]
sweep("3x3 centre missing", holed)
```

### B. Silent overwrite of published pixels (finding 2)

Build a `LivePublisher` over the holed 3×3, publish the eight tiles in sorted order,
snapshot the seamless view over `pos01`'s fill region immediately after `pos01` is
published, compare after the run, then call `run.inspect("pos01")` again.

### C. Uncommitted moment (finding 3)

```python
run = LivePublisher(folder, profile, run_id="run-tp", cells=cells, timepoints=2)
run.write_and_publish("posA", specimen(700))          # moment 0 committed
run.write_a_position("posA", specimen(4242), timepoint=1)   # written, not committed
run.write_and_publish("posB", specimen(900))          # unrelated commit
# read the seamless view at moment 1 over posA -> 4242
```

### D. Generation across restart (finding 4)

```python
run.write_and_publish("posA", specimen(700))
run.replace_a_position("posA", specimen(4200))
again = LivePublisher(folder, profile, run_id="run-gen", cells=cells)  # restart
again.write_the_seamless_view(frozenset(again.manifest.committed().by_store))
# read the seamless view over posA -> 700, the superseded pixels
```

### E. OME-Zarr reality (finding 5)

After `write_and_publish`, check each store for a root `zarr.json`, then
`ngff_zarr.from_ngff_zarr(store)` and
`ngff_zarr.validate(attributes, version="0.5", model="image")`.

### F. Commit cost (finding 6)

Monkeypatch `zmart_live.coordinator.zarr.open_array` to count opens whose path
contains `positions`, then publish 16 positions in a row and time each commit.

### G. Python 3.10 (finding 7)

```bash
/usr/bin/python3.10 -c "
import ast, pathlib
for p in pathlib.Path('.').rglob('*.py'):
    if any(x in p.parts for x in {'.venv','node_modules','__pycache__'}): continue
    try: ast.parse(p.read_text(errors='replace'))
    except SyntaxError as e: print(p, e.lineno, e.msg)"
```

### H. Routing attacks (survived)

Call `where_one_chunk_lives(level0, key)` with an in-range key, a key past the end,
a negative key, too few axes, too many axes, and a moment never written; then append
bytes to the shard file and resolve again.
