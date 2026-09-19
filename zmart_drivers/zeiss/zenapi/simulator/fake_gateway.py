"""
The fake ZEN API gateway: a stand-in for ZEN until a real one is at hand.
=========================================================================
This server implements the ZEN API services the driver uses, on top of the
**real** service definitions from ZEISS's ``zen_api`` wheel, and serves them
over TLS with the gateway's control-token check. From the driver's side it is
indistinguishable from ZEN at the protocol level: the same request and
response messages, the same status codes, the same blocking behaviour.

Behind the services is :class:`FakeZen`, an imaginary light microscope with
an XY stage, a focus drive, an objective changer, a few saved experiments and
an image folder where every acquisition is written as a small placeholder
``.czi`` file. Its behaviour follows the ZEN API documentation:

* ``MoveTo`` on the stage or focus returns once the move is done; a target
  outside the fake's travel range is refused with ``OUT_OF_RANGE``.
* ``RunSnap`` / ``RunExperiment`` block until the acquisition is finished;
  ``StartExperiment`` returns as soon as it is running.
* ``GetStatus`` and the ``RegisterOnStatusChanged`` stream report the
  documented status fields. The stream can only be joined while the
  experiment is active (ZEN throws otherwise, and so does the fake).
* ``GetImageOutputPath`` reports the folder; the file is ``<output_name>.czi``.
* Every call must carry the gateway's control token in its metadata.
  Missing token -> ``UNAUTHENTICATED``; wrong token -> ``PERMISSION_DENIED``.
* In *supervised* mode (the ZEN default before an operator enables
  "Unsupervised API Mode") only monitoring calls are allowed; the fake then
  refuses controlling calls with the message the real gateway uses.

What is **not** simulated: images have no pixels (the ``.czi`` is a
placeholder), no optics or camera model, and the many ZEN services the driver
does not use answer ``UNIMPLEMENTED`` as an unimplemented ZEN service would.

Run it from the command line (``python -m zenapi.simulator``) or in-process
(``FakeGateway().start()``), see the driver README.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import asyncio
import configparser
import datetime as _dt
import json
import logging
import secrets
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

from .certs import ensure_certificate

log = logging.getLogger(__name__)

CONTROLLING_DENIED = (
    "Permission denied - Execution of API methods that can change the system "
    "state is currently not allowed"
)


# =============================================================================
# The imaginary microscope
# =============================================================================


@dataclass
class FakeZen:
    """State of the imaginary microscope behind the fake gateway.

    Positions are in meters, like on the wire. ``move_settle_s`` and
    ``frame_time_s`` add a little realism (moves and acquisitions take time)
    and are zero by default so tests run fast.
    """

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    # travel range, meters (ZEN does not report it; this is the fake's own)
    x_range_m: tuple[float, float] = (-0.06, 0.06)
    y_range_m: tuple[float, float] = (-0.04, 0.04)
    z_range_m: tuple[float, float] = (-0.01, 0.01)
    objective_position: int = 1
    objectives: list[dict] = field(
        default_factory=lambda: [
            {"position": 1, "name": "Plan-Apochromat 10x/0.45", "magnification": 10.0, "na": 0.45},
            {"position": 2, "name": "Plan-Apochromat 20x/0.8", "magnification": 20.0, "na": 0.8},
            {
                "position": 3,
                "name": "Plan-Apochromat 63x/1.4 Oil",
                "magnification": 63.0,
                "na": 1.4,
            },
        ]
    )
    # experiment name -> how many images a run produces (channels x z x tiles)
    experiments: dict[str, dict] = field(
        default_factory=lambda: {
            "ZMART_Snap": {"channels": 1, "zslices": 1, "tiles": 1},
            "ZMART_2CH": {"channels": 2, "zslices": 1, "tiles": 1},
            "ZMART_ZStack": {"channels": 1, "zslices": 5, "tiles": 1},
            "ZMART_Tiles": {"channels": 1, "zslices": 1, "tiles": 4},
        }
    )
    image_folder: Path = field(default_factory=lambda: Path("."))
    surface_z_m: float = 120e-6
    best_focus_z_m: float = 135e-6
    stored_focus_m: float | None = None
    move_settle_s: float = 0.0
    frame_time_s: float = 0.0
    supervised: bool = False
    # bookkeeping
    loaded: dict[str, str] = field(default_factory=dict)  # experiment_id -> name
    last_status: dict[str, dict] = field(default_factory=dict)  # experiment_id -> status dict
    active: dict[str, asyncio.Task] = field(default_factory=dict)
    subscribers: dict[str, list] = field(default_factory=dict)  # experiment_id -> [Queue]
    calls: list[tuple] = field(default_factory=list)

    def snapshot(self) -> dict:
        """A plain dict of the microscope state, for logs and tests."""
        return {
            "x_um": self.x_m * 1e6,
            "y_um": self.y_m * 1e6,
            "z_um": self.z_m * 1e6,
            "objective_position": self.objective_position,
            "loaded": dict(self.loaded),
            "active": sorted(self.active),
        }


# =============================================================================
# Service implementations on the real generated base classes
# =============================================================================


def _grpc_error(status_name: str, message: str):
    from grpclib import GRPCError
    from grpclib.const import Status

    return GRPCError(getattr(Status, status_name), message)


def _controlling(zen: FakeZen) -> None:
    """Refuse a state-changing call while the fake is in supervised API mode."""
    if zen.supervised:
        raise _grpc_error("PERMISSION_DENIED", CONTROLLING_DENIED)


def _check_range(value: float, bounds: tuple[float, float], axis: str) -> None:
    lo, hi = bounds
    if value < lo or value > hi:
        raise _grpc_error(
            "OUT_OF_RANGE",
            f"{axis} target {value * 1e6:.1f} um is outside the stage range "
            f"[{lo * 1e6:.0f}, {hi * 1e6:.0f}] um",
        )


def _stage_service(module_path: str, base_name: str, zen: FakeZen):
    """Build the XY stage service on whichever base class the installed wheel has.

    ``zen_api.hardware.v1.SimpleStageService`` (ZEN 3.14 wheel) and
    ``zen_api.lm.hardware.v2.StageService`` (ZEN 3.13 wheel) have the same
    GetPosition / MoveTo shape, so one implementation serves both.
    """
    mod = import_module(module_path)
    base = getattr(mod, f"{base_name}Base")
    get_resp = getattr(mod, f"{base_name}GetPositionResponse")
    move_resp = getattr(mod, f"{base_name}MoveToResponse")

    class _Stage(base):
        async def get_position(self, request):
            return get_resp(x=zen.x_m, y=zen.y_m)

        async def move_to(self, request):
            _controlling(zen)
            x = zen.x_m if request.x is None else float(request.x)
            y = zen.y_m if request.y is None else float(request.y)
            _check_range(x, zen.x_range_m, "X")
            _check_range(y, zen.y_range_m, "Y")
            changed = (x, y) != (zen.x_m, zen.y_m)
            zen.calls.append(("stage.move_to", x, y))
            if zen.move_settle_s:
                await asyncio.sleep(zen.move_settle_s)
            zen.x_m, zen.y_m = x, y
            return move_resp(position_changed=changed)

    _Stage.__name__ = f"Fake{base_name}"
    return _Stage()


def _focus_service(zen: FakeZen):
    hw = import_module("zen_api.lm.hardware.v2")

    class _Focus(hw.FocusServiceBase):
        async def get_position(self, request):
            return hw.FocusServiceGetPositionResponse(value=zen.z_m)

        async def move_to(self, request):
            _controlling(zen)
            z = float(request.value)
            _check_range(z, zen.z_range_m, "Z")
            changed = z != zen.z_m
            zen.calls.append(("focus.move_to", z))
            if zen.move_settle_s:
                await asyncio.sleep(zen.move_settle_s)
            zen.z_m = z
            return hw.FocusServiceMoveToResponse(position_changed=changed)

    return _Focus()


def _objective_service(zen: FakeZen):
    hw = import_module("zen_api.lm.hardware.v2")

    class _Objective(hw.ObjectiveChangerServiceBase):
        async def get_objectives(self, request):
            return hw.ObjectiveChangerServiceGetObjectivesResponse(
                objectives=[
                    hw.ObjectiveData(
                        name=o["name"],
                        na=o["na"],
                        magnification=o["magnification"],
                        position=o["position"],
                    )
                    for o in zen.objectives
                ]
            )

        async def get_position(self, request):
            return hw.ObjectiveChangerServiceGetPositionResponse(value=zen.objective_position)

        async def move_to(self, request):
            _controlling(zen)
            if request.position_index not in {o["position"] for o in zen.objectives}:
                raise _grpc_error(
                    "INVALID_ARGUMENT", f"no objective at position {request.position_index}"
                )
            zen.calls.append(("objective.move_to", request.position_index))
            if zen.move_settle_s:
                await asyncio.sleep(zen.move_settle_s)
            zen.objective_position = int(request.position_index)
            return hw.ObjectiveChangerServiceMoveToResponse()

    return _Objective()


def _status_message(acq, zen: FakeZen, *, running: bool, images_done: int, started: float):
    """Build an ``ExperimentStatus`` for one acquisition run."""
    plan = zen.experiments[zen.loaded[acq["experiment_id"]]]
    total = plan["channels"] * plan["zslices"] * plan["tiles"]
    return acq["mod"].ExperimentStatus(
        tiles_index=(images_done - 1) // (plan["channels"] * plan["zslices"])
        if plan["tiles"] > 1 and images_done
        else -1,
        tiles_count=plan["tiles"] if plan["tiles"] > 1 else -1,
        scenes_index=-1,
        scenes_count=-1,
        time_points_index=-1,
        time_points_count=-1,
        zstack_slices_index=((images_done - 1) // plan["channels"]) % plan["zslices"]
        if plan["zslices"] > 1 and images_done
        else -1,
        zstack_slices_count=plan["zslices"] if plan["zslices"] > 1 else -1,
        channels_index=(images_done - 1) % plan["channels"] if images_done else 0,
        channels_count=plan["channels"],
        images_acquired_index=images_done,
        images_count=total,
        is_experiment_running=running,
        is_acquisition_running=running,
        total_elapsed_time=_dt.timedelta(seconds=time.perf_counter() - started),
    )


def _experiment_service(zen: FakeZen):
    acq = import_module("zen_api.acquisition.v1beta")

    def _require_loaded(experiment_id: str) -> str:
        name = zen.loaded.get(experiment_id)
        if name is None:
            raise _grpc_error("NOT_FOUND", f"no loaded experiment with id {experiment_id!r}")
        return name

    def _publish(experiment_id: str, status) -> None:
        zen.last_status[experiment_id] = status
        for queue in zen.subscribers.get(experiment_id, []):
            queue.put_nowait(status)

    def _write_czi(name: str, output_name: str, images: int) -> Path:
        zen.image_folder.mkdir(parents=True, exist_ok=True)
        path = zen.image_folder / f"{output_name}.czi"
        payload = {
            "fake": "ZEN API fake gateway placeholder, not a real CZI",
            "experiment": name,
            "images": images,
            "stage_um": {"x": zen.x_m * 1e6, "y": zen.y_m * 1e6, "z": zen.z_m * 1e6},
            "objective_position": zen.objective_position,
            "written_at": time.time(),
        }
        path.write_bytes(b"ZISRAWFILE" + json.dumps(payload, indent=1).encode())
        return path

    async def _acquire(experiment_id: str, output_name: str, *, snap: bool) -> str:
        """The shared body of snap / experiment runs: frames, status, CZI."""
        name = _require_loaded(experiment_id)
        plan = zen.experiments[name]
        total = 1 if snap else plan["channels"] * plan["zslices"] * plan["tiles"]
        output_name = output_name or f"{name}_{uuid.uuid4().hex[:6]}"
        started = time.perf_counter()
        me = {"experiment_id": experiment_id, "mod": acq}
        zen.subscribers.setdefault(experiment_id, [])
        try:
            _publish(
                experiment_id,
                _status_message(me, zen, running=True, images_done=0, started=started),
            )
            for done in range(1, total + 1):
                if zen.frame_time_s:
                    await asyncio.sleep(zen.frame_time_s)
                else:
                    await asyncio.sleep(0)
                _publish(
                    experiment_id,
                    _status_message(me, zen, running=True, images_done=done, started=started),
                )
            _write_czi(name, output_name, total)
        finally:
            _publish(
                experiment_id,
                _status_message(me, zen, running=False, images_done=total, started=started),
            )
            zen.active.pop(experiment_id, None)
            for queue in zen.subscribers.pop(experiment_id, []):
                queue.put_nowait(None)  # end of stream
        return output_name

    def _start(experiment_id: str, coro) -> asyncio.Task:
        if experiment_id in zen.active:
            coro.close()  # never scheduled; closing it avoids a "never awaited" warning
            raise _grpc_error("FAILED_PRECONDITION", "this experiment is already running")
        # A fresh run starts with no status, so waiting for "started" cannot
        # be satisfied by the previous run's final status.
        zen.last_status.pop(experiment_id, None)
        task = asyncio.get_running_loop().create_task(coro)
        zen.active[experiment_id] = task
        return task

    async def _run(experiment_id: str, output_name: str, *, snap: bool) -> str:
        task = _start(experiment_id, _acquire(experiment_id, output_name, snap=snap))
        try:
            return await task
        except asyncio.CancelledError:
            raise _grpc_error("CANCELLED", "the acquisition was stopped") from None

    async def _wait_started(experiment_id: str) -> None:
        while experiment_id not in zen.last_status:
            await asyncio.sleep(0)

    class _Experiment(acq.ExperimentServiceBase):
        async def get_available_experiments(self, request):
            return acq.ExperimentServiceGetAvailableExperimentsResponse(
                experiments=[acq.ExperimentDescriptor(name=n) for n in zen.experiments]
            )

        async def get_image_output_path(self, request):
            return acq.ExperimentServiceGetImageOutputPathResponse(
                image_output_path=str(zen.image_folder)
            )

        async def load(self, request):
            if request.experiment_name not in zen.experiments:
                raise _grpc_error(
                    "NOT_FOUND", f"experiment {request.experiment_name!r} does not exist"
                )
            experiment_id = str(uuid.uuid4())
            zen.loaded[experiment_id] = request.experiment_name
            zen.calls.append(("experiment.load", request.experiment_name))
            return acq.ExperimentServiceLoadResponse(experiment_id=experiment_id)

        async def get_status(self, request):
            experiment_id = request.experiment_id
            if not experiment_id:
                if not zen.active:
                    raise _grpc_error("FAILED_PRECONDITION", "there is no active experiment")
                experiment_id = next(iter(zen.active))
            status = zen.last_status.get(experiment_id)
            if status is None:
                _require_loaded(experiment_id)
                status = acq.ExperimentStatus(is_experiment_running=False)
            return acq.ExperimentServiceGetStatusResponse(status=status)

        async def register_on_status_changed(self, request):
            experiment_id = request.experiment_id or (next(iter(zen.active), ""))
            if experiment_id not in zen.active:
                raise _grpc_error(
                    "FAILED_PRECONDITION",
                    "status notifications are only available for an active experiment",
                )
            queue: asyncio.Queue = asyncio.Queue()
            zen.subscribers.setdefault(experiment_id, []).append(queue)
            last = zen.last_status.get(experiment_id)
            if last is not None:
                yield acq.ExperimentServiceRegisterOnStatusChangedResponse(status=last)
            while True:
                status = await queue.get()
                if status is None:
                    return
                yield acq.ExperimentServiceRegisterOnStatusChangedResponse(status=status)

        async def run_snap(self, request):
            _controlling(zen)
            zen.calls.append(("experiment.run_snap", request.experiment_id, request.output_name))
            name = await _run(request.experiment_id, request.output_name, snap=True)
            return acq.ExperimentServiceRunSnapResponse(output_name=name)

        async def run_experiment(self, request):
            _controlling(zen)
            zen.calls.append(
                ("experiment.run_experiment", request.experiment_id, request.output_name)
            )
            name = await _run(request.experiment_id, request.output_name, snap=False)
            return acq.ExperimentServiceRunExperimentResponse(output_name=name)

        async def start_experiment(self, request):
            _controlling(zen)
            _require_loaded(request.experiment_id)
            output_name = request.output_name or f"{zen.loaded[request.experiment_id]}_started"
            _start(request.experiment_id, _acquire(request.experiment_id, output_name, snap=False))
            await _wait_started(request.experiment_id)
            return acq.ExperimentServiceStartExperimentResponse(output_name=output_name)

        async def start_snap(self, request):
            _controlling(zen)
            _require_loaded(request.experiment_id)
            output_name = request.output_name or f"{zen.loaded[request.experiment_id]}_snap"
            _start(request.experiment_id, _acquire(request.experiment_id, output_name, snap=True))
            await _wait_started(request.experiment_id)
            return acq.ExperimentServiceStartSnapResponse(output_name=output_name)

        async def start_live(self, request):
            _controlling(zen)
            _require_loaded(request.experiment_id)

            async def _live():
                try:
                    while True:
                        await asyncio.sleep(0.05)
                finally:
                    zen.active.pop(request.experiment_id, None)

            _start(request.experiment_id, _live())
            zen.calls.append(("experiment.start_live", request.experiment_id))
            from betterproto.lib.google.protobuf import Empty

            return Empty()

        async def start_continuous(self, request):
            return await self.start_live(request)

        async def stop(self, request):
            _controlling(zen)
            experiment_id = request.experiment_id or next(iter(zen.active), "")
            task = zen.active.get(experiment_id)
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            zen.active.pop(experiment_id, None)
            zen.calls.append(("experiment.stop", experiment_id))
            return acq.ExperimentServiceStopResponse(experiment_id=experiment_id)

    return _Experiment()


def _focus_procedures(zen: FakeZen):
    lm = import_module("zen_api.lm.acquisition.v1")

    class _SwAutofocus(lm.ExperimentSwAutofocusServiceBase):
        async def find_auto_focus(self, request):
            _controlling(zen)
            if request.experiment_id not in zen.loaded:
                raise _grpc_error("NOT_FOUND", "no loaded experiment with that id")
            zen.calls.append(("swaf.find_auto_focus", request.experiment_id, request.timeout))
            if zen.move_settle_s:
                await asyncio.sleep(zen.move_settle_s)
            zen.z_m = zen.best_focus_z_m
            return lm.ExperimentSwAutofocusServiceFindAutoFocusResponse(focus_position=zen.z_m)

    class _DefiniteFocus(lm.DefiniteFocusServiceBase):
        async def find_surface(self, request):
            _controlling(zen)
            zen.z_m = zen.surface_z_m
            zen.calls.append(("df.find_surface",))
            return lm.DefiniteFocusServiceFindSurfaceResponse(zposition=zen.z_m)

        async def store_focus(self, request):
            _controlling(zen)
            zen.stored_focus_m = zen.z_m
            return lm.DefiniteFocusServiceStoreFocusResponse()

        async def recall_focus(self, request):
            _controlling(zen)
            if zen.stored_focus_m is None:
                raise _grpc_error("FAILED_PRECONDITION", "no focus position was stored")
            zen.z_m = zen.stored_focus_m
            return lm.DefiniteFocusServiceRecallFocusResponse(zposition=zen.z_m)

        async def lock_focus(self, request):
            _controlling(zen)
            return lm.DefiniteFocusServiceLockFocusResponse()

        async def unlock_focus(self, request):
            _controlling(zen)
            return lm.DefiniteFocusServiceUnlockFocusResponse()

    return [_SwAutofocus(), _DefiniteFocus()]


def build_services(zen: FakeZen) -> list:
    """All service handlers for ``zen`` (every stage flavour the wheel has)."""
    services = []
    for module_path, base_name in (
        ("zen_api.hardware.v1", "SimpleStageService"),
        ("zen_api.lm.hardware.v2", "StageService"),
    ):
        try:
            mod = import_module(module_path)
        except ImportError:
            continue
        if hasattr(mod, f"{base_name}Base"):
            services.append(_stage_service(module_path, base_name, zen))
    services += [_focus_service(zen), _objective_service(zen), _experiment_service(zen)]
    services += _focus_procedures(zen)
    return services


# =============================================================================
# The gateway process: TLS, token check, lifecycle
# =============================================================================


class FakeGateway:
    """A fake ZEN API gateway you can start and stop from Python.

    Args:
        work_dir: where the certificate, token and image folder live (a temp
            folder when omitted). Reusing a folder reuses its certificate and
            token, like the real gateway.
        host, port: where to listen; port 0 picks a free port (tests).
        zen: the imaginary microscope; a fresh :class:`FakeZen` when omitted.
        control_token: the token clients must send; generated when omitted.

    After ``start()``: ``port``, ``cert_file`` and ``control_token`` are set,
    and ``write_config(path)`` writes a ``config.ini`` the driver can use.
    """

    def __init__(
        self,
        work_dir: str | Path | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        zen: FakeZen | None = None,
        control_token: str | None = None,
    ) -> None:
        import tempfile

        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="fake_zen_"))
        self.host = host
        self.port = port
        self.zen = zen or FakeZen()
        if not zen or self.zen.image_folder == Path("."):
            self.zen.image_folder = self.work_dir / "images"
        token_file = self.work_dir / "GlobalControlToken.txt"
        if control_token is None:
            if token_file.exists():
                control_token = token_file.read_text(encoding="utf-8").strip()
            else:
                control_token = secrets.token_urlsafe(24)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        token_file.write_text(control_token, encoding="utf-8")
        self.control_token = control_token
        self.cert_file: Path | None = None
        self._key_file: Path | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    # --- lifecycle -----------------------------------------------------------

    def start(self, *, timeout: float = 15.0) -> FakeGateway:
        """Start serving on a background thread; returns once the port is open."""
        if self._thread is not None:
            return self
        self.cert_file, self._key_file = ensure_certificate(self.work_dir, hostname=self.host)
        self._thread = threading.Thread(target=self._run, name="fake-zen-gateway", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("the fake gateway did not start in time")
        if self._error is not None:
            raise RuntimeError(f"the fake gateway failed to start: {self._error}")
        return self

    def stop(self) -> None:
        """Stop serving and join the thread. Safe to call twice."""
        if self._thread is None or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=10)
        self._thread = None
        self._loop = None
        self._ready.clear()
        self._error = None

    def __enter__(self) -> FakeGateway:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:  # noqa: BLE001 - surfaced to start()
            self._error = exc
            self._ready.set()

    async def _serve(self) -> None:
        from grpclib.events import RecvRequest, listen
        from grpclib.server import Server

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        server = Server(build_services(self.zen))
        token = self.control_token

        async def _check_token(event: RecvRequest) -> None:
            sent = event.metadata.get("control-token")
            if sent is None:
                raise _grpc_error("UNAUTHENTICATED", "control token missing")
            if sent != token:
                raise _grpc_error("PERMISSION_DENIED", "control token does not match")

        listen(server, RecvRequest, _check_token)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(str(self.cert_file), str(self._key_file))
        ssl_context.set_alpn_protocols(["h2"])
        await server.start(self.host, self.port, ssl=ssl_context)
        self.port = server._server.sockets[0].getsockname()[1]
        log.info("fake ZEN API gateway listening on %s:%d", self.host, self.port)
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            server.close()
            await server.wait_closed()

    # --- for clients ---------------------------------------------------------

    def config(self) -> dict:
        """The connection values as ``connect()`` takes them."""
        return {
            "host": self.host,
            "port": self.port,
            "cert_file": str(self.cert_file),
            "control_token": self.control_token,
        }

    def write_config(self, path: str | Path) -> Path:
        """Write a ``config.ini`` for this gateway (the same shape ZEISS uses)."""
        parser = configparser.ConfigParser()
        parser["api"] = {
            "host": self.host,
            "port": str(self.port),
            "cert_file": str(self.cert_file),
            "control-token": self.control_token,
        }
        path = Path(path)
        with path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
        return path
