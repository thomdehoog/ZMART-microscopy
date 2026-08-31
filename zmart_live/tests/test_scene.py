"""Checking that a run's scene compiles into something a viewer can actually draw.

Two failures are being guarded against here, and neither of them announces itself.

**The viewer becomes unusable as the run grows.** Handing the drawing engine one
source per position is measurably ruinous — a thousand positions drew twenty-four
frames in five seconds where one linked image managed 255 — but nothing about it
looks like a fault. It looks like a slow computer, and it gets slower for the
whole time the viewer is open. So the central test here does not check a rule; it
builds a scene of two thousand positions and counts what comes out.

**Two different pictures quietly become one.** The linked overview and a derived
product that happens to share its name are built over the same files, have the
same voxel size, and can carry the same channel names. Anything that decides what
to draw from those alone folds them into one row with one contrast control, and
the operator is told nothing. So a derived namesake is built beside the overview
and asked to stay apart.

Everything here is pure arithmetic over small records — no zarr is written and no
files are touched — so the whole file runs in well under a second. A check nobody
wants to wait for is a check that stops being run.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from zmart_live.manifest import CommittedState
from zmart_live.model import (
    AcquisitionProfile,
    FrozenMap,
    GridCell,
    LevelGeometry,
    SceneLayoutRevision,
)
from zmart_live.ownership import place_the_tiles
from zmart_live.scene import (
    POSITION_ROLE,
    AffinePlacement,
    CoordinateSystem,
    DerivedView,
    Scene,
    SceneImage,
    SceneRefused,
    build_the_scene,
    compile_for_neuroglancer,
)

# ---------------------------------------------------------------------------
# Small stand-ins with the same shape as a real run
# ---------------------------------------------------------------------------


def a_plan(
    frame: int = 90,
    overlap: int = 10,
    *,
    topology: str = "grid",
    voxel: tuple[float, float, float] = (2.0, 0.5, 0.5),
) -> AcquisitionProfile:
    """A mosaic plan with the same shape as a real one, only small.

    Ninety pixels with ten of overlap is nine chunks across with one chunk given
    up, which is the arrangement the real profiles choose. The voxel size is
    deliberately not one on any axis, so that a transform which forgot to scale
    would stand out rather than happening to look right.
    """
    return AcquisitionProfile(
        profile_id="test-profile",
        acquisition_type="overview",
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": 4, "y": frame, "x": frame},
        dtype="uint16",
        voxel_size=FrozenMap({"z": voxel[0], "y": voxel[1], "x": voxel[2]}),
        voxel_unit="micrometer",
        overlap_pixels={"y": overlap, "x": overlap} if topology == "grid" else {},
        topology=topology,
        levels=(
            LevelGeometry(
                level=0,
                downsampling={"y": 1, "x": 1},
                inner_chunk={"y": 10, "x": 10},
                linkable=True,
            ),
        ),
    )


def a_layout(
    profile: AcquisitionProfile,
    rows: int = 2,
    columns: int = 2,
    *,
    revision: int = 3,
) -> SceneLayoutRevision:
    """A layout snapshot for a rectangular mosaic of the given size."""
    cells = {
        GridCell(row, column): f"pos-{row}-{column}"
        for row in range(rows)
        for column in range(columns)
    }
    return SceneLayoutRevision(
        revision=revision,
        schema_version="zmart-live-layout/1",
        run_id="run-2026-08-08",
        acquisition_type=profile.acquisition_type,
        profile_id=profile.profile_id,
        positions=place_the_tiles(profile, cells),
    )


def a_scattered_layout(profile: AcquisitionProfile) -> SceneLayoutRevision:
    """Positions that do not form a mosaic, as a run of separate targets does.

    Each target is its own single-tile component, which is what the design record
    asks for: an isolated target is a mosaic of one rather than an odd exception
    inside somebody else's grid.
    """
    positions = []
    for index in range(3):
        cells = {GridCell(0, 0): f"target-{index}"}
        positions.extend(
            place_the_tiles(a_plan(topology="grid"), cells, component_id=f"target-{index}")
        )
    return SceneLayoutRevision(
        revision=1,
        schema_version="zmart-live-layout/1",
        run_id="run-targets",
        acquisition_type=profile.acquisition_type,
        profile_id=profile.profile_id,
        positions=tuple(positions),
    )


def nothing_published() -> CommittedState:
    return CommittedState(revision=0, run_id="run-2026-08-08")


def published(revision: int, **by_store: int) -> CommittedState:
    """A publication record where the named positions reached the given revisions."""
    return CommittedState(
        revision=revision,
        run_id="run-2026-08-08",
        by_store=dict(by_store),
        layout_revision=3,
    )


# ---------------------------------------------------------------------------


class TestTheSceneSaysWhatTheRunContains:
    """The scene is the honest description: every position, and the views over them."""

    def test_every_position_in_the_layout_becomes_an_image(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 3))

        assert len(scene.positions) == 6
        assert {image.image_id for image in scene.positions} == {
            f"pos-{row}-{column}" for row in range(2) for column in range(3)
        }

    def test_a_mosaic_gets_exactly_one_linked_overview(self):
        """A run has one presentation: the linked view, every position drawn whole."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))

        assert scene.roles == ("linked", "position")
        assert len(scene.with_role("linked")) == 1
        assert scene.with_role("derived") == ()

    def test_scattered_positions_get_the_same_one_overview(self):
        """A run of separate targets is presented the same way as a mosaic.

        There is no overlap between tiles that never met, and the linked view
        invents none: it simply draws each target where it sits.
        """
        profile = a_plan(topology="independent")
        scene = build_the_scene(profile, a_scattered_layout(profile))

        assert len(scene.with_role("linked")) == 1
        assert scene.with_role("derived") == ()
        assert len(scene.positions) == 3

    def test_the_scene_carries_the_layout_revision_it_was_built_from(self):
        """A published result has to be able to say which arrangement it used."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, revision=11))

        assert scene.layout_revision == 11
        assert scene.profile_id == profile.profile_id
        assert scene.run_id == "run-2026-08-08"

    def test_every_view_records_which_positions_it_shows(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        for view in scene.views:
            assert set(view.draws) == set(scene_positions(scene))

    def test_a_position_never_claims_to_show_other_positions(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))

        assert all(image.draws == () for image in scene.positions)

    def test_derived_products_join_the_scene_without_becoming_positions(self):
        profile = a_plan()
        scene = build_the_scene(
            profile,
            a_layout(profile),
            derived=(
                DerivedView(
                    image_id="nuclei",
                    path="analysis/nuclei.ome.zarr",
                    channels=("labels",),
                    kind="segmentation",
                ),
            ),
        )

        assert len(scene.with_role("derived")) == 1
        assert scene.image("derived/nuclei").kind == "segmentation"
        assert len(scene.positions) == 4  # unchanged by the derived product


def scene_positions(scene: Scene) -> set[str]:
    return {image.image_id for image in scene.positions}


class TestTheAxesAreKeptInTheOrderTheAcquisitionDeclared:
    """Transposing an image produces a picture, not an error, so this is checked."""

    def test_images_carry_the_profiles_axis_order_exactly(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))

        for image in scene.images:
            assert image.axes == ("t", "c", "z", "y", "x")
            assert image.placement.axes == ("t", "c", "z", "y", "x")

    def test_the_compiled_transform_lists_its_numbers_in_that_same_order(self):
        profile = a_plan(voxel=(2.0, 0.5, 0.25))
        scene = build_the_scene(profile, a_layout(profile))
        compiled = compile_for_neuroglancer(scene, nothing_published())

        transform = compiled.source("linked/overview").transform
        assert transform.axes == ("t", "c", "z", "y", "x")
        assert transform.scale_row() == (1.0, 1.0, 2.0, 0.5, 0.25)

    def test_the_shared_coordinates_name_every_axis_and_its_unit(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        world = scene.coordinate_system

        assert world.axes == ("t", "c", "z", "y", "x")
        assert world.unit_of("x") == "micrometer"
        assert world.unit_of("t") == "second"
        assert world.unit_of("c") == ""  # a channel is a name, not a length


class TestTheTransformsPutEachTileWhereItBelongs:
    """A dropped or halved transform still draws; it just draws in the wrong place."""

    def test_the_first_tile_sits_at_the_runs_origin(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))

        corner = scene.image(f"{POSITION_ROLE}/pos-0-0").placement.applied_to({})
        assert corner["y"] == 0.0
        assert corner["x"] == 0.0

    def test_a_neighbour_sits_one_step_away_in_real_units(self):
        """Eighty pixels of step at half a micrometre each is forty micrometres."""
        profile = a_plan(frame=90, overlap=10, voxel=(2.0, 0.5, 0.5))
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        here = scene.image(f"{POSITION_ROLE}/pos-0-0").placement.applied_to({})
        across = scene.image(f"{POSITION_ROLE}/pos-0-1").placement.applied_to({})
        down = scene.image(f"{POSITION_ROLE}/pos-1-0").placement.applied_to({})

        assert across["x"] - here["x"] == pytest.approx(40.0)
        assert across["y"] == here["y"]
        assert down["y"] - here["y"] == pytest.approx(40.0)
        assert down["x"] == here["x"]

    def test_a_pixel_inside_a_tile_lands_where_the_voxel_size_says(self):
        profile = a_plan(voxel=(2.0, 0.5, 0.5))
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        placed = scene.image(f"{POSITION_ROLE}/pos-1-1").placement.applied_to(
            {"y": 10, "x": 10, "z": 3}
        )
        assert placed["x"] == pytest.approx(40.0 + 5.0)
        assert placed["y"] == pytest.approx(40.0 + 5.0)
        assert placed["z"] == pytest.approx(6.0)

    def test_untiled_axes_are_neither_scaled_away_nor_moved(self):
        """Time and colour are not places, so nothing about them is shifted."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        placement = scene.image(f"{POSITION_ROLE}/pos-1-1").placement
        assert placement.scale["t"] == 1.0
        assert placement.scale["c"] == 1.0
        assert placement.translation["t"] == 0.0
        assert placement.translation["c"] == 0.0

    def test_the_matrix_form_carries_the_same_placement(self):
        profile = a_plan(voxel=(2.0, 0.5, 0.5))
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        rows = scene.image(f"{POSITION_ROLE}/pos-0-1").placement.matrix()
        assert len(rows) == 5  # one row per axis
        assert all(len(row) == 6 for row in rows)  # scales, then the offset
        x_row = rows[-1]
        assert x_row[-2] == pytest.approx(0.5)  # the scale on its own axis
        assert x_row[-1] == pytest.approx(40.0)  # the offset

    def test_a_derived_product_may_sit_at_its_own_place_and_its_own_coarseness(self):
        profile = a_plan()
        scene = build_the_scene(
            profile,
            a_layout(profile),
            derived=(
                DerivedView(
                    image_id="stitched",
                    path="analysis/stitched.ome.zarr",
                    voxel_size={"y": 1.0, "x": 1.0},
                    world_offset={"y": 2.5, "x": -1.5},
                ),
            ),
        )

        placement = scene.image("derived/stitched").placement
        assert placement.scale["x"] == 1.0
        assert placement.applied_to({"x": 10})["x"] == pytest.approx(8.5)


