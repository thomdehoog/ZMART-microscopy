# Your first experiment

`example_experiment.ipynb`, next to this page, runs a whole experiment on the
mock microscope. No hardware needed. Once it runs, it is the template for your
own workflow.

## Install

Python 3.12 or newer.

```bash
pip install "git+https://github.com/thomdehoog/ZMART-microscopy@release-candidate-zmart-controller"
pip install jupyterlab
```

## Run it

```bash
jupyter lab
```

Open `example_experiment.ipynb` and run the cells in order with Shift+Enter.
Each cell has a short note above it.

## Make it yours

- **A real microscope.** Delete the setup cell. Your driver is already plugged
  in; pick it by name in step 1.
- **Your positions.** Edit the list in step 3. Stay inside the range that
  `get_xyz()` reports.
- **Your settings.** `get_state()["report"]["changeable"]` shows what your
  driver lets you change.
- **The smart part.** Between the overview and the detailed scan, add your own
  analysis that decides which positions to revisit.

## If something does not work

- `ModuleNotFoundError: zmart_controller`: Jupyter runs a different Python
  than the one you installed into. Install Jupyter into the same environment.
- `no active microscope`: run the connect cell again. A kernel restart closes
  the connection.
- A `ValueError` naming an option, a motor or a position: the driver refused
  it. The matching `get_*` call shows what is allowed.
