"""A run's images described as one scene, and compiled into what the viewer draws.

A smart-microscopy run is not one picture. It is a few hundred positions, a
seamless overview built over them, a raw overview that keeps every overlapping
pixel, and — later — whatever a stitcher or an analysis produced from those. All
of them describe the same specimen, and the only thing that lets a viewer put
them on top of one another correctly is a written statement of where each one
sits in one shared set of coordinates.

That statement is a **scene**. The word comes from OME-Zarr, which is adopting it
in version 0.6: a group above several images declaring how they sit together,
rather than one enormous rectangular array that every tile has to be forced into.
The closing section of
``docs/design/live-position-timepoint-publication-decisions.md`` explains why the
idea is worth adopting now while the file format for it is not: the released
specification is still 0.5, our analysis library cannot read 0.6 at all, and
Neuroglancer's reader has never heard of scenes. So the semantics live here, in
Python, shaped so that writing them out as 0.6 metadata later is a translation
rather than a rewrite.

The rule this module exists to protect
--------------------------------------

**Never hand the drawing engine one source per position.**

This is not a style preference. Neuroglancer builds a drawing layer for every
source it is given, and every one of those layers takes part in every frame,
whether or not anything of it is on screen. That cost is paid forever, sixty
times a second, for as long as the viewer is open. It was measured on this
project's own harness: a thousand positions handed over separately drew
twenty-four frames in five seconds, where one linked image over the same files
managed 255. The like-for-like table in
``docs/design/zmart-ome-zarr-recipe.md`` shows the same thing from the other
side — at six hundred positions, 1,547 metadata requests before the first pixel
against 120, and a worst frame of 733 milliseconds against 17.

So the scene may hold five thousand position images, because that is the truth
about the experiment. What it compiles to is **one source per view** — one for
the seamless overview, one for the raw overview, one for each derived product —
and never one per position. The positions are what those views are made of; they
are not separate things to draw.

The other rule, which looks smaller and is not
---------------------------------------------

**The revision goes in a field beside the source, never inside its address.**

It is tempting to make each commit produce a new URL — ``.../overview.zarr?rev=7``
— because that certainly defeats any stale cache. It is also ruinous. A drawing
engine treats a changed address as a brand new data source; it builds a new layer
for it and has no reason to ever let the old one go. A hundred positions over a
hundred commits is ten thousand layers, and the viewer dies of exactly the cost
described above, only slowly enough that it looks like a memory leak rather than
a design mistake.

The address of a store is therefore stable for the whole run. The revision
travels beside it, as a field the frontend compares against what it last drew, so
that it can refresh the one source that actually changed and leave everything
else — the camera, the contrast, the annotations, the other open datasets —
exactly where the operator left them.

Why the two overviews must never be confused
--------------------------------------------

A run has two overviews and they are genuinely different pictures.

The **seamless** one shows each piece of specimen once: where two tiles overlap,
one of them was chosen and the other's copy of that strip is not shown. It is the
quick-look picture an operator navigates by.

The **raw** one keeps every pixel every tile recorded, overlaps included. It is
what you look at when you want to see what the microscope actually did — whether
two tiles agree, whether the illumination fell off at an edge.

They are built from the same files, they have the same voxel size, and they carry
the same channel names. Anything that decides what to draw by comparing only
those two things will quietly fold them into one layer with one contrast control,
and the operator will never be told that half of what they asked for is missing.
So the role each image plays is part of its identity here, from the scene all the
way through to the compiled layer name.

What is in this file
--------------------

:class:`CoordinateSystem`
    The run's shared coordinates: which axes there are and what their units mean.

:class:`AffinePlacement`
    Where one image sits and how it is scaled. An *affine transform* is simply the
    recipe for that: multiply each pixel coordinate by a scale to turn pixels into
    micrometres, then add an offset to move the image to its place.

:class:`SceneImage` and :class:`Scene`
    One image and its placement, and the whole related set of them.

:func:`build_the_scene`
    Builds that set from a sealed acquisition profile and a layout snapshot.

:func:`compile_for_neuroglancer`
    Turns the scene into the sources, layers and transforms the viewer consumes,
    with each source carrying the revision it was compiled against.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .manifest import CommittedState
from .model import (
    AcquisitionProfile,
    FrozenMap,
    GridCell,
    SceneLayoutRevision,
    ZmartLiveError,
)

__all__ = [
    "POSITION_ROLE",
    "SCENE_ROLES",
    "VIEW_ROLES",
    "AffinePlacement",
    "CompiledLayer",
    "CompiledSource",
    "CoordinateSystem",
    "DerivedView",
    "NeuroglancerScene",
    "Scene",
    "SceneImage",
    "SceneRefused",
    "build_the_scene",
    "compile_for_neuroglancer",
]


class SceneRefused(ZmartLiveError):
    """The scene does not describe something a viewer could draw.

    Refusing early is kinder than compiling something malformed. A scene that
    names an image twice, or whose view claims to show a position nothing knows
    about, would still produce a picture — just one with a piece missing or a
    piece drawn twice, and neither announces itself on screen.
    """


# ---------------------------------------------------------------------------
# The parts an image can play
# ---------------------------------------------------------------------------

#: An image that is one acquired position: the canonical pixels, complete with
#: every overlapping pixel the microscope recorded.
POSITION_ROLE = "position"

#: The parts that are *presentations* — images a viewer is actually given to
#: draw. ``"seamless"`` shows each piece of specimen once; ``"non_seamless"``
#: keeps every overlapping pixel; ``"derived"`` is anything computed afterwards,
#: such as a stitched product or a segmentation.
VIEW_ROLES = ("seamless", "non_seamless", "derived")

#: Every part an image in a scene may play.
SCENE_ROLES = (POSITION_ROLE, *VIEW_ROLES)

#: How each role is written when a person has to read it, on a layer name or in a
#: log. The stored role strings stay machine-plain; these are for eyes.
ROLE_IN_WORDS = {
    POSITION_ROLE: "position",
    "seamless": "seamless",
    "non_seamless": "raw overlap",
    "derived": "derived",
}

#: What the axes of a microscope image usually measure. Space is in whatever unit
#: the profile records, time is in seconds, and a channel has no unit at all
#: because a channel is a name rather than a length.
_NON_SPATIAL_UNITS = {"t": "second", "c": ""}

_SCHEMA = "zmart-live-neuroglancer-scene/1"


def _frozen_number_map(values: Mapping[str, float] | None) -> FrozenMap:
    """Turn an axis-keyed table of numbers into one that cannot be edited afterwards."""
    if values is None:
        return FrozenMap()
    return FrozenMap({str(axis): float(size) for axis, size in values.items()})


# ---------------------------------------------------------------------------
# The shared coordinates everything is placed in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoordinateSystem:
    """The one set of coordinates every image in a run is placed against.

    Without this, "the tile is at 4096" means nothing: 4096 of what, measured from
    where, along which axis? Naming the axes and their units once, for the whole
    run, is what lets a position, an overview and a segmentation be put on top of
    one another and line up.

    Axis order matters and is preserved exactly as the acquisition declared it.
    Reordering axes is one of the classic ways an image analysis goes wrong
    without complaining: the picture still appears, it is simply transposed, and
    the person looking at it has no way to tell.
    """

    name: str
    axes: tuple[str, ...]
    units: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))
        if not isinstance(self.units, FrozenMap):
            object.__setattr__(self, "units", FrozenMap(self.units))
        if not self.axes:
            raise SceneRefused(
                "A coordinate system with no axes cannot place anything. It needs at "
                "least the axes the acquisition writes, such as z, y and x."
            )
        for axis in self.units:
            if axis not in self.axes:
                raise SceneRefused(
                    f"The coordinate system gives a unit for axis '{axis}', which is "
                    f"not one of its axes {self.axes}."
                )

    def unit_of(self, axis: str) -> str:
        """What one step along ``axis`` means, or an empty string when it means nothing."""
        return self.units.get(axis, "")

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk or sending to the browser."""
        return {
            "name": self.name,
            "axes": list(self.axes),
            "units": [self.unit_of(axis) for axis in self.axes],
        }


