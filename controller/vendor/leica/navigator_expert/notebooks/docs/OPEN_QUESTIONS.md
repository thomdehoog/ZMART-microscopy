# Open questions — smart-microscopy v3

Tracked open questions about workflow behavior that the code does not
yet answer. Each entry names the symptom, what would close it, and the
cheapest path to evidence.

---

## Bottom-of-tile bias — open since session 1

**Symptom (operator observation, paraphrased)**: in Step 4 cells are
picked that appear to be only in the bottom of the tile; this is
suspicious.

### 1. Definition of "bottom"

"Bottom" could mean any of three things, which are *not* equivalent:

- High image-row index (near `ny`, with row 0 at the top of the image
  in matplotlib `origin='upper'` convention).
- High stage-y coordinate in microns (sign depends on calibration).
- Visually low in the displayed figure (which is row-axis-up after
  `ax.invert_yaxis()` in the scan-field renderer).

The diagnostic plot has to match the operator's intended meaning.

### 2. Step where the bias appears

- Is it already visible in **Step 3** segmentation overlays (i.e. the
  raw cellpose detection distribution per tile), or
- Only after **Step 4** selection / thresholding (i.e. the
  segmentation is uniform but the *selection* pipeline favors the
  bottom)?

These point at different root causes:
- Step 3 bias → cellpose model bias, illumination gradient,
  vignetting, autofocus z-offset, sample tilt.
- Step 4 bias → threshold filter, sampling, dedup, display axis flip,
  per-tile sparseness handling.

### 3. Reproducibility

Can the bias be reproduced from a **saved `overview-scan/`
directory**, or does it require a new acquisition?

`load_overview_result(analysis_dir)` reconstructs `OverviewResult`
from on-disk `.npz` + `overview_meta.json`. If a representative scan
exists, the diagnostic can be run offline without microscope time. If
not, an acquisition is needed.

### 4. Data required to close

Closing this open question requires an **acquired** `overview-scan`
run on a non-empty biological sample. An operator can produce this on
demand; this is not a passive "wait for circumstances" deferral.

Available data in `media_path/smart` (as of 2026-05-13,
`Z:\zmbstaff\10374\Temporary_Data\smart`) is either:

- **Acquired runs with zero detections** — not representative for a
  centroid-row histogram (the bias question presupposes detections).
- **Mock runs** with `analysis_image_source="skimage_human_mitosis"` —
  not the real cellpose / acquired image pipeline; would answer the
  wrong question.

### 5. Cheapest next diagnostic (once representative data exists)

Run these in order; stop at the first one that explains the symptom.

1. **Sanity-check `overview_meta.json`** for the run:
   - `completed: true`.
   - `tile_acquire_failures`, `engine_failures`, `npz_save_failures`
     are empty or minimal.

2. **Filter to representative tiles**: in `overview-scan/analysis/*.npz`,
   keep tiles where `analysis_image_source == "acquired"` and
   `masks.max() > 0`.

3. **All-detection y-histogram** (cheapest, ~20 lines): for each
   selected tile npz, compute `regionprops` over `masks` and plot a
   1D histogram of `prop.centroid[0]` (image-row coordinate). If
   flat, segmentation is unbiased — proceed to step 4. If peaked
   high (high row index), the bias is upstream of selection
   (cellpose / illumination / focus).

4. **Selected-cell y-histogram**: read the selected picks from
   `run_summary.json` (or the in-process `SelectionResult`) and
   compare the distribution of `centroid_col_row_px[1]` against the
   all-detection distribution from step 3. If all-detection is flat
   but selected is bottom-skewed, the bias is in the selection
   pipeline (threshold, sampling, dedup, border filter, display).

The all-vs-selected comparison is the load-bearing measurement: it
separates **detection bias** (out of `selection.py`'s scope) from
**selection bias** (in scope).

### 6. Scope statement

Bundle C (`fix/selection-correctness`) addresses **deterministic
correctness bugs** in `selection.py`:

- NaN thresholds from `np.median([])` when all cells are near-border.
- Sparse-gate population mismatch (used `n_total`, computed median on
  eligible subset).
- `n_qualifying == 0` reachable from `MODE_SPARSE`.
- Per-tile counter using raw counts when the global gate uses
  eligible counts.
- Annotation string out of sync with the border filter.
- Missing validation of `border_margin_px < 0` and degenerate
  `source_image_size_px`.

Bundle C **does not** address the bottom-of-tile bias, because that
question needs **data, not code changes**. This file makes the
deferral explicit rather than silent: the question is tracked here,
to be closed in a follow-up once representative acquired data exists.
