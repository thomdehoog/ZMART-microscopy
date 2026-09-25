"""The assistant's tools and approvals, with a scripted model in place of Claude.

``Script`` plays the model: it makes the tool calls it is given, in order, so
each test controls exactly what "Claude" asks for and checks what the
microscope (the real bridge over a fake NIS) and the operator see.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
import useq

pytest.importorskip("pydantic_ai")
pytest.importorskip("pymmcore_plus")

from nis_assistant.agent import (  # noqa: E402
    GO_AHEAD_ADVICE,
    HISTORY_KEEP_TURNS,
    LIMIT_ADVICE,
    MODEL_SETTINGS,
    OPTIONS_ADVICE,
    Assistant,
    Microscope,
    as_png,
    image_statistics,
)
from nis_bridge.client import NisConnectionError  # noqa: E402
from nis_engine import NisEngine  # noqa: E402
from pydantic_ai.messages import (  # noqa: E402
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel  # noqa: E402


class Script:
    """A stand-in for the model: each call returns the next step.

    A step is text (the answer), a (tool name, arguments) pair (a tool call), a
    whole ModelResponse, or an exception (the model call fails, as when the API
    is overloaded).
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []  # what the model was sent, per call

    def __call__(self, messages, info):
        self.requests.append(messages)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, ModelResponse):
            return step
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
    scope.images, scope.warnings, scope.tools = [], [], []
    scope.on_image = lambda image, caption: scope.images.append((image, caption))
    scope.on_warning = scope.warnings.append
    scope.on_tool = lambda name, args: scope.tools.append((name, args))
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
    assert assistant.send("hi") == "Hello!"
    prompt = script.requests[0][-1].parts[-1].content
    assert prompt.startswith("hi") and "<microscope_state>" in prompt and "position_um" in prompt


def test_a_quoted_state_block_is_taken_out_of_the_reply(microscope):
    quoted = 'Exposure set.\n\n<microscope_state>{"position_um": {"x": 1}}</microscope_state>'
    cut_off = 'Done. <microscope_state>{"position_um": {"x": 1'  # a block the model did not close
    assistant, _ = talk(microscope, quoted, cut_off)
    assert assistant.send("50 ms please") == "Exposure set."
    assert assistant.send("thanks") == "Done."
    assert "<microscope_state>" in assistant.history[1].parts[0].content  # its own copy stays


def test_the_model_acts_one_step_at_a_time():
    assert MODEL_SETTINGS["parallel_tool_calls"] is False
    assert MODEL_SETTINGS["max_tokens"] >= 16000


def test_status(microscope):
    assistant, _ = talk(microscope, ("get_status", {}), "Here is the status.")
    assistant.send("where are we?")
    status = tool_results(assistant)[0]
    assert status["position_um"] == {"x": 1000.0, "y": -500.0, "z": 500.0}
    assert "DAPI" in status["optical_configurations"]


def test_the_window_hears_of_each_tool_call(microscope):
    assistant, _ = talk(microscope, ("move_stage", {"x": 1100}), "Moved.")
    assistant.send("move a little")
    assert microscope.tools == [("move_stage", {"x": 1100})]


def test_small_move_runs_at_once(microscope, fake):
    assistant, _ = talk(microscope, ("move_stage", {"x": 1100, "z": 510}), "Moved.")
    assistant.send("move a little")
    assert moves(fake) == ["move_xyz(1100,-500,510)"]


def test_limit_breach_is_refused_with_advice_and_shown_in_the_window(microscope, fake):
    assistant, _ = talk(microscope, ("move_stage", {"z": 20000}), "That is outside the limits.")
    assistant.send("go to z 20 mm")
    error = tool_results(assistant)[0]["error"]
    assert error["code"] == "limit" and error["advice"] == LIMIT_ADVICE
    assert error["message"].startswith("z = 20000 um is outside the stage limits [0, 10000]")
    assert microscope.warnings == [error["message"]] and moves(fake) == []


# -- long moves are asked about in the chat first ------------------------------------------

LONG = ("move_stage", {"x": 20000})


