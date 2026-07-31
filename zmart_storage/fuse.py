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

from .canvas import copies_for_a_canvas


def fuse(
    run: str | Path,
    into: str | Path,
    *,
    where_they_meet: str = "blend",
    chunk: int = 256,
    levels: int | None = None,
) -> Path:
    """Join a run's images into a single OME-Zarr image.

    Args:
        run: the folder the run was written to. A run that kept the overlap
            between its tiles holds several numbered images — ``overview_part0``
            to ``overview_part3``, say — and all of them are read and joined.
        into: where to write the joined image. This has to be somewhere outside
            the run's own folder — beside it is the natural place — because the
            joined image is made by emptying whatever is already there, and
            because everything ending in ``.ome.zarr`` inside a run's folder is
            read as one of that run's images. Anything already at this path is
            replaced.
        where_they_meet: ``"blend"``, ``"first"`` or ``"mean"`` — what to do
            where two tiles recorded the same place. See the note at the top of
            this module.
        chunk: how large a piece of the joined image should be, in y and x.
        levels: how many progressively smaller copies to keep. These are what let
            a large picture feel light when it is zoomed out, and normally this is
            left out so that the number can be worked out from how large the
            joined image turns out to be — the same rule the writer follows while
            a run is going, described below. Give a number here if you have a
            reason to, and it is used exactly as asked.

    Returns:
        The path of the joined image.

    Raises:
        FileNotFoundError: if the folder holds no images from a run.
        ValueError: if ``where_they_meet`` is not one of the three above, or if
            the joined image was asked to be written inside the run it is made
            from — which would destroy the run instead of joining it.
    """
    if where_they_meet not in ("blend", "first", "mean"):
        raise ValueError(
            f"{where_they_meet!r} is not a way of handling the places where two "
            "tiles recorded the same specimen. There are three to choose from, "
            "and which one is right depends on what the picture is for:\n\n"
            "  'blend' fades one tile into the other across the strip they share, "
            "which hides the join. This is usually the one to look at.\n"
            "  'first' keeps whichever tile the run wrote first, so every voxel "
            "is one recording exactly as the camera made it. This is the one to "
            "use when the numbers themselves matter.\n"
            "  'mean' averages the two recordings, which is a little less noisy "
            "but smears if the tiles are not perfectly aligned."
        )

    run = Path(run)
    sources = sorted(run.glob("*.ome.zarr"))
    if not sources:
        raise FileNotFoundError(
            f"{run} holds no OME-Zarr images, so there is nothing here to join. "
            "A run's folder holds one image folder per acquisition type — "
            "'overview.ome.zarr', say — or a numbered set of them when the run "
            "kept the overlap between its tiles. Check that this is the run's own "
            "folder rather than the folder holding it."
        )

    into = Path(into)
    # Asked before anything at all is opened, because making the joined image
    # begins by emptying whatever is at that path.
    _refuse_to_write_the_joined_image_into_the_run(run, into, sources)

    groups = [zarr.open_group(str(path), mode="r") for path in sources]
    first = groups[0]["0"]
    shape, dtype = first.shape, first.dtype

    # How many progressively smaller copies the joined picture should keep, when
    # the caller has not said. This follows the same rule the writer uses while a
    # run is going -- see :func:`zmart_storage.canvas.copies_for_a_canvas` -- and
    # it is worth saying why, because joining is a different path and the two
    # could easily have drifted apart.
    #
    # The reason they should not is that what is done with the answer is
    # identical. Anything showing one of these images reads the whole of the
    # smallest copy, for every colour, before it draws anything at all, and it
    # does that again at every zoom. A joined picture as wide as a stage keeping
    # only three copies leaves that smallest copy some twenty-five thousand
    # voxels across, which is roughly nineteen thousand pieces to fetch before
    # the first picture appears; letting the halving continue until the smallest
    # copy is about a thousand voxels brings the same view down to about thirty.
    # The joined picture is the one meant to be kept, archived and looked at for
    # years, so if either path deserves to open quickly it is this one.
    #
    # Only the last two axes are the specimen's y and x, whatever an image
    # declares in front of them, and those are the only axes the copies shrink.
    # The depth handed over here is therefore a placeholder that the rule does
    # not look at.
    if levels is None:
        levels = copies_for_a_canvas((1, shape[-2], shape[-1]))

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