class TestNeverOneSourcePerPosition:
    """The rule that overrides everything else, checked by counting rather than argued.

    Every source the drawing engine is given becomes a layer that takes part in
    every frame for as long as the viewer is open. That cost is paid per source, so
    the count is the thing to watch, and a run of two thousand positions has to
    come out the same size as a run of four.
    """

    def test_two_thousand_positions_compile_to_a_single_source(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 40, 50))
        assert len(scene.positions) == 2000

        compiled = compile_for_neuroglancer(scene, nothing_published())
        assert len(compiled.sources) == 1  # the one linked overview, and no more

    def test_the_number_of_sources_does_not_grow_with_the_run(self):
        profile = a_plan()
        counts = []
        for rows, columns in ((1, 1), (3, 3), (20, 20)):
            scene = build_the_scene(profile, a_layout(profile, rows, columns))
            compiled = compile_for_neuroglancer(scene, nothing_published())
            counts.append(len(compiled.sources))

        assert counts == [1, 1, 1]

    def test_the_number_of_layers_does_not_grow_with_the_run_either(self):
        """A layer costs almost as much as a source; both have to stay bounded."""
        profile = a_plan()
        small = build_the_scene(profile, a_layout(profile, 1, 2), channels=("dapi", "gfp"))
        large = build_the_scene(profile, a_layout(profile, 40, 50), channels=("dapi", "gfp"))

        assert len(compile_for_neuroglancer(small, nothing_published()).layers) == 2
        assert len(compile_for_neuroglancer(large, nothing_published()).layers) == 2

    def test_no_position_ever_becomes_a_source_of_its_own(self):
        """The absence beside the presence: positions are what views are made of."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 3, 3))
        compiled = compile_for_neuroglancer(scene, nothing_published())

        assert all(source.role != POSITION_ROLE for source in compiled.sources)
        position_ids = scene_positions(scene)
        for source in compiled.sources:
            assert source.source_id.split("/", 1)[-1] not in position_ids
            assert not any(name in source.url for name in position_ids)

    def test_the_positions_are_still_covered_even_though_they_are_not_sources(self):
        """Bounded is only useful if nothing was quietly dropped to get there."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 5, 4))
        compiled = compile_for_neuroglancer(scene, nothing_published())

        for source in compiled.sources:
            assert source.draws_positions == 20

    def test_what_goes_to_the_browser_stays_small_at_five_thousand_positions(self):
        """The payload must not grow with the run either, for the same reason.

        Listing every position in the answer would be perfectly correct and would
        make a refresh carry hundreds of kilobytes; a count says as much and costs
        nothing.
        """
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 50, 100))
        assert len(scene.positions) == 5000

        text = json.dumps(compile_for_neuroglancer(scene, nothing_published()).to_json())
        assert len(text) < 8000


