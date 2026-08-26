# Response to the second Codex review: the seven blocking findings

> **Historical snapshot.** This file records the state at the time of that
> review and its “still open” section is intentionally not rewritten after the
> fact. The subsequent Claude review and implementation pass connected the
> manifest-aware gateway to `zmart-viewer/app/server`, made both views multiscale,
> changed normal updates from whole-history rebuilding to affected-unit updates,
> added production OME-Zarr metadata, and fixed Python 3.10 parsing. See
> `docs/reviews/2026-08-09-claude-review-fixes.md` for the current disposition and
> the remaining limits.

**Reviewed head:** `23661841`. **Re-review from:** `64d57ecb` on
`agent/live-position-timepoint-publication`.

Compare against `claude/omezarr-neuroglancer-structure-srnwu6`, not `main` —
this branch sits on top of other work and `main` shows hundreds of unrelated
commits:

```bash
git diff origin/claude/omezarr-neuroglancer-structure-srnwu6...64d57ecb
```

To re-run what is claimed below:

```bash
pip install "zarr>=3" numpy pytest
python -m pytest zmart_live/ -q                                  # 461, about 50s
python -m zmart_live.tests.check_the_tests_can_fail               # 71 faults, ~40 min
python -m zmart_live.tests.check_the_shardlink_tests_can_fail     # 25 faults
python -m zmart_live.tests.check_the_viewroute_tests_can_fail     # 21 faults
python -m zmart_live.tests.check_the_scene_tests_can_fail         # 14 faults
python -m zmart_live.tests.check_the_omezarr_tests_can_fail       # 15 faults
```

The browser work needs a Chromium that Playwright can drive. The suite passes
`executablePath` explicitly, because the pinned Playwright wanted a build that
was not installed here; that is the setting to change, not a browser to
download.

Every finding in that review was accepted. None was argued with, and two were
confirmed by direct inspection before any work started, so that whoever fixed
them was working from established fact rather than from a claim:

- `coordinator.py:459` hardcoded `z=1` in the seamless store's shape;
- `ownership.the_far_edges()` appeared nowhere outside its own tests, so the
  21% of every edge tile it computes really was being written as black.

Two constraints from the review are being honoured. **PR #8 stays a draft**, and
**nothing here is connected to the microscope.**

## How this work was done

Each finding was given to a separate worker owning a disjoint set of files, and
every one was told the same two things: **reproduce the defect with a failing
test before changing any production code**, and record the observed wrong
behaviour in that test's docstring. A fix without a test that failed first was
not accepted.

That discipline earned its place. Several defects turned out to be worse than
described once someone actually watched them happen, and two seeded faults were
found to be uncatchable and had to be rewritten rather than quietly counted.

## The blocking findings

### 1–5. The coordinator

**All five fixed.** Each was reproduced by a failing test before anything was
changed, and each was then independently attacked a second time by writing the
exploit afresh from the review's description rather than re-running the test that
came with the fix. A fix that only satisfies the test written beside it has not
really been checked, so both columns below matter.

| the defect | how it was got away with before | now |
| --- | --- | --- |
| an unwritten moment could be committed | `inspect(…, timepoint=1)` returned `pyramids_ready=True`, `pieces_read=3,525,120`, and the counter advanced for a moment holding not one byte | refused |
| a middle chunk of a zoomed-out level deleted | inspection still passed | refused |
| the seamless picture replaced entirely with zeros | `coarse_chunks_ready=True`, published a black image | refused |
| another run's arrangement swapped in | `layout_ready=True`, published | refused |
| the far edge of a lone tile | 21% of the image silently black | **0% black**, exact expected width |
| a three-plane stack | only plane 111 reached the seamless view | all of 111, 222, 333 |
| one plane offered for a two-colour run | copied into every colour | refused |
| a committed moment written over | canonical became 2000, the view stayed 1000, revision unchanged | refused |

The fixes worth describing rather than listing:

