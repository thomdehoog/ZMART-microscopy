# Upstream PR — built-in command server for mesoSPIM-control

This folder documents a proposed **upstream contribution to
[mesoSPIM-control](https://github.com/mesoSPIM/mesoSPIM-control)**: an opt-in,
off-by-default **external command server** that gives mesoSPIM a TCP control API,
started from a GUI button (**Tools → Command Server…**).

It is the "first-class" end state described in the driver
[`../TODO.md`](../TODO.md) and [`../README.md`](../README.md): once (a version of)
this lands in mesoSPIM, an operator just clicks a button — no Script-Window
loader to paste — and the ZMART driver connects to it unchanged. Until then, the
committed [`../server/scriptwindow_loader.py`](../server/scriptwindow_loader.py)
is the zero-fork way to get the same server running.

**Status:** drafted, built, and **validated against the real mesoSPIM-control
software in `-D` demo mode** (v1.20.0). Not yet submitted upstream. Nothing here
changes the ZMART driver — it is a patch *for mesoSPIM*.

## What the PR does

mesoSPIM-control has **no external API**: everything runs in-process inside the
Qt event loop, so a separate program cannot drive the microscope. The PR adds a
small TCP server that turns a line-oriented JSON protocol
([`PROTOCOL.md`](PROTOCOL.md)) into `mesoSPIM_Core` actions — calling the **same
`Core` methods the GUI buttons call**. So an external process moves stages,
changes state, and runs acquisitions exactly as a click would.

Three files (all inside mesoSPIM):

| File | Change |
|---|---|
| `mesoSPIM/src/mesoSPIM_CommandServer.py` | **New.** The server: a `QTimer`-polled (non-blocking) `QTcpServer`, JSON dispatch, and a single `_CoreBridge` class holding every `Core`-touching call. Optional shared-token auth (fail-closed, constant-time compare over UTF-8 bytes). |
| `mesoSPIM/src/mesoSPIM_Core.py` | `start_command_server(host, port, token)` / `stop_command_server()` slots. |
| `mesoSPIM/src/mesoSPIM_MainWindow.py` | A **Tools → Command Server…** menu entry (added in code, no `.ui` change) opening a small Start/Stop dialog (host / port / token + a token generator); stops the server on app close. |

## Design notes (why it should be mergeable)

- **Opt-in, off by default.** Nothing binds a socket unless an operator clicks
  Start, so existing users see zero behaviour change.
- **Correct threading.** The `Core` runs on its own `QThread`. The menu emits a
  **queued** signal to `Core.start_command_server`, so the server's socket and
  poll-timer are created **on the Core thread** — where the Core's work runs.
  This is the thread placement that makes `wait_until_done` moves and
  acquisitions behave; it is the configuration validated below.
- **Small surface to re-verify.** Every `Core`/`cfg` name the server touches is
  isolated in `_CoreBridge`; names follow mesoSPIM-control v1.20.0.
- **Security is honest.** Plain TCP. The token gates casual access on a trusted
  LAN; it is **not** sniffer-proof. Default bind is `127.0.0.1`; binding to the
  network with no token prompts a confirmation. For untrusted networks, tunnel it
  (SSH/VPN).

## How to apply

From a mesoSPIM-control checkout:

```bash
git checkout -b command-server
git am /path/to/0001-Add-optional-external-command-server-Tools-Command-S.patch
# or, if you prefer not to keep the authorship/message:
#   git apply 0001-...patch
```

Then launch mesoSPIM and use **Tools → Command Server… → Start**.

## How it was validated

Built the real mesoSPIM app (`-D` demo backends) headless and exercised the
**button's actual mechanism** — emitting `MainWindow.sig_start_command_server`,
which is exactly what the dialog's *Start* does — then drove it with the ZMART
client:

- Menu action present; emitting the signal starts the server **on the Core
  thread** (`listening on 127.0.0.1:42000 (token required)`).
- Full round-trip passes against the live demo `Core`: `connect → get_config →
  get_state → move → get_position → acquire` (a real acquisition through the
  image writer), **including a non-ASCII token** (`bütton`); a wrong token is
  refused.

## Relationship to the ZMART driver

- The driver connects to `host:port` (with an optional `token`) **regardless of
  how the server was started** — Script-Window loader today, this button later.
  No driver change is needed to adopt the PR.
- The wire protocol here ([`PROTOCOL.md`](PROTOCOL.md)) is the **same contract**
  the driver's [`../protocol.py`](../protocol.py) implements; keep them in sync.
- `mesoSPIM_CommandServer.py` in the patch is the in-tree form of the driver's
  [`../server/mesospim_command_server.py`](../server/mesospim_command_server.py)
  (identical logic; the in-tree copy is imported normally, so it needs no
  Script-Window loader).

---
Author: Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
thomdehoog@gmail.com. Patch license: **GPL-3.0** (it is part of mesoSPIM-control).
