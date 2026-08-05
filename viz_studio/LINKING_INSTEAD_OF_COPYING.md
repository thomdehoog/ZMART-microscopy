# Showing the run without copying it

Written 5 August 2026. **Nothing here is built.** What is built is the arrangement
that copies — `zmart_storage/cropped.py`, measured in
`HANDOVER_overlapping_runs.md` — and this document is about doing the same thing
without the copy.

---

## Why this matters, and it is not tidiness

The arrangement that works today writes the run twice: the raw tiles, and a canvas
holding the same pixels trimmed and laid out as one picture. At the sizes measured
so far that costs about eighty per cent more disk, which is an easy price.

**At five terabytes it is not a price at all, it is a refusal.** A run that size
cannot be copied to be looked at. There is not the disk, and even where there is,
the copying itself takes long enough to change how the instrument is used. So for
the runs this project is heading towards, copying is not the expensive option — it
is the impossible one, and something else has to be true.

---

## The idea in one paragraph

A picture the viewer opens does not have to exist. It can be a **list of pointers**
into the tiles that already exist, and the pointers can be arranged to describe a
single, ordinary image.

Where two tiles overlap, the view simply **does not point at the shared parts**.
Those pieces stay on disk, in the tiles, untouched and unreferenced — available to
a stitcher, invisible to the viewer. Nothing is trimmed, nothing is rewritten, and
no pixel is ever at risk, because a view is only ever a list of pointers.

If the view is built wrongly, you rebuild the list. The data has no idea a view
exists.

---

## What makes it possible: a piece of the view is a piece of a tile

This is the whole mechanism, and it rests on arithmetic rather than cleverness.

An image is stored in pieces. If a piece of the *view* happens to be exactly a
piece of one *tile*, byte for byte, then answering a request for it is not
assembling anything — it is handing over a file that already exists. No arithmetic
on the pixels at all.

That happens when two conditions hold:

- **The trim is a whole number of pieces.** The trim is half the overlap, so a run
  overlapping by 256 voxels is trimmed by 128, and the pieces must be 128 or
  smaller.
- **The trimmed tile is a whole number of pieces**, so that each tile begins on a
  piece boundary in the view. This one is already checked by the writer that copies.

Worked through, with a tile 2048 voxels across overlapping by 256:

```
trim 128 from each side          = exactly 1 piece of 128
what is left is 1792 across      = exactly 14 pieces of 128

so piece j of tile k's part of the view is tile k's piece j+1
the first and last piece of every tile are simply never asked for
```

## The rule for what else this works on

**If the answer is exactly the bytes of a piece that already exists, it can be a
pointer. If producing the answer needs arithmetic on pixels, it cannot.**

That draws a clean line, and it is worth knowing which side things fall on.

Free, because they only rearrange:

- trimming, when the trim lands on piece boundaries;
- moving a tile, since that only changes which piece is asked for — including
  moving it again later, once a stitcher has found where the stage really went;
- taking a subset: one well of a plate, one colour, one moment, a range of planes;
- presenting the same tiles several ways at once — a whole-plate view, a per-well
  view and a single-colour view can all be lists of pointers into the same files,
  and cost nothing extra;
- joining along an axis, so moments or colours held in separate files appear as one.

Not free, because the pixels genuinely change:

- **the zoomed-out copies**, because shrinking averages across the join between
  tiles and no existing piece holds that answer;
- blending overlap, for the same reason;
- anything rotated, or shifted by less than a piece, which needs resampling;
- changing the compression or the number type, since the bytes themselves change.

So the honest shape is: **full resolution is pointers, the zoomed-out copies are
written once.** Those copies are roughly a tenth of the data, which turns eighty
per cent more disk into about ten.

---

## What else has to be done

The pointing is the easy half. This is the list that decides whether it is a
week's work or a month's.

**Describe the view.** The viewer asks what the image is before it asks for any of
it — its axes, its size, where it sits on the stage, what copies it has. None of
that exists on disk, so the server has to say it. Note that the position must be
written beside each resolution, not once for the image; the reasoning is in
`INTEROP.md` §1 and the writer already does it this way.

**Keep the index.** Which piece of the view is which piece of which tile. It should
extend the record `zmart_storage/coverage.py` already keeps, rather than becoming a
second record that can disagree with the first.

**Answer for ground no tile covers.** Most of a scattered run's bounding box is
empty. The server already answers a plain "nothing here" for that case and the
comment in `backend/server.py` explains why it matters; the pointing path has to do
the same rather than returning a piece of black.

**Make the encodings agree, exactly.** Bytes are handed over untouched, so the
compression, the number type, the fill value and the generation of zarr the view
declares must all match what the tiles really contain. A mismatch here fails
silently, which is the worst way for it to fail. `stores.zarr_scheme` decides which
reader the engine is told to use by looking at the disk, so it needs care.

**Decide about sharding.** If tiles are written as sharded zarr, a piece lives
*inside* a file rather than being one, so handing it over means serving part of a
file rather than a file. Still possible, no longer simple.

**Keep it current during a run.** A tile arriving adds pointers, which is cheap.
The zoomed-out copies are the part that is not cheap, and `ARCHITECTURE.md` §7
already records that keeping them current as tiles land is unsolved.

**Prove it against the copy.** The arrangement that copies is measured and
correct, which makes it the ideal control: the same run, the same viewer, the same
machine, and the only difference is whether the picture was written down or pointed
at. If a linked view does not match a written canvas voxel for voxel, it is wrong.

---

## The one thing that could spoil it, and it is measurable now

The piece size is forced down — it has to divide half the overlap — and smaller
pieces mean the same picture arrives in more requests. The bytes are unchanged;
what grows is how many times the browser has to ask. `WHERE_THINGS_STAND.md`
already records that three requests in four are wasted on a sparse canvas, so this
is not a free direction.

**It is a lever you set when acquiring, not a limitation you discover afterwards**,
and the surprising part is which way it points:

| tile | overlap | trim | largest usable piece |
|---|---|---|---|
| 2048 | 256 (12.5%) | 128 | 128 |
| 2048 | 512 (25%) | 256 | 256, which is what is written today |
| 2048 | 1024 (50%) | 512 | 512 |

**More overlap makes linking easier**, because half of a larger overlap divides
more ways. A run that overlaps by a quarter can keep exactly the piece size this
project already uses, and nothing about the request count changes at all.

`measure_the_chunk_size.py` beside this file writes the same run at four piece
sizes and opens each one, so the only thing differing between the rows is how
finely the picture is divided. **It has not been run.** It needs no linking layer
and no new format, and it answers the question that decides whether any of this is
worth building.
