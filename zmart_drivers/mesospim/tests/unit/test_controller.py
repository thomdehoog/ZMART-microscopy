"""The ZMART controller contract, driven end to end against the mock server."""

from __future__ import annotations

import mesospim
import pytest
from mesospim.limits import checks as limits


@pytest.fixture(autouse=True)
def _no_limits():
    # Controller moves should not be blocked by leaked module-level limits.
    limits.clear_stage_limits()
    yield
    limits.clear_stage_limits()


@pytest.fixture(autouse=True)
def _registry_isolation():
    # The controller registry is process-global; the connections these tests
    # register point at per-test mock servers that die with the test. Restore
    # the registry afterwards so other suites in the same run never resolve a
    # stale mesospim entry.
    from zmart_controller import registry

    before = dict(registry.REGISTRY)
    yield
    registry.REGISTRY.clear()
    registry.REGISTRY.update(before)


@pytest.fixture
def session(server, tmp_path):
    """A connected controller Session wired to the mock command server."""
    import zmart_controller

    connection = {
        "vendor": "mesospim",
        "microscope": "mesospim-test",
        "api": "remote-control",
        "host": server.host,
        "port": server.port,
        "output_root": str(tmp_path / "run"),
        # Hermetic machine dir: origin persistence and limits resolution must
        # never touch the real ProgramData root from a test.
        "machine_root": str(tmp_path / "machine"),
    }
    mesospim.register(connection)
    sess = zmart_controller.set_instrument(connection)
    try:
        yield sess
    finally:
        sess.disconnect()


def test_context_identity(session):
    assert session.context == {
        "vendor": "mesospim",
        "microscope": "mesospim-test",
        "api": "remote-control",
    }


def test_get_instruments_lists_mesospim(session):
    import zmart_controller

    vendors = {i["vendor"] for i in zmart_controller.get_instruments()}
    assert "mesospim" in vendors


def test_actuators_and_origin(session):
    assert session.get_actuators() == {"x": ["motoric"], "y": ["motoric"], "z": ["motoric"]}
    out = session.set_origin()
    assert "origin" in out


def test_set_and_get_xyz_relative_to_origin(session):
    session.set_xyz(10, 20, 5)
    session.set_origin()  # current position becomes (0,0,0)
    pos = session.get_xyz()
    assert pos["x"]["value"] == 0.0
    session.set_xyz(3, 0, 0)
    assert session.get_xyz()["x"]["value"] == 3.0


def test_state_capture_and_reapply(session):
    state = session.get_state()
    assert list(state) == ["changeable", "observed"]  # changeable first
    state["changeable"]["intensity"] = 77.0
    session.set_state(state)
    assert session.get_state()["changeable"]["intensity"] == 77.0


def test_observed_is_a_report_never_an_instruction(session):
    # A mismatching observed part does not block applying the changeable part
    # (operator decision: set_state acts on changeable only).
    state = session.get_state()
    assert state["observed"]["microscope"] == "mesospim-test"
    state["observed"]["host"] = "10.0.0.99"
    state["changeable"]["intensity"] = 55.0
    session.set_state(state)
    assert session.get_state()["changeable"]["intensity"] == 55.0


def test_acquire_stack_z_bounds_use_origin(session, monkeypatch):
    # z_start/z_end are given in the user frame; with a non-zero origin they must
    # be mapped to raw stage coordinates before the capture.
    import mesospim.mesospim_zmart_adapter as ctl

    captured = {}
    real = ctl._acq.acquire

    def spy(client, acquisition_type, *, options=None, state=None):
        captured["options"] = dict(options or {})
        return real(client, acquisition_type, options=options, state=state)

    monkeypatch.setattr(ctl._acq, "acquire", spy)

    session.set_xyz(0, 0, 100)
    session.set_origin()  # raw z=100 now reads as user z=0
    session.acquire("stack", "C3", options={"z_start": 0, "z_end": 4, "z_step": 1})

    assert captured["options"]["z_start"] == 100.0  # 0 (user) + 100 (origin)
    assert captured["options"]["z_end"] == 104.0
    assert captured["options"]["z_step"] == 1  # a delta, unchanged


def test_acquisition_options(session):
    opts = session.get_acquisition_options()
    assert "format" in opts and "backlash_correction" in opts


