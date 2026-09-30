# Your first experiment

This folder holds one notebook, `example_experiment.ipynb`, next to this page. It runs a complete
smart-microscopy experiment on the **mock microscope**, a pretend instrument
that lives entirely in memory, so you need no hardware at all. Once it runs,
the same notebook is the template for your own workflow: keep the structure,
swap the mock for a real driver, and change the positions and settings to
yours.

## 1. Install

You need Python 3.12 or newer. In a terminal:

```bash
pip install "git+https://github.com/thomdehoog/ZMART-microscopy@release-candidate-zmart-controller"
pip install jupyterlab
```

The first line installs the controller and the mock microscope. The second
installs Jupyter, which is how you open and run notebooks. If you already use
Jupyter, skip it.

## 2. Open the notebook

Download `example_experiment.ipynb`, next to this page from this folder (or clone the
repository), then start Jupyter in the folder that holds it:

```bash
jupyter lab
```

Your browser opens. Click `example_experiment.ipynb`, next to this page.

## 3. Run it, cell by cell

Run each cell in turn with Shift+Enter and read the text above it. The notebook
goes through the whole loop an experiment follows:

1. **Connect.** See which microscopes are available and connect to one.
2. **Select states.** Capture the instrument settings twice: a gentle overview
   setting and a detailed one.
3. **Choose the positions.** A short list of places to visit, in micrometers.
4. **Acquire.** Apply a state, then visit every position and capture an image
   at each.
5. **Done.** Close the connection.

Every command answers with `success` (did it work?) and `report` (what the
driver has to say). The notebook shows how to read both.

## 4. Make it yours

- **Use a real microscope.** In the setup cell, replace the two mock lines with
  one line that plugs in your microscope's driver:
  `zmart_controller.register_driver("path/to/driver")`. Everything else stays
  the same; that is the point of the controller.
- **Change the positions.** Edit the list in step 3, or build it from your own
  overview image.
- **Change the settings.** In step 2, set whatever your driver's state
  offers: `get_state()["report"]["changeable"]` shows the names.
- **Add the smart part.** Between the overview and the detailed acquisition,
  put your own analysis that decides which positions are worth revisiting.

## If something does not work

- `ModuleNotFoundError: zmart_controller`: the install in step 1 went into a
  different Python than Jupyter uses. Run the `pip install` line inside a
  notebook cell with a `!` in front, or install Jupyter into the same
  environment.
- `no active microscope`: run the connect cell (step 1) again; connections do
  not survive a kernel restart.
- A `ValueError` names something unknown, such as an option or an actuator:
  the driver refused it. Ask first with the matching `get_*` call to see the
  allowed values.
