# SMART Microscopy

This repository contains a collection of implementations for smart microscopy:
microscope integrations, shared microscope-facing utilities, and workflows that
use those pieces to automate experiments.

The repository is organized around two main folders:

- `microscopes/` contains code and configuration that talks to microscopes.
  It holds vendor integrations, drivers, calibration data, safety limits,
  shared microscope-facing utilities, and the `microscope_agnostic_layer/`.
  That agnostic layer is still under construction. The Leica Navigator Expert
  driver is the current working implementation, and it has been tested on the
  LAS X simulator and the real Leica STELLARIS microscope.
- `workflows/` contains smart-microscopy workflows. The main workflow is
  `workflows/target_acquisition/`.

## Layout

```text
microscopes/
  calibration/
  driver/
  limits/
  microscope_agnostic_layer/
  shared/
  docs/
workflows/
  target_acquisition/
```

The Leica driver lives at:

`microscopes/driver/vendor/leica/navigator_expert/`

The target-acquisition workflow lives at:

`workflows/target_acquisition/`

## Current Status

The Leica Navigator Expert stack is the production-tested path today. It
includes API, log, and hybrid reader modes for LAS X state, with hybrid
selected-job confirmation validated on both simulator and real hardware.

The microscope-agnostic layer is intentionally not treated as production-ready
yet. Code should move there only when it is useful across microscope backends
and has a clear interface for workflows.

## Getting Started

1. Activate the conda environment used for LAS X work:
   `lasxapi_extended`.
2. Run Leica calibration notebooks from:
   `microscopes/calibration/vendor/leica/navigator_expert/notebooks/`.
3. Run the target-acquisition workflow from:
   `workflows/target_acquisition/`.
4. Validate the Leica driver on the simulator or microscope with:

```powershell
python microscopes/driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py --yes
```

Detailed design notes and validation reports are in `microscopes/docs/`.
