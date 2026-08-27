# Response to the adversarial review

**Reviewed commit:** `555d3238`. **This response:** `7db5e572` and later.
**Branch:** `agent/live-position-timepoint-publication`.
**Compare against:** `claude/omezarr-neuroglancer-structure-srnwu6` (`2027f911`).

This answers [`codex-review-findings.md`](codex-review-findings.md) point by point.
It is written so that a second review can start from what changed rather than
from the beginning, and it is deliberately explicit about which claims were
checked by running something and which were not.

The findings were good. Two of them were faults in code that had passed a
mutation check, which is the useful kind of criticism: not that the tests were
absent, but that they were testing the wrong thing.

## The headline

The review's sharpest sentence was that a caller could construct an event with
every readiness flag true without this package having validated the artifacts
those flags describe. That is now closed. `zmart_live/coordinator.py` writes a
position, goes and looks at what actually landed, and builds the publication
event out of **what it found**. There is no parameter anywhere in it that accepts
a readiness flag, and a test asserts that by inspecting the signatures, so that
re-opening the hole fails the suite rather than passing quietly.

The other three items under "established by reading" are being worked on and are
**not** claimed as done in this document. They are listed at the end with their
status.

## The environment blocker is closed

The review could not run the real-browser assertion: Playwright's Chromium
download returned something that was not an archive, and no compatible browser
was present. That was the environment rather than the test.

With a Chromium already installed the whole sequence runs against a real
Neuroglancer:

- the honest run passes in about 47 seconds, and the server's own request
  counters agree with the pixels — four of the second position's pieces were
  asked for and refused while it was uncommitted, and served once it was not;
- **both sabotage runs go red**, including the one that blanks the screen, which
  is the failure the whole objection was about.

For anyone reproducing it: Playwright's pinned browser build may differ from the
one installed, so the tests pass an explicit `executablePath`. That, rather than
downloading a browser, is the setting to change.

This does **not** by itself close finding 4. See the status table.

## What the coordinator now checks

Four things, each corresponding to a way an operator could otherwise be shown a
confident picture of nothing.

| what is checked | how | what it catches |
| --- | --- | --- |
| the pixels and every zoomed-out copy | each advertised level is opened and read back in full | a level never written; a piece that will not decode |
| the pointers | for each pointed-at level, a byte range is resolved out of its bundle, decoded alone, and compared against the image | a range that is subtly wrong, which decodes perfectly and shows the wrong specimen |
| the shared zoomed-out picture | rebuilt from committed positions only, then read back | an unpublished position appearing at low magnification, where it looks like specimen |
| the arrangement | written down and read back before anything refers to it | a published measurement with nothing to point at |

## Three claims the tests were not really making

Writing the coordinator's fault list found three, and one of them was a genuine
bug rather than a missing test. Recording them because they are the same shape as
the review's own best findings.

**The pixel read was decorative.** The count of pieces read came from the array's
*description* rather than from the read, so deleting the read changed no number.
The truncated-chunk test had been passing on the pointer check instead. Counted
from the read itself now.

**A single readiness flag could be hard-coded true** while the overall answer
stayed right, because all four checks shared one list of complaints. Each check
now keeps its own, so a flag that is wrong is a fault even when the overall
answer is not.

**The pointer check compared byte counts**, which the resolver already validates,
rather than comparing pixels, which nothing else does. It now decodes the lifted
bytes and compares them against the image.

Fixing the third surfaced a fourth, worth knowing about: comparing pixels failed
every **edge** piece, because a piece at the edge of a level is stored full-sized
and padded while the image stops where the specimen does. The comparison is now
made over the part that genuinely exists. Missing this makes every edge piece
look wrong at every level whose width is not a whole number of pieces.

## Status of every item under "established by reading"

| # | item | status |
| --- | --- | --- |
| 1 | No coordinator earns readiness | **closed** — `coordinator.py`, 15 mutation faults all caught |
| 2 | The shard resolver is not connected to a view | **closed in `zmart_live`** — `viewroute.py`, 25 tests, 18 faults caught; the viewer's own server still speaks whole files |
| 3 | The raw and seamless stores are descriptions | **closed** — both are written, validated, and refused when absent |
| 4 | The browser harness bypasses the production path | **closed** — the sequence now runs through `LivePublisher`, both sabotages red |
| 5 | Windows and target-filesystem behaviour unmeasured | **open**, and untouched |
| 6 | OME-Zarr scenes remain semantic only | **open by choice**, consistent with the decision record |

### Finding 2: what is closed and what is not

