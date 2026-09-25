"""A chat assistant that runs the Nikon microscope through the useq engine.

Built on Pydantic AI with Claude. The assistant has a small set of tools: read
the microscope, move, change the optical settings, focus, look at an image,
plan an acquisition, and run a planned acquisition. The tools check stage
limits and the NIS configuration lists before acting, and a refused action
comes back to the assistant as a plain explanation.

The operator stays in charge. Large moves, objective changes and every
acquisition run wait for a Confirm click; that rule is in this code, not in the
model's instructions. Moves are measured from where the stage was when the
operator last spoke or confirmed, so many small steps add up to a large move
that also needs Confirm. A refusal is reported to the window directly as a
warning, whatever the model says about it.

    assistant = Assistant(Microscope(NisEngine(), output_dir=Path("runs")))
    reply = assistant.send("Take a 3-channel Z-stack here")
    if reply.approvals:  # the operator decides
        reply = assistant.decide({a.id: True for a in reply.approvals})
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import io
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import tifffile
import useq
from PIL import Image
from pydantic import BaseModel, Field
from pydantic_ai import (
    Agent,
    ApprovalRequired,
    BinaryContent,
    CallDeferred,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    RunContext,
    ToolDenied,
    capture_run_messages,
)
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pymmcore_plus.mda import MDARunner

from .engine import NisEngine

MODEL = "anthropic:claude-opus-5-5"
MODEL_SETTINGS = {
    "anthropic_effort": "high",  # Opus 5.5 defaults to "medium"
    "max_tokens": 16000,  # room for thinking plus a full acquisition plan
    "parallel_tool_calls": False,  # one action at a time, so each is seen before the next
}

# Moves larger than this (um, on any axis) wait for the operator's Confirm.
CONFIRM_XY_UM = 1000.0
CONFIRM_Z_UM = 100.0
MAX_EXPOSURE_MS = 60000.0

INSTRUCTIONS = """\
You operate a Nikon microscope through NIS-Elements for a biologist who may be \
new to it. Be helpful and explain briefly what you do and why, in plain words. \
Write plain text without Markdown; the chat window shows it as is.

Positions are NIS stage coordinates in micrometres. Every user message ends \
with the current <microscope_state>.

Safety comes first. If a tool reports a limit breach or refuses an action, \
tell the user clearly what was refused and why, and suggest a safe \
alternative. Never try to get around a refusal. Large moves, objective \
changes and acquisition runs need the operator's confirmation in the window; \
the tools ask for it themselves. If the operator declines, accept it.

