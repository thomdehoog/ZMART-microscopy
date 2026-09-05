"""The procedures, driven end to end against the mock rig.

The mock's camera is mounted a quarter-turn round and its second lens looks a
little off and focuses a little higher. None of that is told to the
procedures; they have to find it from the pictures, the way they would on a
real microscope. This is the test that says the whole chain -- the vocabulary,
the procedure, the analysis, the document -- agrees with itself.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    assert said["can"] == {"objective": True, "objectives": True, "markers": True,
                           "configurations": True, "new_configuration": True,
                           "use_configuration": True, "configuration": True}
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
    _change_lens(setup, 2)
    target = procedures.capture_lens_view(setup, into=tmp_path / "lens", name="target",
                                          orientation=orientation)
    answer = procedures.measure_objective_pair(reference, target)
    assert answer["accepted"], answer["why"]
    assert answer["translation_um"]["x"] == pytest.approx(-18.0, abs=2.0)
    assert answer["translation_um"]["y"] == pytest.approx(11.0, abs=2.0)
    assert answer["translation_um"]["z"] == pytest.approx(3.5, abs=0.6)
    assert answer["lenses"] == {
        "reference": {"slot": 0, "name": "10x dry", "pixel_um": 4.0},
        "target": {"slot": 2, "name": "40x dry", "pixel_um": 1.0},
    }
    document = procedures.calibration_document(setup.read("calibration")["document"], answer)
    setup.publish("calibration", document)
    held = setup.read("calibration")["document"]["objectives"]
    assert held["0"]["translation_um"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert held["2"]["measured_against"] == "0"


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
    root = mock_setup.where_the_machine_is()
    assert len(mock_setup.snapshots(mock_setup.configuration_root(root), "origin")) == 2


def test_a_setup_that_starts_over_reads_the_defaults_not_what_stands(setup):
    setup.publish("orientation", {"rotation_deg": 90, "reflection": False})
    assert setup.read("orientation")["document"]["rotation_deg"] == 90
    fresh = setup.read("orientation", fresh=True)
    assert fresh["source"] == "default"
    assert fresh["document"]["measured"] is False


def test_the_turret_is_listed_by_the_driver(setup):
    lenses = setup.objectives()
    assert [l["slot"] for l in lenses] == [0, 1, 2, 3]
    assert lenses[2]["name"] == "40x dry"
    assert setup.describe()["can"]["objectives"] is True


def test_a_configuration_is_a_full_copy_and_adopting_stays_inside_it(setup):
    # Opening a setup seeds a first configuration to stand on; nothing is chosen yet.
    assert setup.configuration() is None
    first = setup.configurations()
    assert len(first) == 1 and first[0]["has"] == {"limits": False, "orientation": False,
                                                    "calibration": False, "origin": False}
    # Adopting an origin lands in the configuration being stood on.
    chosen = setup.use_configuration(first[0]["id"])
    assert setup.configuration()["id"] == chosen["id"]
    origin = procedures.origin_here(setup)
    setup.publish("origin", origin)
    assert setup.configurations()[0]["has"]["origin"] is True
    # A new configuration starts as a full copy, and is stood on at once.
    import time
    time.sleep(0.01)
    second = setup.new_configuration()
    assert second["id"] > chosen["id"]
    assert second["has"]["origin"] is True
    assert setup.configuration()["id"] == second["id"]
    assert setup.read("origin")["document"]["x_um"] == origin["x_um"]
    # Newest first, and adopting in the new one leaves the first alone.
    setup.publish("origin", {**origin, "x_um": origin["x_um"] + 1})
    listed = setup.configurations()
    assert [c["id"] for c in listed] == [second["id"], chosen["id"]]
    setup.use_configuration(chosen["id"])
    assert setup.read("origin")["document"]["x_um"] == origin["x_um"]
    with pytest.raises(FileNotFoundError):
        setup.use_configuration("configuration_2000-01-01T00-00-00-000000Z")


def test_evidence_is_kept_beside_the_document_and_read_back(setup, tmp_path):
    picture = tmp_path / "orientation.png"
    picture.write_bytes(b"\x89PNG not really")
    numbers = tmp_path / "orientation_measurement.json"
    numbers.write_text('{"residual": 0.1}', encoding="utf-8")
    frames = tmp_path / "orientation_frames"
    frames.mkdir()
    (frames / "home_Z00000.ome.tiff").write_bytes(b"II*\x00")
    where = setup.publish("orientation", {"rotation_deg": 90, "reflection": False},
                          evidence=[picture, numbers, frames, tmp_path / "missing.png"])
    names = ["orientation.png", "orientation_frames/home_Z00000.ome.tiff", "orientation_measurement.json"]
    assert sorted(e["name"] for e in where["evidence"]) == names
    read = setup.read("orientation")
    assert read["source"] == "published"
    assert sorted(e["name"] for e in read["evidence"]) == names
    assert Path(next(e["path"] for e in read["evidence"] if e["name"] == "orientation.png")).read_bytes() == b"\x89PNG not really"
    # A new configuration carries the evidence along with the snapshot it copies.
    import time
    time.sleep(0.01)
    setup.new_configuration()
    assert sorted(e["name"] for e in setup.read("orientation")["evidence"]) == names



def test_adopted_limits_fence_moves_once_the_setup_is_opened_again(setup):
    """The driver applies a configuration's limits when it opens on it, so
    limits adopted in a setup fence the moves of a setup opened again on the
    same configuration -- which is what the bridge does behind the card."""
    setup.publish("limits", {**setup.read("limits", fresh=True)["document"],
                             "x_um": {"range": [10000, 50000]}})
    setup.move(60000.0, 40000.0, 16.0)          # this open loaded no limits yet
    again = open_setup(setup.connection)
    with pytest.raises(RuntimeError, match="outside the limits \\[10000, 50000\\]"):
        again.move(60000.0, 40000.0, 16.0)
    assert again.move(20000.0, 40000.0, 16.0)["x_um"] == 20000.0
