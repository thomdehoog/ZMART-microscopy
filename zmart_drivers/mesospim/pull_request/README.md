# Upstream PR — Remote Control for mesoSPIM-control

A proposed contribution to
[mesoSPIM-control](https://github.com/mesoSPIM/mesoSPIM-control): let an external
process control mesoSPIM over a socket by sending **named calls** — a **Remote
Control** tab that any external driver or script can build on. Nothing here is
driver-specific; it is a patch *for mesoSPIM*.

## The idea (why it is this small)

A client sends one single-key JSON object, `{"<method>": {args}}`. The server
**validates** it, looks the method up in a fixed allowlist (`COMMANDS`), and runs
the matching `mesoSPIM_Core` call — the same methods the GUI's own buttons call. It
returns a JSON result line. **No client Python is ever run**: the "method" is only
ever a dict-key lookup, so a client can only invoke operations the allowlist names.

An off-the-shelf **LLM** can drive the scope too: a small **MCP-over-HTTP** server
(a separate process) exposes `tools/list` *as* the allowlist and forwards a
`tools/call` to the same TCP command path — the same validated dispatch, just a
different envelope.

```
  a script (framed TCP)                                        INSIDE mesoSPIM
  {"move_absolute": {…}}  ─────────▶───────────┐              (Core context)
  __MESOSPIM_OK__{…}         ◀─────────◀──────────┤
                                               ├──▶  COMMANDS["move_absolute"](core, …)
  an LLM (MCP over HTTP)     ┌── forwards ──────┘        (one validated dispatch)
  POST /mcp {"tools/call"} ──┤  a framed TCP call
  {"result":{…}}           ◀─┘  (separate MCP process)
```

## What the PR does — the files

| File | Change |
|---|---|
| `mesoSPIM/src/mesoSPIM_RemoteControl_ValidateAndRunCommands.py` | **New.** The command vocabulary (`COMMANDS` allowlist), the arg gate `_validate` (type + allowed option + in-range), `run()` — the **single choke point** both transports share — and `self_test()`, a pre-flight that proves the loaded limits are enforced (against a `SimCore` mock of the hardware). Pure stdlib; unit-tested without Qt. |
| `mesoSPIM/src/mesoSPIM_RemoteControl_Servers.py` | **New.** A signal-driven `QTcpServer` (`RemoteControlTCPServer`) hosted by the Core that dispatches framed named calls, **and** a standalone MCP-over-HTTP server (its own process, `--port` default `42100`) that forwards `tools/call` to that TCP server. **On start the TCP server runs `self_test` and refuses to bind (fail-closed) if the limits aren't enforced**, so a drifted config never exposes the instrument. Framing, auth, and dispatch are socket-free helpers. Constant-time token; HTTP adds a Bearer check and an Origin guard. |
| `mesoSPIM/src/mesoSPIM_Core.py` | `start_remote_control(host, port, token)` / `stop_remote_control()` slots, plus a `sig_remote_control_started(ok, message)` signal so a bind failure (e.g. port in use) is reported instead of a false "running". |
| `mesoSPIM/src/mesoSPIM_MainWindow.py` | A **Remote Control tab** (TCP / MCP mode, host / port / password, default `smart_mesospim`); reflects the real start outcome; stops on app close. |
| `mesoSPIM/src/test_remote_control_validation.py` | Qt-free tests for the `_validate` gate. |
| `pyproject.toml` | A `mesospim-mcp-server` console entry point for the standalone MCP server. |

## Wire protocol

Length-framed UTF-8, both directions: `b"<decimal-byte-count>\n" + payload`. If a
token is set, the **first** frame must be it (`OK` / `AUTH-FAILED`). Every frame
after that is a call, `{"<method>": {args}}`; the reply is one `__MESOSPIM_OK__<json>`
line (or error text). See [`PROTOCOL.md`](PROTOCOL.md).

## Security

A named call **controls the microscope** (moves the stage, runs acquisitions), but
it is **not** arbitrary code — the server only ever does a dict lookup + a fixed
call, so nothing outside `COMMANDS` can run. And a bad *value* is refused too: the
args are **validated** (right shape, an option the live `cfg` allows, an in-range
number) before the Core is touched. Still:

- **Off by default**; started by an operator from the Remote Control tab.
- **Binds `127.0.0.1`** unless changed; the dialog warns before a network bind
  without a token.
- **Optional token** gates access (constant-time compare); over HTTP it is an
  `Authorization: Bearer <token>` header.
- **Origin guard (HTTP)**: any non-localhost `Origin` is rejected, so a web page in
  the operator's browser can't drive the instrument (DNS-rebinding / CSRF).
- **Plain TCP**: the token guards casual LAN access, **not** sniffer-proof. For
  untrusted networks, tunnel it (SSH/VPN) — out of scope for this PR.

## Input validation (`_validate`)

Before a call reaches the Core, `_validate` refuses a bad **value**, not just a bad
name — for **every** settable parameter, not only the stage — with a message the caller
can act on (and that **names the limit**, so a script or LLM can correct itself):

- **type** — a number where a number is expected (JSON booleans are *not* numbers), a
  string where a string is expected.
- **allowed option** — `filter`/`zoom`/`laser`/`shutterconfig` (and the same keys inside
  `set_state` / an acquisition) must be one the live `cfg` allows.
- **range** — `move_absolute` targets against the per-axis travel envelope of the config
  the operator **loaded at startup** (`cfg.stage_parameters`), so range checking is on by
  default with no extra setup; `MESOSPIM_RS_LIMITS` (a JSON object `{"x": [lo, hi], …}` or
  a path to one) can *tighten* an axis further. `intensity` and every `%` parameter ∈
  `[0, 100]`. No limit for an axis → the Core's hardware bound is the backstop.

Because both transports meet at the single `run()` choke point, **TCP and MCP can never
breach a limit** — an out-of-range call comes back as an error and never reaches the Core.
A client also has **no way to change the limits**: they come from the read-only `cfg` (plus
the env override) and no allowlisted verb writes them. `get_limits` returns the exact rules
in force — including which checks are **off** (`range: null` = only the type is checked) —
so a script or LLM can read the envelope up front.

## Pre-flight self-test (`self_test`)

The worry with any limits system is *drift*: a wrong limits file, a config quirk, a
validation regression — the limits silently stop matching this machine. So the server
**proves the limits before it goes live**. On **Start**, `RemoteControlTCPServer` runs
`self_test` first: it drives the whole validated `run()` dispatch against a **`SimCore`** that
carries *this instrument's real `cfg`* but simulates the hardware, and checks that a valid
move is accepted while an out-of-range move / bad option / unknown command is refused — and
that *only* the in-range moves reached the mock stage. If any check fails (including "no axis
has a limit"), it **raises and the server never binds** (fail-closed) — the instrument is
never exposed. It runs the *real* code both lanes share, so one gate covers TCP and MCP, and
it never touches real hardware. `self_test` is also an on-demand command on both lanes, so a
script or LLM can ask the server to re-prove its limits at any time.

## Tests

Run the functional/validation suite and the bounded adversarial suite separately:

```bash
python -m pytest zmart_drivers/mesospim/pull_request -m normal -q
python -m pytest zmart_drivers/mesospim/pull_request -m adversarial -q
```

Valid live movement over both MCP and TCP is a third, opt-in group and is excluded from
normal CI. With an operator present and the travel path clear, each transport moves X by a
small in-range amount, verifies the change, restores X, and verifies restoration:

```bash
MESOSPIM_ALLOW_DEVICE_CHANGE=1 MESOSPIM_OPERATOR_PRESENT=1 \
MESOSPIM_LIVE_MCP_TOKEN=<token> MESOSPIM_TEST_X_DELTA_UM=100 \
MESOSPIM_LIVE_TCP_PORT=<port> MESOSPIM_LIVE_TCP_TOKEN=<token> \
python -m pytest zmart_drivers/mesospim/pull_request -m live_valid -q -s
```

Running the directory without `-m` collects all groups, but `live_valid` safely skips unless
both device-change gates and a token are supplied.

The full visible demo sweep is a fourth, separately gated group. It calls every one of the
54 allowlisted commands over live MCP: all 40 instrument-facing operations, 13 read/query
commands, and the deliberately unimplemented `procedure` command (which must fail safely).
It refuses to run unless the server reports `DemoStage`, uses a temporary acquisition
directory, backs up and restores the ETL CSV, and restores position, settings, acquisition
list, shutters, and idle state. On Windows it completes in about 50 seconds:

```bash
MESOSPIM_ALLOW_DEVICE_CHANGE=1 MESOSPIM_OPERATOR_PRESENT=1 \
MESOSPIM_CONFIRM_DEMO_MODE=1 MESOSPIM_RUN_ALL_COMMANDS=1 \
MESOSPIM_LIVE_MCP_TOKEN=<token> \
MESOSPIM_DEMO_PROCESS_ID=<pid-of-mesoSPIM-Control--D> \
MESOSPIM_DEMO_ROOT=<path-to-mesoSPIM> \
MESOSPIM_DEMO_ETL_CONFIG_PATH=<path-to-ETL-parameters.csv> \
python -m pytest zmart_drivers/mesospim/pull_request -m live_demo_all -q -s
```

Without every gate, `live_demo_all` safely skips. It must never be enabled against physical
hardware; the remote `DemoStage` check is an additional fail-closed guard. The full sweep
runs at most once per mesoSPIM process; restart the demo app before intentionally repeating
it so Qt camera/writer resources begin from a clean state. The group also contains a live
cross-transport operation-gate check: MCP starts a short demo acquisition, a simultaneous
valid TCP mutation must receive the active command and operation ID as a busy error, status
polling remains available, and the next TCP mutation is accepted after real completion.

Boundary coverage is intentionally not described as exhaustive yet. The API currently
exposes 54 commands, 15 explicitly ranged parameters, four config-driven enums, and 22
type-only parameters. The adversarial group crosses every configured absolute stage bound
and selected setter/relative-move bounds, but it does not yet exercise both sides of every
ranged parameter through every command that can carry it (notably acquisition lists,
camera/galvo/laser timing setters, row/index values, and time-lapse arguments).

`test_remote_control.py` (here, in `pull_request/`) rebuilds both modules straight
from the `0001-*.patch` new-file hunks and checks the promises **without Qt**:
framing round-trips, the token is constant-time, bad **values** are refused
(type / option / range for every settable, not just the stage), the limits come from
`cfg.stage_parameters` end to end, both lanes refuse an out-of-limit call with an error,
and the MCP reply shape is right. `test_remote_control_adversarial.py` (also here) is a
**wide** sweep that tries to break the two guarantees: ~20 hostile method names
(dunders, dotted paths, Python expressions, unicode/whitespace/NUL variants) that must
never run, every malformed envelope shape, every axis breached in both directions,
`NaN`/`inf`/huge numbers, type confusion in every value slot, attempts to *change* the
limits, MCP hostile `tools/call` names turned into `isError` JSON, and framing/auth
tricks — all against a `_RecordingCore` so each refusal is proven to leave the Core
**untouched**. `test_viability_check.py` stands up the real server on both lanes and runs
the operator's viability check; `test_remote_control.py` also proves the start-time
self-test **gate** (a config with no limits makes construction raise before it ever binds).
`test_remote_control_transport_harsh.py` adds a **black-box transport sweep**: every attack
enters through a real loopback MCP/HTTP request or framed TCP socket, MCP forwards through
TCP exactly as it does in production, and a recording fake Core proves rejected inputs never
reach instrument methods. It covers duplicate auth/origin headers and JSON members,
non-finite numbers, relative-move limit crossings, oversized MCP bodies/TCP frames,
Unicode/delimiter fuzz, malformed JSON-RPC, auth/origin bypass strings, pipelining, and
post-attack liveness.
`test_remote_control_transport_valid.py` is the matching positive black-box contract matrix:
one representative, usable request for every one of the 54 allowlisted commands, sent over
both real loopback MCP/HTTP and framed TCP paths (108 transport cases), plus a completeness
check that fails when the allowlist and test table drift apart. It also verifies the Core
call, state change, or returned value expected from each command.
`test_remote_control_live_demo_all.py` is the corresponding real-Core demo sweep. It logs
each command, verifies observable readback where available, continues after a failure so one
run identifies every broken command, and restores demo state in a `finally` block.
The shipped `test_remote_control_validation.py` covers the same `_validate` gate against the
real module. The complete offline suite is **177 passing tests in under 5 seconds** on the Windows test
environment. The offline/adversarial tests are deliberately bounded: no `sleep`, no unbounded fuzz or retries, at most
48 seeded mutations, and a 0.6-second deadline on every test socket.
**Validated on the bench against mesoSPIM `-D` demo mode
(2026-07-13):** the Remote Control tab starts and drives the demo Core end to end
over **both lanes — framed TCP and MCP-over-HTTP — and it worked as-is** (the
54 command contracts and all 40 operational calls passed with state restoration). **Real-hardware** validation
is the only remaining step.

## How to apply

Cut against **`release/candidate-py312`**, so from that branch it applies cleanly:

```bash
git checkout release/candidate-py312
git checkout -b remote-control
git am 0001-Add-optional-Remote-Control-tab-TCP-MCP-named-call-s.patch
```

(If your tip has drifted, use `git am --3way`.) Then launch mesoSPIM and use the
**Remote Control** tab → **Start**.

## How a driver builds on it

An external driver is *one client* of this bridge — see
[`demo_client.py`](demo_client.py) for the whole protocol in ~40 lines (frame a
call, read the reply line, parse the JSON). A driver's command vocabulary lives
on the client side as a mirror of `COMMANDS`; mesoSPIM learns no client concepts.

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com. Patch license: **GPL-3.0** (part of mesoSPIM-control).
