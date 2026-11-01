"""The mock microscope, driven through the controller: what it captures, and how it answers.

A focus stack is taken to find a height, not to picture a field: on the
page it stands on the canvas over the predicted-height map, and one as wide
as an overview field hid the map it was measured for. The mock's focussing
frame is a quarter of the overview's area -- half its side -- so the map
stays in view around it, the way a real autofocus window is smaller than
the camera's full frame.

A target's frame is the high-resolution job's: fewer micrometres across than
an overview field and finer pixels over them, so a target on the page reads
as the close look it is.

Every command answers in the controller's two-part shape; the ``session``
fixture reads the output of each, as the bridge does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from zmart_controller import ZmartController, check_acquire_answer, validate_driver

from .. import mock_microscope
from . import driver as mock_driver

tifffile = pytest.importorskip("tifffile")
pytest.importorskip("skimage")


@pytest.fixture()
def session(mock_session):
    return mock_session


def test_the_mock_fits_the_controllers_contract(mock_instrument):
    assert validate_driver(mock_microscope, mock_instrument) == []


def test_an_acquisition_lists_every_file_it_saved(mock_instrument):
    """``files`` names the images and the state printed beside them, as the controller's contract asks."""
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        answer = raw.acquire(position_label="P0")
    finally:
        raw.disconnect()
    assert check_acquire_answer(answer) == []
    content = answer["output"]
    # The images, then the state printed beside them.
    assert content["files"][:-1] == [plane["path"] for plane in content["planes"]]
    assert content["files"][-1].endswith("_ZMART_state.json")
    assert "images" not in content


LABEL = "K00_M000000_G000000_P000000_V00"


def test_every_file_name_is_the_acquisition_type_then_the_label(mock_instrument, tmp_path):
    """The workflow names the kind and the place; the mock adds only the time point, channel and plane.

    The files land in ``data`` in the output folder acquire is given, the
    state beside them under ``metadata/ZMART_state``, and a second capture
    under the same label never overwrites the first: it gets ``_001``.
    """
    folder = tmp_path / "a-run_a1b2c3" / "overview"
    folder.mkdir(parents=True)
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        first = raw.acquire(LABEL, acquisition_type="overview", output_folder=folder)["output"]
        again = raw.acquire(LABEL, acquisition_type="overview", output_folder=folder)["output"]
    finally:
        raw.disconnect()
    root = os.path.realpath(folder / "data")
    assert [os.path.basename(plane["path"]) for plane in first["planes"]] == [
        f"overview_{LABEL}_T000000_C{channel:02d}_Z00000.ome.tiff" for channel in range(3)
    ]
    assert {os.path.dirname(os.path.realpath(plane["path"])) for plane in first["planes"]} == {root}
    assert os.path.realpath(first["files"][-1]) == os.path.join(
        root, "metadata", "ZMART_state", f"overview_{LABEL}_T000000_ZMART_state.json"
    )
    assert os.path.basename(again["planes"][0]["path"]) == f"overview_{LABEL}_001_T000000_C00_Z00000.ome.tiff"
    assert all(os.path.exists(path) for path in first["files"] + again["files"])
    assert (first["position_label"], first["acquisition_type"]) == (LABEL, "overview")


def test_without_a_folder_the_mock_saves_where_it_was_plugged_in(mock_instrument):
    """No output folder: ``data`` in the connection's ``output_root``, under the controller's default kind."""
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        answer = raw.acquire(LABEL)["output"]
    finally:
        raw.disconnect()
    assert os.path.dirname(os.path.realpath(answer["planes"][0]["path"])) == os.path.realpath(
        os.path.join(mock_instrument["output_root"], "data")
    )
    assert os.path.basename(answer["planes"][0]["path"]).startswith(f"acquisition_{LABEL}_T000000_")
    assert answer["acquisition_type"] == "acquisition"


def test_the_mock_saves_where_it_is_told(mock_instrument):
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        assert raw.get_info()["output"]["chooses_its_own_folder"] is False
    finally:
        raw.disconnect()


