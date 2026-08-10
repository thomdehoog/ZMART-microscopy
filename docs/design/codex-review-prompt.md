# Review prompt for Codex

Everything below the line can be pasted into a reviewer as-is. It is written to
invite disagreement rather than approval: a reviewer who comes back with "looks
good" has told us nothing, and the useful outcome is a list of things that are
wrong, in an order we can act on.

---

## Where the code is

| | |
| --- | --- |
| **GitHub repository** | `thomdehoog/ZMART-microscopy` — https://github.com/thomdehoog/ZMART-microscopy |
| **Branch to review** | `agent/live-position-timepoint-publication` |
| **Head commit** | Use the branch's current `HEAD`; this prompt is versioned on that same branch, so pinning its own commit here is necessarily one commit stale. |
| **Compare against** | `claude/omezarr-neuroglancer-structure-srnwu6` (`2027f911`) |
| **Pull request** | #8 (draft) — https://github.com/thomdehoog/ZMART-microscopy/pull/8 |
| **Size of the change** | Use the compare command below for the current count; do not infer it from the branch's distance from `main`. |

**Do not diff against `main`.** This branch sits on top of another piece of work,
so `main` shows more than five hundred unrelated commits. The comparison that
shows only the work under review is:

```bash
git clone https://github.com/thomdehoog/ZMART-microscopy
cd ZMART-microscopy
git fetch origin agent/live-position-timepoint-publication \
                 claude/omezarr-neuroglancer-structure-srnwu6
git checkout agent/live-position-timepoint-publication

# everything under review, and nothing else
git diff origin/claude/omezarr-neuroglancer-structure-srnwu6...HEAD
```

Almost all of it is one new package, `zmart_live/`, plus two design documents
under `docs/design/`.

## Running it

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest zmart_live/ -q
```

The browser test also uses the operator page's Node dependencies:

```bash
cd workflows/target_acquisition/webapp-ui
npm ci
PLAYWRIGHT_CHROMIUM=/path/to/chrome \
  npx playwright test --config ../../../zmart_live/tests/browser/playwright.config.mjs
