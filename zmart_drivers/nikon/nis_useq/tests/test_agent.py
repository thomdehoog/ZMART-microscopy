"""The assistant's tools and approvals, with a scripted model in place of Claude.

``Script`` plays the model: it makes the tool calls it is given, in order, so
each test controls exactly what "Claude" asks for and checks what the
microscope (the real bridge over a fake NIS) and the operator see.
"""

import pytest
import tifffile

pytest.importorskip("pydantic_ai")
pytest.importorskip("pymmcore_plus")

from nis_useq.agent import Assistant, Microscope, as_png, image_statistics  # noqa: E402
from nis_useq.engine import NisEngine  # noqa: E402
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402


class Script:
    """A stand-in for the model: each call returns the next step (a tool call or text)."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []  # what the model was sent, per call

    def __call__(self, messages, info):
        self.requests.append(messages)
        step = self.steps.pop(0)
        if isinstance(step, str):
            return ModelResponse(parts=[TextPart(step)])
        name, args = step
        return ModelResponse(parts=[ToolCallPart(name, args)])

    def model(self):
        return FunctionModel(self)


@pytest.fixture
def microscope(port, tmp_path):
    engine = NisEngine("127.0.0.1", port, timeout=5.0)
    scope = Microscope(engine, output_dir=tmp_path / "runs")
    scope.images, scope.warnings = [], []
    scope.on_image = lambda image, caption: scope.images.append((image, caption))
    scope.on_warning = scope.warnings.append
    yield scope
    engine.close()


def talk(microscope, *steps):
    script = Script(*steps)
    return Assistant(microscope, model=script.model()), script


def tool_results(assistant):
    return [
        part.content
        for message in assistant.history
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def moves(fake):
    return [call for call in fake.calls if call.startswith("move")]


# -- reading and small actions -----------------------------------------------------


def test_every_message_carries_the_microscope_state(microscope):
    assistant, script = talk(microscope, "Hello!")
    reply = assistant.send("hi")
    assert reply.text == "Hello!" and reply.approvals == []
    prompt = script.requests[0][-1].parts[-1].content
    assert prompt.startswith("hi") and "<microscope_state>" in prompt and "position_um" in prompt


def test_status(microscope):
    assistant, _ = talk(microscope, ("get_status", {}), "Here is the status.")
    assistant.send("where are we?")
    status = tool_results(assistant)[0]
    assert status["position_um"] == {"x": 1000.0, "y": -500.0, "z": 500.0}
    assert "DAPI" in status["optical_configurations"]


def test_small_move_runs_at_once(microscope, fake):
    assistant, _ = talk(microscope, ("move_stage", {"x": 1100, "z": 510}), "Moved.")
    reply = assistant.send("move a little")
    assert reply.approvals == [] and moves(fake) == ["move_xyz(1100,-500,510)"]


def test_limit_breach_is_refused_and_reported_to_the_window(microscope, fake):
    assistant, _ = talk(microscope, ("move_stage", {"z": 20000}), "That is outside the limits.")
    assistant.send("go to z 20 mm")
    assert tool_results(assistant)[0].startswith("REFUSED: LIMIT BREACH: z = 20000 um")
    assert microscope.warnings and "LIMIT BREACH" in microscope.warnings[0]
    assert moves(fake) == []


# -- actions that wait for the operator ---------------------------------------------


def test_large_move_waits_for_confirm(microscope, fake):
    assistant, _ = talk(microscope, ("move_stage", {"x": 20000}), "Done, we are there.")
    reply = assistant.send("go to x 20 mm")
    assert moves(fake) == []  # nothing happened yet
    (approval,) = reply.approvals
    assert approval.tool == "move_stage" and "19000 um in XY" in approval.summary

    reply = assistant.decide({approval.id: True})
    assert moves(fake) == ["move_xy(20000,-500)"] and reply.text == "Done, we are there."


def test_declined_move_does_not_happen(microscope, fake):
    assistant, _ = talk(microscope, ("move_stage", {"z": 900}), "Understood, I stayed.")
    reply = assistant.decide({a.id: False for a in assistant.send("focus up").approvals})
    assert moves(fake) == [] and reply.text == "Understood, I stayed."
    assert "declined" in tool_results(assistant)[0]


def test_objective_change_waits_for_confirm(microscope, fake):
    assistant, _ = talk(microscope, ("set_microscope", {"objective_slot": 4}), "Now on 60x.")
    reply = assistant.send("use the 60x")
    assert "slot 4 (Plan Apo 60x WI)" in reply.approvals[0].summary and fake.nosepiece == 1
    assistant.decide({reply.approvals[0].id: True})
    assert fake.nosepiece == 4


def test_settings_that_need_no_confirm(microscope, fake):
    call = {"optical_configuration": "FITC", "exposure_ms": 20.4, "pfs_on": True}
    assistant, _ = talk(microscope, ("set_microscope", call), "Set.")
    assistant.send("FITC at 20 ms with PFS")
    assert tool_results(assistant)[0] == {
        "optical_configuration": "FITC",
        "exposure_ms": 20,
        "pfs": "on, focused",
    }


def test_unknown_configuration_is_refused(microscope):
    assistant, _ = talk(
        microscope, ("set_microscope", {"optical_configuration": "GFP"}), "Not available."
    )
    assistant.send("use GFP")
    assert tool_results(assistant)[0].startswith("REFUSED: 'GFP' is not a configuration")


def test_a_nis_error_becomes_a_message_not_a_crash(microscope, fake):
    fake.autofocus_result = 0
    assistant, _ = talk(microscope, ("focus", {"method": "image_sweep"}), "Focus failed.")
    reply = assistant.send("autofocus please")
    assert reply.text == "Focus failed."
    assert tool_results(assistant)[0] == "FAILED: StgFocusInRangeEx: focus not found (0)"


# -- focus and vision -----------------------------------------------------------------


def test_pfs_focus(microscope, fake):
    assistant, _ = talk(microscope, ("focus", {"method": "pfs"}), "In focus.")
    assistant.send("focus")
    assert tool_results(assistant)[0] == {
        "focused": True,
        "z_before_um": 500.0,
        "z_after_um": 502.0,
    }
    assert fake.pfs_on is False  # switched off again after locking


def test_look_shows_the_image_and_asks_a_vision_model(microscope):
    vision = Script("A uniform field with no visible structures.")
    microscope.vision_model = vision.model()
    assistant, _ = talk(microscope, ("look", {"question": "what do you see?"}), "Nothing yet.")
    assistant.send("look at the sample")

    result = tool_results(assistant)[0]
    assert result["answer"] == "A uniform field with no visible structures."
    assert result["statistics"]["saturated_percent"] == 0.0
    image, caption = microscope.images[0]
    assert image.shape == (48, 64) and caption == "what do you see?"
    # the vision model got the question, the measurements and a PNG
    question, png = vision.requests[0][-1].parts[-1].content
    assert "what do you see?" in question and "sharpness" in question
    assert png.media_type == "image/png"


def test_image_statistics_and_png():
    import numpy as np

    image = np.zeros((2000, 1000), dtype=np.uint16)
    image[:10, :10] = 65535
    stats = image_statistics(image)
    assert stats["max"] == 65535 and stats["saturated_percent"] == 0.01
    assert as_png(image).media_type == "image/png"


# -- planning and running an acquisition ----------------------------------------------


PLAN = {
    "name": "stack_test",
    "positions": [{"x": 100, "y": 200, "z": 500, "name": "a"}],
    "channels": [{"config": "DAPI", "exposure_ms": 20}, {"config": "FITC"}],
    "z_stack": {"range_um": 2, "step_um": 1},
}


def test_plan_then_run(microscope, fake):
    assistant, _ = talk(
        microscope,
        ("plan_acquisition", {"plan": PLAN}),
        ("run_acquisition", {"plan_id": "stack_test-1"}),
        "All six images are saved.",
    )
    reply = assistant.send("take a two-channel stack at a")
    plan = tool_results(assistant)[0]
    assert plan["plan_id"] == "stack_test-1" and plan["images"] == 6
    assert moves(fake) == []  # planning never moves
    (approval,) = reply.approvals
    assert approval.tool == "run_acquisition" and "'images': 6" in approval.summary

    reply = assistant.decide({approval.id: True})
    run = tool_results(assistant)[-1]
    assert run["images"] == 6 and run["finished"] == "completed"
    assert tifffile.imread(run["saved_to"]).shape == (2, 3, 48, 64)
    assert list(microscope.output_dir.glob("*.plan.json"))
    assert len(microscope.images) == 6 and reply.text == "All six images are saved."


def test_plan_with_a_problem_is_refused_before_anything_moves(microscope, fake):
    bad = {**PLAN, "positions": [{"x": 100, "y": 200, "z": 20000}]}
    assistant, _ = talk(microscope, ("plan_acquisition", {"plan": bad}), "That plan cannot run.")
    assistant.send("plan it")
    assert "outside the stage limits" in tool_results(assistant)[0]
    assert microscope.warnings and moves(fake) == [] and fake.captures == 0


def test_a_malformed_plan_goes_back_to_the_model(microscope):
    bad = {**PLAN, "channels": []}  # a plan needs at least one channel
    assistant, script = talk(
        microscope, ("plan_acquisition", {"plan": bad}), ("plan_acquisition", {"plan": PLAN}), "OK."
    )
    assistant.send("plan it")
    retry = script.requests[1][-1].parts[-1]
    assert retry.part_kind == "retry-prompt"  # Pydantic caught it before our code ran
    assert tool_results(assistant)[0]["plan_id"] == "stack_test-1"


def test_history_is_only_ever_appended_to(microscope):
    assistant, _ = talk(microscope, "one", "two")
    assistant.send("first")
    before = list(assistant.history)
    assistant.send("second")
    assert assistant.history[: len(before)] == before
