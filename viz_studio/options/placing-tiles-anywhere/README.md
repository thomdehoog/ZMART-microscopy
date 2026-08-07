# Placing tiles anywhere, and showing them as one picture

A working demonstration, kept because it settles a question that had been argued
about for a long time without an answer.

## The question

A view shows many positions as one picture by pointing: a piece of the picture
*is* a piece of one position's file, handed to the browser untouched. That is very
fast — eight thousandths of a millisecond a piece — but it forces every position
onto the grid of pieces, because the server can only hand over a file that already
holds exactly what was asked for. A stitcher's measured drift of a voxel and a
half cannot be expressed that way at all.

The alternative is for the server to **build** each piece: read whichever
positions reach into it, cut the parts it needs, put them together, and send the
result. Then a position can sit anywhere. What was never shown is whether that
actually works end to end, with the real engine drawing it.

It does.

## What was run

Nine positions written by the ordinary writer, at a step of **179 voxels** with
tiles of **256** — so neighbours overlap by **77**, and no seam lands on a piece
boundary. Served as **one** OME-Zarr image by a server that composes every piece
on demand, and drawn by the viewer's real engine.

**Twenty-one of the twenty-five pieces are touched by more than one position.**
None of those could be answered by handing over a file, because no single file
holds them.

- `frames/composed-anywhere.png` — the whole picture. Each tile has its own grey
  level, a border, a disc and a number of bars, so one can be told from another.
  The discs of the tiles that have neighbours are visibly clipped: that clipping
  is the overlap.
- `frames/composed-anywhere-close.png` — the corner where four positions meet,
  with the piece boundaries at voxels 128 and 256 inside the view. No seams.

## That it is right, without looking at the picture

- Every piece composed, written out, reopened with plain `zarr` so the encoding is
  checked too, and compared against a canvas built independently:
  **409,600 voxels, none wrong.** The same over HTTP through the server: none wrong.
- The photograph itself was located against the geometry and compared over
  **349,500 screen pixels** — the largest disagreement was **one grey level in
  255**.
- And the check can tell the difference: compared against the same tiles pushed
  onto the nearest whole piece — which is what the writer insists on today — it
  disagrees on 181,388 pixels, by twenty grey levels in the middle of the range.

## What it costs

| | |
| --- | ---: |
| hand over a piece untouched, as today | 0.0085 ms |
| build a piece | 4.8 ms, worst 12.4 |
| build one, while the browser is asking for others | 14.6 ms, worst 98.5 |
| the whole twenty-five-piece picture | 150 ms |
| until something was on the screen | 0.71 s |

The building is paid **once for each piece**, not once a frame: what the browser
has been sent, it keeps. So the cost falls on newly-seen ground rather than on
panning across ground already fetched.

## The finding that matters more than the demonstration

Three guards had to be switched off to write these positions, and the view's own
`add` had to be made to do nothing, because it refuses a tile landing on ground
already imaged. That is not a set of obstacles to be worked around — it is the
result. **The list of pointers cannot express this geometry**, because a pointer
says "this whole piece is that file", and here five pieces in six are not any one
file. Building the pieces replaces that list rather than extending it.

Nothing in the repository was changed to run this: the guards were set aside
inside these scripts only.

## What it does not answer

**The picture served here keeps only one size.** What a smaller copy of the
picture should even mean when tiles sit at odd offsets is a real question — half
of 179 is not a whole number of voxels — and it is untouched here. A single-size
image is perfectly ordinary OME-Zarr and the engine was content with it, but a
run that is to be looked at while zoomed out needs that question answered first.

## Running it

```
python viz_studio/options/placing-tiles-anywhere/write_positions.py
python viz_studio/options/placing-tiles-anywhere/check.py        # the numbers above
python viz_studio/options/placing-tiles-anywhere/drive_it.py     # the photographs
```

`geometry.py` holds the shape of the run in one place; `compose.py` builds a
piece; `compose_server.py` serves them; `smoke.py` checks what goes over the wire;
`read_the_seams.py` is the comparison between the photograph and the geometry.
