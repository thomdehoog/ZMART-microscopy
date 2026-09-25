"""Against a running NIS-Elements (the Ti2 simulator, or a real microscope) with the bridge started.

Run it in three steps, each building on the one before:

    pytest -m hardware -k engine    # 1. the engine talks to NIS: read, move, snap, settings
    pytest -m hardware -k useq      # 2. useq sequences run on the engine and are saved
    pytest -m hardware -k agent     # 3. the assistant's tools, driven by a scripted model

Skipped when no bridge answers. Everything stays close to where the stage is
(at most 100 um away) and the stage is moved back afterwards. Tests that need
a pixel calibration for the objective in use are skipped without one. The
assistant is driven by a script here, not by a real model, so this step costs
no API calls; trying the real model is done by hand in the window (README).
"""

import json

import numpy as np
import pytest
import tifffile
import useq
import useq.v2 as v2
from nis_useq.client import NisConnectionError
from nis_useq.engine import NisEngine

pytestmark = pytest.mark.hardware
pytest.importorskip("pymmcore_plus")
from pymmcore_plus.mda import MDARunner  # noqa: E402


@pytest.fixture
def engine():
    try:
        engine = NisEngine()
    except NisConnectionError as exc:
        pytest.skip(str(exc))
    start = engine.client.request("get_position")
    yield engine
    engine.client.request("move", **start)
    engine.close()


@pytest.fixture
def here(engine):
    return engine.client.request("get_position")


@pytest.fixture
def configuration(engine):
    return engine.client.request("get_optical_configurations")[0]


@pytest.fixture
def two_configurations(engine):
    """Two different optical configurations (a file cannot hold two channels of one name)."""
    configurations = engine.client.request("get_optical_configurations")
    if len(configurations) < 2:
        pytest.skip("NIS lists fewer than two optical configurations")
    return configurations[:2]


@pytest.fixture
def field(engine):
    """The camera field in um, or a skip when the objective has no pixel calibration."""
    try:
        return engine.field_of_view()
    except ValueError as exc:
        pytest.skip(str(exc))


def run(engine, sequence, output=None):
    runner = MDARunner()
    runner.set_engine(engine)
    runner.run(sequence, output=output)
    return runner


def images_in(folder):
    """How many images the OME-TIFF files under ``folder`` hold."""
    return sum(int(np.prod(tifffile.imread(f).shape[:-2])) for f in folder.rglob("*.ome.tif*"))


# -- 1. the engine -------------------------------------------------------------------------


def test_engine_reads_the_microscope(engine):
    client = engine.client
    print(client.info)
    assert set(client.request("get_position")) == {"x", "y", "z"}
    assert set(engine.limits()) == {"x", "y", "z"}
    assert client.request("get_optical_configurations"), "NIS lists no optical configurations"
    print(client.request("get_objectives"), client.request("get_pfs"))


def test_engine_moves_a_little_and_back(engine, here):
    moved = engine.client.request("move", x=here["x"] + 20, z=here["z"] + 2)
    assert moved["x"] == pytest.approx(here["x"] + 20, abs=1.0)
    assert moved["z"] == pytest.approx(here["z"] + 2, abs=0.5)
    back = engine.client.request("move", **here)
    assert back["x"] == pytest.approx(here["x"], abs=1.0)


def test_engine_sets_a_configuration_and_exposure(engine, configuration):
    assert engine.client.request("select_optical_configuration", name=configuration)["selected"]
    applied = engine.client.request("set_exposure", exposure_ms=20)["exposure_ms"]
    print("exposure asked 20 ms, applied", applied)
    assert applied == pytest.approx(20, rel=0.2)


def test_engine_measures_the_camera_field(engine, field):
    width, height = field
    print(f"camera field {width:.1f} x {height:.1f} um")
    assert width > 0 and height > 0


def test_engine_checks_limits_without_moving(engine, here):
    beyond = engine.limits()["z"]["max"] + 100
    with pytest.raises(ValueError, match="outside the stage limits"):
        engine.check(useq.MDASequence(stage_positions=[(here["x"], here["y"], beyond)]))
    assert engine.client.request("get_position")["z"] == pytest.approx(here["z"], abs=0.5)


# -- 2. useq sequences ------------------------------------------------------------------------


def test_useq_v2_sequence_with_the_pymmcore_plus_runner(engine, here, configuration, tmp_path):
    sequence = v2.MDASequence(
        stage_positions=[
            (here["x"], here["y"], here["z"]),
            (here["x"] + 50, here["y"], here["z"]),
        ],
        channels=[configuration],
        z_plan={"range": 4, "step": 2},
    )
    positions = []

    class Frames:
        def frameReady(self, image, event, meta):
            positions.append(meta["position"])

    run(engine, sequence, output=[Frames(), tmp_path / "run.ome.tiff"])
    assert len(positions) == 6
    assert positions[3]["x"] == pytest.approx(here["x"] + 50, abs=1.0)
    assert [p["z"] for p in positions[:3]] == pytest.approx(
        [here["z"] - 2, here["z"], here["z"] + 2], abs=0.5
    )
    assert images_in(tmp_path) == 6


