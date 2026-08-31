# Positions in a zarr, and one more for the viewer

> **Where this got to, 2026-08-10, late.** Forget the cropping. The positions are
> written whole and the view does the trimming with pointers -- `PlacedTile`
> already carries `taken_from` and `size` for exactly that, and
> `LINKING_INSTEAD_OF_COPYING.md` records it working: two 128-voxel tiles
> acquired 96 apart, cropped 16 at the seam, built and read back with no pixel
> copied. There is then no merged image, so `cropped.py` has no job left -- its
> whole purpose was trimming tiles so they could butt up *inside one picture*.
>
> ```
> run/
>   overview.ome.zarr/       the positions, whole, overlap intact
>   views/canvas.ome.zarr/   pointers into their middles
> ```
>
> Two things this still has to satisfy, both settled earlier tonight and neither
> yet built: **the chunk size must divide the step**, so a trim lands on a piece
> boundary; and **tiles must be padded at write time** by however far the stage
> overshot, so their pieces sit on the run's grid and a pyramid can be pointed at
> rather than written. The rest of this document was written before that turn and
> describes the layout, which still holds.

A run should be laid out the way a mesoSPIM transfer already is: **a container
group holding one complete OME-Zarr per position**, with the merged picture as
one more store beside them. Decided 2026-08-10, against
`D:\OMEzarr data\Thy1-25x-3x2-1ch-OMEZARR\Thy1_Mag25x_Ch561.ome.zarr`, which is
the shape a real instrument writes today.

Nothing about the arrangement changes — the tiles keep their overlap, the canvas
is still trimmed, the merge still happens. What changes is where the pieces sit
and what they are called.

## What it looks like now

```
run/
  overview.ome.zarr             the canvas
  overview.writing              the writer's claim
  overview_tiles/               a plain folder
    overview_pos00000.ome.zarr  the acquisition's name, twice, in every path
  zmart-coverage/
    overview.ome.zarr/          a folder named like a store, which it is not
      regions.json
      tiles.jsonl
```

## What it should look like

Everything that is not load-bearing is gone:

```
run/
  overview.ome.zarr/            what the microscope recorded, and nothing else:
    zarr.json                   a container group -- zarr v3, node_type group,
    Tile0.ome.zarr/             attributes {} -- exactly as theirs is
    Tile1.ome.zarr/
    ...
  views/                        what we worked out, each named for what it is
    canvas.ome.zarr/            the merged, trimmed picture, for the viewer
```

**Two rules, and everything follows from them.**

*Recorded and derived never share a container.* Anything that enumerates a group
draws every child it finds, so a canvas among the positions means another tool
opens the specimen twice -- once as tiles and once as a picture of the same tiles,
drawn on top of each other. Our own viewer would tear along the overlapping joins
doing it. Kept apart, `overview.ome.zarr` is exactly a mesoSPIM transfer and
nothing of ours is in it: a stitcher, napari or Fiji finds the positions and no
surprises.

*`views/` is a plain folder, not a group.* No `zarr.json`, so nothing walking a
zarr hierarchy descends into it -- the same reason the run folder is a plain
directory. It holds derived pictures, each named for what it is, and can hold
more than one as more get built: a mask, a preview, whatever comes. They are ours
and they stay ours.

That is the whole run: one container of positions, one folder of views.

### What was stripped, and what it costs

**The coverage record.** `zmart-coverage/` held `tiles.jsonl` -- origin, shape
and index, one line per tile -- and `regions.json`, a joined summary of the same.
Every one of those facts is already in the position it describes: a store's
translation is where it was imaged and its shape is how much. The record was a
second copy, kept in step by hand.

The cost is not nought and it must be stated. The record exists because reading
it is **one request**, where working the same answer out of the positions means
reading a `zarr.json` per position -- measured at about 5 requests a tile, so a
thousand positions is thousands of requests before anything is drawn. Two
answers, either of which is fine, and neither of which is a sidecar:

- the container's own `zarr.json` carries the summary in its attributes, since
  it is a bare group with nothing in it today; or
- nothing carries it, and a reader that wants coverage enumerates the positions,
  which is what it must do to draw them anyway.

**The `.writing` marker.** A file at the top of the run saying a writer holds it.
Worth keeping only if two writers on one run is a thing that actually happens;
if it is, it belongs in the container's attributes rather than beside it.

**Degenerate axes.** We write `t c z y x` always. Theirs writes `z y x`, because
that is what it has. A run with one moment and one colour should say so by not
mentioning them.

Three properties this buys, and they are the whole reason:

**Anything that opens a mesoSPIM transfer opens ours.** The container is a bare
group and the children are ordinary stores, so napari, Fiji and a stitcher find
the positions without being told anything.

**The name is said once.** `overview.ome.zarr/Tile7.ome.zarr` rather than
`overview_tiles/overview_pos00007.ome.zarr`.

**`fused` says what it is.** Stitching tools already write a fused volume beside
the tiles it came from, so the extra store reads as the thing it is rather than
as a seventh position.

## What the reader has to do

Nothing clever, which is the point of keeping the two apart. The viewer is
pointed at `overview_canvas.ome.zarr` and opens one image. Nothing has to choose
between children, and no rule has to know which of them is ours.

Pointing it at the container instead still works and means what it says: open
the positions, all of them, as placed sources. That is the right thing for a
handful of tiles under examination and the wrong thing for a survey -- measured
at 5.2 requests a tile and linear, against 305 flat for the canvas.

## What has to change

| where | what |
| --- | --- |
| `zmart_storage/cropped.py` | write the container `zarr.json`; put the canvas at `fused.ome.zarr` inside it; name positions `Tile<n>.ome.zarr` |
| `zmart_storage/coverage.py` | write to `<name>_coverage/` rather than `zmart-coverage/<name>.ome.zarr/` |
| `viz_studio/backend/stores.py` | the `fused` rule above |
| `zmart_storage/linked.py` | reads the archive's names |
| `viz_studio/measure_the_overlapping_run.py` | `count_what_was_lost` globs `*.ome.zarr` in the archive |
| tests | every place that builds or asserts a run's paths |

**A migration, not a compatibility layer.** Runs already written are moved by a
script that renames folders and writes the container `zarr.json`; nothing reads
both layouts. Back-compatibility here would mean two shapes to reason about
forever, for a handful of test runs.

## What this does not settle

**Irregular runs.** The trimming rule needs a pattern: `crop = (tile_shape -
tile_step) / 2`, worked out from the step a raster declared. A position the
workflow chose for itself has no neighbours by definition and is kept whole, so
the canvas resolves those overlaps by **overwriting** -- which makes the picture
depend on the order the tiles arrived rather than on where they are. Measured on
a raster the trimmed canvas holds 0.0% doubled ground; for scattered targets it
holds whatever landed last.

The generalisation that would fix it is to take each voxel **from the tile whose
centre is nearest**, which reduces exactly to the midline rule on a raster and
still gives one deterministic answer off it. Its cost is that a tile's neighbours
are not known while the run is going, so the canvas would have to be settled in a
pass at the end or revised as tiles arrive. That is a separate piece of work and
the more important one.
