# A second opinion on the OME-Zarr plan, and what it changes

A critical review of
[`ome-zarr-plan-for-review.md`](ome-zarr-plan-for-review.md), taken 7 August 2026
by a reviewer given the plan, the decision register and a read-only copy of the
code, and asked above all to find what is over-engineered.

It found a good deal. Two items on the build list change or disappear, one
substantial module should be deleted, one measurement not in the plan turns out to
matter more than several that are, and one of the questions the plan was least
confident about is answered in its favour.

**This document records the critique and what follows from it.** Where the review
disagrees with a decision already recorded elsewhere, this page is the later one
and should be treated as such. Note also that **no production code has changed**
on account of any of it: everything here is a decision or a measurement, and the
writer, the viewer and the modules discussed below are all still as they were.

**Two of its findings did not survive a second look, and are marked as refuted
where they appear.** They are the line count given for the view mechanism under
"The questions the plan asked", which was wrong by a factor of four, and the
claim that B7 retires `cropped.py`. A third, the "capping hazard" in item 1, was
struck out in an earlier pass and has since been **reinstated**: the refutation
answered a different question, and measurement has now shown the original finding
was right. All of that is left standing where it appears, with the round trip
recorded beside it rather than tidied away, because a review is a record, and a
record with its mistakes quietly removed is a worse one.

---

## What changed on the build list

| | was | now |
| --- | --- | --- |
| **B1** | repair — per-dataset translation | **unchanged, but it cannot land alone.** Confirmed real at `canvas.py:1921`, and the fix already exists in the repository: `linked._say_where_each_resolution_sits` does exactly the right thing for views, and moving that logic into `_declare_one` is about twenty lines. The view's reader must change with it, because it adds the image-wide translation and then every dataset's as well — see the plan's section 3. |
| **B2** | repair — bundle every level, capping small ones | **qualified.** This review's objection to the capping was struck out in an earlier pass and has since been reinstated on measurement: a capped bundle and a full-sized one are not interchangeable. B2 stands, but not as written while the view points at capped small levels. See "the capping hazard" below. |
| **B3** | repair — the server reads a bundle index | **deleted. It is already built.** |
| B4 | two interop tests | **raised. Highest value per line in the list.** One detail for whoever writes them: a channel with no explicit display window is refused by the validator as well, so the test position must declare one. |
| B5 | `plan_a_grid` | keep, but it is about fifteen lines plus a report. Do not let it become a planner. |
| B6 | `owned_ROI_table` | keep, and **merge with B10** and the useful residue of the coverage record. |
| B7 | chunk-aligned seams | **raised above B5 and B6.** ~~It deletes the most code, by retiring `cropped.py`.~~ **Refuted:** `cropped.py` stays — though not for the reason first given here, which was itself wrong. See "Two writers" below. B7 is still worth doing; it just retires no module. |
| B8 | unique label numbers | keep. Non-negotiable and independent. |
| B9 | a view for segmentations | **deferred.** A second copy of the whole view mechanism, for runs that do not exist yet. Build it when a labelled run actually meets the cliff. |
| B10 | a run-level table | keep, merged with B6. |
| B11 | 0.5 as the default everywhere | **mostly absorbed** — ~~retiring `cropped.py` deletes one of the two writers it exists to fix~~ (refuted with the B7 row above: `cropped.py` stays, so both writers need the default). What remains is a default argument. |
| **new** | — | **Stop re-reading every tile the view has just written.** See below. |

Eleven items become **B1, B2 (qualified as below), B4, B5, B6+B10, B7, B8, and
the new one.**

---

## The three things to change first

### 1. B3 is a phantom — and the objection this review raised to B2 stands after all

**The server already does what B3 asks.** `viz_studio/backend/server.py` parses
`Range` headers including suffix ranges — `bytes=-N`, which is exactly how a shard
index is read — routes `do_HEAD` so the engine can ask a shard's length, and
serves an arbitrary byte window of a file.

**And the design never needs an index anyway.** `zmart_storage/linked.py`
deliberately returns the *shard* shape for a sharded array, and the pointer map is
written in those units. So a whole shard file is handed over at offset zero, and
the browser reads the shard's own index and issues its own range requests — which
the server already honours. There is an end-to-end test:
`test_a_bundled_run_draws_every_voxel_where_it_was_acquired` builds sharded tiles,
points at them, serves them through the real server, and reconstructs the specimen
bit-for-bit.

