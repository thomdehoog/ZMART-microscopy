"""The mock's captures, held to what the page draws from them.

A focus stack is taken to find a height, not to picture a field: on the
page it stands on the canvas over the predicted-height map, and one as wide
as an overview field hid the map it was measured for. The mock's focussing
frame is a quarter of the overview's area -- half its side -- so the map
stays in view around it, the way a real autofocus window is smaller than
the camera's full frame.

A target's frame is the high-resolution job's: fewer micrometres across than
an overview field and finer pixels over them, so a target on the page reads
as the close look it is.
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


def test_the_hires_job_images_small_and_fine(session):
    """The job owns the geometry: on HiRes a capture is 128 px of 1 um, an
    eighth of the overview field across, and the readout says so before
    anything is captured."""
    session.set_state({"changeable": {"job": "HiRes"}})
    observed = session.get_state()["observed"]
    assert observed["frame_size"]["x"] == 128.0 and observed["pixel_size"]["x"] == 1.0
    record = session.acquire(acquisition_type="targets", position_label="T0")
    assert _frame_px(record) == 128
    with tifffile.TiffFile(record["planes"][0]["path"]) as held:
        physical = held.ome_metadata
    assert 'PhysicalSizeX="1.0"' in physical
    session.set_state({"changeable": {"job": "Overview"}})
    assert session.get_state()["observed"]["frame_size"]["x"] == 1024.0


def test_a_target_frame_is_the_same_tissue_looked_at_closer(session):
    """The target's centre pixel and the overview's are one recorded pixel:
    magnification, not a different place."""
    import numpy as np

    # In focus, so neither frame is softened: blur is drawn in pixels, and
    # the two frames' pixels are not the same size.
    session.set_xyz(20_000.0, 30_000.0, mock_driver.sharp_height_um(20_000.0, 30_000.0))
    overview = tifffile.imread(session.acquire(acquisition_type="overview", position_label="P0")["planes"][0]["path"])
    session.set_state({"changeable": {"job": "HiRes"}})
    target = tifffile.imread(session.acquire(acquisition_type="targets", position_label="T0")["planes"][0]["path"])
    assert target[64, 64] == overview[128, 128]
    # Four target pixels to one overview pixel in each direction: every
    # fourth target pixel is the overview's, over the 32 recorded pixels the
    # target's 128 fine ones cover.
    assert np.array_equal(target[::4, ::4], overview[112:144, 112:144])
