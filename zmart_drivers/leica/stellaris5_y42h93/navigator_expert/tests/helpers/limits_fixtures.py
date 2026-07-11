"""Limits fixtures for the offline suite and the mock validators.

Runtime limits resolve through ProgramData. An empty ProgramData root seeds the
repo defaults there automatically; tests call ``provision_machine_limits`` only
when they need a specific fixture envelope or gate policy. Command-mechanics
unit tests can also install a permissive in-memory gate state for one client
(``install_permissive_limits``).

The snapshot holds one flat ``limits.json``: axis ranges, allowed objective
slots, and explicit ``[]`` entries for unrestricted setters.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from navigator_expert.commands import gate as _gate
from navigator_expert.config import profiles
from navigator_expert.config.machine import MachineProfile
from navigator_expert.motion import limits as _motion_limits

from shared import limits as _shared_limits

# The historical machine envelope (== the bundled template and the hardcoded
# backstop in motion/limits.py) — the widest envelope a fixture may use.
DEFAULT_STAGE_UM = {
    "x": [1000.0, 130000.0],
    "y": [1000.0, 100000.0],
    "z_galvo": [-200.0, 200.0],
    "z_wide": [0.0, 25000.0],
}

_SEED_MOMENT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def merged_limits_payload(stage_um: dict, *, functions: dict | None = None) -> dict:
    """The single flat limits.json payload."""
    payload = _gate.build_function_limits_payload(stage_um)
    if functions is not None:
        payload.update(functions)
    return payload


def provision_machine_limits(
    root: str | Path,
    *,
    stage_um: dict | None = None,
    function_limits: dict | None = None,
    moment: datetime | None = None,
) -> MachineProfile:
    """Publish a machine-local snapshot carrying the single merged limits.json.

    ``root`` is the ProgramData root (point ``ZMART_MICROSCOPY_ROOT`` at it,
    or pass the returned profile explicitly). The connect handshake then
    resolves and validates that ProgramData file. ``function_limits`` overrides
    matching top-level entries for malformed-file tests.
    """
    profile = MachineProfile(programdata_root=Path(root))
    stage_um = dict(stage_um or DEFAULT_STAGE_UM)
    profile.publish_snapshot(
        moment or _SEED_MOMENT,
        limits=merged_limits_payload(stage_um, functions=function_limits),
    )
    return profile


def hermetic_mock_machine_root() -> Path:
    """Provision a throwaway, provisioned machine root and make it active.

    For the ``--mock`` validators: creates a fresh temp ProgramData root,
    points ``ZMART_MICROSCOPY_ROOT`` at it (so the global ``MACHINE`` resolves
    there and a developer machine's real ProgramData is never read), and
    publishes a fixture snapshot — the connect-time limits handshake then
    runs for REAL against machine-local files.

    Also redirects ``profiles.LOG_READER`` to nonexistent paths under the
    same throwaway root. The mock CAM client has no log stream (by design —
    see every validator's own "no LAS X log stream" framing), but
    ``LogReaderProfile``'s defaults are the *real* LAS X log paths
    (``config/profiles.py``); left alone, a machine with genuine LAS X log
    history (e.g. the actual bench PC, right after a live session) makes log
    reads succeed with real, stale data instead of correctly reading absent.
    Callers running under pytest must restore ``profiles.LOG_READER``
    afterwards (see ``tests/hardware/conftest.py``'s autouse fixture); this
    function only sets it.
    """
    root = Path(tempfile.mkdtemp(prefix="zmart_microscopy_mock_root_"))
    os.environ["ZMART_MICROSCOPY_ROOT"] = str(root)
    provision_machine_limits(root)
    profiles.LOG_READER = profiles.LogReaderProfile(
        lcs_log_path=str(root / "no_such_lcsCommand.log"),
        msgbox_log_path=str(root / "no_such_MatrixScreener.log"),
    )
    return root


def permissive_function_limits(**set_xyz_constraints) -> object:
    """An in-memory FunctionLimits: every key reviewed-unlimited (``null``).

    Pass ``set_xyz`` parameter constraints (e.g. ``x_um={"min": 0, "max": 1}``)
    to bound the move keys.
    """
    payload = {
        "schema_version": 1,
        "source": "test",
        "constraints": {},
        "functions": {key: None for key in _gate.FUNCTION_LIMIT_KEYS},
    }
    if set_xyz_constraints:
        payload["functions"]["set_xyz"] = {
            param: dict(bounds) for param, bounds in set_xyz_constraints.items()
        }
    return _shared_limits.parse(payload, functions=_gate.FUNCTION_LIMIT_KEYS)


def install_permissive_limits(client, *, wide_stage=False, **set_xyz_constraints):
    """Install a permissive gate state for *client* (unit-test seam).

    Tests about command mechanics (dispatch, confirmation, retries) are not
    about limits; this lets their mock clients through the fail-closed gate
    without touching disk. With ``wide_stage=True`` the module stage envelope
    is also set wide open (the old ``_wide_limits`` idiom) — note the
    hardcoded backstop still bounds every move.
    """
    _gate._install(
        client,
        _gate.GateState(
            limits=permissive_function_limits(**set_xyz_constraints),
            stage_cfg=None,
            error=None,
        ),
    )
    if wide_stage:
        _motion_limits.set_stage_limits(
            x_min=0.0,
            x_max=1_000_000.0,
            y_min=0.0,
            y_max=1_000_000.0,
            z_galvo_min=-200.0,
            z_galvo_max=200.0,
            z_wide_min=-100_000.0,
            z_wide_max=100_000.0,
        )
    return client
