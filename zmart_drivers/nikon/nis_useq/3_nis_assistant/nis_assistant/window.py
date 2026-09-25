"""A chat window for the microscope assistant.

    nis-assistant --output D:\\runs

Needs the bridge running in NIS-Elements and an API key for the chosen model
(ANTHROPIC_API_KEY for the default Claude model). Left: the conversation, the buttons,
and the stage limits in force, which the operator can narrow. Right:
the latest image, the microscope status, and a red banner for anything refused.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
from nis_bridge.client import NisConnectionError
from nis_bridge.protocol import DEFAULT_HOST, DEFAULT_PORT
from nis_engine import NisEngine
from pydantic_ai.exceptions import UnexpectedModelBehavior
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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

from .agent import MODEL, Assistant, Microscope, as_png

WELCOME = (
    "Hello. I can move the stage, change the optical settings, focus, look at the "
    "sample and run acquisitions. Ask me in your own words, for example "
    "<i>What do you see?</i> or <i>Take a 3-channel Z-stack of 10 um here</i>. "
    "Before a long stage move I ask you here first."
)


class _Signals(QObject):
    """Carries results from the assistant's thread to the window's thread."""

    reply = Signal(str)
    error = Signal(str)
    image = Signal(object, str)
    warning = Signal(str)
    tool = Signal(str, dict)


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
        self.signals.tool.connect(self._show_tool)
        microscope = assistant.microscope
        microscope.on_image = self.signals.image.emit
        microscope.on_warning = self.signals.warning.emit
        microscope.on_tool = self.signals.tool.emit

        # left: the conversation
        self.transcript = QTextBrowser()
        self.prompt = QLineEdit(placeholderText="Ask the microscope assistant ...")
        self.prompt.returnPressed.connect(self.send)
        self.send_button = QPushButton("Send", clicked=self.send)
        self.stop_button = QPushButton("Stop microscope", clicked=self.stop_microscope)
        self.stop_button.setStyleSheet("color:#b00020; font-weight:bold")
        input_row = QHBoxLayout()
        input_row.addWidget(self.prompt, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.stop_button)
        self.cancel_button = QPushButton("Cancel prompt", clicked=self.cancel_prompt)
        self.clear_button = QPushButton("Clear context", clicked=self.clear_context)
        self.show_tools = QCheckBox("Show tool calls")
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self.cancel_button)
        buttons_row.addWidget(self.clear_button)
        buttons_row.addWidget(self.show_tools)
        buttons_row.addStretch(1)
        # below: the stage limits in force, one field per side; the operator can narrow them
        self.limit_fields = {
            (axis, side): QLineEdit(placeholderText="NIS") for axis in "xyz" for side in "-+"
        }
        for edit in self.limit_fields.values():
            edit.setMinimumWidth(80)  # room for "-57000" in full: a sign cut off would mislead
        self.apply_limits_button = QPushButton("Apply limits", clicked=self.apply_limits)
        self.nis_limits_button = QPushButton("Use NIS limits", clicked=self.use_nis_limits)
        limits_row = QHBoxLayout()
        limits_row.addWidget(QLabel("Stage limits (um):"))
        for (axis, side), edit in self.limit_fields.items():
            limits_row.addWidget(QLabel(f"{axis.upper()}{side}"))
            limits_row.addWidget(edit, 1)
        limits_row.addWidget(self.apply_limits_button)
        limits_row.addWidget(self.nis_limits_button)

        left = QVBoxLayout()
        left.addWidget(self.transcript, 1)
        left.addLayout(input_row)
        left.addLayout(buttons_row)
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
                "or press Stop microscope, then close.",
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

    def _in_background(self, turn: Callable[[], str]) -> None:
        """Run one assistant turn off the window's thread, so the window stays responsive."""
        self._set_busy(True)

        def work() -> None:
            try:
                self.signals.reply.emit(turn())
            except Exception as exc:
                self.signals.error.emit(_explain(exc, self.assistant.model))

        threading.Thread(target=work, daemon=True).start()

    def _show_reply(self, text: str) -> None:
        self._say("assistant", text)
        self._set_busy(False)
        self._refresh_status()

    def _show_error(self, text: str) -> None:
        self._say("system", text)
        self._set_busy(False)

    # -- the operator's say: Cancel prompt, Stop, Clear ---------------------------------

    def cancel_prompt(self) -> None:
        """Stop the assistant, not the microscope: further tool calls in this turn do nothing.

        What the assistant already started (a move, an acquisition) runs on; Stop
        microscope ends an acquisition.
        """
        if not self.busy:
            return
        self.assistant.microscope.cancel.set()
        self._say("system", "Cancelled. The assistant stops after its current step.")

    def stop_microscope(self) -> None:
        """Cancel the assistant and end a running acquisition after the current image."""
        self.assistant.microscope.stop()
        self._say(
            "system",
            "Stop: the assistant is cancelled and a running acquisition ends after the "
            "current image. A single stage move already under way finishes; use the joystick "
            "or NIS-Elements to stop it sooner.",
        )

    def clear_context(self) -> None:
        """Forget the conversation, in the window and in the assistant's memory."""
        if self.busy:
            return
        self.assistant.clear()
        self.transcript.clear()
        self._say("assistant", WELCOME, escape=False)

    # -- stage limits -------------------------------------------------------------------

    def apply_limits(self) -> None:
        """Use the numbers typed in the six limit fields, on top of the limits set in NIS.

        An empty field keeps NIS's own limit on that side.
        """
        values = {}
        for (axis, side), edit in self.limit_fields.items():
            text = edit.text().strip()
            try:
                values[axis, side] = float(text) if text else None
            except ValueError:
                self._show_warning(f"{axis.upper()}{side}: write a number in um, not {text!r}")
                return
        limits = {axis: (values[axis, "-"], values[axis, "+"]) for axis in "xyz"}
        if self._set_limits(**limits):
            self.warning.hide()
            self._show_limits(announce=True)

    def use_nis_limits(self) -> None:
        if self._set_limits():
            self._show_limits(announce=True)

    def _set_limits(self, **limits) -> bool:
        """Apply limits on the engine; True if they were applied, else a warning."""
        engine = self.assistant.microscope.engine
        try:
            if engine.client.closed:
                engine.reconnect()
            engine.set_limits(**limits)
        except ValueError as exc:
            self._show_warning(f"limits not applied: {exc}")
            return False
        except RuntimeError as exc:  # NIS or the bridge is not reachable
            self._show_warning(f"limits not applied, the microscope did not answer: {exc}")
            return False
        return True

    def _show_limits(self, announce: bool = False) -> None:
        """Fill the fields with the limits in force (a value beyond NIS's is cut to NIS's)."""
        try:
            limits = self.assistant.microscope.engine.limits()
        except (RuntimeError, ValueError):
            return  # the status line already says the microscope is not reachable
        for (axis, side), edit in self.limit_fields.items():
            edit.setText(f"{limits[axis]['min' if side == '-' else 'max']:g}")
        if announce:
            ranges = ", ".join(
                f"{a.upper()} {limits[a]['min']:g} to {limits[a]['max']:g}" for a in "xyz"
            )
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

    def _show_tool(self, name: str, args: dict) -> None:
        if self.show_tools.isChecked():
            call = html.escape(
                f"{name}({', '.join(f'{k}={json.dumps(v)}' for k, v in args.items())})"
            )
            self.transcript.append(f'<p style="color:#888; margin:0">&#8250; {call}</p>')

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
        self.clear_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.send_button.setText("Working ..." if busy else "Send")


# The environment variable that holds the API key, by model provider.
KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY",
                 "openai": "OPENAI_API_KEY"}  # fmt: skip


def _explain(exc: Exception, model: object) -> str:
    """Turn a failure into a sentence for the operator."""
    if isinstance(exc, UnexpectedModelBehavior):  # e.g. the model declined to answer
        return f"The assistant could not answer: {exc.message}"
    text = f"{type(exc).__name__}: {exc}"
    if "api_key" in text.lower() or "authentication" in text.lower():
        provider = str(model).split(":")[0]
        variable = KEY_VARIABLES.get(provider, "the API key variable of your model provider")
        return f"The assistant could not reach the model {model}: set {variable}. ({text})"
    return f"Something went wrong: {text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with the Nikon microscope assistant.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="the bridge's port")
    parser.add_argument(
        "--output",
        default=str(Path.home() / "nis_assistant_runs"),
        help="folder for the acquisitions (default: nis_assistant_runs in your home folder)",
    )
    parser.add_argument("--model", default=MODEL, help=f"Pydantic AI model name ({MODEL})")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    try:
        engine = NisEngine(DEFAULT_HOST, args.port)
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
