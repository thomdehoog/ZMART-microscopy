# Getting Started

First-time Python setup for ZMART Microscopy and the typical path through the
repo. The environment files referenced here live at the **repo root**:
[`environment.yml`](../environment.yml), [`requirements.txt`](../requirements.txt),
and [`build_env.py`](../build_env.py) (manifests stay at the root so the
toolchain auto-discovers them).

## Python environment

ZMART Microscopy targets **Python 3.10-3.12**. The live system runs on
**Windows** (the LAS X PC); registration, focusing, and image processing run on
any OS. Build the environment from conda-forge in one step (run from the repo
root):

```powershell
python build_env.py            # creates the conda-forge "zmart-microscopy" env
conda activate zmart-microscopy
```

`build_env.py` creates the env from `environment.yml`, verifies the core
packages import, and asserts every package came from conda-forge; the Anaconda
`defaults` channel is never used. Re-run with `--recreate` to rebuild it clean,
or `--update` to update it in place. Manual equivalent:
`conda env create -f environment.yml`.

The environment is the minimum needed to drive the microscope and process its
images:

| Capability             | Packages                          |
|------------------------|-----------------------------------|
| LAS X API interaction  | `pythonnet` (Python<->.NET bridge)|
| Registration           | `numpy`, `opencv`, `scikit-image` |
| Focusing, calibration  | `numpy`, `scipy`                  |
| Image I/O (OME-TIFF)   | `tifffile`                        |

For **live** API interaction LAS X must be installed and running: the CAM API
DLLs ship with LAS X and load from the install dir, so the env carries only the
`pythonnet` bridge.

Non-conda machines (e.g. CI) can install the same packages from PyPI:
`python -m pip install -r requirements.txt`. conda-forge is the canonical path;
PyPI is a licensing-safe fallback (only the conda `defaults` channel is
avoided). Test/lint tools are separate (see the driver's `requirements-dev.txt`).

## Working in the checkout

The code runs directly from the source checkout (no `pip install .`). Notebooks
and hardware tools use small `_bootstrap.py` modules to add the driver and
shared packages to `sys.path`.

Typical path through the repo:

1. Review or update calibration under
   `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/calibration/`.
2. Run the Leica driver validation against the simulator or microscope —
   `run_ci.py` is the entry point (offline / online / `--live-writes`); see the
   [driver testing guide](../zmart_drivers/leica/stellaris5_y42h93/navigator_expert/README.md#9-testing)
   and the bench runbook at
   [`tests/hardware/README.md`](../zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/README.md).
   Running the offline suite additionally needs the dev tools:
   `pip install -r zmart_drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt`.
3. Run the target-acquisition workflow from
   `workflows/target_acquisition/zmart_microscopy_v3.2.ipynb`.
