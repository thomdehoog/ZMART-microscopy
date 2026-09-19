"""The ZMART controller session over the real wheel and the fake gateway.

This is what a workflow does: pick the instrument, set the origin, move,
acquire. Nothing here imports the driver's internals.
"""

import pytest


@pytest.fixture
def session(connection):
    import zenapi  # noqa: F401 - registers the instrument

    from zmart_controller.layer import set_instrument

    s = set_instrument({**connection, "experiment": "ZMART_Snap"})
    try:
        yield s
    finally:
        s.disconnect()


def test_instrument_is_listed():
    import zenapi  # noqa: F401

    from zmart_controller.registry import get_instruments

    assert any(i["vendor"] == "zeiss" and i["api"] == "zen-api" for i in get_instruments())


def test_full_round_trip(session, gateway, tmp_path):
    info = session.get_info()
    assert info["limits_are_defaults"] is True
    assert info["server"]["zen_api_version"]
    assert info["experiment"] == "ZMART_Snap"

    session.set_origin()
    assert session.get_xyz()["x"]["value"] == 0.0
    rec = session.set_xyz(250, -250, 12.5)
    assert rec["confirmed"] == pytest.approx({"x": 250.0, "y": -250.0, "z": 12.5})
    assert gateway.zen.x_m == pytest.approx(250e-6)

    state = session.get_state()
    assert state["changeable"]["experiment"] == "ZMART_Snap"
    assert "ZMART_ZStack" in state["observed"]["available_experiments"]
    session.set_state({"changeable": {"objective_position": 3}})
    assert gateway.zen.objective_position == 3

    options = session.get_acquisition_options()
    assert options["mode"]["options"] == ["snap", "experiment"]
    rec = session.acquire(acquisition_type="overview", position_label="A1")
    assert rec["copied"] is True
    assert rec["image_files"] == [str(tmp_path / "out" / "data" / "overview_A1.czi")]
    assert rec["position"] == pytest.approx({"x": 250.0, "y": -250.0, "z": 12.5})

    rec = session.acquire(
        acquisition_type="z-stack", position_label="A1", options={"experiment": "ZMART_ZStack"}
    )
    assert rec["mode"] == "experiment" and rec["planes"] == 5

    af = session.run_procedure({"name": "software_autofocus", "timeout_s": 3})
    assert af["frame_z_um"] == pytest.approx(135.0 - 0.0)  # origin z was 0
    assert session.run_procedure({"name": "live"})["ran"] == "live"
    assert session.run_procedure({"name": "stop"})["ran"] == "stop"


def test_move_outside_limits_is_refused_before_zen_is_asked(session, gateway):
    with pytest.raises(RuntimeError, match="set_xyz refused"):
        session.set_xyz(0, 0, 50000)
    assert not any(c[0].startswith("focus") for c in gateway.zen.calls)