def test_a_long_move_is_asked_about_in_the_chat_first(microscope, fake):
    assistant, _ = talk(microscope, LONG, "Shall I move 19 mm to x = 20 mm?", LONG, "We are there.")
    assert assistant.send("go to x 20 mm") == "Shall I move 19 mm to x = 20 mm?"
    question = tool_results(assistant)[0]
    assert question["status"] == "needs_go_ahead" and question["advice"] == GO_AHEAD_ADVICE
    assert "19000 um in XY" in question["not_done_yet"] and moves(fake) == []

    assert assistant.send("yes, go ahead") == "We are there."
    assert moves(fake) == ["move_xy(20000,-500)"]


def test_when_the_operator_says_no_nothing_moves(microscope, fake):
    assistant, _ = talk(microscope, LONG, "Shall I?", "OK, we stay here.")
    assistant.send("go to x 20 mm")
    assert assistant.send("no, stay") == "OK, we stay here." and moves(fake) == []


def test_asking_twice_in_one_turn_is_not_a_go_ahead(microscope, fake):
    assistant, _ = talk(microscope, LONG, LONG, "Shall I?")
    assistant.send("go to x 20 mm")
    assert [r["status"] for r in tool_results(assistant)] == ["needs_go_ahead"] * 2
    assert moves(fake) == []


def test_a_go_ahead_counts_only_for_the_next_message(microscope, fake):
    assistant, _ = talk(microscope, LONG, "Shall I?", "Sure.", LONG, "Shall I?")
    assistant.send("go to x 20 mm")
    assistant.send("hmm, tell me something else first")
    assistant.send("do it")  # two messages later: asked again, not moved
    assert tool_results(assistant)[-1]["status"] == "needs_go_ahead" and moves(fake) == []


def test_small_steps_that_add_up_are_asked_about_too(microscope, fake):
    steps = [("move_stage", {"z": 500 + 60 * n}) for n in (1, 2)]
    assistant, _ = talk(microscope, *steps, "Shall I go on?")
    assistant.send("walk the focus up")
    # 560 ran (60 um from where the stage was); 620 is 120 um from there, so it asks
    assert moves(fake) == ["move_z(560)"]
    assert "120 um in Z" in tool_results(assistant)[1]["not_done_yet"]


# -- settings ------------------------------------------------------------------------------


def test_settings_change_without_asking(microscope, fake):
    call = {"optical_configuration": "FITC", "exposure_ms": 20.4, "objective_slot": 4}
    assistant, _ = talk(microscope, ("set_microscope", call), "Set.")
    assistant.send("the 60x in FITC at 20 ms")
    assert tool_results(assistant)[0] == {
        "optical_configuration": "FITC",
        "objective_slot": 4,
        "exposure_ms": 20,
    }
    assert fake.nosepiece == 4


@pytest.mark.parametrize(
    "call, message, options",
    [
        (
            {"optical_configuration": "GFP"},
            "'GFP' is not an optical configuration",
            ["DAPI", "FITC", "TxRed", "Brightfield"],
        ),
        ({"objective_slot": 3}, "no objective in nosepiece slot 3", None),
        ({"exposure_ms": 1e9}, "between 0 and 60000 ms", None),
    ],
)
def test_bad_settings_are_refused_before_anything_changes(microscope, fake, call, message, options):
    assistant, _ = talk(microscope, ("set_microscope", {**call, "pfs_on": True}), "Not possible.")
    assistant.send("change it")
    error = tool_results(assistant)[0]["error"]
    assert error["code"] == "invalid" and message in error["message"] and fake.calls == []
    if options:
        assert error["configured_options"] == options and error["advice"] == OPTIONS_ADVICE


def test_an_empty_slot_refusal_lists_the_fitted_objectives(microscope):
    assistant, _ = talk(microscope, ("set_microscope", {"objective_slot": 3}), "Slot 3 is empty.")
    assistant.send("use slot 3")
    assert tool_results(assistant)[0]["error"]["configured_options"] == {
        "1": "Plan Apo 10x",
        "2": "Apo 20x WI",
        "4": "Plan Apo 60x WI",
    }


