"""Neutral acquisition product contracts shared by save exporters.

``Exported*`` types are exporter -> save inputs. ``SavedAcquisition`` is
the save -> caller output manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.output_layout import Naming


@dataclass(frozen=True, order=True)
class PlaneIndex:
    """Canonical flat image plane index."""

    t: int
    z: int
    c: int


@dataclass(frozen=True, order=True)
class PositionIndex:
    """Canonical companion-XML position index."""

    t: int
    v: int = 0


@dataclass(frozen=True)
class ExportedPosition:
    """One exported position/timepoint: shared XML plus flat planes."""

    t: int
    xml_path: Path
    planes: dict[PlaneIndex, Path]


@dataclass(frozen=True)
class ExportedAcquisition:
    """Stable source product produced by an exporter."""

    media_path: Path
    source_dir: Path
    positions: list[ExportedPosition]
    method: str
    relative_path: str | None = None

    @property
    def image_files(self) -> list[Path]:
        return [
            p
            for pos in self.positions
            for _idx, p in sorted(pos.planes.items())
        ]

    @property
    def xml_files(self) -> list[Path]:
        return list(dict.fromkeys(pos.xml_path for pos in self.positions))


@dataclass(frozen=True)
class SavedAcquisition:
    """Manifest for one persisted acquisition product."""

    image_paths: dict[PlaneIndex, Path]
    xml_paths: dict[PositionIndex, Path]
    naming: Naming
