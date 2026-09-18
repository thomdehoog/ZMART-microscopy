"""A stand-in for :class:`bridge.nis_bridge.NisApi` with no NIS-Elements behind it.

It keeps a pretend stage, nosepiece and optical-configuration list in memory
and behaves like the Ti2 simulator did on the bench (same limits, same
objective names), so the whole driver stack can be exercised offline: the
real bridge server, the real client, the real adapter -- only the last
centimetre into NIS is faked.
"""

from __future__ import annotations

from pathlib import Path

from nis_elements_6_10.bridge.nis_bridge import NisError


class FakeNisApi:
    def __init__(self, *, calibrated: bool = False, piezo: bool = True, pfs: bool = True) -> None:
        self.position = {"x": 39904.7, "y": -13433.1, "z": 500.0}
        # A piezo insert as drive index 1 (the simulator has none; the fake has one
        # so the second-actuator path is exercised offline).
        self.has_piezo = piezo
        self.piezo_z = 50.0
        self.has_pfs = pfs
        self.pfs_on = False
        self.exposure_ms = 100.0
        self.is_live = False
        self.z_series: tuple | None = None
        self.limits = {
            "x": {"min": -57000.0, "max": 57000.0},
            "y": {"min": -37500.0, "max": 37500.0},
            "z": {"min": 0.0, "max": 10000.0},
        }
        self.objectives = {
            1: "PLAN APO λD 10x OFN25 DIC N1",
            2: "APO LWD 20x WI λS",
            3: "Apo 40x WI λS DIC N2",
            4: "Plan Apo VC 60xA WI DIC N2",
            5: "SR HP Plan Apo Lambda S 100xC Sil",
            6: "",
        }
        self.nosepiece = 4
        self.optical_configurations = ["DAPI", "FITC", "TxRed", "Brightfield"]
        self.selected_configuration: str | None = None
        self.calibrated = calibrated
        self.captured = 0
        self.open_documents = 0
        self.saved: list[tuple[str, int, int]] = []
        self.calls: list[str] = []

    # -- identity ------------------------------------------------------------
    def version(self) -> str:
        return "6.10.02 (Build 2031)"

    # -- stage -----------------------------------------------------------------
    def xy_present(self) -> bool:
        return True

    def z_present(self, index: int = 0) -> bool:
        return True

    def get_position(self) -> dict[str, float]:
        return dict(self.position)

    def get_limits(self) -> dict[str, dict[str, float]]:
        return {axis: dict(b) for axis, b in self.limits.items()}

    def move_xyz(self, x: float, y: float, z: float) -> None:
        self.calls.append(f"move_xyz({x},{y},{z})")
        self.position = {"x": float(x), "y": float(y), "z": float(z)}

    def move_xy(self, x: float, y: float) -> None:
        self.calls.append(f"move_xy({x},{y})")
        self.position.update(x=float(x), y=float(y))

    def move_z(self, z: float) -> None:
        self.calls.append(f"move_z({z})")
        self.position["z"] = float(z)

    # -- second Z drive ----------------------------------------------------------
    def piezo_device(self) -> int:
        return 1 if self.has_piezo else -1

    def active_z(self) -> int:
        return 0

    def get_z(self, device: int) -> float:
        if device == 0:
            return self.position["z"]
        if device == 1 and self.has_piezo:
            return self.piezo_z
        raise NisError(f"StgGetPosZ(device={device}): DR_NOTAVAILABLE (-4)")

    def move_piezo_z(self, z: float) -> None:
        if not self.has_piezo:
            raise RuntimeError("StgMovePiezoZ: DR_NOTAVAILABLE (-4)")
        self.calls.append(f"move_piezo_z({z})")
        self.piezo_z = float(z)

    # -- autofocus / PFS ---------------------------------------------------------
    def autofocus(self, range_um: float, speed: int) -> int:
        self.calls.append(f"autofocus({range_um},{speed})")
        self.position["z"] += 3.0  # pretend the sharpest plane was 3 um up
        return 1

    def pfs_present(self) -> bool:
        return self.has_pfs

    def pfs_status(self) -> int:
        return 1 if self.pfs_on else 0

    def set_pfs(self, on: bool) -> None:
        self.calls.append(f"set_pfs({on})")
        self.pfs_on = bool(on)

    def wait_for_pfs(self, timeout_s: float) -> None:
        self.calls.append(f"wait_for_pfs({timeout_s})")

    # -- Z-series ----------------------------------------------------------------
    def set_z_series(self, top: float, bottom: float, step: float, count: int) -> None:
        self.z_series = (top, bottom, step, count)

    def run_z_series(self) -> None:
        if self.z_series is None:
            raise RuntimeError("ND_RunZSeriesExp: no Z-series defined")
        self.calls.append(f"run_z_series{self.z_series}")
        self.open_documents += 1

    # -- camera / live -----------------------------------------------------------
    def get_exposure_ms(self) -> float | None:
        return self.exposure_ms

    def set_exposure_ms(self, exposure_ms: float) -> float:
        self.exposure_ms = float(exposure_ms)
        return self.exposure_ms

    def live(self) -> None:
        self.is_live = True

    def freeze(self) -> None:
        self.is_live = False

    # -- nosepiece -------------------------------------------------------------
    def nosepiece_present(self) -> bool:
        return True

    def nosepiece_count(self) -> int:
        return len(self.objectives)

    def nosepiece_position(self) -> int:
        return self.nosepiece

    def nosepiece_objective_name(self, position: int) -> str:
        return self.objectives[position]

    def set_nosepiece_position(self, position: int) -> None:
        if position not in self.objectives:
            raise RuntimeError(f"Stg_SetNosepiecePosition({position}): DR_BADPARAMETER (-2)")
        self.nosepiece = position

    # -- optical configurations -----------------------------------------------
    def optical_configuration_names(self) -> list[str]:
        return list(self.optical_configurations)

    def select_optical_configuration(self, name: str) -> None:
        self.selected_configuration = name

    # -- images ------------------------------------------------------------------
    def capture(self) -> None:
        self.captured += 1
        self.open_documents += 1

    def image_info(self) -> dict[str, int]:
        return {"width": 2048, "height": 2044, "bits_per_component": 16, "planes": 1}

    def calibration(self) -> dict:
        if self.calibrated:
            return {
                "objective": self.objectives[self.nosepiece],
                "pixel_size": 0.1083,
                "aspect": 1.0,
                "unit": 2,
            }
        return {"objective": "Uncalibrated", "pixel_size": 0.0, "aspect": 1.0, "unit": 0}

    def save_image(self, path: str, save_type: int, compression: int = 0) -> None:
        if self.open_documents == 0:
            raise RuntimeError("ImageSaveAs: no document is open")
        Path(path).write_bytes(b"II*\0" + b"\0" * 60)  # a tiny TIFF-looking stub
        self.saved.append((path, save_type, compression))

    def close_document(self) -> None:
        if self.open_documents:
            self.open_documents -= 1
