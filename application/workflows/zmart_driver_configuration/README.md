# ZMART driver configuration: setting a microscope up

Five steps, walked before any imaging workflow can stand on the machine:

1. **Connect** — open the driver's *setup*, then choose the **configuration**
   to work in: reopen one to see and edit what it holds, or start a new one
   as a full copy of the newest. A configuration is one folder the machine
   keeps, named by the moment it was started, holding its limits, orientation,
   objective calibration and origin together. Every step after Connect starts
   from what the chosen configuration holds, and each Save and adopt writes
   into it. The same step target acquisition
   starts with, borrowed unchanged; only the backend behind it differs.
2. **Define limits** — how far the stage may travel, which objective slots
   automation may use, and a permitted value or range for each setting the
   driver can change. Two boxes: one that reads the corners the operator
   marked, one that holds the document to publish.
3. **Image-to-stage calibration** — which of the eight lossless ways of laying a
   picture down lines it up with the stage. Three pictures and a known move;
   the analysis does the looking.
4. **Objective calibration** — where and at what height each lens looks relative
   to one reference lens. Ideally a microscope is parcentric and parfocal and
   every offset is zero, so choosing the reference gives every other lens a
   preset at zero straight away; the reality is often otherwise, so a preset is
   refined by measuring it: the same field through each lens, and a short focus
   stack under each, the operator changing lenses by hand between the two.
5. **Define origin** — drive to the point the run should count from and make it
   (0, 0, 0).

A configuration lives under the machine's root as `configuration_<datetime>/`
(the ProgramData API root on the Leica, the machine root on the mock), holding
the four subsystem trees the driver has always kept, unchanged inside it. Each
subsystem snapshot carries its document and, beside it, the evidence: the
figures the analysis drew and the measurement's numbers, so a reopened
configuration shows what was measured. The driver stands on exactly one
configuration: the one named at connect, else the newest. The controller always
names one, and refuses one without limits.

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
  image_to_stage/    step 3 and its cells
  optics_calibration/  step 4 and its cells
  frame_origin/      step 5 and its cells
```

The page-side half of the seam is `../../parts/microscope/setup.js`; the
Python half is `zmart_setup/` at the repository root, with each driver's setup
beside its operating adapter (`zmart_drivers/mock/mock_setup.py`,
`zmart_drivers/leica/.../zmart_adapter/setup.py`). The measurements themselves
live in `zmart_analysis/workflows/driver_configuration/`, and never learn which
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

Run the bridge and open the page; choose **ZMART driver configuration** and
connect to the mock. Open `python application/mock-instrument.py` beside it:
that window is the pretend rig — turn its camera, change its lens, drop four
markers at the corners — and the workflow has to measure what the window shows,
the way it would on a rig it cannot change. What each step publishes appears at
the bottom of that window, as the driver will read it at the next connect.