A view can now advertise **inner chunks** while its positions stay bundled.
`viewroute.py` resolves a view chunk to a byte range inside a bundle, and a test
builds exactly the geometry `plan_the_writing("overview", frame=1152)` emits,
asserts `step % chunk == 0` while `step % bundle != 0` — the finding stated as an
assertion — and then decodes pieces on both sides of the seam to bytes identical
to what zarr returns.

A companion test watches `zmart_storage.linked.link_the_tiles` **refuse** the same
seam while the new route accepts and serves it, which is the whole-file
limitation demonstrated rather than described.

`zmart_storage` was not modified. The remaining step is the viewer's own server:
`viz_studio/backend/linking.py` still understands only `held_as: "file"`, and
connecting it means adding a range form to the pointer record. Small, on a proven
format, and **not done**.

The writer's single scalar shard was deliberately left alone. On this route the
view is never bundled — it hands over one encoded chunk, so it must declare the
inner chunk and no sharding of its own. Bundling exists to reduce file count, and
the view writes no picture files at all.

### Finding 3: how two measurements of one place are both kept

Two overlapping tiles genuinely recorded different measurements of the same
specimen. Writing them into one scalar picture means the last writer wins, which
destroys one measurement silently — the exact failure this package exists to
prevent.

The raw view therefore has a **selector** dimension. What one stop on it means is
chosen from the geometry rather than from the positions: two tiles can only share
specimen if they sit within one frame of each other, so the number of stops per
axis is `ceil(frame / step)` — two for the 1152 profile, four stops in total. The
tiles fall into interleaved sets like the squares of a chessboard, and no two
tiles in one set ever touch.

This matters at scale: one stop per position would be a five-thousand-stop slider
on a real run, nearly all of it empty wherever the operator is looking. Four
stops stay four stops however large the mosaic grows.

Verified directly: two neighbours written as 1000 and 2000, and over the strip
they both photographed, one stop reads uniformly 1000 while the other reads
uniformly 2000. The seamless view over that same strip holds exactly one of the
two, which is the contrast that justifies keeping both stores.

### Finding 4: closed, and what it does and does not show

The three-step sequence now runs against a real Neuroglancer with the run written
and published by `LivePublisher`. The middle step is `write_and_publish` stopped
one step short of the commit, which matters: writing the position alone would
leave its pixels out of the picture the viewer reads, so "not drawn" would be
true because there was nothing to draw and the gate would be untested. As
written, the pixels genuinely sit in the served image and only the commit hides
them — which the `commit-b-early` sabotage proves by measuring a full 1.000 the
instant it is committed, with no image bytes changed.

A guard parses what `write_and_publish` actually does and refuses to start if the
test's copy of the sequence falls behind it.

Still not shown by this: per-source invalidation, and shard-range serving through
the viewer's own server. Only level 0 is served, so the case where one coarse
piece covers a committed and an uncommitted position at once is out of its scope
— that one is covered separately in `test_coarse.py`.

**Finding 5 is the one that should worry a reader most.** Every measurement on
this branch is from Linux. The file-count argument that justified sharding at all
is about moving hundreds of gigabytes between Windows microscope computers, and
that has not been measured once. The shard sizes in `profiles.py` are reasoned,
not benchmarked, and the decision record itself asks for a Windows benchmark.

## What is deliberately still absent

Raised here so that a second review can tell a decision from an oversight:

- the analysis-ownership half of Decision 9 (required tests 17–22);
- growing a run beyond the declared timepoint room;
- native OME-Zarr 0.6 scene serialization.

## Where to look

```bash
git diff 555d3238..HEAD -- zmart_live/            # everything since the review
python -m pytest zmart_live/ -q                    # 276 tests, about 16 seconds
python -m ruff check zmart_live/
python -m zmart_live.tests.check_the_tests_can_fail
python -m zmart_live.tests.check_the_shardlink_tests_can_fail
python -m zmart_live.tests.check_the_scene_tests_can_fail
```

The browser sequence, from `application`:

```bash
npx playwright test --config ../../../zmart_live/tests/browser/playwright.config.mjs
node ../../../zmart_live/tests/browser/check-the-test-can-fail.mjs
```

## What would be most useful to attack next

In the order we would find it most valuable:

1. **The coordinator's four checks.** Each is meant to be independently
   load-bearing. Find damage that one check should catch and none does — the
   three faults above were exactly that shape, and there are probably more.
2. **`_the_same_picture` in `coordinator.py`.** It decodes a lifted byte range
   into a scratch array and compares. Find a case where it reports a match it
   should not, particularly around edge pieces, unwritten pieces and differing
   codec settings.
3. **The seamless view's rebuild.** It is rewritten from committed positions on
   every publication. That is correct and it is O(published) work per commit,
   which the decision record puts on the acquisition's critical path and nothing
   here budgets.
