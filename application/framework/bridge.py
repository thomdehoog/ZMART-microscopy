"""The bridge: where the operator window's backend verbs meet the controller.

The operator page runs in a browser and cannot import Python, so its backend
(`application/parts/microscope/live.js`) speaks to
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
* ``GET  /api/xyz`` — where the stage is (``get_xyz``), and
  ``POST /api/xyz`` — drive it there (``set_xyz``), answering with where it
  ended up. One noun, the method saying which of the controller's two verbs is
  meant. The page's backend calls them ``get_xyz`` and ``set_xyz`` too — the
  controller's own names, carried through the browser unchanged, because a
  verb that is spelled one way here and another way there is a verb somebody
  will eventually wire to the wrong one. A driven stage is a procedure and not
  a readout, which is why it is a POST and why nothing else on this route
  moves anything.
* ``GET  /api/acquisition_options`` — what the instrument offers for a capture
  and what is chosen now (``get_acquisition_options``), in the driver's own
  words. A readout: asking changes nothing.
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
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import zmart_controller  # noqa: E402
from application.parts.microscope.focus_run import (  # noqa: E402
    measure_focus,
)

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
    from zmart_drivers.mock.mock_driver import register_mock

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
#: What a frame is assumed to be across when the instrument says nothing about
#: it. A guess, and named as one: it is here only so the page has a frame to
#: draw a plan with, not because 512 px is true of anything.
_A_GUESSED_FORMAT_PX = 512


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

    What an operator checks a configuration by: which lens, and how much light
    it collects. The scanner's zoom was here too and came off again — it is one
    more number on a line that is read at a glance, and the objective and the
    pixel size already say what the picture will be. A driver that does not
    report its optics gets nothing here
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
    return " · ".join(said)


def _a_number(value) -> float | None:
    """A positive, finite number, or nothing. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 and value == value and value != float("inf") else None


def _format_across(observed: dict) -> float | None:
    """How many pixels wide a frame is, however the driver says it.

    ``"2048 x 2048"`` is LAS X's own wording, straight out of the job's
    ``format``; a pair of numbers is what a driver reports when it has already
    parsed that. Only the first figure is read — a plan is laid in square
    frames, and a non-square one would need the whole page to grow a second
    dimension before it could be honoured rather than silently halved.
    """
    said = observed.get("format")
    if isinstance(said, str) and "x" in said.lower():
        first = said.lower().split("x")[0].strip()
        try:
            return _a_number(float(first))
        except ValueError:
            return None
    if isinstance(said, dict):
        return _a_number(said.get("x"))
    if isinstance(said, (list, tuple)) and said:
        return _a_number(said[0])
    return _a_number(observed.get("pixels_x"))


def _frame_across(observed: dict, pixel_um: float) -> int:
    """How wide one frame is on the sample, in micrometres.

    Three ways of knowing, in the order they are worth believing.

    **What the instrument measured.** ``frame_size``, shaped like
    ``pixel_size``: LAS X reports ``imageSize`` and the driver parses it. That
    is the field of view itself, and nothing derived from it can be more true.

    **The format and the pixel size.** Failing a field of view, how many pixels
    across times how much sample each covers. This is why the format has to
    reach here at all: it changes — an operator switching a job from 512 to
    2048 changes the ground one frame covers by a factor of four, and a plan
    laid at the old frame would tile the sample with holes or overlaps nobody
    asked for.

    **A guess**, when the instrument says neither, so that the page still has
    something to draw a plan with. It is the last resort and reads like one.
    """
    reported = observed.get("frame_size")
    if isinstance(reported, dict):
        said = _a_number(reported.get("x"))
        if said is not None:
            return round(said)
    across = _format_across(observed)
    return round((across if across is not None else _A_GUESSED_FORMAT_PX) * pixel_um)


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
    frame_um = _frame_across(observed, pixel_um)

    rows: list = []
    _flatten("", state.get("changeable", {}), rows)
    _flatten("", observed, rows)

    summary = _optics(observed) or observed.get(
        "serial", _context.get("microscope", "instrument")
    )
    # The frame, not the pixel size: a collapsed configuration is read to
    # answer "how much ground does one press get me", and a pixel size answers
    # that only once multiplied by a format the line does not carry.
    summary = f"{summary} · {frame_um} × {frame_um} µm"
    reading = {"summary": summary, "detail": rows, "frameUm": frame_um}
    if kind == "autofocus":
        # The stand does not say which family its autofocus is; software is
        # the safe default and the Leica driver's state will name its own.
        reading["kind"] = "software"
        reading["summary"] = f"Software · {summary}"
    return reading


