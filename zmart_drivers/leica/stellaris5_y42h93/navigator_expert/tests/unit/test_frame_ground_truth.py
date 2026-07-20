"""Ground-truth tests for the adapter's uniform coordinate system.

The round-trip tests elsewhere prove ``get_xyz(set_xyz(F)) == F`` — but a
round trip cannot catch a *consistently* flipped ΔT sign, because the flip
cancels in the inverse. These tests close that hole with a simulated
microscope whose physics is DEFINED, independent of the adapter's math:

    the stage position at which lens L views sample point S is  S + T[L]
    (equivalently: the point a lens views is  stage − T[L])

which is exactly how the calibration measurement defines a translation
("home + translation is where the target lens sees the same feature",
calibration/core/objective_pair.py). Against that ground truth we assert
the frame's one promise: after ``set_xyz(F)`` — under ANY lens, with ANY
z actuator, ANY parked offsets on the other drive, from ANY starting
position — the viewed sample point is exactly ``origin_view + F``.

Scope: the coordinate MATH only. Motion primitives are faked (they just
update the simulated state); limit gating and confirmation have their own
suites.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import navigator_expert.readers as readers
import pytest
from navigator_expert.commands import commands as commands_mod
from navigator_expert.commands import objective_shift as shift
from navigator_expert.commands import settings as _cmd_settings
from navigator_expert.connection import session_state
from navigator_expert.orientation import Orientation
from navigator_expert.zmart_adapter import zmart_adapter as adapter

# The ground-truth translation table (µm). Slot 1 is the reference lens.
TRUE_T = {1: (0.0, 0.0, 0.0), 2: (50.0, -30.0, 7.0), 3: (-12.5, 4.0, -3.25)}


class SimScope:
    """A microscope reduced to the state the frame math talks about."""

    def __init__(self, x, y, z_wide, z_galvo, slot):
        self.x, self.y = float(x), float(y)
        self.z_wide, self.z_galvo = float(z_wide), float(z_galvo)
        self.slot = slot

    def viewed_point(self):
        """The sample point this lens is looking at — the DEFINED physics."""
        t = TRUE_T[self.slot]
        return (
            self.x - t[0],
            self.y - t[1],
            (self.z_wide + self.z_galvo) - t[2],
        )

    def state(self):
        return (self.x, self.y, self.z_wide, self.z_galvo, self.slot)


def _handle_at(sim: SimScope) -> adapter.ZmartHandle:
    """A handle whose origin is the sim's current state (like set_origin)."""
    h = adapter.ZmartHandle(client=SimpleNamespace(), connection={}, hash6="ground1")
    h.origin = {
        "x_um": sim.x,
        "y_um": sim.y,
        "z_wide_um": sim.z_wide,
        "z_galvo_um": sim.z_galvo,
        "z_focus_um": sim.z_wide + sim.z_galvo,
        "objective": {"name": f"lens{sim.slot}", "slotIndex": sim.slot},
    }
    h.translations = dict(TRUE_T)
    return h


@contextmanager
def _running(sim: SimScope):
    """Wire the adapter's motion and readers to the simulated scope."""

    def fake_arrive(client, x_um, y_um):
        sim.x, sim.y = float(x_um), float(y_um)

    def fake_move_z(client, job, z, unit="um", z_mode="galvo", **_k):
        if z_mode == "zwide":
            sim.z_wide = float(z)
        else:
            sim.z_galvo = float(z)
        return {"success": True, "confirmed": True}

    def settings(*_a, **_k):
        return {
            "objective": {"name": f"lens{sim.slot}", "magnification": 10, "slotIndex": sim.slot},
            "zPosition": {
                "z-wide": {"position": sim.z_wide},
                "z-galvo": {"position": sim.z_galvo},
            },
        }

    with (
        patch.object(adapter._motion, "arrive_xy", fake_arrive),
        patch.object(adapter._commands, "move_z", fake_move_z),
        patch.object(
            adapter._readers, "get_xy", side_effect=lambda c, **k: {"x_um": sim.x, "y_um": sim.y}
        ),
        patch.object(adapter._readers, "get_job_settings", side_effect=settings),
        patch.object(
            adapter._readers,
            "get_selected_job",
            return_value={"Name": "Overview", "IsSelected": True},
        ),
        patch.object(_cmd_settings, "make_changeable_copy", side_effect=lambda s: s),
    ):
        yield


ORIGIN_STATE = dict(x=10_000.0, y=20_000.0, z_wide=100.0, z_galvo=0.0)


