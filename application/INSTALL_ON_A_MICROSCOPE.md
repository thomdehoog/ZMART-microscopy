# Installing the operator on a microscope

What to clone, where it must live, what has to be built, and in which order. Current as of
2026-09-21 for branch `codex/operator-named-views-simulator`. This is a feature branch on a real
instrument, not a main release: keep the previous checkout and environment for rollback.

## What runs where

Three things run on the microscope PC, all from one conda environment:

| Thing | What it is | Where it comes from |
| --- | --- | --- |
| Operator | The page and its bridge (`application/`), the driver for the instrument, the analysis engine | `thomdehoog/ZMART-microscopy`, branch `codex/operator-named-views-simulator` |
| Viewer | The picture server and engine the page draws with; a Python package the operator imports | `thomdehoog/ZMART-viewer`, branch `codex/operator-embedding`, commit `6791d28946a094cdda7fba05bff9c7744562b7e6`, package version `0.5.0.dev0` |
| Analysis workers | Two conda environments the engine spawns for focus scoring and object detection | Made by the operator's own setup scripts |

The operator pins the viewer commit in `requirements.txt` and `environment.yml`. Both must move together: install the viewer first, then the operator.

## Where things must live

On the ZMB workstations AppLocker refuses to run executables from user-writable folders. Everything
that runs or is built goes under `C:\ProgramData\MinicondaZMB`: the two checkouts, `node_modules`,
the npm cache and the Playwright browsers. A checkout on the Desktop, in Downloads or under
`AppData` can install cleanly and still fail to run. Never run from a network share.

Suggested layout on a new machine:

```
C:\ProgramData\MinicondaZMB\home\<user>\ZMART-microscopy      the operator checkout
C:\ProgramData\MinicondaZMB\home\<user>\ZMART-viewer          the viewer checkout
C:\ProgramData\MinicondaZMB\npm-cache                          npm cache
C:\ProgramData\MinicondaZMB\home\<user>\ms-playwright         Playwright browsers (tests only)
```