def _acquisition_options() -> dict:
    """What the instrument offers for a capture, and what is chosen now.

    The driver's own menu, forwarded untouched: ``{name: {options, active}}``,
    where which settings exist at all is the driver's business. Nothing here
    renames or filters it, because the same shape goes back to ``acquire`` at
    capture time — a page that reworded it would have to word it back.
    """
    return _require_session().get_acquisition_options()


# ---------------------------------------------------------------------------
# Driving the stage on the operator's own say-so
# ---------------------------------------------------------------------------


def _drive_to(asked: dict) -> dict:
    """Drive the stage where the operator asked, and answer with where it is.

    ``set_xyz`` is synchronous and confirmed — the driver moves, checks, and
    raises if it could not — so by the time this returns the stage is standing
    there. That is what lets the page move the mark the moment the answer lands
    instead of waiting for the watch's next turn of the clock.

    Its answer is what says where, rather than a fresh ``get_xyz``. Reading the
    stage again would be a second trip to the instrument for something it has
    just told us, and on this microscope a position read is the call that hangs
    — it is why the driver has log-reading alternatives at all. A driver that
    reports no position is asked, because some may not.

    Reshaped into the one form the page knows, which is ``get_xyz``'s: the
    drive and the watch put the mark in the same place through the same field
    names, and neither has to know which of the two it came from.

    ``z`` is optional and left where it stands when it is not given: an
    operator driving to a place on the plate is asking to move across it, not
    to change how far the objective is from it.
    """
    session = _require_session()
    standing = session.get_xyz()
    here = lambda axis: float(standing.get(axis, {}).get("value", 0.0))  # noqa: E731
    went = session.set_xyz(
        float(asked.get("x", here("x"))),
        float(asked.get("y", here("y"))),
        float(asked["z"]) if asked.get("z") is not None else here("z"),
    )
    arrived = (went or {}).get("position")
    if not arrived:
        return session.get_xyz()
    return {
        axis: {"value": float(arrived[axis]), "unit": "um"}
        for axis in ("x", "y", "z")
        if axis in arrived
    }


# ---------------------------------------------------------------------------
# The focus map: drive, focus, report — the one procedure in this file
# ---------------------------------------------------------------------------


def _measure_focus(asked: dict) -> dict:
    """Drive to each point, focus there, and report the height found.

    The loop itself is :func:`~application.parts.microscope.focus_run.measure_focus`,
    which the workflow's step 4 runs too. This is the translation either side of
    it and nothing more.

    The page calls a point's search centre ``startZ`` — where the objective is
    driven before the instrument sweeps around it — and that is the whole of
    what Rerun and Refine differ by: run again and every search centres on the
    height the objective is standing at; refine and each centres on what the
    map already predicts there. The same focussing configuration does the
    sweeping either way, and the stack it takes is the instrument's business.

    Answered point by point, each carrying what it was asked with, because the
    page matches them up by position and draws what it gets back.
    """
    session = _require_session()
    measured = measure_focus(
        session,
        [
            {"x": float(point["x"]), "y": float(point["y"]),
             **({"z": float(point["startZ"])}
                if isinstance(point.get("startZ"), (int, float)) else {})}
            for point in asked.get("points", [])
        ],
    )
    return {
        "points": [
            {**point, "zAuto": found["z_um"], "z": found["z_um"],
             "lost": found["z_um"] is None}
            for point, found in zip(asked.get("points", []), measured)
        ]
    }


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
            elif path == "/api/acquisition_options":
                with _the_instruments_turn:
                    self._answer(_acquisition_options())
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
            elif self.path == "/api/xyz":
                with _the_instruments_turn:
                    self._answer(_drive_to(asked))
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