**The capping hazard — refuted once, and reinstated on measurement.** The claim
stands as written below; the record of the round trip it took follows it.

Both the register and the ngio proposal praise capping the
bundle at each level's own extent for the small levels. That is a silent
correctness fault against `viz_studio/backend/linking.py`:

```python
shrink = 2 ** level
found = self._tile_covering((z, y * shrink, x * shrink))
piece = self._named(frame, channel, from_z, from_y // shrink, from_x // shrink)
```

This assumes the addressing unit covers **the same number of voxels at every
level**. Cap the shard at a small level's extent and that stops being true, so the
name refers to a shard that either does not exist — a blank picture — or exists
and holds different ground: **a picture of noise, with nothing reported.** It is
precisely the failure `linked.py` spends two hundred lines refusing elsewhere,
arriving through a change the plan called a repair.

**And ngio does exactly this capping**, which section 5 of the plan praised it
for.

Either cap nothing and let small levels be one shard each naturally, or stop
`pointed_levels` at the last level whose shard geometry is uncapped — and assert
it.

> **The round trip this finding took, recorded rather than tidied away.** A
> later reviewer refuted it on the grounds that a capped shard and an uncapped
> one resolve **bit-for-bit identically**, and an earlier pass struck the finding
> out on that basis. **That refutation answered a different question.** It asked
> whether a capped shard's *pixels* decode correctly when the shard is read on
> its own, and they do — but the view never reads a shard on its own. It forwards
> the bytes under its *own* declared shape.
>
> Measured: a position's level 1 holding 256×256 voxels, with its shard capped to
> 256×256, comes to **112,220 bytes** against **112,412** for an uncapped shard
> holding the same pixels. Not identical. The 192-byte gap is the shard's index —
> a 512-voxel shard indexes 4×4 = 16 inner chunks at 16 bytes each, a capped
> 256-voxel one indexes 2×2 = 4 — and that index is checksummed, so handing the
> capped bytes to a reader expecting the uncapped shape **fails with a checksum
> error**. Capping is safe for a position opened directly and unsafe for a view
> that forwards bytes: two different questions.
>
> So the finding above **stands after all**, and its remedies are live again,
> alongside the better one the plan now carries: let the view advertise the small
> inner chunks and serve an inner chunk rather than a whole shard file.
>
> One thing the refuting pass added is worth keeping, because it is true and was
> missed here. `zmart_storage/canvas.py` line 1992 reads
> `if shard is not None and level == 0:` — the writer shards **only the
> full-resolution level** and leaves the whole pyramid above it loose. That is a
> second and plainer fault, and exactly what B2 was put on the list to repair.

### 2. Delete `zmart-coverage` — but not for free

It is 845 lines with 841 lines of tests, and in the arrangement being proposed it
is already dead:

- **Nothing in the recommended write path writes it.** `positions.py` never
  imports it; both view constructors pass `records_coverage=False`. Only the
  copying writer writes it.
- **Nothing in the viewer reads it.** Zero references in `viz_studio/backend/`
  outside a comment. Its only consumer is a measurement prototype.
- `positions.py` lists `zmart-coverage/` in its on-disk layout diagram, which is
  untrue of the code beneath it.

**Declared geometry replaces it, and from closer than expected.** The `zmart`
pointer map already holds each tile's origin and size in chunk units — it *is* the
tile list. The three problems the module's docstring motivates itself with are all
answered by it: requests for never-imaged ground are already refused by
`_tile_covering` returning nothing; dark-versus-never-visited is answered at chunk
granularity, which is the granularity a viewer draws at; and a second front end
reads the same file, which travels inside the image's own metadata.

**But what dies is more than this page first said.** It claimed the useful
residue was one column of the run-level table, and that understates it. Coverage
records the moment in time and the channel, when each tile was written and in
what order, the exact origin and shape, the scan's own tile numbering, repeated
visits to the same place, and whether a leg of the run finished or was abandoned.
A single channel column replaces none of that, and the pointer map omits `t` and
`c` deliberately.

So the deletion should not be presented as free. The honest choice is between two
things: **either build the append-only run event manifest first** — one line per
write, holding the store, the placement, the owned rectangle, the frame, the
channel, the time and the tile number, from which the pointer attribute, the
timepoint count and the B10 table can all be derived — **or state plainly which
of those capabilities are being given up.** Either way the module's own argument,
that coverage must never be inferred from brightness on a photon-counting
detector, survives completely; it just becomes an argument for reading the record
rather than the pixels.

