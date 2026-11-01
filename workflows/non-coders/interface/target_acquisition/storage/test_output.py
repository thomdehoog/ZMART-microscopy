"""Adversarial tests for the workflow-owned folder organization."""

from __future__ import annotations

import pytest

from .output import (
    free_name,
    move_record_images,
    position_label,
    prepare_acquisition,
    prepare_experiment,
    run_hash,
)


def test_exact_experiment_and_acquisition_layout(tmp_path):
    experiment = prepare_experiment(
        tmp_path / "ZMART-microscopy", "organoid-screen", hash6="abc123"
    )
    acquisition = prepare_acquisition(experiment, "overview")

    assert experiment == tmp_path / "ZMART-microscopy/organoid-screen_abc123"
    assert acquisition == experiment / "overview"
    assert acquisition.is_dir()


def test_location_label_has_exact_widths_and_rejects_overflow():
    assert position_label(7, carrier=2, compartment=31, group=4, view=1) == (
        "K02_M000031_G000004_P000007_V01"
    )
    with pytest.raises(ValueError, match="carrier"):
        position_label(0, carrier=100)
    with pytest.raises(ValueError, match="position"):
        position_label(1_000_000)


def test_the_run_hash_ends_the_run_folders_name(tmp_path):
    run = prepare_experiment(tmp_path, "organoid-screen", hash6="abc123")

    assert run_hash(run) == "abc123"


def test_what_the_interface_writes_beside_a_capture_never_takes_an_earlier_name(tmp_path):
    """A label taken again in the run gets the next free name, ``_001``, ...

    What the interface writes about a capture -- its focus curve, the objects
    found in it -- is named after the capture's acquisition type and label, so
    a rerun of the same position keeps what was said about the first capture.
    """
    first = free_name(tmp_path, "overview_K00_M000000_G000000_P000007_V00", "_T000000_targets.json")
    assert first == tmp_path / "overview_K00_M000000_G000000_P000007_V00_T000000_targets.json"
    first.write_text("[]", encoding="utf-8")
    again = free_name(tmp_path, "overview_K00_M000000_G000000_P000007_V00", "_T000000_targets.json")
    assert again == tmp_path / "overview_K00_M000000_G000000_P000007_V00_001_T000000_targets.json"


def leica_shaped(folder):
    """A capture laid out the way the Leica driver lays one out in the folder it is given.

    The store in ``data``, LAS X's description in ``data/metadata/vendor``, the
    printed state in ``data/metadata/ZMART_state``, the projection beside
    ``data`` in ``projections`` and the driver's log in ``log``.
    """
    store = folder / "data" / "a.ome.zarr"
    vendor = folder / "data" / "metadata" / "vendor" / "a.xlif"
    state = folder / "data" / "metadata" / "ZMART_state" / "a_ZMART_state.json"
    projection = folder / "projections" / "a.ome.zarr"
    log = folder / "log" / "a.log.json"
    for made in (store, projection):
        made.mkdir(parents=True)
        (made / "zarr.json").write_text("{}", encoding="utf-8")
    for written in (vendor, state, log):
        written.parent.mkdir(parents=True)
        written.write_text("{}", encoding="utf-8")
    return [store, vendor, state, projection, log]


def test_files_the_driver_saved_where_they_belong_stay_there(tmp_path):
    """A driver given the acquisition's folder lays it out its own way: nothing is moved."""
    acquisition = tmp_path / "run" / "overview"
    saved = leica_shaped(acquisition)
    record = {"files": [str(path) for path in saved],
              "planes": [{"t": 0, "c": 0, "z": 0, "path": str(saved[0])}]}

    move_record_images(record, acquisition)

    assert record["files"] == [str(path) for path in saved]
    assert record["planes"][0]["path"] == str(saved[0])
    assert all(path.exists() for path in saved)


def test_a_capture_saved_elsewhere_keeps_its_layout_in_the_acquisitions_folder(tmp_path):
    """A driver whose software saves in its own place: the folders it made come along as they are.

    So the printed state and LAS X's description stay under ``data/metadata``,
    and the projection and the log beside ``data``, with no list saying which
    file is which.
    """
    saved = leica_shaped(tmp_path / "staging")
    record = {"files": [str(path) for path in saved],
              "planes": [{"t": 0, "c": 0, "z": 0, "path": str(saved[0])}]}
    acquisition = tmp_path / "run" / "overview"

    result = move_record_images(record, acquisition)

    landed = [acquisition / path.relative_to(tmp_path / "staging") for path in saved]
    assert result["files"] == [str(path) for path in landed]
    assert result["planes"][0]["path"] == str(acquisition / "data" / "a.ome.zarr")
    assert all(path.exists() for path in landed)
    assert not any(path.exists() for path in saved)


