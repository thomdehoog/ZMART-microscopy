"""Neutral acquisition product contracts.

Mirrors the Leica driver's ``acquisition.product`` neutral types so the
vendor-neutral save/analysis layers stay identical across drivers. The one
Zeiss-specific difference is the saved manifest: ZEN writes a single **CZI**
container per acquisition (rather than per-plane OME-TIFF), so
``SavedAcquisition`` records a ``czi_path`` here. The per-plane ``PlaneIndex`` /
``AcquisitionMetadata`` / ``ExportedAcquisition`` types are kept verbatim for
the eventual pixel-pull exporter seam (stream -> numpy -> OME).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .naming import Naming


@dataclass(frozen=True, order=True)
class PlaneIndex:
    """Canonical flat image plane index."""

    t: int
    z: int
    c: int


@dataclass(frozen=True, order=True)
class PositionIndex:
    """Canonical companion-metadata position index."""

    t: int
    v: int = 0


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
class ExportedAcquisition:
    """Stable source product produced by an exporter (pixel-pull seam)."""

    media_path: Path
    source_dir: Path
    metadata: AcquisitionMetadata
    method: str
    relative_path: str | None = None
    source_exporter: str = "zenapi_czi"


@dataclass(frozen=True)
class SavedAcquisition:
    """Manifest for one persisted acquisition product.

    ZEN writes one CZI container; ``czi_path`` is the persisted file in the
    workflow output layout. ``naming`` is the resolved output naming, matching
    the Leica manifest so downstream consumers stay vendor-neutral.
    """

    czi_path: Path
    naming: Naming
