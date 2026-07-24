# Testing the viewer

## The short version

From the `viz_studio` folder, one command runs everything:

```
python run_tests.py
```

That is all you need. It installs the test tools if they are missing, builds the
viewer page once, and then runs every test. The first run takes a few minutes
(building the page and, on a real machine, downloading the browser the render
tests drive); after that it is quick.

To test against a **real acquisition** as well, point it at an OME-Zarr store:

```
ZMART_TEST_STORE=/path/to/acquisition.ome.zarr python run_tests.py
```

Anything you add after the command goes straight to pytest, so you can run just
part of the suite while you work:

```
python run_tests.py -k omezarr     # only the OME-Zarr tests
python run_tests.py -v              # one line per test
python run_tests.py -s -k gpu       # print which GPU the renderer found
```

## What runs, and what skips

The suite is written so a plain machine stays green and a capable machine tests
more — nothing fails just because a piece is absent; it *skips* with a clear
reason. Three things decide what runs:

- **Always.** The data-reading tests (finding channels in a store, choosing a
  contrast window, serving chunks safely) need only Python with numpy and zarr.
  These run everywhere.
- **When the page is built.** The browser tests load the real viewer and check
  that pixels actually reach the renderer. `run_tests.py` builds the page for
  you; without Node.js they skip.
- **When a GPU / real data is present.** Two tests only make sense on a real
  machine, and live in `tests/test_gpu_realdata.py`:
  - `test_webgl_is_hardware_accelerated` — confirms a graphics card, not
    software, is drawing WebGL. It **skips** on a machine without one (you will
    see "software WebGL renderer … no GPU on this machine"), so it is quiet in
    CI and meaningful on the microscope PC. Run it with `-s` to print the exact
    GPU it found.
  - `test_real_store_channels_become_layers` and `test_real_store_renders` —
    open the store named by `ZMART_TEST_STORE`, and check that every channel in
    it becomes a layer and that the volume actually streams and renders. They
    **skip** unless that variable is set.

There is also a set of tests that run against a specific real mesoSPIM transfer
on the lab's network share (`tests/test_real_mesospim_data.py`). They skip
wherever that drive is not mounted, and run on the acquisition PC where it is.

## Confirming the GPU is really being used

The clearest single check:

```
python run_tests.py -s -k hardware_accelerated
```

On a machine with a graphics card this prints the renderer, for example
`WebGL renderer: NVIDIA GeForce …`, and passes. On a machine without one it
skips and tells you it saw a software renderer. (For a second opinion outside
the tests, open `chrome://gpu` in the same browser and look for "Hardware
accelerated" next to WebGL2.)

## A note on speed

Where these tests are slow, it is almost always the **software** rendering path:
with no GPU, WebGL runs on the CPU, so the render tests take minutes rather than
seconds. That is a property of the machine, not the viewer — on hardware with a
graphics card the same tests, and the viewer itself, run far faster. The test
*results* (correct channels, safe serving, pixels reaching the renderer) hold on
any machine; only the *timings* change.

## Windows lab-PC setup (validated 2026-07-24)

On a managed Windows PC, AppLocker may block native tools downloaded beneath a
user profile or a temporary directory. Keep the Conda environment, Node build
tools, Playwright browser, and test checkout beneath an approved installation
directory. The setup validated on the ZMART workstation used:

```bat
conda activate ZMART-viewer
conda install -c conda-forge nodejs esbuild
npm install --global vite@7.0.0 esbuild@0.25.12
set PLAYWRIGHT_BROWSERS_PATH=C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\ms-playwright
playwright install chromium
```

The checkout used for browser tests was placed below the same environment:

```text
C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\src\ZMART-microscopy
```

This matters because both Vite/esbuild and Playwright launch native
executables. A checkout under `C:\tmp`, a mapped network drive, or a browser
download under `%LOCALAPPDATA%` may install successfully but then fail with
`spawn UNKNOWN`.

Validation recorded on **2026-07-24 at 11:29 Europe/Zurich** against commit
`4ce2711`:

```text
140 passed, 2 skipped in 568.93s
```

The hardware-accelerated WebGL, interaction, layer-panel, render-acceptance,
synthetic OME-Zarr, network-share mesoSPIM, server, and path-safety tests all
passed. The only skipped tests required an explicit real acquisition through
`ZMART_TEST_STORE`.

## Seeing it for real

Testing aside, to actually look at a real acquisition through the viewer:

```
python run_demo.py --data /path/to/acquisition.ome.zarr
```

This opens the store through the neuroglancer engine, streaming it out-of-core,
in a native window (falling back to a browser). See `README.md` for the details.
