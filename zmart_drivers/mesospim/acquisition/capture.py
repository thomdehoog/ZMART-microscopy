"""
Capture: snap and acquisition-list runs.
========================================
Microscope-only capture. These helpers build a mesoSPIM ``Acquisition`` dict
from the current instrument state plus caller options, hand it to the Remote
Control server, and return a save-agnostic :class:`AcquisitionResult`
referencing the frame files the mesoSPIM image writer produced. No file
relocation, OME rewriting, or canonical naming happens here -- that is
``acquisition.save``.

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
import tempfile
import time
from pathlib import Path

from ..config.profiles import ACQUISITION, HARDWARE
from ..readers.readers import _safe_float, get_state
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


def _wait_for_files(client, files: list[str], *, label: str) -> None:
    """Wait until every file the writer named exists and has stopped growing.

    mesoSPIM reports the run finished when its acquisition signal fires; the
    image writer normally has the stack on disk by then, but a large file may
    still be flushing. Two identical ``stat_files`` readings in a row mean it
    is complete. Raises when the file never appears within the settle budget,
    so a capture can never quietly "succeed" without its data.
    """
    deadline = time.monotonic() + ACQUISITION.file_settle_timeout_s
    prev_sizes: dict | None = None
    while True:
        stat = dict(client.request("stat_files", files=files).data)
        sizes = stat.get("sizes", {})
        missing = stat.get("missing", list(files))
        if not missing and sizes == prev_sizes:
            return
        prev_sizes = sizes
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"acquire({label!r}): mesoSPIM reported the run finished but the stack "
                f"is not complete on disk after {ACQUISITION.file_settle_timeout_s:.0f}s; "
                f"last stat: {stat!r}"
            )
        time.sleep(ACQUISITION.acquire_poll_s)


def _run_acquisition(client, acq: dict, *, label: str) -> dict:
    """Run one ``Acquisition`` on mesoSPIM and wait for its stack.

    Three Remote Control calls: ``acquire_start`` installs the one-row list and
    starts the run (the server accepts it at once and reports the files it
    will write); the client polls that operation until mesoSPIM's own
    "finished" signal marks it completed, then checks with ``stat_files`` that
    the stack has stopped growing; ``acquire_finish`` hands the operator's
    acquisition list back. The operator's list is restored on every path,
    success or not.

    Returns the ``acquire_start`` result (``files``, ``planes``, ``pixels``).
    """
    # The server refuses a field set to null; leave those out so the row keeps
    # mesoSPIM's own default for them.
    row = {k: v for k, v in acq.items() if v is not None}
    try:
        started = client.perform(
            "acquire_start",
            acquisition=row,
            timeout=ACQUISITION.acquire_timeout_s,
            poll_s=ACQUISITION.acquire_poll_s,
        )
        if not started.ok:
            raise RuntimeError(f"acquire({label!r}) failed: {started.error}")
        data = dict(started.data)
        files = [str(p) for p in data.get("files", [])]
        if files:
            _wait_for_files(client, files, label=label)
        return data
    finally:
        # Always hand the operator's acquisition list back, success or not
        # (without masking the original error if the connection died mid-run).
        # While a run that never finished still holds the server's one-change
        # gate, the server refuses with ``busy``: the list can only be restored
        # once that run ends (``stop_activity`` in mesoSPIM, then acquire_finish).
        try:
            finished = client.perform("acquire_finish")
            if not finished.ok:
                log.warning(
                    "could not restore the acquisition list yet (%s); call acquire_finish "
                    "once the run has ended",
                    finished.error,
                )
        except (ConnectionError, OSError, TimeoutError):
            log.warning("could not restore the acquisition list (connection lost)")


def acquire(
    client,
    acquisition_type: str = "snap",
    *,
    options: dict | None = None,
    state: dict | None = None,
) -> AcquisitionResult:
    """Run one capture and return its save-agnostic result.

    Reads the current state (unless ``state`` is supplied), builds the
    ``Acquisition``, runs it, and waits for the frame files the image writer
    produced. Raises ``RuntimeError`` if the server refuses or fails the run,
    or the stack does not appear within the acquisition timeout.
    """
    state = state if state is not None else get_state(client)
    # The image writer needs a concrete folder + filename to write the stack to;
    # the controller supplies a staging path, but a direct capture() caller may
    # not, so default to a fresh temp folder here. The server reports exactly
    # this path back, and save() relocates from it.
    options = dict(options or {})
    options.setdefault("folder", tempfile.mkdtemp(prefix="mesospim_capture_"))
    options.setdefault("filename", f"{acquisition_type}.tiff")
    acq = build_acquisition(state, options)

    started_at = time.time()
    data = _run_acquisition(client, acq, label=acquisition_type)
    finished_at = time.time()

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
    """Run a list of ``Acquisition`` dicts one by one and return every file.

    Each entry is an ``Acquisition`` dict (see :func:`build_acquisition`). This
    is the multi-tile / multi-channel path. Each acquisition runs through the
    same start/wait/finish flow as :func:`acquire`, so the operator's
    acquisition list is restored and the stack verified on disk per item; the
    record carries every produced file grouped per acquisition.
    """
    if not acquisitions:
        raise ValueError("acquisition list is empty")
    files: list[str] = []
    per: list[dict] = []
    for index, one in enumerate(acquisitions):
        # Give every acquisition a concrete folder/filename the image writer can
        # use (and the server can report back), unless the caller set one.
        acq = dict(one)
        acq.setdefault("folder", tempfile.mkdtemp(prefix="mesospim_list_"))
        acq.setdefault("filename", f"acq_{index:04d}.tiff")
        data = _run_acquisition(client, acq, label=f"list[{index}]")
        produced = [str(p) for p in data.get("files", [])]
        files.extend(produced)
        per.append({"files": produced, "planes": int(data.get("planes", 1) or 1)})
    return {"files": files, "per_acquisition": per}
