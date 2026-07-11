"""Offline tests for the ZMART Controller adapter.

The driver layers underneath (readers, commands, capture, save, motion)
are patched; what is under test is the adapter's contract with
``zmart_controller``: registration, frame math, actuator mapping,
option validation, and closed-handle semantics — including a full
end-to-end pass through a real controller ``Session``.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from limits_fixtures import (
    DEFAULT_STAGE_UM,
    install_permissive_limits,
    provision_machine_limits,
)
from navigator_expert.commands import gate as _gate
from navigator_expert.commands import settings as _cmd_settings
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


def _handle(gate_constraints=None, gated=True, **overrides):
    """A handle whose client carries a permissive commands-layer gate state.

    ``gate_constraints`` bounds the ``set_xyz`` key (e.g.
    ``{"x_um": {"min": 0, "max": 100}}``); ``gated=False`` leaves the client
    without any gate state (the fail-closed posture of a failed handshake).
    """
    h = adapter.ZmartHandle(client=object(), connection=dict(adapter.CONNECTION), hash6="000abc")
    if gated:
        install_permissive_limits(h.client, **(gate_constraints or {}))
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
            _cmd_settings,
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


class TestCalibrationSelection(unittest.TestCase):
    def test_named_connection_calibration_is_used_for_objective_translations(self):
        # The driver now owns loading: the named calibration flows through
        # connect_microscope -> session._load_objective_calibration, where one
        # exact document supplies both translations and readiness provenance.
        from navigator_expert.calibration.core import model as cal_model
        from navigator_expert.connection import session as drv_session

        cfg = {
            "schema_version": 12,
            "last_updated": "20260101_000000",
            "objectives": {
                "1": {
                    "name": "10x",
                    "translation_um": [0.0, 0.0, 0.0],
                    "session_id": "ref",
                },
                "2": {
                    "name": "20x",
                    "translation_um": [12.0, 17.0, 3.0],
                    "session_id": "target",
                },
            },
        }

        path = Path("/tmp/lens_A/calibration.json")
        with (
            patch.object(cal_model, "default_path", return_value=path),
            patch.object(cal_model, "load_calibration", return_value=cfg) as load,
        ):
            translations, info = drv_session._load_objective_calibration("lens_A")

        load.assert_called_once_with(path.absolute())
        self.assertEqual(translations[2], (12.0, 17.0, 3.0))
        self.assertEqual(info["measured_slots"], [1, 2])

    def test_translations_and_provenance_come_from_one_calibration_read(self):
        """A snapshot adoption during connect cannot mix old math with new proof."""
        from navigator_expert.calibration.core import model as cal_model
        from navigator_expert.connection import session as drv_session

        old = {
            "schema_version": 12,
            "last_updated": "20260101_000000",
            "objectives": {
                "1": {"name": "10x", "translation_um": [0, 0, 0], "session_id": None},
                "2": {"name": "20x", "translation_um": [1, 2, 3], "session_id": None},
            },
        }
        newly_adopted = {
            **old,
            "objectives": {
                "1": {"name": "10x", "translation_um": [0, 0, 0], "session_id": "new"},
                "2": {"name": "20x", "translation_um": [9, 8, 7], "session_id": "new"},
            },
        }
        path = Path("/tmp/lens_A/calibration.json")
        with (
            patch.object(cal_model, "default_path", return_value=path),
            patch.object(
                cal_model,
                "load_calibration",
                side_effect=[old, newly_adopted],
            ) as load,
        ):
            translations, info = drv_session._load_objective_calibration("lens_A")

        self.assertEqual(load.call_count, 1)
        self.assertEqual(translations[2], (1.0, 2.0, 3.0))
        self.assertEqual(info["measured_slots"], [])


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
            self.assertTrue(record["origin_file"].endswith("origin.json"))
            self.assertEqual(record["reference"]["z_focus_um"], 30.0)
            pos = adapter.get_xyz(h)
        self.assertEqual(pos["x"]["value"], 0.0)
        self.assertEqual(pos["z"]["value"], 0.0)
        self.assertEqual(pos["x"]["unit"], "um")
        self.assertEqual(pos["x"]["actuator"], "motoric")
        self.assertEqual(pos["z"]["actuator"], "z-wide")

    def test_set_origin_persists_into_its_own_origin_folder(self):
        import json
        import tempfile

        from navigator_expert.config.machine import MachineProfile

        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
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
            # Persists to the origin/ folder, independent of any snapshot.
            self.assertEqual(record["origin_file"], str(profile.origin_path()))
            self.assertEqual(profile.origin_path().parent.name, "origin")
            saved = json.loads(profile.origin_path().read_text(encoding="utf-8"))
            self.assertEqual(saved["origin"]["x_um"], 1000.0)
            self.assertEqual(saved["origin"]["z_wide_um"], 30.0)
            self.assertEqual(saved["origin"]["z_galvo_um"], 2.0)
            self.assertEqual(saved["origin"]["z_focus_um"], 32.0)
            self.assertEqual(saved["origin"]["objective"]["magnification"], 63)
            self.assertEqual(saved["job"], "Overview")

    def test_connect_does_not_restore_origin(self):
        """Origin is session-scoped: a fresh connection is an absolute frame."""
        import tempfile

        from navigator_expert.config.machine import MachineProfile

        with tempfile.TemporaryDirectory() as tmp:
            profile = MachineProfile(programdata_root=Path(tmp))
            # An origin file exists on disk from a previous session...
            profile.write_origin(
                {
                    "origin": _origin(x_um=1000.0, y_um=2000.0, z_wide_um=30.0, z_focus_um=30.0),
                    "captured_at": 123.0,
                }
            )
            with (
                patch.object(adapter._machine, "MACHINE", profile),
                patch.object(adapter._session, "connect_python_client", return_value=object()),
            ):
                h = adapter.connect(dict(adapter.CONNECTION))
            # ...but connect does NOT adopt it — the frame starts absolute.
            self.assertEqual(h.origin["x_um"], 0.0)
            self.assertEqual(h.origin["z_focus_um"], 0.0)

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
        # origin inside the physical backstop (x/y >= 1000)
        h = _handle(origin=_origin(x_um=10000.0, y_um=10000.0, z_focus_um=30.0))
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
            patch.object(
                adapter._readers,
                "get_selected_job",
                return_value={"Name": "HiRes", "IsSelected": True},
            ) as selected,
        ):
            opts = adapter.get_acquisition_options(h)
        # autofocus jobs are a separate category, never acquisition options
        self.assertEqual(opts["job"]["options"], ["Overview", "HiRes"])
        self.assertEqual(opts["job"]["active"], "HiRes")
        self.assertNotIn("mode", selected.call_args.kwargs)
        self.assertEqual(opts["strip_scan_fields"]["active"], True)  # default on
        self.assertEqual(opts["format"]["active"], "ome-tiff")
        self.assertEqual(opts["cleanup_source"]["active"], False)

    def test_unknown_or_invalid_option_rejected(self):
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(
                adapter._readers,
                "get_selected_job",
                return_value={"Name": "Overview", "IsSelected": True},
            ),
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
        with (
            patch.object(
                adapter._save, "save_source_root", side_effect=RuntimeError("no autosave")
            ),
            self.assertRaisesRegex(RuntimeError, "output_root"),
        ):
            adapter.acquire(h, acquisition_type="prescan", position_label="A1")

    def test_get_root_procedure_creates_default_run_root(self):
        h = _handle()
        with tempfile.TemporaryDirectory() as tmp:
            autosave = Path(tmp) / "lasx" / "project"
            autosave.mkdir(parents=True)
            with patch.object(adapter._save, "save_source_root", return_value=autosave):
                result = adapter.run_procedure(h, {"name": "get_root"})
                root = Path(result["root"])
        self.assertEqual(result["output_root"], str(root))
        self.assertEqual(root.parent, Path(tmp) / "lasx" / "zmart")
        self.assertTrue(root.name.startswith("target-acquisition_"))
        self.assertEqual(h.connection["output_root"], str(root))

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
            calls["state"] = kwargs.get("state")
            return SimpleNamespace(
                image_paths={0: Path("/tmp/out/img.ome.tif")},
                naming=naming,
            )

        patches = _patch_position(job="Overview")
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._readers, "get_hardware_info", return_value={}),
            patch.object(adapter._commands, "select_job", fake_select_job),
            patch.object(adapter._motion, "correct_backlash", lambda client, **k: None),
            patch.object(adapter._capture, "acquire", fake_capture),
            patch.object(adapter._save, "save", fake_save),
            patch.object(adapter._scanfields, "get_template_state", return_value="fresh"),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            record = adapter.acquire(
                h,
                acquisition_type="prescan",
                position_label="well-7",
                options={"job": "HiRes", "backlash_correction": False},
            )
        self.assertEqual(calls["selected"], "HiRes")
        self.assertEqual(calls["captured"], "HiRes")
        saved_root, naming = calls["saved"]
        self.assertEqual(Path(saved_root), Path("/tmp/out"))  # OS-agnostic separators
        self.assertEqual(naming.acquisition_type, "prescan")
        self.assertEqual(naming.position_label, "well-7")  # explicit label travels verbatim
        self.assertEqual(calls["lineage"]["position_label"], "well-7")
        self.assertEqual(calls["lineage"]["acquisition_type"], "prescan")
        # per-acquisition hash: the Naming hash is NOT the session hash
        self.assertNotEqual(naming.hash6, h.hash6)
        self.assertEqual(calls["lineage"]["acquisition_hash"], naming.hash6)
        self.assertEqual(calls["lineage"]["session_hash6"], h.hash6)
        # the machine/software state is captured and threaded into save()
        self.assertIsInstance(calls["state"], dict)
        self.assertEqual(calls["state"]["provenance"]["position_label"], "well-7")
        self.assertEqual(record["settle"], "direct")
        self.assertEqual([Path(p) for p in record["images"]], [Path("/tmp/out/img.ome.tif")])
        self.assertEqual(
            record["planes"],
            [{"t": 0, "z": 0, "c": 0, "path": "/tmp/out/img.ome.tif"}],
        )

    def test_acquire_applies_the_rigs_measured_orientation(self):
        """The microscope's measured turn reaches ``save``, so saved planes are
        already lined up with the stage.

        This is the safety seam the whole orientation feature rests on. The
        ``set_orientation`` notebook measures how the camera is turned relative to
        the stage and publishes it into the microscope's ProgramData snapshot,
        next to its calibration and limits. Every acquire must read that turn and
        hand it to ``save`` so the images that land on disk are stage-aligned. If
        this one wire were dropped, all the other tests would still pass, yet the
        machine would quietly save quarter-turned pictures -- and the workflow
        would then chase every feature the wrong way. Here we publish a measured
        90-degree turn into a hermetic snapshot and prove it arrives at ``save``.
        """
        from datetime import datetime, timezone

        from navigator_expert.config.machine import MachineProfile

        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        seen = {}

        def fake_save(client, acq, output_root, naming, **kwargs):
            seen["orientation"] = kwargs.get("orientation")
            return SimpleNamespace(image_paths={0: Path("/tmp/out/img.ome.tif")}, naming=naming)

        patches = _patch_position(job="Overview")
        with tempfile.TemporaryDirectory() as tmp:
            machine = MachineProfile(programdata_root=Path(tmp) / "programdata")
            machine.publish_snapshot(
                datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                orientation={"schema_version": 1, "rotate_deg": 90},
            )
            with (
                patch.object(adapter._machine, "MACHINE", machine),
                patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
                patch.object(adapter._readers, "get_hardware_info", return_value={}),
                patch.object(
                    adapter._commands, "select_job", lambda client, job, **k: {"success": True}
                ),
                patch.object(adapter._motion, "correct_backlash", lambda client, **k: None),
                patch.object(
                    adapter._capture, "acquire", lambda client, job, **k: SimpleNamespace(job=job)
                ),
                patch.object(adapter._save, "save", fake_save),
                patch.object(adapter._scanfields, "get_template_state", return_value="fresh"),
                patches[0],
                patches[1],
                patches[2],
                patches[3],
            ):
                adapter.acquire(
                    h,
                    acquisition_type="overview",
                    position_label="A1",
                    options={"backlash_correction": False},
                )

        # The measured 90-degree turn was read from the snapshot and threaded
        # into save -- not the shipped "no turn" placeholder.
        self.assertEqual(seen["orientation"], adapter._orientation.Orientation(rotate_deg=90))

    def _fake_acquire_env(self, calls):
        """Patches for a fully-mocked acquire; records each save's naming."""

        def fake_save(client, acq, output_root, naming, **kwargs):
            calls.setdefault("namings", []).append(naming)
            return SimpleNamespace(image_paths={0: Path("/tmp/out/img.ome.tif")}, naming=naming)

        patches = _patch_position(job="Overview")
        return (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._readers, "get_hardware_info", return_value={}),
            patch.object(adapter._commands, "select_job", return_value={"success": True}),
            patch.object(adapter._motion, "correct_backlash", lambda client, **k: None),
            patch.object(
                adapter._capture, "acquire", lambda client, job, **k: SimpleNamespace(job=job)
            ),
            patch.object(adapter._save, "save", fake_save),
            patch.object(adapter._scanfields, "get_template_state", return_value="fresh"),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        )

    def test_acquire_defaults_to_scan_type_and_counter_label(self):
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        calls = {}
        env = self._fake_acquire_env(calls)
        # A fresh hash is minted per acquire; stub run_hash (1s real resolution)
        # to prove two acquires get distinct per-acquisition hashes.
        with (
            env[0],
            env[1],
            env[2],
            env[3],
            env[4],
            env[5],
            env[6],
            env[7],
            env[8],
            env[9],
            env[10],
            patch.object(adapter, "run_hash", side_effect=["0000a1", "0000a2"]),
        ):
            record0 = adapter.acquire(h)
            record1 = adapter.acquire(h)
        self.assertEqual(record0["acquisition_type"], "scan")
        # unlabeled acquires consume the per-session counter, zero-padded
        self.assertEqual(record0["position_label"], "000000")
        self.assertEqual(record1["position_label"], "000001")
        namings = calls["namings"]
        self.assertEqual(namings[0].position_label, "000000")
        self.assertEqual(namings[1].position_label, "000001")
        # a fresh per-acquisition hash each time
        self.assertEqual(namings[0].hash6, "0000a1")
        self.assertEqual(namings[1].hash6, "0000a2")
        self.assertNotEqual(namings[0].hash6, namings[1].hash6)

    def test_explicit_label_does_not_consume_counter(self):
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        calls = {}
        env = self._fake_acquire_env(calls)
        with (
            env[0],
            env[1],
            env[2],
            env[3],
            env[4],
            env[5],
            env[6],
            env[7],
            env[8],
            env[9],
            env[10],
        ):
            adapter.acquire(h, position_label="named")  # must not bump the counter
            record = adapter.acquire(h)  # still gets 000000
        self.assertEqual(calls["namings"][0].position_label, "named")
        self.assertEqual(record["position_label"], "000000")

    def test_acquire_runs_backlash_correction_before_capture_when_enabled(self):
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        order = []

        def fake_select_job(client, job, **kwargs):
            order.append(("select", job))
            return {"success": True}

        def fake_correct_backlash(client, **kwargs):
            order.append(("backlash", client))

        def fake_capture(client, job, **kwargs):
            order.append(("capture", job))
            return SimpleNamespace(job=job)

        def fake_save(client, acq, output_root, naming, **kwargs):
            return SimpleNamespace(
                image_paths={0: Path("/tmp/out/img.ome.tif")},
                xml_paths={0: Path("/tmp/out/img.xml")},
                naming=naming,
            )

        patches = _patch_position(job="Overview")
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._commands, "select_job", fake_select_job),
            patch.object(adapter._motion, "correct_backlash", fake_correct_backlash),
            patch.object(adapter._capture, "acquire", fake_capture),
            patch.object(adapter._save, "save", fake_save),
            patch.object(adapter._scanfields, "get_template_state", return_value="fresh"),
            patches[2],
        ):
            record = adapter.acquire(
                h,
                acquisition_type="prescan",
                position_label="7",
                options={"job": "HiRes", "backlash_correction": True},
            )
        # select -> backlash takeup -> capture, in that order (backlash pins the
        # slack-state right before the image is taken, not before job selection).
        self.assertEqual(order, [("select", "HiRes"), ("backlash", h.client), ("capture", "HiRes")])
        self.assertEqual(record["settle"], "backlash-corrected")

    def _acquire_with_template_state(self, state, strip_result=None, options=None):
        """Run acquire with the scanfield layer patched; returns the calls list."""
        h = _handle(connection={**adapter.CONNECTION, "output_root": "/tmp/out"})
        calls = []
        patches = _patch_position(job="Overview")
        with (
            patch.object(adapter._readers, "get_jobs", return_value=self._jobs()),
            patch.object(adapter._commands, "select_job", return_value={"success": True}),
            patch.object(adapter._motion, "correct_backlash", lambda client, **k: None),
            patch.object(
                adapter._capture,
                "acquire",
                side_effect=lambda client, job, **k: (
                    calls.append("capture") or SimpleNamespace(job=job)
                ),
            ),
            patch.object(
                adapter._save,
                "save",
                return_value=SimpleNamespace(image_paths={}, xml_paths={}, naming=None),
            ),
            patch.object(adapter._scanfields, "get_template_state", return_value=state),
            patch.object(
                adapter._scanfields,
                "strip_template",
                side_effect=lambda client, **k: calls.append("strip") or strip_result,
            ),
            patches[2],
        ):
            adapter.acquire(h, acquisition_type="prescan", position_label="1", options=options)
        return calls

    def test_acquire_strips_an_unstripped_template_before_capturing(self):
        calls = self._acquire_with_template_state("unstripped", strip_result={"success": True})
        self.assertEqual(calls, ["strip", "capture"])

    def test_acquire_skips_the_strip_when_already_stripped(self):
        self.assertEqual(self._acquire_with_template_state("stripped"), ["capture"])

    def test_acquire_strip_can_be_opted_out(self):
        calls = self._acquire_with_template_state(
            "unstripped", options={"strip_scan_fields": False}
        )
        self.assertEqual(calls, ["capture"])

    def test_acquire_refuses_an_unreadable_template(self):
        with self.assertRaisesRegex(RuntimeError, "unreadable"):
            self._acquire_with_template_state("unreadable")

    def test_acquire_refuses_when_the_strip_fails(self):
        with self.assertRaisesRegex(RuntimeError, "could not strip"):
            self._acquire_with_template_state("unstripped", strip_result=None)


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
        with p[0] as hardware, p[1] as selected, p[2]:
            state = adapter.get_state(h)
        self.assertEqual(list(state), ["changeable", "observed"])  # changeable first
        self.assertEqual(state["changeable"], {"job": "Overview"})
        self.assertNotIn("mode", hardware.call_args.kwargs)
        self.assertNotIn("mode", selected.call_args.kwargs)
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
        self.assertIn("get_root", procedures)
        self.assertIn("get_positions", procedures)
        # The v4 operator notebook reads its autofocus points from LAS X through
        # this procedure, so the adapter must keep advertising it.
        self.assertIn("get_focus_points", procedures)
        self.assertEqual(procedures["autofocus"]["jobs"], ["AF Job"])
        with patch.object(adapter._motion, "correct_backlash", lambda client, **k: None):
            self.assertEqual(
                adapter.run_procedure(h, {"name": "backlash_takeup"})["ran"]["name"],
                "backlash_takeup",
            )
        scan_field = {
            "positions": [
                {"kind": "grid", "frame": {"x_um": 1, "y_um": 2, "z_um": 3}},
                {"kind": "focus-point", "frame": {"x_um": 4, "y_um": 5, "z_um": 6}},
                {"kind": "autofocus-point", "frame": {"x_um": 7, "y_um": 8, "z_um": None}},
            ]
        }
        with patch.object(adapter, "_scan_field", return_value=scan_field):
            self.assertEqual(
                adapter.run_procedure(h, {"name": "get_positions"})["positions"],
                [{"x": 1.0, "y": 2.0, "z": 3.0}],
            )
            self.assertEqual(
                adapter.run_procedure(h, {"name": "get_focus_points"})["positions"],
                [{"x": 4.0, "y": 5.0, "z": 6.0}, {"x": 7.0, "y": 8.0}],
            )
        with self.assertRaises(ValueError):
            adapter.run_procedure(h, {"name": "nope"})

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
            patch.object(adapter._scanfields, "get_template_state", return_value="fresh"),
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
            result = adapter.run_procedure(h, {"name": "autofocus"})  # single AF job: no arg
        # select AF -> capture -> restore the original selection, in order
        self.assertEqual(
            calls, [("select", "AF Job"), ("acquire", "AF Job"), ("select", "Overview")]
        )
        self.assertEqual(result["ran"], "autofocus")
        self.assertEqual(result["job"], "AF Job")
        self.assertEqual(result["focus_um"], 43.5)  # 42.0 + 1.5, read before restore
        self.assertEqual(result["frame_z_um"], 43.5)  # all-zero origin
        self.assertEqual(result["duration_s"], 2.5)

    def test_autofocus_strips_an_unstripped_template_first(self):
        h = _handle()
        p = self._state_patches()
        strip = MagicMock(return_value={"success": True})
        position = _patch_position()
        with (
            p[2],
            position[0],
            position[1],
            position[2],
            position[3],
            patch.object(adapter._scanfields, "get_template_state", return_value="unstripped"),
            patch.object(adapter._scanfields, "strip_template", strip),
            patch.object(adapter._commands, "select_job", return_value={"success": True}),
            patch.object(
                adapter._capture,
                "acquire",
                return_value=SimpleNamespace(job="AF Job", started_at=0.0, finished_at=1.0),
            ),
        ):
            adapter.run_procedure(h, {"name": "autofocus"})
        strip.assert_called_once()

    def test_autofocus_rejects_a_normal_job(self):
        h = _handle()
        p = self._state_patches()
        with p[2]:
            with self.assertRaisesRegex(ValueError, "not an autofocus job"):
                adapter.run_procedure(h, {"name": "autofocus", "job": "Overview"})

    def test_autofocus_requires_a_choice_when_several_exist(self):
        h = _handle()
        p = self._state_patches(af_jobs=("AF Job", "AF Fine"))
        with p[2]:
            with self.assertRaisesRegex(ValueError, "multiple autofocus jobs"):
                adapter.run_procedure(h, {"name": "autofocus"})

    def test_autofocus_without_af_jobs_is_a_clear_error(self):
        h = _handle()
        p = self._state_patches(af_jobs=())
        with p[2]:
            with self.assertRaisesRegex(RuntimeError, "no autofocus job"):
                adapter.run_procedure(h, {"name": "autofocus"})


