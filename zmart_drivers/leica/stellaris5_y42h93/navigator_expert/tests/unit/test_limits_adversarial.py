"""Permanent adversarial suite for the limits enforcement redesign.

Attacks the commands-layer function-keyed gate (``commands/gate.py``), the
connect-time limits handshake, ProgramData resolution, and the hardcoded
physical backstop — through every entry point (direct commands, adapter op,
controller Session).

Policy (operator decision): a malformed or over-wide machine ``limits.json``
must never GOVERN — its bad values must not reach a move — but it does not
leave the session dead. The handshake falls back to the bundled DEFAULT
envelope (loudly, ``is_fallback``), which sits within the physical backstop, so
the wide/malformed values are replaced, not honoured. The two things that never
relax: the hardcoded physical backstop bounds every move regardless, and a
client that never handshook at all still refuses fail-closed. So every attack
must still end with the bad values NOT in force — either refused outright (no
handshake) or overridden by the safe defaults — never silently accepted.

Runs in normal CI (offline, mock-backed). Design:
``docs/design/limits-enforcement.md`` + amendments;
policy: ``docs/reviews/MAINTAINER_DECISIONS.md`` §7.
"""

from __future__ import annotations

import ast
import json
import math
import os
from pathlib import Path

import pytest
from limits_fixtures import DEFAULT_STAGE_UM, merged_limits_payload, provision_machine_limits
from mock_lasx_api import MockLasxClient
from navigator_expert.commands import commands as commands_mod
from navigator_expert.commands import gate
from navigator_expert.config.machine import MachineProfile
from navigator_expert.motion import limits as motion_limits
from navigator_expert.motion import stage_config
from navigator_expert.scanfields import files as scanfield_files

DRIVER_ROOT = Path(__file__).resolve().parents[2]

# =============================================================================
# Helpers
# =============================================================================


def _machine_root() -> Path:
    """The hermetic ProgramData root the autouse conftest fixture points at."""
    return Path(os.environ["ZMART_MICROSCOPY_ROOT"])


def _raw_snapshot(root: Path, *, limits_text: str | None = None) -> MachineProfile:
    """Write a snapshot with a RAW single limits.json (for malformed attacks)."""
    profile = MachineProfile(programdata_root=Path(root))
    snap = profile.snapshot_root() / "2026-01-01T00-00-00-000000Z"
    snap.mkdir(parents=True, exist_ok=True)
    if limits_text is not None:
        (snap / "limits.json").write_text(limits_text, encoding="utf-8")
    return profile


def _valid_payload(stage_um: dict | None = None, functions: dict | None = None) -> dict:
    """A valid flat limits.json payload."""
    return merged_limits_payload(stage_um or DEFAULT_STAGE_UM, functions=functions)


def _valid_limits_text(stage_um: dict | None = None) -> str:
    payload = _valid_payload()
    if stage_um is not None:
        for axis, key in {
            "x": "x_um",
            "y": "y_um",
            "z_galvo": "z_galvo_um",
            "z_wide": "z_wide_um",
        }.items():
            payload[key] = {"range": stage_um[axis]}
    return json.dumps(payload)


def _with_payload(mutate) -> str:
    """A flat payload mutated for one malformed-file attack."""
    payload = _valid_payload()
    return json.dumps(mutate(dict(payload)))


@pytest.fixture()
def clear_stage_limits():
    saved = dict(motion_limits._stage_limits)
    motion_limits._stage_limits.update(dict.fromkeys(motion_limits._stage_limits, None))
    yield
    motion_limits._stage_limits.update(saved)


@pytest.fixture()
def mock_client(clear_stage_limits):
    return MockLasxClient(latency=0.0)


def _assert_refused(result, *, needle="refused"):
    """A command result dict must be a fail-closed refusal, loudly."""
    assert isinstance(result, dict), f"expected a refusal dict, got {result!r}"
    assert result["success"] is False
    assert needle in result["message"], result["message"]


def _mock_stage_position(client):
    return (client._stage_x, client._stage_y)


# =============================================================================
# 1. Malformed limits.json — the handshake falls back to safe defaults
# =============================================================================

_BAD_LIMITS_TEXTS = {
    "truncated": '{"x_um": {"range": [1000, 130000]}, "y_um":',
    "non_json": "this is not json <at all>",
    "empty_dict": "{}",
    "legacy_schema": json.dumps(
        {"schema_version": 1, "source": "defaults", "constraints": {}, "functions": {}}
    ),
    "missing_axis": _with_payload(lambda p: {k: v for k, v in p.items() if k != "y_um"}),
    "unknown_key": _with_payload(lambda p: {**p, "theta_deg": {"range": [0, 360]}}),
    "axis_not_a_range": _with_payload(lambda p: {**p, "x_um": {"min": 1000, "max": 130000}}),
    "axis_wrong_length": _with_payload(lambda p: {**p, "x_um": {"range": [1000]}}),
    "axis_wrong_type": _with_payload(lambda p: {**p, "x_um": {"allowed": [1000, 130000]}}),
    "min_greater_than_max": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[130000, 1000])),
    # json.dumps emits NaN / Infinity literals (allow_nan) — the validators must refuse.
    "nan": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[float("nan"), 130000])),
    "infinity": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[1000, float("inf")])),
    "wider_than_backstop": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[0, 500000])),
}


@pytest.mark.parametrize("attack", sorted(_BAD_LIMITS_TEXTS))
def test_malformed_limits_json_falls_back_to_defaults(attack, mock_client):
    _raw_snapshot(_machine_root(), limits_text=_BAD_LIMITS_TEXTS[attack])
    state = gate.connect_handshake(mock_client)
    # The malformed machine file is NOT used; the session falls back to the
    # bundled DEFAULT envelope (loudly), never left fail-closed.
    assert state.ok, attack
    assert state.limits.describe()["is_fallback"] is True
    # the DEFAULT envelope is applied — NOT the malformed file's values
    assert motion_limits.get_stage_limits()["x_min"] == DEFAULT_STAGE_UM["x"][0]
    # an in-envelope move works; an out-of-envelope one still refuses, so a
    # widened/garbage file can never authorize a move the defaults forbid
    assert commands_mod.move_xy(mock_client, 50000, 50000, unit="um")["success"] is True
    _assert_refused(commands_mod.move_xy(mock_client, 999999, 50000, unit="um"), needle="outside")
    # reads still work
    assert mock_client.PyApiPing is not None


