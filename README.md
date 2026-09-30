# ZMART Drivers

[![python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![status](https://img.shields.io/badge/status-release%20candidate-orange)](#status)

**ZMART drivers** connect the [ZMART Controller](https://github.com/thomdehoog/ZMART-microscopy/tree/release-candidate-zmart-controller)
to real microscopes. The controller gives every workflow the same short list of commands:
move in x, y and z, read and apply the microscope's settings, and acquire an image. A driver
translates those commands into what one particular microscope understands, through that
vendor's own programming interface.

ZMART (ZMB's Microscopy-Agnostic Research Toolkit) is the set of tools we use for smart
microscopy at the Center for Microscopy and Image Analysis (ZMB), University of Zurich.

## What a driver does for you

A workflow should not have to know which microscope it runs on. The driver takes care of
everything that is specific to the instrument, so the workflow does not have to:

1. **It speaks the vendor's language.** Each microscope has its own interface, its own names
   for settings, and its own habits. The driver hides these behind the controller's commands.
2. **It keeps the microscope safe.** Before any command moves hardware, the driver checks it
   against the limits measured for this microscope, such as how far the stage may travel.
3. **It gives you one coordinate system.** Positions are reported in micrometres, relative to
   a zero point the operator chooses. When you change objectives, the driver uses the
   calibration to keep that zero point on the same spot of your sample.
4. **It confirms what happened.** After a command, the driver reads the microscope back to
   check that it really did what was asked, and says so in its answer.

## Drivers in this repository

| Microscope | Vendor interface | Driver | Status |
|---|---|---|---|
| Leica STELLARIS 5 | LAS X Python (CAM) API, Navigator Expert | [`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`](zmart_drivers/leica/stellaris5_y42h93/navigator_expert/README.md) | **Release candidate `6.0.0rc1`**, not yet released. See its [release candidate review](zmart_drivers/leica/stellaris5_y42h93/navigator_expert/RELEASE_CANDIDATE_REVIEW.md). |

Drivers for ZEISS (ZEN API), Nikon (NIS-Elements), mesoSPIM and Evident microscopes are still
under construction in the main [ZMART-microscopy](https://github.com/thomdehoog/ZMART-microscopy)
repository. Each one moves here once it reaches the release candidate stage.

Drivers are organised by vendor, then by microscope, then by the vendor interface they use:
`zmart_drivers/<vendor>/<microscope>/<interface>/`. A single microscope can therefore have
more than one driver if its vendor offers more than one way in.

## Getting started with the Leica driver

The Leica driver runs on the computer that runs LAS X, because it loads Leica's interface
directly into Python. Its [README](zmart_drivers/leica/stellaris5_y42h93/navigator_expert/README.md)
explains the installation, the setup notebooks you run once per microscope (limits,
orientation and calibration), and how to drive the microscope from Python.

To use the driver through the ZMART Controller, install the controller, start Python in the
root folder of this repository, and register the driver by its module name:

```python
import zmart_controller

zmart_controller.register_driver("zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter")
zmart_controller.get_instruments()
```

Registering it by folder path does not work yet for this driver; the release candidate review
explains why (finding L8).

## Status

This repository is a **release candidate**. It collects the drivers that are ready to be
reviewed for release, separately from the rest of ZMART-microscopy. Nothing in it is released
yet. The Leica driver has been tested on the LAS X simulator and on a real STELLARIS, and its
[release candidate review](zmart_drivers/leica/stellaris5_y42h93/navigator_expert/RELEASE_CANDIDATE_REVIEW.md)
lists what must be fixed before release. Please do not leave the Leica driver running
unattended until the high-severity findings in that review are resolved.

The ZMART Controller needs Python 3.12 or newer, so a driver used through the controller needs
it too. The Leica driver on its own also runs on Python 3.10 and 3.11.

## Testing

Every driver carries its own offline test suite, which runs without a microscope. For the
Leica driver:

```bash
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python -m pip install -r requirements-dev.txt
python run_ci.py
```

The adapter tests also need the ZMART Controller to be importable. The continuous-integration
workflow in `.github/workflows/` installs it from its release candidate branch.

## Author

Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
(thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).

## License

MIT License. See the [LICENSE](LICENSE) file for details.

## Links

- [ZMART Microscopy](https://github.com/thomdehoog/ZMART-microscopy): the main repository, with the workflows and the drivers still under construction
- [ZMART Controller](https://github.com/thomdehoog/ZMART-microscopy/tree/release-candidate-zmart-controller): the microscope-independent layer these drivers plug into
- [Smart Analysis](https://github.com/thomdehoog/smart-analysis): the analysis engine that runs between acquisitions
- [ZMART viewer](https://github.com/thomdehoog/ZMART-viewer): the viewer
- [Center for Microscopy and Image Analysis (ZMB)](https://www.zmb.uzh.ch), University of Zurich