def test_acquire_captures_and_saves(session, tmp_path):
    record = session.acquire("prescan", "A1", options={"format": "ome-tiff"})
    assert record["acquisition_type"] == "prescan"
    assert record["plane_count"] == 1
    assert record["images"] and record["image_files"] == record["images"]
    from pathlib import Path

    image = Path(record["images"][0])
    assert image.exists() and image.parent.name == "data"
    # One plane, with where it was taken, in the frame set_xyz accepts.
    assert len(record["planes"]) == 1
    plane = record["planes"][0]
    assert plane["path"] == str(image) and (plane["t"], plane["c"], plane["z"]) == (0, 0, 0)
    assert plane["x_um"] == 0.0 and plane["z_um"] == 0.0
    # What the driver printed about the capture sits under data/metadata.
    import json

    state_file = Path(record["metadata"][0])
    assert (
        state_file.parent.name == "ZMART_state" and state_file.parent.parent.parent == image.parent
    )
    printed = json.loads(state_file.read_text())
    assert printed["state"]["instrument"]["changeable"]["laser"] == "488 nm"
    assert printed["state"]["provenance"]["position_label"] == "A1"
    vendor = Path(record["metadata"][1])
    assert vendor.parent.name == "mesospim" and vendor.parent.parent.name == "vendor"


def test_acquire_stack(session):
    session.set_xyz(0, 0, 100)
    session.set_origin()  # raw z=100 reads as frame z=0
    record = session.acquire("stack", "B2", options={"z_start": 0, "z_end": 4, "z_step": 1})
    assert record["plane_count"] == 5
    # A 5-plane stack is one multi-page file (matches the real Tiff writer).
    assert len(record["images"]) == 1
    # Every plane says where it was taken, in the frame: z 0..4 from the origin.
    assert [p["z"] for p in record["planes"]] == [0, 1, 2, 3, 4]
    assert [p["z_um"] for p in record["planes"]] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert {p["path"] for p in record["planes"]} == {record["images"][0]}


def test_acquire_cleans_staging_and_does_not_duplicate(session, tmp_path):
    record = session.acquire("prescan", "A1")
    from pathlib import Path

    out = Path(record["image_files"][0])
    assert out.exists() and out.parent.name == "data"
    # staging is transient: the writer's originals are removed after relocation.
    staging = out.parent.parent / "_staging"
    assert not staging.exists() or not any(staging.rglob("*.tiff"))


def test_repeated_same_label_acquire_does_not_overwrite(session):
    r1 = session.acquire("prescan", "A1")
    r2 = session.acquire("prescan", "A1")
    # Same type+label twice must yield two distinct saved datasets, not a clobber.
    assert r1["image_files"][0] != r2["image_files"][0]
    from pathlib import Path

    assert Path(r1["image_files"][0]).exists() and Path(r2["image_files"][0]).exists()


def test_acquire_stack_z_out_of_limits_raises(session):
    from mesospim.limits import checks as limits

    limits.set_stage_limits(z=(0, 100))  # tight envelope for this test
    with pytest.raises(RuntimeError, match="stage limits"):
        session.acquire("stack", "Z9", options={"z_start": 0, "z_end": 500, "z_step": 1})


def test_procedures(session, server):
    procs = session.get_procedures()
    assert {"move_focus", "move_rotation", "zero_stage", "load_sample", "stop"} <= set(procs)
    assert "autofocus" not in procs  # nothing is advertised that the server cannot do
    assert session.run_procedure({"name": "move_focus", "value": 12.0})["ran"] == "move_focus"
    assert session.run_procedure({"name": "load_sample"})["ran"] == "load_sample"
    assert server.core.position()["y"] == server.core.cfg.stage_parameters["y_load_position"]
    assert session.run_procedure({"name": "stop"})["ran"] == "stop"
    with pytest.raises(ValueError):
        session.run_procedure({"name": "nope"})


def test_info(session):
    info = session.get_info()
    assert "initial_positions" in info
    assert "output_root" in info
    assert info["server"]["app"] == "mesoSPIM-control"
    # How far the stage may go: the session envelope, the server's, and the
    # canvas in the frame.
    assert info["limits"]["session"]["x"] == [0.0, 25000.0]
    assert info["limits"]["server"]["axes"]["x"] == [-50000.0, 50000.0]
    assert info["canvas"]["x_um"] == [0.0, 25000.0]
    session.set_xyz(100, 0, 0)
    session.set_origin()
    assert session.get_info()["canvas"]["x_um"] == [-100.0, 24900.0]
    status = info["connection_status"]
    assert status["api"] == "answering" and "fallback" in status["limits"]


