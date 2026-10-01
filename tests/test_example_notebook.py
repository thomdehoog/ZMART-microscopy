"""Run the example notebook the way a user would, with a second driver present.

The notebook is the front door, so it must stay safe and portable: it must
drive the mock even when a real microscope's driver is installed too, and it
must work with a driver that describes its saved files in its own way.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
from pathlib import Path

from zmart_controller import registry

NOTEBOOK = Path(__file__).resolve().parent.parent / "docs" / "example_experiment.ipynb"


def _code_cells() -> list[str]:
    cells = json.loads(NOTEBOOK.read_text())["cells"]
    return [
        c["source"] if isinstance(c["source"], str) else "".join(c["source"])
        for c in cells
        if c["cell_type"] == "code"
    ]


def _run_notebook() -> None:
    namespace: dict = {}
    for source in _code_cells():
        exec(compile(source, str(NOTEBOOK), "exec"), namespace)


def test_the_notebook_drives_the_mock_even_when_another_driver_sorts_first(capsys):
    # An installed driver whose name sorts before "mock". The notebook must
    # never send it a single command.
    calls: list[str] = []

    def record(name):
        def op(*args, **kwargs):
            calls.append(name)
            return {"success": True, "report": {}}

        return op

    other = {"vendor": "aaa", "microscope": "real-scope", "api": "real-api"}
    registry.register(other, ops={name: record(name) for name in registry.OPS})
    try:
        _run_notebook()
    finally:
        registry.REGISTRY.pop(registry._identity(other), None)
    assert calls == []


def test_the_notebook_works_with_a_driver_that_names_its_files_differently(monkeypatch):
    # The contract asks for the saved file paths but does not fix a key name.
    def acquire(handle, *, acquisition_type, position_label, options=None):
        return {
            "success": True,
            "report": {
                "acquisition_type": acquisition_type,
                "position_label": position_label,
                "image_files": [f"{position_label}.ome.tiff"],
            },
        }

    key = ("mock", "mock-scope", "mock-api")
    monkeypatch.setitem(registry.REGISTRY[key]["ops"], "acquire", acquire)
    _run_notebook()
