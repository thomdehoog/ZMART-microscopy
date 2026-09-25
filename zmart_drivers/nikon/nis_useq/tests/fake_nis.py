"""A stand-in for ``bridge.NisApi``: an in-memory microscope, no NIS-Elements needed.

Limits, objective names and optical configurations match the Ti2 simulator.
``save_tiff`` writes a real 16-bit TIFF whose pixels all equal the capture
number, so a test can tell which capture ended up in which frame, or the
picture in ``frame`` when one is set. ``running_bridge`` puts the real bridge
server in front of it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import tifffile
from nis_useq import bridge
from nis_useq.bridge import NisError

IMAGE_SHAPE = (48, 64)  # height, width


class FakeNisApi:
    def __init__(self, *, pfs: bool = True, calibrated: bool = False) -> None:
        self.position = {"x": 1000.0, "y": -500.0, "z": 500.0}
        self.limits = {
            "x": {"min": -57000.0, "max": 57000.0},
            "y": {"min": -37500.0, "max": 37500.0},
            "z": {"min": 0.0, "max": 10000.0},
        }
        self.configurations = ["DAPI", "FITC", "TxRed", "Brightfield"]
        self.objectives = {1: "Plan Apo 10x", 2: "Apo 20x WI", 3: "", 4: "Plan Apo 60x WI"}
        self.nosepiece = 1
        self.has_pfs = pfs
        self.pfs_on = False
        self.focal_plane_z = 502.0  # where the PFS locks
        self.autofocus_result = 1
        self.calibrated = calibrated
        self.image_shape = IMAGE_SHAPE
        self.frame: np.ndarray | None = None  # a picture to save instead of the plain one
        self.camera_fails = False
        self.captures = 0
        self.open_images = 0
        self.calls: list[str] = []

    def version(self) -> str:
        return "6.10.02 (Build 2031)"

    # stage
    def get_position(self) -> dict[str, float]:
        return dict(self.position)

    def get_limits(self) -> dict[str, dict[str, float]]:
        return {axis: dict(bounds) for axis, bounds in self.limits.items()}

    def move_xyz(self, x: float, y: float, z: float) -> None:
        self.calls.append(f"move_xyz({x:g},{y:g},{z:g})")
        self.position = {"x": x, "y": y, "z": z}

    def move_xy(self, x: float, y: float) -> None:
        self.calls.append(f"move_xy({x:g},{y:g})")
        self.position.update(x=x, y=y)

    def move_z(self, z: float) -> None:
        self.calls.append(f"move_z({z:g})")
        self.position["z"] = z

    # optical configurations and camera
    def optical_configurations(self) -> list[str]:
        return list(self.configurations)

    def select_optical_configuration(self, name: str) -> None:
        self.calls.append(f"config({name})")

    def set_exposure_ms(self, exposure_ms: float) -> float:
        self.calls.append(f"exposure({exposure_ms:g})")
        return max(1.0, round(exposure_ms))  # the camera applies whole milliseconds

    # nosepiece
    def nosepiece_present(self) -> bool:
        return True

    def nosepiece_count(self) -> int:
        return len(self.objectives)

    def nosepiece_position(self) -> int:
        return self.nosepiece

    def objective_name(self, position: int) -> str:
        return self.objectives[position]

    def set_nosepiece_position(self, position: int) -> None:
        if position not in self.objectives:
            raise NisError(f"Stg_SetNosepiecePosition({position}): DR_BADPARAMETER (-2)")
        self.calls.append(f"objective({position})")
        self.nosepiece = position

    # focus
    def pfs_present(self) -> bool:
        return self.has_pfs

    def pfs_status(self) -> int:
        return 1 if self.pfs_on else 0

    def set_pfs(self, on: bool) -> None:
        self.calls.append(f"pfs({'on' if on else 'off'})")
        self.pfs_on = on

    def wait_for_pfs(self, timeout_s: float) -> None:
        self.position["z"] = self.focal_plane_z

    def autofocus(self, range_um: float, speed: int) -> int:
        self.calls.append(f"autofocus({range_um:g},{speed})")
        if self.autofocus_result == 1:
            self.position["z"] += 3.0  # the sharpest plane was 3 um higher
        return self.autofocus_result

    # images
    def capture(self) -> None:
        if self.camera_fails:
            raise NisError("Capture: the camera did not answer (-8)")
        self.captures += 1
        self.open_images += 1
        self.calls.append("capture")

    def pixel_size_um(self) -> float:
        return 0.108 if self.calibrated else 0.0

    def save_tiff(self, path: str) -> None:
        if not self.open_images:
            raise NisError("ImageSaveAs: no image is open")
        image = self.frame if self.frame is not None else np.full(self.image_shape, self.captures)
        tifffile.imwrite(path, image.astype(np.uint16))

    def close_document(self) -> None:
        self.open_images = max(0, self.open_images - 1)


@contextmanager
def running_bridge(fake: FakeNisApi) -> Iterator[bridge.BridgeServer]:
    """The real bridge server on a free local port, with ``fake`` behind it.

    A background thread stands in for the NIS macro loop that runs the requests.
    """
    server = bridge.serve(fake, "127.0.0.1", 0)
    stop = threading.Event()

    def macro_loop() -> None:
        while not stop.is_set():
            server.pump(wait_s=0.01)

    thread = threading.Thread(target=macro_loop, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        stop.set()
        thread.join()
        server.shutdown()
        server.server_close()