@pytest.mark.parametrize("origin_lens", [1, 2])
@pytest.mark.parametrize("current_lens", [1, 2, 3])
@pytest.mark.parametrize("z_actuator", ["z-wide", "z-galvo"])
@pytest.mark.parametrize("parked_offset", [0.0, -35.0])
@pytest.mark.parametrize("frame_target", [(200.0, -150.0, 5.0), (-80.0, 60.0, -12.0)])
def test_viewed_point_is_origin_view_plus_frame_target(
    origin_lens, current_lens, z_actuator, parked_offset, frame_target
):
    """THE promise, over the full grid (48 cases): set_xyz(F) makes the
    current lens look at exactly origin_view + F — regardless of which
    lens the origin was set under, which lens is in now, which z drive
    realizes the move, and where the OTHER z drive happens to be parked.
    """
    sim = SimScope(**ORIGIN_STATE, slot=origin_lens)
    h = _handle_at(sim)
    origin_view = sim.viewed_point()

    # Life happens behind the adapter's back: the lens is swapped with NO
    # compensation, the stage wanders off, and the unchosen z drive gets
    # parked somewhere else. None of it may leak into where we land.
    sim.slot = current_lens
    sim.x += 1234.5
    sim.y -= 987.0
    if z_actuator == "z-wide":
        sim.z_galvo += parked_offset
    else:
        sim.z_wide += parked_offset

    with _running(sim):
        adapter.set_xyz(h, *frame_target, with_actuators={"z": z_actuator})
        got = adapter.get_xyz(h)

    expected = tuple(o + f for o, f in zip(origin_view, frame_target, strict=True))
    assert sim.viewed_point() == pytest.approx(expected)
    # and the read-back agrees with what was asked, in frame terms
    assert (got["x"]["value"], got["y"]["value"], got["z"]["value"]) == pytest.approx(frame_target)


def test_same_target_lands_identically_from_any_history():
    """Absoluteness: the same F, approached from three different pasts
    (positions, parked drives, lens detours), views the same sample point.
    """
    landings = []
    detours = [
        dict(dx=0.0, dy=0.0, park=0.0, via_lens=3),
        dict(dx=5000.0, dy=-3000.0, park=-50.0, via_lens=1),
        dict(dx=-2500.0, dy=800.0, park=25.0, via_lens=2),
    ]
    for d in detours:
        sim = SimScope(**ORIGIN_STATE, slot=1)
        h = _handle_at(sim)
        sim.slot = d["via_lens"]
        sim.x += d["dx"]
        sim.y += d["dy"]
        sim.z_galvo += d["park"]
        sim.slot = 2  # the lens that ends up in when the move is asked for
        with _running(sim):
            adapter.set_xyz(h, 300.0, -75.0, 9.0, with_actuators={"z": "z-wide"})
        landings.append(sim.viewed_point())

    assert landings[0] == pytest.approx(landings[1])
    assert landings[0] == pytest.approx(landings[2])


def test_repeated_cross_objective_moves_do_not_accumulate():
    """The dangerous path: z-galvo selected across objectives, where ΔT.z
    is pinned on z-wide. Five identical calls must be a fixed point —
    identical hardware state after each — or the objective offset is
    accumulating.
    """
    sim = SimScope(**ORIGIN_STATE, slot=1)
    h = _handle_at(sim)
    sim.slot = 2

    states = []
    with _running(sim):
        for _ in range(5):
            adapter.set_xyz(h, 120.0, 40.0, 3.0, with_actuators={"z": "z-galvo"})
            states.append(sim.state())

    assert all(s == states[0] for s in states[1:])
    # the pinned leg is absolute: origin z-wide plus the lens-pair z delta
    assert sim.z_wide == pytest.approx(ORIGIN_STATE["z_wide"] + (TRUE_T[2][2] - TRUE_T[1][2]))


def test_get_xyz_reports_truthfully_after_external_meddling():
    """Reads: whatever anyone did to the hardware (stage moved, drives
    re-split, lens swapped), get_xyz must equal the DEFINED viewed point
    minus the origin's viewed point.
    """
    sim = SimScope(**ORIGIN_STATE, slot=1)
    h = _handle_at(sim)
    origin_view = sim.viewed_point()

    sim.x += 777.0
    sim.y -= 333.0
    sim.z_wide += 40.0
    sim.z_galvo -= 15.0
    sim.slot = 3

    with _running(sim):
        got = adapter.get_xyz(h)

    truth = tuple(v - o for v, o in zip(sim.viewed_point(), origin_view, strict=True))
    assert (got["x"]["value"], got["y"]["value"], got["z"]["value"]) == pytest.approx(truth)