# =============================================================================
# 2. Malformed flat setter/objective entries — same defaults fallback
# =============================================================================

_BAD_FUNCTION_LIMITS_TEXTS = {
    "truncated": '{"x_um":',
    "non_json": "definitely not json",
    "empty_dict": "{}",
    "missing_setter": _with_payload(lambda p: {k: v for k, v in p.items() if k != "set_zoom"}),
    "unknown_setter": _with_payload(lambda p: {**p, "set_warp_drive": []}),
    "setter_is_null": _with_payload(lambda p: {**p, "set_zoom": None}),
    "setter_is_string": _with_payload(lambda p: {**p, "set_zoom": "unlimited"}),
    "setter_untyped_nonempty": _with_payload(lambda p: {**p, "set_zoom": [1, 10]}),
    "setter_unknown_type": _with_payload(lambda p: {**p, "set_zoom": {"limits": [1, 10]}}),
    "setter_two_types": _with_payload(
        lambda p: {**p, "set_zoom": {"range": [1, 10], "allowed": [1, 10]}}
    ),
    "setter_empty_allowed": _with_payload(lambda p: {**p, "set_zoom": {"allowed": []}}),
    "objective_slots_empty_allowed": _with_payload(
        lambda p: {**p, "objective_slot": {"allowed": []}}
    ),
    "objective_slot_not_integer": _with_payload(
        lambda p: {**p, "objective_slot": {"allowed": [1, "2"]}}
    ),
    "objective_slot_negative": _with_payload(
        lambda p: {**p, "objective_slot": {"allowed": [-1, 1]}}
    ),
    "objective_slot_duplicate": _with_payload(
        lambda p: {**p, "objective_slot": {"allowed": [1, 1]}}
    ),
    "setter_nonfinite_allowed": _with_payload(
        lambda p: {**p, "set_zoom": {"allowed": [float("nan")]}}
    ),
    "setter_boolean_range": _with_payload(lambda p: {**p, "set_zoom": {"range": [False, True]}}),
    "setter_string_range": _with_payload(lambda p: {**p, "set_zoom": {"range": ["1", "5"]}}),
    "setter_null_allowed": _with_payload(lambda p: {**p, "set_zoom": {"allowed": [None]}}),
}


@pytest.mark.parametrize("attack", sorted(_BAD_FUNCTION_LIMITS_TEXTS))
def test_malformed_function_limits_falls_back_to_defaults(attack, mock_client):
    _raw_snapshot(_machine_root(), limits_text=_BAD_FUNCTION_LIMITS_TEXTS[attack])
    state = gate.connect_handshake(mock_client)
    # The malformed flat document is not used; defaults govern instead.
    assert state.ok, attack
    assert state.limits.describe()["is_fallback"] is True
    # the default policy governs: an out-of-envelope move still refuses
    _assert_refused(commands_mod.move_xy(mock_client, 999999, 50000, unit="um"), needle="outside")


