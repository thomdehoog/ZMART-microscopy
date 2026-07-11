"""React-based versions of the v4 review widgets (for ``zmart_microscopy_v4_react.ipynb``).

Every widget here is the same workflow step as its matplotlib sibling in
``workflow/`` — same data, same gating semantics, same hardware paths, and
the image mathematics is literally shared code — but the front end is a
React app rendered inside the notebook cell via `anywidget
<https://anywidget.dev>`_. The apps update in real time as data arrives
(Python pushes each fresh tile / focus point / image pair the moment it
exists) and talk back to the kernel: clicking **Acquire** in the browser is
a message to Python, which then drives the microscope through the exact
same gated controller calls the scripts use.

The only requirement beyond the matplotlib notebook is the ``anywidget``
package in the kernel environment. React itself is **vendored** — the
official MIT-licensed production builds ship inside this package
(``vendor/``) and load into a private scope in the browser — so the React
notebook works fully offline and fetches nothing from any CDN.

Use :func:`view_overview`, :func:`pick_focus_points`,
:func:`explore_targets`, and :func:`acquire_gallery` exactly like their
``workflow.*`` namesakes; :func:`run_status` is the run's one-glance
checklist and :func:`calibration_report` renders the calibration check's
result in plain language. The traits and messages each widget speaks are
documented in ``PROTOCOL.md`` next to this file — that protocol is the
seam to build a future non-notebook front end (a website) against.
"""

from __future__ import annotations

from typing import Any

from ._widgets import (
    AcquisitionGalleryReact,
    CalibrationReportReact,
    FocusPickerReact,
    OverviewViewerReact,
    RunStatusReact,
    TargetExplorerReact,
)

__all__ = [
    "view_overview",
    "pick_focus_points",
    "explore_targets",
    "acquire_gallery",
    "run_status",
    "calibration_report",
    "OverviewViewerReact",
    "FocusPickerReact",
    "TargetExplorerReact",
    "AcquisitionGalleryReact",
    "RunStatusReact",
    "CalibrationReportReact",
]


def view_overview(
    overviews: list[dict] | None = None,
    *,
    downsample: int | None = None,
    palette: str = "default",
) -> OverviewViewerReact:
    """The zoomable overview mosaic as a React app; see :class:`OverviewViewerReact`.

    ``downsample=None`` (the default) keeps each tile's display copy under a
    fixed pixel budget automatically; pass an integer to pin the step.
    ``palette="colorblind"`` starts the channels on colour-vision-friendly
    hues (after Okabe & Ito) instead of the classic microscopy colours.
    """
    return OverviewViewerReact(overviews, downsample=downsample, palette=palette)


def pick_focus_points(
    session: Any,
    positions: list[dict] | None = None,
    *,
    af_job: str | None = None,
    start_z: float | None = None,
    seed: bool = True,
) -> FocusPickerReact:
    """The focus-point picker as a React app; see :class:`FocusPickerReact`."""
    return FocusPickerReact(
        session, positions, af_job=af_job, start_z=start_z, seed=seed
    )


def explore_targets(
    targets: list[dict],
    overviews: list[dict] | None = None,
    *,
    crop_um: float = 60.0,
) -> TargetExplorerReact:
    """The target explorer as a React app; see :class:`TargetExplorerReact`."""
    return TargetExplorerReact(targets, overviews, crop_um=crop_um)


def acquire_gallery(
    session: Any,
    source: Any,
    overviews: list[dict] | None = None,
    *,
    state: dict | None = None,
    focus: Any = None,
    options: dict | None = None,
    after_acquire: Any = None,
    default_count: int = 5,
    seed: int | None = None,
) -> AcquisitionGalleryReact:
    """The acquire-and-review gallery as a React app; see :class:`AcquisitionGalleryReact`."""
    return AcquisitionGalleryReact(
        session,
        source,
        overviews,
        state=state,
        focus=focus,
        options=options,
        after_acquire=after_acquire,
        default_count=default_count,
        seed=seed,
    )


def run_status(ns: dict | None = None) -> RunStatusReact:
    """A one-glance checklist of the run; see :class:`RunStatusReact`.

    Pass the notebook's ``globals()`` (or call ``refresh(globals())`` later,
    after any step) — the widget inspects what the cells already created
    and never talks to the microscope.
    """
    status = RunStatusReact()
    if ns is not None:
        status.refresh(ns)
    return status


def calibration_report(
    report: dict | None = None, *, acceptable_um: float | None = None
) -> CalibrationReportReact:
    """The calibration check's report as a readable panel.

    ``report`` is the dict from ``finish_calibration_check``. With
    ``acceptable_um`` set, the panel states outright whether the measured
    systematic error is within what this run can tolerate (a cell radius
    is a good yardstick).
    """
    return CalibrationReportReact(report, acceptable_um=acceptable_um)
