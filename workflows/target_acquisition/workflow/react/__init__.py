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

Requirements beyond the matplotlib notebook: the ``anywidget`` package in
the kernel environment, and internet access **in the browser** the first
time a widget renders (React itself loads from the esm.sh CDN).

Use :func:`view_overview`, :func:`pick_focus_points`,
:func:`explore_targets`, and :func:`acquire_gallery` exactly like their
``workflow.*`` namesakes.
"""

from __future__ import annotations

from typing import Any

from ._widgets import (
    AcquisitionGalleryReact,
    FocusPickerReact,
    OverviewViewerReact,
    TargetExplorerReact,
)

__all__ = [
    "view_overview",
    "pick_focus_points",
    "explore_targets",
    "acquire_gallery",
    "OverviewViewerReact",
    "FocusPickerReact",
    "TargetExplorerReact",
    "AcquisitionGalleryReact",
]


def view_overview(
    overviews: list[dict] | None = None, *, downsample: int | None = None
) -> OverviewViewerReact:
    """The zoomable overview mosaic as a React app; see :class:`OverviewViewerReact`.

    ``downsample=None`` (the default) keeps each tile's display copy under a
    fixed pixel budget automatically; pass an integer to pin the step.
    """
    return OverviewViewerReact(overviews, downsample=downsample)


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
