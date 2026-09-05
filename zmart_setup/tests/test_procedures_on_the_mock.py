"""The procedures, driven end to end against the mock rig.

The mock's camera is mounted a quarter-turn round and its second lens looks a
little off and focuses a little higher. None of that is told to the
procedures; they have to find it from the pictures, the way they would on a
real microscope. This is the test that says the whole chain -- the vocabulary,
the procedure, the analysis, the document -- agrees with itself.
"""

from __future__ import annotations

import json

import pytest

from zmart_drivers.mock import mock_setup
from zmart_setup import open_setup, procedures, registry


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", {})
    monkeypatch.setenv(mock_setup.MACHINE_ROOT_ENV, str(tmp_path / "machine"))
    mock_setup.register_mock_setup()
    opened = open_setup(mock_setup.CONNECTION)
    yield opened
    opened.close()


def _turn_the_camera(setup, rotation_deg, reflection):
    root = mock_setup.where_the_machine_is()
    rig = mock_setup.read_rig(root)
    rig["camera"] = {"rotation_deg": rotation_deg, "reflection": reflection}
    mock_setup.write_rig(root, rig)


def _change_lens(setup, slot):
    root = mock_setup.where_the_machine_is()
    rig = mock_setup.read_rig(root)
    rig["objective_slot"] = slot
    mock_setup.write_rig(root, rig)


def test_the_mock_describes_all_four_and_both_optional_ops(setup):
    said = setup.describe()
    assert all(said["subsystems"][s]["supported"] for s in registry.SUBSYSTEMS)
    assert said["can"] == {"objective": True, "objectives": True, "markers": True}
    assert said["subsystems"]["limits"]["document"]["measured"] == ["x_um", "y_um"]


@pytest.mark.parametrize("rotation_deg,reflection", [(90, False), (0, True), (270, True), (0, False)])
def test_the_orientation_procedure_finds_how_the_camera_is_mounted(setup, tmp_path, rotation_deg, reflection):
    _turn_the_camera(setup, rotation_deg, reflection)
    home = setup.where()
    answer = procedures.measure_orientation(setup, into=tmp_path / "pictures", stage_move_um=120.0)
    assert answer["accepted"], answer["why"]
    assert answer["orientation"]["rotation_deg"] == rotation_deg
    assert answer["orientation"]["reflection"] is reflection
    # The pixel size falls out of the same three pictures.
    assert answer["pixel_um"]["mean"] == pytest.approx(4.0, rel=0.05)
    # And the stage is back where it started.
    assert setup.where() == home
    # The document is one the driver publishes as-is.
    published = setup.publish("orientation", answer["orientation"])
    assert setup.read("orientation")["document"]["rotation_deg"] == rotation_deg
    assert json.loads(open(published["path"]).read())["measured"] is True


def test_the_optics_procedure_finds_where_the_second_lens_looks(setup, tmp_path):
    _turn_the_camera(setup, 90, False)
    orientation = {"rotation_deg": 90, "reflection": False}
    _change_lens(setup, 0)
    reference = procedures.capture_lens_view(setup, into=tmp_path / "lens", name="reference",
                                             orientation=orientation)
    _change_lens(setup, 1)
    target = procedures.capture_lens_view(setup, into=tmp_path / "lens", name="target",
                                          orientation=orientation)
    answer = procedures.measure_objective_pair(reference, target)
    assert answer["accepted"], answer["why"]
    assert answer["translation_um"]["x"] == pytest.approx(-18.0, abs=2.0)
    assert answer["translation_um"]["y"] == pytest.approx(11.0, abs=2.0)
    assert answer["translation_um"]["z"] == pytest.approx(3.5, abs=0.6)
    assert answer["lenses"] == {
        "reference": {"slot": 0, "name": "10x dry", "pixel_um": 4.0},
        "target": {"slot": 1, "name": "40x dry", "pixel_um": 1.0},
    }
    document = procedures.calibration_document(setup.read("calibration")["document"], answer)
    setup.publish("calibration", document)
    held = setup.read("calibration")["document"]["objectives"]
    assert held["0"]["translation_um"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert held["1"]["measured_against"] == "0"


def test_the_boundary_is_read_from_four_markers_and_nothing_else(setup):
    with pytest.raises(RuntimeError, match="four markers"):
        procedures.read_boundary(setup)
    root = mock_setup.where_the_machine_is()
    rig = mock_setup.read_rig(root)
    rig["markers"] = [{"x_um": 5000, "y_um": 6000}, {"x_um": 110000, "y_um": 6000},
                      {"x_um": 110000, "y_um": 70000}, {"x_um": 5000, "y_um": 70000}]
    mock_setup.write_rig(root, rig)
    assert procedures.read_boundary(setup) == {
        "x_um": {"range": [5000.0, 110000.0]}, "y_um": {"range": [6000.0, 70000.0]}}


def test_limits_wider_than_the_physical_travel_are_refused(setup):
    document = setup.read("limits")["document"]
    document["x_um"] = {"range": [-10.0, 500000.0]}
    with pytest.raises(RuntimeError, match="physical travel"):
        setup.publish("limits", document)


def test_a_move_outside_the_physical_travel_is_refused_whatever_is_published(setup):
    with pytest.raises(RuntimeError, match="physical travel"):
        setup.move(-6000.0, 0.0, 0.0)


def test_the_origin_is_where_the_stage_stands(setup):
    setup.move(1000.0, 2000.0, 3.0)
    document = procedures.origin_here(setup)
    assert {k: document[k] for k in ("x_um", "y_um", "z_um")} == {"x_um": 1000.0, "y_um": 2000.0, "z_um": 3.0}
    # Every drive's reading is on record, so what became zero is legible.
    assert document["actuators"]["x motoric"] == {"value": 1000.0, "unit": "um"}
    assert "z galvo" in document["actuators"]
    setup.publish("origin", document)
    assert setup.read("origin")["source"] == "published"


def test_each_publish_is_a_new_dated_snapshot_and_the_newest_stands(setup):
    first = setup.publish("origin", {"x_um": 1, "y_um": 2, "z_um": 3})
    second = setup.publish("origin", {"x_um": 4, "y_um": 5, "z_um": 6})
    assert first["snapshot"] != second["snapshot"]
    assert setup.read("origin")["document"]["x_um"] == 4
    assert len(mock_setup.snapshots(mock_setup.where_the_machine_is(), "origin")) == 2


def test_a_setup_that_starts_over_reads_the_defaults_not_what_stands(setup):
    setup.publish("orientation", {"rotation_deg": 90, "reflection": False})
    assert setup.read("orientation")["document"]["rotation_deg"] == 90
    fresh = setup.read("orientation", fresh=True)
    assert fresh["source"] == "default"
    assert fresh["document"]["measured"] is False


def test_the_turret_is_listed_by_the_driver(setup):
    lenses = setup.objectives()
    assert [l["slot"] for l in lenses] == [0, 1]
    assert lenses[1]["name"] == "40x dry"
    assert setup.describe()["can"]["objectives"] is True
