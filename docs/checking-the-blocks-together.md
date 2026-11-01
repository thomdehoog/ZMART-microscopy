# Checking the blocks together

This page is for the people who develop ZMART. To *use* ZMART, follow the
"Install ZMART" section of the [README](../README.md) instead: `setup_zmart.py`
installs the released versions and checks them.

`install.py` is the test bench: it installs the five blocks, from branches
when asked, into one environment (`zmart-integration`), together with what
the checks in `tests/` and the walk (`run_walk.py`) need.

## Try it yourself

You need conda (Miniforge or Miniconda, used with conda-forge only) and an internet connection.
From a clone of this repository:

```bash
python install.py                    # the environment, the five blocks, and what the checks need
conda activate zmart-integration
python -m pytest tests               # the plug-in checks, a few minutes
python run_walk.py                   # the operator window, end to end, 10 to 30 minutes
```

To check the blocks together before they are promoted to `main`, install a branch of each:
`--branch release-candidate` takes that branch of every block, and `--branch zmart-analysis=main`
(given as well) keeps one block on another branch. The blocks are then installed at those
branches without their requirements first, and their requirements afterwards, because each block
names the others by their plain GitHub address and pip refuses one package asked for at two.

To check work in another GitHub account before it is brought to the ZMB's repositories, name the
account with `--github`. For example, the change that moved the workflows here is checked with:

```bash
python install.py --github thomdehoog --branch release-candidate \
    --branch zmart-analysis=examples-and-workflows --branch zmart-interface=examples-and-workflows
```

`install.py` creates the environment `zmart-integration` from [`environment.yml`](../environment.yml)
(conda-forge only), installs the five blocks with pip straight from GitHub, clones the controller
and the interface into `work/` (for the controller's mock driver, and for the interface's tools,
which build the operator page from our workflows and run their walk; neither is part of a
package), makes the analysis environments the walk needs from the pipelines in
`workflows/non-coders/analysis` if they are missing, and installs the walk's Node.js tools and
Chromium. What was installed, at which commit,
is written to `work/install-record.json`; the walk keeps a screenshot of every screen and its log
in `work/walk/<date>/`.

**On Windows computers where programs may only run from approved folders** (AppLocker), keep
this repository and the environment in an approved folder, and point `PLAYWRIGHT_BROWSERS_PATH`
and `TMPDIR` at approved folders too: the analysis engine starts each step with `conda run`,
which writes a small script to the temporary folder and runs it.

## Status

This is a release candidate, 0.1.0rc1: the first in which the workflows live here. It has been
checked on Linux on 1 November 2026, with the blocks from the `thomdehoog` account (the command
above): the plug-in checks pass, except the two that run the analysis in its conda environments,
which that computer did not have; our page check passes; and the walk passes, through all ten
steps, on our own Target acquisition. The full check on a Windows workstation is still to come.

Before that, the earlier release candidate was checked like this. The latest run, on a Windows 11 workstation on 11 October 2026,
checked the blocks together before their promotion to `main`: the `release-candidate` branch of
the controller (0.2.0, `4b9ac5c`), the drivers (0.1.0rc1, `6710a7b`), the viewer (0.5.0rc4,
`5a291df`) and the interface (0.1.0rc1, `24a0a0f`), with the analysis engine from `main`
(1.0.0rc1, `80ab373`), whose `release-candidate` branch is older than its `main`:

```bash
python install.py --branch release-candidate --branch zmart-analysis=main
```

| What was checked | Result |
|---|---|
| The install, and `pip check` | passes |
| The plug-in checks (`tests/`) | all 30 pass |
| The walk: all ten steps of the operator window on the kidney mock, against the installed blocks | passes (about 3 minutes) |

On 24 October 2026 the release candidates were checked again, on Linux: the controller
(0.4.0rc7), the drivers (0.7.0b8), the viewer (0.5.0rc8), the analysis (0.6.0rc6) and the
interface (0.1.0rc5), with `python install.py --branch release-candidate`. The install and
`pip check` pass, and the 26 plug-in checks pass. The walk was not run then: the computer could
not download Playwright's browser.

On Windows, pip can fail to build the drivers with "could not create ... No such file or
directory": some of the drivers' file paths are long, and pip builds them inside the temporary
folder, so together they can pass Windows' limit of 260 characters. Point `TMP` and `TEMP` at a
short folder (such as `D:\t`) while installing, or turn on Windows' long paths. The analysis
environments still need `TMPDIR` in an approved folder when the checks run (see above).

The drivers' package holds the Leica driver. The checks here install it and list it, and take
pictures only on the two mock microscopes, because a real driver needs its microscope.

## Testing

The plug-in checks are in [`tests/`](../tests), one file per place where blocks meet:

| File | What it asks |
|---|---|
| `test_installed_versions.py` | `pip check` passes; every block came from its GitHub repository; each clone is at the installed commit; the interface accepts the installed viewer; the versions are written down |
| `test_drivers_plug_in.py` | every driver in the drivers' package installs into the controller from its folder (the one that holds `zmart_controller_plugin/`) and is listed; both mock microscopes pass the controller's `validate_driver`; the two mocks stand side by side, each calling its own plugin |
| `test_analysis_runs.py` | the engine finds the sharp plane of a focus stack in its own environment, directly and through the interface |
| `test_viewer_serves.py` | a capture from either mock fits the controller's contract, is kept by the interface the way its bridge keeps a scan's field (the driver's own OME-Zarr store, or one written from its files), and is served by the viewer |
| `test_bridge_answers.py` | the interface's bridge lists the kidney mock first, serves the page, answers before Connect, passes a capture on as the controller's answer, keeps its own mock when another driver is installed under that name, and the walk's bridge runs the installed interface |
| `test_setup_zmart.py` | the installer, `setup_zmart.py`: its parts, and whole runs on a stand-in computer (one that works, one where conda cannot make an environment, one where a step does not load) |
| `test_our_page_is_built.py` | the operator page committed beside our workflows is exactly what the interface's build makes from them |

The checks run our own workflow, *Target acquisition* in `workflows/non-coders/interface`, on our
own pipelines in `workflows/non-coders/analysis`: the interface is pointed at that folder
(`ZMART_INTERFACE_WORKFLOWS`), as a microscope PC is. Each copy of the analysis pipelines has its
own tests too, run from its folder (`workflows/README.md` says how).

Every check gets an empty ZMART configuration folder of its own, and each driver is plugged in in
a fresh Python, so nothing on the computer changes the answer and nothing is left behind.

The continuous integration in [`.github/workflows/assembly.yml`](../.github/workflows/assembly.yml)
runs every night and on demand, on the blocks' `release-candidate` branches: the plug-in checks on
Ubuntu and Windows with Python 3.12, and the walk on Ubuntu.