# ---------------------------------------------------------------------------
# Where an image sits and how it is scaled
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AffinePlacement:
    """The recipe for where one image sits in the shared coordinates.

    An *affine transform* sounds forbidding and is not. For each axis it holds two
    numbers: a **scale**, which turns a pixel count into a real distance, and a
    **translation**, which slides the whole image to where it belongs. Reading a
    voxel at pixel ``x`` therefore means the specimen at ``x * scale + translation``
    micrometres.

    That is enough for everything an upright, axis-aligned microscope produces,
    which is nearly all of this facility's work. Deskewed light-sheet data and
    rotated multi-view acquisitions need the full matrix with off-diagonal terms;
    this class writes the matrix out in :meth:`matrix` so that the compiled output
    already has the shape those would need, even though nothing fills the corners
    in today.

    Axes are named, and every number is stored against its axis name rather than
    its position in a list, so that an axis order can never be silently swapped
    on the way through.
    """

    axes: tuple[str, ...]
    scale: FrozenMap = field(default_factory=FrozenMap)
    translation: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))
        if not self.axes:
            raise SceneRefused(
                "A placement needs to say which axes it describes; this one names none."
            )
        for name, given in (("scale", self.scale), ("translation", self.translation)):
            for axis in given:
                if axis not in self.axes:
                    raise SceneRefused(
                        f"The placement gives a {name} for axis '{axis}', which is not "
                        f"among the axes it describes, {self.axes}."
                    )
        # An axis nobody said anything about is left exactly as it is: scaled by
        # one and moved by nothing. Filling these in here means every later reader
        # gets a complete answer and never has to guess what a missing axis meant.
        object.__setattr__(
            self,
            "scale",
            _frozen_number_map({axis: self.scale.get(axis, 1.0) for axis in self.axes}),
        )
        object.__setattr__(
            self,
            "translation",
            _frozen_number_map(
                {axis: self.translation.get(axis, 0.0) for axis in self.axes}
            ),
        )
        for axis, size in self.scale.items():
            if size == 0:
                raise SceneRefused(
                    f"The placement scales axis '{axis}' by zero, which would flatten "
                    f"the image to nothing along that axis. A voxel size of zero "
                    f"usually means it was never recorded; leave it out and it will "
                    f"be taken as one."
                )

    def scale_row(self) -> tuple[float, ...]:
        """The scales, in the placement's own axis order."""
        return tuple(self.scale[axis] for axis in self.axes)

    def translation_row(self) -> tuple[float, ...]:
        """The offsets, in the placement's own axis order."""
        return tuple(self.translation[axis] for axis in self.axes)

    def matrix(self) -> tuple[tuple[float, ...], ...]:
        """The same placement written out as rows of numbers.

        One row per axis. Each row holds a scale for every input axis — all zero
        except its own — and finishes with the offset. This is the form a viewer
        wants, and it is also the form that could one day carry a rotation or a
        shear without anything above it changing shape.
        """
        rows = []
        for index, axis in enumerate(self.axes):
            row = [0.0] * len(self.axes)
            row[index] = self.scale[axis]
            row.append(self.translation[axis])
            rows.append(tuple(row))
        return tuple(rows)

    def applied_to(self, point: Mapping[str, float]) -> dict[str, float]:
        """Where a point given in this image's own pixels lands on the specimen.

        Axes the point does not mention are taken as zero, so asking about a tile's
        own corner is simply ``placement.applied_to({})``.
        """
        return {
            axis: float(point.get(axis, 0.0)) * self.scale[axis] + self.translation[axis]
            for axis in self.axes
        }

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk or sending to the browser."""
        return {
            "axes": list(self.axes),
            "scale": list(self.scale_row()),
            "translation": list(self.translation_row()),
            "matrix": [list(row) for row in self.matrix()],
        }


# ---------------------------------------------------------------------------
# One image in the scene
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneImage:
    """One image belonging to a run, and where it sits.

    An image here is a real store on disk with real pixels: an acquired position,
    an overview built over those positions, or something computed afterwards. What
    makes it part of a *scene* is that it carries a placement into the run's shared
    coordinates, so it can be drawn together with the others.

    ``role`` says what part this image plays, and it is part of the image's
    identity rather than a label hung on the side. Two overviews of the same run
    can have the same name, the same voxel size and the same channels and still be
    different pictures; the role is what keeps them apart, from here through to the
    layer the operator sees.

    ``draws`` is how a presentation says which positions it is made of. A position
    leaves it empty, because a position is made of specimen rather than of other
    images. It matters for two reasons: it is how the compiled source works out
    which committed revision it is showing, and it is the record that a view really
    does cover the positions it claims to.

    ``selector_axis`` names an extra dimension the viewer can step through to
    choose between tiles at the same place. The raw overlap view needs one, because
    two tiles genuinely recorded different measurements of the same specimen and a
    single grey value cannot show both at once. The seamless view has no such
    dimension: it already chose.
    """

    image_id: str
    role: str
    path: str
    axes: tuple[str, ...]
    voxel_size: FrozenMap = field(default_factory=FrozenMap)
    voxel_unit: str = "micrometer"
    placement: AffinePlacement | None = None
    channels: tuple[str, ...] = ()
    draws: tuple[str, ...] = ()
    position_id: str | None = None
    component_id: str | None = None
    cell: GridCell | None = None
    kind: str = "image"
    selector_axis: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))
        object.__setattr__(self, "channels", tuple(self.channels))
        object.__setattr__(self, "draws", tuple(self.draws))
        object.__setattr__(self, "voxel_size", _frozen_number_map(self.voxel_size))
        if self.role not in SCENE_ROLES:
            raise SceneRefused(
                f"'{self.role}' is not a part an image can play in a scene. The parts "
                f"are {', '.join(SCENE_ROLES)}."
            )
        if not self.image_id:
            raise SceneRefused("Every image in a scene needs a name to be referred to by.")
        if self.placement is None:
            object.__setattr__(self, "placement", AffinePlacement(axes=self.axes))
        if tuple(self.placement.axes) != self.axes:
            raise SceneRefused(
                f"Image '{self.image_id}' declares axes {self.axes} but its placement "
                f"describes {tuple(self.placement.axes)}. The two have to agree, "
                f"including their order, or the image will be drawn transposed and "
                f"nothing will say so."
            )
        if self.role == POSITION_ROLE and self.draws:
            raise SceneRefused(
                f"Position '{self.image_id}' claims to show {len(self.draws)} other "
                f"positions. A position holds the specimen's own pixels; it is the "
                f"overviews that are made of positions."
            )

    @property
    def identity(self) -> str:
        """What this image is called when something has to refer to exactly it.

        The role comes first and is genuinely load-bearing. A run's two overviews
        share a name on purpose — they are two presentations of one overview — so
        the role is the only thing that keeps ``seamless/overview`` and
        ``non_seamless/overview`` from becoming one picture with one set of
        controls.
        """
        return f"{self.role}/{self.image_id}"

    @property
    def is_a_view(self) -> bool:
        """True when this image is something the viewer is given to draw."""
        return self.role in VIEW_ROLES

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "image_id": self.image_id,
            "role": self.role,
            "identity": self.identity,
            "path": self.path,
            "axes": list(self.axes),
            "voxel_size": {axis: self.voxel_size.get(axis, 1.0) for axis in self.axes},
            "voxel_unit": self.voxel_unit,
            "placement": self.placement.to_json(),
            "channels": list(self.channels),
            "draws": list(self.draws),
            "position_id": self.position_id,
            "component_id": self.component_id,
            "cell": None if self.cell is None else self.cell.to_json(),
            "kind": self.kind,
            "selector_axis": self.selector_axis,
        }


# ---------------------------------------------------------------------------
# The whole related set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    """Every image belonging to one run, placed in one shared set of coordinates.

    This is the honest description of the experiment: five thousand positions are
    five thousand images here, because that is what was acquired. Nothing about
    this object is arranged for a viewer's convenience, and it should not be — the
    arranging happens in :func:`compile_for_neuroglancer`, which is where the
    drawing engine's costs live.

    A scene is frozen, like everything else in this package. A result that says "I
    used layout revision 7" needs revision 7 to still mean today what it meant when
    the result was written.
    """

    scene_id: str
    run_id: str
    layout_revision: int
    profile_id: str
    coordinate_system: CoordinateSystem
    images: tuple[SceneImage, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", tuple(self.images))
        if self.layout_revision < 0:
            raise SceneRefused(
                f"Layout revisions start at zero; this scene claims {self.layout_revision}."
            )
        seen: set[str] = set()
        for image in self.images:
            if image.identity in seen:
                raise SceneRefused(
                    f"'{image.identity}' appears twice in this scene. Each image is "
                    f"described exactly once; two descriptions of one image would let "
                    f"the viewer draw it twice, at two different places, with nothing "
                    f"to say which was meant."
                )
            seen.add(image.identity)
        known_positions = {
            image.image_id for image in self.images if image.role == POSITION_ROLE
        }
        for image in self.images:
            for position_id in image.draws:
                if position_id not in known_positions:
                    raise SceneRefused(
                        f"The {ROLE_IN_WORDS[image.role]} view '{image.image_id}' says "
                        f"it shows position '{position_id}', but this scene holds no "
                        f"such position. A view that names a position nothing knows "
                        f"about would leave a hole in the picture and report nothing."
                    )

    # -- looking things up ---------------------------------------------------

    def image(self, identity: str) -> SceneImage:
        """One image, by its ``role/name`` identity."""
        for candidate in self.images:
            if candidate.identity == identity:
                return candidate
        raise SceneRefused(
            f"This scene has no image called '{identity}'. It holds "
            f"{[image.identity for image in self.images][:6]}"
            f"{' and more' if len(self.images) > 6 else ''}."
        )

    def with_role(self, role: str) -> tuple[SceneImage, ...]:
        """Every image playing one part, in the order the scene lists them."""
        if role not in SCENE_ROLES:
            raise SceneRefused(
                f"'{role}' is not a part an image can play. The parts are "
                f"{', '.join(SCENE_ROLES)}."
            )
        return tuple(image for image in self.images if image.role == role)

    @property
    def positions(self) -> tuple[SceneImage, ...]:
        """The acquired positions: the run's canonical pixels."""
        return self.with_role(POSITION_ROLE)

    @property
    def views(self) -> tuple[SceneImage, ...]:
        """The presentations — the images a viewer is actually given to draw."""
        return tuple(image for image in self.images if image.is_a_view)

    @property
    def roles(self) -> tuple[str, ...]:
        """Which parts are played in this scene at all, in a settled order."""
        return tuple(sorted({image.role for image in self.images}))

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk.

        This is the whole truth about the run and it is correspondingly large — one
        entry per position. It is not what goes to the browser; that is
        :meth:`NeuroglancerScene.to_json`, which is small on purpose.
        """
        return {
            "schema": "zmart-live-scene/1",
            "scene_id": self.scene_id,
            "run_id": self.run_id,
            "layout_revision": self.layout_revision,
            "profile_id": self.profile_id,
            "coordinate_system": self.coordinate_system.to_json(),
            "images": [image.to_json() for image in self.images],
        }


# ---------------------------------------------------------------------------
# Building the scene from a run's own records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedView:
    """Something computed from the run afterwards, asking to be shown beside it.

    A stitched product, a segmentation, a probability map. It is described rather
    than built here, because whatever made it already knows where it lives and how
    coarse it is; the scene only needs to know enough to place it.

    Leave ``voxel_size`` out and the run's own voxel size is used, which is right
    for anything computed at full resolution. A coarser product says so, and a
    product that does not begin at the run's origin gives a ``world_offset`` in the
    same units as the voxel size rather than in its own pixels — that is much
    easier to check by eye against a stage coordinate.
    """

    image_id: str
    path: str
    channels: tuple[str, ...] = ("derived",)
    voxel_size: Mapping[str, float] | None = None
    world_offset: Mapping[str, float] | None = None
    kind: str = "image"
    draws: tuple[str, ...] = ()


def _wants_a_seamless_view(profile: AcquisitionProfile) -> bool:
    """Whether this acquisition has a seam to place at all.

    Only a connected mosaic does. Positions scattered across a slide do not
    overlap, so there is nothing to choose between and no seamless presentation to
    build — the raw view already shows each of them once.
    """
    return profile.topology == "grid" and bool(profile.tiled_axes)


def _units_for(profile: AcquisitionProfile) -> dict[str, str]:
    """What one step along each of the profile's axes means."""
    return {
        axis: _NON_SPATIAL_UNITS.get(axis, profile.voxel_unit) for axis in profile.axes
    }


