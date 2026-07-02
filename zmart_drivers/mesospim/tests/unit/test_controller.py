"""The ZMART controller contract, driven end to end against the mock server."""

from __future__ import annotations

import mesospim
import pytest
from mesospim.config import limits


@pytest.fixture(autouse=True)
def _no_limits():
    # Controller moves should not be blocked by leaked module-level limits.
    limits.clear_stage_limits()
    yield
    limits.clear_stage_limits()


@pytest.fixture
def session(server, tmp_path):
    """A connected controller Session wired to the mock command server."""
    import zmart_controller

    connection = {
        "vendor": "mesospim",
        "microscope": "mesospim-test",
        "api": "command-server",
        "host": server.host,
        "port": server.port,
        "output_root": str(tmp_path / "run"),
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
        "api": "command-server",
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
    assert "immutable" in state and "mutable" in state
    state["mutable"]["intensity"] = 77.0
    session.set_state(state)
    assert session.get_state()["mutable"]["intensity"] == 77.0


def test_set_state_rejects_foreign_instrument(session):
    state = session.get_state()
    state["immutable"]["host"] = "10.0.0.99"
    with pytest.raises(ValueError):
        session.set_state(state)


def test_set_state_rejects_foreign_microscope(session):
    # Same host/port, different instrument name -> still rejected (the guard is
    # not purely endpoint-based).
    state = session.get_state()
    assert state["immutable"]["microscope"] == "mesospim-test"
    state["immutable"]["microscope"] = "some-other-scope"
    with pytest.raises(ValueError):
        session.set_state(state)


def test_set_state_rejects_missing_fingerprint(session):
    state = session.get_state()
    state["immutable"] = {}
    with pytest.raises(ValueError):
        session.set_state(state)


def test_acquire_stack_z_bounds_use_origin(session, monkeypatch):
    # z_start/z_end are given in the user frame; with a non-zero origin they must
    # be mapped to raw stage coordinates before the capture.
    import mesospim.controller as ctl

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
    assert record["planes"] == 1
    assert record["image_files"]
    from pathlib import Path

    assert Path(record["image_files"][0]).exists()


def test_acquire_stack(session):
    record = session.acquire("stack", "B2", options={"z_start": 0, "z_end": 4, "z_step": 1})
    assert record["planes"] == 5
    # A 5-plane stack is one multi-page file (matches the real Tiff writer).
    assert len(record["image_files"]) == 1


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
    from mesospim.config import limits

    limits.set_stage_limits(z=(0, 100))  # tight envelope for this test
    with pytest.raises(RuntimeError, match="stage limits"):
        session.acquire("stack", "Z9", options={"z_start": 0, "z_end": 500, "z_step": 1})


def test_procedures(session):
    from mesospim import MesospimError

    procs = session.get_procedures()
    assert "autofocus" in procs and "move_focus" in procs
    assert session.set_procedure({"name": "move_focus", "value": 12.0})["ran"] == "move_focus"
    # autofocus/find_sample are advertised but the resident server NAKs them today
    # (TODO §5), so forwarding raises rather than silently "succeeding".
    with pytest.raises(MesospimError):
        session.set_procedure({"name": "autofocus"})
    with pytest.raises(ValueError):
        session.set_procedure({"name": "nope"})


def test_context(session):
    ctx = session.get_context()
    assert "initial_positions" in ctx
    assert "output_root" in ctx
