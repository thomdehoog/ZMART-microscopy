"""The XY-calibration validation run, against a synthetic 'sample'.

A stub session renders images out of one shared world texture, so the
commanded stage position fully determines what each acquisition sees.
Injecting a known positioning error into the objective-2 job then gives
ground truth the report must recover — sign included.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tifffile  # noqa: E402
from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: E402
from workflow._calibration_check import (  # noqa: E402
    finish_calibration_check,
    start_calibration_check,
)

# One world texture for every test: smooth random blobs with plenty of
# registration texture, 0.5 um resolution over +-220 um.
_RES_UM = 0.5
_EXTENT_UM = 220.0
_WORLD = gaussian_filter(
    np.random.default_rng(7).normal(size=(880, 880)), sigma=3.0
)


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _render(cx_um, cy_um, pixel_size_um, shape):
    """Sample the world texture for a window centred at (cx, cy)."""
    h, w = shape
    rows, cols = np.mgrid[0:h, 0:w].astype(float)
    y_um = cy_um + (rows - h / 2.0) * pixel_size_um
    x_um = cx_um + (cols - w / 2.0) * pixel_size_um
    mi = (y_um + _EXTENT_UM) / _RES_UM
    mj = (x_um + _EXTENT_UM) / _RES_UM
    values = map_coordinates(_WORLD, [mi, mj], order=1, mode="nearest")
    scaled = (values - values.min()) / max(float(np.ptp(values)), 1e-9)
    return (scaled * 60000).astype(np.uint16)


def _write_ome(path, array, pixel_size_um):
    h, w = array.shape
    description = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
        f'SizeX="{w}" SizeY="{h}" SizeC="1" SizeZ="1" SizeT="1" '
        f'PhysicalSizeX="{pixel_size_um}" PhysicalSizeY="{pixel_size_um}"/>'
        "</Image></OME>"
    )
    tifffile.imwrite(path, array, description=description)
    return path


class _StubSession:
    """Renders each acquisition from the world texture at the commanded spot.

    ``jobs`` maps a state's job name to (pixel_size_um, shape, error) where
    ``error`` is the positioning error injected for that job — where the
    'microscope' actually lands relative to the commanded frame position.
    """

    def __init__(self, image_dir, jobs):
        self.image_dir = image_dir
        self.jobs = jobs
        self.active = None
        self.position = (0.0, 0.0)
        self.states_applied = []
        self.count = 0

    def set_state(self, state):
        self.active = state["changeable"]["job"]
        self.states_applied.append(self.active)

    def set_xyz(self, x, y, z, **_kw):
        self.position = (float(x), float(y))

    def acquire(self, *, acquisition_type, position_label, options=None):
        pixel_size, shape, (err_x, err_y) = self.jobs[self.active]
        cx, cy = self.position[0] + err_x, self.position[1] + err_y
        self.count += 1
        path = _write_ome(
            self.image_dir / f"{acquisition_type}-{position_label}-{self.count}.ome.tif",
            _render(cx, cy, pixel_size, shape),
            pixel_size,
        )
        return {
            "acquisition_type": acquisition_type,
            "position_label": position_label,
            "images": [str(path)],
        }


@pytest.fixture
def session(tmp_path):
    return _StubSession(
        tmp_path,
        jobs={
            # objective 1: coarser pixels, wider field, lands exactly on target
            "Overview": (1.0, (100, 100), (0.0, 0.0)),
            # objective 2: finer pixels, smaller field, lands 3 um +x / 2 um -y off
            "HiRes": (0.5, (120, 120), (3.0, -2.0)),
        },
    )


def _states():
    return {"changeable": {"job": "Overview"}}, {"changeable": {"job": "HiRes"}}


def test_recovers_the_injected_calibration_error(session):
    overview_state, target_state = _states()
    check = start_calibration_check(
        session, overview_state, n_positions=5, radius_um=100.0, seed=11
    )
    report = finish_calibration_check(check, target_state, show=False)

    assert report["n_sites"] == 5
    assert report["n_trusted"] == 5
    # The mean offset IS the injected positioning error, sign included:
    # positive dx means objective 2 landed +x of the objective-1 spot.
    assert report["mean_dx_um"] == pytest.approx(3.0, abs=0.5)
    assert report["mean_dy_um"] == pytest.approx(-2.0, abs=0.5)
    assert report["mean_offset_um"] == pytest.approx(np.hypot(3.0, -2.0), abs=0.6)
    # The stub stage is otherwise perfect, so the scatter is tiny.
    assert report["stage_scatter_rms_um"] < 0.75


def test_sites_sit_on_the_requested_ring_and_are_seeded(session):
    overview_state, _ = _states()
    check = start_calibration_check(
        session, overview_state, n_positions=6, radius_um=100.0, seed=3
    )
    for pos in check.positions:
        assert np.hypot(pos["x"], pos["y"]) == pytest.approx(100.0, abs=1e-6)
    again = start_calibration_check(
        _StubSession(session.image_dir, session.jobs),
        overview_state,
        n_positions=6,
        radius_um=100.0,
        seed=3,
    )
    assert again.positions == check.positions


def test_each_phase_applies_its_own_job_state_once(session):
    overview_state, target_state = _states()
    check = start_calibration_check(
        session, overview_state, n_positions=4, radius_um=100.0, seed=1
    )
    assert session.states_applied == ["Overview"]
    finish_calibration_check(check, target_state, show=False)
    assert session.states_applied == ["Overview", "HiRes"]


def test_report_is_written_to_the_output_root(session, tmp_path):
    overview_state, target_state = _states()
    check = start_calibration_check(
        session, overview_state, n_positions=4, radius_um=100.0, seed=2
    )
    out = tmp_path / "run"
    report = finish_calibration_check(check, target_state, output_root=out, show=False)
    import json

    saved = json.loads((out / "calibration_check.json").read_text(encoding="utf-8"))
    assert saved["n_sites"] == report["n_sites"]
    assert (out / "calibration_check.png").exists()


def test_featureless_sample_is_a_clear_error(tmp_path):
    class _FlatSession(_StubSession):
        def acquire(self, *, acquisition_type, position_label, options=None):
            pixel_size, shape, _err = self.jobs[self.active]
            self.count += 1
            path = _write_ome(
                self.image_dir / f"flat-{self.count}.ome.tif",
                np.zeros(shape, dtype=np.uint16),
                pixel_size,
            )
            return {"position_label": position_label, "images": [str(path)]}

    session = _FlatSession(
        tmp_path,
        jobs={"Overview": (1.0, (64, 64), (0.0, 0.0)), "HiRes": (0.5, (64, 64), (0.0, 0.0))},
    )
    overview_state, target_state = _states()
    check = start_calibration_check(
        session, overview_state, n_positions=4, radius_um=50.0, seed=1
    )
    with pytest.raises(RuntimeError, match="registered confidently"):
        finish_calibration_check(check, target_state, show=False)


def test_too_few_sites_is_refused(session):
    overview_state, _ = _states()
    with pytest.raises(ValueError, match="at least 3"):
        start_calibration_check(session, overview_state, n_positions=2)
