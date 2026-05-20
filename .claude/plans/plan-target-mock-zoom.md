# Plan: target-mock zoom — high-res hijack reads from the overview file

**Status**: drafted, pending review.
**Author**: claude (continuation of Plan 2 + the `analysis_image_source`
end-to-end removal).
**Predecessor commits**: `ef4d2a2`, `e827219`, `c419b02`, `d48f73d`,
`ea69d28` on `smart-microscopy`; `dd8cbe9`, `d6c010c` on
`smart-analysis`. Both repos clean.
**Scope**: smart-microscopy only (target-side of the simulator hijack).

---

## Design intent

After Plan 2 phase 1, `cfg.simulate=True` hijacks both overview and
target acquisitions: pixels are swapped under the real LAS X simulator
OME envelope, so the rest of the pipeline behaves like a real run. The
overview side delivers on the operator's "feels like real microscope"
bar — overviews show wide-field tiled `human_mitosis()` content,
different tile to tile, and cellpose runs on it normally.

The target side **does not** deliver on that bar. Empirical evidence
(simulator run `v3-test_076c54`, target-acquisition panels p00000 and
p00001): the "High-res target" panel shows the same wide-field mock
content as the "Overview tile" panel, not a magnified view of the
picked cell.

Two root causes:

1. **Seed collision.** The mock provider `_skimage_human_mitosis` is
   deterministic on `(naming.g, naming.p)`. In `acquire_targets`, the
   target's `Naming` uses `g=int(rid)` (source overview tile's group)
   and `p=i` (index in the picks list, 0-based). For Position 0
   pick #0 this yields `(g=0, p=0)` — **exactly the same seed as the
   overview tile at Position 0**. Same seed → identical pixels in
   both files. Even when seeds *don't* collide, the mock would be a
   different arbitrary crop, never a zoom of the overview around the
   picked cell.
2. **Wrong content model for targets.** A real high-magnification
   acquisition at the picked cell's stage coordinates would show
   that cell filling most of the FOV at a smaller physical area. The
   simulator obediently produces a frame at those coords, but it has
   no concept of "what's actually under the objective" — it returns
   whatever pixel grid the job dictates. Our current target hijack
   then overwrites that with arbitrary mock content. There is no
   path that makes the high-res frame correlate with the cell the
   workflow picked.

The fix is content-driven, not just seed-driven: the target hijack
needs to **read the source overview tile's saved pixels, crop a
window around the cell's centroid sized to match the target job's
FOV, and resample that crop up to the target image's pixel
dimensions**. Then `cellpose` running on the target file sees a
proportional zoom of the same cell the overview detected. The
pixel-to-stage chain through the workflow stays intact (it reads
pixel sizes from job settings, not from file content).

**End state**:
- Per-target hijack content = a magnified crop of the overview tile
  around the picked cell. Cell-shaped feature visible in the centre
  of the target frame.
- Overview hijack unchanged. Still wide-field, still
  `human_mitosis()`-tiled, still deterministic per `(g, p)`.
- `hijack_frame` itself unchanged — the rewrite mechanism is generic.
  Provider is the variable.
- The per-frame `SystemTypeName="SIMULATOR"` allowlist guard
  unchanged. The 2D-only check unchanged. All Plan 2 safety
  properties preserved.

## Geometry (load-bearing)

The math the implementation rests on. Reviewer should scrutinise
this section specifically.

### Pixel-size model: scalar, matching the rest of the pipeline

The full pipeline (TargetRecord, visualize, summary, smart-analysis
engine) treats target pixel size as a **scalar** (`pixel_w_um` only),
not a `(pw, ph)` tuple. LAS X simulator and real STELLARIS both
produce square pixels in practice, so the scalar is correct for all
observed cases. This commit keeps that scalar model end-to-end —
the provider uses one scalar for both axes, persistence stays
scalar, display stays scalar. No split-brain between "provider
is per-axis but everything else is scalar." If non-square pixels
ever become a real case, the symmetric fix is to widen the whole
pipeline in one separate commit — see §"What's NOT in this plan."

### Inputs (already available in `acquire_targets`)

For each pick:
- `pick.centroid_col_row_px = (cx, cy)` — cell centroid in **overview
  pixel coordinates** (`col=x`, `row=y` per visualize convention).
- `pick.source_pixel_size_um = (pw_ov, ph_ov)` — overview pixel size
  (tuple, but for this commit we use only `pw_ov` and assume
  square; same assumption is implicit elsewhere in the pipeline).
