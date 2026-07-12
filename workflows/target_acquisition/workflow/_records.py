"""Validate the acquisition-record image manifest used by the workflow."""

from __future__ import annotations

from typing import Any


def record_channel_paths(
    record: dict,
    *,
    context: str,
    allow_empty: bool = False,
) -> list[Any]:
    """Return one 2-D image path per channel from a driver record.

    The current target workflow supports one timepoint and one z plane. Drivers
    can still return several channels, but must identify their ``t``/``z``/``c``
    coordinates in ``record["planes"]`` so the workflow never mistakes a z
    stack or time series for channels.

    A legacy single-path ``images`` record remains valid because that path may
    itself hold a C-first/C-last channel stack. Multiple unindexed paths are
    rejected rather than interpreted by filename order.

    Some drivers report ``planes`` as a plain count (how many z planes were
    captured) rather than a manifest — the mesoSPIM adapter does this. A count
    carries no per-file coordinates, so it cannot serve as a manifest; the
    saved paths (``images`` or ``image_files``) are used instead, and a count
    above one is refused just like an unindexed multi-path record.
    """
    planes = record.get("planes")
    if isinstance(planes, (list, tuple)) and planes:
        normalized = []
        for plane in planes:
            try:
                item = (
                    int(plane["t"]),
                    int(plane["z"]),
                    int(plane["c"]),
                    plane["path"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"{context} has an invalid plane manifest entry: {plane!r}"
                ) from exc
            normalized.append(item)

        timepoints = {item[0] for item in normalized}
        z_planes = {item[1] for item in normalized}
        if len(timepoints) != 1 or len(z_planes) != 1:
            raise RuntimeError(
                f"{context} produced {len(timepoints)} timepoint(s) and "
                f"{len(z_planes)} z plane(s); the target-acquisition workflow "
                "requires a 2-D job (one timepoint and one z plane)"
            )
        channels = [item[2] for item in normalized]
        if len(channels) != len(set(channels)):
            raise RuntimeError(f"{context} contains duplicate channel indices: {channels}")
        return [item[3] for item in sorted(normalized)]

    if isinstance(planes, int) and not isinstance(planes, bool) and planes > 1:
        raise RuntimeError(
            f"{context} reports {planes} z planes without a plane manifest; "
            "the target-acquisition workflow requires a 2-D job "
            "(one timepoint and one z plane)"
        )

    images = list(record.get("images") or record.get("image_files") or ())
    if len(images) == 1:
        return images
    if not images and allow_empty:
        return []
    if not images:
        raise ValueError(f"{context} has no saved image path")
    raise RuntimeError(
        f"{context} returned {len(images)} image paths without plane indices; "
        "the driver must include a 'planes' manifest so channels cannot be "
        "confused with z planes or timepoints"
    )