### 3. Stop re-reading every tile the view has just written

`GrowingLinkedView._fill_this_tile_in`:

```python
held = zarr.open_group(str(placed.store), mode="r")["0"]
picture = np.asarray(held[:, :, ...])
```

`positions.Run.write` has just written that array from a numpy array it was
holding, and then hands the *path* to the view, which reopens the store and reads
it back. **On a five-terabyte run that is five terabytes of pointless read and
decompression, in the live acquisition path, on the microscope computer.**

Worse, `canvas._write_smaller_copies` then strides from full resolution even when
starting at level 5 — it could shrink from the tile's own coarsest pointed level,
a two-hundred-and-fifty-sixth of the data, for bit-identical output, because
striding is transitive.

Two small independent fixes: pass the array through `PlacedTile` rather than
re-reading it, and feed the smaller-copy writer the coarsest level that already
exists.

**This was not on the build list at all, and on a real run it is worth more than
several items that were.**

---

## The other bloat candidates, judged

**Two writers — ~~retire `cropped.py`~~ (refuted below), keep `canvas.py`, but
not for the stated reason.** `canvas.py` is not merely the copying writer; it is also *the view's own
declarer*. Both view constructors call `TileCanvases.create`, and the growing view
calls `canvas.only_the_zoomed_out_copies` for every tile. Delete it and pointing
stops working.

~~What can go is `cropped.py` — 965 lines plus 898 of tests, since B7 turns the
trim into the placement's own `taken_from`/`size`, which `linked.py` already
supports and already checks.~~ **REFUTED — keep it.** But the reason first given
here was wrong, and so was the description of the module.

The reason first offered was that reading a small rectangle still drags a whole
shard off disk. Logging every byte range a read actually asks for shows
otherwise: a sharded array fetches the shard's index plus only the inner chunks
the rectangle touches. A 10×10 read from ZMART's own **855,499-byte** shard
fetched **53,744 bytes, or 6.28%**; from a shard with smaller 64-voxel inner
chunks it fetched **10,071 bytes of 1,535,521, or 0.66%**. What sets the cost of
a small read is the inner chunk size, not the shard size. And `cropped.py` is not
a rectangle-reading tool at all: it is a **writer**, whose own docstring says it
writes the acquisition twice, once whole and once trimmed. There is no
rectangle-reading function in it.

An earlier pass here called `cropped.py` the only path that handles overlapping
tiles at all. That is too strong. A linked view *can* describe an overlapping
acquisition when the tiles are aligned: two 128-voxel tiles acquired 96 voxels
apart, with a 16-voxel crop taken at the shared seam, were built into a working
no-copy view through `linked.py`'s own `taken_from` and `size` fields.
`TileCanvases` does still refuse overlapping tiles outright, since one image can
hold only one value per voxel.

What `cropped.py` alone offers is being the **turnkey writer** for such a run,
doing three things at once with nothing asked of the operator. It trims half the
shared strip from each meeting edge so the tiles butt together; it archives every
original tile whole, so a stitcher still has the overlap to work from; and it
leaves behind a **portable, materialised OME-Zarr**, a real single image with
pixels in it that opens in napari or Fiji on its own. The view holds no pixels
and means nothing without its pointer list and its positions folder.

Keep it for that, and revisit once inner-chunk serving or TensorStore works.
B7 is still worth doing on its own merits; it simply retires no module.

**The pointer map — keep it, and stop calling it per-chunk.** The plan
mis-describes its own artefact. It is **one line per tile**, holding origin and
size in chunk units — already "each tile's declared origin and shape", pre-divided
with the store path attached. The per-chunk expansion was tried and abandoned:
tens of gigabytes of memory at ten thousand tiles. Reading each position's
metadata instead would mean opening ten thousand JSON files at viewer start and
again on every change during a live run. One real simplification is available:
`held_as: "file"` is written on every line, is always the same, and is refused if
it is ever anything else. Move it to the header or drop it.

**Declaring an enormous canvas — keep, and it is nearly free.** Empty arrays write
no chunks. The one real cost is that level count is derived from the declared
width, so over-declaring makes every tile write more pyramid levels — already
capped at ten, with a comment saying exactly this. Two consequences worth adding
to the plan: it is *why* coverage looked necessary, and a run that outgrows its
declaration is currently **refused**, with ngio's missing `resize` closing the
obvious escape. On a drifting stage near the travel limit that is a run-ending
refusal at three in the morning.

