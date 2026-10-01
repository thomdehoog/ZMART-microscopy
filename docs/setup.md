# Install and register your microscopes

Three steps, all done once per microscope computer. After that, a notebook
needs nothing but `import zmart_controller`.

1. **Install.** The controller alone, or as part of ZMART Microscopy, which
   brings the drivers with it:

   ```bash
   pip install "git+https://github.com/thomdehoog/ZMART-microscopy@release-candidate-zmart-controller"
   ```

2. **Configure the microscope, once.** Run the driver's own setup step on that
   computer. It measures and saves what only this microscope can know: where
   (0, 0, 0) is, the travel limits, the calibration. The driver writes them to
   the computer's configuration folder (`C:\ProgramData\zmart-microscopy\`
   on Windows), not into any repository, so a re-clone or an upgrade never
   loses them. Each driver's README says how to run its setup.

3. **Plug the driver in, once.** In any Python session on that computer:

   ```python
   import zmart_controller

   zmart_controller.register_driver("path/to/driver")   # the driver's folder
   ```

   The controller imports the driver, checks that it registers a microscope,
   and writes the driver's location to the same configuration folder. From
   then on, every session plugs it in by itself:

   ```python
   import zmart_controller

   zmart_controller.get_instruments()   # your microscope is listed
   ```

   `forget_driver("path/to/driver")` takes it off the list again. To plug a
   driver in for one session only, pass `remember=False`.

   No microscope at hand? The same line works on the bundled mock, so you can
   try the whole flow first: `zmart_controller.register_driver("zmart_driver_mock")`.

The configuration folder is `C:\ProgramData\zmart-microscopy\` on Windows,
`/Library/Application Support/zmart-microscopy/` on macOS and
`/etc/zmart-microscopy/` on Linux. Set `ZMART_MICROSCOPY_ROOT` to use another
folder.

A driver shipped as its own package can skip step 3; see
[Plug in your own driver functions](driver.md).