def test_a_nis_error_becomes_a_failure_with_advice(microscope, fake):
    fake.autofocus_result = 0
    assistant, _ = talk(microscope, ("focus", {"method": "image_sweep"}), "Focus failed.")
    assert assistant.send("autofocus please") == "Focus failed."
    error = tool_results(assistant)[0]["error"]
    assert error["message"] == "RuntimeError: StgFocusInRangeEx: focus not found (0)"
    assert error["code"] == "failed" and "propose one fix as a question" in error["advice"]


# -- cancelling and failing ------------------------------------------------------------------


def test_after_cancel_no_tool_does_anything(microscope, fake):
    def cancel_after_the_first_call(name, args):
        microscope.cancel.set()  # the operator presses Cancel during the first move

    microscope.on_tool = cancel_after_the_first_call
    steps = [("move_stage", {"x": 1100}), ("move_stage", {"x": 1200}), "Stopped."]
    assistant, _ = talk(microscope, *steps, ("move_stage", {"x": 1300}), "Moved.")
    assistant.send("move twice")
    assert moves(fake) == ["move_xy(1100,-500)"]
    assert tool_results(assistant)[1]["status"] == "cancelled"
    microscope.on_tool = lambda name, args: None
    assistant.send("move again")  # a new message starts without the cancel
    assert moves(fake)[-1] == "move_xy(1300,-500)"


def test_the_conversation_survives_a_model_failure_after_a_move(microscope, fake):
    overloaded = RuntimeError("API overloaded (529)")
    step = ("move_stage", {"x": 1500})
    assistant, _ = talk(microscope, step, overloaded, "We are at x 1.5 mm.")
    with pytest.raises(RuntimeError, match="overloaded"):
        assistant.send("go to x 1.5 mm")
    assert moves(fake) == ["move_xy(1500,-500)"]  # the move did happen
    assert assistant.send("are we there?") == "We are at x 1.5 mm."  # and the talk goes on
    assert tool_results(assistant)[0]["x"] == 1500  # the model got the move's result


# -- focus and vision -----------------------------------------------------------------


def test_pfs_focus_leaves_the_pfs_as_it_was(microscope, fake):
    assistant, _ = talk(microscope, ("focus", {"method": "pfs"}), "In focus.")
    assistant.send("focus")
    assert tool_results(assistant)[0] == {
        "focused": True,
        "z_before_um": 500.0,
        "z_after_um": 502.0,
    }
    assert fake.pfs_on is False


@pytest.mark.parametrize(
    "z, range_um, code, message",
    [
        (500, 500, "invalid", "between 0 and 100 um"),
        (9980, 100, "limit", "a 100 um sweep around z = 9980 um would leave the Z limits"),
    ],
)
def test_focus_sweep_is_small_and_inside_the_limits(microscope, fake, z, range_um, code, message):
    fake.position["z"] = z
    call = {"method": "image_sweep", "range_um": range_um}
    assistant, _ = talk(microscope, ("focus", call), "Refused.")
    assistant.send("find focus")
    error = tool_results(assistant)[0]["error"]
    assert error["code"] == code and message in error["message"]
    assert not any("autofocus" in c for c in fake.calls)


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


def test_a_camera_failure_is_reported_with_advice(microscope, fake):
    fake.camera_fails = True
    assistant, _ = talk(microscope, ("look", {"question": "what do you see?"}), "No image.")
    assistant.send("look")
    error = tool_results(assistant)[0]["error"]
    assert "camera did not answer" in error["message"] and error["code"] == "failed"


@pytest.mark.parametrize("shape", [(2000, 1000), (300, 200, 3)], ids=["mono", "colour"])
def test_image_statistics_and_png(shape):
    image = np.zeros(shape, dtype=np.uint16)
    image[:10, :10] = 65535
    stats = image_statistics(image)
    assert stats["max"] == 65535 and stats["saturated_percent"] > 0
    assert as_png(image).media_type == "image/png"


# -- planning and running an acquisition ----------------------------------------------


