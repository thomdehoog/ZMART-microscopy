"""The mock microscope driver: a complete ZMART driver for a pretend microscope.

It is built from the same parts as every ZMART driver (see the driver
anatomy in ``docs/driver.md``), on top of MockScope Control, pretend vendor
software in ``testing/mock_api``. Read it as the template for a new driver,
and use it to try workflows without hardware. The controller-facing
functions are in ``zmart_controller/``.
"""
