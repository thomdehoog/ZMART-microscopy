"""The get dispatcher: one honest reading at a time.

Every reading in the driver passes through :meth:`GetDispatcher.read`. It
does four things, the same for every microscope:

1. **One read at a time.** Reads wait their turn, so a busy microscope is
   never flooded with questions. The turn is taken per read, never around a
   whole confirmation: the Leica driver learned that holding it longer
   blocks the confirmation's own reads.
2. **Try again after a temporary problem**, such as "system busy", a few
   times with a short pause.
3. **Keep to a time limit.** A reading that cannot be had in time is
   reported as unknown, rather than holding everything up.
4. **Answer honestly.** The result is a :class:`Reading`: the value, when it
   was observed and where it came from, or "unknown" with the reason.

Anything that is not temporary (a bad request, a hardware fault, a lost
connection) is raised straight away, following the error rules.

The get dispatcher retries the *read* only. It never sends anything that
could change the microscope.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..error_handling import RULES, Action, Kind


@dataclass(frozen=True)
class GetTuning:
    """How patient the get dispatcher is. Set by the driver author, not the operator.

    ``time_limit_s`` must stay well inside the set dispatcher's confirmation
    window, so that a confirmation always gets its answer in time.
    """

    max_retries: int = 2
    retry_pause_s: float = 0.02
    time_limit_s: float = 0.5
    wait_for_turn_s: float = 2.0


DEFAULT_GET_TUNING = GetTuning()


@dataclass(frozen=True)
class Reading:
    """One answer from the microscope.

    ``value`` is what was read, ``observed_at`` when (in seconds on the
    driver's clock), and ``source`` where from. When the value could not be
    read with confidence, ``value`` is ``None`` and ``reason`` says why.
    """

    value: Any
    observed_at: float | None
    source: str
    reason: str | None = None

    @property
    def known(self) -> bool:
        """True when the value could be read."""
        return self.reason is None

    def value_or_raise(self, what: str) -> Any:
        """The value, or ``RuntimeError`` saying why ``what`` could not be read."""
        if not self.known:
            raise RuntimeError(f"could not read {what}: {self.reason}")
        return self.value


class GetDispatcher:
    """The engine behind every get command of one connected microscope.

    ``classify`` sorts errors into kinds; ``record(level, message)`` adds a
    line to the command log. ``clock`` and ``sleep`` are normally the real
    ones, and can be replaced in tests.
    """

    def __init__(
        self,
        *,
        classify: Callable[[BaseException], Kind],
        record: Callable[[str, str], None],
        tuning: GetTuning = DEFAULT_GET_TUNING,
        source: str = "api",
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._classify = classify
        self._record = record
        self._tuning = tuning
        self._source = source
        self._clock = clock
        self._sleep = sleep
        self._turn = threading.RLock()

    def read(self, label: str, primitive: Callable[[], Any]) -> Reading:
        """Run ``primitive`` (a vendor-interface function) and return a :class:`Reading`."""
        tuning = self._tuning
        if not self._turn.acquire(timeout=tuning.wait_for_turn_s):
            return self._unknown(label, "another read kept the microscope busy for too long")
        try:
            deadline = self._clock() + tuning.time_limit_s
            tries = 0
            while True:
                try:
                    value = primitive()
                    return Reading(value, self._clock(), self._source)
                except Exception as error:
                    kind = self._classify(error)
                    rule = RULES[kind]
                    if rule.get is not Action.RETRY:
                        raise rule.error(f"reading {label} failed: {error}") from error
                    tries += 1
                    pause = tuning.retry_pause_s
                    if tries > tuning.max_retries or self._clock() + pause > deadline:
                        return self._unknown(label, f"{kind.value} problem: {error}")
                    self._record("debug", f"reading {label}: {error}; trying again")
                    self._sleep(pause)
        finally:
            self._turn.release()

    def _unknown(self, label: str, reason: str) -> Reading:
        self._record("warning", f"reading {label} is unknown: {reason}")
        return Reading(None, None, self._source, reason)