**Readiness is now derived from the exact pieces a moment owes.** Inspection
builds the list of chunks that moment is responsible for — its index on time,
every colour, plane, row and column — and asks the store for each one by key,
rather than reading the array and trusting what comes back. That distinction is
the whole defect: Zarr answers for an absent chunk with fill values, so
`array[:]` cannot tell "written as zeros" from "never written". Reading the array
is kept, but as the *decode* check it always was, since a chunk can exist and be
half a chunk long.

**The seamless picture is compared against the pixels, not measured.** The old
check asked whether an 8×8 corner had non-zero *size*, which is true of an
all-black image. It now reads the ground this position covers out of the view and
compares it against the position's own store at that moment.

**`links_ready` means something for the first time.** It was previously true with
no route map existing anywhere. A real route is now built through
`viewroute.route_the_view` — which refuses misaligned or doubly-claimed pieces —
persisted to `zmart-live/links.json`, read back, checked against this run and
plan, and then *followed*: every piece this position supplies at every linkable
level is resolved and its bytes decoded and compared. Ninety-three pieces where
two corners were checked before.

**The far-edge writer is called from production code.** `ownership.the_far_edges()`
existed and was exercised only by its own tests. The seamless writer now paints
what it reports, and the seamless *check* uses the same helper, so the writer and
the checker cannot drift apart.

**Replacement is explicit and generational.** A committed `(position, moment)` is
refused outright. `replace_a_position()` is the deliberate route: it writes a new
generation beside the old, leaves the old untouched, rebuilds both shared pictures
and the route map from it, and publishes a `position_replaced` event — so the two
readers move together under one new revision instead of disagreeing under the
same one.

Twelve faults were added to the coordinator's campaign, nothing removed. **All 27
coordinator faults are caught**, and the 15 that predate this work still fire, so
none went stale.

Two caveats recorded rather than smoothed over. `pieces_read` still counts through
`array[:]`, which reads every moment rather than only the one being inspected —
a genuine decode check, just broader than the unit. And the far-edge strips are
written into the seamless store rather than pointed at, so the route map
deliberately does not cover them.

### 6. The browser harness gated by position, not by moment

**Fixed, and it was worse than reported.** Both halves were reproduced on a real
screen first.

In the three-tile case — A and B published, C written but not published —
C was **fully drawn**, and the server's own counters showed why: `A: served 225`,
`C: served 0, refused 0`. Every one of C's chunks was served *under A's name*.
The server never knew it had been asked for C at all. The two-tile fixture could
not see this, because sharing a stop only becomes possible with three.

The later-moment case was equally plain: with A's second moment written but not
published, `A moment 1: served 64, refused 0`, fully drawn.

The fix keys availability on the `(position, moment)` pair read from the piece's
own address, and attributes raw-view pieces by **stop plus spatial region**
rather than by stop alone — stops are deliberately reused by tiles that cannot
overlap, which is exactly what made the old rule wrong. A start-up check now
refuses to serve any run in which a raw piece could hold two same-stop tiles.

Afterwards: `C: served 0, refused 81`, `A moment 1: served 0, refused 64`.

The sabotage script grew to six faults, all caught, and gained a guard that
lists the runner's real test titles first — because "no test matched" and "a test
failed" look identical from outside, so a reworded title would otherwise be
silently recorded as a fault caught.

### 7. The positions were not conforming OME-Zarr images

**Fixed.** `zarr.open_group()` now succeeds. The group carries `ome.version`,
`multiscales`, axes with UDUNITS-2-checked units, per-dataset scale and
translation, and `dimension_names` on every level. Levels are described first and
the group declared second, so an interruption never leaves a folder announcing
itself as an image it is not.

Fifteen seeded faults, all caught on the first run.

Two details worth recording because they are the kind of thing that makes a test
prove nothing. The headline test opens the group with `mode="r"`, because the
default `mode="a"` **creates** the missing group — written the obvious way, that
test would have passed against the unfixed code. And the multiscale `type` is
`"mean"` rather than `"nearest"`, because the coordinator genuinely averages
two-by-two blocks; describing it otherwise would have been a false statement
about the data in a file other people's software reads.

## What was verified, and how

Everything below was run on a settled tree after all the work had landed, not
reported from the workers who did it.

