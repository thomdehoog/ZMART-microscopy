"""A one-glance checklist of where the run stands — shared by both editions.

The notebooks spread their state across many cell outputs; halfway through
a session it is easy to lose track of which step is done. This module
inspects the notebook's own variables (pass it ``globals()``) and answers
with a row per step: done, still to do, or worth a second look. It never
talks to the microscope — everything comes from what the cells already
created — so refreshing it is always safe.

``run_status_rows`` is the pure data function; :func:`print_run_status`
renders it as text for the matplotlib notebook, and the React edition
wraps the same rows in a live widget (``wreact.run_status``).
"""

from __future__ import annotations

from typing import Any

OK = "ok"
TODO = "todo"
WARN = "warn"


def _row(label: str, state: str, detail: str) -> dict:
    return {"label": label, "state": state, "detail": detail}


def run_status_rows(ns: dict[str, Any]) -> list[dict]:
    """Build the checklist rows from a notebook namespace (``globals()``).

    Each row is ``{"label", "state", "detail"}`` with ``state`` one of
    ``"ok"`` / ``"todo"`` / ``"warn"``. Only things the cells actually
    created are inspected; nothing here touches hardware.
    """
    rows: list[dict] = []

    session = ns.get("zmart_controller")
    if session is None:
        rows.append(_row("Microscope", TODO, "not connected — run the setup cell"))
    elif getattr(session, "closed", None) is True or getattr(session, "disconnected", False):
        rows.append(_row("Microscope", WARN, "session is disconnected — re-run setup"))
    elif getattr(session, "closed", None) is False:
        rows.append(_row("Microscope", OK, "connected (last known; no live probe)"))
    else:
        rows.append(
            _row("Microscope", WARN, "session object present; connection health is unknown")
        )
    engine = ns.get("engine")
    if engine is None:
        rows.append(_row("Analysis engine", TODO, "not loaded — run the setup cell"))
    elif any(
        getattr(engine, name, False) is True
        for name in ("shut_down", "closed", "_closed", "_shutdown_done")
    ):
        rows.append(_row("Analysis engine", WARN, "engine is shut down — re-run setup"))
    else:
        rows.append(
            _row(
                "Analysis engine",
                OK,
                "loaded; setup preflight passed (worker liveness not probed)",
            )
        )
    root = ns.get("ROOT")
    rows.append(
        _row("Run folder", OK, str(root))
        if root is not None
        else _row("Run folder", TODO, "unknown until setup runs")
    )

    overview_state = ns.get("overview_state")
    if overview_state is None:
        rows.append(_row("Overview job", TODO, "capture it in step 3a"))
    else:
        limits = (overview_state.get("observed") or {}).get("limits") or {}
        job = (overview_state.get("changeable") or {}).get("job")
        if limits.get("source") == "machine" and not limits.get("is_fallback"):
            rows.append(_row("Overview job", OK, f"{job!r}, measured stage limits active"))
        else:
            rows.append(
                _row(
                    "Overview job",
                    WARN,
                    f"{job!r}, but the limits are not this machine's measured "
                    f"envelope ({limits.get('source')!r})",
                )
            )
    target_state = ns.get("target_state")
    if target_state is None:
        rows.append(_row("Target job", TODO, "capture it in step 3b"))
    else:
        t_job = (target_state.get("changeable") or {}).get("job")
        o_job = ((overview_state or {}).get("changeable") or {}).get("job")
        if o_job is not None and t_job == o_job:
            rows.append(_row("Target job", WARN, f"same job as the overview ({t_job!r})"))
        else:
            rows.append(_row("Target job", OK, f"{t_job!r}"))

    positions = ns.get("positions")
    rows.append(
        _row("Positions", OK, f"{len(positions)} scan-field position(s)")
        if positions
        else _row("Positions", TODO, "ask the microscope in step 4")
    )

    focus = ns.get("focus")
    if focus is None:
        rows.append(_row("Focus surface", TODO, "pick and measure points in step 5"))
    else:
        n = len(getattr(focus, "measured", []) or [])
        rows.append(_row("Focus surface", OK, f"{getattr(focus, 'model', '?')} fit, {n} point(s)"))

    records = ns.get("overview_records")
    rows.append(
        _row("Overview scan", OK, f"{len(records)} tile(s) acquired")
        if records
        else _row("Overview scan", TODO, "acquire in step 6")
    )
    targets = ns.get("targets")
    rows.append(
        _row("Targets", OK, f"{len(targets)} discovered")
        if targets
        else _row("Targets", TODO, "discover in step 7")
    )

    gallery = ns.get("gallery")
    acquired = list(getattr(gallery, "records", []) or [])
    rows.append(
        _row("Target images", OK, f"{len(acquired)} acquired and committed")
        if acquired
        else _row("Target images", TODO, "acquire in step 8")
    )
    return rows


def print_run_status(ns: dict[str, Any]) -> None:
    """Print the checklist as plain text (the matplotlib notebook's view)."""
    marks = {OK: "[done]", TODO: "[    ]", WARN: "[look]"}
    for row in run_status_rows(ns):
        print(f"{marks[row['state']]} {row['label']}: {row['detail']}")
