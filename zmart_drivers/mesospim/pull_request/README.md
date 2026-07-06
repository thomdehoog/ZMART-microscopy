# Upstream PR — remote control for mesoSPIM-control

A **minimal** proposed contribution to
[mesoSPIM-control](https://github.com/mesoSPIM/mesoSPIM-control): let an external
process control mesoSPIM over a socket by sending **named calls** — one small
feature, **Tools → Remote Scripting…**, that any driver (ZMART included) can build
on. Nothing here changes the ZMART driver; it is a patch *for mesoSPIM*.

## The idea (why it is this small)

A client sends one single-key JSON object, `{"<method>": {args}}`. The server
validates it, looks the method up in a fixed allowlist (`COMMANDS`), and runs the
matching `mesoSPIM_Core` call — the same methods the GUI's own buttons call. It
returns a JSON result line. **No client Python is ever run**: the "method" is only
ever a dict-key lookup, so a client can only invoke operations the allowlist names.

The **same port** also speaks **MCP** (JSON-RPC over HTTP), so an off-the-shelf LLM
client can drive the scope by URL: `tools/list` *is* the allowlist, a `tools/call`
runs one method — the same validated dispatch, just a different envelope. Two
doors, one lock; the server picks the lane from the first bytes of a connection.

```
  a script (framed TCP)                                        INSIDE mesoSPIM
  {"move_absolute": {…}}  ─────────▶──────────┐               (Core context)
  __ZMART_OK__{…}         ◀─────────◀─────────┤
                                              ├──▶  COMMANDS["move_absolute"](core, …)
  an LLM (MCP over HTTP)                       │        (one allowlist dispatch)
  POST {"method":"tools/call",…}  ──▶─────────┘
  {"result":{…}}                  ◀── json
```

## What the PR does — 3 files

| File | Change |
|---|---|
| `mesoSPIM/src/mesoSPIM_RemoteScripting.py` | **New.** A signal-driven `QTcpServer` serving two lanes on one port: framed named calls (scripts) and MCP-over-HTTP (LLMs), both dispatched against the fixed `COMMANDS` allowlist → `__ZMART_OK__<json>` / a JSON-RPC result. Framing, auth, and the whole dispatch (`frame`, `FrameDecoder`, `AuthGate`, `COMMANDS`, `handle_message`, `_mcp_reply`) are socket-free helpers that unit-test without Qt; `QtNetwork` is imported lazily. Constant-time token compare; HTTP adds a Bearer-token check and an Origin guard. A new client preempts a stale one. |
| `mesoSPIM/src/mesoSPIM_Core.py` | `start_remote_scripting(host, port, token)` / `stop_remote_scripting()` slots, plus a `sig_remote_scripting_started(ok, message)` signal so a bind failure (e.g. port in use) is reported instead of the GUI showing a false "running". |
| `mesoSPIM/src/mesoSPIM_MainWindow.py` | A **Tools → Remote Scripting…** menu entry (added in code, no `.ui` change) with a Start/Stop dialog (host / port / token + generator); reflects the real start outcome; stops on app close. |

## Wire protocol

Length-framed UTF-8, both directions: `b"<decimal-byte-count>\n" + payload`. If a
token is set, the **first** frame must be it (`OK` / `AUTH-FAILED`). Every frame
after that is a call, `{"<method>": {args}}`; the reply is one `__ZMART_OK__<json>`
line (or error text). See [`PROTOCOL.md`](PROTOCOL.md).

## Security

A named call still **controls the microscope** (moves the stage, runs
acquisitions), but it is **not** arbitrary code — the server only ever does a dict
lookup + a fixed call, so nothing outside `COMMANDS` can run. Still:

- **Off by default**; started by an operator from the GUI.
- **Binds `127.0.0.1`** unless changed; the dialog warns before a network bind
  without a token.
- **Optional token** gates access (constant-time compare); over HTTP it is an
  `Authorization: Bearer <token>` header.
- **Origin guard (HTTP)**: any non-localhost `Origin` is rejected, so a web page in
  the operator's browser can't drive the instrument (DNS-rebinding / CSRF).
- **Plain TCP**: the token guards casual LAN access, **not** sniffer-proof. For
  untrusted networks, tunnel it (SSH/VPN) — out of scope for this minimal PR.

## Tests

Framing, the token gate, dispatch, **and the HTTP path** carry Qt-free unit tests
that run in ordinary CI (`test_remote_scripting.py`): frame boundaries, oversized
input, constant-time compare incl. a non-ASCII token, an adversarial sweep (unknown
method, a Python-expression method name, a `__dunder__` name, a multi-key object,
malformed JSON — all rejected without running anything), and the two HTTP guards
(foreign Origin → 403, missing/wrong Bearer → 401). The live `-D` end-to-end run
(a real Core moving the demo stage) is the remaining check.

## How to apply

```bash
git checkout -b remote-scripting
git am 0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch
```

Then launch mesoSPIM and use **Tools → Remote Scripting… → Start**.

## How ZMART builds on it

The ZMART mesoSPIM driver is *one client* of this bridge — see
[`demo_client.py`](demo_client.py) for the whole protocol in ~40 lines (frame a
call, read the reply line, parse the JSON). The driver's command vocabulary lives
on the ZMART side as a mirror of `COMMANDS`; mesoSPIM learns no ZMART concepts.

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com. Patch license: **GPL-3.0** (part of mesoSPIM-control).
