# Backbone Redesign — Refactor Request

## Context

We have a LAS X microscope API driver with a central dispatch backbone (`_fire_with_retry` in `core.py`) that all commands route through. The current backbone runs a five-step pipeline: pre-check → setup → fire → error check → confirm. It works, but has hardcoded dependencies and owns concerns it shouldn't.

## Problem Statement

Different commands need different pre-flight checks, error handling, and confirmation logic. Currently these are either hardcoded in the backbone or wired up with boilerplate in each command wrapper. We want a design where:

- New commands can be added by dropping functions into files, without touching the backbone.
- The backbone stays dumb — it doesn't know what it's checking, only the order of operations.
- Pre-check, error-check, and confirm logic are fully pluggable per command.

## Key Design Decisions

### 1. Two-Layer Architecture (not recursion)

We settled on separating the backbone into two layers:

- **Fire Block (inner)** — steps 1–4: pre_check → setup → fire → error_check. This is the delivery engine. It retries on transient errors internally. Returns **success** or **failed**.
- **Confirm Wrapper (outer)** — calls the fire block, then runs confirm_fn to verify the result. If confirmation fails, the wrapper can run corrective commands (by calling the fire block again with different parameters) and re-attempt. This is a flat loop, not recursion.

### 2. Two Ceilings

- `max_retries` — controls transient error retries inside the fire block.
- `max_confirm_attempts` — controls how many times the confirm wrapper can re-run the cycle.

Both are explicit parameters at the call site.

### 3. Consistent Callable Contract

Every pluggable function has the same contract at every layer:

- **In `profiles.py`** — `callable(client) → result`. All four fields (`pre_check_fn`, `error_check_fn`, `confirm_fn`, `correct_fn`) take only `client` and return their result. Extra parameters (timeout, interval, tolerance, etc.) are pre-bound using `partial` before being stored in the profile.
- **In the command function** — `client` is bound via a lambda, producing a zero-arg callable that is passed to the backbone.
- **In the backbone** — zero-arg callable. The backbone calls it and acts on the result. Nothing else.

The binding chain is always the same shape, no exceptions:

```
profile.pre_check_fn                   →  callable(client) → result  # defined in profiles.py
lambda: profile.pre_check_fn(client)   →  zero-arg callable          # bound in command function
backbone calls pre_check_fn()          →  result dict                 # backbone sees only this
```

**No factory functions (`_make_*`).** The factory pattern from `confirm.py` (`_make_acquire_confirm`, `_make_select_job_confirm`) was required in the old backbone because the backbone polled externally, calling the confirm function many times in a loop, requiring state to persist across calls. In the new design, confirm functions own their own polling internally (see section 4). Any state that previously accumulated across backbone polling calls — `saw_scanning`, `t_start`, heartbeat timers — is now initialised as a local variable at the top of the function body on each call. `partial` works cleanly for all confirm functions without exception. There is no case in the new design where a factory is justified.

### Return Contracts

All four pluggable functions return a consistent dict shape. The backbone reads `"success"` from every result. `error_check_fn` additionally carries `"error"` and `"transient"` for the fire block to act on. All four include `"logs"` — a list of timestamped log entries accumulated during the function's execution.

```python
# pre_check_fn, confirm_fn, correct_fn — standard result:
{
    "success": bool,
    "logs": [
        {"ts": float, "level": str, "msg": str},
        ...
    ]
}

# error_check_fn — error result (superset of standard):
{
    "success": bool,
    "error": str | None,       # None when success is True
    "transient": bool | None,  # None when success is True
    "logs": [
        {"ts": float, "level": str, "msg": str},
        ...
    ]
}
```

`ts` is a UTC Unix timestamp (`time.time()`). `level` is one of `"debug"`, `"info"`, `"warning"`, `"error"`. These log entries are accumulated in the timing envelope returned by `confirm_and_fire` so the caller has a full, ordered, timestamped trace of everything that happened across every function call in the pipeline.

A shared helper `_make_log_entry(level, msg)` in `util.py` builds the dict and stamps `ts` — no function constructs the shape inline. This guarantees the shape is identical everywhere.

### 4. Polling Lives Inside Check and Confirm Functions

