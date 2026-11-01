"""Target acquisition's Python half: everything it asks of the microscope, and its routes.

The bridge's general part serves the page and dispatches the routes; it
knows no workflow and no instrument. Everything target acquisition does with
the microscope lives here:

- ``connecting``: what this computer can drive, opening and closing the
  session through the ZMART Controller, and the run folder made at connect;
- ``readings`` and ``stage``: the instrument's settings, a capture, and
  where the stage is and where it is sent;
- ``pictures``: each capture kept as an OME-Zarr position, and the pictures
  the page fetches, made from the records on request;
- ``state``: what is kept between two requests, and the instrument's lock;
- ``starting``: what this half does when the interface starts and closes;
- ``focus``: the focus map, driven by the page one stack at a time;
- ``scan``: the overview scan, run in the bridge's own thread;
- ``discovery``: finding the targets in the overview, through the analysis;
- ``plots``: the population table and its multidimensional plots;
- ``targets``: the target run, driven by the page one tile at a time;
- ``protocols``: the settings a run ran with, and the ones saved by name;
- ``ledgers``: how far each of those runs has got;
- ``views``: the pictures only this workflow draws (focus slices, masks).

Its routes are registered by :func:`routes` under ``/api/target_acquisition/``,
the way every workflow's are (``framework/bridge/workflows.py``).
How far each of its own runs has got is kept in ``ledgers``: while one
runs, the stage's clock answers with where it sent the stage; before
another session opens, ``connecting`` stops them between two fields and
forgets them.

Its routes, and what they are made of
-------------------------------------

Each path below is under ``/api/target_acquisition/``.

* ``POST connect`` — open the session through the controller. The reply
  carries the driver's own account of itself (``get_info``), which is what the
  window's connection checks show. ``GET instruments`` lists what can be
  connected to, each with the settings of its connection the Connect step
  shows, and the folder the last run went to; ``GET info`` is the driver's account of the open session,
  and ``POST disconnect`` closes it.
* ``GET setting`` — **a readout, never a procedure.** The instrument's
  current state (``get_state``), shaped into the reading the window records:
  a one-line summary, the detail rows behind it, and the frame size the plan
  is laid with. Recording a preset — the acquisition settings and the
  focussing preset alike — is this, and nothing more: nothing on the
  instrument moves.
* ``GET xyz`` — where the stage is (``get_xyz``), and
  ``POST xyz`` — drive it there (``set_xyz``), answering with where it
  ended up. One noun, the method saying which of the controller's two verbs is
  meant. The page's backend calls them ``get_xyz`` and ``set_xyz`` too — the
  controller's own names, carried through the browser unchanged, because a
  verb that is spelled one way here and another way there is a verb somebody
  will eventually wire to the wrong one. A driven stage is a procedure and not
  a readout, which is why it is a POST and why nothing else on this route
  moves anything.
* ``GET acquisition_settings`` — what the instrument offers for a capture
  and what is chosen now (``get_acquisition_settings``), in the driver's own
  words. A readout: asking changes nothing.
* ``POST state`` — change settings on the instrument (``set_state``),
  answering with what the driver says it applied. The body is the settings
  themselves; the bridge puts them in ``changeable``, which is where the
  contract says a client's instructions go.
* ``POST acquire`` — capture once where the stage is standing
  (``acquire``), answering with the controller's own answer, untouched:
  ``{"success", "output"}``, the output's ``files`` naming every file saved and
  its ``planes`` which channel, depth and stage position each picture is. The
  one place a client learns the paths of the files a run made.
* ``GET viewer`` — whether the picture server beside the run is up, and
  what it serves. ``GET view/<acquisition>/<name>`` hands out one of a run's
  pictures.
* ``POST focus/begin``, ``POST focus/score`` and ``POST focus/end``
  — the focus map, driven by the page one stack at a time: begin clears the
  focussing acquisition and names the stacks; the page drives (``xyz``)
  and captures (``acquire``) each; score files the stack, scores it and
  answers the point; end closes the map. ``POST focus/stop`` is the
  operator's Interrupt reaching a scoring that has hung: it puts the analysis
  workers down, so that scoring answers. ``GET focus/measure`` is the
  bridge's ledger of the points scored so far.
* ``POST targets/acquire/begin``, ``POST targets/acquire/focus``,
  ``POST targets/acquire/landed`` and ``POST targets/acquire/end``
  — the target run, driven by the page one tile at a time like the focus
  map: begin clears the targets acquisition (unless appending) and names the
  captures; the page drives and captures each, with a focussing stack first
  when the operator asked for one (``focus`` scores it under its own
  acquisition and answers the peak); landed files the target's record the
  way the scan filed its own; end closes the run. ``GET targets/acquire``
  is the ledger, ``?since=N`` the records after the ones a page holds.
  ``POST targets/raise`` puts one acquired target's frame on top of its
  neighbours in the picture.
* ``POST plots/compute`` — a multidimensional plot (``pca`` or ``umap``)
  over the detected population, or the ids named, through ZMART-analysis;
  ``GET`` reads its progress, ``POST plots/compute/stop`` puts it down,
  ``GET plots/columns?kind=`` answers its two columns by id.
* ``POST scan`` — start the overview scan in a background thread: drive
  to each position, acquire, report progress. ``GET scan`` reads the
  progress. The window's live picture watches the run's own store, so nothing
  here needs to push pixels at the browser.
* ``POST scan/stop`` and ``POST targets/discover/stop`` — the
  operator's Interrupt: ask the run to stop between two fields. What was
  captured stands; the answer is the run as it stood, ``stopped`` set once
  the worker has honoured it.
* ``POST targets/discover`` — find the targets in the overview's fields,
  all of them or the ones named, through the warm analysis; ``GET`` reads the
  progress, each field's targets appended as they are found.
* ``GET protocols`` and ``POST protocols`` — the protocols this
  machine has written, before and after connecting; ``POST protocol``
  writes the run's settings beside it, ``POST protocol/save`` into the
  machine's library by name.

One thread owns the instrument. Every route that touches the session takes
``state.the_instruments_turn`` first, so two requests can never move the
stage at once — the scan holds it per position, not for the whole run, so a
readout during a scan waits briefly rather than failing.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import urllib.parse

from ..storage import viewer_service
from . import (
    connecting,
    discovery,
    focus,
    ledgers,
    pictures,
    plots,
    protocols,
    readings,
    scan,
    stage,
    state,
    targets,
)
from .starting import add_arguments, close, start

#: What the bridge asks of this half (``framework/bridge/api.py``).
__all__ = ["add_arguments", "close", "routes", "start"]

def connect(asked: dict) -> dict:
    """Open a session, after the last one's runs have let go of the stage.

    Letting go happens outside the instrument's turn: a running scan needs
    the turn to finish its field.
    """
    connecting.let_the_last_session_go()
    with state.the_instruments_turn:
        return connecting.connect(asked)


def in_the_instruments_turn(do):
    """``do()`` while no other request holds the instrument."""
    with state.the_instruments_turn:
        return do()


def since(query: str) -> int | None:
    """The ``since=N`` a ledger is read from, when the page has part of it already."""
    asked = urllib.parse.parse_qs(query or "").get("since", [None])[0]
    return int(asked) if asked is not None else None


def routes(register) -> None:
    """Every route of the workflow, each ``register(method, path, handler)``.

    ``handler(asked, query)`` takes the request's JSON body and the raw query
    string. The paths are under ``/api/target_acquisition/``.
    """
    # The session, the stage, the instrument's settings and a capture, in
    # the order the page meets them.
    register("GET", "instruments", lambda asked, query: {
        "instruments": connecting.instruments(), "output_root": state.output_root})
    register("POST", "connect", lambda asked, query: connect(asked))
    register("POST", "disconnect", lambda asked, query: in_the_instruments_turn(connecting.disconnect))
    register("GET", "info", lambda asked, query: in_the_instruments_turn(
        lambda: state.require_session().get_info()))
    register("GET", "setting", lambda asked, query: in_the_instruments_turn(lambda: readings.reading(
        urllib.parse.parse_qs(query or "").get("type", ["acquisition"])[0])))
    register("GET", "xyz", lambda asked, query: stage.where_the_stage_is())
    register("POST", "xyz", lambda asked, query: in_the_instruments_turn(lambda: stage.drive_to(asked)))
    register("GET", "acquisition_settings", lambda asked, query: in_the_instruments_turn(
        readings.acquisition_settings))
    register("POST", "state", lambda asked, query: in_the_instruments_turn(lambda: readings.apply_state(asked)))
    register("POST", "acquire", lambda asked, query: in_the_instruments_turn(lambda: readings.capture(asked)))
    # The pictures: what the viewer holds of the run, and the small copies.
    register("GET", "viewer", lambda asked, query: viewer_service.status())
    register("GET", "view/", pictures.a_picture, prefix=True)
    # The focus map: the page drives each point and ends the map.
    register("POST", "focus/begin", lambda asked, query: focus.begin_focus(asked))
    register("POST", "focus/score", lambda asked, query: focus.score_focus(asked))
    register("POST", "focus/stop", lambda asked, query: focus.stop_focus())
    register("POST", "focus/end", lambda asked, query: focus.end_focus(asked))
    register("GET", "focus/measure", lambda asked, query: dict(ledgers.focus))
    # The overview scan, run here and polled by the page.
    register("POST", "scan", lambda asked, query: scan.start_scan(asked))
    register("GET", "scan", lambda asked, query: scan.the_scan(since(query)))
    register("POST", "scan/stop", lambda asked, query: scan.stop_scan())
    # Finding the targets, run here and polled by the page.
    register("POST", "targets/discover", lambda asked, query: discovery.discover_targets(asked))
    register("GET", "targets/discover", lambda asked, query: discovery.the_targets(since(query)))
    register("POST", "targets/discover/stop", lambda asked, query: discovery.stop_targets())
    # The population plots.
    register("POST", "plots/compute", lambda asked, query: plots.compute_plot(asked))
    register("GET", "plots/compute", lambda asked, query: dict(ledgers.plots))
    register("POST", "plots/compute/stop", lambda asked, query: plots.stop_plot())
    register("GET", "plots/columns", lambda asked, query: plots.plot_columns(
        urllib.parse.parse_qs(query or "").get("kind", [""])[0]))
    # The target run: the page drives each tile and ends the run.
    register("POST", "targets/acquire/begin", lambda asked, query: targets.begin_target_run(asked))
    register("POST", "targets/acquire/focus", lambda asked, query: targets.score_target_focus(asked))
    register("POST", "targets/acquire/landed", lambda asked, query: targets.target_landed(asked))
    register("POST", "targets/acquire/end", lambda asked, query: targets.end_target_run(asked))
    register("GET", "targets/acquire", lambda asked, query: targets.the_target_run(since(query)))
    register("POST", "targets/raise", lambda asked, query: targets.raise_target(asked))
    # Protocols: before connecting, the chosen microscope's saved connection
    # says where earlier runs are.
    register("GET", "protocols", lambda asked, query: protocols.protocols())
    register("POST", "protocols", lambda asked, query: protocols.protocols(
        connecting.saved_connection(asked["instrument"]) if asked.get("instrument") else None))
    register("POST", "protocol", lambda asked, query: protocols.save_protocol(asked))
    register("POST", "protocol/save", lambda asked, query: protocols.save_protocol_to_library(asked))
