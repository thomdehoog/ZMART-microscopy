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
  real (if suspiciously tidy) piece of tissue. The sample is **three
  channels**: a *structure* channel that lights every cell (what discovery
  segments), and two *marker* channels (A and B) that each light only a
  random subset. That is enough for demo mode to show the additive colour
  overlay and to exercise combined gating — gate on marker A high AND
  marker B high to pick the double-positive cells.
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

import re
import uuid
from pathlib import Path

import numpy as np
import tifffile

#: Matches the ``_C00_`` channel slot in a saved plane's filename, so the
#: segmentation engine can find a cell's other channels from the one it was
#: handed.
_CHANNEL_IN_NAME = re.compile(r"(_C)(\d{2})(_)")

#: How far the simulated target job lands from where it was told to go, in
#: micrometres. Small enough not to disturb the acquisition flow, and there
#: for any scripted calibration check that wants a real error to measure.
INJECTED_ERROR_UM = (1.8, -1.2)

#: The sample's channels, in order. Channel 0 (structure) lights every cell
#: and is what discovery segments; the two marker channels each light a random
#: subset, so gating on both selects the double-positive cells.
CHANNEL_NAMES = ("structure", "marker-a", "marker-b")


class SimulatedWorld:
    """The synthetic sample: gaussian "cells" in three channels.

    Every cell shows in the *structure* channel; each also carries an
    independent, per-cell brightness in *marker A* and *marker B* — high
    (positive) for a random ~half of the cells, near-zero for the rest. So
    about a quarter of the cells are double-positive, which is what makes
    combined gating meaningful in demo mode.
    """

    def __init__(self, seed: int = 7, extent_um: float = 1200.0) -> None:
        rng = np.random.default_rng(seed)
        spacing = 25.0  # one cell per (spacing x spacing) um on average
        n = int((2 * extent_um / spacing) ** 2)
        self.cx = rng.uniform(-extent_um, extent_um, n)
        self.cy = rng.uniform(-extent_um, extent_um, n)
        self.sigma = rng.uniform(2.5, 5.0, n)
        # Channel 0: structure — every cell, moderate brightness.
        structure = rng.uniform(0.4, 1.0, n)
        # Channels 1 and 2: markers — each cell is independently "positive"
        # (bright) or "negative" (near-zero). Half positive per marker, so
        # ~a quarter of cells are positive in BOTH.
        marker_a = np.where(rng.random(n) < 0.5, rng.uniform(0.6, 1.0, n), rng.uniform(0.0, 0.1, n))
        marker_b = np.where(rng.random(n) < 0.5, rng.uniform(0.6, 1.0, n), rng.uniform(0.0, 0.1, n))
        # One amplitude array per channel, in CHANNEL_NAMES order.
        self.channel_amps = [structure, marker_a, marker_b]
        #: Back-compatible alias: the structure channel's per-cell amplitude.
        self.amp = structure

    def _render_amps(
        self, amps: np.ndarray, center_x: float, center_y: float, pixel_um: float, shape: tuple
    ) -> np.ndarray:
        """Render one channel: the cells' gaussians weighted by ``amps``."""
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
            self.cx[keep], self.cy[keep], self.sigma[keep], amps[keep], strict=True
        ):
            gx = np.exp(-((xs - cx) ** 2) / (2 * sigma**2))
            gy = np.exp(-((ys - cy) ** 2) / (2 * sigma**2))
            image += amp * np.outer(gy, gx).astype(np.float32)
        return (np.clip(image, 0.0, 2.0) * 20000.0 + 800.0).astype(np.uint16)

    def render(self, center_x: float, center_y: float, pixel_um: float, shape: tuple) -> np.ndarray:
        """The 2-D *structure* channel a camera at (x, y) would see.

        Kept as a single 2-D image for callers (and the segmentation harness)
        that want one plane; :meth:`render_channels` returns all three.
        """
        return self._render_amps(self.amp, center_x, center_y, pixel_um, shape)

    def render_channels(
        self, center_x: float, center_y: float, pixel_um: float, shape: tuple
    ) -> np.ndarray:
        """All channels as a ``(C, H, W)`` stack (structure, marker A, marker B)."""
        return np.stack(
            [self._render_amps(a, center_x, center_y, pixel_um, shape) for a in self.channel_amps],
            axis=0,
        )


