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
- `to_builtin` (in `build_object_table.py` and `detect_objects.py`) takes the
  `item()` door only for 0-d values: a one-element numpy array also answers
  `item()`, which collapsed a single-object field's columns to scalars and
  crashed the table step with `len()` on an int.
- `run_pipeline.py` reads through the same contract.
- The `environments/setup_env.py` and `clean_env.py` scripts (focus and
  object_analysis alike) had their `__main__` blocks sitting mid-file above
  the functions they call, and the `sys.path` line for the engine's
  `conda_utils` below the import that needs it — none of the four could run
  at all. Reordered: imports, path, definitions, call at the end.
- `engine/_worker.py` serialises worker spawn-to-connect under one process-wide
  lock. `conda run` on Windows writes its activation through a temp file whose
  name is not unique across concurrent invocations from one parent; parallel
  spawns corrupted each other's activation and every worker but the first died
  naming an environment that exists. Worth offering upstream — it is a
  property of conda, not of this checkout.
- The environment prefix is **`ZMART--`** — the brand here — where upstream
  says `SMART--`: the step metadata, the environment scripts and
  `environment.yml` all name `ZMART--<workflow>--<step>`. The engine's own
  tests keep upstream's `SMART--basic_test--env_a`, being upstream's tests.

- `detect_objects.py` stacks `extra_channel_paths` channel-last into the
  image the feature extractor measures, so intensity features come out per
  colour; segmentation itself still reads the one image it was handed.
- `object_analysis.yaml` turns every extras family on (`extras: [all]`):
  texture, background correction, neighbourhood and morphology all become
  gating axes on the page — and, per the extractor's channelisation, each
  channelised feature is reported per colour like the intensity columns.
- `detect_objects.py` accepts `extra_channel_indices` beside
  `extra_channel_paths`: when the input is one OME-Zarr position rather than
  one file per plane, the other colours are read from the same store by index
  (through `load_plane`) and stacked channel-last exactly like the paths, so
  per-colour features survive the move to zarr input.

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
