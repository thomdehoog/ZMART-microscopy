"""The chat window, offscreen, with a scripted model and the fake NIS behind the bridge."""

import time

import pytest

pytest.importorskip("pytestqt")
pytest.importorskip("pydantic_ai")

from nis_useq.agent import Assistant, Microscope  # noqa: E402
from nis_useq.engine import NisEngine  # noqa: E402
from nis_useq.window import AssistantWindow  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402
from test_agent import Script, moves  # noqa: E402


@pytest.fixture
def open_window(qtbot, port, tmp_path):
    engines, windows = [], []

    def make(*steps, vision=None):
        engine = NisEngine("127.0.0.1", port, timeout=5.0)
        engines.append(engine)
        microscope = Microscope(engine, output_dir=tmp_path)
        if vision is not None:
            microscope.vision_model = Script(vision).model()
        window = AssistantWindow(Assistant(microscope, model=Script(*steps).model()))
        qtbot.addWidget(window)
        windows.append(window)
        return window

    yield make
    for window in windows:  # a failed test may leave a turn waiting: end it first
        window.stop_microscope()
        qtbot.waitUntil(lambda w=window: not w.busy, timeout=10000)
    for engine in engines:
        engine.close()


def ask(qtbot, window, text):
    window.prompt.setText(text)
    window.send()
    qtbot.waitUntil(lambda: not window.busy, timeout=10000)
    return window.transcript.toPlainText()


def test_a_question_and_its_answer(qtbot, open_window):
    window = open_window("The stage is at x 1000 um.")
    assert "Stage x 1000.0" in window.status.text()
    transcript = ask(qtbot, window, "where is the stage?")
    assert "where is the stage?" in transcript and "The stage is at x 1000 um." in transcript


def start(window, text):
    window.prompt.setText(text)
    window.send()


def test_a_long_move_is_asked_about_in_the_chat(qtbot, open_window, fake):
    long = ("move_stage", {"x": 20000})
    window = open_window(long, "Shall I move 19 mm to x = 20 mm?", long, "We are at x 20 mm.")
    transcript = ask(qtbot, window, "go to x 20 mm")
    assert "Shall I move 19 mm to x = 20 mm?" in transcript and moves(fake) == []
    assert "We are at x 20 mm." in ask(qtbot, window, "yes")
    assert moves(fake) == ["move_xy(20000,-500)"] and "Stage x 20000.0" in window.status.text()


def test_cancel_prompt_stops_the_assistant(qtbot, open_window, fake):
    slow_move = fake.move_xy

    def move_xy(x, y):  # a slower stage, so there is time to press Cancel prompt
        time.sleep(0.3)
        slow_move(x, y)

    fake.move_xy = move_xy
    window = open_window(("move_stage", {"x": 1100}), ("move_stage", {"x": 1200}), "Stopped.")
    window.show_tools.setChecked(True)
    start(window, "move twice")
    qtbot.waitUntil(lambda: "move_stage" in window.transcript.toPlainText(), timeout=10000)
    window.cancel_button.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=10000)
    assert moves(fake) == ["move_xy(1100,-500)"]  # the second move did not run
    assert "Cancelled." in window.transcript.toPlainText()


def test_tool_calls_show_when_asked(qtbot, open_window):
    window = open_window(("move_stage", {"x": 1100}), "Moved.", ("get_status", {}), "Here.")
    ask(qtbot, window, "move a little")
    assert "move_stage" not in window.transcript.toPlainText()
    window.show_tools.setChecked(True)
    assert "get_status()" in ask(qtbot, window, "status?")


def test_clear_context_empties_the_chat_and_the_memory(qtbot, open_window):
    window = open_window("One.", "Two.")
    ask(qtbot, window, "good morning")
    window.clear_context()
    assert "good morning" not in window.transcript.toPlainText() and window.assistant.history == []


def test_a_limit_breach_shows_the_red_banner(qtbot, open_window, fake):
    window = open_window(("move_stage", {"z": 20000}), "That is outside the limits.")
    ask(qtbot, window, "go to z 20 mm")
    assert (
        window.warning.isVisibleTo(window) and "outside the stage limits" in window.warning.text()
    )
    assert moves(fake) == []


def test_looking_fills_the_image_panel(qtbot, open_window):
    window = open_window(("look", {"question": "focus?"}), "Looks flat.", vision="A flat field.")
    ask(qtbot, window, "look")
    assert window.image.pixmap() is not None and not window.image.pixmap().isNull()
    assert window.caption.text() == "focus?"


def test_an_error_is_shown_and_the_window_stays_usable(qtbot, open_window):
    window = open_window()  # the script is empty: the "model" fails on the first call
    transcript = ask(qtbot, window, "hello")
    assert "Something went wrong" in transcript and window.prompt.isEnabled()


PLAN = {"name": "run", "channels": [{"config": "DAPI"}], "time_points": 12}


def test_an_acquisition_runs_from_the_window_and_stop_ends_it(qtbot, open_window, fake):
    slow_capture = fake.capture

    def capture():  # a slower camera, so there is time to press Stop
        time.sleep(0.1)
        slow_capture()

    fake.capture = capture
    window = open_window(
        ("plan_acquisition", PLAN), ("run_acquisition", {"plan_id": "run-1"}), "Stopped early."
    )
    window.prompt.setText("take 12 images")
    window.send()
    qtbot.waitUntil(lambda: window.caption.text().startswith("frame 3"), timeout=10000)
    window.stop_button.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=10000)
    transcript = window.transcript.toPlainText()
    assert "Stop: the assistant is cancelled" in transcript and "Stopped early." in transcript
    assert 3 <= fake.captures < 12


def test_the_window_will_not_close_mid_action(qtbot, open_window, monkeypatch):
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[1]))
    window = open_window("Hi.")
    window._set_busy(True)
    assert window.close() is False and told == ["Still working"]
    window._set_busy(False)
    assert window.close() is True


def test_six_limit_fields_show_and_narrow_the_stage_limits(qtbot, open_window, fake):
    window = open_window(("move_stage", {"z": 700}), "That is outside the limits you set.")
    fields = window.limit_fields
    assert fields["z", "-"].text() == "0" and fields["z", "+"].text() == "10000"  # NIS's own

    fields["z", "-"].setText("400")
    fields["z", "+"].setText("600")
    fields["x", "+"].setText("")  # empty: keep NIS's limit on that side
    window.apply_limits()
    assert fields["z", "-"].text() == "400" and fields["z", "+"].text() == "600"
    assert fields["x", "+"].text() == "57000"
    assert "Z 400 to 600" in window.transcript.toPlainText()

    ask(qtbot, window, "focus up to 700")
    assert "z = 700 um is outside the stage limits [400, 600]" in window.warning.text()
    assert moves(fake) == []

    window.use_nis_limits()
    assert fields["z", "+"].text() == "10000"


def test_limits_that_are_not_numbers_or_not_a_range_are_refused(qtbot, open_window):
    window = open_window()
    window.limit_fields["y", "-"].setText("five mm")
    window.apply_limits()
    assert window.warning.isVisibleTo(window) and "Y-: write a number" in window.warning.text()
    window.limit_fields["y", "-"].setText("600")
    window.limit_fields["y", "+"].setText("400")
    window.apply_limits()
    assert "the minimum must be below the maximum" in window.warning.text()
    assert window.assistant.microscope.engine.user_limits == {}
