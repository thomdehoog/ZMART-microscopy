# Target acquisition workflow for coders

The [target acquisition notebook](target_acquisition.ipynb) drives the microscope with the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller): image overview positions, find dividing cells, and image them again.

## 1. Make the environment

```bash
conda create -n zmart -c conda-forge -c nodefaults python=3.12 pip git jupyterlab
conda activate zmart
```

## 2. Install the ZMART Controller and the Leica driver

The driver brings the controller with it.

```bash
pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@release-candidate"
```

## 3. Install ZMART analysis

In this repository's folder:

```bash
git clone -b release-candidate https://github.com/ZMB-UZH/ZMART-analysis work/ZMART-analysis
pip install -e work/ZMART-analysis
python work/ZMART-analysis/workflows/object_analysis/environments/setup_env.py --step classical
```

## 4. Configure the driver

Set up the travel limits, image orientation, objective calibration and zero point once, with the notebooks in the [Leica driver's](https://github.com/ZMB-UZH/ZMART-drivers/blob/release-candidate/zmart_drivers/leica/stellaris_y42h93/navigator_expert/README.md) `driver_setup` folder.

## 5. Register the driver

Register it once with the ZMART Controller: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/release-candidate/docs/plug_in_a_driver/README.md).

## 6. Open the notebook

```bash
jupyter lab workflows/for-coders/target_acquisition.ipynb
```
