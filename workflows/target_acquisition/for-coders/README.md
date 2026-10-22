# Target acquisition workflow for coders

Image overview positions, find targets, and image them again, from a [Jupyter notebook](target_acquisition_template.ipynb). The targets here are dividing cells, found with [ZMART analysis](https://github.com/ZMB-UZH/ZMART-analysis), as an example; choose your own targets, or bring your own analysis, in the notebook.

## 1. Install the base environment

Clone the repository:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-coders
```

Create the base environment, and activate it:

```bash
conda env create -f environment.yml
conda activate zmart-for-coders
```

## 2. Install the ZMART driver for your microscope, and configure it

Install the driver for the Leica STELLARIS:

```bash
pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b3"
```

Configure it once per microscope: [how](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b3/zmart_drivers/leica/stellaris/navigator_expert/README.md#3-configuration).

You can stop here if you want just the driver: it works on its own. See the [ZMART driver's manual for the Leica STELLARIS through Navigator Expert](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b3/zmart_drivers/leica/stellaris/navigator_expert/README.md); we do not provide a full workflow for this. For the target acquisition workflow, follow through to step 4.

## 3. Install the ZMART Controller, and register the driver

We provide a template workflow for target acquisition through the vocabulary of the ZMART Controller. The controller provides one unified language for every microscope with a ZMART driver, so workflows built on it are interoperable, and easier to test and share.

```bash
pip install "zmart-controller @ git+https://github.com/ZMB-UZH/ZMART-controller@v0.4.0rc4"
```

Register the driver with it once: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/v0.4.0rc4/docs/plug_in_a_driver/README.md).

## 4. Install ZMART analysis for the example

To benefit from ZMART analysis in the template, install it: the engine, and the environment its [`analysis`](analysis/) runs in, so its tools never clash with the notebook's.

```bash
pip install "zmart-analysis @ git+https://github.com/ZMB-UZH/ZMART-analysis@v0.6.0rc3"
python analysis/environments/setup_env.py --step classical
```

## 5. Run

```bash
conda activate zmart-for-coders
cd ZMART-microscopy/workflows/target_acquisition/for-coders
jupyter lab target_acquisition_template.ipynb
```
