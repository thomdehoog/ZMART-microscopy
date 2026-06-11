# SMART — adaptive feedback microscopy

SMART picks cells from a low-magnification overview and re-images each one at
high magnification across an objective switch, fully unattended. You scan a
well at 10x, the pipeline segments the cells, maps each one through the
objective-change geometry, and drives the microscope back to acquire every
target at 20x (or higher). Segmentation is Cellpose; the optical-frame
transforms come from a measured calibration; the microscope itself is a Leica
STELLARIS driven through LAS X.

The hard part is not the imaging — it is trusting what the instrument reports
back between steps. This repository is built around making each automated move
**verifiable**: every command confirms its own effect before the workflow
continues, and the state readers are designed to fail closed rather than act on
a stale value.

## Why this exists

Smart/adaptive microscopy is usually bespoke scripting glued to a vendor API.
That breaks the moment the API lags, hangs on a modal dialog, or hands back a
confidently-wrong value — all of which the Leica CAM API does in practice. SMART
treats the instrument as an unreliable narrator: commands are wrapped with retry
and readback-confirmation, machine-specific tuning lives in profiles rather than
scattered constants, and operator notebooks stay thin (markdown plus a few-line
call) so the logic is reviewable in the package, not buried in a cell.

## Repository layout

- **`driver/`** — microscope drivers. Currently `vendor/leica/navigator_expert/`
  (Leica STELLARIS via LAS X). Every command returns a result dict with
  `success`, `confirmed`, `message`, `timing`, and `logs`. Full API reference:
  [`driver/vendor/leica/navigator_expert/README.md`](driver/vendor/leica/navigator_expert/README.md).
- **`calibration/`** — measured optical state: image-to-stage rotation for the
  reference objective, objective translations, and backlash. Operator notebooks
  adopt their results into `current/calibration.json`.
- **`limits/`** — configured Leica stage envelopes. `defaults.json` is the
  physical envelope and safe default; `current.json` is the last active working
  envelope written by target acquisition.
- **`workflows/`** — operator-facing automation built on the driver and
  calibration. `target_acquisition/` is the main pipeline; `examples/` are short
  cookbook scripts for on-scope checks.
- **`shared/`** — vendor-neutral primitives: `algorithms/` (focus scoring,
  registration) and `output_layout/` (canonical run-directory layout).
- **`docs/`** — design plans, measured-result write-ups, and cleanup history.

## State readers — the design idea worth knowing

LAS X exposes its state two ways, and **each one is wrong in places the other is
right**:

- the **CAM API** is fast and fresh for actively-queried values (XY, scan
  status), but its selected-job readback can stay stale for 15 s+ on this LAS X
  version, and it can hang on a modal dialog;
- the **LAS X log** never hangs (it is a file read) and reflects job switches in
  ~0.2 s, but it is empty on an idle scope and cannot be polled to freshness for
  passive state.

So `driver/.../state_readers/` routes each read across both backends
(profile-controlled: `api`, `log`, or `both` — all default `api`, never a stale
guess). On top of that, `state_readers/change_wait.py` answers the question a
feedback workflow actually asks after a command — *did the state visibly
change?* — by alternating API and log reads until one source differs from its
own pre-command baseline, or a timeout returns `unconfirmed`. It is
source-agnostic by construction: a stale source keeps reporting its old value
and simply never wins, and every API/log disagreement is reported, not hidden.
Measured behavior is written up in
[`docs/READER_VALIDATION_SIMULATOR_20260611.md`](docs/READER_VALIDATION_SIMULATOR_20260611.md).

## Getting started

1. Activate the conda env: `lasxapi_extended` (Cellpose-dependent steps use
   `dino3_test`).
2. Run the calibration notebooks in
   `calibration/vendor/leica/navigator_expert/notebooks/`: image-to-stage first,
   then objective-pair for each supported objective pair. Adopt each result into
   `current/calibration.json`.
3. Run the target-acquisition notebook:
   `workflows/vendor/leica/navigator_expert/target_acquisition/smart_microscopy_v3.2.ipynb`.

New to a STELLARIS/LAS X setup? Point LAS X at its **simulator** first and run
`driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py --yes`
— it exercises the full command surface (reversible writes only by default) and
prints a pass/fail line per check.

## Conventions

- Operator notebooks stay thin. Logic lives in the package beside the notebook.
- Machine-specific tuning (tolerances, timeouts, poll intervals) lives in
  `core/profiles.py`, not in workflow code.
- Runtime artifacts write to operator-selected output roots under
  `media_path/smart/…`. They are not source files and must not be committed.
- See [`CLAUDE.md`](CLAUDE.md) for repository-wide code-style guidance.
