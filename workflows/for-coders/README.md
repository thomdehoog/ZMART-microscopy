# Target acquisition workflow for coders

Image overview positions, find targets, and image them again, from a [Jupyter notebook](target_acquisition_template.ipynb). The targets here are dividing cells, found with [ZMART analysis](https://github.com/ZMB-UZH/ZMART-analysis), as an example; choose your own targets, or bring your own analysis, in the notebook.

**You need:** conda, git, access to [ZMB-UZH](https://github.com/ZMB-UZH) on GitHub, and LAS X on the microscope PC.

## 1. Install (once per computer)

Clone the repository:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy
```

Create the conda environment for the notebook, and activate it:

```bash
conda env create -f workflows/for-coders/environment.yml
conda activate zmart-coders
```

Create the conda environment for the image analysis. ZMART analysis is optional, but this example needs it; it runs in an environment of its own, so its tools never clash with the notebook's:

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
