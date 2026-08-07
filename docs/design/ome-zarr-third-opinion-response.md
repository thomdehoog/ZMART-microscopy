# What the third review changed, and where it did not

A reply to the review recorded in
[`ome-zarr-plan-third-opinion.md`](ome-zarr-plan-third-opinion.md), written after
re-running its probes rather than reading them.

**Nine of its findings are accepted. Four of those nine needed a correction of
their own, because re-running the probe showed something the review had not
looked for. One recommendation is declined, for a reason the reviewer could not
have known.** Everything below was measured on this machine; nothing is taken on
report.

Before any of it, the plainest thing: **no production code has changed.** Every
commit in this line of work touches documentation. The writer still bundles only
the full-resolution level, the pyramid still shrinks by taking every nth voxel,
and the coverage, cropped and linking modules are all still in place. These pages
are a plan, not a description.

---

## The finding that mattered most, and that we had wrongly dismissed

**The capping hazard is real, and reinstated.** An earlier pass struck it out on
the grounds that a capped bundle and a full-sized one "resolve bit-for-bit
identically". Reproduced here, that is false:

| | bytes |
| --- | ---: |
| a level of 256 × 256 voxels, bundle capped to 256 × 256 | **112,220** |
| the same pixels in a bundle declared at 512 × 512 | **112,412** |

The 192-byte gap is the bundle's index and nothing else. A 512-voxel bundle
indexes 4 × 4 = 16 inner chunks at sixteen bytes each; a capped 256-voxel one
indexes 2 × 2 = 4. That index carries a checksum, so handing the capped bytes to
a reader expecting the full shape **fails outright with a checksum error**.

The reason the earlier refutation missed this is worth recording, because it is a
mistake that could be made again. It asked whether a capped bundle's *pixels*
decode correctly when the bundle is opened on its own — and they do. But the view
never opens a bundle on its own. It forwards the bytes onward under its *own*
declared shape. Capping is safe for a position a colleague opens in napari, and
unsafe for a view that passes bytes through. Two different questions, and only one
of them was asked.

So the build item stands, but **not as written while the view points at capped
small levels.**

---

## The one recommendation declined

The review's preferred way out of the capping hazard is to point only at the
full-resolution level and let the view write its own smaller copies. That
certainly works, and it is recorded as the fallback.

It is not the plan, because it gives up the one property this whole arrangement
was built to have: the view holds no pixels and points at the positions' own
smaller copies, so a run never pays for a second pyramid. That was a deliberate
choice made early and for good reasons, and the review had no way to know it.

The review's *own* second suggestion keeps it — let the view advertise the small
inner chunks, and have the server or TensorStore return an inner chunk rather than
a whole bundle file. That closes the same hazard at no cost to the design, and it
is the same change the chunk-aligned seam already needs. It is recorded as
preferred, with the reviewer's route beneath it.

---

## Accepted, with a correction the review had not looked for

### The multi-channel bug: right to delete, wrong that nothing is there

The review is correct that the recorded bug does not exist. `_make_the_copies`
declares the full channel extent at every level, and `_write_smaller_copies`
indexes with the caller's channel rather than zero. Two channels holding the
values 11 and 29 read back 11 and 29 at levels 0, 1 and 2, through both write
paths. The claim has been deleted.

**But a real defect sits one layer up, and the review's probe would not have found
it.** It is in `positions.Run`, and it touches only the levels the *view writes
for itself* — the ones too coarse for any single position to supply.
`positions.Run.write` tells the view about a place the first time it sees it, and
the view fills its own coarse levels by reading that position *at that instant*,
before the later channels have been written. So at those levels only whichever
channel arrived first at that position holds any picture. Writing channel 1 first
reverses which one survives.

The review tested the position stores and `TileCanvases`, both of which are
correct, and concluded there was nothing wrong. The symptom described in the
original note was real; the cause was somewhere else entirely. For an operator it
looks like this: on a two-channel run the second channel is right until you zoom
far enough out, and then goes blank.

### The translation multiplier: worse than either of us said

We had recorded that the reader counts a position's stated place twice. The review
said once per level. Measured, for a true origin of (3, 5, 7) micrometres:

| how the place is written | what the reader returns | multiplier |
| --- | --- | --- |
| image-wide only — what happens today | (3, 5, 7) | correct |
| per-dataset only — the fix landing alone | **(9, 15, 21)** at three levels | the number of levels |
| both at once | (12, 20, 28) at three levels | levels plus one |

The reader adds the image-wide statement once and then adds *every* dataset's on
top. So the writer fix landing alone puts each position as many times too far as
the pyramid has levels — worse than doubling, and worse the deeper the pyramid.
The review's (9, 15, 21) is reproduced exactly. The conclusion is unchanged and
stronger: the writer change and the reader change are one change.

The review's proposed repair is right and has been recorded: combine the
image-wide transform with **one** chosen dataset, normally the first, rather than
walking every level.

### `cropped.py`: the reason was wrong, and so was our description of the module

The review is right that reading a small rectangle does not drag a whole bundle
off disk, and the measurement is not close:

| read | bytes fetched | share of the bundle |
| --- | ---: | ---: |
| 10 × 10 from ZMART's own 855,499-byte bundle | 53,744 | **6.28 %** |
| 10 × 10 from a bundle with 64-voxel inner chunks | 10,071 | **0.66 %** |

