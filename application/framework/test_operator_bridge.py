"""The operator page's bridge, held to the driver contract it speaks to.

Every fault these cover was invisible from the page: the window drew a focus
map, the rows filled with numbers, and every number was a zero. What the page
cannot see is which key a driver puts its answer under, so that is what is
asserted here — against stubs shaped exactly like the drivers in this repo.

The module is loaded by path rather than by name, so that nothing on the way
to it can pull in a package the bridge itself refuses to need. It wants the
standard library and :mod:`zmart_controller` and no more, which is the property
worth keeping: it runs on a microscope PC with nothing installed on it.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "operator_bridge", Path(__file__).parent / "bridge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge()


class _Driver:
    """A stage that stays where it is put, and an autofocus that answers.

    Shaped after the two drivers in this repo: ``set_xyz`` returns a move
    record carrying the commanded position, and the autofocus reports its
    height under ``frame_z_um`` — the sharp height in frame terms, which is
    the one in the page's own coordinates.
    """

    def __init__(self, *, height_key: str | None = "frame_z_um"):
        self.at = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.drove_to: list[tuple] = []
        self.ran: list[dict] = []
        self.height_key = height_key

    def get_xyz(self) -> dict:
        return {axis: {"value": v, "unit": "um"} for axis, v in self.at.items()}

    def set_xyz(self, x, y, z, **_kw) -> dict:
        self.drove_to.append((x, y, z))
        self.at = {"x": float(x), "y": float(y), "z": float(z)}
        return {"position": {"x": x, "y": y, "z": z}, "actuators": {"z": "motoric"}}

    def run_procedure(self, procedure: dict) -> dict:
        """Refuses an unnamed procedure, exactly as the Leica adapter does."""
        self.ran.append(dict(procedure))
        name = procedure.get("name")
        if name != "autofocus":
            raise ValueError(f"unknown procedure {name!r}")
        answer = {"ran": dict(procedure)}
        if self.height_key:
            # the sharp height is wherever this stage stands, as the mock
            # driver's is: deterministic, and enough to tell a real height
            # from a default
            answer[self.height_key] = self.at["z"]
        return answer


@pytest.fixture()
def driver(monkeypatch):
    stub = _Driver()
    monkeypatch.setattr(bridge, "_session", stub)
    return stub


# --- driving the stage -------------------------------------------------------


def test_a_drive_answers_with_the_position_the_move_reported(driver):
    """No second read: set_xyz is confirmed and says where it went."""
    went = bridge._drive_to({"x": 61_000, "y": 42_000, "z": -380})
    assert driver.drove_to[-1] == (61_000.0, 42_000.0, -380.0)
    assert {axis: reading["value"] for axis, reading in went.items()} == {
        "x": 61_000.0,
        "y": 42_000.0,
        "z": -380.0,
    }
    assert all(reading["unit"] == "um" for reading in went.values())


def test_an_axis_not_asked_about_is_left_where_it_stands(driver):
    """Driving across the plate is not a request to move the objective."""
    bridge._drive_to({"x": 20_000, "y": 30_000, "z": -390})
    bridge._drive_to({"x": 25_000})
    assert driver.drove_to[-1] == (25_000.0, 30_000.0, -390.0)


def test_a_driver_that_names_no_position_is_asked_where_it_ended_up(monkeypatch):
    """Some may confirm the move and say nothing about where."""

    class Quiet(_Driver):
        def set_xyz(self, x, y, z, **_kw):
            self.at = {"x": float(x), "y": float(y), "z": float(z)}
            return {"ok": True}

    monkeypatch.setattr(bridge, "_session", Quiet())
    went = bridge._drive_to({"x": 7, "y": 8, "z": 9})
    assert {axis: reading["value"] for axis, reading in went.items()} == {
        "x": 7.0,
        "y": 8.0,
        "z": 9.0,
    }


# --- the focus map -----------------------------------------------------------


def test_the_autofocus_is_named_the_way_every_driver_reads_it(driver):
    """``name``, not ``procedure``.

    Both drivers in this repo read ``procedure["name"]``, and the Leica one
    raises on anything it does not recognise. Sent under the wrong key the
    map raised on the microscope and quietly measured nothing on the mock.
    """
    bridge._measure_focus({"points": [{"x": 1, "y": 2}]})
    assert driver.ran[-1]["name"] == "autofocus"


def test_the_height_the_driver_found_is_the_height_reported(driver):
    """It was read from keys no driver uses, so every point came back 0.0."""
    got = bridge._measure_focus({"points": [{"x": 1, "y": 2, "startZ": -350.0}]})
    point = got["points"][0]
    assert point["zAuto"] == -350.0
    assert point["z"] == -350.0
    assert point["lost"] is False


def test_a_search_begins_where_the_page_asked_it_to(driver):
    """`startZ` is the page saying "begin from what the map predicts here"."""
    bridge._measure_focus({"points": [{"x": 1, "y": 2, "startZ": -412.5}]})
    assert driver.drove_to[-1] == (1.0, 2.0, -412.5)


def test_a_search_with_no_start_asked_for_keeps_the_height_it_has(driver):
    """It used to be driven to frame zero, which threw the map's answer away."""
    bridge._drive_to({"x": 0, "y": 0, "z": -300.0})
    bridge._measure_focus({"points": [{"x": 5, "y": 6}]})
    assert driver.drove_to[-1] == (5.0, 6.0, -300.0)


