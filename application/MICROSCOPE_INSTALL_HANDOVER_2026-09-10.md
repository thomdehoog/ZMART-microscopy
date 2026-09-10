# Microscope installation handover — Top / Slice / MIP

Date: 2026-09-10. This is a feature-branch test deployment, not a main-branch release.

## Branches and current readiness

| Component | Repository | Branch | Current committed HEAD |
| --- | --- | --- | --- |
| Operator | `thomdehoog/ZMART-microscopy` | `codex/operator-named-views-simulator` | `4de0a8bcf5713c7531a52733a40282ccc2a00c30` |
| Viewer | `thomdehoog/zmart-viewer` | `codex/operator-embedding` | `128130d761589c02c67933b40cb379ae33afe0cb` |

Viewer package version required by the operator: **0.5.0.dev0**.

IMPORTANT: both worktrees currently have uncommitted fixes beyond these HEADs. The simulator session tested those working copies, not just these commits. `requirements.txt` and `environment.yml` still pin the viewer HEAD above. A pull/install of that pin does NOT reproduce the latest tested behavior.

Before transferring to the microscope: review and commit the intended changes in both repositories, build/verify the viewer, update both operator dependency pins to the new viewer commit, rebuild the operator page, and push the feature branches. Record the final two commit IDs here. Do not push or merge main as part of this handover. This note itself does not perform any of those operations.

Current development worktrees:

- Operator: `C:\ProgramData\MinicondaZMB\home\t.de\zmart-operator-named-views-20260910`
- Viewer: `C:\ProgramData\MinicondaZMB\home\t.de\zmart-viewer-embedding-20260910`

Keep the existing microscope checkout and environment available for rollback. Do not reset them or copy simulator machine configuration over them.

## Windows tool location — important

Run **Node, npm, Vite, Vitest, Playwright and its browsers from under `C:\ProgramData\MinicondaZMB`**. Keep the checkout, `node_modules`, npm cache and Playwright browser cache there too. On this workstation AppLocker blocks executables in other user-writable locations; Desktop, Downloads, AppData and a home-directory tool installation can fail even when the package installed successfully.

Activate the intended conda environment before building or testing. Do not accidentally use a system Node, an AppData Playwright browser, or another environment's Python. Vite is invoked through the checkout's npm scripts, not a global Vite installation.

Example PowerShell setup, after activating the environment:

```powershell
$env:PYTHON = (Get-Command python).Source
$env:npm_config_cache = 'C:\ProgramData\MinicondaZMB\npm-cache'
$env:PLAYWRIGHT_BROWSERS_PATH = 'C:\ProgramData\MinicondaZMB\ms-playwright'
Get-Command python, node, npm, conda | Select-Object Name, Source
python --version
node --version
```

Use Node 22.12+ for the operator's Vite 8 toolchain. Leave `CONDA_PREFIX` as set by conda activation; Playwright's driver resolution also depends on the active environment. Do not copy the development machine's `_op050/site` or its temporary `PYTHONPATH` overrides onto the microscope.

## Install into a separate environment

These steps assume the final feature commits and matching viewer pin have been published as described above. Use a separate clone/worktree under MinicondaZMB; do not switch the running rig checkout while acquisition is active.

From that operator checkout:

```powershell
git fetch origin
git status --short --branch
git log -1 --oneline
# Verify this is codex/operator-named-views-simulator at the final handover commit.
conda env create -n zmart-operator-named-views -f environment.yml
conda activate zmart-operator-named-views
python -m pip install -e .
python -m pip check
python -c "import sys, importlib.metadata as m, zmart_viewer; print(sys.executable); print(m.version('zmart-viewer')); print(zmart_viewer.__file__)"
```

`environment.yml` supplies the main operator environment, including pythonnet for LAS X. Installing just the small root `requirements.txt` is not a complete microscope/analysis environment. The version string alone is not enough: multiple development commits use 0.5.0.dev0. Verify the installed viewer commit as well:

```powershell
python -c "import importlib.metadata as m; print(m.distribution('zmart-viewer').read_text('direct_url.json'))"
```

If installing a supplied viewer wheel instead, use the wheel built from the final viewer commit and verify its supplied SHA256. Installing operator requirements afterwards may reinstall the pinned viewer; recheck the installed origin. Do not install an arbitrary older wheel carrying the same version name.

## Analysis workers

Focus and detection run in separate conda environments, not just the operator environment. Check `conda env list`. Required for focus and Fast detection:

