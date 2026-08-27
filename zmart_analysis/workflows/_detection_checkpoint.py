"""Shared object-detection checkpoint helpers.

The checkpoint boundary is the contract between expensive segmentation and
re-runnable feature extraction. Keep the segmentation identity here so the
writer, loader, notebook helpers, and tests cannot drift.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
from pathlib import Path

from _contracts import to_builtin


SEGMENTATION_IDENTITY_KEYS = (
    "channels",
    "channel_axis",
    "cellprob_threshold",
    "flow_threshold",
    "niter",
    "diameter",
    "segmentation_binning",
)


def segmentation_params(inp: dict, params: dict) -> dict:
    """Return params that define mask generation, excluding runtime details."""
    return {
        "channels": inp.get("channels", params.get("channels", None)),
        "channel_axis": _channel_axis(
            inp.get("channel_axis", params.get("channel_axis", None))
        ),
        # From the submission when it names one, else the pipeline's default.
        # That is what lets an operator tune detection on a single position
        # and see the answer without re-registering a pipeline.
        "cellprob_threshold": _setting(inp, params, "cellprob_threshold"),
        "flow_threshold": _setting(inp, params, "flow_threshold"),
        "niter": _setting(inp, params, "niter"),
        "diameter": _setting(inp, params, "diameter"),
        "segmentation_binning": _setting(inp, params, "segmentation_binning"),
    }


def border_filter_params(inp: dict, params: dict) -> dict:
    """The overlap guard: how wide a band at each tile edge is rejected."""
    return {"border_margin_px": _none_or_int(
        _setting(inp, params, "border_margin_px")
    )}


def area_filter_params(inp: dict, params: dict) -> dict:
    """Return post-segmentation object-size filtering params."""
    min_area_px = _setting(inp, params, "min_area_px")
    max_area_px = _setting(inp, params, "max_area_px")
    min_diameter_um = _setting(inp, params, "min_equivalent_diameter_um")
    max_diameter_um = _setting(inp, params, "max_equivalent_diameter_um")

    min_area_px = _area_bound_px(
        area_px=min_area_px,
        diameter_um=min_diameter_um,
        source_pixel_size_um=_setting(inp, params, "source_pixel_size_um"),
        bound="min",
    )
    max_area_px = _area_bound_px(
        area_px=max_area_px,
        diameter_um=max_diameter_um,
        source_pixel_size_um=_setting(inp, params, "source_pixel_size_um"),
        bound="max",
    )
    if (
        min_area_px is not None
        and max_area_px is not None
        and max_area_px < min_area_px
    ):
        raise ValueError("max object size must be >= min object size.")
    return {
        "min_area_px": min_area_px,
        "max_area_px": max_area_px,
        "min_equivalent_diameter_um": _none_or_float(min_diameter_um),
        "max_equivalent_diameter_um": _none_or_float(max_diameter_um),
    }


def _setting(inp: dict, params: dict, key: str):
    return inp.get(key, params.get(key, None))


def _area_bound_px(*, area_px, diameter_um, source_pixel_size_um, bound: str):
    area_px = _none_or_int(area_px)
    diameter_um = _none_or_float(diameter_um)
    if area_px is not None and diameter_um is not None:
        raise ValueError(
            f"Specify either {bound}_area_px or {bound}_equivalent_diameter_um, "
            "not both."
        )
    if area_px is not None:
        if area_px < 0:
            raise ValueError(f"{bound}_area_px must be >= 0.")
        return area_px
    if diameter_um is None:
        return None
    if diameter_um < 0:
        raise ValueError(f"{bound}_equivalent_diameter_um must be >= 0.")
    pixel_area_um2 = _pixel_area_um2(source_pixel_size_um)
    area_um2 = math.pi * (diameter_um / 2.0) ** 2
    area_px_float = area_um2 / pixel_area_um2
    if bound == "min":
        return int(math.ceil(area_px_float))
    if bound == "max":
        return int(math.floor(area_px_float))
    raise ValueError("bound must be 'min' or 'max'.")


def _pixel_area_um2(source_pixel_size_um):
    if source_pixel_size_um is None:
        raise ValueError(
            "source_pixel_size_um is required when filtering by equivalent diameter."
        )
    if isinstance(source_pixel_size_um, (int, float)):
        sx = sy = float(source_pixel_size_um)
    else:
        values = list(source_pixel_size_um)
        if len(values) == 0:
            raise ValueError("source_pixel_size_um cannot be empty.")
        sx = float(values[0])
        sy = float(values[1] if len(values) > 1 else values[0])
    if sx <= 0 or sy <= 0:
        raise ValueError("source_pixel_size_um values must be > 0.")
    return sx * sy


def _none_or_int(value):
    if value is None:
        return None
    return int(value)


def _none_or_float(value):
    if value is None:
        return None
    return float(value)


def _channel_axis(value):
    """Validate and normalize equivalent channel-last axis declarations."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(
            f"channel_axis must be 0, 2, -1, or None; got {value}."
        )
    try:
        value = operator.index(value)
    except TypeError as exc:
        raise ValueError(
            f"channel_axis must be 0, 2, -1, or None; got {value}."
        ) from exc
    if value == 0:
        return 0
    if value in (-1, 2):
        return -1
    raise ValueError(
        f"channel_axis must be 0, 2, -1, or None; got {value}."
    )


def segmentation_params_hash(params: dict) -> str:
    """Stable hash of true segmentation identity params.

    This deliberately excludes GPU/CPU placement and area filters. GPU is an
    execution detail, while area filters are applied after Cellpose and can be
    retuned from persisted raw masks.
    """
    identity = {key: params.get(key, None) for key in SEGMENTATION_IDENTITY_KEYS}
    identity["channel_axis"] = _channel_axis(identity["channel_axis"])
    text = json.dumps(to_builtin(identity), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    """Return a SHA256 digest for a persisted artifact."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
