# Upstream PR — remote scripting for mesoSPIM-control

A **minimal** proposed contribution to
[mesoSPIM-control](https://github.com/mesoSPIM/mesoSPIM-control): let an external
process send a Python script to the Script Window over a socket and get its
console output back. One small feature — **Tools → Remote Scripting…** — that any
driver (ZMART included) can build on.

**Status:** built and **validated against the real mesoSPIM software in `-D` demo
mode** (v1.20.0). Not yet submitted upstream. Nothing here changes the ZMART
driver — it is a patch *for mesoSPIM*.

## The idea (why it is this small)

mesoSPIM already runs Python in the live Core via its **Script Window**
(`Core.execute_script`, `self` == Core). This PR just makes that reachable from
another process. So it adds **no command vocabulary, no data format, no control
semantics** — it is *text in, console text out*. A client scripts the scope with
the full mesoSPIM Python API and `print()`s whatever it wants back. Everything
opinionated (a command set, error semantics, structured results) lives in the
*client*, injected as a script — not in mesoSPIM.

```
  external process ──socket──▶  Remote Scripting server (in mesoSPIM)
     sends a script                runs it via the EXISTING Core.execute_script,
                                    with stdout/stderr captured
     ◀───────────────              returns the captured console text
```

## What the PR does — 3 files, ~276 lines

| File | Change |
|---|---|
| `mesoSPIM/src/mesoSPIM_RemoteScripting.py` | **New.** A signal-driven `QTcpServer`. For each received script it runs the **existing** `Core.execute_script` with stdout/stderr redirected into a buffer, and returns the buffer. Optional shared-token gate (constant-time compare over UTF-8 bytes). |
| `mesoSPIM/src/mesoSPIM_Core.py` | `start_remote_scripting(host, port, token)` / `stop_remote_scripting()` slots. |
| `mesoSPIM/src/mesoSPIM_MainWindow.py` | A **Tools → Remote Scripting…** menu entry (added in code, no `.ui` change) with a Start/Stop dialog (host / port / token + generator); stops on app close. |

**`execute_script` is reused unmodified** — the PR only puts a socket in front of
a method mesoSPIM already has. That is the whole pitch, and why it should be easy
to review.

## Wire protocol

Length-framed UTF-8, both directions:

```
message = b"<decimal-byte-count>\n" + <payload bytes>
```

If a token is set, the **first** frame the client sends must be the token; the
server replies `OK` or `AUTH-FAILED` (and closes on failure). Every frame after
that (or every frame, when no token) is a **script**; the reply frame is the
captured console output. See [`PROTOCOL.md`](PROTOCOL.md).

## Security — read this

A received script is **arbitrary Python on the acquisition PC** (it can touch the
filesystem, not just the scope). So:

- **Off by default**; started by an operator from the GUI.
- **Binds `127.0.0.1`** unless changed; the dialog warns before binding to the
  network without a token.
- **Optional token** gates access (constant-time compare). Because the payload is
  arbitrary code, the token matters *more* here than for a bounded command set —
  a token-holder can run anything.
- **Plain TCP**: the token is a gate against casual/accidental LAN access, **not**
  sniffer-proof. For untrusted networks, tunnel it (SSH/VPN) or add TLS — out of
  scope for this minimal PR (and a decision the maintainers can make separately).

## One faithful wrinkle

The reply is the process console output *during* the script's run, so it can
interleave with messages other threads print at the same time — exactly as the
Script Window console does. A client that needs a clean result should delimit it
with a marker and extract between markers (see the demo below).

## How to apply

```bash
git checkout -b remote-scripting
git am 0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch
```

Then launch mesoSPIM and use **Tools → Remote Scripting… → Start**.

## How it was validated

Built the real mesoSPIM app (`-D` demo backends) headless and started the server
through the **button's real signal path** (`sig_start_remote_scripting`), then
drove it from a raw socket client:

- wrong token → `AUTH-FAILED`; correct (non-ASCII) token → `OK`;
- `print(self.state['position'])` → real position returned;
- structured output via `print(json.dumps(...))` → parsed;
- `self.move_absolute({'x_abs':1234,'z_abs':42}, wait_until_done=True)` → the
  **demo stage actually moved** (position became 1234.0 / 42.0);
- a script that raises → traceback returned as text, no crash.

## How ZMART builds on it

The ZMART driver is *one client* of this bridge. Its command vocabulary,
threading helpers, and result format live on the ZMART side and are injected as
scripts. See [`demo_client.py`](demo_client.py) for the marker-delimited pattern
(send a script, read the console frame, extract the result between markers).

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com. Patch license: **GPL-3.0** (part of mesoSPIM-control).
