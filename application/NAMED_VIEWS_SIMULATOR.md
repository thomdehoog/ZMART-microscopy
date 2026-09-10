# Named views and simulator integration

Feature branch: `codex/operator-named-views-simulator`, based on local
`codex/operator-relative-z-integration` at `7e0b8f8f`, including its rig fixes.
Companion viewer branch: `codex/operator-embedding`, version `0.5.0.dev0`.
Tested viewer commit: `1af6d7ab1633dd34449c6451862d0da1016edc07`.
Neither branch is a microscope deployment.

## Display and storage

Top | Slice | MIP sit before Carrier. Selection is remembered per acquisition;
only its selected named product reaches the engine. Top is the operator default.
The original stores retain specimen Z; relative display placement belongs to
the viewer. Top holds boundary planes, Slice samples Z, MIP remains flat.

The coalesced publisher creates `<acquisition>_top.zmartview.zarr`,
`<acquisition>_slice.zmartview.zarr`, and `<acquisition>_max.zmartview.zarr`
in the run's `view` folder. Acquisition identity comes from metadata. Separate
original position stores remain untouched. Per-position MIPs go in the
acquisition's `projections` folder. Bake off/on uses the same products and
coverage; the bridge does not compose image data.

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
The feature-only requirements/conda pins name the exact viewer commit. Until
that commit is pushed, use the local viewer checkout; a remote-only installation
cannot fetch an unpublished commit. Existing rig pins are unchanged.

## LAS X simulator

The operator's `--simulator-pixels` flag is opt-in and labels the native window
`LAS X SIMULATOR / SYNTHETIC PIXELS`. Replacement occurs after the real TIFF read,
in the storage ingestion seam, only with allowlisted SIMULATOR vendor metadata.
It neither edits the driver nor changes saved vendor TIFFs. Synthetic provenance
is recorded in the OME-Zarr. Missing files/coordinates fail instead of becoming
synthetic success.

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
