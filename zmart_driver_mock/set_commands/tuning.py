"""How patient the set dispatcher is, per command.

These numbers belong to the driver author, not to the operator: they
describe how this microscope behaves, not what an experiment may do. That is
why they live here, next to the dispatcher, and not in the configuration.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SetTuning:
    """The patience of the set dispatcher for one command.

    ``max_retries``: how often to send again after a temporary problem.
    ``retry_pause_s``: the first pause before that; it doubles each time.
    ``max_confirm_attempts``: how many confirmation windows to allow.
    ``confirm_window_s``: how long to keep reading back in one window.
    ``poll_interval_s``: the pause between two readbacks.
    ``send_again_if_unconfirmed``: whether to send the command again after
    a window ends without confirmation. True for moves and settings, which
    are safe to repeat. False for acquisitions, where repeating would take a
    second image.
    ``ready_timeout_s``: how long to wait for the microscope to be ready
    before sending.
    """

    max_retries: int = 2
    retry_pause_s: float = 0.05
    max_confirm_attempts: int = 3
    confirm_window_s: float = 1.0
    poll_interval_s: float = 0.01
    send_again_if_unconfirmed: bool = True
    ready_timeout_s: float = 10.0


DEFAULT_SET_TUNING = SetTuning()

# Changing the objective takes a fraction of a second on the mock.
OBJECTIVE_TUNING = replace(DEFAULT_SET_TUNING, confirm_window_s=3.0)

# An acquisition can take a while, and must never be sent twice by itself.
ACQUIRE_TUNING = replace(
    DEFAULT_SET_TUNING,
    confirm_window_s=60.0,
    max_confirm_attempts=1,
    send_again_if_unconfirmed=False,
)
