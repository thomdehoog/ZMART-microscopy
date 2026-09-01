"""The acquisition-wide channel display contract beside a position collection."""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

DESCRIPTION_NAME = "zmart-acquisition.json"
SCHEMA = "zmart-acquisition-display/1"
_STALE_TEMPORARY_AFTER_S = 24 * 60 * 60


class AcquisitionDescriptionError(ValueError):
    """The acquisition-wide display contract is absent, invalid or contradictory."""


def _finite_numbers(value: Any, what: str) -> None:
    """Refuse NaN/infinity anywhere, including preserved provenance fields."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"{what} contains a number that is not finite")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _finite_numbers(child, f"{what}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _finite_numbers(child, f"{what}[{index}]")


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string")
    return value.strip()


def _number(value: Any, what: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a finite number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{what} must be a finite number")
    return value


def _whole(value: Any, what: str) -> int:
    number = _number(value, what)
    if int(number) != number or int(number) < 0:
        raise ValueError(f"{what} must be a non-negative whole number")
    return int(number)


def _pair(value: Any, what: str, low_name: str, high_name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object")
    low = _number(value.get(low_name), f"{what}.{low_name}")
    high = _number(value.get(high_name), f"{what}.{high_name}")
    if float(high) <= float(low):
        raise ValueError(f"{what}.{high_name} must be greater than {what}.{low_name}")
    return {low_name: low, high_name: high}


def validate_acquisition_description(
    value: Any, *, acquisition_type: str, channel_count: int
) -> dict:
    """Return one canonical version-1 description or raise a precise refusal."""
    if not isinstance(value, dict):
        raise ValueError("the acquisition display description must be an object")
    _finite_numbers(value, "the acquisition display description")
    if value.get("schema") != SCHEMA:
        raise ValueError(f"the acquisition display schema must be {SCHEMA!r}")
    wanted_type = _text(acquisition_type, "acquisition_type")
    found_type = _text(value.get("acquisitionType"), "acquisitionType")
    if found_type != wanted_type:
        raise ValueError(
            f"the acquisition description names {found_type!r}, not {wanted_type!r}"
        )
    raw_channels = value.get("channels")
    if not isinstance(raw_channels, list):
        raise ValueError("channels must be a list")
    if len(raw_channels) != channel_count:
        raise ValueError(
            f"the acquisition describes {len(raw_channels)} channel(s), but {channel_count} "
            "were expected"
        )

    channels = []
    keys: set[str] = set()
    indices: set[int] = set()
    for at, raw in enumerate(raw_channels):
        if not isinstance(raw, dict):
            raise ValueError(f"channels[{at}] must be an object")
        key = _text(raw.get("key"), f"channels[{at}].key")
        index = _whole(raw.get("index"), f"channels[{at}].index")
        label = _text(raw.get("label"), f"channels[{at}].label")
        if key in keys:
            raise ValueError(f"channel key {key!r} is repeated")
        if index in indices:
            raise ValueError(f"channel index {index} is repeated")
        keys.add(key)
        indices.add(index)
        channel = {"key": key, "index": index, "label": label}

        color = raw.get("color")
        if color is not None:
            if not isinstance(color, str) or len(color) != 6:
                raise ValueError(f"channels[{at}].color must be six hexadecimal digits")
            try:
                int(color, 16)
            except ValueError as exc:
                raise ValueError(
                    f"channels[{at}].color must be six hexadecimal digits"
                ) from exc
            channel["color"] = color.upper()

        declared_range = raw.get("range")
        if declared_range is not None:
            channel["range"] = _pair(declared_range, f"channels[{at}].range", "min", "max")

        display = raw.get("displayWindow")
        provenance = raw.get("windowProvenance")
        if (display is None) != (provenance is None):
            raise ValueError(
                f"channels[{at}] must carry displayWindow and windowProvenance together"
            )
        if display is not None:
            if "range" not in channel:
                raise ValueError(f"channels[{at}].displayWindow requires range")
            channel["displayWindow"] = _pair(
                display, f"channels[{at}].displayWindow", "start", "end"
            )
            if (
                float(channel["displayWindow"]["start"]) < float(channel["range"]["min"])
                or float(channel["displayWindow"]["end"]) > float(channel["range"]["max"])
            ):
                raise ValueError(f"channels[{at}].displayWindow must lie inside range")
            if not isinstance(provenance, dict):
                raise ValueError(f"channels[{at}].windowProvenance must be an object")
            normal_provenance = deepcopy(provenance)
            normal_provenance["method"] = _text(
                provenance.get("method"), f"channels[{at}].windowProvenance.method"
            )
            normal_provenance["resolvedFrom"] = _text(
                provenance.get("resolvedFrom"),
                f"channels[{at}].windowProvenance.resolvedFrom",
            )
            if "sampleCount" in provenance:
                normal_provenance["sampleCount"] = _whole(
                    provenance["sampleCount"],
                    f"channels[{at}].windowProvenance.sampleCount",
                )
            if "resolvedAtRevision" in provenance:
                normal_provenance["resolvedAtRevision"] = _whole(
                    provenance["resolvedAtRevision"],
                    f"channels[{at}].windowProvenance.resolvedAtRevision",
                )
            algorithm = provenance.get("algorithm")
            if algorithm is not None and not isinstance(algorithm, str):
                raise ValueError(
                    f"channels[{at}].windowProvenance.algorithm must be a string or null"
                )
            channel["windowProvenance"] = normal_provenance
        channels.append(channel)

    if indices != set(range(channel_count)):
        raise ValueError(f"channel indices must be exactly 0 through {channel_count - 1}")
    channels.sort(key=lambda channel: channel["index"])
    return {"schema": SCHEMA, "acquisitionType": found_type, "channels": channels}


def acquisition_description(
    acquisition_type: str, channels: list[dict] | dict, *, channel_count: int
) -> dict:
    """Make a document checked against the acquisition's independent channel count."""
    document = (
        channels
        if isinstance(channels, dict)
        else {"schema": SCHEMA, "acquisitionType": acquisition_type, "channels": channels}
    )
    return validate_acquisition_description(
        document, acquisition_type=acquisition_type, channel_count=channel_count
    )


