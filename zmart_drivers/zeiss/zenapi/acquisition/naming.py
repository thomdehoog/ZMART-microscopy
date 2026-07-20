"""Zeiss-private naming retained for the existing CZI save path."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

_EPOCH = 1767225600
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_TYPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HASH_RE = re.compile(r"^[0-9a-z]{6}$")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]")


def run_hash(start_time: float | None = None) -> str:
    value = int((time.time() if start_time is None else start_time) - _EPOCH)
    if value < 0:
        raise ValueError("start_time is before 2026-01-01 UTC")
    digits = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(_ALPHABET[remainder])
    return ("".join(reversed(digits)) or "0").rjust(6, "0")


@dataclass(frozen=True)
class Naming:
    acquisition_type: str
    hash6: str
    position_label: str
    c: int = 0
    z: int = 0

    def __post_init__(self) -> None:
        if not _TYPE_RE.fullmatch(self.acquisition_type):
            raise ValueError("acquisition_type must be kebab-case lowercase")
        if not _HASH_RE.fullmatch(self.hash6):
            raise ValueError("hash6 must be 6 lowercase base36 characters")
        if not self.position_label:
            raise ValueError("position_label must be non-empty")
        object.__setattr__(self, "position_label", _UNSAFE_RE.sub("_", self.position_label))


def acquisition_dir(output_root: Path | str, acquisition_type: str) -> Path:
    return Path(output_root) / acquisition_type