def test_the_acquisition_settings_say_only_how_to_trigger(mock_instrument):
    """Every capture runs the selected job, the mock's stored acquisition; which job is state."""
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        settings = raw.get_acquisition_settings()["output"]
        state = raw.get_state()["output"]["changeable"]
    finally:
        raw.disconnect()
    assert settings == {"trigger": {"options": ["full"], "default": "full", "active": "full"}}
    assert state["job"] == "Overview"


def test_the_mock_names_its_default_motor_and_says_which_one_moved(mock_instrument):
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        motors = raw.get_actuators()["output"]
        by_default = raw.get_xyz()["output"]["z"]["used_actuator"]
        chosen = raw.set_xyz(0.0, 0.0, 5.0, with_actuators={"z": "piezo"})["output"]["z"]
    finally:
        raw.disconnect()
    assert motors["z"] == {"options": ["motoric", "galvo", "piezo"], "default": "motoric"}
    assert by_default == "motoric"
    assert chosen["used_actuator"] == "piezo" and chosen["actuator_readings"]["piezo"] == 5.0


def test_a_stack_says_which_depth_and_height_each_picture_is(mock_instrument):
    """Every plane of a focus stack fits the controller's ``planes`` contract, one depth each."""
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        raw.set_state({"changeable": {"job": "Focussing"}})
        answer = raw.acquire(position_label="F0")
    finally:
        raw.disconnect()
    assert check_acquire_answer(answer) == []
    planes = answer["output"]["planes"]
    assert [plane["z"] for plane in planes] == list(range(len(planes)))
    heights = [plane["z_um"] for plane in planes]
    assert heights == sorted(heights) and len(set(heights)) == len(planes) > 1


def test_the_canvas_holds_a_picture_taken_anywhere_the_stage_can_go(mock_instrument):
    """get_xyz's canvas is the whole travel, and half the widest field and deepest stack beyond it.

    The viewer refuses, whole, a capture that shows outside the area it was
    laid out with, and the interface lays that area out from this canvas. A
    stage standing at the edge of its travel takes a field that shows half
    its width further, and a stack half its depth, so any smaller canvas loses
    those pictures.
    """
    widest = max(px * um for px, um in (mock_driver.frame_of(job) for job in mock_driver.JOBS))
    stacks = [{"z_planes": 1, "z_step_um": 0.0}, *mock_driver.JOB_STACKS.values()]
    deepest = max((one["z_planes"] - 1) * one["z_step_um"] for one in stacks)
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        report = raw.get_xyz()["output"]
    finally:
        raw.disconnect()
    for axis, half in (("x", widest / 2), ("y", widest / 2), ("z", deepest / 2)):
        low, high = mock_driver.TRAVEL_UM[axis]
        assert list(report[axis]) == [
            "position",
            "unit",
            "used_actuator",
            "actuator_readings",
            "canvas",
        ], axis
        assert report[axis]["canvas"] == [low - half, high + half], axis
    assert deepest > 0, "the mock takes stacks, so z's canvas goes past the travel"


def test_the_mock_says_nothing_of_a_canvas_in_get_info(mock_instrument):
    """The area pictures can cover is get_xyz's, per axis; get_info no longer carries a copy."""
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        assert "canvas" not in raw.get_info()["output"]
    finally:
        raw.disconnect()


def test_a_field_taken_before_the_stage_has_moved_lies_within_the_canvas(mock_instrument):
    """Right after Connect, where an operator may first press Acquire, the field is on the canvas."""
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        canvas = raw.get_xyz()["output"]
        report = raw.acquire(position_label="P0")["output"]
    finally:
        raw.disconnect()
    plane = report["planes"][0]
    height, width = tifffile.imread(plane["path"]).shape
    for axis, across in (("x", width), ("y", height)):
        half = across * 4.0 / 2
        low, high = canvas[axis]["canvas"]
        assert low <= plane[f"{axis}_um"] - half and plane[f"{axis}_um"] + half <= high