PLAN = {  # the flat form, as Claude sends it
    "name": "stack_test",
    "positions": [{"x": 100, "y": 200, "z": 500, "name": "a"}],
    "channels": [{"config": "DAPI", "exposure_ms": 20}, {"config": "FITC"}],
    "z_stack": {"range_um": 2, "step_um": 1},
}
RUN = ("run_acquisition", {"plan_id": "stack_test-1"})


def test_an_acquisition_starts_only_after_the_operator_saw_the_plan(microscope, fake):
    steps = [("plan_acquisition", PLAN), RUN, "Shall I start these 6 images?", RUN, "Saved."]
    assistant, _ = talk(microscope, *steps)
    assert assistant.send("take a two-channel stack at a") == "Shall I start these 6 images?"
    plan, question = tool_results(assistant)
    assert plan["plan_id"] == "stack_test-1" and plan["images"] == 6
    assert "a at x 100, y 200, z 500 um" in plan["summary"] and "900 um in XY" in plan["summary"]
    assert question["status"] == "needs_go_ahead" and "6 images" in question["not_done_yet"]
    assert fake.captures == 0 and moves(fake) == []  # nothing happened yet

    assert assistant.send("yes, start") == "Saved."
    run = tool_results(assistant)[-1]
    assert run["images"] == 6 and run["finished"] == "completed"
    assert tifffile.imread(run["saved_to"]).shape == (2, 3, 48, 64)
    assert list(microscope.output_dir.glob("*.useq.json")) and len(microscope.images) == 6


def test_the_plan_comes_back_as_a_useq_sequence(microscope):
    assistant, _ = talk(microscope, ("plan_acquisition", PLAN), "Here is the plan.")
    assistant.send("plan a stack at a")
    sequence = useq.MDASequence(**tool_results(assistant)[0]["useq_sequence"])
    assert len(list(sequence)) == 6 and sequence.channels[0].config == "DAPI"


def test_a_plan_the_operator_declines_is_not_run(microscope, fake):
    steps = [("plan_acquisition", PLAN), RUN, "Shall I start?", "OK, not now."]
    assistant, _ = talk(microscope, *steps)
    assistant.send("take a stack")
    assistant.send("no")
    assert fake.captures == 0 and not microscope.output_dir.exists()


def test_a_far_away_plan_says_so(microscope):
    far = {**PLAN, "positions": [{"x": 50000, "y": 30000, "z": 900}]}
    assistant, _ = talk(microscope, ("plan_acquisition", far), "Shall I? It is far.")
    assistant.send("image over there")
    summary = tool_results(assistant)[0]["summary"]
    assert "49000 um in XY and 401 um in Z" in summary and "This includes a long move." in summary


def test_the_run_images_exactly_the_planned_positions(microscope, fake):
    here = {**PLAN, "positions": []}  # "here" is fixed when the plan is made
    steps = [
        ("plan_acquisition", here),
        ("move_stage", {"x": 1100}),
        "Shall I start?",
        RUN,
        "Done.",
    ]
    assistant, _ = talk(microscope, *steps)
    assistant.send("stack here")
    assert "here at x 1000, y -500, z 500 um" in tool_results(assistant)[0]["summary"]
    assistant.send("yes")
    assert fake.position["x"] == 1000.0  # imaged at the planned x, not where the stage went


def test_a_tiled_plan_measures_the_field_and_makes_a_useq_grid(microscope, fake):
    fake.calibrated = True  # 0.108 um per pixel, 64 x 48 pixels
    tiled = {**PLAN, "z_stack": None, "grid": {"rows": 2, "columns": 3, "overlap_percent": 10}}
    assistant, _ = talk(microscope, ("plan_acquisition", tiled), "Shall I start?")
    assistant.send("tile around a")
    plan = tool_results(assistant)[0]
    grid = plan["useq_sequence"]["grid_plan"]
    assert (grid["rows"], grid["columns"]) == (2, 3) and grid["fov_width"] == pytest.approx(6.912)
    assert plan["images"] == 12 and "each as 2 x 3 tiles" in plan["summary"]
    assert fake.captures == 1 and moves(fake) == []  # one image to measure the field, no move


