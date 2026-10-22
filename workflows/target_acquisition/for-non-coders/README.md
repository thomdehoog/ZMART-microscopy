# Target acquisition workflow for non-coders

The [ZMART interface](https://github.com/ZMB-UZH/ZMART-interface) lets you scan an overview, find targets, and image them again, without code.

1. **Install the dependencies.** [Install the interface](https://github.com/ZMB-UZH/ZMART-interface/blob/release-candidate/docs/install-on-a-microscope.md) with the Leica driver.
2. **Configure the ZMART driver.** Set up the travel limits, image orientation, objective calibration and zero point once, with the notebooks in the [Leica driver's](https://github.com/ZMB-UZH/ZMART-drivers/blob/v0.7.0b3/zmart_drivers/leica/stellaris/navigator_expert/README.md) `driver_setup` folder.
3. **Register the driver** with the ZMART Controller: [how](https://github.com/ZMB-UZH/ZMART-controller/blob/release-candidate/docs/plug_in_a_driver/README.md).
4. **Start the interface** with `zmart-interface --output-root D:\ZMART-data`. The folder is where your images are saved.
5. Pick the STELLARIS and follow the steps.