A bundled read fetches the index and then only the inner chunks the rectangle
touches, so the cost is set by the inner chunk and not by the bundle. One caveat
worth carrying: this needs a store that answers byte-range requests. Local files
and web servers that honour ranges do; a store without partial reads would fall
back to the whole object.

The review is also right that `cropped.py` is a **writer**, not a
rectangle-reading tool — its own docstring says it writes the acquisition twice,
once whole and once trimmed, and there is no rectangle-reading function in it.

One refinement to the review's account of what would be lost. It describes the
module as a fallback for acquisitions whose tiles do not land on an aligned grid.
It is narrower and more important than that: it is **the only path that handles
overlapping tiles at all**, because `TileCanvases` refuses them outright — one
image can hold only one value per voxel. `cropped.py` trims half the shared strip
from each meeting edge so the tiles butt together, and keeps every tile whole in a
separate archive so a stitcher still has the overlap it needs. The second lost
capability, a portable materialised OME-Zarr that opens in napari or Fiji on its
own, is confirmed as stated.

### Averaging and phase: confirmed to the digit, but the prescription overshoots

The review's number reproduces exactly. A seam at voxel 144 with averaging blocks
of 64 gives a maximum difference of **16.000000** on a ramp, and **49.2** on noisy
data, and leaves one coarse voxel that no tile can supply at all. An aligned
origin owning only 160 voxels gives **52.4**. Swept a voxel at a time, the error is
exactly the seam's remainder.

Two corrections, both of which make the situation easier than the review implies.

**The governing number is the deepest level's total shrink, not 64.** For an 8×
ladder that is 8 — and 144 is already a multiple of 8, so the review's own example
is harmless for the ladder actually under discussion. Its block of 64 models a
seven-level ladder. The rule, stated once: a tile's origin and the extent of the
ground it owns must both be whole multiples of the deepest level's total shrink,
on every coarsened axis.

**And this was never peculiar to averaging.** Today's every-nth-voxel shrinking
has exactly the same requirement, and fails the same seam by **592.9**. The reason
today's arrangement is safe is that `linked.py` already refuses any placement that
does not line up when shrunk. So moving to an averaged ladder does not need a new
guard — only that the existing one goes on being enforced. That is a good deal
more reassuring than "one check too many was deleted".

---

## Accepted without qualification

- **Reverse the build order.** Run the TensorStore benchmark on a Windows
  microscope computer *before* building any custom inner-chunk machinery. Our
  ordering had the custom work first, which contradicts this project's own stated
  preference for ecosystem packages where they give the same result. The
  reviewer's Linux figure — 0.505 ms median, 1.004 ms at the 95th percentile over
  a warm 10,000-position overlay — sits with our own 0.586 ms and clears the gate
  comfortably. Neither settles the cold NTFS filesystem, several readers filling a
  screen at once, or positions being replaced while a run is live, which is why
  the Windows run is the one that decides.
- **Coverage.** The deletion was presented as nearly free, with "one column of the
  run-level table" as the residue. That understates it: the record holds the
  moment in time, the channel, the write order, exact origin and shape, the scan's
  own tile numbering, repeated visits, and whether a leg finished or was
  abandoned. Either the append-only run event manifest is built first, or those
  capabilities are given up explicitly.
- **The copy multipliers mix denominators.** 1.98× counts bytes against what the
  camera produced; 1.3× counts extra imaging against unique specimen area. Both
  now carry their basis.
- **The per-tile-plane counts are chunk counts, not complete web requests.** A
  bundled read also asks for the bundle's index, usually cached after the first.
  The arithmetic was right; the labelling was not.
- **ngio.** The "0.91–1.14× like for like" figure is unsupported and has been
  dropped. The matched-layout benchmark — 2.39× for a single 512-voxel plane,
  1.45× for sixteen — is what the documents now carry, with the note that absolute
  time per position matters more than the ratio, since the only question is
  whether the microscope has to wait. The verdict is softened from *never* to
  *not today*: capped bundles are not byte-compatible with a byte-forwarding view,
  and it has not been qualified on a Windows microscope computer. Neither of those
  is permanent, and a permanent rejection would sit badly with this project's
  preference for ecosystem packages that enforce the standard.
- **A channel needs an explicit display window to validate.** Without the start
  and end values the position is still refused, so the per-dataset translation is
  necessary but not sufficient. The interop tests have to cover both.

---

## What the passing tests do and do not tell us

The suites pass — 148 in the storage tests, and 105 passed with 1 skipped across
the storage, server and linking suites, the skip being a real-browser rendering
test with no built front end. That confirms the whole-bundle design as it stands
today.

It confirms nothing about the three things the targeted probes broke: capped
versus uncapped small levels, validation with a default channel, and the
per-dataset translation across several levels. All three had passing tests around
them and were wrong anyway. That is the argument for the two interop tests, and it
is a better argument than the one originally written for them.

---

## What to do next

1. **The writer fix and the reader fix, together, with the interop tests.** They
   are one change; landing the writer alone puts every position as many times too
   far as the pyramid has levels. The tests must cover the display window as well
   as the translation.
2. **The TensorStore benchmark on a Windows microscope computer.** It is one
   measurement, and it decides whether a large piece of custom machinery is needed
   at all.
3. **Only then** choose between TensorStore and a custom inner-chunk path, and
   only then revisit bundling every level.
