# Named views and simulator integration

Feature branch: `codex/operator-named-views-simulator`, based on local
`codex/operator-relative-z-integration` at `7e0b8f8f`, including its rig fixes.
Companion viewer branch: `codex/operator-embedding`, version `0.5.0.dev0`.
Tested viewer commit: `90e0350777a2852ee19dee7b5fe48846aa5bcf14` (published).
Neither branch is a microscope deployment.

## Display and storage

The operator draws one product of every acquisition: its maximum projection.
A single plane is its own plane; a stack, the focus stacks of Step 4 included,
is collapsed to its projection and lies flat beside the single planes. There
is no Z slider under the picture and no depth to navigate. The T slider
remains for a timelapse.

The dropdown over the picture, in the row's right half directly left of the
acquisitions strip, lists Projection (the default and the only way that is
built), Z-slices (Top view), Z-slice (Absolute) and 3D. The last three are
greyed out and nothing exists behind them; they name what is not built yet.
The dropdown appears with the first published product. Top and Slice were
removed on 2026-09-21 (see `PLANE_TOP_ABSOLUTE_SLICE_2026-09-10.md`); the
shared viewer still supports them for its own use.

The column beside the canvas is the step's channel alone. The picture's own
panel is mounted out of sight; the operator reaches its acquisitions and
channels through the row over the picture, whose presses drive that panel.

The coalesced publisher creates `<acquisition>_max.zmartview.zarr` in the
run's `view` folder and nothing else. Acquisition identity comes from
metadata. Separate original position stores remain untouched, retaining
specimen Z. Per-position MIPs go in the acquisition's `projections` folder.
Bake off/on uses the same product and coverage; the bridge does not compose
image data.

Step 6 reads the original position through the analysis reader's `z="max"`
path, including the additional channels. It uses the captured pixel calibration
and first timepoint. A projected stack has no single-plane Z; acquisition focus
provenance remains separate. MIP raises the noise maximum as stack depth grows:
Fast thresholds may need retuning between unequal-depth acquisitions. No
normalization is silently applied. Min, Sum and 3D controls are out of scope.

## Installation and build

Use a separate test environment, install the companion viewer checkout, then
install this operator with `pip install -e <operator-checkout>`. The service checks the exact viewer version; an older
viewer is an explicit error, not an empty canvas fallback. In `application`,
run `npm ci` and `npm run build` with that environment's Python on the configured
tool path. The worker build imports the growth patch from the installed viewer.
Distribute the rebuilt page and its matching generated worker together.
The feature-only requirements/conda pins name the exact published viewer commit.
The viewer requires its frontend build before wheel creation; a bare Git pip
install does not perform that build. Use the source-build/wheel instructions in
`MICROSCOPE_INSTALL_HANDOVER_2026-09-10.md`. Existing rig branches are unchanged.

## LAS X simulator

The operator's `--simulator-pixels` flag is opt-in and labels the native window
`LAS X SIMULATOR / SYNTHETIC PIXELS`. Replacement occurs after the real TIFF read,
in the storage ingestion seam, only with allowlisted SIMULATOR vendor metadata.
It neither edits the driver nor changes saved vendor TIFFs. Synthetic provenance
is recorded in the OME-Zarr. Missing files/coordinates fail instead of becoming
synthetic success.
The visual simulator now uses the same scikit-image kidney micrograph as the
mock, with fixed specimen-space XY placement and Gaussian defocus around a
recorded synthetic focus height (the stage's specimen Z at connection). This
reference stays fixed across every job, tile and stack in the session and is
saved in `synthetic-specimen.json` and each position's provenance. Reconnecting
starts a new synthetic specimen at the new starting height; old captures are
never rewritten. The probe also anchors once, or accepts `--focus-z-um`.
It is a defocus model
of a 2D image, not an anatomical 3D kidney reconstruction. The small cell-pattern
provider remains available for numerical tests (`--pixels cells` on the probe).
Focus scoring and focus-stack previews read the canonical first-timepoint store,
including its physical Z ordering, rather than the untouched vendor stripes.
The legacy TIFF path remains for callers without a canonical position; failed
canonical conversion is not permission to score a different TIFF image.
An explicit simulator-identity refusal aborts both scan and focus acquisition.
The Detect/Discover preview reads the canonical OME-Zarr MIP, as detection does;
it does not reapply the simulator recipe or read different vendor pixels.

For a bounded capture probe, run the module below in the configured environment:

```text
python -m application.parts.microscope.probe_named_views_simulator --output <new-folder> --job <flat-job> --job <stack-job>
```

The probe checks simulator identity and idle state, takes the jobs as arguments,
and restores the selected job. It does not encode job names, plane counts or
scan direction. Synthetic cells use recorded physical XYZ and channel/time,
not filenames or arrival order; ascending/descending and overlapping fields
are covered by automated tests. Original file hashes are retained as evidence.

Simulator verification is not proof of the rig's stage calibration, optical
quality, or real acquisition throughput. Do not deploy this branch to the rig
until the integration review and microscope checks are complete.

## Remaining lifecycle limits

Connect starts a new run. Resuming an existing named publication across a process
restart is not supported by this operator: its local revision counters must first
be reconciled with committed viewer revisions. Do not bypass revision rejection.

Superseded per-position projection products are retained. Automatic pruning needs
ownership across every publication sharing that projection folder; deleting files
based only on this acquisition's current order could break another view set.
Repeated rewrites therefore grow projection storage until a safe retention policy
is implemented. No original or derived acquisition data is deleted by this change.

Synthetic replay proves consistency with the recorded coordinates, not that LAS X
reported the correct physical coordinates. The full workflow tests use the mock;
real simulator focus scoring and microscope calibration still require validation.