def _voxel_sizes(profile: AcquisitionProfile) -> dict[str, float]:
    """The size of one voxel on every axis, filling in one where nothing was recorded."""
    return {axis: float(profile.voxel_size.get(axis, 1.0)) for axis in profile.axes}


def build_the_scene(
    profile: AcquisitionProfile,
    layout: SceneLayoutRevision,
    *,
    channels: tuple[str, ...] = ("channel 0",),
    scene_id: str | None = None,
    positions_folder: str = "positions",
    views_folder: str = "views",
    overview_name: str = "overview",
    seamless: bool | None = None,
    derived: Iterable[DerivedView] = (),
) -> Scene:
    """Describe a run's images and where they sit, from its own sealed records.

    Give it the acquisition profile that was sealed before the run started and the
    layout snapshot saying where the tiles actually landed, and it returns the
    scene: one image per committed position, the overviews built over them, and
    any derived product you hand it.

    ``seamless`` is decided for you unless you say otherwise. A connected mosaic
    gets a seamless overview because it has overlaps to resolve; scattered target
    positions do not, and asking for one anyway would produce a picture with seams
    invented where no tiles ever met.

    What comes back is a description, not a picture and not a viewer
    configuration. Nothing has been arranged for the drawing engine yet; that is
    :func:`compile_for_neuroglancer`.

    Raises :class:`SceneRefused` when the description does not hold together — a
    position named twice, a view claiming a position that is not there.
    """
    axes = tuple(profile.axes)
    voxel_size = _voxel_sizes(profile)
    world = CoordinateSystem(
        name=f"{layout.run_id or 'run'}/world",
        axes=axes,
        units=FrozenMap(_units_for(profile)),
    )

    images: list[SceneImage] = []

    # Each position first. Its placement turns its own pixels into a place on the
    # specimen: scaled by the voxel size, then slid to wherever its grid cell put
    # it. The origin comes from the layout snapshot rather than from any stage
    # reading, because the layout is what the ownership rules were worked out
    # against and the two must not disagree.
    for placement in layout.positions:
        translation = {
            axis: float(placement.origin.get(axis, 0)) * voxel_size[axis] for axis in axes
        }
        images.append(
            SceneImage(
                image_id=placement.position_id,
                role=POSITION_ROLE,
                path=f"{positions_folder}/{placement.position_id}.ome.zarr",
                axes=axes,
                voxel_size=FrozenMap(voxel_size),
                voxel_unit=profile.voxel_unit,
                placement=AffinePlacement(
                    axes=axes,
                    scale=FrozenMap(voxel_size),
                    translation=FrozenMap(translation),
                ),
                channels=channels,
                position_id=placement.position_id,
                component_id=placement.component_id,
                cell=placement.cell,
            )
        )

    position_ids = tuple(placement.position_id for placement in layout.positions)

    # Both overviews begin at the run's own origin, so their placement is the voxel
    # size alone. They deliberately share a name: they are two presentations of one
    # overview, and their role is what tells them apart.
    def an_overview(role: str, suffix: str, selector: str | None) -> SceneImage:
        return SceneImage(
            image_id=overview_name,
            role=role,
            path=f"{views_folder}/{overview_name}-{suffix}.ome.zarr",
            axes=axes,
            voxel_size=FrozenMap(voxel_size),
            voxel_unit=profile.voxel_unit,
            placement=AffinePlacement(axes=axes, scale=FrozenMap(voxel_size)),
            channels=channels,
            draws=position_ids,
            selector_axis=selector,
        )

    # The raw view keeps every overlapping pixel, which means two tiles can claim
    # the same place on the specimen. One grey value cannot show two measurements,
    # so the view carries a dimension the operator can step through to choose
    # which tile they are looking at. That is the alternative to handing the
    # engine one source per position, which is the thing this module exists to
    # prevent.
    images.append(an_overview("non_seamless", "raw", "tile"))

    wanted = _wants_a_seamless_view(profile) if seamless is None else bool(seamless)
    if wanted:
        images.append(an_overview("seamless", "seamless", None))

    for product in derived:
        product_voxels = (
            voxel_size
            if product.voxel_size is None
            else {axis: float(product.voxel_size.get(axis, voxel_size[axis])) for axis in axes}
        )
        offset = product.world_offset or {}
        images.append(
            SceneImage(
                image_id=product.image_id,
                role="derived",
                path=product.path,
                axes=axes,
                voxel_size=FrozenMap(product_voxels),
                voxel_unit=profile.voxel_unit,
                placement=AffinePlacement(
                    axes=axes,
                    scale=FrozenMap(product_voxels),
                    translation=FrozenMap(
                        {axis: float(offset.get(axis, 0.0)) for axis in axes}
                    ),
                ),
                channels=product.channels,
                draws=tuple(product.draws),
                kind=product.kind,
            )
        )

    return Scene(
        scene_id=scene_id or f"{layout.run_id}-scene-{layout.revision}",
        run_id=layout.run_id,
        layout_revision=layout.revision,
        profile_id=profile.profile_id,
        coordinate_system=world,
        images=tuple(images),
    )


