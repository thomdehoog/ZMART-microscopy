# Independent review prompt for Claude

Everything below the line can be given to Claude as-is. This is a review
assignment, not a request to implement fixes. The useful outcome is an
evidence-backed list of defects and remaining engineering gates, not agreement
with the existing design or its response documents.

---

## Repository coordinates

| | |
| --- | --- |
| **Repository** | `thomdehoog/ZMART-microscopy` |
| **Branch to review** | `agent/live-position-timepoint-publication` |
| **Head** | Use the branch's current `HEAD`; record its SHA when the review starts |
| **Actual review base** | `claude/omezarr-neuroglancer-structure-srnwu6` (`2027f911`) |
| **Pull request** | Draft PR #8 |

Do **not** diff against `main`. This branch is built on the OME-Zarr structure
branch, so a comparison with `main` includes hundreds of unrelated commits.
Use:

```bash
git fetch origin agent/live-position-timepoint-publication \
                 claude/omezarr-neuroglancer-structure-srnwu6
git checkout agent/live-position-timepoint-publication
git status --short --branch
git rev-parse HEAD
git diff --stat origin/claude/omezarr-neuroglancer-structure-srnwu6...HEAD
git diff origin/claude/omezarr-neuroglancer-structure-srnwu6...HEAD
```

The branch is large because it contains a new `zmart_live/` package and its
tests. Review the implementation itself. Existing review and response documents
are evidence and claims, not the boundary of the review.

## Mission

Perform an independent, adversarial architecture and implementation review of
the live OME-Zarr position/timepoint publication system. Look wider than
`docs/design/codex-review-prompt.md` and wider than the issues previous
reviewers chose to discuss.

The system will sit beside microscopes producing up to multi-terabyte runs while
Neuroglancer is open. A silent partial picture, omitted plane, duplicated object,
stale chunk or misregistered tile is more serious than an exception because it
looks scientifically plausible. Rank the review accordingly.

Do not assume a claim is true because:

- a response document marks it fixed;
- a test with the same name passes;
- a readiness field says `true`;
- Zarr can open a path;
- a synthetic browser server behaves correctly; or
- the code is careful and extensively documented.

Try to produce counterexamples. Prefer a small executable reproducer over a
plausible concern. Clearly distinguish what you **ran**, what you established by
**reading**, and what remained **blocked or untested**.

## Intended architecture

The design currently intends:

```text
<run>/                                  ZMART run container
  positions/
    pos-00001.ome.zarr/                 complete canonical acquisition
      0/ 1/ 2/ ...                      pixels and per-position pyramids
    pos-00002.ome.zarr/
  views/
    overview-seamless.ome.zarr/         one de-overlapped viewer source
    overview-raw.ome.zarr/              overlap-preserving selector source
  zmart-live/
    profiles/ layouts/ manifest/ ...    operational and publication state
```

The intended interoperability boundary is deliberate:

- every canonical position must be an independently conforming, portable
  OME-Zarr image;
- the outer run is currently a ZMART collection whose relationships are
  compiled by an adapter rather than native OME-Zarr scene metadata;
- virtual view routing is ZMART-specific, even when the adapter exposes
  OME-Zarr-shaped metadata and chunk endpoints;
- a view is independently portable only when it is materialized;
- native OME-Zarr scene serialization is deferred, but the internal model should
  not require an architectural rewrite when scenes become usable.

Do not report the existence of `positions/` and `views/` as an
interoperability defect by itself. Determine precisely which layer is portable,
which is adapter-dependent, whether the code and documentation say that
honestly, and whether standard clients observe the promised behavior.

Other load-bearing decisions:

- canonical positions keep every overlap pixel and are never modified by a view;
- stitching, registration and drift correction are separate downstream work;
- each acquisition type seals its own frame, overlap, chunks, shards, pyramid
  factors, codecs and ownership policies;
- pyramid downsampling is by halves;
- sharding reduces physical file count but does not relax inner-chunk/seam
  alignment;