def test_every_answer_comes_in_two_parts(mock_instrument):
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        info = raw.get_info()
        assert info["success"] is True
        assert {"description", "connection_status", "setup"} <= set(info["output"])
        assert "output_root" not in info["output"]
        saving = info["output"]["setup"]["saving"]
        assert saving["done"] is True and mock_instrument["output_root"] in saving["says"]
        assert list(raw.get_xyz()["output"]["x"]) == [
            "position",
            "unit",
            "used_actuator",
            "actuator_readings",
            "canvas",
        ]
    finally:
        raw.disconnect()


def test_a_move_outside_the_travel_is_refused_and_nothing_moves(mock_instrument):
    """The canvas is wider than the travel; a move past the travel is a mistake, refused before moving.

    The mock raises before anything moves, and the controller turns that into
    the declined answer every caller reads: ``success`` False, with the
    reason as the output.
    """
    raw = ZmartController(mock_microscope, mock_instrument)
    try:
        refused = raw.set_xyz(10_000_000.0, 0.0, 0.0)
        assert refused["success"] is False
        assert "x = 1e+07 um is outside the stage's travel" in refused["output"]
        assert raw.get_xyz()["output"]["x"]["position"] == 0.0
    finally:
        raw.disconnect()


def test_the_window_is_open_only_while_a_live_window_holds_the_lock(tmp_path):
    state = tmp_path / "instrument.json"
    assert mock_driver.the_window_is_open(state) is False
    mock_driver.claim_the_window(os.getpid(), state)
    assert mock_driver.the_window_is_open(state) is True
    # a lock left by a window that died is not a window
    mock_driver.claim_the_window(2 ** 22 + 12345, state)
    assert mock_driver.the_window_is_open(state) is False
    mock_driver.release_the_window(state)
    assert not mock_driver.where_the_window_stands(state).exists()
    mock_driver.release_the_window(state)


def _frame_px(record) -> int:
    return tifffile.imread(record["planes"][0]["path"]).shape[0]


def test_an_overview_frame_is_the_full_frame(session):
    record = session.acquire(acquisition_type="overview", position_label="P0")
    assert _frame_px(record) == mock_driver._FRAME_PX == 256


