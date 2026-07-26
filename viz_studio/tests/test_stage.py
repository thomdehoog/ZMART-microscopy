"""Check that a box drawn in the viewer becomes the right stage position.

These tests guard the two things that could hurt: converting the image's own
coordinate units into the micrometres the microscope expects, and refusing to
move anything unless movement was actually asked for.
"""

from __future__ import annotations

import pytest
from stage import StageRefused, goto, target_micrometres, to_micrometres


def _axis(value: float, unit: str = "m") -> dict:
    return {"value": value, "unit": unit}


def _box(unit: str = "m") -> dict:
    """A box spanning 10-30 µm in x, 40-60 in y, 4-6 in z, written in ``unit``."""
    scale = {"m": 1e-6, "mm": 1e-3, "um": 1.0, "nm": 1e3}[unit]
    return {
        "pointA": {
            "x": _axis(10 * scale, unit),
            "y": _axis(40 * scale, unit),
            "z": _axis(4 * scale, unit),
        },
        "pointB": {
            "x": _axis(30 * scale, unit),
            "y": _axis(60 * scale, unit),
            "z": _axis(6 * scale, unit),
        },
    }


class TestUnits:
    """A store written in metres and one in micrometres must agree."""

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("m", 1_000_000.0),
            ("meter", 1_000_000.0),
            ("mm", 1_000.0),
            ("um", 1.0),
            ("µm", 1.0),
            ("μm", 1.0),  # the Greek mu, which looks identical but is a different character
            ("micrometer", 1.0),
            ("nm", 0.001),
        ],
    )
    def test_each_supported_unit_converts(self, unit, expected):
        assert to_micrometres(1.0, unit) == pytest.approx(expected)

    def test_surrounding_spaces_are_tolerated(self):
        assert to_micrometres(2.0, " um ") == pytest.approx(2.0)

    def test_an_unknown_unit_is_refused_rather_than_guessed(self):
        """Guessing is the dangerous option, so an unknown unit must raise."""
        with pytest.raises(ValueError, match="unsupported coordinate unit"):
            to_micrometres(1.0, "furlong")

    def test_a_missing_unit_is_refused(self):
        with pytest.raises(ValueError, match="what unit"):
            to_micrometres(1.0, "")

    def test_non_finite_and_non_numeric_values_are_refused(self):
        with pytest.raises(ValueError, match="finite"):
            to_micrometres(float("inf"), "um")
        with pytest.raises(ValueError, match="numbers"):
            to_micrometres("5", "um")
        # True is an int in Python, which would silently become 1 µm.
        with pytest.raises(ValueError, match="numbers"):
            to_micrometres(True, "um")


class TestTarget:
    """A box goes to its middle; a point goes to itself."""

    def test_a_box_targets_its_centre(self):
        assert target_micrometres(_box("m")) == pytest.approx({"x": 20.0, "y": 50.0, "z": 5.0})

    def test_the_same_box_in_different_units_gives_the_same_place(self):
        """The whole point of the conversion: the unit must not change the answer."""
        answers = [target_micrometres(_box(unit)) for unit in ("m", "mm", "um", "nm")]
        for answer in answers[1:]:
            assert answer == pytest.approx(answers[0])

    def test_a_point_targets_itself(self):
        payload = {"point": {"x": _axis(1e-5), "y": _axis(2e-5), "z": _axis(3e-5)}}
        assert target_micrometres(payload) == pytest.approx({"x": 10.0, "y": 20.0, "z": 30.0})

    def test_axes_the_image_does_not_have_are_simply_absent(self):
        """A flat overview has no z, and that is not an error."""
        payload = {
            "pointA": {"x": _axis(1e-5), "y": _axis(1e-5)},
            "pointB": {"x": _axis(3e-5), "y": _axis(3e-5)},
        }
        assert target_micrometres(payload) == pytest.approx({"x": 20.0, "y": 20.0})

    def test_channel_and_time_axes_are_ignored(self):
        """They say what is shown, not where the stage stands."""
        payload = {
            "pointA": {"x": _axis(1e-5), "c": _axis(0.0, "um"), "t": _axis(3.0, "um")},
            "pointB": {"x": _axis(3e-5), "c": _axis(2.0, "um"), "t": _axis(9.0, "um")},
        }
        assert target_micrometres(payload) == pytest.approx({"x": 20.0})

    def test_an_axis_in_only_one_corner_is_treated_as_missing(self):
        """Half a span is not a midpoint, so it must not be invented."""
        payload = {
            "pointA": {"x": _axis(1e-5), "z": _axis(4e-6)},
            "pointB": {"x": _axis(3e-5)},
        }
        assert target_micrometres(payload) == pytest.approx({"x": 20.0})

    def test_a_target_with_no_stage_axis_at_all_is_refused(self):
        with pytest.raises(ValueError, match="none of the x, y or z"):
            target_micrometres({"pointA": {"c": _axis(0.0, "um")}, "pointB": {"c": _axis(1.0, "um")}})

    def test_a_shapeless_request_is_refused(self):
        with pytest.raises(ValueError, match="either a box"):
            target_micrometres({"id": "target-1"})
        with pytest.raises(ValueError, match="expected an object"):
            target_micrometres([1, 2, 3])