- a complete position or appended timepoint is the publication unit, never an
  individual Zarr chunk;
- data, all advertised pyramids, routes, affected view chunks, ownership layout
  and commit state must become visible as one validated revision;
- analysis may use the complete overlapping tile as context, but explicit
  versioned ownership regions ensure an acquisition-wide result is published
  exactly once;
- Neuroglancer receives one bounded source per view, never one source per
  position;
- source URLs remain stable and revisions travel beside them so refresh does not
  leak layers.

Read these before judging whether the implementation matches the decisions:

1. `docs/design/live-position-timepoint-publication-decisions.md`
2. `docs/design/live-writer-and-linked-views-plan.md`
3. `docs/design/codex-review-findings.md`
4. `docs/design/codex-review-response.md`
5. `docs/design/codex-review-2-blocking-findings-response.md`
6. `docs/design/zmart-ome-zarr-recipe.md`

Also read `CLAUDE.md`. Long explanatory docstrings are intentional and written
for scientists learning the system. Flag inaccurate prose, contradictions and
unexplained dangerous assumptions; do not flag prose merely for being long.

## Establish a trustworthy baseline

Use the repository environment if it exists, otherwise install the declared
development dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest zmart_live/tests -q
.venv/bin/ruff check zmart_live
git diff --check
```

At the time this prompt was written, the Python suite reported **458 passed and
3 skipped**. Treat that only as a reproducibility coordinate. If your count
differs, explain why; do not silently reuse this number.

Before and after any destructive or mutation-style probe:

```bash
git status --short
git diff --quiet
git diff --cached --quiet
```

Do not leave generated files, modified sources, compiled artifacts that affect
the suite, or a dirty worktree behind. Never call an infrastructure error, test
collection failure, missing browser, timeout or already-red baseline a
successfully caught fault.

## First attack: try to make the tests lie

The repository contains these mutation/fault campaigns:

```bash
.venv/bin/python -m zmart_live.tests.check_the_tests_can_fail
.venv/bin/python -m zmart_live.tests.check_the_omezarr_tests_can_fail
.venv/bin/python -m zmart_live.tests.check_the_shardlink_tests_can_fail
.venv/bin/python -m zmart_live.tests.check_the_scene_tests_can_fail
.venv/bin/python -m zmart_live.tests.check_the_viewroute_tests_can_fail

