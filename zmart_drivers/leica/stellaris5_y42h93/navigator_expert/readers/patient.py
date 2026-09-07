"""A reading, answered or raised: the door for a caller that must have the value.

The routed readers are bounded on purpose. A CAM call that hangs behind a
dialog parks in a capped worker and the reader answers ``None`` within its
own window, so no poll loop above it ever blocks for good. That bound is
right for the confirmations, which poll a reader on a clock of their own.
It is wrong for a caller that must have the value -- the controller adapter
answering "where is the stage", the objective compensation identifying the
lens on both sides of a change -- because LAS X returns empty answers for
seconds at a time while it prints an export or swaps a job, and one empty
answer used to be that caller's failure: the page's mark went blank over a
stage standing still, the focus map declared two healthy points dead, and a
job switch was refused over a lens the instrument had not named yet.

Such a caller asks here instead. The reader is asked again until it answers,
and only past :data:`PATIENCE_S` is the silence reported, in one sentence
whatever the datum was.
"""

from __future__ import annotations

import time
from typing import Any, Callable

#: How long a reading is asked again before the instrument is declared
#: silent. LAS X takes orders but returns empty answers while it prints an
#: export, and a CAM call hangs while a dialog is up; both pass in seconds.
PATIENCE_S = 30.0


def answered(read: Callable[[], Any], what: str) -> Any:
    """Ask *read* until it answers; raise once the instrument has stayed silent.

    A reader answers ``None`` when the instrument gave nothing within its own
    bound, and raises when the call itself failed; neither is the reading's
    failure, and both are asked again. What comes back is never ``None``.
    """
    deadline = time.monotonic() + PATIENCE_S
    while True:
        try:
            answer = read()
        except Exception as why:  # noqa: BLE001 -- silence is the condition waited out
            answer, last = None, why
        else:
            last = None
        if answer is not None:
            return answer
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"could not read {what}: the instrument answered nothing for "
                f"{PATIENCE_S:.0f}s" + (f" (last: {last})" if last is not None else "")
            )
        time.sleep(0.1)
