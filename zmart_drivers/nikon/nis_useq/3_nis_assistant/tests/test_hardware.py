"""Step 3 on a running NIS-Elements (the Ti2 simulator, or a real microscope).

    pytest -m hardware -s

Needs start_bridge.mac running in NIS, and steps 1 and 2 (nis-bridge, nis-engine)
passing; skipped when no bridge answers. The assistant is driven by a scripted
model, not a real one, so this costs no API calls; the real model is tried by
hand in the window (see README). Everything stays within 100 um of where the
stage is, and the stage is moved back afterwards.
"""

import pytest
import tifffile
from nis_bridge.client import NisConnectionError
from nis_engine import NisEngine
from test_agent import Script, tool_results

from nis_assistant.agent import Assistant, Microscope

pytestmark = pytest.mark.hardware


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
def talk(engine, tmp_path):
    """An assistant on the real microscope whose "model" plays the given steps."""

    def make(*steps, vision="A test image."):
        microscope = Microscope(engine, output_dir=tmp_path / "runs")
        microscope.vision_model = Script(vision).model()
        return Assistant(microscope, model=Script(*steps).model())

    return make


def test_reads_and_moves_a_little(talk, here):
    assistant = talk(
        ("get_status", {}), ("move_stage", {"x": here["x"] + 30}), ("move_stage", here), "Done."
    )
    assert assistant.send("status, then a small step and back") == "Done."
    status, moved, back = tool_results(assistant)
    assert status["optical_configurations"] and moved["x"] == pytest.approx(here["x"] + 30, abs=1)
    assert back["x"] == pytest.approx(here["x"], abs=1)


def test_looks_at_a_real_image(talk):
    assistant = talk(("look", {"question": "what do you see?"}), "Seen.")
    assistant.send("look")
    (result,) = tool_results(assistant)
    print("image statistics", result["statistics"])
    assert result["answer"] == "A test image." and result["statistics"]["max"] > 0


def test_refuses_a_move_beyond_the_limits(engine, talk, here):
    beyond = engine.limits()["z"]["max"] + 100
    assistant = talk(("move_stage", {"z": beyond}), "Refused.")
    assistant.send("go beyond the limit")
    assert tool_results(assistant)[0]["error"]["code"] == "limit"
    assert engine.client.request("get_position")["z"] == pytest.approx(here["z"], abs=0.5)


def test_asks_before_a_long_move(engine, talk, here):
    assistant = talk(("move_stage", {"x": here["x"] + 5000}), "Shall I move 5 mm?")
    assistant.send("move 5 mm")  # the operator never says yes, so nothing moves
    assert tool_results(assistant)[0]["status"] == "needs_go_ahead"
    assert engine.client.request("get_position")["x"] == pytest.approx(here["x"], abs=1.0)


def test_plans_then_runs_after_the_go_ahead(talk, configuration):
    plan = {"name": "hardware", "channels": [{"config": configuration}],
            "z_stack": {"range_um": 2, "step_um": 1}}  # fmt: skip
    run_it = ("run_acquisition", {"plan_id": "hardware-1"})
    assistant = talk(("plan_acquisition", plan), run_it, "Shall I start?", run_it, "Saved.")
    assistant.send("a small stack here")
    planned, asked = tool_results(assistant)
    print(planned["summary"])
    assert planned["images"] == 3 and asked["status"] == "needs_go_ahead"
    assistant.send("yes")
    ran = tool_results(assistant)[-1]
    assert ran["images"] == 3 and ran["finished"] == "completed"
    assert tifffile.imread(ran["saved_to"]).shape[0] == 3
