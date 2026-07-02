"""
Capture: snap and acquisition-list runs.
========================================
Microscope-only capture. These helpers build a mesoSPIM ``Acquisition`` dict
from the current instrument state plus caller options, fire it at the command
server, and return a save-agnostic :class:`AcquisitionResult` referencing the
frame files the mesoSPIM image writer produced. No file relocation, OME
rewriting, or canonical naming happens here -- that is ``acquisition.save``.

An ``Acquisition`` is the real mesoSPIM data class (``utils/acquisitions.py``):
``x_pos, y_pos, z_start, z_end, z_step, planes, rot, f_start, f_end, laser,
intensity, filter, zoom, shutterconfig, folder, filename, etl_*``. We build it
from the live state so a capture reproduces exactly what the operator set up.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..config.profiles import ACQUISITION, HARDWARE
from ..readers.readers import get_state
from ..utils import _safe_float
from .product import AcquisitionMetadata, AcquisitionResult, ChannelMetadata

log = logging.getLogger(__name__)


def _pixel_size_for_zoom(zoom: str | None) -> float | None:
    for name, px in HARDWARE.zoom_pixel_size_um:
        if name == zoom:
            return px
    return None


def _wavelength_for_laser(laser: str | None) -> float | None:
    for name, wl in HARDWARE.lasers:
        if name == laser:
            return float(wl)
    return None


def build_acquisition(state: dict, options: dict | None = None) -> dict:
    """Compose a mesoSPIM ``Acquisition`` dict from live state + options.

    ``state`` is the dict from :func:`readers.get_state`. ``options`` may
    override any acquisition field (``z_start``/``z_end``/``z_step``/``planes``,
    ``laser``, ``intensity``, ``filter``, ``zoom``, ``shutterconfig``, ...).
    A single-plane capture leaves ``planes=1`` and equal ``z_start``/``z_end``.
    """
    options = dict(options or {})
    pos = state.get("position", {}) or {}
    z = _safe_float(pos.get("z"), 0.0)
    f = _safe_float(pos.get("f"), 0.0)

    acq = {
        "x_pos": _safe_float(pos.get("x"), 0.0),
        "y_pos": _safe_float(pos.get("y"), 0.0),
        "z_start": z,
        "z_end": z,
        "z_step": 1.0,
        "planes": 1,
        "rot": _safe_float(pos.get("theta"), 0.0),
        "f_start": f,
        "f_end": f,
        "laser": state.get("laser"),
        "intensity": state.get("intensity"),
        "filter": state.get("filter"),
        "zoom": state.get("zoom"),
        "shutterconfig": state.get("shutterconfig"),
        "etl_l_amplitude": state.get("etl_l_amplitude"),
        "etl_l_offset": state.get("etl_l_offset"),
        "etl_r_amplitude": state.get("etl_r_amplitude"),
        "etl_r_offset": state.get("etl_r_offset"),
    }
    acq.update({k: v for k, v in options.items() if k in acq or k in ("folder", "filename")})

    # Derive a consistent plane count from the z range if a stack was requested
    # but planes was not given explicitly.
    if "planes" not in options:
        span = abs(_safe_float(acq["z_end"], 0.0) - _safe_float(acq["z_start"], 0.0))
        step = abs(_safe_float(acq["z_step"], 1.0)) or 1.0
        acq["planes"] = int(round(span / step)) + 1 if span > 0 else 1
    return acq


def _metadata_from(acq: dict, server_data: dict) -> AcquisitionMetadata:
    px = _pixel_size_for_zoom(acq.get("zoom"))
    pixels = server_data.get("pixels") or list(HARDWARE.camera_pixels)
    channel = ChannelMetadata(
        index=0,
        laser=acq.get("laser"),
        filter=acq.get("filter"),
        wavelength_nm=_wavelength_for_laser(acq.get("laser")),
        intensity=_safe_float(acq.get("intensity")),
    )
    return AcquisitionMetadata(
        size_x=int(pixels[0]),
        size_y=int(pixels[1]),
        size_z=int(acq.get("planes", 1)),
        pixel_size_um=px,
        z_step_um=_safe_float(acq.get("z_step")),
        zoom=acq.get("zoom"),
        shutterconfig=acq.get("shutterconfig"),
        channels=(channel,),
    )


def acquire(
    client,
    acquisition_type: str = "snap",
    *,
    options: dict | None = None,
    state: dict | None = None,
) -> AcquisitionResult:
    """Run one capture and return its save-agnostic result.

    Reads the current state (unless ``state`` is supplied), builds the
    ``Acquisition``, fires it, and returns the frame files the image writer
    produced. Raises ``RuntimeError`` if the server reports failure or produces
    no frames.
    """
    state = state if state is not None else get_state(client)
    acq = build_acquisition(state, options)

    started_at = time.time()
    # A capture reply arrives only when the run finishes, which far exceeds the
    # default per-request socket deadline -- use the acquisition timeout.
    reply = client.request(
        "acquire",
        acquisition=acq,
        acquisition_type=acquisition_type,
        read_timeout=ACQUISITION.acquire_timeout_s,
    )
    finished_at = time.time()

    data = dict(reply.data)
    files = tuple(Path(p) for p in data.get("files", []))
    planes = int(data.get("planes", acq.get("planes", 1)))
    if not files:
        raise RuntimeError(
            f"acquire({acquisition_type!r}) returned no frame files; server data: {data!r}"
        )
    return AcquisitionResult(
        acquisition_type=acquisition_type,
        acquisition=acq,
        started_at=started_at,
        finished_at=finished_at,
        files=files,
        planes=planes,
        metadata=_metadata_from(acq, data),
        server_data=data,
    )


def snap(client, *, options: dict | None = None) -> AcquisitionResult:
    """Capture a single frame with the current settings (planes forced to 1)."""
    opts = dict(options or {})
    opts["planes"] = 1
    return acquire(client, "snap", options=opts)


def run_acquisition_list(client, acquisitions: list[dict]) -> dict:
    """Submit a full mesoSPIM ``AcquisitionList`` and return the server's record.

    Each entry is an ``Acquisition`` dict (see :func:`build_acquisition`). This
    is the multi-tile / multi-channel path; the reply carries every produced
    file grouped per acquisition.
    """
    if not acquisitions:
        raise ValueError("acquisition list is empty")
    reply = client.request(
        "run_acquisition_list",
        acquisitions=list(acquisitions),
        read_timeout=ACQUISITION.acquire_timeout_s,
    )
    return dict(reply.data)