# ---------------------------------------------------------------------------
# What the drawing engine is actually given
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledSource:
    """One store the viewer is told to read, and what it is showing.

    There is one of these per view, never one per position. Everything about the
    cost of drawing follows from how many of these exist, so the count is the
    number to watch and the reason the compile step deliberately throws the
    positions away.

    ``url`` is stable for the whole run. ``revision`` is what changes when new data
    is committed, and it travels here, beside the address, rather than in it — see
    the module docstring for what putting it in the address costs.

    ``draws_positions`` is a count rather than a list. The list would be perfectly
    correct and would make this record grow with the run, and this record is sent
    to the browser on every refresh; a payload that grows with the number of
    positions is the same mistake as a source that does, only cheaper.
    """

    source_id: str
    role: str
    url: str
    revision: int
    layout_revision: int
    axes: tuple[str, ...]
    transform: AffinePlacement
    draws_positions: int = 0
    local_dimension: str | None = None
    kind: str = "image"

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for sending to the browser."""
        return {
            "source_id": self.source_id,
            "role": self.role,
            "url": self.url,
            "revision": self.revision,
            "layout_revision": self.layout_revision,
            "transform": self.transform.to_json(),
            "draws_positions": self.draws_positions,
            "local_dimension": self.local_dimension,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class CompiledLayer:
    """One row of controls in the viewer, reading from one or more sources.

    A layer is what an operator actually touches: it has a name, a colour, a
    contrast setting. There is one per channel of each view, so the seamless and
    the raw overview of a two-colour run come to four rows, each with its own
    contrast — which is the point, because the two overviews can differ exactly
    where it matters and being handed one merged control would hide that.

    A layer may read from several sources, which is how the shipping viewer already
    works: one row, several stores, the engine compositing them. What it must never
    be is one row per position.
    """

    name: str
    role: str
    channel: str
    channel_index: int
    source_ids: tuple[str, ...]
    kind: str = "image"
    local_position: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        if not isinstance(self.local_position, FrozenMap):
            object.__setattr__(self, "local_position", FrozenMap(self.local_position))

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for sending to the browser."""
        return {
            "name": self.name,
            "role": self.role,
            "channel": self.channel,
            "channel_index": self.channel_index,
            "source_ids": list(self.source_ids),
            "kind": self.kind,
            "local_position": dict(sorted(self.local_position.as_dict().items())),
        }


