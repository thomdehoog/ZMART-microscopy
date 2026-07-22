"""The run itself: the v4 notebook's steps, driven from the browser.

Each method here is one numbered section of ``zmart_microscopy_v4_react
.ipynb``, in the same order and calling the same public workflow and
``zmart_controller`` functions — connect, set the origin, capture the two
jobs, measure focus, scan the overview, discover targets, acquire and curate, save, disconnect. The notebook stays the
reference; this class only replaces the *cells* (the orchestration), never
the science.

Every step runs on the hub's single worker thread, so the widgets see the
same one-thing-at-a-time world they see under a notebook kernel. A step
that cannot run yet (its prerequisite step has not happened) refuses with
a plain sentence rather than a stack trace — the browser shows that
sentence to the operator.

In demo mode the flow drives :mod:`workflow._simulation` — the same
simulated microscope, sample and analysis engine the offline notebook
tests execute against — so the whole interface can be learned and tested
without a Leica in the room.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import react as wreact
from ._host import WidgetHub

log = logging.getLogger(__name__)


class FlowError(RuntimeError):
    """A step refused to run; the message is written for the operator."""


class RunFlow:
    """One acquisition session, from connect to disconnect."""

    def __init__(
        self,
        hub: WidgetHub,
        *,
        demo: bool = False,
        analysis_repo: str | Path | None = None,
        vendor: str = "leica",
        demo_root: str | Path | None = None,
        af_job: str | None = None,
        experiment: str = "target-acquisition",
    ) -> None:
        if not demo and analysis_repo is None:
            raise ValueError(
                "a real session needs --analysis-repo (the smart analysis checkout); "
                "or start with --demo to use the simulated microscope"
            )
        self.hub = hub
        self.demo = demo
        self.analysis_repo = analysis_repo
        self.vendor = vendor
        self.demo_root = Path(demo_root) if demo_root is not None else None
        self.af_job = af_job
        self.experiment = experiment

        # The same names the notebook's cells would define, so the run
        # checklist reads this session exactly as it reads a notebook.
        self.ns: dict[str, Any] = {}

        self.session: Any = None
        self.engine: Any = None
        self.root: Path | None = None
        self.overview_state: dict | None = None
        self.target_state: dict | None = None
        self.positions: list[dict] | None = None
        self.picker: Any = None
        self.viewer: Any = None
        self.overview_records: list[dict] | None = None
        self.overviews: list[dict] | None = None
        self.targets: list[dict] | None = None
        self.explorer: Any = None
        self.gallery: Any = None
        # Which overview channel cells are detected in (0 = the first). The
        # operator can change this before running discovery; the overview map
        # shows every channel so they can see which one holds the structure.
        self.segmentation_channel: int = 0
        self.completed: list[str] = []
        self._pending: set[str] = set()
        self._state_lock = threading.Lock()
        self._engine_shutdown_attempted = False
        self._engine_shutdown_error: Exception | None = None
        # Set once the microscope session has been released, so the shutdown
        # path never disconnects a second time (see _disconnect).
        self._session_released = False

        # The checklist and the (still empty) overview map exist from the
        # start, so the page always has something honest to show.
        self.status_widget = wreact.run_status(self.ns)
        hub.add_widget("status", self.status_widget)
        self.viewer = wreact.view_overview()
        hub.add_widget("overview", self.viewer)

        self._steps: dict[str, Callable[[], str]] = {
            "connect": self._connect,
            "set_origin": self._set_origin,
            "capture_overview_job": self._capture_overview_job,
            "capture_target_job": self._capture_target_job,
            "load_positions": self._load_positions,
            "run_overview": self._run_overview,
            "discover_targets": self._discover_targets,
            "save_results": self._save_results,
            "disconnect": self._disconnect,
        }
        self._prerequisite = {
            "set_origin": "connect",
            "capture_overview_job": "set_origin",
            "capture_target_job": "capture_overview_job",
            "load_positions": "capture_target_job",
            "run_overview": "load_positions",
            "discover_targets": "run_overview",
            "save_results": "discover_targets",
            # Disconnect is deliberately available early: releasing a session
            # must never depend on finishing the experiment.
            "disconnect": "connect",
        }

    # -- driving ---------------------------------------------------------------

    def has_step(self, name: str) -> bool:
        """Whether ``name`` is one of this flow's public actions."""
        return name in self._steps

    def run_step(self, name: str) -> bool:
        """Queue one named step on the worker; False if the name is unknown."""
        step = self._steps.get(name)
        if step is None:
            return False
        with self._state_lock:
            if name in self._pending:
                return True  # coalesce a double-click with the queued/running step
            self._pending.add(name)
        if self.hub.submit(lambda: self._run_step(name, step)):
            return True
        with self._state_lock:
            self._pending.discard(name)
        self._flow_event(name, "failed", "the server is busy — wait for the current work")
        return False

    def _run_step(self, name: str, step: Callable[[], str]) -> None:
        self._flow_event(name, "running", "")
        try:
            with self._state_lock:
                completed = set(self.completed)
            if name in completed and name != "save_results":
                raise FlowError(f"{name.replace('_', ' ')} is already complete")
            if "disconnect" in completed and name not in {"disconnect", "save_results"}:
                raise FlowError("this session is disconnected — start a new server for a new run")
            prerequisite = self._prerequisite.get(name)
            if prerequisite is not None and prerequisite not in completed:
                raise FlowError(
                    f"finish {prerequisite.replace('_', ' ')} before {name.replace('_', ' ')}"
                )
            message = step()
        except FlowError as exc:
            # A refusal we wrote for the operator — show it as-is.
            self._flow_event(name, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001 -- shown to the operator, not lost
            # An unexpected hardware/driver error. Lead with a plain sentence
            # naming the step, then the underlying message — never a bare
            # traceback the operator cannot act on. The full traceback is still
            # available in the server console for a maintainer.
            step_label = name.replace("_", " ")
            self._flow_event(
                name, "failed", f"{step_label} could not finish: {exc}"
            )
            log.exception("step %r failed", name)
        else:
            with self._state_lock:
                if name not in self.completed:
                    self.completed.append(name)
            self.status_widget.refresh(self.ns)
            self._flow_event(name, "done", message)
        finally:
            with self._state_lock:
                self._pending.discard(name)

    def _flow_event(self, step: str, state: str, message: str) -> None:
        self.hub.broadcast({"kind": "flow", "step": step, "state": state, "message": message})
        self._journal(step, state, message)

    def _journal(self, step: str, state: str, message: str) -> None:
        """Append one step event to the run's on-disk journal.

        The website's progress is otherwise only ever shown live in the
        browser and lost when the tab closes. This gives every web run the
        same timestamped, reconstructable narrative the notebook runs get:
        one JSON line per step start / finish / failure, next to the images
        in the run folder. It is best-effort — a journal write must never
        take down a run — and only starts once the run folder exists (after
        connect). Nearly all events come from the single worker thread; the
        one exception is a "server busy" refusal emitted from a request
        thread, so the append relies on the OS's atomic append for a single
        short line rather than assuming one writer.
        """
        if self.root is None:
            return
        try:
            from datetime import datetime, timezone

            line = json.dumps(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "step": step,
                    "state": state,
                    "message": message,
                }
            )
            with open(self.root / "run_journal.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 -- journalling must never fail a run
            # A single warning to the server console; the run continues.
            print(f"warning: could not write the run journal: {exc}")

    def flow_snapshot(self) -> dict:
        """What a fresh (or refreshed) tab needs to restore its buttons."""
        with self._state_lock:
            completed = list(self.completed)
        return {"completed": completed, "demo": self.demo}

    def reset(self, timeout: float = 30.0) -> None:
        """Safely disconnect this run and replace it with a fresh one.

        Reset is deliberately separate from browser reconnect: a dropped tab
        must never erase an active acquisition. Once Connect has completed,
        the explicit reset runs on the hub worker, releases the microscope and
        analysis engine, and then clears the browser-facing run state.
        """
        with self._state_lock:
            if "connect" not in self.completed:
                raise FlowError("connect before restarting the workflow")
            if self._pending:
                raise FlowError("wait for the current workflow action to finish")
        # A flow step is not the only thing that drives hardware: the focus
        # Measure and the gallery Acquire run on the same worker as their own
        # widget actions, and ``_pending`` does not see them. Name a running one
        # for a helpful message.
        busy = self._busy_widget()
        if busy is not None:
            raise FlowError(
                f"a {busy} is running — wait for it to finish (or press Cancel) "
                "before restarting the workflow"
            )
        # And refuse if ANY work is running or merely queued on the worker: an
        # Acquire that was just clicked is queued but has not set its ``_busy``
        # flag yet, so without this check the reset would queue behind it, time
        # out, report "restart failed", and then still disconnect the scope when
        # the acquisition finally ran. Checking the worker closes that window.
        if self.hub.busy():
            raise FlowError(
                "the microscope is busy — wait for the current work to finish "
                "before restarting the workflow"
            )

        finished = threading.Event()
        errors: list[BaseException] = []

        def apply() -> None:
            try:
                self._reset_now()
            except BaseException as exc:  # surfaced to the requesting browser
                errors.append(exc)
            finally:
                finished.set()

        if not self.hub.submit(apply):
            raise FlowError("the server is busy — wait before starting a new run")
        if not finished.wait(timeout):
            raise FlowError("the new run did not initialize in time")
        if errors:
            raise errors[0]

    def _busy_widget(self) -> str | None:
        """The operator-facing name of an in-flight hardware widget, or None.

        The focus picker's Measure and the gallery's Acquire each drive the
        stage on the shared worker; both carry a private ``_busy`` flag while
        running. Restart checks this so it never queues behind an acquisition.
        """
        if self.picker is not None and getattr(self.picker, "_busy", False):
            return "focus measurement"
        if self.gallery is not None and getattr(self.gallery, "_busy", False):
            return "target acquisition"
        return None

    def release_on_shutdown(self, timeout: float = 30.0) -> None:
        """Release the microscope on the worker thread when the server stops.

        Ctrl+C or a crash ends the process, but the microscope session and the
        analysis engine must not be left connected and locked. The catch: this
        runs on the MAIN thread during shutdown while the step worker may still
        be mid-acquisition, and driving the same session from two threads at
        once could corrupt it. So the release is submitted to the worker queue
        — it runs AFTER any in-flight acquisition, never alongside it — and we
        wait a bounded time for it. If the worker is wedged past the timeout we
        warn (pointing the operator at the vendor software) rather than reach in
        and disconnect concurrently. Best-effort and never raises.
        """
        with self._state_lock:
            already_disconnected = "disconnect" in self.completed
        if self.session is None or self._session_released or already_disconnected:
            return

        done = threading.Event()
        outcome: dict[str, Any] = {}

        def _release() -> None:
            try:
                self._disconnect()
                outcome["ok"] = True
            except Exception as exc:  # noqa: BLE001 -- process is stopping anyway
                outcome["error"] = exc
            finally:
                done.set()

        if not self.hub.submit(_release):
            print("warning: could not queue the shutdown release; the microscope may be left connected")
            return
        if not done.wait(timeout):
            print(
                "warning: the microscope did not release before shutdown timed out — "
                "check the vendor software"
            )
        elif "error" in outcome:
            print(f"warning: could not fully release the microscope on shutdown: {outcome['error']}")
        else:
            print("released the microscope session on shutdown")

    def _reset_now(self) -> None:
        with self._state_lock:
            completed = set(self.completed)
            if "connect" not in completed:
                raise FlowError("connect before restarting the workflow")
        if "disconnect" not in completed:
            self._disconnect()
        settings = {
            "demo": self.demo,
            "analysis_repo": self.analysis_repo,
            "vendor": self.vendor,
            "demo_root": self.demo_root,
            "af_job": self.af_job,
            "experiment": self.experiment,
        }
        self.hub.clear_widgets()
        self.__init__(self.hub, **settings)
        self.hub.broadcast({"kind": "reset"})

    # -- the steps, in notebook order -------------------------------------------

    def _require(self, condition: Any, message: str) -> None:
        if not condition:
            raise FlowError(message)

    def _connect(self) -> str:
        from .. import connect, load_analysis_engine, preflight_analysis_engine, prepare_experiment

        self._require(self.session is None, "already connected — continue with the next step")
        if self.demo:
            from .._simulation import SimulatedEngine, SimulatedSession

            engine = SimulatedEngine()
            preflight_analysis_engine(engine)
            session = SimulatedSession(self.demo_root or Path.cwd() / "zmart_demo_run")
        else:
            engine = load_analysis_engine(self.analysis_repo)
            try:
                preflight_analysis_engine(engine)
                session = connect(self.vendor)
            except Exception:
                engine.shutdown()
                raise
        try:
            output_root = Path(session.get_info()["output_root"])
            root = prepare_experiment(output_root, self.experiment)
        except Exception:
            session.disconnect()
            engine.shutdown()
            raise
        self.session, self.engine, self.root = session, engine, root
        self.ns.update(zmart_controller=session, engine=engine, ROOT=root)
        mode = "the simulated microscope" if self.demo else f"the {self.vendor} session"
        return f"connected to {mode} — this run saves under {root}"

    def _set_origin(self) -> str:
        self._require(self.session is not None, "connect first")
        self.session.set_origin()
        return "origin set — positions now count from where the stage is right now"

    def _capture_overview_job(self) -> str:
        self._require(self.session is not None, "connect first")
        if self.demo:
            self.session.select_job(self.session.OVERVIEW_JOB)
        state = self.session.get_state()
        from .. import require_driver_ready

        try:
            require_driver_ready(state)
        except RuntimeError as exc:
            raise FlowError(str(exc)) from exc
        self.overview_state = state
        self.ns["overview_state"] = state
        job = state["changeable"].get("job")
        return f"overview job captured: {job!r}"

    def _capture_target_job(self) -> str:
        self._require(self.overview_state is not None, "capture the overview job first")
        if self.demo:
            self.session.select_job(self.session.TARGET_JOB)
        state = self.session.get_state()
        if state["changeable"].get("job") == self.overview_state["changeable"].get("job"):
            raise FlowError(
                "the overview and target jobs are the same; select the "
                "high-magnification target job (in LAS X) and capture again"
            )
        from .. import require_driver_ready

        try:
            require_driver_ready(state)
        except RuntimeError as exc:
            raise FlowError(str(exc)) from exc
        self.target_state = state
        self.ns["target_state"] = state
        job = state["changeable"].get("job")
        return f"target job captured: {job!r}"

    def _load_positions(self) -> str:
        self._require(self.session is not None, "connect first")
        self._require(self.overview_state is not None, "capture the overview job first")
        # Positions were authored for the overview job. Restore that captured
        # controller state before the controller translates stored stage
        # coordinates into the session frame.
        self.session.set_state(self.overview_state)
        info = self.session.get_info()
        positions = info["tile_positions"]
        self._require(positions, "the microscope returned no overview positions")
        self.positions = positions
        self.ns["positions"] = positions
        if self.picker is None:
            self.picker = wreact.pick_focus_points(
                self.session,
                positions,
                focus_positions=info.get("focus_positions"),
                af_job=self.af_job,
            )
            self.ns["picker"] = self.picker
            self.hub.add_widget("focus", self.picker)
        return (
            f"{len(positions)} overview positions loaded — click focus points on "
            "the map below, then press Measure"
        )

    def _focus(self) -> Any:
        self._require(
            self.picker is not None, "load the positions first (the focus map needs them)"
        )
        try:
            focus = self.picker.require_focus()
        except Exception as exc:
            raise FlowError(str(exc)) from exc
        self.ns["focus"] = focus
        return focus

    def _run_overview(self) -> str:
        from .. import overview_inputs_from_records, run_overview

        self._require(self.overview_state is not None, "capture the overview job first")
        self._require(self.positions is not None, "load the positions first")
        focus = self._focus()
        self.viewer.expect_tiles(len(self.positions))
        records = run_overview(
            self.session,
            self.positions,
            state=self.overview_state,
            focus=focus,
            on_record=self.viewer.add_acquisition,
            output_root=self.root,
        )
        self.overview_records = records
        self.ns["overview_records"] = records
        self.overviews = overview_inputs_from_records(self.positions, records, focus=focus)
        self.ns["overviews"] = self.overviews
        return f"{len(records)} overview tiles captured — the map above is the sample"

    def _discover_targets(self) -> str:
        from .. import discover_targets

        self._require(self.engine is not None, "connect first")
        self._require(self.overviews, "run the overview scan first")
        self._require(self.target_state is not None, "capture the target job first")
        targets = discover_targets(
            self.engine, self.overviews, segmentation_channel=self.segmentation_channel
        )
        self._require(targets, "discovery found no cells in the overview tiles")
        self.targets = targets
        self.ns["targets"] = targets
        if self.explorer is None:
            self.explorer = wreact.explore_targets(targets, self.overviews)
            # Where "save gates" writes and "load gates" reads. A stable path
            # beside the experiment folders (not inside this run's hashed one),
            # so a double/triple-positive definition carries across runs saving
            # under the same output location.
            if self.root is not None:
                self.explorer._gates_path = self.root.parent / "saved_gates.json"
            self.ns["explorer"] = self.explorer
            self.hub.add_widget("explorer", self.explorer)
            self.gallery = wreact.acquire_gallery(
                self.session,
                self.explorer,
                self.overviews,
                state=self.target_state,
                focus=self.ns.get("focus"),
                output_root=self.root,
            )
            self.ns["gallery"] = self.gallery
            self.hub.add_widget("gallery", self.gallery)
        # Link the discovered cells onto the overview map: every cell becomes a
        # dot at its real position (bright when it passes the gate, ringed when
        # picked, filled once acquired), so gating and picking are judged
        # against the sample itself — and hovering or clicking is mirrored
        # between the map and the scatter.
        self.viewer.show_targets(targets, self.explorer)
        return (
            f"{len(targets)} candidate cells found — gate them in the explorer or on the map, "
            "then acquire"
        )

    def _save_results(self) -> str:
        from .. import write_run_report

        self._require(self.gallery is not None, "discover targets first")
        self._require(
            self.gallery.records,
            "no targets have been acquired; use the Acquire button first",
        )
        summary = write_run_report(
            self.root,
            positions=self.positions,
            focus=self.ns.get("focus"),
            overview_records=self.overview_records,
            targets=self.gallery.picked,
            overviews=self.overviews,
            show=False,
        )
        self.ns["summary"] = summary
        curation = self.gallery.save_curation(self.root)
        return (
            f"saved — run report and layout in {self.root}, your good/bad "
            f"verdicts in {curation.name}"
        )

    def _disconnect(self) -> str:
        self._require(self.session is not None, "nothing is connected")
        try:
            if self.engine is not None and not self._engine_shutdown_attempted:
                self._engine_shutdown_attempted = True
                try:
                    self.engine.shutdown()
                except Exception as exc:
                    self._engine_shutdown_error = exc
        finally:
            # Mark the session released BEFORE the raising engine-shutdown
            # branch below, so a Disconnect step that fails on the engine still
            # records that the session itself was released — otherwise the
            # shutdown path (which sees the step did not "complete") would call
            # disconnect a second time. The driver's disconnect is idempotent
            # anyway; this makes the intent explicit instead of relying on it.
            self.session.disconnect()
            self._session_released = True
        if self._engine_shutdown_error is not None:
            exc = self._engine_shutdown_error
            raise FlowError(
                f"analysis engine shutdown failed ({type(exc).__name__}: {exc}); "
                "the microscope session was still released"
            )
        return "disconnected — the microscope is released; it is safe to close this page"
