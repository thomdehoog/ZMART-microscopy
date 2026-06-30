# SMART Microscopy

[![navigator-expert](https://github.com/thomdehoog/smart-microscopy/actions/workflows/navigator-expert.yml/badge.svg?branch=microscope-agnostic-layer)](https://github.com/thomdehoog/smart-microscopy/actions/workflows/navigator-expert.yml)
[![controller](https://github.com/thomdehoog/smart-microscopy/actions/workflows/controller.yml/badge.svg?branch=microscope-agnostic-layer)](https://github.com/thomdehoog/smart-microscopy/actions/workflows/controller.yml)
[![python](https://img.shields.io/badge/python-3.10--3.12-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)](https://github.com/thomdehoog/smart-microscopy/actions)

SMART Microscopy puts microscopes under programmatic control and runs workflows
that analyze data and make acquisition decisions live during an experiment. The
design is **vendor-neutral**: a workflow targets one small controller interface,
and any microscope with a driver behind that interface can run it.

## Architecture

Four roots, layered from vendor-specific up to vendor-neutral:

```text
drivers/                                        vendor microscope drivers
  <vendor>/<machine>/<api>/                     one driver per (vendor, machine, API)
  leica/stellaris5_y42h93/navigator_expert/     Leica LAS X Navigator Expert driver
    calibration/                                calibration notebooks and code
    limits/                                     safety-limit data and helpers
shared/                                         vendor-independent utilities (output layout, algorithms)
controller/                                     cross-vendor controller (single workflow-facing surface)
workflows/                                      smart-microscopy workflows
  target_acquisition/                           operator notebook, pipeline, tests
```

- **`drivers/`** — each driver speaks one microscope's native API and is keyed by
  `<vendor>/<machine>/<api>`. A driver owns its own calibration and limits. New
  microscopes are added here without touching workflows.
- **`shared/`** — vendor-independent utilities: the lab-wide output layout and
  image algorithms (registration, focus) used across drivers and workflows.
- **`controller/`** — the cross-vendor controller: one small, consistent interface
  a workflow drives, so the same workflow runs on any microscope that has a
  driver. See its README for the full API and for how to register a new driver.
- **`workflows/`** — the smart-microscopy workflows themselves (current:
  `workflows/target_acquisition/`).

## Drivers

Drivers live under `drivers/<vendor>/<machine>/<api>/` and are registered with
the controller through its registry (see the controller README), so adding a
vendor, microscope, or API is an additive change. Each driver documents its own
command model, state handling, and gotchas in its own README.

| Microscope | API | Driver | Status |
|---|---|---|---|
| Leica STELLARIS 5 | LAS X CAM / Navigator Expert | [`drivers/leica/stellaris5_y42h93/navigator_expert/`](drivers/leica/stellaris5_y42h93/navigator_expert/README.md) | Production-tested (LAS X simulator + real STELLARIS) |

The cross-vendor controller is the intended single surface above the drivers and
is still under construction; today the workflow uses the Leica driver path
directly through local bootstrap modules. As more drivers land, this table grows
and workflows move onto the controller surface.

## Getting Started

Install the Python environment. We use [conda-forge](https://conda-forge.org) to
avoid licensing issues. Build it in one step, then activate:

```powershell
python build_env.py            # creates the "smart-microscopy" conda-forge env
conda activate smart-microscopy
```

This targets **Python 3.10-3.12** and installs the minimum to drive a microscope
and process its images. Driving a microscope *live* also needs that microscope's
own software installed (e.g. LAS X for the Leica driver); registration, focusing,
and image processing run on any OS. Full setup — dependency rationale, the
conda-forge / PyPI choice, and the typical path through the repo — is in
**[`getting_started/`](getting_started/README.md)**.

## Tests

Each component has its own offline suite that needs no microscope and no vendor
software. Install the offline test/lint deps (separate from the runtime env),
then run the suites:

```powershell
python -m pip install -r drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt
python -m pytest -q controller/tests
python -m pytest -q drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit
python -m pytest -q drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware
python -m pytest -q workflows/target_acquisition/tests
python -m pytest -q drivers/leica/stellaris5_y42h93/navigator_expert/calibration/tests shared/output_layout/tests
```

Live validation is explicit and safe by default — vendor-specific and gated. For
the Leica driver, hardware-moving sections only run when their `--allow-*` flags
are present:

```powershell
python drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/validate_hardware.py --yes --allow-xy --allow-z --allow-objective --allow-acquire --state-reader-mode hybrid
```

Validator JSONL outputs are runtime artifacts and are ignored by default.