@dataclass(frozen=True)
class NeuroglancerScene:
    """Everything the viewer needs, and deliberately nothing more.

    Small, plain and bounded: a handful of sources, a handful of layers, and the
    revisions they were compiled against. A run of five thousand positions produces
    the same shape of answer as a run of five, which is the whole claim of the
    arrangement.
    """

    scene_id: str
    run_id: str
    revision: int
    layout_revision: int
    coordinate_system: CoordinateSystem
    sources: tuple[CompiledSource, ...] = ()
    layers: tuple[CompiledLayer, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "layers", tuple(self.layers))

    def source(self, source_id: str) -> CompiledSource:
        """One source, by its identity."""
        for candidate in self.sources:
            if candidate.source_id == source_id:
                return candidate
        raise SceneRefused(
            f"Nothing here is called '{source_id}'. The sources compiled are "
            f"{[source.source_id for source in self.sources]}."
        )

    def layer(self, name: str) -> CompiledLayer:
        """One layer, by the name the operator sees."""
        for candidate in self.layers:
            if candidate.name == name:
                return candidate
        raise SceneRefused(
            f"There is no layer called '{name}'. The layers compiled are "
            f"{[layer.name for layer in self.layers]}."
        )

    def describe(self) -> str:
        """One line for a log, saying what the viewer was handed."""
        drawn = sum(source.draws_positions for source in self.sources)
        return (
            f"{len(self.sources)} sources and {len(self.layers)} layers covering "
            f"{drawn} positions, at revision {self.revision} of layout "
            f"{self.layout_revision}"
        )

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for sending to the browser."""
        return {
            "schema": _SCHEMA,
            "scene_id": self.scene_id,
            "run_id": self.run_id,
            "revision": self.revision,
            "layout_revision": self.layout_revision,
            "coordinate_system": self.coordinate_system.to_json(),
            "sources": [source.to_json() for source in self.sources],
            "layers": [layer.to_json() for layer in self.layers],
        }


def _the_address_of(store_root: str, path: str) -> str:
    """Where a store is reached, and nothing about how fresh it is.

    Kept in a function of its own because this is where the tempting mistake goes
    in. Adding the revision here would certainly defeat every cache; it would also
    make the drawing engine treat each commit as a new data source, keep the old
    one alive, and build a fresh drawing layer for every commit of every position.
    The address is what a store *is*; the revision is what it is *at*, and that
    belongs in :attr:`CompiledSource.revision`.
    """
    if not store_root:
        return path
    return f"{store_root.rstrip('/')}/{path.lstrip('/')}"


def _revision_for(image: SceneImage, committed: CommittedState) -> int:
    """Which committed revision this view is showing.

    A view is exactly as fresh as the newest position it draws, which is what lets
    the frontend refresh one source and leave the rest of the viewer alone. When a
    view draws no positions at all — a stitched product, a segmentation — nothing
    tells us anything more precise than the run-wide counter, so that is what it
    gets, and it will refresh slightly more often than it strictly needs to.

    A view whose positions have committed nothing is at revision zero even while
    the run is at seven. That is the honest answer: none of what this view shows
    has been published yet.
    """
    if not image.draws:
        return committed.revision
    return max(committed.by_store.get(position_id, 0) for position_id in image.draws)


def _layer_key(image: SceneImage, channel: str) -> tuple[str, str, str]:
    """What makes two things the same row of controls.

    The role is in here on purpose and is the part that is easy to lose. The
    seamless and the raw overview share a name, a voxel size and their channel
    names; anything keyed on those alone folds them into one row with one contrast
    control, and the operator is never told that half of what they asked for
    vanished.
    """
    return (image.role, image.image_id, channel)


def _layer_name(role: str, image_id: str, channel: str) -> str:
    """The name the operator reads on the row."""
    return f"{image_id} ({ROLE_IN_WORDS[role]}) {channel}"


def compile_for_neuroglancer(
    scene: Scene,
    committed: CommittedState,
    *,
    store_root: str = "",
) -> NeuroglancerScene:
    """Turn the scene into the sources, layers and transforms the viewer consumes.

    This is the step where the truth about the experiment meets the cost of drawing
    it. The scene may hold five thousand positions; what comes out holds one source
    per view and one layer per channel of each view, and that count does not grow
    with the run. The reasoning, with the measurements behind it, is at the top of
    this file.

    ``committed`` is the run's publication record — what is finished and therefore
    safe to read. Each source is stamped with the revision of the newest position
    it shows, so that a frontend noticing a higher number can refresh that one
    source and leave the camera, the contrast and every other open dataset exactly
    as the operator left them.

    ``store_root`` is where the browser reaches the run, such as ``/runs/2026-08-08``.
    It is given here rather than stored in the scene because where a run is served
    from is a property of the server, not of the experiment.

    Returns a small, plain object that converts straight to JSON. Raises
    :class:`SceneRefused` if two views would compile to the same identity, which
    would mean one silently replacing the other.
    """
    sources: list[CompiledSource] = []
    grouped: dict[tuple[str, str, str], list[tuple[SceneImage, int, str]]] = {}
    order: list[tuple[str, str, str]] = []

    for image in scene.images:
        if image.role == POSITION_ROLE:
            # The single most important line in this module. A position is what a
            # view is made of, not a thing to hand over separately: every source
            # the engine is given becomes a drawing layer that takes part in every
            # frame for as long as the viewer is open.
            continue

        source = CompiledSource(
            source_id=image.identity,
            role=image.role,
            url=_the_address_of(store_root, image.path),
            revision=_revision_for(image, committed),
            layout_revision=scene.layout_revision,
            axes=image.axes,
            transform=image.placement,
            draws_positions=len(image.draws),
            local_dimension=image.selector_axis,
            kind=image.kind,
        )
        if any(existing.source_id == source.source_id for existing in sources):
            raise SceneRefused(
                f"Two views compiled to the same identity, '{source.source_id}'. One "
                f"would silently replace the other on screen. This normally means the "
                f"part an image plays has been left out of its identity, which is what "
                f"lets the seamless and the raw overview become one picture."
            )
        sources.append(source)

        for index, channel in enumerate(image.channels):
            key = _layer_key(image, channel)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append((image, index, source.source_id))

    layers: list[CompiledLayer] = []
    for key in order:
        members = grouped[key]
        first_image, first_index, _ = members[0]
        role, image_id, channel = first_image.role, first_image.image_id, key[-1]
        # A layer pins the channel it is showing, and — where the view offers a
        # choice between overlapping tiles — starts on the first of them. The
        # operator can step through the rest; nothing is hidden, it simply is not
        # all shown at once.
        pinned: dict[str, int] = {"c": first_index}
        if first_image.selector_axis:
            pinned[first_image.selector_axis] = 0
        layers.append(
            CompiledLayer(
                name=_layer_name(role, image_id, channel),
                role=role,
                channel=channel,
                channel_index=first_index,
                source_ids=tuple(source_id for _, _, source_id in members),
                kind=first_image.kind,
                local_position=FrozenMap(pinned),
            )
        )

    return NeuroglancerScene(
        scene_id=scene.scene_id,
        run_id=scene.run_id,
        revision=committed.revision,
        layout_revision=scene.layout_revision,
        coordinate_system=scene.coordinate_system,
        sources=tuple(sources),
        layers=tuple(layers),
    )
