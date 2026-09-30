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

A driver shipped as its own package can skip step 3: one line in its
`pyproject.toml` names the function to call, and the controller calls it the
first time `get_instruments()` runs.

```toml
[project.entry-points."zmart_controller.drivers"]
acme = "zmart_drivers.acme:register"
```

