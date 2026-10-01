"""The set dispatcher: change the microscope, then make sure it happened.

Every set command runs through :meth:`SetDispatcher.run`, in the same steps
for every microscope:

1. **Limits gate.** A request outside the limits is refused with
   ``ValueError`` before anything is sent.
2. **Ready.** Wait, within a time limit, until the microscope is ready, for
   example not in the middle of an acquisition.
3. **Send** the command through its primitive.
4. **Error check.** A temporary problem is sent again after a pause, a few
   times. Anything else follows the error rules and is raised. A lost reply
   is special: the command may already have happened, so the dispatcher
   reads back instead of sending again blindly.
5. **Confirm.** Read back through the get dispatcher, again and again within
   a time window, until the target is reached.
6. **Send again** if a window ends without confirmation, when that is safe.
7. **Give up softly.** If the change is still not confirmed, the outcome
   says so, and the caller decides what that means for the experiment.

Commands are assumed to come from one caller at a time.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..error_handling import RULES, Action, Kind
from .gate import Gate
from .tuning import DEFAULT_SET_TUNING, SetTuning

# Marks a send whose reply was lost: the command may or may not have happened.
REPLY_LOST = object()


class NeverConfirmed(Exception):
    """Raised by a confirmation that can already see the target will never be reached.

    For example, the microscope is idle and no acquisition of ours is
    running. The dispatcher then stops waiting at once instead of using up
    the whole confirmation window.
    """


@dataclass
class SetCommand:
    """One set command, ready to run.

    ``name`` is for messages. ``send`` calls the primitive and returns its
    result. ``confirm(result)`` reads back and returns True once the target
    is reached, or raises :class:`NeverConfirmed` when it can see it never
    will be; ``result`` is ``None`` when the reply was lost. ``limits`` is
    ``(key, values)`` for the gate; ``None`` is allowed only for commands
    that cannot make anything less safe, such as stopping. ``ready``, when
    given, returns True once the microscope can take the command.
    """

    name: str
    send: Callable[[], Any]
    confirm: Callable[[Any], bool]
    limits: tuple[str, dict[str, Any]] | None
    ready: Callable[[], bool] | None = None
    tuning: SetTuning = DEFAULT_SET_TUNING


@dataclass
class Outcome:
    """What happened to one set command.

    ``confirmed`` says whether the readback showed the target. ``result`` is
    what the send returned (such as a file name). ``sends`` and
    ``confirm_windows`` count the work it took. ``reason`` explains an
    unconfirmed outcome.
    """

    confirmed: bool
    result: Any
    sends: int
    confirm_windows: int
    reason: str | None = None


class SetDispatcher:
    """The engine behind every set command of one connected microscope."""

    def __init__(
        self,
        *,
        gate: Gate,
        classify: Callable[[BaseException], Kind],
        record: Callable[[str, str], None],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._gate = gate
        self._classify = classify
        self._record = record
        self._clock = clock
        self._sleep = sleep

    def run(self, command: SetCommand) -> Outcome:
        """Run ``command`` through every step. See the module description."""
        if command.limits is not None:
            refusal = self._gate.check(*command.limits)
            if refusal is not None:
                self._record("warning", f"{command.name} refused by the limits: {refusal}")
                raise ValueError(f"{command.name} refused: {refusal}")
        if command.ready is not None:
            self._wait_until_ready(command)
        tuning = command.tuning
        sends = 0
        result: Any = None
        reason = "the microscope accepted the command, but the readback never showed the target"
        for window in range(1, tuning.max_confirm_attempts + 1):
            if window == 1 or tuning.send_again_if_unconfirmed:
                result = self._send(command)
                sends += 1
            confirm_with = None if result is REPLY_LOST else result
            try:
                confirmed = self._confirm(command, confirm_with)
            except NeverConfirmed as never:
                self._record("warning", f"{command.name} will not be confirmed: {never}")
                reason = str(never)
                if tuning.send_again_if_unconfirmed:
                    continue
                return Outcome(False, confirm_with, sends, window, str(never))
            if confirmed:
                self._record("info", f"{command.name} confirmed")
                return Outcome(True, confirm_with, sends, window)
            self._record(
                "warning",
                f"{command.name} not confirmed within {tuning.confirm_window_s} s "
                f"(window {window} of {tuning.max_confirm_attempts})",
            )
        return Outcome(
            False,
            None if result is REPLY_LOST else result,
            sends,
            tuning.max_confirm_attempts,
            reason,
        )

    def _wait_until_ready(self, command: SetCommand) -> None:
        deadline = self._clock() + command.tuning.ready_timeout_s
        while not command.ready():
            if self._clock() >= deadline:
                raise RuntimeError(
                    f"{command.name}: the microscope stayed busy for "
                    f"{command.tuning.ready_timeout_s} s, so the command was not sent"
                )
            self._sleep(command.tuning.poll_interval_s)

    def _send(self, command: SetCommand) -> Any:
        tuning = command.tuning
        tries = 0
        while True:
            try:
                return command.send()
            except Exception as error:
                kind = self._classify(error)
                rule = RULES[kind]
                if isinstance(error, TimeoutError) and kind is Kind.TEMPORARY:
                    self._record("warning", f"{command.name}: reply lost; reading back to find out")
                    return REPLY_LOST
                if rule.set is Action.RETRY and tries < tuning.max_retries:
                    pause = tuning.retry_pause_s * 2**tries
                    tries += 1
                    self._record("info", f"{command.name}: {error}; sending again in {pause} s")
                    self._sleep(pause)
                    continue
                if rule.set is Action.RETRY:
                    raise RuntimeError(
                        f"{command.name} failed {tries + 1} times; last answer: {error}"
                    ) from error
                self._record("error", f"{command.name}: {kind.value}: {error}")
                raise rule.error(f"{command.name}: {error}") from error

    def _confirm(self, command: SetCommand, result: Any) -> bool:
        tuning = command.tuning
        deadline = self._clock() + tuning.confirm_window_s
        while True:
            if command.confirm(result):
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(tuning.poll_interval_s)