**Five axes always — keep. The cheapest decision in the document.** The
axis-dropping alternative was tried and made the viewer draw the specimen as a
thin band. Every consumer prefers the canonical five.

**But the time-axis over-declaration is not free, and the plan treats it as a
footnote.** Roughly 250 lines of `viz_studio/backend/stores.py` — a cache, a
"too many to count" sentinel, a twenty-thousand-entry scan limit, and separate
folder-and-file counting paths for two zarr generations — exist *solely* because
the time axis is declared longer than the run and the slider must not offer
moments that do not exist. **Five axes cost nothing; over-declaring `t` costs 250
lines of filesystem archaeology.** If a run knows its frame count, and most do,
declare it honestly and that collapses to a constant.

---

## Where the reasoning did not follow

**The render table does not support the sentence under it.** The plan reads a
threshold — "the view earns its place between two hundred and six hundred" — out
of the first-pixel column, which runs 2.53 / 7.91 / 3.66 s. A quantity that goes
up threefold and then down twofold while the variable triples is noise. The
columns that are clean are **requests** (197 → 647 → 1,547, essentially linear)
and **worst frame** (17 → 17 → 733 ms). The conclusion survives; the evidence
offered for it does not. Argue from those two.

**"Copying nothing" overstates it.** The view writes its coarse levels and reads
every full-resolution tile back off disk to make them. Honestly: copying writes
about 0.98 of an acquisition extra; pointing writes about 0.26 and reads 1.0 — and
after fix 3 above, reads about 0.004. Still decisive. State it as a win rather
than as a zero.

**The file-count argument for 0.5 is the weaker version of an argument already
made better.** 0.4 with a 2048 chunk gives the same file count as 0.5 with a 128
chunk in 2048 shards. The genuine argument is that sharding *decouples the chunk
from the file*, which the register states well a page later.

**Decision 19 — one file per position per level — should be closed as "no".**
The 596,000 files often quoted for a five-terabyte run is the
**full-resolution level on its own**; once every level is bundled the whole run
comes to about **2.98 million**, and neither figure is remarkable on NTFS or
ext4. Reducing the count further by bundling a whole tile at a time, at 800 MB in
flight per tile and delayed live viewing, is a trade against no constraint. The
conclusion already reached is the right one: one tile plane per bundle.

**Decision 16 — HTTP/2 — has the right recommendation for the wrong reason.** "A
certificate on every microscope PC" is not the real cost; on localhost you control
both ends. Take the bigger chunk first and measure, which is what the register
says.

---

## The questions the plan asked

**Is the view right, or a workaround that ages badly?** A workaround, the correct
one, and it will age *well* — because what is written is a valid OME-Zarr image
plus one namespaced attribute. When scenes land, the migration is to write a scene
document beside the same positions and keep the view for Neuroglancer. Nothing
gets rewritten because nothing was written. **What to guard — and this review got
its size badly wrong.** It called the mechanism about 590 lines in one contained
module, having counted only the viewer half; it is **about 2,380 lines** across
`zmart_storage/linked.py` and `viz_studio/backend/linking.py`. So replacing it —
by the TensorStore overlay discussed below or by anything else — is a
two-thousand-line replacement, not lifting out one contained module.

**A view served from memory?** **No.** It costs the property the arrangement is
built around: a run you can copy. It exists only while the server runs, cannot be
handed to a colleague, inspected, or diffed. And it saves less than it appears —
the map is in memory either way, and is already built from an appended sidecar at
O(1) per tile.

**The pyramid, and averaging.** **The reasoning in the plan is right**, and the
docstring in `canvas.py` states the wrong reason for the rule. But an earlier
pass went too far the other way, saying the code already makes the rule
unnecessary. It does not: `linked.py` checks a placement against the levels the
view *points at*, while the levels it **builds itself, tile by tile** go
unchecked — and those are the deep ones where an averaging block can straddle a
join. The number that governs is the total shrink of the deepest level built that
way, which is 512 for three levels of an eighth-sized ladder, not 8. Re-measured,
a seam at voxel 1,632 is exact at level 1 and out by 32.0 at level 2 and 96.0 at
level 3. The phase check stays.