class TestTheRevisionTravelsBesideTheAddressNeverInsideIt:
    """A revision in the address makes every commit a brand new data source.

    The engine would keep the old one alive and build a fresh drawing layer for
    each: a hundred positions over a hundred commits is ten thousand layers. So the
    address of a store is stable for the whole run, and the revision is a field
    the frontend compares against what it last drew.
    """

    def test_the_address_is_the_same_at_every_revision(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        early = compile_for_neuroglancer(
            scene, published(1, **{"pos-0-0": 1}), store_root="/runs/today"
        )
        later = compile_for_neuroglancer(
            scene,
            published(9, **{"pos-0-0": 1, "pos-0-1": 4, "pos-1-0": 9}),
            store_root="/runs/today",
        )

        assert [s.url for s in early.sources] == [s.url for s in later.sources]

    def test_the_revision_field_does_move(self):
        """Stable is only right if something else is doing the noticing."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 2))

        early = compile_for_neuroglancer(scene, published(1, **{"pos-0-0": 1}))
        later = compile_for_neuroglancer(scene, published(9, **{"pos-0-0": 1, "pos-1-0": 9}))

        assert early.source("linked/overview").revision == 1
        assert later.source("linked/overview").revision == 9

    def test_the_revision_appears_nowhere_in_any_address(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 2))
        compiled = compile_for_neuroglancer(
            scene, published(7, **{"pos-0-0": 7}), store_root="/runs/today"
        )

        for source in compiled.sources:
            assert "7" not in source.url
            assert "rev" not in source.url.lower()
            assert "?" not in source.url

    def test_a_view_is_as_fresh_as_the_newest_position_it_shows(self):
        """Per source rather than run-wide, which is what lets one picture refresh alone."""
        profile = a_plan()
        scene = build_the_scene(
            profile,
            a_layout(profile, 2, 2),
            derived=(DerivedView(image_id="nuclei", path="analysis/nuclei.ome.zarr"),),
        )
        compiled = compile_for_neuroglancer(scene, published(9, **{"pos-0-0": 3, "pos-0-1": 7}))

        assert compiled.source("linked/overview").revision == 7
        # A derived product names no positions, so nothing tells us anything more
        # precise than the run-wide counter.
        assert compiled.source("derived/nuclei").revision == 9

    def test_a_view_whose_positions_have_published_nothing_is_at_revision_zero(self):
        """The honest answer: none of what this picture shows is safe to read yet."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 2, 2))
        compiled = compile_for_neuroglancer(scene, published(5, **{"somebody-else": 5}))

        assert compiled.source("linked/overview").revision == 0
        assert compiled.revision == 5  # the run has moved on; this view has not

    def test_the_store_root_is_prefixed_without_doubling_the_slash(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        compiled = compile_for_neuroglancer(scene, nothing_published(), store_root="/runs/today/")

        assert compiled.source("linked/overview").url == ("/runs/today/views/overview.ome.zarr")

    def test_with_no_store_root_the_path_stands_alone(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        compiled = compile_for_neuroglancer(scene, nothing_published())

        assert compiled.source("linked/overview").url == ("views/overview.ome.zarr")


class TestADerivedNamesakeDoesNotCollapseIntoTheOverview:
    """The role is part of identity, and this is where that earns its keep.

    A derived product is free to share the overview's name, its voxel size and
    its channel names, and still be a different picture. Anything that decides
    what to draw from those alone folds the two into one row with one contrast
    control, and the operator is told nothing.
    """

    def a_scene_with_a_namesake(self, channels: tuple[str, ...] = ("dapi", "gfp")) -> Scene:
        """The linked overview, and a derived product that shares its name."""
        profile = a_plan()
        return build_the_scene(
            profile,
            a_layout(profile),
            channels=channels,
            derived=(
                DerivedView(
                    image_id="overview",
                    path="analysis/overview.ome.zarr",
                    channels=channels,
                ),
            ),
        )

    def test_they_really_are_indistinguishable_by_voxel_size_and_channels(self):
        """The trap, demonstrated rather than asserted about.

        If this test ever fails it means the two images became different in some
        other way, and the rest of this class is testing something easier than it
        was written for.
        """
        scene = self.a_scene_with_a_namesake()
        linked = scene.image("linked/overview")
        namesake = scene.image("derived/overview")

        assert linked.voxel_size == namesake.voxel_size
        assert linked.channels == namesake.channels
        assert linked.image_id == namesake.image_id

    def test_they_compile_to_two_separate_sources(self):
        compiled = compile_for_neuroglancer(self.a_scene_with_a_namesake(), nothing_published())

        ids = [source.source_id for source in compiled.sources]
        assert len(ids) == len(set(ids)) == 2
        assert {source.role for source in compiled.sources} == {"linked", "derived"}

    def test_each_gets_its_own_row_of_controls_for_every_channel(self):
        """One merged row would mean one contrast control for two different pictures."""
        compiled = compile_for_neuroglancer(self.a_scene_with_a_namesake(), nothing_published())

        assert len(compiled.layers) == 4
        names = [layer.name for layer in compiled.layers]
        assert len(set(names)) == 4
        by_role = {}
        for layer in compiled.layers:
            by_role.setdefault(layer.role, []).append(layer.channel)
        assert by_role["linked"] == ["dapi", "gfp"]
        assert by_role["derived"] == ["dapi", "gfp"]

    def test_every_layer_reads_from_exactly_one_of_the_two(self):
        compiled = compile_for_neuroglancer(
            self.a_scene_with_a_namesake(channels=("dapi",)), nothing_published()
        )

        for layer in compiled.layers:
            assert len(layer.source_ids) == 1
            assert compiled.source(layer.source_ids[0]).role == layer.role

    def test_the_part_each_plays_is_readable_on_the_row(self):
        """An operator should be able to tell which picture a control belongs to."""
        compiled = compile_for_neuroglancer(
            self.a_scene_with_a_namesake(channels=("dapi",)), nothing_published()
        )

        names = " ".join(layer.name for layer in compiled.layers)
        assert "linked" in names
        assert "derived" in names

    def test_a_channel_is_pinned_by_index_on_every_row(self):
        compiled = compile_for_neuroglancer(self.a_scene_with_a_namesake(), nothing_published())

        gfp = compiled.layer("overview (linked) gfp")
        assert gfp.channel_index == 1
        assert gfp.local_position["c"] == 1
        dapi = compiled.layer("overview (derived) dapi")
        assert dapi.channel_index == 0
        assert dapi.local_position["c"] == 0


class TestTheCompiledAnswerIsPlainData:
    """It crosses a network to a browser, so it has to be ordinary JSON."""

    def test_the_whole_thing_converts_to_json_and_back(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile), channels=("dapi", "gfp"))
        compiled = compile_for_neuroglancer(
            scene, published(4, **{"pos-0-0": 4}), store_root="/runs/today"
        )

        written = json.loads(json.dumps(compiled.to_json()))
        assert written["schema"] == "zmart-live-neuroglancer-scene/1"
        assert written["revision"] == 4
        assert written["layout_revision"] == 3
        assert len(written["sources"]) == 1
        assert len(written["layers"]) == 2
        assert written["coordinate_system"]["axes"] == ["t", "c", "z", "y", "x"]

    def test_each_written_source_carries_its_transform_and_its_revision(self):
        profile = a_plan(voxel=(2.0, 0.5, 0.5))
        scene = build_the_scene(profile, a_layout(profile))
        compiled = compile_for_neuroglancer(scene, published(6, **{"pos-0-0": 6}))

        written = compiled.to_json()["sources"][0]
        assert written["revision"] == 6
        assert written["transform"]["scale"] == [1.0, 1.0, 2.0, 0.5, 0.5]
        assert written["transform"]["translation"] == [0.0, 0.0, 0.0, 0.0, 0.0]
        assert "url" in written

    def test_the_scene_itself_also_converts_to_json(self):
        """The scene is the record kept beside the run, so it has to be writable too."""
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))

        written = json.loads(json.dumps(scene.to_json()))
        assert written["schema"] == "zmart-live-scene/1"
        assert len(written["images"]) == 5  # four positions and the one overview

    def test_the_one_line_summary_says_what_was_handed_over(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile, 3, 3))
        compiled = compile_for_neuroglancer(scene, published(2, **{"pos-0-0": 2}))

        summary = compiled.describe()
        assert "1 sources" in summary
        assert "revision 2" in summary


