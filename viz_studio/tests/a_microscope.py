"""A writer that behaves like the microscope, and has never heard of us.

The contract's whole point is that ``data/`` belongs to the acquisition side:
pixels arrive there from the microscope's own software, and our viewer is
just configuration that interacts with them. So the tests need a writer that
is NOT our publisher -- one that writes what a well-behaved acquisition
would write and nothing more: plain zarr v3 members inside one collection,
five axes, each position's place stamped in its own translation, chunk files
that never span time or channel, and a member declaration updated after each
completed write.

Deliberately, this module imports no ZMART package at all. Everything here
is numpy, zstd, and JSON -- the same things any vendor could use. If the
viewer can show what this writer produces, it can show data we did not
write, which is the future it is being built for. Keeping the two writers
strangers to each other is also what keeps the viewer honest: it may depend
on the CONTRACT, never on our publisher's habits.

The declaration doubles as the arrival signal. Watching raw files cannot
distinguish a finished frame from one still being written (and filesystem
events do not travel over network shares), so the writer declares AFTER
completing each write: the member list, and beside each member how many
moments it holds. A watcher stats one small file, and anything not yet
declared simply does not exist yet -- the same pixels-first, record-second
rule the viewer's own publisher lives by, arrived at from the other side of
the fence.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
from numcodecs import Zstd


def _atomically(path: Path, text: str) -> None:
    """Replace a small file in one step, so no reader sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, staged = tempfile.mkstemp(dir=path.parent, suffix=".writing")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(staged, path)
    except BaseException:
        if os.path.exists(staged):
            os.unlink(staged)
        raise


def _halved(plane: np.ndarray) -> np.ndarray:
    """One pyramid step: a 2x2 average, the same rule the contract states."""
    trimmed = plane[: plane.shape[0] // 2 * 2, : plane.shape[1] // 2 * 2]
    return (trimmed.reshape(trimmed.shape[0] // 2, 2,
                            trimmed.shape[1] // 2, 2)
            .mean(axis=(1, 3)).round().astype("<u2"))


class AMicroscope:
    """Writes one acquisition's ``data/`` the way the instrument would.

    ``voxel_size`` is micrometres per pixel as (y, x); ``levels`` is how many
    pyramid steps each position carries (level 0 plus halved copies);
    ``timepoints`` and ``channels`` are the room every member declares up
    front, filled frame by frame as the run records.
    """

    def __init__(self, acquisition: Path, *,
                 voxel_size: tuple[float, float] = (1.0, 1.0),
                 levels: int = 3, timepoints: int = 1,
                 channels: int = 1) -> None:
        self.collection = Path(acquisition) / "data" / "survey.ome.zarr"
        self.voxel_size = voxel_size
        self.levels = levels
        self.timepoints = timepoints
        self.channels = channels
        self._members: dict[str, int] = {}  # member name -> moments written
        if not (self.collection / "zarr.json").exists():
            self._declare()

    def image_a_position(self, name: str, pixels: np.ndarray, *,
                         location_yx: tuple[float, float],
                         timepoint: int = 0) -> Path:
        """Record one moment of one position, pixels first, declaration last.

        ``pixels`` is (channels, y, x) or (y, x) uint16. The position's
        place on the canvas goes into the member's own translation -- the
        one way every outside tool learns where a tile sits. Every chunk
        file covers exactly one moment of one channel, so recording a new
        moment only ever ADDS files.
        """
        if pixels.ndim == 2:
            pixels = pixels[None]
        member = self.collection / name
        if not (member / "zarr.json").exists():
            self._describe_a_member(member, pixels.shape[1], pixels.shape[2],
                                    location_yx)
        squeeze = Zstd(level=1)
        for channel in range(pixels.shape[0]):
            plane = pixels[channel].astype("<u2")
            for level in range(self.levels):
                chunk = (member / str(level) / "c" / str(timepoint)
                         / str(channel) / "0" / "0" / "0")
                chunk.parent.mkdir(parents=True, exist_ok=True)
                chunk.write_bytes(
                    squeeze.encode(np.ascontiguousarray(plane).tobytes()))
                plane = _halved(plane)
        self._members[name] = max(self._members.get(name, 0), timepoint + 1)
        self._declare()
        return member

    def _describe_a_member(self, member: Path, height: int, width: int,
                           location_yx: tuple[float, float]) -> None:
        """One OME-Zarr image: five axes, a pyramid, its place inside it."""
        size_y, size_x = self.voxel_size
        datasets = []
        for level in range(self.levels):
            factor = 2 ** level
            shape = [self.timepoints, self.channels, 1,
                     height // factor, width // factor]
            _atomically(member / str(level) / "zarr.json", json.dumps({
                "zarr_format": 3, "node_type": "array",
                "shape": shape,
                "data_type": "uint16",
                "chunk_grid": {"name": "regular", "configuration": {
                    "chunk_shape": [1, 1, 1, shape[3], shape[4]]}},
                "chunk_key_encoding": {"name": "default"},
                "fill_value": 0,
                "codecs": [
                    {"name": "bytes", "configuration": {"endian": "little"}},
                    {"name": "zstd",
                     "configuration": {"level": 1, "checksum": False}},
                ],
            }, indent=2) + "\n")
            datasets.append({
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale",
                     "scale": [1.0, 1.0, 1.0,
                               size_y * factor, size_x * factor]},
                    {"type": "translation",
                     "translation": [0.0, 0.0, 0.0,
                                     location_yx[0] * size_y,
                                     location_yx[1] * size_x]},
                ],
            })
        _atomically(member / "zarr.json", json.dumps({
            "zarr_format": 3, "node_type": "group",
            "attributes": {"ome": {"version": "0.5", "multiscales": [{
                "axes": [
                    {"name": "t", "type": "time"},
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space", "unit": "micrometer"},
                    {"name": "y", "type": "space", "unit": "micrometer"},
                    {"name": "x", "type": "space", "unit": "micrometer"},
                ],
                "datasets": datasets,
            }]}},
        }, indent=2) + "\n")

    def _declare(self) -> None:
        """The member list and each member's written moments, replaced last.

        This one small file is both the community's membership metadata and
        the arrival signal a watcher polls: nothing counts until it appears
        here, and everything named here is complete.
        """
        _atomically(self.collection / "zarr.json", json.dumps({
            "zarr_format": 3, "node_type": "group",
            "attributes": {"zmart": {
                "schema": "zmart-collection/1",
                "members": sorted(self._members),
                "moments": dict(sorted(self._members.items())),
            }},
        }, indent=2) + "\n")