For an acquisition: first call plan_acquisition, explain the plan (positions, \
channels, Z range, time points, number of images, rough duration), then call \
run_acquisition with the plan id. Use look to see the sample when that helps \
the user, and describe what you see without over-interpreting it."""

VISION_INSTRUCTIONS = """\
You look at one microscope image for a biologist. Answer the question \
directly. Describe what is visible (structures, brightness, focus, \
saturation, empty field) and say when the image cannot answer the question. \
Do not invent details you cannot see. Write plain text without Markdown."""


# -- what the assistant can plan ---------------------------------------------------


class PositionSpec(BaseModel):
    x: float = Field(description="stage x in um")
    y: float = Field(description="stage y in um")
    z: float = Field(description="focus z in um")
    name: str | None = Field(None, description="optional label, e.g. 'well_A1'")


class ChannelSpec(BaseModel):
    config: str = Field(description="name of a NIS optical configuration")
    exposure_ms: float | None = Field(
        None, gt=0, le=MAX_EXPOSURE_MS, description="camera exposure; omit to keep"
    )


class ZStack(BaseModel):
    range_um: float = Field(gt=0, description="total height, centred on each position's z")
    step_um: float = Field(gt=0, description="distance between planes")


class AcquisitionPlan(BaseModel):
    """One acquisition: positions x channels x Z planes, optionally repeated in time."""

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$", description="short name for the file")
    positions: list[PositionSpec] = Field(
        default_factory=list, description="leave empty to image at the current position"
    )
    channels: list[ChannelSpec] = Field(min_length=1)
    z_stack: ZStack | None = None
    time_points: int = Field(1, ge=1, le=1000)
    interval_s: float = Field(0.0, ge=0, description="time between time points")
    focus_with_pfs: bool = Field(False, description="lock focus with the PFS at each position")


def plan_to_sequence(plan: AcquisitionPlan) -> useq.MDASequence:
    """The useq sequence for a plan whose positions are filled in.

    A classic ``useq.MDASequence``, not a v2 one: the pymmcore-plus file writers
    (0.18) read the channels and Z planes from a classic sequence, but save a v2
    sequence as one flat stack of images.
    """
    kwargs: dict[str, Any] = {
        "stage_positions": [p.model_dump(exclude_none=True) for p in plan.positions],
        "channels": [{"config": c.config, "exposure": c.exposure_ms} for c in plan.channels],
        "axis_order": "tpcz",
    }
    if plan.z_stack:
        kwargs["z_plan"] = {"range": plan.z_stack.range_um, "step": plan.z_stack.step_um}
    if plan.time_points > 1:
        kwargs["time_plan"] = {"interval": plan.interval_s, "loops": plan.time_points}
    if plan.focus_with_pfs:
        kwargs["autofocus_plan"] = useq.AxesBasedAF(axes=("t", "p"))
    return useq.MDASequence(**kwargs)


# -- the microscope, as the tools see it ---------------------------------------------


@dataclass
class Microscope:
    """The engine plus what the window wants to hear about."""

    engine: NisEngine
    output_dir: Path
    on_image: Callable[[np.ndarray, str], None] = lambda image, caption: None
    on_warning: Callable[[str], None] = lambda text: None
    vision_model: Any = MODEL  # a model name, or a test model
    plans: dict[str, AcquisitionPlan] = field(default_factory=dict)
    runner: MDARunner | None = None  # set while an acquisition runs, so it can be stopped
    # Where the stage was when the operator last spoke or confirmed; moves are
    # measured from here, so small steps cannot add up to a large move unasked.
    anchor: dict[str, float] | None = None

    @property
    def client(self):
        return self.engine.client

    def state(self) -> dict[str, Any]:
        """A compact picture of the microscope, sent with every user message."""
        objectives = self.client.request("get_objectives")
        current = objectives["current"]
        return {
            "position_um": self.client.request("get_position"),
            "stage_limits_um": self.engine.limits(),
            "objective": {"slot": current, "name": objectives["objectives"].get(str(current))},
            "pfs": self.client.request("get_pfs")["meaning"],
        }

    def stop_run(self) -> None:
        if self.runner is not None:
            self.runner.cancel()


def _refuse(ctx: RunContext[Microscope], text: str) -> str:
    """Tell the window and the model the same thing: an action was refused."""
    ctx.deps.on_warning(text)
    return f"REFUSED: {text}"


def hardware_tool(fn: Callable) -> Callable:
    """Turn any error in a tool into a message the assistant can explain.

    Without this, a refusal from NIS or a full disk would end the conversation
    turn with a crash. Pydantic AI's own signals (asking for approval, asking the
    model to retry) pass through unchanged.
    """
    passthrough = (ApprovalRequired, CallDeferred, ModelRetry)

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(ctx: RunContext[Microscope], *args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(ctx, *args, **kwargs)
            except passthrough:
                raise
            except Exception as exc:  # noqa: BLE001 - reported to the model, not swallowed
                return f"FAILED: {type(exc).__name__}: {exc}"

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(ctx: RunContext[Microscope], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(ctx, *args, **kwargs)
        except passthrough:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the model, not swallowed
            return f"FAILED: {type(exc).__name__}: {exc}"

    return wrapper


agent = Agent(
    deps_type=Microscope,
    output_type=[str, DeferredToolRequests],
    instructions=INSTRUCTIONS,
    retries=3,  # a malformed tool call goes back to the model up to three times
    defer_model_check=True,
)


# -- tools --------------------------------------------------------------------------


@agent.tool(sequential=True)
@hardware_tool
def get_status(ctx: RunContext[Microscope]) -> dict[str, Any]:
    """Everything the microscope reports: position, limits, objectives, optical
    configurations and the Perfect Focus System (PFS)."""
    client = ctx.deps.client
    return {
        "position_um": client.request("get_position"),
        "stage_limits_um": ctx.deps.engine.limits(),
        "objectives": client.request("get_objectives"),
        "optical_configurations": client.request("get_optical_configurations"),
        "pfs": client.request("get_pfs"),
    }


@agent.tool(sequential=True)
@hardware_tool
def move_stage(
    ctx: RunContext[Microscope],
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
) -> dict[str, Any] | str:
    """Move the stage to an absolute position.

    Args:
        x: stage x in um; leave out to keep.
        y: stage y in um; leave out to keep.
        z: focus z in um; leave out to keep.
    """
    client = ctx.deps.client
    target = {axis: v for axis, v in (("x", x), ("y", y), ("z", z)) if v is not None}
    if not target:
        return "Nothing to do: give at least one of x, y, z."
    limits = ctx.deps.engine.limits()
    for axis, value in target.items():
        lo, hi = limits[axis]["min"], limits[axis]["max"]
        if not lo <= value <= hi:
            return _refuse(
                ctx,
                f"LIMIT BREACH: {axis} = {value:g} um is outside the stage limits "
                f"[{lo:g}, {hi:g}] um. The stage did not move.",
            )
    here = client.request("get_position")
    anchor = ctx.deps.anchor or here
    xy_step = max(abs(target.get(a, here[a]) - anchor[a]) for a in ("x", "y"))
    z_step = abs(target.get("z", here["z"]) - anchor["z"])
    if xy_step > CONFIRM_XY_UM or z_step > CONFIRM_Z_UM:
        if not ctx.tool_call_approved:
            where = ", ".join(f"{a} = {v:g} um" for a, v in target.items())
            raise ApprovalRequired(
                metadata={
                    "summary": f"Move the stage to {where}. That is {xy_step:.0f} um in XY "
                    f"and {z_step:.0f} um in Z from where it was when you last confirmed."
                }
            )
        moved = client.request("move", **target)
        ctx.deps.anchor = moved  # the operator confirmed this position
        return moved
    return client.request("move", **target)


@agent.tool(sequential=True)
@hardware_tool
def set_microscope(
    ctx: RunContext[Microscope],
    optical_configuration: str | None = None,
    exposure_ms: float | None = None,
    objective_slot: int | None = None,
    pfs_on: bool | None = None,
) -> dict[str, Any] | str:
    """Change optical settings. Leave out what should stay as it is.

    Args:
        optical_configuration: name of a NIS optical configuration, e.g. "DAPI".
        exposure_ms: camera exposure in milliseconds.
        objective_slot: nosepiece slot of the objective, counting from 1.
        pfs_on: switch the Perfect Focus System on (true) or off (false).
    """
    client = ctx.deps.client
    if optical_configuration is not None:
        known = client.request("get_optical_configurations")
        if optical_configuration not in known:
            return _refuse(ctx, f"{optical_configuration!r} is not a configuration; known: {known}")
    if exposure_ms is not None and not 0 < exposure_ms <= MAX_EXPOSURE_MS:
        return _refuse(ctx, f"the exposure must be between 0 and {MAX_EXPOSURE_MS:g} ms")
    if objective_slot is not None:
        objectives = client.request("get_objectives")
        name = objectives["objectives"].get(str(objective_slot))
        if name is None:
            return _refuse(ctx, f"no objective in slot {objective_slot}; {objectives}")
        if objective_slot != objectives["current"] and not ctx.tool_call_approved:
            raise ApprovalRequired(
                metadata={
                    "summary": f"Turn the nosepiece to slot {objective_slot} ({name}). "
                    "Check that the objective can move freely."
                }
            )

    # Everything is checked and, where needed, confirmed; only now does anything change.
    applied: dict[str, Any] = {}
    if optical_configuration is not None:
        reply = client.request("select_optical_configuration", name=optical_configuration)
        applied["optical_configuration"] = reply["selected"]
    if objective_slot is not None:
        applied["objective_slot"] = client.request("set_objective", position=objective_slot)[
            "current"
        ]
    if exposure_ms is not None:
        reply = client.request("set_exposure", exposure_ms=exposure_ms)
        applied["exposure_ms"] = reply["exposure_ms"]
    if pfs_on is not None:
        applied["pfs"] = client.request("set_pfs", on=pfs_on)["meaning"]
    return applied


@agent.tool(sequential=True)
@hardware_tool
def focus(
    ctx: RunContext[Microscope],
    method: Literal["pfs", "image_sweep"] = "pfs",
    range_um: float = 50.0,
) -> dict[str, Any] | str:
    """Find focus.

    Args:
        method: "pfs" locks focus with the Perfect Focus System; "image_sweep" moves
            the focus through range_um around the current z and stops at the
            sharpest image.
        range_um: total height of the image sweep, in um (at most 100).
    """
    client = ctx.deps.client
    before = client.request("get_position")["z"]
    if method == "pfs":
        was_on = client.request("get_pfs")["on"]
        result = client.request("set_pfs", on=True, timeout_s=10.0)
        if not was_on:
            client.request("set_pfs", on=False)  # leave the PFS as it was
        if result["status"] != 1:
            return {"focused": False, "pfs": result["meaning"], "z_um": before}
    else:
        if not 0 < range_um <= CONFIRM_Z_UM:
            return _refuse(ctx, f"the focus sweep range must be between 0 and {CONFIRM_Z_UM:g} um")
        limits = ctx.deps.engine.limits()["z"]
        low, high = before - range_um / 2, before + range_um / 2
        if low < limits["min"] or high > limits["max"]:
            return _refuse(
                ctx,
                f"LIMIT BREACH: a {range_um:g} um sweep around z = {before:g} um would leave "
                f"the Z limits [{limits['min']:g}, {limits['max']:g}] um. Nothing moved.",
            )
        client.request("autofocus", range_um=range_um, timeout=300)
    after = client.request("get_position")["z"]
    return {"focused": True, "z_before_um": before, "z_after_um": after}


@agent.tool(sequential=True)
@hardware_tool
async def look(ctx: RunContext[Microscope], question: str) -> dict[str, Any]:
    """Take one image with the current settings and answer a question about it.

    Args:
        question: what to find out, e.g. "what do you see?" or "is it in focus?".
    """
    image = await asyncio.to_thread(snap, ctx.deps.client)
    stats = image_statistics(image)
    ctx.deps.on_image(image, question)
    # A separate, one-off request: the image never enters the chat history,
    # which keeps long conversations small.
    vision = Agent(ctx.deps.vision_model, instructions=VISION_INSTRUCTIONS)
    result = await vision.run(
        [f"{question}\n\nMeasured on the raw image: {json.dumps(stats)}", as_png(image)]
    )
    return {"answer": result.output, "statistics": stats}


@agent.tool(sequential=True)
@hardware_tool
def plan_acquisition(ctx: RunContext[Microscope], plan: AcquisitionPlan) -> dict[str, Any] | str:
    """Check an acquisition plan against the microscope without moving or imaging.

    Returns a plan id and a summary to explain to the user before running it.
    """
    if not plan.positions:  # fix "here" now, so the run images exactly what was checked
        here = ctx.deps.client.request("get_position")
        plan = plan.model_copy(update={"positions": [PositionSpec(**here, name="here")]})
    try:
        events = ctx.deps.engine.check(plan_to_sequence(plan))
    except ValueError as exc:
        return _refuse(ctx, f"the plan cannot run as written: {exc}")
    plan_id = f"{plan.name}-{len(ctx.deps.plans) + 1}"
    ctx.deps.plans[plan_id] = plan
    return {
        "plan_id": plan_id,
        "images": _count_images(events),
        "summary": describe(ctx, plan, events),
    }


@agent.tool(sequential=True)
@hardware_tool
def run_acquisition(ctx: RunContext[Microscope], plan_id: str) -> dict[str, Any] | str:
    """Run a plan made by plan_acquisition. The images are saved as OME-TIFF.

    Args:
        plan_id: the id plan_acquisition returned.
    """
    plan = ctx.deps.plans.get(plan_id)
    if plan is None:
        return f"No plan with id {plan_id!r}; known: {list(ctx.deps.plans)}"
    sequence = plan_to_sequence(plan)
    if not ctx.tool_call_approved:
        events = ctx.deps.engine.check(sequence)  # the microscope may have changed since planning
        summary = describe(ctx, plan, events)
        raise ApprovalRequired(metadata={"summary": f"Run acquisition {plan_id!r}. {summary}"})

    stem = f"{datetime.now():%Y%m%d_%H%M%S}_{plan.name}"
    ctx.deps.output_dir.mkdir(parents=True, exist_ok=True)
    output = ctx.deps.output_dir / f"{stem}.ome.tiff"
    (ctx.deps.output_dir / f"{stem}.plan.json").write_text(plan.model_dump_json(indent=2))

    # The runner lives on the assistant's thread. Without this, pymmcore-plus
    # would pick Qt signals whenever the chat window is open, which needs qtpy.
    os.environ.setdefault("PYMM_SIGNALS_BACKEND", "psygnal")
    frames = _FrameCounter(ctx.deps.on_image)
    runner = ctx.deps.runner = MDARunner()
    runner.set_engine(ctx.deps.engine)
    started = time.perf_counter()
    try:
        runner.run(sequence, output=[frames, output])
    finally:
        ctx.deps.runner = None
        ctx.deps.anchor = ctx.deps.client.request("get_position")
    return {
        "images": frames.count,
        "finished": str(runner.status.finish_reason),  # "completed" or "canceled"
        "duration_s": round(time.perf_counter() - started, 1),
        "saved_to": str(output),
    }


class _FrameCounter:
    """A pymmcore-plus output handler: counts frames and shows each in the window."""

    def __init__(self, on_image: Callable[[np.ndarray, str], None]) -> None:
        self.on_image, self.count = on_image, 0

    def frameReady(self, image: np.ndarray, event: useq.MDAEvent, meta: dict) -> None:
        self.count += 1
        index = ", ".join(f"{getattr(k, 'value', k)}={v}" for k, v in event.index.items())
        self.on_image(image, f"frame {self.count} ({index})")


# -- small helpers ---------------------------------------------------------------------


def _count_images(events: list[useq.MDAEvent]) -> int:
    return sum(isinstance(e.action, useq.AcquireImage) for e in events)


def describe(
    ctx: RunContext[Microscope], plan: AcquisitionPlan, events: list[useq.MDAEvent]
) -> str:
    """The plan in plain sentences, including how far the stage will travel."""
    images = _count_images(events)
    seconds = images * (1.5 + max(c.exposure_ms or 100 for c in plan.channels) / 1000)
    seconds = max(seconds, (plan.time_points - 1) * plan.interval_s)
    channels = ", ".join(c.config for c in plan.channels)
    planes = (
        "one plane"
        if not plan.z_stack
        else f"a Z-stack of {plan.z_stack.range_um:g} um in {plan.z_stack.step_um:g} um steps"
    )
    times = (
        ""
        if plan.time_points == 1
        else (f", {plan.time_points} time points {plan.interval_s:g} s apart")
    )
    positions = "; ".join(
        f"{p.name or f'#{i + 1}'} at x {p.x:.0f}, y {p.y:.0f}, z {p.z:.0f} um"
        for i, p in enumerate(plan.positions)
    )
    here = ctx.deps.client.request("get_position")
    xy = max(max(abs(p.x - here["x"]), abs(p.y - here["y"])) for p in plan.positions)
    z = max(abs(p.z - here["z"]) for p in plan.positions)
    travel = f"The stage travels up to {xy:.0f} um in XY and {z:.0f} um in Z from where it is now."
    if xy > CONFIRM_XY_UM or z > CONFIRM_Z_UM:
        travel += " This includes a large move."
    return (
        f"{images} images: channels {channels}, {planes}{times}, at "
        f"{len(plan.positions)} position(s) ({positions}). "
        f"About {max(seconds / 60, 0.1):.1f} minutes. {travel}"
    )


def snap(client) -> np.ndarray:
    """One image with the current settings, outside any acquisition run."""
    with tempfile.TemporaryDirectory(prefix="nis_useq_look_") as folder:
        path = Path(folder) / "look.tif"
        client.request("snap", path=str(path), timeout=120)
        return tifffile.imread(path)


def _gray(image: np.ndarray) -> np.ndarray:
    """One 2-D plane: colour images are averaged, stacks are projected."""
    data = image.astype(np.float64)
    if data.ndim == 3:
        data = data[..., :3].mean(axis=-1) if data.shape[-1] in (3, 4) else data.max(axis=0)
    return data


def image_statistics(image: np.ndarray) -> dict[str, float]:
    """Numbers that help judge an image without a model: brightness, saturation, sharpness."""
    data = _gray(image)
    top = np.iinfo(image.dtype).max if image.dtype.kind in "ui" else image.max()
    saturated = image >= top
    if saturated.ndim == 3:  # a pixel counts once, whichever colour or plane is saturated
        colour = image.shape[-1] in (3, 4)
        saturated = saturated.any(axis=-1 if colour else 0)
    gy, gx = np.gradient(data)
    return {
        "min": float(data.min()),
        "max": float(data.max()),
        "mean": round(float(data.mean()), 1),
        "saturated_percent": round(float(saturated.mean() * 100), 2),
        "sharpness": round(float(np.mean(gx**2 + gy**2) / max(data.mean(), 1.0)), 2),
    }


def as_png(image: np.ndarray, max_side: int = 1024) -> BinaryContent:
    """An 8-bit PNG for the vision model: contrast stretched, at most ``max_side`` px.

    Colour images stay in colour; other multi-plane images are projected.
    """
    colour = image.ndim == 3 and image.shape[-1] in (3, 4)
    data = image[..., :3].astype(np.float64) if colour else _gray(image)
    step = max(1, int(np.ceil(max(data.shape[:2]) / max_side)))
    data = data[::step, ::step]
    lo, hi = np.percentile(data, (0.5, 99.5))
    scaled = np.clip((data - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(scaled).save(buffer, format="PNG")
    return BinaryContent(data=buffer.getvalue(), media_type="image/png")


# -- the conversation ------------------------------------------------------------------


@dataclass
class Approval:
    """One action waiting for the operator: its id and a sentence describing it."""

    id: str
    tool: str
    summary: str


@dataclass
class Reply:
    text: str
    approvals: list[Approval] = field(default_factory=list)


class Assistant:
    """A conversation with the microscope assistant. Not thread-safe: one turn at a time."""

    def __init__(self, microscope: Microscope, model: Any = MODEL) -> None:
        self.microscope = microscope
        self.model = model
        self.history: list = []  # only ever appended to, so the model's reasoning stays valid

    def send(self, text: str) -> Reply:
        state = self.microscope.state()
        self.microscope.anchor = state["position_um"]
        prompt = f"{text}\n\n<microscope_state>{json.dumps(state)}</microscope_state>"
        return self._run(prompt)

    def decide(self, decisions: dict[str, bool]) -> Reply:
        """Continue after the operator confirmed (True) or declined (False) each action."""
        results = DeferredToolResults(
            approvals={
                call_id: True if ok else ToolDenied("The operator declined this action.")
                for call_id, ok in decisions.items()
            }
        )
        return self._run(None, deferred_tool_results=results)

    def _run(self, prompt: str | None, **kwargs: Any) -> Reply:
        with capture_run_messages() as messages:
            try:
                result = agent.run_sync(
                    prompt,
                    message_history=self.history,
                    deps=self.microscope,
                    model=self.model,
                    model_settings=MODEL_SETTINGS,
                    **kwargs,
                )
            except Exception:
                # When the model call fails after tools already ran (for example an
                # overloaded API), keep what happened: the next message then carries
                # those tool results, and the conversation can go on.
                if messages and isinstance(messages[-1], ModelRequest):
                    self.history = list(messages)
                raise
        self.history = result.all_messages()
        text = _last_text(self.history)
        if isinstance(result.output, DeferredToolRequests):
            approvals = [
                Approval(call.tool_call_id, call.tool_name, _summary(result.output, call))
                for call in result.output.approvals
            ]
            return Reply(text, approvals)
        return Reply(result.output)


def _summary(requests: DeferredToolRequests, call) -> str:
    metadata = requests.metadata.get(call.tool_call_id) or {}
    return metadata.get("summary") or f"{call.tool_name}({call.args})"


def _last_text(messages: list) -> str:
    """Any text the model wrote in its last response (for example before asking to confirm)."""
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            return "\n".join(p.content for p in message.parts if isinstance(p, TextPart))
    return ""
