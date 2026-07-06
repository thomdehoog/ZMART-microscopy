"""Permanent adversarial suite for the limits enforcement redesign.

Attacks the commands-layer function-keyed gate (``commands/gate.py``), the
connect-time limits handshake, the no-fallback resolution, and the hardcoded
physical backstop — through every entry point (direct commands, adapter op,
controller Session). Every attack must produce a FAIL-CLOSED refusal with a
clear error: never silent acceptance, never a crash that bypasses the gate.

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

from shared import limits as shared_limits

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
    """A valid merged limits.json payload: constraints + functions + backlash."""
    return merged_limits_payload(stage_um or DEFAULT_STAGE_UM, functions=functions)


def _valid_limits_text(stage_um: dict | None = None) -> str:
    return json.dumps(_valid_payload(stage_um))


def _with_constraints(mutate) -> str:
    """A merged payload whose (otherwise valid) constraints are mutated."""
    payload = _valid_payload()
    payload["constraints"] = mutate(dict(payload["constraints"]))
    return json.dumps(payload)


def _with_functions(functions: dict) -> str:
    """A merged payload (valid envelope) with a custom ``functions`` block."""
    return json.dumps(_valid_payload(functions=functions))


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
# 1. Malformed limits.json — the handshake must refuse, reads must survive
# =============================================================================

_BAD_LIMITS_TEXTS = {
    "truncated": '{"schema_version": 1, "source": "defa',
    "non_json": "this is not json <at all>",
    "empty_dict": "{}",
    "wrong_schema_version": json.dumps(dict(_valid_payload(), schema_version=99)),
    "missing_source": json.dumps({k: v for k, v in _valid_payload().items() if k != "source"}),
    "missing_constraints": json.dumps(
        {k: v for k, v in _valid_payload().items() if k != "constraints"}
    ),
    "missing_axis": _with_constraints(lambda c: {k: v for k, v in c.items() if k != "stage.y"}),
    "unknown_axis": _with_constraints(lambda c: {**c, "stage.theta": {"min": 0, "max": 360}}),
    "constraint_not_an_object": _with_constraints(lambda c: {**c, "stage.x": [1000, 130000]}),
    "constraint_missing_min_max": _with_constraints(lambda c: {**c, "stage.x": {"lo": 1, "hi": 2}}),
    "min_greater_than_max": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[130000, 1000])),
    # json.dumps emits NaN / Infinity literals (allow_nan) — the validators must refuse.
    "nan": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[float("nan"), 130000])),
    "infinity": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[1000, float("inf")])),
    "wider_than_backstop": _valid_limits_text(dict(DEFAULT_STAGE_UM, x=[0, 500000])),
}


@pytest.mark.parametrize("attack", sorted(_BAD_LIMITS_TEXTS))
def test_malformed_limits_json_fails_the_handshake_closed(attack, mock_client):
    _raw_snapshot(_machine_root(), limits_text=_BAD_LIMITS_TEXTS[attack])
    state = gate.connect_handshake(mock_client)
    assert not state.ok
    assert "set_stage_limits.ipynb" in state.error  # actionable, names the factory
    # every mutating command refuses with the recorded reason...
    _assert_refused(commands_mod.move_xy(mock_client, 50000, 50000, unit="um"))
    _assert_refused(commands_mod.set_zoom(mock_client, "HiRes", 5.0))
    # ...and the envelope was never applied
    assert motion_limits.get_stage_limits()["x_min"] is None
    # reads still work (read-only sessions stay usable)
    assert mock_client.PyApiPing is not None


# =============================================================================
# 2. Malformed functions block (same limits.json) — same fail-closed posture
# =============================================================================

_ALL_NULL = {key: None for key in gate.FUNCTION_LIMIT_KEYS}

_BAD_FUNCTION_LIMITS_TEXTS = {
    "truncated": '{"schema_version": 1, "sou',
    "non_json": "definitely not json",
    "empty_dict": "{}",
    "missing_functions": json.dumps(
        {k: v for k, v in _valid_payload().items() if k != "functions"}
    ),
    "functions_empty_but_valid_json": _with_functions({}),
    "missing_op_key": _with_functions(
        {k: None for k in gate.FUNCTION_LIMIT_KEYS if k != "acquire"}
    ),
    "unknown_op_key": _with_functions(dict(_ALL_NULL, set_warp_drive=None)),
    "entry_is_list": _with_functions(dict(_ALL_NULL, acquire=[])),
    "entry_is_string": _with_functions(dict(_ALL_NULL, acquire="yes")),
    # json.dumps emits NaN / Infinity literals (allow_nan) — the parser must refuse.
    "constraint_nan_min": _with_functions(
        dict(_ALL_NULL, set_xyz={"x_um": {"min": float("nan"), "max": 1.0}})
    ),
    "constraint_infinite_max": _with_functions(
        dict(_ALL_NULL, set_xyz={"x_um": {"min": 0, "max": float("inf")}})
    ),
    "constraint_bounds_nothing": _with_functions(dict(_ALL_NULL, set_xyz={"x_um": {}})),
    "constraint_min_gt_max": _with_functions(
        dict(_ALL_NULL, set_xyz={"x_um": {"min": 10, "max": 1}})
    ),
}


@pytest.mark.parametrize("attack", sorted(_BAD_FUNCTION_LIMITS_TEXTS))
def test_malformed_function_limits_fails_the_handshake_closed(attack, mock_client):
    _raw_snapshot(_machine_root(), limits_text=_BAD_FUNCTION_LIMITS_TEXTS[attack])
    state = gate.connect_handshake(mock_client)
    assert not state.ok, attack
    _assert_refused(commands_mod.move_xy(mock_client, 50000, 50000, unit="um"))
    _assert_refused(commands_mod.select_job(mock_client, "Overview"))


def test_nan_in_function_constraint_is_rejected(mock_client):
    """json.dumps emits a bare NaN literal; the shared parser must refuse it —
    even when it lives in an inline ``functions`` constraint, not the envelope."""
    text = _with_functions(dict(_ALL_NULL, set_xyz={"x_um": {"min": float("nan"), "max": 130000}}))
    _raw_snapshot(_machine_root(), limits_text=text)
    state = gate.connect_handshake(mock_client)
    assert not state.ok
    assert "finite" in state.error


# =============================================================================
# 3. Poisoned call values — after a GOOD handshake
# =============================================================================


@pytest.fixture()
def governed_client(mock_client):
    provision_machine_limits(_machine_root())
    state = gate.connect_handshake(mock_client)
    assert state.ok, state.error
    return mock_client


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
    """NaN compares False against every bound; the constraint must still refuse."""
    limits = shared_limits.parse(
        gate.build_function_limits_payload(DEFAULT_STAGE_UM),
        functions=gate.FUNCTION_LIMIT_KEYS,
    )
    with pytest.raises(shared_limits.LimitViolation, match="finite"):
        limits.check("set_xyz", {"x_um": float("nan")})


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
    assert "set_stage_limits.ipynb" in result["message"]
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


def test_hand_widened_limits_file_is_refused_at_the_handshake(mock_client):
    _raw_snapshot(
        _machine_root(),
        limits_text=_valid_limits_text(dict(DEFAULT_STAGE_UM, y=[0.0, 400000.0])),
    )
    state = gate.connect_handshake(mock_client)
    assert not state.ok
    assert "backstop" in state.error
    _assert_refused(commands_mod.move_xy(mock_client, 50000, 50000, unit="um"))


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


def test_op_key_missing_from_machine_file_refuses_everything(mock_client):
    _raw_snapshot(
        _machine_root(),
        limits_text=_with_functions({k: None for k in gate.FUNCTION_LIMIT_KEYS if k != "set_xyz"}),
    )
    state = gate.connect_handshake(mock_client)
    assert not state.ok
    assert "set_xyz" in state.error
    _assert_refused(commands_mod.set_scan_speed(mock_client, "HiRes", 400))


def test_absent_key_fails_closed_but_explicit_null_is_unlimited(mock_client):
    """The shared spec's semantics, pinned at the commands gate (amendment 3):
    explicit ``null`` = reviewed-and-unlimited (command may fire); an ABSENT
    key is a load error (everything refuses)."""
    provision_machine_limits(_machine_root())  # template policy: null everywhere
    state = gate.connect_handshake(mock_client)
    assert state.ok
    ok = commands_mod.select_job(mock_client, "Overview")  # gated by null key
    assert ok["success"] is True
    # absent key case is test_op_key_missing_from_machine_file_refuses_everything


def test_reads_work_while_all_mutations_refuse(mock_client):
    """Failed handshake == read-only session, not a dead session."""
    import navigator_expert as drv

    state = gate.connect_handshake(mock_client)  # empty machine root: fails
    assert not state.ok
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
    "set_zoom": lambda c: commands_mod.set_zoom(c, "J", 5.0),
    "set_scan_speed": lambda c: commands_mod.set_scan_speed(c, "J", 400),
    "set_scan_resonant": lambda c: commands_mod.set_scan_resonant(c, "J", True),
    "set_scan_mode": lambda c: commands_mod.set_scan_mode(c, "J", "xyz"),
    "set_sequential_mode": lambda c: commands_mod.set_sequential_mode(c, "J", "Frame"),
    "set_scan_field_rotation": lambda c: commands_mod.set_scan_field_rotation(c, "J", 0.0),
    "set_image_format": lambda c: commands_mod.set_image_format(c, "J", "512 x 512"),
    "set_objective": lambda c: commands_mod.set_objective(c, "J", _HW_INFO, slot_index=1),
    "set_z_stack_definition": lambda c: commands_mod.set_z_stack_definition(
        c, "J", begin_um=0.0, end_um=1.0
    ),
    "set_z_stack_step_size": lambda c: commands_mod.set_z_stack_step_size(c, "J", 1.0),
    "set_z_stack_size": lambda c: commands_mod.set_z_stack_size(c, "J", 10.0),
    "set_frame_accumulation": lambda c: commands_mod.set_frame_accumulation(c, "J", 0, 2),
    "set_frame_average": lambda c: commands_mod.set_frame_average(c, "J", 0, 2),
    "set_line_accumulation": lambda c: commands_mod.set_line_accumulation(c, "J", 0, 2),
    "set_line_average": lambda c: commands_mod.set_line_average(c, "J", 0, 2),
    "set_pinhole_airy": lambda c: commands_mod.set_pinhole_airy(c, "J", 0, 1.0),
    "set_detector_gain": lambda c: commands_mod.set_detector_gain(c, "J", 0, "40;3", 100.0),
    "set_laser_intensity": lambda c: commands_mod.set_laser_intensity(c, "J", 0, "30", 0, 0.1),
    "set_laser_shutter": lambda c: commands_mod.set_laser_shutter(c, "J", 0, "30", True),
    "set_filter_wheel_slot": lambda c: commands_mod.set_filter_wheel_slot(c, "J", 0, "40;3", 1, 2),
    "set_filter_wheel_spectrum": lambda c: commands_mod.set_filter_wheel_spectrum(
        c, "J", 0, "40;3", 1, 500.0
    ),
    "move_xy": lambda c: commands_mod.move_xy(c, 50000, 50000, unit="um"),
    "move_z": lambda c: commands_mod.move_z(c, "J", 0.0, unit="um", z_mode="galvo"),
    "move_galvo_to_pixel": lambda c: commands_mod.move_galvo_to_pixel(c, 10, 10),
    "acquire": lambda c: commands_mod.acquire(c, "J"),
    "select_job": lambda c: commands_mod.select_job(c, "Overview"),
    "save_experiment": lambda c: scanfield_files.save_experiment(c, "t.xml", "/nonexistent"),
    "load_experiment": lambda c: scanfield_files.load_experiment(c, "t.xml"),
}


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
    """Adapter entry point against an unprovisioned machine: set_xyz raises
    the ops-contract RuntimeError carrying the gate's actionable message."""
    from unittest.mock import patch

    from navigator_expert.commands import settings as _cmd_settings
    from navigator_expert.zmart_adapter import zmart_adapter as adapter

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
        with pytest.raises(RuntimeError, match="set_stage_limits.ipynb"):
            adapter.set_xyz(handle, 0.0, 0.0, 0.0)