def test_focus_split_does_not_change_frame_z():
    """Frame z is the focus SUM: two hardware states with the same sum but
    different z-wide/z-galvo splits must read the same frame z."""
    reads = []
    for z_wide, z_galvo in [(140.0, -20.0), (100.0, 20.0), (35.0, 85.0)]:
        sim = SimScope(**ORIGIN_STATE, slot=1)
        h = _handle_at(sim)
        sim.z_wide, sim.z_galvo = z_wide, z_galvo
        with _running(sim):
            reads.append(adapter.get_xyz(h)["z"]["value"])
    assert reads[0] == pytest.approx(reads[1])
    assert reads[0] == pytest.approx(reads[2])


def test_swap_compensation_keeps_the_viewed_point():
    """The driver-side swap compensation, judged by ground truth: after
    record-before → lens swap → compensate-after, the NEW lens must be
    looking at the exact sample point the OLD lens was looking at.
    """
    sim = SimScope(x=12_345.0, y=6_789.0, z_wide=90.0, z_galvo=0.0, slot=1)
    client = SimpleNamespace()
    session_state.install(
        client,
        session_state.SessionConfig(orientation=Orientation(), translations=dict(TRUE_T)),
    )
    try:
        def fake_move_xy(c, x, y, unit="um", **_k):
            sim.x, sim.y = float(x), float(y)
            return {"success": True, "confirmed": True}

        def fake_move_z(c, job, z, unit="um", z_mode="galvo", **_k):
            if z_mode == "zwide":
                sim.z_wide = float(z)
            else:
                sim.z_galvo = float(z)
            return {"success": True, "confirmed": True}

        with (
            patch.object(readers, "get_xy", side_effect=lambda c, **k: {"x_um": sim.x, "y_um": sim.y}),
            patch.object(
                readers,
                "get_selected_job",
                return_value={"Name": "Overview", "IsSelected": True},
            ),
            patch.object(
                readers,
                "get_job_settings",
                side_effect=lambda c, j, **k: {"objective": {"slotIndex": sim.slot}},
            ),
            patch.object(readers, "read_zwide_um", side_effect=lambda c, j, **k: sim.z_wide),
            patch.object(commands_mod, "move_xy", fake_move_xy),
            patch.object(commands_mod, "move_z", fake_move_z),
        ):
            viewed_before = sim.viewed_point()
            before = shift.record_before_change(client)
            sim.slot = 2  # the swap itself moves nothing
            report = shift.compensate_after_change(client, "Overview", before)

        assert report["ok"] and report["objective_changed"]
        # z-galvo is untouched by compensation, so compare the full point:
        assert sim.viewed_point() == pytest.approx(viewed_before)
    finally:
        session_state.uninstall(client)


def test_zero_z_galvo_procedure_preserves_frame_z():
    """The new procedure judged by ground truth: after zero_z_galvo the
    galvo is at 0, the frame z is unchanged (pure re-split of the focus
    sum), and the transferred amount is reported."""
    sim = SimScope(**ORIGIN_STATE, slot=1)
    h = _handle_at(sim)
    sim.z_galvo = 42.0  # someone parked the galvo off-zero

    with _running(sim):
        z_before = adapter.get_xyz(h)["z"]["value"]
        result = adapter.run_procedure(h, {"name": "zero_z_galvo"})
        z_after = adapter.get_xyz(h)["z"]["value"]

    assert sim.z_galvo == 0.0
    assert sim.z_wide == pytest.approx(ORIGIN_STATE["z_wide"] + 42.0)
    assert z_after == pytest.approx(z_before)
    assert result["transferred_um"] == pytest.approx(42.0)


def test_zero_z_galvo_is_a_noop_when_already_zero():
    sim = SimScope(**ORIGIN_STATE, slot=1)
    h = _handle_at(sim)
    before = sim.state()
    with _running(sim):
        result = adapter.run_procedure(h, {"name": "zero_z_galvo"})
    assert sim.state() == before
    assert result["transferred_um"] == 0.0


def test_zero_z_galvo_refused_first_leg_moves_nothing():
    """Fail-safe leg order: if z-wide refuses to absorb the offset (e.g.
    a limit), the galvo must not have been touched — the procedure aborts
    with the hardware exactly as it found it."""
    sim = SimScope(**ORIGIN_STATE, slot=1)
    h = _handle_at(sim)
    sim.z_galvo = 42.0
    before = sim.state()

    def refusing_move_z(client, job, z, unit="um", z_mode="galvo", **_k):
        return {"success": False, "message": "z_wide_um outside range"}

    with _running(sim), patch.object(adapter._commands, "move_z", refusing_move_z):
        with pytest.raises(RuntimeError, match="zero_z_galvo"):
            adapter.run_procedure(h, {"name": "zero_z_galvo"})
    assert sim.state() == before
