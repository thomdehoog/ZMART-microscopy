# Target acquisition workflow for coders

## The workflow

This workflow provides a template [Jupyter notebook](template/target_acquisition_template.ipynb) that runs a target acquisition workflow: it images overview positions, finds targets in them, and images the targets. It is meant as a starting point to develop your own workflow.

It is intentionally **a simplified example** and **not an end-to-end solution**. For an end-to-end example, we refer to the [target acquisition workflow for non-coders](../for-non-coders/).

## 1. Install the driver, controller and analysis

Clone the repository, and create and activate the base environment:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
conda env create -f environment.yml
conda activate zmart-for-coders
```

Install the driver for your microscope. The part in brackets selects it:

| Microscope | Connects through | In brackets | Manual |
|---|---|---|---|
| Leica STELLARIS | LAS X Navigator Expert | `leica` | [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b8/zmart_drivers/leica/stellaris/navigator_expert/README.md) |

```bash
pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b8"
```

Install the controller and the analysis engine, and create the environment the [analysis](template/analysis/) runs in:

```bash
pip install "zmart-controller @ git+https://github.com/ZMB-UZH/ZMART-controller@v0.4.0rc7"
pip install "zmart-analysis @ git+https://github.com/ZMB-UZH/ZMART-analysis@v0.6.0rc9"
conda env create -f analysis/environments/classical.yml
```

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

## 3. Run the notebook

```bash
conda activate zmart-for-coders
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
jupyter lab target_acquisition_template.ipynb
```
