"""Leica-private flat OME-TIFF filename convention."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

EPOCH = 1767225600  # 2026-01-01 00:00:00 UTC
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_ACQUISITION_TYPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HASH_RE = re.compile(r"^[0-9a-z]{6}$")
_UNSAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_-]")
_IMAGE_RE = re.compile(
    r"^(?P<acq>[a-z0-9]+(?:-[a-z0-9]+)*)_(?P<hash>[0-9a-z]{6})"
    r"_(?P<label>[A-Za-z0-9_-]+)_T(?P<t>\d{6})_C(?P<c>\d{2})_Z(?P<z>\d{5})"
    r"\.ome\.tiff$"
)


def run_hash(start_time: float | None = None) -> str:
    """Return six sortable base36 characters for a timestamp."""

    value = int((time.time() if start_time is None else start_time) - EPOCH)
    if value < 0:
        raise ValueError(f"start_time is before convention epoch {EPOCH}")
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(_ALPHABET[remainder])
    return ("".join(reversed(digits)) or "0").rjust(6, "0")


@dataclass(frozen=True)
class Naming:
    """Validated filename values for one Leica OME-TIFF plane."""

    acquisition_type: str
    hash6: str
    position_label: str
    t: int = 0
    c: int = 0
    z: int = 0

    def __post_init__(self) -> None:
        if not _ACQUISITION_TYPE_RE.fullmatch(self.acquisition_type):
            raise ValueError(
                f"acquisition_type must be kebab-case lowercase, got {self.acquisition_type!r}"
            )
        if len(self.acquisition_type) > 25:
            raise ValueError("acquisition_type is longer than 25 characters")
        if not _HASH_RE.fullmatch(self.hash6):
            raise ValueError(f"hash6 must be 6 lowercase base36 characters, got {self.hash6!r}")
        for field, value, maximum in (
            ("t", self.t, 999_999),
            ("c", self.c, 99),
            ("z", self.z, 99_999),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise ValueError(f"{field} must be a whole number from 0 through {maximum}")
        if not isinstance(self.position_label, str) or not self.position_label:
            raise ValueError("position_label must be a non-empty string")
        if len(self.position_label) > 40:
            raise ValueError("position_label is longer than 40 characters")
        object.__setattr__(self, "position_label", _UNSAFE_LABEL_RE.sub("_", self.position_label))


def build_image_name(naming: Naming) -> str:
    """Return the canonical Leica filename for one T/C/Z plane."""

    return (
        f"{naming.acquisition_type}_{naming.hash6}_{naming.position_label}_"
        f"T{naming.t:06d}_C{naming.c:02d}_Z{naming.z:05d}.ome.tiff"
    )


def parse_image_name(filename: str) -> Naming | None:
    """Parse a canonical Leica filename, or return ``None``."""

    match = _IMAGE_RE.fullmatch(filename)
    if match is None:
        return None
    return Naming(
        acquisition_type=match.group("acq"),
        hash6=match.group("hash"),
        position_label=match.group("label"),
        t=int(match.group("t")),
        c=int(match.group("c")),
        z=int(match.group("z")),
    )


def acquisition_dir(output_root: Path | str, acquisition_type: str) -> Path:
    """Return the driver's staging directory for an acquisition type."""

    return Path(output_root) / acquisition_type
