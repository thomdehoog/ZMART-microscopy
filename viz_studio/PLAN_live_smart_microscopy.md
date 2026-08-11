# One zarr that a smart run grows inside — the plan

Written 11 August 2026. This gathers decisions already measured elsewhere into
one work order: what a live smart-microscopy acquisition should write, how the
viewer stays current while it writes, and what remains to build. Nothing here
is speculative — every claim leans on a dated measurement in
`LINKING_INSTEAD_OF_COPYING.md`, and the open items are listed at the end with
their sizes.

## What a smart run is, for this plan

Positions land **anywhere on the placement lattice**, chosen by the experiment
as it goes — not on a grid known in advance. They keep landing for hours. Some
places are imaged again later, so **time grows** as well as space. The operator
has the viewer open the whole while, and what they see must be current, one
picture, and fast — which the scatter measurement already proved at ten
thousand positions for the space half of this.

## The layout: one zarr, with the positions inside it

```
run.ome.zarr/                     <- the whole acquisition; open this
  zarr.json                       <- one description: the picture's own
                                     (axes, levels, place on the stage), the
                                     map of pointers, and a change counter
  0/  1/  ...  8/                 <- the picture's levels: pointed ones hold
                                     nothing, deep ones hold written pixels
  pos00000.ome.zarr/              <- one complete OME-Zarr per position,
  pos00001.ome.zarr/                 directly inside -- no subfolder between
  ...
run.ome.zarr-positions-arriving.jsonl   <- during the run only; folded into
                                           the description at the end
```

The container **is** the view. There is no `positions/` subfolder, no `views/`
folder beside it, no name appearing twice in every path: one zarr group whose
own description declares the picture, whose numbered children are the
picture's levels, and whose named children are the positions themselves. A
position must simply never be named a bare number, which the writer enforces.

**Why a zarr rather than a plain folder** — a fair question, because the
difference is one small file. A folder of stores already works; it is what a
mesoSPIM transfer looks like and the viewer opens it. What the `zarr.json`
buys, for the cost of a few hundred bytes:

- **The container is itself the picture.** Opening `run.ome.zarr` in this
  viewer, in napari, in anything that reads OME-Zarr, gives the one merged
  image — because the container's own description declares it. A plain folder
  declares nothing; every reader must be taught what it holds.
- **The map travels inside.** The list of pointers and the change counter live
  in the container's own attributes (already how `linked.py` writes them), so
  the acquisition cannot be separated from the description of how to show it.
- **Each position stays an ordinary image.** A nested OME-Zarr opens on its
  own, exactly as it would in a folder. Nothing is lost.

So the choice is: the folder gives you a heap of parts, the zarr gives you the
assembled instrument for one extra file. This supersedes the two-folder shape
in `docs/design/positions-in-a-container.md` by one step: the view no longer
sits *beside* the container, it **is** the container.

## Chunk and shard: the numbers, and why

Two different units doing two different jobs, decoupled by sharding:

- **Chunk — the read unit — `(1, 1, 1, 256, 256)`.** One moment, one colour,
  one plane, 256 voxels across. The 256 is measured: opening the same picture
  cost 46 requests at 256 against 1,925 at 32, and the scatter at 256 loads in
  1.3 s. The single plane is also measured, from the other direction: Thy1's
  32-plane chunks made showing one plane decompress thirty-two and keep one.
  128 across is the acceptable floor if a trim ever forces it; below that it
  costs real seconds.
- **Shard — the file unit — `(1, 1, depth of the position, 256, 256)`.** The
  whole depth of a position in one file, with the single-plane chunks intact
  inside it, so reading one plane still reads one plane's bytes (the engine
  asks for a stretch of the file, which the server already answers). This is
  what collapses the file count — the thing that filesystems, backups, and
  endpoint protection all punished at ten thousand positions — by a factor of
  the stack depth, while changing nothing about read cost.
- **The step stays fine.** The placement lattice is the shard's footprint in
  y and x, and that footprint stays 256 — so a smart run places positions
  exactly as freely as the unsharded scatter that was measured.
- **The buffer is what the acquisition already holds.** A shard can only be
  written whole, so the writer must hold a shard in memory before writing —
  and a shard is one position's stack, which is precisely what the acquisition
  has in hand when a position finishes. No new buffering exists anywhere;
  writing a position writes each of its shards once.

## The positions carry their own pyramids

Each position is written with its own zoomed-out copies, always. The reason is
the position's own life, not the view's: a complete OME-Zarr with a pyramid
opens and zooms properly **on its own** — in napari, in Fiji, in this viewer —
and people will open positions on their own. It costs about a third more disk
per position, which is small at position scale.

The view then uses them when it can and is not harmed when it cannot:

