# Documentation Index

Durable documentation for the microscope-facing code. Dated working notes from
past sessions live in git history, not in this folder.

## Design and rationale

- [WHY_HYBRID_READERS_20260605.md](WHY_HYBRID_READERS_20260605.md) — why LAS X state
  is read through three reader families (`api`, `log`, `hybrid`) and why command
  confirmation races admissible evidence instead of trusting a single source.
- [NATIVE_AUTOSAVE_LOG_DEFAULTS_USEFUL_FINDINGS_SUMMARY.md](NATIVE_AUTOSAVE_LOG_DEFAULTS_USEFUL_FINDINGS_SUMMARY.md)
  — measured LAS X native-autosave and log behavior that the driver defaults rely on.

## Validation evidence

- [READER_VALIDATION_SIMULATOR_20260611.md](READER_VALIDATION_SIMULATOR_20260611.md)
  — all three reader modes on the LAS X simulator.
- [READER_VALIDATION_REAL_SCOPE_20260611.md](READER_VALIDATION_REAL_SCOPE_20260611.md)
  — the same matrix on the real Leica STELLARIS.
- [READER_VALIDATION_REAL_SCOPE_20260611_HYBRID_MATRIX.md](READER_VALIDATION_REAL_SCOPE_20260611_HYBRID_MATRIX.md)
  — the 10-position XY acceptance record: hybrid passes with zero failures where
  api-only and log-only each fail differently.

Curated raw measurement records (JSONL) referenced by these reports are tracked in
`../driver/vendor/leica/navigator_expert/tests/hardware/`; all other validator output
is git-ignored runtime data.

## Setup

- [MINIMAL_LASX_PYTHON_ENV.md](MINIMAL_LASX_PYTHON_ENV.md) — the Python environment
  needed to talk to LAS X.

## Reviews and plans

- [CONFERENCE_READINESS_REVIEW_20260612.md](CONFERENCE_READINESS_REVIEW_20260612.md)
  — branch readiness review with verification runs.
- [FABLE5_TRYOUT_SYNTHESIS_20260612.md](FABLE5_TRYOUT_SYNTHESIS_20260612.md) —
  synthesized findings and the cleanup/publication plan.
- [TEST_CLEANUP_REFACTOR_PLAN_20260612.md](TEST_CLEANUP_REFACTOR_PLAN_20260612.md) —
  planned test-suite reorganization (not yet executed).
- [CALIBRATION_REFACTOR_PLAN.md](CALIBRATION_REFACTOR_PLAN.md) — calibration package
  design reference.

## Standards

- [CONVENTIONS.md](CONVENTIONS.md) — coding and review conventions for this repo.