def read_acquisition_description(
    folder: Path | str, *, channel_count: int
) -> dict | None:
    """Read and validate the complete sidecar, or return ``None`` when absent."""
    folder = Path(folder)
    source = folder / DESCRIPTION_NAME
    if not source.is_file():
        return None
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} is not readable JSON") from exc
    return validate_acquisition_description(
        value, acquisition_type=folder.name, channel_count=channel_count
    )


def _sweep_abandoned_temporaries(folder: Path) -> None:
    """Remove only old, certainly abandoned siblings; never race a live writer."""
    now = time.time()
    for temporary in folder.glob(f".{DESCRIPTION_NAME}.*.tmp"):
        try:
            if now - temporary.stat().st_mtime > _STALE_TEMPORARY_AFTER_S:
                temporary.unlink()
        except OSError:
            continue


def _sync_directory(folder: Path) -> None:
    """Make the newly linked filename durable where directory fsync exists."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(folder, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Windows supports the atomic hard link below but not directory fsync.
        pass
    finally:
        os.close(descriptor)


def write_acquisition_description(
    folder: Path | str, description: dict, *, channel_count: int
) -> Path:
    """Publish one immutable description atomically and without a writer race.

    The contract is create-once, so a hard link is stronger than replacing the
    target: two writers can both prepare complete files, but only one can create
    the target name.  The loser then compares against the winner and either
    accepts the identical value or refuses the contradiction.
    """
    folder = Path(folder)
    normal = validate_acquisition_description(
        description,
        acquisition_type=folder.name,
        channel_count=channel_count,
    )
    folder.mkdir(parents=True, exist_ok=True)
    _sweep_abandoned_temporaries(folder)
    target = folder / DESCRIPTION_NAME
    existing = read_acquisition_description(folder, channel_count=channel_count)
    if existing is not None:
        if existing != normal:
            raise ValueError(
                f"{target} already describes this acquisition differently; a published "
                "display contract is immutable"
            )
        return target

    temporary = folder / f".{DESCRIPTION_NAME}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(normal, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            existing = read_acquisition_description(folder, channel_count=channel_count)
            if existing != normal:
                raise ValueError(
                    f"{target} was concurrently published with a different display "
                    "contract; the acquisition has not started"
                ) from None
        else:
            _sync_directory(folder)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def ome_channel_blocks(description: dict, *, depth_max: int) -> list[dict]:
    """Mirror the acquisition contract into ordinary OME channel blocks.

    A resolved acquisition gives every position the same label, colour and
    window, so a dim field and a bright field open on one scale. An acquisition
    with any unresolved channel gives an empty list, and the store is written
    with no channel block at all: strict readers refuse a block whose window
    has ``min``/``max`` but no ``start``/``end``, and inventing the camera's
    range for the missing pair makes real images open almost black.
    """
    normal = validate_acquisition_description(
        description,
        acquisition_type=description.get("acquisitionType"),
        channel_count=len(description.get("channels") or []),
    )
    blocks = []
    unresolved = False
    for channel in normal["channels"]:
        declared_range = channel.get("range") or {"min": 0, "max": depth_max}
        window = dict(declared_range)
        chosen = channel.get("displayWindow")
        if chosen is not None:
            window.update(chosen)
        else:
            unresolved = True
        block = {"label": channel["label"], "window": window}
        if channel.get("color") is not None:
            block["color"] = channel["color"]
        blocks.append(block)
    # ngio refuses an omero block with min/max but no start/end. Omitting the
    # whole advisory block is the shape every reader opens.
    return [] if unresolved else blocks
