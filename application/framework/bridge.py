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
* ``POST /api/state`` — change settings on the instrument (``set_state``),
  answering with what the driver says it applied. The body is the settings
  themselves; the bridge puts them in ``changeable``, which is where the
  contract says a client's instructions go.
* ``POST /api/acquire`` — capture once where the stage is standing
  (``acquire``), answering with the driver's record: what it wrote, and where.
  The one place a client learns the paths of the files a run made.
* ``POST /api/focus/measure`` — the autofocus procedure, run at each requested
  position: drive there, focus, report the height. This is the one place a
  preset-shaped request *does* something, which is exactly why it is its own
  verb and not part of the readout above.
* ``POST /api/scan`` — start the overview scan in a background thread: drive
  to each position, acquire, report progress. ``GET /api/scan`` reads the
  progress. The window's live picture watches the run's own store, so nothing
  here needs to push pixels at the browser.
* ``POST /api/scan/stop`` and ``POST /api/focus/measure/stop`` — the
  operator's Interrupt: ask the run to stop between two fields. What was
  captured stands; the answer is the run as it stood, ``stopped`` set once
  the worker has honoured it.
* ``POST /api/targets/discover`` — find the targets in the overview's fields,
  all of them or the ones named, through the warm analysis; ``GET`` reads the
  progress, each field's targets appended as they are found.
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
from application.parts.storage.output import (  # noqa: E402
    move_record_images,
    position_label,
    prepare_acquisition,
    prepare_experiment,
)
from application.parts.analysis import warm  # noqa: E402
from application.parts.microscope import detection, focus_score  # noqa: E402
from application.parts.microscope.focus_run import (  # noqa: E402
    FOCUSSING,
    RunCancelled,
    apply_state_settled,
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


#: Where ``npm run build`` leaves the page, beside the window that shows it.
THE_PAGE = Path(__file__).resolve().parent / "window" / "static"

#: What a run made through this page is called. One name for the workflow, so
#: two runs are told apart by their hash and not by what somebody typed.
EXPERIMENT = "target-acquisition"

#: This session's run folder: ``<output root>/target-acquisition_<hash6>``,
#: made at connect. Everything a session captures goes under it, which is what
#: makes one run a run -- without it every scan piles into the same folder and
#: the second is indistinguishable from the first.
_run: Path | None = None

#: Where runs go, when this bridge was started with somewhere to put them.
#: A driver that discovers its own (the Leica finds the root beside LAS X)
#: needs none of this; one that cannot has to be told, and the page has
#: nowhere to say it -- it connects with the entry the registry listed.
_output_root: str | None = None


def _connect(asked: dict) -> dict:
    """Open the session for one of the registry's entries and answer with the driver's account."""
    global _session, _context
    connection = asked.get("connection")
    if not isinstance(connection, dict):
        raise ValueError(
            "connect needs the instrument's connection entry, as listed by /api/instruments"
        )
    if _output_root is not None:
        connection = {**connection, "output_root": _output_root}
    global _run
    _session = zmart_controller.set_instrument(connection)
    _context = dict(_session.context)
    info = _session.get_info()
    _run = prepare_experiment(info["output_root"], EXPERIMENT)
    # A fresh session has scanned nothing. The bridge outlives the page, and
    # records carried over from the last session rebuilt its scan's pictures
    # into this run's view -- a just-connected canvas showed a scan nobody
    # had taken.
    _records.clear()
    _view_built.clear()
    _scan.update(running=False, done=0, of=0, error=None, acquisition_type=None)
    _focus.update(running=False, done=0, of=0, error=None, points=[])
    _targets.update(running=False, done=0, of=0, error=None, fields=[])
    return {"context": _context, "info": info, "run": str(_run)}


def _disconnect() -> dict:
    global _session, _run
    if _session is not None:
        _session.disconnect()
        _session = None
    _run = None
    # The workers outlive a focus map on purpose, but not the session: a
    # disconnected page is not about to measure anything.
    warm.close()
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
    lens = observed.get("objective") or observed.get("active_objective") or {}
    said = []
    if lens.get("name"):
        # The Leica names its lens outright, and the name is what identifies
        # it on the shelf; magnification and aperture only qualify it.
        said.append(str(lens["name"]))
    elif lens.get("magnification"):
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
    # `or {}`, not a default: the Leica reports pixel_size as None when the
    # job's geometry fails to parse, and the default never fires on None.
    pixel = observed.get("pixel_size") or {}
    pixel_um = float(pixel.get("x", 1.0))
    frame_um = _frame_across(observed, pixel_um)

    rows: list = []
    _flatten("", state.get("changeable", {}), rows)
    _flatten("", observed, rows)

    summary = (_optics(observed) or observed.get("serial")
               or observed.get("serial_number")
               or _context.get("microscope", "instrument"))
    # The frame, not the pixel size: a collapsed configuration is read to
    # answer "how much ground does one press get me", and a pixel size answers
    # that only once multiplied by a format the line does not carry.
    summary = f"{summary} · {frame_um} × {frame_um} µm"
    reading = {
        "summary": summary, "detail": rows, "frameUm": frame_um,
        # The reapplicable half, kept with the reading: a recording is the
        # instrument's changeable state, and the step that recorded it hands
        # it back when it runs. Without this the recordings were readouts
        # that configured nothing.
        "changeable": state.get("changeable", {}),
    }
    if kind == "autofocus":
        # The stand does not say which family its autofocus is; software is
        # the safe default and the Leica driver's state will name its own.
        # Said in ``kind`` and not in the summary: the row is for the numbers
        # an operator checks, and the family led it as a word nobody asked for.
        reading["kind"] = "software"
    return reading


def _apply_state(asked: dict) -> dict:
    """Change settings on the instrument, and answer with what stuck.

    The page names only the settings it is changing; ``changeable`` is where
    the contract says they go, and the page has no business sending an
    ``observed`` half — that is the driver's report about itself, never an
    instruction. What comes back is the driver's own account of what it
    applied, which is not always what was asked: a value it will not take is
    the driver's to refuse.

    Which settings exist here is the driver's business, as it is for the menu.
    On the Leica it is the LAS X job; on another instrument it is whatever
    that instrument lets a client change.

    Nothing on the operator page calls this, and that is a decision rather
    than an omission. A control for choosing a job would be a control named
    after one vendor's noun: ``job`` is what LAS X calls a stored recipe, and
    another instrument has a protocol, an experiment, or nothing shaped like
    one — so the page would have learned one microscope. It reads what it is
    told and leaves the choosing to the software that authors the recipes,
    where what each one carries can be seen.

    The verb is here because the seam mirrors the controller's surface, not
    this one page's needs. The next client may set what this one only reads.
    """
    return _require_session().set_state({"changeable": dict(asked)})


def _capture(asked: dict) -> dict:
    """Capture once where the stage is standing, and answer with the record.

    The record is the half nothing else can reconstruct. Where a run will land
    is in ``get_info``; what one capture wrote is known only to the capture —
    the driver names its own files, and one acquisition is one file per plane.
    So it is answered whole rather than picked over.

    ``options`` go through as they came from ``get_acquisition_options``.
    Whatever is left out the driver fills from its own actives, which is why
    nothing here invents a default.
    """
    session = _require_session()
    return session.acquire(
        acquisition_type=str(asked["acquisition_type"]),
        position_label=str(asked["position_label"]),
        options=asked.get("options"),
    )


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


def _score_a_stack():
    """How a captured stack becomes a height and a curve.

    Through the warm analysis, which is shared with every other step that
    measures pixels and outlives any one focus map. See
    :mod:`application.parts.analysis.warm`.
    """
    return focus_score.through(warm.the_analysis())


def _measure_focus(asked: dict) -> dict:
    """Drive to each point, capture a stack there, and report what was found.

    The loop itself is :func:`~application.parts.microscope.focus_run.measure_focus`,
    which the workflow's step 4 runs too. This is the translation either side of
    it and nothing more.

    The page calls a point's search centre ``startZ`` — where the objective is
    driven before the stack is taken around it — and that is the whole of what
    Rerun and Refine differ by: run again and every stack centres on the height
    the objective is standing at; refine and each centres on what the map
    already predicts there. The same focussing settings decide the range and
    the step either way.

    Every point comes back with its curves as well as its height, because a
    height alone cannot be argued with: the plot is how the routine shows its
    work, and it is what lets an operator see that a peak was a speck of dust.

    Answered point by point, each carrying what it was asked with, because the
    page matches them up by position and draws what it gets back.
    """
    if _focus["running"]:
        raise RuntimeError("a focus map is already being measured")
    asked_points = asked.get("points", [])
    _stop_asked["focus"] = False
    _focus.update(
        running=True, done=0, of=len(asked_points), error=None, stopped=False,
        points=[],
    )
    threading.Thread(
        target=_focus_worker, args=(asked_points, asked.get("state")), daemon=True
    ).start()
    return dict(_focus)


def _stop_focus() -> dict:
    """The operator's Interrupt: ask the focus run to stop between two points.

    The flag is all this does; the loop reads it before each drive, so the
    point being measured completes and is kept. Idempotent, and harmless
    when nothing runs.
    """
    _stop_asked["focus"] = True
    return dict(_focus)


#: The focus map under way, polled by the page the way the scan is. Each
#: point is added the moment it is measured, so the window can show a height
#: while the stage is still working through the rest.
_focus = {
    "running": False, "done": 0, "of": 0, "error": None, "stopped": False,
    "points": [],
}

#: The operator's hand on the brake, one per procedure. Set by the stop
#: routes, read by the workers between two fields — never mid-capture: the
#: capture in flight completes and is kept, because a field interrupted
#: halfway is a file nobody can account for.
_stop_asked = {"scan": False, "focus": False}


def _focus_worker(asked: list, state: dict | None = None) -> None:
    def landed(index: int, found: dict) -> None:
        # `startZ` said where to begin this search; echoing it back would have
        # the next run silently begin where this one did.
        point = {key: value for key, value in asked[index].items() if key != "startZ"}
        _focus["points"].append({
            **point, "zAuto": found["z_um"], "z": found["z_um"],
            "lost": found["z_um"] is None, "traces": found["traces"],
            "slices": _the_slice_copies_of(found.get("planes") or []),
        })
        _focus["done"] = index + 1

    try:
        with _the_instruments_turn:
            measure_focus(
                _require_session(),
                [
                    {"x": float(point["x"]), "y": float(point["y"]),
                     **({"z": float(point["startZ"])}
                        if isinstance(point.get("startZ"), (int, float)) else {})}
                    for point in asked
                ],
                score=_score_a_stack(),
                state=state,
                output_root=_the_run(),
                on_point=lambda m, _n=[0]: (landed(_n[0], m), _n.__setitem__(0, _n[0] + 1)),
                cancel=lambda: _stop_asked["focus"],
            )
    except RunCancelled:
        # The operator's own hand, not a failure: the points measured so far
        # stand, and the row of the one not taken says nothing at all.
        _focus["stopped"] = True
    except Exception as why:  # noqa: BLE001 — the window shows the sentence
        _focus["error"] = str(why)
    finally:
        _focus["running"] = False


# ---------------------------------------------------------------------------
# The scan: a background thread drives the stage; the window watches the run
# ---------------------------------------------------------------------------

_scan = {
    "running": False, "done": 0, "of": 0, "error": None, "stopped": False,
    "acquisition_type": None,
}

#: What every scan captured, by the kind of scan. The overview's records are
#: what discovery reads and what its pictures are made from, and a targets
#: scan taken afterwards must not replace them -- it did, when there was one
#: list, and the overview's view filled with the targets' pictures.
_records: dict[str, list] = {}


def _scan_worker(
    positions: list, acquisition_type: str = "overview", state: dict | None = None
) -> None:
    """Drive to each position, capture, and keep what came back.

    The records are kept because nothing else can reconstruct them: where a
    run lands is knowable in advance, what each capture wrote is not. They
    were dropped on the floor here, so a run could be caused and never
    accounted for.
    """
    standing = None
    try:
        if state:
            # The recorded configuration for this kind of scan, applied once
            # before the first drive and CONFIRMED to have taken -- recording
            # it and never applying it captured everything with whatever job
            # happened to be selected, and applying without waiting let the
            # first field fire on the job the step before left behind.
            with _the_instruments_turn:
                apply_state_settled(_require_session(), state)
        for i, position in enumerate(positions):
            if _stop_asked["scan"]:
                # Between two fields, on the operator's say-so: what was
                # captured stands, and no further stage move is made.
                _scan["stopped"] = True
                break
            with _the_instruments_turn:
                session = _require_session()
                z = position.get("z")
                if z is None:
                    # A position that names no height means "image where the
                    # objective stands", read once. It defaulted to 0.0 -- an
                    # absolute drive to the frame's z-zero for every field of
                    # every scan, while the panel above reported a measured
                    # focus map.
                    if standing is None:
                        standing = float(session.get_xyz()["z"]["value"])
                    z = standing
                session.set_xyz(float(position["x"]), float(position["y"]), float(z))
                record = session.acquire(
                    acquisition_type=acquisition_type,
                    position_label=_label_for(i, position),
                )
                move_record_images(
                    record, prepare_acquisition(_the_run(), acquisition_type).data
                )
            _records.setdefault(acquisition_type, []).append(record)
            _scan["done"] = i + 1
    except Exception as why:  # noqa: BLE001 — the window shows the sentence
        _scan["error"] = str(why)
    finally:
        _scan["running"] = False


#: Where a scan's display copies go: beside ``data``, under the acquisition
#: type. They are made *from* the pixels rather than being pixels, which is
#: what puts them next to ``data`` instead of inside it.
VIEW = "view"


def view_of(acquisition_type: str) -> Path:
    """Where this kind of scan's pictures are, in this run's own folder."""
    return _the_run() / acquisition_type / VIEW


def _the_run() -> Path:
    """This session's run folder, or a refusal that says what to do."""
    if _run is None:
        raise RuntimeError("no run is open — connect first")
    return _run


#: One view-builder at a time, and only when the scan has grown: every file
#: request used to rebuild the whole view, and two rebuilding at once
#: interleaved their writes into a corrupt note that failed every request
#: after it.
_view_lock = threading.Lock()
_view_built: dict[str, int] = {}


def _the_slice_copies_of(planes: list) -> list:
    """Small copies of one focus stack, one per height, for the panel's eye.

    Made as the point lands -- on the worker's time, never a request's -- and
    named to the page without their folder: where pictures are fetched from
    stays ``viewOf``'s answer. A stack that cannot be copied (a driver whose
    files are not canonical planes) costs the preview and never the run.
    """
    from viz_studio.backend.jpeg_tiles import make_slice_copies  # noqa: PLC0415

    try:
        return make_slice_copies(view_of(FOCUSSING) , planes)
    except Exception as why:  # noqa: BLE001 -- the preview is optional, the height is not
        import logging

        logging.getLogger(__name__).warning("no slice copies for a focus point: %s", why)
        return []


def _the_view_of(acquisition_type: str) -> Path | None:
    """Ask the viewer to bring this scan's pictures up to date, and say where.

    Every field the run captured, the files it left behind, and where on the
    sample it was taken -- all read off the records, because the acquisition is
    what says where it was. What a display copy is, and how one is made, is the
    viewer's own business.

    The records are copied at the door: a field that lands while a build runs
    is not in the snapshot and must not be signed for -- counting the live
    list once marked a run's last stride built without building it.
    """
    from viz_studio.backend.jpeg_tiles import make_what_is_missing  # noqa: PLC0415

    with _view_lock:
        records = list(_records.get(acquisition_type, []))
        note = view_of(acquisition_type) / "tiles.json"
        if _view_built.get(acquisition_type) == len(records) and note.is_file():
            return note if records else None
        made = make_what_is_missing(view_of(acquisition_type), {
            record["position_label"]: (record["images"], _the_middle_of(record))
            for record in records
        })
        _view_built[acquisition_type] = len(records)
        return made


def _the_middle_of(record: dict) -> tuple:
    """Where on the sample a capture was taken, from what it reported.

    Every plane of one capture is at the same place, so the first is enough.
    """
    first = record["planes"][0]
    return float(first["x_um"]), float(first["y_um"])


def _label_for(index: int, position: dict) -> str:
    """Where on the sample this capture is, in the workflow's own label.

    It was a running index, ``pos_00000``, which names nothing: a file called
    that cannot be traced back to a well. The caller says which compartment
    and which group a position belongs to — it drew them — and what it leaves
    out is zero, which is honest about not knowing rather than invented.
    """
    return position_label(
        index,
        carrier=int(position.get("carrier", 0)),
        compartment=int(position.get("compartment", 0)),
        group=int(position.get("group", 0)),
        view=int(position.get("view", 0)),
    )


def _start_scan(asked: dict) -> dict:
    if _scan["running"]:
        raise RuntimeError("a scan is already running")
    positions = asked.get("positions", [])
    acquisition_type = str(asked.get("acquisition_type", "overview"))
    _records[acquisition_type] = []
    _stop_asked["scan"] = False
    _scan.update(
        running=True, done=0, of=len(positions), error=None, stopped=False,
        acquisition_type=acquisition_type,
    )
    threading.Thread(
        target=_scan_worker, args=(positions, acquisition_type, asked.get("state")), daemon=True
    ).start()
    return _the_scan()


def _stop_scan() -> dict:
    """The operator's Interrupt: ask the scan to stop between two fields.

    The flag is all this does; the worker reads it before each drive, so the
    field being captured completes and is kept. Idempotent, and harmless
    when nothing runs.
    """
    _stop_asked["scan"] = True
    return _the_scan()


def _the_scan() -> dict:
    """The scan under way or last finished, with what it has captured so far."""
    return {**_scan, "records": _records.get(_scan["acquisition_type"], [])}


# ---------------------------------------------------------------------------
# The targets: detection over the overview's fields, watched like the scan
# ---------------------------------------------------------------------------

#: Discovery under way, polled by the page the way the scan is. Each field is
#: appended as its targets are found, so the page can draw them while the
#: rest of the overview is still being looked at.
_targets = {"running": False, "done": 0, "of": 0, "error": None, "fields": []}


def _find_targets():
    """The finder for this session: detection through the warm analysis, in
    the pixels the instrument reports. Built when discovery starts rather than
    at import, so the bridge loads with no analysis installed."""
    with _the_instruments_turn:
        observed = _require_session().get_state().get("observed", {})
    pixel_um = float((observed.get("pixel_size") or {}).get("x", 1.0))
    return detection.through(warm.the_analysis(), pixel_um=pixel_um)


def _discover_targets(asked: dict) -> dict:
    """Start detection over the overview: every field, or only the ones named.

    ``fields`` names the overview's fields by index -- one, to try settings on
    before the whole sample is run -- and left out means all of them.
    """
    if _targets["running"]:
        raise RuntimeError("targets are already being discovered")
    records = _records.get("overview", [])
    if not records:
        raise RuntimeError("no overview has been scanned, so there is nothing to find targets in")
    chosen = asked.get("fields")
    fields = list(range(len(records))) if chosen is None else [int(field) for field in chosen]
    _targets.update(running=True, done=0, of=len(fields), error=None, fields=[])
    threading.Thread(
        target=_targets_worker, args=(fields, dict(asked.get("settings") or {})), daemon=True
    ).start()
    return dict(_targets)


def _targets_worker(fields: list, settings: dict) -> None:
    try:
        find = _find_targets()
        for field in fields:
            record = _records["overview"][field]
            cells = find(record, field, settings)
            _keep_targets(cells, record)
            _targets["fields"].append({
                "field": field, "position_label": record["position_label"], "cells": cells,
            })
            _targets["done"] += 1
    except Exception as why:  # noqa: BLE001 -- the window shows the sentence
        _targets["error"] = str(why)
    finally:
        _targets["running"] = False


def _keep_targets(cells: list, record: dict) -> None:
    """Write what was found beside the field it was found in.

    ``<acquisition>/analysis``, next to the ``data`` the objects came from, the
    way a focus curve is kept: without this the only copy is on the operator's
    screen, and it goes when the window does.
    """
    where = _the_run() / record["acquisition_type"] / "analysis"
    where.mkdir(parents=True, exist_ok=True)
    name = (
        f"{record['acquisition_type']}_{record['acquisition_hash']}_"
        f"{record['position_label']}_T000000_targets.json"
    )
    (where / name).write_text(json.dumps(cells, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# The HTTP shell: routes in, JSON out, errors as sentences
# ---------------------------------------------------------------------------


class _Bridge(BaseHTTPRequestHandler):
    # Keep the connection: HTTP/1.0 opened a fresh TCP connection per
    # picture, which is 34 measured milliseconds a tile and seventy seconds
    # for a 2061-field overview. Every response carries its Content-Length,
    # which is what keep-alive requires.
    protocol_version = "HTTP/1.1"

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

    #: What the built page is made of, and what to call each piece when sent.
    #: A browser will not start a background program from a file it was told is
    #: anything but JavaScript, and it says nothing when it refuses -- the
    #: picture simply never appears.
    PAGE = {
        ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
        ".css": "text/css", ".json": "application/json", ".wasm": "application/wasm",
        ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2",
    }

    def _send_the_page(self, path: str) -> None:
        """Hand out the built operator page, so one process serves the whole thing.

        The microscope PC gets one program: the page it draws and the
        instrument it drives, on one address. That is also why the page finds
        the bridge at its own origin and needs telling only in development,
        where a dev server holds the page instead so that edits reload live.
        """
        name = path.lstrip("/") or "index.html"
        where = (THE_PAGE / name).resolve()
        wanted = self.PAGE.get(where.suffix)
        if THE_PAGE not in where.parents or wanted is None or not where.is_file():
            self._answer({"error": f"no page at {path}"}, status=404)
            return
        body = where.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", wanted)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    #: What a view folder is allowed to hold, and what to call it when sent.
    #: A short list rather than a guess, because this hands out files by a name
    #: the page chose: anything not on it is not a picture and is not sent.
    PICTURES = {".jpg": "image/jpeg", "tiles.json": "application/json"}

    def _send_a_picture(self, path: str) -> None:
        """Hand out one file from a scan's view folder.

        ``/view/<acquisition type>/<name>``. Browsers will not let a page read
        files off a disk, so the pictures a scan makes have to be served, and
        this is the only reason the bridge serves anything that is not JSON.

        The name is taken apart rather than joined on: a name with a path in it
        would otherwise reach out of the folder and hand out any file this
        process can read.
        """
        _, _, rest = path.partition("/view/")
        kind, _, name = rest.partition("/")
        wanted = self.PICTURES.get(name if name in self.PICTURES else Path(name).suffix)
        if not kind or not name or name != Path(name).name or wanted is None:
            self._answer({"error": f"no picture {rest!r}"}, status=404)
            return
        if kind == FOCUSSING:
            # A focus stack's slices: written as each point lands, no note --
            # the point itself tells the page their names and heights.
            where = view_of(kind) / name
        else:
            note = _the_view_of(kind)
            where = None if note is None else (note if name == "tiles.json" else note.parent / name)
        if where is None or not where.is_file():
            self._answer({"error": f"nothing has been imaged at {rest}"}, status=404)
            return
        body = where.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", wanted)
        self.send_header("Content-Length", str(len(body)))
        # A scan's note and its pictures change as it runs, so nothing here is
        # worth keeping: a cached note is a canvas that stops growing.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

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
                self._answer(_the_scan())
            elif path == "/api/focus/measure":
                self._answer(dict(_focus))
            elif path == "/api/targets/discover":
                self._answer(dict(_targets))
            elif path.startswith("/view/"):
                self._send_a_picture(path)
            elif not path.startswith("/api/"):
                self._send_the_page(path)
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
            elif self.path == "/api/state":
                with _the_instruments_turn:
                    self._answer(_apply_state(asked))
            elif self.path == "/api/acquire":
                with _the_instruments_turn:
                    self._answer(_capture(asked))
            elif self.path == "/api/focus/measure":
                self._answer(_measure_focus(asked))
            elif self.path == "/api/focus/measure/stop":
                self._answer(_stop_focus())
            elif self.path == "/api/scan":
                self._answer(_start_scan(asked))
            elif self.path == "/api/scan/stop":
                self._answer(_stop_scan())
            elif self.path == "/api/targets/discover":
                self._answer(_discover_targets(asked))
            else:
                self._answer({"error": f"no route {self.path}"}, status=404)
        except Exception as why:  # noqa: BLE001
            self._fail(why)

    def log_message(self, *_args) -> None:
        """Quiet: the terminal is the operator's too."""


def _a_bridge_on(port: int, output_root: str | None = None) -> ThreadingHTTPServer:
    """A bridge ready to answer, with every driver this machine has.

    Both ways in build it here. They did not: run as a script it registered
    nothing, so the page's Microscope list came back empty and there was
    nothing to connect to -- while the same file imported and served was fine.
    """
    global _output_root
    _output_root = output_root
    _register_known_drivers()
    return ThreadingHTTPServer(("127.0.0.1", port), _Bridge)


def serve(port: int = 8600, output_root: str | None = None) -> ThreadingHTTPServer:
    server = _a_bridge_on(port, output_root)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8600)
    parser.add_argument(
        "--output-root",
        help="where runs go, for a driver that cannot discover its own",
    )
    args = parser.parse_args()
    server = _a_bridge_on(args.port, args.output_root)
    print(f"bridge listening on 127.0.0.1:{args.port}")
    server.serve_forever()