**And the interaction with pointing is a price rather than a prohibition.**
Pointing at three levels of an eighth-sized ladder needs placements aligned to
chunk × 64 — with chunk 192, a 12,288-voxel granularity, unreachable in practice.
One pointed smaller level needs only chunk × 8, and works if the view advertises
the small levels' inner chunks. But with a whole 2048-voxel tile plane as the
unit handed over, even that first smaller level would need 16,384-voxel
alignment, which no stage plan can meet. **So an 8× ladder and pointing at
smaller levels are not mutually exclusive, as this review first said** — the
whole-tile-plane bundle and pointing at smaller levels very nearly are.

The cheaper escape stays open. At 1.8% of the run, the view can **write its whole
pyramid and point only at level 0** — which is *simpler* than what exists:
`pointed_levels` disappears and the `// shrink` arithmetic of item 1 goes with
it. The phase check does not, because the view still shrinks tile by tile. Since
item 1's hazard is real after all, that is both a simplification and one way out
of it, though the costlier way: it gives up pointing at the positions' own
smaller copies. **Take the eighth-sized averaged ladder and the code deletion
that comes with it:** **about 90 GB** instead of 1.8 TB, which is what the
measured overheads of 1.8% and 36% come to on five terabytes, minus much of the
pointing arithmetic — though not the phase check, which survives either way.
One caveat for operators — an averaged coarse voxel is no longer a measurement, so
brightness readings and thresholds must be taken at full resolution, and
`contrast.py` measures from the coarsest level and needs re-checking.

**Adopting ngio on the acquisition machine.** **Do not.** Its value is that it
cannot write the B1 fault; that value is available without the cost, by validating
against its schemas as a development dependency. Against it: it cannot resize and it
cannot write the view. (This review also counted its per-level shard capping
against it, on the strength of the hazard in item 1. That hazard is real after
all, so the objection stands — but it bears on how the view points at small
levels rather than on ngio in particular, and on its own it does not decide the
ngio question either way.) **Adopt ngio for reading, validating and analysis; write
positions with your own code, checked against ngio's schemas in CI.**

*(The write timing took several passes to settle. A first one reported
2,230–2,825 ms a position through ngio against 485–500 ms by hand, but it
compared two paths doing different amounts of work. A second then recorded
**0.91–1.14×**, the same speed like for like — no measurement supports that
figure, and it should be dropped. On matched pixel layouts the numbers are
**2.39× for a single 512-voxel plane and 1.45× for sixteen**, with larger writes
closer to parity, and **7–9×** if the library is left on its own defaults. So the
honest range is one and a half to two and a half times, and much of the rest is a
matter of configuring the library correctly. The absolute time a position takes
matters more than the ratio, since the only question is whether the microscope
has to wait: **"not today" is well supported, "never" is not.** The
recommendation above rests on the two reasons that survive: it cannot resize, and
it cannot write the view.)*

**Overlap ownership.** Centre-in-owned-rectangle is right and is what the field
does. Two additions needing no stitching: break ties for border-touching objects
by **largest area across the tiles that see it**, computable from tile-local masks
alone; and recognise that objects larger than the overlap are an **acquisition
planning** problem, not an analysis one — the operator states the largest expected
object and the planner refuses an intent that gives less overlap. That converts
the worst failure mode from a silent bias into a refusal at setup.

**What breaks when somebody else opens it.** The view reading as all zeros is the
most serious hazard, and honesty in a docstring does not reach the colleague who
double-clicks a folder. Three cheap mitigations: put the warning in the
multiscale `name` field, which every reader displays; drop a `README.txt` at run
root; and consider a `fill_value` a human would notice. Also — the positions live
*inside* the view folder, so a naive recursive open finds the blank thing first.
Wrong way round for a stranger, right way round for Neuroglancer.

---

## The standing preference, applied to the viewer

The reviewer checked what the community offers. **Nothing does "one live-updating
OME-Zarr source composed from N tile stores, in a browser."**

- **`neuroglancer` (npm) is already the community package here** — pinned and used
  as a library, not forked. What is custom is the operator shell, which is where
  the microscopy value is. Right call, already made.
- **`neuroglancer` (PyPI)** serves volumes in neuroglancer's own encoding, so
  every chunk would be decompressed from zarr and re-encoded. The 647 ms shape of
  problem. Not a substitute.
