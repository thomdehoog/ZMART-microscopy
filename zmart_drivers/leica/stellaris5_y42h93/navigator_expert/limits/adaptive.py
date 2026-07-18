"""Driver-only adaptive XY limit capture for the limits notebook.

The operator places exactly four temporary Point markers in the active LAS X
Navigator Expert template. This module saves and parses that template through
the Leica driver, derives the inclusive XY bounding box, optionally strips the
temporary markers, and returns the recorded coordinates and limits as data.

No controller API is involved.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..motion.limits import STAGE_BACKSTOP_UM
from ..scanfields.files import (
    TEMPLATE_BASE,
    TEMPLATE_LRP,
    TEMPLATE_RGN,
    TEMPLATE_XML,
    find_scanning_templates_dir,
    save_experiment,
)
from ..scanfields.parsers import parse_scan_positions
from ..scanfields.strip_restore import strip_template_in_place


def _archive_saved_template(templates_dir: Path):
    """Copy the saved LAS X experiment trio before marker cleanup overwrites it."""
    archive = TemporaryDirectory(prefix="zmart_limits_template_")
    archive_dir = Path(archive.name)
    archived_paths: list[Path] = []
    try:
        for filename in (TEMPLATE_XML, TEMPLATE_RGN, TEMPLATE_LRP):
            source = templates_dir / filename
            if not source.is_file():
                raise RuntimeError(
                    f"LAS X saved an incomplete experiment; missing template file {source}"
                )
            destination = archive_dir / filename
            shutil.copy2(source, destination)
            archived_paths.append(destination)
    except BaseException:
        archive.cleanup()
        raise
    return archive, archived_paths


def boundary_points_from_template(
    parsed: Mapping[str, Any],
    *,
    expected_points: int = 4,
) -> list[dict[str, float]]:
    """Return exactly four temporary Point-marker centers from parsed scan data.

    Refuse templates containing scan fields, focus markers, or non-Point
    geometry so the later strip operation cannot silently remove real work.
    """
    geometries = parsed.get("geometries", {})
    non_points = [
        str(name)
        for name, geometry in geometries.items()
        if geometry.get("type") != "Point"
    ]
    tile_count = sum(
        len(region.get("positions", ()))
        for region in parsed.get("acquisition_positions", {}).values()
    )
    focus_count = len(parsed.get("focus_points", ())) + len(
        parsed.get("autofocus_points", ())
    )
    if non_points or tile_count or focus_count:
        raise RuntimeError(
            "Adaptive XY capture requires a clean template containing only "
            f"{expected_points} temporary Point markers; found "
            f"{len(non_points)} non-Point geometries, {tile_count} tiles, and "
            f"{focus_count} focus markers."
        )

    points: list[dict[str, float]] = []
    for name, geometry in geometries.items():
        if geometry.get("type") != "Point":
            continue
        center = geometry.get("center_um")
        if (
            not isinstance(center, Mapping)
            or "x_um" not in center
            or "y_um" not in center
        ):
            raise RuntimeError(f"Point marker {name!r} has no readable XY center")
        try:
            x_um = float(center["x_um"])
            y_um = float(center["y_um"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Point marker {name!r} has a non-numeric XY center") from exc
        if not (math.isfinite(x_um) and math.isfinite(y_um)):
            raise RuntimeError(f"Point marker {name!r} has a non-finite XY center")
        points.append({"x_um": x_um, "y_um": y_um})

    if len(points) != expected_points:
        raise RuntimeError(
            f"Adaptive XY capture requires exactly {expected_points} Point markers; "
            f"found {len(points)}."
        )
    return sorted(points, key=lambda point: (point["x_um"], point["y_um"]))


def xy_limits_from_points(
    points: Sequence[Mapping[str, float]],
    *,
    stage_envelope: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, dict[str, list[float]]]:
    """Compute inclusive XY ranges and verify them against the hard backstop."""
    if len(points) != 4:
        raise ValueError(f"exactly four points are required, got {len(points)}")
    xs = [float(point["x_um"]) for point in points]
    ys = [float(point["y_um"]) for point in points]
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        raise ValueError("point coordinates must be finite")

    x_range = [min(xs), max(xs)]
    y_range = [min(ys), max(ys)]
    if x_range[0] >= x_range[1] or y_range[0] >= y_range[1]:
        raise ValueError(
            f"four points must span a non-zero rectangle, got X={x_range}, Y={y_range}"
        )

    envelope = stage_envelope or STAGE_BACKSTOP_UM
    for axis, bounds in (("x", x_range), ("y", y_range)):
        envelope_min, envelope_max = map(float, envelope[axis])
        if bounds[0] < envelope_min or bounds[1] > envelope_max:
            raise RuntimeError(
                f"adaptive {axis.upper()} range {bounds} lies outside the maximum "
                f"stage envelope [{envelope_min}, {envelope_max}]"
            )
    return {
        "x_um": {"range": x_range},
        "y_um": {"range": y_range},
    }


def capture_adaptive_xy_limits(
    client: Any,
    *,
    remove_markers: bool = True,
    save_timeout: float = 60,
) -> dict[str, Any]:
    """Read four live LAS X Point markers and optionally remove them afterward.

    All reads and mutations use the Leica navigator_expert driver. Markers are
    stripped only after the saved template has been validated as containing
    exactly four Points and no other scan-field or focus content.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        raise RuntimeError("LAS X ScanningTemplates directory was not found")

    saved = save_experiment(
        client,
        TEMPLATE_XML,
        templates_dir,
        timeout=save_timeout,
        confirm_path=templates_dir / TEMPLATE_RGN,
    )
    if saved is None:
        raise RuntimeError("LAS X did not save the active template; no points were read")

    parsed = parse_scan_positions(templates_dir, TEMPLATE_BASE, client=client)
    points = boundary_points_from_template(parsed)
    limits = xy_limits_from_points(points)
    template_archive, template_paths = _archive_saved_template(Path(templates_dir))

    markers_removed = False
    if remove_markers:
        stripped = strip_template_in_place(client, save_timeout=save_timeout)
        if stripped is None:
            raise RuntimeError(
                "The four points were read, but the driver could not remove them "
                "from the LAS X template"
            )
        markers_removed = True

    return {
        "points_um": points,
        "limits": limits,
        "markers_removed": markers_removed,
        "template_paths": [str(path) for path in template_paths],
        # Retain the temporary directory until the notebook publishes the files.
        "_template_archive": template_archive,
    }