def test_a_run_over_several_positions_is_saved_as_a_folder(microscope, fake):
    fake.calibrated = True
    tiled = {**PLAN, "z_stack": None, "grid": {"rows": 1, "columns": 2}}
    steps = [("plan_acquisition", tiled), "Shall I start?", RUN, "Saved."]
    assistant, _ = talk(microscope, *steps)
    assistant.send("two tiles at a")
    assistant.send("yes")
    folder = Path(tool_results(assistant)[-1]["saved_to"])
    assert folder.is_dir() and len(list(folder.glob("*.ome.tiff"))) == 2


def test_a_grid_without_a_pixel_calibration_is_refused(microscope):
    tiled = {**PLAN, "grid": {"rows": 2, "columns": 2}}
    assistant, _ = talk(microscope, ("plan_acquisition", tiled), "The objective is not calibrated.")
    assistant.send("tile it")
    assert "no pixel calibration" in tool_results(assistant)[0]["error"]["message"]


def test_channels_can_skip_the_stack_and_time_points(microscope):
    plan = {
        **PLAN,
        "channels": [
            {"config": "DAPI"},
            {"config": "Brightfield", "do_stack": False},
            {"config": "FITC", "acquire_every": 2, "z_offset_um": 1.5},
        ],
        "time_points": 2,
        "interval_s": 5,
    }
    assistant, _ = talk(microscope, ("plan_acquisition", plan), "Shall I start?")
    assistant.send("plan it")
    result = tool_results(assistant)[0]
    # per time point: DAPI 3 planes + Brightfield 1; FITC 3 planes at the first only
    assert result["images"] == 2 * (3 + 1) + 3
    assert "Brightfield (one plane)" in result["summary"]
    assert "FITC (every 2 time points, +1.5 um in z)" in result["summary"]
    assert "2 time points 5 s apart" in result["summary"]


SEQUENCE = {  # a classic useq MDASequence, as another useq tool would save it
    "stage_positions": [{"x": 1200, "y": -500, "z": 500, "name": "cell"}],
    "channels": [{"config": "DAPI", "exposure": 30}, {"config": "TxRed"}],
    "z_plan": {"range": 4, "step": 2},
}


def test_a_useq_file_from_elsewhere_is_checked_and_run(microscope, fake, tmp_path):
    path = tmp_path / "from_widgets.json"
    path.write_text(json.dumps(SEQUENCE))
    call = ("plan_useq_sequence", {"name": "widgets", "path": str(path)})
    run = ("run_acquisition", {"plan_id": "widgets-1"})
    assistant, _ = talk(microscope, call, "Shall I start?", run, "Saved.")
    assistant.send(f"run the sequence in {path}")
    plan = tool_results(assistant)[0]
    assert plan["images"] == 6 and "cell at x 1200, y -500, z 500 um" in plan["summary"]
    assert fake.captures == 0  # nothing starts before the operator agrees

    assistant.send("yes")
    run_result = tool_results(assistant)[-1]
    assert tifffile.imread(run_result["saved_to"]).shape == (2, 3, 48, 64)
    (saved,) = microscope.output_dir.glob("*.useq.json")
    assert useq.MDASequence.from_file(saved) == useq.MDASequence(**SEQUENCE)


def test_a_useq_sequence_without_positions_is_imaged_here(microscope):
    inline = {"channels": [{"config": "FITC"}]}
    call = ("plan_useq_sequence", {"name": "inline", "sequence": inline})
    assistant, _ = talk(microscope, call, "Shall I start?")
    assistant.send("run this sequence")
    assert "here at x 1000, y -500, z 500 um" in tool_results(assistant)[0]["summary"]


@pytest.mark.parametrize(
    "args",
    [{"path": "no/such/file.json"}, {"sequence": {"channels": "not a list"}}],
    ids=["missing file", "not a sequence"],
)
def test_an_unreadable_useq_sequence_is_refused(microscope, args):
    call = ("plan_useq_sequence", {"name": "bad", **args})
    assistant, _ = talk(microscope, call, "That did not work.")
    assistant.send("run it")
    error = tool_results(assistant)[0]["error"]
    assert error["code"] == "invalid" and "no useq sequence could be read" in error["message"]


