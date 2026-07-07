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
class ChannelMetadata:
    """Minimal reusable channel metadata for canonical SMART OME."""

    index: int
    name: str | None = None
    color: int | None = None
    wavelength_nm: float | None = None


@dataclass(frozen=True)
class AcquisitionMetadata:
    """Common denominator needed to write valid, reusable SMART OME."""

    size_x: int
    size_y: int
    size_t: int
    size_z: int
    size_c: int
    pixel_type: str
    physical_size_x_um: float | None = None
    physical_size_y_um: float | None = None
    physical_size_z_um: float | None = None
    channels: tuple[ChannelMetadata, ...] = ()

    def channel(self, index: int) -> ChannelMetadata:
        for channel in self.channels:
            if channel.index == index:
                return channel
        return ChannelMetadata(index=index)


@dataclass(frozen=True)
class VendorMetadataSource:
    """Raw vendor metadata preserved as provenance, not output truth."""

    name: str
    path: Path | None = None
    data: bytes | None = None


@dataclass(frozen=True)
class ExportedPosition:
    """One exported timepoint: canonical plane sources."""

    t: int
    planes: dict[PlaneIndex, PlaneSource]


@dataclass(frozen=True)
class ExportedAcquisition:
    """Stable source product produced by an exporter."""

    source_root: Path
    source_dir: Path
    positions: list[ExportedPosition]
    metadata: AcquisitionMetadata
    method: str
    relative_path: str | None = None
    source_exporter: str = "lasx_native_autosave"
    cleanup_source_supported: bool = True
    vendor_metadata_sources: tuple[VendorMetadataSource, ...] = ()

    @property
    def image_files(self) -> list[Path]:
        return list(
            dict.fromkeys(
                src.path for pos in self.positions for _idx, src in sorted(pos.planes.items())
            )
        )

    @property
    def metadata_files(self) -> list[Path]:
        return list(
            dict.fromkeys(src.path for src in self.vendor_metadata_sources if src.path is not None)
        )

    @property
    def source_files(self) -> list[Path]:
        return list(dict.fromkeys([*self.image_files, *self.metadata_files]))


@dataclass(frozen=True)
class SavedAcquisition:
    """Manifest for one persisted acquisition product."""

    image_paths: dict[PlaneIndex, Path]
    xml_paths: dict[PositionIndex, Path]
    naming: Naming
