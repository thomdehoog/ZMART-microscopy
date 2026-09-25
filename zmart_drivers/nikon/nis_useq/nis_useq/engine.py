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
  with the PFS. ``CustomAction(name="autofocus", data={"range_um": 50, "speed": 30})``
  runs the NIS image-based focus sweep. A focus action shifts later Z moves at the
  same position by the distance it moved.

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
from useq import AcquireImage, CustomAction, HardwareAutofocus, MDAEvent

from .client import DEFAULT_HOST, DEFAULT_PORT, NisClient, NisConnectionError

log = logging.getLogger("nis_useq")

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
        runner.run(sequence, output="run.ome.zarr")
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 30.0):
        self.client = NisClient(host, port, timeout)
        self._image_info: dict[str, Any] | None = None  # shape, dtype, pixel size of the last image

    def close(self) -> None:
        self.client.close()

    # -- sequence --------------------------------------------------------------

    def setup_sequence(self, sequence: Any) -> dict:
        """Read what the microscope offers, and return summary metadata for writers.

        The first run of an engine snaps one image with the current settings, so
        that file writers know the image size before the first real frame.
        """
        self._limits = self.client.request("get_limits")
        self._configurations = self.client.request("get_optical_configurations")
        self._objectives = [int(p) for p in self.client.request("get_objectives")["objectives"]]
        self._has_pfs = self.client.request("get_pfs")["present"]
        self._channel: str | None = None  # unknown until the first event sets it
        self._exposure_ms: float | None = None  # NIS cannot report it; known once set
        self._z_offset: dict[int | None, float] = {}  # focus found per position index
        self._workdir = Path(tempfile.mkdtemp(prefix="nis_useq_"))
        self._frames = 0
        self._t0 = time.perf_counter()
        if self._image_info is None:
            self._snap()
        info = self._image_info
        height, width = info["shape"][:2]
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
                    "plane_shape": info["shape"],
                    "dtype": info["dtype"],
                    "height": height,
                    "width": width,
                    "pixel_size_um": info["pixel_size_um"],
                },
            ),
            "position": self.client.request("get_position"),
            "config_groups": (),
            "pixel_size_configs": (),
            "mda_sequence": sequence,
        }

    def event_iterator(self, events: Iterable[MDAEvent]) -> Iterator[MDAEvent]:
        """Check the whole plan before anything moves, then hand out the events."""
        _check_relative_z(events)
        events = list(events)
        for event in events:
            self._check(event)
        yield from events

    def teardown_sequence(self, sequence: Any) -> None:
        shutil.rmtree(self._workdir, ignore_errors=True)

    # -- events ----------------------------------------------------------------

    def setup_event(self, event: MDAEvent) -> None:
        """Move the stage, then apply channel, exposure and properties."""
        self._check(event)
        target = {"x": event.x_pos, "y": event.y_pos, "z": event.z_pos}
        if target["z"] is not None:
            target["z"] += self._z_offset.get(event.index.get("p"), 0.0)
        target = {axis: value for axis, value in target.items() if value is not None}
        if target:
            self._check_limits(f"event {dict(event.index)} (with focus correction)", target)
            self.client.request("move", **target)

        if event.channel is not None and event.channel.config != self._channel:
            self.client.request("select_optical_configuration", name=event.channel.config)
            self._channel = event.channel.config
            self._exposure_ms = None  # a configuration can bring its own exposure

        if event.exposure is not None and event.exposure != self._exposure_ms:
            self.client.request("set_exposure", exposure_ms=event.exposure)
            self._exposure_ms = event.exposure

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
                self.client.request("set_pfs", on=False)  # stage moves stay predictable
            return
        if isinstance(action, CustomAction):  # "autofocus", checked in _check
            self._focus(event, "autofocus", **action.data)
            return

        image = self._snap()
        t0 = event.metadata.get("runner_t0", self._t0)  # the pymmcore-plus runner sets this
        yield (
            image,
            event,
            {
                "format": "frame-dict",
                "version": "1.0",
                "pixel_size_um": self._image_info["pixel_size_um"],
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

    def _snap(self) -> np.ndarray:
        """Capture in NIS, read the saved TIFF back, delete it."""
        self._frames += 1
        path = self._workdir / f"frame_{self._frames:06d}.tif"
        info = self.client.request("snap", path=str(path), timeout=SNAP_TIMEOUT_S)
        image = tifffile.imread(path)
        path.unlink()
        self._image_info = {
            "shape": image.shape,
            "dtype": str(image.dtype),
            "pixel_size_um": info["pixel_size_um"],
        }
        return image

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
            raise
        except RuntimeError as exc:
            log.warning("focus failed at %s; continuing without it: %s", dict(event.index), exc)
            return
        if op == "set_pfs" and result["status"] != 1:
            log.warning("PFS did not lock at %s: %s", dict(event.index), result["meaning"])
            return
        after = self.client.request("get_position")["z"]
        p = event.index.get("p")
        self._z_offset[p] = self._z_offset.get(p, 0.0) + after - before

    def _check(self, event: MDAEvent) -> None:
        """Raise ValueError if this engine cannot run the event as written."""
        where = f"event {dict(event.index)}"
        if event.roi is not None or event.slm_image is not None:
            raise ValueError(f"{where}: camera ROI and SLM images are not supported")

        position = {axis: getattr(event, f"{axis}_pos") for axis in ("x", "y", "z")}
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
            if device == "Nosepiece" and int(value) not in self._objectives:
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
            if action.name != "autofocus" or not set(action.data) <= {"range_um", "speed"}:
                raise ValueError(
                    f"{where}: the only custom action is "
                    'CustomAction(name="autofocus", data={"range_um": ..., "speed": ...})'
                )
        elif not isinstance(action, (AcquireImage, HardwareAutofocus)):
            raise ValueError(f"{where}: unsupported action {action!r}")

    def _check_limits(self, where: str, target: dict[str, float]) -> None:
        for axis, value in target.items():
            lo, hi = self._limits[axis]["min"], self._limits[axis]["max"]
            if not lo <= value <= hi:
                raise ValueError(
                    f"{where}: {axis} = {value} um is outside the stage limits [{lo}, {hi}] um"
                )


def _on_off(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("on", "1", "true"):
        return True
    if str(value).lower() in ("off", "0", "false"):
        return False
    raise ValueError(f'PFS State must be "On" or "Off", not {value!r}')


def _check_relative_z(sequence: Any) -> None:
    """Refuse a relative Z plan that has no position Z to be relative to.

    useq then produces bare offsets (for example -2 ... +2 um), and an engine
    would send the focus drive to those absolute values.
    """
    z_plan = getattr(sequence, "z_plan", None)
    if z_plan is None or not z_plan.is_relative:
        return
    positions = list(getattr(sequence, "stage_positions", None) or ())
    # A v2 position can be a nested sequence whose own position is in `.value`.
    zs = [getattr(getattr(p, "value", p), "z", None) for p in positions]
    if not zs or None in zs:
        raise ValueError(
            "the Z plan is relative (a range around each position), but not every stage "
            "position has a z. Give each position a z, or use an absolute Z plan "
            "such as ZTopBottom."
        )
