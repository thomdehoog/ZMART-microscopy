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

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import react as wreact
from ._host import WidgetHub


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
            self._flow_event(name, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001 -- shown to the operator, not lost
            self._flow_event(name, "failed", f"{type(exc).__name__}: {exc}")
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

    def release_on_shutdown(self) -> None:
        """Best-effort hardware release when the server itself is stopping.

        Ctrl+C or a crash ends the process, but the microscope session and the
        analysis engine must not be left connected and locked — otherwise the
        operator has to recover them by hand in the vendor software. Called
        from the server's shutdown path (not the step worker), so it is
        deliberately defensive: it acts only if something is still connected,
        never raises, and says what it did. The driver's disconnect is
        idempotent, so a later explicit Disconnect (if any) stays safe.
        """
        with self._state_lock:
            already_disconnected = "disconnect" in self.completed
        if self.session is None or already_disconnected:
            return
        try:
            self._disconnect()
        except Exception as exc:  # noqa: BLE001 -- the process is stopping anyway
            print(f"warning: could not fully release the microscope on shutdown: {exc}")
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
        return (
            f"{len(targets)} candidate cells found — gate them in the explorer, then acquire below"
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
            self.session.disconnect()
        if self._engine_shutdown_error is not None:
            exc = self._engine_shutdown_error
            raise FlowError(
                f"analysis engine shutdown failed ({type(exc).__name__}: {exc}); "
                "the microscope session was still released"
            )
        return "disconnected — the microscope is released; it is safe to close this page"
