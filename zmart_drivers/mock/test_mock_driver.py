"""The mock's captures, held to what the page draws from them.

A focus stack is taken to find a height, not to picture a field: on the
page it stands on the canvas over the predicted-height map, and one as wide
as an overview field hid the map it was measured for. The mock's focussing
frame is a quarter of the overview's area -- half its side -- so the map
stays in view around it, the way a real autofocus window is smaller than
the camera's full frame.
"""

from __future__ import annotations

import pytest

tifffile = pytest.importorskip("tifffile")
pytest.importorskip("skimage")

import zmart_controller  # noqa: E402
from zmart_drivers.mock import mock_driver  # noqa: E402


@pytest.fixture()
def session(tmp_path):
    mock_driver.register_mock()
    instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    opened = zmart_controller.set_instrument(instrument)
    try:
        yield opened
    finally:
        opened.disconnect()


def _frame_px(record) -> int:
    return tifffile.imread(record["planes"][0]["path"]).shape[0]


def test_an_overview_frame_is_the_full_frame(session):
    record = session.acquire(acquisition_type="overview", position_label="P0")
    assert _frame_px(record) == mock_driver._FRAME_PX == 256


def test_a_focus_stack_is_half_the_side_of_an_overview_frame(session):
    record = session.acquire(acquisition_type="focussing", position_label="P0")
    assert _frame_px(record) == mock_driver._FOCUS_FRAME_PX == mock_driver._FRAME_PX // 2
    # Every plane of the stack the same size, and the record's own size says so.
    assert {tifffile.imread(p["path"]).shape for p in record["planes"]} == {(128, 128)}


def test_the_focus_stack_is_still_centred_where_the_stage_stands(session):
    """Smaller, not moved: the store's corner is centre minus half of THIS frame."""
    session.set_xyz(20_000.0, 30_000.0, 0.0)
    record = session.acquire(acquisition_type="focussing", position_label="P1")
    plane = record["planes"][0]
    assert (plane["x_um"], plane["y_um"]) == (20_000.0, 30_000.0)