Machine-local instrument configuration lives outside the checkouts, under
`C:\ProgramData\zmart-microscopy\<vendor>\<microscope>\<api>\<datetime>\`; the configuration
workflow in the page writes it. Runs are written wherever the driver's export settings point; the
launcher's `--output-root` overrides that for the mock.

## Order of work

### 1. Clone both repositories

```powershell
cd C:\ProgramData\MinicondaZMB\home\<user>
git clone https://github.com/thomdehoog/ZMART-microscopy.git
git clone https://github.com/thomdehoog/ZMART-viewer.git
cd ZMART-microscopy; git switch codex/operator-named-views-simulator
cd ..\ZMART-viewer; git fetch origin codex/operator-embedding
git switch --detach 6791d28946a094cdda7fba05bff9c7744562b7e6
```

Check the operator's pin matches the viewer commit you checked out: `grep zmart-viewer requirements.txt`.

### 2. The conda environment

Conda-forge only; never the `defaults` channel. From the operator checkout, either clone a working
environment from another microscope, or create one from `environment.yml` with its
`zmart-viewer @ git+...` pip line removed (a bare Git install of the viewer fails, see step 3):

```powershell
conda env create -n zmart-microscopy -f environment.yml     # after removing the zmart-viewer line
conda activate zmart-microscopy
```

The environment carries Node (22.12 or newer) for the two page builds. Set these once per shell:

```powershell
$env:PYTHON = (Get-Command python).Source
$env:npm_config_cache = 'C:\ProgramData\MinicondaZMB\npm-cache'
Get-Command python, node, npm | Select-Object Name, Source     # all three under MinicondaZMB
```

### 3. Build and install the viewer

The viewer's page is not tracked in Git and its wheel refuses to build without it. Build the page,
then install:

```powershell
cd C:\ProgramData\MinicondaZMB\home\<user>\ZMART-viewer
npm --prefix app/page ci
npm --prefix app/page run build
python -m pip install .
```

### 4. Install the operator and build its page

```powershell
cd C:\ProgramData\MinicondaZMB\home\<user>\ZMART-microscopy
python -m pip install --no-deps -e .
python -m pip check
python -c "import importlib.metadata as m, zmart_viewer; print(m.version('zmart-viewer'), zmart_viewer.__file__)"
cd application
npm ci
npm run build
```

`--no-deps` keeps pip from replacing the viewer you just built with an unbuilt Git one. The page
build writes `application/framework/window/static/` (the page and two worker files); the workers
are compiled from the installed viewer, which is why the viewer comes first. The built page is
committed, so a checkout already carries one, but rebuild after any change to the page's sources.

### 5. The analysis environments

Focus scoring and object detection run in their own environments, spawned by the engine on first
use. From the operator checkout:

```powershell
python zmart_analysis/workflows/focus/environments/setup_env.py --step main
python zmart_analysis/workflows/object_analysis/environments/setup_env.py --step classical
python zmart_analysis/workflows/object_analysis/environments/setup_env.py --step cellpose   # Robust only
```

They are named `ZMART--focus--main`, `ZMART--object_analysis--classical` and
`ZMART--object_analysis--cellpose`. Fast detection runs its fields twelve at a time in the classical
environment; the first press of a session pays the worker spawns, about fifteen seconds on a desk
PC, once. Check the readers before trusting a run:

```powershell
conda run -n ZMART--object_analysis--classical python -c "import tifffile, ngio, zarr; print(tifffile.__version__, zarr.__version__)"
```

### 6. The instrument

The driver for the instrument is in the operator checkout (`zmart_drivers/`, and `drivers/` for
the Leica navigator). LAS X must be running with the CAM API and the intended jobs set up before the
page connects. The configuration workflow in the page measures limits and calibration and writes the
machine-local configuration; a session always stands on one.

### 7. Launch

```powershell
cd C:\ProgramData\MinicondaZMB\home\<user>\ZMART-microscopy
python application/zmart-interface.py --built
```

This opens the operator window on the built page with its bridge beside it. Never pass
`--simulator-pixels` on a real instrument. For a browser instead of a window:
`python -m application.framework.bridge --port 8600` and open `http://127.0.0.1:8600`. One
controlling operator process at a time.

For a dry run without an instrument, the mock: `python application/mock-instrument.py` opens the
mock's own window, where jobs are chosen the way they are in LAS X, and the operator window
connects to "mock".

## First checks on a new instrument

1. Connect to the real driver and its measured configuration. If limits or orientation fall back
   to bundled defaults, stop and fix the configuration; never bypass limits.
2. In a safe region, one flat image and one small stack. Check pixels, XY placement and Z against
   LAS X.
3. Place three or four focus points spread over the area, not in a line; on a strip, spread them
   across it. Read the map's label: "exact fit" means as many points as the model has parameters,
   an rms means the surface had points to spare.
4. Scan a few positions. The picture is the projection of each position; a stack is its brightest
   plane. Baking is on unless switched off in the session card.
5. Test detection on one tile before the whole sample. Threshold is in raw counts.
6. Acquire a few targets and look at the pairs in the list.

Only after these, larger acquisitions. The mock and the LAS X simulator prove the software, never
the stage calibration, the optics or the throughput of the real instrument.

## Optional: the tests

Playwright and its browsers go under MinicondaZMB too:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = 'C:\ProgramData\MinicondaZMB\home\<user>\ms-playwright'
cd application
npm run test:unit
npx playwright install chromium
npx playwright test parts/canvas/named-views.spec.js parts/canvas/flat-tiles.spec.js
```

The nine-step walk on the mock is `npx playwright test workflows/target_acquisition/walk.spec.js`.

## Rollback

Keep the previous checkout and environment. Switching back is a matter of activating the old
environment and launching from the old checkout; run data written by the new one stays valid.