def test_useq_classic_sequence_keeps_its_axes(engine, here, two_configurations, tmp_path):
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[{"config": name, "exposure": 20} for name in two_configurations],
        z_plan={"range": 2, "step": 1},
    )
    run(engine, sequence, output=tmp_path / "run.ome.tiff")
    data = tifffile.imread(tmp_path / "run.ome.tiff")
    print("saved", data.shape, data.dtype)
    assert data.shape[:2] == (2, 3)  # channels, planes


def test_useq_tiles_spaced_by_the_camera_field(engine, here, configuration, field, tmp_path):
    grid = {"rows": 1, "columns": 2, "overlap": (10, 10), "fov_width": field[0],
            "fov_height": field[1]}  # fmt: skip
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[configuration],
        grid_plan=grid,
        axis_order="tpgcz",
    )
    events = engine.check(sequence)
    step = abs(events[1].x_pos - events[0].x_pos)
    assert step == pytest.approx(field[0] * 0.9, rel=0.01)  # one field less the overlap
    run(engine, sequence, output=tmp_path / "tiles.ome.tiff")
    assert images_in(tmp_path) == 2


def test_useq_channel_options(engine, here, two_configurations, tmp_path):
    first, second = two_configurations
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[{"config": first}, {"config": second, "do_stack": False}],
        z_plan={"range": 2, "step": 1},
    )
    run(engine, sequence, output=tmp_path / "run.ome.tiff")
    assert images_in(tmp_path) == 3 + 1  # a stack in the first, one plane in the second


def test_useq_sequence_from_a_file(engine, here, configuration, tmp_path):
    path = tmp_path / "sequence.json"
    path.write_text(json.dumps({
        "stage_positions": [{"x": here["x"], "y": here["y"], "z": here["z"]}],
        "channels": [{"config": configuration}],
        "time_plan": {"interval": 0.5, "loops": 2},
    }))  # fmt: skip
    run(engine, useq.MDASequence.from_file(path), output=tmp_path / "run.ome.tiff")
    assert images_in(tmp_path) == 2


# -- 3. the assistant, with a scripted model ---------------------------------------------------


@pytest.fixture
def talk(engine, tmp_path):
    """An assistant on the real microscope whose "model" plays the given steps."""
    pytest.importorskip("pydantic_ai")
    from nis_useq.agent import Assistant, Microscope
    from test_agent import Script

    def make(*steps, vision="A test image."):
        microscope = Microscope(engine, output_dir=tmp_path / "runs")
        microscope.vision_model = Script(vision).model()
        return Assistant(microscope, model=Script(*steps).model())

    return make


def results(assistant):
    from test_agent import tool_results

    return tool_results(assistant)


def test_agent_reads_and_moves_a_little(talk, here):
    assistant = talk(
        ("get_status", {}), ("move_stage", {"x": here["x"] + 30}), ("move_stage", here), "Done."
    )
    assert assistant.send("status, then a small step and back") == "Done."
    status, moved, back = results(assistant)
    assert status["optical_configurations"] and moved["x"] == pytest.approx(here["x"] + 30, abs=1)
    assert back["x"] == pytest.approx(here["x"], abs=1)


def test_agent_looks_at_a_real_image(talk):
    assistant = talk(("look", {"question": "what do you see?"}), "Seen.")
    assistant.send("look")
    (result,) = results(assistant)
    print("image statistics", result["statistics"])
    assert result["answer"] == "A test image." and result["statistics"]["max"] > 0


def test_agent_refuses_a_move_beyond_the_limits(engine, talk, here):
    beyond = engine.limits()["z"]["max"] + 100
    assistant = talk(("move_stage", {"z": beyond}), "Refused.")
    assistant.send("go beyond the limit")
    assert results(assistant)[0]["error"]["code"] == "limit"
    assert engine.client.request("get_position")["z"] == pytest.approx(here["z"], abs=0.5)


def test_agent_asks_before_a_long_move(engine, talk, here):
    assistant = talk(("move_stage", {"x": here["x"] + 5000}), "Shall I move 5 mm?")
    assistant.send("move 5 mm")  # the operator never says yes, so nothing moves
    assert results(assistant)[0]["status"] == "needs_go_ahead"
    assert engine.client.request("get_position")["x"] == pytest.approx(here["x"], abs=1.0)


def test_agent_plans_then_runs_after_the_go_ahead(talk, configuration):
    plan = {"name": "hardware", "channels": [{"config": configuration}],
            "z_stack": {"range_um": 2, "step_um": 1}}  # fmt: skip
    run_it = ("run_acquisition", {"plan_id": "hardware-1"})
    assistant = talk(("plan_acquisition", plan), run_it, "Shall I start?", run_it, "Saved.")
    assistant.send("a small stack here")
    planned, asked = results(assistant)
    print(planned["summary"])
    assert planned["images"] == 3 and asked["status"] == "needs_go_ahead"
    assistant.send("yes")
    ran = results(assistant)[-1]
    assert ran["images"] == 3 and ran["finished"] == "completed"
    assert tifffile.imread(ran["saved_to"]).shape[0] == 3