def test_plan_with_a_problem_is_refused_before_anything_moves(microscope, fake):
    bad = {**PLAN, "positions": [{"x": 100, "y": 200, "z": 20000}]}
    assistant, _ = talk(microscope, ("plan_acquisition", bad), "That plan cannot run.")
    assistant.send("plan it")
    error = tool_results(assistant)[0]["error"]
    assert error["code"] == "limit" and "outside the stage limits" in error["message"]
    assert microscope.warnings and moves(fake) == [] and fake.captures == 0


def test_repeated_position_names_are_refused_when_planning(microscope):
    twice = {**PLAN, "positions": [{"x": 100, "y": 200, "z": 500, "name": "cell"}] * 2}
    assistant, _ = talk(microscope, ("plan_acquisition", twice), "Two positions share a name.")
    assistant.send("plan it")
    assert "used more than once: cell" in tool_results(assistant)[0]["error"]["message"]


def test_a_sequence_whose_positions_have_only_z(microscope):
    call = ("plan_useq_sequence", {"name": "z_only", "sequence": {"stage_positions": [{"z": 500}]}})
    assistant, _ = talk(microscope, call, "Planned.")
    assistant.send("plan it")
    assert "#1 at z 500 um" in tool_results(assistant)[0]["summary"]


def test_a_useq_v2_sequence_as_json_is_refused_clearly(microscope):
    v2_json = {"axes": [{"axis_key": "c", "values": []}]}
    call = ("plan_useq_sequence", {"name": "v2", "sequence": v2_json})
    assistant, _ = talk(microscope, call, "That is a v2 sequence.")
    assistant.send("run it")
    assert "useq v2 sequence" in tool_results(assistant)[0]["error"]["message"]


def test_a_plan_that_became_invalid_before_its_run_is_refused_with_the_limit(microscope, fake):
    steps = [("plan_acquisition", PLAN), "Shall I start?", RUN, "The plan is outside the limits."]
    assistant, _ = talk(microscope, *steps)
    assistant.send("a stack at a")
    microscope.engine.set_limits(x=(500, None))  # the operator narrows the limits meanwhile
    assistant.send("yes")
    assert tool_results(assistant)[-1]["error"]["code"] == "limit" and microscope.warnings
    assert fake.captures == 0


def test_stop_while_a_run_is_being_prepared_prevents_it(microscope, fake):
    real_check = microscope.engine.check

    def check_then_stop(sequence):
        events = real_check(sequence)
        microscope.stop()  # the operator presses Stop microscope during the check
        return events

    steps = [("plan_acquisition", PLAN), "Shall I start?", RUN, "Stopped."]
    assistant, _ = talk(microscope, *steps)
    assistant.send("a stack at a")
    microscope.engine.check = check_then_stop
    assistant.send("yes")
    assert tool_results(assistant)[-1]["status"] == "cancelled" and fake.captures == 0


def test_a_run_that_loses_the_connection_says_what_was_saved(microscope, fake):
    steps = [("plan_acquisition", PLAN), "Shall I start?", RUN, "The connection was lost."]
    assistant, _ = talk(microscope, *steps)
    assistant.send("a stack at a")
    real_request, snaps = microscope.engine.client.request, []

    def request(op, **args):
        snaps.extend([op] if op == "snap" else [])
        if len(snaps) >= 4:  # the size check and two images, then NIS stops answering
            raise NisConnectionError("connection lost during 'snap'")
        return real_request(op, **args)

    microscope.engine.client.request = request
    assistant.send("yes")
    result = tool_results(assistant)[-1]
    assert result["finished"] == "failed" and "connection lost" in result["error"]["message"]
    assert result["images"] == 2 and result["saved_to"]


def test_a_closed_connection_is_opened_again_with_the_next_message(microscope):
    assistant, _ = talk(microscope, "Hello again.")
    microscope.engine.client.close()
    assert assistant.send("are you there?") == "Hello again."
    assert not microscope.engine.client.closed


def test_a_plan_with_an_unknown_channel_lists_the_known_ones(microscope):
    bad = {**PLAN, "channels": [{"config": "GFP"}]}
    assistant, _ = talk(microscope, ("plan_acquisition", bad), "GFP is not set up.")
    assistant.send("plan it in GFP")
    error = tool_results(assistant)[0]["error"]
    assert error["configured_options"] == ["DAPI", "FITC", "TxRed", "Brightfield"]


