# Target acquisition workflow for coders

## The workflow

This workflow consists of a template [Jupyter notebook](template/target_acquisition_template.ipynb) that runs a target acquisition workflow: it images overview positions, finds targets in them, and images the targets. It is meant as a starting point to develop your own workflow.

It is intentionally **a simplified example** and **not an end-to-end solution**. For an end-to-end example, we refer to the [target acquisition workflow for non-coders](../for-non-coders/).

The notebook drives the microscope through the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller), so it runs on any microscope with a ZMART driver, and finds the targets with the [ZMART analysis](https://github.com/ZMB-UZH/ZMART-analysis) engine.

## 1. Install

Clone the repository, and create and activate the base environment:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
conda env create -f environment.yml
conda activate zmart-for-coders
```

Install the driver for your microscope, the controller and the analysis engine, and create the environment the [analysis](template/analysis/) runs in:

```bash
pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b8"
pip install "zmart-controller @ git+https://github.com/ZMB-UZH/ZMART-controller@v0.4.0rc7"
pip install "zmart-analysis @ git+https://github.com/ZMB-UZH/ZMART-analysis@v0.6.0rc9"
conda env create -f analysis/environments/classical.yml
```

The driver above is for a Leica STELLARIS with LAS X Navigator Expert.

## 2. Set up the driver

Tell the driver, once, about this microscope: where its pictures go, how far the stage may travel, which point counts as zero, and how its images and objectives line up. The setup wizard walks you through this; the [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md#setting-up-the-driver) explains each step. Start it on the computer that runs LAS X:

```bash
python -m zmart_drivers.leica.stellaris.navigator_expert.driver_setup.wizard
```

Then register the driver with the controller, once ([how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc7/docs/plug_in_a_driver/README.md)). It prints `stellaris`, the name you connect with:

```bash
python -c "from pathlib import Path; import zmart_drivers.leica.stellaris.navigator_expert as d; from zmart_controller import mic; print(mic.register_driver(Path(d.__file__).parent))"
```

### Check it at the microscope

Before the first experiment, check that the driver and the controller work together on this computer. The checks are not part of the installed package, so clone the driver at the same version and run them from the folder that holds the clone:

```bash
pip install "zmart-drivers[leica,test] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b8"
git clone -b v0.7.0b8 https://github.com/ZMB-UZH/ZMART-drivers
python ZMART-drivers/zmart_drivers/leica/stellaris/navigator_expert/testing/run_ci.py --controller
```

This first run needs no microscope and takes about five minutes. Then start LAS X in its simulator mode, and run the checks against it:

```bash
python ZMART-drivers/zmart_drivers/leica/stellaris/navigator_expert/testing/run_ci.py --hardware --controller
```

- **The stage moves.** It goes to X 63,500 µm, Y 41,500 µm, both z drives at 0, makes small moves around it, and takes a few pictures. Make sure nothing on the stage can be damaged.
- **The saved settings stay as they are.** The wizard is checked in a copy of the settings folder.
- **The controller's `stellaris` now points at the clone.** Keep the clone, or register the installed driver again with the command above.

Every line of the summary should say `OK`. The reports are in `ZMART-drivers/zmart_drivers/leica/stellaris/navigator_expert/testing/report/`. Run the same command on the microscope itself only after it passes on the simulator.

## 3. Run the notebook

```bash
conda activate zmart-for-coders
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
jupyter lab target_acquisition_template.ipynb
```