| check | result |
| --- | --- |
| Python suite | 461 passed |
| `ruff check zmart_live/` | clean |
| full fault campaign | **71 faults, none uncaught** |
| independently written exploits for findings 1–5 | 8 of 8 blocked |
| browser tests against the landed coordinator | 3 passed |
| production sabotages | **6 of 6 went red** |

The exploits were written afresh from the review's wording rather than by
re-running the tests that came with each fix, because a fix that only satisfies
the test written beside it has not really been checked.

Two corrections to my own checking, recorded because they are the same class of
mistake this review is about. My first exploit reported the far edge still 66.7%
black; that was my test's fault — it built a run with three moments and wrote
one, so two thirds was legitimately unwritten. Measured on the moment actually
written, the seamless picture is 0% black at one tile and at two. And my first
sabotage run appeared to show five faults caught rather than six; that was a
filter in my own command dropping a line, not a fault surviving.

The browser harness's drift guard had to be reconciled with the coordinator's
refactor, which split `write_and_publish` into a public method and a private
helper. Rather than update the list of steps it compares against — which would
have made it weaker — the guard now **follows into private helpers**, so it reads
the real sequence wherever the code puts it. Otherwise a refactor that merely
moved those steps somewhere it could not see would leave the test measuring a
sequence nobody runs, which is the exact failure the guard exists to prevent.

## Identity and persistence

All five fixed, each reproduced first.

- **Profiles are persisted**, atomically, and re-fingerprinted on load so a
  hand-edited file is caught rather than believed.
- **Profile identity is content-addressed** over the whole profile. The
  reviewer's two colliding `confocal-1152-128` profiles now get different names.
  `channels` had to be added to `AcquisitionProfile` for this: without it the
  fingerprint could not cover the colours, and a profile whose identity does not
  cover its contents is not sealed at all.
- **Names are path-safe**, checked when the record is built, before any pixels
  are written. `../../escaped` is refused, as are Windows device names such as
  `CON` and `CON.txt`, since this runs on Windows microscope computers.
- **Layout revisions are numbered and immutable.** A changed arrangement mints
  the next snapshot; an arrangement that says the same thing reuses the existing
  one, which is what the decision record asks for.
- **Rectangular frames** are supported per axis. The square-only shorthands now
  refuse to answer for a rectangle rather than handing back one of two sides.

One seeded fault — *measure the width's overlap against the height* — was **not**
caught at first, because a 2:1 rectangle still gives the right answer. The tests
were widened to four shapes in both orientations until it was.

## Scaling: the shard resolver

**Reproduced, diagnosed and fixed — and the diagnosis was not what anyone
expected.**

The reviewer measured about 71 ms per chunk request; 90 ms was reproduced here on
a 96-plane bundle. But measuring rather than assuming showed that **95% of it was
the CRC32C checksum**, computed one bit at a time over a 124 KB table. That
matters independently of any cache, because during a live run the bundle being
written keeps changing and every request legitimately misses.

| planes per bundle | as it was | reading afresh now | remembered |
| ---: | ---: | ---: | ---: |
| 12 | 12.0 ms | 1.7 ms | 33.8 µs |
| 24 | 24.0 ms | 3.4 ms | 40.5 µs |
| 48 | 49.4 ms | 6.9 ms | 29.8 µs |
| 96 | **90.2 ms** | 15.7 ms | **29.3 µs** |

The shape is the finding. The old cost **doubled every time the bundle doubled**
— it was proportional to the whole table, not to the one chunk being asked for.
Remembered is flat. Expressed as a count, which survives a busy machine where a
timing does not: one screenful of 48 requests now reads **one** table off the
disk instead of forty-eight.

The cache is keyed on the file's full identity — path, device, inode, size and
both timestamps, plus the geometry the table was parsed with — so a rewritten
bundle misses rather than serving a stale index. It is bounded twice, by
remembered positions and by remembered bundles, so neither a few huge bundles nor
many tiny ones can grow it without limit.

`viewroute` was also re-reading each position's description on every request,
about two thirds of what remained after the checksum fix.

Three things that worker declined to claim: the re-stat guard is untestable and
is recorded as a claim the tests do not make; one seeded fault was uncatchable
and was rewritten into two that are; and the miss path is still 15.7 ms on the
largest bundle, with the next step identified but deliberately not taken.

