"""Adversarial tests for the workflow-owned folder organization."""

from __future__ import annotations

import pytest
from application.workflows.target_acquisition import position_label, prepare_experiment
from application.parts.storage.output import move_record_images, prepare_acquisition


def test_exact_experiment_and_acquisition_layout(tmp_path):
    experiment = prepare_experiment(
        tmp_path / "ZMART-microscopy", "organoid-screen", hash6="abc123"
    )
    acquisition = prepare_acquisition(experiment, "overview")

    assert experiment == tmp_path / "ZMART-microscopy/organoid-screen_abc123"
    assert acquisition.root == experiment / "overview"
    assert acquisition.data == experiment / "overview/data"
    assert acquisition.data.is_dir()


def test_location_label_has_exact_widths_and_rejects_overflow():
    assert position_label(7, carrier=2, compartment=31, group=4, view=1) == (
        "K02_M000031_G000004_P000007_V01"
    )
    with pytest.raises(ValueError, match="carrier"):
        position_label(0, carrier=100)
    with pytest.raises(ValueError, match="position"):
        position_label(1_000_000)


def test_move_returns_full_final_filenames_in_images_and_planes(tmp_path):
    source = (
        tmp_path
        / "staging"
        / ("overview_abc123_K00_M000000_G000000_P000000_V00_T000000_C00_Z00000.ome.tiff")
    )
    source.parent.mkdir()
    source.write_bytes(b"image")
    record = {
        "images": [str(source)],
        "planes": [{"t": 0, "c": 0, "z": 0, "path": str(source)}],
    }

    result = move_record_images(record, tmp_path / "experiment/acquisition/data")

    final = tmp_path / "experiment/acquisition/data" / source.name
    assert result["images"] == [str(final)]
    assert result["planes"][0]["path"] == str(final)
    assert final.read_bytes() == b"image"
    assert not source.exists()


def test_the_printed_state_travels_with_the_images_it_describes(tmp_path):
    """A record's metadata lands in ``data/metadata``, not left in staging.

    The driver prints the state beside the images it wrote. Moving the images
    into the run and leaving the state behind would strand it in a staging
    folder nothing reads.
    """
    staging = tmp_path / "staging"
    (staging / "metadata").mkdir(parents=True)
    image = staging / "overview_aaaaaa_K00_P000000_T000000_C00_Z00000.ome.tiff"
    image.write_bytes(b"image")
    state = staging / "metadata" / "overview_aaaaaa_K00_P000000_T000000_ZMART_state.json"
    state.write_text('{"changeable": {}}', encoding="utf-8")
    data = tmp_path / "data"

    record = move_record_images(
        {"images": [str(image)], "metadata": [str(state)]},
        data,
    )

    assert record["metadata"] == [str(data / "metadata" / state.name)]
    assert (data / "metadata" / state.name).read_text(encoding="utf-8") == '{"changeable": {}}'
    assert not state.exists()


def test_existing_destination_refuses_before_moving_any_plane(tmp_path):
    sources = [tmp_path / "staging" / f"plane-{i}.ome.tiff" for i in range(2)]
    sources[0].parent.mkdir()
    for i, source in enumerate(sources):
        source.write_bytes(bytes([i]))
    data = tmp_path / "data"
    data.mkdir()
    (data / sources[1].name).write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="refusing to replace"):
        move_record_images({"images": [str(path) for path in sources]}, data)

    assert all(path.exists() for path in sources)
    assert (data / sources[1].name).read_bytes() == b"existing"


def test_mid_move_failure_rolls_back_the_record(monkeypatch, tmp_path):
    from application.parts.storage import output as _output

    sources = [tmp_path / "staging" / f"plane-{i}.ome.tiff" for i in range(2)]
    sources[0].parent.mkdir()
    for source in sources:
        source.write_bytes(b"image")
    real_move = _output.shutil.move
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected move failure")
        return real_move(source, target)

    monkeypatch.setattr(_output.shutil, "move", fail_second)
    with pytest.raises(OSError, match="injected"):
        move_record_images({"images": [str(path) for path in sources]}, tmp_path / "data")

    assert all(path.exists() for path in sources)
    assert not any((tmp_path / "data").iterdir())


def test_hash_and_name_validation_are_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="experiment"):
        prepare_experiment(tmp_path, "../escape")
    with pytest.raises(ValueError, match="acquisition_type"):
        prepare_acquisition(tmp_path, "../overview")
