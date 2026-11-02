# Target acquisition workflow for non-coders

## The workflow

The [ZMART Interface](https://github.com/ZMB-UZH/ZMART-interface) runs the whole target acquisition workflow in one window, without code: it scans an overview, finds targets in it, and images the targets.

To build your own workflow in code instead, see the [target acquisition workflow for coders](../for-coders/).

On a ZMB workstation, read [where things must live](https://github.com/ZMB-UZH/ZMART-interface/blob/v0.1.0rc6/docs/install-on-a-microscope.md#where-things-must-live) first: programs only run from `C:\ProgramData\MinicondaZMB`.

## 1. Install the interface, driver and analysis

Clone the repository, and create and activate the base environment. It installs the ZMART Interface 0.1.0rc6, and with it the controller, the viewer and the analysis engine it was tested with:

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

Install the analysis: the `focus` and `object_analysis` workflows of ZMART Analysis 0.6.0rc9, next to `ZMART-microscopy`, each in its own environment. If environments of an earlier version exist, remove them first with `conda env remove -n <name>`:

```bash
cd ../../../..
git clone -b v0.6.0rc9 https://github.com/ZMB-UZH/ZMART-analysis
conda env create -f ZMART-analysis/examples/focus/environments/main.yml
conda env create -f ZMART-analysis/examples/object_analysis/environments/classical.yml
conda env create -f ZMART-analysis/examples/object_analysis/environments/cellpose.yml   # robust detection only
conda env create -f ZMART-analysis/examples/object_analysis/environments/umap.yml       # population plots only
conda env config vars set -n zmart-for-non-coders ZMART_ANALYSIS_WORKFLOWS=<full path>/ZMART-analysis/examples
conda activate zmart-for-non-coders
```

The first time the robust detection runs, Cellpose downloads its trained network, once, so do that first run while the computer is online.

## 2. Set up the driver and controller

### Set up the driver

Set up the driver once for this microscope. For the Leica STELLARIS, start the setup wizard on the computer that runs LAS X; the [Leica driver's manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md#setting-up-the-driver) explains each step, and its [checks at the microscope](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/testing/hardware/README.md) are worth running before the first experiment:

```bash
python -m zmart_drivers.leica.stellaris.navigator_expert.driver_setup.wizard
```

### Set up the controller

Register the driver with the controller, once, as the [controller's guide](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc7/docs/plug_in_a_driver/README.md) describes. It prints `stellaris`, the name you connect with:

```bash
python -c "from pathlib import Path; import zmart_drivers.leica.stellaris.navigator_expert as d; from zmart_controller import mic; print(mic.register_driver(Path(d.__file__).parent))"
```

## 3. Run the interface

Start the microscope's own software first (LAS X, on the STELLARIS). Then:

```bash
conda activate zmart-for-non-coders
zmart-interface --output-root D:\ZMART-data
```

`--output-root` is the folder your runs are saved in; choose one on the drive the microscope saves to. Pick your microscope on the first step and follow the steps. To try the workflow without a microscope, pick **Mock**.