- `ZMART--focus--main`
- `ZMART--object_analysis--classical`

Robust/Cellpose additionally uses `ZMART--object_analysis--cellpose`.

For missing environments, use the repository setup scripts from the operator root:

```powershell
python zmart_analysis/workflows/focus/environments/setup_env.py --step main
python zmart_analysis/workflows/object_analysis/environments/setup_env.py --step classical
# Only when Robust/Cellpose is wanted:
python zmart_analysis/workflows/object_analysis/environments/setup_env.py --step cellpose
```

Do not delete/recreate existing rig analysis environments blindly: these names are shared across operator environments. Check their compatibility first. The analysis reader requires `tifffile>=2026.6.1` with the current Zarr 3 stack. For example:

```powershell
conda run -n ZMART--focus--main python -c "import tifffile, ngio, zarr; print(tifffile.__version__, zarr.__version__)"
conda run -n ZMART--object_analysis--classical python -c "import tifffile, ngio, zarr; print(tifffile.__version__, zarr.__version__)"
```

## Build the page, or transfer the complete matching build

Set the MinicondaZMB tool/cache variables above, then from the operator root:

```powershell
Push-Location application
npm ci
npm run build
Pop-Location
```

Stop if either command fails; do not serve an old page left on disk. The build reads the growth patch from the installed viewer through `$env:PYTHON`, so install the matching viewer first. Transfer the entire `application/framework/window/static/` output, including the worker files, not only `index.html`.

When building the companion viewer from source, build its `app/page` first (`npm ci`, then `npm run build`) before creating/installing its wheel. Both frontends must correspond to the recorded handover commits. If the microscope has no build toolchain/network, build on the development machine and deliver the matching artifacts/dependencies in advance.

Optional preflight tests, from `application`, with the same MinicondaZMB environment and caches:

```powershell
npm run test:unit
npx playwright install chromium
npx playwright test parts/canvas/named-views.spec.js
```

Playwright test tooling is not needed for ordinary acquisition. If `PLAYWRIGHT_CHROMIUM` is set, it must name the actual installed executable under MinicondaZMB, not a stale browser path from another machine. Do not run mock/simulator acquisition probes against a real microscope.

## Launch on the real microscope

LAS X must be running with the real instrument, CAM API available, and the intended jobs configured. Preserve its machine-local measured configuration under `C:\ProgramData\zmart-microscopy`.

From the operator checkout in the activated environment:

```powershell
python application/zmart-interface.py --built
```

Do **not** pass `--simulator-pixels`. Do not use `_op050/operator-simulator-demo.py`, the mock-only launcher, or the simulator capture probe. The real launcher must not say `SIMULATOR / SYNTHETIC PIXELS`.

For a browser instead of a native window:

```powershell
python -m application.framework.bridge --port 8600
```

Open `http://127.0.0.1:8600`. Use only one controlling operator process. Confirm the actual run/data destination in the real session; the earlier path was `Z:\zmbstaff\10374\Raw_Data\ZMART microscopy`, but this note does not override driver export settings. Verify that the share is reachable and writable in the account running LAS X and the operator.

## First microscope checks

1. Select the real Leica driver and its correct machine configuration. If measured limits or orientation fail validation and bundled defaults are substituted, stop and resolve the configuration; do not bypass limits or copy the simulator's setup.
2. In a known safe region, acquire one flat image and one small stack. Check actual vendor pixels, XY size/placement, physical plane order and Z against LAS X before a larger run.
3. Check Top (relative plane navigation with boundary holding), Slice (absolute specimen Z), and MIP. Verify a singleton and a stack both behave correctly, with no unexplained disappearance or opaque unacquired areas.
4. Check focus scoring and sidebar previews against the captured canonical OME-Zarr. The shared reader changed; simulator success alone is not real-microscope validation.
5. Test detection on one tile. Threshold is in raw counts, not the contrast-stretched preview values. The simulator's 0–16-count images needed a much lower threshold than 100; **do not carry threshold 8 over as a real-microscope recommendation**.
6. Run a small multi-position acquisition with the desired bake setting. Confirm publication reaches ready and the final images appear without manual refresh before increasing scale.

The latest bounded simulator focus-to-overview test and 100 targeted regressions passed. This does not certify real stage calibration, instrument limits, optical focus or acquisition throughput. Keep the old working branch/environment as the rollback path; switching back does not require deleting the new run data.
