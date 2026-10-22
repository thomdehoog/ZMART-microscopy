# Target acquisition workflow for coders

Image overview positions, find targets, and image them again, from a [Jupyter notebook](target_acquisition_template.ipynb). The targets here are dividing cells, as an example; choose your own in the notebook.

**You need:** conda, git, access to [ZMB-UZH](https://github.com/ZMB-UZH) on GitHub, and LAS X on the microscope PC.

## 1. Install (once per computer)

Get this repository:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
```

Go into it:

```bash
cd ZMART-microscopy
```

Make the environment:

```bash
conda env create -f workflows/for-coders/environment.yml
```

Activate it:

```bash
conda activate zmart-coders
```

Make the environment the analysis runs in:

```bash
python -m zmart_analysis.environments object_analysis --step classical
```

## 2. Set up the microscope (once per microscope)

Configure the driver: set the travel limits, image orientation, objective calibration and zero point with the notebooks in the [Leica driver's](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b2/zmart_drivers/leica/stellaris/navigator_expert/README.md) `driver_setup` folder.

Register the driver with the ZMART Controller: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc4/docs/plug_in_a_driver/README.md).

## 3. Run (every time)

Activate the environment:

```bash
conda activate zmart-coders
```

Open the notebook:

```bash
jupyter lab workflows/for-coders/target_acquisition_template.ipynb
```
