# Nikon NIS-Elements integration — findings & architecture

> **Status:** investigation / planning. No driver code yet. This document captures what the
> Nikon macro-library bundle actually contains and what it means for a `drivers/nikon/` driver
> that sits beside `drivers/leica/stellaris5_y42h93/navigator_expert/`.
>
> **Target instrument:** lab runs **NIS-Elements 6.2** (= 6.20).
> **Contact:** Kees van der Oord, Nikon (`Kees.van.der.Oord@nikon.com`), who pointed us at the
> Macro Utility Libraries module (email 2026-06-18).
> **Source material:** `C:\Users\t.de\Desktop\Nikon api (1)\` (collected `Nk*.dll`, interface
> macros, ~50 legacy LUCIA example macros, and the `NkMacroLibs_6.20.00.exe` installer).
> Installed canonical locations on an NIS box: `C:\Program Files\NIS-Elements\{macros,examples}`.

---

## TL;DR

- NIS-Elements exposes automation through **three layers**: (1) the classic LUCIA/LIM C-like
  **macro language**, (2) the **`Nk*` utility DLLs** (the "Macro Utility Libraries" Kees sent),
  and (3) an **embedded Python** interpreter (`limpy` in 6.x, `limjob`/`nis.mac` in 7.x).
- **The decisive find:** `NkSocket.dll` is a full TCP client/server stack, and the bundled
  `NkSocketServerDemo.mac` already implements a **command protocol** — any socket line starting
  with `!` is executed as a NIS macro command via `Int_ExecuteCommand(...)`.
- **Consequence:** NIS can be driven *exactly the way LAS X is* — an **external Python
  orchestrator** sending text commands over a socket. So our existing driver shape
  (connection + command vocabulary + state readers) **generalizes to Nikon**; Nikon becomes a
  sibling driver speaking the same neutral "waist", with **no architectural inversion**.
- This **reverses** an earlier read (made before the socket library was extracted) that Nikon
  forces the control loop inside NIS and that only a REST analysis-service could be shared. See
  [Correction](#correction-supersedes-the-first-read).

---

## Capabilities — what we can and can't do (grounded in the 6.2 bundle)

> Verified 2026-07-01 by an exhaustive read of every macro in the bundle (48 `SampleAPI_*.mac`, the
> interface/library `.mac` files, and the socket/serial/process demos extracted from **inside**
> `NkMacroLibs_6.20.00.exe` — a plain zip, not loose files). DLLs are native C/C++ (no .NET); each
> utility DLL's full callable surface is declared in its paired `.mac`, so no decompilation was needed.

### ✅ Can do
- **Drive NIS from an external process over TCP.** `NkSocket.dll` is a full client/server;
  `NkSocketServerDemo.mac` runs any socket line prefixed with `!` via `Int_ExecuteCommand(pid, cmd)`.
  Architecturally identical to the Leica CAM route.
- **Run any NIS command or macro by name** — `Int_ExecuteCommand`, `RunMacro`, `Int_ExecProgram`,
  gated by `ExistProc`.
- **Run Python inside NIS** — `limpy.mac` → `v6_gnr_python.dll` (`Python_RunString`, `Eval*`, `SetAttr/Item*`).
- **Have NIS launch our Python** — `CreateProcess.mac` (`CreateProcessW`), or `ShellExecuteW`.
- **Serial/COM device control** — `NkComPort` (Arduino demo).
- **Build a request/response protocol** — the socket is bidirectional; `NkString.dll` provides regex
  + a key/value StrMap to parse a `?query`→reply inside the macro.
- **Read state (read-only getters):** calibration µm/px per objective (`Get_Calibration`), device
  presence/status (`Get_Info(INFO_STAGEPRESENT/STAGEINIT/LIGHTPRESENT/LIVESTATUS/GRABBING…)`,
  `GetLightLevels`), image info / pixel type / size (`Get_ImageInfo`), pixel/RGB values, histograms,
  open-document list, paths, version/board strings.
- **Analyze images in-process:** threshold + particle analysis by Feret/circularity/mean-intensity
  (`makpud.mac`), `MeasureObject`/`MeasureField`, histograms, filters (Sobel, Golay, morpho, stretch).
  Native SDKs present: `NkUnmix2` (OpenCV spectral unmix), `NkImg2xProcess` (cell-distribution /
  segmentation), `NkLAppAutoAlignLib` (auto-align / autofocus) — invoked via NIS, not standalone.

### ❌ Can't do (with this bundle)
- **No device-motion / acquisition verbs anywhere.** Zero stage-move, Z/focus, capture/acquire,
  objective/nosepiece, shutter/filter/illumination/lamp/laser, or camera-select commands. The
  `!Capture();` in the server banner is a **string literal**, never defined. → The verb vocabulary
  must be pinned from the **NIS 6.2 macro command reference** (or from Kees). **This is the single
  blocker** to a working driver — everything else is ready.
- **No built-in state read-back** — the stock server is fire-and-forget; the `?query`→reply layer is ours.
- **No security** — `Int_ExecuteCommand` runs arbitrary text off the socket. Bind `127.0.0.1`
  (never `0.0.0.0`) and gate commands with an allow-list.
- **Embedded Python is version-locked** to 6.2 `limpy.*` names (7.x differs); whether the JOBS Python
  node and `requests`/`httpx` ship in 6.2 is unconfirmed.
- **Polling only** — the demo polls every ~500 ms (`WM_TIMER`); no event push.
- **Native SDK DLLs are not a clean external API** — no headers, invoked internally by NIS.

### Command inventory (what's actually in the bundle)
| Area | In bundle? | Evidence |
|---|---|---|
| TCP transport + `!cmd` dispatch | ✅ | `NkSocket.mac`, `NkSocketServerDemo.mac:240` |
| Embedded Python bridge | ✅ | `limpy.mac` |
| Process spawn / serial | ✅ | `CreateProcess.mac`, `NkComPort.mac` |
| Read-only getters (calibration, info, image, histogram) | ✅ | `SampleAPI_07/18/20/23/43.mac` |
| In-process analysis (Feret/circularity/measure/filters) | ✅ | `makpud.mac`, `SampleAPI_10/24/77.mac` |
| Stage / Z / capture / objective / illumination verbs | ❌ | absent — full read, zero hits |

---

## The three API layers

### 1. Classic macro language (LUCIA / LIM API)
C-like scripting interpreted inside NIS. The ~50 `SampleAPI_*.mac` examples are this layer:
`Get_Info`, `Get_Calibration`, `Get_ImageInfo`, `Get_Filename`, stage/light-driver presence
checks, and binary-image analysis (`Restrictions`, Feret, circularity — see `makpud.mac`).
Macro command strings can also be executed programmatically via `Int_ExecuteCommand(pid, cmd)`.

### 2. The `Nk*` utility DLLs (the Macro Utility Libraries)
Native libraries that extend the macro runtime. From `NkMacroLibs_6.20.00.exe`:

| Library / macro | Purpose |
|---|---|
| **`NkSocket.dll` / `NkSocket.mac`** | **TCP client + server** (see below) |
| `NkListen.exe` | standalone listener helper process |
| `NkWindow.dll` / `NkWindow.mac` | Win32 window automation, `NkDialog_*` dialogs, file I/O `NkFile_*` |
| `NkComPort.dll` / `NkComPort.mac` / `NkComPortCon.exe` | serial / COM-port control |
| `CreateProcess.mac` | spawn external processes (`CreateProcessW`, optional wait) |
| `NkPropSheet` / `NkListCtrl` / `RichEdit` / `NkString` / `NkPath` | UI + helper utilities |
| `Win32.mac` | raw Win32 constants + `Kernel32/User32/Shlwapi/Ole32` imports |
| `NkImgSDK.dll` (26 MB), `NkDatabase.dll`, `NkUnmix2.dll`, auto-align | image SDK / DB / spectral unmix |

Installer note: it is a zip self-extractor that runs `install.bat RUNASADMIN`; it deploys the
macros/examples under `C:\Program Files\NIS-Elements\` and bundles `VC_redist.x64.exe`.

### 3. Embedded Python
`limpy.mac` imports `v6_gnr_python.dll`, exposing `Python_RunString`, `Python_Eval{Int,Float,Str}`,
and `Python_SetAttr*/SetItem*` to macros. The interpreter is **embedded — a single interpreter
inside the NIS process** (confirmed by LIM's JOBS docs and the Smart Microscopy Working Group).

- **NIS 6.x** (our 6.2): `import limpy.macro as mac` / `import limpy.utils as utl`.
- **NIS 7.x**: `import limjob`; drive the scope via `nis.mac.<MacroCmd>(...)`
  (e.g. `nis.mac.PiezoXYMoveToXYPosition(0,0)`, `nis.mac.PiezoXYGetPosition(x,y)`,
  `nis.mac.GA3_Execute(...)`), with `nis.ptr.double()` wrappers for output-pointer params.

> ⚠ **Version caveat:** anchor any code that must run on the bench on the **6.2 `limpy.*`**
> names. The public 7.01 `JOBS-examples` (`limjob`/`nis.mac`) are directionally right but the
> module/function names differ — version-check before copying.

---

## The socket bridge (the important part)

`NkSocket.mac` — the full interface (small and clean):

```c
import("NkSocket.dll");
// port_or_service: "NIS_SERVICE", "54468", or "127.0.0.1:54468"
int NkSocket_Listen      (int64 *phSocket, char *port_or_service);   // NIS as TCP server
int NkSocket_Connect     (int64 *phSocket, char *addressport_or_service); // NIS as TCP client
int NkSocket_IsListening (int64 hSocket, char *buf, int count);
int NkSocket_IsConnected (int64 hSocket, char *buf, int count);
int NkSocket_Close       (int64 *phSocket);
int NkSocket_Write       (int64 hSocket, byte *data, long count);
int NkSocket_Read        (int64 hSocket, byte *data, long count, long timeout);
int NkSocket_WriteLine   (int64 hSocket, char  *line);   // lines terminated by '\r'
int NkSocket_ReadLine    (int64 hSocket, char  *data, long count, long timeout);
int NkSocket_WriteLineA  (int64 hSocket, char8 *line);   // ASCII variants
int NkSocket_ReadLineA   (int64 hSocket, char8 *data, long count, long timeout);
int NkSocket_IsValid     (int64 hSocket);
int NkSocket_GetErrorDescription(int err, char *buf, int count);
```

`NkSocketServerDemo.mac` is effectively a **ready-made command server**. Its receive loop:

```c
result = NkSocket_ReadLine(socket, bufW, 128, 0);
if (result > 0 && bufW[0] == '!') {
    // any line starting with '!' is executed as a NIS macro command
    Int_ExecuteCommand(GetCurrentProcessId(), bufW + 1);
}
```

The demo's own welcome banner says it plainly:
> *"Commands starting with a ! will be executed by NIS. E.G. !Capture();"*

So out of the box an external process can connect over TCP and send `!Capture();`,
`!StgMoveXY(...);`, `!<any macro command>;` and NIS runs it. `NkSocketClientDemo.mac` shows the
mirror case (NIS as the client connecting outward). `CreateProcess.mac` lets a macro launch our
Python process; `NkComPort.*` gives direct serial control of devices on COM ports.

---

## Architecture

### Leica vs Nikon — same shape

| | **Leica (existing)** | **Nikon (NkSocket route)** |
|---|---|---|
| Transport | LAS X CAM socket | `NkSocket` TCP |
| Protocol | text commands | text `!<MacroCmd>;` lines (`\r`-terminated) |
| Control locus | **external** Python orchestrator | **external** Python orchestrator |
| State read-back | log-tailing / CAM reads | macro writes response lines back over the socket |
| Process launch | — | `CreateProcess.mac` (NIS can spawn our Python) |

### Recommended: Route 1 — NkSocket external-orchestrator (Leica-symmetric)
Run a resident NIS macro (a fork of `NkSocketServerDemo.mac`) that listens on a TCP port. The
existing external Python orchestrator connects and sends commands; we **extend the demo protocol**
so the macro also writes state/values back (e.g. answer a `?Get_Calibration` query). This maps
~1:1 onto the Leica CAM driver, so `drivers/nikon/...` can be a sibling with:
`connection` (socket) + `commands` (macro vocabulary) + `readers` (parse responses), speaking the
**same neutral waist** as Leica.

### Available: Route 2 — embedded Python in JOBS, REST-out
The control loop lives inside NIS (JOBS + embedded Python) and calls **out** to an analysis
service. More NIS-native for tight feedback loops, but it inverts our architecture and depends on
the JOBS Python-node feature set in 6.2. Best treated as a **hybrid** partner to Route 1: sockets
for command/control from the orchestrator; embedded Python inside NIS for heavy in-process
analysis (CellPose-SAM, DINO) when we don't want to ship pixels back out.

### Implication for the vendor-neutral "waist"
The mid-layer contract is still unfrozen. This is the second-vendor leak-test, and the result is
encouraging: a **text-command-over-socket driver contract** is satisfiable by *both* LAS X CAM and
NkSocket, so keep the driver abstraction as the waist. (The analysis/decision layer is separately
a candidate for a shared service, but that is no longer *forced* by Nikon.)

### Correction (supersedes the first read)
An earlier assessment — made from the embedded-Python/JOBS **web docs only**, before
`NkMacroLibs_6.20.00.exe` was extracted — concluded that Nikon *inverts* the control model and
that the neutral waist had to become a REST analysis-service because "the driver abstraction won't
generalize." **The actual 6.2 socket library refutes that.** NIS can be driven externally over a
socket with a text command protocol, identical in shape to Leica. The driver abstraction
generalizes; the inversion is optional, not required.

---

## Open questions / TODO

1. **Device-control verb vocabulary** — the real macro command names for stage (`Stg*`/move),
   `Capture`/acquire, Z, and objective selection are **not in this bundle**; they live in the
   NIS-Elements macro command reference. *Pin these down before any driver work.*
2. **State read-back protocol** — `NkSocketServerDemo.mac` is fire-and-forget (`!cmd` returns
   nothing). Design the request/response extension (e.g. `?<query>` → reply line) — this is ours
   to own, same as designing the Leica readers.
3. **6.2 capability check** — confirm whether the JOBS **Python node** (not just macro-level
   `limpy`) and `requests`/`httpx` ship in 6.2, in case we want Route 2 / hybrid.
4. **Security** — `Int_ExecuteCommand` runs arbitrary macro text received over TCP. Bind to
   `127.0.0.1` or a private instrument subnet; never `0.0.0.0`. Consider a command allow-list in
   the resident macro rather than blanket `!`-execution.

## Proposed next step — a round-trip spike
A minimal proof on the bench:
- a forked socket-server `.mac` that adds a **reply** (respond to a `?Get_Calibration`-style query
  with the value), and
- a ~30-line Python client that connects, sends a command, and reads the response.

This proves the exact Leica-symmetric loop end-to-end. It requires the machine with NIS 6.2.
Use placeholder verbs until item (1) above is resolved, or pin the vocabulary first so the spike
uses real `Stg*`/`Capture` commands.

**This spike is now written — see [`spike/`](spike/):** `nis_socket_server_roundtrip.mac` (resident
server, loopback-bound, `!command` + `?query` dispatch with a real `?Get_Calibration` reply) and
`nis_roundtrip_client.py` (+ offline tests for framing/parsing). It uses `?Get_Calibration` /
`?ping` — real getters that work **today**, so the round-trip can be validated before any device
verbs are pinned. Bench run instructions in [`spike/README.md`](spike/README.md).

---

## Reference

### Source files (in the collected bundle / installer)
- Interface macros: `NkSocket.mac`, `NkWindow.mac`, `Win32.mac`, `limpy.mac`, `CreateProcess.mac`,
  `NkComPort.mac`, `NkPath.mac`, `NkPropSheet.mac`.
- Examples: `NkSocketServerDemo.mac`, `NkSocketClientDemo.mac`, `NkWindowDemo.mac`,
  `NkComPortDemo.mac`, plus the legacy `SampleAPI_*.mac` set.
- Libraries: `NkSocket.dll`, `NkWindow.dll`, `NkComPort.dll`, `NkImgSDK.dll`, `NkDatabase.dll`,
  `NkUnmix2.dll`; helper exes `NkListen.exe`, `NkComPortCon.exe`.

### External references
- Python in JOBS (Laboratory-Imaging): <https://github.com/Laboratory-Imaging/JOBS-examples/blob/main/NIS_v7.01/61-Python_in_JOBs/README.md>
- Smart Microscopy Working Group — Nikon: <https://smartmicroscopy.github.io/implementations/industry/nikon.html>
- NIS-Elements Python docs: <https://www.nisoftware.net/NikonSaleApplication/Help/Docs-D/eng_d/p4c14s2.html>

<!-- Investigation date: 2026-06-30. Maintainer: Thom de Hoog (ZMB / University of Zurich). -->
