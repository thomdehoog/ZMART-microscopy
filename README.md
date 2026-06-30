# SMART Microscopy

This repository contains implementations for smart microscopy: microscope
integrations that put an instrument under programmatic control, and workflows
that use that control to analyze data and make acquisition decisions during an
experiment.

The repository has four main roots:

- `drivers/` contains the vendor microscope drivers, organized as
  `drivers/<vendor>/<machine>/<api>/` (e.g.
  `drivers/leica/stellaris5_y42h93/navigator_expert/`). Each driver carries its
  own calibration and limits code.
- `shared/` contains vendor-independent utilities (output layout, algorithms).
- `microscope_agnostic_controller/` is the cross-vendor controller — the single
  workflow-facing surface that sits above the drivers.
- `workflows/` contains smart-microscopy workflows. The current workflow is
  `workflows/target_acquisition/`.

```text
drivers/
  leica/stellaris5_y42h93/navigator_expert/   Leica LAS X Navigator Expert driver
    calibration/                              calibration notebooks and code
    limits/                                   safety-limit data and helpers
shared/                                       vendor-independent utilities
microscope_agnostic_controller/               cross-vendor controller (see its README)
workflows/
  target_acquisition/                         operator notebook, pipeline, tests
```

## Current Status

The Leica Navigator Expert driver is the production-tested path. It has been
validated against the LAS X simulator and a real Leica STELLARIS. The
microscope-agnostic layer is still under construction; workflow code currently
uses the Leica driver path directly through local bootstrap modules.

The repository runs from the source checkout (no `pip install .`); its Python
dependencies install from conda-forge (see [Getting Started](#getting-started)).

## State Readers

The Leica driver exposes three reader families:

- `api`: CAM/PyAPI readback only.
- `log`: LAS X log-derived state only.
- `hybrid`: both sources participate where available; command confirmation
  accepts the first admissible evidence.

Hybrid is the default for selected-job confirmation. This is deliberate: API
and log can each fail differently, so the driver treats source disagreement as
diagnostic evidence instead of silently hiding it.

## Getting Started

Build the conda-forge environment in one step, then activate it:

```powershell
python build_env.py            # creates the "smart-microscopy" conda-forge env
conda activate smart-microscopy
```

This targets **Python 3.10-3.12** (Windows for live LAS X use; registration and
focusing run on any OS) and installs the minimum to drive the microscope and
process its images. Full setup — dependency rationale, the conda-forge / PyPI
choice, live-LAS X notes, and the typical path through the repo — is in
**[`getting-started/`](getting-started/README.md)**.

## Tests

Offline tests need no microscope and no LAS X installation. Install the offline
test/lint deps (separate from the runtime env; no `pythonnet`, so the suite runs
on any OS):

```powershell
python -m pip install -r drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt
python -m pytest -q drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit
python -m pytest -q drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware
python -m pytest -q workflows/target_acquisition/tests
python -m pytest -q drivers/leica/stellaris5_y42h93/navigator_expert/calibration/tests shared/output_layout/tests
```

Live validation is explicit and safe by default. Hardware-moving sections only
run when their `--allow-*` flags are present:

```powershell
python drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/validate_hardware.py --yes --allow-xy --allow-z --allow-objective --allow-acquire --state-reader-mode hybrid
```

Validator JSONL outputs are runtime artifacts and are ignored by default.