class _FakeSession:
    """Stands in for a connected microscope, recording where it was sent."""

    def __init__(self, *, refuse=None, position=None):
        self.refuse = refuse
        self.position = position or {"x": 100.0, "y": 200.0, "z": 300.0}
        self.moves = []

    def get_xyz(self, with_actuators=None):
        return self.position

    def set_xyz(self, x, y, z, with_actuators=None):
        if self.refuse is not None:
            raise self.refuse
        self.moves.append((x, y, z))
        return {"moved_to": {"x": x, "y": y, "z": z}}


class TestFailClosed:
    """Nothing moves unless a microscope is attached *and* moves are switched on."""

    def test_no_session_means_nothing_moves(self):
        report = goto(_box(), session=None, allow_moves=True)
        assert report["moved"] is False
        assert "no microscope" in report["action"]
        # The target is still reported, so the answer is useful in the demo.
        assert report["target"] == pytest.approx({"x": 20.0, "y": 50.0, "z": 5.0})

    def test_a_session_alone_is_not_enough(self):
        session = _FakeSession()
        report = goto(_box(), session=session, allow_moves=False)
        assert report["moved"] is False
        assert "switched off" in report["action"]
        assert session.moves == []

    def test_both_together_move_the_stage(self):
        session = _FakeSession()
        report = goto(_box(), session=session, allow_moves=True)
        assert report["moved"] is True
        assert session.moves == [pytest.approx((20.0, 50.0, 5.0))]
        assert report["driver"] == {"moved_to": {"x": 20.0, "y": 50.0, "z": 5.0}}

    def test_a_bad_request_never_reaches_the_microscope(self):
        session = _FakeSession()
        with pytest.raises(ValueError):
            goto({"pointA": {"x": _axis(1.0, "furlong")}, "pointB": {"x": _axis(2.0, "furlong")}},
                 session=session, allow_moves=True)
        assert session.moves == []


class TestRefusals:
    """A driver saying no is the guard working, and must reach the operator."""

    def test_a_driver_refusal_is_reported_with_its_reason(self):
        session = _FakeSession(refuse=RuntimeError("target outside the z travel limit"))
        with pytest.raises(StageRefused, match="outside the z travel limit"):
            goto(_box(), session=session, allow_moves=True)

    def test_a_caller_mistake_stays_a_value_error(self):
        """The controller's contract: ValueError means the request was wrong."""
        session = _FakeSession(refuse=ValueError("z must be a number"))
        with pytest.raises(ValueError, match="z must be a number"):
            goto(_box(), session=session, allow_moves=True)


class TestFillingInMissingAxes:
    """An image without a z still needs three numbers to move the stage."""

    def _flat_box(self):
        return {
            "pointA": {"x": _axis(1e-5), "y": _axis(1e-5)},
            "pointB": {"x": _axis(3e-5), "y": _axis(3e-5)},
        }

    def test_the_current_position_holds_the_missing_axis(self):
        session = _FakeSession(position={"x": 1.0, "y": 2.0, "z": 42.0})
        report = goto(self._flat_box(), session=session, allow_moves=True)
        # x and y come from the box; z stays where the microscope already was.
        assert session.moves == [pytest.approx((20.0, 20.0, 42.0))]
        assert report["target"]["z"] == pytest.approx(42.0)

    def test_a_wrapped_position_reading_is_understood_too(self):
        """Some drivers report {"z": {"value": ...}} rather than {"z": ...}."""
        session = _FakeSession(position={"x": {"value": 1.0}, "y": {"value": 2.0}, "z": {"value": 7.5}})
        goto(self._flat_box(), session=session, allow_moves=True)
        assert session.moves == [pytest.approx((20.0, 20.0, 7.5))]

    def test_an_unreadable_position_refuses_rather_than_guessing_zero(self):
        session = _FakeSession(position={"x": 1.0, "y": 2.0})  # no z reported
        with pytest.raises(StageRefused, match="did not report its current z"):
            goto(self._flat_box(), session=session, allow_moves=True)

    def test_a_failing_position_read_refuses_the_move(self):
        session = _FakeSession()
        session.get_xyz = lambda with_actuators=None: (_ for _ in ()).throw(
            RuntimeError("stage controller not responding")
        )
        with pytest.raises(StageRefused, match="not responding"):
            goto(self._flat_box(), session=session, allow_moves=True)
