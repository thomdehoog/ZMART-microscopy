"""
Behavioral fake ZEN API for offline tests.
===========================================
Lets the whole driver run with NO ``zen_api`` wheel, NO gateway, and NO scope:
fake async service stubs + async-iterator streams + a fake channel, injected
into a REAL ``ZenClient`` (real loop thread, real ``submit``/``stream``). Only
the wire is faked -- the async->blocking bridge is exercised for real, mirroring
how the Leica ``MockLasxClient`` substitutes the client while the dispatch
backbone runs for real.

The scope state is mutable: ``move_to`` writes it, reads see it, so readback
confirmations pass. Errors and status scripts are configurable per test.

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


def running_status(**progress) -> SimpleNamespace:
    """A status item indicating an acquisition is in progress."""
    return SimpleNamespace(
        is_experiment_running=True, is_acquisition_running=True,
        tiles_index=progress.get("tiles_index"),
        images_acquired_index=progress.get("images_acquired_index"),
        zstack_slices_index=progress.get("zstack_slices_index"),
        time_points_index=None, channels_index=None,
    )


def idle_status() -> SimpleNamespace:
    """A status item indicating nothing is running."""
    return SimpleNamespace(
        is_experiment_running=False, is_acquisition_running=False,
        tiles_index=None, images_acquired_index=None, zstack_slices_index=None,
        time_points_index=None, channels_index=None,
    )


# =============================================================================
# Scope state
# =============================================================================


@dataclass
class FakeScope:
    """Mutable fake instrument state shared by all fake stubs."""

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    objective_index: int = 0
    objectives: list = field(
        default_factory=lambda: [
            {"index": 0, "name": "Plan-Apochromat 10x/0.45", "magnification": 10},
            {"index": 1, "name": "Plan-Apochromat 20x/0.8", "magnification": 20},
            {"index": 2, "name": "Plan-Apochromat 63x/1.4", "magnification": 63},
        ]
    )
    czi_path: str | None = None
    # status stream script the experiment stub replays; default = a clean run.
    status_script: list = field(
        default_factory=lambda: [running_status(), running_status(tiles_index=1), idle_status()]
    )
    # per-op injected errors, keyed by op name ("stage_move", "focus_move",
    # "objective_move", "run_snap", "run_experiment", "stage_get", ...).
    errors: dict = field(default_factory=dict)

    def _maybe_raise(self, op: str) -> None:
        exc = self.errors.get(op)
        if exc is not None:
            raise exc


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
        self._s.x_m, self._s.y_m = req.x, req.y
        return _obj(ok=True)


class _FakeFocusStub:
    def __init__(self, scope):
        self._s = scope

    async def get_position(self, req):
        self._s._maybe_raise("focus_get")
        return _obj(value=self._s.z_m)

    async def move_to(self, req):
        self._s._maybe_raise("focus_move")
        self._s.z_m = req.value
        return _obj(ok=True)


class _FakeObjectiveStub:
    def __init__(self, scope):
        self._s = scope

    async def get_position(self, req):
        self._s._maybe_raise("objective_get")
        return _obj(position_index=self._s.objective_index)

    async def move_to(self, req):
        self._s._maybe_raise("objective_move")
        self._s.objective_index = req.position_index
        return _obj(ok=True)

    async def get_objectives(self, req):
        return _obj(objectives=[_obj(**o) for o in self._s.objectives])


class _FakeExperimentStub:
    def __init__(self, scope):
        self._s = scope

    async def load(self, req):
        return _obj(experiment_id=f"exp::{req.name}")

    async def run_snap(self, req):
        self._s._maybe_raise("run_snap")
        return _obj(ok=True)

    async def run_experiment(self, req):
        self._s._maybe_raise("run_experiment")
        return _obj(output_name=req.output_name)

    async def get_image_output_path(self, req):
        return _obj(path=self._s.czi_path)

    def register_on_status_changed(self, req):
        script = list(self._s.status_script)

        async def _gen():
            for item in script:
                yield item

        return _gen()


# =============================================================================
# Fake messages (request builders) + channel
# =============================================================================


class FakeMessages:
    """Request builders returning simple objects the fake stubs read."""

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

    def experiment_load(self, name):
        return _obj(name=name)

    def run_snap(self, experiment_id):
        return _obj(experiment_id=experiment_id)

    def run_experiment(self, experiment_id, output_name):
        return _obj(experiment_id=experiment_id, output_name=output_name)

    def status_subscribe(self, experiment_id):
        return _obj(experiment_id=experiment_id)

    def image_output_path(self, output_name):
        return _obj(output_name=output_name)


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
    return client, scope
