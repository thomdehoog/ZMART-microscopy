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

## What had to be built — done 11 August 2026, same day as the plan

1. **Positions directly inside the view.** *Built.* `keeps_its_tiles_in="."`
   says the tiles are the view's own children named ``.ome.zarr`` — checked,
   not trusted — and everything that empties or inspects an image steps around
   them by one shared rule. The viewer needed no change: an image is an image
   because of its own description, so the picture stays one image however many
   positions it holds inside.
2. **A change counter in the view's description.** *Built.* Every rewrite of
   the list moves ``generation``, and `note_a_change` moves it for the changes
   no file's length can show. This is the counter
   `OPEN_a_run_that_changes_while_you_watch.md` asked for.
3. **Frames-imaged-so-far.** *Already existed, now fed.* The viewer counts how
   far time reaches from the written copies (`written_timepoints` in
   `stores.py`) and stops the slider there; what was missing was later moments
   ever reaching those copies, which item 4 fixed. `Run.frames_reached` says
   the same number without looking at disk.
4. **The writer's time API.** *Built.* A later moment written into an existing
   position updates that moment's share of the written zoomed-out copies and
   moves the change counter (`GrowingLinkedView.imaged_again`); adding a tile
   can be told which moment just landed, so a long declared timelapse costs
   what was imaged rather than what was declared; and `Run.image_again`
   records a revisited place at its own next moment, never over an earlier
   observation.
5. **Sharded growth, tested.** *Both combinations now pinned.* A growing view
   over bundled tiles answers correctly mid-run. Bundled tiles that carry
   their own copies point at full size only — the served unit changes between
   levels, so deeper pointing is capped and the deeper zooms are written,
   which the test proves gives the right picture. Deeper pointing over
   bundles means the map carrying each level's own unit: future work, not a
   gap in correctness.

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

### First rows, sandbox, 11 August 2026 — the graphics-card rows still owed

Both arms at 2,000 positions on identical spots
(`measure_a_random_scatter.py 2000 --coarse` against `--sharded`, software
renderer, single-plane demo positions of 512 voxels in 2 x 2 pieces):

| | plain | bundled |
| --- | --- | --- |
| writing and linking, per position | 42 ms | 42 ms |
| files on disk | 17,482 | 11,485 |
| fully loaded from a cold page | 1.27 s, 61 pieces | 1.32 s, 50 pieces |
| whole stage fitted | 1.95 s | 2.01 s |
| zoom ladder | ~0.3-0.5 s a rung | ~0.3-0.5 s a rung |
| pointers proven to cover their piece | 251 of 251 | 251 of 251 |

**Reads the same, writes the same, correctness the same** — the expectation
holds. The file count deserves the honest reading: each position went from six
files to three (four pieces into one bundle, plus its two descriptions), and
the rest of both totals is the view's written zoom levels, identical either
way. A single-plane 2 x 2-piece demo position is the *worst* case for
bundling; the plan's real shape — a whole stack of single-plane pieces in one
bundle — divides a position's picture files by pieces-per-position, which for
a 30-plane, 2048-voxel position is hundreds into one. The division grows with
exactly the thing that makes runs heavy.

And measured again the same day at sixteen times the ratio, to see whether it
stays flat: 300 positions of 2048 voxels — **64 pieces in one bundle** —
identical spots, both arms (`--tile 2048`):

| | plain | bundled |
| --- | --- | --- |
| writing and linking, per position | 210 ms | **158 ms** |
| files on disk | 26,391 | 7,554 |
| fully loaded from a cold page | 1.48 s | 1.32 s |
| whole stage fitted | 2.18 s | 2.18 s |
| zoom ladder | ~0.3–0.8 s a rung | ~0.3–1.0 s a rung |
| pointers proven to cover their piece | 533 of 533 | 533 of 533 |

Flat where it must be, and better where it may: reads and the ladder did not
move, a position's picture files went 66 to 3 — twenty-two into one — and
**writing got a quarter faster**, because one file created is cheaper than
sixty-four. The engine's asks over bundles count a little higher at the
busiest rung (each bundle answers through its own index), and the seconds do
not care. Packing more pieces per bundle makes bundling better, not worse.

### The graphics-card rows, NVIDIA T400 machine, 11 August 2026

