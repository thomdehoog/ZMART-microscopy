"""Making the pretend microscope misbehave, on purpose.

Real microscopes fail in many small ways: the software is busy, a reply never
arrives, a setting is accepted but quietly not applied, a reading is out of
date, the program crashes. A driver has to handle every one of these calmly,
and the only way to be sure it does is to make them happen in a test.

Each fault below matches one kind of error from the driver anatomy
(``docs/design/driver-anatomy.md`` in the ZMART-microscopy repository), so a
test can check that the driver's error handling sorts it into the right kind
and does the right thing.

Use it through :attr:`MockScope.faults`::

    scope.faults.add("MoveStage", "busy")            # the next MoveStage is refused as busy
    scope.faults.add("GetStagePosition", "stale", times=3)
    scope.faults.add("*", "disconnect")              # the next command of any name

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

# Every fault the mock can produce, with the kind of error a driver should
# sort it into, and what happens.
FAULTS: dict[str, str] = {
    "busy": (
        "Temporary. The software answers error 100, 'System busy, try again later'. "
        "Nothing is applied. Trying again should work."
    ),
    "out_of_range": (
        "Bad request. The software answers error 201, 'Value out of range'. Nothing is applied."
    ),
    "hardware_fault": (
        "Permanent. The software answers error 300, 'Hardware fault: controller not "
        "responding'. Nothing is applied."
    ),
    "unknown_error": (
        "Not recognisable. The software answers error 999 with a message no driver knows. "
        "A driver should treat it as permanent."
    ),
    "timeout": (
        "Temporary, and tricky. The command IS applied, but the reply is lost and the call "
        "raises TimeoutError. A driver cannot know whether it worked, so it must read back."
    ),
    "ignore": (
        "Unconfirmed. The software answers 'OK' but does not apply the command. Only "
        "reading back reveals it."
    ),
    "stale": (
        "Unknown reading. A get command returns the answer it gave last time, not the "
        "current value."
    ),
    "disconnect": (
        "Connection lost. The software closes; this and every later call raises "
        "ConnectionError until MockScope.restart()."
    ),
}


class Faults:
    """The list of faults waiting to happen.

    Each fault is tied to a command name (or ``"*"`` for any command) and
    happens the next ``times`` times that command is sent. ``times=None``
    means every time, until :meth:`clear`.
    """

    def __init__(self) -> None:
        self._pending: list[dict] = []

    def add(self, command: str, fault: str, *, times: int | None = 1) -> None:
        """Make ``command`` fail with ``fault`` the next ``times`` times it is sent."""
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault!r}; choose one of {sorted(FAULTS)}")
        if times is not None and times < 1:
            raise ValueError("times must be at least 1, or None for every time")
        self._pending.append({"command": command, "fault": fault, "left": times})

    def clear(self) -> None:
        """Forget every fault still waiting."""
        self._pending.clear()

    def take(self, command: str) -> str | None:
        """The fault for this call of ``command``, if any, used up by one.

        Faults added first happen first.
        """
        for entry in self._pending:
            if entry["command"] in (command, "*"):
                if entry["left"] is not None:
                    entry["left"] -= 1
                    if entry["left"] == 0:
                        self._pending.remove(entry)
                return entry["fault"]
        return None

    def __len__(self) -> int:
        return len(self._pending)