def write_ome(path: Path, array: np.ndarray, pixel_um: float) -> Path:
    """Save one rendered 2-D channel the way the driver would: OME-TIFF on disk."""
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
        stack = self.world.render_channels(x + err_x, y + err_y, job["pixel_um"], job["shape"])
        staging = self.root / ".staging" / acquisition_type
        images: list[str] = []
        planes: list[dict] = []
        # One OME-TIFF per channel, like a driver that saves each plane to its
        # own file. The C-index in the name is how the channels are told apart
        # (and how the segmentation engine finds a cell's other channels).
        for channel in range(stack.shape[0]):
            path = write_ome(
                staging
                / (
                    f"{acquisition_type}_{acquisition_hash}_{position_label}_"
                    f"T000000_C{channel:02d}_Z00000.ome.tiff"
                ),
                stack[channel],
                job["pixel_um"],
            )
            images.append(str(path))
            planes.append({"t": 0, "c": channel, "z": 0, "path": str(path)})
        return {
            "acquisition_type": acquisition_type,
            "acquisition_hash": acquisition_hash,
            "position_label": position_label,
            "images": images,
            "planes": planes,
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

    @staticmethod
    def _channel_images(seg_path: str) -> dict[int, np.ndarray]:
        """Every channel image saved next to the segmented one, by channel index.

        The engine is handed one channel's file; a cell's brightness in the
        OTHER channels (the markers) lives in the sibling files named with a
        different ``_C0d_`` slot. Returns ``{}`` for a file with no channel
        slot in its name (e.g. a plain single-channel test tile).
        """
        path = Path(seg_path)
        if not _CHANNEL_IN_NAME.search(path.name):
            return {}
        pattern = _CHANNEL_IN_NAME.sub(r"\g<1>??\g<3>", path.name)
        found: dict[int, np.ndarray] = {}
        for sibling in path.parent.glob(pattern):
            match = _CHANNEL_IN_NAME.search(sibling.name)
            if match:
                found[int(match.group(2))] = tifffile.imread(str(sibling)).astype(np.float32)
        return found

    def results(self, _queue: str) -> list[dict]:
        from skimage.measure import label, regionprops

        while self._pending:
            payload = self._pending.pop(0)
            image = tifffile.imread(payload["image_path"]).astype(np.float32)
            channels = self._channel_images(payload["image_path"])
            threshold = float(image.mean() + 2.0 * image.std())
            labels = label(image > threshold)
            picks = []
            for region in regionprops(labels, intensity_image=image):
                if region.area < 6:
                    continue  # noise specks are not cells
                row, col = region.centroid
                # Each cell's mean brightness in every channel — the per-marker
                # features the explorer gates on (marker_a AND marker_b high ->
                # double positive). Measured over the region's own pixels.
                rows, cols = region.coords[:, 0], region.coords[:, 1]
                metrics = {
                    (CHANNEL_NAMES[c].replace("-", "_") if c < len(CHANNEL_NAMES) else f"channel_{c}"): float(
                        img[rows, cols].mean()
                    )
                    for c, img in channels.items()
                }
                picks.append(
                    {
                        "centroid_col_row_px": (float(col), float(row)),
                        "area_px": float(region.area),
                        "eccentricity": float(region.eccentricity),
                        "mean_intensity": float(getattr(region, "intensity_mean", 0.0)),
                        "metrics": metrics,
                    }
                )
            n_picks = payload.get("n_picks")
            if n_picks:
                picks.sort(key=lambda p: p["area_px"], reverse=True)
                picks = picks[: int(n_picks)]
            self._done.append({"input": payload, "pick_targets": {"picks": picks}})
        drained, self._done = self._done, []
        return drained
