"""Target discovery: segment overviews via the analysis engine -> frame targets.

Reuses the existing cellpose analysis engine (``submit`` / ``status`` / ``results``)
for segmentation -- no reinvented segmentation. Each detected cell's pixel centroid
is converted to a frame ``(x, y)`` target here via ``overview_pixel_to_frame`` (no
calibration, no ``navigator_expert`` import); the engine is used only to find cells.
"""

from __future__ import annotations

import time
from typing import Any

from ._geom import overview_pixel_to_frame


def _identity_image_to_stage(pixel_size_um: float) -> list[list[float]]:
    """A 2x2 pixel->um matrix with no rotation/flip (isotropic pixel size)."""
    size = float(pixel_size_um)
    return [[size, 0.0], [0.0, size]]


def discover_targets(
    engine: Any,
    overviews: list[dict],
    *,
    feature: str = "area",
    n_picks: int | None = None,
    queue: str = "overview",
    poll_interval: float = 0.05,
) -> list[dict]:
    """Segment each overview via *engine*; return target frame positions.

    Each overview dict provides ``image_path``, ``center_frame_um`` (x, y um -- the
    frame position the overview was captured at), ``pixel_size_um``, and
    ``image_size_px`` (H, W). Submits every overview, drains the engine to
    completion, and returns ``[{"x", "y", "source": {...}}]`` frame targets.
    """
    for index, overview in enumerate(overviews):
        engine.submit(
            queue,
            {
                "image_path": str(overview["image_path"]),
                "naming_p": index,
                "tile_id": overview.get("label", index),
                "tile_stage_xy_um": tuple(overview["center_frame_um"]),
                "tile_zwide_um": 0.0,
                "source_pixel_size_um": float(overview["pixel_size_um"]),
                "source_image_size_px": tuple(overview["image_size_px"]),
                "image_to_stage": _identity_image_to_stage(overview["pixel_size_um"]),
                "n_picks": n_picks,
                "feature": feature,
            },
        )

    by_index = dict(enumerate(overviews))
    targets: list[dict] = []
    while True:
        status = engine.status(queue)
        for result in engine.results(queue):
            overview = by_index[result["input"]["naming_p"]]
            for pick in result.get("pick_targets", {}).get("picks", []):
                x_um, y_um = overview_pixel_to_frame(
                    centroid_col_row_px=tuple(pick["centroid_col_row_px"]),
                    image_shape_px=tuple(overview["image_size_px"]),
                    pixel_size_um=float(overview["pixel_size_um"]),
                    image_center_frame_um=tuple(overview["center_frame_um"]),
                )
                targets.append(
                    {
                        "x": x_um,
                        "y": y_um,
                        "source": {
                            "naming_p": result["input"]["naming_p"],
                            "centroid_col_row_px": tuple(pick["centroid_col_row_px"]),
                            "area_px": pick.get("area_px"),
                            "mean_intensity": pick.get("mean_intensity"),
                        },
                    }
                )
        if status["pending"] == 0 and status["running"] == 0:
            break
        time.sleep(poll_interval)
    return targets
