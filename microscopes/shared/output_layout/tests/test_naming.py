"""Unit tests for the lab-wide output naming convention."""

from __future__ import annotations

import pytest
from shared.output_layout.naming import (
    EPOCH,
    MAX_ACQUISITION_TYPE_LEN,
    MAX_EXPERIMENT_LEN,
    LayoutPlan,
    Naming,
    build_image_name,
    build_layout,
    build_position_analysis_name,
    build_xml_name,
    parse_image_name,
    run_hash,
)

# --- run_hash ----------------------------------------------------------------


class TestRunHash:
    def test_epoch_returns_all_zeros(self):
        assert run_hash(EPOCH) == "000000"

    def test_one_second_after_epoch(self):
        assert run_hash(EPOCH + 1) == "000001"

    def test_ten_seconds_rolls_into_letter(self):
        # base36: 10 -> 'a'
        assert run_hash(EPOCH + 10) == "00000a"

    def test_six_chars_for_large_values(self):
        # 36^4 = 1,679,616 — still fits in 6 chars
        assert len(run_hash(EPOCH + 1_679_616)) == 6

    def test_lexicographic_sort_matches_chronological(self):
        hashes = [run_hash(EPOCH + t) for t in [0, 1, 100, 10_000, 1_000_000, 100_000_000]]
        assert hashes == sorted(hashes)

    def test_before_epoch_raises(self):
        with pytest.raises(ValueError, match="before convention epoch"):
            run_hash(EPOCH - 1)

    def test_default_uses_current_time(self):
        h = run_hash()
        assert len(h) == 6
        assert all(c in "0123456789abcdefghijklmnopqrstuvwxyz" for c in h)


# --- Naming validation -------------------------------------------------------


