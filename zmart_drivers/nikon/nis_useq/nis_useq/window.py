"""A chat window for the microscope assistant.

    python -m nis_useq.window --output D:\\runs

Needs the bridge running in NIS-Elements and an Anthropic API key in the
ANTHROPIC_API_KEY environment variable. Left: the conversation, and below it
the stage limits in force, which the operator can narrow. Right: the latest
image, the microscope status, and a red banner for anything refused. Large
moves, objective changes and acquisitions ask for confirmation first.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
from pydantic_ai.exceptions import UnexpectedModelBehavior
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .agent import MODEL, Assistant, Microscope, Reply, as_png
from .client import NisConnectionError
from .engine import NisEngine
from .protocol import DEFAULT_PORT

WELCOME = (
    "Hello! I can move the stage, change the optical settings, focus, look at the "
    "sample and run acquisitions. Ask me in your own words, for example "
    "<i>What do you see?</i> or <i>Take a 3-channel Z-stack of 10 um here</i>. "
    "Large moves, objective changes and acquisitions wait for your confirmation."
)


class _Signals(QObject):
    """Carries results from the assistant's thread to the window's thread."""

    reply = Signal(object)
    error = Signal(str)
    image = Signal(object, str)
    warning = Signal(str)


class AssistantWindow(QMainWindow):
    def __init__(self, assistant: Assistant) -> None:
        super().__init__()
        self.assistant = assistant
        self.setWindowTitle("Nikon microscope assistant")
        self.resize(1200, 750)

        self.signals = _Signals()
        self.signals.reply.connect(self._show_reply)
        self.signals.error.connect(self._show_error)
        self.signals.image.connect(self._show_image)
        self.signals.warning.connect(self._show_warning)
        microscope = assistant.microscope
        microscope.on_image = self.signals.image.emit
        microscope.on_warning = self.signals.warning.emit

        # left: the conversation
        self.transcript = QTextBrowser()
        self.prompt = QLineEdit(placeholderText="Ask the microscope assistant ...")
        self.prompt.returnPressed.connect(self.send)
        self.send_button = QPushButton("Send", clicked=self.send)
        self.stop_button = QPushButton("Stop acquisition", clicked=microscope.stop_run)
        input_row = QHBoxLayout()
        input_row.addWidget(self.prompt, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.stop_button)
        # below: the stage limits in force; the operator can narrow them
        self.limit_fields = {axis: QLineEdit(placeholderText="min to max") for axis in "xyz"}
        self.apply_limits_button = QPushButton("Apply limits", clicked=self.apply_limits)
        self.nis_limits_button = QPushButton("Use NIS limits", clicked=self.use_nis_limits)
        limits_row = QHBoxLayout()
        limits_row.addWidget(QLabel("Stage limits (um):"))
        for axis, edit in self.limit_fields.items():
            limits_row.addWidget(QLabel(axis.upper()))
            limits_row.addWidget(edit, 1)
        limits_row.addWidget(self.apply_limits_button)
        limits_row.addWidget(self.nis_limits_button)

        left = QVBoxLayout()
        left.addWidget(self.transcript, 1)
        left.addLayout(input_row)
        left.addLayout(limits_row)

        # right: warning, image, status
        self.warning = QLabel(wordWrap=True)
        self.warning.setStyleSheet(
            "background:#b00020; color:white; padding:8px; font-weight:bold; border-radius:4px"
        )
        self.warning.hide()
        self.image = QLabel("No image yet.", alignment=Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(480, 480)
        self.image.setStyleSheet("background:#111; color:#aaa")
        self.caption = QLabel(wordWrap=True)
        self.status = QLabel(wordWrap=True)
        self.status.setStyleSheet("color:#555")
        right = QVBoxLayout()
        right.addWidget(self.warning)
        right.addWidget(self.image, 1)
        right.addWidget(self.caption)
        right.addWidget(self.status)

        body = QHBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)
        container = QWidget()
        container.setLayout(body)
        self.setCentralWidget(container)

        self._say("assistant", WELCOME, escape=False)
        self._refresh_status()
        self._show_limits()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Do not close in the middle of an action: the microscope would be left mid-way."""
        if self.busy:
            QMessageBox.information(
                self,
                "Still working",
                "The assistant is still working on the microscope. Wait until it is done, "
                "or press Stop acquisition to end a running acquisition, then close.",
            )
            event.ignore()
            return
        event.accept()

    # -- one turn of the conversation ----------------------------------------------

    def send(self) -> None:
        text = self.prompt.text().strip()
        if not text or self.busy:
            return
        self.prompt.clear()
        self.warning.hide()
        self._say("you", text)
        self._in_background(lambda: self.assistant.send(text))

    @property
    def busy(self) -> bool:
        return not self.send_button.isEnabled()

    def _in_background(self, turn: Callable[[], Reply]) -> None:
        """Run one assistant turn off the window's thread, so the window stays responsive."""
        self._set_busy(True)

        def work() -> None:
            try:
                self.signals.reply.emit(turn())
            except Exception as exc:  # noqa: BLE001 - shown to the operator, not swallowed
                self.signals.error.emit(_explain(exc))

        threading.Thread(target=work, daemon=True).start()

    def _show_reply(self, reply: Reply) -> None:
        if reply.text:
            self._say("assistant", reply.text)
        if reply.approvals:
            decisions = {a.id: self._confirm(a.summary) for a in reply.approvals}
            for approval in reply.approvals:
                verdict = "confirmed" if decisions[approval.id] else "declined"
                self._say("system", f"You {verdict}: {approval.summary}")
            self._in_background(lambda: self.assistant.decide(decisions))
            return
        self._set_busy(False)
        self._refresh_status()

    def _confirm(self, summary: str) -> bool:
        answer = QMessageBox.question(
            self, "Confirm on the microscope", f"{summary}\n\nGo ahead?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )  # fmt: skip
        return answer == QMessageBox.StandardButton.Yes

    def _show_error(self, text: str) -> None:
        self._say("system", text)
        self._set_busy(False)

    # -- stage limits -------------------------------------------------------------------

    def apply_limits(self) -> None:
        """Use the ranges typed in the limit fields, on top of the limits set in NIS."""
        ranges = {}
        for axis, edit in self.limit_fields.items():
            try:
                ranges[axis] = _parse_range(edit.text())
            except ValueError:
                self._show_warning(
                    f"{axis.upper()} limits: write two numbers in um, for example -5000 to 5000"
                )
                return
        try:
            self.assistant.microscope.engine.set_limits(**ranges)
        except ValueError as exc:
            self._show_warning(f"limits not applied: {exc}")
            return
        self.warning.hide()
        self._show_limits(announce=True)

    def use_nis_limits(self) -> None:
        self.assistant.microscope.engine.set_limits()
        self._show_limits(announce=True)

    def _show_limits(self, announce: bool = False) -> None:
        """Fill the fields with the limits in force (a wider range typed is cut to NIS's)."""
        try:
            limits = self.assistant.microscope.engine.limits()
        except (RuntimeError, ValueError):
            return  # the status line already says the microscope is not reachable
        for axis, edit in self.limit_fields.items():
            edit.setText(f"{limits[axis]['min']:g} to {limits[axis]['max']:g}")
        if announce:
            ranges = ", ".join(f"{a.upper()} {e.text()}" for a, e in self.limit_fields.items())
            self._say("system", f"Stage limits in use (um): {ranges}.")

    # -- the right-hand side ----------------------------------------------------------

    def _show_image(self, image: np.ndarray, caption: str) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(as_png(image).data)
        self.image.setPixmap(
            pixmap.scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.caption.setText(caption)

    def _show_warning(self, text: str) -> None:
        self.warning.setText(f"Refused: {text}")
        self.warning.show()

    def _refresh_status(self) -> None:
        try:
            state = self.assistant.microscope.state()
        except (RuntimeError, ValueError) as exc:
            self.status.setText(f"Microscope not reachable: {exc}")
            return
        p = state["position_um"]
        self.status.setText(
            f"Stage x {p['x']:.1f}, y {p['y']:.1f}, z {p['z']:.1f} um  ·  "
            f"objective {state['objective']['name']}  ·  PFS {state['pfs']}"
        )

    # -- small helpers ------------------------------------------------------------------

    def _say(self, who: str, text: str, escape: bool = True) -> None:
        colour = {"you": "#1a5fb4", "assistant": "#26a269", "system": "#b00020"}[who]
        body = html.escape(text).replace("\n", "<br>") if escape else text
        self.transcript.append(f'<p><b style="color:{colour}">{who}</b><br>{body}</p>')

    def _set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.prompt.setEnabled(not busy)
        self.apply_limits_button.setEnabled(not busy)
        self.nis_limits_button.setEnabled(not busy)
        self.send_button.setText("Working ..." if busy else "Send")


def _parse_range(text: str) -> tuple[float, float] | None:
    """'-5000 to 5000' -> (-5000.0, 5000.0); an empty field -> None (NIS's own limits)."""
    if not text.strip():
        return None
    numbers = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text)
    if len(numbers) != 2:
        raise ValueError(text)
    return float(numbers[0]), float(numbers[1])


def _explain(exc: Exception) -> str:
    """Turn a failure into a sentence for the operator."""
    if isinstance(exc, UnexpectedModelBehavior):  # e.g. Claude declined to answer
        return f"The assistant could not answer: {exc.message}"
    text = f"{type(exc).__name__}: {exc}"
    if "api_key" in text.lower() or "authentication" in text.lower():
        return f"The assistant could not reach Claude: set ANTHROPIC_API_KEY. ({text})"
    return f"Something went wrong: {text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with the Nikon microscope assistant.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output", default=str(Path.home() / "nis_useq_runs"))
    parser.add_argument("--model", default=MODEL, help=f"Pydantic AI model name ({MODEL})")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    try:
        engine = NisEngine(args.host, args.port)
    except NisConnectionError as exc:
        QMessageBox.critical(None, "No connection to NIS-Elements", str(exc))
        return 1
    microscope = Microscope(engine, output_dir=Path(args.output), vision_model=args.model)
    window = AssistantWindow(Assistant(microscope, model=args.model))
    window.show()
    try:
        return app.exec()
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
