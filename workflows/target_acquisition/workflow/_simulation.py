"""A complete simulated microscope: synthetic sample, session, and engine.

Everything here exists so the whole target-acquisition flow can run
WITHOUT a Leica attached — the notebook end-to-end tests execute both v4
notebooks against it, and the web interface's demo mode drives it so you
can learn the flow at your desk before a real session.

The pieces mirror the real boundary exactly:

- :class:`SimulatedWorld` is the "sample": gaussian blobs standing in for
  cells, scattered over the stage area. Every acquisition renders the
  commanded field of view from this one world, so overview tiles, target
  shots, and calibration pairs all agree about where things are — like a
  real (if suspiciously tidy) piece of tissue.
- :class:`SimulatedSession` answers the same calls a
  ``zmart_controller.Session`` does (``set_origin``, ``get_state``,
  ``run_procedure``, ``acquire``, ...). Its two "jobs" stand in for the
  two objectives, and the target job is deliberately mis-aimed by
  :data:`INJECTED_ERROR_UM` — the small calibration error the notebooks'
  calibration check exists to measure.
- :class:`SimulatedEngine` answers the smart analysis contract with
  honest blob segmentation, so the targets you gate and acquire really
  are the bright cells in the overview tiles.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import tifffile

#: How far the simulated target job lands from where it was told to go, in
#: micrometres. Small enough not to disturb the acquisition flow, and there
#: for any scripted calibration check that wants a real error to measure.
INJECTED_ERROR_UM = (1.8, -1.2)


class SimulatedWorld:
    """The synthetic sample: gaussian "cells" scattered over the stage."""

    def __init__(self, seed: int = 7, extent_um: float = 1200.0) -> None:
        rng = np.random.default_rng(seed)
        spacing = 25.0  # one cell per (spacing x spacing) um on average
        n = int((2 * extent_um / spacing) ** 2)
        self.cx = rng.uniform(-extent_um, extent_um, n)
        self.cy = rng.uniform(-extent_um, extent_um, n)
        self.sigma = rng.uniform(2.5, 5.0, n)
        self.amp = rng.uniform(0.4, 1.0, n)

    def render(self, center_x: float, center_y: float, pixel_um: float, shape: tuple) -> np.ndarray:
        """The image a camera at (x, y) would see, at this pixel size."""
        h, w = shape
        # The same pixel convention the pipeline uses: index - size/2.
        xs = center_x + (np.arange(w) - w / 2.0) * pixel_um
        ys = center_y + (np.arange(h) - h / 2.0) * pixel_um
        margin = 4 * float(self.sigma.max())
        keep = (
            (self.cx > xs[0] - margin)
            & (self.cx < xs[-1] + margin)
            & (self.cy > ys[0] - margin)
            & (self.cy < ys[-1] + margin)
        )
        image = np.zeros((h, w), dtype=np.float32)
        for cx, cy, sigma, amp in zip(
            self.cx[keep], self.cy[keep], self.sigma[keep], self.amp[keep], strict=True
        ):
            gx = np.exp(-((xs - cx) ** 2) / (2 * sigma**2))
            gy = np.exp(-((ys - cy) ** 2) / (2 * sigma**2))
            image += amp * np.outer(gy, gx).astype(np.float32)
        return (np.clip(image, 0.0, 2.0) * 20000.0 + 800.0).astype(np.uint16)


def write_ome(path: Path, array: np.ndarray, pixel_um: float) -> Path:
    """Save one rendered image the way the driver would: OME-TIFF on disk."""
    h, w = array.shape
    description = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
        f'SizeX="{w}" SizeY="{h}" SizeC="1" SizeZ="1" SizeT="1" '
        f'PhysicalSizeX="{pixel_um}" PhysicalSizeY="{pixel_um}"/>'
        "</Image></OME>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, array, description=description)
    return path


class SimulatedSession:
    """The controller surface, backed by the synthetic sample.

    Two jobs with different pixel sizes stand in for the two objectives;
    the "target" job lands off by :data:`INJECTED_ERROR_UM` — the mis-set
    calibration the calibration check exists to measure.
    """

    _JOBS = {
        "Sim Overview 10x": {"pixel_um": 1.2, "shape": (128, 128), "error": (0.0, 0.0)},
        "Sim Target 63x": {"pixel_um": 0.35, "shape": (128, 128), "error": INJECTED_ERROR_UM},
    }

    #: The two job names, in the order the flow uses them.
    OVERVIEW_JOB = "Sim Overview 10x"
    TARGET_JOB = "Sim Target 63x"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        # The real driver's run root exists the moment get_info answers.
        self.root.mkdir(parents=True, exist_ok=True)
        self.world = SimulatedWorld()
        self.job = self.OVERVIEW_JOB
        self.position = (0.0, 0.0, 0.0)
        self.count = 0
        self.disconnected = False

    # -- what the operator does in LAS X between capturing the two jobs ----
    def select_job(self, name: str) -> None:
        assert name in self._JOBS, name
        self.job = name

    @property
    def closed(self) -> bool:
        """Mirrors ``zmart_controller.Session.closed`` so lifecycle
        reporting reads the simulation exactly like a real session."""
        return self.disconnected

    # -- the Session ops the notebooks (and the web interface) call ---------
    def set_origin(self) -> dict:
        return {"origin": {"x": 0.0, "y": 0.0, "z": 0.0}}

    def get_state(self) -> dict:
        pixel_um = self._JOBS[self.job]["pixel_um"]
        return {
            "changeable": {"job": self.job},
            "observed": {
                "limits": {
                    "schema_version": 1,
                    "source": "machine",
                    "path": "<simulated>",
                    "is_fallback": False,
                },
                "setup": {"ready": True, "issues": []},
                "pixel_size": {"x": pixel_um, "y": pixel_um, "unit": "um"},
            },
        }

    def set_state(self, state: dict) -> dict:
        job = (state.get("changeable") or {}).get("job")
        if job:
            self.select_job(job)
        return {"applied": {"job": self.job}}

    def get_procedures(self) -> dict:
        return {"autofocus": {}}

    def get_info(self) -> dict:
        """Return the live simulated vendor setup."""
        step = 130.0  # a touch under the overview field of view
        overview = self._JOBS[self.OVERVIEW_JOB]
        tile_size = {
            "x": overview["shape"][1] * overview["pixel_um"],
            "y": overview["shape"][0] * overview["pixel_um"],
        }
        return {
            "output_root": str(self.root),
            "tile_positions": [
                {"x": sx, "y": sy, "z": 0.0, "tile_size": dict(tile_size)}
                for sy in (-step / 2, step / 2)
                for sx in (-step / 2, step / 2)
            ],
            "focus_positions": [
                {"x": -100.0, "y": -100.0},
                {"x": 100.0, "y": -100.0},
                {"x": 0.0, "y": 100.0},
            ],
        }

    def run_procedure(self, procedure: dict) -> dict:
        name = procedure.get("name")
        if name == "autofocus":
            return {"frame_z_um": 5.0}  # a flat, honest focal plane
        raise ValueError(f"unknown procedure {name!r}")

    def get_xyz(self) -> dict:
        x, y, z = self.position
        return {axis: {"value": value} for axis, value in (("x", x), ("y", y), ("z", z))}

    def set_xyz(self, x: float, y: float, z: float, **_kw: object) -> dict:
        self.position = (float(x), float(y), float(z))
        return {"position": {"x": x, "y": y, "z": z}}

    def acquire(self, *, acquisition_type: str, position_label: str, options=None) -> dict:
        job = self._JOBS[self.job]
        err_x, err_y = job["error"]
        x, y, _z = self.position
        self.count += 1
        acquisition_hash = uuid.uuid4().hex[:6]
        image = self.world.render(x + err_x, y + err_y, job["pixel_um"], job["shape"])
        path = write_ome(
            self.root
            / ".staging"
            / acquisition_type
            / (
                f"{acquisition_type}_{acquisition_hash}_{position_label}_"
                "T000000_C00_Z00000.ome.tiff"
            ),
            image,
            job["pixel_um"],
        )
        return {
            "acquisition_type": acquisition_type,
            "acquisition_hash": acquisition_hash,
            "position_label": position_label,
            "images": [str(path)],
            "planes": [{"t": 0, "c": 0, "z": 0, "path": str(path)}],
        }

    def disconnect(self) -> None:
        self.disconnected = True


class SimulatedEngine:
    """The smart analysis contract, answered by honest blob segmentation.

    ``submit``/``status``/``results`` match what ``discover_targets``
    drives; the picks come from thresholding the actual rendered images,
    so the targets you gate and acquire really are the bright cells in
    the overview tiles.
    """

    def __init__(self) -> None:
        self._pending: list[dict] = []
        self._done: list[dict] = []
        self.shut_down = False

    def register(self, _name: str, _pipeline: object) -> None:
        pass

    def shutdown(self) -> None:
        self.shut_down = True

    def submit(self, _queue: str, payload: dict) -> None:
        self._pending.append(dict(payload))

    def status(self, _queue: str) -> dict:
        return {"pending": len(self._pending), "running": 0, "failed": 0, "failures": []}

    def results(self, _queue: str) -> list[dict]:
        from skimage.measure import label, regionprops

        while self._pending:
            payload = self._pending.pop(0)
            image = tifffile.imread(payload["image_path"]).astype(np.float32)
            threshold = float(image.mean() + 2.0 * image.std())
            labels = label(image > threshold)
            picks = []
            for region in regionprops(labels, intensity_image=image):
                if region.area < 6:
                    continue  # noise specks are not cells
                row, col = region.centroid
                picks.append(
                    {
                        "centroid_col_row_px": (float(col), float(row)),
                        "area_px": float(region.area),
                        "eccentricity": float(region.eccentricity),
                        "mean_intensity": float(getattr(region, "intensity_mean", 0.0)),
                    }
                )
            n_picks = payload.get("n_picks")
            if n_picks:
                picks.sort(key=lambda p: p["area_px"], reverse=True)
                picks = picks[: int(n_picks)]
            self._done.append({"input": payload, "pick_targets": {"picks": picks}})
        drained, self._done = self._done, []
        return drained
