# Plan: every position store in absolute stage xyz

Written 2026-09-08 on branch `claude/smart-operator-workflow-review-ehw3c5`.
Follows from `BLACK_TILE.md`. **Implemented 2026-09-08** (writer, engine,
mock, tests, spec fixes); what was found on the way is at the end.

## Goal

A position store places every voxel in the stage's own frame, in all three
axes, whichever way it was acquired. `scale` is a positive voxel size;
`translation` is the absolute stage coordinate of the first voxel and may be
negative. Nothing about acquisition order or sweep direction survives into
the transform.

x and y already work this way (the overview's translation is the absolute
stage corner). z does not.

## What the writer does today

`application/parts/storage/zarr_positions.py`, `_the_z_model` (line ~318)
and `_the_corner_of` (line ~410), by design:

- **A "table" convention.** Every stack's lowest plane is placed at display
  z = 0; a flat capture lies at z = 0 too. Raw stage z is kept only as
  provenance (`acquisition_provenance.raw_stage_plane_centres_um`) and is
  explicitly *not* used as the store's z.
- **Signed spacing.** The median step between adjacent plane centres is
  written as the z `scale`, sign included, so a top-down sweep gets a
  negative scale. That is the invalid store neuroglancer refused.
- The model is written into the store's attributes as `z_coordinate`
  (`zmart-microscopy-2d-display-anchor-v1`).

So two conventions have to go: the table, and the signed step.

## The change

### 1. Writer (`zarr_positions.py`)

- Take each plane's absolute stage z from the record (`plane["z_um"]`,
  already present; confirm it is z-wide + galvo, the same number
  `get_xyz` reports).
- Sort the planes by that z, ascending, before filling the volume. A
  bottom-up sweep is unchanged; a top-down sweep is reversed.
- `scale_z` = |median adjacent step|; `1.0` for a single plane.
- `translation_z` = the lowest plane's absolute z (single plane: its own z).
  Positive or negative as the stage says.
- Drop the display-anchor model from the transform. Keep the provenance
  block (plane order as acquired, sweep direction, requested z) in
  attributes for anyone who wants the acquisition story.
- Both writers (`_write_a_position` ~line 117 and the second at ~line 508)
  go through the same helper so they cannot drift.

### 2. Engine (`viz_studio/options/neuroglancer-under/viewer.js`)

The `2d-overlay` presentation assumes the table: "every stack begins at
z = 0, so that is where the picture opens". Replace with:

- Open at the lowest z among the loaded stacks, or at the current stage z
  when the page supplies one; never at a hard-coded 0.
- `withItsDepthKeptToItself` (flat sources drawn at any depth) stays as is;
  it is what keeps the overview visible while scrubbing through a stack.
- `theDepthItCanShow` reads bounds from the space, so it follows.

### 3. Page

- Z slider (`parts/canvas/viewer.js` ~line 882-950): reads
  `lowUm/highUm` from the engine, so it follows. Check the label reads
  absolute µm rather than "plane 1".
- Focus step slice preview and orthogonal view: they fetch slices from the
  bridge by index. Confirm they map index -> height through the record's
  plane z, not through "index 0 is the first captured plane".
- Stage mark / `takeThePosition` z: nothing to change, it is already
  absolute.

### 4. Tests and mock

- `parts/storage/test_zarr_positions.py`: replace the table assertions
  with absolute-z assertions; add a top-down sweep case (negative raw
  steps -> positive scale, reversed planes, translation = lowest z) and a
  negative-stage-z case.
- Mock instrument: add a top-down focus sweep option so the walk covers it.
- `viz_studio` option tests: the "picture opens at z=0" expectation, if any.
- `the-operator-walk.spec.js`: update the two stale expectations noted in
  `BLACK_TILE.md` (focussing eye default, pre-scan pixel count).

### 5. Verification

1. Rewrite last night's run's focussing store with the new writer from its
   record, then `engine-look.spec.js` with both real stores at
   `ZV_CENTRE=12433,10688`: the overview must draw with the stack beside it.
2. The operator walk on the mock, bottom-up and top-down.
3. One real focus map + overview scan in the window: tile shows the field,
   chip bar present, Z slider spans the stack in absolute µm.

## Sequence

Writer + unit tests -> engine open-depth -> page checks -> mock top-down ->
walk spec fixes -> real-run verification. The writer alone already fixes the
black tile; the rest makes the absolute frame consistent end to end.

## Risks

- Existing runs on disk carry the table convention; the viewer will show
  them at z = 0 while new ones sit at stage z. Acceptable: old runs are
  test runs. If not, a one-off migration reads provenance and rewrites the
  transform.
- The engine's open-depth change touches the delicate depth code; keep it to
  the one line that picks the opening plane.
- Which z the driver reports per plane (z-wide vs galvo vs sum) must be
  pinned down before step 1; the bridge log's "planes are stamped at the
  drive's height" warning suggests it is not always a true per-plane value.

## What happened when it was done

- **Writer:** `_the_z_model` now returns the array order (vendor z numbers,
  ascending stage z), a positive spacing, the lowest plane's stage z and the
  provenance (`zmart-microscopy-absolute-stage-z-v1`). `_the_volume_of` takes
  that order. Both writers share it. 23 unit tests pass, including a
  top-down sweep, an up-vs-down pair that must produce identical stores, and
  a stack below the origin.
- **Engine:** `standOnTheTable` and the `2d-overlay` branch of
  `openOnThePlaneWhereTheSpecimenIs` open at the lowest plane on the shared
  depth axis (`theLowestPlaneOf`) rather than at a hard-coded z = 0.
- **Mock:** `ZMART_MOCK_FOCUS_SWEEP=down` makes the pretend stage sweep
  top-down; the operator walk passes either way.
- **Specs:** `review-live-target-arrival` and `step-five-kidney-evidence`
  no longer expect display z = 0; the operator walk's two stale expectations
  are relaxed as `BLACK_TILE.md` describes.
- **Verified on real data:** last night's focussing stack, re-encoded from
  its TIFFs and provenance by the new writer (scale +1.2998, translation
  -5804.05), draws beside last night's overview in `engine-look.spec.js` with
  no layer error. The overview draws whole; the focus patch sits at its
  centre.

## Open: which z the driver stamps on a plane

The pinned risk turned out to be real. In that run the stage reported
z = 6.97 um (`get_xyz`, and the overview's plane), while the focus stack's
per-plane `z_um` ran from -5603.9 to -5804.0. Those are two frames, not one.
The picture still draws, because a flat source keeps its depth to itself,
but the Z slider will read the stack's numbers and a stack and a flat
capture taken at the same place will not line up in z until the driver
stamps every plane with the same z the stage reports. That is a driver
question (z-wide vs galvo vs the sum), to settle in
`zmart_drivers/leica/.../navigator_expert`, not in the writer.

## Noted: a knife-edge in the operator walk

`the-operator-walk.spec.js` sometimes fails its last assertion with "the
nearest tissue is 43px from the projected first field" against a 40 px
limit, upward and downward sweeps alike, and passes on a rerun. It is the
screenshot's timing against which field has landed, and predates this
change.
