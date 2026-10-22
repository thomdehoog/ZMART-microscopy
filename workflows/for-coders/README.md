# Target acquisition workflow for coders

The [target acquisition template](target_acquisition_template.ipynb) drives the microscope with the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller): image overview positions, find dividing cells, and image them again.

## 1. Install

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

Make the environment the object analysis runs in:

```bash
python -m zmart_analysis.environments object_analysis --step classical
```

## 2. Configure the driver

Set up the travel limits, image orientation, objective calibration and zero point once, with the notebooks in the [Leica driver's](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b2/zmart_drivers/leica/stellaris/navigator_expert/README.md) `driver_setup` folder.

## 3. Register the driver

Register it once with the ZMART Controller: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc4/docs/plug_in_a_driver/README.md).

## 4. Open the notebook

```bash
jupyter lab workflows/for-coders/target_acquisition_template.ipynb
```
