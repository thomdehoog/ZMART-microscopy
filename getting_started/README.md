# Getting Started

First-time setup for ZMART Microscopy, in three steps. The environment files
referenced here live at the **repo root**: [`environment.yml`](../environment.yml),
[`requirements.txt`](../requirements.txt), and [`build_env.py`](../build_env.py)
(manifests stay at the root so the toolchain auto-discovers them).

ZMART Microscopy targets **Python 3.10-3.12**. The live system runs on **Windows**
(the LAS X PC); registration, focusing, and image processing run on any OS. The
code runs directly from the source checkout — there is no `pip install .`;
notebooks and tools add the packages to `sys.path` via small `_bootstrap.py`
modules.

## Step 1 — Install the environment

Build the conda-forge environment in one step (run from the repo root), then
activate it:

```powershell
python build_env.py            # creates the conda-forge "zmart-microscopy" env
conda activate zmart-microscopy
```

`build_env.py` creates the env from `environment.yml`, verifies the core packages
import, and asserts every package came from conda-forge (the Anaconda `defaults`
channel is never used). Re-run with `--recreate` to rebuild it clean or `--update`
to update in place. Manual equivalent: `conda env create -f environment.yml`.

For **live** control, LAS X must be installed and running — the CAM API DLLs ship
with LAS X and load from its install dir, so the env carries only the `pythonnet`
bridge. Add the dev/test tools (needed to run the driver's validation):

```powershell
pip install -r zmart_drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt
```

| Capability             | Packages                          |
|------------------------|-----------------------------------|
| LAS X API interaction  | `pythonnet` (Python<->.NET bridge)|
| Registration           | `numpy`, `opencv`, `scikit-image` |
| Focusing, calibration  | `numpy`, `scipy`                  |
| Image I/O (OME-TIFF)   | `tifffile`                        |

> On a **fresh Miniconda** install, `conda env create` refuses to run until the
> Anaconda default channels' Terms of Service are accepted — even though this env
> never uses them. If the build fails with a ToS message, run the two
> `conda tos accept …` commands it prints and re-run `build_env.py` (Miniforge
> installs don't have this gate). Non-conda machines can install the same
> packages from PyPI: `python -m pip install -r requirements.txt` (conda-forge is
> canonical; PyPI is the licensing-safe fallback).

## Step 2 — Set the stage limits

The driver **refuses every move until machine-local stage limits are provisioned**
— there is no bundled fallback (a wrong-machine envelope would be unsafe). Create
them once by running the notebook:

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/notebooks/set_stage_limits.ipynb
```

The pre-filled values are this machine's known-good envelope; adjust only if you
have better numbers. Running the cell publishes a single machine-local
`limits.json` (the stage envelope + the function gate) under
`C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\<datetime>\`.
Calibration is separate and keeps a loud last-known-good fallback; run the
calibration notebooks under `.../calibration/notebooks/` if you want a fresh one.

## Step 3 — Run it

Drive the microscope through the driver's entry point (`run_ci.py`), starting
read-only:

```powershell
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python run_ci.py online                 # read-only pass, no instrument changes
python run_ci.py online --live-writes    # full validation (reversible, restored)
```

The bench runbook — prerequisites, what each pass does, where the reports land —
is at
[`tests/hardware/README.md`](../zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/README.md).
To run an actual experiment, open the operator notebook
`workflows/target_acquisition/zmart_microscopy_v3.2.ipynb`.