def test_controller_session_bypass_refuses_at_the_commands_layer(clear_stage_limits):
    """Controller entry point (Session -> ops table -> adapter -> commands):
    the refusal still originates at the commands layer."""
    from unittest.mock import patch

    from navigator_expert.commands import settings as _cmd_settings
    from navigator_expert.zmart_adapter import zmart_adapter as adapter

    import zmart_controller

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
            with pytest.raises(RuntimeError, match="set_stage_limits.ipynb"):
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
    assert set(gate.MUTATING_COMMANDS.values()) <= set(gate.FUNCTION_LIMIT_KEYS)
    assert set(_WRAPPER_CALLS) == set(gate.MUTATING_COMMANDS)


def test_bundled_template_declares_exactly_the_key_vocabulary():
    template = json.loads(
        (DRIVER_ROOT / "limits" / "defaults" / "limits.json").read_text(encoding="utf-8")
    )
    assert set(template["functions"]) == set(gate.FUNCTION_LIMIT_KEYS)
    # the merged template carries a backlash block the gate parser ignores...
    assert "backlash" in template
    # ...and it still parses under the shared spec against the declared vocabulary
    shared_limits.parse(template, functions=gate.FUNCTION_LIMIT_KEYS)


def test_generated_machine_payload_matches_the_vocabulary():
    payload = gate.build_function_limits_payload(DEFAULT_STAGE_UM)
    assert set(payload["functions"]) == set(gate.FUNCTION_LIMIT_KEYS)
    limits = shared_limits.parse(payload, functions=gate.FUNCTION_LIMIT_KEYS)
    with pytest.raises(shared_limits.LimitViolation):
        limits.check("set_xyz", {"x_um": 999999.0})


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
        constraint = template["constraints"][f"stage.{axis}"]
        assert [constraint["min"], constraint["max"]] == [lo, hi]
        assert math.isfinite(lo) and math.isfinite(hi)


