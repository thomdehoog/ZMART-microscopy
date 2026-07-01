# NIS-Elements API — investigation findings & progress log

> **Date:** 2026-07-01 · **Author:** Thom de Hoog (ZMB, University of Zurich) —
> thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com · **License:** MIT
>
> Companion to [`README.md`](README.md) (living reference) — this file is the dated investigation
> record and progress log. Target instrument: **NIS-Elements 6.2 (6.20)**.

---

## TL;DR

The Nikon macro bundle proves the **transport + dispatch + read-back + analysis** halves of a driver:
NIS can be driven from an external Python process over TCP exactly like Leica's CAM socket — no
architectural inversion. The **one missing piece** is the hardware-verb vocabulary (stage / Z /
capture / objective), which is not in this bundle and must come from the NIS macro command
reference or from Kees. A round-trip spike is written and its client is verified offline; it uses
real read-only getters (`?Get_Calibration`, `?ping`) so the loop can be validated **before** the
device verbs are pinned.

---

## What was examined

- **Bundle:** `C:\Users\t.de\Desktop\Nikon api (1)\` — `Nk*.dll`, interface macros, 48
  `SampleAPI_*.mac`, and the `NkMacroLibs_6.20.00.exe` installer.
- **Installer:** confirmed to be a **plain zip** (`Expand-Archive` extracts it). The socket/serial/
  process libraries the architecture depends on — `NkSocket.dll`+`.mac`, `NkSocketServerDemo/ClientDemo.mac`,
  `NkComPort.*`, `CreateProcess.mac`, `NkListen.exe`, plus `NkString`/`NkListCtrl`/`NkPropSheet`/
  `RichEdit`/`NkPath` — live **inside** the installer, not loose in the folder. The README's
  "decisive find" is accurate.
- **Coverage:** an exhaustive read of every macro (all 48 `SampleAPI_*.mac` + `autorun.mac` +
  `NkWindowDemo.mac`, the interface/library `.mac` files, and the extracted demos).
- **DLLs:** native C/C++ (no `mscoree` reference → not .NET). No `dumpbin`/`objdump`/`strings`/`7z`
  on this machine, so no formal decompilation — **and none needed**: every utility DLL's full
  callable surface is declared in its paired `.mac` file. The three image DLLs (no `.mac`) were
  characterized by a string scan (see below).

---

## Findings — what we CAN and CAN'T do

### ✅ Can do (all evidenced by real code)

- **Drive NIS from an external process over TCP.** `NkSocket.dll` is a full client/server;
  `NkSocketServerDemo.mac:240` runs any socket line prefixed with `!` via `Int_ExecuteCommand(pid, cmd)`.
  Architecturally identical to the Leica CAM route.
- **Run any NIS command or macro by name** — `Int_ExecuteCommand`, `RunMacro`, `Int_ExecProgram`, gated by `ExistProc`.
- **Run Python inside NIS** — `limpy.mac` → `v6_gnr_python.dll` (`Python_RunString`, `Eval*`, `SetAttr/Item*`).
- **Have NIS launch our Python** — `CreateProcess.mac` (`CreateProcessW`) or `ShellExecuteW`.
- **Serial/COM device control** — `NkComPort` (Arduino demo).
- **Build a request/response protocol** — the socket is bidirectional; `NkString.dll` gives regex +
  a key/value StrMap to parse a `?query`→reply inside the macro.
- **Read state (read-only getters):** calibration µm/px per objective (`Get_Calibration`,
  `SampleAPI_07.mac:149`), device presence/status (`Get_Info(INFO_STAGEPRESENT/STAGEINIT/LIGHTPRESENT/
  LIVESTATUS/GRABBING…)`, `GetLightLevels`), image info/pixel type/size (`Get_ImageInfo`), pixel/RGB
  values, histograms, open-document list, paths, version/board strings.
- **Analyze images in-process:** threshold + particle analysis by Feret/circularity/mean-intensity
  (`makpud.mac`), `MeasureObject`/`MeasureField`, histograms, filters (Sobel, Golay, morpho, stretch).

### ❌ Can't do (with this bundle)

- **No device-motion / acquisition verbs anywhere.** Zero stage-move, Z/focus, capture/acquire,
  objective/nosepiece, shutter/filter/illumination/lamp/laser, or camera-select commands. The
  `!Capture();` in the server banner is a **string literal**, never defined. → Pin the verbs from the
  **NIS 6.2 macro command reference** (or Kees). **This is the single blocker** to a working driver.
- **No built-in state read-back** — the stock server is fire-and-forget; the `?query`→reply layer is ours.
- **No security** — `Int_ExecuteCommand` runs arbitrary text off the socket. Bind `127.0.0.1`
  (never `0.0.0.0`) and gate commands with an allow-list.
- **Embedded Python is version-locked** to 6.2 `limpy.*` names (7.x uses `limjob`/`nis.mac`); whether
  the JOBS Python node and `requests`/`httpx` ship in 6.2 is unconfirmed.
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

### Native image-SDK DLLs (string-scan characterization)

| DLL | Character |
|---|---|
| `NkUnmix2.dll` | OpenCV-based spectral unmixing (A1 confocal) |
| `NkImg2xProcess.dll` | OpenCV cell-distribution / segmentation (`NkImgCellDistribution`, mask/center/crop outputs) |
| `NkLAppAutoAlignLib.dll` | auto-align / autofocus (phase / xy / focus-quality / progress) |
| `NkDatabase.dll` | LAPP SDK database module |
| `NkImgSDK.dll` | image-manipulation SDK (26 MB) |

These run inside NIS; they are not a standalone external API.

---

## Architecture verdict

A **text-command-over-socket driver contract** is satisfiable by *both* LAS X CAM and NkSocket, so
the driver abstraction remains the vendor-neutral waist. Nikon becomes a sibling
`zmart_drivers/nikon/{connection, commands, readers}`:

| | Leica (existing) | Nikon (NkSocket route) |
|---|---|---|
| Transport | LAS X CAM socket | `NkSocket` TCP |
| Protocol | text commands | text `!<cmd>;` / `?<query>` lines (`\r`-terminated) |
| Control locus | external Python orchestrator | external Python orchestrator |
| State read-back | log-tailing / CAM reads | macro writes reply lines back over the socket |

Route 2 (embedded Python in JOBS calling out to a REST analysis service) remains a **hybrid partner**
for heavy in-process analysis (CellPose/DINO) — optional, not forced.

---

## Progress — this session (2026-07-01)

- **README:** added a grounded "Capabilities — what we can and can't do" section + command inventory.
- **Spike written** under [`spike/`](spike/):
  - `nis_socket_server_roundtrip.mac` — resident NIS macro, **loopback-bound** fork of
    `NkSocketServerDemo.mac`; `!command` execution + `?query` dispatch (`?ping`, `?Get_Calibration`
    with an open-document guard). Uses the verified LUCIA dialect conventions.
  - `nis_roundtrip_client.py` — external Python client (`NisRoundTripClient` + pure `parse_reply`);
    pipe-delimited replies so a spaced objective name parses cleanly.
  - `test_nis_roundtrip_client.py` — offline tests (parsing + a threaded fake-server socket round-trip).
  - `spike/README.md` — bench-run instructions, protocol spec, security note.

### Validated vs pending

- **Client (offline): 6/6 tests green** — reply parsing (incl. spaced objective), error replies, the
  `\r` terminator contract, and the full connect→send→drain→parse socket path against an emulated server.
  (No `pytest` in the local envs; ran the assert-functions directly with the `smart-microscopy` env's
  Python. The file is standard pytest.)
- **Server macro: NOT yet run on hardware** — written against the proven demo's exact API usage, but
  the LUCIA interpreter isn't available here. First NIS 6.2 bench run is its validation.

---

## Next steps / open blockers

1. **Pin the device-verb vocabulary** (`Stg*`/move, `Capture`/acquire, Z, objective) from the NIS 6.2
   macro command reference or from Kees — the only blocker to a working driver.
2. **Bench-run the spike** (see `spike/README.md`): install `NkMacroLibs_6.20.00.exe`, run the macro,
   click Listen, open an image, run the client → expect `?Get_Calibration` to return real µm/px.
3. **Harden** before non-bench use: replace blanket `!` execution with a command allow-list.
4. **Confirm 6.2 capability** for Route 2/hybrid: JOBS Python node + `requests`/`httpx`.
5. Once verbs are pinned, grow the spike into `zmart_drivers/nikon/{connection, commands, readers}`.
