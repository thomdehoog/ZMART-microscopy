"""
Mock mesoSPIM Remote Scripting server (offline test double).
============================================================
A faithful **MIT** re-implementation of the *restricted-mode* Remote Scripting
bridge for offline testing. Like the real server, it speaks the length-framed
protocol, optionally gates on a token, and -- for each received call -- **decodes
the ``{call, args}`` JSON and dispatches it through the shared allowlist**
(:mod:`mesospim.connection.command_api`) against a Core-shaped fake, sending the
JSON result back. No ``exec``: the server runs only names it recognises.

This exercises the whole path the real server does -- framing, auth, the fixed
dispatch table, and a Core whose method/signal/state surface matches
mesoSPIM-control v1.20.0. Only the live hardware Core is absent.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import traceback
import types
from pathlib import Path

import numpy as np
import tifffile
from mesospim.connection import command_api
from mesospim.protocol import ProtocolError, decode_call, encode_reply

_AXES = ("x", "y", "z", "f", "theta")


# A fake ``utils.acquisitions`` so the acquire handler's
# ``from utils.acquisitions import Acquisition, AcquisitionList`` resolves
# offline (the real ones are GPL mesoSPIM classes).
class _FakeAcquisition(dict):
    """dict subclass whose ``.update`` merges over the mesoSPIM defaults."""

    def __init__(self):
        super().__init__(planes=1, z_step=1.0, folder="", filename="")


class _FakeAcquisitionList(list):
    pass


def _install_fake_acquisitions() -> None:
    if "utils.acquisitions" in sys.modules:
        return
    pkg = sys.modules.setdefault("utils", types.ModuleType("utils"))
    mod = types.ModuleType("utils.acquisitions")
    mod.Acquisition = _FakeAcquisition
    mod.AcquisitionList = _FakeAcquisitionList
    pkg.acquisitions = mod
    sys.modules["utils.acquisitions"] = mod


_install_fake_acquisitions()


# =============================================================================
# A Core-shaped fake: the surface the injected scripts touch (== self).
# =============================================================================


class _FakeSignal:
    """Stand-in for a pyqtSignal: ``emit()`` runs a bound handler."""

    def __init__(self, handler=None):
        self._handler = handler or (lambda *a: None)

    def emit(self, *args):
        self._handler(*args)


class FakeCfg:
    """Matches the mesoSPIM config attributes ``get_config`` reads."""

    laserdict = {"405 nm": "PWM", "488 nm": "PWM", "561 nm": "PWM", "647 nm": "PWM"}
    filterdict = {"Empty-Alignment": 0, "515/30": 1, "561/LP": 2, "647-LP": 3}
    zoomdict = {"1x": 6.55, "2x": 3.26}
    shutteroptions = ("Left", "Right", "Both")
    version = "1.20.0-mock"
    # Small camera so synthetic frames stay tiny in tests.
    camera_x_pixels = 64
    camera_y_pixels = 64


class FakeCore:
    """Duck-typed ``mesoSPIM_Core`` with exactly the surface the scripts use."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = FakeCfg()
        self.state = {
            "state": "idle",
            "position": {f"{a}_pos": 0.0 for a in _AXES},
            "laser": "488 nm",
            "intensity": 10.0,
            "filter": "515/30",
            "zoom": "1x",
            "shutterconfig": "Left",
            "etl_l_amplitude": 1.0,
            "etl_l_offset": 2.0,
            "etl_r_amplitude": 1.0,
            "etl_r_offset": 2.0,
            "snap_image_path": None,
        }
        self.sig_stop_movement = _FakeSignal()
        self.sig_state_request_and_wait_until_done = _FakeSignal(self._apply_state)
        self._seq = 0

    # -- Core API the scripts call ------------------------------------------

    def _apply_state(self, settings):
        self.state.update(settings)

    def move_absolute(self, sdict, wait_until_done=False, use_internal_position=True):
        for key, val in sdict.items():
            self.state["position"][key.replace("_abs", "") + "_pos"] = float(val)

    def move_relative(self, ddict, wait_until_done=False):
        for key, val in ddict.items():
            self.state["position"][key.replace("_rel", "") + "_pos"] += float(val)

    def zero_axes(self, axes):
        for axis in axes:
            self.state["position"][f"{axis}_pos"] = 0.0

    def start(self, row=0):
        """Run the acquisition at ``state['acq_list'][row]``: write ONE stack.

        Mirrors the real Core entry point + default Tiff image writer -- a single
        multi-page TIFF (shape ``(planes, H, W)``, or 2-D for a single plane) at
        the Acquisition's ``folder``/``filename`` -- then returns to idle.
        """
        acq = self.state["acq_list"][row]
        planes = max(1, int(acq.get("planes", 1) or 1))
        folder = acq.get("folder") or str(self.output_dir)
        filename = acq.get("filename") or f"stack_{self._next():06d}.tiff"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)
        w, h = self.cfg.camera_x_pixels, self.cfg.camera_y_pixels
        pages = []
        for _ in range(planes):
            self._seq += 1
            base = np.arange(w * h, dtype=np.uint16).reshape(h, w)
            pages.append(((base + self._seq) % 65535).astype(np.uint16))
        stack = pages[0] if planes == 1 else np.stack(pages)  # (H,W) or (planes,H,W)
        tifffile.imwrite(path, stack, photometric="minisblack")
        self.state["snap_image_path"] = path
        self.state["state"] = "idle"

    def _next(self) -> int:
        self._acq_seq = getattr(self, "_acq_seq", 0) + 1
        return self._acq_seq