The backbone does not poll. It does not sleep. It calls a function once and gets back a result dict. All polling logic lives inside the functions themselves. Each function owns its own interval, timeout, and heartbeat logging internally. The backbone never sees any of that.

This means there is no separate `polling.py` module. A shared private loop helper can live inside `checks.py` if needed to avoid duplication, but it is not a public API.

Confirm functions follow the same rule. A stateful confirm — one that needs to track whether an expected intermediate state was observed, or enforce a settle delay before polling — initialises all local state at the top of its polling loop on every call. Because the confirm function owns its loop, there is no mutable state that persists between backbone calls and therefore no need for a factory. The `_make_*` factory pattern from the old backbone is eliminated entirely.

### 5. Error Check Is Pluggable with a Default

`error_check_fn` is a parameter with a clean contract: returns a result dict with `"success": True` and an empty (or populated) `"logs"` list on success, or `"success": False` with `"error"`, `"transient"`, and `"logs"` on failure. The fire block reads `result["success"]` to decide whether to retry, and `result["transient"]` to decide whether the retry is warranted. The fire block never calls `_is_transient_error` directly.

The default is a new `_default_error_check` adapter in `errors.py` that calls both `_check_api_error` and `_is_transient_error` and builds the expected shape. `_check_api_error` and `_is_transient_error` are unchanged — the adapter is the only new addition. 99% of commands never override `error_check_fn`. The rare command that needs custom error handling passes its own function implementing the same interface.

### 6. Correction Without Recursion

When a confirm_fn detects something wrong, the confirm wrapper can:

1. Call `check_idle` to wait for the scanner to be ready.
2. Call the fire block with a corrective setup (flat call, not recursive).
3. Re-run the original fire block.
4. Re-confirm.

This all happens inside the confirm wrapper's attempt loop. The fire block doesn't know it's being called for correction — it just runs its four steps.

Currently only idle-check correction is implemented. The `correct_fn` parameter is stubbed in the signature as `None` for future custom correction strategies. Stubbing it now avoids a breaking API change later.

Idle correction reuses `pre_check_timeout` — the same ceiling that governs pre-fire idle waits. Correction attempts count against `max_confirm_attempts`, not a separate counter.

### 7. Confirm Wrapper Can Call Fire Block Multiple Times

The confirm wrapper is not limited to calling the fire block once. If confirm_fn returns False, the wrapper can run a decision process — inspect state, fire corrective fire blocks, and re-attempt the original command. All within the `max_confirm_attempts` ceiling.

### 8. Per-Command Profiles

Every command has a `CommandProfile` in `profiles.py` that is its complete recipe — all four pluggable callables and all retry/confirm settings in one place. Adding a new command means adding a profile and a command function. Tuning a command means editing its profile. Nothing else needs to change.

```python
@dataclass
class CommandProfile:
    pre_check_fn: callable = None                    # callable(client) → bool
    error_check_fn: callable = _default_error_check  # callable(client) → None | {error, transient}
    confirm_fn: callable = None                      # callable(client) → bool
    correct_fn: callable = None                      # callable(client) → bool
    max_retries: int = 3
    max_confirm_attempts: int = 3
    confirm_timeout: float = 5.0
    confirm_interval: float = 0.01
```

All four callable fields follow the same rule: `callable(client) → result`. Extra parameters are pre-bound with `partial` at profile definition time. The command function always binds `client` via lambda — the same pattern for every field, no exceptions.

Two illustrative patterns cover the full range of cases:

```python
# Pattern A — confirm_fn needs extra parameters: use partial to pre-bind them.
SOME_COMMAND = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=30.0, heartbeat=30.0),
    error_check_fn=_default_error_check,
    confirm_fn=partial(_confirm_something, tolerance=0.1),
    correct_fn=None,
)

# Pattern B — confirm_fn takes only client: assign directly, no partial needed.
ANOTHER_COMMAND = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=60.0, heartbeat=30.0),
    error_check_fn=_default_error_check,
    confirm_fn=_confirm_something_else,
    correct_fn=None,
    confirm_timeout=10.0,
)
```

A command with no pre-flight check sets `pre_check_fn=None`. A command with a long-running confirm (e.g. acquisition) sets a larger `confirm_timeout`. These are the only variations — the binding pattern itself never changes.

