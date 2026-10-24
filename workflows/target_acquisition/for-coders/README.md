# Target acquisition workflow for coders

## The workflow

This workflow consists of a template [Jupyter notebook](template/target_acquisition_template.ipynb) that runs a target acquisition workflow: it images overview positions, finds targets in them, and images the targets.

It is intentionally **a simplified example** and **not an end-to-end solution**. It is meant as a starting point to develop your own workflow with. For an end-to-end example, we refer to the [target acquisition workflow for non-coders](../for-non-coders/).

For the template we are using the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller), because its simple, universal vocabulary makes the workflow a good starting point for any microscope that has a ZMART driver. As an example, we filter for dividing cells with a simple metric, using analysis done with the [ZMART analysis](https://github.com/ZMB-UZH/ZMART-analysis) pipeline.

## Install

### 1. Install the base environment

Clone the repository:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
```

Create the base environment, and activate it:

```bash
conda env create -f environment.yml
conda activate zmart-for-coders
```

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

You can stop here if you want just the driver: it works on its own, as its manual describes.

However, we do not provide a template target acquisition workflow for this. For the target acquisition workflow, follow through to step 4.

### 3. Install the ZMART Controller, and register the ZMART driver of interest

We provide a template workflow for target acquisition through the vocabulary of the ZMART Controller. The controller provides one unified language for every microscope with a ZMART driver, so workflows built on it are interoperable, and easier to test and share.

```bash
pip install "zmart-controller @ git+https://github.com/ZMB-UZH/ZMART-controller@v0.4.0rc7"
```

Register the driver with it once: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc7/docs/plug_in_a_driver/README.md). For the Leica driver installed in step 2, this is one command; it prints `stellaris`, the name you connect with:

```bash
python -c "from pathlib import Path; import zmart_drivers.leica.stellaris.navigator_expert as d; from zmart_controller import mic; print(mic.register_driver(Path(d.__file__).parent))"
```

### 4. Install ZMART analysis for the target acquisition template

To run the analysis in the target acquisition template, install the ZMART analysis engine and the environment its [`analysis`](template/analysis/) runs in:

```bash
pip install "zmart-analysis @ git+https://github.com/ZMB-UZH/ZMART-analysis@v0.6.0rc5"
conda env create -f analysis/environments/classical.yml
```

## Check it at the microscope

Before the first experiment, check that the driver and the controller work together on this computer. The driver brings its own checks; they are not part of the installed package, so clone the driver at the same version, add what the checks need, and run them from the folder that holds the clone:

```bash
conda activate zmart-for-coders
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

```bash
conda activate zmart-for-coders
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
jupyter lab target_acquisition_template.ipynb
```
