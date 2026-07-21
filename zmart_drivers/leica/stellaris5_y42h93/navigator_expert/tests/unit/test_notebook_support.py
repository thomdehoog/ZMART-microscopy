"""Tests for shared operator-notebook save behavior."""

from __future__ import annotations

import sys
from types import ModuleType

from navigator_expert.notebook_support import NotebookCheckpoint


def test_save_and_adopt_clears_prompt_after_saved_checkpoint(tmp_path, monkeypatch):
    events = []
    checkpoint = NotebookCheckpoint(tmp_path / "operator.ipynb")

    def request_save(self):
        events.append("request")
        return 17

    def wait_for_save(self, previous_mtime_ns):
        events.append(("wait", previous_mtime_ns))
        return self.path

    fake_ipython = ModuleType("IPython")
    fake_display = ModuleType("IPython.display")
    fake_display.clear_output = lambda: events.append("clear")
    fake_ipython.display = fake_display

    monkeypatch.setattr(NotebookCheckpoint, "request_save", request_save)
    monkeypatch.setattr(NotebookCheckpoint, "wait_for_save", wait_for_save)
    monkeypatch.setitem(sys.modules, "IPython", fake_ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", fake_display)

    def adopt(saved_path):
        events.append(("adopt", saved_path))
        return "published"

    assert checkpoint.save_and_adopt(adopt) == "published"
    assert events == [
        "request",
        ("wait", 17),
        "clear",
        ("adopt", checkpoint.path),
    ]