## Backbone Signature

```python
confirm_and_fire(
    client, api_obj, description,
    max_retries=3,
    max_confirm_attempts=3,
    setup_fn=None,
    pre_check_fn=None,        # default: None → skip
    error_check_fn=None,      # default: _default_error_check (see errors.py)
    confirm_fn=None,          # default: None → skip
    correct_fn=None,          # default: None → idle-check correction only
)
```

> **✏ Note — `error_check_fn` contract:** The interface is `{"success": bool, "error": str | None, "transient": bool | None, "logs": [...]}`. The default `_default_error_check` in `errors.py` produces this shape. Anyone writing a custom `error_check_fn` must implement the same interface. The fire block never calls `_is_transient_error` directly.

> **✏ Note — `correct_fn` stub:** `correct_fn=None` is in the signature now even though no command uses it yet. When a command needs custom correction it passes a callable here; until then the confirm wrapper only runs the built-in idle-check correction path. This avoids a breaking API change when the first command needing custom correction is added.

### `confirm_and_fire` Return Shape

`confirm_and_fire` returns the same top-level shape as the current `_fire_with_retry`, preserving backwards compatibility for all callers:

```python
{
    "success":   bool,      # True if fired and confirmed (or no confirm_fn provided)
    "confirmed": bool|None, # True/False if confirm_fn ran; None if skipped
    "message":   str,       # Human-readable outcome description
    "timing":    dict,      # Full timing envelope (see _make_timing in util.py)
    "logs":      list,      # Ordered, timestamped log entries from all pipeline functions
}
```

`timing` includes all keys from `_make_timing` plus the new `confirm_attempts` key. `logs` is the accumulated list of all `{"ts", "level", "msg"}` entries returned by every pluggable function called during the pipeline — giving the caller a complete trace without needing to parse the Python log output.

## Example Call Site

```python
# profiles.py — define the recipe once
SOME_COMMAND = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=30.0, heartbeat=30.0),
    error_check_fn=_default_error_check,
    confirm_fn=partial(_confirm_something, tolerance=0.1),
    correct_fn=None,
)

# commands.py — bind client, unpack profile, call the backbone
def some_command(client, param_a, param_b, *, profile=SOME_COMMAND):
    api_obj = client.SomeApiObject

    def setup(m):
        m.ParamA = param_a
        m.ParamB = param_b

    return confirm_and_fire(
        client, api_obj, f"SomeCommand -> {param_a}",
        setup_fn=setup,
        pre_check_fn=lambda: profile.pre_check_fn(client),
        error_check_fn=lambda: profile.error_check_fn(client),
        confirm_fn=lambda: profile.confirm_fn(client),
        correct_fn=profile.correct_fn,
        max_retries=profile.max_retries,
        max_confirm_attempts=profile.max_confirm_attempts,
    )
```

Every command wrapper is this shape. The only things that vary are the `api_obj`, the `setup` body, the description string, and the profile. The structure is identical across all commands.

## Architecture Summary

```
┌─────────────────────────────────────────┐
│  Confirm Wrapper                        │
│  ┌───────────────────────────────────┐  │
│  │  confirm attempt loop             │  │
│  │                                   │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Fire Block                 │  │  │
│  │  │  ┌───────────────────────┐  │  │  │
│  │  │  │ transient retry loop  │  │  │  │
│  │  │  │  1. pre_check_fn()    │  │  │  │
│  │  │  │  2. setup_fn(model)   │  │  │  │
│  │  │  │  3. fire_with_receipt │  │  │  │
│  │  │  │  4. error_check_fn()  │  │  │  │
│  │  │  └───────────────────────┘  │  │  │
│  │  │  → success / failed         │  │  │
│  │  └─────────────────────────────┘  │  │
│  │                                   │  │
│  │  if failed → stop                 │  │
│  │  if success → confirm_fn()        │  │
│  │    True  → return success         │  │
│  │    False → correct_fn() or        │  │
│  │      built-in idle correction     │  │
│  │      re-run original fire block   │  │
│  │      or give up                   │  │
│  └───────────────────────────────────┘  │
│  return result                          │
└─────────────────────────────────────────┘
```

