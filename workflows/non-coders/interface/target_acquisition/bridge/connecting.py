"""Opening and closing the session: which microscopes are offered, and connecting to one.

The Connect step lists what this computer can drive (``/api/instruments``):
what whoever started the bridge offered first (the interface offers its own
mock microscope there), then every driver the controller's registry knows,
each with the settings of its connection the step shows. Connecting opens a
``ZmartController`` of the bridge's own for the chosen one, with what the
operator typed put over the connection it was saved with, makes the run
folder every capture goes under, and starts the picture server beside it.
Disconnecting closes all of that.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import sys
import time
from importlib.metadata import version

from zmart_controller import ZmartController
from zmart_controller.registry import find_driver, get_instruments, plugin_class

from ..analysis import warm
from ..microscope.instrument import Instrument
from ..storage import viewer_service
from ..storage.output import checked_name, prepare_experiment
from . import discovery, ledgers, scan, state

#: The microscopes whoever started the bridge offers beside the controller's
#: list, by name: ``{name: (driver, connection)}``, where ``driver`` is what
#: ``ZmartController`` is handed (a driver package, plugged in directly) and
#: ``connection`` what it is connected with. Target acquisition offers its
#: own mock here (``workflows/target_acquisition/bridge/starting.py``); the
#: bridge itself offers nothing and knows no instrument.
offered: dict[str, tuple[object, dict]] = {}


#: The settings of a driver's connection the Connect step shows, when the
#: connection names them: the controller's connection words but the output
#: folder, which is the bridge's own. The microscope and its API are the
#: driver's and are only shown.
SHOWN_SETTINGS = ("microscope", "api_type", "host", "client", "password", "config")

#: The ones the operator may type over what was saved. Each one typed is
#: handed on, named by the driver's connection or not: a driver uses the
#: words it needs and leaves the rest. A password is only ever typed: the
#: controller refuses a driver file that holds one, and the bridge never
#: hands one out or keeps one.
TYPED_SETTINGS = ("host", "client", "password", "config")


def listed() -> dict[str, dict]:
    """The microscopes the Connect step offers, by name in the order it shows them, each with its connection.

    What the starter offered first -- the interface puts its mock there, so a
    page opened by accident drives nothing real -- then every driver
    installed on this computer, as the controller lists them.
    """
    return {
        **{name: connection for name, (driver, connection) in offered.items()},
        **{name: connection for name, connection in get_instruments().items() if name not in offered},
    }


def instruments() -> list[dict]:
    """The microscopes the Connect step offers, each with the settings of its connection it shows.

    ``{"name", "settings", "configs"}``: of :data:`SHOWN_SETTINGS`, the ones
    the connection names, with the value each was saved with -- a password
    only as named, its value always ``None``. A setting the connection does
    not name is one the driver does not need, and the step says so.
    ``configs`` is what :func:`configurations` finds.
    """
    return [
        {"name": name, "settings": {
            key: None if key == "password" else connection[key] for key in SHOWN_SETTINGS if key in connection
        }, "configs": configurations(name)}
        for name, connection in listed().items()
    ]


def configurations(name: str) -> list[str] | None:
    """The configs a listed microscope's driver keeps, as its ``config`` may name them, or None.

    A driver's plugin may say which it keeps, the most recent first, with a
    ``configurations()`` that is asked before connecting; the Connect step
    then offers them to choose from. None when it does not say, or cannot
    answer: then the config is typed.
    """
    try:
        driver = offered[name][0] if name in offered else find_driver(name)[0]
        ask = getattr(plugin_class(driver), "configurations", None)
        return [str(one) for one in ask()] if callable(ask) else None
    except Exception as why:  # noqa: BLE001 -- a driver that cannot list its configs is typed into
        print(f"{name}: its configs could not be listed: {why}", file=sys.stderr, flush=True)
        return None


def saved_connection(name: str) -> dict:
    """The connection a listed microscope is plugged in with, before anything is added to it.

    For an installed driver, the connection its ``zmart_controller_plugin.json`` gives.
    Finding it imports the driver, which is why a name that is not listed is
    refused first: the page can only ever name a microscope this computer
    offers.
    """
    if name in offered:
        return dict(offered[name][1])
    if name not in listed():
        raise ValueError(f"no microscope is listed as {name!r}; listed: {list(listed())}")
    return find_driver(name)[1]


#: The controller versions this interface works with: 0.4.0rc1 and later,
#: below 0.5. From 0.3.0 a driver names its default motor per axis and every
#: answer says which one moved, and acquisition settings say only how to
#: trigger; from 0.4.0 acquire is given the kind of acquisition and the folder
#: to save in, and get_info says whether the microscope chooses its own folder
#: instead: the interface decides where its own runs go.
CONTROLLER_VERSIONS = ">=0.4.0rc7,<0.5"


def accept_the_controller(installed_version: str) -> None:
    """Refuse a controller outside :data:`CONTROLLER_VERSIONS`, saying which was found."""
    from packaging.specifiers import SpecifierSet  # noqa: PLC0415

    if not SpecifierSet(CONTROLLER_VERSIONS, prereleases=True).contains(installed_version):
        raise RuntimeError(
            f"the ZMART Controller {installed_version} is installed, and this interface "
            f"needs zmart-controller {CONTROLLER_VERSIONS}"
        )


#: What a run is called on disk when the page names nothing: ``run_<hash>``.
#: A workflow names its own (Target acquisition's runs are
#: ``target-acquisition_<hash>``), so that its runs are told apart from other
#: workflows' by name and from each other by their hash.
A_RUN = "run"


def connect(asked: dict) -> dict:
    """Open the session for one of the listed microscopes and answer with the driver's account.

    ``asked["instrument"]`` is a name from :func:`instruments`. What the
    operator typed on the Connect step goes over the connection that was
    saved for it: ``host``, ``client``, ``password`` and ``config``, and
    ``output_root``, the folder the run is made under.
    A field left empty keeps what was saved, and the folder is the one the
    last run went to (at first ``--output-root``). Once the run folder is
    made, the folder is kept as the last one used.
    ``asked["experiment"]`` is what the workflow calls its runs: the run
    folder is ``<experiment>_<hash>``. It is checked to be a plain folder
    name before anything is opened.
    """
    accept_the_controller(version("zmart-controller"))
    name = asked.get("instrument")
    if not isinstance(name, str):
        raise ValueError("connect needs the name of one of the microscopes listed by /api/instruments")
    experiment = checked_name(asked.get("experiment") or A_RUN, field="experiment")
    connection = saved_connection(name)
    for key in TYPED_SETTINGS:
        if asked.get(key):
            connection[key] = asked[key]
    output_root = asked.get("output_root") or state.output_root
    if output_root is not None:
        connection["output_root"] = output_root
    # The session before this one is closed first. A page that is reloaded
    # connects again, and the old session was left open behind the new one:
    # the microscope software still had a client, and a scan still running
    # on it kept moving the stage. The scan itself was asked to stop by
    # :func:`let_the_last_session_go` before the instrument's turn was taken.
    close_the_last_session()
    # A controller of the bridge's own, not the module-level ``mic`` that
    # scripts share: the bridge opens and closes it, and nothing else may.
    driver = offered[name][0] if name in offered else name
    session = Instrument(ZmartController(driver, connection))
    try:
        info = session.get_info()
        standing = session.get_xyz()
        area = the_viewers_area(standing)
        if output_root is None:
            # What the microscope says it still needs set up, in its own words.
            missing = [
                f"{item}: {said.get('says')}" for item, said in (info.get("setup") or {}).items()
                if isinstance(said, dict) and not said.get("done")
            ]
            raise RuntimeError(
                "the interface was not told where to put its runs; give an Output folder, "
                "or start it with --output-root and a folder, ideally on the drive the "
                "microscope saves to"
                + (f" (not set up on {name!r}: {'; '.join(missing)})" if missing else "")
            )
        run = prepare_experiment(output_root, experiment)
    except Exception:
        # A microscope that cannot describe itself, say where its pictures
        # can show, or be given a folder to save into is not a session to
        # keep. Nothing of it was handed to the rest of the bridge yet, so
        # closing it here leaves no half-open session behind.
        session.disconnect()
        raise
    state.session = session
    # The folder this run went to is the one the Connect step offers next.
    state.output_root = output_root
    state.context = {**session.context, "name": name}
    session.run = run
    state.run = run
    # The analysis writes its records and files into this run.
    warm.open(run)
    # A fresh session has scanned nothing. The bridge outlives the page, and
    # records carried over from the last session rebuilt its scan's pictures
    # into this run's view -- a just-connected canvas showed a scan nobody
    # had taken.
    state.records.clear()
    state.view_built.clear()
    state.displayed_pictures.clear()
    # And forgets how far its own runs had got.
    ledgers.forget()
    # The picture server, beside the run: the viewer links each acquisition's
    # positions into one live picture and serves it to the page's own engine.
    # An optional guest -- a machine without it still scans, and still draws
    # the JPEG copies -- so a viewer that cannot start is a sentence on
    # /api/viewer, never a failed connect.
    viewer_service.stop()
    # Baked, always: the zoomed-out picture composed on demand from every
    # position measured seconds a chunk against milliseconds baked, and the
    # first screen of a scan is zoomed out.
    viewer_service.start(state.run, bake=True, canvas=area)
    return {"context": state.context, "info": info, "run": str(state.run)}


def the_viewers_area(reading: dict) -> dict[str, list[float]]:
    """The area the viewer lays pictures out on: get_xyz's ``canvas``, axis by axis.

    ``canvas`` is everywhere a picture can show along an axis -- the stage's
    travel and half a field (or half a stack) beyond it -- in the
    micrometres get_xyz counts in. The viewer refuses, whole, a picture that
    falls outside its area, so the area is laid out before the first picture
    from what the driver says, never guessed. A driver that does not say is
    refused at connect, in words the operator can act on.
    """
    area = {}
    for axis in ("x", "y", "z"):
        canvas = (reading.get(axis) or {}).get("canvas")
        if not (isinstance(canvas, (list, tuple)) and len(canvas) == 2):
            raise RuntimeError(
                f"the microscope's driver does not say where its pictures can show along {axis} "
                "(get_xyz gives no 'canvas'), so the area to show them on cannot be laid out; "
                "the driver needs updating to the controller's current contract"
            )
        area[f"{axis}_um"] = [float(canvas[0]), float(canvas[1])]
    return area


#: How long letting the last session go waits for the running scan to finish
#: the field it is capturing. A field is never cut off halfway, and one slow
#: field (a deep stack) can take minutes; beyond this the operator is told to
#: try again.
WAIT_FOR_THE_LAST_SCAN_S = 600.0


def let_the_last_session_go(wait_s: float | None = None) -> None:
    """Stop the scan and discovery between two fields, and wait until they have.

    Both run in the bridge's own threads and outlive the page that started
    them, so another session must not open beneath them; they are stopped as
    the operator's Interrupt stops them. The focus map and the target run are
    driven by the page itself, so a reloaded page has already let them go;
    connecting forgets their records. It must be called without holding the
    instrument's turn, because a run needs that turn to finish its field.
    """
    if ledgers.scan["running"]:
        scan.stop_scan()
    if ledgers.targets["running"]:
        discovery.stop_targets()
    limit = time.monotonic() + (WAIT_FOR_THE_LAST_SCAN_S if wait_s is None else wait_s)
    while ledgers.scan["running"] or ledgers.targets["running"]:
        if time.monotonic() > limit:
            raise RuntimeError(
                "the scan that was running has not stopped yet; it finishes the field it is "
                "capturing first, so wait a moment and connect again"
            )
        time.sleep(0.05)


def close_the_last_session() -> None:
    """Close the session that is open, if any, even when the microscope no longer answers.

    A microscope that has gone away cannot be closed politely, and that must
    not stop the operator from opening a new session, so a failure here is
    reported in the terminal and otherwise ignored.
    """
    if state.session is None:
        return
    try:
        state.session.disconnect()
    except Exception as why:  # noqa: BLE001 -- the old session is being let go either way
        print(f"the last session could not be closed cleanly: {why}", file=sys.stderr, flush=True)
    state.session = None
    state.run = None


def disconnect() -> dict:
    if state.session is not None:
        state.session.disconnect()
        state.session = None
    state.run = None
    # The context is the session's: a name left over from the last one
    # made the next session's readings pretend it was the mock.
    state.context = {}
    # The workers outlive a focus map on purpose, but not the session: a
    # disconnected page is not about to measure anything.
    warm.close()
    warm.open(None)
    # The picture server belongs to the session's run, and goes with it.
    viewer_service.stop()
    return {"closed": True}
