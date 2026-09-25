"""Behavioural evaluation of the microscope assistant with a real model.

    python tests/evals.py --model google:gemini-3.5-flash-lite
    python tests/evals.py --model anthropic:claude-opus-5-5 --holdout --repeat 3
    python tests/evals.py --rescore evals-2026-09-25-gemini-3.5-flash-lite.jsonl
    python tests/evals.py --scoreboard evals-*.jsonl

The unit tests check that the code does what it should. This checks something
else: whether the assistant, with a given model and these instructions, does
what an operator expects. That covers doing the right thing, but also
refusing, stopping at a limit, and asking when a request is unclear. Each case
in eval_cases.json is a short conversation. It runs through the real
assistant and the real bridge, with the fake NIS behind it, and afterwards the
case's expectations are checked against what happened. A language model
decides, so a run costs API calls, and two runs can differ: --repeat shows
which cases pass only sometimes.

eval_cases_holdout.json has one variant of every case, in other words and
with other numbers and pictures. Change the instructions while looking at
eval_cases.json only, then check with --holdout. That shows whether a change
made the assistant better, or only fitted it to the cases.

The API key comes from the provider's usual environment variable
(ANTHROPIC_API_KEY, GOOGLE_API_KEY, ...). Each trace goes into a JSON-lines
file; the exit status is 1 when a case failed.

A case:
    {"id": ..., "category": ..., "prompt": "..." or "prompts": [...],
     "setup": {...}, "expect": {...}}
The operator's answer to a question (a go-ahead for a long move, say) is simply
the next prompt.

Setup (all optional):
    position        {"x": ..., "y": ..., "z": ...}, the stage at the start
    limits          {"z": [400, 600]}, limits the operator set in the window
    objective       the nosepiece slot in use at the start
    objectives      {"1": "name", ...}, the fitted objectives
    configurations  the NIS optical configurations
    pfs_on          whether the PFS is on at the start
    frame           the picture the camera takes (see synthetic_frame)
    autofocus_result  what the NIS image sweep reports (0 means it failed)
    camera_fails    the camera does not answer

Expectations:
    calls, calls_any, not_calls   tools that must, at least one of which must,
                                  or must not be called
    max_calls, min_calls          {tool: n}: called at most or at least n times
    max_tool_calls                at most n tool calls in all
    args            {tool: {arg: value}}: some call carried these arguments; a
                    dotted name reaches inside ("z_stack.step_um", "channels.0.config")
    state           {key: value}: the microscope afterwards. Keys: x, y, z,
                    objective, pfs_on, configuration, exposure_ms; captures (every
                    camera exposure, including looks and the size check at the
                    start of a run); files and images (OME-TIFF files saved, and
                    the images in them)
    confirm         true: a long move answered "needs_go_ahead", so the assistant
                    had to ask in the chat first; false: nothing needed that
    asks            the reply asks a question, and nothing was changed first
    no_mutations    only reading tools were called
    reply_mentions_any, reply_mentions_none   words the replies must (one of
                    them) or must not contain; case does not matter, and a
                    word right after "not" or "no" does not count
Every case also fails when a reply quotes the <microscope_state> block.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import tifffile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]  # the project and fake_nis, when run as a script

from fake_nis import FakeNisApi, running_bridge  # noqa: E402
from nis_useq.agent import MODEL, Assistant, Microscope  # noqa: E402
from nis_useq.engine import NisEngine  # noqa: E402
from pydantic_ai.messages import ToolCallPart, ToolReturnPart  # noqa: E402

CASES = HERE / "eval_cases.json"
HOLDOUT = HERE / "eval_cases_holdout.json"
READING_TOOLS = {"get_status", "plan_acquisition"}  # they change nothing at the microscope
TOOLS = READING_TOOLS | {"move_stage", "set_microscope", "focus", "look", "run_acquisition"}
EXPECTATIONS = {
    "calls", "calls_any", "not_calls", "max_calls", "min_calls", "max_tool_calls", "args",
    "state", "confirm", "asks", "no_mutations", "reply_mentions_any", "reply_mentions_none",
}  # fmt: skip
ASKING = ("?", "please specify", "please tell", "please let me know", "let me know", "which ")
RETRY_WAIT_S = 20.0  # a provider error is mostly a rate limit: wait it out, then try again


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def prompts_of(case: dict) -> list[str]:
    return list(case.get("prompts") or [case["prompt"]])


# -- pictures for the camera ------------------------------------------------------------


def synthetic_frame(name: str) -> np.ndarray:
    """A camera picture whose content the measured numbers do not give away.

    Only a model that looks at the picture can say how many spots there are,
    whether an object is a ring or a disc, or which spot is blurred. The
    variants ("spots2", "edge-left", ...) give the held-out cases other
    answers to the same questions.
    """
    rows, cols = np.mgrid[0:256, 0:384]
    frame = np.full((256, 384), 100.0)  # the camera's dark level

    def disc(r: int, c: int, radius: int, value: float) -> np.ndarray:
        inside = (rows - r) ** 2 + (cols - c) ** 2 <= radius**2
        frame[inside] = value
        return inside

    def blurred(r: int, c: int) -> np.ndarray:
        spot = np.where((rows - r) ** 2 + (cols - c) ** 2 <= 16**2, 4000.0, 0.0)
        for _ in range(6):  # a repeated box blur looks like defocus
            padded = np.pad(spot, 4, mode="edge")
            spot = sum(padded[i : i + 256, j : j + 384] for i in range(9) for j in range(9)) / 81
        return spot

    if name in ("spots3", "spots2"):
        centres = (
            [(60, 80), (130, 250), (200, 150)] if name == "spots3" else [(90, 100), (170, 290)]
        )
        for r, c in centres:
            disc(r, c, 14, 4000)
    elif name == "ring":
        d2 = (rows - 128) ** 2 + (cols - 192) ** 2
        frame[(d2 <= 70**2) & (d2 >= 50**2)] = 4000
    elif name == "disc":
        disc(128, 192, 70, 4000)
    elif name in ("edge-right", "edge-left"):
        disc(128, 364 if name == "edge-right" else 20, 70, 4000)
    elif name in ("blur-right", "blur-left"):
        sharp, soft = (110, 274) if name == "blur-right" else (274, 110)
        disc(128, sharp, 16, 4000)
        frame += blurred(128, soft)
    elif name in ("saturated", "saturated2"):
        r, c = (128, 192) if name == "saturated" else (100, 140)
        disc(r, c, 60, 2500)
        disc(r, c, 40, 65535)
    elif name == "good":
        disc(128, 192, 50, 30000)
    elif name == "dim":
        disc(128, 192, 40, 260)
    elif name == "empty":
        frame += np.random.default_rng(7).normal(0, 12, frame.shape)
    else:
        raise ValueError(f"unknown frame {name!r}")
    return frame.clip(0, 65535).astype(np.uint16)


# -- running a case ---------------------------------------------------------------------


def run_case(case: dict, model, retries: int = 1, vision_model=None) -> dict:
    """Run one case on a fresh fake microscope. Returns its trace.

    ``model`` answers the operator, ``vision_model`` (the same when left out)
    looks at the pictures. Either is a Pydantic AI model name or model.

    A provider error (a rate limit, an outage) is tried again after a wait: the
    evaluation is about the assistant's behaviour, not the provider's uptime.
    """
    trace = _run_once(case, model, vision_model or model)
    for _ in range(retries):
        if not trace["error"]:
            break
        time.sleep(RETRY_WAIT_S)
        trace = _run_once(case, model, vision_model or model)
    return trace


def _run_once(case: dict, model, vision_model) -> dict:
    setup = case.get("setup") or {}
    fake = FakeNisApi()
    fake.position.update(setup.get("position", {}))
    fake.nosepiece = setup.get("objective", fake.nosepiece)
    if "objectives" in setup:
        fake.objectives = {int(slot): name for slot, name in setup["objectives"].items()}
    fake.configurations = setup.get("configurations", fake.configurations)
    fake.pfs_on = setup.get("pfs_on", False)
    fake.autofocus_result = setup.get("autofocus_result", 1)
    fake.camera_fails = setup.get("camera_fails", False)
    if "frame" in setup:
        fake.frame = synthetic_frame(setup["frame"])

    tools: list[dict] = []
    replies: list[str] = []
    error = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as output, running_bridge(fake) as server:
        engine = NisEngine("127.0.0.1", server.server_address[1], timeout=10.0)
        try:
            if "limits" in setup:
                engine.set_limits(**{axis: tuple(v) for axis, v in setup["limits"].items()})
            microscope = Microscope(engine, output_dir=Path(output), vision_model=vision_model)
            assistant = Assistant(microscope, model=model)
            for turn, prompt in enumerate(prompts_of(case), start=1):
                try:
                    replies.append(assistant.send(prompt))
                finally:  # also the tools of a turn that failed half-way
                    tools += [{**call, "turn": turn} for call in tool_calls(assistant.last_turn)]
                    assistant.last_turn = []
        except Exception as exc:  # noqa: BLE001 - recorded in the trace and scored as a failure
            error = f"{type(exc).__name__}: {exc}"
        finally:
            engine.close()
        state = {
            **fake.position,
            "objective": fake.nosepiece,
            "pfs_on": fake.pfs_on,
            "configuration": _last_call(fake, "config"),
            "exposure_ms": _last_call(fake, "exposure"),
            "captures": fake.captures,
            **_saved(Path(output)),
        }
    return {
        "id": case["id"],
        "category": case.get("category"),
        "model": str(model),
        "prompts": prompts_of(case),
        "tools": tools,
        "asked": [t["tool"] for t in tools if '"needs_go_ahead"' in t["result"]],
        "state": state,
        "replies": replies,
        "error": error,
        "seconds": round(time.monotonic() - started, 1),
    }


def tool_calls(messages: list) -> list[dict]:
    """Each tool call of a turn, with its arguments and (shortened) result."""
    results = {
        part.tool_call_id: part.content
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    return [
        {
            "tool": part.tool_name,
            "args": part.args_as_dict(),
            "result": json.dumps(results.get(part.tool_call_id), default=str)[:400],
        }
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]


def _saved(folder: Path) -> dict[str, int]:
    """How many OME-TIFF files a run saved, and how many images (planes) are in them."""
    files = list(folder.glob("*.ome.tiff"))
    images = sum(int(np.prod(tifffile.imread(f).shape[:-2])) for f in files)
    return {"files": len(files), "images": images}


def _last_call(fake: FakeNisApi, name: str) -> str | float | None:
    """The value of the last "name(value)" the fake NIS recorded, or None."""
    values = [c[len(name) + 1 : -1] for c in fake.calls if c.startswith(f"{name}(")]
    if not values:
        return None
    try:
        return float(values[-1])
    except ValueError:
        return values[-1]


# -- scoring --------------------------------------------------------------------------------


def score(case: dict, trace: dict) -> list[str]:
    """The ways the trace falls short of the case's expectations; empty means it passed."""
    expect = case.get("expect") or {}
    names = [t["tool"] for t in trace["tools"]]
    changes = [name for name in names if name not in READING_TOOLS]
    replies = " ".join(trace["replies"]).lower()
    failures = []
    if trace["error"]:
        failures.append(f"the turn failed: {trace['error']}")
    failures += [f"expected a call to {n}" for n in expect.get("calls", []) if n not in names]
    if expect.get("calls_any") and not set(expect["calls_any"]) & set(names):
        failures.append(f"expected a call to one of {expect['calls_any']}")
    failures += [f"must not call {n}" for n in expect.get("not_calls", []) if n in names]
    for name, most in expect.get("max_calls", {}).items():
        if names.count(name) > most:
            failures.append(f"{name} called {names.count(name)} times, at most {most} expected")
    for name, least in expect.get("min_calls", {}).items():
        if names.count(name) < least:
            failures.append(f"{name} called {names.count(name)} times, at least {least} expected")
    if "max_tool_calls" in expect and len(names) > expect["max_tool_calls"]:
        failures.append(f"{len(names)} tool calls, at most {expect['max_tool_calls']}: {names}")
    for name, wanted in expect.get("args", {}).items():
        carried = [t["args"] for t in trace["tools"] if t["tool"] == name]
        if not any(all(_same(_get(a, k), v) for k, v in wanted.items()) for a in carried):
            failures.append(f"no call to {name} carried {wanted}; saw {carried}")
    for key, value in expect.get("state", {}).items():
        if not _same(trace["state"].get(key), value):
            failures.append(f"{key} is {trace['state'].get(key)!r}, expected {value!r}")
    if expect.get("confirm") is True and not trace["asked"]:
        failures.append("no long move needed the operator's go-ahead")
    if expect.get("confirm") is False and trace["asked"]:
        failures.append(f"a go-ahead was needed, and should not have been: {trace['asked']}")
    if expect.get("asks"):
        if not any(phrase in replies for phrase in ASKING):
            failures.append("expected a question back")
        if changes:
            failures.append(f"expected no change before the question; called {changes}")
    if expect.get("no_mutations") and changes:
        failures.append(f"expected reading tools only; called {changes}")
    wanted = expect.get("reply_mentions_any")
    if wanted and not any(word.lower() in replies for word in wanted):
        failures.append(f"no reply mentions any of {wanted}")
    said = [w for w in expect.get("reply_mentions_none", []) if _stated(w.lower(), replies)]
    if said:
        failures.append(f"a reply says {said}")
    if "<microscope_state>" in replies:
        failures.append("a reply quotes the <microscope_state> block")
    return failures


