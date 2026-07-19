"""The command layer keeps the sample point across job/objective changes.

Pins the owner's model at the layer that performs the change: record motoric
XY and z-wide BEFORE a job or objective change, perform the change, and when
the objective swapped add the calibrated translation difference to the
recorded values. Armed only for clients the driver connected (per-connection
config installed at connect); bare command-level use is untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

import navigator_expert.readers as readers
import pytest
from limits_fixtures import install_permissive_limits
from navigator_expert.commands import commands as cmds
from navigator_expert.commands import objective_shift as shift
from navigator_expert.connection import session_state
from navigator_expert.orientation import Orientation

TRANSLATIONS = {1: (0.0, 0.0, 0.0), 2: (10.0, -6.0, 3.0)}


@pytest.fixture
def client():
    c = SimpleNamespace(PyApiSelectJobByName=object(), PyApiSetObjectiveSlotByJobName=object())
    yield c
    session_state.uninstall(c)


def _arm(client, translations=TRANSLATIONS):
    session_state.install(
        client,
        session_state.SessionConfig(orientation=Orientation(), translations=translations),
    )


def _rig(monkeypatch, *, slot):
    """Fake the readers: stage at (1000, 2000), z-wide 30, objective per *slot*.

    *slot* is a mutable dict {"value": n} so a test can swap the objective
    between the before-record and the after-compensation read.
    """
    monkeypatch.setattr(readers, "get_xy", lambda c, **k: {"x_um": 1000.0, "y_um": 2000.0})
    monkeypatch.setattr(
        readers,
        "get_selected_job",
        lambda c, **k: {"Name": "Overview", "IsSelected": True},
    )
    monkeypatch.setattr(
        readers,
        "get_job_settings",
        lambda c, job, **k: {"objective": {"slotIndex": slot["value"]}},
    )
    monkeypatch.setattr(readers, "read_zwide_um", lambda c, job, **k: 30.0)


def _moves(monkeypatch):
    moves = []
    monkeypatch.setattr(
        cmds,
        "move_xy",
        lambda c, x, y, unit="um", **k: moves.append(("xy", x, y)) or {"success": True},
    )
    monkeypatch.setattr(
        cmds,
        "move_z",
        lambda c, job, z, unit="um", z_mode="galvo", **k: (
            moves.append(("z", job, z, z_mode)) or {"success": True}
        ),
    )
    return moves


def test_unarmed_client_is_left_completely_untouched(client, monkeypatch):
    # No per-connection config installed: nothing is read, nothing recorded.
    def _explode(*a, **k):
        raise AssertionError("an unarmed client must not be probed")

    monkeypatch.setattr(readers, "get_xy", _explode)
    assert shift.record_before_change(client) is None


def test_record_before_change_reads_position_and_objective(client, monkeypatch):
    _arm(client)
    _rig(monkeypatch, slot={"value": 1})
    before = shift.record_before_change(client)
    assert before == {
        "job": "Overview",
        "x_um": 1000.0,
        "y_um": 2000.0,
        "z_wide_um": 30.0,
        "slot": 1,
        "translations": TRANSLATIONS,
    }


def test_compensation_adds_the_translation_difference_to_the_recorded_values(
    client, monkeypatch
):
    _arm(client)
    slot = {"value": 1}
    _rig(monkeypatch, slot=slot)
    moves = _moves(monkeypatch)

    before = shift.record_before_change(client)
    slot["value"] = 2  # the change swapped the objective
    report = shift.compensate_after_change(client, "HiRes", before)

    assert report["ok"] and report["objective_changed"]
    assert report["applied_translation_um"] == [10.0, -6.0, 3.0]
    assert moves == [("xy", 1010.0, 1994.0), ("z", "HiRes", 33.0, "zwide")]


def test_same_objective_means_no_move(client, monkeypatch):
    _arm(client)
    _rig(monkeypatch, slot={"value": 2})
    moves = _moves(monkeypatch)
    before = shift.record_before_change(client)
    report = shift.compensate_after_change(client, "HiRes", before)
    assert report == {
        "ok": True,
        "objective_changed": False,
        "applied_translation_um": None,
        "message": None,
    }
    assert moves == []


def test_uncovered_objective_swap_fails_the_command_result(client, monkeypatch):
    _arm(client, translations={1: (0.0, 0.0, 0.0)})  # slot 3 is not calibrated
    slot = {"value": 1}
    _rig(monkeypatch, slot=slot)
    moves = _moves(monkeypatch)

    before = shift.record_before_change(client)
    slot["value"] = 3
    report = shift.compensate_after_change(client, "HiRes", before)
    assert not report["ok"]
    assert "no calibration translation covers" in report["message"]
    assert moves == []

    result = shift.merge_into_result({"success": True, "message": None}, report)
    assert result["success"] is False
    assert "no calibration translation covers" in result["message"]
    assert result["objective_compensation"]["objective_changed"] is True


def test_select_job_records_before_the_switch_and_compensates_after(client, monkeypatch):
    install_permissive_limits(client)
    _arm(client)
    order = []
    slot = {"value": 1}
    _rig(monkeypatch, slot=slot)
    monkeypatch.setattr(
        readers,
        "get_xy",
        lambda c, **k: order.append("read_xy") or {"x_um": 1000.0, "y_um": 2000.0},
    )
    monkeypatch.setattr(
        cmds,
        "prepare_select_job",
        lambda c, job: (None, {"api_baseline_name": "Overview", "api_said_selected": False}),
    )
    monkeypatch.setattr(cmds, "select_job_confirm_legs", lambda *a, **k: (None, None, 0.0))

    def fake_dispatch(*a, **k):
        order.append("dispatch")
        slot["value"] = 2  # the new job carries the other objective
        return {"success": True, "confirmed": True, "logs": []}

    monkeypatch.setattr(cmds, "_dispatch", fake_dispatch)
    monkeypatch.setattr(
        cmds,
        "move_xy",
        lambda c, x, y, unit="um", **k: order.append(("xy", x, y)) or {"success": True},
    )
    monkeypatch.setattr(
        cmds,
        "move_z",
        lambda c, job, z, unit="um", z_mode="galvo", **k: (
            order.append(("z", job, z, z_mode)) or {"success": True}
        ),
    )

    result = cmds.select_job(client, "HiRes")

    # Measured before the switch, switched, then moved by exactly ΔT.
    assert order == [
        "read_xy",
        "dispatch",
        ("xy", 1010.0, 1994.0),
        ("z", "HiRes", 33.0, "zwide"),
    ]
    assert result["success"]
    assert result["objective_compensation"]["applied_translation_um"] == [10.0, -6.0, 3.0]


def test_select_job_on_an_unarmed_client_behaves_as_before(client, monkeypatch):
    install_permissive_limits(client)

    def _explode(*a, **k):
        raise AssertionError("an unarmed client must not be probed")

    monkeypatch.setattr(readers, "get_xy", _explode)
    monkeypatch.setattr(
        cmds,
        "prepare_select_job",
        lambda c, job: (None, {"api_baseline_name": "Overview", "api_said_selected": False}),
    )
    monkeypatch.setattr(cmds, "select_job_confirm_legs", lambda *a, **k: (None, None, 0.0))
    monkeypatch.setattr(
        cmds, "_dispatch", lambda *a, **k: {"success": True, "confirmed": True, "logs": []}
    )

    result = cmds.select_job(client, "HiRes")
    assert result["success"]
    assert "objective_compensation" not in result


def test_set_objective_records_before_and_compensates_with_the_commanded_slot(
    client, monkeypatch
):
    install_permissive_limits(client)
    _arm(client)
    order = []
    _rig(monkeypatch, slot={"value": 1})
    monkeypatch.setattr(
        readers,
        "get_xy",
        lambda c, **k: order.append("read_xy") or {"x_um": 1000.0, "y_um": 2000.0},
    )
    monkeypatch.setattr(
        cmds,
        "_dispatch",
        lambda *a, **k: order.append("dispatch") or {"success": True, "confirmed": True},
    )
    monkeypatch.setattr(
        cmds,
        "move_xy",
        lambda c, x, y, unit="um", **k: order.append(("xy", x, y)) or {"success": True},
    )
    monkeypatch.setattr(
        cmds,
        "move_z",
        lambda c, job, z, unit="um", z_mode="galvo", **k: (
            order.append(("z", job, z, z_mode)) or {"success": True}
        ),
    )
    hw_info = {
        "Microscope": {
            "objectives": [
                {"slotIndex": 1, "name": "10x dry", "objectiveNumber": 101},
                {"slotIndex": 2, "name": "63x oil", "objectiveNumber": 202},
            ]
        }
    }

    result = cmds.set_objective(client, "Overview", hw_info, slot_index=2)

    assert order == [
        "read_xy",
        "dispatch",
        ("xy", 1010.0, 1994.0),
        ("z", "Overview", 33.0, "zwide"),
    ]
    assert result["success"]
    assert result["objective_compensation"]["applied_translation_um"] == [10.0, -6.0, 3.0]


class TestCompensateParameter:
    """Decision §8: compensation is explicit and session-scoped.

    ``compensate=None`` follows the connect-time policy, ``False`` asks
    for a bare change, ``True`` requires calibration or refuses up front.
    """

    def test_declined_session_swaps_bare(self, client, monkeypatch):
        """load_calibration=False installs translations=None: the session
        declared itself uncalibrated, so a lens swap records nothing,
        compensates nothing, and refuses nothing."""
        _arm(client, translations=None)
        assert shift.record_before_change(client) is None

    def test_wanted_but_unusable_calibration_still_refuses(self, client, monkeypatch):
        """An empty table means the session WANTED calibration but none is
        usable — a swap must fail loudly, not proceed bare."""
        _arm(client, translations={})
        _rig(monkeypatch, slot={"value": 1})
        moves = _moves(monkeypatch)
        before = shift.record_before_change(client)
        assert before is not None  # armed: the pre-change position is recorded
        report = shift.compensate_after_change(client, "Overview", before, new_slot=2)
        assert not report["ok"]
        assert "no calibration translation covers" in report["message"]
        assert moves == []

    def test_compensate_false_is_a_bare_change_even_when_calibrated(self, client):
        _arm(client)  # full table loaded
        assert shift.record_before_change(client, compensate=False) is None

    def test_compensate_true_refuses_up_front_without_calibration(self, client):
        _arm(client, translations=None)
        with pytest.raises(RuntimeError, match="compensate=True"):
            shift.record_before_change(client, compensate=True)

    def test_compensate_true_on_unarmed_client_refuses_up_front(self, client):
        with pytest.raises(RuntimeError, match="compensate=True"):
            shift.record_before_change(client, compensate=True)


class TestSingleSourcedDelta:
    """The translation math lives in ONE place (calibration/core/model.py),
    shared by the driver's swap-time compensation and the adapter's
    per-move frame mapping — so sign or policy drift between the two
    layers is structurally impossible."""

    def test_sign_convention_is_to_minus_from(self):
        from navigator_expert.calibration.core import model

        assert model.translation_delta_um(TRANSLATIONS, 1, 2) == (10.0, -6.0, 3.0)
        assert model.translation_delta_um(TRANSLATIONS, 2, 1) == (-10.0, 6.0, -3.0)

    def test_uncovered_pair_raises_the_one_shared_message(self):
        from navigator_expert.calibration.core import model

        with pytest.raises(RuntimeError, match="no calibration translation covers"):
            model.translation_delta_um(TRANSLATIONS, 1, 5)
        with pytest.raises(RuntimeError, match="no calibration translation covers"):
            model.translation_delta_um(None, 1, 2)

    def test_swap_compensation_and_frame_math_agree(self, client, monkeypatch):
        """The property the whole two-moment design rests on: the driver's
        swap-time stage move equals the adapter's per-move frame offset for
        the same lens pair. Swap-then-move-to-F therefore lands exactly
        where move-to-F-alone would."""
        from navigator_expert.zmart_adapter import zmart_adapter as adapter

        _arm(client)
        slot = {"value": 1}
        _rig(monkeypatch, slot=slot)
        moves = _moves(monkeypatch)
        before = shift.record_before_change(client)
        slot["value"] = 2
        report = shift.compensate_after_change(client, "Overview", before)
        assert report["ok"]
        driver_delta = tuple(report["applied_translation_um"])

        handle = SimpleNamespace(
            origin={"objective": {"slotIndex": 1}},
            translations=TRANSLATIONS,
        )
        adapter_delta = adapter._objective_delta_um(handle, {"slotIndex": 2})
        assert adapter_delta == driver_delta
        # and the physical move the driver fired is exactly that delta
        assert moves[0] == ("xy", 1000.0 + driver_delta[0], 2000.0 + driver_delta[1])
        assert moves[1] == ("z", "Overview", 30.0 + driver_delta[2], "zwide")