- **`tensorstore`** — its `stack`/`overlay` drivers compose N stores into one
  virtual array lazily in C++. That is genuinely one-source-over-N-tiles as a
  maintained package. It re-encodes per chunk rather than handing over a file, so
  it will not match 4.6 ms — **but if it lands at 20 ms it deletes both
  `linked.py` and `linking.py`.** *This is the highest-value unmeasured question
  in the plan and it was not in the plan.* An afternoon's work. *(It has since
  been measured twice — a median of 0.586 ms through an overlay of ten thousand
  positions, and 0.505 ms with a 95th percentile of 1.004 ms in an independent
  reproduction on Linux — comfortably beating the 4.6 ms this bullet doubted it
  could reach. Neither run was on a Windows microscope computer, which is where
  it counts. **So the order of work is: benchmark there first, and build the
  custom inner-chunk server only if it fails the gate** — building our own
  machinery ahead of a measurement that may make it unnecessary is the very thing
  the standing preference argues against. The plan's section 4 records the
  figures, the gate, and the one capability adoption would cost: compressed bytes
  could no longer be passed through untouched. Note also that what would be
  deleted is about 2,380 lines, not the 590 stated further up; the prize is
  larger and so is the undertaking.)*
- **`multiview-stitcher`** does exactly this job and is 140× too slow for a
  diagnosable reason: it detects the grid-aligned case and then never uses the
  answer, resampling an integer translation through a general affine transform.
  **That is a fixable upstream bug, and fixing it is more aligned with the
  standing preference than anything else here.** A pull request would give the
  community the fast path and give this project a maintained fallback.
- **vizarr/Viv, napari, `ome-zarr-py`** — no live update, no N-tile composition,
  or superseded.
- **Kerchunk / VirtualiZarr / Icechunk** — already considered in `linking.py`,
  with the correct reason they do not fit.
- **Incremental pyramid building** — no package builds a pyramid *as tiles land*,
  which is why a live run does not look empty until you zoom in. Keep.
- **The chunk server** — the file-serving core is about a hundred lines; the rest
  is liveness-dependent caching, ranges, events and repair for a store being
  written underneath it. No package does that. Keep, and resist putting a
  framework under it.
- **`stores.py`** — its job is tolerating half-written stores during acquisition,
  which strict libraries refuse by design. A capability, not an accident.
- **`contrast.py`** — not examined, and the next place to look for a library swap.

**So the preference strongly supports adopting ngio for reading and validating,
strongly supports fixing `multiview-stitcher` upstream, and does not support
replacing the viewer** — because the capability that must survive exists nowhere
else. That is the strongest paragraph that can be written for the custom code, and
it should be demonstrated in the plan rather than asserted.

---

## What the plan had not considered

1. The capping hazard of item 1 — silent wrong bytes. **Struck out in an earlier
   pass and since reinstated on measurement; see item 1.** Underneath it sits a
   second fault the plan had also not considered: `canvas.py:1992` bundles only
   the full-resolution level and leaves the whole pyramid above it unbundled.
2. The ladder width and the pointing alignment rule widen together, and the
   number that sets the alignment is the deepest level built tile by tile.
3. What happens when a run outgrows its declared canvas mid-acquisition: currently
   a refusal with no recovery path.
4. Crash recovery for the view — the sidecar survives and is merged on read, but
   nothing folds it in afterwards, so abandoned runs accumulate them.
5. Two visits to "the same" field one voxel apart give two stores and two pointers
   to overlapping ground. On a drifting stage revisiting targets, this will happen.
   Needs a tolerance and a refusal.
6. **The plan never states the disk budget for the arrangement it recommends.**
   Positions (1.00) + pyramid (0.018 at an 8× averaged ladder) + view (~0) =
   **1.02×**. That single number is the plan's best argument and it is nowhere in
   it.
7. Nothing says how a run is *deleted*. Positions live inside the view folder. On
   a shared microscope computer filling up at three in the morning, somebody will
   delete something. A `README.txt` at run root is the cheapest insurance here.

---

## What the review confirmed

Worth recording, because these were the places the plan was least sure of:

- The pointer map's shape is well designed and correctly justified. Only the
  plan's description of it was wrong.
- The refusal-over-silence discipline throughout `linked.py` is the right instinct
  for a project whose worst failure is a plausible picture of the wrong specimen.
- Beside-the-images rather than inside is correct, for both reasons given.
- Rejecting the HCS plate layout is right and will keep being right.
- Not trimming the overlap out of the pixels is right, and is the decision a
  future maintainer will be most grateful for.
- **The averaging-versus-striding reasoning is sound. Act on it.**
