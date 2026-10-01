"""Writing a flat OME-TIFF: one image plane per file.

OME-TIFF is an ordinary TIFF image with a description in OME-XML, the open
microscopy metadata standard, so any image program can open the pixels and
any OME-aware program also knows the pixel size and position. ZMART saves
one plane per file, so every file is small and complete on its own.

This writer uses only the Python standard library: uncompressed 16-bit
grey images with the OME-XML stored in the TIFF's image description.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import struct
import sys
import uuid
from array import array
from pathlib import Path
from xml.sax.saxutils import quoteattr

# TIFF field types: 2 = text, 3 = 16-bit number, 4 = 32-bit number.
_TEXT, _SHORT, _LONG = 2, 3, 4


def ome_xml(
    *,
    name: str,
    width: int,
    height: int,
    pixel_size_um: float,
    position_um: dict[str, float],
    extra: dict[str, str],
) -> str:
    """The OME-XML description of one plane, with its pixel size and user position."""
    annotations = "".join(
        f"<M K={quoteattr(key)}>{_escape(value)}</M>" for key, value in sorted(extra.items())
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06" '
        f'Creator="zmart_driver_mock" UUID="urn:uuid:{uuid.uuid4()}">'
        f'<Image ID="Image:0" Name={quoteattr(name)}>'
        f'<Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16" '
        f'SizeX="{width}" SizeY="{height}" SizeZ="1" SizeC="1" SizeT="1" '
        f'PhysicalSizeX="{pixel_size_um}" PhysicalSizeXUnit="µm" '
        f'PhysicalSizeY="{pixel_size_um}" PhysicalSizeYUnit="µm">'
        '<Channel ID="Channel:0:0" SamplesPerPixel="1"/>'
        '<TiffData IFD="0" PlaneCount="1"/>'
        f'<Plane TheZ="0" TheC="0" TheT="0" '
        f'PositionX="{position_um["x"]}" PositionXUnit="µm" '
        f'PositionY="{position_um["y"]}" PositionYUnit="µm" '
        f'PositionZ="{position_um["z"]}" PositionZUnit="µm"/>'
        "</Pixels>"
        '<AnnotationRef ID="Annotation:0"/>'
        "</Image>"
        '<StructuredAnnotations><MapAnnotation ID="Annotation:0" '
        'Namespace="zmart/acquisition"><Value>'
        f"{annotations}"
        "</Value></MapAnnotation></StructuredAnnotations>"
        "</OME>"
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_ome_tiff(path: Path, plane: array, width: int, height: int, description: str) -> None:
    """Write one 16-bit plane as a TIFF file with ``description`` as its OME-XML."""
    text = description.encode("utf-8") + b"\0"
    pixels = array("H", plane)
    if sys.byteorder == "big":
        pixels.byteswap()
    data = pixels.tobytes()
    tags = [
        (256, _LONG, 1, width),  # image width
        (257, _LONG, 1, height),  # image length
        (258, _SHORT, 1, 16),  # bits per sample
        (259, _SHORT, 1, 1),  # no compression
        (262, _SHORT, 1, 1),  # black is zero
        (270, _TEXT, len(text), None),  # image description: the OME-XML
        (273, _LONG, 1, None),  # where the pixels start
        (277, _SHORT, 1, 1),  # one sample per pixel
        (278, _LONG, 1, height),  # all rows in one strip
        (279, _LONG, 1, len(data)),  # how many bytes of pixels
    ]
    ifd_offset = 8
    ifd_size = 2 + 12 * len(tags) + 4
    text_offset = ifd_offset + ifd_size
    data_offset = text_offset + len(text)
    if data_offset % 2:
        data_offset += 1  # keep the pixels on an even byte, as TIFF readers prefer
    entries = b""
    for tag, kind, count, value in tags:
        if tag == 270:
            value = text_offset
        elif tag == 273:
            value = data_offset
        if kind == _SHORT:
            field = struct.pack("<HHIHH", tag, kind, count, value, 0)
        else:
            field = struct.pack("<HHII", tag, kind, count, value)
        entries += field
    with path.open("wb") as stream:
        stream.write(b"II*\0" + struct.pack("<I", ifd_offset))
        stream.write(struct.pack("<H", len(tags)) + entries + struct.pack("<I", 0))
        stream.write(text)
        stream.write(b"\0" * (data_offset - text_offset - len(text)))
        stream.write(data)
