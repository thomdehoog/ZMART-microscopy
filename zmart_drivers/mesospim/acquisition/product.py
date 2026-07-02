"""
Acquisition product contracts.
==============================
Structured results shared by capture and save, so the driver returns typed
records rather than loose dicts (a ZMART design rule).

- :class:`AcquisitionResult` -- the save-agnostic result of one capture: the
  ``Acquisition`` that was run, timing, and the source frame files the mesoSPIM
  image writer produced.
- :class:`ChannelMetadata` / :class:`AcquisitionMetadata` -- the minimal,
  writer-agnostic metadata needed to persist a valid image.
- :class:`SavedAcquisition` -- the manifest returned by ``save`` after the
  frames land in the canonical output layout.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChannelMetadata:
    """One acquisition channel (a laser line + emission filter)."""

    index: int
    laser: str | None = None
    filter: str | None = None
    wavelength_nm: float | None = None
    intensity: float | None = None


@dataclass(frozen=True)
class AcquisitionMetadata:
    """Common-denominator metadata to persist a valid mesoSPIM image."""

    size_x: int
    size_y: int
    size_z: int
    pixel_size_um: float | None = None
    z_step_um: float | None = None
    zoom: str | None = None
    shutterconfig: str | None = None
    channels: tuple[ChannelMetadata, ...] = ()


@dataclass(frozen=True)
class AcquisitionResult:
    """Save-agnostic result of one capture (snap or acquisition list).

    ``files`` are the output files the mesoSPIM image-writer wrote on the
    acquisition PC -- normally one multi-page stack per acquisition (the default
    Tiff writer), so ``files`` is usually a single path even for a Z-stack.
    ``acquisition`` is the mesoSPIM ``Acquisition`` dict that produced them.
    """

    acquisition_type: str
    acquisition: dict
    started_at: float
    finished_at: float
    files: tuple[Path, ...]
    planes: int
    metadata: AcquisitionMetadata
    server_data: dict = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return self.finished_at - self.started_at


@dataclass(frozen=True)
class SavedAcquisition:
    """Manifest for one persisted acquisition product."""

    acquisition_type: str
    position_label: str
    image_paths: tuple[Path, ...]
    metadata_path: Path | None
    format: str
    metadata: AcquisitionMetadata