# -- not joining a run on top of itself ----------------------------------------


def _refuse_to_write_the_joined_image_into_the_run(
    run: Path, into: Path, sources: list[Path]
) -> None:
    """Stop the joined image from being written on top of the run it is made from.

    Joining begins by emptying whatever is already at the target path, and it
    reads the run's images as it goes. So if the target is one of those images —
    or the run's folder itself, or a place inside one of the images — the run is
    emptied before a single plane of it has been read. What follows is the worst
    kind of failure: the joining stops part way with a complaint about missing
    description, no joined image is produced, and the run it was made from is
    gone. Asked for directly, ``fuse(run, run / "overview.ome.zarr")`` did exactly
    that, and ``fuse(run, run)`` replaced the whole run folder with an empty one.

    A target sitting beside the run's images rather than on top of them is
    refused too, though nothing would be destroyed by it. The reason is that a
    run's folder is read by gathering everything in it whose name ends in
    ``.ome.zarr``, so a joined image left there becomes, from then on, one of that
    run's own images: the viewer would show it as part of the acquisition, and
    joining the run a second time would read the first joined image back in as
    though it were acquired data. Keeping the joined image outside the run's
    folder avoids all of that, and costs nothing.
    """
    run_here = run.resolve()
    into_here = into.resolve()
    somewhere_else = run.parent / (run.name + "_joined.ome.zarr")

    def is_inside_or_the_same(inner: Path, outer: Path) -> bool:
        return inner == outer or outer in inner.parents

    what_would_go = None
    if is_inside_or_the_same(run_here, into_here):
        # The target is the run folder itself, or a folder holding it, so
        # emptying it would take every image the run wrote.
        what_would_go = f"the whole run folder {run}"
    else:
        for source in sources:
            if is_inside_or_the_same(into_here, source.resolve()):
                what_would_go = f"the run's own image {source.name}"
                break

    if what_would_go is not None:
        raise ValueError(
            f"the joined image was asked for at {into}, which would empty "
            f"{what_would_go}. Joining starts by emptying whatever is at the "
            "target path and only then reads the run, so the run would be "
            "destroyed before it could be read, and no joined image would be "
            "produced at all.\n\n"
            f"Write the joined image somewhere outside the run's folder — "
            f"{somewhere_else} would do — so that the run it was made from is "
            "still there afterwards. The run's images are worth keeping: they are "
            "the only place both recordings of every shared strip exist, which is "
            "what a stitcher needs in order to work out where the stage really "
            "put each tile."
        )

    if is_inside_or_the_same(into_here, run_here):
        raise ValueError(
            f"the joined image was asked for at {into}, which is inside the run "
            f"folder {run} that it is made from. Nothing would be destroyed by "
            "that, but a run's folder is read by gathering every image in it, so "
            "a joined image left there would become one of that run's own images "
            "from then on: the viewer would draw it as part of the acquisition, "
            "and joining the run again would read it back in as though it had "
            "been acquired.\n\n"
            f"Write it outside the run's folder instead — {somewhere_else} would "
            "do — which also keeps the run plainly separate from the picture made "
            "from it."
        )


# -- deciding what to do where two tiles recorded the same place ---------------


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


# -- the smaller copies, and the description that names them -------------------


def _write_smaller_copies(group, full, levels: int, chunk: int) -> None:
    """Build the progressively smaller copies from the finished full-size one.

    Each copy is read out of the full-size picture rather than out of the copy
    above it, so a deeper pyramid means a few more passes over the whole image.
    That is worth knowing but it is not worth avoiding here: this runs once, when
    the run is over and nobody is waiting at the microscope, whereas the writer
    pays for its copies on every tile that lands. The cost of keeping more of them
    therefore falls in the one place where it is cheapest to pay.
    """
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
