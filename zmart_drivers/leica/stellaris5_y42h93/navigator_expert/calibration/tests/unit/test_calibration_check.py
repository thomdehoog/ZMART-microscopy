"""Mock-driven tests for the single-position calibration check.

The check must drive the return move through the ADOPTED calibration (home +
the pair's translation difference) — that is the thing it validates — and the
leftover registered offset must come back as the negated feature shift. It
must also refuse to run when the operator forgot to switch objectives or is
on a slot the calibration does not cover.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib
import numpy as np
import pytest
import tifffile

matplotlib.use("Agg")

pytest.importorskip("cv2")  # register_voting imports cv2/skimage

from navigator_expert.acquisition.naming import build_image_name
from navigator_expert.calibration.core import calibration_check as chk
from navigator_expert.calibration.core import common as cm
from navigator_expert.orientation import Orientation

PIXEL_UM = 0.5
JOB = "Overview"


def _blob(shape=(96, 96), seed=3):
    rng = np.random.RandomState(seed)
    yy, xx = np.indices(shape, dtype=float)
    img = np.zeros(shape, float)
    for _ in range(30):
        cx, cy = rng.uniform(16, shape[1] - 16), rng.uniform(16, shape[0] - 16)
        img += rng.uniform(0.3, 1.0) * np.exp(-0.5 * (((xx - cx) / 4) ** 2 + ((yy - cy) / 4) ** 2))
    return (img / img.max() * np.iinfo(np.uint16).max).astype(np.uint16)


def _shift(img, dx, dy):
    out = np.full_like(img, int(np.median(img)))
    sx = slice(max(0, -dx), min(img.shape[1], img.shape[1] - dx))
    sy = slice(max(0, -dy), min(img.shape[0], img.shape[0] - dy))
    dxs = slice(max(0, dx), min(img.shape[1], img.shape[1] + dx))
    dys = slice(max(0, dy), min(img.shape[0], img.shape[0] + dy))
    out[dys, dxs] = img[sy, sx]
    return out


def _manifest(output_root, naming, image):
    path = Path(output_root) / build_image_name(naming)
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, np.asarray(image))
    return SimpleNamespace(
        image_paths={cm.drv.PlaneIndex(t=0, z=0, c=0): path},
        xml_paths={cm.drv.PositionIndex(t=0, v=0): Path(output_root) / "mock.ome.xml"},
        naming=naming,
    )


def _patch(
    monkeypatch,
    frames,
    *,
    home=(1000.0, 2000.0),
    home_z=50.0,
    translations=None,
):
    """Fake the driver surface. Returns a mutable rig-state dict the test can
    steer (switch the objective) and inspect (commanded moves)."""
    if translations is None:
        translations = {1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 0.0)}
    rig = {
        "slot": 1,
        "x": home[0],
        "y": home[1],
        "z": home_z,
        "xy_moves": [],
        "z_moves": [],
    }

    monkeypatch.setattr(chk._model, "load_translations", lambda calibration_name=None: dict(translations))
    monkeypatch.setattr(chk.drv, "connect_python_client", lambda *a, **k: object())
    monkeypatch.setattr(
        chk.drv, "connect_limits_handshake", lambda c, **k: SimpleNamespace(ok=True, error=None)
    )
    monkeypatch.setattr(chk.drv, "get_hardware_info", lambda c, **k: {"ok": True})
    monkeypatch.setattr("navigator_expert.orientation.rig_orientation", Orientation)

    get_xy = lambda c, **k: {"x_um": rig["x"], "y_um": rig["y"]}  # noqa: E731

    def move_xy(c, x, y, unit="um", **k):
        rig["x"], rig["y"] = x, y
        rig["xy_moves"].append((x, y))
        return {"success": True}

    def move_z(c, job, z, unit="um", **k):
        rig["z"] = z
        rig["z_moves"].append(z)
        return {"success": True}

    job_settings = lambda c, job, **k: {"objective": {"slotIndex": rig["slot"], "name": f"obj-{rig['slot']}"}}  # noqa: E731

    monkeypatch.setattr(chk.drv, "get_xy", get_xy)
    monkeypatch.setattr(cm.drv, "get_xy", get_xy)
    monkeypatch.setattr(cm.drv, "move_xy", move_xy)
    monkeypatch.setattr(cm.drv, "move_z", move_z)
    monkeypatch.setattr(cm.drv, "read_zwide_um", lambda c, job, **k: rig["z"])
    monkeypatch.setattr(cm.drv, "get_selected_job", lambda c, **k: {"Name": JOB})
    monkeypatch.setattr(cm.drv, "get_job_settings", job_settings)
    monkeypatch.setattr(
        cm.drv,
        "parse_tile_geometry",
        lambda s: {"pixel_w_um": PIXEL_UM, "pixel_h_um": PIXEL_UM, "pixels_x": 96, "pixels_y": 96},
    )
    monkeypatch.setattr(
        cm.drv, "acquire", lambda c, job, **k: SimpleNamespace(job=job, command_result={"ok": True})
    )
    seq = iter(frames)
    monkeypatch.setattr(cm.drv, "save", lambda c, acq, output_root, naming, **k: _manifest(
        output_root, naming, next(seq)
    ))
    return rig


def test_check_returns_via_the_adopted_translation(monkeypatch, tmp_path):
    # The pair's adopted translations differ by (+10, -6, +3) um. A correct
    # check must command the return move to home + that difference — the
    # very correction it exists to validate — and a rig that lands exactly
    # there must produce a near-zero leftover offset.
    ref = _blob()
    rig = _patch(
        monkeypatch,
        [ref, ref],
        translations={1: (0.0, 0.0, 0.0), 2: (10.0, -6.0, 3.0)},
    )
    session = chk.start_session(session_id="chk", job_name=JOB, sessions_root=tmp_path / "s")
    chk.measure_reference(session)
    rig["slot"] = 2  # operator switches to the target objective
    report = chk.measure_target_and_report(session, show=False)

    assert rig["xy_moves"] == [(1010.0, 1994.0)]
    assert rig["z_moves"] == [53.0]
    assert report["applied_translation_um"] == [10.0, -6.0, 3.0]
    assert report["from_slot"] == 1 and report["to_slot"] == 2
    assert report["trusted"]
    assert report["offset_um"] == pytest.approx(0.0, abs=PIXEL_UM)


def test_check_reports_negated_offset_and_writes_report(monkeypatch, tmp_path):
    ref = _blob()
    target = _shift(ref, 6, -4)  # target features at +6 col, -4 row
    rig = _patch(monkeypatch, [ref, target])

    session = chk.start_session(session_id="chk", job_name=JOB, sessions_root=tmp_path / "s")
    chk.measure_reference(session)
    rig["slot"] = 2
    report = chk.measure_target_and_report(session, show=False)

    assert report["trusted"]
    # Landing error is the negated feature shift, in micrometres.
    assert report["dx_um"] == pytest.approx(-6 * PIXEL_UM, abs=PIXEL_UM)
    assert report["dy_um"] == pytest.approx(4 * PIXEL_UM, abs=PIXEL_UM)
    assert report["position_frame_um"] == {"x": 1000.0, "y": 2000.0}

    written = json.loads((session.paths.reports_dir / "calibration_check.json").read_text())
    assert written == report
    assert (session.paths.reports_dir / "calibration_check.png").is_file()


def test_check_refuses_when_objective_was_not_switched(monkeypatch, tmp_path):
    ref = _blob()
    _patch(monkeypatch, [ref, ref])
    session = chk.start_session(session_id="chk", job_name=JOB, sessions_root=tmp_path / "s")
    chk.measure_reference(session)
    # Objective left on the reference slot: the check must refuse rather
    # than register two identical frames and bless the calibration.
    with pytest.raises(RuntimeError, match="still the reference objective"):
        chk.measure_target_and_report(session, show=False)


def test_check_refuses_a_slot_the_calibration_does_not_cover(monkeypatch, tmp_path):
    ref = _blob()
    rig = _patch(monkeypatch, [ref, ref])
    session = chk.start_session(session_id="chk", job_name=JOB, sessions_root=tmp_path / "s")
    chk.measure_reference(session)
    rig["slot"] = 3  # not in the adopted calibration
    with pytest.raises(RuntimeError, match="not covered by the adopted calibration"):
        chk.measure_target_and_report(session, show=False)


def test_start_session_requires_two_calibrated_slots(monkeypatch, tmp_path):
    _patch(monkeypatch, [], translations={1: (0.0, 0.0, 0.0)})
    with pytest.raises(RuntimeError, match="at least two calibrated objective slots"):
        chk.start_session(session_id="chk", job_name=JOB, sessions_root=tmp_path / "s")


def test_featureless_frames_are_untrusted(monkeypatch, tmp_path):
    flat = np.full((96, 96), 1000, np.uint16)
    rig = _patch(monkeypatch, [flat, flat])

    session = chk.start_session(session_id="flat", job_name=JOB, sessions_root=tmp_path / "s")
    chk.measure_reference(session)
    rig["slot"] = 2
    report = chk.measure_target_and_report(session, show=False)

    assert report["trusted"] is False
    assert report["dx_um"] is None and report["dy_um"] is None
    assert report["offset_um"] is None
