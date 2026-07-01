"""Unit tests for routed state readers."""

import dataclasses
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert import readers
from navigator_expert.commands import confirm_select_job
from navigator_expert.config import profiles
from navigator_expert.readers import capabilities, router


class TestStateReaders(unittest.TestCase):
    def setUp(self):
        self._state_profile = profiles.STATE_READERS

    def tearDown(self):
        profiles.STATE_READERS = self._state_profile

    def test_default_profile_uses_api_readers(self):
        profile = profiles.STATE_READERS
        self.assertEqual(profile.xy_mode, "api")
        self.assertEqual(profile.job_settings_mode, "api")
        self.assertEqual(profile.jobs_mode, "api")
        self.assertEqual(profile.selected_job_mode, "api")
        self.assertEqual(profile.hardware_info_mode, "api")
        self.assertEqual(profile.scan_status_mode, "api")

    def test_default_xy_uses_api(self):
        expected = {"x_um": 1.0, "y_um": 2.0}
        with (
            patch.object(router.api_reader, "get_xy", return_value=expected) as api,
            patch.object(router.log_reader, "parse_log") as parse_log,
        ):
            self.assertEqual(readers.get_xy(object()), expected)
        api.assert_called_once()
        parse_log.assert_not_called()

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

    def test_jobs_mode_can_use_log_for_select_job_readback(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            jobs_mode="log",
            jobs_log_max_age_s=2.0,
        )
        snapshot = SimpleNamespace(now=100.0)
        jobs = [{"Name": "Overview", "IsSelected": True}]
        ages = {"jobs": {"Overview": 0.3}, "selected": 0.2}
        with (
            patch.object(router.log_reader, "parse_log", return_value=snapshot),
            patch.object(router.log_reader, "get_jobs", return_value=jobs) as log_jobs,
            patch.object(router.log_reader, "ages", return_value=ages),
        ):
            self.assertEqual(readers.get_jobs(object()), jobs)
        log_jobs.assert_called_once_with(snapshot, max_age_s=2.0)

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
        self.assertEqual(settings["export"]["media_path"], "C:\\data")
        self.assertTrue(settings["export_formats"]["ome_tif"])
        self.assertEqual(
            settings["image_orientation"]["transformation"],
            "RIGHTTOP",
        )


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


if __name__ == "__main__":
    unittest.main()
