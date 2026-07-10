# Review: v4 target-acquisition hardware proof (branch vs main + commit 2230501)

Response to `v4_notebook_hardware_proof_forFable.md`. Scope: the whole
`claude/leica-config-loading-review-ammwaz` branch against `origin/main`, with the
hardening commit `2230501` ("Harden v4 hardware acquisition workflow") inspected
separately. Beyond the requested scope, anything else worth mentioning is included.

Deviating from the prompt's "do not implement fixes" on the maintainer's explicit
instruction, every finding below marked **FIXED** was implemented, tested, and pushed
in the follow-up commit on this branch. Findings are ordered by severity.

Verification baseline before fixes: `git diff --check` clean; notebook JSON valid;
`pytest zmart_controller/tests workflows/target_acquisition/tests
navigator_expert/tests/unit/test_zmart_adapter.py` → 252 passed, 3 skipped
(network-dependent scikit-image data fetches); ruff clean on all changed files.

---

## Findings

### 1. major — the limits preflight accepted a machine that never measured limits — FIXED

`zmart_microscopy_v4.ipynb`, jobs cell (3a). The preflight raised only on
`not limits or limits.get("is_fallback")`. On a freshly seeded machine the config
ladder copies the *bundled defaults* into ProgramData and the handshake resolves them
as the machine file: `describe()` returns `source: "defaults", is_fallback: False`
(verified against a live mock-CAM connect earlier in this session). The notebook's
stated guarantee — "refuses to continue when machine-specific stage limits are not
active" — was therefore not met exactly on the machines that need it most (first run
after install), where the governing envelope is the full-travel default, not a
measured one.

Why tests missed it: no test connects on a fresh ProgramData root and then runs the
notebook's preflight expression.

Fix applied: the cell now also requires `limits.get("source") == "machine"` and names
the notebook that publishes measured limits.

### 2. major — a click queued during a long run started a second hardware run — FIXED

`workflow/_acquisition_widget.py` (`_on_acquire_clicked`),
`workflow/_focus_widget.py` (`_on_measure_clicked`). While an acquisition or focus
run holds the kernel, extra button clicks queue as ipympl comm messages and are
delivered the instant the callback returns. The `_busy` flag cannot catch them —
callbacks are serialized, so `_busy` is always False again by the time the queued
click runs — and a stray double-click would silently acquire a second random batch
(or re-drive the stage through every focus point).

Why tests missed it: Agg tests invoke handlers synchronously; the queue only exists
under a live ipympl kernel.

Fix applied: both handlers ignore clicks arriving within 2 s of the previous run's
completion (monotonic clock) and say so on the figure. Programmatic
`acquire()`/`measure()` are not debounced.

### 3. minor — a failed connect could leak the analysis engine — FIXED

Setup cell: in the failure path, `zmart_controller.disconnect()` ran before
`engine.shutdown()`; a disconnect that itself raises would skip the shutdown and leave
the Cellpose worker alive. Fix applied: the disconnect is wrapped so the engine
shutdown runs in a `finally`.

### 4. minor — a broken old engine blocked every setup re-run — FIXED

Setup cell: re-running setup called `engine.shutdown()` on the previous engine
unguarded; if that shutdown raises, the cell aborts before creating the new engine —
and every subsequent re-run hits the same corpse. Fix applied: the old-engine shutdown
is best-effort with a printed warning.

### 5. minor — the hardware validator now failed on a template without focus points — FIXED

`2230501` changed `zmart_adapter/procedures.py::focus_points` to return `[]` for a
template with no focus points (previously it raised, which the validator's
skip-on-missing wrapper translated into SKIP). The validator's follow-up comparison
"at least one focus point" then FAILed on hardware whenever the operator simply had
not placed focus points — a legitimate state the v4 notebook explicitly supports.
Fix applied: `tests/hardware/validate_zmart_adapter.py` treats an empty list as a
SKIP with a plain-language reason.

### 6. worth mentioning — no offline test can validate the smart-analysis v4 contract

