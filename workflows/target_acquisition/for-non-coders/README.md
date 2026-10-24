# Target acquisition workflow for non-coders

## The workflow

The [ZMART Interface](https://github.com/ZMB-UZH/ZMART-interface) runs the whole target acquisition workflow in one window, without code: it scans an overview, finds targets in it, and images the targets.

It drives the microscope through the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller), so it works on any microscope that has a ZMART driver. The focus map and the detection are done by the example workflows of [ZMART Analysis](https://github.com/ZMB-UZH/ZMART-analysis).

To build your own workflow in code instead, see the [target acquisition workflow for coders](../for-coders/).

On a ZMB workstation, read [where things must live](https://github.com/ZMB-UZH/ZMART-interface/blob/v0.1.0rc5/docs/install-on-a-microscope.md#where-things-must-live) first: programs only run from `C:\ProgramData\MinicondaZMB`.

## Install

### 1. Install the base environment

Clone the repository:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-non-coders
```

Create the base environment, and activate it:

```bash
conda env create -f environment.yml
conda activate zmart-for-non-coders
```

This installs the ZMART Interface, and with it the parts it was tested with:

| Part | Version |
|---|---|
| [ZMART Interface](https://github.com/ZMB-UZH/ZMART-interface) | 0.1.0rc5 |
| [ZMART Viewer](https://github.com/ZMB-UZH/ZMART-viewer) | 0.5.0rc8 |
| [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller) | 0.4.0rc7 |
| [ZMART Analysis](https://github.com/ZMB-UZH/ZMART-analysis) (the engine) | 0.6.0rc5 |

### 2. Install the ZMART driver for your microscope, and configure it

Install the driver for your microscope, and configure it once:

| Microscope | Connection | Install the driver | Manual |
|---|---|---|---|
| Leica STELLARIS | LAS X Navigator Expert | `pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b8"` | [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md) |

Configuring means telling the driver, once, about this microscope: where its pictures go, how far
the stage may travel, which point counts as zero, and how its images and objectives line up. The
Leica driver has a setup wizard that walks you through these steps one by one; its manual explains
each of them under [Setting up the driver](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md#setting-up-the-driver). Start it on the computer that runs LAS X:

```bash
python -m zmart_drivers.leica.stellaris.navigator_expert.driver_setup.wizard
```

### 3. Register the ZMART driver with the ZMART Controller

The controller came with the interface. Register the driver with it once: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc7/docs/plug_in_a_driver/README.md). For the Leica driver installed in step 2, this is one command; it prints `stellaris`, the name you connect with:

```bash
python -c "from pathlib import Path; import zmart_drivers.leica.stellaris.navigator_expert as d; from zmart_controller import mic; print(mic.register_driver(Path(d.__file__).parent))"
```

### 4. Install the analysis

The focus map and the detection run the `focus` and `object_analysis` workflows of ZMART Analysis, each in its own environment. Clone them at the version the interface was tested with, next to `ZMART-microscopy`, and create their environments:

```bash
cd ../../../..
git clone -b v0.6.0rc5 https://github.com/ZMB-UZH/ZMART-analysis
conda env create -f ZMART-analysis/workflows/focus/environments/main.yml
conda env create -f ZMART-analysis/workflows/object_analysis/environments/classical.yml
conda env create -f ZMART-analysis/workflows/object_analysis/environments/cellpose.yml
conda env create -f ZMART-analysis/workflows/object_analysis/environments/umap.yml
```

`cellpose.yml` is needed for the robust detection only, `umap.yml` for the population plots only.

Tell the interface where the analysis is, with the full path of the `ZMART-analysis` folder, and activate the environment again:

```bash
conda env config vars set -n zmart-for-non-coders ZMART_ANALYSIS_WORKFLOWS=<full path>/ZMART-analysis
conda activate zmart-for-non-coders
```

## Check it at the microscope

Before the first experiment, check that the driver and the controller work together on this computer. The driver brings its own checks; they are not part of the installed package, so clone the driver at the same version, add what the checks need, and run them from the folder that holds the clone:

```bash
conda activate zmart-for-non-coders
pip install "zmart-drivers[leica,test] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b8"
git clone -b v0.7.0b8 https://github.com/ZMB-UZH/ZMART-drivers
python ZMART-drivers/zmart_drivers/leica/stellaris/navigator_expert/testing/run_ci.py --controller
```

This first run needs no microscope, and takes about five minutes. Then start LAS X, first in its simulator mode, and run the checks against it:

```bash
python ZMART-drivers/zmart_drivers/leica/stellaris/navigator_expert/testing/run_ci.py --hardware --controller
```

What to know before you start it:

- **The stage moves.** It goes to a fixed starting point (X 63,500 µm, Y 41,500 µm, both z drives at 0), makes small moves around it, and takes a few pictures. Make sure nothing on the stage can be damaged, and leave the room clear for it.
- **The saved settings stay as they are.** The setup wizard is checked in a copy of the settings folder, and the check fails if the real one changed.
- **The controller's `stellaris` now points at the clone.** One check registers the cloned driver, so that the code under test is the code that runs. Keep the clone, or register the installed driver again with the command in step 3.

Every line of the summary should say `OK`. The reports, one per check, are in `ZMART-drivers/zmart_drivers/leica/stellaris/navigator_expert/testing/report/`. Run the same command on the microscope itself only after it passes on the simulator.

## Run

Start the microscope's own software first (LAS X, on the STELLARIS). Then:

```bash
conda activate zmart-for-non-coders
zmart-interface --output-root D:\ZMART-data
```

`--output-root` is the folder your runs are saved in; choose one on the drive the microscope saves to. Pick your microscope on the first step and follow the steps. To try the workflow without a microscope, pick **Mock**.