# =============================================================================
# The socket server.
# =============================================================================


class MockMesospimServer:
    """One-client-at-a-time fake Remote Scripting server for tests.

    Args:
        host, port: bind address; ``port=0`` picks a free ephemeral port
            (read ``.port`` after construction).
        output_dir: where synthetic frame files are written; a temp dir by default.
        token: if set, the first frame a client sends must be this token.
        errors: call names that should reply with an error instead of running --
            to exercise the client/dispatch failure paths.
    """

    def __init__(self, host="127.0.0.1", port=0, *, output_dir=None, token=None, errors=None):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self.core = FakeCore(output_dir or tempfile.mkdtemp(prefix="mock_mesospim_"))
        self._token = token or None
        self.errors = set(errors or [])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- compatibility accessors --------------------------------------------

    @property
    def state(self) -> dict:
        return self.core.state

    @property
    def output_dir(self) -> Path:
        return self.core.output_dir

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
        import hmac

        conn.settimeout(0.3)
        buf = b""
        authed = self._token is None
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue  # idle wait -- buf is preserved across timeouts
            except OSError:
                return
            if not chunk:
                return  # client disconnected
            buf += chunk
            # Process every complete "<len>\n<payload>" frame currently buffered.
            while b"\n" in buf:
                head, _, rest = buf.partition(b"\n")
                try:
                    length = int(head)
                except ValueError:
                    conn.sendall(_frame("framing error: expected a byte count"))
                    return
                if len(rest) < length:
                    break  # payload not fully arrived yet
                payload = rest[:length].decode("utf-8", "replace")
                buf = rest[length:]
                if not authed:
                    ok = hmac.compare_digest(
                        payload.encode("utf-8"), str(self._token).encode("utf-8")
                    )
                    authed = ok
                    conn.sendall(_frame("OK" if ok else "AUTH-FAILED"))
                    if not ok:
                        return
                else:
                    conn.sendall(_frame(self._run(payload)))

    # -- run a received call -------------------------------------------------

    def _run(self, payload: str) -> str:
        try:
            call, args = decode_call(payload)
        except ProtocolError as exc:
            return f"bad call: {exc}"  # no OK line -> client surfaces it as an error
        if call in self.errors:
            return f"injected error for command {call!r}"
        try:
            result = command_api.run(self.core, call, args)
        except Exception:
            return traceback.format_exc()  # unknown call / handler error -> error reply
        return encode_reply(result)


def _frame(text: str) -> bytes:
    b = text.encode("utf-8")
    return str(len(b)).encode("ascii") + b"\n" + b