@pytest.mark.parametrize("job,kind,depth,spacing,size", [
    ("Overview stack", "overview", 7, 2, 256),
    ("Target stack", "targets", 11, 1, 128),
])
def test_imaging_stack_jobs_capture_real_planes_and_return_to_single_plane(session, job, kind, depth, spacing, size):
    import numpy as np

    session.set_xyz(20_000, 30_000, mock_driver.sharp_height_um(20_000, 30_000))
    session.set_state({"changeable": {"job": job}})
    record = session.acquire(acquisition_type=kind, position_label="stack")
    planes = record["planes"]
    assert len(planes) == depth * 3
    assert {p["z"] for p in planes} == set(range(depth))
    assert {p["c"] for p in planes} == {0, 1, 2}
    heights = sorted({p["z_um"] for p in planes})
    assert np.allclose(np.diff(heights), spacing)
    images = [tifffile.imread(p["path"]) for p in planes if p["c"] == 0]
    assert all(image.shape == (size, size) for image in images)
    assert not np.array_equal(images[0], images[depth // 2])
    session.set_state({"changeable": {"job": job.removesuffix(" stack")}})
    flat = session.acquire(acquisition_type=kind, position_label="flat")
    assert len(flat["planes"]) == 3


def test_a_focus_stack_is_what_the_focussing_job_takes(session):
    """The job decides the stack, as on a real instrument: the Focussing job takes
    61 planes of 256 px of 1 um, a quarter of an overview field's width."""
    session.set_state({"changeable": {"job": "Focussing"}})
    record = session.acquire(acquisition_type="focussing", position_label="P0")
    assert len(record["planes"]) == 61
    # Every plane of the stack the same size.
    assert {tifffile.imread(p["path"]).shape for p in record["planes"]} == {(256, 256)}


def test_the_focus_stack_is_still_centred_where_the_stage_stands(session):
    """Smaller, not moved: the store's corner is centre minus half of THIS frame."""
    session.set_xyz(20_000.0, 30_000.0, 0.0)
    session.set_state({"changeable": {"job": "Focussing"}})
    record = session.acquire(acquisition_type="focussing", position_label="P1")
    plane = record["planes"][0]
    assert (plane["x_um"], plane["y_um"]) == (20_000.0, 30_000.0)


def test_the_hires_job_images_small_and_fine(session):
    """The job owns the geometry: on Target a capture is 128 px of 1 um, an
    eighth of the overview field across, and the readout says so before
    anything is captured."""
    session.set_state({"changeable": {"job": "Target"}})
    observed = session.get_state()["observed"]
    assert observed["image_size_px"] == [128, 128] and observed["pixel_size_um"] == [1.0, 1.0]
    record = session.acquire(acquisition_type="targets", position_label="T0")
    assert _frame_px(record) == 128
    with tifffile.TiffFile(record["planes"][0]["path"]) as held:
        physical = held.ome_metadata
    assert 'PhysicalSizeX="1.0"' in physical
    session.set_state({"changeable": {"job": "Overview"}})
    observed = session.get_state()["observed"]
    assert observed["image_size_px"][0] * observed["pixel_size_um"][0] == 1024.0


def test_a_target_frame_is_the_same_tissue_looked_at_closer(session):
    """The target's centre pixel and the overview's are one recorded pixel:
    magnification, not a different place."""
    import numpy as np

    # In focus, so neither frame is softened: blur is drawn in pixels, and
    # the two frames' pixels are not the same size.
    session.set_xyz(20_000.0, 30_000.0, mock_driver.sharp_height_um(20_000.0, 30_000.0))
    overview = tifffile.imread(session.acquire(acquisition_type="overview", position_label="P0")["planes"][0]["path"])
    session.set_state({"changeable": {"job": "Target"}})
    target = tifffile.imread(session.acquire(acquisition_type="targets", position_label="T0")["planes"][0]["path"])
    assert target[64, 64] == overview[128, 128]
    # Four target pixels to one overview pixel in each direction: every
    # fourth target pixel is the overview's, over the 32 recorded pixels the
    # target's 128 fine ones cover.
    assert np.array_equal(target[::4, ::4], overview[112:144, 112:144])


def test_the_settings_live_in_the_file_and_whoever_wrote_last_wins(session):
    """The mock's LAS X is a file: the mock instrument window writes it and
    the driver reads it back on every readout and capture, so a job chosen
    there with no session open is the job the next session stands on. And
    ``set_state`` writes the same file, so the two never disagree."""
    where = mock_driver.where_the_instrument_stands()
    session.set_state({"changeable": {"job": "Target"}})
    assert mock_driver.read_instrument_settings(where)["job"] == "Target"
    mock_driver.write_instrument_settings({"job": "Focussing"}, where)
    assert session.get_state()["changeable"]["job"] == "Focussing"
    assert session.get_acquisition_settings() == {
        "trigger": {"options": ["full"], "default": "full", "active": "full"}
    }
    record = session.acquire(acquisition_type="overview", position_label="P0")
    # The state printed beside the capture names the job it ran.
    assert json.loads(Path(record["files"][-1]).read_text())["changeable"]["job"] == "Focussing"
    with pytest.raises(ValueError):
        mock_driver.write_instrument_settings({"job": "HiRes"}, where)


def test_the_focussing_job_images_a_stacks_frame(session, tmp_path):
    """Under the Focussing job a stack is 256 um of 1 um pixels, whole: the
    job's frame is the stack's frame, not halved again."""
    session.set_state({"changeable": {"job": "Focussing"}})
    observed = session.get_state()["observed"]
    assert observed["image_size_px"][0] * observed["pixel_size_um"][0] == 256.0
    record = session.acquire(acquisition_type="focussing", position_label="F0")
    assert _frame_px(record) == 256