def test_a_malformed_plan_goes_back_to_the_model(microscope):
    bad = {**PLAN, "channels": []}  # a plan needs at least one channel
    assistant, script = talk(
        microscope, ("plan_acquisition", bad), ("plan_acquisition", PLAN), "OK."
    )
    assistant.send("plan it")
    retry = script.requests[1][-1].parts[-1]
    assert retry.part_kind == "retry-prompt"  # Pydantic caught it before our code ran
    assert tool_results(assistant)[0]["plan_id"] == "stack_test-1"


# -- reading the source ----------------------------------------------------------------------


def test_the_source_of_the_three_parts_and_useq_can_be_read(microscope):
    steps = [
        ("search_source", {"text": "def setup_event"}),
        ("read_source", {"file": "useq/v2/_mda_sequence.py", "start_line": 1, "lines": 3}),
        "Here is how it works.",
    ]
    assistant, _ = talk(microscope, *steps)
    assistant.send("how does the engine move the stage?")
    found, read = tool_results(assistant)
    assert any(m.startswith("nis_engine/engine.py:") for m in found["matches"])
    assert read["lines"].startswith("1 to 3 of") and read["text"].startswith("1: ")


def test_nothing_outside_those_sources_can_be_read(microscope):
    assistant, _ = talk(microscope, ("read_source", {"file": "../../etc/passwd"}), "No.")
    assistant.send("read that file")
    error = tool_results(assistant)[0]["error"]
    assert error["code"] == "not_found" and "nis_engine/engine.py" in error["configured_options"]
    parts = ("nis_bridge/", "nis_engine/", "nis_assistant/", "useq/")
    assert all(f.startswith(parts) for f in error["configured_options"])
    assert microscope.warnings == []  # not a fault at the microscope: no red banner


# -- memory ----------------------------------------------------------------------------------


def answer(n):
    """A model answer with reasoning attached, as Claude Opus 5.5 sends it."""
    return ModelResponse(parts=[ThinkingPart("thinking", signature=f"sig{n}"), TextPart(f"{n}")])


def operator_prompts(history):
    return [
        part.content
        for message in history
        for part in message.parts[:1]
        if isinstance(part, UserPromptPart)
    ]


def test_the_history_only_grows_until_it_is_long(microscope):
    assistant, _ = talk(microscope, *[answer(n) for n in range(1, 16)])
    grown = []
    for n in range(1, 16):
        assistant.send(f"message {n}")
        assert assistant.history[: len(grown)] == grown  # nothing earlier was changed
        grown = list(assistant.history)


def test_a_long_conversation_is_made_smaller_between_turns(microscope):
    steps = [answer(n) for n in range(1, 17)]
    steps[7:7] = [("get_status", {})]  # turn 8 reads the (long) status first
    assistant, _ = talk(microscope, *steps)
    for n in range(1, 17):
        assistant.send(f"message {n}")

    prompts = operator_prompts(assistant.history)
    assert len(prompts) == HISTORY_KEEP_TURNS and prompts[0].startswith("message 7")
    # the newest three turns keep the full state; older ones keep a one-line reading
    assert ["<microscope_state>" in p for p in prompts] == [False] * 7 + [True] * 3
    assert "<microscope_state_then>" in prompts[0] and "position_um" in prompts[0]
    # the old reasoning is left out, all of it, so what remains is valid for Claude
    parts = [part for message in assistant.history for part in message.parts]
    assert not any(isinstance(part, ThinkingPart) for part in parts)
    assert any(isinstance(part, TextPart) and part.content == "16" for part in parts)
    (status,) = tool_results(assistant)
    assert status.endswith("(shortened in memory)")


def test_clear_context_forgets_the_conversation(microscope):
    assistant, script = talk(microscope, "One.", "Two.")
    assistant.send("first")
    assistant.clear()
    assistant.send("second")
    assert operator_prompts(script.requests[1]) == [script.requests[1][-1].parts[0].content]
