# Two of eight tiles — 2026-09-08

Branch `claude/smart-operator-workflow-review-ehw3c5`, fix in `fbe0de7a`.
Rig: Stellaris 5, Y42H93.

After the branch moved every position store onto specimen z (`feffb418`),
the first real overview scan drew tiles 1 and 2 of 8. All eight stores were
on disk and correct. The canvas shows one depth; each flat tile stood at its
own focus height, a micrometre or so apart; only the two whose one-voxel
slab crossed the viewing plane were drawn.

## What was on disk

Run `E:\Experiments\ZMART-microscopy\target-acquisition_5d4481`, eight
one-plane overview stores, z translation from the measured focus map:

| tile | well  | z (µm) | slab (µm)     | crosses 63.49 |
|-----:|-------|-------:|---------------|---------------|
| 1    | left  | 62.99  | 62.99 – 63.99 | yes           |
| 2    | left  | 62.79  | 62.79 – 63.79 | yes           |
| 3    | left  | 64.26  | 64.26 – 65.26 | no            |
| 4    | left  | 64.01  | 64.01 – 65.01 | no            |
| 5    | right | 61.10  | 61.10 – 62.10 | no            |
| 6    | right | 60.40  | 60.40 – 61.40 | no            |
| 7    | right | 62.20  | 62.20 – 63.20 | no            |
| 8    | right | 61.40  | 61.40 – 62.40 | no            |

The canvas opened at the centre of tile 1's voxel (63.49 µm). The prediction
matched the screen exactly, including an empty right well.

## What the viewer was supposed to do

`854874c4` made every flat source a metre thick along a depth kept private
to its layer (`A_FLAT_PICTURES_THICKNESS` in
`viz_studio/options/neuroglancer-under/viewer.js`), so a slice is seen from
any height while focusing through a stack. `NEXT_SESSION.md` already
recorded that this was unreliable (last tile of four stayed thin). With real
per-tile heights it failed on six of eight.

## The first patch, and why it was wrong

A first attempt cancelled each tile's z inside the viewer by folding the
source's input lower bound into the transform's shift. It passed a
Playwright spec built from eight tiles at the run's own heights. It did not
work in the window.

Measured in the real scene: neuroglancer reads an OME-Zarr translation into
the source's *input bounds*, not its transform, and re-expresses those
bounds whenever the unit of the shared depth changes. The focussing stacks
land with a 1.30 µm step and set that unit; the spec had no stacks, so
nothing rescaled. In the real scene the four loaded overview tiles stood at
four depths ~600 000 voxels apart, each 1.54 million thick:

```
overview tile 1   z' lower  -32 741 628   upper  -31 203 013
overview tile 2   z' lower  -32 136 534   upper  -30 597 919
overview tile 3   z' lower  -31 031 670   upper  -29 493 055
overview tile 4   z' lower  -30 327 976   upper  -28 789 361
```

A display-only cancellation cannot be made stable against that rescaling.
Reverted before the commit.

## The rule, and the fix

> Stacks are placed relative to each other. Slices are all shown at the
> same z. The store keeps the height a slice was really taken at, as
> provenance.

1. **Writer** (`application/parts/storage/zarr_positions.py`): a one-plane
   capture is written at `A_FLAT_CAPTURES_SHARED_Z_UM = 0.0`; its measured
   height stays in `acquisition_provenance.plane_centres_um`. Stacks are
   unchanged and keep absolute specimen z.
2. **Viewer** (`viewer.js`): the metre-thick slab for a flat source is
   centred on the shared depth. No bound arithmetic.
3. **Tests**: `parts/canvas/flat-tiles.spec.js` writes eight tiles at the
   run's heights, arriving one by one and all at once, and asserts every
   source is thick and shares one lower bound. `test_zarr_positions.py`
   asserts the shared z and the preserved provenance.

| check                                       | result           |
|---------------------------------------------|------------------|
| `test_zarr_positions.py`                    | 24 passed        |
| `flat-tiles.spec.js` (3 tests, Chromium)    | 3 passed         |
| rescan on the rig after a bridge restart    | 8 of 8 drawn     |

## Consequences worth knowing

- Runs recorded before `fbe0de7a` keep per-tile z in their stores and still
  draw sparsely. Rescan, or rewrite the stores, to see them whole.
- A flat target frame and a stack at the same site no longer line up in z
  on the canvas. The frame's true height is in provenance.
- This is a pragmatic patch, not an elegant one. The clean version would
  place flat sources in the viewer, which needs a way to reach
  neuroglancer's input bounds that the adapter does not expose today.
- The Python change lives in the bridge, which runs inside the window
  process: any edit there needs a window restart, not a page reload.

## Session notes

- Launch the operator window visibly. Started with a hidden window style,
  pywebview inherits it and the ZMART window never appears.
- A synthetic spec passing is not evidence for the rig. "Fixed" should have
  waited for the window; it now does.