## Design Principles

1. **Backbone is dumb** — it owns pipeline order, retry ceiling, confirm ceiling, and timing. Nothing else.
1. **No polling in backbone** — all polling lives inside check functions in `checks.py`. The backbone never sleeps.
1. **No domain knowledge in backbone** — it doesn't know about zoom, objectives, stages, or Z-drives.
1. **Callables flow in, not looked up inside** — the backbone never imports or references specific check functions.
1. **No recursion** — correction is handled by the confirm wrapper calling fire blocks sequentially.
1. **Consistent callable contract** — every pluggable field is `callable(client) → result`. No exceptions. `partial` pre-binds extra parameters; the command function binds `client` via lambda.
1. **Profiles are the single source of truth** — every command's recipe (which functions, which settings) lives in one profile in `profiles.py`. Tuning a command means editing its profile, nothing else.
1. **Two ceilings, both explicit** — `max_retries` for transient errors, `max_confirm_attempts` for the outer loop.
1. **Clean, readable, professional code** — every function has a docstring. No workarounds, no patchwork, no clever one-liners at the expense of clarity. See *Code Quality & Modularity Standards* below.
1. **Strict modularity** — each file has one responsibility. Split before growing. No circular imports. The import graph is a strict DAG enforced by the file structure.
1. **One pattern, applied consistently** — if a pattern exists, all new code follows it. Two coexisting patterns for the same thing is not acceptable.

## Code Quality & Modularity Standards

These standards are **non-negotiable** for every file produced in this redesign. They are not aspirational — they are the bar. Any code that does not meet them should be rewritten, not patched.

### Readability First

- **Every module, class, function, and non-obvious variable must have a docstring or inline comment** that explains *what it does and why*, not just *how*.
- Code must be immediately understandable by a developer who has never seen the project. If a reader has to trace three files to understand what a function does, the code needs to be restructured.
- Favour explicit over clever. No one-liners that sacrifice clarity, no nested comprehensions that require effort to parse, no "smart" tricks that save a line at the cost of readability.
- Name things precisely. `fire_block`, `confirm_wrapper`, `error_check_fn` are good names. `helper`, `do_thing`, `wrapper2` are not.

### No Patchwork, No Workarounds

- **No workarounds.** If something requires a workaround, the underlying problem must be fixed instead.
- **No dead code.** No commented-out blocks left "just in case", no unused imports, no vestigial parameters.
- **No silent swallowing of errors.** Every exception path must be handled explicitly and logged or re-raised. No bare `except: pass`.
- **No implicit behaviour.** Every default, every fallback, every None-check must be documented at the point it is written.
- If a design decision required a trade-off, it belongs in a comment *at the call site*, not in a commit message that will never be read again.

### Modularity and File Structure

- **Prefer splitting files over growing them.** A file that is growing long or whose responsibilities are blurring is a signal to split, not to add more. Each file should have a single, clearly stated responsibility.
- **No circular imports — ever.** The import graph must be a strict DAG. The dependency direction is fixed:
  ```
  commands.py  →  profiles.py  →  checks.py, confirm.py, errors.py
  core.py      →  errors.py
  ```
  Nothing in `checks.py`, `errors.py`, or `confirm.py` may import from `commands.py`, `profiles.py`, or `core.py`. If you find yourself wanting to, the design is wrong — restructure.
- **Each module exports a clean, minimal public interface.** Internal helpers are prefixed with `_` and are not imported by other modules. If another module needs an internal helper, it should become a shared utility — not imported directly.
- The purpose of every file must be statable in one sentence. If it cannot, the file is doing too much.

### Consistent Patterns — No Exceptions

- The callable contract (`callable(client) → result`) applies to every pluggable field in every profile, without exception. No special-casing for "simple" commands.
- `partial` is always used to pre-bind extra parameters before storing in a profile. Lambda-binding of `client` at the command function is always the same shape. These two rules have no exceptions.
- If a pattern exists in the codebase, new code follows it. If a better pattern is introduced, the old code is updated to match. There is never a period where two different patterns coexist.
- Copy-paste duplication is a bug. If the same logic appears in two places, it belongs in a shared helper with a name and a docstring.