def test_containment_checker_accepts_the_template_and_narrower():
    motion_limits.check_envelope_within_backstop(DEFAULT_STAGE_UM)
    motion_limits.check_envelope_within_backstop(dict(DEFAULT_STAGE_UM, x=[20000.0, 40000.0]))
    with pytest.raises(RuntimeError, match="backstop"):
        motion_limits.check_envelope_within_backstop(
            dict(DEFAULT_STAGE_UM, z_galvo=[-201.0, 200.0])
        )


# =============================================================================
# 9. No-fallback resolution — provenance is explicit, templates refused
# =============================================================================


def test_resolution_reports_fallback_provenance_and_strict_path_refuses():
    profile = MachineProfile(programdata_root=_machine_root())
    path, is_fallback = profile.resolve("limits.json")
    assert is_fallback and path.name == "limits.json"
    with pytest.raises(RuntimeError, match="TEMPLATE"):
        profile.require_machine_local("limits.json", "the physical stage envelope")
    with pytest.raises(RuntimeError, match="set_stage_limits.ipynb"):
        stage_config.load()  # the limits leg is strict with no explicit path


def test_calibration_values_keep_their_loud_in_memory_read_fallback():
    """§7b: publishing never seeds calibration from the bundled template, but
    the READ fallback stays — calibration_path() resolves to the bundled file
    (a real last-known-good calibration) when no snapshot exists."""
    machine = MachineProfile(programdata_root=_machine_root())
    path, is_fallback = machine.resolve("calibration.json")
    assert is_fallback and path.exists()
    assert machine.calibration_path() == path  # loud fallback, still usable


