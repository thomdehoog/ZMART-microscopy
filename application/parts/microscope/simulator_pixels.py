"""Deterministic specimen-space pixels for explicitly identified LAS X simulators."""

import math

import numpy as np


class SimulatorPixels:
    """Periodic cells at distinct physical heights; never use vendor plane indices."""

    recipe = {"name": "specimen-cells", "version": 2, "synthetic": True}

    def __call__(self, shape, dtype, *, plane, pixel_um):
        x, y, z = (plane.get(key) for key in ("x_um", "y_um", "z_um"))
        if any(value is None or not math.isfinite(value) for value in (x, y, z)):
            raise ValueError("Synthetic specimen pixels require recorded x_um, y_um and z_um")
        if any(not math.isfinite(value) or value <= 0 for value in pixel_um):
            raise ValueError("Synthetic specimen pixels require positive pixel spacing")
        ny, nx = shape
        xs = x + (np.arange(nx) + 0.5 - nx / 2) * pixel_um[1]
        ys = y + (np.arange(ny) + 0.5 - ny / 2) * pixel_um[0]
        # A fixed world, independent of field size, position label and arrival order.
        gx, gy = np.meshgrid(xs, ys)
        cx, cy = np.floor(gx / 64), np.floor(gy / 64)
        radius2 = ((gx % 64) - 32) ** 2 + ((gy % 64) - 32) ** 2
        height = ((cx + 2 * cy) % 3 - 1) * 4
        # Repeat the specimen in physical Z as well, so an arbitrary stage
        # reference does not put the simulator permanently above all objects.
        distance = np.abs((z - height + 6) % 12 - 6)
        depth = np.maximum(0, 1 - distance / 3)
        signal = (radius2 < 12**2) * depth
        signal *= 0.5 + 0.1 * (int(plane.get("c", 0)) % 3)
        signal *= 1 - 0.05 * (int(plane.get("t", 0)) % 4)
        # Exact zero outside cells is acquired black, not missing coverage.
        dtype = np.dtype(dtype)
        if dtype.kind in "iu":
            return np.rint(signal * min(np.iinfo(dtype).max, 40000)).astype(dtype)
        if dtype.kind == "f":
            return signal.astype(dtype)
        raise ValueError(f"Unsupported synthetic pixel dtype: {dtype}")
