# Evident FLUOVIEW integration — findings & architecture (RDK route)

> **Status:** investigation / planning. No driver code yet. This document captures what the
> Evident/Olympus **Remote Development Kit (RDK)** is, grounded in the publicly-documented Olympus
> RDK family, and what it means for a `drivers/evident/` driver that sits beside
> `drivers/leica/stellaris5_y42h93/navigator_expert/`, `drivers/nikon/`, and `drivers/zeiss/zenapi/`.
>
> **Target instrument (ZMB):** Evident **FLUOVIEW FV4000** confocal on an **Olympus IX83** inverted
> stand — motorized XYZ stage (IX3-SSU) + hardware autofocus (IX3-ZDC2), resonant scanner, SilVIR SiPM
> detectors (6 ch), 10 laser lines incl. NIR, objectives 2×/20×/40× (air) + 30×/60× (silicone oil),
> cellVIVO stage-top incubation. Control software: **cellSens-FV** (v3.x).
> ([ZMB system page](https://www.zmb.uzh.ch/en/Available-Systems/LightMicroscopes/CLSM/CLSMEvident.html))
>
> **Route chosen:** the **RDK** (external TCP command server), following the FV3000 RDK model — the
> Leica-CAM-/Nikon-NkSocket-symmetric route.
>
> **Access caveat:** the actual FV-series RDK command reference is behind **Evident's developer
> program** and is not public. The concrete command vocabulary below is drawn from the publicly
> documented sibling **OLS5000 RDK** as the closest evidence; the FV confocal verbs differ and must be
> pinned from the real FV RDK. **This is the single blocker to a driver.**

---

## TL;DR

- Olympus/Evident ships **Remote Development Kits (RDKs)** for its instruments. The documented ones
  work the same way: the **microscope PC runs an RDK TCP server**; an **external client connects and
  sends text "macro" commands** (`COMMAND= arg1,arg2`), and the server replies with an
  acknowledgement (`COMMAND= +` on success).
- This is **architecturally identical to Leica LAS X CAM and Nikon NkSocket** — an external Python
  orchestrator driving the scope over a socket with a text command protocol. So the Evident driver is
  a **sibling `drivers/evident/...`** on the same neutral waist (connection + command vocabulary +
  state readers), **with no architectural inversion**.
- The **FV3000 had an RDK**; the FV3000 is now discontinued and Evident's current FLUOVIEW line (the
  **FV4000** at ZMB) carries it forward. The FV4000's RDK availability + command set must be confirmed
  with Evident.
- The IX83 stand also has a device **SDK** (driven from Python by others) and **cellSens-FV** has
  in-application automation — these are alternative/lower layers, not the RDK route (see
  [Alternative layers](#alternative-control-layers)).

---

## Evidence: how the Olympus/Evident RDK works

The FV3000 RDK page now redirects to a discontinued-product notice, and the FV RDK reference itself is
gated. The **OLS5000 RDK** (Olympus LEXT laser microscope) is the closest **publicly documented**
member of the same RDK family, with open C# sample code — it establishes the family's shape:

- **Transport:** TCP sockets. The **RDK runs as a TCP *server*** on the controller PC; the user's
  program is the **TCP client**. (OLS5000: port `50100`; controller `192.168.0.1`, client
  `192.168.0.2`.)
- **Command format:** text strings, `COMMAND= param1,param2` (equals delimiter, comma-separated args),
  sent with a socket `Write()`.
- **Acknowledgement:** the server echoes `COMMAND= +` on success.
- **Representative commands** (OLS5000 vocabulary — *illustrative of the shape, not the FV verbs*):

  | Purpose | OLS5000 command |
  |---|---|
  | Connect / login | `CONNECT= 0`, `INITNRML= <id>,<pw>` |
  | Move XY stage (µm) | `MVSTG= x,y` (e.g. `MVSTG= -50000,50000`) |
  | Switch objective | `CHOB= <1-6>` |
  | Change zoom/mag | `CHZOOM= <value>` |
  | Z home | `MVZHOME= 0` |
  | Load / run a macro | `RDWIZ= <name>`, `WIZEXE= 0` |
  | Mode / disconnect | `CHMODE= 0`, `DISCONNECT= 0` |

  Note the stage command takes **micrometers** (unlike Zeiss ZEN's SI meters) and the objective is a
  **turret index** — both convenient for our existing conventions.

Sources: [OLS5000 RDK C# sample (ospqul/OLS50C_RDK_Demo)](https://github.com/ospqul/OLS50C_RDK_Demo),
[FV3000 RDK (now redirects to discontinued notice)](https://evidentscientific.com/en/products/obsolete/fv3000),
[Evident FV4000](https://evidentscientific.com/en/products/confocal/fv4000).

---

## Architecture

### Leica vs Nikon vs Evident — same shape

| | Leica (built) | Nikon (spike) | **Evident (RDK route)** |
|---|---|---|---|
| Transport | LAS X CAM socket | NkSocket TCP | **RDK TCP** (server on scope PC) |
| Protocol | text commands | text `!<MacroCmd>;` | **text `COMMAND= args`** lines |
| Control locus | external Python | external Python | **external Python orchestrator** |
| Ack / read-back | echo model / log | reply line (ours to design) | **`COMMAND= +` ack; queries TBD** |
| Units | µm | (TBD) | **µm (per OLS5000 `MVSTG`)** |

Because the RDK is a text-command socket, the Evident driver reuses the **exact skeleton** already
proven for Leica and mirrored for Nikon/Zeiss:

```
drivers/evident/fv4000/rdk/         (eventual path; vendor/machine/api)
  connection/    TCP client to the RDK server + session (connect/login/disconnect)
  commands/      dispatch backbone + RDK verb wrappers (move_xy, move_z, set_objective, acquire, ...)
  readers/       parse acks / query replies into state
  config/        profiles (host/port/login; per-command confirm/retry tuning)
  motion/        µm safety limits (reuse), backlash
  acquisition/   acquire() + save()
  tests/         offline mock RDK server (fake TCP) + hardware-gated smokes
```

The dispatch/confirm/retry backbone, `CommandProfile`, motion limits, neutral acquisition product
types, and the test/mock pattern are **vendor-neutral** and copied from the Leica driver; only the
transport (RDK socket) and the command vocabulary are Evident-specific.

### Reuse the Nikon round-trip spike

The Nikon spike (`drivers/nikon/spike/`) is a text-over-TCP client with `?query`→reply framing. The
Evident RDK is the same shape (text command + `= +` ack), so the **first Evident step is a near-copy
of that spike** pointed at the RDK server — connect, send a benign query/command, read the ack —
before any driver code.

---

## Command vocabulary to pin (the blocker)

The real **FV confocal RDK** verbs are not public. Pin these from the Evident FV RDK reference (or by
inspecting the RDK on the bench) before driver work — the OLS5000 names are only a shape guide:

| Capability | Needed | OLS5000 analog |
|---|---|---|
| Connect / authenticate / disconnect | ✅ | `CONNECT`, `INITNRML`, `DISCONNECT` |
| Stage XY move (µm) + read-back | ✅ | `MVSTG` |
| Focus Z move + read-back | ✅ | `MVZHOME` (home only shown) |
| Objective / zoom | ✅ | `CHOB`, `CHZOOM` |
| **Acquire / scan (confocal image)** | ✅ | *(not in OLS5000; FV-specific)* |
| Laser lines / power | ✅ | *(FV-specific)* |
| Detectors (SilVIR) / channels | ✅ | *(FV-specific)* |
| Live / resonant scan control | ➖ | *(FV-specific)* |
| ZDC2 hardware autofocus | ➖ | *(IX3-ZDC2-specific)* |
| State queries (position, status) | ✅ | design the request/response like Nikon's `?query` |

---

## Can do / can't do (grounded)

### ✅ Can do (if the FV RDK is obtained)
- Drive the FV4000 **externally over TCP** from our Python orchestrator, exactly like Leica/Nikon.
- Send **text commands + read acks**; **load and execute macros** on the scope (`RDWIZ`/`WIZEXE` analog).
- Stage in **micrometers**, objective by **index** — matches our conventions; motion limits reuse directly.
- Slot straight into the existing driver skeleton (connection + commands + readers + profiles).

### ❌ Can't do yet
- **No public FV RDK API** — the command reference is behind Evident's developer program; **must be
  obtained** (this is the blocker).
- **FV4000-vs-FV3000 RDK parity unconfirmed** — the FV3000 had an RDK; confirm the FV4000 exposes an
  equivalent and get its version/command set.
- **No confirmed Python binding** — the public samples are **C#**; the socket protocol is
  language-agnostic (we'd write a plain Python TCP client), but there is no official Python SDK to lean on.
- **State read-back protocol** — beyond `= +` acks, structured queries (position/status) may be ours to
  design, as with Nikon.
- **Licensing / access** — RDKs are gated; ZMB would need to request the FV RDK from Evident (and it
  may be a paid/licensed add-on).

---

## Alternative control layers (not the RDK route)

- **IX83 frame SDK** — the motorized stand (IX3-SSU stage, objectives, IX3-ZDC2) has an Olympus/Evident
  device SDK that others drive from **Python** ([Image.sc: IX83 SDK in Python](https://forum.image.sc/t/i-would-like-to-control-the-ix83-using-its-sdk-in-python/106874)).
  Covers stage/focus/objective but **not** the confocal scan/acquire — a lower layer than the RDK.
- **cellSens-FV automation** — the FV4000's own software has the Experiment/Process manager, macros,
  and reportedly a Python scripting environment. This is *in-application* control (a possible inversion,
  like ZEN OAD / NIS embedded Python) — a hybrid partner to the RDK, not a replacement.

---

## Next steps

1. **Obtain the FV4000 RDK** from Evident (developer program) — confirm availability for the FV4000,
   licensing, and get the command reference. *Everything else is blocked on this.*
2. **Pin the confocal command vocabulary** (stage/Z/objective/**acquire**/laser/detector/query) from the
   FV RDK reference or bench inspection.
3. **Round-trip spike** — fork the Nikon `spike/` TCP client at the RDK server: connect → login →
   read-back a position/status → one benign command. Proves the loop before driver code.
4. **Grow into `drivers/evident/fv4000/rdk/`** — copy the Leica skeleton, implement connection +
   commands + readers against the pinned verbs, offline-test against a mock RDK TCP server.

The FV4000's motorized XYZ + hardware autofocus (ZDC2) + multi-objective + live-cell incubation make it
an excellent fit for the smart-microscopy adaptive workflow (2× overview → segment → 40×/60× target).

---

## References
- ZMB system: <https://www.zmb.uzh.ch/en/Available-Systems/LightMicroscopes/CLSM/CLSMEvident.html>
- Evident FV4000: <https://evidentscientific.com/en/products/confocal/fv4000>
- FV3000 (discontinued; RDK lineage): <https://evidentscientific.com/en/products/obsolete/fv3000>
- OLS5000 RDK C# sample (RDK family shape): <https://github.com/ospqul/OLS50C_RDK_Demo>
- IX83 SDK from Python (Image.sc): <https://forum.image.sc/t/i-would-like-to-control-the-ix83-using-its-sdk-in-python/106874>

<!-- Investigation date: 2026-07-01. Maintainer: Thom de Hoog (ZMB / University of Zurich),
     thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com. License: MIT.
     RDK command shape grounded in the public OLS5000 RDK; FV RDK verbs pending Evident developer access. -->