def test_backlash_comes_from_the_same_limits_file():
    """§7b: the merged limits.json's backlash block is what stage_config reads
    (envelope from constraints.stage.*, backlash from the backlash block)."""
    profile = provision_machine_limits(_machine_root())
    cfg = stage_config.load(limits_path=profile.latest_snapshot() / "limits.json")
    assert set(cfg["stage_um"]) == {"x", "y", "z_galvo", "z_wide"}
    assert cfg["stage_um"]["x"] == DEFAULT_STAGE_UM["x"]
    assert "overshoot_um" in cfg["backlash"] and "approach" in cfg["backlash"]


def test_a_calibration_adopt_cannot_mint_enforceable_limits_from_the_template():
    """publish_snapshot must not copy the bundled templates into a machine
    snapshot as a side effect — that would launder the template into
    machine-local (enforceable) provenance."""
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    snap = profile.publish_snapshot(
        datetime(2026, 3, 1, tzinfo=timezone.utc), calibration={"marker": "cal"}
    )
    assert not (snap / "limits.json").exists()
    assert not (snap / "function_limits.json").exists()  # the file is gone entirely
    client = MockLasxClient(latency=0.0)
    state = gate.connect_handshake(client)
    assert not state.ok  # still refusing: the adopt did not provision limits


def test_fresh_limits_adopt_writes_only_limits_json_no_seeded_calibration():
    """§7b: a fresh-machine limits adopt writes ONLY limits.json (+origin if a
    prior one exists — here none does). It never mints a calibration.json from
    the bundled template."""
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    assert profile.latest_snapshot() is None  # fresh machine
    stage_config.adopt_limits(
        DEFAULT_STAGE_UM, machine=profile, moment=datetime(2026, 4, 1, tzinfo=timezone.utc)
    )
    snap = profile.latest_snapshot()
    files = sorted(p.name for p in snap.iterdir())
    assert files == ["limits.json"]  # exactly one file: no seeded calibration.json
    assert not (snap / "function_limits.json").exists()


def test_merged_limits_round_trip_adopt_handshake_gated_move(mock_client):
    """(§7b end-to-end) adopt -> one limits.json with constraints+functions+
    backlash -> handshake ok -> a legal move works, an out-of-envelope move is
    refused naming limits.json."""
    from datetime import datetime, timezone

    profile = MachineProfile(programdata_root=_machine_root())
    stage_config.adopt_limits(
        DEFAULT_STAGE_UM, machine=profile, moment=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )
    snap = profile.latest_snapshot()
    merged = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert set(merged) >= {"schema_version", "source", "constraints", "functions", "backlash"}
    assert merged["constraints"]["stage.x"] == {"min": 1000.0, "max": 130000.0}
    assert merged["functions"]["set_xyz"]["x_um"] == "@stage.x"

    state = gate.connect_handshake(mock_client, machine=profile)
    assert state.ok, state.error
    assert commands_mod.move_xy(mock_client, 50000, 50000, unit="um")["success"] is True
    refused = commands_mod.move_xy(mock_client, 200000, 50000, unit="um")
    assert refused["success"] is False
    assert "outside" in refused["message"] or "backstop" in refused["message"]
