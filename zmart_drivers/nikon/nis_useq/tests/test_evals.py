"""The evaluation harness itself, offline: the case files are sound, a scripted
model that does what a case expects passes, and one that does not fails with
reasons. No real model is called here."""

import pytest

pytest.importorskip("pydantic_ai")

import evals  # noqa: E402
from nis_useq.agent import image_statistics  # noqa: E402
from test_agent import Script  # noqa: E402


def case(case_id, path=evals.CASES):
    return next(c for c in evals.load_cases(path) if c["id"] == case_id)


def run(case_id, *steps, vision="A plain grey field."):
    """Run a case with scripted models: one answers, the other looks at the picture."""
    return evals.run_case(case(case_id), Script(*steps).model(), 0, Script(vision).model())


def test_the_case_files_are_sound_and_the_holdout_mirrors_the_cases():
    cases, held = evals.load_cases(evals.CASES), evals.load_cases(evals.HOLDOUT)
    assert evals.check_cases(cases) == [] and evals.check_cases(held) == []
    assert [c["category"] for c in cases] == [c["category"] for c in held]  # case for case
    prompts = {p for c in cases for p in evals.prompts_of(c)}
    assert not prompts & {p for c in held for p in evals.prompts_of(c)}  # other words


def test_the_frames_say_what_their_cases_assume():
    saturated = image_statistics(evals.synthetic_frame("saturated"))["saturated_percent"]
    assert (
        saturated > 1 and image_statistics(evals.synthetic_frame("good"))["saturated_percent"] == 0
    )
    assert image_statistics(evals.synthetic_frame("dim"))["max"] < 1000


def test_a_model_that_does_the_right_thing_passes():
    trace = run("move-x-um", ("move_stage", {"x": 1200}), "The stage is at x = 1200 um.")
    assert evals.score(case("move-x-um"), trace) == []
    assert trace["tools"][0]["tool"] == "move_stage" and trace["state"]["x"] == 1200


def test_a_model_that_does_not_fails_with_reasons():
    trace = run("move-x-um", "Sure, done.")
    failures = evals.score(case("move-x-um"), trace)
    assert "expected a call to move_stage" in failures and "x is 1000.0, expected 1200" in failures


def test_a_long_move_is_asked_about_and_the_answer_is_the_next_prompt():
    long = ("move_stage", {"x": 20000})
    trace = run("move-long-cancelled", long, "Shall I move 19 mm to x = 20 mm?", "OK, we stay.")
    assert trace["asked"] == ["move_stage"] and trace["state"]["x"] == 1000
    assert evals.score(case("move-long-cancelled"), trace) == []


def test_asking_back_passes_only_without_a_change():
    assert (
        evals.score(case("ambiguous-move"), run("ambiguous-move", "Which axis, and how far?")) == []
    )
    moved = run("ambiguous-move", ("move_stage", {"x": 1010}), "Moved a bit, is that ok?")
    assert any("no change" in f for f in evals.score(case("ambiguous-move"), moved))


def test_a_vision_case_uses_the_synthetic_frame():
    trace = run(
        "vision-count",
        ("look", {"question": "how many spots?"}),
        "I see three bright spots.",
        vision="Three separate bright spots.",
    )
    assert evals.score(case("vision-count"), trace) == []
    assert '"max": 4000.0' in trace["tools"][0]["result"]  # the picture, not the plain frame


def test_an_acquisition_case_counts_the_saved_files():
    plan = {"plan": {"name": "two", "channels": [{"config": "DAPI"}, {"config": "FITC"}]}}
    trace = run(
        "acquisition-two-channels",
        ("plan_acquisition", plan),
        ("run_acquisition", {"plan_id": "two-1"}),
        "Two images saved.",
    )
    assert trace["state"]["images"] == 2 and trace["state"]["files"] == 1
    assert evals.score(case("acquisition-two-channels"), trace) == []


def test_argument_names_reach_inside_the_plan():
    plan = {"channels": [{"config": "DAPI"}], "z_stack": {"step_um": 2}}
    assert (
        evals._get(plan, "channels.0.config") == "DAPI" and evals._get(plan, "z_stack.step_um") == 2
    )
    assert evals._get(plan, "channels.5.config") is None


def test_negated_words_do_not_count_against_a_reply():
    assert not evals._stated("fully inside", "the sample is not fully inside the image")
    assert evals._stated("fully inside", "the sample is fully inside the image")


def test_the_scoreboard_sums_up_runs_per_model():
    traces = [
        {"id": "a", "category": "moves", "model": "m", "failures": [], "error": None, "seconds": 1},
        {
            "id": "a",
            "category": "moves",
            "model": "m",
            "failures": ["x"],
            "error": None,
            "seconds": 3,
        },
    ]
    board = evals.scoreboard(traces)
    assert "| m | 2 | 50% | 0 | 2.0 | 1 | 0 |" in board and "pass only sometimes: a" in board