def test_observed_reports_run_state_and_configuration(session):
    observed = session.get_state()["observed"]
    assert observed["state"] == "idle"
    assert "488 nm" in observed["lasers"] and "515/30" in observed["filters"]
    assert set(observed["position"]) == {"x", "y", "z", "f", "theta"}


def test_acquisition_options_list_the_configured_zooms(session):
    opts = session.get_acquisition_options()
    assert opts["zoom"]["options"] == ["1x", "2x"]
    assert opts["shutterconfig"]["options"] == ["Left", "Right", "Both"]


# =============================================================================
# machine-local config: function limits, persisted origin, machine envelope
# =============================================================================


def _connection(server, tmp_path):
    return {
        "vendor": "mesospim",
        "microscope": "mesospim-test",
        "api": "remote-control",
        "host": server.host,
        "port": server.port,
        "output_root": str(tmp_path / "run"),
        "machine_root": str(tmp_path / "machine"),
    }


def test_bundled_function_limits_cover_every_mutating_op():
    """THE completeness guard: adding a mutating op without a limits entry fails here."""
    from mesospim import mesospim_zmart_adapter as controller
    from mesospim.calibration import machine
    from mesospim.limits import function_limits as shared_limits

    path = machine._bundled_default(machine.FUNCTION_LIMITS_FILENAME)
    loaded = shared_limits.load(path, functions=controller._MUTATING_OPS)
    assert loaded.source == "defaults"


def test_origin_persists_across_sessions(server, tmp_path):
    import zmart_controller

    connection = _connection(server, tmp_path)
    mesospim.register(connection)

    first = zmart_controller.set_instrument(connection)
    try:
        first.set_xyz(100, 200, 50)  # move somewhere first (origin still 0)
        out = first.set_origin()
        assert out["origin_file"]  # persisted machine-locally
        assert first.get_xyz()["x"]["value"] == 0.0
    finally:
        first.disconnect()

    second = zmart_controller.set_instrument(connection)
    try:
        # The restored origin makes the same physical spot read (0, 0, 0).
        pos = second.get_xyz()
        assert (pos["x"]["value"], pos["y"]["value"], pos["z"]["value"]) == (0.0, 0.0, 0.0)
    finally:
        second.disconnect()


def test_machine_stage_envelope_overrides_bundled(server, tmp_path):
    """A machine copy of stage_limits.json governs moves, not the bundled default."""
    import json

    import zmart_controller

    connection = _connection(server, tmp_path)
    machine_dir = tmp_path / "machine" / "mesospim" / "mesospim-test"
    machine_dir.mkdir(parents=True)
    (machine_dir / "stage_limits.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "defaults",
                "axes": {
                    "x": [0.0, 500.0],  # tighter than the bundled 25000
                    "y": [0.0, 25000.0],
                    "z": [0.0, 25000.0],
                    "f": [0.0, 25000.0],
                    "theta": [-360.0, 360.0],
                },
            }
        ),
        encoding="utf-8",
    )
    mesospim.register(connection)
    sess = zmart_controller.set_instrument(connection)
    try:
        sess.set_xyz(400, 0, 0)  # inside the machine envelope
        with pytest.raises(RuntimeError, match="stage.x"):
            sess.set_xyz(600, 0, 0)  # inside bundled, outside the machine copy
    finally:
        sess.disconnect()


def test_focus_and_rotation_procedures_are_limit_gated(session):
    with pytest.raises(RuntimeError, match="stage.f"):
        session.run_procedure({"name": "move_focus", "value": 99999.0})
    with pytest.raises(RuntimeError, match="stage.theta"):
        session.run_procedure({"name": "move_rotation", "value": 720.0})
    # In-bounds still runs.
    assert session.run_procedure({"name": "move_rotation", "value": 15.0})["ran"] == "move_rotation"


def test_mutating_ops_refuse_without_function_limits(session):
    """Fail-closed: no loaded limits means no mutations — reads still work."""
    session._handle.function_limits = None
    for call in (
        lambda: session.set_origin(),
        lambda: session.set_xyz(1, 1, 1),
        lambda: session.set_state({"changeable": {}}),
        lambda: session.run_procedure({"name": "zero_stage"}),
    ):
        with pytest.raises(RuntimeError, match="function limits are not configured"):
            call()
    assert "move_focus" in session.get_procedures()  # read-only unaffected


def test_observed_reports_limits_provenance(session):
    observed = session.get_state()["observed"]
    assert observed["limits"]["schema_version"] == 1
    assert observed["limits"]["is_fallback"] is True  # no machine copy in this fixture