### Docstring Standard

Every public function must have a docstring that covers:
1. **What it does** — one sentence.
2. **Parameters** — name, type, and what it means.
3. **Return value** — type and what it represents.
4. **Raises** — any exceptions the caller should be aware of.

```python
def check_something(client, *, timeout: float, heartbeat: float) -> dict:
    """
    Poll until the expected condition is met, or until timeout is exceeded.

    Logs a heartbeat message at regular intervals so long-running waits are
    visible in the logs. All polling logic is internal — the caller sees only
    a result dict with "success" and "logs".

    Args:
        client: The connected LAS X API client.
        timeout: Maximum seconds to wait before returning a failure result.
        heartbeat: Interval in seconds between log messages during the wait.

    Returns:
        {"success": True, "logs": [...]} if the condition was met within timeout.
        {"success": False, "logs": [...]} if timeout was exceeded.
    """
```

---

## What Changes from Current Code

| Current                                    | New                                                                              |
|--------------------------------------------|----------------------------------------------------------------------------------|
| `_check_api_error` hardcoded in backbone   | `error_check_fn` parameter, defaults to `_default_error_check` adapter          |
| Polling loops (while/sleep) inside backbone| Polling lives inside check and confirm functions; backbone never sleeps          |
| `poll_interval`, `poll_timeout` on backbone| Removed — belong to check functions and confirm functions                        |
| `pre_check_heartbeat` in backbone          | Heartbeat logging lives inside check functions in `checks.py`                    |
| `_default_pre_check` lambda in `core.py`   | Replaced by `check_idle` in `checks.py`                                          |
| Confirm is step 5 inside backbone          | Confirm wrapper sits outside fire block                                          |
| No correction mechanism                    | Confirm wrapper has built-in idle correction + `correct_fn` stub for future use  |
| Single retry counter for everything        | Two counters: `max_retries` (fire block), `max_confirm_attempts` (wrapper)       |
| `_make_*` closure factories in `confirm.py`  | Eliminated — confirm functions own their own polling loop; all state is local   |
| Plain `bool` return from pre/confirm/correct | Structured dict `{"success": bool, "logs": [...]}` with timestamped entries    |
| `None \| {"error", "transient"}` from error_check | `{"success": bool, "error", "transient", "logs": [...]}` — consistent shape |

## File Organisation

Each file has exactly one responsibility, stated below. If a file is growing beyond that responsibility, it must be split. No file should be so long that its purpose is ambiguous.

| File | Single responsibility | May import from |
|---|---|---|
| `util.py` | Shared low-level helpers: `_make_log_entry(level, msg)` and any other primitives with no domain knowledge | stdlib only |
| `core.py` | `_fire_block` (steps 1–4) + `confirm_and_fire` (outer wrapper) | `errors.py`, `util.py`, stdlib |
| `errors.py` | Error detection and classification; `_default_error_check` adapter | `util.py`, stdlib |
| `checks.py` | Pre-flight check functions (`check_idle`, future additions); each owns its own polling internally | `util.py`, stdlib |
| `confirm.py` | Confirm functions; each owns its own polling loop internally | `checks.py`, `errors.py`, `util.py`, stdlib |
| `profiles.py` | `CommandProfile` dataclass + one named profile per command; single source of truth | `checks.py`, `confirm.py`, `errors.py` |
| `commands.py` | Command wrappers: bind `client`, unpack profile, call `confirm_and_fire` | `core.py`, `profiles.py` |

**Import DAG — strictly enforced:**
```
commands.py  →  core.py, profiles.py
profiles.py  →  checks.py, confirm.py, errors.py
core.py      →  errors.py, util.py
checks.py    →  util.py, stdlib
confirm.py   →  checks.py, errors.py, util.py
errors.py    →  util.py, stdlib
util.py      →  stdlib only
```

No module imports from a module above it in this graph. If you find yourself needing to, the design is wrong — restructure rather than introduce a cycle.

---

## Resolved Questions

### Q1 — Where does correction logic live? ✓

