"""Finding the vendor's file and waiting until it is complete.

MockScope Control, like most vendor software, writes a file in steps: the
description first, the pixels when the acquisition is done. Reading too
early gives half a file. So data handling waits until the software reports
the acquisition as done *and* the file reads back complete.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import time
from typing import Any

from .. import get_commands as get

POLL_INTERVAL_S = 0.01


def wait_for_file(ctx, file: str, *, timeout_s: float = 30.0) -> tuple[dict[str, Any], list]:
    """Wait until the vendor's ``file`` is complete and return ``(description, planes)``.

    Raises ``RuntimeError`` when the acquisition was stopped, or when the
    file is still incomplete after ``timeout_s`` seconds. Both are permanent:
    waiting longer would not help.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        status = get.status(ctx)
        if status.known and status.value["last_acquisition"] is not None:
            last = status.value["last_acquisition"]
            if last["file"] == file and last["state"] == "aborted":
                raise RuntimeError(
                    f"the acquisition writing {file} was stopped; the file is incomplete"
                )
            if last["file"] == file and last["state"] == "done":
                try:
                    return ctx.vendor.read_image_file(file)
                except ValueError:
                    pass  # reported done but not fully on disk yet: wait a little longer
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{file} was still incomplete after {timeout_s} s")
        time.sleep(POLL_INTERVAL_S)