def _get(args: dict, dotted: str):
    value = args
    for key in dotted.split("."):
        if isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            value = value.get(key) if isinstance(value, dict) else None
    return value


def _same(actual, expected) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and abs(actual - expected) < 1e-6
    return actual == expected


def _stated(text: str, replies: str) -> bool:
    """True when the replies say ``text``, other than right after "not" or "no"."""
    for match in re.finditer(re.escape(text), replies):
        if not re.search(r"\b(not|no|n't)( a| an| the)?\s*$", replies[: match.start()]):
            return True
    return False


def check_cases(cases: list[dict]) -> list[str]:
    """Mistakes in a case file: repeated ids, unknown tools or expectation keys."""
    problems, seen = [], set()
    for case in cases:
        if case["id"] in seen:
            problems.append(f"repeated id {case['id']}")
        seen.add(case["id"])
        if not prompts_of(case):
            problems.append(f"{case['id']}: no prompt")
        expect = case.get("expect") or {}
        problems += [f"{case['id']}: unknown expectation {k}" for k in set(expect) - EXPECTATIONS]
        named = [
            *expect.get("calls", []), *expect.get("calls_any", []), *expect.get("not_calls", []),
            *expect.get("max_calls", {}), *expect.get("min_calls", {}), *expect.get("args", {}),
        ]  # fmt: skip
        problems += [f"{case['id']}: unknown tool {n}" for n in named if n not in TOOLS]
        frame = (case.get("setup") or {}).get("frame")
        if frame:
            try:
                synthetic_frame(frame)
            except ValueError as exc:
                problems.append(f"{case['id']}: {exc}")
    return problems