node zmart_live/tests/browser/check-the-test-can-fail.mjs
node zmart_live/tests/browser/production/check-the-production-test-can-fail.mjs
```

Audit the harnesses as well as running them:

- Does each establish a green baseline first?
- Does it accept only an ordinary assertion/test failure as a caught fault?
- Does every textual mutation definitely alter the intended source?
- Is the restored source byte-identical afterwards?
- Can Python bytecode, Node caches, test selection drift or a timeout make the
  campaign report success without exercising the fault?
- Are several mutations merely different spellings of the same behavior?

Then add independent temporary faults or standalone reproducers that are not
already in those scripts. Finding one scientifically meaningful mutation that
survives is more valuable than confirming all existing mutations.

## Required review areas

### 1. Atomic publication and immutability

Attempt to expose a timepoint when only some channels, Z planes, pyramid levels,
view routes or affected coarse artifacts exist. Check new positions and appended
timepoints separately. Test two writers, crash tails, restart/recovery, clock
changes, full-disk/short-write behavior where practical, and readers racing the
atomic replace.

Verify that an already committed canonical position/timepoint cannot be changed
silently under the same revision. A checksum only checked before publication is
not an immutability guarantee afterwards.

Determine whether the five readiness checks in `coordinator.py` prove the
artifacts that Neuroglancer and analysis will actually consume, rather than
nearby proxies. Try missing middle chunks, corrupt pyramid chunks, valid-looking
but wrong layouts, wrong codecs, incomplete routes and stale view data.

### 2. Pixel correctness and overlap geometry

Exercise at least:

- one tile, two adjacent tiles, 2×2 and 3×3 mosaics;
- a several-row browser case;
- rectangular frames and different camera/confocal formats;
- odd and even overlaps;
- one row, one column, component boundaries, an internal hole and disconnected
  components;
- `t > 1`, `c > 1` and `z > 1`, both separately and together;
- absent/unwritten positions that already have planned grid cells.

Check every outer edge, not only internal seams. Confirm that the union of owned
regions covers the promised acquisition extent exactly once and that no channel
or Z plane is duplicated from another.

The design documents have historically disagreed about whether top/left or
lower/right supplies an overlap and whether every tile is trimmed identically.
Find the current executable rule, compare it with every claimed rule, and test
the far edges. Treat a contradiction as important even if both policies could be
valid in isolation.

### 3. OME-Zarr conformance and interoperability

Do more than `zarr.open_group()`. Validate canonical positions against the
official OME-Zarr 0.5 requirements and, where practical, open them with at least
one independent OME-Zarr reader. Check:

- the image root and `ome.version`;
- `multiscales`, axes, units and dataset paths;
- scale then translation at every level;
- array `dimension_names`;
- shapes, chunks/shards, codecs and metadata matching the bytes;
- non-square images, multiple channels, multiple planes and multiple
  timepoints.

Use primary specifications as the authority and cite them. Separately inspect
the two view stores. State whether each is:

1. a portable materialized OME-Zarr image;
2. a valid metadata facade whose pixels work only through ZMART's adapter; or
3. not yet a conforming OME-Zarr image at all.

Check whether the raw view's local `tile` selector can be represented honestly
to Neuroglancer without falsely advertising it as a standard OME-Zarr axis.

### 4. Virtual routing, chunks and shards

Attack `shardlink.py` and `viewroute.py` with real Zarr v3 shards, not only
hand-built indexes. Cover:

- index at start and end;
- supported and unsupported index codec chains;
- CRC32C damage;
- absent-entry sentinels;
- truncated or concurrently growing shards;
- overlapping, out-of-bounds or index-overlapping ranges;
- non-integer and malicious chunk keys;
- cache invalidation when a shard is replaced or appended;
- two source chunks with similar addresses but different position/timepoint
  identity.

Verify byte-for-byte that extracted encoded chunks decode to the same data as
the canonical store. Check the seam where an inner chunk lies inside an outer
shard and confirm sharding has not accidentally become a seam-alignment
constraint.

Trace one real Neuroglancer request all the way through the production backend.
If that path does not exist, say exactly where the chain stops. Do not treat a
standalone range resolver as completed viewer integration.

### 5. Pyramids and live view consistency

Confirm every advertised canonical pyramid level exists and is derived from the
correct channel, plane and timepoint. Confirm downsampling is actually by halves
and that metadata describes the method used.

Raw-overlap and seamless views contain different pixels and therefore cannot
share one derived global pyramid. Determine what is linked, what is copied, what
is recomputed and what is still absent. Verify that a commit dirties exactly the
affected coarse chunks: too few produces stale scientific pixels; too many
turns live acquisition into quadratic work.

Measure or instrument repeated commits. Determine whether the current
implementation still recopies every previously committed position into both
full-resolution views and characterize the complexity and practical break point.

### 6. Production browser path

Distinguish:

- a real Neuroglancer renderer;
- a synthetic test server;
- `LivePublisher` used by a test-only server; and
- the actual `zmart-viewer/app/server` path the operator will run.

The production guarantee exists only when the last path performs discovery,
routes bytes, observes the manifest, invalidates the correct cached chunks and
refreshes stable sources without losing camera, annotations or controls.

Run honest and sabotaged browser cases if Chromium is available. A browser launch
failure is **blocked**, not passed. Add tests for cached missing chunks across a
commit, partial HTTP responses, several mosaic rows, channel/Z selection, raw
selector behavior and source/layer count over repeated revisions.

### 7. Analysis ownership

The design says analysis reads complete overlapping canonical positions as
context and publishes/counts only the result owned by an explicit,
layout-revisioned core. Check whether any executable analysis consumer currently
enforces that contract.

Test semantic masks, detections and instance masks that cross a seam; centroid or
anchor ambiguity; odd overlaps; four-tile intersections; later tile arrival; and
a layout revision changing membership. A correct visual crop does not by itself
prevent double-counted analysis results.

### 8. Scalability, recovery and portability

Review asymptotic behavior as well as unit correctness:

- number of files, metadata calls, sources/layers and open handles;
- memory retained per position, timepoint and revision;
- startup and commit cost at 10,000 positions and multi-terabyte scale;
- shard-index cache bounds and miss behavior;
- repeated full-tree scans or copies;
- manifest growth and recovery time.

This is intended mostly for Windows microscope computers and may use local disks
or SMB. Identify every conclusion supported only on Linux. Check declared Python
3.10–3.12 support; in particular, verify whether importing
`zmart_storage/canvas.py` still fails on Python 3.10.

Also inspect path safety, symlink/junction behavior, TOCTOU opportunities,
Windows device names, malformed metadata, decompression bombs and resource
exhaustion. Do not broaden this into a generic security checklist: tie findings
to a concrete reachable path.

## Known open items to verify, not merely repeat

The branch currently admits these gaps. Confirm their exact present state,
severity and dependencies, and look for additional gaps:

1. `ViewRoute` is persisted and used by the coordinator, but is not wired into
   `zmart-viewer/app/server`.
2. Full-resolution view writing still appears to copy all committed positions
   repeatedly, giving O(N²) total work over a growing run.
3. Raw and seamless global coarse view pyramids are not implemented.
4. Manifest-driven production frontend refresh and the concurrent analysis
   reader are not connected.
5. Canonical positions are intended to conform to OME-Zarr, while current view
   stores may still be bare arrays.
6. The browser production harness is not necessarily the application backend.
7. No several-row mosaic has been visually tested end to end.
8. Windows/SMB locking, recovery and shard/write performance remain unmeasured.
9. Python 3.10 compatibility may be broken by
   `zmart_storage/canvas.py`.
10. Native OME-Zarr scene serialization is intentionally deferred.

Do not inflate the finding count by listing each known omission twice. The
review's main value is verifying whether fixes 1–4 from the previous recommended
order are actually complete, testing how dangerous items 5–8 are, and finding
anything the previous reviews missed.

## Reporting requirements

Lead with a release verdict:

- safe reference implementation;
- suitable for controlled prototype use;
- suitable for live scientific decisions; or
- production-ready.

Do not choose a stronger category unless the evidence supports the entire path.

Rank findings by:

1. silently wrong pixels, coordinates or counts;
2. exposure of incomplete or stale committed data;
3. data loss or irreproducible publication state;
4. inability to operate at intended scale;
5. interoperability and portability failures;
6. maintainability and documentation contradictions.

For every finding provide:

- severity and affected scientific outcome;
- file and current line or symbol;
- the smallest concrete reproducer or failing input;
- expected versus observed behavior;
- whether you ran it or inferred it by reading;
- the likely root cause;
- the minimum credible fix; and
- the regression test that should remain.

End with four explicit sections:

1. **Verified by running** — commands, environment and observed results.
2. **Established by reading only** — and why execution was not performed.
3. **Claims that survived attack** — include only claims you genuinely tried to
   break.
4. **Recommended next slice** — the smallest vertical implementation that most
   increases confidence, in dependency order.

Answer these questions plainly:

- Are canonical positions genuinely interoperable OME-Zarr images?
- Are virtual raw and seamless views described honestly?
- Can any uncommitted or partially complete timepoint become visible?
- Can a committed image later change without a new revision?
- Do all axes, outer edges and overlaps produce correct pixels?
- Does analysis have an executable exactly-once ownership path?
- Is the real operator-facing Neuroglancer path connected?
- At what run size does the current implementation become impractical?
- What must be completed before this can guide live scientific decisions?

Review only. Do not repair product code during this pass. Temporary probes are
welcome, but restore the worktree completely and report their code or commands so
the failures can be reproduced.
