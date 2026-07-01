"""
Mock mesoSPIM command server (offline test double).
====================================================
An independent **MIT** re-implementation of the mesoSPIM command-server protocol
(``server/PROTOCOL.md``) for offline testing -- the analog of the Evident
``MockRdkServer``. It holds a little mutable instrument state (5-axis position,
light-path settings, a hardware config) and, for ``acquire``, writes small
synthetic frame files so the driver's capture + save path can be exercised end
to end with NO mesoSPIM software and no hardware.

It is deliberately separate from the GPL ``server/mesospim_command_server.py``:
both implement the same documented protocol, but this double imports nothing GPL
and touches no Qt, so it runs anywhere pytest does.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
from pathlib import Path

import numpy as np
import tifffile

_AXES = ("x", "y", "z", "f", "theta")

_CONFIG = {
    "app": "mesoSPIM-control",
    "version": "1.20.0-mock",
    "lasers": [
        {"name": "405 nm", "wavelength_nm": 405},
        {"name": "488 nm", "wavelength_nm": 488},
        {"name": "561 nm", "wavelength_nm": 561},
        {"name": "647 nm", "wavelength_nm": 647},
    ],
    "filters": ["Empty-Alignment", "515/30", "561/LP", "647-LP"],
    "zooms": [
        {"name": "1x", "pixel_size_um": 6.55},
        {"name": "2x", "pixel_size_um": 3.26},
    ],
    "shutter_configs": ["Left", "Right", "Both"],
    "axes": list(_AXES),
    # Small camera so synthetic frames stay tiny in tests.
    "camera": {"pixels_x": 64, "pixels_y": 64},
}


class MockMesospimServer:
    """One-client-at-a-time fake mesoSPIM command server for tests.

    Args:
        host, port: bind address; ``port=0`` picks a free ephemeral port
            (read ``.port`` after construction).
        output_dir: where synthetic frame files are written; a temp dir by
            default (read ``.output_dir``).
        errors: command names that should reply with a NAK, to exercise the
            client/dispatch error paths.
    """

    def __init__(self, host="127.0.0.1", port=0, *, output_dir=None, errors=None):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self.output_dir = Path(output_dir or tempfile.mkdtemp(prefix="mock_mesospim_"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.errors = set(errors or [])
        self.state = {
            "state": "idle",
            "position": {axis: 0.0 for axis in _AXES},
            "laser": "488 nm",
            "intensity": 10.0,
            "filter": "515/30",
            "zoom": "1x",
            "shutterconfig": "Left",
            "etl_l_amplitude": 1.0,
            "etl_l_offset": 2.0,
            "etl_r_amplitude": 1.0,
            "etl_r_offset": 2.0,
        }
        self._frame_seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> MockMesospimServer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, name="mock-mesospim", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- server loop ---------------------------------------------------------

    def _serve(self) -> None:
        self._sock.settimeout(0.3)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(0.3)
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                raw, _, buf = buf.partition(b"\n")
                reply = self._respond(raw.decode("utf-8", "replace"))
                conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))

    # -- dispatch ------------------------------------------------------------

    def _respond(self, line: str) -> dict:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"bad json: {exc}", "id": None}
        req_id = request.get("id")
        cmd = request.get("cmd")
        args = request.get("args") or {}
        if cmd in self.errors:
            return {"ok": False, "error": f"injected error for {cmd}", "id": req_id}
        try:
            return {"ok": True, "data": self._dispatch(cmd, args), "id": req_id}
        except _Nak as exc:
            return {"ok": False, "error": str(exc), "id": req_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "id": req_id}

    def _dispatch(self, cmd, args):
        if cmd == "hello":
            return {"app": _CONFIG["app"], "version": _CONFIG["version"], "protocol": 1,
                    "state": self.state["state"]}
        if cmd in ("ping", "bye"):
            return {}
        if cmd == "get_state":
            return self._state_snapshot()
        if cmd == "get_position":
            return dict(self.state["position"])
        if cmd == "get_config":
            return dict(_CONFIG)
        if cmd == "get_progress":
            return {"state": self.state["state"], "current_plane": 0, "total_planes": 0,
                    "current_acquisition": 0, "total_acquisitions": 0}
        if cmd == "move_absolute":
            targets = self._axes(args.get("targets"))
            self.state["position"].update(targets)
            return {"position": dict(self.state["position"])}
        if cmd == "move_relative":
            deltas = self._axes(args.get("deltas"))
            for axis, delta in deltas.items():
                self.state["position"][axis] = self.state["position"].get(axis, 0.0) + delta
            return {"position": dict(self.state["position"])}
        if cmd == "zero":
            for axis in args.get("axes") or _AXES:
                if axis in self.state["position"]:
                    self.state["position"][axis] = 0.0
            return {}
        if cmd == "stop":
            return {}
        if cmd == "set_state":
            settings = args.get("settings") or {}
            if not settings:
                raise _Nak("set_state needs 'settings'")
            for key, value in settings.items():
                self.state[key] = value
            return {"applied": dict(settings)}
        if cmd == "acquire":
            acq = args.get("acquisition")
            if not acq:
                raise _Nak("acquire needs 'acquisition'")
            return self._acquire(acq)
        if cmd == "run_acquisition_list":
            acqs = args.get("acquisitions") or []
            if not acqs:
                raise _Nak("run_acquisition_list needs 'acquisitions'")
            files, per = [], []
            for one in acqs:
                data = self._acquire(one)
                files.extend(data["files"])
                per.append(data)
            return {"files": files, "per_acquisition": per}
        if cmd == "procedure":
            name = args.get("name")
            if name in ("autofocus", "find_sample"):
                return {"ran": name, "result": "ok"}
            raise _Nak(f"procedure {name!r} not implemented")
        raise _Nak(f"unknown cmd {cmd!r}")

    # -- helpers -------------------------------------------------------------

    def _state_snapshot(self) -> dict:
        snap = {k: v for k, v in self.state.items() if k != "position"}
        snap["position"] = dict(self.state["position"])
        return snap

    @staticmethod
    def _axes(raw) -> dict:
        out = {}
        for axis, value in (raw or {}).items():
            if axis not in _AXES:
                raise _Nak(f"unknown axis {axis!r}")
            out[axis] = float(value)
        if not out:
            raise _Nak("no axes given")
        return out

    def _acquire(self, acq: dict) -> dict:
        planes = max(1, int(acq.get("planes", 1)))
        px = _CONFIG["camera"]
        files = []
        for _i in range(planes):
            self._frame_seq += 1
            # Deterministic synthetic content: a gradient offset by the frame seq.
            base = np.arange(px["pixels_x"] * px["pixels_y"], dtype=np.uint16)
            frame = (base.reshape(px["pixels_y"], px["pixels_x"]) + self._frame_seq) % 65535
            path = self.output_dir / f"mock_frame_{self._frame_seq:06d}.tiff"
            tifffile.imwrite(str(path), frame.astype(np.uint16))
            files.append(str(path))
        return {"files": files, "planes": planes,
                "pixels": [px["pixels_x"], px["pixels_y"]]}


class _Nak(Exception):
    """A request the mock understood but declined."""