class TestScanFieldContext(unittest.TestCase):
    """get_context().scan_field: template positions, typed, in both spaces."""

    _PARSED = {
        "acquisition_positions": {
            "0": {
                "job_name": "HiRes",
                "positions": [
                    {"row": 0, "col": 0, "x_um": 1100.0, "y_um": 2200.0, "z_um": 40.0},
                    {"row": 0, "col": 1, "x_um": 1150.0, "y_um": 2200.0, "z_um": 41.0},
                ],
            }
        },
        "focus_points": [
            {"identifier": "F1", "x_um": 1500.0, "y_um": 2500.0, "z_um": 33.0, "enabled": True}
        ],
        "autofocus_points": [
            {"identifier": "AF1", "x_um": 1600.0, "y_um": 2600.0, "z_um": 35.0, "enabled": True}
        ],
        "geometries": {
            "g1": {"type": "Point", "center_um": {"x_um": 1050.0, "y_um": 2050.0}, "label": "A"},
            "g2": {"type": "Rectangle", "center_um": {"x_um": 9.0, "y_um": 9.0}},
        },
    }

    def _context(self, parsed=None, save_result=None, templates_dir="X:/tpl"):
        h = _handle(origin=_origin(x_um=1000.0, y_um=2000.0, z_wide_um=30.0, z_focus_um=30.0))
        calls = []
        position = _patch_position()
        save_result = {"success": True} if save_result is None else save_result
        with (
            position[0],
            position[1],
            position[2],
            position[3],
            patch.object(
                adapter._scanfields,
                "find_scanning_templates_dir",
                return_value=None if templates_dir is None else Path(templates_dir),
            ),
            patch.object(
                adapter._scanfields,
                "save_experiment",
                side_effect=lambda *a, **k: calls.append("save") or save_result,
            ),
            patch.object(
                adapter._scanfields,
                "parse_scan_positions",
                side_effect=lambda *a, **k: (
                    calls.append("parse") or dict(parsed if parsed is not None else self._PARSED)
                ),
            ),
            patch.object(adapter._scanfields, "get_template_state", return_value="unstripped"),
        ):
            return adapter.get_context(h), calls

    def test_positions_are_typed_and_in_both_spaces(self):
        context, calls = self._context()
        self.assertEqual(calls, ["save", "parse"])  # always flush before parsing
        field = context["scan_field"]
        self.assertEqual(field["template_state"], "unstripped")
        by_kind = {}
        for position in field["positions"]:
            by_kind.setdefault(position["kind"], []).append(position)
        # grid tiles carry their group and job; frame = stage - origin
        first = by_kind["grid"][0]
        self.assertEqual(first["group"], {"region": "0", "row": 0, "col": 0})
        self.assertEqual(first["job"], "HiRes")
        self.assertEqual(first["stage"], {"x_um": 1100.0, "y_um": 2200.0, "z_um": 40.0})
        self.assertEqual(first["frame"], {"x_um": 100.0, "y_um": 200.0, "z_um": 10.0})
        self.assertEqual(len(by_kind["grid"]), 2)
        # focus and autofocus points are distinct kinds
        self.assertEqual(by_kind["focus-point"][0]["id"], "F1")
        self.assertEqual(by_kind["focus-point"][0]["frame"]["z_um"], 3.0)
        self.assertEqual(by_kind["autofocus-point"][0]["id"], "AF1")
        # point markers come through with their label; other shapes do not
        marker = by_kind["marker"][0]
        self.assertEqual(marker["label"], "A")
        self.assertEqual(marker["frame"]["x_um"], 50.0)
        self.assertIsNone(marker["frame"]["z_um"])
        self.assertEqual(len(field["positions"]), 5)

    def test_no_templates_profile_reports_none(self):
        context, calls = self._context(templates_dir=None)
        self.assertIsNone(context["scan_field"])
        self.assertEqual(calls, [])  # nothing saved, nothing parsed

    def test_unconfirmed_save_degrades_to_none(self):
        # get_context is informational: a stale template must not raise.
        context, calls = self._context(save_result=False)
        self.assertIsNone(context["scan_field"])
        self.assertEqual(calls, ["save"])
        self.assertEqual(context["session_hash6"], "000abc")  # rest of the context intact