`correct_fn=None` is stubbed in the signature now. Currently the only correction implemented is idle-check: if `confirm_fn` returns False, the wrapper calls `check_idle` (reusing `pre_check_timeout`) before re-running the fire block. This counts against `max_confirm_attempts`. When a command needs a custom correction strategy it passes `correct_fn`; until then the stub is a no-op and the idle-check path handles all cases.

### Q2 — Where does polling/heartbeat logic live? ✓

Inside check and confirm functions. There is no `polling.py`. Each function owns its interval, timeout, and heartbeat parameters internally. The backbone sees only a zero-arg callable returning a result dict — it never sees polling, sleep, or timing state.

### Q3 — How does timing roll up across two layers? ✓

`_fire_block` returns a partial timing envelope `{pre_check_s, setup_s, fire_s, check_s}`. `confirm_and_fire` accumulates across multiple `_fire_block` calls, adds `confirm_s` and `confirm_attempts`, then builds the final envelope via `_make_timing`.

`_make_timing` in `util.py` gains one new parameter: `confirm_attempts`. All existing keys are preserved. Test helpers that construct expected timing dicts must be updated to include it.

> **⚠ Test impact:** Any test that asserts `pre_check_s > 0` depends on timing elapsed inside a check function being propagated back into the fire block's timing envelope. This must be verified end-to-end before the migration is considered done.

### Q4 — Is `_fire_block` a callable the wrapper invokes by reference? ✓

`_fire_block` is a standalone internal function with an explicit signature. `confirm_and_fire` calls it directly and passes `setup_fn` each time. For a corrective call it passes a different `setup_fn`. No closure needed.

```python
# Inside confirm_and_fire:
result = _fire_block(client, api_obj, description,
                     setup_fn=setup_fn, ...)            # normal call

result = _fire_block(client, api_obj, "Correct: ...",
                     setup_fn=corrective_setup_fn, ...)  # corrective call
```

### Q5 — `_fire_with_retry` migration strategy ✓

Full migration in one go. A compatibility shim that silently ignores `poll_interval` and `poll_timeout` would hide bugs — callers think they're configuring behaviour but nothing happens. All references in `test_unit.py` and all command wrappers are updated as part of this work. `_fire_with_retry` is replaced by `confirm_and_fire` with no alias.

---

## Implementation Order

**Write unit tests before implementing each step.** For every step below, write the tests against the specified contracts first, confirm they fail, then implement until they pass. Tests for the new design live in a separate file from the existing `test_unit.py` — do not modify the old test file until the migration is complete. Delete it only once the new suite covers the same ground.

1. **`util.py`** — add `_make_log_entry(level, msg)` and add `confirm_attempts` parameter to `_make_timing`. No other changes. Every subsequent step depends on this.
2. **`errors.py`** — add `_default_error_check` adapter returning the full `{"success", "error", "transient", "logs"}` shape. Verify the shape is correct in isolation before touching anything else.
3. **`checks.py`** — new module. Implement `check_idle` returning `{"success": bool, "logs": [...]}` with internal polling, timeout, and heartbeat. Delete `_default_pre_check` from `core.py` once this exists.
4. **`confirm.py`** — migrate all confirm functions from returning `bool` to returning `{"success": bool, "logs": [...]}`. This is the highest-risk step: there are ~25 functions and every test that asserts on a confirm result checks a bool today. Complete this step and update all affected tests before touching the backbone. Do not proceed to step 5 until the test suite passes.
5. **`core.py`** — `_fire_block` (steps 1–4) then `confirm_and_fire` (outer wrapper with idle correction and `correct_fn` stub). The backbone now reads `result["success"]` from all four pluggable functions. Remove `_fire_with_retry`.
6. **`profiles.py`** — new module. Define `CommandProfile` dataclass and one profile per command. Start with one simple command and one complex command (long-running confirm with internal state) to validate both patterns before defining the rest.
7. **Migrate two commands first** — one simple command (no confirm polling) and one complex command (long-running confirm with internal state). Validate full timing plumbing and the `pre_check_s > 0` assertion before migrating the remainder.
8. **Update `__init__.py`** — add `confirm_and_fire`, remove `_fire_with_retry`. Update all references in `test_unit.py` at the same time. Do not leave them out of sync.
9. **Bulk migrate `commands.py`** — once timing, `checks.py`, and `profiles.py` are proven stable.