class TestNaming:
    def test_valid_kebab_case(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        assert n.acquisition_type == "overview-scan"

    def test_single_token(self):
        n = Naming(acquisition_type="overview", hash6="0a3k7m")
        assert n.acquisition_type == "overview"

    def test_multi_hyphen(self):
        n = Naming(acquisition_type="overview-scan-fast", hash6="0a3k7m")
        assert n.acquisition_type == "overview-scan-fast"

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="Overview-Scan", hash6="0a3k7m")

    def test_rejects_underscore(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview_scan", hash6="0a3k7m")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="-overview", hash6="0a3k7m")

    def test_rejects_trailing_hyphen(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview-", hash6="0a3k7m")

    def test_rejects_double_hyphen(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview--scan", hash6="0a3k7m")

    def test_rejects_space(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview scan", hash6="0a3k7m")

    def test_at_length_cap_accepted(self):
        at_cap = "a" * MAX_ACQUISITION_TYPE_LEN
        n = Naming(acquisition_type=at_cap, hash6="0a3k7m")
        assert len(n.acquisition_type) == MAX_ACQUISITION_TYPE_LEN

    def test_rejects_too_long(self):
        too_long = "a" * (MAX_ACQUISITION_TYPE_LEN + 1)
        with pytest.raises(ValueError, match="too long"):
            Naming(acquisition_type=too_long, hash6="0a3k7m")

    def test_rejects_uppercase_hash(self):
        with pytest.raises(ValueError, match="hash6"):
            Naming(acquisition_type="overview-scan", hash6="ABC123")

    def test_rejects_short_hash(self):
        with pytest.raises(ValueError, match="hash6"):
            Naming(acquisition_type="overview-scan", hash6="abc12")

    def test_rejects_long_hash(self):
        with pytest.raises(ValueError, match="hash6"):
            Naming(acquisition_type="overview-scan", hash6="abc1234")


# --- build_image_name / build_xml_name --------------------------------------


class TestBuildNames:
    def test_image_name_all_zero(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        assert build_image_name(n) == (
            "overview-scan_0a3k7m_k00000_m00000_g00000_p00000_t00000_v00_c00_z00000.ome.tiff"
        )

    def test_image_name_with_values(self):
        n = Naming(
            acquisition_type="target-acquisition",
            hash6="bf2x91",
            k=1,
            m=47,
            g=2,
            p=123,
            t=5,
            v=1,
            c=2,
            z=10,
        )
        assert build_image_name(n) == (
            "target-acquisition_bf2x91_k00001_m00047_g00002_p00123_t00005_v01_c02_z00010.ome.tiff"
        )

    def test_xml_omits_c_and_z(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m", c=5, z=42)
        xml = build_xml_name(n)
        assert xml == ("overview-scan_0a3k7m_k00000_m00000_g00000_p00000_t00000_v00.ome.xml")

    def test_max_widths_fit(self):
        n = Naming(
            acquisition_type="a" * MAX_ACQUISITION_TYPE_LEN,
            hash6="zzzzzz",
            k=99999,
            m=99999,
            g=99999,
            p=99999,
            t=99999,
            v=99,
            c=99,
            z=99999,
        )
        # Sanity: the literal max filename is well under 255-char component limit
        assert len(build_image_name(n)) < 255


# --- build_position_analysis_name -------------------------------------------


class TestBuildPositionAnalysisName:
    def test_all_zero(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        assert build_position_analysis_name(n) == (
            "overview-scan_0a3k7m_k00000_m00000_g00000_p00000_t00000_v00.npz"
        )

    def test_with_values(self):
        n = Naming(
            acquisition_type="overview-scan",
            hash6="bf2x91",
            g=2,
            p=123,
            t=5,
            v=1,
            c=7,
            z=42,
        )
        assert build_position_analysis_name(n) == (
            "overview-scan_bf2x91_k00000_m00000_g00002_p00123_t00005_v01.npz"
        )

    def test_c_and_z_omitted(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m", c=99, z=99999)
        name = build_position_analysis_name(n)
        assert "_c" not in name
        assert "_z" not in name
        assert name.endswith(".npz")

    def test_same_slots_as_xml(self):
        n = Naming(
            acquisition_type="target-acquisition",
            hash6="abc123",
            k=1,
            m=2,
            g=3,
            p=4,
            t=5,
            v=6,
            c=7,
            z=8,
        )
        xml = build_xml_name(n)
        npz = build_position_analysis_name(n)
        # Same prefix (all slots except extension), different extension
        assert xml.rsplit(".", 2)[0] == npz.rsplit(".", 1)[0]

    def test_extension_is_npz(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        assert build_position_analysis_name(n).endswith(".npz")


# --- parse_image_name -------------------------------------------------------


class TestParseImageName:
    def test_round_trip_with_values(self):
        n = Naming(
            acquisition_type="target-acquisition",
            hash6="bf2x91",
            k=1,
            m=47,
            g=2,
            p=123,
            t=5,
            v=1,
            c=2,
            z=10,
        )
        assert parse_image_name(build_image_name(n)) == n

    def test_round_trip_all_zero(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        assert parse_image_name(build_image_name(n)) == n

    def test_round_trip_multi_hyphen(self):
        n = Naming(acquisition_type="my-cool-scan", hash6="abcdef", k=42)
        assert parse_image_name(build_image_name(n)) == n

    def test_round_trip_at_max_values(self):
        n = Naming(
            acquisition_type="overview-scan",
            hash6="zzzzzz",
            k=99999,
            m=99999,
            g=99999,
            p=99999,
            t=99999,
            v=99,
            c=99,
            z=99999,
        )
        assert parse_image_name(build_image_name(n)) == n

    def test_rejects_garbage(self):
        assert parse_image_name("garbage.tif") is None

    def test_rejects_missing_slot(self):
        # missing _z[NNNNN]
        bad = "overview-scan_0a3k7m_k00000_m00000_g00000_p00000_t00000_v00_c00.ome.tiff"
        assert parse_image_name(bad) is None

    def test_rejects_wrong_extension(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        wrong_ext = build_image_name(n).replace(".ome.tiff", ".tif")
        assert parse_image_name(wrong_ext) is None

    def test_rejects_xml_filename(self):
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m")
        assert parse_image_name(build_xml_name(n)) is None

    def test_rejects_underscore_in_acquisition_type(self):
        bad = "over_scan_0a3k7m_k00000_m00000_g00000_p00000_t00000_v00_c00_z00000.ome.tiff"
        assert parse_image_name(bad) is None


# --- LayoutPlan helpers -----------------------------------------------------


class TestLayoutPlan:
    def test_run_dir(self, tmp_path):
        layout = LayoutPlan(
            output_root=tmp_path,
            experiment="exp",
            hash6="0a3k7m",
            start_time_utc=EPOCH + 1000,
        )
        assert layout.run_dir == tmp_path / "exp_0a3k7m"

    def test_acquisition_dir(self, tmp_path):
        layout = LayoutPlan(tmp_path, "exp", "0a3k7m", EPOCH + 1000)
        assert layout.acquisition_dir("overview-scan") == tmp_path / "exp_0a3k7m" / "overview-scan"

    def test_data_metadata_analysis_logs(self, tmp_path):
        layout = LayoutPlan(tmp_path, "exp", "0a3k7m", EPOCH + 1000)
        acq = "overview-scan"
        assert layout.data_dir(acq) == layout.run_dir / acq / "data"
        assert layout.metadata_dir(acq) == layout.run_dir / acq / "data" / "metadata"
        assert layout.analysis_dir(acq) == layout.run_dir / acq / "analysis"
        assert layout.logs_dir(acq) == layout.run_dir / acq / "logs"

    def test_logs_dir_accepts_any_kind(self, tmp_path):
        # "initialization" is a kind like any other -- acquisition_dir
        # takes any string, so logs_dir does too.
        layout = LayoutPlan(tmp_path, "exp", "0a3k7m", EPOCH + 1000)
        assert layout.logs_dir("initialization") == (layout.run_dir / "initialization" / "logs")


# --- build_layout (atomic mkdir + collision bump) ---------------------------


class TestBuildLayout:
    def test_creates_run_dir(self, tmp_path):
        layout = build_layout(tmp_path, "my-experiment")
        assert layout.run_dir.exists()
        assert layout.run_dir.is_dir()
        assert layout.run_dir.name.startswith("my-experiment_")

    def test_layout_fields_populated(self, tmp_path):
        layout = build_layout(tmp_path, "exp", start_time=EPOCH + 1000)
        assert layout.experiment == "exp"
        assert layout.output_root == tmp_path
        assert layout.start_time_utc == EPOCH + 1000
        assert len(layout.hash6) == 6

    def test_deterministic_hash_from_start_time(self, tmp_path):
        layout = build_layout(tmp_path, "exp", start_time=EPOCH + 1000)
        assert layout.hash6 == run_hash(EPOCH + 1000)

    def test_collision_bumps_by_one_second(self, tmp_path):
        t0 = EPOCH + 1000
        first = build_layout(tmp_path, "exp", start_time=t0)
        second = build_layout(tmp_path, "exp", start_time=t0)
        assert first.hash6 != second.hash6
        assert second.start_time_utc == t0 + 1
        assert second.hash6 == run_hash(t0 + 1)

    def test_collision_cap_raises(self, tmp_path):
        t0 = EPOCH + 1000
        # Pre-create 10 dirs to exhaust the retry cap
        for offset in range(10):
            h = run_hash(t0 + offset)
            (tmp_path / f"exp_{h}").mkdir()
        with pytest.raises(RuntimeError, match="consecutive 1-second slots"):
            build_layout(tmp_path, "exp", start_time=t0)

    def test_creates_output_root_if_missing(self, tmp_path):
        nested = tmp_path / "does" / "not" / "exist"
        layout = build_layout(nested, "exp")
        assert layout.run_dir.exists()

    def test_rejects_empty_experiment(self, tmp_path):
        with pytest.raises(ValueError, match="non-empty"):
            build_layout(tmp_path, "")

    def test_rejects_too_long_experiment(self, tmp_path):
        with pytest.raises(ValueError, match="too long"):
            build_layout(tmp_path, "a" * (MAX_EXPERIMENT_LEN + 1))

    def test_experiment_at_cap_accepted(self, tmp_path):
        layout = build_layout(tmp_path, "a" * MAX_EXPERIMENT_LEN)
        assert layout.run_dir.exists()

    def test_rejects_spaces_in_experiment(self, tmp_path):
        with pytest.raises(ValueError, match="must match"):
            build_layout(tmp_path, "experiment with spaces")

    def test_rejects_slashes_in_experiment(self, tmp_path):
        with pytest.raises(ValueError, match="must match"):
            build_layout(tmp_path, "exp/with/slashes")

    def test_accepts_alnum_underscore_hyphen(self, tmp_path):
        layout = build_layout(tmp_path, "Exp_2026-05-11")
        assert layout.run_dir.exists()