class TestObjectiveCompensation(unittest.TestCase):
    """Cross-objective frame math: ΔT = T[current] − T[origin's objective].

    Uses the EXISTING calibration translation totals (no schema change,
    operator decision 2026-07-02); the driver assumes x/y apply to the motoric
    stage and objective-translation z applies through z-wide.
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
                z_wide_um=30.0,
                z_galvo_um=0.0,
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
        moves = {"z": []}

        def fake_xy(client, x_um, y_um, **kwargs):
            moves["xy"] = (x_um, y_um)
            return {"success": True, "confirmed": True}

        def fake_z(client, job, z, unit="um", z_mode="galvo", **kwargs):
            moves["z"].append((z, z_mode))
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
        # ΔT.z=10 is pinned absolutely on z-wide (30+10), while the
        # ordinary requested frame z=5 is realized by z-galvo (0+5).
        self.assertEqual(moves["z"], [(40.0, "zwide"), (5.0, "galvo")])
        self.assertEqual(record["objective_translation_um"], [100.0, 50.0, 10.0])
        self.assertEqual(record["hardware_targets"]["z_wide_um"], 40.0)
        self.assertEqual(record["hardware_targets"]["z_galvo_um"], 5.0)

    def test_cross_objective_galvo_moves_do_not_accumulate_translation_on_zwide(self):
        h = self._cross_handle()
        moves = []

        def fake_z(client, job, z, unit="um", z_mode="galvo", **kwargs):
            moves.append((z, z_mode))
            return {"success": True, "confirmed": True}

        patches = _patch_position(z_wide_um=40.0, z_galvo_um=0.0, slot=2)
        with (
            patch.object(
                adapter._motion,
                "move_xy_with_backlash",
                return_value={"success": True, "confirmed": True},
            ),
            patch.object(adapter._commands, "move_z", fake_z),
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            adapter.set_xyz(h, 0.0, 0.0, 4.0, with_actuators={"z": "z-galvo"})
            adapter.set_xyz(h, 1.0, 1.0, 4.0, with_actuators={"z": "z-galvo"})

        assert moves == [
            (40.0, "zwide"),
            (4.0, "galvo"),
            (40.0, "zwide"),
            (4.0, "galvo"),
        ]

    def test_cross_objective_zwide_translation_is_preflighted_before_any_motion(self):
        h = self._cross_handle()
        install_permissive_limits(
            h.client,
            z_wide_um={"min": 0.0, "max": 35.0},
            z_galvo_um={"min": -200.0, "max": 200.0},
        )
        patches = _patch_position(z_wide_um=40.0, z_galvo_um=0.0, slot=2)
        with (
            patch.object(adapter._motion, "move_xy_with_backlash") as xy,
            patch.object(adapter._commands, "move_z") as move_z,
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            self.assertRaisesRegex(RuntimeError, "z_wide_um") as ctx,
        ):
            adapter.set_xyz(h, 0.0, 0.0, 4.0, with_actuators={"z": "z-galvo"})
        xy.assert_not_called()
        move_z.assert_not_called()
        # The failing leg is the calibrated objective offset, which only
        # z-wide can realize — suggesting the other actuator would send the
        # operator in a circle, so the message must not do that.
        message = str(ctx.exception)
        self.assertIn("calibrated objective offset", message)
        self.assertNotIn("with_actuators", message)

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
            patch.object(_cmd_settings, "make_changeable_copy", side_effect=lambda s: s),
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
        h = _handle(
            origin=_origin(x_um=10000.0, y_um=10000.0, objective={"name": "63x", "slotIndex": 3})
        )
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


class TestDriverSetupReadiness(unittest.TestCase):
    def test_ready_requires_measured_orientation_loaded_calibration_and_active_slot(self):
        h = _handle(origin=_origin(objective={"slotIndex": 1, "name": "10x"}))
        adapter._session_state.install(
            h.client,
            adapter._session_state.SessionConfig(
                orientation=adapter._orientation.Orientation(rotate_deg=0),
                translations={1: (0.0, 0.0, 0.0), 2: (1.0, 2.0, 3.0)},
                calibration_name="water_lens_setup",
                orientation_info={"loaded": True, "measured": True, "rotate_deg": 0},
                calibration_info={
                    "loaded": True,
                    "name": "water_lens_setup",
                    "slots": [1, 2],
                    "measured_slots": [1, 2],
                },
            ),
        )
        self.addCleanup(adapter._session_state.uninstall, h.client)

        ready = adapter._setup_readiness(h, {"slotIndex": 2, "name": "20x"})
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["issues"], [])

        missing = adapter._setup_readiness(h, {"slotIndex": 3, "name": "40x"})
        self.assertFalse(missing["ready"])
        self.assertIn("slot 3", missing["issues"][0])

        h.origin["objective"] = {"slotIndex": 4, "name": "uncalibrated"}
        bad_origin = adapter._setup_readiness(h, {"slotIndex": 2, "name": "20x"})
        self.assertFalse(bad_origin["ready"])
        self.assertIn("run-origin objective slot 4", bad_origin["issues"][0])

    def test_seeded_placeholder_calibration_is_not_ready_even_though_it_loads(self):
        """A bundled-default calibration loads fine but was never measured HERE.

        Its entries carry no session provenance (``measured_slots`` empty), so
        the verdict must refuse — otherwise a never-calibrated microscope would
        compensate objective changes with the repository's placeholder numbers.
        """
        h = _handle(origin=_origin(objective={"slotIndex": 1, "name": "10x"}))
        adapter._session_state.install(
            h.client,
            adapter._session_state.SessionConfig(
                orientation=adapter._orientation.Orientation(rotate_deg=0),
                translations={1: (0.0, 0.0, 0.0), 2: (-6.5, 21.5, -3.7)},
                calibration_name="water_lens_setup",
                orientation_info={"loaded": True, "measured": True, "rotate_deg": 0},
                calibration_info={
                    "loaded": True,
                    "name": "water_lens_setup",
                    "slots": [1, 2],
                    "measured_slots": [],  # seeded from the bundled placeholder
                },
            ),
        )
        self.addCleanup(adapter._session_state.uninstall, h.client)

        setup = adapter._setup_readiness(h, {"slotIndex": 2, "name": "20x"})

        self.assertFalse(setup["ready"])
        self.assertTrue(any("placeholder" in issue for issue in setup["issues"]))
        self.assertTrue(any("calibrate_objective_pair" in issue for issue in setup["issues"]))

    def test_calibration_info_without_provenance_field_fails_closed(self):
        """An info dict lacking measured_slots must count as unmeasured."""
        h = _handle(origin=_origin(objective={"slotIndex": 1, "name": "10x"}))
        adapter._session_state.install(
            h.client,
            adapter._session_state.SessionConfig(
                orientation=adapter._orientation.Orientation(rotate_deg=0),
                translations={1: (0.0, 0.0, 0.0)},
                orientation_info={"loaded": True, "measured": True, "rotate_deg": 0},
                calibration_info={"loaded": True, "slots": [1]},
            ),
        )
        self.addCleanup(adapter._session_state.uninstall, h.client)

        setup = adapter._setup_readiness(h, {"slotIndex": 1, "name": "10x"})

        self.assertFalse(setup["ready"])
        self.assertTrue(any("placeholder" in issue for issue in setup["issues"]))

    def test_placeholder_orientation_is_not_ready_even_when_rotation_is_zero(self):
        h = _handle(origin=_origin(objective={"slotIndex": 1, "name": "10x"}))
        adapter._session_state.install(
            h.client,
            adapter._session_state.SessionConfig(
                orientation=adapter._orientation.Orientation(rotate_deg=0),
                translations={1: (0.0, 0.0, 0.0)},
                orientation_info={"loaded": True, "measured": False, "rotate_deg": 0},
                calibration_info={"loaded": True, "slots": [1]},
            ),
        )
        self.addCleanup(adapter._session_state.uninstall, h.client)

        setup = adapter._setup_readiness(h, {"slotIndex": 1})

        self.assertFalse(setup["ready"])
        self.assertIn("orientation", setup["issues"][0])


class TestLifecycle(unittest.TestCase):
    def test_ops_after_disconnect_raise(self):
        h = _handle()
        adapter.disconnect(h)
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            adapter.get_actuators(h)

    def test_disconnect_uninstalls_the_commands_layer_gate_state(self):
        h = _handle()
        self.assertIsNotNone(adapter._gate.state_for(h.client))
        adapter.disconnect(h)
        self.assertIsNone(adapter._gate.state_for(h.client))

    def test_connect_runs_the_limits_handshake(self):
        """connect must run the machine-local limits handshake, or set_xyz can't move.

        move_xy/move_z refuse until the stage envelope is applied and the
        function-keyed gate is installed, and the controller has no limits
        hook -- so the adapter's connect must do it, against REAL machine-local
        files, seeding ProgramData defaults first when needed.
        """
        import os

        _clear_limits()
        self.addCleanup(_clear_limits)
        provision_machine_limits(os.environ["ZMART_MICROSCOPY_ROOT"])
        with patch.object(adapter._session, "connect_python_client", return_value=object()):
            h = adapter.connect(dict(adapter.CONNECTION))
        self.assertIsInstance(h, adapter.ZmartHandle)
        # the stage envelope was applied from the ProgramData snapshot...
        self.assertEqual(adapter._limits.get_stage_limits()["x_max"], 130000.0)
        # ...and the commands-layer gate governs this client (with provenance)
        described = _gate.describe(h.client)
        self.assertEqual(described["source"], "machine")
        self.assertFalse(described["is_fallback"])

    def test_connect_seeds_default_limits_when_programdata_is_empty(self):
        """Empty ProgramData is initialized from defaults, then governs the session."""
        with patch.object(adapter._session, "connect_python_client", return_value=object()):
            h = adapter.connect(dict(adapter.CONNECTION))
        self.assertIsInstance(h, adapter.ZmartHandle)
        self.assertFalse(h.closed)
        described = _gate.describe(h.client)
        self.assertEqual(described["source"], "defaults")
        self.assertFalse(described["is_fallback"])
        state = _gate.state_for(h.client)
        self.assertTrue(state.ok)

    def test_full_controller_session_flow(self):
        """End to end through a real zmart_controller Session (real handshake)."""
        import os

        import zmart_controller

        _clear_limits()
        self.addCleanup(_clear_limits)
        provision_machine_limits(os.environ["ZMART_MICROSCOPY_ROOT"])
        patches = _patch_position(x_um=1000.0, y_um=2000.0, z_wide_um=30.0)
        with (
            patch.object(adapter._session, "connect_python_client", return_value=object()),
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
    """The commands-layer function-keyed gate as seen through the adapter.

    The gate itself lives in ``commands/gate.py`` (and is exhaustively
    attacked in test_limits_adversarial.py); these tests pin the adapter's
    contract on top of it: whole-move pre-flight, fail-closed refusals with
    actionable RuntimeErrors, and provenance reporting.
    """

    def test_bundled_template_covers_every_declared_key(self):
        """THE completeness guard on the template: a new key cannot ship absent."""
        from shared import limits as shared_limits

        path = adapter._machine.MACHINE.bundled_default_path(adapter._machine.LIMITS_FILENAME)
        limits = shared_limits.load(path, functions=_gate.FUNCTION_LIMIT_KEYS, is_fallback=True)
        self.assertEqual(limits.source, "defaults")
        self.assertTrue(limits.is_fallback)  # provenance: template, not machine

    def test_set_xyz_refuses_beyond_function_limits_before_any_motion(self):
        _wide_limits()  # Phase A permissive, so the function-limits layer is what fires
        self.addCleanup(_clear_limits)
        h = _handle(gate_constraints={"x_um": {"min": 0, "max": 500}})
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
        h = _handle(
            gate_constraints={"z_galvo_um": {"min": -200, "max": 200}},
            origin=_origin(x_um=10000.0, y_um=10000.0),
        )
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

    def test_mutating_ops_refuse_without_a_limits_handshake(self):
        """Fail-closed below the adapter: no gate state means no mutations.

        The refusal comes from the commands layer and surfaces as the ops
        contract's RuntimeError; read-only ops still work. (set_origin fires
        no native command — it captures a reference — so it is deliberately
        not among the refusals.)
        """
        _wide_limits()  # the stage envelope alone must NOT be enough
        self.addCleanup(_clear_limits)
        h = _handle(gated=False)
        patches = _patch_position()
        catalog = [
            {"Name": "Overview", "IsSelected": True, "IsAutofocus": False},
            {"Name": "HiRes", "IsSelected": False, "IsAutofocus": False},
        ]
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(adapter._readers, "get_jobs", return_value=catalog),
        ):
            with self.assertRaisesRegex(RuntimeError, "refused"):
                adapter.set_xyz(h, 0.0, 0.0, 0.0)
            with self.assertRaisesRegex(RuntimeError, "refused"):
                adapter.set_state(h, {"changeable": {"job": "HiRes"}})
            with self.assertRaisesRegex(RuntimeError, "refused"):
                adapter.run_procedure(h, {"name": "backlash_takeup"})
            self.assertIn("backlash_takeup", adapter.get_procedures(h))  # reads fine

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

    def test_machine_stage_envelope_governs_the_gate(self):
        """The snapshot's envelope governs moves, never a stale template copy."""
        import os

        _clear_limits()
        self.addCleanup(_clear_limits)
        provision_machine_limits(
            os.environ["ZMART_MICROSCOPY_ROOT"],
            stage_um=dict(DEFAULT_STAGE_UM, x=[2000.0, 50000.0]),
        )
        client = object()
        state = _gate.connect_handshake(client)
        self.assertTrue(state.ok)
        state.limits.check("set_xyz", {"x_um": 2500.0})
        from shared import limits as shared_limits

        with self.assertRaises(shared_limits.LimitViolation):
            # inside the template envelope, outside the machine's
            state.limits.check("set_xyz", {"x_um": 1500.0})

    def test_unknown_machine_axis_falls_back_to_defaults(self):
        """An envelope the schema can't represent falls back to bundled defaults."""
        import os

        provision_machine_limits(
            os.environ["ZMART_MICROSCOPY_ROOT"],
            stage_um=dict(DEFAULT_STAGE_UM, theta=[0.0, 360.0]),
        )
        client = object()
        state = _gate.connect_handshake(client)
        # The invalid machine file is not used; the session is governed by the
        # bundled DEFAULT limits (loudly), never left fail-closed.
        self.assertTrue(state.ok)
        self.assertTrue(state.limits.describe()["is_fallback"])
        # A move inside the default envelope is allowed; one outside is refused.
        self.assertIsNone(_gate.check_refusal(client, "move_xy", {"x_um": 5000.0, "y_um": 5000.0}))
        self.assertIsNotNone(
            _gate.check_refusal(client, "move_xy", {"x_um": 999999.0, "y_um": 5000.0})
        )


if __name__ == "__main__":
    unittest.main()
