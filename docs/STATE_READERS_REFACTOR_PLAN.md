# State Readers Refactor Plan

## Goal

Create a clean `state_readers/` package for Leica LAS X state readout:

- API-backed state reads.
- Log-backed state reads.
- A small routing layer that can use API, log, or concurrent API+log rescue.

This is a responsiveness and robustness improvement, not a rewrite of command
or confirmation logic.

## Starting State

Starting layout before this refactor:

```text
navigator_expert/
  acquisition/
  core/
    readers.py       # API-backed state readers
    log_reader.py    # log-backed state readers, built and verified but uncommitted
    profiles.py
    confirmations.py
    prechecks.py
    commands.py
```

The original importers of `core.readers` were bounded and internal:

- `core/commands.py`
- `core/confirmations.py`
- `core/prechecks.py`
- `stage/movement.py`
- `positions/parsers.py`
- `templates/transaction.py`
- `experimental/lrp_edits/roi.py`
- package exports in `navigator_expert/__init__.py`
- hardware/unit tests

## Target Layout

Use a separate flat package next to `acquisition/`:

```text
navigator_expert/
  acquisition/
  state_readers/
    __init__.py       # public routed state-reader surface
    router.py         # mode selection and concurrent trustworthy-read routing
    api_reader.py     # moved from core/readers.py
    log_reader.py     # moved from core/log_reader.py
  core/
    commands.py
    confirmations.py
    profiles.py
    prechecks.py
    ...
```

No nested `state_readers/readers/` folder for now. Two implementations do not
justify another level of structure.

## Core Principle

There are two layers, and they must never be conflated.

1. State reader layer: answers "can either backend give me a trustworthy reading
   right now?"
2. Confirmation/caller layer: answers "has the trustworthy state changed to the
   expected value?"

The reader must not become a hidden confirmation engine. It does not know the
target position, expected scan status, requested setting, or command start time.
It only returns a trustworthy reading, or no reading.

## Design Rules

1. No abstract base class.
2. No plugin registry.
3. No compatibility shim such as `core/readers.py` re-exporting with
   `import *`.
4. No production behavior change by default.
5. Modes are `api`, `log`, and `both`. `fast` is removed.
6. `both` mode is concurrent in v1, but it is log-rescue semantics, not
   first-response-wins: a fresh log reading wins if it arrives within the
   profile grace window; otherwise API is the fallback.
7. The reader checks intrinsic trustworthiness only. It does not receive an
   expected-match predicate.
8. Confirmation/readback code owns polling, expected-match checks, tolerances,
   and command-start freshness.
9. The reader reports state; callers decide whether state changed.

## Reader Modes

Profile defaults choose normal read behavior:

```python
mode = "api"   # API only
mode = "log"   # log only, freshness-gated
mode = "both"  # API and log concurrently; fresh log rescue, API fallback
```

Default every reader to `api`. Enable `both` one reader at a time after
validation.

Do not implement first-response-wins. That is unsafe because either backend can
return stale state. `both` means both backends run, and the coordinator prefers
a trustworthy log reading if it arrives within the profile grace window;
otherwise it returns the trustworthy API reading.

To avoid overlapping calls on the non-thread-safe CAM API, `both` also caps the
background API leg to one in-flight read per client. If an API read is already
pending, a later `both` read does not start another API thread; it tries the log
leg and returns `None` if the log is not trustworthy.

## Reading Shape

The router internally carries a structured reading:

```python
@dataclass(frozen=True)
class Reading:
    value: object | None
    source: str              # "api" or "log"
    observed_at: float | None
    age_s: float | None
    error: Exception | None = None
```

Public reader functions return the plain value by default, preserving the current
API. When `diagnostics=True`, they return the full `Reading`.

If no backend produces a trustworthy reading before `timeout_s`, the routed
reader returns `None` by default, or a diagnostic `Reading`/failure summary when
`diagnostics=True`.

## Intrinsic Trustworthiness

Trustworthiness is source-aware and intrinsic to the reading:

- Log reading: fresh enough (`age_s < per-reader bound`) and unambiguous.
- API reading: returned non-error and non-blank.

This is not the same as "matches the expected target." Expected-match checks
belong to the caller or confirmation layer.

## Profile Policy

Reader modes, age bounds, and timeouts live in the existing profile mechanism:
`core/profiles.py`.

Do not create a second parallel config object. There must be one obvious place a
user changes reader behavior.

Sketch inside the existing profile structure:

```python
both_log_grace_s = 0.25

xy_reader_mode = "api"
xy_log_max_age_s = 1.0
xy_reader_timeout_s = 2.0

job_settings_reader_mode = "api"
job_settings_log_max_age_s = 2.0
job_settings_reader_timeout_s = 2.0

scan_status_reader_mode = "api"
scan_status_reader_timeout_s = 2.0
```

Default every reader to API. Enable `both` one reader at a time after validation.

## Routing Rule

Centralize the mode rule in one helper. Do not copy-paste it into every reader.

Sketch:

```python
def _route_read(mode, *, api_fn, log_fn, trust_api, trust_log, timeout_s):
    if mode == "api":
        reading = _read_api(api_fn)
        return reading if trust_api(reading) else None
    if mode == "log":
        reading = _read_log(log_fn)
        return reading if trust_log(reading) else None
    if mode == "both":
        return _log_rescue_concurrent(
            api_fn=api_fn,
            log_fn=log_fn,
            trust_api=trust_api,
            trust_log=trust_log,
            timeout_s=timeout_s,
        )
    raise ValueError(f"unknown reader mode {mode!r}")
```

Example routed reader:

```python
def get_xy(client, *, mode=None, diagnostics=False):
    mode = mode or PROFILE.xy_reader_mode
    reading = _route_read(
        mode,
        api_fn=lambda: api_reader.get_xy(client),
        log_fn=lambda: log_reader.get_xy(max_age_s=PROFILE.xy_log_max_age_s),
        trust_api=_non_blank_reading,
        trust_log=_fresh_non_blank_reading,
        timeout_s=PROFILE.xy_reader_timeout_s,
    )
    if diagnostics:
        return reading
    return None if reading is None else reading.value
```

Do not call the concurrent helper `_first_valid_concurrent`. "Valid" carried the
old overloaded meaning. Use trustworthy/read/trust language instead. The
implemented helper should encode log-rescue semantics, not raw first-finished
semantics.

## Confirmation Layer

Command-control reads pin API mode explicitly. That includes prechecks, early
exits that decide whether a command fires, confirmations, and post-write
readbacks. It also includes reads that parameterize a later command, such as
the selected job/FOV reads used for galvo pan and the current XY read used for
backlash correction. These reads are part of the API/write channel and must not
inherit a passive status-reader profile that prefers log rescue. The safety
mechanism is still poll-until-expected-match using diagnostic readings, but the
backend for command confirmation is API.

The confirmation layer owns:

- expected target
- tolerance
- poll loop
- timeout
- `observed_at > command_start`
- retry-until-match

Sketch:

```python
while before_timeout:
    reading = state_readers.get_xy(
        client,
        mode="api",
        diagnostics=True,
    )
    if (
        reading is not None
        and reading.observed_at is not None
        and reading.observed_at > command_start
        and close_to_target(reading.value, target, tolerance)
    ):
        return confirmed
```

The reader already guarantees intrinsic trustworthiness. The confirmation layer
only checks:

- a reading exists
- it was observed after the command started
- it matches the expected target

Do not reimplement the reader's trustworthiness logic in confirmation code.

## Two Freshness Checks

There are two different freshness checks at two different layers:

- Absolute age: `age_s < bound`. This is part of reader trustworthiness.
- Observed after command: `observed_at > command_start`. This belongs to the
  confirmation/caller layer because only that layer knows `command_start`.

This separation is what stops a stale-but-otherwise-trustworthy reading that
happens to match the old state from falsely confirming a just-issued command.

## Scan / Idle Checks

Scan/idle transition checks follow the same split as confirmations:

- Reader returns the routed trustworthy scan-status reading.
- Caller checks `observed_at > acquisition_start` and `state == "idle"`.

Do not pass an "idle after acquisition started" predicate into the reader. The
reader does not know acquisition intent.

Default scan status to API until the workflow explicitly validates `both` for
that reader.

## Special Readers

Some readers need conservative handling:

- `ping`: API-only. Log mtime is not CAM-channel liveness.
- `get_pending_dialog`: log-only. The API cannot report the dialog that is
  blocking it.
- `get_scan_status` / idle checks: API by default; `both` only when the caller
  performs the observed-after-start transition check outside the reader.

Do not route every reader blindly just because the router exists.

## Minimal Public Surface

The moved package must expose the full existing reader surface unchanged from the
moment of the move. Non-routed readers can pass directly through to `api_reader`
with default API behavior.

Routing can start with:

- `get_xy`
- `get_job_settings`
- scan status only if the caller-side transition check is implemented

The package public surface is `state_readers/__init__.py`, re-exporting routed
functions from `router.py`. `router.py` owns `_route_read` and the routed
implementations.

## Named Limitation

