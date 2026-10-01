"""Everything for testing the mock driver, starting with its mock API.

This folder follows the driver anatomy (``docs/design/driver-anatomy.md`` in
the ZMART-microscopy repository): the stand-in for the vendor software lives
here, next to the tests, and it ships with the package so workflows can be
tried without hardware. The driver itself never imports from this folder.
"""
