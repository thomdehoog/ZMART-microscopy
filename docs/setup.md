# Install and register your microscopes

Three steps. The first two happen once per microscope computer; the third is
one line in every notebook.

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

3. **Plug the driver in.** At the top of a notebook:

   ```python
   import zmart_controller

   zmart_controller.register_driver("path/to/driver")   # a folder, a file, or a module name
   zmart_controller.get_instruments()                   # your microscope is listed
   ```

   The driver loads its saved configuration every time it connects.

   No microscope at hand? The same line works on the bundled mock, so you can
   try the whole flow first: `zmart_controller.register_driver("zmart_controller.mock")`.

A driver shipped as its own package can skip step 3; see
[Plug in your own driver functions](driver.md).