A cold read with no expectation cannot be fully protected against a silently
stale API. There is no expected target or command-start time to test it against.

The only way to catch a stale cold API read is an independent, provably fresh log
reading that disagrees. `both` mode is therefore most useful for caller-owned
transition checks where an expectation exists and the caller can poll until the
expected state is observed. Command confirmations deliberately pin API mode
because they are read-backs of commands sent on the API/write channel.

Do not claim that `both` validates every cold API read.

## Sequencing

### Step 0: Land `log_reader`

When doing this as separate changes, commit the verified log reader before
building routing.

Include:

- `state_readers/log_reader.py`
- `tests/unit/test_log_reader.py`
- `tests/hardware/validate_readers_side_by_side.py` if it is intended to stay as
  the live parity validator.

If the branch already contains the full end-to-end refactor, keep it coherent:
log-backed reads, routing, profile config, import updates, and tests must land
together. Do not leave a half-moved reader stack.

### Step 1: Move Readers Into `state_readers/`

Move:

```text
core/readers.py    -> state_readers/api_reader.py
core/log_reader.py -> state_readers/log_reader.py
```

Add:

```text
state_readers/__init__.py
state_readers/router.py
```

Delete the old `core/readers.py` and `core/log_reader.py` paths. Do not leave a
shim.

### Step 2: Update Imports

Update internal imports in one pass.

Examples:

```python
from navigator_expert import state_readers
from ..state_readers import api_reader
```

Package-level exports in `navigator_expert/__init__.py` should re-export the
routed public functions from `state_readers`, not the API implementation.

### Step 3: Add Routing With API Defaults

Implement routed public readers in `state_readers/router.py`.
`state_readers/__init__.py` re-exports the public reader functions.

Default behavior must remain API-only until the profile is explicitly changed.

Start by routing only readers with clear trustworthiness rules. Keep ping
API-only. Keep pending-dialog log-only. Command-control reads stay pinned to
API: prechecks, early-exit checks, command-parameterizing reads,
confirmations, and post-write readbacks.

### Step 4: Update Confirmation / Readback

Update confirmation/readback code so it polls trustworthy readings and checks
expected-match outside the reader.

For each confirmation read:

- record `command_start`
- call the routed reader with `diagnostics=True`
- require `reading.observed_at > command_start`
- require expected-match within tolerance
- retry until match or timeout

Do not pass expected-match predicates into the state reader.

### Step 5: Tests

Add focused tests for routing behavior:

- default mode is API.
- `mode="log"` returns log value when fresh.
- `mode="log"` returns `None` when stale/ambiguous.
- `mode="both"` starts API and log backends concurrently.
- `mode="both"` prefers a fresh log reading over a faster API reading within
  the profile grace window.
- `mode="both"` ignores a faster stale/untrustworthy reading.
- public readers return plain values by default.
- `diagnostics=True` returns `Reading`.
- confirmation/readback code rejects trustworthy-but-pre-command readings and
  waits for a trustworthy post-command reading that matches the expected state.
- command-control reads pin API mode: prechecks, early-exit command guards,
  command-parameterizing reads, confirmations, and post-write readbacks.
- ping remains API-only.
- pending dialog remains log-only.

Keep existing API reader behavior tests passing after the move.

## Rollout

Initial production profile:

```python
xy_mode = "api"
job_settings_mode = "api"
scan_status_mode = "api"
```

First optional concurrent reader:

```python
xy_mode = "both"
```

Use command-control reads only through API-pinned prechecks, early exits,
command-parameterizing reads, confirmations, or post-write readbacks.

Do not enable `both` mode for cold job settings until its behavior is validated
in the workflow that uses it.

## Non-Goals

- No ABC/interface class.
- No plugin registry.
- No compatibility import shim.
- No first-response-wins race.
- No `fast` mode.
- No production default switch from API to log/both.
- No expected-match predicate passed into the reader.
- No raw log-backed scan/idle confirmation without caller-side transition proof.
- No claim that `both` can fully validate cold reads.

## Acceptance Criteria

- `state_readers/` exists as the only state-reader package.
- Old `core/readers.py` and `core/log_reader.py` import paths are gone.
- Reader modes, age bounds, and timeouts live in `core/profiles.py`.
- Public reader return shapes remain compatible by default.
- `diagnostics=True` exposes `Reading`.
- Default behavior remains API-only.
- `both` mode is concurrent fresh-log rescue with API fallback.
- Confirmation/readback tests prove pre-command or stale readings cannot confirm
  a command.
- Existing unit suite passes.
- Hardware-side reader parity validator still works after import updates.
