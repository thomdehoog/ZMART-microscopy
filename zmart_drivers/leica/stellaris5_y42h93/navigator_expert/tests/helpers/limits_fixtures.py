"""Limits fixtures for the offline suite and the mock validators.

Enforcement no longer falls back to the bundled ``limits/defaults/`` files
(they are templates), so anything that exercises mutating commands must
either provision a real machine-local snapshot (``provision_machine_limits``,
which the connect-time handshake then validates for real) or install a
permissive in-memory gate state for a specific client
(``install_permissive_limits``, the unit-test seam for command-mechanics
tests that are not about limits).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from navigator_expert.commands import gate as _gate
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


def provision_machine_limits(
    root: str | Path,
    *,
    stage_um: dict | None = None,
    function_limits: dict | None = None,
    moment: datetime | None = None,
) -> MachineProfile:
    """Publish a machine-local snapshot carrying limits + function limits.

    ``root`` is the ProgramData root (point ``SMART_MICROSCOPY_ROOT`` at it,
    or pass the returned profile explicitly). The connect handshake then
    resolves REAL machine-local files — the honest replacement for the old
    silent bundled fallback.
    """
    profile = MachineProfile(programdata_root=Path(root))
    stage_um = dict(stage_um or DEFAULT_STAGE_UM)
    limits_payload = {"schema_version": 1, "source": "defaults", "stage_um": stage_um}
    fl_payload = function_limits or _gate.build_function_limits_payload(stage_um)
    profile.publish_snapshot(
        moment or _SEED_MOMENT,
        limits=limits_payload,
        function_limits=fl_payload,
    )
    return profile


def hermetic_mock_machine_root() -> Path:
    """Provision a throwaway, provisioned machine root and make it active.

    For the ``--mock`` validators: creates a fresh temp ProgramData root,
    points ``SMART_MICROSCOPY_ROOT`` at it (so the global ``MACHINE`` resolves
    there and a developer machine's real ProgramData is never read), and
    publishes a fixture snapshot — the connect-time limits handshake then
    runs for REAL against machine-local files.
    """
    root = Path(tempfile.mkdtemp(prefix="smart_microscopy_mock_root_"))
    os.environ["SMART_MICROSCOPY_ROOT"] = str(root)
    provision_machine_limits(root)
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
