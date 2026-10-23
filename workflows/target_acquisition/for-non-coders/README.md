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

Create the base environment, and activate it. It holds the ZMART Interface, with the ZMART Controller, Viewer and Analysis it was tested with:

```bash
conda env create -f environment.yml
conda activate zmart-for-non-coders
```

### 2. Install the ZMART driver for your microscope, and configure it

Install the driver for your microscope, and configure it once:

| Microscope | Connection | Install the driver | Manual |
|---|---|---|---|
| Leica STELLARIS | LAS X Navigator Expert | `pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b6"` | [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b6/zmart_drivers/leica/stellaris/navigator_expert/README.md) |

### 3. Register the ZMART driver with the ZMART Controller

The controller came with the interface. Register the driver with it once: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc7/docs/plug_in_a_driver/README.md).

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

## Run

Start the microscope's own software first (LAS X, on the STELLARIS). Then:

```bash
conda activate zmart-for-non-coders
zmart-interface --output-root D:\ZMART-data
```

`--output-root` is the folder your runs are saved in; choose one on the drive the microscope saves to. Pick your microscope on the first step and follow the steps. To try the workflow without a microscope, pick **Mock**.
