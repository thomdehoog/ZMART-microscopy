"""Joining a run's images back into one picture, once the run is over.

A run written by :mod:`zmart_storage.canvas` is spread over a few images so that
overlapping tiles never overwrite each other. That is the right shape while the
microscope is running, and it is the shape that keeps every pixel — but it is not
the right thing to archive or to hand to a colleague, because it is several files
that only make sense together, and anything opening them has to know they belong
to one specimen.

So when a run is finished there is a second, optional artefact worth making: **one
image, with the overlapping strips joined up**. Any tool can open it without
knowing how the acquisition was organised.

The point of doing this *afterwards* rather than while writing is that by then
both recordings of every shared strip exist, so there is a real choice about what
to do with them. During the run there was no choice: whichever tile arrived second
would simply have replaced the first.

What to do where two tiles meet
-------------------------------

Three ways are offered, and which is right depends on what the picture is for.

``"blend"`` fades smoothly from one tile to the other across the shared strip.
This is usually what you want to look at. Tile edges are the dimmest part of an
image — the illumination falls off and, in a light sheet, the sheet is least even
there — so a hard join shows as a visible grid. Fading across the strip hides it.

``"first"`` keeps whichever tile the run wrote first and ignores the rest. This
is the honest choice when the numbers matter more than the appearance: every voxel
then comes from exactly one recording, unaltered, rather than being a mixture of
two.

``"mean"`` averages the two recordings. Slightly less noisy than either alone,
since the two are independent measurements of the same place, but it will smear
if the tiles are not perfectly aligned.

None of these corrects the alignment. They join the tiles up where the stage said
they were. Working out where the stage *actually* put them is a separate and
harder job, and it is the reason the overlap was kept in the first place — the two
recordings of a shared strip are what a stitcher compares. That comparison stays
possible for as long as the run's own images are kept, so fusing does not close
the door on it; it only produces a picture that does not wait for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr


def fuse(
    run: str | Path,
    into: str | Path,
    *,
    where_they_meet: str = "blend",
    chunk: int = 256,
    levels: int = 3,
) -> Path:
    """Join a run's images into a single OME-Zarr image.

    Args:
        run: the folder the run was written to, holding ``canvas0.ome.zarr`` and
            its siblings.
        into: where to write the joined image. Replaced if it already exists.
        where_they_meet: ``"blend"``, ``"first"`` or ``"mean"`` — what to do
            where two tiles recorded the same place. See the note at the top of
            this module.
        chunk: how large a piece of the joined image should be, in y and x.
        levels: how many progressively smaller copies to keep.

    Returns:
        The path of the joined image.

    Raises:
        FileNotFoundError: if the folder holds no images from a run.
        ValueError: if ``where_they_meet`` is not one of the three above.
    """
    if where_they_meet not in ("blend", "first", "mean"):
        raise ValueError(
            f"'{where_they_meet}' is not one of 'blend', 'first' or 'mean'"
        )

    run = Path(run)
    sources = sorted(run.glob("*.ome.zarr"))
    if not sources:
        raise FileNotFoundError(
            f"{run} holds no images from a run — expected canvas0.ome.zarr and so on"
        )

    groups = [zarr.open_group(str(path), mode="r") for path in sources]
    first = groups[0]["0"]
    shape, dtype = first.shape, first.dtype

    into = Path(into)
    joined = zarr.open_group(str(into), mode="w", zarr_format=2)
    # One piece per plane in every axis except the last two, whatever those axes
    # happen to be -- a run of a single moment has no time axis, so the number of
    # them is not fixed.
    full = joined.create_array(
        "0", shape=shape,
        chunks=(*(1,) * (len(shape) - 2), chunk, chunk), dtype=dtype,
        chunk_key_encoding={"name": "v2", "separator": "/"},
    )

    # Worked through one plane at a time. A run is very often larger than memory,
    # and a plane of it is not, so this keeps the joining possible on an ordinary
    # machine rather than only on the one with the most memory in the building.
    for at in np.ndindex(*shape[:-2]):
        planes = [np.asarray(g["0"][at]) for g in groups]
        full[at] = _join(planes, where_they_meet, dtype)

    _write_smaller_copies(joined, full, levels, chunk)
    _describe(into, sources[0], levels)
    return into


def _join(planes: list[np.ndarray], how: str, dtype) -> np.ndarray:
    """Combine the same plane from each of the run's images into one.

    A voxel is empty in every image but the one whose tile covered it, so most of
    the work is simply "take whichever image has something here". Only in the
    shared strips does more than one have a value, and that is where the choice
    matters.
    """
    written = [plane != 0 for plane in planes]
    # How many recordings exist at each place: 0 where nothing was imaged, 1 in
    # the ordinary interior of a tile, 2 or more in a shared strip.
    depth_of_cover = np.sum(written, axis=0)

    if how == "first":
        out = np.zeros_like(planes[0])
        # Later images only fill in what earlier ones left empty, so the earliest
        # recording of any place is the one that survives.
        for plane, has in zip(reversed(planes), reversed(written), strict=True):
            out = np.where(has, plane, out)
        return out

    total = np.zeros(planes[0].shape, dtype=np.float64)
    weight = np.zeros(planes[0].shape, dtype=np.float64)

    for plane, has in zip(planes, written, strict=True):
        if how == "mean":
            here = has.astype(np.float64)
        else:
            # Fade each tile out towards its own edges, so that across a shared
            # strip one tile is rising while the other falls and the join cannot
            # be seen. Away from the strips only one tile has any weight at all,
            # so its own value comes through untouched.
            here = _fade_towards_the_edges(has)
        total += plane.astype(np.float64) * here
        weight += here

    out = np.zeros(planes[0].shape, dtype=np.float64)
    somewhere = weight > 0
    out[somewhere] = total[somewhere] / weight[somewhere]
    # Nothing was imaged here at all, which is the ordinary state of most of a
    # generously declared canvas.
    out[depth_of_cover == 0] = 0
    return np.rint(out).astype(dtype)


def _fade_towards_the_edges(has: np.ndarray) -> np.ndarray:
    """A weight that is high in the middle of a written region and low at its rim.

    Worked out from the picture itself rather than from a list of where the tiles
    were, so it needs nothing to be remembered about the run. For each written
    voxel it is the distance to the nearest unwritten one, which rises steadily
    from the edge of a tile towards its middle — exactly the shape wanted.
    """
    try:
        from scipy.ndimage import distance_transform_edt

        return distance_transform_edt(has) + 1e-6
    except ImportError:
        # Without SciPy a plain average is a reasonable stand-in: the join shows
        # as a faint seam rather than being invisible, and nothing is lost.
        return has.astype(np.float64)


def _write_smaller_copies(group, full, levels: int, chunk: int) -> None:
    """Build the progressively smaller copies from the finished full-size one."""
    for level in range(1, levels):
        factor = 2 ** level
        shape = (*full.shape[:-2],
                 max(1, full.shape[-2] // factor), max(1, full.shape[-1] // factor))
        array = group.create_array(
            str(level), shape=shape,
            chunks=(*(1,) * (len(shape) - 2),
                    min(chunk, shape[-2]), min(chunk, shape[-1])),
            dtype=full.dtype,
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )
        for at in np.ndindex(*shape[:-2]):
            plane = np.asarray(full[at])
            array[at] = plane[::factor, ::factor][:shape[-2], :shape[-1]]


def _describe(into: Path, like: Path, levels: int) -> None:
    """Give the joined image the run's own axes, voxel size and channels.

    Copied from one of the run's images rather than worked out again, so the
    joined picture sits in the same place in the world, is the same size in
    microns, and names its channels the same way.
    """
    original = json.loads((like / ".zattrs").read_text(encoding="utf-8"))
    multiscale = original["multiscales"][0]
    scale = multiscale["datasets"][0]["coordinateTransformations"][0]["scale"]

    datasets = []
    for level in range(levels):
        factor = 2 ** level
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [{
                "type": "scale",
                # Only y and x shrink between levels, and they are the last two
                # axes whatever else the image declares -- a run of a single
                # moment has no time axis, so counting from the front would break.
                "scale": [*scale[:-2], scale[-2] * factor, scale[-1] * factor],
            }],
        })

    (into / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": multiscale["axes"],
            "datasets": datasets,
            "coordinateTransformations": multiscale.get(
                "coordinateTransformations", []
            ),
        }],
        **({"omero": original["omero"]} if "omero" in original else {}),
    }, indent=2), encoding="utf-8")
