"""Deterministic specimen-space pixels for explicitly identified LAS X simulators."""

import math
from functools import lru_cache

import numpy as np


class KidneyPixels:
    """The mock's kidney micrograph, sampled in specimen XY with optical defocus.

    Focus is an explicit specimen height, never inferred from a filename or
    changed per capture. Blur the shared texture before cropping so overlapping
    fields agree even away from focus. Original vendor TIFFs are not modified.
    """

    def __init__(self, *, focus_z_um, texture_pixel_um=2.0):
        if not math.isfinite(focus_z_um) or not math.isfinite(texture_pixel_um) or texture_pixel_um <= 0:
            raise ValueError("Kidney specimen needs finite focus and positive texture spacing")
        self.focus_z_um = float(focus_z_um)
        self.texture_pixel_um = float(texture_pixel_um)
        self.recipe = {"name": "kidney-defocus", "version": 1, "synthetic": True,
                       "focus_z_um": self.focus_z_um, "texture_pixel_um": self.texture_pixel_um,
                       "source": "skimage.data.kidney", "source_plane": 8}

    @staticmethod
    @lru_cache(maxsize=1)
    def _texture():
        from skimage.data import kidney

        return np.moveaxis(kidney()[8], -1, 0).astype(np.float32) / 65535.0

    @lru_cache(maxsize=12)
    def _blurred(self, channel, z):
        from scipy.ndimage import gaussian_filter

        sigma = abs(z - self.focus_z_um) / self.texture_pixel_um
        return gaussian_filter(self._texture()[channel % 3], sigma=sigma, mode="reflect")

    def __call__(self, shape, dtype, *, plane, pixel_um):
        from scipy.ndimage import map_coordinates

        coordinates = [plane.get(key) for key in ("x_um", "y_um", "z_um")]
        if any(v is None or not math.isfinite(v) for v in coordinates):
            raise ValueError("Kidney pixels require recorded x_um, y_um and z_um")
        if any(not math.isfinite(v) or v <= 0 for v in pixel_um):
            raise ValueError("Kidney pixels require positive pixel spacing")
        x, y, z = coordinates
        ny, nx = shape
        xs = (x + (np.arange(nx) + 0.5 - nx / 2) * pixel_um[1]) / self.texture_pixel_um
        ys = (y + (np.arange(ny) + 0.5 - ny / 2) * pixel_um[0]) / self.texture_pixel_um
        gy, gx = np.meshgrid(ys, xs, indexing="ij")
        values = map_coordinates(self._blurred(int(plane.get("c", 0)), z),
                                 [gy, gx], order=1, mode="reflect", prefilter=False)
        dtype = np.dtype(dtype)
        if dtype.kind in "iu":
            return np.rint(np.clip(values, 0, 1) * np.iinfo(dtype).max).astype(dtype)
        if dtype.kind == "f":
            return values.astype(dtype)
        raise ValueError(f"Unsupported synthetic pixel dtype: {dtype}")


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
