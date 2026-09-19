"""
Behavioral fake ZEN API for offline tests (no wheel, no gateway, no network).
==============================================================================
Lets the whole driver run with NO ``zen_api`` wheel, NO gateway, and NO scope:
fake async service stubs + async-iterator streams + a fake channel, injected
into a REAL ``ZenClient`` (real loop thread, real ``submit``/``stream``). Only
the wire is faked -- the async->blocking bridge is exercised for real.

The responses mimic the real wheel's shapes (field names verified against the
``zen_api`` 2025.10.1 and 2026.05.1 packages): stage ``x``/``y`` in meters,
focus ``value`` in meters, objective changer ``value`` (position index) and
``objectives[].position``, experiment ``experiment_id`` / ``output_name`` /
``image_output_path`` and ``status`` objects.

For a protocol-level test over the real wheel and real TLS, see
``zenapi.simulator`` (the fake gateway) and ``tests/gateway``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from zenapi.connection.client import ZenClient

# =============================================================================
# Fake exception + status helpers
# =============================================================================


class FakeGRPCError(Exception):
    """Stand-in for grpclib.GRPCError: carries a ``.status`` with a ``.name``."""

    def __init__(self, status_name: str, message: str = ""):
        super().__init__(f"{status_name}: {message}")
        self.status = SimpleNamespace(name=status_name)
        self.message = message


def _status(running: bool, **progress) -> SimpleNamespace:
    fields = {
        "tiles_index": -1,
        "tiles_count": -1,
        "scenes_index": -1,
        "scenes_count": -1,
        "time_points_index": -1,
        "time_points_count": -1,
        "zstack_slices_index": -1,
        "zstack_slices_count": -1,
        "channels_index": 0,
        "channels_count": 1,
        "images_acquired_index": 1 if not running else 0,
        "images_count": 1,
        "is_experiment_running": running,
        "is_acquisition_running": running,
        "total_elapsed_time": None,
    }
    fields.update(progress)
    return SimpleNamespace(**fields)


def running_status(**progress) -> SimpleNamespace:
    """A status message saying an acquisition is in progress."""
    return _status(True, **progress)


def idle_status(**progress) -> SimpleNamespace:
    """A status message saying nothing is running."""
    return _status(False, **progress)


# =============================================================================
# Scope state
# =============================================================================


@dataclass
class FakeScope:
    """Mutable fake instrument state shared by all fake stubs."""

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    objective_index: int = 1
    objectives: list = field(
        default_factory=lambda: [
            {"position": 1, "name": "Plan-Apochromat 10x/0.45", "magnification": 10.0, "na": 0.45},
            {"position": 2, "name": "Plan-Apochromat 20x/0.8", "magnification": 20.0, "na": 0.8},
            {"position": 3, "name": "Plan-Apochromat 63x/1.4", "magnification": 63.0, "na": 1.4},
        ]
    )
    available_experiments: list = field(default_factory=lambda: ["ZMART_Snap", "ZMART_ZStack"])
    image_output_folder: str = ""
    # the folder above is where run_* "writes" <output_name>.czi (when set)
    loaded: dict = field(default_factory=dict)  # experiment_id -> name
    status_by_experiment: dict = field(default_factory=dict)
    active_experiment: str | None = None
    # status stream script the experiment stub replays; default = a clean run.
    status_script: list = field(
        default_factory=lambda: [running_status(), running_status(tiles_index=1), idle_status()]
    )
    surface_z_m: float = 120e-6
    best_focus_z_m: float = 135e-6
    stored_focus_m: float | None = None
    calls: list = field(default_factory=list)
    # per-op injected errors, keyed by op name ("stage_move", "focus_move",
    # "objective_move", "run_snap", "run_experiment", "stage_get", ...).
    errors: dict = field(default_factory=dict)

    def _maybe_raise(self, op: str) -> None:
        exc = self.errors.get(op)
        if exc is not None:
            raise exc

    def _write_czi(self, output_name: str) -> None:
        if self.image_output_folder:
            from pathlib import Path

            folder = Path(self.image_output_folder)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{output_name}.czi").write_bytes(b"ZISRAWFILE-fake-" + output_name.encode())


# =============================================================================
# Fake service stubs (methods mimic zen_api's stub coroutines / streams)
# =============================================================================


def _obj(**fields) -> SimpleNamespace:
    return SimpleNamespace(**fields)


class _FakeStageStub:
    def __init__(self, scope):
        self._s = scope

    async def get_position(self, req):
        self._s._maybe_raise("stage_get")
        return _obj(x=self._s.x_m, y=self._s.y_m)

    async def move_to(self, req):
        self._s._maybe_raise("stage_move")
        self._s.calls.append(("stage_move", req.x, req.y))
        if req.x is not None:
            self._s.x_m = req.x
        if req.y is not None:
            self._s.y_m = req.y
        return _obj(position_changed=True)


class _FakeFocusStub:
    def __init__(self, scope):
        self._s = scope

    async def get_position(self, req):
        self._s._maybe_raise("focus_get")
        return _obj(value=self._s.z_m)

    async def move_to(self, req):
        self._s._maybe_raise("focus_move")
        self._s.calls.append(("focus_move", req.value))
        self._s.z_m = req.value
        return _obj(position_changed=True)


class _FakeObjectiveStub:
    def __init__(self, scope):
        self._s = scope

    async def get_position(self, req):
        self._s._maybe_raise("objective_get")
        return _obj(value=self._s.objective_index)

    async def move_to(self, req):
        self._s._maybe_raise("objective_move")
        self._s.calls.append(("objective_move", req.position_index))
        self._s.objective_index = req.position_index
        return _obj()

    async def get_objectives(self, req):
        return _obj(objectives=[_obj(immersion_type=None, **o) for o in self._s.objectives])


class _FakeExperimentStub:
    def __init__(self, scope):
        self._s = scope

    async def get_available_experiments(self, req):
        return _obj(experiments=[_obj(name=n) for n in self._s.available_experiments])

    async def load(self, req):
        self._s._maybe_raise("load")
        if req.experiment_name not in self._s.available_experiments:
            raise FakeGRPCError("NOT_FOUND", f"experiment {req.experiment_name!r} not found")
        experiment_id = f"exp::{req.experiment_name}"
        self._s.loaded[experiment_id] = req.experiment_name
        return _obj(experiment_id=experiment_id)

    def _run(self, op, req):
        self._s._maybe_raise(op)
        name = req.output_name or f"auto_{len(self._s.calls)}"
        self._s.calls.append((op, req.experiment_id, name))
        self._s._write_czi(name)
        self._s.status_by_experiment[req.experiment_id] = idle_status(images_acquired_index=1)
        return _obj(output_name=name)

    async def run_snap(self, req):
        return self._run("run_snap", req)

    async def run_experiment(self, req):
        return self._run("run_experiment", req)

    async def start_experiment(self, req):
        self._s._maybe_raise("start_experiment")
        name = req.output_name or "auto"
        self._s.calls.append(("start_experiment", req.experiment_id, name))
        self._s.active_experiment = req.experiment_id
        self._s._write_czi(name)
        return _obj(output_name=name)

    async def start_live(self, req):
        self._s.calls.append(("start_live", req.experiment_id))
        self._s.active_experiment = req.experiment_id
        return _obj()

    async def stop(self, req):
        stopped = req.experiment_id or self._s.active_experiment or ""
        self._s.calls.append(("stop", stopped))
        self._s.active_experiment = None
        return _obj(experiment_id=stopped)

    async def get_status(self, req):
        self._s._maybe_raise("get_status")
        if req.experiment_id:
            return _obj(status=self._s.status_by_experiment.get(req.experiment_id, idle_status()))
        if self._s.active_experiment is None:
            raise FakeGRPCError("FAILED_PRECONDITION", "no active experiment")
        return _obj(status=running_status())

    async def get_image_output_path(self, req):
        return _obj(image_output_path=self._s.image_output_folder)

    def register_on_status_changed(self, req):
        script = list(self._s.status_script)

        async def _gen():
            for item in script:
                yield _obj(status=item)

        return _gen()


class _FakeSwAutofocusStub:
    def __init__(self, scope):
        self._s = scope

    async def find_auto_focus(self, req):
        self._s._maybe_raise("find_autofocus")
        self._s.calls.append(("find_autofocus", req.experiment_id, req.timeout))
        self._s.z_m = self._s.best_focus_z_m
        return _obj(focus_position=self._s.z_m)


class _FakeDefiniteFocusStub:
    def __init__(self, scope):
        self._s = scope

    async def find_surface(self, req):
        self._s._maybe_raise("find_surface")
        self._s.z_m = self._s.surface_z_m
        return _obj(zposition=self._s.z_m)

    async def store_focus(self, req):
        self._s.stored_focus_m = self._s.z_m
        return _obj()

    async def recall_focus(self, req):
        if self._s.stored_focus_m is None:
            raise FakeGRPCError("FAILED_PRECONDITION", "no focus stored")
        self._s.z_m = self._s.stored_focus_m
        return _obj(zposition=self._s.z_m)


# =============================================================================
# Fake messages (request builders) + channel
# =============================================================================


class FakeMessages:
    """Request builders returning simple objects the fake stubs read.

    Same method names and argument order as ``zen_runtime.RealMessages``.
    """

    def stage_get(self):
        return _obj()

    def stage_move(self, x_m, y_m):
        return _obj(x=x_m, y=y_m)

    def focus_get(self):
        return _obj()

    def focus_move(self, z_m):
        return _obj(value=z_m)

    def objective_get(self):
        return _obj()

    def objective_move(self, index):
        return _obj(position_index=index)

    def objectives_get(self):
        return _obj()

    def experiments_available(self):
        return _obj()

    def experiment_load(self, name):
        return _obj(experiment_name=name)

    def run_snap(self, experiment_id, output_name=""):
        return _obj(experiment_id=experiment_id, output_name=output_name or "")

    def run_experiment(self, experiment_id, output_name=""):
        return _obj(experiment_id=experiment_id, output_name=output_name or "")

    def start_experiment(self, experiment_id, output_name=""):
        return _obj(experiment_id=experiment_id, output_name=output_name or "")

    def start_live(self, experiment_id):
        return _obj(experiment_id=experiment_id)

    def stop(self, experiment_id=""):
        return _obj(experiment_id=experiment_id or "")

    def status_get(self, experiment_id=""):
        return _obj(experiment_id=experiment_id or "")

    def status_subscribe(self, experiment_id=""):
        return _obj(experiment_id=experiment_id or "")

    def image_output_path(self):
        return _obj()

    def find_autofocus(self, experiment_id, timeout_s=None):
        return _obj(experiment_id=experiment_id, timeout=timeout_s)

    def find_surface(self):
        return _obj()

    def store_focus(self):
        return _obj()

    def recall_focus(self):
        return _obj()


class FakeChannel:
    """Minimal channel; ``close`` is a coroutine like grpclib's."""

    async def close(self):
        return None


# =============================================================================
# Assembly
# =============================================================================


def build_fake_client(scope: FakeScope | None = None):
    """Construct a REAL ZenClient wired to fakes. Returns ``(client, scope)``.

    The caller must ``client.close()`` (the conftest fixture does this).
    """
    scope = scope or FakeScope()
    stubs = {
        "stage": _FakeStageStub(scope),
        "focus": _FakeFocusStub(scope),
        "objective": _FakeObjectiveStub(scope),
        "experiment": _FakeExperimentStub(scope),
        "sw_autofocus": _FakeSwAutofocusStub(scope),
        "definite_focus": _FakeDefiniteFocusStub(scope),
    }

    def stub_factory(key, channel, metadata):
        return stubs[key]

    client = ZenClient(
        metadata=[("control-token", "test")],
        channel_factory=FakeChannel,
        stub_factory=stub_factory,
        messages=FakeMessages(),
        default_call_timeout=5.0,
        connect_timeout=5.0,
    )
    client.runtime = {"host": "fake", "port": 0, "zen_api_version": "fake", "services": {}}
    return client, scope
