"""The acquisition optimizer must earn strict zero-copy geometry.

These tests deliberately cover camera and scan formats rather than one blessed
square.  The invariant is checked at every pyramid level and on each axis: the
frame, overlap and grid step all consist of whole logical chunks.  That is what
allows both view types to return canonical encoded bytes without a terminal
chunk or a copied fallback.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from zmart_live.model import (
    AcquisitionProfile,
    LevelGeometry,
    OverlapBand,
    ZmartLiveError,
)
from zmart_live.profiles import (
    DEFAULTS,
    a_kinder_frame,
    choose_the_geometry,
    optimize_the_geometry,
    plan_the_writing,
)

# Fixed cameras, configurable confocal formats, and rectangular sensors in both
# orientations.  Hamamatsu's 2304 square format is included explicitly.
CAMERA_FORMATS = (
    512,
    768,
    1024,
    1152,
    1280,
    1536,
    1728,
    1920,
    2000,
    2048,
    2160,
    2304,
    2560,
    3072,
    4096,
    4608,
    5120,
    (512, 1024),
    (1024, 2304),
    (1152, 2304),
    (2304, 1152),
    (2048, 2304),
    (2304, 2048),
)


def _strict_equations_hold(geometry) -> None:
    for level, chunk_shape in enumerate(geometry.level_chunk_shapes):
        factor = 2**level
        for frame, overlap, step, chunk in zip(
            geometry.frame_shape,
            geometry.overlap_shape,
            geometry.step_shape,
            chunk_shape,
            strict=True,
        ):
            assert frame % factor == 0
            assert overlap % factor == 0
            assert step % factor == 0
            assert (frame // factor) % chunk == 0
            assert (overlap // factor) % chunk == 0
            assert (step // factor) % chunk == 0


class TestStrictGeometryAcrossCameraFormats:
    @pytest.mark.parametrize("frame", CAMERA_FORMATS)
    def test_every_level_has_no_terminal_source_chunk(self, frame):
        band = DEFAULTS["overview"].overlap_band
        geometry = choose_the_geometry(frame, band=band)

        _strict_equations_hold(geometry)
        assert geometry.kept_levels == 4
        assert geometry.pointed_levels == 4
        assert geometry.written_levels == 0
        assert all(band.permits(value) for value in geometry.overlap_fractions)

    @pytest.mark.parametrize("frame", CAMERA_FORMATS)
    def test_the_viewer_request_grid_stays_bounded(self, frame):
        geometry = choose_the_geometry(
            frame,
            band=DEFAULTS["overview"].overlap_band,
        )
        assert all(
            y <= DEFAULTS["overview"].target_chunks_across
            and x <= DEFAULTS["overview"].target_chunks_across
            for y, x in geometry.chunks_across_by_level
        )

    def test_the_smallest_format_uses_a_small_coarse_chunk_not_extra_overlap(self):
        geometry = choose_the_geometry(
            512,
            band=DEFAULTS["overview"].overlap_band,
        )
        assert geometry.overlap == 64
        assert geometry.overlap_fraction == pytest.approx(0.125)
        assert geometry.level_chunk_shapes == (
            (64, 64),
            (32, 32),
            (16, 16),
            (8, 8),
        )
        assert geometry.chunks_across_by_level == ((8, 8),) * 4

    def test_hamamatsu_2304_has_four_directly_linked_levels(self):
        geometry = choose_the_geometry(
            2304,
            band=DEFAULTS["overview"].overlap_band,
        )
        assert geometry.overlap == 288
        assert geometry.level_chunk_shapes == (
            (288, 288),
            (144, 144),
            (72, 72),
            (36, 36),
        )

    def test_a_rectangle_is_optimized_independently_per_axis(self):
        geometry = choose_the_geometry(
            (1152, 2304),
            band=DEFAULTS["overview"].overlap_band,
        )
        assert geometry.frame_shape == (1152, 2304)
        assert geometry.overlap_shape == (144, 288)
        assert geometry.level_chunk_shapes[0] == (144, 288)
        assert geometry.chunks_across_by_level == ((8, 8),) * 4
        for scalar in ("frame", "overlap", "step", "overlap_fraction", "chunk"):
            with pytest.raises(ZmartLiveError):
                getattr(geometry, scalar)

    def test_one_number_and_an_equal_pair_mean_the_same_square(self):
        band = DEFAULTS["overview"].overlap_band
        assert choose_the_geometry(1152, band=band) == choose_the_geometry(
            (1152, 1152), band=band
        )


class TestTheOptimizerShowsTheTradeOff:
    def test_the_report_keeps_non_dominated_alternatives(self):
        report = optimize_the_geometry(
            1152,
            band=DEFAULTS["overview"].overlap_band,
        )
        assert report.recommended is report.alternatives[0]
        assert report.candidates_considered >= len(report.alternatives)
        assert len(report.alternatives) == len(set(report.alternatives))
        assert {geometry.overlap for geometry in report.alternatives} == {
            128,
            144,
            192,
        }

    def test_no_reported_alternative_is_worse_on_both_costs(self):
        report = optimize_the_geometry(
            (1152, 2304),
            band=DEFAULTS["overview"].overlap_band,
        )
        for candidate in report.alternatives:
            assert not any(
                other.acquisition_multiplier < candidate.acquisition_multiplier
                and all(
                    other_count < candidate_count
                    for other_count, candidate_count in zip(
                        other.chunks_per_level,
                        candidate.chunks_per_level,
                        strict=True,
                    )
                )
                for other in report.alternatives
            )

    def test_an_acquisition_can_deliberately_permit_less_than_ten_percent(self):
        unusual = DEFAULTS["overview"].with_overlap(0.05, 0.09, 0.075)
        profile, geometry = plan_the_writing(
            "overview",
            frame=2048,
            defaults=unusual,
        )
        assert geometry.overlap_fraction == pytest.approx(0.0625)
        assert profile.overlap_band is unusual.overlap_band
        _strict_equations_hold(geometry)

    def test_the_default_policy_never_exceeds_twenty_percent(self):
        for defaults in DEFAULTS.values():
            assert defaults.overlap_band.permitted_fraction[1] == 0.20

    def test_a_format_without_a_strict_answer_is_refused_with_remedies(self):
        with pytest.raises(ZmartLiveError) as raised:
            choose_the_geometry(
                584,
                band=DEFAULTS["overview"].overlap_band,
            )
        message = str(raised.value)
        assert "584" in message
        assert "Reduce the number of levels" in message
        assert "smaller chunk" in message
        assert "overlap" in message

    def test_a_frame_must_halve_exactly_through_the_requested_pyramid(self):
        with pytest.raises(ZmartLiveError, match="halved exactly"):
            choose_the_geometry(
                1002,
                band=DEFAULTS["overview"].overlap_band,
            )

    def test_an_overlap_that_cannot_halve_with_a_deeper_pyramid_is_refused(self):
        # 136 shares useful chunks with a 1024-pixel frame, but it is not a
        # multiple of 16 and therefore cannot describe an exact fifth level.
        only_136_pixels = OverlapBand(
            preferred_fraction=(136 / 1024, 136 / 1024),
            permitted_fraction=(136 / 1024, 136 / 1024),
            preferred_target=136 / 1024,
        )
        with pytest.raises(ZmartLiveError, match="No overlap"):
            optimize_the_geometry(
                1024,
                band=only_136_pixels,
                pyramid_levels=5,
                minimum_chunk=1,
            )

    @pytest.mark.parametrize("frame", [0, -1, (512,), (512, 512, 512), "512"])
    def test_malformed_frames_are_refused(self, frame):
        with pytest.raises(ZmartLiveError):
            choose_the_geometry(frame, band=DEFAULTS["overview"].overlap_band)

    def test_a_good_fixed_format_is_not_told_to_change(self):
        assert a_kinder_frame(2304) is None


class TestEveryCanonicalLevelIsSharded:
    @pytest.mark.parametrize(
        "kind,frame,z,expected_mb",
        [
            ("confocal", 1152, 100, 256),
            ("mesospim", 4608, 300, 512),
            ("timelapse", 2304, 20, 128),
        ],
    )
    def test_full_resolution_shards_follow_the_acquisition_budget(
        self, kind, frame, z, expected_mb
    ):
        profile, _ = plan_the_writing(kind, frame=frame, z_planes=z)
        shard = profile.level(0).shard
        megabytes = shard["z"] * shard["y"] * shard["x"] * 2 / 1024**2
        assert megabytes == pytest.approx(expected_mb, rel=0.55)

    @pytest.mark.parametrize("frame", [512, 1152, 2304, 4608, (1152, 2304)])
    def test_every_level_is_one_spatial_shard_or_fewer_z_slabs(self, frame):
        profile, geometry = plan_the_writing(
            "overview",
            frame=frame,
            z_planes=37,
        )
        for level, chunk_shape in zip(
            profile.levels,
            geometry.level_chunk_shapes,
            strict=True,
        ):
            factor = 2**level.level
            assert level.shard is not None
            assert level.shard["y"] == geometry.height // factor
            assert level.shard["x"] == geometry.width // factor
            assert level.shard["z"] <= 37
            assert level.inner_chunk["y"] == chunk_shape[0]
            assert level.inner_chunk["x"] == chunk_shape[1]
            for axis in ("z", "y", "x"):
                assert level.shard[axis] % level.inner_chunk[axis] == 0

    def test_a_shard_never_crosses_time_or_channel(self):
        profile, _ = plan_the_writing(
            "timelapse",
            frame=2304,
            z_planes=20,
            channels=("green", "red"),
        )
        for level in profile.levels:
            assert "t" not in level.shard
            assert "c" not in level.shard

    def test_all_pyramid_resolutions_still_halve_by_two(self):
        profile, _ = plan_the_writing("overview", frame=2304)
        assert [level.downsampling["y"] for level in profile.levels] == [1, 2, 4, 8]
        assert [level.downsampling["x"] for level in profile.levels] == [1, 2, 4, 8]
        assert profile.linkable_levels == (0, 1, 2, 3)


class TestAcquisitionProfilesStayHonest:
    @pytest.mark.parametrize("kind", sorted(DEFAULTS))
    def test_a_profile_round_trips_exactly(self, kind):
        profile, _ = plan_the_writing(kind, frame=2304, z_planes=10)
        assert AcquisitionProfile.from_json(profile.to_json()) == profile

    def test_a_rectangular_profile_records_both_axes(self):
        profile, geometry = plan_the_writing(
            "confocal",
            frame=(1152, 2304),
            z_planes=8,
        )
        assert tuple(profile.frame_shape[axis] for axis in ("y", "x")) == (
            1152,
            2304,
        )
        assert tuple(profile.overlap_pixels[axis] for axis in ("y", "x")) == (
            geometry.overlap_shape
        )

    def test_a_mutable_input_cannot_change_a_sealed_profile(self):
        profile, _ = plan_the_writing("overview", frame=2304)
        stored = profile.to_json()
        recovered = AcquisitionProfile.from_json(stored)
        stored["voxel_size"]["x"] = 99.0
        assert recovered.voxel_size["x"] != 99.0

    def test_a_linkable_terminal_frame_chunk_is_refused(self):
        with pytest.raises(ZmartLiveError, match="camera edge"):
            AcquisitionProfile(
                profile_id="terminal-frame",
                acquisition_type="overview",
                axes=("y", "x"),
                frame_shape={"y": 90, "x": 90},
                dtype="uint16",
                overlap_pixels={"y": 10, "x": 10},
                topology="grid",
                levels=(
                    LevelGeometry(
                        0,
                        {"y": 1, "x": 1},
                        {"y": 16, "x": 16},
                        linkable=True,
                    ),
                ),
            )

    def test_a_linkable_terminal_overlap_chunk_is_refused(self):
        with pytest.raises(ZmartLiveError, match="partial source chunk"):
            AcquisitionProfile(
                profile_id="terminal-overlap",
                acquisition_type="overview",
                axes=("y", "x"),
                frame_shape={"y": 96, "x": 96},
                dtype="uint16",
                overlap_pixels={"y": 8, "x": 8},
                topology="grid",
                levels=(
                    LevelGeometry(
                        0,
                        {"y": 1, "x": 1},
                        {"y": 16, "x": 16},
                        linkable=True,
                    ),
                ),
            )

    def test_a_shard_must_hold_whole_chunks(self):
        with pytest.raises(ZmartLiveError, match="whole number of chunks"):
            LevelGeometry(
                0,
                {"y": 1},
                {"y": 16},
                shard={"y": 30},
            )

    def test_pyramid_levels_cannot_start_at_one(self):
        with pytest.raises(ZmartLiveError):
            AcquisitionProfile(
                profile_id="bad-levels",
                acquisition_type="overview",
                axes=("y", "x"),
                frame_shape={"y": 96, "x": 96},
                dtype="uint16",
                levels=(
                    LevelGeometry(1, {"y": 2, "x": 2}, {"y": 16, "x": 16}),
                ),
            )

    @pytest.mark.parametrize(
        "changes",
        [
            {"z_planes": 0},
            {"dtype": "not-a-real-pixel-type"},
            {"channels": ()},
            {"voxel_size": (1.0, 0.0, 1.0)},
            {"voxel_size": (1.0, float("nan"), 1.0)},
        ],
    )
    def test_unwritable_inputs_are_refused(self, changes):
        with pytest.raises(ZmartLiveError):
            plan_the_writing("overview", frame=2304, **changes)

    def test_an_unknown_acquisition_names_the_known_kinds(self):
        with pytest.raises(ZmartLiveError, match="overview"):
            plan_the_writing("holotomography", frame=2304)

    def test_defaults_cannot_be_used_under_a_misleading_type(self):
        wrong = replace(DEFAULTS["overview"], acquisition_type="confocal")
        with pytest.raises(ZmartLiveError, match="not the requested"):
            plan_the_writing("overview", frame=2304, defaults=wrong)
