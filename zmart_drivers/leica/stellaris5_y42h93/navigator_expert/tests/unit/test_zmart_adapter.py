"""Offline tests for the ZMART Controller adapter.

The driver layers underneath (readers, commands, capture, save, motion)
are patched; what is under test is the adapter's contract with
``zmart_controller``: registration, frame math, actuator mapping,
option validation, and closed-handle semantics — including a full
end-to-end pass through a real controller ``Session``.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # machine dir
sys.path.insert(0, str(Path(__file__).resolve().parents[6]))  # repo root (zmart_controller)

from navigator_expert.zmart_adapter import zmart_adapter as adapter


def _origin(x_um=0.0, y_um=0.0, z_wide_um=0.0, z_galvo_um=0.0, z_focus_um=0.0, objective=None):
    return {
        "x_um": x_um,
        "y_um": y_um,
        "z_wide_um": z_wide_um,
        "z_galvo_um": z_galvo_um,
        "z_focus_um": z_focus_um,
        "objective": objective,
    }


def _function_limits(**constraint_overrides):
    """A permissive function-limits object (every mutating op reviewed-unlimited).

    Pass constraint overrides shaped like the bundled file's ``stage.*`` names
    to bound ``set_xyz``, e.g. ``x_um={"min": 0, "max": 100}``.
    """
    payload = {
        "schema_version": 1,
        "source": "test",
        "constraints": {},
        "functions": {op: None for op in adapter._MUTATING_OPS},
    }
    if constraint_overrides:
        payload["functions"]["set_xyz"] = {}
        for param, bounds in constraint_overrides.items():
            payload["functions"]["set_xyz"][param] = dict(bounds)
    return adapter._shared_limits.parse(payload, functions=adapter._MUTATING_OPS)


def _handle(**overrides):
    h = adapter.ZmartHandle(client=object(), connection=dict(adapter.CONNECTION), hash6="000abc")
    h.function_limits = _function_limits()
    for key, value in overrides.items():
        setattr(h, key, value)
    return h


def _settings(z_wide_um=50.0, z_galvo_um=0.0, objective="HC PL APO 63x/1.40 OIL CS2", slot=3):
    return {
        "objective": {"name": objective, "magnification": 63, "slotIndex": slot},
        "zPosition": {
            "z-wide": {"position": z_wide_um},
            "z-galvo": {"position": z_galvo_um},
        },
    }


def _patch_position(x_um=100.0, y_um=200.0, z_wide_um=50.0, z_galvo_um=0.0, job="Overview", slot=3):
    return (
        patch.object(adapter._readers, "get_xy", return_value={"x_um": x_um, "y_um": y_um}),
        patch.object(
            adapter._readers,
            "get_job_settings",
            return_value=_settings(z_wide_um=z_wide_um, z_galvo_um=z_galvo_um, slot=slot),
        ),
        patch.object(
            adapter._readers,
            "get_selected_job",
            return_value={"Name": job, "IsSelected": True},
        ),
        patch.object(
            adapter._cmd_settings,
            "make_changeable_copy",
            side_effect=lambda settings: settings,
        ),
    )


def _wide_limits():
    """Configure a permissive stage envelope for tests that exercise set_xyz."""
    adapter._limits.set_stage_limits(
        x_min=0.0,
        x_max=1_000_000.0,
        y_min=0.0,
        y_max=1_000_000.0,
        z_galvo_min=-200.0,
        z_galvo_max=200.0,
        z_wide_min=-100_000.0,
        z_wide_max=100_000.0,
    )


def _clear_limits():
    adapter._limits._stage_limits.update(dict.fromkeys(adapter._limits._stage_limits, None))


class TestRegistration(unittest.TestCase):
    def test_importing_the_adapter_registers_the_instrument(self):
        from zmart_controller import registry

        entry = registry.REGISTRY.get(("leica", "stellaris5-y42h93", "navigator-expert"))
        self.assertIsNotNone(entry, "adapter import must register the instrument")
        for op in registry.OPS:
            self.assertIn(op, entry["ops"])
        self.assertIn("disconnect", entry["ops"])


class TestFrame(unittest.TestCase):
    def setUp(self):
        _wide_limits()  # set_xyz pre-flights against the stage envelope

    def tearDown(self):
        _clear_limits()

    def test_set_origin_zeros_the_frame(self):
        h = _handle()
        patches = _patch_position(x_um=1000.0, y_um=2000.0, z_wide_um=30.0)
        with patches[0], patches[1], patches[2], patches[3]:
            record = adapter.set_origin(h)
            self.assertEqual(record["origin"], {"x": 0.0, "y": 0.0, "z": 0.0})
            self.assertIsNone(record["origin_file"])  # no machine snapshot (hermetic root)
            self.assertEqual(record["reference"]["z_focus_um"], 30.0)
            pos = adapter.get_xyz(h)
        self.assertEqual(pos["x"]["value"], 0.0)
        self.assertEqual(pos["z"]["value"], 0.0)
        self.assertEqual(pos["x"]["unit"], "um")
        self.assertEqual(pos["x"]["actuator"], "motoric")
        self.assertEqual(pos["z"]["actuator"], "z-wide")

    def test_set_origin_persists_into_newest_machine_snapshot(self):
        import json
        import tempfile

        from navigator_expert.config.machine import MachineProfile

        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            snapshot = profile.snapshot_root() / "2026-07-01T14-30-00-123456Z"
            snapshot.mkdir(parents=True)
            h = _handle()
            patches = _patch_position(x_um=1000.0, y_um=2000.0, z_wide_um=30.0, z_galvo_um=2.0)
            with (
                patch.object(adapter._machine, "MACHINE", profile),
                patches[0],
                patches[1],
                patches[2],
                patches[3],
            ):
                record = adapter.set_origin(h)
            self.assertEqual(record["origin_file"], str(snapshot / "origin.json"))
            saved = json.loads((snapshot / "origin.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["origin"]["x_um"], 1000.0)
            self.assertEqual(saved["origin"]["z_wide_um"], 30.0)
            self.assertEqual(saved["origin"]["z_galvo_um"], 2.0)
            self.assertEqual(saved["origin"]["z_focus_um"], 32.0)
            self.assertEqual(saved["origin"]["objective"]["magnification"], 63)
            self.assertEqual(saved["job"], "Overview")

    def test_connect_restores_persisted_origin(self):
        """The machine-local origin is the frame truth across sessions."""
        import tempfile

        from navigator_expert.config.machine import MachineProfile

        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            snapshot = profile.snapshot_root() / "2026-07-01T14-30-00-123456Z"
            snapshot.mkdir(parents=True)
            profile.write_origin(
                {
                    "origin": _origin(x_um=1000.0, y_um=2000.0, z_wide_um=30.0, z_focus_um=30.0),
                    "captured_at": 123.0,
                }
            )
            with (
                patch.object(adapter._machine, "MACHINE", profile),
                patch.object(adapter._session, "connect_python_client", return_value=object()),
                patch.object(adapter._limits, "apply_stage_limits_from_config"),
                patch.object(adapter._stage_config, "load", return_value={}),
            ):
                h = adapter.connect(dict(adapter.CONNECTION))
            self.assertEqual(h.origin["x_um"], 1000.0)
            self.assertEqual(h.origin["z_focus_um"], 30.0)

            # A malformed persisted origin must not poison the frame.
            profile.write_origin({"origin": {"x_um": 1.0}})  # missing keys
            with (
                patch.object(adapter._machine, "MACHINE", profile),
                patch.object(adapter._session, "connect_python_client", return_value=object()),
                patch.object(adapter._limits, "apply_stage_limits_from_config"),
                patch.object(adapter._stage_config, "load", return_value={}),
            ):
                h2 = adapter.connect(dict(adapter.CONNECTION))
            self.assertEqual(h2.origin["x_um"], 0.0)  # frame stays absolute

    def test_get_xyz_is_origin_relative(self):
        h = _handle(origin=_origin(x_um=1000.0, y_um=2000.0, z_focus_um=30.0))
        patches = _patch_position(x_um=1010.0, y_um=1990.0, z_wide_um=32.0, z_galvo_um=3.0)
        with patches[0], patches[1], patches[2], patches[3]:
            pos = adapter.get_xyz(h)
        self.assertEqual(pos["x"]["value"], 10.0)
        self.assertEqual(pos["y"]["value"], -10.0)
        self.assertEqual(pos["z"]["value"], 5.0)  # (32 + 3) - 30 focus sum
        self.assertEqual(pos["hardware"]["z_wide_um"], 32.0)
        self.assertEqual(pos["hardware"]["z_galvo_um"], 3.0)
        self.assertEqual(pos["hardware"]["x_um"], 1010.0)
        self.assertIn("objective", pos["hardware"])

    def test_set_xyz_moves_to_absolute_and_maps_z_actuator(self):
        h = _handle(origin=_origin(x_um=1000.0, y_um=2000.0, z_focus_um=30.0))
        moves = {}

        def fake_move_xy_with_backlash(client, x_um, y_um, **kwargs):
            moves["xy"] = (x_um, y_um)
            return {"success": True, "confirmed": True}

        def fake_move_z(client, job, z, unit="um", z_mode="galvo", **kwargs):
            moves["z"] = (z, z_mode)
            return {"success": True, "confirmed": True}

        # current hardware: z-wide at 32, z-galvo at 3
        patches = _patch_position(z_wide_um=32.0, z_galvo_um=3.0)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash", fake_move_xy_with_backlash),
            patch.object(adapter._commands, "move_z", fake_move_z),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            record = adapter.set_xyz(h, 10.0, 20.0, 5.0, with_actuators={"z": "z-galvo"})
        self.assertEqual(moves["xy"], (1010.0, 2020.0))
        # target focus = 30 + 5 = 35; galvo absorbs it minus z-wide's 32 -> 3
        self.assertEqual(moves["z"], (3.0, "galvo"))
        self.assertEqual(record["actuators"]["z"], "z-galvo")
        self.assertEqual(record["hardware_targets"]["z_galvo_um"], 3.0)
        # the selection does NOT persist: defaults are fixed, never sticky
        self.assertEqual(adapter._resolve_actuators(None)["z"], "z-wide")
        self.assertEqual(adapter._resolve_actuators(None)["x"], "motoric")

    def test_set_xyz_z_wide_compensates_parked_galvo(self):
        h = _handle(origin=_origin(z_focus_um=30.0))
        moves = {}

        def fake_move_z(client, job, z, unit="um", z_mode="galvo", **kwargs):
            moves["z"] = (z, z_mode)
            return {"success": True, "confirmed": True}

        patches = _patch_position(z_wide_um=25.0, z_galvo_um=4.0)
        with (
            patch.object(
                adapter._motion,
                "move_xy_with_backlash",
                return_value={"success": True, "confirmed": True},
            ),
            patch.object(adapter._commands, "move_z", fake_move_z),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            adapter.set_xyz(h, 0.0, 0.0, 10.0)  # default z actuator: z-wide
        # target focus = 30 + 10 = 40; the parked galvo offset (4) is kept
        self.assertEqual(moves["z"], (36.0, "zwide"))

    def test_unconfirmed_z_move_raises(self):
        h = _handle()
        patches = _patch_position()
        with (
            patch.object(
                adapter._motion,
                "move_xy_with_backlash",
                return_value={"success": True, "confirmed": True},
            ),
            patch.object(
                adapter._commands,
                "move_z",
                return_value={"success": True, "confirmed": False},
            ),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            self.assertRaises(RuntimeError),
        ):
            adapter.set_xyz(h, 0.0, 0.0, 0.0)

    def test_unknown_actuator_rejected(self):
        h = _handle()
        with self.assertRaises(ValueError):
            adapter.get_actuators(h) and adapter.set_xyz(
                h, 0, 0, 0, with_actuators={"z": "hovercraft"}
            )

    def test_actuator_menu(self):
        h = _handle()
        self.assertEqual(
            adapter.get_actuators(h),
            {"x": ["motoric"], "y": ["motoric"], "z": ["z-wide", "z-galvo"]},
        )


class TestAcquire(unittest.TestCase):
    def _jobs(self):
        return [
            {"Name": "Overview", "IsSelected": True, "IsAutofocus": False},
            {"Name": "HiRes", "IsSelected": False, "IsAutofocus": False},
            {"Name": "AF Job", "IsSelected": False, "IsAutofocus": True},
        ]

    def test_options_discovered_from_live_jobs(self):
        h = _handle()
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._save, "active_save_exporter", return_value="navigator_expert"),
        ):
            opts = adapter.get_acquisition_options(h)
        # autofocus jobs are a separate category, never acquisition options
        self.assertEqual(opts["job"]["options"], ["Overview", "HiRes"])
        self.assertEqual(opts["job"]["active"], "Overview")
        self.assertEqual(opts["format"]["active"], "ome-tiff")
        self.assertEqual(opts["exporter"]["active"], "navigator_expert")
        self.assertEqual(opts["cleanup_source"]["active"], False)

    def test_unknown_or_invalid_option_rejected(self):
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._save, "active_save_exporter", return_value="navigator_expert"),
        ):
            with self.assertRaisesRegex(ValueError, "unknown acquisition option"):
                adapter.acquire(
                    h, acquisition_type="prescan", position_label="A1", options={"fromat": "x"}
                )
            with self.assertRaisesRegex(ValueError, "invalid value"):
                adapter.acquire(
                    h, acquisition_type="prescan", position_label="A1", options={"job": "Nope"}
                )

    def test_missing_output_root_is_a_clear_error(self):
        h = _handle()
        with self.assertRaisesRegex(RuntimeError, "output_root"):
            adapter.acquire(h, acquisition_type="prescan", position_label="A1")

    def test_acquire_selects_job_captures_and_saves(self):
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        calls = {}

        def fake_select_job(client, job, **kwargs):
            calls["selected"] = job
            return {"success": True}

        def fake_capture(client, job, **kwargs):
            calls["captured"] = job
            return SimpleNamespace(job=job)

        def fake_save(client, acq, output_root, naming, **kwargs):
            calls["saved"] = (str(output_root), naming)
            calls["lineage"] = kwargs.get("lineage")
            calls["exporter"] = kwargs.get("exporter")
            return SimpleNamespace(
                image_paths={0: Path("/tmp/out/img.ome.tif")},
                xml_paths={0: Path("/tmp/out/img.xml")},
                naming=naming,
            )

        patches = _patch_position(job="Overview")
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._commands, "select_job", fake_select_job),
            patch.object(adapter._motion, "correct_backlash", lambda client, **k: None),
            patch.object(adapter._capture, "acquire", fake_capture),
            patch.object(adapter._save, "save", fake_save),
            patch.object(adapter._save, "active_save_exporter", return_value="navigator_expert"),
            patches[2],
        ):
            record = adapter.acquire(
                h,
                acquisition_type="prescan",
                position_label="7",
                options={"job": "HiRes", "backlash_correction": False},
            )
        self.assertEqual(calls["selected"], "HiRes")
        self.assertEqual(calls["captured"], "HiRes")
        saved_root, naming = calls["saved"]
        self.assertEqual(Path(saved_root), Path("/tmp/out"))  # OS-agnostic separators
        self.assertEqual(naming.acquisition_type, "prescan")
        self.assertEqual(naming.p, 7)  # numeric label maps onto the p slot
        self.assertEqual(calls["lineage"]["position_label"], "7")
        self.assertEqual(calls["lineage"]["acquisition_type"], "prescan")
        self.assertEqual(calls["exporter"], "navigator_expert")
        self.assertEqual(record["settle"], "direct")
        self.assertEqual([Path(p) for p in record["images"]], [Path("/tmp/out/img.ome.tif")])


class TestStateAndProcedures(unittest.TestCase):
    _HW = {
        "SerialNumber": "STELLARIS-1234",
        "SystemType": "CONFOCAL",
        "Microscope": {
            "name": "DM Manual-6",
            "objectives": [
                {"slotIndex": 0, "objectiveNumber": 506511},
                {"slotIndex": 1, "objectiveNumber": 506513},
            ],
        },
    }

    def _state_patches(self, jobs=("Overview", "HiRes"), af_jobs=("AF Job",)):
        catalog = [
            {"Name": n, "IsSelected": n == "Overview", "IsAutofocus": False} for n in jobs
        ] + [{"Name": n, "IsSelected": False, "IsAutofocus": True} for n in af_jobs]
        return (
            patch.object(adapter._readers, "get_hardware_info", return_value=dict(self._HW)),
            patch.object(
                adapter._readers,
                "get_selected_job",
                return_value={"Name": "Overview", "IsSelected": True},
            ),
            patch.object(adapter._readers, "get_jobs", return_value=catalog),
        )

    def test_state_shape_changeable_first_then_observed(self):
        h = _handle()
        p = self._state_patches()
        with p[0], p[1], p[2]:
            state = adapter.get_state(h)
        self.assertEqual(list(state), ["changeable", "observed"])  # changeable first
        self.assertEqual(state["changeable"], {"job": "Overview"})
        observed = state["observed"]
        self.assertEqual(observed["vendor"], "leica")
        self.assertEqual(observed["microscope"], "stellaris5-y42h93")
        self.assertEqual(observed["serial_number"], "STELLARIS-1234")
        self.assertEqual(observed["system_type"], "CONFOCAL")
        self.assertEqual(observed["stand"], "DM Manual-6")
        self.assertEqual(observed["objectives"], [[0, 506511], [1, 506513]])
        # the rich readings ride along: the full selected-job record + catalog,
        # with autofocus jobs as their own category
        self.assertEqual(observed["job"]["Name"], "Overview")
        self.assertEqual([j["Name"] for j in observed["jobs"]], ["Overview", "HiRes"])
        self.assertEqual([j["Name"] for j in observed["autofocus_jobs"]], ["AF Job"])

    def test_set_state_refuses_an_autofocus_job(self):
        h = _handle()
        p = self._state_patches()
        with p[0], p[1], p[2], patch.object(adapter._commands, "select_job") as select:
            with self.assertRaisesRegex(ValueError, "autofocus"):
                adapter.set_state(h, {"changeable": {"job": "AF Job"}})
        select.assert_not_called()

    def test_set_state_applies_changeable_ignoring_observed(self):
        h = _handle()
        p = self._state_patches()
        with (
            p[0],
            p[1],
            p[2],
            patch.object(adapter._commands, "select_job", return_value={"success": True}) as select,
        ):
            captured = adapter.get_state(h)
            captured["changeable"]["job"] = "HiRes"
            # observed is a report, never an instruction: even a wildly
            # mismatching observed part does not block the apply.
            captured["observed"]["serial_number"] = "SOMETHING-ELSE"
            result = adapter.set_state(h, captured)
            self.assertEqual(result["applied"], {"job": "HiRes"})
            select.assert_called_once()

    def test_set_state_refuses_a_job_that_no_longer_exists(self):
        h = _handle()
        p = self._state_patches(jobs=("Overview",))
        with p[0], p[1], p[2], patch.object(adapter._commands, "select_job") as select:
            with self.assertRaisesRegex(ValueError, "no longer exists"):
                adapter.set_state(h, {"changeable": {"job": "Gone"}})
        select.assert_not_called()

    def test_procedures(self):
        h = _handle()
        p = self._state_patches()
        with p[2]:
            procedures = adapter.get_procedures(h)
        self.assertIn("backlash_takeup", procedures)
        self.assertEqual(procedures["autofocus"]["jobs"], ["AF Job"])
        with patch.object(adapter._motion, "correct_backlash", lambda client, **k: None):
            self.assertEqual(
                adapter.set_procedure(h, {"name": "backlash_takeup"})["ran"]["name"],
                "backlash_takeup",
            )
        with self.assertRaises(ValueError):
            adapter.set_procedure(h, {"name": "nope"})

    def test_autofocus_runs_capture_only_and_restores_the_selection(self):
        from types import SimpleNamespace

        h = _handle()
        calls = []
        p = self._state_patches()
        position = _patch_position(z_wide_um=42.0, z_galvo_um=1.5)
        with (
            p[2],  # job catalog (AF Job flagged)
            position[0],
            position[1],
            position[2],
            position[3],
            patch.object(
                adapter._commands,
                "select_job",
                side_effect=lambda client, job, **k: (
                    calls.append(("select", job)) or {"success": True}
                ),
            ),
            patch.object(
                adapter._capture,
                "acquire",
                side_effect=lambda client, job, **k: (
                    calls.append(("acquire", job))
                    or SimpleNamespace(job=job, started_at=1.0, finished_at=3.5)
                ),
            ),
        ):
            result = adapter.set_procedure(h, {"name": "autofocus"})  # single AF job: no arg
        # select AF -> capture -> restore the original selection, in order
        self.assertEqual(
            calls, [("select", "AF Job"), ("acquire", "AF Job"), ("select", "Overview")]
        )
        self.assertEqual(result["ran"], "autofocus")
        self.assertEqual(result["job"], "AF Job")
        self.assertEqual(result["focus_um"], 43.5)  # 42.0 + 1.5, read before restore
        self.assertEqual(result["frame_z_um"], 43.5)  # all-zero origin
        self.assertEqual(result["duration_s"], 2.5)

    def test_autofocus_rejects_a_normal_job(self):
        h = _handle()
        p = self._state_patches()
        with p[2]:
            with self.assertRaisesRegex(ValueError, "not an autofocus job"):
                adapter.set_procedure(h, {"name": "autofocus", "job": "Overview"})

    def test_autofocus_requires_a_choice_when_several_exist(self):
        h = _handle()
        p = self._state_patches(af_jobs=("AF Job", "AF Fine"))
        with p[2]:
            with self.assertRaisesRegex(ValueError, "multiple autofocus jobs"):
                adapter.set_procedure(h, {"name": "autofocus"})

    def test_autofocus_without_af_jobs_is_a_clear_error(self):
        h = _handle()
        p = self._state_patches(af_jobs=())
        with p[2]:
            with self.assertRaisesRegex(RuntimeError, "no autofocus job"):
                adapter.set_procedure(h, {"name": "autofocus"})


class TestObjectiveCompensation(unittest.TestCase):
    """Cross-objective frame math: ΔT = T[current] − T[origin's objective].

    Uses the EXISTING calibration translation totals (no schema change,
    operator decision 2026-07-02); the driver assumes x/y apply to the motoric
    stage and z applies in focus space.
    """

    def setUp(self):
        _wide_limits()

    def tearDown(self):
        _clear_limits()

    def _cross_handle(self):
        return _handle(
            origin=_origin(
                x_um=1000.0,
                y_um=2000.0,
                z_focus_um=30.0,
                objective={"name": "10x", "slotIndex": 1},
            ),
            translations={1: (0.0, 0.0, 0.0), 2: (100.0, 50.0, 10.0)},
        )

    def test_cross_objective_read_applies_translation(self):
        h = self._cross_handle()
        patches = _patch_position(x_um=1110.0, y_um=2060.0, z_wide_um=45.0, z_galvo_um=0.0, slot=2)
        with patches[0], patches[1], patches[2], patches[3]:
            pos = adapter.get_xyz(h)
        self.assertEqual(pos["x"]["value"], 10.0)  # 1110 − 1000 − 100
        self.assertEqual(pos["y"]["value"], 10.0)  # 2060 − 2000 − 50
        self.assertEqual(pos["z"]["value"], 5.0)  # 45 − 30 − 10

    def test_cross_objective_move_targets_include_translation(self):
        h = self._cross_handle()
        moves = {}

        def fake_xy(client, x_um, y_um, **kwargs):
            moves["xy"] = (x_um, y_um)
            return {"success": True, "confirmed": True}

        def fake_z(client, job, z, unit="um", z_mode="galvo", **kwargs):
            moves["z"] = (z, z_mode)
            return {"success": True, "confirmed": True}

        patches = _patch_position(z_wide_um=40.0, z_galvo_um=0.0, slot=2)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash", fake_xy),
            patch.object(adapter._commands, "move_z", fake_z),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            record = adapter.set_xyz(h, 10.0, 10.0, 5.0, with_actuators={"z": "z-galvo"})
        self.assertEqual(moves["xy"], (1110.0, 2060.0))  # ref + F + ΔT
        # focus target = 30 + 5 + 10 = 45; galvo = 45 − z_wide(40) = 5
        self.assertEqual(moves["z"], (5.0, "galvo"))
        self.assertEqual(record["objective_translation_um"], [100.0, 50.0, 10.0])

    def test_round_trip_property_across_objectives(self):
        """get_xyz(set_xyz(F)) == F — commanded hardware read back through the frame."""
        h = self._cross_handle()
        state = {"x": 0.0, "y": 0.0, "z_wide": 40.0, "z_galvo": 0.0}

        def fake_xy(client, x_um, y_um, **kwargs):
            state["x"], state["y"] = x_um, y_um
            return {"success": True, "confirmed": True}

        def fake_z(client, job, z, unit="um", z_mode="galvo", **kwargs):
            state["z_galvo" if z_mode == "galvo" else "z_wide"] = z
            return {"success": True, "confirmed": True}

        with (
            patch.object(adapter._motion, "move_xy_with_backlash", fake_xy),
            patch.object(adapter._commands, "move_z", fake_z),
            patch.object(
                adapter._readers,
                "get_xy",
                side_effect=lambda client, **kw: {"x_um": state["x"], "y_um": state["y"]},
            ),
            patch.object(
                adapter._readers,
                "get_job_settings",
                side_effect=lambda client, job, **kw: _settings(
                    z_wide_um=state["z_wide"], z_galvo_um=state["z_galvo"], slot=2
                ),
            ),
            patch.object(
                adapter._readers,
                "get_selected_job",
                return_value={"Name": "Overview", "IsSelected": True},
            ),
            patch.object(adapter._cmd_settings, "make_changeable_copy", side_effect=lambda s: s),
        ):
            adapter.set_xyz(h, 12.0, -7.0, 4.0, with_actuators={"z": "z-galvo"})
            pos = adapter.get_xyz(h)
        self.assertAlmostEqual(pos["x"]["value"], 12.0)
        self.assertAlmostEqual(pos["y"]["value"], -7.0)
        self.assertAlmostEqual(pos["z"]["value"], 4.0)

    def test_cross_objective_move_without_translations_refuses(self):
        h = _handle(origin=_origin(objective={"name": "10x", "slotIndex": 1}))
        patches = _patch_position(slot=2)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash") as xy,
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            with self.assertRaisesRegex(RuntimeError, "translation"):
                adapter.set_xyz(h, 1.0, 1.0, 0.0)
        xy.assert_not_called()  # refused before any motion

    def test_cross_objective_read_without_translations_warns_uncompensated(self):
        h = _handle(origin=_origin(x_um=1000.0, objective={"name": "10x", "slotIndex": 1}))
        patches = _patch_position(x_um=1110.0, slot=2)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            self.assertLogs(adapter.log, level="WARNING"),
        ):
            pos = adapter.get_xyz(h)
        self.assertEqual(pos["x"]["value"], 110.0)  # uncompensated, but loud

    def test_same_objective_needs_no_calibration(self):
        h = _handle(origin=_origin(x_um=1000.0, objective={"name": "63x", "slotIndex": 3}))
        patches = _patch_position(x_um=1010.0, slot=3)
        with patches[0], patches[1], patches[2], patches[3]:
            pos = adapter.get_xyz(h)
        self.assertEqual(pos["x"]["value"], 10.0)  # ΔT = 0, translations unused

    def test_preflight_refuses_out_of_range_galvo_before_any_motion(self):
        h = _handle(origin=_origin(objective={"name": "63x", "slotIndex": 3}))
        patches = _patch_position(z_wide_um=0.0, z_galvo_um=0.0, slot=3)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash") as xy,
            patch.object(adapter._commands, "move_z") as mz,
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            with self.assertRaisesRegex(RuntimeError, "z-wide"):
                adapter.set_xyz(h, 10.0, 10.0, 300.0, with_actuators={"z": "z-galvo"})
        xy.assert_not_called()
        mz.assert_not_called()


class TestLifecycle(unittest.TestCase):
    def test_ops_after_disconnect_raise(self):
        h = _handle()
        adapter.disconnect(h)
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            adapter.get_actuators(h)

    def test_connect_configures_stage_limits(self):
        """connect must apply the machine's stage envelope, or set_xyz can't move.

        move_xy/move_z refuse to run until set_stage_limits() has been called,
        and the controller has no limits hook -- so the adapter must do it.
        """
        cfg = {
            "stage_um": {
                "x": [1000.0, 130000.0],
                "y": [1000.0, 100000.0],
                "z_galvo": [-200.0, 200.0],
                "z_wide": [0.0, 25000.0],
            },
            "backlash": {"overshoot_um": 50.0, "settle_ms": 100, "tolerance_um": 20.0},
        }
        with (
            patch.object(adapter._session, "connect_python_client", return_value=object()),
            patch.object(adapter._stage_config, "load", return_value=cfg),
            patch.object(adapter._limits, "apply_stage_limits_from_config") as apply_mock,
        ):
            h = adapter.connect(dict(adapter.CONNECTION))
        self.assertIsInstance(h, adapter.ZmartHandle)
        apply_mock.assert_called_once_with(cfg)

    def test_connect_degrades_when_limits_config_unavailable(self):
        """A missing/invalid limits config must not fail connect (read-only still works)."""
        with (
            patch.object(adapter._session, "connect_python_client", return_value=object()),
            patch.object(adapter._stage_config, "load", side_effect=RuntimeError("no config")),
        ):
            h = adapter.connect(dict(adapter.CONNECTION))
        self.assertIsInstance(h, adapter.ZmartHandle)
        self.assertFalse(h.closed)

    def test_full_controller_session_flow(self):
        """End to end through a real zmart_controller Session."""
        import zmart_controller

        _wide_limits()
        self.addCleanup(_clear_limits)
        patches = _patch_position(x_um=1000.0, y_um=2000.0, z_wide_um=30.0)
        with (
            patch.object(adapter._session, "connect_python_client", return_value=object()),
            patch.object(adapter._limits, "apply_stage_limits_from_config"),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(
                adapter._motion,
                "move_xy_with_backlash",
                return_value={"success": True, "confirmed": True},
            ),
            patch.object(
                adapter._commands,
                "move_z",
                return_value={"success": True, "confirmed": True},
            ),
        ):
            instrument = next(
                i for i in zmart_controller.get_instruments() if i["vendor"] == "leica"
            )
            session = zmart_controller.set_instrument(instrument)
            try:
                session.set_origin()
                record = session.set_xyz(10, 20, 5, with_actuators={"z": "z-galvo"})
                self.assertEqual(record["position"], {"x": 10, "y": 20, "z": 5})
                self.assertEqual(session.get_xyz()["x"]["value"], 0.0)  # mocked readback
            finally:
                session.disconnect()


class TestFunctionLimits(unittest.TestCase):
    """The function-keyed limits gate (``shared.limits``) wired through the adapter."""

    def test_bundled_file_covers_every_mutating_op(self):
        """THE completeness guard: adding a mutating op without a limits entry fails here."""
        path = adapter._machine.MACHINE.bundled_default_path(
            adapter._machine.FUNCTION_LIMITS_FILENAME
        )
        limits = adapter._shared_limits.load(path, functions=adapter._MUTATING_OPS)
        self.assertEqual(limits.source, "defaults")

    def test_set_xyz_refuses_beyond_function_limits_before_any_motion(self):
        _wide_limits()  # Phase A permissive, so the function-limits layer is what fires
        self.addCleanup(_clear_limits)
        h = _handle(function_limits=_function_limits(x_um={"min": 0, "max": 500}))
        patches = _patch_position(x_um=0.0, y_um=0.0)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash") as xy,
            patch.object(adapter._commands, "move_z") as mz,
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            with self.assertRaisesRegex(RuntimeError, r"set_xyz\.x_um"):
                adapter.set_xyz(h, 1000.0, 10.0, 0.0)
        xy.assert_not_called()
        mz.assert_not_called()

    def test_z_leg_function_limit_violation_keeps_the_actuator_hint(self):
        _wide_limits()
        self.addCleanup(_clear_limits)
        h = _handle(function_limits=_function_limits(z_galvo_um={"min": -200, "max": 200}))
        patches = _patch_position(z_wide_um=0.0, z_galvo_um=0.0)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash") as xy,
            patch.object(adapter._commands, "move_z") as mz,
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            with self.assertRaisesRegex(RuntimeError, r"with_actuators=\{'z': 'z-wide'\}"):
                adapter.set_xyz(h, 10.0, 10.0, 300.0, with_actuators={"z": "z-galvo"})
        xy.assert_not_called()
        mz.assert_not_called()

    def test_mutating_ops_refuse_without_function_limits(self):
        """Fail-closed: no loaded limits means no mutations — reads still work."""
        h = _handle(function_limits=None)
        for call in (
            lambda: adapter.set_origin(h),
            lambda: adapter.set_state(h, {"changeable": {}}),
            lambda: adapter.set_procedure(h, {"name": "backlash_takeup"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "function limits are not configured"):
                call()
        self.assertIn("backlash_takeup", adapter.get_procedures(h))  # read-only unaffected

    def test_get_state_reports_limits_provenance(self):
        h = _handle()
        with (
            patch.object(
                adapter._readers,
                "get_hardware_info",
                return_value={"SerialNumber": "S", "SystemType": "T", "Microscope": {}},
            ),
            patch.object(
                adapter._readers,
                "get_selected_job",
                return_value={"Name": "Overview", "IsSelected": True},
            ),
            patch.object(adapter._readers, "get_jobs", return_value=[]),
        ):
            observed = adapter.get_state(h)["observed"]
        self.assertEqual(
            observed["limits"],
            {"schema_version": 1, "source": "test", "path": None, "is_fallback": False},
        )

    def test_machine_stage_envelope_overrides_bundled_constraints(self):
        """The snapshot's envelope governs set_xyz, never a stale bundled copy."""
        cfg = {
            "stage_um": {
                "x": [2000.0, 50000.0],
                "y": [1000.0, 100000.0],
                "z_galvo": [-200.0, 200.0],
                "z_wide": [0.0, 25000.0],
            }
        }
        limits = adapter._load_function_limits(cfg)
        self.assertIsNotNone(limits)
        limits.check("set_xyz", {"x_um": 2500.0})
        with self.assertRaises(adapter._shared_limits.LimitViolation):
            limits.check(
                "set_xyz", {"x_um": 1500.0}
            )  # inside the bundled envelope, outside the machine's

    def test_unknown_machine_axis_fails_closed(self):
        """An envelope the file can't represent must refuse mutations, not skip the axis."""
        self.assertIsNone(adapter._load_function_limits({"stage_um": {"theta": [0.0, 360.0]}}))


if __name__ == "__main__":
    unittest.main()
