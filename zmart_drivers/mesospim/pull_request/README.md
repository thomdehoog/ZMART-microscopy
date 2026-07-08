# Upstream PR — Remote Control for mesoSPIM-control

A proposed contribution to
[mesoSPIM-control](https://github.com/mesoSPIM/mesoSPIM-control): let an external
process control mesoSPIM over a socket by sending **named calls** — a **Remote
Control** tab that any driver (ZMART included) can build on. Nothing here changes
the ZMART driver; it is a patch *for mesoSPIM*.

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
  __ZMART_OK__{…}         ◀─────────◀──────────┤
                                               ├──▶  COMMANDS["move_absolute"](core, …)
  an LLM (MCP over HTTP)     ┌── forwards ──────┘        (one validated dispatch)
  POST /mcp {"tools/call"} ──┤  a framed TCP call
  {"result":{…}}           ◀─┘  (separate MCP process)
```

## What the PR does — the files

| File | Change |
|---|---|
| `mesoSPIM/src/mesoSPIM_RemoteControl_ValidateAndRunCommands.py` | **New.** The command vocabulary (`COMMANDS` allowlist), the arg gate `_validate` (shape + allowed option + in-range), and `run()` — the **single choke point** both transports share. Pure stdlib; unit-tested without Qt. |
| `mesoSPIM/src/mesoSPIM_RemoteControl_Servers.py` | **New.** A signal-driven `QTcpServer` (`RemoteControlTCPServer`) hosted by the Core that dispatches framed named calls, **and** a standalone MCP-over-HTTP server (its own process, `--port` default `42100`) that forwards `tools/call` to that TCP server. Framing, auth, and dispatch are socket-free helpers. Constant-time token; HTTP adds a Bearer check and an Origin guard. |
| `mesoSPIM/src/mesoSPIM_Core.py` | `start_remote_control(host, port, token)` / `stop_remote_control()` slots, plus a `sig_remote_control_started(ok, message)` signal so a bind failure (e.g. port in use) is reported instead of a false "running". |
| `mesoSPIM/src/mesoSPIM_MainWindow.py` | A **Remote Control tab** (TCP / MCP mode, host / port / token + generator); reflects the real start outcome; stops on app close. |
| `mesoSPIM/src/test_remote_control_validation.py` | Qt-free tests for the `_validate` gate. |
| `pyproject.toml` | A `mesospim-mcp-server` console entry point for the standalone MCP server. |

## Wire protocol

Length-framed UTF-8, both directions: `b"<decimal-byte-count>\n" + payload`. If a
token is set, the **first** frame must be it (`OK` / `AUTH-FAILED`). Every frame
after that is a call, `{"<method>": {args}}`; the reply is one `__ZMART_OK__<json>`
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
name — with a message the caller can act on:

- **shape** — `targets`/`deltas` an object of `axis → number`, `settings` an object.
- **allowed option** — `filter`/`zoom`/`laser`/`shutterconfig` must be one the live
  `cfg` allows; `intensity` ∈ `[0, 100]`.
- **range** — `move_absolute` targets against optional per-axis soft limits from
  `MESOSPIM_RS_LIMITS` (a JSON object `{"x": [lo, hi], …}` or a path to one). Unset
  → no soft limit (the Core's hardware bound is the backstop).

## Tests

`test_remote_control.py` (here, in `pull_request/`) rebuilds both modules straight
from the `0001-*.patch` new-file hunks and checks the promises **without Qt**:
framing round-trips, the token is constant-time, bad **values** are refused
(shape / option / range), the MCP reply shape is right, and a hostile-payload sweep
(unknown method, a Python-expression name, a `__dunder__`, a multi-key object,
malformed JSON) is rejected without running anything. The shipped
`test_remote_control_validation.py` covers the same `_validate` gate against the
real module. The live `-D` end-to-end run (a real Core moving the demo stage, over
both TCP and MCP) is the remaining check.

## How to apply

```bash
git checkout -b remote-control
git am --3way 0001-Add-optional-Remote-Control-tab-TCP-MCP-named-call-s.patch
```

(`--3way` because the patch is cut from the candidate base; it merges cleanly onto
a newer tip.) Then launch mesoSPIM and use the **Remote Control** tab → **Start**.

## How ZMART builds on it

The ZMART mesoSPIM driver is *one client* of this bridge — see
[`demo_client.py`](demo_client.py) for the whole protocol in ~40 lines (frame a
call, read the reply line, parse the JSON). The driver's command vocabulary lives
on the ZMART side as a mirror of `COMMANDS`; mesoSPIM learns no ZMART concepts.

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com. Patch license: **GPL-3.0** (part of mesoSPIM-control).