def test_nan_in_axis_range_triggers_the_defaults_fallback(mock_client):
    """A non-finite flat axis bound never governs a move."""
    text = _with_payload(lambda p: {**p, "x_um": {"range": [float("nan"), 130000]}})
    _raw_snapshot(_machine_root(), limits_text=text)
    state = gate.connect_handshake(mock_client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True


# =============================================================================
# 3. Poisoned call values — after a GOOD handshake
# =============================================================================


@pytest.fixture()
def governed_client(mock_client):
    provision_machine_limits(_machine_root())
    state = gate.connect_handshake(mock_client)
    assert state.ok, state.error
    return mock_client


def test_objective_allow_list_checks_the_resolved_slot(mock_client):
    payload = _valid_payload()
    payload["objective_slot"] = {"allowed": [1]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    assert gate.connect_handshake(mock_client).ok
    hw_info = {
        "Microscope": {
            "objectives": [
                {"slotIndex": 1, "name": "10x", "magnification": 10, "objectiveNumber": 1},
                {"slotIndex": 2, "name": "20x", "magnification": 20, "objectiveNumber": 2},
            ]
        }
    }

    refused = commands_mod.set_objective(mock_client, "HiRes", hw_info, name="20x")
    assert refused["success"] is False
    assert "objective_slot=2" in refused["message"]
    assert "expected one of [1]" in refused["message"]


def test_objective_allow_list_allows_a_listed_slot(mock_client):
    payload = _valid_payload()
    payload["objective_slot"] = {"allowed": [1]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    assert gate.connect_handshake(mock_client).ok
    hw_info = {
        "Microscope": {
            "objectives": [
                {"slotIndex": 1, "name": "10x", "magnification": 10, "objectiveNumber": 1}
            ]
        }
    }

    result = commands_mod.set_objective(mock_client, "HiRes", hw_info, slot_index=1)
    assert result["success"] is True


def test_default_objective_slot_is_unrestricted(mock_client):
    """``objective_slot: []`` — the shipped default — fences nothing.

    Which slots exist is hardware knowledge the wrapper checks live, so with
    the default in place automation may switch to any slot the turret
    actually has, slot 0 included (slots count from 0).
    """
    _raw_snapshot(_machine_root(), limits_text=json.dumps(_valid_payload()))
    assert gate.connect_handshake(mock_client).ok
    hw_info = {
        "Microscope": {
            "objectives": [
                {"slotIndex": 0, "name": "5x", "magnification": 5, "objectiveNumber": 5},
                {"slotIndex": 2, "name": "20x", "magnification": 20, "objectiveNumber": 2},
            ]
        }
    }

    assert commands_mod.set_objective(mock_client, "HiRes", hw_info, slot_index=0)["success"]
    assert commands_mod.set_objective(mock_client, "HiRes", hw_info, name="20x")["success"]


@pytest.mark.parametrize(
    "x,y",
    [
        (float("nan"), 50000.0),
        (50000.0, float("nan")),
        (float("inf"), 50000.0),
        (float("-inf"), 50000.0),
        (None, 50000.0),
        ("50000", 50000.0),  # strings are not positions
        (1e18, 50000.0),
        (-1e18, 50000.0),
    ],
)
def test_poisoned_move_xy_targets_refuse(governed_client, x, y):
    before = _mock_stage_position(governed_client)
    result = commands_mod.move_xy(governed_client, x, y, unit="um")
    assert result["success"] is False, (x, y)
    assert result["message"]
    assert _mock_stage_position(governed_client) == before  # nothing fired


@pytest.mark.parametrize("z", [float("nan"), float("inf"), float("-inf"), None, "12", 1e18, -1e18])
@pytest.mark.parametrize("z_mode", ["galvo", "zwide"])
def test_poisoned_move_z_targets_refuse(governed_client, z, z_mode):
    result = commands_mod.move_z(governed_client, "HiRes", z, unit="um", z_mode=z_mode)
    assert result["success"] is False, (z, z_mode)
    assert result["message"]


@pytest.mark.parametrize("px,py", [(float("nan"), 10), (10, float("nan"))])
def test_poisoned_pixel_target_cannot_compose_a_nan_galvo_pan(governed_client, px, py):
    """NaN compares False against the angular pan limit, and the default
    machine file's ``move_galvo_to_pixel`` entry is ``null`` — so a NaN pixel
    target must be refused by the composed-pan finiteness check, never
    written into the LRP that LAS X executes."""
    from unittest.mock import patch

    from navigator_expert import readers
    from navigator_expert.experimental.lrp_edits import scan as lrp_scan
    from navigator_expert.scanfields import transaction as lrp_transaction

    written = []

    def fake_apply_lrp_change(client, template_xml, edit_fn):
        # Mirror the real transaction's contract: run the edit; an exception
        # from the edit propagates (load_experiment then never fires).
        edit_fn("dummy.lrp")
        return {"success": True}

    with (
        patch.object(readers, "get_selected_job", return_value={"Name": "Overview"}),
        patch.object(readers, "get_job_settings", return_value={"settings": "raw"}),
        patch.object(readers, "get_base_fov", return_value=(0.000512, 0.000512)),
        patch(
            "navigator_expert.utils.parse_tile_geometry",
            return_value={"pixel_w_um": 1.0, "pixels_x": 512},
        ),
        patch.object(lrp_scan, "lrp_get_pan", return_value=(0.0, 0.0)),
        patch.object(lrp_scan, "lrp_set_pan", side_effect=lambda *a: written.append(a)),
        patch.object(lrp_transaction, "apply_lrp_change", side_effect=fake_apply_lrp_change),
    ):
        result = commands_mod.move_galvo_to_pixel(governed_client, px, py)
    assert result["success"] is False, result
    assert "not finite" in result["message"], result["message"]
    assert written == []  # the poisoned pan never reached the LRP


def test_nan_never_slips_past_a_bounded_constraint():
    """NaN compares False against every bound; flat validation must refuse it."""
    payload = stage_config.build_limits_payload(DEFAULT_STAGE_UM)
    payload["x_um"] = {"range": [float("nan"), 130000]}
    with pytest.raises(ValueError, match="finite"):
        stage_config.validate_payload(payload)


def test_degenerate_envelope_min_equals_max_pins_the_stage(mock_client):
    """min == max is legal and means exactly one allowed position."""
    provision_machine_limits(_machine_root(), stage_um=dict(DEFAULT_STAGE_UM, x=[50000.0, 50000.0]))
    state = gate.connect_handshake(mock_client)
    assert state.ok, state.error
    ok = commands_mod.move_xy(mock_client, 50000, 30000, unit="um")
    assert ok["success"] is True
    refused = commands_mod.move_xy(mock_client, 50001, 30000, unit="um")
    assert refused["success"] is False


# =============================================================================
# 4. State abuse
# =============================================================================


def test_moves_refuse_before_any_handshake(mock_client):
    before = _mock_stage_position(mock_client)
    result = commands_mod.move_xy(mock_client, 50000, 50000, unit="um")
    _assert_refused(result)
    assert "set_limits.ipynb" in result["message"]
    assert _mock_stage_position(mock_client) == before


def test_manual_set_stage_limits_allows_silent_widening_but_backstop_holds(governed_client):
    """PINS the current contract: set_stage_limits() accepts a WIDER envelope
    without complaint (an explicit operator action — flagged for review, not
    changed here). The hardcoded backstop still refuses the move the widened
    envelope would have allowed.
    """
    motion_limits.set_stage_limits(
        x_min=0.0,
        x_max=500000.0,  # far beyond the physical travel; accepted silently today
        y_min=0.0,
        y_max=500000.0,
        z_galvo_min=-200.0,
        z_galvo_max=200.0,
        z_wide_min=0.0,
        z_wide_max=25000.0,
    )
    assert motion_limits.get_stage_limits()["x_max"] == 500000.0  # the pin
    # a target beyond the physical travel, inside the widened in-memory
    # envelope: the machine file's set_xyz constraint and the backstop both
    # stand in the way — the move must refuse, not fire
    result = commands_mod.move_xy(governed_client, 200000, 50000, unit="um")
    assert result["success"] is False
    assert "outside" in result["message"]


def test_backstop_refuses_even_with_a_widened_in_memory_envelope(mock_client):
    """A hand-widened in-memory envelope cannot authorize a physical overrun."""
    from limits_fixtures import install_permissive_limits

    install_permissive_limits(mock_client)  # function gate wide open
    motion_limits.set_stage_limits(
        x_min=0.0,
        x_max=1_000_000.0,
        y_min=0.0,
        y_max=1_000_000.0,
        z_galvo_min=-10_000.0,
        z_galvo_max=10_000.0,
        z_wide_min=-10_000.0,
        z_wide_max=100_000.0,
    )
    before = _mock_stage_position(mock_client)
    result = commands_mod.move_xy(mock_client, 200000, 50000, unit="um")
    assert result["success"] is False
    assert "backstop" in result["message"]
    assert _mock_stage_position(mock_client) == before
    z = commands_mod.move_z(mock_client, "HiRes", 5000, unit="um", z_mode="galvo")
    assert z["success"] is False
    assert "backstop" in z["message"]


def test_hand_widened_limits_file_does_not_govern(mock_client):
    """A machine file hand-widened past the backstop is rejected and replaced by
    the safe defaults — its wide values never authorize a move."""
    _raw_snapshot(
        _machine_root(),
        limits_text=_valid_limits_text(dict(DEFAULT_STAGE_UM, y=[0.0, 400000.0])),
    )
    state = gate.connect_handshake(mock_client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True
    # a target the WIDENED file would have allowed (y within [0, 400000]) but the
    # defaults forbid must still refuse — the wide value is not in force
    _assert_refused(commands_mod.move_xy(mock_client, 50000, 300000, unit="um"), needle="outside")


def test_broken_setter_entry_widens_a_narrow_envelope_to_the_defaults(mock_client):
    """PINS a chosen consequence of the defaults fallback (maintainer decision):
    an invalid machine file is rejected WHOLE. So a file with a deliberately
    NARROW envelope but a broken setter entry is replaced by the bundled
    defaults, which are WIDER — a move the operator's own file forbids is then
    ALLOWED, and only the loud is_fallback warning tells them their narrow
    limits are not in force. If this test starts failing because the narrow
    envelope survives, the fallback policy changed — update the docs with it."""
    payload = _valid_payload(dict(DEFAULT_STAGE_UM, x=[40000.0, 60000.0]))
    payload["set_zoom"] = [1, 10]  # non-empty setter contract is not defined
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    state = gate.connect_handshake(mock_client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True
    # x=100000 violates the (rejected) machine file's narrow envelope but sits
    # inside the defaults: the fallback allows it. This is the sanctioned
    # trade-off — bounded by the defaults and the backstop, not left dead.
    assert commands_mod.move_xy(mock_client, 100000, 50000, unit="um")["success"] is True


def test_rehandshake_after_fixing_the_file_replaces_the_fallback(mock_client):
    """Recovery path: after a broken file put the session on the defaults
    fallback, fixing limits.json and re-running the handshake installs the REAL
    machine envelope (is_fallback False) — no fallback state lingers, in the
    gate or in the module-global envelope."""
    profile = _raw_snapshot(_machine_root(), limits_text=_BAD_LIMITS_TEXTS["non_json"])
    state = gate.connect_handshake(mock_client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True

    # The operator fixes the file in the newest limits snapshot, which is what
    # the next handshake reads.
    (profile.latest_snapshot("limits") / "limits.json").write_text(
        _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[40000.0, 60000.0])), encoding="utf-8"
    )
    # ...and reconnects: the machine envelope governs again.
    state2 = gate.connect_handshake(mock_client)
    assert state2.ok
    assert state2.limits.describe()["is_fallback"] is False
    assert motion_limits.get_stage_limits()["x_min"] == 40000.0
    _assert_refused(commands_mod.move_xy(mock_client, 100000, 50000, unit="um"), needle="outside")
    assert commands_mod.move_xy(mock_client, 50000, 50000, unit="um")["success"] is True


def test_second_handshake_rebinds_without_leaking_between_clients(tmp_path):
    """PR-09: two clients in one process each get their own gate state; the
    module-global stage envelope belongs to whichever handshake ran last
    (documented single-instrument-per-process invariant)."""
    client_a = MockLasxClient(latency=0.0)
    client_b = MockLasxClient(latency=0.0)
    provision_machine_limits(_machine_root())
    state_a = gate.connect_handshake(client_a)
    assert state_a.ok
    # b never handshook: it must refuse even though a's state exists
    _assert_refused(commands_mod.move_xy(client_b, 50000, 50000, unit="um"))
    # a re-handshakes against a NARROWER machine file: the new envelope governs
    root_b = tmp_path / "narrow_root"
    profile = provision_machine_limits(
        root_b, stage_um=dict(DEFAULT_STAGE_UM, x=[40000.0, 60000.0])
    )
    state_a2 = gate.connect_handshake(client_a, machine=profile)
    assert state_a2.ok
    refused = commands_mod.move_xy(client_a, 70000, 50000, unit="um")
    assert refused["success"] is False


# =============================================================================
# 5. Gate abuse
# =============================================================================


def test_setter_key_missing_from_machine_file_falls_back_to_defaults(mock_client):
    """A machine file missing a setter key is invalid (a new setter could ship silently
    ungated), so it is rejected and the complete bundled defaults govern."""
    _raw_snapshot(
        _machine_root(),
        limits_text=_with_payload(lambda p: {k: v for k, v in p.items() if k != "set_zoom"}),
    )
    state = gate.connect_handshake(mock_client)
    assert state.ok
    assert state.limits.describe()["is_fallback"] is True
    # the defaults carry every setter key, so set_zoom is explicitly unlimited
    assert gate.check_refusal(mock_client, "set_scan_speed", {}) is None


def test_absent_setter_falls_back_but_explicit_empty_list_is_unlimited(mock_client):
    """The flat contract uses [] for reviewed-and-unlimited setters."""
    provision_machine_limits(_machine_root())
    state = gate.connect_handshake(mock_client)
    assert state.ok
    ok = commands_mod.set_zoom(mock_client, "Overview", 1.0)
    assert ok["success"] is True
    # Missing-key fallback is covered above.


def test_reads_work_without_a_handshake_while_mutations_refuse(mock_client):
    """No handshake == read-only session, not a dead session. Reads never touch
    the gate; mutations refuse fail-closed until a handshake runs."""
    import navigator_expert as drv

    # This client never handshook — the one path that stays fail-closed.
    assert gate.state_for(mock_client) is None
    assert drv.ping(mock_client)
    jobs = drv.get_jobs(mock_client, mode="api")
    assert jobs
    _assert_refused(commands_mod.acquire(mock_client, jobs[0]["Name"]))


# =============================================================================
# 6. Bypass attempts — every entry point, refused at the commands layer
# =============================================================================


class _Untouchable:
    """A client stand-in that fails the test if the wrapper touches it."""

    def __getattr__(self, name):  # pragma: no cover - reaching here IS the failure
        raise AssertionError(f"native client touched (attribute {name!r}) before the gate refused")


_HW_INFO = {"Microscope": {"objectives": [{"slotIndex": 1, "name": "10x", "objectiveNumber": 1}]}}

# wrapper name -> zero-state invocation (client is a poisoned _Untouchable):
# the gate must refuse BEFORE any client attribute is touched.
_WRAPPER_CALLS = {
    "set_zoom": lambda c: commands_mod.set_zoom(c, "Overview", 5.0),
    "set_scan_speed": lambda c: commands_mod.set_scan_speed(c, "Overview", 400),
    "set_scan_resonant": lambda c: commands_mod.set_scan_resonant(c, "Overview", True),
    "set_scan_mode": lambda c: commands_mod.set_scan_mode(c, "Overview", "xyz"),
    "set_sequential_mode": lambda c: commands_mod.set_sequential_mode(c, "Overview", "Frame"),
    "set_scan_field_rotation": lambda c: commands_mod.set_scan_field_rotation(c, "Overview", 0.0),
    "set_image_format": lambda c: commands_mod.set_image_format(c, "Overview", "512 x 512"),
    "set_objective": lambda c: commands_mod.set_objective(c, "J", _HW_INFO, slot_index=1),
    "set_z_stack_definition": lambda c: commands_mod.set_z_stack_definition(
        c, "Overview", begin_um=0.0, end_um=1.0
    ),
    "set_z_stack_step_size": lambda c: commands_mod.set_z_stack_step_size(c, "Overview", 1.0),
    "set_z_stack_size": lambda c: commands_mod.set_z_stack_size(c, "Overview", 10.0),
    "set_frame_accumulation": lambda c: commands_mod.set_frame_accumulation(c, "Overview", 0, 2),
    "set_frame_average": lambda c: commands_mod.set_frame_average(c, "Overview", 0, 2),
    "set_line_accumulation": lambda c: commands_mod.set_line_accumulation(c, "Overview", 0, 2),
    "set_line_average": lambda c: commands_mod.set_line_average(c, "Overview", 0, 2),
    "set_pinhole_airy": lambda c: commands_mod.set_pinhole_airy(c, "Overview", 0, 1.0),
    "set_detector_gain": lambda c: commands_mod.set_detector_gain(c, "Overview", 0, "40;3", 100.0),
    "set_laser_intensity": lambda c: commands_mod.set_laser_intensity(
        c, "Overview", 0, "30", 0, 0.1
    ),
    "set_laser_shutter": lambda c: commands_mod.set_laser_shutter(c, "Overview", 0, "30", True),
    "set_filter_wheel_slot": lambda c: commands_mod.set_filter_wheel_slot(
        c, "Overview", 0, "40;3", 1, 2
    ),
    "set_filter_wheel_spectrum": lambda c: commands_mod.set_filter_wheel_spectrum(
        c, "Overview", 0, "40;3", 1, 500.0
    ),
    "move_xy": lambda c: commands_mod.move_xy(c, 50000, 50000, unit="um"),
    "move_z": lambda c: commands_mod.move_z(c, "J", 0.0, unit="um", z_mode="galvo"),
    "move_galvo_to_pixel": lambda c: commands_mod.move_galvo_to_pixel(c, 10, 10),
    "acquire": lambda c: commands_mod.acquire(c, "J"),
    "select_job": lambda c: commands_mod.select_job(c, "Overview"),
    "save_experiment": lambda c: scanfield_files.save_experiment(c, "t.xml", "/nonexistent"),
    "load_experiment": lambda c: scanfield_files.load_experiment(c, "t.xml"),
}

_SETTER_ALLOWED_VALUES = {
    "set_zoom": [5.0],
    "set_scan_speed": [400],
    "set_scan_resonant": [True],
    "set_scan_mode": ["xyz"],
    "set_sequential_mode": ["Frame"],
    "set_scan_field_rotation": [0.0],
    "set_image_format": ["512 x 512"],
    "set_z_stack_definition": [0.0, 1.0],
    "set_z_stack_step_size": [1.0],
    "set_z_stack_size": [10.0],
    "set_frame_accumulation": [2],
    "set_frame_average": [2],
    "set_line_accumulation": [2],
    "set_line_average": [2],
    "set_pinhole_airy": [1.0],
    "set_detector_gain": [100.0],
    "set_laser_intensity": [0.1],
    "set_laser_shutter": [True],
    "set_filter_wheel_slot": [2],
    "set_filter_wheel_spectrum": [500.0],
}


@pytest.mark.parametrize("setter", stage_config.SETTER_LIMIT_KEYS)
def test_every_configurable_setter_enforces_before_touching_native_api(setter):
    """Every flat setter key is wired to its own lowest-level command wrapper."""
    client = _Untouchable()
    payload = _valid_payload()
    payload[setter] = {"allowed": ["__blocked_test_value__"]}
    policy = stage_config.validate_payload(payload)
    gate._install(
        client,
        gate.GateState(
            limits=gate.LeicaLimits(policy, source="test", path="limits.json", is_fallback=False),
            stage_cfg=None,
            error=None,
        ),
    )

    result = _WRAPPER_CALLS[setter](client)
    assert result["success"] is False
    assert f"{setter} refused" in result["message"]
    assert "not allowed" in result["message"]


@pytest.mark.parametrize("setter", stage_config.SETTER_LIMIT_KEYS)
def test_every_configurable_setter_accepts_its_allowed_value(mock_client, setter):
    """The typed policy forwards the real setter value, not a metadata field."""
    payload = _valid_payload()
    payload[setter] = {"allowed": _SETTER_ALLOWED_VALUES[setter]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    assert gate.connect_handshake(mock_client).ok

    result = _WRAPPER_CALLS[setter](mock_client)
    assert result["success"] is True, (setter, result)


def test_setter_range_accepts_boundaries_and_refuses_outside(mock_client):
    payload = _valid_payload()
    payload["set_zoom"] = {"range": [1.0, 5.0]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    assert gate.connect_handshake(mock_client).ok

    assert commands_mod.set_zoom(mock_client, "Overview", 1.0)["success"] is True
    assert commands_mod.set_zoom(mock_client, "Overview", 5.0)["success"] is True
    refused = commands_mod.set_zoom(mock_client, "Overview", 5.01)
    assert refused["success"] is False
    assert "outside range [1.0, 5.0]" in refused["message"]


def test_setter_allowed_accepts_member_and_refuses_other(mock_client):
    payload = _valid_payload()
    payload["set_scan_mode"] = {"allowed": ["xyz"]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    assert gate.connect_handshake(mock_client).ok

    assert commands_mod.set_scan_mode(mock_client, "Overview", "xyz")["success"] is True
    refused = commands_mod.set_scan_mode(mock_client, "Overview", "xyzt")
    assert refused["success"] is False
    assert "expected one of ['xyz']" in refused["message"]


def test_z_stack_definition_checks_both_endpoints_before_native_api():
    client = _Untouchable()
    payload = _valid_payload()
    payload["set_z_stack_definition"] = {"range": [0.0, 10.0]}
    policy = stage_config.validate_payload(payload)
    gate._install(
        client,
        gate.GateState(
            limits=gate.LeicaLimits(policy, source="test", path="limits.json", is_fallback=False),
            stage_cfg=None,
            error=None,
        ),
    )

    refused = commands_mod.set_z_stack_definition(client, "J", begin_um=5.0, end_um=11.0)
    assert refused["success"] is False
    assert "11.0 outside range [0.0, 10.0]" in refused["message"]


def test_z_stack_definition_configured_limit_refuses_value_unknown_reset():
    client = _Untouchable()
    payload = _valid_payload()
    payload["set_z_stack_definition"] = {"range": [0.0, 10.0]}
    policy = stage_config.validate_payload(payload)
    gate._install(
        client,
        gate.GateState(
            limits=gate.LeicaLimits(policy, source="test", path="limits.json", is_fallback=False),
            stage_cfg=None,
            error=None,
        ),
    )

    refused = commands_mod.set_z_stack_definition(client, "J", old_begin_um=0.0)
    assert refused["success"] is False
    assert "configured limit but the wrapper supplied no value" in refused["message"]


def test_installed_policy_is_independent_of_input_payload_mutation():
    client = _Untouchable()
    payload = _valid_payload()
    payload["set_zoom"] = {"allowed": [1.0]}
    policy = stage_config.validate_payload(payload)
    installed = gate.LeicaLimits(policy, source="test", path="limits.json", is_fallback=False)
    gate._install(
        client,
        gate.GateState(limits=installed, stage_cfg=None, error=None),
    )

    _assert_refused(commands_mod.set_zoom(client, "Overview", 5.0), needle="not allowed")
    payload["set_zoom"]["allowed"].append(5.0)
    policy["set_zoom"]["allowed"].append(5.0)
    _assert_refused(commands_mod.set_zoom(client, "Overview", 5.0), needle="not allowed")


def test_public_gate_status_is_detached_from_installed_policy(mock_client):
    payload = _valid_payload()
    payload["set_zoom"] = {"allowed": [1.0]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    status = gate.connect_handshake(mock_client)
    _assert_refused(commands_mod.set_zoom(mock_client, "Overview", 5.0), needle="not allowed")

    assert not hasattr(status.limits, "payload")
    assert not hasattr(status.limits, "check")
    status.stage_cfg["policy"]["set_zoom"]["allowed"].append(5.0)
    second_status = gate.state_for(mock_client)
    assert second_status.stage_cfg["policy"]["set_zoom"] == {"allowed": [1.0]}
    _assert_refused(commands_mod.set_zoom(mock_client, "Overview", 5.0), needle="not allowed")


def test_private_installed_policy_and_stage_snapshot_are_immutable(mock_client):
    payload = _valid_payload()
    payload["set_zoom"] = {"allowed": [1.0]}
    _raw_snapshot(_machine_root(), limits_text=json.dumps(payload))
    assert gate.connect_handshake(mock_client).ok
    installed = gate._state_for(mock_client)

    with pytest.raises(TypeError):
        installed.limits._policy["set_zoom"] = ("allowed", (1.0, 5.0))
    with pytest.raises(AttributeError):
        installed.limits._policy["set_zoom"][1].append(5.0)
    with pytest.raises(TypeError):
        installed.stage_cfg["policy"]["set_zoom"] = {"allowed": [1.0, 5.0]}
    _assert_refused(commands_mod.set_zoom(mock_client, "Overview", 5.0), needle="not allowed")


@pytest.mark.parametrize("wrapper", sorted(gate.MUTATING_COMMANDS))
def test_every_mutating_wrapper_refuses_fail_closed_without_state(wrapper):
    """Direct-commands bypass: no handshake -> refusal BEFORE the client is
    touched, for every declared mutating wrapper."""
    result = _WRAPPER_CALLS[wrapper](_Untouchable())
    if wrapper in ("save_experiment", "load_experiment"):
        assert result is None  # their contract: None = failure (refusal logged)
    else:
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "refused" in result["message"]


def test_adapter_bypass_refuses_at_the_commands_layer(clear_stage_limits):
    """Adapter entry point: an out-of-envelope move raises the ops-contract
    RuntimeError from the commands-layer gate, below the adapter. The invalid
    machine file falls back to defaults, so the refusal is the envelope check,
    not a missing handshake."""
    from unittest.mock import patch

    from navigator_expert.commands import settings as _cmd_settings
    from navigator_expert.zmart_adapter import zmart_adapter as adapter

    _raw_snapshot(_machine_root(), limits_text=_BAD_LIMITS_TEXTS["missing_axis"])
    client = MockLasxClient(latency=0.0)
    with patch.object(adapter._session, "connect_python_client", return_value=client):
        handle = adapter.connect(dict(adapter.CONNECTION))
    settings = {
        "objective": {"name": "10x", "magnification": 10, "slotIndex": 1},
        "zPosition": {"z-wide": {"position": 0.0}, "z-galvo": {"position": 0.0}},
    }
    with (
        patch.object(adapter._readers, "get_xy", return_value={"x_um": 50000, "y_um": 30000}),
        patch.object(adapter._readers, "get_job_settings", return_value=settings),
        patch.object(
            adapter._readers,
            "get_selected_job",
            return_value={"Name": "Overview", "IsSelected": True},
        ),
        patch.object(_cmd_settings, "make_changeable_copy", side_effect=lambda s: s),
    ):
        # Frame target (0, 0, 0) with an unset (absolute) origin lands at stage
        # x = 0, below the envelope's x_min — the commands-layer gate refuses.
        with pytest.raises(RuntimeError, match="outside"):
            adapter.set_xyz(handle, 0.0, 0.0, 0.0)


def test_controller_session_bypass_refuses_at_the_commands_layer(clear_stage_limits):
    """Controller entry point (Session -> ops table -> adapter -> commands):
    an out-of-envelope move still refuses at the commands layer."""
    from unittest.mock import patch

    from navigator_expert.commands import settings as _cmd_settings
    from navigator_expert.zmart_adapter import zmart_adapter as adapter

    import zmart_controller

    _raw_snapshot(_machine_root(), limits_text=_BAD_LIMITS_TEXTS["missing_axis"])
    client = MockLasxClient(latency=0.0)
    settings = {
        "objective": {"name": "10x", "magnification": 10, "slotIndex": 1},
        "zPosition": {"z-wide": {"position": 0.0}, "z-galvo": {"position": 0.0}},
    }
    with (
        patch.object(adapter._session, "connect_python_client", return_value=client),
        patch.object(adapter._readers, "get_xy", return_value={"x_um": 50000, "y_um": 30000}),
        patch.object(adapter._readers, "get_job_settings", return_value=settings),
        patch.object(
            adapter._readers,
            "get_selected_job",
            return_value={"Name": "Overview", "IsSelected": True},
        ),
        patch.object(_cmd_settings, "make_changeable_copy", side_effect=lambda s: s),
    ):
        instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "leica")
        session = zmart_controller.set_instrument(instrument)
        try:
            with pytest.raises(RuntimeError, match="outside"):
                session.set_xyz(0.0, 0.0, 0.0)
        finally:
            session.disconnect()


def test_stale_gate_state_does_not_govern_a_new_client():
    """A fresh client must not inherit another client's (or a dead client's)
    envelope: the registry pins clients by strong reference, so a new client
    always starts fail-closed."""
    provision_machine_limits(_machine_root())
    governed = MockLasxClient(latency=0.0)
    assert gate.connect_handshake(governed).ok
    fresh = MockLasxClient(latency=0.0)
    assert gate.state_for(fresh) is None
    _assert_refused(commands_mod.move_xy(fresh, 50000, 50000, unit="um"))


# =============================================================================
# 7. Completeness — the commands-layer successor of _MUTATING_OPS
# =============================================================================


def test_mapping_is_total_over_the_key_vocabulary():
    assert set(_WRAPPER_CALLS) == set(gate.MUTATING_COMMANDS)


def test_bundled_template_declares_exactly_the_key_vocabulary():
    template = json.loads(
        (DRIVER_ROOT / "limits" / "defaults" / "limits.json").read_text(encoding="utf-8")
    )
    assert set(template) == set(stage_config._REQUIRED_FILE_KEYS)
    assert all(template[name] == [] for name in stage_config.SETTER_LIMIT_KEYS)
    stage_config.validate_payload(template)


def test_generated_machine_payload_matches_the_vocabulary():
    payload = stage_config.build_limits_payload(DEFAULT_STAGE_UM)
    assert set(payload) == set(stage_config._REQUIRED_FILE_KEYS)
    assert payload["x_um"] == {"range": DEFAULT_STAGE_UM["x"]}
    assert payload["objective_slot"] == []


def test_every_dispatching_wrapper_declares_and_calls_the_gate():
    """AST completeness sweep over commands.py: any public function that
    reaches the fire path (_dispatch/_dispatch_setting/confirm_and_fire)
    or the LRP transaction must (a) be declared in gate.MUTATING_COMMANDS and
    (b) call the gate with ITS OWN name — a new command cannot ship ungated."""
    source = (DRIVER_ROOT / "commands" / "commands.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fire_names = {"_dispatch", "_dispatch_setting", "confirm_and_fire", "apply_lrp_change"}
    # Raw-receipt fires (the scanfields/files.py shape) must not escape the
    # sweep either: a wrapper that skips the dispatch helpers and calls
    # api_obj.UpdateAwaitReceipt()/UpdateAsync() directly still reaches
    # hardware.
    fire_attrs = {"UpdateAwaitReceipt", "UpdateAsync"}
    checked = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        referenced = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        referenced_attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        if not (referenced & fire_names) and not (referenced_attrs & fire_attrs):
            continue
        assert node.name in gate.MUTATING_COMMANDS, (
            f"{node.name} dispatches to the fire path but has no MUTATING_COMMANDS entry"
        )
        gate_literals = {
            call.args[1].value
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and (
                (isinstance(call.func, ast.Name) and call.func.id == "_limits_refusal")
                or (isinstance(call.func, ast.Attribute) and call.func.attr == "check_refusal")
            )
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
        }
        assert node.name in gate_literals, (
            f"{node.name} never calls the limits gate with its own name"
        )
        checked.append(node.name)
    # sanity: the sweep actually saw the wrapper set (all but the two
    # scanfields file mutators, which live in scanfields/files.py)
    assert set(checked) == set(gate.MUTATING_COMMANDS) - {"save_experiment", "load_experiment"}


def test_scanfield_file_mutators_call_the_gate():
    source = (DRIVER_ROOT / "scanfields" / "files.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name in ("save_experiment", "load_experiment"):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        literals = {
            call.args[1].value
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "check_refusal"
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
        }
        assert name in literals, f"{name} never calls the limits gate with its own name"


# =============================================================================
# 8. Backstop constants — pinned to the historical machine envelope
# =============================================================================


def test_backstop_matches_the_historical_machine_envelope():
    """VERIFY-ON-RIG values: the backstop must equal the bundled template's
    envelope until measured rig data says otherwise (never wider)."""
    template = json.loads(
        (DRIVER_ROOT / "limits" / "defaults" / "limits.json").read_text(encoding="utf-8")
    )
    for axis, (lo, hi) in motion_limits.STAGE_BACKSTOP_UM.items():
        assert template[f"{axis}_um"] == {"range": [lo, hi]}
        assert math.isfinite(lo) and math.isfinite(hi)


def test_containment_checker_accepts_the_template_and_narrower():
    motion_limits.check_envelope_within_backstop(DEFAULT_STAGE_UM)
    motion_limits.check_envelope_within_backstop(dict(DEFAULT_STAGE_UM, x=[20000.0, 40000.0]))
    with pytest.raises(RuntimeError, match="backstop"):
        motion_limits.check_envelope_within_backstop(
            dict(DEFAULT_STAGE_UM, z_galvo=[-201.0, 200.0])
        )


# =============================================================================
# 9. ProgramData seeding — repo defaults become local runtime state
# =============================================================================


def test_resolution_seeds_programdata_and_returns_local_paths():
    profile = MachineProfile(programdata_root=_machine_root())
    path, is_fallback = profile.resolve("limits.json")
    assert is_fallback is False
    assert path == profile.latest_snapshot("limits") / "limits.json"
    assert path.exists()
    assert profile.require_machine_local("limits.json", "the physical stage envelope") == path
    assert stage_config.load()["stage_um"]["x"] == DEFAULT_STAGE_UM["x"]


def test_calibration_values_seed_programdata_from_repo_defaults():
    machine = MachineProfile(programdata_root=_machine_root())
    path, is_fallback = machine.resolve("calibration.json")
    assert is_fallback is False
    assert path == machine.latest_snapshot("calibration") / "calibration.json"
    assert path.exists()
    assert machine.calibration_path() == path


def test_backlash_is_not_config_and_the_primitive_uses_its_default_params():
    """§2b (resolves MR-01/MR-02): backlash left limits.json entirely. The
    published limits.json has NO backlash block, stage_config.load reads only
    the envelope, and the motion primitive carries its own baked-in defaults —
    there is no config path (and so no NaN-backlash path) left in limits."""
    import inspect

    from navigator_expert.motion import movement

    profile = provision_machine_limits(_machine_root())
    limits_path = profile.latest_snapshot("limits") / "limits.json"
    on_disk = json.loads(limits_path.read_text(encoding="utf-8"))
    assert "backlash" not in on_disk

    cfg = stage_config.load(limits_path=limits_path)
    assert set(cfg) == {"policy", "stage_um"}
    assert set(cfg["stage_um"]) == {"x", "y", "z_galvo", "z_wide"}
    assert cfg["stage_um"]["x"] == DEFAULT_STAGE_UM["x"]

    # the primitive's params are baked into its signature, not read from config
    defaults = inspect.signature(movement.move_xy_with_backlash).parameters
    assert defaults["overshoot_um"].default == 50.0
    assert defaults["settle_ms"].default == 100
    assert defaults["tolerance_um"].default is None


def test_a_calibration_adopt_does_not_duplicate_other_machine_config():
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    snap = profile.publish_snapshot(
        datetime(2026, 3, 1, tzinfo=timezone.utc), calibration={"marker": "cal"}
    )
    assert not (snap / "limits.json").exists()
    assert not (snap / "orientation.json").exists()
    assert not (snap / "function_limits.json").exists()  # the file is gone entirely
    client = MockLasxClient(latency=0.0)
    state = gate.connect_handshake(client)
    assert state.ok


def test_fresh_limits_adopt_writes_complete_limits_snapshot():
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    assert profile.latest_snapshot("limits") is None  # fresh machine
    stage_config.adopt_limits(
        DEFAULT_STAGE_UM, machine=profile, moment=datetime(2026, 4, 1, tzinfo=timezone.utc)
    )
    snap = profile.latest_snapshot("limits")
    files = sorted(p.name for p in snap.iterdir())
    assert files == [".limits-machine", "limits.json"]
    assert not (snap / "function_limits.json").exists()


def test_adopted_limits_report_machine_source_to_the_notebook_preflight(mock_client):
    """Publishing measured limits must satisfy the v4 notebook's preflight.

    The jobs cell of ``zmart_microscopy_v4.ipynb`` refuses to run unless the
    observed limits say ``source == "machine"`` — and its error message sends
    the operator to the ``set_stage_limits`` notebook. That notebook publishes
    through ``adopt_limits``, so the whole chain must land on ``"machine"``:
    adopt -> limits.json -> connect handshake -> ``describe()``. It once did
    not (``adopt_limits`` defaulted to ``"defaults"``), which sent operators
    around the error message's instructions in a circle forever.
    """
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    stage_config.adopt_limits(
        DEFAULT_STAGE_UM, machine=profile, moment=datetime(2026, 6, 1, tzinfo=timezone.utc)
    )
    merged = json.loads(
        (profile.latest_snapshot("limits") / "limits.json").read_text(encoding="utf-8")
    )
    assert "source" not in merged

    state = gate.connect_handshake(mock_client, machine=profile)
    assert state.ok, state.error
    limits = state.limits.describe()
    # The exact refusal expression the v4 notebook's jobs cell evaluates:
    assert not (not limits or limits.get("is_fallback") or limits.get("source") != "machine")


def test_flat_limits_round_trip_adopt_handshake_gated_move(mock_client):
    """Notebook shape -> snapshot -> handshake -> bounded move."""
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    stage_config.adopt_limits(
        DEFAULT_STAGE_UM, machine=profile, moment=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )
    snap = profile.latest_snapshot("limits")
    merged = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert set(merged) == set(stage_config._REQUIRED_FILE_KEYS)
    assert merged["x_um"] == {"range": [1000.0, 130000.0]}
    assert merged["objective_slot"] == []

    state = gate.connect_handshake(mock_client, machine=profile)
    assert state.ok, state.error
    assert commands_mod.move_xy(mock_client, 50000, 50000, unit="um")["success"] is True
    refused = commands_mod.move_xy(mock_client, 200000, 50000, unit="um")
    assert refused["success"] is False
    assert "outside" in refused["message"] or "backstop" in refused["message"]