The rows the sandbox owed, measured on the machine the plan was waiting for:
Windows 11, NVIDIA T400 4GB (every browser run announced ANGLE/Direct3D11 on
the card, none fell back to SwiftShader), Kaspersky endpoint protection fully
active, runs on a large data disk. Both pairs on identical spots, through the
production run writer, `--headed`.

At 10,000 positions of 512 voxels — five times the sandbox's 2,000, and the
first time both arms of this size have survived this machine at all:

| | plain | bundled |
| --- | --- | --- |
| writing and linking, per position | **29 ms** | 36 ms |
| files on disk | 87,652 | 67,654 |
| fully loaded from a cold page | 1.19 s, 61 pieces | 1.44 s, 58 pieces |
| whole stage fitted | 1.86 s, 72 pieces | 2.10 s, 69 pieces |
| zoom ladder | 0.30–0.40 s a rung | 0.30–0.64 s a rung |
| pointers proven to cover their piece | 1,171 of 1,171 | 1,171 of 1,171 |

And at 2048-voxel positions — 64 pieces in one bundle. **1,500 positions, not
the 2,000 this section used to ask for**: the bundle-sized lattice over an
81,920-voxel stage has 40 × 40 = 1,600 places, so 2,000 non-overlapping
positions cannot exist on it; the script now refuses the impossible ask in
words. At 1,500:

| | plain | bundled |
| --- | --- | --- |
| writing and linking, per position | 104 ms | **91 ms** |
| files on disk | 135,464 | 72,506 |
| fully loaded from a cold page | 1.29 s, 61 pieces | **0.71 s**, 69 pieces |
| whole stage fitted | 1.96 s, 72 pieces | 1.38 s, 80 pieces |
| zoom ladder | 0.30–0.43 s a rung | 0.31–0.43 s a rung |
| pointers proven to cover their piece | 2,805 of 2,805 | 2,805 of 2,805 |

The sandbox's verdict survives the card and the real disk: writing flat to
slightly better bundled at the ratio where bundling earns its keep, reads the
same or better, correctness identical. The demo-tile pair leans the other way
by 7 ms a position — sixty-odd extra sharding indexes to write and nothing
saved bundling 2 × 2 pieces — which is the "worst case for bundling" the
first sandbox table already named, now with a number on it.

Two honest footnotes. The "holding N GB" line reads 0.01–0.05 GB here, not
the 1 GB / 17 GB the setup section budgets: these synthetic tiles hold one
constant value and compress to almost nothing, so the *file counts* are real
and the *bytes* are not — budget disk by the setup section, not by this
table. And the cold-page piece counts (58–61 against the sandbox's 71) moved
with the placement lattice, not the machine: both arms here land on the
bundle-sized lattice, the sandbox's fine-lattice run asked the same window for
more, smaller-spread pieces. Piece counts belong to the window *and the
lattice*; seconds belong to the disk.

### What the endpoint protection did, same machine, same day

Kaspersky Endpoint Security 12.9.0, fully active throughout, no exclusion in
place. The score, run by run:

- **All four scatter arms above got through unkilled** — including the
  10,000-position pair whose earlier build this same machine's protection
  killed twice (silently, exit code 5). What changed: the runs were pointed
  at a folder on the data disk rather than the user profile's temp.
- **The frame-rate measurement was killed on its first attempt** (exit 5,
  6,471 files into the write, no traceback) and passed whole on the retry —
  the pattern the run doc predicts, on the smallest write of the day.
- **The step-4 arithmetic run was suspended mid-write** after ~31,000 files,
  hard enough that the machine needed a restart, and afterwards the
  protection **quarantined `python.exe` itself** out of both Python 3.14
  environments and conda's package cache (PDM:Trojan.Win32.Generic on the
  interpreter's hash). Restored by reinstalling the python package from
  conda-forge; a false-positive notice with the hash is with IT, asking for
  an exclusion on the measurement folder.

So the honest reading for acquisitions on machines like this: the sharded
arm's fewer files is not merely tidier, it is the difference between a run
the protection tolerates and one it kills, and an exclusion for the
acquisition folder should be part of commissioning a smart-microscopy PC.

## What this plan deliberately does not do

No stitching, no blending, no sub-voxel placement — those change pixels and
belong to the build/assemble route and the stitcher. No new formats: one zarr,
OME-Zarr 0.5 throughout, readable by anything that reads the standard.
