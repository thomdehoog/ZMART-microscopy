"""
vendors — Manufacturer-specific backends for the smart-microscopy framework.

Each vendor lives in its own sub-package (e.g. ``vendors.lasx``).
Importing a vendor package registers its backends with the generic
registries in ``microscope_connector`` and ``microscope_inspect``.

Available vendors
-----------------
    lasx    Leica LAS X
"""
