# The same thing, with smaller copies

The demonstration in the folder above shows that positions can be put anywhere —
overlapping, at offsets that land nowhere near a piece boundary — and still be
shown as one picture, if the server **builds** each piece instead of handing one
over. It served **one size** only, and left the obvious question open: what does a
smaller copy of the picture even mean when tiles sit at odd offsets?

This answers it. **A server that builds pieces can serve a whole ladder of sizes,
and it is right at every one of them.**

## Why the odd offset stopped mattering

A picture that *points* at files cannot have a smaller copy at an odd offset,
because you cannot point at half a voxel. A picture that is **built** does not
point — it reads the ground it needs, shrinks it, and sends the result. The tiles
are laid out first and shrunk afterwards, so a block of voxels that straddles a
seam is averaged *across* the seam, exactly as it would be if the whole picture had
been one image all along.

Shrinking here is by **averaging**, not by taking every nth voxel, and the picture
says so (`"type": "mean"`). This is the case where the two genuinely differ: tiles
at odd offsets do not line up with the blocks being averaged.

## Right at every size

Ten positions, five across and two down, a step of 179 voxels with tiles of 256 —
so neighbours overlap by 77 and no seam falls on a 128-voxel piece boundary. Four
sizes. Every piece built, encoded, written out, reopened with plain `zarr`, and
compared with a picture built independently; then the same again fetched over HTTP
from the running server.

| size | voxels | wrong on disk | wrong over the wire |
| ---: | --- | ---: | ---: |
| full | 512 × 1024 | **0** | **0** |
| half | 256 × 512 | **0** | **0** |
| quarter | 128 × 256 | **0** | **0** |
| eighth | 64 × 128 | **0** | **0** |

**And the comparison that gives it meaning.** Pointing at each position's own
smaller copy instead, and laying those at the nearest half-offset, gets **6,173 of
131,072 voxels wrong at half size — five per cent** — typically out by 1,124 grey
levels in 65,535 and at worst 3,800. The two smallest sizes could not be pointed at
at all, because each position carries only one smaller copy of itself and the
picture needs three.

## What it costs

| size | ground a piece covers | median | source pieces read | whole picture |
| ---: | --- | ---: | ---: | ---: |
| full | 128 × 128 | 4.8 ms | 3 | 160 ms |
| half | 256 × 256 | 11.4 ms | 8 | 91 ms |
| quarter | 512 × 512 | 24.8 ms | 22 | 50 ms |
| eighth | 1024 × 1024 | 47.2 ms | 40 | 47 ms |

The fear was that a piece four times the ground would cost four times as much, so a
picture zoomed well out would be ruinous. **It does not work out that way.** A
piece does cost more the more ground it covers, but there are proportionally fewer
of them, so the *whole picture* gets cheaper at every smaller size — 160, 91, 50,
47 milliseconds. A screenful of coarse ground never costs more than a screenful of
fine ground.

**Building a smaller piece is reading, and nothing else.** Of the slowest piece at
each size, reading took 7.0 / 12.2 / 25.1 / 42.6 ms, averaging 0.0 / 0.7 / 1.7 /
3.4, and encoding 1.6 / 1.6 / 1.7 / 1.8. And the reading is not the disk — a bare
read of one 32 KB piece costs 1.41 ms on its own, which is the library's overhead
per call. Reading the pieces together, or at the same time, should cut it several
times over.

## In the viewer

| magnification | size drawn | until something was on screen |
| --- | --- | ---: |
| 0.4 µm a pixel | full | 0.85 s |
| 1.0 | half | 0.78 s |
| 2.0 | quarter | 0.71 s |
| 4.0 | eighth | 0.56 s |

Which size was actually drawn could not be read off the traffic: at every
magnification the engine asked for **all** forty-four pieces of all four sizes,
reaching for the smallest first. So `which_level_is_drawn.py` settles it another
way — each size paints one patch of ground in its own brightness, and the patch is
read off the photograph. The four readings came back exactly on the four
brightnesses, with no spread at all.

## Where it stops

The cost is about 1.3 ms for every source piece read, and a piece at size 2^L reads
4^L of them once the picture is big enough. On this small picture that saturates —
the smallest size *is* the whole dataset — but on a real run it would not. Five
steps out is roughly a thousand source pieces, about 1.3 seconds for a single
piece, and that is the size a viewer **opens on**.

So the honest cut: **build the first few sizes as they are asked for, and write the
smaller ones once.** There is very little data in them and writing them costs
almost nothing — measured elsewhere at under two per cent of a run.

Two things would push that cut further out if it were worth doing. The per-piece
cost is the library's overhead rather than the disk, so reading together or in
parallel should help a great deal. And a builder *could* read each position's own
smaller copy where one exists instead of the full-size one — cheaper, but it brings
back exactly the five-per-cent error measured above, so it is only safe where
positions do not overlap.

## Running it

```
python viz_studio/options/placing-tiles-anywhere/pyramid/write_positions.py
python viz_studio/options/placing-tiles-anywhere/pyramid/check.py
python viz_studio/options/placing-tiles-anywhere/pyramid/drive_it.py
python viz_studio/options/placing-tiles-anywhere/pyramid/which_level_is_drawn.py
```
