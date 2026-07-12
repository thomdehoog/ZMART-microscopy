"""Unit tests for routed state readers."""

import dataclasses
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from navigator_expert import readers
from navigator_expert.commands import confirm_select_job
from navigator_expert.config import profiles
from navigator_expert.readers import capabilities, router


class TestStateReaders(unittest.TestCase):
    def setUp(self):
        self._state_profile = profiles.STATE_READERS

    def tearDown(self):
        profiles.STATE_READERS = self._state_profile

    def test_default_profile_uses_hybrid_readers(self):
        # Maintainer decision (docs/reviews/MAINTAINER_DECISIONS.md §1):
        # hybrid is the default for routed cold reads; api/log stay selectable
        # per datum. Exception: `jobs` is API-pinned because the log only sees
        # the active job, so its list is incomplete (bench 2026-07-06).
        profile = profiles.STATE_READERS
        self.assertEqual(profile.xy_mode, "hybrid")
        self.assertEqual(profile.job_settings_mode, "hybrid")
        self.assertEqual(profile.jobs_mode, "api")
        self.assertEqual(profile.selected_job_mode, "hybrid")
        self.assertEqual(profile.hardware_info_mode, "hybrid")
        self.assertEqual(profile.scan_status_mode, "hybrid")

    def test_default_xy_hybrid_degrades_to_api_without_fresh_log(self):
        expected = {"x_um": 1.0, "y_um": 2.0}
        snapshot = SimpleNamespace(now=100.0)
        with (
            patch.object(router.api_reader, "get_xy", return_value=expected) as api,
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=None),
            patch.object(router.log_reader, "ages", return_value={}),
        ):
            self.assertEqual(readers.get_xy(object()), expected)
        api.assert_called_once()

    def test_hybrid_empty_list_is_a_valid_value_not_a_failure(self):
        # An empty jobs list is a real answer ("no jobs"), not a missing
        # one: only None means no value. The log leg cannot represent
        # "empty" (no evidence == None), so [] must arrive via the api leg
        # and win the hybrid race instead of being retried or dropped.
        snapshot = SimpleNamespace(now=100.0)
        with (
            patch.object(router.api_reader, "get_jobs", return_value=[]) as api,
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_jobs", return_value=None),
            patch.object(router.log_reader, "ages", return_value={}),
        ):
            reading = readers.get_jobs(object(), diagnostics=True)
        self.assertEqual(reading.value, [])
        self.assertEqual(reading.source, "api")
        self.assertIsNone(reading.error)
        api.assert_called_once()

    def test_diagnostics_returns_reading(self):
        expected = {"x_um": 1.0, "y_um": 2.0}
        with patch.object(router.api_reader, "get_xy", return_value=expected):
            reading = readers.get_xy(object(), diagnostics=True)
        self.assertIsInstance(reading, readers.Reading)
        self.assertEqual(reading.value, expected)
        self.assertEqual(reading.source, "api")
        self.assertIsNotNone(reading.observed_at)

    def test_log_mode_returns_fresh_log_value(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="log",
            xy_log_max_age_s=1.0,
        )
        snapshot = SimpleNamespace(now=100.0)
        expected = {"x_um": 3.0, "y_um": 4.0}
        with (
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=expected) as log_xy,
            patch.object(router.log_reader, "ages", return_value={"xy": 0.2}),
        ):
            self.assertEqual(readers.get_xy(object()), expected)
        log_xy.assert_called_once_with(snapshot, max_age_s=1.0)

    def test_log_mode_rejects_stale_log_value(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="log",
            xy_log_max_age_s=1.0,
        )
        snapshot = SimpleNamespace(now=100.0)
        with (
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=None),
            patch.object(router.log_reader, "ages", return_value={"xy": 5.0}),
        ):
            self.assertIsNone(readers.get_xy(object()))

    def test_hybrid_returns_log_when_api_hangs(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="hybrid",
            xy_log_max_age_s=1.0,
            xy_timeout_s=1.0,
        )
        snapshot = SimpleNamespace(now=100.0)
        expected = {"x_um": 5.0, "y_um": 6.0}

        def slow_api(*_args, **_kwargs):
            time.sleep(0.25)
            return {"x_um": 100.0, "y_um": 200.0}

        with (
            patch.object(router.api_reader, "get_xy", side_effect=slow_api),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=expected),
            patch.object(router.log_reader, "ages", return_value={"xy": 0.1}),
        ):
            reading = readers.get_xy(object(), diagnostics=True)
        self.assertEqual(reading.source, "log")
        self.assertEqual(reading.value, expected)

    def test_hybrid_prefers_fresh_log_over_faster_api(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="hybrid",
            xy_log_max_age_s=1.0,
            xy_timeout_s=1.0,
            hybrid_log_grace_s=0.25,
        )
        snapshot = SimpleNamespace(now=100.0)
        api_value = {"x_um": 100.0, "y_um": 200.0}
        log_value = {"x_um": 5.0, "y_um": 6.0}

        def delayed_log(*_args, **_kwargs):
            time.sleep(0.05)
            return log_value

        with (
            patch.object(router.api_reader, "get_xy", return_value=api_value),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", side_effect=delayed_log),
            patch.object(router.log_reader, "ages", return_value={"xy": 0.1}),
        ):
            reading = readers.get_xy(object(), diagnostics=True)
        self.assertEqual(reading.source, "log")
        self.assertEqual(reading.value, log_value)

    def test_hybrid_ignores_untrustworthy_log_and_returns_api(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="hybrid",
            xy_log_max_age_s=1.0,
            xy_timeout_s=1.0,
        )
        snapshot = SimpleNamespace(now=100.0)
        expected = {"x_um": 7.0, "y_um": 8.0}
        with (
            patch.object(router.api_reader, "get_xy", return_value=expected),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=None),
            patch.object(router.log_reader, "ages", return_value={"xy": 9.0}),
        ):
            reading = readers.get_xy(object(), diagnostics=True)
        self.assertEqual(reading.source, "api")
        self.assertEqual(reading.value, expected)

    def test_hybrid_does_not_start_second_api_read_while_one_is_pending(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="hybrid",
            xy_log_max_age_s=1.0,
            xy_timeout_s=1.0,
        )
        client = object()
        snapshot = SimpleNamespace(now=100.0)
        log_value = {"x_um": 5.0, "y_um": 6.0}
        api_started = threading.Event()
        release_api = threading.Event()
        api_calls = []
        first_result = []

        def blocked_api(*_args, **_kwargs):
            api_calls.append(1)
            api_started.set()
            release_api.wait(timeout=2.0)
            return {"x_um": 100.0, "y_um": 200.0}

        with (
            patch.object(router.api_reader, "get_xy", side_effect=blocked_api),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=log_value),
            patch.object(router.log_reader, "ages", return_value={"xy": 0.1}),
        ):
            first = threading.Thread(
                target=lambda: first_result.append(readers.get_xy(client, diagnostics=True)),
                daemon=True,
            )
            first.start()
            self.assertTrue(api_started.wait(timeout=1.0))

            second = readers.get_xy(client, diagnostics=True)
            release_api.set()
            first.join(timeout=2.0)

        self.assertEqual(len(api_calls), 1)
        self.assertEqual(second.source, "log")
        self.assertEqual(second.value, log_value)
        self.assertEqual(first_result[0].source, "log")

    def test_jobs_has_no_log_leg_and_always_comes_from_api(self):
        # Bench 2026-07-06: the log stream only reports the ACTIVE job, so the
        # job LIST has no log source. jobs is API-only — mode="log" fails
        # closed (UnsupportedSource), and mode="hybrid" degrades to api.
        profiles.STATE_READERS = profiles.StateReaderProfile(jobs_mode="log")
        reading = readers.get_jobs(object(), diagnostics=True)
        self.assertIsNone(reading.value)
        self.assertIsInstance(reading.error, capabilities.UnsupportedSource)

        full = [{"Name": "A"}, {"Name": "B"}, {"Name": "C"}]
        for mode in ("api", "hybrid"):
            profiles.STATE_READERS = profiles.StateReaderProfile(jobs_mode=mode)
            with (
                patch.object(router.api_reader, "get_jobs", return_value=full) as api,
                patch.object(router.log_reader, "parse_log"),
                patch.object(router.log_reader, "get_jobs") as log_jobs,
            ):
                self.assertEqual(readers.get_jobs(object()), full)
            api.assert_called_once()
            log_jobs.assert_not_called()

    def test_selected_job_log_route_is_independent_from_job_list_route(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            jobs_mode="log",
            jobs_log_max_age_s=2.0,
            selected_job_mode="log",
            selected_job_log_max_age_s=2.0,
        )
        snapshot = SimpleNamespace(now=100.0)
        selected = {"Name": "Overview", "IsSelected": True}
        ages = {"jobs": {}, "job_list": 30.0, "current_block": 0.3}
        with (
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_jobs", return_value=None) as log_jobs,
            patch.object(
                router.log_reader, "get_selected_job", return_value=selected
            ) as log_selected,
            patch.object(router.log_reader, "ages", return_value=ages),
        ):
            self.assertEqual(readers.get_selected_job(object()), selected)
        log_jobs.assert_not_called()
        log_selected.assert_called_once_with(snapshot, max_age_s=2.0)

    def test_confirmation_rejects_pre_command_reading(self):
        old = readers.Reading(
            value=[{"Name": "Overview", "IsSelected": True}],
            source="log",
            observed_at=time.time() - 10.0,
            age_s=10.0,
        )
        fresh = readers.Reading(
            value=[{"Name": "Overview", "IsSelected": True}],
            source="log",
            observed_at=time.time() + 1.0,
            age_s=0.0,
        )
        with (
            patch.object(
                confirm_select_job._readers,
                "get_jobs",
                side_effect=[old, fresh],
            ),
            patch("time.sleep"),
        ):
            result = confirm_select_job.confirm_select_job(
                object(),
                job_name="Overview",
                timeout=1.0,
                poll_interval=0.001,
            )
        self.assertTrue(result["success"])

    def test_confirm_select_job_pins_api_mode(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(jobs_mode="hybrid")
        calls = []

        def fake_get_jobs(client, **kwargs):
            calls.append(kwargs)
            return readers.Reading(
                value=[{"Name": "Overview", "IsSelected": True}],
                source="api",
                observed_at=time.time() + 1.0,
                age_s=0.0,
            )

        with (
            patch.object(confirm_select_job._readers, "get_jobs", side_effect=fake_get_jobs),
            patch("time.sleep"),
        ):
            result = confirm_select_job.confirm_select_job(
                object(),
                job_name="Overview",
                timeout=1.0,
                poll_interval=0.001,
            )

        self.assertTrue(result["success"])
        self.assertEqual(calls[0]["mode"], "api")
        self.assertTrue(calls[0]["diagnostics"])

    def test_get_lasx_settings_returns_consumed_sections_only(self):
        xml = """<Root>
          <SettingsGeneral>
            <DeleteLogFilesOlderThanTheLastDays>5</DeleteLogFilesOlderThanTheLastDays>
          </SettingsGeneral>
          <SettingsNavigatorExpert>
            <SettingsDataExporter>
              <MediaPath>C:\\data</MediaPath>
              <ExportDataAutomatically>true</ExportDataAutomatically>
              <DeleteExportedExperiments>false</DeleteExportedExperiments>
              <UseAutoSave>false</UseAutoSave>
              <SaveLIFInExperimentFolder>true</SaveLIFInExperimentFolder>
            </SettingsDataExporter>
            <ExportFileFormats>
              <AsOmeTifFile>true</AsOmeTifFile>
              <AsMultiPageOmeTifFile>false</AsMultiPageOmeTifFile>
              <AsMultiPageTifFile>false</AsMultiPageTifFile>
              <EnableImageCompression>false</EnableImageCompression>
              <ImageCompressionValue>0</ImageCompressionValue>
            </ExportFileFormats>
            <SettingsExportedImage>
              <EnableImageTransformation>true</EnableImageTransformation>
              <ImageTransformation>RIGHTTOP</ImageTransformation>
            </SettingsExportedImage>
          </SettingsNavigatorExpert>
        </Root>"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(xml)
            path = fh.name
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))

        settings = readers.get_lasx_settings(settings_path=path)

        self.assertEqual(
            set(settings),
            {"export", "export_formats", "image_orientation"},
        )
        self.assertTrue(settings["export_formats"]["ome_tif"])
        self.assertEqual(
            settings["image_orientation"]["transformation"],
            "RIGHTTOP",
        )


class TestApiModeCappedWorker(unittest.TestCase):
    """mode="api" must run in the capped worker with the profile timeout."""

    def setUp(self):
        self._state_profile = profiles.STATE_READERS

    def tearDown(self):
        profiles.STATE_READERS = self._state_profile

    def test_api_mode_hung_read_returns_none_after_timeout(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_timeout_s=0.2)
        release = threading.Event()

        def hung_api(*_args, **_kwargs):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        try:
            with patch.object(router.api_reader, "get_xy", side_effect=hung_api):
                t0 = time.monotonic()
                result = readers.get_xy(object(), mode="api")
                elapsed = time.monotonic() - t0
            self.assertIsNone(result)
            self.assertLess(elapsed, 2.0)  # caller must not block on the hang
        finally:
            release.set()

    def test_api_mode_respects_in_flight_cap(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_timeout_s=0.2)
        release = threading.Event()
        client = object()

        def hung_api(*_args, **_kwargs):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        try:
            with patch.object(router.api_reader, "get_xy", side_effect=hung_api) as api:
                self.assertIsNone(readers.get_xy(client, mode="api"))  # parks the worker
                self.assertIsNone(readers.get_xy(client, mode="api"))  # must not pile on
                self.assertEqual(api.call_count, 1)
        finally:
            release.set()

    def test_api_mode_error_reading_carries_error_in_diagnostics(self):
        with patch.object(router.api_reader, "get_xy", side_effect=RuntimeError("com fault")):
            reading = readers.get_xy(object(), mode="api", diagnostics=True)
        self.assertIsNotNone(reading)
        self.assertIsNone(reading.value)
        self.assertIsInstance(reading.error, RuntimeError)

    def test_api_mode_hung_read_reports_timeout_in_diagnostics(self):
        """Regression: a timed-out API read must give diagnostics callers the
        documented error-carrying Reading, not bare None. The hung-CAM case
        (a modal LAS X dialog) is exactly the failure diagnostics exist to
        explain."""
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_timeout_s=0.2)
        release = threading.Event()

        def hung_api(*_args, **_kwargs):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        try:
            with patch.object(router.api_reader, "get_xy", side_effect=hung_api):
                reading = readers.get_xy(object(), mode="api", diagnostics=True)
            self.assertIsNotNone(reading)
            self.assertIsNone(reading.value)
            self.assertEqual(reading.source, "api")
            self.assertIsInstance(reading.error, router.ApiReadTimeout)
            self.assertIn("timed out", str(reading.error))
        finally:
            release.set()

    def test_api_mode_blocked_in_flight_slot_reports_timeout_in_diagnostics(self):
        """A read that never got the in-flight slot (another read is parked on
        a hung CAM call) also reports the timeout instead of bare None."""
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_timeout_s=0.2)
        release = threading.Event()
        client = object()

        def hung_api(*_args, **_kwargs):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        try:
            with patch.object(router.api_reader, "get_xy", side_effect=hung_api):
                readers.get_xy(client, mode="api")  # parks the worker
                reading = readers.get_xy(client, mode="api", diagnostics=True)
            self.assertIsNotNone(reading)
            self.assertIsNone(reading.value)
            self.assertIsInstance(reading.error, router.ApiReadTimeout)
        finally:
            release.set()


class TestDerivedZoom(unittest.TestCase):
    def test_sub_unity_zoom_is_not_clamped(self):
        from navigator_expert.readers import derived

        settings = {
            "imageSize": "100.0 um x 100.0 um",
            "format": "512 x 512",
            "zoom": {"current": 0.75},
        }
        fov = derived.base_fov_from_settings(settings)
        self.assertIsNotNone(fov)
        self.assertAlmostEqual(fov[0], 100.0e-6 * 0.75)


class TestMissingLegs(unittest.TestCase):
    """A family asked for a leg the datum lacks fails closed with a
    recorded ``UnsupportedSource`` reason; hybrid degrades to the legs
    that exist."""

    def test_api_mode_without_api_leg_fails_closed_with_reason(self):
        log_only = dataclasses.replace(capabilities.spec("xy"), api_fn=None)
        with patch.dict(capabilities.DATUMS, {"xy": log_only}):
            reading = readers.get_xy(object(), mode="api", diagnostics=True)
            self.assertIsNone(reading.value)
            self.assertIsInstance(reading.error, capabilities.UnsupportedSource)
            self.assertIn("no api leg", str(reading.error))
            # the plain-value contract fails closed to None
            self.assertIsNone(readers.get_xy(object(), mode="api"))

    def test_hybrid_degrades_to_log_when_api_leg_missing(self):
        log_only = dataclasses.replace(capabilities.spec("xy"), api_fn=None)
        snapshot = SimpleNamespace(now=100.0)
        expected = {"x_um": 3.0, "y_um": 4.0}
        with (
            patch.dict(capabilities.DATUMS, {"xy": log_only}),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", return_value=expected),
            patch.object(router.log_reader, "ages", return_value={"xy": 0.1}),
        ):
            reading = readers.get_xy(object(), mode="hybrid", diagnostics=True)
        self.assertEqual(reading.source, "log")
        self.assertEqual(reading.value, expected)

    def test_hybrid_degrades_to_api_when_log_leg_missing(self):
        api_only = dataclasses.replace(capabilities.spec("xy"), log_fn=None)
        expected = {"x_um": 7.0, "y_um": 8.0}
        with (
            patch.dict(capabilities.DATUMS, {"xy": api_only}),
            patch.object(router.api_reader, "get_xy", return_value=expected),
            patch.object(router.log_reader, "parse_log") as parse_log,
        ):
            reading = readers.get_xy(object(), mode="hybrid", diagnostics=True)
        self.assertEqual(reading.source, "api")
        self.assertEqual(reading.value, expected)
        parse_log.assert_not_called()


class TestAgeForSnapshot(unittest.TestCase):
    """age_for_snapshot must report the age of the datum that produced the
    value, mirroring the log readers' derivation order -- not a min/max over
    tangential timestamps."""

    def _age(self, ages, **kwargs):
        with patch.object(capabilities.log_reader, "ages", return_value=ages):
            return capabilities.age_for_snapshot(SimpleNamespace(now=100.0), **kwargs)

    def test_jobs_fresh_summary_ignores_ancient_cluster(self):
        # get_jobs derives the list from the fresh matrix summary; ancient
        # per-job ATL lines and stale selection markers are tangential.
        ages = {"job_list": 0.2, "jobs": {"A": 300.0, "B": 250.0}, "selected": 400.0}
        self.assertEqual(self._age(ages, age_key="jobs", max_age_s=2.0), 0.2)

    def test_jobs_cluster_fallback_bounds_by_oldest_job_line(self):
        ages = {"job_list": None, "jobs": {"A": 0.4, "B": 1.1}}
        self.assertEqual(self._age(ages, age_key="jobs", max_age_s=2.0), 1.1)

    def test_jobs_stale_summary_falls_back_to_cluster(self):
        # The reader refuses a summary older than max_age_s and derives from
        # the ATL cluster; the age must mirror that.
        ages = {"job_list": 500.0, "jobs": {"A": 0.4, "B": 1.1}}
        self.assertEqual(self._age(ages, age_key="jobs", max_age_s=2.0), 1.1)

    def test_selected_job_stale_current_block_must_not_report_fresh_intent(self):
        # Regression: value from CurrentBlock, min() reported the fresher
        # SetCurrentSelectedElementID intent echo -- stale value, fresh age.
        ages = {"current_block": 1.8, "selected": 0.1}
        self.assertEqual(self._age(ages, age_key="selected_job", max_age_s=2.0), 1.8)

    def test_selected_job_without_current_block_uses_intent(self):
        ages = {"current_block": None, "selected": 0.4}
        self.assertEqual(self._age(ages, age_key="selected_job", max_age_s=2.0), 0.4)

    def test_selected_job_refused_current_block_uses_intent(self):
        ages = {"current_block": 500.0, "selected": 0.4}
        self.assertEqual(self._age(ages, age_key="selected_job", max_age_s=2.0), 0.4)

    def test_job_name_path_reads_per_job_age(self):
        ages = {"jobs": {"A": 0.7}}
        self.assertEqual(self._age(ages, job_name="A"), 0.7)

    def test_plain_keys_pass_through(self):
        ages = {"xy": 0.9}
        self.assertEqual(self._age(ages, age_key="xy"), 0.9)


class TestRoutedErrorAndDiagnosticShapes(unittest.TestCase):
    """Failure paths must return error-carrying Readings (diagnostics) and
    fail closed to None (plain), never leak values or raise."""

    def setUp(self):
        self._state_profile = profiles.STATE_READERS

    def tearDown(self):
        profiles.STATE_READERS = self._state_profile

    def test_unknown_mode_raises_value_error(self):
        with self.assertRaises(ValueError):
            readers.get_xy(object(), mode="bogus")

    def test_replace_value_none_strips_value_and_keeps_provenance(self):
        err = RuntimeError("boom")
        reading = readers.Reading(
            value={"x_um": 1.0}, source="api", observed_at=42.0, age_s=0.5, error=err
        )
        stripped = reading._replace_value_none()
        self.assertIsNone(stripped.value)
        self.assertEqual(stripped.source, "api")
        self.assertEqual(stripped.observed_at, 42.0)
        self.assertEqual(stripped.age_s, 0.5)
        self.assertIs(stripped.error, err)

    def test_replace_value_none_is_identity_when_value_already_none(self):
        reading = readers.Reading(value=None, source="log", observed_at=1.0, age_s=0.1)
        self.assertIs(reading._replace_value_none(), reading)

    def test_log_mode_reader_exception_carries_error_in_diagnostics(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_mode="log")
        with patch.object(
            router.log_reader, "parse_log", side_effect=RuntimeError("log unreadable")
        ):
            reading = readers.get_xy(object(), diagnostics=True)
            self.assertEqual(reading.source, "log")
            self.assertIsNone(reading.value)
            self.assertIsInstance(reading.error, RuntimeError)
            # the plain-value contract fails closed to None
            self.assertIsNone(readers.get_xy(object()))

    def test_log_mode_without_log_leg_fails_closed_with_reason(self):
        api_only = dataclasses.replace(capabilities.spec("xy"), log_fn=None)
        with patch.dict(capabilities.DATUMS, {"xy": api_only}):
            reading = readers.get_xy(object(), mode="log", diagnostics=True)
            self.assertIsNone(reading.value)
            self.assertIsInstance(reading.error, capabilities.UnsupportedSource)
            self.assertIn("no log leg", str(reading.error))
            self.assertIsNone(readers.get_xy(object(), mode="log"))

    def test_hybrid_without_any_leg_fails_closed_with_reason(self):
        no_legs = dataclasses.replace(capabilities.spec("xy"), api_fn=None, log_fn=None)
        with patch.dict(capabilities.DATUMS, {"xy": no_legs}):
            reading = readers.get_xy(object(), mode="hybrid", diagnostics=True)
        self.assertIsNone(reading.value)
        self.assertIsInstance(reading.error, capabilities.UnsupportedSource)
        self.assertIn("no hybrid leg", str(reading.error))

    def test_hybrid_api_only_hung_read_returns_none_after_timeout(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_timeout_s=0.1)
        api_only = dataclasses.replace(capabilities.spec("xy"), log_fn=None)
        release = threading.Event()

        def hung_api(*_args, **_kwargs):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        try:
            with (
                patch.dict(capabilities.DATUMS, {"xy": api_only}),
                patch.object(router.api_reader, "get_xy", side_effect=hung_api),
            ):
                self.assertIsNone(readers.get_xy(object(), mode="hybrid"))
        finally:
            release.set()

    def test_hybrid_api_only_hung_read_reports_timeout_in_diagnostics(self):
        """The api-only hybrid leg reports the same timeout diagnostics as
        pure api mode (regression companion to the plain-None test above)."""
        profiles.STATE_READERS = profiles.StateReaderProfile(xy_timeout_s=0.1)
        api_only = dataclasses.replace(capabilities.spec("xy"), log_fn=None)
        release = threading.Event()

        def hung_api(*_args, **_kwargs):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        try:
            with (
                patch.dict(capabilities.DATUMS, {"xy": api_only}),
                patch.object(router.api_reader, "get_xy", side_effect=hung_api),
            ):
                reading = readers.get_xy(object(), mode="hybrid", diagnostics=True)
            self.assertIsNotNone(reading)
            self.assertIsNone(reading.value)
            self.assertIsInstance(reading.error, router.ApiReadTimeout)
        finally:
            release.set()

    def test_hybrid_log_only_error_reading_carries_error(self):
        log_only = dataclasses.replace(capabilities.spec("xy"), api_fn=None)
        with (
            patch.dict(capabilities.DATUMS, {"xy": log_only}),
            patch.object(router.log_reader, "parse_log", side_effect=RuntimeError("gone")),
        ):
            reading = readers.get_xy(object(), mode="hybrid", diagnostics=True)
        self.assertEqual(reading.source, "log")
        self.assertIsNone(reading.value)
        self.assertIsInstance(reading.error, RuntimeError)


class TestHybridGraceWindow(unittest.TestCase):
    """Log wins within the grace window; API wins once it expires."""

    def setUp(self):
        self._state_profile = profiles.STATE_READERS

    def tearDown(self):
        profiles.STATE_READERS = self._state_profile

    def test_api_wins_after_grace_expires_without_a_log_result(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="hybrid",
            xy_log_max_age_s=1.0,
            xy_timeout_s=5.0,
            hybrid_log_grace_s=0.05,
        )
        api_value = {"x_um": 100.0, "y_um": 200.0}

        def slow_log(*_args, **_kwargs):
            time.sleep(1.0)  # never lands inside the grace window
            return {"x_um": 5.0, "y_um": 6.0}

        snapshot = SimpleNamespace(now=100.0)
        with (
            patch.object(router.api_reader, "get_xy", return_value=api_value),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", side_effect=slow_log),
            patch.object(router.log_reader, "ages", return_value={"xy": 0.1}),
        ):
            t0 = time.monotonic()
            reading = readers.get_xy(object(), diagnostics=True)
            elapsed = time.monotonic() - t0
        self.assertEqual(reading.source, "api")
        self.assertEqual(reading.value, api_value)
        self.assertLess(elapsed, 0.9)  # bounded by the grace window, not the log

    def test_untrusted_log_after_api_candidate_returns_api_before_grace_expires(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            xy_mode="hybrid",
            xy_log_max_age_s=1.0,
            xy_timeout_s=5.0,
            hybrid_log_grace_s=2.0,
        )
        api_value = {"x_um": 7.0, "y_um": 8.0}

        def stale_log(*_args, **_kwargs):
            time.sleep(0.05)
            return None  # untrustworthy: no fresh evidence

        snapshot = SimpleNamespace(now=100.0)
        with (
            patch.object(router.api_reader, "get_xy", return_value=api_value),
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_xy", side_effect=stale_log),
            patch.object(router.log_reader, "ages", return_value={"xy": 9.0}),
        ):
            t0 = time.monotonic()
            reading = readers.get_xy(object(), diagnostics=True)
            elapsed = time.monotonic() - t0
        self.assertEqual(reading.source, "api")
        self.assertEqual(reading.value, api_value)
        self.assertLess(elapsed, 1.5)  # untrusted log releases the grace wait


class TestDerivedReaderFamilies(unittest.TestCase):
    """get_job_by_name / get_fov / get_base_fov / read_zwide_um /
    get_pending_dialog derive values while preserving the underlying
    reading's provenance."""

    _SETTINGS = {
        "imageSize": "100.0 um x 100.0 um",
        "format": "512 x 512",
        "zoom": {"current": 2.0},
        "scanSpeed": {"value": 400, "isResonant": False},
        "activeSettings": [],
        "zPosition": {"z-wide": {"position": 42.5}},
    }

    def test_get_job_by_name_returns_named_job_with_provenance(self):
        jobs = [{"Name": "Overview"}, {"Name": "HiRes", "IsSelected": True}]
        with patch.object(router.api_reader, "get_jobs", return_value=jobs):
            plain = readers.get_job_by_name(object(), "HiRes", mode="api")
            reading = readers.get_job_by_name(object(), "HiRes", mode="api", diagnostics=True)
        self.assertEqual(plain, jobs[1])
        self.assertEqual(reading.value, jobs[1])
        self.assertEqual(reading.source, "api")
        self.assertIsNotNone(reading.observed_at)

    def test_get_job_by_name_unknown_name_is_none_with_provenance(self):
        jobs = [{"Name": "Overview"}]
        with patch.object(router.api_reader, "get_jobs", return_value=jobs):
            self.assertIsNone(readers.get_job_by_name(object(), "Nope", mode="api"))
            reading = readers.get_job_by_name(object(), "Nope", mode="api", diagnostics=True)
        self.assertIsNone(reading.value)
        self.assertEqual(reading.source, "api")

    def test_get_fov_and_base_fov_derive_metres_from_settings(self):
        with patch.object(router.api_reader, "get_job_settings", return_value=self._SETTINGS):
            fov = readers.get_fov(object(), "HiRes", mode="api")
            base = readers.get_base_fov(object(), "HiRes", mode="api", diagnostics=True)
        self.assertAlmostEqual(fov[0], 100.0e-6)
        self.assertAlmostEqual(fov[1], 100.0e-6)
        # base FOV backs out the zoom: 100 um image at zoom 2 -> 200 um base
        self.assertAlmostEqual(base.value[0], 200.0e-6)
        self.assertEqual(base.source, "api")

    def test_read_zwide_um_returns_position_from_settings(self):
        with patch.object(router.api_reader, "get_job_settings", return_value=self._SETTINGS):
            self.assertEqual(readers.read_zwide_um(object(), "HiRes", mode="api"), 42.5)

    def test_read_zwide_um_unreadable_settings_returns_none(self):
        with patch.object(
            router.api_reader, "get_job_settings", side_effect=RuntimeError("COM fault")
        ):
            self.assertIsNone(readers.read_zwide_um(object(), "HiRes", mode="api"))

    def test_get_pending_dialog_reports_log_provenance_and_age(self):
        snapshot = SimpleNamespace(now=100.0)
        dialog = {"title": "Warning", "text": "Stage limit"}
        with (
            patch.object(router.log_reader, "parse_msgbox_log", return_value=snapshot),
            patch.object(router.log_reader, "get_pending_dialog", return_value=dialog),
            patch.object(router.log_reader, "ages", return_value={"dialog": 0.5}),
        ):
            plain = readers.get_pending_dialog()
            reading = readers.get_pending_dialog(diagnostics=True)
        self.assertEqual(plain, dialog)
        self.assertEqual(reading.value, dialog)
        self.assertEqual(reading.source, "log")
        self.assertEqual(reading.age_s, 0.5)
        self.assertAlmostEqual(reading.observed_at, 99.5)


if __name__ == "__main__":
    unittest.main()
