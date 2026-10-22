# Target acquisition workflow for coders

The [target acquisition notebook](target_acquisition_template.ipynb) drives the microscope with the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller): image overview positions, find dividing cells, and image them again.

## 1. Install

In a clone of this repository.

Get ZMART analysis:

```bash
git clone -b release-candidate https://github.com/ZMB-UZH/ZMART-analysis work/ZMART-analysis
```

Make the environment:

```bash
conda env create -f workflows/for-coders/environment.yml
```

Activate it:

```bash
conda activate zmart-coders
```

Make the environment the object analysis runs in:

```bash
python work/ZMART-analysis/workflows/object_analysis/environments/setup_env.py --step classical
```

This installs the ZMART Controller, the Leica driver, ZMART analysis and the environment its object analysis runs in.

## 2. Configure the driver

Set up the travel limits, image orientation, objective calibration and zero point once, with the notebooks in the [Leica driver's](https://github.com/ZMB-UZH/ZMART-drivers/blob/release-candidate/zmart_drivers/leica/stellaris_y42h93/navigator_expert/README.md) `driver_setup` folder.

## 3. Register the driver

Register it once with the ZMART Controller: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/release-candidate/docs/plug_in_a_driver/README.md).

## 4. Open the notebook

```bash
jupyter lab workflows/for-coders/target_acquisition_template.ipynb
```
