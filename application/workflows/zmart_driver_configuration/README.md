# ZMART driver setup: setting a microscope up

Five steps, walked before any imaging workflow can stand on the machine:

1. **Connect** — open the driver's *setup*. The same step target acquisition
   starts with, borrowed rather than retyped; only its wording differs.
2. **Set up limits** — how far the stage may travel, which objective slots
   automation may use, and a permitted value or range for each setting the
   driver can change. Two boxes: one that reads the corners the operator
   marked, one that holds the document to publish.
3. **Stage-to-image calibration** — which of the eight lossless ways of laying a
   picture down lines it up with the stage. Three pictures and a known move;
   the analysis does the looking.
4. **Optics calibration** — where and at what height a target lens looks
   relative to the reference lens. The same field through each, and a short
   focus stack under each; the operator changes lenses by hand between the two.
5. **Set up origin** — drive to the point the run should count from and make it
   (0, 0, 0).

Steps 2 to 5 publish the four documents the driver keeps for a machine — under
`limits/`, `orientation/`, `calibration/` and `origin/` in dated snapshots, the
newest of which the driver stands on at its next connect.

## What is where

```
flow.js              the front door: the name, the steps, the panel, the backend
panel/               the notebook-shaped panel this workflow works on (no canvas)
steps/
  cells.js           the cells every step is made of: a title, a sentence, a
                     control, and what came back
  connect/           the borrowed Connect step, reworded
  stage_limits/      step 2 and its two boxes
  stage_to_image/    step 3 and its cells
  optics_calibration/  step 4 and its cells
  frame_origin/      step 5 and its cells
drivers/             what a page-side driver module may declare (wording); the
                     driver's own account of itself comes from the seam
```

The page-side half of the seam is `../../parts/microscope/setup.js`; the
Python half is `zmart_setup/` at the repository root, with each driver's setup
beside its operating adapter (`zmart_drivers/mock/mock_setup.py`,
`zmart_drivers/leica/.../zmart_adapter/setup.py`). The measurements themselves
live in `zmart_analysis/workflows/stage_calibration/`, and never learn which
microscope took the pictures.

## The boundary, in one paragraph

Configuring a driver deliberately does not go through the controller. The
stage is guarded by a published envelope and, independently, by a hard-coded
backstop no file can widen; that layering only means something while the thing
being limited cannot rewrite its own limits. The origin is kept behind the same
door, because moving it silently redefines every recorded position. Agents will
drive the controller; keeping configuration off it is what makes "an agent
cannot arrive at a new machine configuration on its own" structural rather than
a matter of asking nicely. The full reasoning is in
`docs/design/2026-09-05-zmart-driver-configuration-workflow.md`.

## Trying it without a microscope

Run the bridge and open the page; choose **ZMART driver setup** and
connect to the mock. Open `python application/mock-instrument.py` beside it:
that window is the pretend rig — turn its camera, change its lens, drop four
markers at the corners — and the workflow has to measure what the window shows,
the way it would on a rig it cannot change. What each step publishes appears at
the bottom of that window, as the driver will read it at the next connect.