def test_move_returns_full_final_filenames_in_files_and_planes(tmp_path):
    source = (
        tmp_path
        / "staging"
        / ("overview_abc123_K00_M000000_G000000_P000000_V00_T000000_C00_Z00000.ome.tiff")
    )
    source.parent.mkdir()
    source.write_bytes(b"image")
    record = {
        "files": [str(source)],
        "planes": [{"t": 0, "c": 0, "z": 0, "path": str(source)}],
    }

    result = move_record_images(record, tmp_path / "experiment/acquisition")

    final = tmp_path / "experiment/acquisition" / source.name
    assert result["files"] == [str(final)]
    assert result["planes"][0]["path"] == str(final)
    assert final.read_bytes() == b"image"
    assert not source.exists()


def test_existing_destination_refuses_before_moving_any_plane(tmp_path):
    sources = [tmp_path / "staging" / f"plane-{i}.ome.tiff" for i in range(2)]
    sources[0].parent.mkdir()
    for i, source in enumerate(sources):
        source.write_bytes(bytes([i]))
    acquisition = tmp_path / "overview"
    acquisition.mkdir()
    (acquisition / sources[1].name).write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="refusing to replace"):
        move_record_images({"files": [str(path) for path in sources]}, acquisition)

    assert all(path.exists() for path in sources)
    assert (acquisition / sources[1].name).read_bytes() == b"existing"


def test_mid_move_failure_rolls_back_the_record(monkeypatch, tmp_path):
    from . import output as _output

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
        move_record_images({"files": [str(path) for path in sources]}, tmp_path / "overview")

    assert all(path.exists() for path in sources)
    assert not any((tmp_path / "overview").iterdir())


def test_the_files_are_what_is_moved_and_images_is_not_read(tmp_path):
    """``files`` is the name the ZMART Controller's contract fixes; an old ``images`` list is refused.

    Reading a second name beside it would let a driver drift from the
    contract unnoticed until a capture from another microscope went missing.
    """
    image = tmp_path / "staging" / "A1.ome.tif"
    image.parent.mkdir()
    image.write_bytes(b"image")

    with pytest.raises(RuntimeError, match="listed no files"):
        move_record_images({"images": [str(image)]}, tmp_path / "overview")
    assert image.exists()


def test_every_file_a_driver_saved_is_moved_also_without_planes(tmp_path):
    """A driver that answers only the contract's ``files`` has all of them kept in the run."""
    staging = tmp_path / "staging"
    staging.mkdir()
    saved = [staging / "A1.ome.tif", staging / "A1.commands.json"]
    for path in saved:
        path.write_bytes(b"saved")

    record = move_record_images({"files": [str(path) for path in saved]}, tmp_path / "overview")

    assert record["files"] == [str(tmp_path / "overview" / path.name) for path in saved]
    assert not any(path.exists() for path in saved)


def test_a_plane_whose_file_is_not_listed_is_refused_before_moving(tmp_path):
    """Every plane's file must be one of the files the driver says it saved."""
    staging = tmp_path / "staging"
    staging.mkdir()
    listed, unlisted = staging / "A1_C00.ome.tif", staging / "A1_C01.ome.tif"
    for path in (listed, unlisted):
        path.write_bytes(b"image")
    record = {
        "files": [str(listed)],
        "planes": [
            {"t": 0, "c": 0, "z": 0, "path": str(listed)},
            {"t": 0, "c": 1, "z": 0, "path": str(unlisted)},
        ],
    }

    with pytest.raises(RuntimeError, match="not among the files"):
        move_record_images(record, tmp_path / "overview")
    assert listed.exists() and unlisted.exists()


def test_hash_and_name_validation_are_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="experiment"):
        prepare_experiment(tmp_path, "../escape")
    with pytest.raises(ValueError, match="acquisition_type"):
        prepare_acquisition(tmp_path, "../overview")
