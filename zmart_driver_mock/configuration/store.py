"""Loading, checking and saving the configuration.

Each item lives in its own file under the computer's ZMART configuration
folder (``C:\\ProgramData\\zmart-microscopy`` on Windows), never in a
repository, so a fresh download or an upgrade cannot lose it::

    <configuration folder>/mock/mock-scope/mock-api/origin/origin.json
    <configuration folder>/mock/mock-scope/mock-api/limits/limits.json
    ...

When an item has never been saved, the shipped default is used, and the
driver says so in ``get_info``. A saved file that is malformed is refused
with a message naming the file and the problem; the driver never guesses.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zmart_controller.registry import config_root

from .checks import CHECKS

# The order matters: connect loads them in this order, because each one
# depends on the ones before it.
ITEMS: tuple[str, ...] = (
    "machine_description",
    "image_stage_registration",
    "origin",
    "limits",
    "optical_calibration",
)

DEFAULTS = Path(__file__).resolve().parent / "defaults"

IDENTITY = ("mock", "mock-scope", "mock-api")


@dataclass(frozen=True)
class Configuration:
    """Every configuration item of one microscope, as loaded at connect.

    ``sources`` says, for each item, which file it came from, so the
    operator can see whether a setting was measured or is still a default.
    """

    machine_description: dict[str, Any]
    image_stage_registration: dict[str, Any]
    origin: dict[str, float]
    limits: dict[str, Any]
    optical_calibration: dict[str, Any]
    sources: dict[str, str]


def saved_path(item: str, identity: tuple[str, str, str] = IDENTITY) -> Path:
    """Where ``item`` is saved for the microscope named by ``identity``."""
    _known(item)
    return config_root().joinpath(*identity, item, f"{item}.json")


def _known(item: str) -> None:
    if item not in ITEMS:
        raise ValueError(f"unknown configuration item {item!r}; known: {list(ITEMS)}")


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from None


def load(item: str, identity: tuple[str, str, str] = IDENTITY) -> tuple[Any, str]:
    """Load and check one item. Returns ``(value, where it came from)``."""
    path = saved_path(item, identity)
    if not path.is_file():
        path = DEFAULTS / f"{item}.json"
    value = _read(path)
    CHECKS[item](value, str(path))
    return value, str(path)


def load_configuration(identity: tuple[str, str, str] = IDENTITY) -> Configuration:
    """Load every item, in order. Raises ``ValueError`` naming the first bad file."""
    values = {}
    sources = {}
    for item in ITEMS:
        values[item], sources[item] = load(item, identity)
    return Configuration(**values, sources=sources)


def save(item: str, value: Any, identity: tuple[str, str, str] = IDENTITY) -> Path:
    """Check ``value`` and save it as the configuration ``item``. Returns the file.

    The new file replaces the old one in a single step, so a crash halfway
    through can never leave a half-written file behind. The driver uses it
    from the next connect on.
    """
    CHECKS[item](value, f"the new {item}")
    path = saved_path(item, identity)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except PermissionError:
        raise PermissionError(
            f"cannot write {path}. Run this with the rights to write there, "
            f"or point ZMART_MICROSCOPY_ROOT at a folder you can write."
        ) from None
    return path
