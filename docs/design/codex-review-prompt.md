# Review prompt for Codex

Paste everything below the line into Codex, pointed at the branch
`agent/live-position-timepoint-publication`.

It is written to invite disagreement rather than approval. A reviewer who comes
back with "looks good" has told us nothing; the useful outcome is a list of
things that are wrong, in an order we can act on.

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

All new code is under `zmart_live/`. It is complete and tested except where noted.

| file | what it claims to guarantee |
| --- | --- |
| `model.py` | one shared vocabulary; half-open regions; records that cannot be edited after publication |
| `profiles.py` | chooses chunk, overlap, step, pyramid depth and shard shape per acquisition type |
| `manifest.py` | nothing half-written is ever published; the revision only goes up |
| `ownership.py` | every pixel of a mosaic has exactly one owner, visually and for analysis |
| `coarse.py` | a zoomed-out piece never shows an uncommitted position |
| `shardlink.py` | one chunk can be lifted from a Zarr v3 shard by byte range, so bundling does not constrain chunk choice |
| `tests/browser/` | the above, proven in a real Chromium with a real Neuroglancer |

**211 Python tests, about 5 seconds. The browser test takes about 47 seconds.**

`scene.py` compiles a run into Neuroglancer sources and layers. Measured on a
71×71 mosaic: **5,041 positions become 2 sources, 2 layers, and a payload of
about 1,700 characters** that does not grow with the run.

## Before anything else: try to make the tests lie

There are two mutation checks. They introduce deliberate faults one at a time and
report whether the suite noticed:

```
python -m zmart_live.tests.check_the_tests_can_fail
python -m zmart_live.tests.check_the_shardlink_tests_can_fail
node zmart_live/tests/browser/check-the-test-can-fail.mjs
```

They currently claim **55 faults, all caught**. Your first job is to add faults
they do not cover and find one that survives. A surviving fault is a claim the
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

2. **`plan_the_writing` never emits a plan the real writer rejects.** The stated
   rule `overlap % chunk == 0` is known to be necessary but not sufficient — a
   2000-pixel frame satisfies it and is still refused. Find a frame, overlap band
   or acquisition type where the chooser emits something `link_the_tiles` will
   not accept. **This is the highest-value bug available to you.**

3. **The preference ordering in `choose_the_geometry`.** It ranks staying inside
   the comfortable overlap band *above* chunk size, arguing that overlap is
   microscope time — minutes of a real experiment — while chunk size is only
   viewer latency. Getting this backwards was a real bug found during
   development. Is the current order right in every case, or is there a geometry
   where it produces a bad plan?

4. **Nothing half-written can be published.** `manifest.py` gates on four
   readiness flags and publishes by renaming a small file over another. Find a
   sequence — crash, two writers, a clock change, a reader mid-read, a full disk
   — where a viewer can observe a revision not fully backed by data. The claim is
   that a reader sees either the previous complete revision or the next, never a
   mixture.

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
   chunk out of a Zarr v3 shard by byte range. Check the index parsing against
   the sharding-indexed spec: index location, CRC32C handling, entry order, the
   empty-chunk sentinel, and behaviour on a truncated file. A wrong byte range
   here decodes to plausible noise rather than failing.

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

- The analysis-ownership half of Decision 9 (required tests 17–22).
- Growing a run *beyond* the declared timepoint room.
- Any measurement on Windows, where the file-count argument actually bites.
- The non-seamless overview. `viz_studio/backend/library.py` groups stores by
  voxel size and channel names, which the two overviews agree about exactly, so
  they would merge into one row with one contrast control. Is the proposed fix
  in the plan sufficient?

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
