"""Guard tests for the limits architecture.

The design (MAINTAINER_DECISIONS.md §7 and the 2026-07-19 driver review)
is one sentence: ``limits/`` is the rulebook, the commands layer is the
only place it is enforced, and nothing above the commands layer checks
limits or moves the stage itself.

These tests read the driver's source files and fail when a new module
breaks that sentence — so the rule survives as a red test instead of a
code-review comment. If one of these fails, the fix is almost never to
edit this file: move the offending call down into ``commands/`` (or ask
the rulebook via a command) instead.
"""

from __future__ import annotations

from pathlib import Path

DRIVER_ROOT = Path(__file__).resolve().parents[2]

# Folders whose modules are allowed to fire native stage motion or call
# the limit-check functions. Tests are excluded from the scan entirely —
# they may exercise anything.
COMMANDS = "commands"
LIMITS = "limits"


def _driver_sources():
    """Yield (relative_path, text) for every non-test driver module."""
    for path in sorted(DRIVER_ROOT.rglob("*.py")):
        rel = path.relative_to(DRIVER_ROOT)
        if rel.parts[0] in ("tests",) or "tests" in rel.parts[:-1]:
            continue
        yield rel, path.read_text(encoding="utf-8")


def test_native_stage_motion_fires_only_from_the_commands_layer():
    """The native CAM motion functions are the stage's real door.

    Only the command wrappers may touch them — that is where the limit
    checks run, immediately before the native call. A native-motion
    reference anywhere else would be a second, unchecked door.
    """
    offenders = [
        str(rel)
        for rel, text in _driver_sources()
        if "PyApiMoveHardware" in text and rel.parts[0] != COMMANDS
    ]
    assert offenders == [], (
        f"native stage motion referenced outside commands/: {offenders} — "
        f"route the move through commands.move_xy / move_z instead"
    )


def test_limit_checks_are_called_only_from_the_commands_layer():
    """``check_xy`` / ``check_z`` may be *defined* in limits/ and *called*
    only from commands/. A call anywhere else is a second whistle: a copy
    of enforcement that can drift out of sync with the real one."""
    offenders = []
    for rel, text in _driver_sources():
        if rel.parts[0] in (COMMANDS, LIMITS):
            continue
        if "check_xy(" in text or "check_z(" in text:
            offenders.append(str(rel))
    assert offenders == [], (
        f"limit checks called outside commands/: {offenders} — the commands "
        f"already check every move; delete the duplicate call"
    )


def test_the_decision_engine_lives_in_limits():
    """``LeicaLimits`` (the compiled limits document) is defined in
    limits/checks.py; the gate only imports it. If the class definition
    moves back into the gate, rulebook and whistle have merged again."""
    checks_text = (DRIVER_ROOT / "limits" / "checks.py").read_text(encoding="utf-8")
    gate_text = (DRIVER_ROOT / "commands" / "gate.py").read_text(encoding="utf-8")
    assert "class LeicaLimits" in checks_text
    assert "class LeicaLimits" not in gate_text
