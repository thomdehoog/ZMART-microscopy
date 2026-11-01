"""The mock instrument's window: choosing a job there is what the next capture is taken with.

The window is pywebview and cannot open here; its ``Api`` can, and that is
where the behaviour is: a job chosen in the window has to land in the same
settings file the mock's driver reads, or the operator page would import a
job the window was not showing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import driver
from .window import Api


def test_the_window_lists_every_job_with_the_frame_it_images():
    state = Api().state()
    assert [job["name"] for job in state["jobs"]] == list(driver.JOBS)
    assert state["job"] == "Overview"
    frames = {job["name"]: job["frame"] for job in state["jobs"]}
    assert frames["Overview"] == "1024 × 1024 µm · 4 µm/px"
    assert frames["Focussing"].endswith("61 planes, 1.13333 µm step")
    assert state["where"] == str(driver.where_the_instrument_stands())


def test_a_job_chosen_in_the_window_is_the_one_the_driver_stands_on(mock_session):
    Api().choose("Target")
    assert Api().state()["job"] == "Target"
    assert mock_session.get_state()["changeable"]["job"] == "Target"
    record = mock_session.acquire(acquisition_type="targets", position_label="T0")
    # The state printed beside the capture names the job it ran.
    assert json.loads(Path(record["files"][-1]).read_text())["changeable"]["job"] == "Target"


def test_a_job_the_mock_does_not_have_is_refused():
    with pytest.raises(ValueError, match="unknown job"):
        Api().choose("HiRes")
