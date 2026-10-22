# Target acquisition workflow for coders

The [target acquisition notebook](target_acquisition.ipynb) drives the microscope with the [ZMART Controller](https://github.com/ZMB-UZH/ZMART-controller): image overview positions, find dividing cells, and image them again.

1. **Install the dependencies.** Run `python install.py --branch release-candidate` in this repository.
2. **Configure the ZMART driver.** Set up the travel limits, image orientation, objective calibration and zero point once, with the notebooks in the [Leica driver's](https://github.com/ZMB-UZH/ZMART-drivers/blob/release-candidate/zmart_drivers/leica/stellaris_y42h93/navigator_expert/README.md) `driver_setup` folder.
3. **Register the driver** with the ZMART Controller: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/release-candidate/docs/plug_in_a_driver/README.md).
4. **Open the [notebook](target_acquisition.ipynb)** and run it cell by cell.
