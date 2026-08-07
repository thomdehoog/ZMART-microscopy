# Should ngio write the positions? Tested, and what it settles

Written 7 August 2026, by writing a position through ngio and putting it in front
of every reader that has to accept one.

The question came from a fair observation: today's blocking fault — a position
that states its place on the stage in a spot the format does not allow — happened
because the metadata is written by hand. **A library that writes the metadata for
us cannot make that mistake.** So it is worth knowing exactly how much of the
outstanding work that would take away.

The short answer: **four of the eleven changes on the list, including two of the
three repairs — and it hands the third to you immediately rather than eventually.**

---

## What was tested

One position, written entirely through ngio at OME-Zarr 0.5, with every knob the
recipe calls for:

```python
container = ngio.create_empty_ome_zarr(
    store=..., shape=(1, 1, 1, 512, 512),        # t, c, z, y, x
    pixelsize=0.35, z_spacing=2.0,
    axes_names=["t", "c", "z", "y", "x"],
    translation=(0.0, 0.0, 11.0, 5.5, 7.25),     # where it sits on the stage
    levels=4, scaling_factors=(1, 1, 1, 2, 2),   # y and x halve, z is kept
    chunks=(1, 1, 1, 128, 128),
    shards=(1, 1, 1, 512, 512),                  # one bundle per tile plane
    dtype="uint16", ngff_version="0.5",
)
image.set_array(...)
image.consolidate(order=0)                        # build the pyramid, nearest
container.add_table("owned_ROI_table", container.build_image_roi_table("owned"))
```

Then handed to the four readers a position has to satisfy:

```
1. official 0.5 image schema : VALID
2. ngio                      : opens. axes ('t','c','z','y','x'), pixel size (2.0, 0.35, 0.35)
   level 0: ['scale', 'translation']
   level 1: ['scale', 'translation']
3. ZMART's viewer reader     : is_store=True, axes ok, voxel size ok
4. chunk layout for pointing : chunks [1,1,1,512,512], codecs ['sharding_indexed']
   files under level 0        : ['c/0/0/0/0/0', 'zarr.json']
```

**The translation lands on every level, after the scale, without being asked for.**
That is the blocking fault gone by construction: the API takes a `translation`
argument, so there is no way to put it in the wrong place.

**And bundling reaches every level, capping itself on the small ones:**

```
level 0: 512² chunk 512²  sharding_indexed  1 data file
level 1: 256² chunk 256²  sharding_indexed  1 data file
level 2: 128² chunk 128²  sharding_indexed  1 data file
level 3:  64² chunk  64²  sharding_indexed  1 data file
```

That is exactly what change 2 was described as needing — bundle every level, cap
the bundle at the level's own extent — and it arrives for nothing.

---

## What it settles, and what it does not

| # | change | through ngio? |
| ---: | --- | --- |
| **1** | **Per-dataset translation** | ✅ **settled** — the API takes it as an argument |
| **2** | **Bundle every level** | ✅ **settled** — including the cap on small levels |
| 3 | Server reads a bundle index | ❌ the viewer's server; untouched — **and see the warning below** |
| 4 | Two interop tests | ~ still worth having; one of the two becomes structural |
| 5 | `plan_a_grid` | ❌ ngio *takes* a chunk. Deciding which chunk is still ours |
| **6** | **`tables/owned_ROI_table`** | ✅ **settled** — `build_image_roi_table` + `add_table` |
| 7 | Chunk-aligned seams | ❌ the writer's geometry, not the format's |
| 8 | Unique label numbers across a run | ❌ an analysis convention |
| 9 | A view for segmentations | ❌ the view; non-standard by design |
| 10 | A run-level table | ❌ its table API helps, but assembling the run's is ours |
| **11** | **0.5 as the default everywhere** | ✅ **settled** — `ngff_version` on every call |

### The warning that comes with it

**Change 3 stops being optional.** ngio bundles by default, so the moment the
positions are written this way, every store on disk is bundled — and the viewer's
server today hands over whole chunk *files*. A bundled chunk is a stretch of bytes
inside a file, found through an index. So the server has to learn that on day one
rather than eventually.

That is probably still the right trade. Change 3 was on the list anyway, and this
forces it to be done properly instead of deferred.

---

## Where the line falls

**The position is ngio's. The run is ours.**

| ngio writes | we write |
| --- | --- |
| the position container and all its metadata | the **view** — an image whose chunks live elsewhere; non-standard by design, and no library will ever produce it |
| the pixels, and the pyramid (`consolidate`) | the pointer map, appended a line at a time |
| `tables/owned_ROI_table` | the coverage record — the format has nowhere to say "this ground has really been imaged" |
| later: `labels` and measurement tables | the queueing of positions for analysis |

That is a better boundary than the code has today. The positions are the part that
**must** be standard — they are what a stitcher, a colleague or a pipeline opens.
The run-level machinery is where this project's invention actually lives, and it
stays hand-written because nothing else could write it.

---

## What it costs

- **Sixty-one packages on the microscope computer**, where today `zmart_storage`
  needs `zarr` and `numpy` and nothing else. This is the real price and it should
  be checked against the acquisition environment before committing.
- **ngio cannot resize an array.** There is no `resize`, `append` or `extend` —
  only `shape`, which is read-only. So a run must **declare generously and fill
  in**, which is already exactly what this project does; `canvas.py` says so in as
  many words. For a position it is a smaller concession than it sounds: `y` and
  `x` are the camera frame, `z` is the stack depth and `c` is the channels, all
  known before the run. **Only `t` is over-declared.**
- **Two loose ends found in the test**, neither a blocker:
  - **Channel metadata came out as `channel 1`, with no colour and no window.**
    The call for it needs finding. It matters, because that block is what makes an
    acquisition open at the brightness it asked for rather than the camera's whole
    range.
  - **ngio writes zarr's consolidated metadata**, which is not part of the Zarr v3
    specification — it warns about this itself. Harmless to readers that ignore
    it; worth checking Neuroglancer is one of them.

---

## Recommendation

**Adopt it for the positions.** It removes two of the three broken things, brings
the third forward, and puts the part of the arrangement that has to be standard in
the hands of a library that cannot get it wrong.

Do these first, in this order:

1. **Find the channel metadata call**, so colours and windows survive.
2. **Teach the viewer's server to read a bundle index** — required from the first
   ngio-written run, not later.
3. **Check the sixty-one packages** against the microscope computer's environment.
4. **Then switch the position writer**, leaving the view, the pointer map and the
   coverage record exactly where they are.
