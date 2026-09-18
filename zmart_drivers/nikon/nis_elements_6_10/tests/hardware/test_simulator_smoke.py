"""Against a live NIS-Elements (the simulator is fine) with start_bridge.mac already run.

Select with ``pytest -m hardware``. Moves the stage by a small, checked amount
and returns it; captures one image into a temp folder.
"""

import pytest
from nis_elements_6_10.commands import commands as cmd
from nis_elements_6_10.connection.client import NisClient, NisConnectionError
from nis_elements_6_10.readers import readers

pytestmark = pytest.mark.hardware


@pytest.fixture
def live():
    c = NisClient()
    try:
        c.connect()
    except NisConnectionError as exc:
        pytest.skip(str(exc))
    yield c
    c.close()


def test_read_everything(live):
    print(readers.get_bridge_info(live), readers.get_devices(live))
    print(readers.get_position(live), readers.get_limits(live))
    print(readers.get_objectives(live), readers.get_optical_configurations(live))


def test_small_move_and_back(live):
    start = readers.get_position(live)
    moved = cmd.move_xyz(live, start["x"] + 50, start["y"] + 50, start["z"])
    assert moved["x"] == pytest.approx(start["x"] + 50, abs=1.0)
    back = cmd.move_xyz(live, start["x"], start["y"], start["z"])
    assert back["x"] == pytest.approx(start["x"], abs=1.0)


def test_capture_and_save(live, tmp_path):
    info = cmd.capture(live, timeout=120)
    assert info["width"] > 0
    saved = cmd.save_image(live, str(tmp_path / "smoke.tif"))
    assert saved["bytes"] > 0


def test_extras_read_only(live):
    print(readers.get_z_drives(live), readers.get_pfs(live), readers.get_exposure_ms(live))


def test_exposure_set_and_restore(live):
    before = readers.get_exposure_ms(live)
    if before != before:  # NaN: NIS did not report a value
        pytest.skip("camera exposure is not readable on this setup")
    assert cmd.set_exposure_ms(live, 33) == pytest.approx(33, abs=1)
    cmd.set_exposure_ms(live, before)


def test_autofocus_runs(live):
    """The call reaches NIS and answers; "focus failed" is a legitimate answer on a
    simulator, whose flat image gives the focus criterion nothing to work with."""
    start = readers.get_position(live)
    try:
        result = cmd.autofocus(live, range_um=20, speed=30, timeout=300)
        assert abs(result["position"]["z"] - start["z"]) <= 20
    except RuntimeError as exc:
        assert "StgFocusInRangeEx" in str(exc)
    finally:
        cmd.move_xyz(live, start["x"], start["y"], start["z"])


def test_z_stack_saves_nd2(live, tmp_path):
    start = readers.get_position(live)
    info = cmd.capture_z_stack(
        live, z_top=start["z"] + 4, z_bottom=start["z"] - 4, z_step=2, timeout=300
    )
    assert info["z_planes"] == 5
    saved = cmd.save_image(live, str(tmp_path / "stack.nd2"), format="nd2")
    assert saved["bytes"] > 0
    cmd.move_xyz(live, start["x"], start["y"], start["z"])