- **Where the placement allows, the view points at them** instead of writing —
  a run whose step is a multiple of chunk x 2 points one extra level deep, x 4
  two levels, and a run aligned all the way down writes nothing at any zoom
  (proven voxel for voxel in `test_a_view_that_writes_nothing.py`). The depth
  is worked out from the run automatically; nothing is refused over it.
- **Where it does not** — a position placed freely on the fine lattice keeps a
  different set of every-second-voxels than the view would, so its copies are
  right for itself but out of phase for the view — the view writes that level
  itself, and the position's pyramid still serves standalone opening.
- **The deepest levels are the view's alone either way.** A whole-stage zoom
  summarises thousands of positions in a few kilobytes; no single position
  file could ever hold it. Those cross-tile levels are what made the
  whole-plate open cost 2 pieces instead of 10,000, and they stay written.

The step rule is therefore the experiment's knob: fine placement and a little
more written pyramid, or coarser placement and pointers nearly all the way
down. Both are correct; the choice is freedom against disk.

There is a third reason, and it is the deepest: **the positions are the system
of record, and everything else is derived.** A position with its own pyramid
is a complete, standard image that owes nothing to the view, the map, or this
codebase — any OME-Zarr tool reads it whole, today or in ten years. The view
can be deleted and rebuilt from the positions in seconds; the reverse is not
true. So if the project ever has to move away from zarr, or from this viewer,
or from this whole arrangement, the way out is "convert the position files
with any standard tool" — and nothing of value lives anywhere else. That is
what self-contained positions buy, and it is worth a third more disk many
times over.

## Time: declare the room, then let frames simply begin to exist

- Every position store, and the view, declare **the whole experiment's
  possible span of moments** up front. Declared, unimaged time costs nothing
  on disk — the same principle as declaring the stage's travel range in space.
- A frame landing is written into the position's own store. **The map does not
  change** — pointers are arithmetic over time, so the new pieces are simply
  found on the next request. Unimaged frames answer "nothing here" and draw as
  blank ground, which is the ordinary case rather than an error.
- **Re-imaging a position writes the next moment, never over an old one.** It
  genuinely is a later observation; the earlier one is data; and this turns
  the hardest staleness problem (a file changing under an unchanged pointer)
  into ordinary time growth. Overwriting in place becomes something the run
  never does.
- The viewer stays current the way it already does for positions: the run's
  **revision** goes up when anything lands, the manifest carries it, and the
  page invalidates the engine's cache for that source. Image data is served
  `no-store` while a run is live, so the browser holds nothing stale to begin
  with.

## What has to be built

Listed smallest first; the first three are hours each, not days.

1. **Positions directly inside the view.** `keeps_its_tiles_in` today wants a
   named subfolder; teach it (or a sibling flag) that the tiles are the view's
   own non-numeric children, and make `discard_existing_run` step around them
   there too.
2. **A change counter in the view's description.** Goes up on every change,
   including the ones the file's length cannot show. The reader watches it;
   the announcements channel relays it. This is the counter
   `OPEN_a_run_that_changes_while_you_watch.md` asked for.
3. **Frames-imaged-so-far in the manifest**, so the time slider follows what
   exists rather than the declared room. The canvas writer already computes
   this for timelapses; it needs saying for linked views too.
4. **The writer's time API.** `start_a_run` grows a `frames=` room and a way
   to write a given position at its next moment; the revision bump rides the
   same announcement a new position already sends.
5. **Sharded growth, tested.** Sharded tiles link and draw today
   (`test_a_pointed_at_view_of_the_newer_format.py`), but two combinations are
   untested and this plan needs both: a *growing* view over sharded positions,
   and sharded tiles pointed at more than one level deep.

## Benchmark last: sharding against not, once everything works

Extend `measure_a_random_scatter.py` into a live variant — positions arriving
over time, frames filling in — and run it both ways on the same seed, sharded
and unsharded, at 2,000 and 10,000 positions, on the machine with the card
(`--headed`, as the script already says). The columns that decide:

| what | why it decides |
| --- | --- |
| files on disk | the count that upset the filesystem and the endpoint protection |
| one position landing, ms | the acquisition pays this thousands of times |
| one frame landing, ms | the timelapse pays this even more often |
| cold open, and the zoom ladder | must not regress from 1.3 s / ~0.3 s a rung |
| scrubbing the time slider | the read that sharding must not have made worse |

The expectation, stated so the benchmark can falsify it: sharding divides the
file count by the stack depth, leaves every read the same, and costs only the
position-sized write buffer the acquisition holds anyway. If any column says
otherwise, the shard shape above is wrong, not the idea.

## What this plan deliberately does not do

No stitching, no blending, no sub-voxel placement — those change pixels and
belong to the build/assemble route and the stitcher. No new formats: one zarr,
OME-Zarr 0.5 throughout, readable by anything that reads the standard.
