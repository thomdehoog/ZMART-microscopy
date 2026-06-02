"""Neutral acquisition product contracts shared by save exporters.

``Exported*`` types are exporter -> save inputs and are writer-agnostic.
``SavedAcquisition`` is the current flat OME-TIFF/XML save -> caller
output manifest.
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
class PlaneSource:
    """Source for one canonical image plane.

    ``page_index=None`` means the source path is already a single-plane
    image file and can be copied as a whole. An integer page index means
    the plane must be materialized from that page in a multipage TIFF.
    """

    path: Path
    page_index: int | None = None


@dataclass(frozen=True)
class XmlSource:
    """Source for one canonical companion XML.

    ``embedded=False`` means *path* is a standalone XML file.
    ``embedded=True`` means the XML comes from TIFF tag 270 in *path*.
    """

    path: Path
    embedded: bool = False


@dataclass(frozen=True)
class ExportedPosition:
    """One exported position/timepoint: shared XML plus plane sources."""

    t: int
    xml: XmlSource
    planes: dict[PlaneIndex, PlaneSource]


@dataclass(frozen=True)
class ExportedAcquisition:
    """Stable source product produced by an exporter."""

    media_path: Path
    source_dir: Path
    positions: list[ExportedPosition]
    method: str
    relative_path: str | None = None
    source_exporter: str = "navigator_expert_exporter"
    cleanup_source_supported: bool = True

    @property
    def image_files(self) -> list[Path]:
        return list(dict.fromkeys(
            src.path
            for pos in self.positions
            for _idx, src in sorted(pos.planes.items())
        ))

    @property
    def xml_files(self) -> list[Path]:
        return list(dict.fromkeys(pos.xml.path for pos in self.positions))

    @property
    def source_files(self) -> list[Path]:
        return list(dict.fromkeys([*self.image_files, *self.xml_files]))


@dataclass(frozen=True)
class SavedAcquisition:
    """Manifest for one persisted acquisition product."""

    image_paths: dict[PlaneIndex, Path]
    xml_paths: dict[PositionIndex, Path]
    naming: Naming
