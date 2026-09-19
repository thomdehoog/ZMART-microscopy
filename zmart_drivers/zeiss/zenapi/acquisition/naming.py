"""Zeiss-private naming for the CZI save path, and where a capture's files go.

The layout is the one every ZMART driver writes, so a workflow finds the same
things in the same places whatever microscope took the picture::

    <output_root>/<type>/
        data/
            <type>_<hash>_<label>.czi                          the pixels (ZEN's CZI container)
            metadata/
                ZMART_state/<type>_<hash>_<label>_ZMART_state.json   ZMART's account of the capture

The pixels get a folder of their own so what is made from them later -- a
stitched view, an analysis -- becomes a folder beside them, and everything that
merely *describes* a capture sits under ``metadata``.
"""

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


def data_dir(output_root: Path | str, acquisition_type: str) -> Path:
    """Return where the images of an acquisition go: ``<type>/data``.

    The pixels get a folder of their own so what is made from them later --
    a stitched view, an analysis -- becomes a folder beside them.
    """
    return acquisition_dir(output_root, acquisition_type) / "data"


def metadata_dir(output_root: Path | str, acquisition_type: str) -> Path:
    """Return where an acquisition's printed metadata goes: ``<type>/data/metadata``."""
    return data_dir(output_root, acquisition_type) / "metadata"


def state_dir(output_root: Path | str, acquisition_type: str) -> Path:
    """Return where ZMART's own account of a capture goes: ``<type>/data/metadata/ZMART_state``.

    One folder per party (ZMART here, the vendor beside it), so whose account a
    file is never has to be read off its name.
    """
    return metadata_dir(output_root, acquisition_type) / "ZMART_state"


def build_state_name(naming: Naming) -> str:
    """Return the filename for one acquisition's printed state.

    The CZI name without its extension, because one state describes the whole
    container ZEN wrote for that capture.
    """
    return f"{naming.acquisition_type}_{naming.hash6}_{naming.position_label}_ZMART_state.json"