## A flaw found in our own evidence

Two workers independently hit the same trap, and it undermines every fault
campaign in this repository, so it is reported here rather than buried.

Python decides whether its compiled copy of a module is still valid from the
source's **size** and the **second** it last changed. A seeded fault that swaps
one word for another of the same length, and is reverted within the same second,
leaves both unchanged — so the compiled copy holding the **faulty** version stays
in use. The campaign restores every file correctly, reports every fault caught,
and the next ordinary test run silently executes the broken code. One worker
watched exactly that: a green campaign followed by eight failures from a file
that had already been put back.

The shared harness now discards the compiled copy after every rewrite.

**What is honestly established about that fix:** the guard removes the compiled
copies it says it removes, and that is demonstrated. Staging the trap
deliberately on this machine did *not* reproduce it — the restored answer came
back every time — so something here hides it. The guard is kept because it is
cheap and certainly correct, not because a test here demonstrates the failure it
prevents.

## Against the recommended order

The review closed with eight steps. Answering them directly, so the next pass
does not have to work out what moved:

| # | recommended step | state |
| --- | --- | --- |
| 1 | regression tests for the reproduced failures | **done** — each defect has a test that failed first, with the observed wrong behaviour in its docstring |
| 2 | per-timepoint inspection and gating; forbid mutation of committed units | **done** — findings 1 and 5, verified by independently written exploits |
| 3 | complete outer-edge coverage; correct Z and channel handling | **done** — findings 3 and 4; the seamless picture is 0% black at one tile and at two |
| 4 | valid canonical OME-Zarr 0.5; content-addressed profiles; immutable layout revisions | **done** — finding 7 and the identity section |
| 5 | connect ViewRoute to the real backend; remove full-resolution view copying | **half done, and the half that is missing is the larger one.** A real route is now built, persisted and followed by the coordinator, which is what makes `links_ready` mean anything. It is *not* wired into `zmart-viewer/app/server`, and the view stores are still written at full resolution, so the copying is untouched |
| 6 | implement and validate affected raw and seamless coarse pyramid chunks | **not done.** Neither view store has zoomed-out copies at all; `coarse.py` plans the work and nothing writes those pixels |
| 7 | manifest-driven viewer refresh and concurrent analysis ownership | **not done.** The browser harness still invalidates Neuroglancer's cache by hand, and there is no analysis reader |
| 8 | benchmark shard geometry, locking and recovery on Windows and SMB | **not done.** Every measurement here is Linux on a four-core shared machine |

So steps 1 to 4 are complete and steps 5 to 8 are the remaining work, with step 5
partly begun. That ordering still looks right, with one caveat worth raising: the
quadratic view copying in step 5 is the thing that makes this unusable at real
run sizes, and it is a design change rather than a repair. It may deserve to come
before the rest of step 5 rather than alongside it.

## Still open, and not claimed as fixed

- **The O(N²) view copying.** Every commit still recopies every committed
  position into both full-resolution stores. This is not a defect to patch; it is
  the zero-copy design that was agreed and never built — virtual routing for
  linkable levels, and incremental materialization of only the affected coarse
  chunks. It is the next substantial piece of work.
- **The view stores are not OME-Zarr images either.** Finding 7 was fixed for
  positions; `views/overview-seamless.ome.zarr` and `overview-raw.ome.zarr` are
  still bare arrays, and the view is what an operator actually opens.
- **The browser harness is still not the application path.** It uses a server in
  the test directory rather than `zmart-viewer/app/server`, with no `ViewRoute`, no
  scene discovery and no production refresh, and it calls Neuroglancer's internal
  cache invalidation by hand. The README now says so at the top.
- **No mosaic several rows deep has been watched on a screen.** Stop attribution
  does not assume a single row, but every browser run so far has been one.
- **Nothing has been measured on Windows or SMB**, which is where the file-count
  argument that justified sharding actually bites.
- **`zmart_storage/canvas.py` does not parse on Python 3.10** while
  `pyproject.toml` declares `>=3.10`. Pre-existing, and now inherited by
  `zmart_live.omezarr`, which imports it.
