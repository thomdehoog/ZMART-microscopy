r"""
LAS X DataContainer Temp Image Reader
======================================

Extract acquired images from the Leica LAS X DataContainer temporary files.

Background
----------
Leica LAS X (confocal microscopy software) uses a service called
``LMSDataContainerService`` (executable: ``LMSDataContainerServerV2.exe``)
to manage all image data during a session. This service acts as a shared
memory broker between the scanner hardware, the viewer UI, and any connected
clients (Python API, MatrixScreener, etc.).

The DataContainer server is started with a configurable temp directory::

    LMSDataContainerServerV2.exe install <port> <temp_dir>

On this system the temp directory is ``D:\\Temp`` and the port is ``8892``.
The server communicates with clients over TCP sockets using XML commands.

File types in the temp directory
--------------------------------
All files are created by the DataContainer service. There are four types:

1. ``V2LMSDC_OBJ<id>_<pid>.tmp`` — **Object metadata (XML)**
   Contains an XML description of a DataContainer object. For image objects
   this includes:
   - Channel info: LUT name, bit depth, channel tag, data type
   - Dimension info: DimID, NumberOfElements, Origin, Length, Unit
   - Attachment info: image pyramid metadata, experiment names
   - Properties: user name, UUID, save flags

   The file has a small binary header (variable length, typically ~20 bytes)
   before the XML payload. The XML is encoded in **UTF-16-LE**. To find the
   XML start, search for the byte sequence ``<\x00D\x00a\x00t\x00a\x00>``
   (which is ``<Data>`` in UTF-16-LE).

   DimID values:
   - 1 = X dimension (pixels in a row)
   - 2 = Y dimension (pixels in a column)
   - 3 = Z dimension (slices in a z-stack)
   - 4 = spectral / lambda dimension
   - 10 = pyramid level or multi-stack index

2. ``V2LMSDC_MMF<id>_<offset>_<pid>.tmp`` — **Memory-Mapped File (pixel data)**
   Contains raw pixel data for the object with the matching ``<id>``. The
   ``<offset>`` indicates the byte offset within the logical data stream
   (usually ``0`` for the first/only chunk). The ``<pid>`` is the process ID
   of the DataContainer server.

   The pixel data is stored as a flat binary array with no header — just raw
   bytes. The data type and dimensions must be read from the corresponding
   OBJ file. Common formats:
   - 8-bit unsigned int (``Resolution="8"``, dtype=uint8)
   - 16-bit unsigned int (``Resolution="16"``, dtype=uint16)
   - 32-bit float (``Resolution="32"``, dtype=float32)

   Pixel ordering is row-major (C order): the X dimension increments fastest,
   then Y, then Z, then channels (BytesInc fields confirm this).

   For a 512x512 16-bit single-channel image: 512 * 512 * 2 = 524,288 bytes.

3. ``V2LMSDC_CLD<id>_<pid>.tmp`` — **Child/link data**
   Small binary files that define parent-child relationships between
   DataContainer objects. For example, linking an image to its pyramid
   thumbnail objects. Each entry is ~13 bytes containing object IDs.

4. ``<hexname>.tmp`` (e.g., ``11412D7.tmp``) — **Process memory dumps**
   These are memory-mapped regions of the DataContainer server process itself.
   They start with an ``MZ`` (PE) header, indicating they are mapped DLL or
   executable images. They are NOT pixel data and should be ignored when
   looking for microscopy images. They are typically ~26 MB each and
   accumulate over sessions.

Image pyramid structure
-----------------------
For each acquired image, LAS X creates a set of downsampled versions for
fast display in the Navigator Expert viewer. Both dimensions are halved
independently at each level, down to a minimum of ~32 pixels on the
shortest side. Examples:

- 512x512 source   -> 256x256, 128x128, 64x64, 32x32
- 1024x1024 source -> 512x512, 256x256, 128x128, 64x64, 32x32
- 1024x512 source  -> 512x256, 256x128, 128x64, 64x32
- 7536x471 source  -> 3768x235, 1884x117, 942x58, 471x29, 235x14

The pyramid levels are 8-bit Gray even when the source is 16-bit because
they are only used for screen rendering. The CLD (child/link) files
connect the full-resolution image to its pyramid children.

For z-stacks (DimID=3), each pyramid level also contains all z-slices.
So a 7536x471x10 z-stack produces pyramid levels of 3768x235x10, etc.
This means pyramids add roughly 15% storage overhead on top of the full
image data.

There may also be associated objects for:
- Histogram data (DimID=4, 1024 elements, 32-bit)
- LUT/color mapping tables (65536 elements, stored as 65536x1)
- Composite overlay images (RGBA, 4 channels)

Memory-mapped files and RAM
---------------------------
The temp files are "memory-mapped files" (MMF). This means the OS maps
the file contents directly into the process's virtual memory address
space. The program reads and writes memory addresses, and the OS
automatically syncs those pages with the file on disk.

This has important implications:

- **During live scanning**: pixel data goes into RAM first (the 50 MB
  shared memory pool ``V2LMSDC_MMF0_0_<pid>.tmp``) for maximum speed.
- **After acquisition**: the data is flushed to individual MMF temp files
  in the temp directory. These files ARE on disk but are also cached in
  RAM by the OS.
- **Multiple processes share data**: the DataContainer server writes
  pixels, and the LAS X viewer reads them — both map the same file, so
  no data copying is needed between processes.
- **The OS manages the RAM cache**: recently accessed images stay in RAM;
  older ones get evicted to disk. The program does not explicitly "load"
  or "save" — the boundary between RAM and disk is invisible.
- **Data is NOT persistent**: if you close LAS X without saving, the
  temp files may be cleaned up and the data is lost. The ``.xlef``
  project files shown in the LAS X Projects panel are in-memory
  containers, not saved files. You must explicitly save/export to keep
  your data.

In the LAS X Projects panel, each project (e.g., ``Project001.xlef``)
shows a size (e.g., 82.3 MB) — this reflects the total memory-mapped
data for that project. It is simultaneously in RAM (cached) and on disk
(in ``D:\\Temp``), but NOT saved permanently until you export it.

Pixel data format
-----------------
The MMF files contain **raw uncompressed pixel data** — no TIFF headers,
no compression, no metadata. Just a flat binary array of pixel values.
This is necessary for memory-mapping to work (random access requires
uncompressed data).

The pixel format (dimensions, dtype, byte strides) must be read from the
corresponding OBJ metadata file. Without the OBJ file, an MMF file is
just an opaque blob of bytes.

Identifying the latest image
-----------------------------
To find the most recently acquired image:
1. List all V2LMSDC_OBJ files sorted by modification time (newest first)
2. Parse the XML metadata of each, looking for ``<Image>`` elements
3. Filter for objects that have both DimID=1 (X) and DimID=2 (Y) — these
   are 2D images, not histograms or LUTs
4. Skip 8-bit Gray objects — these are pyramid thumbnails, not acquired
   images. Acquired images have a colored LUT (Green, Red, etc.) and are
   typically 16-bit.
5. Skip objects with width or height of 1 — these are LUT tables
   (e.g., 65536x1).
6. Read the corresponding MMF file to get the raw pixel data
7. Find associated pyramid levels by looking at nearby OBJ IDs with
   decreasing resolutions

The ``CurrentDCImageID`` in the LAS X log (``LAS X.log``) indicates which
DataContainer object ID is currently being displayed/acquired.

Storage considerations
----------------------
Temp files accumulate over sessions and are NOT automatically cleaned up.
Typical sizes per acquisition:

=========================  ============  ==========  ===========
Acquisition                Full image    Pyramids    Total
=========================  ============  ==========  ===========
512x512, 1ch, 16-bit       0.5 MB        0.1 MB      0.6 MB
1024x1024, 1ch, 16-bit     2 MB          0.5 MB      2.5 MB
2048x2048, 2ch, 16-bit     16 MB         4 MB        20 MB
7536x471x10z, 1ch, 16-bit  67.7 MB       11.2 MB     78.9 MB
2048x2048x50z, 2ch, 16-bit 800 MB        133 MB      933 MB
=========================  ============  ==========  ===========

The ``D:\Temp`` directory can easily grow to tens of GB over multiple
sessions. It is safe to delete its contents when LAS X is NOT running.

Key paths on this system
------------------------
- Temp dir:     ``D:\\Temp``
- DC Server:    ``C:\\Program Files\\Leica Microsystems CMS GmbH\\Services\\DataContainer\\Bin\\Service\\LMSDataContainerServerV2.exe``
- DC Server log: ``C:\\ProgramData\\Leica Microsystems\\LMSDataContainerService\\DCServerLogFileOld.log``
- LAS X log:    ``C:\\ProgramData\\Leica Microsystems\\LAS X\\LAS X.log``
- LAS X config: ``C:\\Users\\t.de\\AppData\\Roaming\\Leica Microsystems\\LAS X\\``

Usage
-----
Run this script directly to extract and display the latest acquired image::

    python lasx_temp_image_reader.py

Or import the functions for use in your own code::

    from lasx_temp_image_reader import find_latest_image, read_image_pyramid
    meta, pixels = find_latest_image("D:/Temp")
    pyramid = read_image_pyramid("D:/Temp", meta["obj_id"], meta["pid"])
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMP_DIR = Path("D:/Temp")

# Byte pattern marking the start of XML payload in OBJ files (UTF-16-LE "<Data>")
XML_START_MARKER = b"<\x00D\x00a\x00t\x00a\x00>"

# Map Resolution attribute value to numpy dtype
RESOLUTION_TO_DTYPE = {
    "8": np.uint8,
    "16": np.uint16,
    "32": np.float32,
}

# Map DimID to human-readable name
DIM_NAMES = {
    "1": "X",
    "2": "Y",
    "3": "Z",
    "4": "Spectral",
    "10": "Pyramid/Stack",
}

# Pyramid levels are always square and power-of-two, from half the source down to 32
PYRAMID_MIN_SIZE = 32


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ChannelInfo:
    """Metadata for a single image channel."""

    lut_name: str  # e.g., "Green", "Red", "Gray"
    resolution: int  # bits per pixel: 8, 16, or 32
    dtype: np.dtype  # numpy dtype corresponding to resolution
    channel_tag: int  # channel identifier
    min_val: float
    max_val: float


@dataclass
class DimensionInfo:
    """Metadata for a single image dimension."""

    dim_id: str  # "1"=X, "2"=Y, "3"=Z, etc.
    dim_name: str  # human-readable name
    num_elements: int  # number of pixels/slices
    origin: float  # physical origin in meters
    length: float  # physical extent in meters
    unit: str  # physical unit (usually "m")
    bytes_inc: int  # byte stride for this dimension


@dataclass
class ImageMetadata:
    """Complete metadata for a DataContainer image object."""

    obj_id: int  # DataContainer object ID
    pid: str  # DataContainer server process ID (may be hex)
    file_path: Path  # path to the OBJ file
    modified: datetime  # file modification time
    channels: list[ChannelInfo] = field(default_factory=list)
    dimensions: list[DimensionInfo] = field(default_factory=list)
    width: int = 0  # pixels (DimID=1)
    height: int = 0  # pixels (DimID=2)
    depth: int = 1  # slices (DimID=3), default 1 for 2D
    raw_xml: str = ""  # the full XML for debugging


# ---------------------------------------------------------------------------
# Parsing functions
# ---------------------------------------------------------------------------


def parse_obj_filename(name: str) -> tuple[int, str] | None:
    """
    Extract object ID and process ID from an OBJ filename.

    Example: ``V2LMSDC_OBJ3229_5984.tmp`` -> (3229, "5984")
    Example: ``V2LMSDC_OBJ80_8f1c.tmp``   -> (80, "8f1c")

    The PID can be decimal or hexadecimal, so it is returned as a string.
    Returns None if the filename does not match the expected pattern.
    """
    m = re.match(r"V2LMSDC_OBJ(\d+)_([0-9a-fA-F]+)\.tmp", name)
    if m:
        return int(m.group(1)), m.group(2)
    return None


def parse_mmf_filename(name: str) -> tuple[int, int, str] | None:
    """
    Extract object ID, byte offset, and process ID from an MMF filename.

    Example: ``V2LMSDC_MMF3229_0_5984.tmp`` -> (3229, 0, "5984")
    Example: ``V2LMSDC_MMF80_0_8f1c.tmp``   -> (80, 0, "8f1c")
    """
    m = re.match(r"V2LMSDC_MMF(\d+)_(\d+)_([0-9a-fA-F]+)\.tmp", name)
    if m:
        return int(m.group(1)), int(m.group(2)), m.group(3)
    return None


def read_obj_xml(file_path: Path) -> str | None:
    """
    Read an OBJ temp file and extract the XML payload.

    The OBJ file has a binary header followed by UTF-16-LE encoded XML.
    We locate the XML by searching for the ``<Data>`` marker.

    Returns the decoded XML string, or None if no XML was found.
    """
    data = file_path.read_bytes()
    idx = data.find(XML_START_MARKER)
    if idx < 0:
        return None
    return data[idx:].decode("utf-16-le", errors="replace")


def parse_image_metadata(file_path: Path) -> ImageMetadata | None:
    """
    Parse an OBJ file and return structured image metadata.

    Returns None if the file does not describe an image (no <Image> element)
    or if it lacks 2D spatial dimensions (DimID 1 and 2).
    """
    ids = parse_obj_filename(file_path.name)
    if ids is None:
        return None
    obj_id, pid = ids

    xml = read_obj_xml(file_path)
    if xml is None or "<Image" not in xml:
        return None

    meta = ImageMetadata(
        obj_id=obj_id,
        pid=pid,
        file_path=file_path,
        modified=datetime.fromtimestamp(file_path.stat().st_mtime),
        raw_xml=xml,
    )

    # Parse channels — use flexible attribute extraction to handle any order
    for tag_match in re.finditer(r"<ChannelDescription\s+([^>]+)", xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag_match.group(1)))
        res_str = attrs.get("Resolution", "8")
        meta.channels.append(
            ChannelInfo(
                lut_name=attrs.get("LUTName", "Gray"),
                resolution=int(res_str),
                dtype=RESOLUTION_TO_DTYPE.get(res_str, np.uint8),
                channel_tag=int(attrs.get("ChannelTag", "0")),
                min_val=float(attrs.get("Min", "0")),
                max_val=float(attrs.get("Max", "0")),
            )
        )

    # Parse dimensions — use flexible attribute extraction to handle any order
    for tag_match in re.finditer(r"<DimensionDescription\s+([^>]+)", xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag_match.group(1)))
        dim_id = attrs.get("DimID", "0")
        num_elements = int(attrs.get("NumberOfElements", "0"))
        meta.dimensions.append(
            DimensionInfo(
                dim_id=dim_id,
                dim_name=DIM_NAMES.get(dim_id, f"Dim{dim_id}"),
                num_elements=num_elements,
                origin=float(attrs.get("Origin", "0")),
                length=float(attrs.get("Length", "0")),
                unit=attrs.get("Unit", ""),
                bytes_inc=int(attrs.get("BytesInc", "0")),
            )
        )
        if dim_id == "1":
            meta.width = num_elements
        elif dim_id == "2":
            meta.height = num_elements
        elif dim_id == "3":
            meta.depth = num_elements

    # Only return if this is a proper 2D image (has X and Y)
    if meta.width > 0 and meta.height > 0:
        return meta
    return None


# ---------------------------------------------------------------------------
# Image reading functions
# ---------------------------------------------------------------------------


def read_mmf_pixels(
    temp_dir: Path, obj_id: int, pid: str, meta: ImageMetadata
) -> np.ndarray | None:
    """
    Read raw pixel data from the MMF file matching the given object ID.

    Returns a 2D numpy array shaped (height, width) with the appropriate
    dtype, or None if the MMF file doesn't exist or has no data.
    """
    mmf_path = temp_dir / f"V2LMSDC_MMF{obj_id}_0_{pid}.tmp"
    if not mmf_path.exists():
        return None

    raw = mmf_path.read_bytes()
    if len(raw) == 0:
        return None

    # Determine dtype from the first channel
    if meta.channels:
        dtype = meta.channels[0].dtype
    else:
        dtype = np.uint8

    pixels = np.frombuffer(raw, dtype=dtype)
    expected = meta.width * meta.height
    if len(pixels) < expected:
        return None

    return pixels[:expected].reshape(meta.height, meta.width)


def find_latest_image(
    temp_dir: Path = TEMP_DIR,
) -> tuple[ImageMetadata, np.ndarray] | None:
    """
    Find and read the most recently modified image in the temp directory.

    Scans all OBJ files, parses their metadata, filters for 2D images,
    and returns the newest one along with its pixel data.

    Returns a tuple of (metadata, pixel_array) or None if no image was found.
    """
    obj_files = sorted(
        temp_dir.glob("V2LMSDC_OBJ*"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    for obj_file in obj_files:
        meta = parse_image_metadata(obj_file)
        if meta is None:
            continue

        # Skip 1D objects (LUTs, histograms)
        if meta.width <= 1 or meta.height <= 1:
            continue

        # Skip 8-bit Gray thumbnails — these are pyramid levels, not
        # acquired images. Acquired images have a channel LUT like
        # Green, Red, Cyan, etc. or are 16-bit.
        if meta.channels:
            ch = meta.channels[0]
            if ch.lut_name == "Gray" and ch.resolution == 8:
                continue

        pixels = read_mmf_pixels(temp_dir, meta.obj_id, meta.pid, meta)
        if pixels is not None and np.any(pixels > 0):
            return meta, pixels

    return None


def read_image_pyramid(
    temp_dir: Path,
    base_obj_id: int,
    pid: str,
    source_width: int = 0,
    source_height: int = 0,
) -> list[tuple[ImageMetadata, np.ndarray]]:
    """
    Read all pyramid levels associated with an image.

    LAS X stores pyramid thumbnails in OBJ files with IDs immediately
    following the base image. We scan forward from base_obj_id + 1 looking
    for images with decreasing resolution.

    The pyramid starts at half the source resolution and halves down to 32.
    Both dimensions are halved independently, so non-square images produce
    non-square pyramids:
    - 1024x1024 source -> 512x512, 256x256, 128x128, 64x64, 32x32
    -  512x512  source -> 256x256, 128x128, 64x64, 32x32
    - 1024x512  source -> 512x256, 256x128, 128x64

    Parameters
    ----------
    source_width, source_height : int
        Dimensions of the full-resolution image. Used to determine which
        sizes are valid pyramid levels. If 0, any downsampled image is
        accepted.

    Returns a list of (metadata, pixel_array) tuples, from largest to
    smallest. The list may be empty if no pyramids are found.
    """
    # Build expected pyramid dimensions by halving width and height independently
    if source_width > 0 and source_height > 0:
        expected = set()
        w, h = source_width // 2, source_height // 2
        while w >= PYRAMID_MIN_SIZE or h >= PYRAMID_MIN_SIZE:
            expected.add((w, h))
            w //= 2
            h //= 2
    else:
        expected = None  # accept any downsampled image

    pyramid = []
    seen_sizes = set()

    for offset in range(1, 20):
        candidate_id = base_obj_id + offset
        obj_path = temp_dir / f"V2LMSDC_OBJ{candidate_id}_{pid}.tmp"
        if not obj_path.exists():
            continue

        meta = parse_image_metadata(obj_path)
        if meta is None:
            continue

        size_key = (meta.width, meta.height)
        is_valid = expected is None or size_key in expected

        if is_valid:
            # Skip duplicates
            if size_key in seen_sizes:
                continue

            pixels = read_mmf_pixels(temp_dir, candidate_id, pid, meta)
            if pixels is not None and np.any(pixels > 0):
                pyramid.append((meta, pixels))
                seen_sizes.add(size_key)

    # Sort largest first (by total pixel count)
    pyramid.sort(key=lambda item: item[0].width * item[0].height, reverse=True)
    return pyramid


def find_all_recent_images(
    temp_dir: Path = TEMP_DIR, max_age_seconds: float = 600
) -> list[tuple[ImageMetadata, np.ndarray]]:
    """
    Find all images acquired within the last ``max_age_seconds``.

    Useful for monitoring live acquisition. Returns a list of
    (metadata, pixel_array) tuples sorted by modification time (newest first).
    """
    now = datetime.now().timestamp()
    results = []

    for obj_file in temp_dir.glob("V2LMSDC_OBJ*"):
        mtime = obj_file.stat().st_mtime
        if now - mtime > max_age_seconds:
            continue

        meta = parse_image_metadata(obj_file)
        if meta is None or meta.width < 64 or meta.height < 64:
            continue

        ids = parse_obj_filename(obj_file.name)
        if ids is None:
            continue

        pixels = read_mmf_pixels(temp_dir, ids[0], ids[1], meta)
        if pixels is not None and np.any(pixels > 0):
            results.append((meta, pixels))

    results.sort(key=lambda item: item[0].modified, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


LUT_TO_CMAP = {
    "Green": "Greens",
    "Red": "Reds",
    "Blue": "Blues",
    "Cyan": "cyan",
    "Magenta": "magenta",
    "Yellow": "YlOrBr",
    "Gray": "gray",
}


def get_cmap(meta: ImageMetadata) -> str:
    """Return a matplotlib colormap name based on the channel LUT."""
    if meta.channels:
        return LUT_TO_CMAP.get(meta.channels[0].lut_name, "gray")
    return "gray"


def plot_image_with_pyramid(
    meta: ImageMetadata,
    pixels: np.ndarray,
    pyramid: list[tuple[ImageMetadata, np.ndarray]],
    save_path: Optional[Path] = None,
):
    """
    Plot the full-resolution image alongside its pyramid thumbnails.
    """
    n_panels = 1 + len(pyramid)
    fig, axes = plt.subplots(1, n_panels, figsize=(4 * n_panels, 4))
    if n_panels == 1:
        axes = [axes]

    cmap = get_cmap(meta)
    ch_name = meta.channels[0].lut_name if meta.channels else "Unknown"
    bits = meta.channels[0].resolution if meta.channels else "?"

    axes[0].imshow(pixels, cmap=cmap)
    axes[0].set_title(f"Full: {meta.width}x{meta.height} {bits}-bit {ch_name}")
    axes[0].axis("off")

    for i, (pmeta, ppixels) in enumerate(pyramid):
        axes[i + 1].imshow(ppixels, cmap=cmap)
        axes[i + 1].set_title(f"Pyramid: {pmeta.width}x{pmeta.height}")
        axes[i + 1].axis("off")

    objid = meta.obj_id
    timestamp = meta.modified.strftime("%H:%M:%S")
    fig.suptitle(
        f"LAS X Image OBJ{objid} acquired at {timestamp} — {ch_name} channel",
        fontsize=12,
    )
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Saved to {save_path}")
    else:
        plt.show()

    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    matplotlib.use("Agg")

    print(f"Scanning {TEMP_DIR} for latest LAS X image...")
    result = find_latest_image(TEMP_DIR)
    if result is None:
        print("No image found in temp directory.")
        return

    meta, pixels = result
    ch_name = meta.channels[0].lut_name if meta.channels else "Unknown"
    print(f"Found: OBJ{meta.obj_id}  {meta.width}x{meta.height}  "
          f"{meta.channels[0].resolution}-bit  {ch_name}  "
          f"modified {meta.modified.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Pixel stats: min={pixels.min()}, max={pixels.max()}, "
          f"mean={pixels.mean():.1f}")

    # Read pyramid thumbnails
    pyramid = read_image_pyramid(
        TEMP_DIR, meta.obj_id, meta.pid, meta.width, meta.height
    )
    print(f"  Pyramid levels: {[f'{m.width}x{m.height}' for m, _ in pyramid]}")

    # Find all recent images (last 10 minutes)
    all_recent = find_all_recent_images(TEMP_DIR, max_age_seconds=600)
    print(f"\nAll images from last 10 min: {len(all_recent)}")
    for m, p in all_recent:
        ch = m.channels[0].lut_name if m.channels else "?"
        print(f"  OBJ{m.obj_id}: {m.width}x{m.height} {ch} "
              f"({m.modified.strftime('%H:%M:%S')})")

    # Plot
    out = Path("C:/Users/t.de/Downloads/lasx_latest_image.png")
    plot_image_with_pyramid(meta, pixels, pyramid, save_path=out)


if __name__ == "__main__":
    main()
