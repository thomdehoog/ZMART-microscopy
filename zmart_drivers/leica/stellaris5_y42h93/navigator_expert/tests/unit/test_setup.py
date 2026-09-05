"""The Leica's setup side, offline: what it declares, reads and publishes.

The instrument itself is patched at the reader/command seams the adapter tests
use, so none of this needs LAS X. What is asserted is the contract with the
setup seam: every subsystem is declared, reading resolves the newest snapshot
or the bundled default and says which, and publishing writes a dated snapshot
in the shape the driver reads back at connect.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navigator_expert.config.machine import MachineProfile, is_snapshot_name
from navigator_expert.zmart_adapter import setup as leica_setup
from navigator_expert.zmart_adapter import zmart_adapter as adapter
from zmart_setup import registry as setup_registry


def _settings(z_wide_um=50.0, z_galvo_um=0.0, slot=3):
    return {
        "objective": {"name": "HC PL APO 63x/1.40 OIL CS2", "magnification": 63, "slotIndex": slot},
        "zPosition": {"z-wide": {"position": z_wide_um}, "z-galvo": {"position": z_galvo_um}},
        "imageSize": {"x": 1024, "y": 1024},
    }


def _handle():
    return leica_setup.SetupHandle(client=object(), connection=dict(leica_setup.CONNECTION), hash6="abc123")


class TestRegistration(unittest.TestCase):
    def test_importing_the_setup_registers_with_the_setup_registry_only(self):
        entry = setup_registry.REGISTRY.get(("leica", "stellaris5-y42h93", "navigator-expert"))
        self.assertIsNotNone(entry, "importing the setup module must register it")
        for op in setup_registry.OPS:
            self.assertIn(op, entry["ops"])
        self.assertIn("markers", entry["ops"])
        self.assertIn("objective", entry["ops"])

    def test_the_setup_shares_the_operating_identity(self):
        for key in ("vendor", "microscope", "api"):
            self.assertEqual(leica_setup.CONNECTION[key], adapter.CONNECTION[key])


class TestDescribe(unittest.TestCase):
    def test_all_four_subsystems_and_the_limits_document_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with (
                patch.object(leica_setup._machine, "MACHINE", profile),
                patch.object(leica_setup.drv, "ping", return_value=True),
            ):
                said = leica_setup.describe(_handle())
        self.assertEqual(said["checks"]["api"], "answering")
        self.assertIn("fallback", said["checks"]["limits"])
        for name in ("limits", "orientation", "calibration", "origin"):
            self.assertTrue(said["subsystems"][name]["supported"])
        document = said["subsystems"]["limits"]["document"]
        self.assertEqual([a["key"] for a in document["axes"]], ["x_um", "y_um", "z_galvo_um", "z_wide_um"])
        self.assertEqual(document["measured"], ["x_um", "y_um"])
        self.assertEqual(len(document["settings"]), 20)


class TestReadAndPublish(unittest.TestCase):
    def test_limits_read_the_bundled_default_until_published_then_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with patch.object(leica_setup._machine, "MACHINE", profile):
                before = leica_setup.read(_handle(), "limits")
                self.assertEqual(before["source"], "default")
                document = dict(before["document"])
                document["x_um"] = {"range": [2000.0, 120000.0]}
                published = leica_setup.publish(_handle(), "limits", document)
                after = leica_setup.read(_handle(), "limits")
        self.assertEqual(after["source"], "published")
        self.assertEqual(after["document"]["x_um"]["range"], [2000.0, 120000.0])
        self.assertTrue(is_snapshot_name(Path(published["snapshot"]).name))
        self.assertEqual(Path(published["snapshot"]).parent.name, "limits")

    def test_limits_wider_than_the_backstop_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with patch.object(leica_setup._machine, "MACHINE", profile):
                document = dict(leica_setup.read(_handle(), "limits")["document"])
                document["x_um"] = {"range": [-5000.0, 9_000_000.0]}
                with self.assertRaises((RuntimeError, ValueError)):
                    leica_setup.publish(_handle(), "limits", document)

    def test_orientation_is_published_in_the_drivers_own_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with patch.object(leica_setup._machine, "MACHINE", profile):
                self.assertEqual(leica_setup.read(_handle(), "orientation")["source"], "default")
                published = leica_setup.publish(
                    _handle(), "orientation", {"rotation_deg": 90, "reflection": False},
                )
                after = leica_setup.read(_handle(), "orientation")
                saved = json.loads(Path(published["path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["rotation_deg"], 90)
        self.assertIs(saved["measured"], True)
        self.assertEqual(saved["sign_convention"], {"stage_x_from_image": "-Y", "stage_y_from_image": "+X"})
        self.assertEqual(after["source"], "published")

    def test_a_contradictory_orientation_document_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with patch.object(leica_setup._machine, "MACHINE", profile):
                with self.assertRaises(ValueError):
                    leica_setup.publish(_handle(), "orientation", {"rotation_deg": 45, "reflection": False})

    def test_the_origin_record_is_the_one_connect_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with (
                patch.object(leica_setup._machine, "MACHINE", profile),
                patch.object(adapter._machine, "MACHINE", profile),
                patch.object(leica_setup.drv, "get_xy", return_value={"x_um": 1000.0, "y_um": 2000.0}),
                patch.object(leica_setup.drv, "read_zwide_um", return_value=30.0),
                patch.object(leica_setup.drv, "get_selected_job", return_value={"Name": "Overview"}),
                patch.object(leica_setup.drv, "get_job_settings", return_value=_settings(30.0, 2.0)),
                patch.object(adapter._readers, "get_job_settings", return_value=_settings(30.0, 2.0)),
                patch.object(adapter, "_z_um_from_settings",
                             side_effect=lambda settings, drive, **_k: settings["zPosition"][drive]["position"]),
            ):
                published = leica_setup.publish(
                    _handle(), "origin", {"x_um": 1000.0, "y_um": 2000.0, "z_um": 30.0},
                )
                saved = json.loads(Path(published["path"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["origin"]["x_um"], 1000.0)
                self.assertEqual(saved["origin"]["z_focus_um"], 32.0)
                self.assertEqual(saved["origin"]["objective"]["slotIndex"], 3)
                self.assertEqual(Path(published["snapshot"]).parent.name, "origin")
                # And the next connect stands on it.
                with patch.object(adapter._session, "connect_python_client", return_value=object()):
                    h = adapter.connect(dict(adapter.CONNECTION))
                self.assertEqual(h.origin["x_um"], 1000.0)
                self.assertEqual(h.origin["z_focus_um"], 32.0)

    def test_calibration_folds_a_measured_pair_into_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            with patch.object(leica_setup._machine, "MACHINE", profile):
                before = leica_setup.read(_handle(), "calibration")
                self.assertEqual(before["source"], "default")
                document = {
                    "schema_version": before["document"]["schema_version"],
                    "objectives": {
                        "1": {"name": "10x", "translation_um": [0.0, 0.0, 0.0]},
                        "3": {"name": "63x", "translation_um": [-18.0, 11.0, 3.5]},
                    },
                }
                published = leica_setup.publish(_handle(), "calibration", document)
                after = leica_setup.read(_handle(), "calibration")
        self.assertEqual(after["source"], "published")
        self.assertEqual(after["document"]["objectives"]["3"]["translation_um"], [-18.0, 11.0, 3.5])
        self.assertTrue(published["path"].endswith("calibration.json"))


class TestTheVocabulary(unittest.TestCase):
    def test_where_reads_every_drive_and_the_objective(self):
        with (
            patch.object(leica_setup.drv, "get_xy", return_value={"x_um": 10.0, "y_um": 20.0}),
            patch.object(leica_setup.drv, "read_zwide_um", return_value=5.0),
            patch.object(leica_setup.drv, "get_selected_job", return_value={"Name": "Overview"}),
            patch.object(leica_setup.drv, "get_job_settings", return_value=_settings(5.0, 2.0)),
            patch.object(adapter, "_z_um_from_settings",
                         side_effect=lambda settings, drive, **_k: settings["zPosition"][drive]["position"]),
        ):
            here = leica_setup.where(_handle())
        self.assertEqual((here["x_um"], here["y_um"], here["z_um"]), (10.0, 20.0, 5.0))
        self.assertEqual(here["actuators"]["z-galvo"], {"value": 2.0, "unit": "um"})
        self.assertEqual(here["actuators"]["z-wide"]["value"], 5.0)
        self.assertEqual(here["objective"]["slot"], 3)

    def test_objective_is_observed_never_commanded(self):
        with (
            patch.object(leica_setup.drv, "get_selected_job", return_value={"Name": "Overview"}),
            patch.object(leica_setup.drv, "get_job_settings", return_value=_settings(slot=3)),
            patch.object(leica_setup._parsing, "parse_tile_geometry",
                         return_value={"pixel_w_um": 0.5, "pixel_h_um": 0.5, "pixels_x": 1024, "pixels_y": 1024}),
        ):
            lens = leica_setup.objective(_handle())
        self.assertEqual(lens["slot"], 3)
        self.assertEqual(lens["pixel_um"], 0.5)
        self.assertNotIn("set_objective", dir(leica_setup))

    def test_a_closed_setup_refuses(self):
        h = _handle()
        leica_setup.close_setup(h)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            leica_setup.where(h)


if __name__ == "__main__":
    unittest.main()


class TestSetterLimitKinds(unittest.TestCase):
    """A setter is fenced as a range -- open at either end -- or as allowed values."""

    def test_a_range_may_leave_one_end_open(self):
        from navigator_expert.limits import config as limits_config

        document = json.loads(Path(limits_config.defaults_path()).read_text(encoding="utf-8"))
        document["set_laser_intensity"] = {"range": [None, 10]}
        normalized = limits_config.validate_payload(document)
        self.assertEqual(normalized["set_laser_intensity"], {"range": [None, 10.0]})
        with self.assertRaisesRegex(ValueError, "both ends open"):
            limits_config.validate_payload({**document, "set_laser_intensity": {"range": [None, None]}})
        # A stage axis stays strict: both ends, always.
        with self.assertRaises(ValueError):
            limits_config.validate_payload({**document, "x_um": {"range": [None, 1000]}})

    def test_an_open_end_is_no_bound_on_that_side(self):
        from navigator_expert.limits import checks

        policy = checks.LeicaLimits(
            {"set_laser_intensity": {"range": [None, 10]}, "set_zoom": {"allowed": [1, 2]}},
            source="test", path="test", is_fallback=False,
        )
        policy.check("set_laser_intensity", {"value": -50})
        with self.assertRaisesRegex(checks.LimitViolation, "outside range"):
            policy.check("set_laser_intensity", {"value": 11})
        policy.check("set_zoom", {"value": 2})
        with self.assertRaisesRegex(checks.LimitViolation, "not allowed"):
            policy.check("set_zoom", {"value": 3})