def test_a_point_the_autofocus_could_not_answer_for_reports_no_height(monkeypatch):
    """None, not zero.

    The page fits a surface through what it is given, so one invented zero
    drags the whole map towards a place nobody measured.
    """
    monkeypatch.setattr(bridge, "_session", _Driver(height_key=None))
    got = bridge._measure_focus({"points": [{"x": 1, "y": 2}]})
    point = got["points"][0]
    assert point["zAuto"] is None
    assert point["z"] is None
    assert point["lost"] is True


# --- how big a frame is ------------------------------------------------------


class _Optics(_Driver):
    """A driver that reports its optics, and says what it is asked to say."""

    def __init__(self, observed):
        super().__init__()
        self.observed = observed

    def get_state(self) -> dict:
        return {"changeable": {}, "observed": self.observed}


def _frame(observed, monkeypatch):
    monkeypatch.setattr(bridge, "_session", _Optics(observed))
    return bridge._reading("acquisition")["frameUm"]


def test_a_frame_size_is_read_the_way_a_pixel_size_is(monkeypatch):
    """Measured beats derived.

    `frame_size`, shaped like `pixel_size`: LAS X's ``imageSize``, parsed by
    the driver into micrometres per axis. A format times a pixel size is
    arithmetic on two rounded numbers that can disagree with it. Only `x` is
    read — a plan is laid in square frames.
    """
    assert _frame(
        {"pixel_size": {"x": 0.33}, "frame_size": {"x": 676.4, "y": 676.4, "unit": "um"}},
        monkeypatch) == 676


def test_the_format_and_the_pixel_size_make_the_frame(monkeypatch):
    """When no field of view is reported, the format is what says how wide it
    is — and the format changes, which is the whole point."""
    assert _frame(
        {"pixel_size": {"x": 0.33}, "format": "2048 x 2048"}, monkeypatch) == 676
    assert _frame(
        {"pixel_size": {"x": 0.33}, "format": "512 x 512"}, monkeypatch) == 169


def test_a_format_said_as_numbers_counts_the_same(monkeypatch):
    """A driver may say it as a pair rather than as a string."""
    assert _frame(
        {"pixel_size": {"x": 0.5}, "pixels_x": 1024, "pixels_y": 1024}, monkeypatch) == 512


def test_an_instrument_that_says_neither_gets_a_guess(monkeypatch):
    """And it is a guess, not a measurement: 512 px is a stand-in for a format
    nobody reported, kept only so the page has a frame to draw at all."""
    assert _frame({"pixel_size": {"x": 1.0}}, monkeypatch) == bridge._A_GUESSED_FORMAT_PX


# --- what the instrument offers ----------------------------------------------


def test_the_acquisition_menu_is_handed_over_untouched(monkeypatch):
    """The driver's own menu, in the driver's own words.

    ``options`` is what may be chosen and ``active`` what is chosen now, and
    which settings exist at all is the driver's business — the page shows what
    it is given and hands the same shape back at capture time, so anything
    reworded here would have to be worded back before `acquire` could read it.
    """
    menu = {
        "job": {"options": ["Overview", "HiRes"], "active": "Overview"},
        "format": {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
        "backlash_rounds": {"options": "int >= 0", "active": 0},
    }

    class Offering(_Driver):
        def get_acquisition_options(self):
            return menu

    monkeypatch.setattr(bridge, "_session", Offering())
    assert bridge._acquisition_options() == menu


def test_a_setting_is_applied_as_the_changeable_half_of_state(monkeypatch):
    """`set_state` takes a whole state; the page sends only what it changed.

    The driver acts on `changeable` and treats `observed` as a report, so the
    page has no business sending one — it names the settings it is changing
    and the bridge puts them where the contract says they go.
    """
    sent = {}

    class Settable(_Driver):
        def set_state(self, state):
            sent.update(state)
            return {"applied": dict(state.get("changeable", {}))}

    monkeypatch.setattr(bridge, "_session", Settable())
    answered = bridge._apply_state({"job": "HiRes"})
    assert sent == {"changeable": {"job": "HiRes"}}
    assert answered == {"applied": {"job": "HiRes"}}