`2230501` rewrote the discovery payload: `source_pixel_size_um` became a 2-tuple,
`source_image_size_px` swapped to (width, height), `image_to_stage` became the unit
matrix (stage-aligned images), `tile_id` became `("overview", 0, index)`, and result
handling now consumes `status["failed"]`/`failures`. Every one of these mirrors an
external contract in `smart-analysis@v4-engine` that is not reachable from this
review environment (repository access was declined), and the offline fake engine
would pass regardless of whether the real one does. The commit's own tests pin the
payload shape, which guards against *regression* but not against a *mismatch*.
Residual risk: run one registration-plus-preflight against the real
`v4-engine` checkout before the hardware session; `preflight_analysis_engine` will
surface a mismatch before any stage move, which is the right failure point.

### 7. nit — `record_channel_paths`' channel fallback is positional

`workflow/_records.py`: for legacy single-`images` records the channel index falls
back to the enumeration ordinal. Harmless today (the Leica adapter always sends real
`PlaneIndex` keys, verified in `acquisition/product.py` / `save.py`), but a future
driver emitting multiple unindexed paths is already rejected loudly, which is the
right behavior. No change.

---

## Verified correct (with the reasoning that convinced me)

- **Planes manifest** (`zmart_adapter.py::acquire`): keys of `saved.image_paths` are
  frozen, ordered `PlaneIndex(t, z, c)` dataclasses, so the manifest is faithful and
  deterministically sorted; multi-z/multi-t records are rejected by
  `record_channel_paths` before any workflow step misreads them as channels.
- **Centroid → stage trace**: Cellpose centroid (col, row) → `overview_pixel_to_frame`
  (col→x, row→y, µm via isotropic pixel size, centred on the tile's frame position)
  → `capture_positions` → `Session.set_xyz` → adapter frame math (origin + objective
  translation + both-leg preflight) → gated `move_xy`. Signs and axis order are
  consistent with the driver's stage-aligned saves; the same convention renders the
  overview mosaic, and synthetic end-to-end tests (gallery pairing, calibration check)
  recover injected ground-truth offsets sign-correct.
- **No successful-looking summary without acquisition**: `gallery.picked/records`
  commit only after `acquire_targets` returns; the summary cell refuses when
  `gallery.records` is empty; a failed acquisition leaves both empty (pinned by test).
- **Gate coverage**: every stage move in the workflow goes through `Session.set_xyz`
  or the adapter's acquire path; no widget or workflow function calls driver motion
  directly (checked by grep across `workflows/target_acquisition/workflow/`).
- **Controller tests cannot connect to Leica by accident**: `test_layer` selects the
  mock by vendor; the workflow guard test restores the registry it touches.
- **Cross-suite pollution**: controller + workflow + adapter suites pass in one
  pytest process (252 green before fixes, 261 after).
- **Setup-cell lifecycle**: engine loads and preflights *before* the CAM connection,
  so an absent/wrong smart-analysis checkout fails before the microscope is touched;
  re-runs tear down both resources; the final cell shuts the engine down and
  disconnects in a `finally`.
- **Overview viewer memory**: auto-downsample keeps the display under a ~20 M-pixel
  budget without touching extents, acquisition files, or analysis inputs.

## Residual risks that only hardware can retire

1. Physical z additivity of z-wide + z-galvo on a real objective (pre-existing note in
   the adapter docstring; one manual pass).
2. The real LAS X native-AutoSave layout on the microscope PC (offline suites fake the
   `.lcf`/project structure).
3. The smart-analysis v4 contract (finding 6) and the Cellpose conda environment named
   in `segment_tile.METADATA` existing on the scope workstation.
4. ipympl event behaviour under the scope PC's JupyterLab (the 2 s debounce is a
   defense, not a proof; watch for double-fires on slow canvases).
5. The registration sign convention on the real optical path — the calibration check
   (added after this review) recovers injected errors sign-correct on synthetic data;
   one hardware run with a deliberately mis-set translation would pin it physically.

## Also added on maintainer instruction (same follow-up commit)

- **XY-calibration validation run** (`workflow/_calibration_check.py`, notebook
  section 5b): 12 sites on a ~1000 µm ring, objective-1 pass then objective-2 pass at
  the same frame positions, voting registration per pair; reports the systematic
  calibration offset (mean) separated from stage repeatability (rms scatter), with a
  JSON + plot in the run root. Ground-truth synthetic test recovers an injected
  (+3, −2) µm error, sign included; featureless windows are refused rather than
  reported as perfect.
- **Backlash takeup is now three back-and-forth passes** (driver
  `motion/movement.py::correct_backlash`, default `passes=3`), each return leg
  approaching from −X −Y.
