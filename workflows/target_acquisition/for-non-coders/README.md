# Target acquisition workflow for non-coders

> We have tested these installation steps, but we cannot guarantee that they work on every system. We have found that agentic AI coding tools, such as Claude Code, Codex or GitHub Copilot, are often very good at fixing installation problems. If something still fails, please open an [issue](https://github.com/ZMB-UZH/ZMART-microscopy/issues).

## The workflow

The [ZMART Interface](https://github.com/ZMB-UZH/ZMART-interface) runs the whole target acquisition workflow in one window, without code: it scans an overview, finds targets in it, and images the targets.

To build your own workflow in code instead, see the [target acquisition workflow for coders](../for-coders/).

On a ZMB workstation, read [where things must live](https://github.com/ZMB-UZH/ZMART-interface/blob/v0.1.0rc6/docs/install-on-a-microscope.md#where-things-must-live) first: programs only run from `C:\ProgramData\MinicondaZMB`.

## 1. Install the driver and controller

In a conda prompt, clone the repository, and create and activate the base environment. It installs the ZMART Controller:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-non-coders
conda env create -f environment.yml
conda activate zmart-for-non-coders
```

Install the driver for your microscope. The part in brackets selects it:

| Microscope | Connects through | In brackets | Manual |
|---|---|---|---|
| Leica STELLARIS | LAS X Navigator Expert | `leica` | [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md) |

```bash
pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b8"
```

Then configure the driver and register it with the controller, once, as the driver's manual describes: [setting up the driver](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md#setting-up-the-driver) and [through the ZMART Controller](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md#how-to-call-the-driver).

## 2. Install the rest

One script does the rest. `--output-root` is the folder your runs are saved in; choose one on the drive the microscope saves to:

```bash
python install.py --output-root D:\ZMART-data
```

It adds the ZMART Interface 0.1.0rc6 to the base environment, with the viewer and the analysis engine it was tested with. It clones ZMART Analysis 0.6.0rc9 next to `ZMART-microscopy` and makes the environments of its `focus` and `object_analysis` workflows. It writes a launcher, `zmart-interface.bat`, into the base environment's folder, with a shortcut, **ZMART Interface**, on the desktop.

An environment that already exists is kept. To rebuild one from an earlier version, remove it first with `conda env remove -n <name>`. `python install.py --output-root D:\ZMART-data --dry-run` shows what it would do.

The first time the robust detection runs, Cellpose downloads its trained network, once, so do that first run while the computer is online.

## 3. Run the interface

Start the microscope's own software first (LAS X, on the STELLARIS). Then double-click **ZMART Interface** on the desktop.

Pick your microscope on the first step and follow the steps. To try the workflow without a microscope, pick **Mock**.
