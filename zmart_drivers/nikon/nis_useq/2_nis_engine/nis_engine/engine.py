"""A useq-schema acquisition engine for NIS-Elements.

``NisEngine`` implements the engine interface of pymmcore-plus (``PMDAEngine``),
so the pymmcore-plus runner can execute useq sequences (the classic
``useq.MDASequence`` and the new ``useq.v2.MDASequence``) on a Nikon microscope
and hand the images to any of its writers or viewers.

What each event field does here:

- ``x_pos``, ``y_pos``, ``z_pos``: absolute NIS stage position in um; None = stay.
- ``channel.config``: the name of a NIS optical configuration (``group`` is ignored).
- ``exposure``: camera exposure in ms.
- ``properties``: ``("Nosepiece", "Position", n)`` turns the nosepiece to slot n
  (1, 2, ...); ``("PFS", "State", "On")`` or ``"Off"`` switches the Perfect Focus System.
- ``action``: ``AcquireImage`` snaps one image. ``HardwareAutofocus`` locks focus
  with the PFS, then switches it off.
  ``CustomAction(name="autofocus", data={"range_um": 50, "speed": 30})`` runs the
  NIS image-based focus sweep. A focus action shifts later Z moves at the same
  position by the distance it moved.

Anything else (camera ROI, SLM images, other custom actions) is refused before
the run starts. ``keep_shutter_open`` is ignored; NIS handles the shutter.
Waiting for ``min_start_time`` is the runner's job.

The bridge and this engine must run on the same computer: each image travels
as a temporary TIFF file.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
from nis_bridge.client import NisClient, NisConnectionError
from nis_bridge.protocol import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TIMEOUT_S
from useq import AcquireImage, CustomAction, HardwareAutofocus, MDAEvent

log = logging.getLogger("nis_engine")

SNAP_TIMEOUT_S = 120.0
FOCUS_TIMEOUT_S = 300.0

# The (device, property) pairs an event may set, with the values each accepts.
PROPERTIES = {
    ("Nosepiece", "Position"): "a nosepiece slot number (1, 2, ...)",
    ("PFS", "State"): '"On" or "Off"',
}


class NisEngine:
    """Runs useq events on NIS-Elements through the bridge.

    With pymmcore-plus::

        runner = MDARunner()
        runner.set_engine(NisEngine())
        runner.run(sequence, output="run.ome.tiff")
    """

    def __init__(
        self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT_S
    ):
        self.client = NisClient(host, port, timeout)
        self.user_limits: dict[str, tuple[float, float]] = {}  # see set_limits
        self._workdir: Path | None = None  # temporary TIFFs of the current run
        # What the microscope offers, read by check() and setup_sequence().
        self._limits: dict[str, dict[str, float]] = {}
        self._configurations: list[str] = []
        self._objectives: list[int] = []
        self._has_pfs = False
        self._pfs_at_start = False  # restored by teardown_sequence
        self._pixel_size_um: float | None = None  # measured by the run's first snap
        self._image_shape: tuple[int, int] | None = None

    def close(self) -> None:
        self.client.close()

    def reconnect(self) -> None:
        """Open a new connection to the bridge, for example after a timeout closed the
        old one, or after start_bridge.mac was restarted. The session limits stay."""
        old = self.client
        old.close()
        self.client = NisClient(old.host, old.port, old.timeout)

    # -- stage limits ----------------------------------------------------------

    def set_limits(
        self,
        x: tuple[float | None, float | None] | None = None,
        y: tuple[float | None, float | None] | None = None,
        z: tuple[float | None, float | None] | None = None,
    ) -> None:
        """Narrow the stage limits for this session, each axis as (min, max) in um.

        These come on top of the limits set in NIS-Elements: an axis can only get
        narrower, never wider. None, for an axis or for one side of it, keeps
        NIS's own limit there. Raises ValueError, changing nothing, when a
        minimum is not below its maximum or a range lies outside NIS's limits.
        """
        previous = self.user_limits
        self.user_limits = {
            axis: (bounds[0], bounds[1])
            for axis, bounds in {"x": x, "y": y, "z": z}.items()
            if bounds is not None
        }
        try:
            limits = self.limits()
        except Exception:  # the bridge did not answer: keep what was in force
            self.user_limits = previous
            raise
        for axis, limit in limits.items():
            if not limit["min"] < limit["max"]:
                self.user_limits = previous
                raise ValueError(
                    f"{axis}: the minimum must be below the maximum, inside NIS's own limits"
                )

    def limits(self) -> dict[str, dict[str, float]]:
        """The stage limits in force (um): NIS's own, narrowed by set_limits."""
        limits = self.client.request("get_limits")
        for axis, (lo, hi) in self.user_limits.items():
            if lo is not None:
                limits[axis]["min"] = max(float(lo), limits[axis]["min"])
            if hi is not None:
                limits[axis]["max"] = min(float(hi), limits[axis]["max"])
        return limits

    def field_of_view(self) -> tuple[float, float]:
        """The camera field (width, height) in um, from one image and NIS's pixel size.

        Takes one image. Raises ValueError when NIS has no pixel calibration for
        the objective in use, since the field size is then unknown.
        """
        with tempfile.TemporaryDirectory(prefix="nis_engine_fov_") as folder:
            path = Path(folder) / "fov.tif"
            reply = self.client.request("snap", path=str(path), timeout=SNAP_TIMEOUT_S)
            height, width = tifffile.imread(path).shape[:2]
        pixel_size_um = reply["pixel_size_um"]
        if pixel_size_um is None:
            raise ValueError(
                "NIS reports no pixel calibration for the objective in use, so the size of "
                "the camera field is unknown. Calibrate the objective in NIS, or give the "
                "field of view in um."
            )
        return width * pixel_size_um, height * pixel_size_um

    # -- sequence --------------------------------------------------------------

    def check(self, sequence: Any) -> list[MDAEvent]:
        """Check a whole sequence against the microscope without moving or imaging.

        Returns the checked events. Raises ValueError, naming the first problem.
        """
        self._read_microscope()
        self._pixel_size_um = self._image_shape = None  # not measured by a check
        return list(self.event_iterator(sequence))

    def setup_sequence(self, sequence: Any) -> dict:
        """Read what the microscope offers, and return summary metadata for writers.

        Snaps one image with the current settings, so that file writers know the
        image size and pixel size before the first frame of the run.
        """
        self._read_microscope()
        self._pfs_at_start = self.client.request("get_pfs")["on"]  # restored by teardown
        self._channel: str | None = None  # unknown until the first event sets it
        self._exposure_requested: float | None = None
        self._exposure_ms: float | None = None  # as NIS applied it; NIS cannot report it
        self._z_offset: dict[int | None, float] = {}  # focus found per position index
        self._workdir = self._workdir or Path(tempfile.mkdtemp(prefix="nis_engine_"))
        self._frames = 0
        self._t0 = time.perf_counter()

        probe, self._pixel_size_um = self._snap()
        if probe.ndim != 2:
            raise ValueError(
                f"the camera gives colour or multi-plane images (shape {probe.shape}), which this "
                "engine does not save correctly. Set the camera to monochrome in NIS-Elements."
            )
        self._image_shape = height, width = probe.shape
        return {
            "format": "summary-dict",
            "version": "1.0",
            "datetime": datetime.now().astimezone().isoformat(sep=" "),
            "devices": (),
            "system_info": {
                "nis_elements": self.client.info["nis"],
                "bridge": self.client.info["bridge"],
            },
            "image_infos": (
                {
                    "camera_label": "NIS-Elements",
                    "plane_shape": probe.shape,
                    "dtype": str(probe.dtype),
                    "height": height,
                    "width": width,
                    "pixel_format": f"Mono{probe.dtype.itemsize * 8}",
                    "pixel_size_um": self._pixel_size_um,
                    "pixel_size_config_name": "",
                },
            ),
            "position": self.client.request("get_position"),
            "config_groups": (),
            "pixel_size_configs": (),
            "mda_sequence": sequence,
        }

    def event_iterator(self, events: Iterable[MDAEvent]) -> Iterator[MDAEvent]:
        """Check the whole plan before anything moves, then hand out the events."""
        self._check_plans(events)
        events = list(events)
        for event in events:
            self._check(event)
        yield from events

    def _read_microscope(self) -> None:
        """What every check needs: stage limits, configurations, objectives, PFS."""
        self._limits = self.limits()
        self._configurations = self.client.request("get_optical_configurations")
        self._objectives = [int(p) for p in self.client.request("get_objectives")["objectives"]]
        self._has_pfs = self.client.request("get_pfs")["present"]

    def teardown_sequence(self, sequence: Any) -> None:
        """Remove the temporary images, and put the PFS back the way the run found it."""
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None
        # Never raise here: the runner would then not finish the run, and whatever
        # waits for its end (a viewer, the assistant) would wait forever.
        try:
            if self._has_pfs and self.client.request("get_pfs")["on"] != self._pfs_at_start:
                self.client.request("set_pfs", on=self._pfs_at_start)
        except Exception as exc:  # noqa: BLE001 - reported, and the run still finishes
            log.warning("could not put the PFS back after the run: %s", exc)

    # -- events ----------------------------------------------------------------

    def setup_event(self, event: MDAEvent) -> None:
        """Move the stage, then apply channel, exposure and properties."""
        # Checked again here because the runner skips event_iterator when it is
        # given a plain iterator of events.
        self._check(event)
        target = {"x": event.x_pos, "y": event.y_pos, "z": event.z_pos}
        if target["z"] is not None:
            target["z"] += self._z_offset.get(event.index.get("p"), 0.0)
        target = {axis: value for axis, value in target.items() if value is not None}
        if target:
            self._check_limits(f"{_where(event)} (with the focus correction)", target)
            self.client.request("move", **target)

        if event.channel is not None and event.channel.config != self._channel:
            self.client.request("select_optical_configuration", name=event.channel.config)
            self._channel = event.channel.config
            # A configuration can bring its own exposure, which NIS cannot report.
            self._exposure_requested = self._exposure_ms = None

        if event.exposure is not None and event.exposure != self._exposure_requested:
            reply = self.client.request("set_exposure", exposure_ms=event.exposure)
            self._exposure_requested, self._exposure_ms = event.exposure, reply["exposure_ms"]

        for device, prop, value in event.properties or ():
            if (device, prop) == ("Nosepiece", "Position"):
                self.client.request("set_objective", position=int(value))
            else:  # ("PFS", "State"), checked in _check
                self.client.request("set_pfs", on=_on_off(value))

    def exec_event(self, event: MDAEvent) -> Iterator[tuple[np.ndarray, MDAEvent, dict]]:
        """Snap an image, or run a focus action (which yields no image)."""
        action = event.action
        if isinstance(action, HardwareAutofocus):
            try:
                self._focus(event, "set_pfs", on=True)
            finally:
                # Off again, so the PFS does not fight the Z moves that follow.
                self.client.request("set_pfs", on=False)
            return
        if isinstance(action, CustomAction):  # "autofocus", checked in _check
            self._focus(event, "autofocus", **action.data)
            return

        image, pixel_size_um = self._snap()
        t0 = event.metadata.get("runner_t0", self._t0)  # the pymmcore-plus runner sets this
        yield (
            image,
            event,
            {
                "format": "frame-dict",
                "version": "1.0",
                "pixel_size_um": pixel_size_um,
                "camera_device": "NIS-Elements",
                "exposure_ms": self._exposure_ms or 0.0,  # 0 = not set in this sequence
                "property_values": (),
                "runner_time_ms": (time.perf_counter() - t0) * 1000,
                "position": self.client.request("get_position"),
                "mda_event": event,
            },
        )

    def teardown_event(self, event: MDAEvent) -> None:
        pass

    # -- helpers ---------------------------------------------------------------

    def _snap(self) -> tuple[np.ndarray, float | None]:
        """Capture in NIS, read the saved TIFF back, delete it. Returns image and um/px."""
        self._frames += 1
        path = self._workdir / f"frame_{self._frames:06d}.tif"
        reply = self.client.request("snap", path=str(path), timeout=SNAP_TIMEOUT_S)
        image = tifffile.imread(path)
        path.unlink()
        return image, reply["pixel_size_um"]

    def _focus(self, event: MDAEvent, op: str, **args: Any) -> None:
        """Run a focus op and remember how far it moved Z at this position.

        Later events at the same position are shifted by the same distance, so a
        Z-stack taken after focusing keeps its place relative to the focus. If
        focusing fails, the run continues without a shift (as in pymmcore-plus).
        """
        before = self.client.request("get_position")["z"]
        try:
            result = self.client.request(op, timeout=FOCUS_TIMEOUT_S, **args)
        except NisConnectionError:
            raise  # a lost connection must stop the run (it is also a RuntimeError)
        except RuntimeError as exc:
            log.warning("focus failed at %s; continuing without it: %s", _where(event), exc)
            return
        if op == "set_pfs" and result["status"] != 1:
            log.warning("PFS did not lock at %s: %s", _where(event), result["meaning"])
            return
        after = self.client.request("get_position")["z"]
        p = event.index.get("p")
        self._z_offset[p] = self._z_offset.get(p, 0.0) + after - before

    def _check(self, event: MDAEvent) -> None:
        """Raise ValueError if this engine cannot run the event as written."""
        where = _where(event)
        if event.roi is not None or event.slm_image is not None:
            raise ValueError(f"{where}: camera ROI and SLM images are not supported")

        position = {"x": event.x_pos, "y": event.y_pos, "z": event.z_pos}
        self._check_limits(where, {k: v for k, v in position.items() if v is not None})

        if event.channel is not None and event.channel.config not in self._configurations:
            raise ValueError(
                f"{where}: {event.channel.config!r} is not an optical configuration in "
                f"NIS-Elements; known: {', '.join(self._configurations)}"
            )

        for device, prop, value in event.properties or ():
            if (device, prop) not in PROPERTIES:
                known = "; ".join(f"{d}.{p}: {v}" for (d, p), v in PROPERTIES.items())
                raise ValueError(f"{where}: unsupported property {device}.{prop}; known: {known}")
            if device == "Nosepiece" and _slot(value) not in self._objectives:
                raise ValueError(f"{where}: no objective in nosepiece slot {value}")
            if device == "PFS":
                _on_off(value)

        action = event.action
        uses_pfs = isinstance(action, HardwareAutofocus) or any(
            device == "PFS" for device, _, _ in event.properties or ()
        )
        if uses_pfs and not self._has_pfs:
            raise ValueError(f"{where}: needs a Perfect Focus System, and NIS reports none")
        if isinstance(action, HardwareAutofocus) and action.autofocus_motor_offset is not None:
            raise ValueError(f"{where}: setting a PFS offset is not supported")
        if isinstance(action, CustomAction):
            _check_autofocus_action(where, action)
        elif not isinstance(action, (AcquireImage, HardwareAutofocus)):
            raise ValueError(f"{where}: unsupported action {action!r}")

    def _check_limits(self, where: str, target: dict[str, float]) -> None:
        for axis, value in target.items():
            lo, hi = self._limits[axis]["min"], self._limits[axis]["max"]
            if not lo <= value <= hi:
                raise ValueError(
                    f"{where}: {axis} = {value} um is outside the stage limits [{lo}, {hi}] um"
                )

    def _check_plans(self, sequence: Any) -> None:
        """Refuse Z and grid plans that useq would turn into wrong absolute positions.

        A relative Z plan or grid is laid out around a stage position; without
        one, useq produces bare offsets around 0 um, and an engine would send the
        stage there. A tiling grid also needs the field of view, or useq places
        the tiles 1 um apart. Nested per-position sequences are checked as well.
        """
        top_z = getattr(sequence, "z_plan", None)
        top_grid = getattr(sequence, "grid_plan", None)
        positions = list(getattr(sequence, "stage_positions", None) or ()) or [None]
        for p in positions:
            # classic: Position(sequence=...); v2: a nested sequence with its Position in .value
            sub = p if hasattr(p, "axes") else getattr(p, "sequence", None)
            pos = getattr(p, "value", p)
            z_plan = getattr(sub, "z_plan", None) or top_z
            grid = getattr(sub, "grid_plan", None) or top_grid

            if z_plan is not None and z_plan.is_relative and getattr(pos, "z", None) is None:
                raise ValueError(
                    "the Z plan is relative (a range around each position), but a stage "
                    "position has no z. Give each position a z, or use an absolute Z plan "
                    "such as ZTopBottom."
                )
            if grid is None:
                continue
            if grid.is_relative and None in (getattr(pos, "x", None), getattr(pos, "y", None)):
                raise ValueError(
                    "the grid is relative (tiles around each position), but a stage position "
                    "has no x and y. Give each position x and y, or use GridFromEdges."
                )
            if hasattr(grid, "overlap") and None in (grid.fov_width, grid.fov_height):
                raise ValueError(
                    "the grid needs the field of view to space its tiles: set fov_width and "
                    f"fov_height (um) on the grid plan. {self._field_of_view()}"
                )

    def _field_of_view(self) -> str:
        """One sentence on the current camera field, for error messages."""
        if self._image_shape is None:
            return ""  # nothing measured yet (a check takes no image)
        if self._pixel_size_um is None:
            return "NIS reports no pixel calibration for this objective."
        height, width = self._image_shape
        field = (width * self._pixel_size_um, height * self._pixel_size_um)
        return "The camera field here is {:.1f} x {:.1f} um.".format(*field)


def _where(event: MDAEvent) -> str:
    """The event's place in the sequence, for messages: 'event p=0, z=2'."""
    index = ", ".join(f"{getattr(k, 'value', k)}={v}" for k, v in event.index.items())
    return f"event {index}" if index else "event"


def _slot(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Nosepiece Position must be a slot number (1, 2, ...), not {value!r}"
        ) from None


def _on_off(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("on", "1", "true"):
        return True
    if str(value).lower() in ("off", "0", "false"):
        return False
    raise ValueError(f'PFS State must be "On" or "Off", not {value!r}')


def _check_autofocus_action(where: str, action: CustomAction) -> None:
    usage = 'CustomAction(name="autofocus", data={"range_um": 50, "speed": 30})'
    if action.name != "autofocus" or not set(action.data) <= {"range_um", "speed"}:
        raise ValueError(f"{where}: the only custom action is {usage}")
    try:
        range_um = float(action.data.get("range_um", 50))
        speed = float(action.data.get("speed", 30))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: range_um and speed must be numbers: {usage}") from None
    if range_um <= 0 or not 0 <= speed <= 90:
        raise ValueError(f"{where}: range_um must be positive and speed between 0 and 90")