```

`PLAYWRIGHT_CHROMIUM` is optional when the configured authoring path exists. A
missing browser is an environment failure, not evidence that a sabotage was
caught; the fault harness now refuses to conflate those outcomes.

---

You are reviewing a live-microscopy storage and publication layer in
`thomdehoog/ZMART-microscopy`, branch `agent/live-position-timepoint-publication`.
Be adversarial and concrete. Assume the author is competent and has already
thought about the obvious things; your value is in what they missed.

## What the code is for

A microscope writes positions and timepoints continuously, sometimes for days. A
viewer (Neuroglancer) is open the whole time, and biologists make decisions from
what it shows. The requirement is that the viewer never displays data from a
position or timepoint that is only partly written.

That requirement is not about tidiness. A picture built from half-written data is
not a slow picture — it is a **wrong** one, it raises nothing, and it looks
exactly like a right one. The same is true of the counting: a nucleus in the
overlap between two tiles must be counted once, and an error there is a wrong
number in a paper rather than a stack trace.

Read `docs/design/live-position-timepoint-publication-decisions.md` for the
architecture, then `docs/design/live-writer-and-linked-views-plan.md` for the
implementation plan, which records the measurements the design rests on.

## What exists

All new code is under `zmart_live/`.

| file | what it claims to guarantee |
| --- | --- |
| `model.py` | one shared vocabulary; half-open regions; records that cannot be edited after publication |
| `profiles.py` | chooses chunk, overlap, step, pyramid depth and shard shape per acquisition type |
| `manifest.py` | durable monotonic publication record, recovery and one-writer exclusion |
| `ownership.py` | every pixel of a mosaic has exactly one owner, visually and for analysis |
| `coarse.py` | a zoomed-out piece never shows an uncommitted position |
| `shardlink.py` | validates and locates one encoded inner chunk inside a Zarr v3 shard |
| `scene.py` | internal scene contract compiles to a bounded Neuroglancer adapter payload; it does not create the backing view stores |
| `coordinator.py` | readiness is earned by inspection, never accepted from a caller; writes both view stores and refuses publication until all five checks hold |
| `viewroute.py` | a view advertises inner chunks while its positions stay bundled, so sharding does not constrain chunk choice |
| `tests/browser/` | real-Neuroglancer publication harness over a synthetic writer |
| `tests/browser/production/` | the same sequence driven by `LivePublisher`, the production path; both sabotages verified red |

**257 Python tests pass in about three seconds in the review environment.** The
browser test takes roughly a minute on the authoring machine.

Measured on a 71×71 mosaic: 5,041 positions become **2 sources, 2 layers, and a
payload of about 1,700 characters**, none of which grows with the run.

## Before anything else: try to make the tests lie

There are six fault checks. Each introduces deliberate faults one at a time and
reports whether the suite noticed:

```
python -m zmart_live.tests.check_the_tests_can_fail            # commit record, ownership, zoomed-out, coordinator
python -m zmart_live.tests.check_the_shardlink_tests_can_fail  # byte ranges out of bundles
python -m zmart_live.tests.check_the_scene_tests_can_fail      # sources and layers
python -m zmart_live.tests.check_the_viewroute_tests_can_fail  # inner chunks out of a bundled position
node zmart_live/tests/browser/check-the-test-can-fail.mjs                  # the synthetic neuroglancer test
node zmart_live/tests/browser/production/check-the-production-test-can-fail.mjs   # the production one
```

The last two take a few minutes each and need a Chromium that Playwright can
drive; the four Python ones take about ten minutes together.

They currently claim **94 Python faults and 4 browser sabotages, all caught**.
Your first job is to add faults they do not cover and find one that survives. A surviving fault is a claim the
suite is not really making, and it is the cheapest real finding available to you.

## The claims I want attacked

Each is load-bearing. Prefer running code over reading it — several of the
author's own conclusions were overturned by execution during this work, including
one that reversed a decision in the architecture record.

1. **The seam is given to the lower/right neighbour, every tile trimmed
   identically to one `step`.** The claim is that this makes every placement
   number a multiple of the step, raising the pyramid levels a view can point at
   from 1 to 4 (measured on a 3×3 mosaic of 2304-pixel frames at a 256 chunk).
   Verify against `zmart_storage/linked.py`'s *real* refusals, not the
   description. **This deliberately contradicts Decision 7 of the architecture
   record**, which says top/left wins. The claim is that the contradiction is
   harmless because both rules cover the mosaic identically and only move which
   tile supplies a pixel. Is that actually true at the component edges?

2. **The unsharded geometry survives the real linker, while the planned sharded
   route deliberately does not yet.** The stated rule `overlap % chunk == 0` is
   necessary but not sufficient — a 2000-pixel frame satisfies it and is still
   refused. Attack the unsharded test across frames and bands. Separately verify
   the explicit regression showing that `plan_the_writing`'s level-0 shard is
   rejected by the current whole-shard `link_the_tiles`; do not mistake the
   standalone byte-range resolver for completed integration.

3. **The preference ordering in `choose_the_geometry`.** It ranks staying inside
   the comfortable overlap band *above* chunk size, arguing that overlap is
   microscope time — minutes of a real experiment — while chunk size is only
   viewer latency. Getting this backwards was a real bug found during
   development. Is the current order right in every case, or is there a geometry
   where it produces a bad plan?

4. **The manifest cannot publish an event whose readiness flags are false.** It
   publishes by renaming a small file over another. Find a
   sequence — crash, two writers, a clock change, a reader mid-read, a full disk
   — where a viewer can observe a revision not fully backed by data. The claim is
   that a reader sees either the previous complete revision or the next, never a
   mixture.

   The flags are now *earned* rather than asserted: `coordinator.py` inspects
   what landed on disk and has no parameter that accepts a readiness flag. So
   the sharper question is whether its five checks are each independently
   load-bearing. Find damage that one of them should catch and none does —
   three faults of exactly that shape were found while writing it, and one was
   a real bug rather than a missing test.

5. **Every pixel has exactly one owner.** `ownership.py` claims no gaps and no
   duplicates for any rectangular mosaic, including odd overlaps and four-tile
   corners. The central test *sweeps* rather than checking the rule, but it uses
   a stride of 3 pixels. Find a case that stride misses, or a shape — single row,
   single column, L-shaped component, 1×1, a component with a hole — that breaks
   the invariant.

6. **A zoomed-out piece never shows an uncommitted position.** `coarse.py` states
   this as an equality: whether a second position exists on disk or was never
   started must make no difference to what the zoomed-out picture may show. Also
   check `chunks_touched_by` names *exactly* the affected pieces — too many is
   wasted work on the microscope's critical path, too few leaves a stale strip at
   every tile boundary that looks like specimen rather than a fault.

7. **Sharding does not constrain chunk choice.** `shardlink.py` lifts one inner
   chunk out of a Zarr v3 shard by byte range, and `viewroute.py` uses that so a
   view can advertise inner chunks while its positions stay bundled. Check the
   index parsing against the sharding-indexed spec: index location, CRC32C
   handling, entry order, the empty-chunk sentinel, and behaviour on a truncated
   file. A wrong byte range here decodes to plausible noise rather than failing.

   `test_the_sharded_plan_the_profile_chooses_now_links` asserts that the step
   divides the chunk but *not* the bundle, then serves pieces either side of the
   seam. Try to break the seam case where an inner chunk sits in the middle of a
   bundle, and the case where two positions could both claim one piece.

8. **Never one Neuroglancer source per position.** Measured
   in this repo, a thousand positions handed over separately drew 24 frames in
   five seconds where one linked image managed 255 — the cost is per source, paid
   on every frame forever. Also: the committed revision must live in a per-source
   *field*, never in the store URL, because a revision in the address makes the
   engine treat every commit as a new source and never drop the old one.

## The browser test specifically

`zmart_live/tests/browser/` drives a real Neuroglancer and proves:

```
commit A            -> A drawn, B not
write B, no commit  -> A STILL drawn and still bright, B still not
commit B            -> both drawn
```

The middle step is the interesting one, because "B was not drawn" passes over a
completely black screen. Two sabotage runs demonstrate it can fail in both
directions — committing B early, and refusing to serve anything. **Run them.**
Then ask what the test still cannot see. Candidates worth your time: a chunk
cached by the browser across a commit; a partially written chunk served with a
200; the position boundary not falling on a chunk edge.

## What is deliberately missing

State these as findings only if you think the omission is wrong, not merely that
it exists:

- Growing a run *beyond* the declared timepoint room.
- Any measurement on Windows, where the file-count argument actually bites.
- Zoomed-out copies for either view store. Both are written at full resolution
  only, so the run-wide picture has no prepared levels of its own.
- OME-Zarr metadata naming the raw view's selector dimension, which a viewer
  would need in order to label that slider.
- The last step of the shard route: `viz_studio/backend/linking.py` still
  understands only whole files, so exposing a byte range through the viewer's
  own server means adding a range form to the pointer record.
- Production viewer refresh. The browser harness proves the server's
  gate, not the application path that will consume the scene adapter.
- Native OME-Zarr 0.6 scene serialization; the current object is internal scene
  semantics with a 0.5-era adapter contract.

## How to report

Rank findings by whether they can produce a **silently wrong picture or a wrong
count**, then everything else. For each: file and line, a concrete failing input,
and what you would change.

Say explicitly which claims you verified by running something and which you only
read. If a claim survives your attack, say so — that is useful, but only if you
genuinely tried to break it.

One style note: docstrings here are written for microscopists and biologists who
are learning, not for software engineers (see `CLAUDE.md`). Flag anything
**inaccurate**, or jargon left unexplained. Do not flag prose for being long —
that is deliberate.
