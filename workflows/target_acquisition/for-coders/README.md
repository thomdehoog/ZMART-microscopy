# Target acquisition workflow for coders

> We have tested these installation steps, but we cannot guarantee that they work on every system. We have found that agentic AI coding tools, such as Claude Code, Codex or GitHub Copilot, are often very good at fixing installation problems. If something still fails, please open an [issue](https://github.com/ZMB-UZH/ZMART-microscopy/issues).

## The workflow

This workflow provides a simplified template [Jupyter notebook](template/target_acquisition_template.ipynb) that gets you started with building a target acquisition workflow.

It is **intentionally not an end-to-end solution**. It is meant as a starting point to develop your own workflow.

For an end-to-end example, we refer to the [target acquisition workflow for non-coders](../for-non-coders/).

## 1. Install the driver and controller

The setup can do steps 1 and 2 for you, from the top folder of `ZMART-microscopy` and with conda's base Python: `python setup_zmart.py --coder --microscope leica`. It also installs the operator window, and checks both end to end. By hand, it goes like this.

In a conda prompt, clone the repository, and create and activate the base environment:

```bash
git clone -b example-workflows https://github.com/ZMB-UZH/ZMART-microscopy
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
conda env create -f environment.yml
conda activate zmart-for-coders
```

Install the driver for your microscope, and the controller. The part in brackets selects the driver:

| Microscope | Connects through | In brackets | Manual |
|---|---|---|---|
| Leica STELLARIS | LAS X Navigator Expert | `leica` | [manual](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b9/zmart_drivers/leica/stellaris/navigator_expert/README.md) |

```bash
pip install "zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@v0.7.0b9"
pip install "zmart-controller @ git+https://github.com/ZMB-UZH/ZMART-controller@v0.4.0rc8"
```

Then configure the driver and register it with the controller, once, as the driver's manual describes: [setting up the driver](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b9/zmart_drivers/leica/stellaris/navigator_expert/README.md#setting-up-the-driver) and [through the ZMART Controller](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b9/zmart_drivers/leica/stellaris/navigator_expert/README.md#how-to-call-the-driver).

## 2. Install the rest

Install the analysis engine, and create the environment the [analysis](template/analysis/) runs in:

```bash
pip install "zmart-analysis @ git+https://github.com/ZMB-UZH/ZMART-analysis@v0.6.0rc9"
conda env create -f analysis/environments/classical.yml
conda env create -f focus/environments/main.yml   # optional: the focus routine
```

## 3. Run the notebook

```bash
conda activate zmart-for-coders
cd ZMART-microscopy/workflows/target_acquisition/for-coders/template
jupyter lab target_acquisition_template.ipynb
```
