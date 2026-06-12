# SMART Microscopy

Implementations for smart microscopy: microscope integrations that put the instrument
under programmatic control, and workflows that use that control to analyze data and
make acquisition decisions during an experiment rather than after it.

The repository has two roots:

- `microscopes/` — everything that talks to a microscope: vendor drivers, calibration,
  safety limits, and shared microscope-facing utilities.
- `workflows/` — the smart-microscopy workflows built on that control. The first (and
  currently only) one is `workflows/target_acquisition/`: acquire an overview, select
  targets by analysis, re-acquire them at high resolution.

```text
microscopes/
  driver/vendor/leica/navigator_expert/   Leica LAS X driver (commands, state readers,
                                          scan fields, acquisition, stage)
  calibration/vendor/leica/...            objective-pair and image-to-stage calibration
  limits/                                 stage safety envelopes
  shared/                                 focus/registration algorithms, output naming
  microscope_agnostic_layer/              reserved for cross-vendor abstractions
  docs/                                   design notes and validation reports (see index)
workflows/
  target_acquisition/                     operator notebook + pipeline + tests
```

## Status and scope

The **Leica Navigator Expert driver is the production-tested path**: it runs against
the LAS X simulator and a real Leica STELLARIS, and its behavior is backed by committed
validation evidence (below). The microscope-agnostic layer is intentionally empty —
code moves there only once it is genuinely useful across vendors.

The repository is not yet pip-installable; imports are wired through small
`_bootstrap.py` shims next to the notebooks and pipelines.

## Reading microscope state: api / log / hybrid

LAS X state can be read through three reader families:

- `api` — the CAM/PyAPI readback;
- `log` — a passive mirror built from LAS X log files;
- `hybrid` — both, raced per confirmation, where the **first admissible evidence
  wins** (a stale API readback that already showed the target before the command
  cannot confirm that command).

Hybrid is the default for selected-job confirmation because measurement showed each
single source failing differently: on the real scope's 10-position XY validation,
hybrid passed with zero failures while api-only and log-only each failed in
environment-specific ways. The full matrices are in
[`microscopes/docs/`](microscopes/docs/README.md):

- [simulator validation](microscopes/docs/READER_VALIDATION_SIMULATOR_20260611.md)
- [real-scope validation](microscopes/docs/READER_VALIDATION_REAL_SCOPE_20260611.md)
- [real-scope 10-XY hybrid matrix](microscopes/docs/READER_VALIDATION_REAL_SCOPE_20260611_HYBRID_MATRIX.md)
- [design rationale](microscopes/docs/WHY_HYBRID_READERS_20260605.md)

## Getting started

1. Set up the Python environment that can talk to LAS X — see
   [`microscopes/docs/MINIMAL_LASX_PYTHON_ENV.md`](microscopes/docs/MINIMAL_LASX_PYTHON_ENV.md).
2. Calibrate the rig with the notebooks in
   `microscopes/calibration/vendor/leica/navigator_expert/notebooks/`
   (image-to-stage orientation, then the objective pair).
3. Run a workflow — e.g. target acquisition from its operator notebook
   `workflows/target_acquisition/smart_microscopy_v3.2.ipynb`: markdown steps with
   thin calls into `workflows/target_acquisition/pipeline/`.

## Testing

The offline suite needs no microscope and no LAS X installation:

```powershell
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit
python -m pytest -q workflows/target_acquisition/tests
python -m pytest -q microscopes/calibration/vendor/leica/navigator_expert/tests microscopes/shared/output_layout/tests
```

Live validation against the simulator or a real microscope is explicit and
safe-by-default — nothing moves hardware without opt-in flags:

```powershell
python microscopes/driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py --yes --allow-xy --allow-z --allow-objective --allow-acquire
```

Omit any `--allow-*` flag to keep that subsystem untouched; without `--yes` the
validator asks interactively before live writes, and `--read-only` skips writes
entirely. Validator runs write JSONL records; the curated evidence referenced by the
validation reports is tracked, all other runtime output is git-ignored.

## Documentation

Design notes, validation reports, and active plans are indexed in
[`microscopes/docs/README.md`](microscopes/docs/README.md).
