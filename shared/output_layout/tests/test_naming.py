"""Unit tests for the lab-wide output naming convention."""

from __future__ import annotations

import pytest
from shared.output_layout.naming import (
    EPOCH,
    MAX_ACQUISITION_TYPE_LEN,
    MAX_EXPERIMENT_LEN,
    MAX_POSITION_LABEL_LEN,
    LayoutPlan,
    Naming,
    build_image_name,
    build_layout,
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
        n = Naming(acquisition_type="overview-scan", hash6="0a3k7m", position_label="000000")
        assert n.acquisition_type == "overview-scan"

    def test_single_token(self):
        n = Naming(acquisition_type="overview", hash6="0a3k7m", position_label="A1")
        assert n.acquisition_type == "overview"

    def test_multi_hyphen(self):
        n = Naming(acquisition_type="overview-scan-fast", hash6="0a3k7m", position_label="A1")
        assert n.acquisition_type == "overview-scan-fast"

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="Overview-Scan", hash6="0a3k7m", position_label="A1")

    def test_rejects_underscore(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview_scan", hash6="0a3k7m", position_label="A1")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="-overview", hash6="0a3k7m", position_label="A1")

    def test_rejects_trailing_hyphen(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview-", hash6="0a3k7m", position_label="A1")

    def test_rejects_double_hyphen(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview--scan", hash6="0a3k7m", position_label="A1")

    def test_rejects_space(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Naming(acquisition_type="overview scan", hash6="0a3k7m", position_label="A1")

    def test_at_length_cap_accepted(self):
        at_cap = "a" * MAX_ACQUISITION_TYPE_LEN
        n = Naming(acquisition_type=at_cap, hash6="0a3k7m", position_label="A1")
        assert len(n.acquisition_type) == MAX_ACQUISITION_TYPE_LEN

    def test_rejects_too_long(self):
        too_long = "a" * (MAX_ACQUISITION_TYPE_LEN + 1)
        with pytest.raises(ValueError, match="too long"):
            Naming(acquisition_type=too_long, hash6="0a3k7m", position_label="A1")

    def test_rejects_uppercase_hash(self):
        with pytest.raises(ValueError, match="hash6"):
            Naming(acquisition_type="overview-scan", hash6="ABC123", position_label="A1")

    def test_rejects_short_hash(self):
        with pytest.raises(ValueError, match="hash6"):
            Naming(acquisition_type="overview-scan", hash6="abc12", position_label="A1")

    def test_rejects_long_hash(self):
        with pytest.raises(ValueError, match="hash6"):
            Naming(acquisition_type="overview-scan", hash6="abc1234", position_label="A1")

    # --- position_label ------------------------------------------------------

    def test_counter_label_is_preserved(self):
        n = Naming(acquisition_type="scan", hash6="0a3k7m", position_label="000000")
        assert n.position_label == "000000"

    def test_label_with_safe_chars_preserved(self):
        n = Naming(acquisition_type="scan", hash6="0a3k7m", position_label="well_A1-2")
        assert n.position_label == "well_A1-2"

    def test_unsafe_chars_sanitized_to_underscore(self):
        n = Naming(acquisition_type="scan", hash6="0a3k7m", position_label="well A1/2")
        assert n.position_label == "well_A1_2"

    def test_rejects_empty_label(self):
        with pytest.raises(ValueError, match="non-empty"):
            Naming(acquisition_type="scan", hash6="0a3k7m", position_label="")

    def test_label_at_length_cap_accepted(self):
        at_cap = "a" * MAX_POSITION_LABEL_LEN
        n = Naming(acquisition_type="scan", hash6="0a3k7m", position_label=at_cap)
        assert len(n.position_label) == MAX_POSITION_LABEL_LEN

    def test_rejects_too_long_label(self):
        too_long = "a" * (MAX_POSITION_LABEL_LEN + 1)
        with pytest.raises(ValueError, match="position_label too long"):
            Naming(acquisition_type="scan", hash6="0a3k7m", position_label=too_long)


# --- build_image_name --------------------------------------------------------


class TestBuildNames:
    def test_image_name_all_zero(self):
        n = Naming(acquisition_type="scan", hash6="9k2m4p", position_label="000000")
        assert build_image_name(n) == "scan_9k2m4p_000000_c00_z00000.ome.tiff"

    def test_image_name_with_values(self):
        n = Naming(
            acquisition_type="target-acquisition",
            hash6="bf2x91",
            position_label="well_A1",
            c=2,
            z=10,
        )
        assert build_image_name(n) == (
            "target-acquisition_bf2x91_well_A1_c02_z00010.ome.tiff"
        )

    def test_max_widths_fit(self):
        n = Naming(
            acquisition_type="a" * MAX_ACQUISITION_TYPE_LEN,
            hash6="zzzzzz",
            position_label="z" * MAX_POSITION_LABEL_LEN,
            c=99,
            z=99999,
        )
        # Sanity: the literal max filename is well under 255-char component limit
        assert len(build_image_name(n)) < 255


# --- parse_image_name -------------------------------------------------------


class TestParseImageName:
    def test_round_trip_with_values(self):
        n = Naming(
            acquisition_type="target-acquisition",
            hash6="bf2x91",
            position_label="well_A1-2",
            c=2,
            z=10,
        )
        assert parse_image_name(build_image_name(n)) == n

    def test_round_trip_all_zero(self):
        n = Naming(acquisition_type="scan", hash6="0a3k7m", position_label="000000")
        assert parse_image_name(build_image_name(n)) == n

    def test_round_trip_multi_hyphen(self):
        n = Naming(acquisition_type="my-cool-scan", hash6="abcdef", position_label="P1", z=42)
        assert parse_image_name(build_image_name(n)) == n

    def test_round_trip_at_max_values(self):
        n = Naming(
            acquisition_type="overview-scan",
            hash6="zzzzzz",
            position_label="z" * MAX_POSITION_LABEL_LEN,
            c=99,
            z=99999,
        )
        assert parse_image_name(build_image_name(n)) == n

    def test_rejects_garbage(self):
        assert parse_image_name("garbage.tif") is None

    def test_rejects_missing_slot(self):
        # missing _z[NNNNN]
        bad = "scan_0a3k7m_000000_c00.ome.tiff"
        assert parse_image_name(bad) is None

    def test_rejects_wrong_extension(self):
        n = Naming(acquisition_type="scan", hash6="0a3k7m", position_label="000000")
        wrong_ext = build_image_name(n).replace(".ome.tiff", ".tif")
        assert parse_image_name(wrong_ext) is None

    def test_rejects_xml_filename(self):
        assert parse_image_name("scan_0a3k7m_000000.ome.xml") is None

    def test_rejects_uppercase_in_acquisition_type(self):
        bad = "Over_0a3k7m_000000_c00_z00000.ome.tiff"
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
