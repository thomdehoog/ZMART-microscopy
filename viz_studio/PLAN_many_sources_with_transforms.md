# A hundred placed sources: the fault was in the script, not the engine

This document first recorded an unexplained rendering fault and proposed an
investigation. **The fault was mine and it is fixed.** What is kept here is the
cause, why four diagnoses in a row missed it, and the corrections a review turned
up in the surrounding work — because those outlast the bug.

## What actually happened

Ten positions placed by a translation in each store's description drew correctly.
A hundred drew as a patchwork of blocks at mismatched scales.

**A position records its stage position in the multiscale-level
`coordinateTransformations`.** The script that built the hundred deleted it:

```python
multiscale.pop("coordinateTransformations", None)   # the whole fault
```

An earlier version of the same script did the same damage by another route,
rewriting that block to drop any `translation` in it. The script that built the
working ten touched only `multiscale["datasets"]` and left the stage position
alone.

Compared field by field, on the same position of the same run:

```
ORIGINAL      multiscale: translation [.., 0, 832.0]        the stage position
              dataset:    scale only

WORKED  (10)  multiscale: translation [.., 166.4, 166.4]    preserved
              dataset:    scale + translation -16.64        the correction, composed on top

BROKE  (100)  multiscale: (none)                            deleted
              dataset:    scale + translation -83.2         only the correction left
```

With their stage positions gone, all hundred tiles collapse towards the origin and
pile on one another. That is the patchwork. Restoring the block fixes it; a hundred
sources then draw as a sharp grid with the tiles overlapping as asked.

The correction belongs in the dataset transforms, which **compose with** the stage
position rather than replacing it. `place_positions_by_transform.py` does it that
way and says so at length.

## Four diagnoses, all wrong, all argued from the code

Kept because the pattern matters more than the bug.

1. **The transform slot** — multiscale level against per dataset. Both "failed",
   because both versions of the script deleted the placement.
2. **Fractional voxels** — 51.2 is a fifth of a voxel. 64 is whole at every level
   and "failed" too, for the same reason.
3. **Overlap and compositing** — separating the tiles so none ever met "failed"
   as well. Same reason.
4. **Progressive loading** — `lit` was flat, so the picture was called settled.

Every one was reasoned from reading the engine, and every one was tested by
changing a variable in the *broken* script — so all four inherited the bug and all
four appeared to be disproved. **Varying something inside a broken harness cannot
disprove anything.** What found it was diffing the working build against the broken
one, which is the first thing that should have been done and was the eighth.

## What the review corrected, and still stands

An adversarial review was run against the earlier version of this document. Its
central verdict is moot — it was analysing a fault that did not exist — but four of
its findings are about the surrounding work and survive.

- **`lit` is not the fraction of the panel with specimen on it.** It is the
  fraction of the **centre half** of the canvas above a brightness floor
  (`tests/pixels.py`), and it is blind to which pyramid level drew. It cannot tell
  a settled picture from a refining one, so diagnosis 4 above was never evidence
  either way. Use it as a blank-screen guard and nothing else.
- **`held` counts sources a layer *declares*, not sources that loaded.**
  `layer/index.js` pushes each one synchronously, and one that fails stays in the
  list with an error on it, still counted. "All hundred registered" was never
  evidenced. The honest reading is separate counts of loaded, failed and pending.
- **The camera is a load race.** Neuroglancer centres the view once, from
  whichever source resolves first, and never recentres; the zoom is reset the same
  way. With per-store placements each source declares different bounds, so the view
  can land differently run to run. **Nothing measured so far pinned position or
  zoom**, and it should.
- **A whole number of voxels is not a whole number of chunks.** The writer keeps
  the chunk size constant while halving each level, so 64 voxels is one chunk at
  level 0 and a quarter of one at level 2.

## What to do next

- Pin `position` and `zoomFactor` explicitly after opening, in anything that
  compares two arrangements. Until then rows are comparable only loosely.
- Re-run the ladder in `PLAN_placement_by_transform.md` with the camera pinned and
  with loaded/failed/pending counted rather than `held`. The shape of the curve is
  unlikely to move; the numbers deserve to be trustworthy.
- If a rendering fault is ever suspected again: **diff the artefact that works
  against the artefact that does not, before forming any hypothesis about the
  engine.**
