# ZMART Analysis

The party that reads pixels and returns numbers.

ZMART has three: the **instrument** moves and captures, **this** measures what
was captured, and the **page** decides what to do about it. Nothing here knows
why it was asked, and nothing here moves a stage. See
`docs/design/what-runs-where.md` for the rule and where the line falls.

## The two workflows

**`workflows/focus/`** — sharpness of every plane in a z-stack, and the height
it peaks at. Given an OME-Zarr position it needs no heights passed in: the
store records its own z spacing and origin. The result is a trace and a
decision — a score per z for both metrics, and one chosen height — plus the
settings it was scored with, because a curve is only readable beside them. Two metrics, both always scored: `brenner` (gradient-based) and
`dct` (entropy-based, from `scipy.fft.dctn`). Each carries its own curve and
its own peak, so the operator window can chart one against the other and show
where each would have landed. The peak is refined between planes with a
parabola, and the first and last `skip_ends` planes may not win it — the ends
of a drive carry artefacts, and an artefact is a hard edge, which is exactly
what a sharpness metric rewards. They are still scored and still returned; they
just cannot be chosen.

**`workflows/object_analysis/`** — cellpose detection, then per-object
features. `detect_objects` takes `channels` and `channel_axis` along with the
cellprob/flow thresholds and size filters; `extract_classical_features` wraps
the shared `_features.py`, which computes shape, per-channel intensity, local
and global background, neighbourhoods, gradients, statistical texture, LBP,
Fourier and grey-level run-length features as opt-in groups;
`build_object_table` assembles the table. `border_margin_px` rejects objects
within a band of each tile edge: tiles overlap, so an object near an edge is
very likely to appear again in the neighbour, and a margin keeps it once
without either tile knowing the other exists.

Every detection parameter can be set in the pipeline **or** overridden per
submission, so the operator page can tune detection on one position without
registering a pipeline of its own.

Two pipelines sit in `object_analysis/`: `object_analysis.yaml` is detection
plus features plus the table, and is what `load_analysis_engine` registers;
`object_detection.yaml` stops after detection and writes only the checkpoint.

## Where this came from

Vendored from **smart-analysis**, branch `v4-engine`, at commit
`a760858` ("Fix Windows worker parent heartbeat", 2026-07-11).

    https://github.com/thomdehoog/smart-analysis

This is a **subset, copied** — not a subtree and not a submodule, so there is
no automatic way to re-sync it. Taken:

    engine/                     the whole engine and its tests
    workflows/_*.py             the shared helpers
    workflows/object_analysis/  detection, features, object table
    conftest.py                 the test fixtures
    LICENSE

`workflows/_image_io.py` and its tests come from a **different branch**,
`claude/v4-branch-wweiv5`, where they sit at
`workflows/rare_event_selection/steps/image_io.py`. That branch is a small
offshoot with no `Engine` class, so only the reader was taken. It is the one
file here whose upstream is not `v4-engine`.

Left behind: `basic_test/`, `cell_analysis/`, `rare_event_selection/`,
`target_discovery/`, and the repo's own packaging. Upstream's
`target_acquisition/` (`segment_tile` plus `pick_targets`) was taken and then
removed: `object_analysis` supersedes it, and carrying both meant two answers
to the same question.

`workflows/focus/` is **not** from upstream. It was written here, and has no
counterpart in smart-analysis.

## Where results are written

    <acquisition>/
        data/       the images a driver wrote
        vendor/     the instrument's own metadata
        analysis/   everything made from the pixels

`workflows/_output.py` is the one place that says so. A step given no
`output_dir` files its results in the `analysis` folder beside the `data` the
image came from; an image kept outside an acquisition has no such place and
writes nothing unless the caller names one.

## Changes made to the vendored code

Kept to the minimum, so a later re-sync stays cheap.

- `conftest.py` gained a `pytest_configure` registering the markers. Upstream
  declares them in its `pyproject.toml`, which was not taken; ZMART has no
  repo-wide pytest configuration and should not grow one just for this.
- `object_analysis/tests/test_object_analysis.py` skips its handoff test when
  `target_discovery/` is absent, rather than failing on a file this checkout
  deliberately does not have.
- `object_analysis/steps/detect_objects.py` derives `output_dir` from the
  image when the caller names none, instead of writing nothing. Upstream had
  no acquisition layout to derive it from; ZMART does.
- `_segmentation.py` reads through `_image_io` rather than calling
  `tifffile.imread`, so a position is segmented the same whether it was
  written as OME-TIFF or OME-Zarr. `segment_tiff` became `segment_position`,
  since the old name stopped being true.
- `_segmentation.py` gained `filter_masks_by_border`, and
  `_detection_checkpoint.py` gained `border_filter_params`, for the overlap
  guard. `segmentation_params` now takes the cellpose tuning values from the
  submission as well as the pipeline.
- `load_detected_objects.py` and `run_pipeline.py` read through the same
  contract. The masks they load are this workflow's own output and stay a
  plain TIFF.

Nothing in `engine/` was modified.

Written here, with no upstream counterpart: `workflows/focus/` and
`workflows/_output.py`.

## Running the tests

    python -m pytest zmart_analysis

The engine uses relative imports throughout, so it works as a subpackage with
no path setup: `from zmart_analysis.engine import Engine`. The vendored tests
import it as top-level `engine`, which `conftest.py` arranges by putting this
directory on `sys.path` — that is upstream's own arrangement, left alone.

Tests needing a runtime that is not installed skip themselves: `cellpose` and
`deep` probe for their runtime in a subprocess first, and `conda_env` and
`cluster` need conda environments built by the workflows' `environments/`
scripts.

**On this machine, run them from `dino3_test`.** In `lasxapi_extended`, torch
fails to load `fbgemm.dll` in-process; the cellpose probe runs in a subprocess
and so passes, and the test then fails on the in-process import.

    C:/ProgramData/MinicondaZMB/envs/dino3_test/python.exe -m pytest zmart_analysis

## One contract for both formats

`_image_io.load_plane(source, level, t, c, z)` returns one 2D plane and a
metadata dict, from an OME-Zarr position (via ngio, NGFF 0.4 and 0.5) or an
OME-TIFF (via tifffile and ome-types), and nothing above it knows which it
was. `load_channels` is the same read repeated over up to three channels, for
a segmenter. Reads are lazy in both formats, so a position costs the planes
asked for rather than its whole TCZYX array.

Two things it refuses rather than guesses, and both are right: a channel-last
`(H, W, 3)` image, which is RGB samples to a TIFF reader and cannot be told
from three channels; and a focus stack with no `z` among its axes, because
which axis is depth is not a thing to infer.

**`tifffile` must be 2026.6.1 or newer.** Older versions import a name that
zarr 3.3 moved, and every read fails with a misleading
`zarr 3.3.0 < 3 is not supported`. The floor is pinned in both workflows'
`setup_env.py` and in CI.

## Still owed

The rest of `claude/v4-branch-wweiv5` is not here: handling stores written by
other tools, and the rename. Those touch an `engine/engine.py` that does not
exist on this lineage, so they are a port rather than a cherry-pick.

Nothing has yet run against a real ZMART acquisition — every store tested so
far is synthetic or a skimage sample.
