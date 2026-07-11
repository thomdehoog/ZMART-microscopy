# Getting Started

First-time setup for ZMART Microscopy, in three steps. The environment files
referenced here live at the **repo root**: [`environment.yml`](../environment.yml),
[`requirements.txt`](../requirements.txt), [`requirements-dev.txt`](../requirements-dev.txt),
and [`build_env.py`](../build_env.py)
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

`build_env.py` creates the env from `environment.yml`, verifies all runtime,
notebook, CI, and website packages, installs and launches Playwright's matching
Chromium build, verifies Node.js, and asserts every conda package came from
conda-forge (the Anaconda `defaults` channel is never used). Re-run with
`--recreate` to rebuild it clean or `--update` to update in place. `--offline`
uses only cached conda packages and requires the matching Chromium build to
already be cached.

> Prefer a different env name? `python build_env.py --name my-env` uses it instead
> of `zmart-microscopy`; the script prints the exact `conda activate <name>` line
> to run when it finishes. (The env name is just a conda label — nothing in the
> code depends on it.)

For **live** control, LAS X must be installed and running — the CAM API DLLs ship
with LAS X and load from its install dir, so the env carries only the `pythonnet`
bridge. The conda environment already includes the test/lint tools used by the
driver validation. If you are using the pip fallback or another minimal env,
install the complete repository test requirements explicitly:

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium
```

| Capability             | Packages                          |
|------------------------|-----------------------------------|
| LAS X API interaction  | `pythonnet` (Python<->.NET bridge)|
| Registration           | `numpy`, `opencv`, `scikit-image` |
| Focusing, calibration  | `numpy`, `scipy`                  |
| Image I/O (OME-TIFF)   | `tifffile`                        |
| Notebook + website CI  | `nbformat`, `anywidget`, `playwright`, `nodejs` |

> On a **fresh Miniconda** install, `conda env create` refuses to run until the
> Anaconda default channels' Terms of Service are accepted — even though this env
> never uses them. If the build fails with a ToS message, run the two
> `conda tos accept …` commands it prints and re-run `build_env.py` (Miniforge
> installs don't have this gate). Non-conda machines can install runtime packages
> from PyPI with `requirements.txt`, or the full test-ready set with
> `requirements-dev.txt` (conda-forge is canonical; PyPI is the licensing-safe
> fallback).

## Step 2 — Publish machine setup

The driver reads limits, orientation, calibration, and origin from the newest
machine-local snapshot under `C:\ProgramData\zmart-microscopy\...`. If no local
snapshot exists yet, the driver seeds ProgramData from the repo defaults so CI,
mock runs, and first connects work without editing the checkout. On the real
microscope, replace those defaults with measured machine values.

Start with the stage-limit notebook:

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/notebooks/set_stage_limits.ipynb
```

The pre-filled values are this machine's known-good envelope; adjust only if you
have better numbers. Running the cell publishes a machine-local `limits.json`
(the stage envelope + the function gate) under
`C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\<datetime>\`.
Then run the orientation notebook:
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/orientation/notebooks/set_orientation.ipynb`

For calibration, run the objective-pair notebook for each lens configuration
you will use:
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/calibration/notebooks/calibrate_objective_pair.ipynb`

Calibration can be adopted into the default file or into named
`calibrations/<name>/calibration.json` entries; ProgramData remains the source
of truth.

## Step 3 — Run it

Drive validation through the driver's entry point (`run_ci.py`):

```powershell
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python run_ci.py             # mock/offline, no microscope, no LAS X
python run_ci.py --hardware  # live LAS X validation: moves/acquires, restored where possible
```

The bench runbook — prerequisites, what each pass does, where the reports land —
is at
[`tests/hardware/README.md`](../zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/hardware/README.md).
To run an actual experiment, open the operator notebook
`workflows/target_acquisition/zmart_microscopy_v4.ipynb`.
