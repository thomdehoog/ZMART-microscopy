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
    assert len(record["image_files"]) == 5


def test_procedures(session):
    procs = session.get_procedures()
    assert "autofocus" in procs and "move_focus" in procs
    assert session.set_procedure({"name": "move_focus", "value": 12.0})["ran"] == "move_focus"
    assert session.set_procedure({"name": "autofocus"})["ran"] == "autofocus"
    with pytest.raises(ValueError):
        session.set_procedure({"name": "nope"})


def test_context(session):
    ctx = session.get_context()
    assert "initial_positions" in ctx
    assert "output_root" in ctx