class TestWhatIsRefused:
    """Each refusal here corresponds to a picture that would otherwise look right."""

    def test_an_image_cannot_play_a_part_nobody_recognises(self):
        with pytest.raises(SceneRefused, match="not a part"):
            SceneImage(image_id="x", role="overview", path="x.zarr", axes=("y", "x"))

    def test_the_same_image_cannot_be_described_twice(self):
        image = SceneImage(
            image_id="x",
            role="linked",
            path="x.zarr",
            axes=("y", "x"),
            channels=("green",),
        )
        with pytest.raises(SceneRefused, match="appears twice"):
            Scene(
                scene_id="s",
                run_id="r",
                layout_revision=0,
                profile_id="p",
                coordinate_system=CoordinateSystem(name="w", axes=("y", "x")),
                images=(image, image),
            )

    def test_the_same_name_in_two_different_parts_is_perfectly_fine(self):
        """Which is the whole point: the overview and a derived namesake coexist."""
        scene = Scene(
            scene_id="s",
            run_id="r",
            layout_revision=0,
            profile_id="p",
            coordinate_system=CoordinateSystem(name="w", axes=("y", "x")),
            images=(
                SceneImage(
                    image_id="overview",
                    role="linked",
                    path="a.zarr",
                    axes=("y", "x"),
                    channels=("green",),
                ),
                SceneImage(
                    image_id="overview",
                    role="derived",
                    path="b.zarr",
                    axes=("y", "x"),
                    channels=("green",),
                ),
            ),
        )
        assert len(scene.views) == 2

    def test_a_view_cannot_claim_a_position_the_scene_does_not_hold(self):
        with pytest.raises(SceneRefused, match="no such position"):
            Scene(
                scene_id="s",
                run_id="r",
                layout_revision=0,
                profile_id="p",
                coordinate_system=CoordinateSystem(name="w", axes=("y", "x")),
                images=(
                    SceneImage(
                        image_id="overview",
                        role="linked",
                        path="a.zarr",
                        axes=("y", "x"),
                        channels=("green",),
                        draws=("ghost",),
                    ),
                ),
            )

    def test_a_position_cannot_claim_to_show_other_positions(self):
        with pytest.raises(SceneRefused, match="holds the specimen"):
            SceneImage(
                image_id="p",
                role=POSITION_ROLE,
                path="p.zarr",
                axes=("y", "x"),
                channels=("green",),
                draws=("q",),
            )

    def test_a_placement_whose_axes_disagree_with_the_image_is_refused(self):
        """Transposed images draw perfectly happily, which is exactly the danger."""
        with pytest.raises(SceneRefused, match="have to agree"):
            SceneImage(
                image_id="p",
                role=POSITION_ROLE,
                path="p.zarr",
                axes=("y", "x"),
                channels=("green",),
                placement=AffinePlacement(axes=("x", "y")),
            )

    def test_a_scale_of_zero_is_refused(self):
        with pytest.raises(SceneRefused, match="flatten"):
            AffinePlacement(axes=("y", "x"), scale=FrozenMap({"x": 0.0}))

    def test_a_placement_cannot_speak_about_an_axis_it_does_not_describe(self):
        with pytest.raises(SceneRefused, match="not among the axes"):
            AffinePlacement(axes=("y", "x"), scale=FrozenMap({"z": 2.0}))

    def test_a_layout_cannot_be_interpreted_with_another_profile(self):
        profile = a_plan()
        layout = replace(a_layout(profile), profile_id="some-other-profile")
        with pytest.raises(SceneRefused, match="belongs to profile"):
            build_the_scene(profile, layout)

    def test_an_unsealed_profile_cannot_reach_the_viewer(self):
        profile = replace(a_plan(), sealed=False)
        with pytest.raises(SceneRefused, match="not sealed"):
            build_the_scene(profile, a_layout(profile))

    def test_publication_state_from_another_run_is_refused(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        with pytest.raises(SceneRefused, match="publication record belongs"):
            compile_for_neuroglancer(
                scene,
                CommittedState(revision=1, run_id="another-run"),
            )

    @pytest.mark.parametrize("path", ["../outside.zarr", "/absolute.zarr", "C:/run.zarr"])
    def test_a_store_path_cannot_leave_the_run(self, path):
        with pytest.raises(SceneRefused, match="safe store path"):
            SceneImage(
                image_id="x",
                role="linked",
                path=path,
                axes=("y", "x"),
                channels=("green",),
            )

    def test_a_non_finite_transform_is_refused(self):
        with pytest.raises(SceneRefused, match="finite"):
            AffinePlacement(axes=("y", "x"), translation=FrozenMap({"x": float("nan")}))

    def test_asking_for_a_part_nobody_recognises_is_refused(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        with pytest.raises(SceneRefused, match="not a part"):
            scene.with_role("overview")

    def test_asking_for_an_image_that_is_not_there_says_what_is(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        with pytest.raises(SceneRefused, match="no image called"):
            scene.image("linked/nothing")

    def test_asking_for_a_source_that_is_not_there_says_what_is(self):
        profile = a_plan()
        scene = build_the_scene(profile, a_layout(profile))
        compiled = compile_for_neuroglancer(scene, nothing_published())
        with pytest.raises(SceneRefused, match="Nothing here is called"):
            compiled.source("linked/nothing")
