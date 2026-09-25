"""The chat window, offscreen, with a scripted model and the fake NIS behind the bridge."""

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
    engines = []

    def make(*steps, vision=None):
        engine = NisEngine("127.0.0.1", port, timeout=5.0)
        engines.append(engine)
        microscope = Microscope(engine, output_dir=tmp_path)
        if vision is not None:
            microscope.vision_model = Script(vision).model()
        window = AssistantWindow(Assistant(microscope, model=Script(*steps).model()))
        qtbot.addWidget(window)
        return window

    yield make
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


def test_a_large_move_asks_for_confirmation(qtbot, open_window, fake, monkeypatch):
    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Yes,
    )
    window = open_window(("move_stage", {"x": 20000}), "We are at x 20 mm.")
    transcript = ask(qtbot, window, "go to x 20 mm")
    assert "19000 um in XY" in asked[0] and moves(fake) == ["move_xy(20000,-500)"]
    assert "You confirmed" in transcript and "We are at x 20 mm." in transcript
    assert "Stage x 20000.0" in window.status.text()


def test_a_limit_breach_shows_the_red_banner(qtbot, open_window, fake):
    window = open_window(("move_stage", {"z": 20000}), "That is outside the limits.")
    ask(qtbot, window, "go to z 20 mm")
    assert window.warning.isVisibleTo(window) and "LIMIT BREACH" in window.warning.text()
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
