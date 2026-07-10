"""Retired driver-coupled pipeline (preserved, not on the active path).

These modules are the pre-controller operator flow: they drove the Leica
directly via ``import navigator_expert as drv`` (``drv.acquire`` /
``drv.save`` / ``drv.get_job_settings`` / ``drv.parse_tile_geometry`` /
``drv.move_*``). The active pipeline now goes through the
``zmart_controller`` Session surface only (see ``pipeline.steps`` /
``pipeline.discovery`` / ``pipeline._capture_run``).

Kept for reference and reuse of proven logic (selection thresholds, NPZ
schema v2, live visualization, summary schema). Import submodules
explicitly, e.g. ``from pipeline.retired.selection import select_targets``;
this package intentionally does not eagerly import its submodules, several
of which pull in ``navigator_expert``. Kept driver-free helpers still live
in the parent package and are imported from there (``..``).

Note (2026-07): some of these modules reference driver exports that were
removed in the config-loading cleanup (``write_stage_limits_config``,
``current_stage_limits_path``, most ``LIMITS_SOURCE_*`` names). They run
only against older driver checkouts; the retired test suite is not
collected by CI, and running it against the current driver raises
``AttributeError`` on those names.
"""