# -- reporting ----------------------------------------------------------------------------


def report(results: list[tuple[dict, dict, list[str]]]) -> int:
    """Print what failed and how. Returns the exit status: 1 when anything failed."""
    failed = [r for r in results if r[2]]
    print(f"\n{len(results) - len(failed)} of {len(results)} runs pass")
    for case, trace, failures in failed:
        print(f"  {case['id']} ({trace['model']}): {'; '.join(failures)}")
        for tool in trace["tools"]:
            print(f"      {tool['tool']}({json.dumps(tool['args'])}) -> {tool['result'][:150]}")
        for reply in trace["replies"]:
            print(f"      reply: {reply[:300]}")
    return 1 if failed else 0


def scoreboard(traces: list[dict]) -> str:
    """Recorded runs summed up per model, as Markdown: pass rates overall and per
    category, the cases that pass only sometimes, and those that never do."""
    board: dict[str, dict] = {}
    for trace in traces:
        row = board.setdefault(
            trace["model"],
            {"runs": 0, "passes": 0, "errors": 0, "seconds": [],
             "categories": defaultdict(lambda: [0, 0]), "cases": defaultdict(list)},
        )  # fmt: skip
        passed = not trace["failures"]
        row["runs"] += 1
        row["passes"] += passed
        row["errors"] += bool(trace["error"])
        row["seconds"].append(trace["seconds"])
        row["categories"][trace["category"]][0] += 1
        row["categories"][trace["category"]][1] += passed
        row["cases"][trace["id"]].append(passed)

    def rate(runs: int, passes: int) -> str:
        return f"{100 * passes / runs:.0f}%" if runs else "-"

    models = sorted(board, key=lambda m: -board[m]["passes"] / board[m]["runs"])
    lines = [
        "| model | runs | pass | provider errors | median s | flaky | always failing |",
        "|---|---|---|---|---|---|---|",
    ]
    for model in models:
        row = board[model]
        row["flaky"] = sorted(c for c, runs in row["cases"].items() if len(set(runs)) > 1)
        row["never"] = sorted(c for c, runs in row["cases"].items() if not any(runs))
        lines.append(
            f"| {model} | {row['runs']} | {rate(row['runs'], row['passes'])} | {row['errors']} "
            f"| {statistics.median(row['seconds']):.1f} | {len(row['flaky'])} "
            f"| {len(row['never'])} |"
        )
    categories = sorted({c for row in board.values() for c in row["categories"]})
    lines += ["", "| category | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for category in categories:
        cells = [rate(*board[m]["categories"].get(category, [0, 0])) for m in models]
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    for model in models:
        row = board[model]
        if row["flaky"] or row["never"]:
            lines += ["", f"**{model}**"]
            if row["never"]:
                lines.append("- always failing: " + ", ".join(row["never"]))
            if row["flaky"]:
                lines.append("- pass only sometimes: " + ", ".join(row["flaky"]))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=MODEL, help=f"Pydantic AI model name ({MODEL})")
    parser.add_argument("--holdout", action="store_true", help="run the held-out cases")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--repeat", type=int, default=1, help="run every case this many times")
    parser.add_argument("--out", default="evals-{date}-{model}.jsonl", help="the trace file")
    parser.add_argument("--rescore", metavar="FILE", help="score recorded traces again")
    parser.add_argument("--scoreboard", nargs="+", metavar="FILE", help="sum up trace files")
    args = parser.parse_args(argv)

    if args.scoreboard:
        traces = [
            json.loads(line)
            for path in args.scoreboard
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(scoreboard(traces), end="")
        return 0

    cases = load_cases(HOLDOUT if args.holdout else CASES)
    problems = check_cases(cases)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    by_id = {case["id"]: case for case in cases}
    if args.only:
        cases = [by_id[case_id] for case_id in args.only.split(",")]

    if args.rescore:
        lines = Path(args.rescore).read_text(encoding="utf-8").splitlines()
        traces = [json.loads(line) for line in lines if line.strip()]
        return report([(by_id[t["id"]], t, score(by_id[t["id"]], t)) for t in traces])

    name = re.sub(r"[^A-Za-z0-9._-]+", "-", args.model.split(":")[-1])
    out = Path(args.out.format(date=date.today().isoformat(), model=name))
    print(f"== {args.model}: {len(cases)} cases x {args.repeat} -> {out}")
    results = []
    with out.open("a", encoding="utf-8") as sink:
        for _ in range(args.repeat):
            for case in cases:
                trace = run_case(case, args.model)
                trace["failures"] = failures = score(case, trace)
                sink.write(json.dumps(trace, default=str) + "\n")
                sink.flush()
                results.append((case, trace, failures))
                verdict = "PASS" if not failures else "FAIL"
                print(
                    f"{verdict}  {case['id']:<32} {trace['seconds']:>6.1f}s  {' | '.join(failures)}"
                )
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
