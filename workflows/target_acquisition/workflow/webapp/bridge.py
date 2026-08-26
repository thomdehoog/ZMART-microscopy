"""The bridge: where the operator window's backend verbs meet the controller.

The operator page runs in a browser and cannot import Python, so its backend
(`webapp-ui/src/workflows/target_acquisition/microscope/live.js`) speaks to
this file over HTTP instead. Every route here is one of the page's backend
verbs; behind each route sits :mod:`zmart_controller`, and behind that
whichever driver is plugged in — the Leica driver on the microscope PC (real
LAS X or its simulator, same driver either way), or the controller's own mock
driver on a development machine with no instrument at all.

Standard library only, on purpose. The microscope computer has no network to
install packages from, and this server is a handful of routes: a framework
would save thirty lines and cost a dependency forever. The pattern is the same
one `_server.py` and `live_overview_demo.py` already use.

The verbs, and what they are made of
------------------------------------

* ``POST /api/connect`` — open the session through the controller. The reply
  carries the driver's own account of itself (``get_info``), which is what the
  window's connection checks show.
* ``GET  /api/setting`` — **a readout, never a procedure.** The instrument's
  current state (``get_state``), shaped into the reading the window records:
  a one-line summary, the detail rows behind it, and the frame size the plan
  is laid with. Recording a preset — the acquisition settings and the
  focussing preset alike — is this, and nothing more: nothing on the
  instrument moves.
* ``POST /api/focus/measure`` — the autofocus procedure, run at each requested
  position: drive there, focus, report the height. This is the one place a
  preset-shaped request *does* something, which is exactly why it is its own
  verb and not part of the readout above.
* ``POST /api/scan`` — start the overview scan in a background thread: drive
  to each position, acquire, report progress. ``GET /api/scan`` reads the
  progress. The window's live picture watches the run's own store, so nothing
  here needs to push pixels at the browser.
* ``POST /api/disconnect`` — close the session.

This bridge deliberately stops at the overview scan. Discovery, refinement and
acquisition of targets are still rehearsed inside the window; their verbs
arrive here when that work starts.

One thread owns the instrument. Every route that touches the session takes
``_the_instruments_turn`` first, so two requests can never move the stage at
once — the scan holds it per position, not for the whole run, so a readout
during a scan waits briefly rather than failing.

Which driver answers is the workflow's choice, made per connect — the page's
mock workflow asks for the controller's mock driver, the real one for the
Leica — so the bridge takes no driver flag: it serves, and connects what it
is asked to connect.

Run it as a plain script — deliberately not as a module of the ``webapp``
package, whose import chain pulls in the notebook stack this server has no
use for::

    python workflows/target_acquisition/workflow/webapp/bridge.py

What the scan does not do yet: write the run's OME-Zarr store. The drive is
real — every position visited, every acquire made — and the store arrives
with the storage integration, at which point the window's live picture fills
in on this path the way it already does on the pretend one.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The repository root, so this file runs the same from a checkout however it
# is started.
_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import zmart_controller  # noqa: E402

# ---------------------------------------------------------------------------
# The session, and the one lock that guards it
# ---------------------------------------------------------------------------

_the_instruments_turn = threading.Lock()

# The open controller session, or None. One session at a time: the window is
# one operator at one instrument.
_session = None

# How the driver was chosen; filled by connect, shown by /api/connect replies.
_context: dict = {}


def _require_session():
    if _session is None:
        raise RuntimeError("no session is open — connect first")
    return _session


# The controller's reference driver: no hardware behind it, registered on
# demand the way its own tests register it.
_MOCK_CONNECTION = {
    "vendor": "mock",
    "microscope": "mock-scope",
    "api": "mock-api",
    "client": "mock-client",
}

# Where the Leica driver lives. Its folder is not a package on the path —
# the example notebook adds it and imports the adapter, and importing IS
# registering: that is the driver's own opt-in.
_LEICA_HOME = _ROOT / "zmart_drivers" / "leica" / "stellaris5_y42h93"


def _leica_connection() -> dict:
    """Register the Leica driver and hand back its own connection identity.

    The identity — vendor, microscope, api, and the driver-specific connect
    parameters — is the adapter's ``CONNECTION``, taken verbatim rather than
    restated here: one owner, so the bridge can never ask for an instrument
    under a name the driver did not give itself. The driver speaks to real
    LAS X or to its simulator without knowing which; nothing here does
    either.
    """
    if str(_LEICA_HOME) not in sys.path:
        sys.path.insert(0, str(_LEICA_HOME))
    from navigator_expert.zmart_adapter import CONNECTION  # importing registers

    return dict(CONNECTION)


def _register_known_drivers() -> None:
    """Put every driver this machine has into the controller's registry.

    The registry is what the page's Microscope list shows — ``get_instruments``
    is the controller's own answer to "what can I connect to" — so the bridge
    registers what it can find at start: the mock always, the Leica when its
    driver imports. A driver that fails to import is simply not offered.
    """
    from zmart_controller.tests.mock_driver import register_mock

    register_mock()
    try:
        _leica_connection()
    except Exception as why:  # noqa: BLE001 — not installed here is a normal state
        print(f"bridge: the Leica driver is not available on this machine ({why})")


def _instruments() -> list:
    return zmart_controller.get_instruments()


def _connect(asked: dict) -> dict:
    """Open the session for one of the registry's entries and answer with the driver's account."""
    global _session, _context
    connection = asked.get("connection")
    if not isinstance(connection, dict):
        raise ValueError(
            "connect needs the instrument's connection entry, as listed by /api/instruments"
        )
    _session = zmart_controller.set_instrument(connection)
    _context = dict(_session.context)
    info = _session.get_info()
    return {"context": _context, "info": info}


def _require_session():
    if _session is None:
        raise RuntimeError("no session is open — connect first")
    return _session


def _disconnect() -> dict:
    global _session
    if _session is not None:
        _session.disconnect()
        _session = None
    return {"closed": True}


# ---------------------------------------------------------------------------
# The readout: a preset is the instrument's state, shaped for the window
# ---------------------------------------------------------------------------

# How wide one camera frame is, in pixels. The mock driver's state does not
# carry a frame size, so the bridge holds the one constant the reading needs;
# the Leica driver's state reports its own and overrides this.
_FALLBACK_FRAME_PX = 512


def _flatten(prefix: str, mapping: dict, rows: list) -> None:
    for key, value in mapping.items():
        label = f"{prefix}{key}".replace("_", " ")
        if isinstance(value, dict) and "unit" not in value:
            _flatten(f"{label} · ", value, rows)
        else:
            rows.append(
                [label, json.dumps(value, default=str) if isinstance(value, dict) else str(value)]
            )


def _optics(observed: dict) -> str:
    """How the light path reads on one line: magnification, aperture, zoom.

    What an operator checks a configuration by, in the order they check it —
    which lens, how much light it collects, and what the scanner is doing on
    top of that. A driver that does not report its optics gets nothing here
    and the caller falls back to naming the instrument, because a line of
    blanks says less than a serial number.
    """
    lens = observed.get("objective") or {}
    said = []
    if lens.get("magnification"):
        said.append(f"{lens['magnification']:g}x")
    if lens.get("numerical_aperture"):
        na = f"{lens['numerical_aperture']:g} NA"
        if lens.get("immersion"):
            na = f"{na} {lens['immersion']}"
        said.append(na)
    if observed.get("zoom"):
        said.append(f"zoom {observed['zoom']:g}")
    return " · ".join(said)


def _reading(kind: str) -> dict:
    """The instrument's state, now, as the reading the window records.

    ``kind`` is which slot is asking — ``acquisition`` or ``autofocus`` — and
    changes only the labelling: the readout underneath is the same
    ``get_state`` either way, because a preset is a readout and never a
    procedure.
    """
    session = _require_session()
    state = session.get_state()
    observed = state.get("observed", {})
    pixel = observed.get("pixel_size", {})
    pixel_um = float(pixel.get("x", 1.0))
    frame_um = round(_FALLBACK_FRAME_PX * pixel_um)

    rows: list = []
    _flatten("", state.get("changeable", {}), rows)
    _flatten("", observed, rows)

    summary = _optics(observed) or observed.get(
        "serial", _context.get("microscope", "instrument")
    )
    summary = f"{summary} · {pixel_um:g} µm/px"
    reading = {"summary": summary, "detail": rows, "frameUm": frame_um}
    if kind == "autofocus":
        # The stand does not say which family its autofocus is; software is
        # the safe default and the Leica driver's state will name its own.
        reading["kind"] = "software"
        reading["summary"] = f"Software · {summary}"
    return reading


# ---------------------------------------------------------------------------
# The focus map: drive, focus, report — the one procedure in this file
# ---------------------------------------------------------------------------


def _measure_focus(asked: dict) -> dict:
    """Drive to each point, run the autofocus procedure, report the height."""
    session = _require_session()
    measured = []
    for point in asked.get("points", []):
        session.set_xyz(float(point["x"]), float(point["y"]), 0.0)
        answer = session.run_procedure({"procedure": "autofocus"})
        z = answer.get("z", answer.get("position", {}).get("z", 0.0))
        measured.append({**point, "zAuto": z, "z": z})
    return {"points": measured}


# ---------------------------------------------------------------------------
# The scan: a background thread drives the stage; the window watches the run
# ---------------------------------------------------------------------------

_scan = {"running": False, "done": 0, "of": 0, "error": None}


def _scan_worker(positions: list) -> None:
    try:
        for i, position in enumerate(positions):
            with _the_instruments_turn:
                session = _require_session()
                session.set_xyz(
                    float(position["x"]), float(position["y"]), float(position.get("z", 0.0))
                )
                session.acquire(acquisition_type="overview", position_label=f"pos_{i:05d}")
            _scan["done"] = i + 1
    except Exception as why:  # noqa: BLE001 — the window shows the sentence
        _scan["error"] = str(why)
    finally:
        _scan["running"] = False


def _start_scan(asked: dict) -> dict:
    if _scan["running"]:
        raise RuntimeError("a scan is already running")
    positions = asked.get("positions", [])
    _scan.update(running=True, done=0, of=len(positions), error=None)
    threading.Thread(target=_scan_worker, args=(positions,), daemon=True).start()
    return dict(_scan)


# ---------------------------------------------------------------------------
# The HTTP shell: routes in, JSON out, errors as sentences
# ---------------------------------------------------------------------------


class _Bridge(BaseHTTPRequestHandler):
    def _answer(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The page may be served by the dev server on another port while this
        # is being developed; on the microscope one server serves both and
        # this header is redundant but harmless.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, why: Exception) -> None:
        kind = 400 if isinstance(why, (ValueError, KeyError)) else 500
        self._answer({"error": str(why)}, status=kind)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:  # noqa: N802 — http.server's naming
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 — http.server's naming
        path, _, query = self.path.partition("?")
        try:
            if path == "/api/setting":
                kind = dict(pair.split("=") for pair in query.split("&") if pair).get(
                    "type", "acquisition"
                )
                with _the_instruments_turn:
                    self._answer(_reading(kind))
            elif path == "/api/instruments":
                self._answer({"instruments": _instruments()})
            elif path == "/api/info":
                # The driver's account of the session: its connection checks
                # (polled while they answer), the canvas, the setup.
                with _the_instruments_turn:
                    self._answer(_require_session().get_info())
            elif path == "/api/xyz":
                with _the_instruments_turn:
                    self._answer(_require_session().get_xyz())
            elif path == "/api/scan":
                self._answer(dict(_scan))
            else:
                self._answer({"error": f"no route {path}"}, status=404)
        except Exception as why:  # noqa: BLE001
            self._fail(why)

    def do_POST(self) -> None:  # noqa: N802 — http.server's naming
        try:
            asked = self._body()
            if self.path == "/api/connect":
                with _the_instruments_turn:
                    self._answer(_connect(asked))
            elif self.path == "/api/disconnect":
                with _the_instruments_turn:
                    self._answer(_disconnect())
            elif self.path == "/api/focus/measure":
                with _the_instruments_turn:
                    self._answer(_measure_focus(asked))
            elif self.path == "/api/scan":
                self._answer(_start_scan(asked))
            else:
                self._answer({"error": f"no route {self.path}"}, status=404)
        except Exception as why:  # noqa: BLE001
            self._fail(why)

    def log_message(self, *_args) -> None:
        """Quiet: the terminal is the operator's too."""


def serve(port: int = 8600) -> ThreadingHTTPServer:
    _register_known_drivers()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Bridge)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Bridge)
    print(f"bridge listening on 127.0.0.1:{args.port}")
    server.serve_forever()
