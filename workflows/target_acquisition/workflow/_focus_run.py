"""Measure focus at operator-chosen points -- controller surface only.

Step 4: the workflow decides WHERE to focus (its own logic); this moves to each
frame (x, y) point and runs the driver's ``autofocus`` procedure, collecting the
frame-z the driver reports. Feed the result to
:func:`_focus_surface.fit_focus_surface`.
"""

from __future__ import annotations

from typing import Any


def measure_focus(
    session: Any,
    points: list[dict],
    *,
    af_job: str | None = None,
    start_z: float | None = None,
    on_point: Any = None,
    cancel: Any = None,
) -> list[dict]:
    """Autofocus at each frame ``(x, y)`` point; return ``[{"x_um","y_um","z_um"}]``.

    ``points`` are frame micrometres, each a dict with ``x``/``y``. ``start_z`` is
    the z to move to before each autofocus (default: the current z). ``af_job``
    names the autofocus job (omit when the instrument has exactly one). ``z_um`` is
    the driver's reported frame focus (``frame_z_um``, falling back to ``focus_um``).

    ``on_point(measurement)`` fires after each point's autofocus completes —
    the focus widgets use it to show every measured z (and grow the fitted
    map) while the stage is still working through the remaining points.

    ``cancel`` (optional) is asked before every move; answering True raises
    :class:`~._capture_run.RunCancelled` cleanly between two points, exactly
    like the capture loop.
    """
    from ._capture_run import RunCancelled

    if start_z is None:
        start_z = float(session.get_xyz()["z"]["value"])
    measured = []
    for index, point in enumerate(points, start=1):
        if cancel is not None and cancel():
            raise RunCancelled(
                f"the focus run was cancelled before point {index} of "
                f"{len(points)}: {index - 1} point(s) measured, and no further "
                "stage move was made."
            )
        session.set_xyz(point["x"], point["y"], start_z)
        procedure = {"name": "autofocus"}
        if af_job is not None:
            procedure["job"] = af_job
        result = session.run_procedure(procedure)
        z = result.get("frame_z_um", result.get("focus_um"))
        if z is None:
            job_note = f" (job {af_job!r})" if af_job is not None else ""
            raise RuntimeError(
                f"autofocus at point {index} of {len(points)}{job_note} reported no "
                "focus z (neither 'frame_z_um' nor 'focus_um'); the driver's autofocus "
                "may have failed here — check that this point is on the sample."
            )
        measurement = {"x_um": point["x"], "y_um": point["y"], "z_um": float(z)}
        measured.append(measurement)
        if on_point is not None:
            on_point(measurement)
    return measured