- `pick.source_image_size_px = (W_ov, H_ov)` — overview image size
  at detection time.
- `pick.position` — flat tile index `p` of the source overview tile
  (the overview-scan file index, set when the pick was constructed
  in `_picks_from_result`).
- `pick.pick_id[0]` — group `rid` of the source overview tile
  (string-form of the overview's `g`).

From `drv.parse_tile_geometry(get_job_settings(client, cfg.target_job))`
(already called in the loop):
- `target_pixel_size_um` — scalar `float(target_geo["pixel_w_um"])`,
  exactly as the existing code reads it. No new field, no widening.

From the actual saved target file (read inside `hijack_frame` before
the provider is called):
- `saved.shape = (H_tg, W_tg)` — target image's pixel dimensions
  (single-plane 2-D; multi-plane is blocked upstream by the 2-D
  guard in `hijack_frame`).
- `saved.dtype` — target image's dtype.

The provider also reads the source overview's saved canonical file
at the default single-plane indices (`c=0, z=0`, defaulted by
`Naming`). The 2-D-only scope (still enforced by the existing
hijack guard) makes this correct: the only file at that name is
the single saved plane.

### Computation

Target FOV in physical µm. The pixel size is scalar (same value
for both axes — that's the "square pixels" assumption). The image
dimensions are **not** assumed square — a 2048×1024 target frame
has half the height FOV of its width FOV, and the math handles
that cleanly:
```
target_fov_w_um = W_tg * target_pixel_size_um
target_fov_h_um = H_tg * target_pixel_size_um
```

Same FOV expressed in **overview** pixel coordinates (the size of
the crop we extract from the overview file), per-axis from the
per-axis FOVs above:
```
crop_w_ov_px = int(math.floor(target_fov_w_um / pw_ov))
crop_h_ov_px = int(math.floor(target_fov_h_um / pw_ov))
```

`math.floor` (not Python's `round`) avoids banker's-rounding
surprises on exact half-pixel ties: when `crop = 410.5`, floor
gives 410, not 410 *or* 411 depending on parity. Tests use
sizes that avoid half-pixel ties anyway, but the choice is
documented intentionally.

Crop top-left in overview pixels (centred on the cell):
```
x0 = int(math.floor(cx - crop_w_ov_px / 2))
y0 = int(math.floor(cy - crop_h_ov_px / 2))
```

Read the overview file (single-plane canonical name; `c=0, z=0`
defaulted by `Naming`):
```
overview_naming = Naming(
    acquisition_type="overview-scan", hash6=layout.hash6,
    g=int(pick.pick_id[0]), p=int(pick.position),
)
overview = tifffile.imread(layout.data_dir("overview-scan")
                           / build_image_name(overview_naming))
```

Extract the crop, padding with the overview's median intensity for
any area that falls outside the overview's bounds (cell near tile
edge). Padding is silent — it's a normal occurrence for cells
near tile boundaries, not an error condition; a per-tile warning
would be operator-noisy in many-tile runs without giving them
any new actionable information. The
`test_edge_cell_pads_with_median_no_crash` test documents the
behaviour for any contributor inspecting later:
```
pad = int(np.median(overview))
# Clip the requested crop window to the overview's bounds (per-axis,
# since crop width and height may differ for non-square target images):
xs = max(0, x0); ys = max(0, y0)
xe = min(W_ov, x0 + crop_w_ov_px); ye = min(H_ov, y0 + crop_h_ov_px)
# Build a padded crop of the exact requested size in one allocation:
crop = np.full((crop_h_ov_px, crop_w_ov_px), pad, dtype=overview.dtype)
dst_y0 = ys - y0; dst_x0 = xs - x0
crop[dst_y0:dst_y0 + (ye - ys),
     dst_x0:dst_x0 + (xe - xs)] = overview[ys:ye, xs:xe]
```

Resample to target dimensions (zoom up). `anti_aliasing=False`
because we're scaling *up* — anti-aliasing only helps on downscale:
```
from skimage.transform import resize
mock = resize(
    crop, (H_tg, W_tg),
    preserve_range=True, anti_aliasing=False,
)
return mock.astype(saved.dtype)
```

### Zoom-ratio sanity

For a typical run: overview at 10× objective (`pw_ov ≈ 0.65` µm/px),
target at 63× (`pw_tg ≈ 0.13` µm/px) → zoom ≈ 5×. If target is
2048×2048, crop is ~410×410 overview pixels, centred on the cell.
A cellpose-detected cell ~30 px across in overview becomes ~150 px
across in target — matches what a real 10× → 63× swap would show.

## Edge cases

| Case | Behaviour | Rationale |
|------|-----------|-----------|
| Cell near tile edge (crop extends past overview bounds) | Pad with overview's median intensity | A real high-mag swap would still capture data; padding with median (≈ background) is the least misleading analog. Not zero (would show black bars), not mean (skewed by bright cells). |
| Non-square *images* (e.g. 2048×1024 target frame) | Per-axis FOV computation — `target_fov_w_um` and `target_fov_h_um` derived independently from `W_tg` and `H_tg` against the scalar pixel size. The crop is also per-axis (`crop_w_ov_px ≠ crop_h_ov_px` allowed). Image aspect ratio is honoured. | "Square pixel" assumption (the scalar pixel-size model) is **independent** of the image shape; the math must not bake "square image" into a place where only "square pixel" was intended. |
| Non-square *pixels* (`pw ≠ ph` on either side) | **Out of scope for this commit.** The provider, like the rest of the pipeline (TargetRecord, visualize, summary), uses the scalar `pixel_w_um` for both axes. Visible symptom on a future non-square-pixel acquisition would be a stretched target mock — operator-visible. Fix is the deferred widen-everywhere commit (see §"What's NOT in this plan"). | Avoids the patchwork pattern of per-axis math in one layer and scalar everywhere else. |
| Crop rounds to ≤ 1 pixel (degenerate zoom or tiny target FOV) | Warning + clip to min 1 px; `resize` handles 1×1 → N×N | Won't crash, won't silently produce empty content. |
| Overview file missing on disk | `RuntimeError` from `tifffile.imread` propagates as per-tile hijack failure (recorded in `hijack_failures`, loop continues; NOT `NonSimulatorFrameError`) | The guard is structurally about the **target** frame's companion XML — the source overview file being missing is a per-tile data integrity issue, not a safety-allowlist failure. |
| `pick.position is None` (pre-`position` NPZ reload) | `RuntimeError` with message naming the contract | Fresh simulator runs always have `position`. Defensive only; back-compat reload + simulate=True is an unusual combo. |
| Overview file ≠ 2D (multi-plane) | Already blocked by the overview-side 2D check at hijack time; if it ever reaches here, raise `RuntimeError` | Fail-loud rather than silently picking channel 0. |

## Scope (file changes)

- **`workflow/_mockprovider.py`** — add `build_target_provider(*, pick, target_pixel_size_um, layout)` returning a callable matching the existing `(shape, dtype, *, naming) -> ndarray` provider contract. The callable closes over the pick + layout + scalar `target_pixel_size_um` and does the read-crop-resize. Its docstring documents that the `naming` parameter on the returned callable is **ignored** — the provider's content source is entirely determined by the closed-over `pick`, not by the target frame's own naming. Same `(shape, dtype, *, naming)` shape is preserved so the existing `hijack_frame` doesn't need to know whether it has an overview or target provider in hand.

  `get_provider("skimage_human_mitosis")` (the overview path) is unchanged. The two builders are intentionally separate functions because they do structurally different things: the overview provider invents content; the target provider derives it from the overview file. Sharing a name parameter would conflate them.

- **`workflow/target.py`** `acquire_targets`:
  - **Inside the `if cfg.simulate:` branch only** (not at the top of `acquire_targets`): build a per-pick target provider via `build_target_provider(pick=pick, target_pixel_size_um=target_pixel_size_um, layout=ctx.run.layout)` and pass it to `hijack_frame`. The new code lives entirely under the simulate gate — a real-hardware run executes none of it. The `target_pixel_size_um` scalar variable is already populated by the existing `target_geo["pixel_w_um"]` read earlier in the loop; no new geometry parsing.
  - **Drop the shared `provider = get_provider(...)`** at the top of `acquire_targets`. Each pick gets its own provider; the function-level provider is dead code after this commit. Operator-visible behaviour on a non-simulate run is unchanged (the `if cfg.simulate:` gate skips all provider construction).
  - **Add a short tombstone comment** above the per-pick provider construction explaining the lifecycle: "Per-pick provider closes over this pick's centroid + source-tile lineage; building it once at the top of acquire_targets would lose that per-iteration context. Cheap to construct (closures only) so per-iteration cost is negligible."

- **`workflow/_hijack.py`** — **no change**. The rewrite mechanism is generic; provider is the variable. The 2-D-only guard and SystemTypeName allowlist already gate the target frame correctly.

- **Tests** — new `workflow/test/test_target_mock.py`. Each test corresponds to a structural property:

  Provider math:
  - `test_zoom_factor_correct` — known overview pixel size, target pixel size, target shape; assert the crop size in overview pixels equals `floor(target_shape * target_pixel_size / overview_pixel_size)`. Pick sizes that avoid half-pixel ties so banker's-rounding is irrelevant (e.g., overview 0.65 µm/px, target 0.13 µm/px, target shape 200×200 → crop 40×40).
  - `test_centroid_lands_at_target_center` — overview fixture has a single unique bright pixel at an **asymmetric** centroid `(cx=120, cy=50)`. Build a pick at that centroid. Assert the bright feature appears at `(cx_target=100, cy_target=100)` (centre of a 200×200 target) within a 1-pixel tolerance. The asymmetric coordinates fail hard on any `(col, row) ↔ (x, y)` or `(x, y) ↔ (y, x)` swap.
  - `test_output_shape_matches_target` — out shape exactly matches requested target shape.
  - `test_output_dtype_matches_target` — out dtype matches the requested dtype, including the typical LAS X uint16 case.
  - `test_edge_cell_pads_with_median_no_crash` — cell at `(2, 2)` overview pixels; crop extends into negative. Assert no crash, output's edge regions equal the overview's median intensity. Documents the silent-padding behaviour.

  Integration (wiring acquire_targets → build_target_provider → hijack_frame):
  - `test_acquire_targets_uses_per_pick_target_provider_on_simulate` — set up a minimal `acquire_targets` invocation with `cfg.simulate=True` and two picks at different centroids. Spy on `hijack_frame` (or assert via written file content) that two distinct providers fired, each producing content derived from the overview file rather than human_mitosis directly. This is the test that catches "math is right but the loop still calls the wrong provider."
  - `test_acquire_targets_does_not_build_target_provider_when_simulate_is_false` — real-hardware regression test. `cfg.simulate=False`. Patch `build_target_provider` with a sentinel that raises if called. Run a target acquisition. Assert no exception (provider is never built) and no hijack call is made. Pins that the new code is strictly gated to simulate mode.

  Error paths:
  - `test_missing_overview_file_raises_per_tile_not_nsfe` — overview file deleted before target hijack; assert the provider raises `RuntimeError` (or `OSError`/`FileNotFoundError`, which the loop catches as per-tile) — explicitly NOT `NonSimulatorFrameError`. The error path stays per-tile, not run-fatal.
  - `test_pick_without_position_raises_clearly` — `pick.position is None`; assert `RuntimeError` with a message naming the contract ("source overview tile index missing").

- **`workflow/test/test_hijack.py`** — **no change**. Tests there use `_constant_provider(42)` and exercise the rewrite mechanics, not provider content. They stay green.

- **`smart_microscopy_v3.1.ipynb`** — **no change**. Same operator-facing knobs (`simulate=True, mock_image_source="skimage_human_mitosis"`). No new config surface.

## What's NOT in this plan (intentional)

- **No change to the overview hijack.** Wide-field mock content per
  tile is appropriate for an overview; that's what a real overview
  looks like compared to a target.
- **No change to `hijack_frame`.** The mechanism (read-validate-mock-
  write) is generic; only the content source varies. Touching the
  mechanism for this would conflate concerns.
- **No change to the safety guard.** Per-frame `SystemTypeName=="SIMULATOR"`
  allowlist remains the only thing standing between simulate mode and
  a real-hardware accident.
- **No per-axis pixel-size widening of TargetRecord / visualize /
  summary.** A prior reviewer raised this: if the provider does per-
  axis math, the persisted/display layer should follow. The fix is
  to widen the *whole* pipeline (TargetRecord becomes a tuple, every
  call site updates), in one separate commit. This commit instead
  keeps the scalar model end-to-end — provider, record, display —
  matching what the pipeline already does and what LAS X actually
  produces. The "non-square pixels widen-everywhere" commit is
  deferred until a real (not theoretical) case appears.
- **No caching of overview file reads.** The straightforward
  implementation reads the source overview tile once per pick from
  that tile. If profiling shows this is a real bottleneck (network
  share, many picks per tile), a `tile_id → ndarray` cache slots in
  cleanly later. Premature optimisation now would muddy the diff.
- **No multi-plane / multi-channel support.** Out of scope (the 2D
  check in `hijack_frame` already blocks multi-plane saved files; a
  multi-plane overview would already have failed the overview hijack
  before we got here).
- **No structural test analog to the AST single-trace test.** The
  pattern this plan introduces (closure-based per-iteration provider
  injection) is small and localised; the existing hijack tests +
  the new target-mock tests (including the real-hardware regression
  test) cover its surface adequately.

## Risks

- **`skimage.transform.resize` startup cost.** The first import of
  `skimage.transform` pulls scipy + several heavy submodules. Lazy-
  import inside the provider closure (not at module top of
  `_mockprovider.py`) so the cost is only paid in simulate mode.
- **Square-pixel assumption.** This commit uses a scalar
  `target_pixel_size_um` for both axes, matching the rest of the
  pipeline (TargetRecord, visualize, summary). LAS X simulator and
  real STELLARIS both produce square pixels. If non-square pixels
  ever appear, the symptom is a stretched target mock — visible
  to the operator. The fix is the deferred widen-everywhere commit
  (see §"What's NOT in this plan"), not a localised provider tweak.
- **`cx, cy` vs `cy, cx` confusion.** `centroid_col_row_px = (col, row)
  = (x, y)`. NumPy indexing is `[row, col] = [y, x]`. The crop math
  must use `cy` for the row axis and `cx` for the column axis.
  `test_centroid_lands_at_target_center` uses asymmetric
  `(cx=120, cy=50)` so any `(x, y) ↔ (row, col)` swap fails hard.
- **`pick.position` semantics.** Confirmed via audit:
  `_picks_from_result` sets `position = result.get("input", {}).get("naming_p")`
  which `run_overview` sets to `i` (the snake-order loop index, =
  the overview tile's `naming.p`). So `pick.position` is exactly the
  overview tile's flat `p` index. The plan depends on this; if it
  ever changes, every target hijack breaks loudly (overview file
  lookup fails).
- **Per-frame read cost.** Reading the overview file (e.g. 2K×2K
  uint16 = 8 MB) per pick is fine on local disk, possibly slow on a
  network share. Acceptable for simulator dry runs; the existence of
  this concern is itself the cache argument noted above.
- **`if cfg.simulate:` gate discipline.** The real-hardware
  regression test pins that none of the new code runs on a
  non-simulate run. If the gate is accidentally dropped (e.g. a
  refactor moves the per-pick provider construction outside the
  `if` block), the test catches it.

## Test strategy (TDD)

1. Write all the new tests in `test_target_mock.py` first, with
   `_make_overview_fixture` / `_make_pick_at` / `_make_layout` helpers
   matching the existing patterns in `test_hijack.py`. Run → all RED
   (function doesn't exist yet, or returns wrong shape/content).
2. Implement `build_target_provider` in `_mockprovider.py`. Run →
   each test goes GREEN as the corresponding behaviour lands.
3. Wire `acquire_targets` to use it per-pick. Run the full smart-
   microscopy suite → must stay at 213 baseline + 9 new target-mock
   tests (5 math/edge + 2 integration + 2 error path) = 222 expected;
   verify exact count after.
4. Visual confirmation: re-run v3.1 in simulate mode, inspect
   `target-acquisition/logs/*_live.png`. The "High-res target" panel
   should show a magnified view of the cell the centre crop
   identified. Sanity check: a side-by-side comparison of
   `_p00000_*` and `_p00001_*` should show *different* cells (each
   target zooms into its own picked cell), not the identical
   wide-field content of the current bug.

## Order of operations

1. Write the plan (this file).
2. Reviewer pass.
3. Fold reviewer findings into the plan; revise.
4. TDD-style implementation: tests → RED, implementation → GREEN.
5. One commit on `try/all-four`:
   `feat(target-mock): high-res hijack reads cropped + zoomed overview`.
6. Operator visual smoke: re-run v3.1 simulator mode end-to-end,
   confirm the target panels show magnified cells.
7. If anything looks off in the smoke: stop, surface, decide. Don't
   ship a commit that the operator hasn't visually confirmed for a
   feature whose whole point is visual realism.

## Reference: what stays after the cut

After the commit, `grep -r "skimage_human_mitosis" workflow/` returns
only `_mockprovider.py` (the overview provider) and tests. The target
provider does not name `human_mitosis` — it reads whatever is in the
overview file, which gives it forward-compat with any future overview
mock.

The structural pins from prior commits all still hold:
- AST single-trace test on `analysis_image_source` — still passes
  (this commit doesn't touch the field).
- 2D-only check in `hijack_frame` — still gates target frames.
- `SystemTypeName="SIMULATOR"` guard — still gates target frames.
- Per-frame `NonSimulatorFrameError` propagation — unchanged.
