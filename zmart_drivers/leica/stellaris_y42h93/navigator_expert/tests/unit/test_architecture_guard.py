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

import re
from pathlib import Path

DRIVER_ROOT = Path(__file__).resolve().parents[2]

# Folders whose modules are allowed to fire native stage motion or call
# the limit-check functions. Tests are excluded from the scan entirely —
# they may exercise anything.
COMMANDS = "commands"
LIMITS = "limits"

# Source selection is policy, not caller behaviour. The router implements
# the profile-controlled modes; the confirmation modules construct explicit
# API/log legs that the command policy races. Higher-level code must leave
# ``mode`` unset and consume the configured reader abstraction.
READER_SOURCE_POLICY_MODULES = {
    Path("readers/router.py"),
    Path("commands/confirmations.py"),
    Path("commands/confirm_select_job.py"),
    Path("commands/dispatch.py"),
}
EXPLICIT_READER_MODE = re.compile(r"\bmode\s*=\s*['\"](?:api|log|hybrid)['\"]")
LOW_LEVEL_READER_CALL = re.compile(r"(?<!\w)_?(?:api_reader|log_reader)\.")


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


def test_reader_source_is_selected_only_by_reader_and_confirmation_policy():
    """Operational callers consume the configured reader policy.

    An adapter, calibration routine, scanfield parser, or command helper that
    pins ``api``/``log``/``hybrid`` silently defeats ``StateReaderProfile``.
    Explicit modes belong only to the router and to confirmation-policy code
    constructing the individual legs of a configured race.
    """
    offenders = [
        str(rel)
        for rel, text in _driver_sources()
        if rel not in READER_SOURCE_POLICY_MODULES and EXPLICIT_READER_MODE.search(text)
    ]
    assert offenders == [], (
        f"reader source pinned outside policy layer: {offenders}; remove the "
        "mode override and let StateReaderProfile/capabilities route the datum"
    )


def test_low_level_readers_are_called_only_by_reader_and_confirmation_policy():
    """Operational callers cannot bypass the routed reader API."""
    offenders = [
        str(rel)
        for rel, text in _driver_sources()
        if rel.parts[0] != "readers"
        and rel not in READER_SOURCE_POLICY_MODULES
        and LOW_LEVEL_READER_CALL.search(text)
    ]
    assert offenders == [], (
        f"low-level reader called outside policy layer: {offenders}; route the "
        "read through navigator_expert.readers instead"
    )


def test_the_utils_grab_bag_stays_dissolved():
    """utils.py was dissolved on 2026-07-19 (each function moved to its
    natural owner: readers/parsing.py, commands/envelope.py,
    config/timing.py, config/galvo.py). A folder called "utils" promises
    nothing and therefore accumulates everything — this test keeps the
    grab-bag from quietly coming back."""
    assert not (DRIVER_ROOT / "utils.py").exists(), (
        "utils.py has reappeared — give each function a truthful home "
        "instead (see the 2026-07-19 driver review, §5.3.13)"
    )
