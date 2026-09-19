"""The ZMART controller contract, driven end to end over the fake ZEN API.

The adapter's own ``connect`` needs the ``zen_api`` wheel and a gateway; here
the client it would open is replaced by a real ``ZenClient`` over the fake
stubs, and everything above it -- the envelope, the origin, moves, state, the
experiment run, the CZI copy and the printed state -- runs for real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import zenapi
from mock_zen_api import build_fake_client
from zenapi import zenapi_zmart_adapter as adapter


@pytest.fixture(autouse=True)
def _registry_isolation():
    from zmart_controller import registry

    before = dict(registry.REGISTRY)
    yield
    registry.REGISTRY.clear()
    registry.REGISTRY.update(before)


@pytest.fixture
def scope_and_client(tmp_path):
    client, scope = build_fake_client()
    scope.czi_dir = str(tmp_path / "zen_images")
    yield scope, client
    client.close()


@pytest.fixture
def connection(tmp_path):
    return {
        "vendor": "zeiss",
        "microscope": "zen-test",
        "api": "zen-api",
        "experiment": "TileScan_10x",
        "output_root": str(tmp_path / "run"),
        # Hermetic machine dir: origin persistence and the envelope must never
        # touch the real ProgramData root from a test.
        "machine_root": str(tmp_path / "machine"),
    }


@pytest.fixture
def session(scope_and_client, connection, monkeypatch):
    """A connected controller Session over the fake ZEN API."""
    import zmart_controller

    scope, client = scope_and_client
    monkeypatch.setattr(adapter, "_connect", lambda *a, **k: client)
    zenapi.register(connection)
    sess = zmart_controller.set_instrument(connection)
    try:
        yield sess, scope
    finally:
        sess.disconnect()


def test_instrument_is_registered_at_import():
    import zmart_controller

    zenapi.register()
    names = [(i["vendor"], i["microscope"], i["api"]) for i in zmart_controller.get_instruments()]
    assert ("zeiss", "zen-01", "zen-api") in names


def test_context_and_actuators(session):
    sess, _ = session
    assert sess.context == {"vendor": "zeiss", "microscope": "zen-test", "api": "zen-api"}
    assert sess.get_actuators() == {"x": ["motoric"], "y": ["motoric"], "z": ["motoric"]}


def test_set_and_get_xyz_relative_to_origin(session):
    sess, scope = session
    sess.set_xyz(1000, 2000, 50)
    assert scope.x_m == pytest.approx(1e-3) and scope.z_m == pytest.approx(50e-6)
    out = sess.set_origin()
    assert out["origin"] == pytest.approx({"x": 1000.0, "y": 2000.0, "z": 50.0})
    assert Path(out["origin_file"]).exists()
    assert sess.get_xyz()["x"]["value"] == pytest.approx(0.0)
    record = sess.set_xyz(3, 0, 0)
    assert record["confirmed"] is True
    assert sess.get_xyz()["x"]["value"] == pytest.approx(3.0)
    assert scope.x_m == pytest.approx(1.003e-3)


def test_origin_persists_across_sessions(scope_and_client, connection, monkeypatch):
    import zmart_controller

    scope, client = scope_and_client
    monkeypatch.setattr(adapter, "_connect", lambda *a, **k: client)
    zenapi.register(connection)
    first = zmart_controller.set_instrument(connection)
    first.set_xyz(100, 200, 5)
    first.set_origin()
    first.disconnect()
    # A new session over the same (fake) microscope: its own client, same scope.
    second_client, _ = build_fake_client(scope)
    monkeypatch.setattr(adapter, "_connect", lambda *a, **k: second_client)
    second = zmart_controller.set_instrument(connection)
    try:
        pos = second.get_xyz()
        assert (pos["x"]["value"], pos["y"]["value"], pos["z"]["value"]) == pytest.approx(
            (0.0, 0.0, 0.0)
        )
    finally:
        second.disconnect()


def test_moves_are_fenced_by_the_envelope(session):
    sess, scope = session
    scope.x_m = 0.123  # sentinel: the stub must NOT be called
    with pytest.raises(RuntimeError, match="refused"):
        sess.set_xyz(1e6, 0, 0)
    assert scope.x_m == 0.123
    with pytest.raises(RuntimeError, match="refused"):
        sess.set_xyz(0, 0, 1e6)


def test_machine_envelope_overrides_bundled(scope_and_client, connection, monkeypatch, tmp_path):
    import zmart_controller

    scope, client = scope_and_client
    monkeypatch.setattr(adapter, "_connect", lambda *a, **k: client)
    machine_dir = tmp_path / "machine" / "zeiss" / "zen-test"
    machine_dir.mkdir(parents=True)
    (machine_dir / "stage_limits.json").write_text(
        json.dumps({"source": "machine", "stage_um": {"x": [0, 500], "y": [0, 500], "z": [0, 100]}})
    )
    zenapi.register(connection)
    sess = zmart_controller.set_instrument(connection)
    try:
        sess.set_xyz(400, 0, 0)
        with pytest.raises(RuntimeError, match="outside limits"):
            sess.set_xyz(600, 0, 0)
        assert sess.get_info()["limits"]["source"] == "machine"
    finally:
        sess.disconnect()


def test_state_capture_and_reapply(session):
    sess, scope = session
    state = sess.get_state()
    assert list(state) == ["changeable", "observed"]
    assert state["changeable"] == {"objective_index": 0}
    assert state["observed"]["objective"]["name"] == "Plan-Apochromat 10x/0.45"
    assert [o["index"] for o in state["observed"]["objectives"]] == [0, 1, 2]
    assert state["observed"]["limits"]["source"] == "defaults"
    state["changeable"]["objective_index"] = 2
    assert sess.set_state(state)["applied"] == {"objective_index": 2}
    assert scope.objective_index == 2
    assert sess.set_state({"changeable": {"objective": "Plan-Apochromat 20x/0.8"}})["applied"] == {
        "objective_index": 1
    }
    with pytest.raises(ValueError, match="No objective named"):
        sess.set_state({"changeable": {"objective": "no such lens"}})


def test_no_procedures_are_advertised(session):
    sess, _ = session
    assert sess.get_procedures() == {}
    with pytest.raises(ValueError):
        sess.run_procedure({"name": "autofocus"})


def test_acquisition_options_name_the_experiment(session):
    sess, _ = session
    opts = sess.get_acquisition_options()
    assert opts["experiment"]["active"] == "TileScan_10x"
    assert opts["format"]["options"] == ["czi"]


def test_acquire_runs_the_experiment_and_saves(session, tmp_path):
    sess, scope = session
    sess.set_xyz(1000, 0, 10)
    sess.set_origin()
    record = sess.acquire("overview", "A1")
    czi = Path(record["images"][0])
    assert czi.exists() and czi.suffix == ".czi"
    assert czi.parent == tmp_path / "run" / "overview" / "data"
    assert czi.name.startswith("overview_") and czi.name.endswith("_A1.czi")
    assert record["experiment"] == "TileScan_10x" and record["position"]["x"] == pytest.approx(0.0)
    state_file = Path(record["metadata"][0])
    assert state_file.parent == czi.parent / "metadata" / "ZMART_state"
    printed = json.loads(state_file.read_text())
    assert printed["state"]["instrument"]["changeable"] == {"objective_index": 0}
    assert printed["state"]["provenance"]["experiment"] == "TileScan_10x"
    assert printed["images"] == [czi.name]
    # A second capture at the same label gets a hash of its own, so nothing is overwritten.
    again = sess.acquire("overview", "A1")
    assert again["images"][0] != record["images"][0]
    assert again["acquisition_hash"] != record["acquisition_hash"]


def test_acquire_needs_an_experiment_name(scope_and_client, connection, monkeypatch):
    import zmart_controller

    scope, client = scope_and_client
    monkeypatch.setattr(adapter, "_connect", lambda *a, **k: client)
    connection = {**connection, "experiment": None}
    zenapi.register(connection)
    sess = zmart_controller.set_instrument(connection)
    try:
        with pytest.raises(ValueError, match="experiment"):
            sess.acquire("overview", "A1")
        assert (
            sess.acquire("overview", "A1", options={"experiment": "Snap"})["experiment"] == "Snap"
        )
    finally:
        sess.disconnect()


def test_acquire_refuses_a_bad_acquisition_type(session):
    sess, _ = session
    with pytest.raises(ValueError, match="kebab-case"):
        sess.acquire("Over View", "A1")


def test_info_reports_limits_canvas_and_status(session):
    sess, _ = session
    info = sess.get_info()
    assert info["initial_position"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert info["limits"]["stage_um"]["x"] == [-60000.0, 60000.0]
    assert info["canvas"]["x_um"] == [-60000.0, 60000.0]
    assert [o["name"] for o in info["objectives"]][0] == "Plan-Apochromat 10x/0.45"
    sess.set_xyz(100, 0, 0)
    sess.set_origin()
    assert sess.get_info()["canvas"]["x_um"] == [-60100.0, 59900.0]
    status = info["connection_status"]
    assert status["api"] == "answering"
    assert "bundled default" in status["limits"]
    assert status["experiment"] == "TileScan_10x"


def test_disconnected_handle_refuses(session):
    sess, _ = session
    sess.disconnect()
    with pytest.raises(RuntimeError, match="disconnected"):
        sess._ops["get_xyz"](sess._handle)
