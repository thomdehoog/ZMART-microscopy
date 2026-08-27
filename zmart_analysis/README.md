# ZMART Analysis

The party that reads pixels and returns numbers. ZMART has three: the
instrument moves and captures, this measures what was captured, and the page
decides what to do about it. Nothing here moves a stage. See
`docs/design/what-runs-where.md` for where the line falls.

## The workflows

- **`focus/`** — sharpness of every plane in a z-stack: a gradient metric and
  an entropy one, both on every run, peak refined between planes. Returns a
  trace and a decision.
- **`object_analysis/`** — cellpose detection, per-object features, object
  table. `object_analysis.yaml` is detection plus features; `object_detection.yaml`
  stops at the checkpoint.

Each step's docstring is the reference for what it takes and returns; each
pipeline's YAML lists every parameter with its default. Detection parameters
can be set in the pipeline or overridden per submission, so the operator page
can tune on one position without registering a pipeline of its own.

## Reading and writing

`_image_io.load_plane` reads an OME-Zarr position (ngio, NGFF 0.4 and 0.5) or
an OME-TIFF (tifffile, ome-types) through one contract, lazily, so a position
costs the planes asked for. It refuses a channel-last `(H, W, 3)` image, which
is RGB samples to a TIFF reader, and a focus stack that does not say which axis
is depth.

`_output.py` says where results go: the `analysis` folder beside the `data` an
image came from, under the frame's short name.

    <acquisition>/data/  vendor/  analysis/

**`tifffile` must be 2026.6.1 or newer.** Older versions import a name zarr 3.3
moved and every read fails claiming `zarr 3.3.0 < 3 is not supported`. Pinned in
both `setup_env.py` files and in CI.

## Where this came from

Vendored from [smart-analysis](https://github.com/thomdehoog/smart-analysis)
`v4-engine` at `a760858`, as a **copied subset** — not a subtree, so there is no
automatic re-sync. Taken: `engine/`, the shared `workflows/_*.py`,
`object_analysis/`, `conftest.py`, `LICENSE`. Left: `basic_test`,
`cell_analysis`, `rare_event_selection`, `target_discovery`, and the packaging.
Upstream's `target_acquisition` was taken and then removed, superseded by
`object_analysis`; so was the DINO deep-feature path (`extract_deep_features`,
`_object_crops`, `_intensity_scale`, `load_detected_objects`, the `*_deep`
pipelines) — unused here, and one `git archive` away when wanted.

`workflows/_image_io.py` comes from a different branch,
`claude/v4-branch-wweiv5` (`rare_event_selection/steps/image_io.py`) — the one
file here whose upstream is not `v4-engine`. `workflows/focus/` and
`workflows/_output.py` were written here and have no upstream.

### Changes to vendored code

Kept minimal, so a re-sync stays cheap.

- `conftest.py` registers the pytest markers, which upstream declares in a
  `pyproject.toml` that was not taken.
- `test_object_analysis.py` and `test_image_io.py` skip tests for workflows and
  engine APIs this checkout does not have.
- `detect_objects.py` derives `output_dir` from the image when the caller names
  none. Upstream had no acquisition layout to derive it from.
- `_segmentation.py` reads through `_image_io`; `segment_tiff` became
  `segment_position`. It gained `filter_masks_by_border` for tile overlap, and
  `segmentation_params` now accepts per-submission overrides.
- `run_pipeline.py` reads through the same contract.

Nothing in `engine/` was modified.

## Running the tests

    python -m pytest zmart_analysis

Tests needing a runtime that is absent skip themselves. **On this machine use
`dino3_test`**: in `lasxapi_extended`, torch fails to load `fbgemm.dll`
in-process while the cellpose probe, which runs in a subprocess, passes.

    C:/ProgramData/MinicondaZMB/envs/dino3_test/python.exe -m pytest zmart_analysis

## Still owed

Nothing has run against a real ZMART acquisition — every store tested so far is
synthetic or a skimage sample. The rest of `claude/v4-branch-wweiv5` (foreign
stores, the rename) is not ported.
