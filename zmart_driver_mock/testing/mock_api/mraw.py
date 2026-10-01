"""The MockScope image file format, ``.mraw``.

Every real microscope saves its images in its own format: Leica writes
``.lif`` and exports, ZEISS writes ``.czi``, Nikon writes ``.nd2``. A driver's
data handling has to find these files, wait until they are complete, and turn
them into OME-TIFF or OME-Zarr. So the pretend vendor software has a format of
its own too, deliberately simple, so that this step can be practised and
tested without any hardware.

An ``.mraw`` file has two parts:

1. **One line of text** with a description of the image in JSON (a common
   text format for structured data): the image size, the number of planes,
   the pixel size, where the stage was, which objective was in place, and the
   settings at the time of capture. The line ends with a newline character.
2. **The pixels**, as 16-bit unsigned whole numbers (0 to 65535), stored
   little-endian (the lowest byte first), plane after plane, row after row.

The vendor software writes the description first, when an acquisition
starts, and the pixels only when it finishes. A file that is read too early
therefore has a description but no pixels, and :func:`read_mraw` refuses it
as incomplete. A real driver meets exactly this situation, and has to wait.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import sys
from array import array
from pathlib import Path
from typing import Any

FORMAT = "MRAW"
FORMAT_VERSION = 1


def write_header(path: Path, header: dict[str, Any]) -> None:
    """Start a new ``.mraw`` file with only its description line.

    This is what the vendor software does when an acquisition starts. The
    file exists from this moment on, but it is not complete yet.
    """
    line = json.dumps({"format": FORMAT, "version": FORMAT_VERSION, **header})
    path.write_bytes(line.encode("utf-8") + b"\n")


def append_planes(path: Path, planes: list[array]) -> None:
    """Add the pixels to a file started with :func:`write_header`.

    Each plane is an ``array("H")`` of ``width * height`` values.
    """
    with path.open("ab") as handle:
        for plane in planes:
            data = array("H", plane)
            if sys.byteorder == "big":
                # The format stores the lowest byte first on every computer.
                data.byteswap()
            handle.write(data.tobytes())


def read_mraw(path: str | Path) -> tuple[dict[str, Any], list[array]]:
    """Read an ``.mraw`` file and return ``(description, planes)``.

    ``description`` is the dictionary from the first line. ``planes`` is a
    list with one ``array("H")`` per plane, each holding ``width * height``
    pixel values, row after row.

    Raises ``ValueError`` when the file is not an ``.mraw`` file, or when it
    is incomplete because the vendor software has not finished writing it.
    """
    raw = Path(path).read_bytes()
    first_line, newline, body = raw.partition(b"\n")
    if not newline:
        raise ValueError(f"{path} has no description line; it is not an .mraw file")
    try:
        header = json.loads(first_line)
    except ValueError:
        raise ValueError(f"{path} does not start with a JSON description line") from None
    if not isinstance(header, dict) or header.get("format") != FORMAT:
        raise ValueError(f"{path} is not an .mraw file")
    plane_values = header["width"] * header["height"]
    expected = plane_values * header["planes"] * 2
    if len(body) < expected:
        raise ValueError(
            f"{path} is incomplete: {len(body)} of {expected} pixel bytes are written. "
            f"The acquisition may still be running."
        )
    data = array("H")
    data.frombytes(body[:expected])
    if sys.byteorder == "big":
        data.byteswap()
    planes = [
        data[index * plane_values : (index + 1) * plane_values] for index in range(header["planes"])
    ]
    return header, planes
