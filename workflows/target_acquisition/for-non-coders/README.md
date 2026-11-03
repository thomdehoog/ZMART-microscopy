# Target acquisition workflow for non-coders

> We have tested these installation steps, but we cannot guarantee that they work on every system. We have found that agentic AI coding tools, such as Claude Code, Codex or GitHub Copilot, are often very good at fixing installation problems. If something still fails, please open an [issue](https://github.com/ZMB-UZH/ZMART-microscopy/issues).

## The workflow

The [ZMART Interface](https://github.com/ZMB-UZH/ZMART-interface) runs the whole target acquisition workflow in one window, without code: it scans an overview, finds targets in it, and images the targets.

To build your own workflow in code instead, see the [target acquisition workflow for coders](../for-coders/).

On a ZMB workstation, read [where things must live](https://github.com/ZMB-UZH/ZMART-interface/blob/v0.2.0rc7/docs/install-on-a-microscope.md#where-things-must-live) first: programs only run from the folders AppLocker approves on that computer, so conda, its environments and this repository must be in one of them. `conda info` shows where conda is and where it makes environments.

## 1. Install

In a conda prompt (Miniforge Prompt), clone the repository and run the setup with conda's base Python. `--output-root` is the folder your runs are saved in; choose one on the drive the microscope saves to:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy
python setup_zmart.py --microscope leica --output-root D:\ZMART-data
```

| Microscope | Connects through | `--microscope` | Manual |
|---|---|---|---|
| Leica STELLARIS | LAS X Navigator Expert | `leica` | [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b11/zmart_drivers/leica/stellaris/navigator_expert/README.md) |
| none: try the workflow first | | `mock` | |

The setup makes the environment `zmart-for-non-coders` and installs the ZMART blocks into it at the releases in [`releases.toml`](../../../releases.toml), with the driver for your microscope, which it registers with the ZMART Controller. Next to `ZMART-microscopy`, it clones the interface's target acquisition workflow (the steps you click through) and ZMART Analysis, and makes the environments of the `focus` and `object_analysis` analysis. It asks whether to make the large Cellpose environment for the robust detection (`--cellpose` or `--no-cellpose` answers on the command line). It puts an icon, **ZMART interface**, on the desktop, then checks everything end to end and ends with **"ZMART is ready."** or a list of what did not work.

When it is not ready, open Claude Code in `ZMART-microscopy` and say: *Read .claude/agents/zmart-install-doctor.md and follow it.* `python setup_zmart.py --check` runs the checks again without installing anything. An environment that already exists is kept; to rebuild one, remove it first with `conda env remove -n <name>`.

The first time the robust detection runs, Cellpose downloads its trained network, once, so do that first run while the computer is online.

## 2. Set up the driver

Once per microscope, set the driver up as its manual describes: [setting up the driver](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b11/zmart_drivers/leica/stellaris/navigator_expert/README.md#setting-up-the-driver). A microscope that was set up before keeps its settings.

## 3. Run the interface

Start the microscope's own software first (LAS X, on the STELLARIS). Then double-click **ZMART interface** on the desktop.

Pick your microscope on the first step and follow the steps. To try the workflow without a microscope, pick **Mock**.
