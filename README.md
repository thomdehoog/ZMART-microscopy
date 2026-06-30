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

The repository is source-checkout based for now, not pip-installable.

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

Use a Python environment that can import the LAS X Python API runtime and the
scientific Python dependencies used by the workflow. In this source checkout,
the notebook and hardware tools use small `_bootstrap.py` modules to add the
local driver and workflow packages to `sys.path`.

Typical path through the repo:

1. Review or update calibration under
   `drivers/leica/stellaris5_y42h93/navigator_expert/calibration/`.
2. Run the Leica driver validator against the simulator or microscope.
3. Run the target-acquisition workflow from
   `workflows/target_acquisition/smart_microscopy_v3.2.ipynb`.

## Tests

Offline tests need no microscope and no LAS X installation:

```powershell
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
